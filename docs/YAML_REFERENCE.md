# YAML Manifest Reference

Full reference for `trailer-forge` manifest files.

## Top-Level Fields

```yaml
output: out/my_trailer.mp4     # Output path (relative to manifest)
resolution: [1920, 1080]       # Width x Height (pixels)
fps: 30                        # Frames per second
film_grain: true               # Apply subtle film grain (default: true)
color_grade: dark_thriller     # Grade preset (see below)
audio:
  music: assets/music.mp3      # Background music
  voiceover: assets/vo.mp3     # Voiceover narration
  music_vol: 0.28              # Music volume multiplier (0.0–1.0)
  voice_vol: 1.0               # Voice volume multiplier
  voice_delay: 0.0             # Seconds to delay voiceover start
timeline:
  - type: ...                  # See segment types below
```

## Color Grades

| Value | Description |
|-------|-------------|
| `none` | No grading |
| `teal_orange` | Hollywood blockbuster look (warm highlights, cool shadows) |
| `dark_thriller` | Low-key, desaturated, moody |
| `vintage` | Faded, warm, classic |

## Segment Types

### `title_card`

Displays text on a dark background with gold rule brackets, vignette, and cinema bars.

```yaml
- type: title_card
  lines:
    - {text: "IN A WORLD",   font: bebas, size: 200, color: white}
    - {text: "subtitle here", font: sans,  size: 56,  color: gold}
  duration: 2.5     # seconds on screen
  fade_in: 0.60     # seconds to fade in
  fade_out: 0.30    # seconds to fade out
```

**Font options:** `bebas` (Bebas Neue, all-caps cinematic) · `sans` (NimbusSans bold, body text)

**Color options:** `white` · `gold` · `grey` · `red`

**Fade strategy:**
- Opening titles: `fade_in: 0.60–0.90` (cinematic)
- Impact titles: `fade_in: 0.06` (hard cut, maximum punch)
- Revelation words: `fade_in: 0.25` (slow gold dissolve)

---

### `veo_clip`

Video clip with trim, color grade, cinema bars, and fades.

```yaml
- type: veo_clip
  file: clips/my_clip.mp4   # path relative to manifest
  trim: [0, 4.5]            # [start_seconds, end_seconds]
  fade_in: 0.40
  fade_out: 0.35
  # Optional — add prompt for auto-generation with `build` command:
  prompt: "cinematic wide shot, abandoned warehouse, moody blue light, film grain"
```

If `prompt` is set and `file` doesn't exist, running `trailer-forge build` will call
Veo 2 to generate it (requires `GEMINI_API_KEY`).

---

### `black`

A silent black frame — use for dramatic pauses between beats.

```yaml
- type: black
  duration: 0.5   # seconds
```

---

### `main_title`

The final hero title card. Renders "T H E" above the title automatically between two gold rules.

```yaml
- type: main_title
  title: "PLUNGE"                              # Do NOT include "THE" — it's added automatically
  tagline: "They shared an apartment. Not a plunger."
  duration: 5.0
  fade_in: 0.90
  fade_out: 0.0
```

## Sync Tip: Whisper-Driven Timing

The most reliable way to sync title cards to narration:

1. Generate your voiceover
2. Run Whisper with `--word_timestamps True` to get exact word-level timestamps
3. Set each segment's start time to the corresponding Whisper timestamp by adjusting durations so their cumulative sum equals the target timestamp

```
segment_duration = next_key_timestamp - running_total
```

See [`../skills/` scripts](../skills/) for helper scripts.

## Complete Example

See [`examples/simple.yaml`](../examples/simple.yaml) for a minimal working manifest.
