# Trailer & Commercial Style Guide

Five battle-tested style templates with different ratios of video, text, and silence.
The current default (text-heavy percussive) is one tool. These are the others.

---

## The Problem with Text-Heavy Trailers

The first instinct is: match every spoken word with a title card. It's safe. It's explicit.
It's also what every amateur YouTube gaming trailer does.

Real trailers — the ones people share — use text *surgically*. Often just a title at the end.
The footage does the heavy lifting. Music carries the emotion. Text arrives like a punch.

**The ratio that separates amateur from pro:**
- Amateur: 70% text cards, 30% video
- Professional: 20% text (at most), 80% video
- Apple/Nike/A24: 5% text, 95% video + silence

---

## Style 1 — APPLE (Minimal / Product Poetry)

**Signature examples:** Shot on iPhone campaigns, Mac Pro "Unleashed", AirPods Max reveal

### Philosophy
One idea. Perfect execution. No clutter. The product speaks. Music does the feeling.
Text appears exactly once — the product name, the tagline. White, clean, full stop.

### Structure (60s commercial / 35s teaser)
```
0:00-0:05   BLACK + single musical note / ambient tone
0:05-0:25   BEAUTY SHOTS — slow, deliberate. 3-5 cuts maximum.
             Each shot holds for 4-7 seconds. Let it breathe.
0:25-0:32   ONE REVEAL SHOT — the hero moment. Hold it.
0:32-0:35   BLACK + PRODUCT NAME in white. Nothing else.
             (For 35s: compress accordingly)
```

### Editing Rules
- Minimum 3 seconds per shot (longer is better)
- Hard cuts, not dissolves — deliberate, clean transitions
- Music: single instrument or ambient tone builds slowly. Never a drop.
- NO voiceover. If you must: one sentence, barely above a whisper.
- NO text except: product name + tagline at the END only
- Color grade: clean, neutral, slightly warm or cool depending on product

### YAML Segment Pattern
```yaml
# Apple style — 35s teaser
timeline:
  - type: black
    duration: 1.5

  - type: veo_clip        # Beauty shot 1 — establish world
    file: clips/beauty_01.mp4
    trim: [0, 5.0]
    fade_in: 0.5
    fade_out: 0.0         # Hard cut out

  - type: veo_clip        # Beauty shot 2 — product in context
    file: clips/beauty_02.mp4
    trim: [0, 6.0]
    fade_in: 0.0
    fade_out: 0.0

  - type: veo_clip        # Hero reveal
    file: clips/hero_shot.mp4
    trim: [0, 7.0]
    fade_in: 0.0
    fade_out: 0.8

  - type: black
    duration: 1.2

  - type: title_card      # THE ONLY TEXT IN THE WHOLE THING
    duration: 4.0
    lines:
      - text: "PRODUCT NAME"
        font: bebas
        size: 72
        color: "#ffffff"
      - text: "tagline goes here."
        font: bebas
        size: 36
        color: "#888888"

  - type: black
    duration: 2.0
```

### Music Direction
- Key: minor or neutral — never triumphant
- Tempo: slow enough that individual notes are felt (< 80 BPM)
- Arc: starts nearly silent, rises through the piece, resolves clean
- Examples: Olafur Arnalds, Nils Frahm, Hans Zimmer minimal piano

---

## Style 2 — NIKE (Athletic / Visceral)

**Signature examples:** "Find Your Greatness", "You Can't Stop Us" split-screen, "Dream Crazy"

### Philosophy
Struggle is beautiful. The body is the proof. No product shots (sometimes none at all).
Emotion through face, breath, sweat, failure, triumph. The tagline is the last frame.

### Structure
```
0:00-0:03   AMBIENT COLD OPEN — sound before picture. Crowd noise. Rain. Breath.
0:03-0:15   MONTAGE ACT 1 (struggle) — tight faces, effort, failure. Fast cuts 0.5-1s each.
             Ambient sound: feet, impact, breath MIXED with music.
0:15-0:25   MONTAGE ACT 2 (rising) — pace builds. Cuts get faster. Music surges.
0:25-0:30   CLIMAX — one sustained shot of triumph. Hold 3-5 seconds.
0:30-0:33   BLACK
0:33-0:35   TAGLINE — minimal, powerful. No explanation.
```

### Editing Rules
- Mix diegetic sound (real athlete sounds) with music — don't silence the world
- Varied cut rhythm: establish with long hold → break into rapid-fire → hold the peak
- Faces over action: reaction shots carry more weight than the action itself
- Text: max 2-3 words, appears 1-2 times total. Never explanatory.
- Never subtitle the voiceover — if VO is used, let it breathe alone, no matching cards

