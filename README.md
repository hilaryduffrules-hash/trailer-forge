<div align="center">

# 🎬 trailer-forge

**Build cinematic video trailers from a YAML manifest.**  
Localhost. No subscription. No cloud. Just you, ffmpeg, and a little drama.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![ffmpeg required](https://img.shields.io/badge/requires-ffmpeg-orange.svg)](https://ffmpeg.org)

</div>

---

trailer-forge is a local video assembly tool for agents, filmmakers, and anyone who wants
to produce cinematic title cards, AI-generated clips, and dramatic voiceovers — all driven
by a simple YAML file.

```
script → voiceover → AI clips → YAML manifest → trailer-forge → 🎬
```

## Features

- **YAML-driven** — define your entire trailer as a timeline, no code required
- **Cinema-quality title cards** — Bebas Neue type, gold rules, vignette, glow effects
- **Node.js canvas renderer** — browser-quality text rendering (falls back to Pillow)
- **Color grades** — dark thriller, teal-orange, vintage, or none
- **Film grain** — subtle temporal noise pass for that cinematic texture
- **Whisper sync** — word-level timestamp extraction for frame-perfect audio sync
- **Veo 2 integration** — auto-generate missing clips (optional, requires API key)
- **Fully local** — runs on your machine, no data leaves unless you ask it to

## Quick Start

### 1. Install dependencies

```bash
# Python deps
pip install pillow pyyaml requests

# Node.js canvas renderer (better text quality)
cd canvas_renderer && npm install && cd ..

# ffmpeg — required
# Ubuntu/Debian: sudo apt install ffmpeg
# macOS:         brew install ffmpeg
# Windows:       https://ffmpeg.org/download.html
```

### 2. Add your fonts

Bebas Neue is bundled in `fonts/`. For system-wide install:

```bash
# Linux
sudo cp fonts/BebasNeue.ttf /usr/local/share/fonts/
sudo fc-cache -fv
```

### 3. Build a trailer

```bash
# Preview your timeline (no rendering)
python3 trailer_forge.py preview examples/simple.yaml

# Assemble from existing clips
python3 trailer_forge.py assemble examples/simple.yaml

# Assemble + auto-generate any missing clips via Veo 2
GEMINI_API_KEY=your_key python3 trailer_forge.py build examples/simple.yaml
```

## YAML Manifest

```yaml
output: out/my_trailer.mp4
resolution: [1920, 1080]
fps: 30
film_grain: true
color_grade: dark_thriller

audio:
  music: assets/music.mp3
  voiceover: assets/voiceover.mp3
  music_vol: 0.28
  voice_vol: 1.0
  voice_delay: 0.0

timeline:

  - type: title_card
    lines:
      - {text: "IN A WORLD", font: bebas, size: 200, color: white}
      - {text: "where things go sideways", font: sans, size: 56, color: gold}
    duration: 3.0
    fade_in: 0.70
    fade_out: 0.30

  - type: veo_clip
    file: clips/opening.mp4
    trim: [0, 4.0]
    fade_in: 0.40
    fade_out: 0.35
    prompt: "cinematic wide shot, moody lighting, film grain"  # auto-generate if missing

  - type: black
    duration: 0.5

  - type: main_title
    title: "SOMETHING"        # "T H E" is added automatically above
    tagline: "A story about stuff."
    duration: 5.0
    fade_in: 0.90
```

See [`docs/YAML_REFERENCE.md`](docs/YAML_REFERENCE.md) for the full spec.

## Perfect Sync with Whisper

Getting title cards to cut in **exactly when the narrator says the word** separates a real
trailer from a slideshow with music. The method: every segment's duration is calculated so the
**cumulative sum of all preceding segments equals the Whisper timestamp** for the target word.

```bash
# 1. Transcribe your voiceover with word-level timestamps
whisper assets/voiceover.mp3 --model small --word_timestamps True \
  --output_format json --output_dir whisper_out

# 2. See all word timestamps
python3 tools/sync_yaml.py whisper_out/voiceover.json

# 3. Compute segment durations for your sync cues + get YAML stubs
python3 tools/sync_yaml.py whisper_out/voiceover.json \
    --offset 0.2 \
    --cues \
        "wonders:WONDERS CARD:SOME BUILD WONDERS." \
        "trebuchet:TREBUCHET:SOME GET TREBUCHET'D" \
        "night:ONE NIGHT:ONE NIGHT. ONE LAN PARTY." \
        "legendary:LEGENDARY:ONE LEGENDARY GAME." \
    --yaml
```

Output shows exact durations for each preceding segment and YAML stubs ready to paste:

```
   START     DUR    ENDS    SYNC              SEGMENT
------------------------------------------------------------------------
   0.200s  3.100s  3.300s  ← 'wonders'       EVERY CIVILIZATION card
   3.300s  0.800s  4.100s  ← 'wonders' ✓     veo_01 flash
   4.100s  1.300s  5.400s  ← 'trebuchet' ✓   SOME BUILD WONDERS.
   5.400s  1.940s  7.340s  ← 'best' ✓        SOME GET TREBUCHET'D
```

**Key rule:** every `black` segment counts toward the cumulative sum.  
Verify your full timeline before assembling — see [`docs/SYNC_GUIDE.md`](docs/SYNC_GUIDE.md).

### Segment design patterns

| Pattern | When to use | How |
|---------|-------------|-----|
| **Card-on-word** | Text card appears on spoken word | Preceding durations sum to word timestamp |
| **Video + spoken VO** | Action footage with narration over it | Clip duration = length of that VO section |
| **Percussive single-word** | ONE. / MORE. / GAME. beats | Duration = gap between consecutive spoken words |
| **Impact flash cut** | Visual punctuation between cards | `trim: [0, 0.5]`, `fade_in: 0.08, fade_out: 0.08` |
| **Title reveal beat** | Main title with dramatic weight | Spoken word → 0.5s black → title card |

See [`examples/the_gathering_v2.yaml`](examples/the_gathering_v2.yaml) for a complete
8-sync-point example with all patterns applied.

## Recommended Voiceover

ElevenLabs **"David — Epic Movie Trailer"** (voice ID: `FF7KdobWPaiR0vkcALHF`)  
Settings: `stability=0.45`, `similarity_boost=0.90`, `style=0.85`, `speaker_boost=True`

## Clipper — YouTube to Social Clips

Clipper is a one-command pipeline that takes any YouTube URL and produces
short-form, social-ready clips (vertical 9:16 for Nostr/Reels/TikTok, max 60s each).

```
YouTube URL → yt-dlp download → Whisper transcription → clip detection → ffmpeg assembly → out/clips/
```

### Quick start

```bash
# Extract top 3 vertical clips (default)
python3 trailer_forge.py clip "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Extract top 5 horizontal clips
python3 trailer_forge.py clip "https://youtu.be/dQw4w9WgXcQ" --top 5 --format horizontal

# Vertical blur with zoom (talking-head video)
python3 trailer_forge.py clip "https://youtu.be/..." --format vertical_blur --zoom 1.5

# Custom output directory
python3 trailer_forge.py clip "https://youtu.be/..." --top 3 --out /tmp/my_clips
```

### How clip detection works

Clipper builds sentence-boundary windows and scores each using curation-style analysis
(inspired by Opus Clip methodology):
- **Hook strength (40%)** — does the first sentence grab attention? Penalizes filler starts and context-dependent openers
- **Narrative arc (30%)** — does the window tell a complete mini-story with setup + payoff?
- **Authority signals (15%)** — specific numbers, proper nouns, expert vocabulary
- **Topic coherence (15%)** — is the window focused on one clear idea?

When `GEMINI_API_KEY` is set, scoring is enhanced with Gemini Flash LLM curation.
The top N non-overlapping windows are selected and assembled on clean sentence boundaries.

### Output

Each clip produces two files:
```
out/clips/
  clip_01.mp4   ← assembled clip (vertical 9:16 or horizontal 16:9)
  clip_01.yaml  ← trailer-forge manifest (for further editing/remixing)
  clip_02.mp4
  clip_02.yaml
  ...
```

The YAML manifests are fully compatible with `trailer_forge.py assemble` — you can
open one, add title cards or color grades, and re-assemble.

### Requirements

| Tool | Purpose | Install |
|------|---------|---------|
| `yt-dlp` | YouTube download | `pip install yt-dlp` |
| `whisper` | Local transcription | `pip install openai-whisper` |
| `ffmpeg` | Video assembly | `sudo apt install ffmpeg` |

### Options

```
python3 trailer_forge.py clip <youtube_url> [options]

  --top N           Number of clips to extract (default: 3)
  --format FORMAT   vertical_blur (blurred bg, default) | vertical (pillarbox dark bg) | horizontal (16:9)
  --zoom N          Zoom factor for vertical_blur foreground (default: 1.0 = fit width).
                    Use 1.5–2.0 for talking-head / person-on-screen video to punch in on subject.
                    No effect on vertical or horizontal formats.
  --out DIR         Output directory (default: out/clips)
  --no-cache        Disable transcript caching. Default caches to /tmp/ for fast re-runs.
                    Use --no-cache when running multiple clipper processes in parallel
                    (prevents concurrent runs clobbering each other's temp files).
```

---

## Broadcast Elements

The `broadcast` command assembles a full broadcast package: SMPTE colour bars,
classic countdown leader, and your programme — exactly as delivered to a broadcaster.

```bash
python3 trailer_forge.py broadcast examples/the_heist_broadcast.yaml
```

### Broadcast YAML structure

```yaml
output: out/the_heist_broadcast.mp4
resolution: [1920, 1080]

broadcast:
  - type: color_bars    # SMPTE 7-bar + PLUGE strip
    duration: 5

  - type: countdown     # 8→2 crosshair leader, 1s/count (1 omitted per convention)
    duration: 7

  - type: programme     # your main content
    source: out/the_heist.mp4

  # Optional: burn a lower third overlay onto a clip
  - type: lower_third
    clip: out/the_heist.mp4
    name: "THE HEIST"
    role: "A trailer-forge demo"
    fade_in: 1.0
    fade_out: 1.0
    output: out/the_heist_with_lower_third.mp4
```

See `examples/the_heist_broadcast.yaml` for a full annotated example.

---

## Chapters — YouTube Chapter Markers

Chapters auto-generates YouTube chapter markers from any local video file using
Whisper transcription and silence-gap detection.

```
video file → ffmpeg audio extract → Whisper transcription → silence detection → chapter markers
```

### Quick start

```bash
# Generate chapters for a video
python3 trailer_forge.py chapters my_video.mp4

# Adjust silence threshold (default: 2s gaps)
python3 trailer_forge.py chapters my_video.mp4 --silence 3.0

# Tweak noise floor for silence detection
python3 trailer_forge.py chapters my_video.mp4 --noise-db -35
```

### Output

Chapters are printed to stdout in YouTube-compatible format and saved alongside the video:

```
0:00 Intro
1:23 Welcome To The Show
4:07 Deep Dive On Topic
9:55 Final Thoughts
```

The `.chapters` file (`my_video.mp4.chapters`) is ready to paste into YouTube's chapter
field in Studio.

### How it works

1. **Audio extract** — ffmpeg pulls mono 16kHz audio (ideal for Whisper)
2. **Silence detection** — `silencedetect` filter finds gaps ≥ 2s at −40 dB
3. **Transcription** — Whisper base model produces word-level timestamps
4. **Sentence grouping** — words are grouped by sentence-ending punctuation
5. **Boundary alignment** — each silence gap is matched to the nearest sentence end
6. **Label generation** — chapter title = first 5 words of the following sentence

### Options

```
python3 trailer_forge.py chapters <video_file> [options]

  --silence N       Minimum silence gap in seconds (default: 2.0)
  --noise-db N      Noise threshold in dB, e.g. -40 (default: -40)
  --label-words N   Words to use for chapter label (default: 5)
```

### Requirements

| Tool | Purpose | Install |
|------|---------|---------|
| `whisper` | Local transcription | `pip install openai-whisper` |
| `ffmpeg` | Audio extract + silence detect | `sudo apt install ffmpeg` |

---

## Compress for Sharing

```bash
# For Telegram/Discord (targets ~3MB for a 40s trailer)
ffmpeg -y -i out/my_trailer.mp4 \
  -vcodec libx264 -crf 30 -preset slow \
  -acodec aac -b:a 128k \
  -movflags +faststart \
  my_trailer_share.mp4
```

> **Note:** Film grain is incompressible — the raw output is large. Always recompress
> with `crf 28–32` before sharing.

## Project Structure

```
trailer-forge/
├── trailer_forge.py          # Main CLI (~1500 lines)
├── tools/
│   ├── clipper.py            # YouTube → social clips pipeline
│   ├── chapters.py           # YouTube chapter marker generator
│   └── sync_yaml.py          # Whisper word-timestamp → YAML duration calculator
├── canvas_renderer/
│   ├── render_card.js        # Node.js canvas renderer
│   └── package.json
├── fonts/
│   └── BebasNeue.ttf         # Bundled (SIL Open Font License)
├── shots.yaml                # Shot preset library (cinematography vocabulary)
├── sfx_map.yaml              # Automated SFX sound design mappings
├── examples/
│   ├── simple.yaml           # Minimal example
│   ├── the_heist.yaml        # Full demo with presets + SFX
│   ├── the_heist_broadcast.yaml  # Broadcast package example (colour bars, countdown)
│   └── the_gathering_v2.yaml    # Frame-perfect sync example (8 Whisper cues, Veo clips)
└── docs/
    ├── YAML_REFERENCE.md
    ├── SYNC_GUIDE.md
    ├── SHOT_PRESETS.md
    └── PRODUCTION_PIPELINE.md
```

## Requirements

| Dependency | Purpose | Required? |
|-----------|---------|-----------|
| `ffmpeg` | Video assembly, encoding | ✅ Yes |
| `pillow` | Title card rendering (fallback) | ✅ Yes |
| `pyyaml` | YAML manifest parsing | ✅ Yes |
| `requests` | Veo API calls | ✅ Yes |
| Node.js + `canvas` npm | Better text rendering | Optional (recommended) |
| `whisper` | Word-level sync | Optional (recommended) |
| `GEMINI_API_KEY` | Veo 2 clip generation | Optional |

## Use with AI Agents

trailer-forge is built to be called by agents via shell. OpenClaw users can load the
`movie-trailer` skill for a full end-to-end pipeline including ElevenLabs VO generation,
Veo clip queuing, Whisper sync, and assembly.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

Open issues for:
- New color grades
- Additional segment types (image slideshow, text animation)
- Better font fallback on Windows/macOS
- Subtitle/SRT overlay support as a first-class segment type

---

<div align="center">

**Made with 🎬 by [Hilary Kai](https://github.com/hilaryduffrules-hash) × [MurdawkMedia](https://www.murdawkmedia.com)**

*A collab between an AI and the human who keeps giving her interesting problems.*

⚡ If this saved you time, a few sats are always appreciated:  
`⚡ hilaryduffrules@coinos.io`

</div>
