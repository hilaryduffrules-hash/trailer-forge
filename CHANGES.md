# trailer-forge — Change Log

## Session: Mar 1–7, 2026 (Hilary Kai)

All of the following were added directly to `main`. Future changes will come through PRs.

### ✨ New Commands
- **`clip <youtube_url>`** — Download → Whisper transcribe → detect top moments → assemble vertical (9:16) or horizontal social clips. `--top N`, `--format vertical|horizontal`
- **`chapters <video_file>`** — Auto-generate YouTube chapter markers from a video's transcript. Detects silence gaps + sentence boundaries, outputs `0:00 Label` format + `.chapters` file
- **`deliver <video>`** — Multi-platform export: YouTube, Telegram, Instagram feed/Reel, TikTok (auto-crops, CRF-tuned per platform)
- **`export-srt <whisper_json>`** — Whisper JSON → SRT subtitles with word-level timecodes
- **`storyboard <yaml>`** — Shot list → AI visual panel descriptions (Veo-ready)
- **`broadcast <yaml>`** — Broadcast package: lower thirds, countdown leader, colorbars

### 🔧 Infrastructure
- **Shot presets** (`shots.yaml`) — 20+ cinematic vocabulary: ECU, CU, OTS, dolly zoom, crane, whip pan, etc. Mapped to Veo prompt formula
- **SFX automation** (`sfx_map.yaml`) — Scene types auto-mapped to sound effect layers
- **Unified CLI** — All commands under single `trailer_forge.py` entry point
- **Clipper module** (`tools/clipper.py`) — Reusable pipeline: yt-dlp + Whisper + sliding window scoring + ffmpeg assembly
- **Chapters module** (`tools/chapters.py`) — Silence detection + sentence boundary alignment

### 📖 Docs
- `docs/SHOT_PRESETS.md` — Full vocabulary reference
- `tools-knowledge-vault/Workflows/Film-Production-Pipeline-Research.md` — Research synthesis
- `tools-knowledge-vault/Workflows/trailer-forge-roadmap.md` — 7-phase implementation plan

