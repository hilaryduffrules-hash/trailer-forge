#!/usr/bin/env python3
"""
chapters.py — Auto-generate YouTube chapter markers from a video file.

Pipeline:
  1. Extract audio from video with ffmpeg
  2. Detect silence gaps >2s (silencedetect filter)
  3. Transcribe audio with Whisper (base model, word-level timestamps)
  4. Align silence gaps with sentence boundaries
  5. Output YouTube-format chapter markers + save .chapters file

Usage:
  python3 trailer_forge.py chapters <video_file>

Output format (stdout + .chapters file):
  0:00 Intro
  1:23 Topic Name
  ...
"""

import os
import re
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):   print(f"  {msg}", flush=True)
def ok(msg):    print(f"  ✅ {msg}", flush=True)
def warn(msg):  print(f"  ⚠  {msg}", flush=True)
def die(msg):   print(f"  ❌ {msg}", flush=True); sys.exit(1)


def run(cmd: str, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"CMD: {cmd[:120]}", file=sys.stderr)
        print(f"STDERR: {r.stderr[-1500:]}", file=sys.stderr)
        raise RuntimeError(f"Command failed (exit {r.returncode}): {cmd[:80]}")
    return r


# ── Step 1: Extract audio ─────────────────────────────────────────────────────

def extract_audio(video_path: str, audio_path: str) -> None:
    """Extract mono 16kHz audio from video — ideal for Whisper."""
    log(f"Extracting audio from {Path(video_path).name}…")
    run(f'ffmpeg -y -i "{video_path}" -vn -ac 1 -ar 16000 "{audio_path}" -loglevel error')
    ok("Audio extracted")


# ── Step 2: Detect silence gaps ───────────────────────────────────────────────

def detect_silence(video_path: str, min_silence_sec: float = 2.0, noise_db: int = -40) -> List[float]:
    """
    Use ffmpeg silencedetect to find gaps of silence ≥ min_silence_sec.
    Returns list of midpoint timestamps (seconds) for each silence gap.
    """
    log(f"Detecting silence gaps >{min_silence_sec}s…")
    result = run(
        f'ffmpeg -i "{video_path}" '
        f'-af "silencedetect=noise={noise_db}dB:d={min_silence_sec}" '
        f'-f null - 2>&1',
        check=False
    )
    output = result.stdout + result.stderr

    # Parse silence_start and silence_end pairs
    starts = [float(m) for m in re.findall(r'silence_start: ([\d.]+)', output)]
    ends   = [float(m) for m in re.findall(r'silence_end: ([\d.]+)', output)]

    midpoints = []
    for s, e in zip(starts, ends):
        midpoints.append((s + e) / 2.0)

    ok(f"Found {len(midpoints)} silence gap(s)")
    return midpoints


# ── Step 3: Transcribe ────────────────────────────────────────────────────────

def transcribe(audio_path: str) -> dict:
    """
    Transcribe audio with local Whisper (base model).
    Returns the full Whisper JSON result dict with word-level timestamps.
    """
    log("Transcribing with Whisper (base model)…")
    whisper_cmd = (
        f'python3 -c "'
        f'import whisper, json; '
        f'm = whisper.load_model(\'base\'); '
        f'r = m.transcribe(\'{audio_path}\', word_timestamps=True); '
        f'print(json.dumps(r))'
        f'"'
    )
    result = run(whisper_cmd)
    data = json.loads(result.stdout)
    ok("Transcription complete")
    return data


# ── Step 4: Build word list with timestamps ───────────────────────────────────

def extract_words(whisper_data: dict) -> List[dict]:
    """
    Extract word-level entries from Whisper output.
    Returns list of {'word': str, 'start': float, 'end': float}.
    """
    words = []
    for segment in whisper_data.get("segments", []):
        for w in segment.get("words", []):
            words.append({
                "word":  w.get("word", "").strip(),
                "start": w.get("start", segment.get("start", 0)),
                "end":   w.get("end",   segment.get("end",   0)),
            })
    return words


# ── Step 5: Group words into sentences ────────────────────────────────────────

SENTENCE_END = re.compile(r'[.!?]$')

def group_into_sentences(words: List[dict]) -> List[dict]:
    """
    Group consecutive words into sentence-like chunks.
    A sentence ends when a word ends with . ! ?
    Returns list of {'text': str, 'start': float, 'end': float}.
    """
    sentences = []
    current_words = []

    for w in words:
        if not w["word"]:
            continue
        current_words.append(w)
        if SENTENCE_END.search(w["word"]):
            text = " ".join(cw["word"] for cw in current_words).strip()
            sentences.append({
                "text":  text,
                "start": current_words[0]["start"],
                "end":   current_words[-1]["end"],
            })
            current_words = []

    # Flush remaining words as a final sentence
    if current_words:
        text = " ".join(cw["word"] for cw in current_words).strip()
        sentences.append({
            "text":  text,
            "start": current_words[0]["start"],
            "end":   current_words[-1]["end"],
        })

    return sentences


