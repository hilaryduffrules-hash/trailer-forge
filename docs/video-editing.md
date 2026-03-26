# Video Editing Patterns — trailer-forge reference

## Seamless Loop Stitching (card spin / product rotation)

**Use case:** Two clips of a rotating object (front→back, back→front) need to be joined into a seamless infinite loop.

**The problem:** Rotation videos typically slow down at the ends. A direct concat creates a visible stutter.

**The fix:** Find the matching angle frames in both clips and trim to those.

### Step-by-step

```python
# 1. Extract diagnostic frames to find trim points
# Extract every 0.2s near the end of clip A and start of clip B
for t in [x/10 for x in range(60, 82, 2)]:  # t=6.0 to t=8.0
    os.system(f"ffmpeg -ss {t} -i clip_a.mp4 -vframes 1 clip_a_t{t}.jpg -y")
for t in [x/10 for x in range(0, 20, 2)]:   # t=0.0 to t=2.0
    os.system(f"ffmpeg -ss {t} -i clip_b.mp4 -vframes 1 clip_b_t{t}.jpg -y")

# 2. Visually inspect frames to find matching angles
# Look for: same tilt/perspective on the object in both clips

# 3. Trim
# ffmpeg -i clip_a.mp4 -ss 0 -t <trim_end> -c:v libx264 -crf 16 -an a_trim.mp4
# ffmpeg -i clip_b.mp4 -ss <trim_start> -c:v libx264 -crf 16 -an b_trim.mp4

# 4. Concat
# printf "file 'a_trim.mp4'\nfile 'b_trim.mp4'\n" > concat.txt
# ffmpeg -f concat -safe 0 -i concat.txt -c:v libx264 -crf 16 one_cycle.mp4

# 5. Loop N times
# printf "file 'one_cycle.mp4'\n" * N > loop.txt
# ffmpeg -f concat -safe 0 -i loop.txt -c:v libx264 -crf 18 -movflags +faststart output.mp4
```

### Typical trim values for product rotation clips
- Cut clip A at ~80% of its duration (skip the slowdown at end)
- Start clip B at ~5-10% in (skip dead start)
- Target: both frames show same object angle at the cut point

---

## Ken Burns on Still Images (9:16)

```bash
# Slow zoom in
ffmpeg -loop 1 -i input.jpg \
  -vf "scale=2160:3840,zoompan=z='min(zoom+0.0008,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=<fps*duration>:s=1080x1920" \
  -t <duration> -r 24 -pix_fmt yuv420p output.mp4

# Pan left to right
ffmpeg -loop 1 -i input.jpg \
  -vf "scale=2500:4500,zoompan=z='1.2':x='if(lte(on,1),0,x+2)':y='ih/2-(ih/zoom/2)':d=<fps*duration>:s=1080x1920" \
  -t <duration> -r 24 output.mp4
```

---

## xfade Assembly with Python Offset Calculator

```python
import subprocess

clips = ["clip1.mp4", "clip2.mp4", "clip3.mp4"]  # pre-processed clips
xfade_dur = 0.5

# Get durations
durations = []
for c in clips:
    r = subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0",c], capture_output=True, text=True)
    durations.append(float(r.stdout.strip()))

# Build filtergraph
n = len(clips)
inputs = " ".join([f"-i {c}" for c in clips])
filter_parts = []
offset = durations[0] - xfade_dur
filter_parts.append(f"[0:v][1:v]xfade=transition=fade:duration={xfade_dur}:offset={offset:.3f}[v01]")

prev = "v01"
cumulative = durations[0] + durations[1] - xfade_dur
for i in range(2, n):
    tag = f"v{i:02d}"
    filter_parts.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={xfade_dur}:offset={cumulative-xfade_dur:.3f}[{tag}]")
    cumulative += durations[i] - xfade_dur
    prev = tag

total_dur = sum(durations) - xfade_dur * (n-1)
filter_str = ";".join(filter_parts)
final_tag = f"v{n-1:02d}"
```

