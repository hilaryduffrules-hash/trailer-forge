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

Requirements:
  pip install pillow pyyaml requests
  cd canvas_renderer && npm install   (Node.js renderer — better text quality)
  ffmpeg in PATH

Optional:
  GEMINI_API_KEY  → Veo 2 clip generation
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
CANVAS_RENDERER = SCRIPT_DIR / "canvas_renderer" / "render_card.js"

# ── Constants ─────────────────────────────────────────────────────────────────
VEO_BASE  = "https://generativelanguage.googleapis.com/v1beta"
VEO_MODEL = "veo-2.0-generate-001"

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
    path = FONT_BEBAS if family == "bebas" else FONT_SANS
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

def render_title_card(config, W, H, out_png):
    bar_h   = int(H * 0.1)
    safe_cy = (bar_h + H - bar_h) // 2
    max_w   = int(W * 0.84)
    gap     = 14
    img     = Image.new("RGB", (W, H), COLOURS["darkbg"])
    draw    = ImageDraw.Draw(img)
    lines   = config.get("lines", [])

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


def render_main_title(title, tagline, W, H, out_png):
    bar_h = int(H * 0.1)
    mid   = H // 2
    max_w = int(W * 0.9)
    img   = Image.new("RGB", (W, H), (3, 3, 12))
    draw  = ImageDraw.Draw(img)

    draw.text((W//2, int(H * 0.21)), "SUMMER  2026",
              font=load_font("sans", 52), fill=COLOURS["gold"], anchor="mm")
    rx1, rx2 = int(W * 0.18), int(W * 0.82)
    draw.line([(rx1, mid - 105), (rx2, mid - 105)], fill=COLOURS["gold"], width=2)
    draw.line([(rx1, mid + 100), (rx2, mid + 100)], fill=COLOURS["gold"], width=2)
    draw.text((W//2, mid - 62), "T H E",
              font=load_font("bebas", 88), fill=(220, 220, 220), anchor="mm")

    main_font, _ = _autofit_font(draw, title, "bebas", 290, max_w)
    img  = _text_glow(img, W//2, mid + 40, title, main_font, COLOURS["white"],
                      glow_color=(220, 220, 255), radius=30)
    draw = ImageDraw.Draw(img)

    if tagline:
        draw.text((W//2, int(H * 0.75)), f'"{tagline}"',
                  font=load_font("sans", 36), fill=COLOURS["grey"], anchor="mm")
    draw.text((W//2, int(H * 0.82)), "RATED PG-13  ·  FOR CONTENT",
              font=load_font("sans", 22), fill=(75, 75, 95), anchor="mm")

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
                color_grade="none", fade_in=0.3, fade_out=0.3):
    duration = trim_end - trim_start
    bar_h    = int(H * 0.1)
    grade    = COLOR_GRADES.get(color_grade, "")
    scale    = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
    bars     = f"drawbox=y=0:w={W}:h={bar_h}:color=black:t=fill,drawbox=y={H-bar_h}:w={W}:h={bar_h}:color=black:t=fill"
    fi_f     = f"fade=t=in:st=0:d={fade_in}" if fade_in else ""
    fo_f     = f"fade=t=out:st={duration-fade_out}:d={fade_out}" if fade_out else ""
    vf       = ",".join(p for p in [scale, grade, bars, fi_f, fo_f] if p)
    run(f'ffmpeg -y -ss {trim_start} -i "{src}" -t {duration} '
        f'-r {fps} -vf "{vf}" '
        f'-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "{out_mp4}"')

# ── Veo 2 clip generation ──────────────────────────────────────────────────────
def veo_generate(prompt, out_path, duration_sec=5):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        warn("GEMINI_API_KEY not set — skipping Veo generation")
        return None
    if Path(out_path).exists() and Path(out_path).stat().st_size > 50_000:
        log(f"Cache hit: {Path(out_path).name}")
        return out_path

    log(f"Generating clip: {Path(out_path).stem} …")
    r = requests.post(
        f"{VEO_BASE}/models/{VEO_MODEL}:predictLongRunning?key={key}",
        json={"instances": [{"prompt": prompt}],
              "parameters": {"aspectRatio": "16:9", "durationSeconds": duration_sec}}
    )
    if r.status_code != 200:
        warn(f"Veo {r.status_code}: {r.text[:200]}")
        return None
    op = r.json()["name"]
    for _ in range(60):
        time.sleep(10)
        poll = requests.get(f"{VEO_BASE}/{op}?key={key}").json()
        if poll.get("done"):
            samples = poll.get("response", {}).get("generateVideoResponse", {}).get("generatedSamples", [])
            if not samples:
                warn(f"No samples for {Path(out_path).stem}")
                return None
            uri  = samples[0]["video"]["uri"]
            url  = f"{uri}&key={key}" if "?" in uri else f"{uri}?key={key}"
            data = requests.get(url).content
            Path(out_path).write_bytes(data)
            ok(f"{Path(out_path).name} ({len(data)//1024}KB)")
            return out_path
    warn(f"Veo timeout: {Path(out_path).stem}")
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
def assemble(manifest_path, generate_missing=True):
    manifest_path = Path(manifest_path).resolve()
    base_dir = manifest_path.parent

    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)

    W, H   = cfg.get("resolution", [1920, 1080])
    fps    = cfg.get("fps", 30)
    grade  = cfg.get("color_grade", "teal_orange")
    out    = base_dir / cfg.get("output", "output.mp4")
    audio  = cfg.get("audio", {})
    grain  = cfg.get("film_grain", True)
    auto_sfx = audio.get("sfx", "none") == "auto"

    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tf_"))
    timeline_items = cfg.get("timeline", [])

    segments, total_dur = [], 0.0
    print(f"\n🎬 TRAILER FORGE")
    print(f"   {W}×{H} @ {fps}fps  |  Grade: {grade}  |  Grain: {'on' if grain else 'off'}  |  SFX: {'auto' if auto_sfx else 'off'}\n")

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
                render_title_card(item, W, H, str(png))
            png_to_seg(str(png), dur, fps, str(seg_out), fi, fo)
            label = " | ".join(str(l.get("text","")) for l in item.get("lines",[]))
            print(f"— {dur:.1f}s — \"{label[:50]}\"")

        elif kind == "main_title":
            dur     = float(item.get("duration", 6.0))
            title   = item.get("title", "UNTITLED")
            tagline = item.get("tagline", "")
            png     = work / f"main_{i}.png"
            if not render_with_node("main_title", {"title": title, "tagline": tagline}, W, H, str(png)):
                render_main_title(title, tagline, W, H, str(png))
            png_to_seg(str(png), dur, fps, str(seg_out), fi, fo)
            print(f"— {dur:.1f}s — \"{title}\"")

        elif kind == "veo_clip":
            src    = base_dir / item.get("file", "")
            trim   = item.get("trim", [0, 5])
            dur    = float(trim[1]) - float(trim[0])
            prompt = resolve_veo_prompt(item)

            if not src.exists() and generate_missing:
                src.parent.mkdir(parents=True, exist_ok=True)
                veo_generate(prompt, str(src))

            if src.exists():
                clip_to_seg(str(src), float(trim[0]), float(trim[1]),
                            fps, W, H, str(seg_out), grade, fi, fo)
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
        """
    )
    p.add_argument("command",
                   choices=["build","assemble","gen-clips","preview","deliver","export-srt"])
    p.add_argument("manifest",
                   help="Trailer YAML manifest, or video file path for deliver, or Whisper JSON for export-srt")
    p.add_argument("--targets", nargs="+", default=["youtube", "telegram"],
                   metavar="PLATFORM",
                   help=f"Delivery targets (default: youtube telegram). Options: {', '.join(PLATFORM_SPECS)}")
    p.add_argument("--output", default="output.srt",
                   help="Output SRT path (for export-srt command)")
    args = p.parse_args()

    if   args.command == "preview":    preview(args.manifest)
    elif args.command == "assemble":   assemble(args.manifest, generate_missing=False)
    elif args.command == "build":      assemble(args.manifest, generate_missing=True)
    elif args.command == "gen-clips":  assemble(args.manifest, generate_missing=True)
    elif args.command == "deliver":    deliver(args.manifest, targets=args.targets)
    elif args.command == "export-srt": export_srt(args.manifest, args.output)
