# Comic / Illustration Video Pipeline

Complete step-by-step guide: comic page JPGs → cinematic 9:16 video.

Developed during the Satoshi's Heroes teaser production (2026-03-25).

---

## Overview

```
Comic page JPGs
    → PIL: strip white margins, crop to 9:16
    → Veo: animate pages (start+end frame = art preserved)
    → Veo: atmospheric bridge shots (prompts only)
    → ffmpeg: pre-process all clips to common spec
    → Python: compute xfade offsets
    → ffmpeg: xfade assembly + color grades
    → ffmpeg: audio mix + film grain
    → Final encode
```

---

## Step 1: Prepare Comic Pages

### Strip White Margins and Scale to 9:16

```python
from PIL import Image
import numpy as np
import os

def find_content_bounds(img_path, threshold=240):
    """Return (x0, y0, x1, y1) bounding box of non-white content."""
    img = Image.open(img_path).convert('RGB')
    arr = np.array(img)
    mask = np.any(arr < threshold, axis=2)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return (0, 0, img.width, img.height)
    return (cols[0], rows[0], cols[-1]+1, rows[-1]+1)

def prepare_page(img_path, out_path, target_w=1080, target_h=1920):
    """Strip white margins and place content on black 9:16 canvas."""
    img = Image.open(img_path)
    x0, y0, x1, y1 = find_content_bounds(img_path)
    content = img.crop((x0, y0, x1, y1))
    content.thumbnail((target_w, target_h), Image.LANCZOS)
    canvas = Image.new('RGB', (target_w, target_h), (0, 0, 0))
    paste_x = (target_w - content.width) // 2
    paste_y = (target_h - content.height) // 2
    canvas.paste(content, (paste_x, paste_y))
    canvas.save(out_path)
    print(f"  {img_path} → {out_path} ({content.width}x{content.height} content)")

# Process all pages
os.makedirs('prepared', exist_ok=True)
for i, f in enumerate(sorted(os.listdir('pages/'))):
    if f.lower().endswith(('.jpg', '.jpeg', '.png')):
        prepare_page(f'pages/{f}', f'prepared/page_{i+1:02d}.png')
```

---

## Step 2: Animate Pages with Veo

### The Art Preservation Rule

Pass the **same image as both `start_frame` AND `end_frame`**. This constrains Veo to atmospheric-only animation — the artwork stays intact.

Without an end frame, Veo treats the image as a launch point and will freely transform it.

### Veo Prompt Templates

**For comic pages (art preservation):**
```
Atmospheric animation only. No changes to artwork. Camera completely still.
Gentle dust particles drifting in warm golden light. The comic illustration remains intact.
Film grain texture. 5 seconds.
```

```
Subtle atmospheric motion only. No transformation of the artwork. Completely static camera.
A soft glow pulses at the edges. Faint smoke drifts in the background shadows.
The illustration does not change. 5 seconds.
```

```
Still illustration. Atmospheric breathing only. No morphing, no camera movement.
Ambient bokeh light shifts slowly. Particles float in the foreground.
Art is completely preserved. 5 seconds.
```

**For atmospheric bridge shots (no source art):**
```
Cinematic close-up of [subject]. Moody [lighting style]. Shallow depth of field.
Slow drift of [smoke/dust/rain]. Film grain. 4-5 seconds.
```

**Prompts that FAIL (never use on art clips):**
- "transforms into" → page-ripping chaos
- "reveals" / "morphs" / "emerges" → Veo destroys the art
- "camera pushes in" / "pan right" → destabilizes the frame
- "dissolves to" → will start blending with nothing

### Naming Convention

```
clips/
├── veo_page_01.mp4       # Animated page 1 (start+end frame = same image)
├── veo_page_02.mp4       # Animated page 2
├── veo_page_03.mp4       # etc.
├── veo_atmos_01.mp4      # Atmospheric bridge (Bitcoin symbol, city skyline, etc.)
├── veo_atmos_02.mp4
└── veo_transition_01.mp4 # Hard cut transition shot
```

### Generating Clips via kie.ai API

```bash
source ~/.openclaw/workspace/.env   # loads KIE_AI_API_KEY

# Submit a Veo job with start+end frames (art preservation)
python3 scripts/veo_gen.py \
  --prompt "Atmospheric animation only. No changes to artwork..." \
  --start-frame prepared/page_01.png \
  --end-frame prepared/page_01.png \   # SAME image = art preserved
  --duration 5 \
  --output clips/veo_page_01.mp4

# Atmospheric shot (prompts only)
python3 scripts/veo_gen.py \
  --prompt "Cinematic shot of a Bitcoin symbol carved in stone, warm golden light..." \
  --duration 5 \
  --output clips/veo_atmos_01.mp4
```