### YAML Segment Pattern
```yaml
# Nike style — visceral athletic montage
timeline:
  - type: black
    duration: 0.3          # cold open on sound alone

  - type: veo_clip         # tight face, effort
    file: clips/face_01.mp4
    trim: [0, 1.2]
    fade_in: 0.0
    fade_out: 0.0

  - type: veo_clip         # action — hands, feet
    file: clips/action_01.mp4
    trim: [0, 0.8]
    fade_in: 0.0
    fade_out: 0.0

  # ... rapid fire 0.5-1.5s clips (8-12 total) ...

  - type: veo_clip         # HOLD — climax shot (5s minimum)
    file: clips/triumph.mp4
    trim: [0, 5.0]
    fade_in: 0.0
    fade_out: 0.8

  - type: black
    duration: 0.5

  - type: title_card       # THE ONLY TEXT
    duration: 3.0
    lines:
      - text: "JUST DO IT."
        font: bebas
        size: 110
        color: "#ffffff"

  - type: black
    duration: 1.5
```

### Music Direction
- Starts as texture (not melody) — gradually becomes identifiable
- Key transition: music becomes undeniable exactly when the climax shot hits
- Often a cover or remix of a recognizable song (unexpected genre switch works)
- The music DROP lands on the triumph moment, not a text card

---

## Style 3 — A24 (Arthouse / Slow Burn)

**Signature examples:** Midsommar, Hereditary, Everything Everywhere, Past Lives trailers

### Philosophy
Atmosphere over plot. Mystery over explanation. The audience should feel *unsettled*
before they understand why. Never show the full monster. Never explain the twist.
Let silence do work. Let wrong-feeling music do work.

### Structure
```
0:00-0:08   ATMOSPHERIC COLD OPEN — long hold. Ambient sound or eerie music.
             One slowly moving shot. Something slightly wrong about it.
0:08-0:18   SLOW REVEAL SEQUENCE — 3-4 shots, each 3-4s, building unease.
             Cut on silence, not on music beat. That's the A24 move.
0:18-0:28   CONTRAST MOMENT — one thing that feels "normal" then a cut
             to something deeply not normal. No explanation.
0:28-0:32   SILENCE — pure black. Audience held.
0:32-0:35   TITLE — just the film name. Simple. Maybe just white text.
             Sometimes a single sound sting. Then silence again.
```

### Editing Rules
- Cut on SILENCE, not on the beat — the jarring disconnect is the point
- Music: often beautiful music during disturbing imagery (or vice versa)
- Hold shots longer than comfortable — the discomfort is intentional
- NEVER use voiceover in A24 style
- Text: film title only, at the very end. Sometimes production company.
- Color: high contrast, often desaturated or pushed into specific palette
- Sound design: the sound matters MORE than in any other style

### YAML Segment Pattern
```yaml
# A24 style — atmospheric, minimal
film_grain: true          # always on
color_grade: teal_orange  # or cold_blue, desaturated

timeline:
  - type: black
    duration: 2.0          # hold the black. make them wait.

  - type: veo_clip         # atmospheric opening — something beautiful but wrong
    file: clips/atmosphere_01.mp4
    trim: [0, 6.0]
    fade_in: 1.2           # slow in
    fade_out: 0.0          # hard cut — unsettling

  - type: black
    duration: 0.8          # breath of silence between shots

  - type: veo_clip         # slow reveal
    file: clips/reveal_01.mp4
    trim: [0, 5.0]
    fade_in: 0.0
    fade_out: 0.0

  - type: veo_clip         # the wrong thing
    file: clips/wrong_thing.mp4
    trim: [0, 3.0]
    fade_in: 0.0
    fade_out: 0.0

  - type: black
    duration: 3.0          # the long silence before title

  - type: title_card
    duration: 5.0
    lines:
      - text: "FILM TITLE"
        font: bebas
        size: 84
        color: "#e8e8e8"   # not quite white — slightly aged

  - type: black
    duration: 3.0
```

### Music Direction
- Often a single instrument building — cello, piano, a voice
- The emotional register of the music should be *wrong* for what's on screen
- Beautiful music over horror. Dread under a sunny picnic. That's the move.
- Silence is a tool. Use it more than you're comfortable with.

---

## Style 4 — BLOCKBUSTER (Three-Act Reveal)

**Signature examples:** Marvel, Mission Impossible, any franchise summer film

### Philosophy
World → stakes → chaos → title. The audience needs to know: who, what's at stake,
what the spectacle looks like, and why they should care. Every 10 seconds is an act.

### Structure
```
0:00-0:08   ACT 1 — WORLD & CHARACTER. 2-3 medium shots. Calm music.
             One line of exposition VO or dialogue. "Establish normalcy."
0:08-0:18   ACT 2 — STAKES. The threat or twist revealed. Music shifts.
             Quick cuts. 2-3 text cards ("The fate of X is...").
0:18-0:28   ACT 3 — SPECTACLE. Rapid fire action/VFX/money shots.
             Music surges, big percussion, SFX mixed in. 0.5-1s cuts.
0:28-0:32   TITLE STING — big logo/title reveal. Music peak. Often a
             single orchestral hit, then silence.
0:32-0:35   TAG — small moment (comedy, mystery, or character beat).
             Softer music. Audiences expect this.
```

