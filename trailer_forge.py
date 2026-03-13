#!/usr/bin/env python3
"""
trailer-forge — Build cinematic video trailers from a YAML manifest.

Usage:
  python3 trailer_forge.py preview   trailer.yaml               # print timeline
  python3 trailer_forge.py assemble  trailer.yaml               # assemble only
  python3 trailer_forge.py build     trailer.yaml               # assemble + Veo
  python3 trailer_forge.py gen-clips trailer.yaml               # Veo clips only
  python3 trailer_forge.py deliver   out/video.mp4 --targets youtube telegram
  python3 trailer_forge.py export-srt whisper.json --output subs.srt
  python3 trailer_forge.py quick --product "BTC Cards" --style direct-response --format 9x16

Requirements:
  pip install pillow pyyaml requests google-genai
  cd canvas_renderer && npm install   (Node.js renderer — better text quality)
  ffmpeg in PATH

Optional:
  GEMINI_API_KEY  → Veo 3.1 clip generation + ElevenLabs for quick mode
"""

import os, sys, json, time, shutil, random, tempfile, subprocess, argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "-q"])
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    import requests
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()

def _find_font(*candidates):
    for p in candidates:
        if Path(p).exists():
            return str(p)
    return None

FONT_BEBAS = _find_font(
    SCRIPT_DIR / "fonts" / "BebasNeue.ttf",
    "/usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf",
    "/usr/local/share/fonts/BebasNeue.ttf",
)
FONT_SANS = _find_font(
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Windows/Fonts/arialbd.ttf",
)
FONT_SERIF = _find_font(
    SCRIPT_DIR / "fonts" / "CormorantGaramond-Light.ttf",
    "/usr/share/fonts/truetype/cormorant/CormorantGaramond-Light.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
)
CANVAS_RENDERER = SCRIPT_DIR / "canvas_renderer" / "render_card.js"

# ── Constants ─────────────────────────────────────────────────────────────────
VEO_BASE  = "https://generativelanguage.googleapis.com/v1beta"
VEO_MODEL = "veo-3.1-fast-generate-preview"   # upgraded from veo-2.0 (Phase 2)
VEO_MODEL_FALLBACK = "veo-2.0-generate-001"   # fallback if 3.1 unavailable

# ── Multi-format output presets (Phase 2) ─────────────────────────────────────
FORMAT_PRESETS = {
    "16x9": {"w": 1920, "h": 1080, "aspect_ratio": "16:9",
             "label": "16:9 (YouTube/Desktop)"},
    "9x16": {"w": 1080, "h": 1920, "aspect_ratio": "9:16",
             "label": "9:16 (TikTok/Reels/Stories)",
             "crop": True},
    "1x1":  {"w": 1080, "h": 1080, "aspect_ratio": "1:1",
             "label": "1:1 (Instagram Feed/LinkedIn)",
             "crop": True},
    "4x5":  {"w": 1080, "h": 1350, "aspect_ratio": "4:5",
             "label": "4:5 (Facebook/Instagram Feed)",
             "crop": True},
}

COLOR_GRADES = {
    "none":          "",
    "teal_orange":   "colorchannelmixer=rr=1.1:rb=-0.05:gr=0:gb=0.05:br=-0.08:bb=1.12,eq=saturation=1.3:contrast=1.05",
    "dark_thriller": "curves=r='0/0 0.5/0.45 1/0.9':g='0/0 0.5/0.48 1/0.92':b='0/0 0.5/0.55 1/1',eq=saturation=1.15:brightness=-0.04",
    "vintage":       "curves=r='0/0.05 1/0.95':g='0/0.03 1/0.88':b='0/0.02 1/0.75',eq=saturation=0.85",
}

COLOURS = {
    "white":  (255, 255, 255),
    "black":  (0,   0,   0),
    "gold":   (212, 175, 55),
    "goldhi": (245, 224, 128),
    "grey":   (160, 160, 170),
    "darkbg": (7,   7,   16),
    "red":    (200, 30,  30),
}

# ── Utilities ─────────────────────────────────────────────────────────────────
def log(msg):  print(f"  {msg}",    flush=True)
def warn(msg): print(f"  ⚠  {msg}", flush=True)
def ok(msg):   print(f"  ✅ {msg}",  flush=True)

def run(cmd, check=True):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"FFMPEG ERROR:\n{r.stderr[-2000:]}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {cmd[:80]}")
    return r

def dur_str(sec):
    return f"{int(sec//60):02d}:{sec%60:05.2f}"

# ── Shot Preset Library ────────────────────────────────────────────────────────
_SHOTS_CACHE = None

def load_shots():
    """Load shots.yaml from the same directory as this script."""
    global _SHOTS_CACHE
    if _SHOTS_CACHE is not None:
        return _SHOTS_CACHE
    shots_path = SCRIPT_DIR / "shots.yaml"
    if not shots_path.exists():
        _SHOTS_CACHE = {}
        return _SHOTS_CACHE
    with open(shots_path) as f:
        _SHOTS_CACHE = yaml.safe_load(f) or {}
    return _SHOTS_CACHE

def resolve_veo_prompt(item):
    """
    Build a Veo prompt from a veo_clip segment.
    Priority:
      1. Explicit 'prompt:' field → use as-is
      2. Named 'preset:' → look up in shots.yaml, interpolate {subject}
      3. 'shot:' dict → build from vocabulary fields
      4. Fallback: generic cinematic description
    """
    if item.get("prompt"):
        return item["prompt"]

    subject = item.get("subject", "the scene")
    shots   = load_shots()

    # Named preset
    preset_name = item.get("preset")
    if preset_name:
        presets = shots.get("genre_presets", shots.get("presets", {}))
        preset  = presets.get(preset_name)
        if preset and preset.get("template"):
            prompt = preset["template"].replace("{subject}", subject)
            log(f"  Shot preset [{preset_name}]: {prompt[:80]}…")
            return prompt
        else:
            warn(f"Preset '{preset_name}' not found in shots.yaml — using generic")

    # Compose from shot dict
    shot = item.get("shot", {})
    if shot:
        shot_types = shots.get("shot_types", {})
        movements  = shots.get("movements",  {})
        angles     = shots.get("angles",     {})
        lighting   = shots.get("lighting",   {})
        moods      = shots.get("moods",      {})
        technical  = shots.get("technical",  {})

        parts = []
        if shot.get("type"):      parts.append(shot_types.get(shot["type"],  shot["type"]))
        if shot.get("movement"):  parts.append(movements.get(shot["movement"], shot["movement"]))
        if shot.get("angle"):     parts.append(angles.get(shot["angle"],      shot["angle"]))
        if subject != "the scene": parts.append(f"of {subject}")
        if shot.get("lighting"):  parts.append(lighting.get(shot["lighting"], shot["lighting"]))
        if shot.get("mood"):      parts.append(moods.get(shot["mood"],        shot["mood"]))
        fps = shot.get("fps", 24)
        parts.append(technical.get(f"cinematic_{fps}", f"{fps}fps cinematic"))

        prompt = ", ".join(parts)
        log(f"  Shot composed: {prompt[:80]}…")
        return prompt

    return f"Cinematic shot of {subject}, film grain, 24fps, professional cinematography"

# ── SFX Automation ────────────────────────────────────────────────────────────
_SFX_CACHE = None

def load_sfx_map():
    """Load sfx_map.yaml from the same directory as this script."""
    global _SFX_CACHE
    if _SFX_CACHE is not None:
        return _SFX_CACHE
    sfx_path = SCRIPT_DIR / "sfx_map.yaml"
    if not sfx_path.exists():
        _SFX_CACHE = {}
        return _SFX_CACHE
    with open(sfx_path) as f:
        _SFX_CACHE = yaml.safe_load(f) or {}
    return _SFX_CACHE

def generate_sfx_tone(sound_name, duration, pitch_shift=0, out_path=None):
    """
    Generate a fallback SFX tone using ffmpeg when no .wav file exists.
    Uses sine waves and noise at characteristic frequencies per sound type.
    Applies pitch_shift in semitones.
    Returns path to generated .wav file.
    """
    if out_path is None:
        out_path = Path(tempfile.mkdtemp()) / f"{sound_name}.wav"
    out_path = Path(out_path)

    # Pitch shift multiplier: 2^(semitones/12)
    pitch_mult = 2 ** (pitch_shift / 12.0) if pitch_shift != 0 else 1.0

    # Sound profiles — each generates something characteristic
    profiles = {
        "impact_boom":      {"freq": 80,   "type": "sine",  "fade": "out", "eq": "lowpass=f=200"},
        "deep_bass_hit":    {"freq": 60,   "type": "sine",  "fade": "out", "eq": "lowpass=f=180"},
        "swoosh_fast":      {"freq": 800,  "type": "noise", "fade": "both", "eq": "bandpass=f=800:width_type=o:w=2"},
        "tension_rise":     {"freq": 200,  "type": "sine",  "sweep": 800, "fade": "none"},
        "shimmer_riser":    {"freq": 1000, "type": "sine",  "sweep": 4000, "fade": "in"},
        "low_drone_swell":  {"freq": 55,   "type": "sine",  "fade": "both"},
        "ambient_chaos":    {"freq": 300,  "type": "noise", "fade": "both", "eq": "bandpass=f=600:width_type=o:w=3"},
        "room_tone":        {"freq": 200,  "type": "noise", "fade": "none", "vol": 0.05},
        "subtle_whoosh_in": {"freq": 400,  "type": "noise", "fade": "in",   "eq": "bandpass=f=600:width_type=o:w=2"},
        "low_exhale":       {"freq": 150,  "type": "noise", "fade": "out",  "eq": "lowpass=f=400"},
        "epic_swell":       {"freq": 90,   "type": "sine",  "sweep": 180, "fade": "both"},
        "vertigo_drone":    {"freq": 220,  "type": "sine",  "fade": "both", "eq": "bandpass=f=220:width_type=o:w=1"},
    }

    p = profiles.get(sound_name, {"freq": 440, "type": "sine", "fade": "both"})
    freq     = p.get("freq", 440)
    snd_type = p.get("type", "sine")
    sweep    = p.get("sweep", None)
    fade     = p.get("fade", "both")
    vol      = p.get("vol", 0.6)
    eq       = p.get("eq", "")

    dur = max(0.1, float(duration))

    # Build the audio source
    if snd_type == "noise":
        src = f"anoisesrc=duration={dur}:color=white"
    elif sweep:
        # Chirp / frequency sweep
        src = f"sine=frequency={freq}:beep_factor={sweep/freq}:duration={dur}"
    else:
        src = f"sine=frequency={freq}:duration={dur}"

    # Build filter chain
    filters = [f"volume={vol}"]
    if eq:
        filters.append(eq)
    if pitch_mult != 1.0:
        new_rate = int(44100 * pitch_mult)
        filters += [f"asetrate={new_rate}", "aresample=44100"]
    if fade == "in":
        filters.append(f"afade=t=in:d={min(0.1, dur/2)}")
    elif fade == "out":
        filters.append(f"afade=t=out:st={max(0,dur-0.15)}:d={min(0.15, dur/2)}")
    elif fade == "both":
        fade_d = min(0.1, dur/4)
        filters.append(f"afade=t=in:d={fade_d},afade=t=out:st={max(0,dur-fade_d)}:d={fade_d}")

    filter_str = ",".join(filters)
    cmd = (f'ffmpeg -y -f lavfi -i "{src}" '
           f'-af "{filter_str}" '
           f'-ar 44100 -ac 2 "{out_path}"')
    r = run(cmd, check=False)
    if r.returncode != 0:
        # Ultra-safe fallback: silent file
        run(f'ffmpeg -y -f lavfi -i "anullsrc=duration={dur}" -ar 44100 -ac 2 "{out_path}"', check=False)

    return out_path

