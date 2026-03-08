# Sync Guide — Nailing Audio/Visual Timing

The #1 challenge in AI trailer generation: making title cards appear exactly
when the narrator says the corresponding phrase. This guide explains the method
that actually works.

## The Wrong Way (Estimation)

Writing durations by feel: "I think the narrator says this phrase around second 10..."

This leads to timing that's "off" — sometimes early, sometimes late, accumulating
errors through the video. Don't do this.

## The Right Way (Whisper Word Timestamps)

1. **Generate your voiceover** (ElevenLabs or any TTS)
2. **Run Whisper** to get exact word-level timestamps
3. **Build the YAML** so cumulative segment durations equal Whisper timestamps

### Step 1: Extract timestamps

```bash
# Activate your Whisper environment
source ~/.venv-whisper/bin/activate  # or wherever yours is

mkdir -p whisper_out
whisper assets/voiceover.mp3 \
  --model small \
  --word_timestamps True \
  --output_format json \
  --output_dir whisper_out \
  --language en \
  --device cuda   # or cpu
```

### Step 2: Read the timestamps

```bash
python3 - << 'EOF'
import json, sys
data = json.load(open("whisper_out/voiceover.json"))
for seg in data["segments"]:
    for w in seg.get("words", []):
        print(f"{w['start']:6.2f} → {w['end']:6.2f}  {w['word']}")
EOF
```

Output will look like:
```
  0.00 →   0.16   In
  0.16 →   0.30   a
  0.30 →   0.64   world
  2.94 →   3.38   man,
 10.76 →  11.08   plunger,
```

### Step 3: Calculate segment durations

For each title card, find the Whisper timestamp of its key word, then calculate
the duration of the preceding clip/segment to fill the gap:

```python
# If "NOT HIS PLUNGER" should appear at t=10.76
# And previous segments sum to t=7.20
# Then the clip filling the gap must be:
clip_duration = 10.76 - 7.20  # = 3.56s
```

Build your YAML with these exact durations — the cumulative sum of all segments
before a title card equals that card's Whisper timestamp.

### Step 4: Verify with diagnostic subtitles

```bash
# Generate SRT from Whisper output
python3 - << 'EOF'
import json
data = json.load(open("whisper_out/voiceover.json"))
def ts(s): h,m,r=int(s//3600),int((s%3600)//60),s%60; return f"{h:02d}:{m:02d}:{r:06.3f}".replace(".",",")
lines, i = [], 1
for seg in data["segments"]:
    for w in seg.get("words", []):
        lines.append(f"{i}\n{ts(w['start'])} --> {ts(w['end'])}\n{w['word']}\n"); i += 1
open("words.srt", "w").write("\n".join(lines))
print(f"Written {i-1} words")
EOF

# Burn into video for diagnosis
ffmpeg -y -i out/my_trailer.mp4 \
  -vf "subtitles=words.srt:force_style='FontSize=28,PrimaryColour=&H0000FFFF,Outline=2'" \
  -c:a copy -movflags +faststart diagnostic.mp4
```

Watch the diagnostic: yellow subtitles show exact word timing.
- **Subtitles before cards** → cards are late → shorten preceding clip
- **Subtitles after cards** → cards are early → extend preceding clip

### Whisper Model Recommendations

| Model | GPU VRAM | Speed | Accuracy |
|-------|----------|-------|---------|
| `tiny` | ~1GB | Very fast | Low |
| `small` | ~2GB | Fast | Good enough |
| `medium` | ~5GB | Medium | High |
| `large` | ~10GB | Slow | Best |

`small` is the sweet spot for trailer work — accurate enough for ±100ms sync,
runs in ~30s on a modern GPU.

## Common Timing Issues

**"All cards consistently early/late"** — Global offset. Check that `voice_delay: 0.0`
and that the audio file doesn't have leading silence. Re-examine which Whisper
timestamp corresponds to which phrase.

**"One specific card is off, rest are fine"** — Local issue. Extend or shorten the
preceding clip by the offset amount. Use the diagnostic subtitles to measure exactly.

**"Cards drift over time"** — Accumulating floating point error is rare but real.
ffmpeg rounds to frame boundaries (1/30s = 33ms). Over 30 segments, max drift is ~1s.
Fix by verifying cumulative sums at multiple keyframes, not just the first.
