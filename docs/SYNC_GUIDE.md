# Frame-Perfect Sync Guide

Getting title cards to cut in **exactly when the narrator says the word** is what separates
a real trailer from a slideshow with music. This guide covers the full method.

---

## The Core Principle

In trailer-forge, **segments are sequential** — each one plays for its duration, then the next starts.
The visual position at any moment is the **cumulative sum of all preceding segment durations**.

To make a title card appear when the narrator says "wonders" (at 4.10s), the sum of all segments
before that card must equal exactly **4.10s**.

```
black (0.2s) + title_card_1 (3.1s) + veo_clip (0.8s) = 4.1s  ← "SOME BUILD WONDERS." hits here
```

This is what `tools/sync_yaml.py` automates.

---

## Step-by-Step Workflow

### 1. Generate your voiceover

```bash
# ElevenLabs (recommended — natural delivery, pacing control)
python3 tools/gen_voiceover.py "Your script text" assets/voiceover.mp3

# Or use any TTS tool — just get a clean mp3/wav
```

### 2. Transcribe with Whisper (word-level timestamps)

Word-level timestamps are **required**. Segment-level is not precise enough.

```bash
whisper assets/voiceover.mp3 \
    --model small \
    --word_timestamps True \
    --output_format json \
    --output_dir whisper_out
```

GPU recommended for speed. `small` model is accurate enough for VO; `medium` for noisy audio.

### 3. Extract all word timestamps

```bash
python3 tools/sync_yaml.py whisper_out/voiceover.json
```

Output:
```
   START      END   WORD
----------------------------------------
   0.000s   0.320s  Every
   0.320s   0.800s  civilization
   0.800s   1.100s  begins
   ...
   4.100s   4.460s  wonders
   5.400s   5.940s  trebuchet'd
   ...
```

### 4. Identify your sync cues

Pick the **key word** for each title card — the word the narrator says right when you want the cut:

| Timestamp | Word        | Card to show                    |
|-----------|-------------|---------------------------------|
| 4.10s     | "wonders"   | `SOME BUILD WONDERS.`           |
| 5.40s     | "trebuchet" | `SOME GET TREBUCHET'D`          |
| 7.34s     | "best"      | `BY THEIR BEST FRIEND.`         |
| 11.46s    | "night"     | `ONE NIGHT. / ONE LAN PARTY.`   |
| 21.20s    | "one"       | `ONE.`                          |
| 21.92s    | "more"      | `MORE.`                         |
| 22.72s    | "game"      | `GAME.`                         |

### 5. Compute segment durations

```bash
python3 tools/sync_yaml.py whisper_out/voiceover.json \
    --offset 0.2 \
    --cues \
        "wonders:WONDERS:SOME BUILD WONDERS." \
        "trebuchet:TREBUCHET:SOME GET TREBUCHET'D" \
        "best:BEST FRIEND:BY THEIR BEST FRIEND." \
        "night:ONE NIGHT:ONE NIGHT." \
    --yaml
```

The tool outputs:
- A timing table showing each segment's start, duration, end, and which VO word it syncs to
- YAML stubs you can paste directly into your manifest

### 6. Verify with the timeline diagnostic

Before assembling, verify cumulative math:

```python
segs = [
    ("black",             0.20),
    ("EVERY CIVILIZATION", 3.10),
    ("veo_01 flash",       0.80),  # ends at 4.10 ← "wonders" hits here
    ("SOME BUILD WONDERS", 1.30),  # ends at 5.40 ← "trebuchet" hits here
    # ...
]
t = 0
for label, dur in segs:
    print(f"  {t:.2f}s  {label}")
    t += dur
```

Compare each `t` against your Whisper timestamps. Mismatches > 0.1s will be audible.

### 7. Assemble

```bash
python3 trailer_forge.py assemble your_project.yaml
```

---

## Segment Design Patterns

### Pattern 1: Card-on-word (most common)
The card appears exactly when that word is spoken.
```
[veo clip running] → [card cuts in at spoken word] → [veo clip continues]
```
Duration of preceding segment(s) = word timestamp.

### Pattern 2: Video with spoken VO (no card)
Let a video clip play while the VO delivers a sentence. More cinematic for action/establishing beats.
```yaml
# VO: "Build your economy. Raise your army. Destroy everything they love."
# plays OVER this footage with no title cards — maximally cinematic
- type: veo_clip
  file: assets/medieval_siege.mp4
  trim: [0, 3.78]  # exactly covers the battle cry VO section
```

### Pattern 3: Percussive single-word cards
For ONE. / MORE. / GAME. style beats — each card duration = gap between spoken words.
```
"one" at 21.20s, "more" at 21.92s → "ONE." card duration = 21.92 - 21.20 = 0.72s
"more" at 21.92s, "game" at 22.72s → "MORE." card duration = 22.72 - 21.92 = 0.80s
```

### Pattern 4: Impact flash cut (video)
A short veo clip used as a punctuation cut between text cards.
```yaml
- type: veo_clip
  file: assets/keyboard_flash.mp4
  trim: [0, 0.62]   # 0.62s flash — just before the percussive ONE/MORE/GAME cards
  fade_in: 0.08
  fade_out: 0.08
```
Gives visual variety without disrupting the text rhythm.

### Pattern 5: Title reveal with dramatic beat
For the main title, let the spoken word land on black first, then reveal the card.
```
23.58s "gathering" spoken → 0.5s black beat → 24.08s THE GATHERING title card
```
The brief black after the VO word gives the title card **weight**.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using segment-level Whisper output | Always pass `--word_timestamps True` |
| Forgetting to count preceding segments | Verify cumulative sum with the diagnostic script |
| Fades eating into short clips | For clips < 0.5s, use `fade_in: 0.08, fade_out: 0.08` or 0 |
| Title card too long → pushes all following cards late | Recalculate forward from that point |
| Black segments not counted | Every black segment counts toward the cumulative sum |

---

## Quick Reference: sync_yaml.py

```bash
# Print all words
python3 tools/sync_yaml.py whisper.json

# Compute durations + print YAML stubs
python3 tools/sync_yaml.py whisper.json \
    --offset 0.2 \
    --cues "WORD:Label:Card text" "WORD2:Label2:Card text 2" \
    --yaml
```

Arguments:
- `whisper_json` — path to Whisper JSON with `word_timestamps=True`
- `--offset` — leading time before the first cue segment (e.g. `0.2` for a black intro)
- `--cues` — `WORD:Label:Text` triplets; tool finds first matching word in transcript
- `--yaml` — output YAML title_card stubs

---

## Real-World Example: THE GATHERING

Source: Age of Empires II LAN party trailer. Voiceover: 26.70s, 8 hard sync points.

```bash
python3 tools/sync_yaml.py whisper_out/voiceover.json
```

Key timestamps extracted:
```
 4.100s  wonders       → SOME BUILD WONDERS.
 5.400s  trebuchet     → SOME GET TREBUCHET'D INTO OBLIVION.
 7.340s  best          → BY THEIR BEST FRIEND.
 7.940s  sitting       → SITTING THREE FEET AWAY.
11.460s  night         → ONE NIGHT. ONE LAN PARTY.
13.960s  legendary     → ONE LEGENDARY GAME.
21.200s  one           → ONE.
21.920s  more          → MORE.
22.720s  game          → GAME.
```

Result: every title card appears within ±0.01s of the spoken word. See `examples/the_gathering_v2.yaml`.