# ── Step 6: Align silence gaps → chapter boundaries ──────────────────────────

def pick_chapter_boundaries(
    silence_midpoints: List[float],
    sentences: List[dict],
    max_label_words: int = 5,
) -> List[Tuple[float, str]]:
    """
    For each silence gap midpoint, find the sentence that ends closest to (and before)
    the midpoint. That sentence's end time becomes the chapter start time.
    The label comes from the first few words of the *next* sentence.

    Returns list of (timestamp_seconds, label) tuples, always starting with (0.0, 'Intro').
    """
    if not sentences:
        return [(0.0, "Intro")]

    boundaries: List[Tuple[float, str]] = [(0.0, "Intro")]
    used_indices: set = set()

    for gap in sorted(silence_midpoints):
        # Find sentence whose end is closest to (and before) the silence midpoint
        best_idx = None
        best_diff = float("inf")

        for i, sent in enumerate(sentences):
            if i in used_indices:
                continue
            if sent["end"] <= gap:
                diff = gap - sent["end"]
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i

        if best_idx is None:
            continue

        # The chapter starts at the end of this sentence (= silence gap boundary)
        chapter_start = sentences[best_idx]["end"]

        # Label = first few words of next sentence
        next_idx = best_idx + 1
        while next_idx in used_indices and next_idx < len(sentences):
            next_idx += 1

        if next_idx < len(sentences):
            raw = sentences[next_idx]["text"]
        else:
            raw = sentences[best_idx]["text"]  # fallback: label from current sentence

        label = _make_label(raw, max_label_words)
        boundaries.append((chapter_start, label))
        used_indices.add(best_idx)

    return sorted(boundaries, key=lambda x: x[0])


def _make_label(text: str, max_words: int) -> str:
    """Title-case first N words, strip trailing punctuation, cap at ~40 chars."""
    words = text.split()[:max_words]
    label = " ".join(w.strip(".,!?;:") for w in words).strip()
    label = label[:40]  # hard cap
    return label.title() if label else "Chapter"


# ── Step 7: Format output ─────────────────────────────────────────────────────

def fmt_timestamp(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS for YouTube chapters."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_chapters(boundaries: List[Tuple[float, str]]) -> str:
    """Format chapter list as YouTube-compatible string."""
    lines = [f"{fmt_timestamp(ts)} {label}" for ts, label in boundaries]
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_chapters(
    video_path: str,
    min_silence_sec: float = 2.0,
    noise_db: int = -40,
    max_label_words: int = 5,
) -> str:
    """
    Full pipeline: video → YouTube chapter markers.
    Prints to stdout and saves alongside video as <video>.chapters
    Returns the formatted chapters string.
    """
    video = Path(video_path).resolve()
    if not video.exists():
        die(f"Video not found: {video}")

    print(f"\n🎬 Generating chapters for: {video.name}\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = str(Path(tmpdir) / "audio.wav")

        # 1. Extract audio
        extract_audio(str(video), audio_path)

        # 2. Detect silence
        silence_midpoints = detect_silence(str(video), min_silence_sec, noise_db)

        # 3. Transcribe
        whisper_data = transcribe(audio_path)

    # 4. Extract word timestamps
    words = extract_words(whisper_data)
    if not words:
        warn("No word-level timestamps found — trying segment-level fallback")
        # Fall back to segments as pseudo-words
        for seg in whisper_data.get("segments", []):
            words.append({
                "word":  seg.get("text", "").strip(),
                "start": seg.get("start", 0),
                "end":   seg.get("end", 0),
            })

    # 5. Group into sentences
    sentences = group_into_sentences(words)
    log(f"Grouped into {len(sentences)} sentences")

    # 6. Align to silence boundaries
    boundaries = pick_chapter_boundaries(silence_midpoints, sentences, max_label_words)

    # 7. Format and output
    output = format_chapters(boundaries)
    chapters_path = video.with_suffix(video.suffix + ".chapters")

    print(f"\n{'─' * 50}")
    print(output)
    print(f"{'─' * 50}\n")

    chapters_path.write_text(output + "\n")
    ok(f"Saved → {chapters_path}")

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 chapters.py <video_file>")
        sys.exit(1)
    run_chapters(sys.argv[1])