**Rate limits:** Submit clips sequentially with `time.sleep(5)` between jobs. Parallel submission triggers 429.

---

## Step 3: Pre-Process All Clips

Normalize all clips to the same spec before assembly:

```bash
mkdir -p processed

# Process each clip: scale to 1080x1920, 30fps, yuv420p
for f in clips/veo_page_*.mp4 clips/veo_atmos_*.mp4; do
    base=$(basename "$f" .mp4)
    ffmpeg -y -i "$f" \
      -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1" \
      -r 30 -pix_fmt yuv420p -c:v libx264 -crf 18 -preset fast \
      -an \
      "processed/${base}.mp4"
    echo "Processed: $base"
done
```

---

## Step 4: Apply Color Grades (Atmospheric Only)

**KEY RULE: Never grade source art clips. Only grade atmospheric/bridge shots.**

```bash
# Warm grade for atmospheric shots
# colorchannelmixer: slight red boost, slight blue reduction = warm cinematic feel
for f in processed/veo_atmos_*.mp4; do
    base=$(basename "$f" .mp4)
    ffmpeg -y -i "$f" \
      -vf "colorchannelmixer=rr=1.05:gg=0.98:bb=0.90" \
      -c:v libx264 -crf 18 -preset fast \
      "processed/${base}_graded.mp4"
    mv "processed/${base}_graded.mp4" "$f"
done
```

---

## Step 5: Compute xfade Offsets (Python)

xfade offset = cumulative duration of all preceding clips minus the crossfade duration.

```python
#!/usr/bin/env python3
"""Compute xfade filter offsets for ffmpeg assembly."""

import subprocess

def get_duration(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())

# Define your clip sequence
clips = [
    'processed/veo_atmos_01.mp4',   # Opening atmosphere
    'processed/veo_page_01.mp4',    # Page 1
    'processed/veo_atmos_02.mp4',   # Bridge
    'processed/veo_page_02.mp4',    # Page 2
    'processed/veo_page_03.mp4',    # Page 3
    'processed/veo_atmos_03.mp4',   # Closing atmosphere
]

XFADE_DURATION = 0.5  # seconds of overlap between clips

durations = [get_duration(c) for c in clips]

print("Clip durations:")
for c, d in zip(clips, durations):
    print(f"  {c}: {d:.3f}s")

# Compute offsets
offsets = []
running = 0.0
for i, d in enumerate(durations[:-1]):
    running += d
    offset = running - XFADE_DURATION
    offsets.append(offset)
    running -= XFADE_DURATION  # account for overlap

print(f"\nxfade offsets (duration={XFADE_DURATION}s):")
for i, o in enumerate(offsets):
    print(f"  clip {i} → clip {i+1}: offset={o:.3f}")

print("\nTotal video duration:", sum(durations) - XFADE_DURATION * (len(clips) - 1))
```

---

## Step 6: Assemble with xfade Filtergraph

```bash
# Example: 6 clips with dissolve transitions
# Replace offset values with output from Step 5

XFADE_DUR=0.5

ffmpeg -y \
  -i processed/veo_atmos_01.mp4 \
  -i processed/veo_page_01.mp4 \
  -i processed/veo_atmos_02.mp4 \
  -i processed/veo_page_02.mp4 \
  -i processed/veo_page_03.mp4 \
  -i processed/veo_atmos_03.mp4 \
  -filter_complex "
    [0:v][1:v]xfade=transition=dissolve:duration=0.5:offset=4.50[v01];
    [v01][2:v]xfade=transition=dissolve:duration=0.5:offset=9.00[v02];
    [v02][3:v]xfade=transition=dissolve:duration=0.5:offset=13.50[v03];
    [v03][4:v]xfade=transition=dissolve:duration=0.5:offset=18.00[v04];
    [v04][5:v]xfade=transition=dissolve:duration=0.5:offset=22.50[vout]
  " \
  -map "[vout]" \
  -c:v libx264 -crf 18 -preset slow \
  assembled.mp4
```

**Generate the filtergraph string dynamically:**
```python
def build_xfade_filtergraph(n_clips, offsets, transition='dissolve', duration=0.5):
    lines = []
    prev = '0:v'
    for i in range(1, n_clips):
        label = f'vout' if i == n_clips - 1 else f'v{i:02d}'
        lines.append(
            f'[{prev}][{i}:v]xfade=transition={transition}:duration={duration}'
            f':offset={offsets[i-1]:.3f}[{label}]'
        )
        prev = label
    return ';\n    '.join(lines)

# Print it
print(build_xfade_filtergraph(len(clips), offsets))
```

