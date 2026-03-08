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

Getting title cards to appear exactly when the narrator says the phrase is the hard part.
trailer-forge solves this with Whisper word-level timestamps:

```bash
# 1. Get exact word timestamps from your voiceover
whisper assets/voiceover.mp3 --model small --word_timestamps True \
  --output_format json --output_dir whisper_out

# 2. Print word timings
python3 -c "
import json
data = json.load(open('whisper_out/voiceover.json'))
for s in data['segments']:
    for w in s.get('words', []):
        print(f\"{w['start']:6.2f}s  {w['word']}\")
"

# 3. Set each segment duration so its cumulative sum = that word's timestamp
# 4. Verify with the diagnostic subtitle burn (see docs/SYNC_GUIDE.md)
```

See [`docs/SYNC_GUIDE.md`](docs/SYNC_GUIDE.md) for the full method.

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

# Custom output directory
python3 trailer_forge.py clip "https://youtu.be/..." --top 3 --out /tmp/my_clips
```

### How clip detection works

Clipper scores every 45-second sliding window of the transcript using:
- **Word density** — windows with more speech get higher scores
- **Sentence completeness** — windows that end on complete sentences score better

The top N non-overlapping windows are selected and assembled. This means you get
the most information-dense, cleanly bounded moments from the video — not arbitrary cuts.

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
  --format FORMAT   vertical (9:16) or horizontal (16:9) (default: vertical)
  --out DIR         Output directory (default: out/clips)
```

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
├── trailer_forge.py          # Main CLI
├── canvas_renderer/
│   ├── render_card.js        # Node.js canvas renderer
│   └── package.json
├── fonts/
│   └── BebasNeue.ttf         # Bundled (SIL Open Font License)
├── examples/
│   └── simple.yaml
└── docs/
    ├── YAML_REFERENCE.md
    └── SYNC_GUIDE.md
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