def get_sfx(sound_name, duration, sfx_dir=None, pitch_shift=0):
    """
    Get an SFX file: check sfx/ folder first, else generate via ffmpeg.
    Applies Foley principle: slight pitch variation to avoid robotic repetition.
    """
    if not sound_name or sound_name == "silence":
        return None

    # Apply Foley pitch variation from sfx_map.yaml
    sfx_map = load_sfx_map()
    var_ranges = sfx_map.get("pitch_variation", {})
    if sound_name in var_ranges and pitch_shift == 0:
        lo, hi = var_ranges[sound_name]
        pitch_shift = random.uniform(lo, hi)

    # Check for real .wav file first
    if sfx_dir:
        for ext in [".wav", ".mp3", ".ogg"]:
            candidate = Path(sfx_dir) / f"{sound_name}{ext}"
            if candidate.exists():
                log(f"  SFX [{sound_name}] ← {candidate.name} (pitch={pitch_shift:+.1f}st)")
                if pitch_shift != 0:
                    tmp = Path(tempfile.mkdtemp()) / f"{sound_name}_pitched{ext}"
                    mult = 2 ** (pitch_shift / 12)
                    rate = int(44100 * mult)
                    run(f'ffmpeg -y -i "{candidate}" -af "asetrate={rate},aresample=44100" "{tmp}"', check=False)
                    return tmp
                return candidate

    # Generate synthetic fallback
    log(f"  SFX [{sound_name}] ← generated (pitch={pitch_shift:+.1f}st)")
    tmp = Path(tempfile.mkdtemp()) / f"{sound_name}.wav"
    return generate_sfx_tone(sound_name, duration, pitch_shift, tmp)

def build_sfx_mix(timeline, base_dir, total_dur, work_dir, grade="dark_thriller"):
    """
    Automated sound design: analyze timeline, generate SFX per transition/segment type,
    mix into a single ambient SFX track to layer under the final video.
    Returns path to SFX .wav file, or None if nothing to mix.
    """
    sfx_map   = load_sfx_map()
    sfx_dir   = base_dir / "sfx"
    trans_map = sfx_map.get("transitions", {})
    mov_map   = sfx_map.get("movements",   {})
    amb_map   = sfx_map.get("ambience",    {})

    sfx_events = []  # [(start_sec, wav_path, volume)]
    t = 0.0

    for i, item in enumerate(timeline):
        kind      = item.get("type", "black")
        trim      = item.get("trim", [0, 5])
        dur       = (float(trim[1]) - float(trim[0])) if kind == "veo_clip" else float(item.get("duration", 3.0))
        next_kind = timeline[i+1].get("type", "black") if i+1 < len(timeline) else None

        # Transition SFX at the cut point
        if kind == "black" and next_kind == "title_card":
            tspec = trans_map.get("black_to_reveal", {})
            snd   = tspec.get("sound", "shimmer_riser")
            vol   = tspec.get("volume", 0.5)
            sfx   = get_sfx(snd, 0.5, sfx_dir)
            if sfx: sfx_events.append((t, sfx, vol))

        elif kind == "title_card" and next_kind in ("veo_clip", "black"):
            tspec = trans_map.get("clip_to_card", {})
            snd   = tspec.get("sound", "low_drone_swell")
            vol   = tspec.get("volume", 0.35)
            sfx   = get_sfx(snd, min(dur, 1.0), sfx_dir)
            if sfx: sfx_events.append((t, sfx, vol))

        elif kind == "veo_clip" and next_kind == "title_card":
            tspec = trans_map.get("hard_cut_to_impact", {})
            snd   = tspec.get("sound", "deep_bass_hit")
            vol   = tspec.get("volume", 0.7)
            sfx   = get_sfx(snd, 0.6, sfx_dir)
            if sfx: sfx_events.append((t + dur - 0.05, sfx, vol))

        # Camera movement SFX for veo_clips
        if kind == "veo_clip":
            movement = item.get("shot", {}).get("movement") or item.get("movement")
            if not movement and item.get("preset"):
                shots    = load_shots()
                preset_d = shots.get("genre_presets", shots.get("presets", {})).get(item["preset"], {})
                movement = preset_d.get("movement")
            if movement and movement in mov_map:
                mspec = mov_map[movement]
                snd   = mspec.get("sound")
                vol   = mspec.get("volume", 0.4)
                if snd:
                    sfx = get_sfx(snd, min(dur * 0.4, 1.5), sfx_dir)
                    if sfx: sfx_events.append((t + dur * 0.1, sfx, vol))

            # Ambient bed under clips (fills "empty audio" problem)
            amb_key = grade if grade in amb_map else "none"
            if amb_key in amb_map:
                aspec = amb_map[amb_key]
                snd   = aspec.get("sound", "room_tone")
                vol   = aspec.get("volume", 0.10)
                sfx   = get_sfx(snd, dur, sfx_dir)
                if sfx: sfx_events.append((t, sfx, vol))

        t += dur

    if not sfx_events:
        return None

    # Render all SFX events onto a single timeline
    out_sfx = work_dir / "sfx_mix.wav"
    silence  = work_dir / "sfx_silence.wav"
    run(f'ffmpeg -y -f lavfi -i "anullsrc=duration={total_dur}" -ar 44100 -ac 2 "{silence}"', check=False)

    # Build a complex amix filter
    inputs  = [f'-i "{silence}"']
    filters = ["[0:a]anull[base]"]
    for idx, (start_sec, wav, vol) in enumerate(sfx_events):
        delay_ms = int(start_sec * 1000)
        n = idx + 1
        inputs.append(f'-i "{wav}"')
        filters.append(f"[{n}:a]volume={vol},adelay={delay_ms}|{delay_ms}[s{n}]")

    labels = "[base]" + "".join(f"[s{n}]" for n in range(1, len(sfx_events)+1))
    n_in   = len(sfx_events) + 1
    filters.append(f"{labels}amix=inputs={n_in}:duration=first:dropout_transition=2[out]")

    filter_chain = ";".join(filters)
    input_str    = " ".join(inputs)
    cmd = (f'ffmpeg -y {input_str} '
           f'-filter_complex "{filter_chain}" '
           f'-map "[out]" -t {total_dur} -ar 44100 "{out_sfx}"')
    r = run(cmd, check=False)
    if r.returncode == 0 and out_sfx.exists():
        ok(f"SFX mix: {len(sfx_events)} events → {out_sfx.name}")
        return out_sfx
    else:
        warn("SFX mix failed — proceeding without automated sound design")
        return None

# ── Font loading ───────────────────────────────────────────────────────────────
def load_font(family, size):
    if family == "bebas":
        path = FONT_BEBAS
    elif family in ("serif", "garamond", "cormorant"):
        path = FONT_SERIF
    else:
        path = FONT_SANS
    if path and Path(path).exists():
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

# ── Title card rendering (Pillow fallback) ─────────────────────────────────────
def _autofit_font(draw, txt, family, desired_size, max_w):
    size = desired_size
    while size > 20:
        font = load_font(family, size)
        bb   = draw.textbbox((0, 0), txt, font=font, anchor="lt")
        if (bb[2] - bb[0]) <= max_w:
            return font, size
        size = int(size * 0.93)
    return load_font(family, 20), 20

def _line_height(draw, txt, font):
    bb = draw.textbbox((0, 0), txt, font=font, anchor="lt")
    return bb[3] - bb[1]

def _text_glow(img, cx, cy, txt, font, fill, glow_color=(200, 160, 40), radius=18):
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    gd.text((cx, cy), txt, font=font, fill=(*glow_color, 200), anchor="mm")
    glow = glow.filter(ImageFilter.GaussianBlur(radius))
    base = Image.alpha_composite(img.convert("RGBA"), glow)
    td   = ImageDraw.Draw(base)
    td.text((cx + 2, cy + 3), txt, font=font, fill=(0, 0, 0), anchor="mm")
    td.text((cx, cy),         txt, font=font, fill=fill,       anchor="mm")
    return base.convert("RGB")

