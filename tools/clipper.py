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

def _sentence_boundaries(text: str) -> int:
    """Count sentence-ending punctuation — proxy for complete thoughts."""
    return len(re.findall(r'[.!?]', text))


def _score_window(segments: list, t_start: float, t_end: float) -> Tuple[float, str]:
    """
    Score a time window [t_start, t_end] by:
      - word count (density)
      - sentence boundary count (completeness — complete thoughts score higher)
      - question marks (engagement — questions pull audiences in)
      - window starts on a sentence boundary (bonus — clean in-point)
    Returns (score, combined_text).
    """
    words = []
    text_parts = []
    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end   = seg.get("end",   0.0)
        if seg_end < t_start or seg_start > t_end:
            continue
        text_parts.append(seg.get("text", "").strip())
        for w in seg.get("words", []):
            ws = w.get("start", seg_start)
            if t_start <= ws <= t_end:
                words.append(w.get("word", ""))

    text    = " ".join(text_parts)
    n_words = len(words) if words else len(text.split())
    n_sent  = _sentence_boundaries(text)
    n_quest = len(re.findall(r'\?', text))

    # Bonus if the window starts within 2s of a sentence boundary
    # (ensures clips open on a clean thought, not mid-sentence)
    clean_start_bonus = 0
    for seg in segments:
        seg_text  = seg.get("text", "")
        seg_start = seg.get("start", 0.0)
        if abs(seg_start - t_start) < 2.0 and re.search(r'[.!?]\s*$', seg_text.strip()):
            clean_start_bonus = 15
            break

    score = (n_words * 1.0
             + n_sent  * 8.0
             + n_quest * 12.0   # questions are engaging
             + clean_start_bonus)
    return score, text


def detect_clips(transcript: dict, top_n: int = 3,
                 window: float = WINDOW_SEC) -> List[dict]:
    """
    Slide a window over the transcript and return the top_n non-overlapping
    clip windows, each as:
      { start, end, score, text, duration }
    """
    segments  = transcript.get("segments", [])
    if not segments:
        die("Transcript has no segments — cannot detect clips")

    total_dur = max(seg.get("end", 0.0) for seg in segments)
    log(f"Video duration: {total_dur:.1f}s  |  Window: {window}s  |  Step: {STEP_SEC}s")

    # Clamp window to something sensible
    win = min(window, MAX_CLIP_SEC)
    win = max(win,    MIN_CLIP_SEC)

    # Score every window position
    scored = []
    t = 0.0
    while t + win <= total_dur + STEP_SEC:
        t_end  = min(t + win, total_dur)
        t_end  = min(t_end, t + MAX_CLIP_SEC)
        if (t_end - t) < MIN_CLIP_SEC:
            t += STEP_SEC
            continue
        score, text = _score_window(segments, t, t_end)
        scored.append({"start": t, "end": t_end, "score": score, "text": text})
        t += STEP_SEC

    if not scored:
        die("No scoreable windows found in transcript")

    # Sort by score descending, then pick top_n non-overlapping windows
    scored.sort(key=lambda x: x["score"], reverse=True)

    selected = []
    for candidate in scored:
        if len(selected) >= top_n:
            break
        # Check overlap with already-selected clips
        overlap = False
        for sel in selected:
            latest_start = max(candidate["start"], sel["start"])
            earliest_end = min(candidate["end"],   sel["end"])
            if earliest_end - latest_start > 5.0:   # >5s overlap = skip
                overlap = True
                break
        if not overlap:
            candidate["duration"] = round(candidate["end"] - candidate["start"], 2)
            selected.append(candidate)

    # Sort selected by start time for natural ordering
    selected.sort(key=lambda x: x["start"])

    for i, clip in enumerate(selected):
        log(f"Clip {i+1}: {clip['start']:.1f}s → {clip['end']:.1f}s "
            f"(score={clip['score']:.0f}, {clip['duration']:.0f}s) "
            f"— \"{clip['text'][:60].strip()}…\"")

    return selected


# ── Step 4: Generate YAML manifests ──────────────────────────────────────────

def generate_manifest(clip: dict, index: int, video_path: str,
                      fmt: str, out_dir: Path) -> Path:
    """
    Write a trailer-forge YAML manifest for a single clip.
    Returns the path to the written manifest.
    """
    if fmt == "vertical":
        resolution = [1080, 1920]
        crop_note  = "9:16 vertical (center crop)"
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
        # 9:16 vertical — center crop from source
        # Scale to fit height first, then crop to 9:16 width
        W, H = 1080, 1920
        # crop_w = H * 9 / 16 = 1080, so: scale to iw*H/ih then crop
        vf = (
            f"scale=-2:{H},"                          # scale to target height, keep AR
            f"crop={W}:{H}:(iw-{W})/2:(ih-{H})/2,"  # center crop to 9:16
            f"fade=t=in:st=0:d=0.4,"
            f"fade=t=out:st={max(0, duration-0.4):.3f}:d=0.4"
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

def run_clipper(url: str, top_n: int = 3, fmt: str = "vertical",
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
    print(f"   Format: {fmt} ({'9:16' if fmt == 'vertical' else '16:9'})")
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
    ap.add_argument("--format", choices=["vertical","horizontal"], default="vertical",
                    help="Output format (default: vertical 9:16)")
    ap.add_argument("--out",    default="out/clips",          help="Output directory")
    args = ap.parse_args()
    run_clipper(args.url, top_n=args.top, fmt=args.format, out_dir=Path(args.out))
