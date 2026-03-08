#!/usr/bin/env python3
"""
clipper.py — YouTube → social-ready short clips

Pipeline:
  1. Download audio (mp3) + video via yt-dlp
  2. Transcribe audio with Whisper (local, base model)
  3. Score sliding 45-second windows → pick top N clips
  4. Generate YAML manifests for each clip
  5. Assemble each clip with ffmpeg (vertical 9:16 or horizontal 16:9)

Output: out/clips/clip_01.mp4, out/clips/clip_01.yaml, ...
"""

import os
import re
import sys
import json
import subprocess
import shutil
from pathlib import Path
from typing import List, Tuple

# ── Defaults ──────────────────────────────────────────────────────────────────
WINDOW_SEC   = 45        # sliding window length (seconds)
MIN_CLIP_SEC = 20        # minimum clip length to consider
MAX_CLIP_SEC = 60        # hard cap for social platforms
STEP_SEC     = 5         # sliding step
AUDIO_TMP    = "/tmp/clip_audio.mp3"
VIDEO_TMP    = "/tmp/clip_source.mp4"
TRANSCRIPT_TMP = "/tmp/clip_transcript.json"


def log(msg):  print(f"  {msg}",     flush=True)
def ok(msg):   print(f"  ✅ {msg}",   flush=True)
def warn(msg): print(f"  ⚠  {msg}",  flush=True)
def die(msg):  print(f"  ❌ {msg}",   flush=True); sys.exit(1)


def run(cmd: str, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"CMD: {cmd[:120]}", file=sys.stderr)
        print(f"STDERR: {r.stderr[-1500:]}", file=sys.stderr)
        raise RuntimeError(f"Command failed (exit {r.returncode}): {cmd[:80]}")
    return r


# ── Step 1: Download ──────────────────────────────────────────────────────────

def download(url: str) -> Tuple[str, str]:
    """
    Download audio (mp3) and best video (<=1080p) from a YouTube URL.
    Returns (audio_path, video_path).
    """
    log("Downloading audio track…")
    run(f'yt-dlp -x --audio-format mp3 -o "/tmp/clip_audio.%(ext)s" "{url}"')

    # yt-dlp may produce .mp3 directly or .mp3 after conversion
    audio_path = AUDIO_TMP
    if not Path(audio_path).exists():
        # fallback: find any mp3 in /tmp matching clip_audio
        candidates = list(Path("/tmp").glob("clip_audio.*"))
        if candidates:
            audio_path = str(candidates[0])
        else:
            die("Audio download failed — no clip_audio.* found in /tmp")

    log("Downloading video…")
    run(f'yt-dlp -f "best[height<=1080]" -o "/tmp/clip_source.%(ext)s" "{url}"')

    video_path = VIDEO_TMP
    if not Path(video_path).exists():
        # yt-dlp may use mkv/webm if no mp4 available
        candidates = sorted(Path("/tmp").glob("clip_source.*"),
                            key=lambda p: p.stat().st_size, reverse=True)
        if candidates:
            video_path = str(candidates[0])
        else:
            die("Video download failed — no clip_source.* found in /tmp")

    ok(f"Audio: {audio_path}")
    ok(f"Video: {video_path}")
    return audio_path, video_path


# ── Step 2: Transcribe ────────────────────────────────────────────────────────

def transcribe(audio_path: str) -> dict:
    """
    Transcribe audio with local Whisper (base model).
    Returns the full Whisper JSON result dict.
    """
    transcript_path = TRANSCRIPT_TMP

    if Path(transcript_path).exists():
        existing_age = os.path.getmtime(transcript_path)
        audio_age    = os.path.getmtime(audio_path)
        if existing_age > audio_age:
            log("Using cached transcript.")
            with open(transcript_path) as f:
                return json.load(f)

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
    data   = json.loads(result.stdout)

    with open(transcript_path, "w") as f:
        json.dump(data, f, indent=2)

    ok(f"Transcript saved → {transcript_path}")
    return data


# ── Step 3: Detect best clip windows ─────────────────────────────────────────

# Power words that trigger emotional engagement / virality signals
_POWER_WORDS = re.compile(
    r'\b(never|always|every|most|only|secret|real reason|actually|truth|wrong|'
    r'mistake|fail|impossible|revolutionary|critical|dangerous|shocking|proven|'
    r'biggest|fastest|best|worst|hidden|exposing|finally|stop|warning)\b',
    re.IGNORECASE
)