def _add_vignette(img, W, H, strength=140, power=1.8):
    vig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd  = ImageDraw.Draw(vig)
    r_max = min(W, H) // 2
    for r in range(r_max, 0, -8):
        alpha = int(strength * (1 - r / r_max) ** power)
        vd.ellipse([W//2-r, H//2-r, W//2+r, H//2+r], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB")

def render_title_card(config, W, H, out_png, font_scale=1.0):
    bar_h   = int(H * 0.1)
    safe_cy = (bar_h + H - bar_h) // 2
    max_w   = int(W * 0.84)
    gap     = 14
    img     = Image.new("RGB", (W, H), COLOURS["darkbg"])
    draw    = ImageDraw.Draw(img)
    lines   = config.get("lines", [])
    # Apply font scaling for non-16:9 formats
    lines   = [{**ln, "size": max(18, int(ln.get("size", 80) * font_scale))}
               for ln in lines]

    if not lines:
        draw.rectangle([0, 0, W, bar_h],   fill=COLOURS["black"])
        draw.rectangle([0, H-bar_h, W, H], fill=COLOURS["black"])
        img.save(out_png)
        return

    items = []
    for ln in lines:
        txt  = str(ln.get("text", ""))
        size = int(ln.get("size", 80))
        fam  = ln.get("font", "sans")
        clr  = COLOURS.get(ln.get("color", "white"), (255, 255, 255))
        font, _ = _autofit_font(draw, txt, fam, size, max_w)
        h    = _line_height(draw, txt, font)
        items.append({"txt": txt, "font": font, "clr": clr, "h": h})

    total_h  = sum(it["h"] for it in items) + gap * (len(items) - 1)
    block_y  = safe_cy - total_h // 2
    rule_pad = 20
    rx1, rx2 = int(W * 0.12), int(W * 0.88)
    draw.line([(rx1, block_y - rule_pad), (rx2, block_y - rule_pad)], fill=COLOURS["gold"], width=2)
    draw.line([(rx1, block_y + total_h + rule_pad), (rx2, block_y + total_h + rule_pad)], fill=COLOURS["gold"], width=2)

    cy = block_y
    for it in items:
        mid_cy = cy + it["h"] // 2
        if it["clr"] == COLOURS["gold"]:
            img  = _text_glow(img, W//2, mid_cy, it["txt"], it["font"], it["clr"],
                              glow_color=(180, 140, 20), radius=22)
            draw = ImageDraw.Draw(img)
        else:
            draw.text((W//2 + 2, mid_cy + 3), it["txt"], font=it["font"], fill=(0,0,0), anchor="mm")
            draw.text((W//2, mid_cy),          it["txt"], font=it["font"], fill=it["clr"], anchor="mm")
        cy += it["h"] + gap

    draw.rectangle([0,       0, W,    bar_h], fill=COLOURS["black"])
    draw.rectangle([0, H-bar_h, W,        H], fill=COLOURS["black"])
    img = _add_vignette(img, W, H, strength=160, power=2.0)
    img.save(out_png)


def render_main_title(title, tagline, W, H, out_png, font_scale=1.0):
    bar_h = int(H * 0.1)
    mid   = H // 2
    max_w = int(W * 0.9)
    img   = Image.new("RGB", (W, H), (3, 3, 12))
    draw  = ImageDraw.Draw(img)

    draw.text((W//2, int(H * 0.21)), "SUMMER  2026",
              font=load_font("sans", int(52 * font_scale)), fill=COLOURS["gold"], anchor="mm")
    rx1, rx2 = int(W * 0.18), int(W * 0.82)
    draw.line([(rx1, mid - 105), (rx2, mid - 105)], fill=COLOURS["gold"], width=2)
    draw.line([(rx1, mid + 100), (rx2, mid + 100)], fill=COLOURS["gold"], width=2)
    draw.text((W//2, mid - 62), "T H E",
              font=load_font("bebas", int(88 * font_scale)), fill=(220, 220, 220), anchor="mm")

    main_font, _ = _autofit_font(draw, title, "bebas", int(290 * font_scale), max_w)
    img  = _text_glow(img, W//2, mid + 40, title, main_font, COLOURS["white"],
                      glow_color=(220, 220, 255), radius=30)
    draw = ImageDraw.Draw(img)

    if tagline:
        draw.text((W//2, int(H * 0.75)), f'"{tagline}"',
                  font=load_font("sans", int(36 * font_scale)), fill=COLOURS["grey"], anchor="mm")
    draw.text((W//2, int(H * 0.82)), "RATED PG-13  ·  FOR CONTENT",
              font=load_font("sans", int(22 * font_scale)), fill=(75, 75, 95), anchor="mm")

    img  = _add_vignette(img, W, H, strength=160, power=1.6)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,       0, W,    bar_h], fill=COLOURS["black"])
    draw.rectangle([0, H-bar_h, W,        H], fill=COLOURS["black"])
    img.save(out_png)

def render_black(W, H, out_png):
    Image.new("RGB", (W, H), (0, 0, 0)).save(out_png)

# ── Node.js canvas renderer (preferred) ───────────────────────────────────────
def render_with_node(type_, config_dict, W, H, out_png):
    if not CANVAS_RENDERER.exists():
        return False
    r = subprocess.run(
        ["node", str(CANVAS_RENDERER),
         "--type", type_, "--config", json.dumps(config_dict),
         "--output", out_png, "--width", str(W), "--height", str(H)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        # Suppress canvas module errors — Pillow fallback handles it silently
        if "Cannot find module 'canvas'" not in r.stderr:
            warn(f"Node renderer: {r.stderr[:120]}")
        return False
    return True

# ── PNG → video segment ────────────────────────────────────────────────────────
def png_to_seg(png, duration, fps, out_mp4, fade_in=0.3, fade_out=0.3):
    half = duration / 2.0
    fi, fo = min(fade_in, half), min(fade_out, half)
    fo_start = max(0.0, duration - fo)
    vf_parts = []
    if fi > 0.01:  vf_parts.append(f"fade=t=in:st=0:d={fi:.3f}")
    if fo > 0.01:  vf_parts.append(f"fade=t=out:st={fo_start:.3f}:d={fo:.3f}")
    vf_arg = f'-vf "{",".join(vf_parts)}"' if vf_parts else ""
    run(f'ffmpeg -y -loop 1 -i "{png}" -t {duration} -r {fps} '
        f'{vf_arg} -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "{out_mp4}"')

def clip_to_seg(src, trim_start, trim_end, fps, W, H, out_mp4,
                color_grade="none", fade_in=0.3, fade_out=0.3, crop_fill=False):
    duration = trim_end - trim_start
    bar_h    = int(H * 0.1)
    grade    = COLOR_GRADES.get(color_grade, "")

    if crop_fill:
        # Crop-to-fill: scale up to cover full frame, crop center
        # Used for portrait (9:16, 4:5) and square (1:1) formats
        scale = (f"scale='if(gt(iw/ih,{W}/{H}),trunc(oh*a/2)*2,{W})':'if(gt(iw/ih,{W}/{H}),{H},trunc(ow/a/2)*2)',"
                 f"crop={W}:{H}")
    else:
        scale = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"

    bars     = f"drawbox=y=0:w={W}:h={bar_h}:color=black:t=fill,drawbox=y={H-bar_h}:w={W}:h={bar_h}:color=black:t=fill"
    fi_f     = f"fade=t=in:st=0:d={fade_in}" if fade_in else ""
    fo_f     = f"fade=t=out:st={duration-fade_out}:d={fade_out}" if fade_out else ""
    vf       = ",".join(p for p in [scale, grade, bars, fi_f, fo_f] if p)
    run(f'ffmpeg -y -ss {trim_start} -i "{src}" -t {duration} '
        f'-r {fps} -vf "{vf}" '
        f'-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "{out_mp4}"')

# ── Veo 3.1 clip generation (Phase 2 upgrade) ─────────────────────────────────
def veo_generate(prompt, out_path, duration_sec=5, aspect_ratio="16:9",
                 reference_image=None, model=None):
    """
    Generate a video clip with Veo 3.1 via google-genai SDK.

    Args:
        prompt:          Text prompt for the clip
        out_path:        Output file path (.mp4)
        duration_sec:    Duration in seconds (snapped to 4/6/8)
        aspect_ratio:    "16:9" or "9:16" (auto-set by format)
        reference_image: Path to reference image for image-to-video mode
        model:           Override model name (default: VEO_MODEL)
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        warn("GEMINI_API_KEY not set — skipping Veo generation")
        return None
    if Path(out_path).exists() and Path(out_path).stat().st_size > 50_000:
        log(f"Cache hit: {Path(out_path).name}")
        return out_path

    # Snap duration to valid Veo values (4, 6, 8)
    valid_durations = {4, 6, 8}
    duration_sec = min(valid_durations, key=lambda x: abs(x - duration_sec))

    model_name = model or VEO_MODEL
    log(f"Generating clip [{model_name}]: {Path(out_path).stem} …")

    try:
        from google import genai
        from google.genai import types as gentypes

        client = genai.Client(api_key=key)

        config_kwargs = {
            "number_of_videos": 1,
            "duration_seconds": duration_sec,
            "aspect_ratio":     aspect_ratio,
        }

        input_image = None
        if reference_image and Path(reference_image).exists():
            with open(reference_image, "rb") as f:
                img_data = f.read()
            ext = Path(reference_image).suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".webp": "image/webp"}
            input_image = gentypes.Image(
                image_bytes=img_data,
                mime_type=mime_map.get(ext, "image/png")
            )
            log(f"  Image-to-video: {Path(reference_image).name}")

        config = gentypes.GenerateVideosConfig(**config_kwargs)

        gen_kwargs = {"model": model_name, "prompt": prompt, "config": config}
        if input_image:
            gen_kwargs["image"] = input_image

        operation = client.models.generate_videos(**gen_kwargs)

        log(f"  Waiting for Veo…")
        for attempt in range(60):
            time.sleep(10)
            operation = client.operations.get(operation)
            if operation.done:
                break
            if attempt % 3 == 0:
                log(f"  …still generating ({attempt*10}s)")

        if not operation.done:
            warn(f"Veo timeout: {Path(out_path).stem}")
            return None

        if not operation.response or not operation.response.generated_videos:
            warn(f"No videos generated for {Path(out_path).stem}")
            return None

        video = operation.response.generated_videos[0].video
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)

        if video.video_bytes:
            Path(out_path).write_bytes(video.video_bytes)
        elif video.uri:
            url  = f"{video.uri}&key={key}" if "?" in video.uri else f"{video.uri}?key={key}"
            data = requests.get(url).content
            Path(out_path).write_bytes(data)
        else:
            warn(f"Veo returned no video data for {Path(out_path).stem}")
            return None

        size_kb = Path(out_path).stat().st_size // 1024
        ok(f"{Path(out_path).name} ({size_kb}KB, {duration_sec}s)")
        return out_path

    except Exception as exc:
        # Fallback to Veo 2.0 via REST if 3.1 fails
        warn(f"Veo 3.1 error ({exc}) — falling back to Veo 2.0 REST")
        return _veo2_generate_rest(prompt, out_path, duration_sec)


def _veo2_generate_rest(prompt, out_path, duration_sec=5):
    """Legacy Veo 2.0 REST fallback."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    r = requests.post(
        f"{VEO_BASE}/models/{VEO_MODEL_FALLBACK}:predictLongRunning?key={key}",
        json={"instances": [{"prompt": prompt}],
              "parameters": {"aspectRatio": "16:9", "durationSeconds": duration_sec}}
    )
    if r.status_code != 200:
        warn(f"Veo2 {r.status_code}: {r.text[:200]}")
        return None
    op = r.json()["name"]
    for _ in range(60):
        time.sleep(10)
        poll = requests.get(f"{VEO_BASE}/{op}?key={key}").json()
        if poll.get("done"):
            samples = poll.get("response", {}).get("generateVideoResponse", {}).get("generatedSamples", [])
            if not samples:
                return None
            uri  = samples[0]["video"]["uri"]
            url  = f"{uri}&key={key}" if "?" in uri else f"{uri}?key={key}"
            data = requests.get(url).content
            Path(out_path).write_bytes(data)
            ok(f"{Path(out_path).name} ({len(data)//1024}KB) [Veo2 fallback]")
            return out_path
    warn(f"Veo2 timeout: {Path(out_path).stem}")
    return None

# ── Audio mixing ───────────────────────────────────────────────────────────────
def mix_audio(music, voice, sfx, out, duration,
              music_vol=0.35, voice_vol=1.0, voice_delay=0.0, sfx_vol=1.0):
    """Mix music + voiceover + optional SFX track."""
    delay_ms = int(voice_delay * 1000)

    if sfx and Path(sfx).exists():
        filt = (f"[0]volume={music_vol}[m];"
                f"[1]volume={voice_vol},adelay={delay_ms}|{delay_ms}[v];"
                f"[2]volume={sfx_vol}[s];"
                f"[m][v][s]amix=inputs=3:duration=first:dropout_transition=2[out]")
        run(f'ffmpeg -y -i "{music}" -i "{voice}" -i "{sfx}" '
            f'-filter_complex "{filt}" -map "[out]" '
            f'-t {duration} -ar 44100 "{out}"')
    else:
        filt = (f"[0]volume={music_vol}[m];"
                f"[1]volume={voice_vol},adelay={delay_ms}|{delay_ms}[v];"
                f"[m][v]amix=inputs=2:duration=first:dropout_transition=2[out]")
        run(f'ffmpeg -y -i "{music}" -i "{voice}" '
            f'-filter_complex "{filt}" -map "[out]" '
            f'-t {duration} -ar 44100 "{out}"')

def mix_audio_simple(music, out, duration, music_vol=0.35):
    """Music-only mix when no voiceover is available."""
    run(f'ffmpeg -y -i "{music}" -af "volume={music_vol}" '
        f'-t {duration} -ar 44100 "{out}"')

# ── Assembly ───────────────────────────────────────────────────────────────────
def assemble(manifest_path, generate_missing=True, format_override=None):
    """
    Assemble a trailer from a YAML manifest.

    Args:
        manifest_path:   Path to the YAML manifest file
        generate_missing: Generate missing Veo clips if GEMINI_API_KEY is set
        format_override: Override output format ('16x9','9x16','1x1','4x5').
                         Overrides resolution in YAML. Enables crop-fill for
                         portrait/square formats.
    """
    manifest_path = Path(manifest_path).resolve()
    base_dir = manifest_path.parent

    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)

    W, H   = cfg.get("resolution", [1920, 1080])
    fps    = cfg.get("fps", 30)
    grade  = cfg.get("color_grade", "teal_orange")
    audio  = cfg.get("audio", {})
    grain  = cfg.get("film_grain", True)
    auto_sfx = audio.get("sfx", "none") == "auto"

    # Apply format override (Phase 2 multi-format)
    crop_fill   = False
    fmt_label   = ""
    veo_aspect  = "16:9"
    font_scale  = 1.0

    if format_override and format_override in FORMAT_PRESETS:
        fmt = FORMAT_PRESETS[format_override]
        W, H        = fmt["w"],  fmt["h"]
        crop_fill   = fmt.get("crop", False)
        veo_aspect  = fmt.get("aspect_ratio", "16:9")
        fmt_label   = fmt["label"]
        # Scale fonts relative to reference width of 1920
        font_scale  = W / 1920.0
    elif format_override and format_override not in FORMAT_PRESETS:
        warn(f"Unknown format '{format_override}' — using YAML resolution. "
             f"Valid: {', '.join(FORMAT_PRESETS)}")

    # Compute output path; append format suffix if overriding
    base_out = base_dir / cfg.get("output", "output.mp4")
    if format_override and format_override != "16x9":
        out = base_out.parent / f"{base_out.stem}_{format_override}{base_out.suffix}"
    else:
        out = base_out

    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tf_"))
    timeline_items = cfg.get("timeline", [])

    segments, total_dur = [], 0.0
    fmt_display = f"  [{fmt_label}]" if fmt_label else ""
    print(f"\n🎬 TRAILER FORGE{fmt_display}")
    print(f"   {W}×{H} @ {fps}fps  |  Grade: {grade}  |  Grain: {'on' if grain else 'off'}  |  SFX: {'auto' if auto_sfx else 'off'}  |  Crop-fill: {'on' if crop_fill else 'off'}\n")

    for i, item in enumerate(timeline_items):
        kind    = item.get("type", "black")
        fi      = item.get("fade_in",  0.35)
        fo      = item.get("fade_out", 0.35)
        seg_out = work / f"seg_{i:03d}.mp4"

        print(f"  [{i+1:02d}] {kind}", end=" ", flush=True)

        if kind == "black":
            dur = float(item.get("duration", 0.5))
            png = work / f"black_{i}.png"
            render_black(W, H, str(png))
            png_to_seg(str(png), dur, fps, str(seg_out), 0, 0)
            print(f"— {dur:.1f}s")

        elif kind == "title_card":
            dur = float(item.get("duration", 3.0))
            png = work / f"title_{i}.png"
            if not render_with_node("title_card", item, W, H, str(png)):
                render_title_card(item, W, H, str(png), font_scale=font_scale)
            png_to_seg(str(png), dur, fps, str(seg_out), fi, fo)
            label = " | ".join(str(l.get("text","")) for l in item.get("lines",[]))
            print(f"— {dur:.1f}s — \"{label[:50]}\"")

        elif kind == "main_title":
            dur     = float(item.get("duration", 6.0))
            title   = item.get("title", "UNTITLED")
            tagline = item.get("tagline", "")
            png     = work / f"main_{i}.png"
            if not render_with_node("main_title", {"title": title, "tagline": tagline}, W, H, str(png)):
                render_main_title(title, tagline, W, H, str(png), font_scale=font_scale)
            png_to_seg(str(png), dur, fps, str(seg_out), fi, fo)
            print(f"— {dur:.1f}s — \"{title}\"")

        elif kind == "veo_clip":
            src    = base_dir / item.get("file", "")
            trim   = item.get("trim", [0, 5])
            dur    = float(trim[1]) - float(trim[0])
            prompt = resolve_veo_prompt(item)
            ref_img = item.get("reference_image")  # image-to-video support

            if not src.exists() and generate_missing:
                src.parent.mkdir(parents=True, exist_ok=True)
                veo_generate(prompt, str(src),
                             duration_sec=int(dur) if dur in (4,6,8) else 6,
                             aspect_ratio=veo_aspect,
                             reference_image=str(base_dir/ref_img) if ref_img else None)

            if src.exists():
                clip_to_seg(str(src), float(trim[0]), float(trim[1]),
                            fps, W, H, str(seg_out), grade, fi, fo,
                            crop_fill=crop_fill)
                print(f"— {dur:.1f}s ← {src.name}")
            else:
                warn(f"Missing: {src.name} — substituting black")
                bpng = work / f"black_{i}.png"
                render_black(W, H, str(bpng))
                png_to_seg(str(bpng), dur, fps, str(seg_out), 0, 0)
                print(f"— {dur:.1f}s [BLACK]")
        else:
            print(f"unknown type '{kind}', skipping"); continue

        segments.append(str(seg_out))
        total_dur += (float(item["trim"][1]) - float(item["trim"][0])) if kind == "veo_clip" \
                     else float(item.get("duration", 3.0))

    # Concatenate segments
    print(f"\n  Concatenating {len(segments)} segments ({dur_str(total_dur)})…")
    concat_txt = work / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{s}'" for s in segments))

    no_audio = work / "no_audio.mp4"
    grain_vf = "noise=alls=6:allf=t,unsharp=3:3:0.4:3:3:0.0" if grain else ""
    vf_arg   = f'-vf "{grain_vf}"' if grain_vf else ""
    run(f'ffmpeg -y -f concat -safe 0 -i "{concat_txt}" '
        f'{vf_arg} -c:v libx264 -preset slow -crf 19 -pix_fmt yuv420p '
        f'-movflags +faststart "{no_audio}"')

    # Build automated SFX mix if requested
    sfx_mix = None
    if auto_sfx:
        print(f"\n  🎵 Building automated sound design…")
        sfx_mix = build_sfx_mix(timeline_items, base_dir, total_dur, work, grade=grade)

    # Audio mixing
    music_path = audio.get("music", "")
    voice_path = audio.get("voiceover", "")

    if music_path:
        mp = base_dir / music_path
        vp = (base_dir / voice_path) if voice_path else None

        if mp.exists():
            print(f"  Mixing audio…")
            mixed = work / "mixed.aac"
            if vp and vp.exists():
                mix_audio(str(mp), str(vp), sfx_mix, str(mixed), total_dur,
                          float(audio.get("music_vol", 0.35)),
                          float(audio.get("voice_vol", 1.0)),
                          float(audio.get("voice_delay", 0.0)),
                          sfx_vol=float(audio.get("sfx_vol", 0.8)))
            else:
                if vp: warn(f"Voiceover not found: {vp.name}")
                mix_audio_simple(str(mp), str(mixed), total_dur, float(audio.get("music_vol", 0.35)))

            run(f'ffmpeg -y -i "{no_audio}" -i "{mixed}" '
                f'-c:v copy -c:a aac -b:a 192k -shortest '
                f'-movflags +faststart "{out}"')
        else:
            warn(f"Music not found: {mp.name} — silent output")
            shutil.copy(no_audio, out)
    else:
        shutil.copy(no_audio, out)

    shutil.rmtree(work, ignore_errors=True)
    size_kb = out.stat().st_size // 1024
    ok(f"Done → {out} ({size_kb}KB, ~{dur_str(total_dur)})")
    return str(out)

# ── Preview ────────────────────────────────────────────────────────────────────
def preview(manifest_path):
    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)
    W, H = cfg.get("resolution", [1920, 1080])
    auto_sfx = cfg.get("audio", {}).get("sfx", "none") == "auto"
    print(f"\n📋 TIMELINE: {manifest_path}")
    print(f"   {W}×{H} @ {cfg.get('fps',30)}fps | Grade: {cfg.get('color_grade','none')} | SFX: {'auto' if auto_sfx else 'off'}\n")
    print(f"   {'#':>3}  {'START':>7}  {'END':>7}  {'TYPE':<12}  {'PRESET/LABEL'}")
    print(f"   {'─'*65}")
    t = 0.0
    for i, item in enumerate(cfg.get("timeline", [])):
        kind  = item.get("type", "?")
        trim  = item.get("trim", [0, 5])
        dur   = (float(trim[1]) - float(trim[0])) if kind == "veo_clip" else float(item.get("duration", 3))
        preset = item.get("preset", "")
        if kind == "title_card":
            label = " | ".join(str(l.get("text","")) for l in item.get("lines",[]))[:40]
        elif kind == "veo_clip":
            label = f"[{preset}] {item.get('file','?')}" if preset else item.get("file", "?")
        elif kind == "main_title":
            label = item.get("title", "?")
        else:
            label = ""
        print(f"   {i+1:>3}  {dur_str(t):>7}  {dur_str(t+dur):>7}  {kind:<12}  {label}")
        t += dur
    print(f"\n   Total: {dur_str(t)}")

# ── Multi-Platform Delivery ────────────────────────────────────────────────────
PLATFORM_SPECS = {
    "youtube":        {"w": 1920, "h": 1080, "crf": 18, "audio": "192k"},
    "youtube_4k":     {"w": 3840, "h": 2160, "crf": 16, "audio": "256k"},
    "telegram":       {"w": 1280, "h": 720,  "crf": 30, "audio": "128k", "max_mb": 15},
    "instagram_feed": {"w": 1080, "h": 1080, "crf": 26, "audio": "128k"},
    "instagram_reel": {"w": 1080, "h": 1920, "crf": 26, "audio": "128k"},
    "tiktok":         {"w": 1080, "h": 1920, "crf": 26, "audio": "128k", "max_mb": 287},
    "twitter":        {"w": 1280, "h": 720,  "crf": 28, "audio": "128k", "max_mb": 512},
    "festival_prores":{"w": 1920, "h": 1080, "crf": 0,  "audio": "320k", "codec": "prores_ks"},
}

def deliver(video_path, targets=None):
    """One master → all platform formats."""
    if not targets:
        targets = ["youtube", "telegram"]
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    out_dir = video_path.parent / "delivered"
    out_dir.mkdir(exist_ok=True)

    print(f"\n📦 MULTI-PLATFORM DELIVERY")
    print(f"   Master: {video_path.name}\n")

    for target in targets:
        if target not in PLATFORM_SPECS:
            warn(f"Unknown target '{target}' — skipping")
            continue
        spec     = PLATFORM_SPECS[target]
        w, h     = spec["w"], spec["h"]
        crf      = spec["crf"]
        abr      = spec["audio"]
        codec    = spec.get("codec", "libx264")
        out_file = out_dir / f"{video_path.stem}_{target}.mp4"

        print(f"  [{target}] {w}×{h} (crf={crf}, audio={abr})…", flush=True)
        scale_vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
        if codec == "prores_ks":
            run(f'ffmpeg -y -i "{video_path}" -vf "{scale_vf}" '
                f'-c:v prores_ks -profile:v 3 -c:a pcm_s16le '
                f'-movflags +faststart "{out_file}"')
        else:
            run(f'ffmpeg -y -i "{video_path}" -vf "{scale_vf}" '
                f'-c:v {codec} -preset slow -crf {crf} -pix_fmt yuv420p '
                f'-c:a aac -b:a {abr} -movflags +faststart "{out_file}"')

        size_mb = out_file.stat().st_size / (1024*1024)
        max_mb  = spec.get("max_mb")
        flag    = f" ⚠ EXCEEDS {max_mb}MB limit!" if max_mb and size_mb > max_mb else ""
        ok(f"{out_file.name} ({size_mb:.1f}MB){flag}")

    print(f"\n✅ Delivered to: {out_dir}/")

# ── Subtitle / SRT Export ──────────────────────────────────────────────────────
def export_srt(whisper_json_path, output_srt="output.srt"):
    """Generate SRT subtitle file from Whisper word-timestamp JSON."""
    with open(whisper_json_path) as f:
        data = json.load(f)

    def ts(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

    lines = []
    idx   = 1
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            word  = w.get("word", "").strip()
            start = w.get("start", 0)
            end   = w.get("end", start + 0.1)
            if word:
                lines.append(f"{idx}\n{ts(start)} --> {ts(end)}\n{word}\n")
                idx += 1

    Path(output_srt).write_text("\n".join(lines))
    ok(f"SRT export: {output_srt} ({idx-1} words)")

# ── Phase 4: M&E Export (Music & Effects — no dialogue) ───────────────────────
def export_me(manifest_path, output_path=None):
    """
    Export a Music & Effects (M&E) track — music + SFX with dialogue stripped.
    Used for international distribution: foreign distributors dub in their language
    over a clean M&E stem.

    Output: a .wav file (stereo, 44.1kHz) alongside the master video.
    """
    manifest_path = Path(manifest_path).resolve()
    base_dir      = manifest_path.parent

    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)

    audio    = cfg.get("audio", {})
    out_vid  = base_dir / cfg.get("output", "output.mp4")
    out_me   = Path(output_path) if output_path else out_vid.parent / (out_vid.stem + "_ME.wav")

    music_path = audio.get("music", "")
    auto_sfx   = audio.get("sfx", "none") == "auto"

    print(f"\n🎵 M&E EXPORT (Music & Effects — no dialogue)")
    print(f"   Manifest : {manifest_path.name}")
    print(f"   Output   : {out_me}\n")

    if not music_path:
        warn("No music defined in manifest — M&E will be silence")
        run(f'ffmpeg -y -f lavfi -i "anullsrc=duration=10" -ar 44100 -ac 2 "{out_me}"', check=False)
        return str(out_me)

    mp = base_dir / music_path
    if not mp.exists():
        warn(f"Music file not found: {mp}")
        return None

    # Measure total duration from manifest timeline
    total_dur = 0.0
    for item in cfg.get("timeline", []):
        kind  = item.get("type", "black")
        trim  = item.get("trim", [0, 5])
        total_dur += (float(trim[1]) - float(trim[0])) if kind == "veo_clip" \
                     else float(item.get("duration", 3.0))

    music_vol = float(audio.get("music_vol", 0.35))
    work      = Path(tempfile.mkdtemp(prefix="tf_me_"))

    if auto_sfx:
        log("Building SFX layer for M&E…")
        sfx_mix = build_sfx_mix(
            cfg.get("timeline", []), base_dir, total_dur, work,
            grade=cfg.get("color_grade", "dark_thriller")
        )
        if sfx_mix:
            sfx_vol = float(audio.get("sfx_vol", 0.8))
            filt = (f"[0]volume={music_vol}[m];"
                    f"[1]volume={sfx_vol}[s];"
                    f"[m][s]amix=inputs=2:duration=first:dropout_transition=2[out]")
            run(f'ffmpeg -y -i "{mp}" -i "{sfx_mix}" '
                f'-filter_complex "{filt}" -map "[out]" '
                f'-t {total_dur} -ar 44100 -ac 2 "{out_me}"')
        else:
            run(f'ffmpeg -y -i "{mp}" -af "volume={music_vol}" '
                f'-t {total_dur} -ar 44100 -ac 2 "{out_me}"')
    else:
        run(f'ffmpeg -y -i "{mp}" -af "volume={music_vol}" '
            f'-t {total_dur} -ar 44100 -ac 2 "{out_me}"')

    shutil.rmtree(work, ignore_errors=True)
    size_kb = Path(out_me).stat().st_size // 1024
    ok(f"M&E export: {out_me.name} ({size_kb}KB, {dur_str(total_dur)})")
    ok("Ready for international dubbing — no dialogue track included")
    return str(out_me)


# ── Phase 5: Storyboard Generation ────────────────────────────────────────────
def storyboard(manifest_path, output_png=None, cols=4):
    """
    Generate a visual storyboard from a trailer YAML manifest.

    Each panel shows:
    - Shot number + timecode
    - Segment type badge
    - Shot preset/type label
    - Description text
    - If a veo_clip file exists → extracts a thumbnail frame
    - Otherwise → colored placeholder with cinematography vocabulary

    Output: PNG grid image (print-ready, letter/A4 proportions)
    """
    manifest_path = Path(manifest_path).resolve()
    base_dir      = manifest_path.parent

    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)

    out_png = Path(output_png) if output_png else \
              base_dir / (Path(manifest_path).stem + "_storyboard.png")

    timeline = cfg.get("timeline", [])
    title    = cfg.get("title", Path(manifest_path).stem.replace("_", " ").upper())

    # Panel dimensions
    PW, PH   = 480, 280           # panel width, height
    PAD      = 16                 # padding between panels
    MARGIN   = 40                 # page margin
    HEADER_H = 80                 # title header height
    LABEL_H  = 60                 # label strip below frame
    PANEL_H  = PH + LABEL_H + 8  # total panel height with label

    # Segment type colors
    TYPE_COLORS = {
        "veo_clip":   (20,  60,  120),
        "title_card": (60,  20,  80),
        "main_title": (100, 20,  20),
        "black":      (20,  20,  20),
    }
    TYPE_LABELS = {
        "veo_clip":   "📹 CLIP",
        "title_card": "📝 CARD",
        "main_title": "🎬 TITLE",
        "black":      "⬛ BLACK",
    }

    # Filter out pure black segments from storyboard (they're just timing)
    panels = []
    t = 0.0
    for i, item in enumerate(timeline):
        kind = item.get("type", "black")
        trim = item.get("trim", [0, 5])
        dur  = (float(trim[1]) - float(trim[0])) if kind == "veo_clip" \
               else float(item.get("duration", 3.0))
        if kind != "black":
            panels.append({"idx": i+1, "item": item, "t": t, "dur": dur})
        t += dur

    # Grid dimensions
    rows       = max(1, -(-len(panels) // cols))  # ceil division
    page_w     = MARGIN*2 + cols*(PW+PAD) - PAD
    page_h     = MARGIN*2 + HEADER_H + rows*(PANEL_H+PAD) - PAD + 40
    page       = Image.new("RGB", (page_w, page_h), (18, 18, 26))
    draw       = ImageDraw.Draw(page)

    # Header
    header_font = load_font("bebas", 52)
    sub_font    = load_font("sans",  22)
    draw.text((MARGIN, MARGIN), title,
              font=header_font, fill=COLOURS["white"])
    draw.text((MARGIN, MARGIN + 56),
              f"STORYBOARD  ·  {len(panels)} shots  ·  {dur_str(t)}",
              font=sub_font, fill=COLOURS["gold"])
    draw.line([(MARGIN, MARGIN + HEADER_H - 4),
               (page_w - MARGIN, MARGIN + HEADER_H - 4)],
              fill=COLOURS["gold"], width=1)

    for pi, panel in enumerate(panels):
        col   = pi % cols
        row   = pi // cols
        px    = MARGIN + col * (PW + PAD)
        py    = MARGIN + HEADER_H + row * (PANEL_H + PAD)
        item  = panel["item"]
        kind  = item.get("type", "black")
        color = TYPE_COLORS.get(kind, (40, 40, 40))

        # Try to extract frame from existing clip
        frame_img = None
        if kind == "veo_clip":
            src = base_dir / item.get("file", "")
            if src.exists():
                try:
                    thumb = Path(tempfile.mktemp(suffix=".png"))
                    trim_start = float(item.get("trim", [0,5])[0])
                    grab_at    = trim_start + panel["dur"] * 0.4
                    run(f'ffmpeg -y -ss {grab_at} -i "{src}" -vframes 1 '
                        f'-vf "scale={PW}:{PH}:force_original_aspect_ratio=increase,crop={PW}:{PH}" '
                        f'"{thumb}"', check=False)
                    if thumb.exists():
                        frame_img = Image.open(thumb).convert("RGB").resize((PW, PH))
                except Exception:
                    pass

        # Draw panel frame
        if frame_img:
            page.paste(frame_img, (px, py))
        else:
            # Colored placeholder
            draw.rectangle([px, py, px+PW, py+PH], fill=color)
            # Gradient overlay suggestion lines
            for lx in range(0, PW, 40):
                draw.line([(px+lx, py), (px+lx, py+PH)],
                          fill=(*color, 60) if hasattr(color, '__len__') else color, width=1)

            # Description text in placeholder
            desc = ""
            if kind == "veo_clip":
                preset = item.get("preset", "")
                subj   = item.get("subject", item.get("prompt", ""))[:60]
                desc   = f"[{preset}]\n{subj}" if preset else subj
            elif kind == "title_card":
                desc = "\n".join(str(l.get("text","")) for l in item.get("lines",[]))[:80]
            elif kind == "main_title":
                desc = f"T H E\n{item.get('title','')}"

            if desc:
                dfont = load_font("sans", 18)
                # Word wrap
                words = desc.replace("\n", " \n ").split(" ")
                lines_out, cur = [], ""
                for w in words:
                    if w == "\n":
                        lines_out.append(cur.strip()); cur = ""
                    elif len(cur) + len(w) + 1 > 32:
                        lines_out.append(cur.strip()); cur = w
                    else:
                        cur = (cur + " " + w).strip()
                if cur: lines_out.append(cur)

                ty = py + PH//2 - len(lines_out)*12
                for ln in lines_out[:6]:
                    draw.text((px + PW//2, ty), ln, font=dfont,
                              fill=(200,200,220), anchor="mm")
                    ty += 22

        # Type badge (top-left)
        badge_label = TYPE_LABELS.get(kind, kind.upper())
        bfont = load_font("sans", 16)
        bw    = 110 if kind != "black" else 80
        draw.rectangle([px, py, px+bw, py+22], fill=(0,0,0,180))
        draw.text((px+6, py+4), badge_label, font=bfont, fill=COLOURS["gold"])

        # Shot number + timecode (top-right)
        nfont = load_font("sans", 16)
        tc    = dur_str(panel["t"])
        draw.text((px+PW-6, py+4), f"#{panel['idx']} {tc}",
                  font=nfont, fill=(180,180,180), anchor="ra")

        # Label strip below frame
        label_bg_y = py + PH
        draw.rectangle([px, label_bg_y, px+PW, label_bg_y+LABEL_H],
                       fill=(12, 12, 20))
        draw.line([(px, label_bg_y), (px+PW, label_bg_y)],
                  fill=COLOURS["gold"], width=1)

        # Duration
        dur_font = load_font("bebas", 26)
        draw.text((px+8, label_bg_y+6),
                  f"{panel['dur']:.1f}s",
                  font=dur_font, fill=COLOURS["goldhi"])

        # Preset or shot info
        info = ""
        if kind == "veo_clip" and item.get("preset"):
            info = item["preset"].replace("_", " ").upper()
        elif kind == "veo_clip" and item.get("shot"):
            s = item["shot"]
            info = f"{s.get('type','')} {s.get('movement','')}"
        elif kind == "title_card":
            first_line = item.get("lines", [{}])[0].get("text", "")
            info = first_line[:28]
        elif kind == "main_title":
            info = item.get("title", "")

        if info:
            ifont = load_font("sans", 15)
            draw.text((px+8, label_bg_y+32), info, font=ifont,
                      fill=(180, 180, 200))

        # Panel border
        draw.rectangle([px, py, px+PW, py+PH+LABEL_H],
                       outline=COLOURS["gold"], width=1)

    # Footer
    footer_y = page_h - 28
    draw.text((MARGIN, footer_y),
              "trailer-forge  ·  murdawkmedia.com  ·  github.com/hilaryduffrules-hash/trailer-forge",
              font=load_font("sans", 14), fill=(60, 60, 80))

    page.save(str(out_png))
    ok(f"Storyboard: {out_png} ({len(panels)} panels, {page_w}×{page_h}px)")
    return str(out_png)


# ── Phase 6: Broadcast Elements ───────────────────────────────────────────────

def render_countdown(W, H, work_dir, fps=30):
    """
    Classic film countdown leader: 8-7-6-5-4-3-2 with SMPTE-style frames.
    Returns list of (segment_mp4, duration) tuples.
    """
    segs = []
    for n in range(8, 1, -1):
        png = work_dir / f"count_{n}.png"
        img = Image.new("RGB", (W, H), (10, 10, 10))
        d   = ImageDraw.Draw(img)

        # Outer circle
        cx, cy, r = W//2, H//2, min(W,H)//2 - 40
        d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(200,200,200), width=6)

        # Cross hairs
        d.line([(0, H//2), (W, H//2)], fill=(200,200,200), width=2)
        d.line([(W//2, 0), (W//2, H)], fill=(200,200,200), width=2)

        # Inner circle
        ri = r // 3
        d.ellipse([cx-ri, cy-ri, cx+ri, cy+ri], outline=(200,200,200), width=3)

        # Number
        nfont = load_font("bebas", min(W, H) // 3)
        img   = _text_glow(img, cx, cy, str(n), nfont, COLOURS["white"],
                           glow_color=(180,180,180), radius=20)

        # SMPTE-style color strip at bottom
        bar_colors = [(192,0,0),(192,192,0),(0,192,0),(0,192,192),
                      (0,0,192),(192,0,192),(192,192,192)]
        bw = W // len(bar_colors)
        bd = ImageDraw.Draw(img)
        for bi, bc in enumerate(bar_colors):
            bd.rectangle([bi*bw, H-60, (bi+1)*bw, H], fill=bc)

        img.save(str(png))
        seg = work_dir / f"count_{n}.mp4"
        # Each number holds for 1 frame, then beep — classic 24fps leader = 1s/number
        png_to_seg(str(png), 1.0, fps, str(seg), fade_in=0, fade_out=0)
        segs.append((str(seg), 1.0))

    return segs


def render_color_bars(W, H, duration, fps, out_mp4):
    """
    SMPTE-style color bars for monitor calibration.
    Standard broadcast tool — goes at the head of any deliverable master.
    """
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d   = ImageDraw.Draw(img)

    # Top 75% — SMPTE 7 color bars
    bar_h   = int(H * 0.67)
    colors  = [(192,192,192),(192,192,0),(0,192,192),(0,192,0),
               (192,0,192),(192,0,0),(0,0,192)]
    bw      = W // len(colors)
    for i, c in enumerate(colors):
        d.rectangle([i*bw, 0, (i+1)*bw, bar_h], fill=c)

    # Middle strip — -I, white, +Q, black sub-blacks
    mid_h   = int(H * 0.08)
    mid_y   = bar_h
    sub_colors = [(0,33,76),(255,255,255),(50,0,106),(10,10,10),
                  (16,16,16),(20,20,20),(10,10,10)]
    for i, c in enumerate(sub_colors):
        d.rectangle([i*bw, mid_y, (i+1)*bw, mid_y+mid_h], fill=c)

    # Bottom — PLUGE (Picture Line-Up Generation Equipment)
    bot_y = mid_y + mid_h
    d.rectangle([0, bot_y, int(W*0.16), H], fill=(10,10,10))    # black
    d.rectangle([int(W*0.16), bot_y, int(W*0.50), H], fill=(16,16,16)) # superblack
    d.rectangle([int(W*0.50), bot_y, int(W*0.75), H], fill=(255,255,255)) # white
    d.rectangle([int(W*0.75), bot_y, W, H], fill=(10,10,10))    # black

    # Labels
    lfont = load_font("sans", 22)
    for i, label in enumerate(["GY","YEL","CYN","GRN","MAG","RED","BLU"]):
        d.text((i*bw + bw//2, bar_h - 28), label, font=lfont,
               fill=(0,0,0) if colors[i] != (0,0,192) else (255,255,255),
               anchor="mm")

    # "COLOR BARS" watermark
    wfont = load_font("bebas", 48)
    d.text((W//2, H//2 + 40), "COLOUR BARS  ·  SMPTE  ·  trailer-forge",
           font=wfont, fill=(100,100,100), anchor="mm")

    png = str(out_mp4).replace(".mp4", "_bars.png")
    img.save(png)
    png_to_seg(png, duration, fps, out_mp4, fade_in=0, fade_out=0)
    ok(f"Color bars: {Path(out_mp4).name} ({duration}s)")


def render_lower_third(text_top, text_bottom, W, H, out_png,
                       accent_color=(212,175,55), duration=None):
    """
    Lower third graphic — name/title overlay for broadcast or doc style.
    Transparent PNG that overlays on a video clip.
    """
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)

    # Bar geometry — lower-left position
    bar_x    = int(W * 0.06)
    bar_y    = int(H * 0.72)
    bar_w    = int(W * 0.44)
    bar_h    = 80
    accent_w = 6

    # Dark semi-transparent backing
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+bar_h],
                 fill=(5, 5, 15, 210))
    img = Image.alpha_composite(img, overlay)
    d   = ImageDraw.Draw(img)

    # Accent bar (left edge)
    d.rectangle([bar_x, bar_y, bar_x+accent_w, bar_y+bar_h],
                fill=(*accent_color, 255))

    # Top line — name (bigger, Bebas)
    tfont = load_font("bebas", 36)
    d.text((bar_x + accent_w + 14, bar_y + 8),
           text_top.upper(), font=tfont, fill=(255, 255, 255, 255))

    # Bottom line — title/role (smaller, sans)
    bfont = load_font("sans", 20)
    d.text((bar_x + accent_w + 14, bar_y + 48),
           text_bottom, font=bfont, fill=(*accent_color, 230))

    # Bottom accent line
    d.rectangle([bar_x + accent_w, bar_y + bar_h - 3,
                 bar_x + bar_w, bar_y + bar_h],
                fill=(*accent_color, 180))

    img.save(str(out_png))
    return str(out_png)


def burn_lower_third(clip_path, text_top, text_bottom, out_mp4,
                     start_sec=0.5, hold_sec=3.5, fade_dur=0.3,
                     accent_color=(212,175,55)):
    """
    Burn a lower third overlay onto a video clip.
    The text fades in at start_sec, holds for hold_sec, then fades out.
    """
    W, H = 1920, 1080
    # Probe actual video dimensions
    probe = run(f'ffprobe -v quiet -select_streams v:0 '
                f'-show_entries stream=width,height '
                f'-of csv=p=0 "{clip_path}"', check=False)
    if probe.returncode == 0 and probe.stdout.strip():
        try:
            parts = probe.stdout.strip().split(",")
            W, H = int(parts[0]), int(parts[1])
        except Exception:
            pass

    # Render lower third PNG
    lt_png = Path(tempfile.mktemp(suffix="_lt.png"))
    render_lower_third(text_top, text_bottom, W, H, lt_png, accent_color)

    end_sec  = start_sec + hold_sec
    fade_end = end_sec + fade_dur

    # ffmpeg overlay with fade in/out using enable expression
    filt = (
        f"[1:v]"
        f"fade=t=in:st={start_sec}:d={fade_dur}:alpha=1,"
        f"fade=t=out:st={end_sec}:d={fade_dur}:alpha=1"
        f"[lt];"
        f"[0:v][lt]overlay=0:0[out]"
    )
    run(f'ffmpeg -y -i "{clip_path}" -i "{lt_png}" '
        f'-filter_complex "{filt}" -map "[out]" -map "0:a?" '
        f'-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p '
        f'-c:a copy "{out_mp4}"')

    ok(f"Lower third burned: {Path(out_mp4).name}")
    return str(out_mp4)


def assemble_broadcast(manifest_path, generate_missing=True):
    """
    Assemble with broadcast elements support.
    Handles new segment types: countdown, color_bars, lower_third overlay.
    Falls through to standard assemble() for non-broadcast manifests.
    """
    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)

    # Check if any broadcast segment types are present
    has_broadcast = any(
        item.get("type") in ("countdown", "color_bars", "lower_third")
        for item in cfg.get("timeline", [])
    )

    if not has_broadcast:
        return assemble(manifest_path, generate_missing)

    # Patch: expand broadcast segment types then call standard assemble
    manifest_path = Path(manifest_path).resolve()
    base_dir      = manifest_path.parent
    W, H          = cfg.get("resolution", [1920, 1080])
    fps           = cfg.get("fps", 30)
    work          = Path(tempfile.mkdtemp(prefix="tf_bc_"))

    new_timeline = []
    for item in cfg.get("timeline", []):
        kind = item.get("type", "black")

        if kind == "color_bars":
            dur    = float(item.get("duration", 10.0))
            barmp4 = work / "color_bars.mp4"
            render_color_bars(W, H, dur, fps, str(barmp4))
            new_timeline.append({
                "type": "veo_clip",
                "file": str(barmp4),
                "trim": [0, dur],
                "fade_in":  0,
                "fade_out": 0,
            })

        elif kind == "countdown":
            segs = render_countdown(W, H, work, fps)
            for seg_path, seg_dur in segs:
                new_timeline.append({
                    "type": "veo_clip",
                    "file": seg_path,
                    "trim": [0, seg_dur],
                    "fade_in":  0,
                    "fade_out": 0,
                })

        elif kind == "lower_third":
            # lower_third overlays on the NEXT veo_clip — inject a helper tag
            new_timeline.append({**item, "_lower_third": True})

        else:
            new_timeline.append(item)

    # Apply lower_third overlays to following clips
    resolved = []
    i = 0
    while i < len(new_timeline):
        item = new_timeline[i]
        if item.get("_lower_third") and i+1 < len(new_timeline):
            next_item = new_timeline[i+1]
            if next_item.get("type") == "veo_clip":
                src = base_dir / next_item.get("file", "")
                if src.exists():
                    lt_out = work / f"lt_{i}.mp4"
                    burn_lower_third(
                        str(src),
                        item.get("name", "NAME"),
                        item.get("role", "TITLE"),
                        str(lt_out),
                        start_sec    = float(item.get("start_sec", 0.5)),
                        hold_sec     = float(item.get("hold_sec",  3.0)),
                        accent_color = tuple(item.get("accent_color", [212,175,55])),
                    )
                    resolved.append({**next_item, "file": str(lt_out)})
                else:
                    # Clip missing — skip lower third, keep original clip item
                    log(f"Lower third skipped (clip missing): {next_item.get('file','?')}")
                    resolved.append(next_item)
                i += 2
                continue
            # No following veo_clip — just drop the lower_third item
            i += 1
            continue
        resolved.append(item)
        i += 1

    # Write patched manifest with all paths resolved to absolute
    # (patched manifest lives in work dir so relative paths would break)
    out_path = base_dir / cfg.get("output", "out/output.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    audio_abs = {}
    for k, v in cfg.get("audio", {}).items():
        if k in ("music", "voiceover") and v:
            resolved_path = base_dir / v
            audio_abs[k] = str(resolved_path) if resolved_path.exists() else v
        else:
            audio_abs[k] = v

    patched = work / "patched_manifest.yaml"
    cfg_patched = {**cfg, "timeline": resolved,
                   "output": str(out_path),
                   "audio": audio_abs}
    with open(patched, "w") as f:
        yaml.dump(cfg_patched, f, default_flow_style=False)

    result = assemble(str(patched), generate_missing=False)
    shutil.rmtree(work, ignore_errors=True)
    return result


# ── Quick Mode — One-liner ad generator (Phase 2) ─────────────────────────────
QUICK_STYLE_TEMPLATES = {
    "direct-response": {
        "color_grade": "none",
        "film_grain":  False,
        "prompts": [
            "ultra-close product shot, hands holding {product}, clean white background, professional commercial, 4K",
            "person looking directly at camera, excited expression, pointing at {product}, bright studio lighting",
            "bold price tag or CTA text overlay, {product} hero shot, clean modern design, social media ad",
        ],
        "cards": [
            {"lines": [{"text": "THE PROBLEM IS REAL", "font": "sans", "size": 72, "color": "white"}],
             "duration": 1.5},
            {"lines": [{"text": "{product}", "font": "bebas", "size": 100, "color": "gold"},
                       {"text": "CHANGES EVERYTHING", "font": "sans", "size": 48, "color": "white"}],
             "duration": 2.0},
            {"lines": [{"text": "GET YOURS NOW", "font": "bebas", "size": 110, "color": "white"}],
             "duration": 2.5},
        ],
    },
    "product-launch": {
        "color_grade": "teal_orange",
        "film_grain":  False,
        "prompts": [
            "mysterious teaser shot of {product} partially revealed from shadow, dramatic spotlight, product photography",
            "sleek macro shot of {product} features, detail textures, Apple-style product photography, pure white background",
            "lifestyle shot of person using {product} in aspirational setting, golden hour, natural",
        ],
        "cards": [
            {"lines": [{"text": "INTRODUCING", "font": "sans", "size": 52, "color": "grey"}],
             "duration": 1.5},
            {"lines": [{"text": "{product}", "font": "bebas", "size": 120, "color": "white"}],
             "duration": 2.5},
            {"lines": [{"text": "AVAILABLE NOW", "font": "sans", "size": 44, "color": "gold"}],
             "duration": 2.0},
        ],
    },
    "social": {
        "color_grade": "none",
        "film_grain":  False,
        "prompts": [
            "fast-cut hook shot, {product} hero angle, vibrant colors, social media style, vertical format",
            "{product} in lifestyle context, aspirational, clean",
            "bold CTA screen, {product} logo centered, clean white background",
        ],
        "cards": [
            {"lines": [{"text": "STOP SCROLLING", "font": "bebas", "size": 90, "color": "white"}],
             "duration": 1.2},
            {"lines": [{"text": "{product}", "font": "bebas", "size": 100, "color": "gold"}],
             "duration": 1.5},
        ],
    },
    "testimonial": {
        "color_grade": "vintage",
        "film_grain":  True,
        "prompts": [
            "documentary-style talking head shot, person speaking authentically, natural window light",
            "b-roll lifestyle footage showing {product} in real use, handheld, authentic, warm",
            "satisfied customer close-up, genuine smile, soft natural lighting",
        ],
        "cards": [
            {"lines": [{"text": '"THIS CHANGED MY LIFE"', "font": "serif", "size": 60, "color": "white"}],
             "duration": 2.5},
            {"lines": [{"text": "— REAL CUSTOMER", "font": "sans", "size": 32, "color": "grey"}],
             "duration": 1.5},
            {"lines": [{"text": "{product}", "font": "bebas", "size": 90, "color": "gold"},
                       {"text": "TRY IT TODAY", "font": "sans", "size": 42, "color": "white"}],
             "duration": 2.5},
        ],
    },
}

# Voiceover scripts for quick mode
QUICK_VO_SCRIPTS = {
    "direct-response": "You've been struggling with this problem long enough. {product} is the solution you've been waiting for. Try it now.",
    "product-launch":  "Introducing {product}. Designed for those who demand more.",
    "social":          "Meet {product}. Your life will never be the same.",
    "testimonial":     "{product} — trusted by thousands. Yours to try today.",
}


def quick_generate(product, style="direct-response", output_format="9x16",
                   duration=15, output_dir=None, generate_clips=True):
    """
    Generate a complete ad from just a product name — no YAML needed.

    Quick mode pipeline:
    1. Select template based on style
    2. Build auto-prompts from product name
    3. Generate 3 Veo 3.1 clips
    4. Generate 1 ElevenLabs voiceover line
    5. Assemble into complete ad

    Args:
        product:         Product/brand name (e.g. "BTC Cards")
        style:           Ad style: direct-response, product-launch, social, testimonial
        output_format:   Output format: 9x16, 16x9, 1x1, 4x5
        duration:        Target duration in seconds (15 or 30)
        output_dir:      Output directory (default: out/quick/)
        generate_clips:  If False, skips Veo (for YAML preview only)
    """
    # Normalize style name
    style = style.lower().replace("-", "").replace("_", "")
    style_map = {
        "directresponse": "direct-response",
        "productlaunch":  "product-launch",
        "social":         "social",
        "socialclip":     "social",
        "testimonial":    "testimonial",
    }
    style_key = style_map.get(style, "direct-response")
    template  = QUICK_STYLE_TEMPLATES.get(style_key, QUICK_STYLE_TEMPLATES["direct-response"])

    if output_format not in FORMAT_PRESETS:
        warn(f"Unknown format '{output_format}' — defaulting to 9x16")
        output_format = "9x16"

    fmt     = FORMAT_PRESETS[output_format]
    W, H    = fmt["w"], fmt["h"]
    veo_ar  = fmt.get("aspect_ratio", "16:9")

    output_dir = Path(output_dir or "out/quick")
    output_dir.mkdir(parents=True, exist_ok=True)
    clips_dir  = output_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    # Sanitize product name for filenames
    product_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in product.lower())
    out_mp4 = output_dir / f"{product_slug}_{style_key}_{output_format}.mp4"

    print(f"\n⚡ QUICK MODE — trailer-forge")
    print(f"   Product: {product}")
    print(f"   Style:   {style_key}")
    print(f"   Format:  {fmt['label']}")
    print(f"   Target:  {duration}s\n")

    # Build timeline from template
    prompts  = [p.replace("{product}", product) for p in template["prompts"]]
    cards    = []
    for card in template["cards"]:
        card_copy = dict(card)
        card_copy["lines"] = [
            {**ln, "text": ln["text"].replace("{product}", product)}
            for ln in card["lines"]
        ]
        cards.append(card_copy)

    # Time budget: split evenly between 3 clips + cards
    clip_dur  = 5  # seconds per clip (using Veo 4s minimum, trim to fit)
    if duration == 15:
        # 15s: 3 clips × ~3s + 2 cards × ~1.5s = ~12s + 2 black = ~15s
        clip_trim = [0, 3]
        n_clips   = 3
    elif duration == 30:
        # 30s: 3 clips × ~5s + 3 cards × ~2.5s = ~22.5s + blacks = ~27s
        clip_trim = [0, 5]
        n_clips   = 3
    else:
        clip_trim = [0, max(3, min(8, duration // 4))]
        n_clips   = min(3, len(prompts))

    # Generate Veo clips
    clip_files = []
    for i, prompt in enumerate(prompts[:n_clips]):
        clip_path = clips_dir / f"{product_slug}_clip_{i+1:02d}.mp4"
        if generate_clips:
            result = veo_generate(
                prompt     = prompt,
                out_path   = str(clip_path),
                duration_sec = clip_dur,
                aspect_ratio = veo_ar,
            )
            if result:
                clip_files.append(str(clip_path))
                ok(f"Clip {i+1}/3 ready")
            else:
                warn(f"Clip {i+1}/3 failed — will use black placeholder")
                clip_files.append(None)
        else:
            clip_files.append(str(clip_path) if clip_path.exists() else None)

    # Generate ElevenLabs voiceover
    vo_script = QUICK_VO_SCRIPTS.get(style_key, "").replace("{product}", product)
    vo_path   = output_dir / f"{product_slug}_vo.mp3"
    vo_generated = False

    if generate_clips and not vo_path.exists():
        vo_generated = _generate_elevenlabs_vo(vo_script, str(vo_path))

    # Build timeline
    timeline = []
    timeline.append({"type": "black", "duration": 0.3})

    # Interleave clips and cards based on style
    clip_idx = 0
    card_idx = 0

    if style_key == "direct-response":
        # Hook clip → card → solution clip → card → CTA clip → card
        pattern = ["clip", "card", "clip", "card", "clip", "card"]
    elif style_key == "product-launch":
        # Tease card → clip → feature clip → card → lifestyle clip → CTA card
        pattern = ["card", "clip", "clip", "card", "clip", "card"]
    elif style_key == "social":
        # Fast: card → clip → clip → card → clip
        pattern = ["card", "clip", "clip", "card", "clip"]
    else:  # testimonial
        # Quote card → clip → clip → card → clip → card
        pattern = ["card", "clip", "clip", "card", "clip", "card"]

    for step in pattern:
        if step == "clip" and clip_idx < len(clip_files):
            f = clip_files[clip_idx]
            clip_idx += 1
            timeline.append({
                "type":     "veo_clip" if f else "black",
                "file":     f or "",
                "trim":     clip_trim,
                "duration": clip_trim[1] - clip_trim[0] if not f else None,
                "fade_in":  0.0,
                "fade_out": 0.0,
            } if f else {"type": "black", "duration": clip_trim[1] - clip_trim[0]})
            timeline.append({"type": "black", "duration": 0.2})

        elif step == "card" and card_idx < len(cards):
            c = cards[card_idx]
            card_idx += 1
            timeline.append({**c, "type": "title_card", "fade_in": 0.2, "fade_out": 0.1})
            timeline.append({"type": "black", "duration": 0.2})

    # Build manifest dict
    manifest = {
        "title":       product,
        "resolution":  [W, H],
        "fps":         30,
        "color_grade": template["color_grade"],
        "film_grain":  template["film_grain"],
        "output":      str(out_mp4),
        "audio":       {},
        "timeline":    [item for item in timeline if item is not None],
    }

    if vo_generated and vo_path.exists():
        manifest["audio"]["voiceover"] = str(vo_path)
        manifest["audio"]["voice_vol"] = 1.0

    # Save manifest for transparency/editing
    manifest_path = output_dir / f"{product_slug}_{style_key}.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
    ok(f"Manifest saved: {manifest_path}")

    # Assemble
    print(f"\n  Assembling {out_mp4.name}…")
    result = assemble(str(manifest_path), generate_missing=False,
                      format_override=output_format)

    if result and Path(result).exists():
        size_kb = Path(result).stat().st_size // 1024
        ok(f"\n⚡ Quick mode complete → {result} ({size_kb}KB)")
        return result
    else:
        warn("Assembly failed — check logs above")
        return None


def _generate_elevenlabs_vo(script, out_path, voice_id="7Z12f9JBDnOACrQtUL9Q"):
    """Generate ElevenLabs TTS voiceover for quick mode."""
    import subprocess

    # Try Bitwarden for API key first
    key = None
    try:
        r = subprocess.run(
            'export BW_SESSION=$(cat /tmp/bw_session 2>/dev/null); '
            'bw list items --session "$BW_SESSION" --search "ElevenLabs API" 2>/dev/null '
            '| python3 -c "import json,sys; items=json.load(sys.stdin); '
            'print(items[0][\'login\'][\'password\'])" 2>/dev/null',
            shell=True, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            key = r.stdout.strip()
    except Exception:
        pass

    if not key:
        key = os.environ.get("ELEVENLABS_API_KEY")

    if not key:
        warn("ElevenLabs API key not found — skipping voiceover")
        return False

    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": key, "Content-Type": "application/json"}
        payload = {
            "text": script,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            Path(out_path).write_bytes(r.content)
            ok(f"Voiceover: {Path(out_path).name}")
            return True
        else:
            warn(f"ElevenLabs {r.status_code}: {r.text[:100]}")
            return False
    except Exception as exc:
        warn(f"ElevenLabs error: {exc}")
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(
        prog="trailer-forge",
        description="Build cinematic video trailers from YAML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  preview     Print timeline summary (no rendering)
  assemble    Render from existing clips only (no Veo calls)
  build       Render + generate missing Veo clips
  gen-clips   Generate Veo clips only, no render
  deliver     Export master to all platform formats
  export-srt  Convert Whisper JSON → SRT subtitle file
  export-me   Export Music & Effects stem (no dialogue)
  storyboard  Generate visual storyboard PNG from manifest
  broadcast   Assemble with broadcast elements (countdown, color bars, lower thirds)
  clip        YouTube → transcribe → detect → social-ready clips
  chapters    Auto-generate YouTube chapter markers from a video file
  quick       One-liner ad generator (no YAML needed)

format options (--format):
  16x9        1920×1080 — YouTube, desktop (default)
  9x16        1080×1920 — TikTok, Instagram Reels, Stories
  1x1         1080×1080 — Instagram feed, LinkedIn
  4x5         1080×1350 — Facebook/Instagram feed

quick mode examples:
  trailer-forge quick --product "BTC Cards" --style direct-response --format 9x16 --duration 15
  trailer-forge quick --product "My App" --style product-launch --format 16x9 --duration 30
        """
    )
    p.add_argument("command",
                   choices=["build","assemble","gen-clips","preview",
                            "deliver","export-srt","export-me",
                            "storyboard","broadcast","clip","chapters","quick"])
    p.add_argument("manifest", nargs="?",
                   help="YAML manifest / video path / Whisper JSON / YouTube URL (not needed for quick)")
    p.add_argument("--targets", nargs="+", default=["youtube", "telegram"],
                   metavar="PLATFORM",
                   help=f"Delivery platforms. Options: {', '.join(PLATFORM_SPECS)}")
    p.add_argument("--output", default=None,
                   help="Output path override")
    p.add_argument("--cols",   type=int, default=4,
                   help="Storyboard columns (default: 4)")
    p.add_argument("--top",    type=int, default=3,
                   help="Clipper: number of clips to extract (default: 3)")
    # Multi-format output (Phase 2)
    p.add_argument("--format",
                   help="Output format: 16x9 (default), 9x16 (TikTok/Reels), 1x1 (Instagram), 4x5 (FB feed). "
                        "For clip subcommand: vertical, vertical_blur, horizontal.",
                   default=None)
    p.add_argument("--zoom", type=float, default=1.0,
                   help="Clipper: zoom factor for vertical_blur foreground (default: 1.0). "
                        "Use 1.5-2.0 for talking-head video.")
    p.add_argument("--no-cache", action="store_true",
                   help="Clipper: disable transcript caching (use for concurrent runs)")
    # Quick mode (Phase 2)
    p.add_argument("--product", default=None,
                   help="[quick] Product/brand name (e.g. 'BTC Cards')")
    p.add_argument("--style", default="direct-response",
                   choices=["direct-response","product-launch","social","testimonial"],
                   help="[quick] Ad style template (default: direct-response)")
    p.add_argument("--duration", type=int, default=15,
                   help="[quick] Target duration in seconds: 15 or 30 (default: 15)")
    p.add_argument("--no-generate", action="store_true",
                   help="[quick] Skip Veo generation, preview YAML only")
    # chapters subcommand options
    p.add_argument("--silence", type=float, default=2.0,
                   help="[chapters] Minimum silence gap in seconds (default: 2.0)")
    p.add_argument("--noise-db", type=int, default=-40,
                   help="[chapters] Noise threshold in dB for silence detection (default: -40)")
    p.add_argument("--label-words", type=int, default=5,
                   help="[chapters] Max words to use for chapter label (default: 5)")
    args = p.parse_args()

    # Determine effective format for non-quick commands
    fmt_arg = args.format

    if   args.command == "preview":
        if not args.manifest: p.error("preview requires a manifest file")
        preview(args.manifest)
    elif args.command == "assemble":
        if not args.manifest: p.error("assemble requires a manifest file")
        assemble(args.manifest, generate_missing=False, format_override=fmt_arg)
    elif args.command == "build":
        if not args.manifest: p.error("build requires a manifest file")
        assemble(args.manifest, generate_missing=True, format_override=fmt_arg)
    elif args.command == "gen-clips":
        if not args.manifest: p.error("gen-clips requires a manifest file")
        assemble(args.manifest, generate_missing=True, format_override=fmt_arg)
    elif args.command == "deliver":
        if not args.manifest: p.error("deliver requires a video file")
        deliver(args.manifest, targets=args.targets)
    elif args.command == "export-srt":
        if not args.manifest: p.error("export-srt requires a Whisper JSON file")
        export_srt(args.manifest, args.output or "output.srt")
    elif args.command == "export-me":
        if not args.manifest: p.error("export-me requires a manifest file")
        export_me(args.manifest, args.output)
    elif args.command == "storyboard":
        if not args.manifest: p.error("storyboard requires a manifest file")
        storyboard(args.manifest, args.output, cols=args.cols)
    elif args.command == "broadcast":
        if not args.manifest: p.error("broadcast requires a manifest file")
        assemble_broadcast(args.manifest, generate_missing=False)
    elif args.command == "clip":
        if not args.manifest: p.error("clip requires a video/URL argument")
        sys.path.insert(0, str(SCRIPT_DIR / "tools"))
        from clipper import run_clipper
        clip_fmt = fmt_arg if fmt_arg in ("vertical","vertical_blur","horizontal") else "vertical_blur"
        run_clipper(args.manifest, top_n=args.top, fmt=clip_fmt,
                    zoom=args.zoom, out_dir=Path(args.output or "out/clips"),
                    cache=not getattr(args, "no_cache", False))
    elif args.command == "chapters":
        if not args.manifest: p.error("chapters requires a video file")
        sys.path.insert(0, str(SCRIPT_DIR / "tools"))
        from chapters import run_chapters
        run_chapters(
            video_path      = args.manifest,
            min_silence_sec = args.silence,
            noise_db        = args.noise_db,
            max_label_words = args.label_words,
        )
    elif args.command == "quick":
        if not args.product:
            p.error("quick mode requires --product (e.g. --product 'BTC Cards')")
        quick_generate(
            product        = args.product,
            style          = args.style,
            output_format  = fmt_arg or "9x16",
            duration       = args.duration,
            output_dir     = args.output,
            generate_clips = not args.no_generate,
        )
