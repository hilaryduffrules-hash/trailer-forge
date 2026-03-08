# Production Pipeline Reference
> Synthesized from professional film production research (NotebookLM, 50+ sources)
> For commercials and short films

## The 5 Stages

```
DEVELOPMENT → PRE-PRODUCTION → PRODUCTION → POST-PRODUCTION → DELIVERY
     ↓               ↓              ↓               ↓              ↓
  AV Script      Shot List       RAW Files       EDL/XML        DCP/H264
  Pitch Deck     Storyboard      .braw + .wav    ProRes 4444    M&E Tracks
  Budget         Call Sheet      Set Reports     Audio Stems    SRT/Subtitles
```

---

## Stage 1: Development

**What gets made:** Script, pitch deck, rough budget

**For commercials:** Use AV Script format (two columns: VISUAL | AUDIO/VO)
**For short films:** Standard screenplay format

**trailer-forge can help with:**
- AV Script → shot list generation (coming Phase 2)
- Script text → ElevenLabs voiceover segments

---

## Stage 2: Pre-Production

**What gets made and in what order:**

### 1. Locked Script
Standardized sluglines, consistent character names, locked scene numbers.
*Why it matters:* One typo creates duplicate budget line items and scheduling errors.

### 2. Script Breakdown
Scene-by-scene audit tagging: Cast, Extras, Props, Set Dressing, Stunts, VFX, Sound.
*Format:* Breakdown sheet per scene.

### 3. Stripboard / Shooting Schedule
Scenes grouped by: location, cast availability, equipment, light conditions.
*Format:* Stripboard (horizontal strips per scene, grouped by day).
*Key metric:* Page eighths (⅛ page = standard scene length unit for scheduling).

### 4. Shot List
The DP's bible for every camera setup. Columns:
| # | Scene | Description | Shot Type | Angle | Movement | Lens | FPS | Equipment | VFX | Prep | Shoot |
|---|-------|-------------|-----------|-------|----------|------|-----|-----------|-----|------|-------|

**trailer-forge shot types:** ECU, CU, MS, Cowboy, FS, LS, ELS, OTS, POV, Two
**trailer-forge movements:** static, push_in, pull_out, tracking, whip_pan, arc, dolly_zoom, handheld, crane

### 5. Storyboard
Visual panels for each shot. Rough sketches + reference images + camera notes.
*Feeds into:* Shot list and physical framing on set.

### 6. Call Sheet (daily, 24h before shoot)
- Who: Cast + crew with roles
- Where: Location with maps + parking
- When: General call time + individual call times
- What: Scenes shooting, equipment, weather, catering, contacts

### 7. Day Out of Days (DOOD)
Grid showing which actors/equipment appear on which shooting days.
*Used for:* Finalizing talent contracts, equipment rental periods.

---

## Stage 3: Production (Principal Photography)

**The on-set sequence (per take):**
```
1st AD: "Quiet on set"
1st AD: "Roll sound"
Sound Mixer: "Speed" (recording)
1st AD: "Roll camera"  
Camera Op: "Camera set" or "Speed"
Director: "Action"
[performance]
Director: "Cut"
1st AD: marks shot as PRINTED / NG / HOLD
```

**File outputs:**
- RAW camera files (`.braw`, `.r3d`, `.arw`)
- Multi-channel production audio (`.wav`, 24-bit 48kHz)
- Slate/clapperboard metadata for sync

---

## Stage 4: Post-Production

### 4A: Ingest (The Bottleneck)
Assistant editor manually wrangles → **biggest indie pain point**

Automated pipeline:
1. Sync audio to video using slate timecode cues
2. Generate proxy files (ProRes LT 1080p → cache folder)
3. Wrangle file names, add metadata
4. Link proxies back to RAW originals

### 4B: Editorial
```
Assembly Cut → Rough Cut → Fine Cut → PICTURE LOCK
```
- Assembly: Chronological, all selects, no pacing
- Rough: Core rhythm and structure established  
- Fine: Frame-by-frame timing decisions
- **PICTURE LOCK**: Director approves. Nothing changes after this. VFX and audio need locked timing.