# Authority signals: numbers, percentages, proper-noun-like capitalized words
_AUTHORITY = re.compile(r'\b\d[\d,.%$BMK]+|\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b')

# Filler starts that kill hooks
_FILLER_START = re.compile(r'^(so|um|uh|and|but|like|you know|basically|anyway|right|okay|well)\b',
                            re.IGNORECASE)

# Hook-positive openers
_HOOK_OPENERS = re.compile(
    r"^(what if|here'?s|the real|nobody|most people|the problem|the truth|"
    r"what nobody|did you know|the secret|this is why|the reason|stop|never|"
    r"imagine|the biggest|every|the only)",
    re.IGNORECASE
)


def _extract_sentences(segments: list) -> List[dict]:
    """
    Build a list of sentences from Whisper word timestamps.
    Each sentence: {text, start, end}
    Splits on sentence-ending punctuation using word-level timestamps.
    """
    sentences = []
    current_words = []

    all_words = []
    for seg in segments:
        for w in seg.get("words", []):
            all_words.append({
                "word":  w.get("word", "").strip(),
                "start": w.get("start", seg.get("start", 0)),
                "end":   w.get("end",   seg.get("end",   0)),
            })
        # Fallback: if no word timestamps, treat whole segment as one sentence
        if not seg.get("words"):
            sentences.append({
                "text":  seg.get("text", "").strip(),
                "start": seg.get("start", 0),
                "end":   seg.get("end",   0),
            })

    for w in all_words:
        if not w["word"]:
            continue
        current_words.append(w)
        if re.search(r'[.!?]$', w["word"]):
            if current_words:
                sentences.append({
                    "text":  " ".join(cw["word"] for cw in current_words).strip(),
                    "start": current_words[0]["start"],
                    "end":   current_words[-1]["end"],
                })
                current_words = []

    if current_words:
        sentences.append({
            "text":  " ".join(cw["word"] for cw in current_words).strip(),
            "start": current_words[0]["start"],
            "end":   current_words[-1]["end"],
        })

    return sentences


def _score_window_heuristic(text: str, first_sentence: str) -> float:
    """
    Curation-style scoring (no LLM) based on Opus Clip methodology:
      Hook strength (40%) + Narrative arc signals (30%) +
      Authority + power words (15%) + Topic coherence (15%)
    Returns 0–100.
    """
    # ── Hook strength (0–40) ─────────────────────────────────────────────────
    hook = 0
    if _HOOK_OPENERS.search(first_sentence):
        hook += 20
    if '?' in first_sentence:
        hook += 15
    if _AUTHORITY.search(first_sentence):
        hook += 10
    if _FILLER_START.search(first_sentence):
        hook -= 25   # hard penalty
    hook = max(0, min(40, hook))

    # ── Narrative arc signals (0–30) ─────────────────────────────────────────
    n_sentences = len(re.findall(r'[.!?]', text))
    has_setup   = bool(re.search(r'\b(problem|issue|challenge|question|why|what|how)\b', text, re.I))
    has_payoff  = bool(re.search(r'\b(so|therefore|that\'?s why|which means|this means|result|answer|solution|key)\b', text, re.I))
    arc = min(30, n_sentences * 4 + (10 if has_setup else 0) + (10 if has_payoff else 0))

    # ── Authority + power words (0–15) ────────────────────────────────────────
    n_auth   = len(_AUTHORITY.findall(text))
    n_power  = len(_POWER_WORDS.findall(text))
    authority = min(15, n_auth * 3 + n_power * 2)

    # ── Topic coherence proxy (0–15): penalty for drifting ───────────────────
    # Simple proxy: unique "topic words" (nouns > 4 chars) per sentence count
    nouns   = re.findall(r'\b[a-z]{5,}\b', text.lower())
    unique  = len(set(nouns))
    total   = len(nouns) + 1
    ratio   = unique / total   # low ratio = repetitive = focused
    coherence = int(15 * (1 - min(ratio, 0.8) / 0.8))

    return hook + arc + authority + coherence


def _llm_score_window(text: str, first_sentence: str) -> float:
    """
    Use Gemini Flash (free) to score a clip window.
    Returns curation score 0–100 or falls back to heuristic on error.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return _score_window_heuristic(text, first_sentence)

    prompt = f"""You are scoring a transcript window for viral short-form video potential (TikTok/Reels/Shorts).