---

## Step 7: Film Grain Pass

Apply consistent film grain to the assembled video. This unifies art clips and atmospheric shots visually.

```bash
ffmpeg -y -i assembled.mp4 \
  -vf "noise=alls=6:allf=t" \
  -c:v libx264 -crf 20 -preset slow \
  assembled_grain.mp4
```

**Note:** `noise=alls=6:allf=t` creates large files. Always recompress after (crf=28-30).

---

## Step 8: Audio Mix

```bash
# Kevin MacLeod "At Rest" — sparse piano, melancholic, free/CC
# Download: wget "https://incompetech.com/music/royalty-free/mp3-royaltyfree/At%20Rest.mp3"

VIDEO_DUR=$(ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 assembled_grain.mp4)

ffmpeg -y \
  -i assembled_grain.mp4 \
  -i assets/at_rest.mp3 \
  -filter_complex "
    [1:a]afade=t=in:d=2,afade=t=out:st=$(echo "$VIDEO_DUR - 3" | bc):d=3,
    atrim=0:${VIDEO_DUR},asetpts=PTS-STARTPTS[music]
  " \
  -map 0:v -map '[music]' \
  -c:v copy -c:a aac -b:a 192k \
  -shortest \
  with_audio.mp4
```

---

## Step 9: Final Encode

```bash
ffmpeg -y -i with_audio.mp4 \
  -vcodec libx264 -crf 28 -preset slow \
  -acodec aac -b:a 128k \
  -movflags +faststart \
  final.mp4

# Compress for Telegram (<15MB target)
ffmpeg -y -i final.mp4 \
  -vcodec libx264 -crf 30 -preset slow \
  -acodec aac -b:a 128k \
  -movflags +faststart \
  final_tg.mp4
```

---

## Ken Burns / Zoompan Reference

For still images that aren't going through Veo, add subtle Ken Burns motion:

```bash
# Slow zoom in (1.0 → 1.05 over 5 seconds at 30fps = 150 frames)
ffmpeg -loop 1 -i page.png -t 5 \
  -vf "scale=8000:-1,zoompan=z='min(zoom+0.0003,1.05)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920" \
  -c:v libx264 -crf 18 -preset slow -r 30 \
  page_zoompan.mp4

# Slow pan right
ffmpeg -loop 1 -i page.png -t 5 \
  -vf "scale=8000:-1,zoompan=z=1.02:d=150:x='iw/2-(iw/zoom/2)+t*5':y='ih/2-(ih/zoom/2)':s=1080x1920" \
  -c:v libx264 -crf 18 -preset slow -r 30 \
  page_pan.mp4
```

**Note:** Zoompan requires the input image to be significantly larger than the output resolution. Scale to 8000px wide first.

---

## Lessons Learned (Satoshi's Heroes, 2026-03-25)

- **v1-v3:** Veo without end frame caused art chaos (actually cool, but not what we wanted for product)
- **v4:** Same image as both start+end frame — art preserved, only atmospheric motion
- **v5:** Color grade applied to all clips including art — looked wrong. Removed grades from art clips.
- **v6 (final):** Atmospheric grade on bridge shots only, consistent grain, 29s total ✅

### What worked
- Same start+end frame in Veo = reliable art preservation
- "Atmospheric animation only. No changes to artwork." in prompts = Veo respects the art
- Warm grade on atmospheric shots only = separates them visually without fighting the art palette
- Film grain applied to everything = cohesion between art and atmospheric clips
- "At Rest" piano = perfect for emotional/reverent tone

### What failed
- Transformation language in Veo prompts → page ripping, morphing, art destruction
- Grading source art clips → color cast fought the artist's palette
- Applying heavy zoom/push to art clips → made it look like bad presentation slides

---

## kie.ai API Reference

kie.ai provides access to Veo and Runway Gen-3 image-to-video without direct API access.

```bash
source ~/.openclaw/workspace/.env   # loads KIE_AI_API_KEY

# Check available models
curl -H "Authorization: Bearer $KIE_AI_API_KEY" \
  https://api.kie.ai/v1/models | python3 -m json.tool

# Submit Veo job
curl -X POST https://api.kie.ai/v1/video/generate \
  -H "Authorization: Bearer $KIE_AI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "veo-2",
    "prompt": "Atmospheric animation only...",
    "start_frame_url": "https://...",
    "end_frame_url": "https://...",
    "duration": 5,
    "aspectRatio": "9:16"
  }'
```

Runway Gen-3 is available as an alternative for image-to-video via kie.ai.