### Editing Rules
- Three-act emotional arc is non-negotiable — world → threat → climax
- Cut rhythm accelerates act by act (3s cuts → 1s cuts → 0.5s cuts)
- Music: starts orchestral/atmospheric, transitions to a kinetic track
- Text cards: only to establish setting/stakes, not to narrate everything
- The TAG (post-title moment) always lands a laugh, hint, or scare

### YAML Segment Pattern
```yaml
# Blockbuster style
timeline:
  - type: black
    duration: 0.5

  # ACT 1: World (calm, ~8s)
  - type: veo_clip
    file: clips/establishing.mp4
    trim: [0, 4.0]
    fade_in: 0.8

  - type: veo_clip
    file: clips/character.mp4
    trim: [0, 3.5]

  - type: title_card       # ONE setup card maximum
    duration: 1.5
    lines:
      - text: "WHAT THEY THOUGHT WAS SAFE..."
        font: bebas
        size: 60
        color: "#e8d5a3"

  # ACT 2: Stakes (~10s)
  - type: veo_clip
    file: clips/threat.mp4
    trim: [0, 3.0]

  - type: title_card
    duration: 1.2
    lines:
      - text: "CHANGED EVERYTHING."
        font: bebas
        size: 80
        color: "#ffffff"

  - type: veo_clip
    file: clips/reaction.mp4
    trim: [0, 2.0]

  # ACT 3: Spectacle rapid fire (~10s)
  - type: veo_clip
    file: clips/action_01.mp4
    trim: [0, 1.0]
  - type: veo_clip
    file: clips/action_02.mp4
    trim: [0, 0.8]
  - type: veo_clip
    file: clips/action_03.mp4
    trim: [0, 1.2]
  - type: veo_clip
    file: clips/money_shot.mp4
    trim: [0, 2.0]
    fade_out: 0.5

  - type: black
    duration: 0.3

  # TITLE STING
  - type: title_card
    duration: 3.5
    lines:
      - text: "T H E"
        font: bebas
        size: 54
        color: "#c4a96b"
      - text: "FILM TITLE"
        font: bebas
        size: 132
        color: "#ffffff"

  - type: black
    duration: 0.8

  # POST-TITLE TAG
  - type: veo_clip
    file: clips/tag_moment.mp4
    trim: [0, 2.5]
    fade_in: 0.3
    fade_out: 0.5

  - type: black
    duration: 1.5
```

---

## Style 5 — TEXT-HEAVY PERCUSSIVE (Current Default)

**Signature examples:** Game trailers, THE GATHERING v2, THE PLUNGE v12

This is the style we've been building. It works well for:
- Comedy — the text IS the joke
- Gaming — the audience expects rapid text cards
- When the script punchlines are the payoff
- Short-form content where you need to communicate quickly

**When NOT to use it:** emotional stories, products, anything requiring atmosphere.

---

## Hybrid Patterns

Real trailers mix styles. Some patterns that work:

### The Cold Open Pivot
Start A24 (atmospheric, slow, minimal) → pivot to Blockbuster (fast, action) → end Blockbuster.
Creates whiplash surprise. Audience expects something small, gets something big.

### The Nike Music Lock
Structure text-heavy like current style BUT: the music drop lands on a VIDEO CLIP, not a card.
The beat triggers a 3-5 second beauty shot. Text cards before and after, not during.

### The Apple Button
Run ANY style. At the very end: cut to black. ONE TEXT LINE only. Hold 3 seconds.
The Apple button can make any trailer feel more premium.

---

## Quick Decision Table

| Content Type | Best Style | Text Volume | Music Role |
|---|---|---|---|
| Product reveal | Apple | 1 card max | Everything |
| Athletic/motivational | Nike | 2-3 words | Emotional arc |
| Atmospheric/horror | A24 | Title only | Subversive |
| Action/franchise | Blockbuster | 3-5 cards | Building arc |
| Comedy/gaming | Text-Percussive | Many | Punctuation |
| Personal story | Nike or A24 | Minimal | Emotional |

---

## Veo Prompt Strategy by Style

### Apple prompts
- "cinematic beauty shot of [SUBJECT], clean white background, soft diffused light, shallow depth of field, minimal, 4K product photography aesthetic"
- "slow push-in on [SUBJECT], Kubrick-style symmetrical framing, cool neutral tones"

### Nike prompts
- "tight close-up of athlete's [face/hands/feet] showing strain and effort, harsh directional light, gritty realism, handheld camera, shallow DOF"
- "slow motion [action shot], natural light, high contrast, raw energy"

### A24 prompts
- "[Beautiful/peaceful scene] with one subtly wrong element, atmospheric, slightly desaturated, long lens compression, dread in stillness"
- "cinematic wide shot of [location], empty, beautiful, something feels off, film grain, golden hour or twilight"

### Blockbuster prompts
- "epic establishing aerial shot of [location], sweeping drone pullback, golden light, cinematic scale"
- "dramatic low angle of [subject/character], looking up, strong backlight, heroic framing"