### 4C: Handoff Files
- **EDL** (Edit Decision List): Lists every cut with timecodes
- **XML**: Richer metadata, used by DaVinci Resolve
- **AAF/OMF**: Audio-specific handoff to Pro Tools / Fairlight

### 4D: Sound Post (in order)
1. **Dialogue/ADR**: Re-record unusable on-set lines in studio, sync to picture
2. **Sound Spotting Session**: Director + composer + sound supervisor watch picture lock together, "spot" where music/SFX go
3. **Sound Design**: Layer SFX, add Foley substitutes
4. **Foley Recording**: Artists physically recreate sounds (footsteps, object handling, impacts)
5. **Score/Music**: Composer delivers stems or music supervisor licenses tracks
6. **Sound Mix**: Final volume balancing, EQ, noise reduction
7. **Audio Stems Export**: Dialogue, Foley, SFX, Music, Ambience — separate exports

**The Foley principle → trailer-forge automation:**
> Pitch-shift the same sound effect by ±1-3 semitones each time it fires.
> Identical swooshes sound artificial; slightly varied ones sound real.

### 4E: Color Pipeline
1. Colorist imports XML, **relinks proxies to original RAW** (matching file names)
2. Apply **conversion LUT** (e.g., Rec.709) — exposure baseline
3. Apply **creative LUT** — mood and tone
4. Shot-by-shot color correction to match cameras
5. Export color-graded master

**File formats:**
- LUTs: `.cube` format
- Grade output: ProRes 4444 or RAW + LUT baked

---

## Stage 5: Distribution & Delivery

| Format | Use | Spec |
|--------|-----|------|
| **ProRes 4444** | Archival master | Lossless-equivalent |
| **H.264/H.265 1080p** | Web/streaming | 8-20 Mbps |
| **DCP** | Theatrical projection | Encoded package |
| **M&E Tracks** | International dubbing | Music + Effects only, no dialogue |
| **Dialogue Script** | Subtitling | Transcript with exact timecodes |
| **SRT** | Closed captions | `.srt` format with timecodes |

**Social format crops:**
- YouTube: 1920×1080 (16:9)
- Instagram Feed: 1080×1080 (1:1)
- Instagram Reels/TikTok: 1080×1920 (9:16)
- Telegram: 1280×720, <15MB

---

## Key Roles & Their Documents

| Role | Owns | Handoff |
|------|------|---------|
| **Director** | Creative vision, picture lock | Shot list, approved fine cut |
| **DP** | Cinematography, lighting | Shot list (camera specs), LUT package |
| **1st AD** | Schedule, set operations | Call sheet, DOOD report |
| **Production Designer** | Sets, props | Prop lists, set designs |
| **Gaffer** | Lighting tech | Works from DP's shot list |
| **Editor** | Cut, pacing | EDL/XML (picture lock handoff) |
| **Colorist** | Color grade | LUT-applied master file |
| **Sound Designer** | SFX, Foley | Cue sheets → audio stems |
| **Sound Mixer** | Final mix | Mixed audio stems |

---

## Where AI Agents Make the Biggest Difference

**#1 — Ingest automation** (save 4-8 hours per shoot day)
Auto-sync audio, generate proxies, wrangle metadata

**#2 — Sound design** (save $500-$2000, fill the "empty audio" problem)
Auto-layer ambience, pitch-shifted SFX, transition sounds

**#3 — Multi-format delivery** (save 2-4 hours per project)
One master → all platform specs automatically

**#4 — Shot list → Veo prompts** (make AI clips intentional, not random)
Cinematography vocabulary → structured AI generation prompts

**#5 — Subtitle/SRT pipeline** (accessibility + international)
Whisper → timecoded SRT in seconds vs. hours of manual work

---

*Sources: NotebookLM notebook fc2b5a7b (50+ sources including AICP guidelines, Frame.io workflow, DaVinci Resolve manual, Raindance distribution guide, StudioBinder, No Film School, MasterClass)*