---

## Color Grading

```bash
# Warm atmospheric grade (for Veo/cinematic shots, NOT source art)
-vf "colorchannelmixer=rr=1.05:gg=0.98:bb=0.90"

# Slightly desaturated unified look
-vf "eq=saturation=0.85:brightness=0.02:gamma=0.95"

# Film grain
-vf "noise=alls=6:allf=t+u"
```

---

## Audio Patterns

```bash
# Fade in 0.3s, fade out 3s from end, volume 0.65
-af "afade=t=in:d=0.3,afade=t=out:st=<total-3>:d=3.0,volume=0.65"

# Strip all source audio (use with -an during pre-processing)
-an

# Mix single music track over video
ffmpeg -i video.mp4 -i music.mp3 -map 0:v -map 1:a \
  -af "afade=t=in:d=1,afade=t=out:st=<end-3>:d=3,volume=0.65" \
  -shortest output.mp4
```

---

## Strip White Margins from Comic/Image Pages (PIL)

```python
from PIL import Image
import numpy as np

img = Image.open("page.jpg")
arr = np.array(img)
white_mask = (arr[:,:,0] > 240) & (arr[:,:,1] > 240) & (arr[:,:,2] > 240)
content_rows = np.where(~white_mask.all(axis=1))[0]
content_cols = np.where(~white_mask.all(axis=0))[0]
margin = 8
crop = img.crop((content_cols[0]-margin, content_rows[0]-margin,
                 content_cols[-1]+margin, content_rows[-1]+margin))

# Scale to 9:16 (1080x1920)
w, h = crop.size
scale = max(1080/w, 1920/h)
crop = crop.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
left = (crop.width-1080)//2; top = (crop.height-1920)//2
crop = crop.crop((left, top, left+1080, top+1920))
crop.save("output_9x16.jpg", quality=97)
```

---

## Veo Page Animation — Art-Preserving Prompts

**What works:**
- "Subtle ambient motion only. Atmospheric light drifts slowly. Artwork unchanged. Camera still."
- Same image as BOTH start AND end frame = Veo stays on the page

**What causes chaos (avoid unless you want it):**
- "transforms into", "becomes", "evolves into" → dramatic page-ripping/collage effect
- Describing the scene in detail → Veo tries to redraw it

**Warm grade for atmospheric shots only — never on source art clips.**

---

## kie.ai API (Runway Gen-3, Veo 3.1, Kling 3.0)

```bash
# Load key from Bitwarden
KIE_KEY=$(bw get password de5faec6-a367-4b02-ad9f-b41801804ae7)

# Image-to-video (Runway Gen-3)
curl -X POST https://api.kie.ai/api/v1/runway/generate \
  -H "Authorization: Bearer $KIE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gen3a_turbo","promptImage":"<url>","promptText":"<motion prompt>","duration":8,"ratio":"768:1344"}'

# Poll for result
curl https://api.kie.ai/api/v1/task/record-detail?taskId=<id> \
  -H "Authorization: Bearer $KIE_KEY"
```

Credit costs: ~12 credits/sec at 720p, ~20/sec at 1080p. Media auto-deletes after 14 days.

---

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Veo animated pages | veo_page_*.mp4 | veo_page_color.mp4 |
| Veo atmospheric shots | veo_atmos_*.mp4 | veo_atmos_pagoda.mp4 |
| Veo transition clips | veo_transition_*.mp4 | veo_transition_sketch.mp4 |
| Card spin trims | <card>_ftb_trim.mp4 | boomers_ftb_trim.mp4 |
| End frames (no margins) | endframe_*.jpg | endframe_color.jpg |


---

## Seamless Card Spin Stitch — Velocity Matching Method ✅ PROVEN

**The problem with naive trimming:** Both front→back and back→front clips slow down at the back face (card square-on to camera). Cutting at matching angles still produces a visible lurch because the speeds differ.