Score this window 0-100 based on:
- Hook strength (40pts): Does the FIRST SENTENCE grab attention instantly? Bold claim, question, counter-intuitive statement = high score. Filler words ("so", "um", "and") or mid-thought start = deduct heavily.
- Narrative arc (30pts): Does this tell a complete mini-story? Setup + development + payoff = high. All explanation with no hook or punchline = low.
- Authority signals (15pts): Specific numbers, real names, expert vocabulary used naturally.
- Topic coherence (15pts): Is this focused on ONE clear idea, or drifting?

Transcript window:
---
First sentence: {first_sentence[:200]}

Full text: {text[:600]}
---

Reply with ONLY a JSON object: {{"score": <number 0-100>, "hook": "<one phrase describing the hook>", "issue": "<main weakness if any>"}}"""

    try:
        import urllib.request
        payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                              "generationConfig": {"temperature": 0.1, "maxOutputTokens": 80}})
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_key}",
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Strip markdown code fences if present
        raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
        result = json.loads(raw)
        return float(result.get("score", 50))
    except Exception:
        return _score_window_heuristic(text, first_sentence)


def _build_sentence_windows(sentences: list, min_sec: float, max_sec: float) -> List[dict]:
    """
    Build clip candidates that START and END on sentence boundaries.
    This ensures no clip begins mid-thought.
    Returns list of {start, end, text, first_sentence}.
    """
    windows = []
    n = len(sentences)

    for i, sent in enumerate(sentences):
        t_start = sent["start"]
        text_parts = [sent["text"]]

        for j in range(i + 1, n):
            t_end    = sentences[j]["end"]
            duration = t_end - t_start

            if duration < min_sec:
                text_parts.append(sentences[j]["text"])
                continue

            text_parts.append(sentences[j]["text"])
            full_text = " ".join(text_parts)

            windows.append({
                "start":          t_start,
                "end":            t_end,
                "text":           full_text,
                "first_sentence": sent["text"],
                "duration":       duration,
            })

            if duration >= max_sec:
                break

    return windows


def detect_clips(transcript: dict, top_n: int = 3,
                 window: float = WINDOW_SEC) -> List[dict]:
    """
    Build sentence-boundary windows, score each with heuristic+LLM curation
    scoring (Opus Clip methodology), return top_n non-overlapping clips.
    """
    segments  = transcript.get("segments", [])
    if not segments:
        die("Transcript has no segments — cannot detect clips")

    total_dur = max(seg.get("end", 0.0) for seg in segments)

    # Build sentence list from word timestamps
    sentences = _extract_sentences(segments)
    if not sentences:
        die("No sentences extracted from transcript")

    log(f"Video duration: {total_dur:.1f}s  |  {len(sentences)} sentences  |  target: {window}s clips")

    # Build candidate windows that start+end on sentence boundaries
    candidates = _build_sentence_windows(sentences, MIN_CLIP_SEC, MAX_CLIP_SEC)
    if not candidates:
        die("No sentence-bounded windows found — transcript may be too short or have no punctuation")

    log(f"Scoring {len(candidates)} sentence-bounded candidates…")
    use_llm = bool(os.environ.get("GEMINI_API_KEY", ""))
    if use_llm:
        log("LLM scoring via Gemini Flash (Opus Clip-style curation score)…")
    else:
        log("Heuristic scoring (set GEMINI_API_KEY to enable LLM curation)")

    scored = []
    for c in candidates:
        if use_llm:
            score = _llm_score_window(c["text"], c["first_sentence"])
        else:
            score = _score_window_heuristic(c["text"], c["first_sentence"])
        scored.append({**c, "score": score})

    if not scored:
        die("No scoreable windows found in transcript")

    # Sort by score descending, pick top_n non-overlapping windows
    scored.sort(key=lambda x: x["score"], reverse=True)

    selected = []
    for candidate in scored:
        if len(selected) >= top_n:
            break
        overlap = False
        for sel in selected:
            latest_start = max(candidate["start"], sel["start"])
            earliest_end = min(candidate["end"],   sel["end"])
            if earliest_end - latest_start > 5.0:
                overlap = True
                break
        if not overlap:
            candidate["duration"] = round(candidate["end"] - candidate["start"], 2)
            selected.append(candidate)

    selected.sort(key=lambda x: x["start"])

    for i, clip in enumerate(selected):
        hook_preview = clip.get("first_sentence", clip["text"])[:70].strip()
        log(f"Clip {i+1}: {clip['start']:.1f}s → {clip['end']:.1f}s "
            f"(score={clip['score']:.0f}, {clip['duration']:.0f}s)")
        log(f"  Hook: \"{hook_preview}\"")

    return selected


# ── Step 4: Generate YAML manifests ──────────────────────────────────────────

def generate_manifest(clip: dict, index: int, video_path: str,
                      fmt: str, out_dir: Path) -> Path:
    """
    Write a trailer-forge YAML manifest for a single clip.
    Returns the path to the written manifest.
    """
    if fmt in ("vertical", "vertical_blur"):
        resolution = [1080, 1920]
        crop_note  = "9:16 vertical (pillarbox, dark bg)" if fmt == "vertical" else "9:16 vertical (blurred bg)"
    else:
        resolution = [1920, 1080]
        crop_note  = "16:9 horizontal"

    preview_text = clip["text"][:80].strip().replace('"', "'")

    manifest = {
        "output":       f"out/clips/clip_{index:02d}.mp4",
        "resolution":   resolution,
        "fps":          30,
        "film_grain":   False,
        "color_grade":  "teal_orange",
        # Uncomment audio block to add music bed:
        # "audio": {"music": "assets/music.mp3", "music_vol": 0.25, "sfx": "auto"},
        "clipper_meta": {
            "source":   video_path,
            "start":    round(clip["start"], 3),
            "end":      round(clip["end"],   3),
            "duration": clip["duration"],
            "format":   fmt,
            "crop":     crop_note,
            "preview":  preview_text,
        },
        "timeline": [
            # Optional: add a title card hook before the clip
            # {"type": "title_card", "duration": 1.5,
            #  "lines": [{"text": "CLIP TITLE", "font": "bebas", "size": 80}]},
            {
                "type":      "veo_clip",
                "file":      video_path,
                "trim":      [round(clip["start"], 3), round(clip["end"], 3)],
                "fade_in":   0.4,
                "fade_out":  0.4,
            }
            # Optional: add lower third for speaker name:
            # {"type": "lower_third", "name": "SPEAKER NAME", "role": "Title"}
        ],
    }

    # Write YAML manually (avoid pyyaml import requirement in this module)
    try:
        import yaml as _yaml
        yaml_str = _yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
    except ImportError:
        # Fallback: hand-craft minimal YAML
        t = manifest["timeline"][0]
        yaml_str = (
            f"output: {manifest['output']}\n"
            f"resolution: {resolution}\n"
            f"fps: 30\n"
            f"film_grain: false\n"
            f"color_grade: teal_orange\n\n"
            f"clipper_meta:\n"
            f"  source: {video_path}\n"
            f"  start: {clip['start']:.3f}\n"
            f"  end: {clip['end']:.3f}\n"
            f"  duration: {clip['duration']}\n"
            f"  format: {fmt}\n"
            f"  crop: \"{crop_note}\"\n"
            f"  preview: \"{preview_text}\"\n\n"
            f"timeline:\n"
            f"  - type: veo_clip\n"
            f"    file: {video_path}\n"
            f"    trim: [{clip['start']:.3f}, {clip['end']:.3f}]\n"
            f"    fade_in: 0.4\n"
            f"    fade_out: 0.4\n"
        )

    manifest_path = out_dir / f"clip_{index:02d}.yaml"
    manifest_path.write_text(yaml_str)
    log(f"Manifest → {manifest_path}")
    return manifest_path


# ── Step 5: Assemble clips with ffmpeg ────────────────────────────────────────

def assemble_clip(clip: dict, index: int, video_path: str,
                  fmt: str, out_dir: Path) -> Path:
    """
    Trim, crop/scale, and encode a single clip to out/clips/clip_NN.mp4.
    Returns the output path.
    """
    out_path = out_dir / f"clip_{index:02d}.mp4"
    t_start  = clip["start"]
    duration = clip["duration"]

    if fmt == "vertical":
        # 9:16 vertical — pillarbox: full frame preserved, dark near-black bg
        # Better than centre crop — keeps whole subject/frame visible
        W, H = 1080, 1920
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=#1a1a1a,"
            f"fade=t=in:st=0:d=0.4,"
            f"fade=t=out:st={max(0, duration-0.4):.3f}:d=0.4"
        )
        cmd = (
            f'ffmpeg -y '
            f'-ss {t_start:.3f} '
            f'-i "{video_path}" '
            f'-t {duration:.3f} '
            f'-vf "{vf}" '
            f'-c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p '
            f'-c:a aac -b:a 128k '
            f'-movflags +faststart '
            f'"{out_path}"'
        )

    elif fmt == "vertical_blur":
        # 9:16 vertical — blurred background: source frame blurred+stretched as bg,
        # original at full width centred on top. Popular "podcast/talking head" look.
        W, H = 1080, 1920
        fc = (
            f"[0:v]trim=start={t_start:.3f}:duration={duration:.3f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},boxblur=20:5,"
            f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0,duration-0.4):.3f}:d=0.4[bg];"
            f"[0:v]trim=start={t_start:.3f}:duration={duration:.3f},setpts=PTS-STARTPTS,"
            f"scale={W}:-2:force_original_aspect_ratio=decrease,"
            f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0,duration-0.4):.3f}:d=0.4[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
        cmd = (
            f'ffmpeg -y '
            f'-i "{video_path}" '
            f'-filter_complex "{fc}" '
            f'-map "[v]" -map "0:a" '
            f'-t {duration:.3f} '
            f'-c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p '
            f'-c:a aac -b:a 128k '
            f'-movflags +faststart '
            f'"{out_path}"'
        )

    else:
        # 16:9 horizontal — standard scale with letterbox
        W, H = 1920, 1080
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
            f"fade=t=in:st=0:d=0.4,"
            f"fade=t=out:st={max(0, duration-0.4):.3f}:d=0.4"
        )
        cmd = (
            f'ffmpeg -y '
            f'-ss {t_start:.3f} '
            f'-i "{video_path}" '
            f'-t {duration:.3f} '
            f'-vf "{vf}" '
            f'-c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p '
            f'-c:a aac -b:a 128k '
            f'-movflags +faststart '
            f'"{out_path}"'
        )

    log(f"Assembling clip_{index:02d} ({fmt}, {duration:.0f}s)…")
    run(cmd)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    ok(f"clip_{index:02d}.mp4 → {out_path} ({size_mb:.1f}MB)")
    return out_path


# ── Main pipeline entry point ─────────────────────────────────────────────────

def run_clipper(url: str, top_n: int = 3, fmt: str = "vertical_blur",
                out_dir: Path = None) -> List[Path]:
    """
    Full Clipper pipeline: download → transcribe → detect → manifest → assemble.
    Returns list of assembled clip paths.
    """
    if out_dir is None:
        out_dir = Path("out/clips")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n✂️  CLIPPER PIPELINE")
    print(f"   URL:    {url}")
    print(f"   Top:    {top_n} clips")
    _fmt_label = {"vertical": "9:16 pillarbox", "vertical_blur": "9:16 blur bg", "horizontal": "16:9"}.get(fmt, fmt)
    print(f"   Format: {fmt} ({_fmt_label})")
    print(f"   Out:    {out_dir}/\n")

    # 1. Download
    audio_path, video_path = download(url)

    # 2. Transcribe
    transcript = transcribe(audio_path)

    # 3. Detect clip windows
    print()
    log(f"Detecting top {top_n} clip windows…")
    clips = detect_clips(transcript, top_n=top_n)

    # 4 + 5. Manifest + assemble each clip
    print()
    assembled = []
    for i, clip in enumerate(clips, start=1):
        generate_manifest(clip, i, video_path, fmt, out_dir)
        out_path = assemble_clip(clip, i, video_path, fmt, out_dir)
        assembled.append(out_path)

    print(f"\n✅ Clipper complete — {len(assembled)} clip(s) in {out_dir}/")
    for p in assembled:
        print(f"   {p}")
    print()

    return assembled


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Clipper — YouTube to social clips")
    ap.add_argument("url",              help="YouTube URL")
    ap.add_argument("--top",    type=int, default=3,          help="Number of clips (default: 3)")
    ap.add_argument("--format", choices=["vertical","vertical_blur","horizontal"], default="vertical_blur",
                    help="Output format: vertical_blur (blurred bg, default), vertical (pillarbox dark bg), horizontal")
    ap.add_argument("--out",    default="out/clips",          help="Output directory")
    args = ap.parse_args()
    run_clipper(args.url, top_n=args.top, fmt=args.format, out_dir=Path(args.out))
