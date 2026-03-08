# Shot Presets — Cinematic Vocabulary for Veo

Build better AI-generated video clips by using the exact language professional cinematographers use.

## Quick Start

Instead of vague prompts like "a shot of a man running," use structured cinematography vocabulary:

```yaml
- type: veo_clip
  preset: commercial_energy
  subject: "a runner in bright athletic gear sprinting along a track"
  file: clips/runner.mp4
```

This auto-generates a professional prompt:
> *"Medium Shot tracking alongside the runner in motion, smooth lateral tracking shot, eye level, bright high-key lighting, deep focus, energetic and frenetic commercial style, 60fps for slow motion"*

---

## Available Presets

### Thriller
| Preset | Use | Shot Type | Movement | Mood |
|--------|-----|-----------|----------|------|
| `thriller_reveal` | Object slowly revealed with dread | ECU | push_in | unsettling |
| `thriller_chase` | Subject pursued through space | MS | handheld | raw |
| `thriller_dread` | Character confronting something wrong | MS | dolly_zoom | unsettling |

**Example:**
```yaml
preset: thriller_dread
subject: "a woman's face as the hallway behind her stretches and warps"
```

### Commercial
| Preset | Use | Shot Type | Movement | Mood |
|--------|-----|-----------|----------|------|
| `commercial_energy` | Product/athlete in motion | MS | tracking | energetic |
| `commercial_product` | Clean product hero shot | ECU | arc | majestic |
| `commercial_lifestyle` | Person enjoying product naturally | MS | steadicam | intimate |

**Example:**
```yaml
preset: commercial_energy
subject: "a runner sprinting in bright athletic gear"
```

### Drama
| Preset | Use | Shot Type | Movement | Mood |
|--------|-----|-----------|----------|------|
| `drama_dialogue` | Two people in conversation | OTS | push_in | intimate |
| `drama_isolation` | Character alone, feeling small | ELS | pull_out | isolated |

**Example:**
```yaml
preset: drama_dialogue
subject: "a couple at a dining table, one teary-eyed"
```

### Comedy
| Preset | Use | Shot Type | Movement | Mood |
|--------|-----|-----------|----------|------|
| `comedy_reaction` | Character's comedic response | MS | static | comedic |

**Example:**
```yaml
preset: comedy_reaction
subject: "a man's face reacting in shock to the plunger in his hand"
```

### Epic/Establishing
| Preset | Use | Shot Type | Movement | Mood |
|--------|-----|-----------|----------|------|
| `epic_establish` | Grand establishing shot | ELS | crane | majestic |

**Example:**
```yaml
preset: epic_establish
subject: "a sprawling cityscape at golden hour"
```

---

## Advanced: Custom Shot Composition

If presets don't fit, compose your own:

```yaml
- type: veo_clip
  shot:
    type: CU              # Close-Up
    movement: push_in     # slow dolly
    angle: low            # looking up
    lighting: side        # harsh shadows
    mood: tense           # suspenseful
    fps: 24               # cinematic
  subject: "a hand turning a door handle in slow motion"
  file: clips/custom.mp4
```

This generates:
> *"Close-Up, slow dolly push-in, low angle looking up imparting power, harsh high-contrast side lighting, shallow focus, tense and suspenseful mood, 24fps film grain, cinematic"*

---

## Vocabulary Reference

### Shot Sizes
- **ECU** — Extreme Close-Up, minute detail (eye, mouth, object)
- **CU** — Close-Up, subject's face filling screen
- **MS** — Medium Shot, subject from waist up
- **Cowboy** — American shot, mid-thigh up (classic Western framing)
- **FS** — Full Shot, head to toe
- **LS** — Long Shot, subject small in environment
- **ELS** — Extreme Long Shot, epic establishing scale
- **OTS** — Over-the-Shoulder, looking past one person at another
- **POV** — Point-of-View, first-person perspective
- **Two** — Two Shot, both subjects in frame

### Camera Movements
- **Static** — Motionless, tripod-mounted
- **Push In** — Dolly forward, building tension/intimacy
- **Pull Out** — Dolly backward, revealing isolation/scope
- **Tracking** — Lateral movement following subject
- **Whip Pan** — Fast pan with motion blur, frenetic energy
- **Arc** — Semi-circular motion around subject
- **Dolly Zoom** — Camera moves while lens zooms opposite direction (Vertigo effect)
- **Handheld** — Unstabilized, documentary realism
- **Crane/Boom** — Vertical sweep from mechanical arm
- **Steadicam** — Smooth gliding motion

### Angles
- **Eye Level** — Most naturalistic, neutral perspective
- **Low Angle** — Looking up, imparts power/dominance
- **High Angle** — Looking down, subject feels vulnerable
- **Dutch** — Camera canted/tilted, psychological tension
- **Overhead** — Bird's-eye view, looking straight down

### Lighting
- **High Key** — Bright, even, minimal shadows (commercials)
- **Side/Rembrandt** — Harsh side light, high contrast (drama, thriller)
- **Warm Bounce** — Soft, warm light (intimate, cozy)
- **Cold Blue** — Clinical or ominous tone
- **Motivated** — Realistic light source (window, lamp)

### Mood
- **Tense** — Suspenseful, foreboding
- **Unsettling** — Disorienting, psychologically uneasy
- **Intimate** — Emotionally vulnerable, personal
- **Isolated** — Lonely, contemplative
- **Energetic** — High-velocity, frenetic
- **Majestic** — Epic, grand in scale
- **Raw** — Chaotic, documentary realism
- **Melancholic** — Quiet, bittersweet
- **Comedic** — Light, warm, approachable

### Frame Rates
- **24fps** — Standard cinematic motion
- **60fps** — Smooth slow motion (60fps shot in 24fps timeline = 2.5x slow)
- **120fps** — Extreme slow motion (120fps shot in 24fps = 5x slow)

---

## Tips for Better Results

1. **Be specific about the subject.** Generic "a person walking" → Specific "a woman in a red coat walking through falling snow"
2. **Match preset to story beat.** Action sequence = `commercial_energy`. Tense confrontation = `thriller_dread`.
3. **Layer multiple descriptors.** Preset handles cinematography; subject description adds narrative detail.
4. **Use lighting for mood.** `side` lighting screams thriller. `warm` lighting says drama or intimate moment.
5. **Test and iterate.** Veo results vary. If a preset doesn't land, tweak the subject or compose a custom shot.

---

## Research Source
Presets informed by professional cinematography practice documented in:
- StudioBinder film production guides
- MasterClass cinematography articles
- No Film School camera technique glossary
- Rocket Jump Filmmaking education videos