**The correct approach — pixel velocity measurement:**

```python
import subprocess, numpy as np
from PIL import Image

def mean_diff(f1, f2):
    """Pixel displacement between frames = proxy for rotation speed."""
    a = np.array(Image.open(f1).convert("L"), dtype=float)
    b = np.array(Image.open(f2).convert("L"), dtype=float)
    return np.mean(np.abs(a - b))

# 1. Extract frames around end of clip A and start of clip B
for i in range(150, 180):
    subprocess.run(["ffmpeg", "-i", "clip_a.mp4",
        "-vf", f"select=eq(n\\,{i})", "-vframes", "1", "-q:v", "2",
        f"frames/a_{i:03d}.jpg", "-y"], capture_output=True)

for i in range(0, 30):
    subprocess.run(["ffmpeg", "-i", "clip_b.mp4",
        "-vf", f"select=eq(n\\,{i})", "-vframes", "1", "-q:v", "2",
        f"frames/b_{i:03d}.jpg", "-y"], capture_output=True)

# 2. Measure speed at each frame
print("Clip A tail speeds:")
for i in range(150, 178):
    diff = mean_diff(f"frames/a_{i:03d}.jpg", f"frames/a_{i+1:03d}.jpg")
    print(f"  frame {i}→{i+1}: {diff:.2f}")

print("Clip B head speeds:")
for i in range(0, 20):
    diff = mean_diff(f"frames/b_{i:03d}.jpg", f"frames/b_{i+1:03d}.jpg")
    print(f"  frame {i}→{i+1}: {diff:.2f}")

# 3. Find cut frame in clip A where speed matches clip B frame 0
# Look for where clip A speed ≈ clip B speed at frame 0-5
# In card spin: this is typically where card is square-on (minimum speed ~1.0-1.5)
```

### Typical card spin speed profile
| Point | Speed (mean pixel diff) |
|-------|------------------------|
| Card edge (fastest) | 5.0-8.0 |
| Card at 45° | 3.0-5.0 |
| Card square-on (slowest) | 0.8-1.5 |

**Cut point:** Find frame in clip A where speed ≈ speed of clip B frame 0-3.
For symmetric clips (same decel/accel curve), this is near the minimum speed.

### Assembly with dissolve
```bash
# Cut clip A at matched frame, keep full clip B, dissolve through join
FTB_CUT_FRAME=171      # where ftb speed ≈ btf frame-0 speed
XFADE_FRAMES=8         # 8-frame dissolve (0.33s at 24fps) — enough to hide blend
FPS=24

ftb_dur=$(echo "scale=6; $FTB_CUT_FRAME/$FPS" | bc)
xfade_dur=$(echo "scale=6; $XFADE_FRAMES/$FPS" | bc)
offset=$(echo "scale=6; $ftb_dur - $xfade_dur" | bc)

# Trim clip A to cut frame
ffmpeg -i clip_a.mp4 -vf "trim=end_frame=${FTB_CUT_FRAME},setpts=PTS-STARTPTS" \
  -c:v libx264 -crf 14 -preset fast -an clip_a_trim.mp4 -y

# Assemble with xfade
ffmpeg -i clip_a_trim.mp4 -i clip_b.mp4 \
  -filter_complex "[0:v][1:v]xfade=transition=fade:duration=${xfade_dur}:offset=${offset}[v]" \
  -map "[v]" -c:v libx264 -crf 16 -preset medium -movflags +faststart -an \
  output_seamless.mp4 -y
```

**Why this works:**
- The dissolve covers the 1-2 frame angle mismatch that remains after speed matching
- At minimum speed, consecutive frames are nearly identical — the dissolve is invisible
- 8 frames (0.33s) is enough to smooth the transition without looking like a fade

**Validated on:** Boomers in Bitcoin #32 card spin (TAG graded slab, 1920x1080 24fps)
