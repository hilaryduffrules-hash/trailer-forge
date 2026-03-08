#!/usr/bin/env python3
"""
trailer-forge — Build cinematic video trailers from a YAML manifest.

Usage:
  python3 trailer_forge.py assemble  trailer.yaml   # assemble from existing clips
  python3 trailer_forge.py build     trailer.yaml   # assemble + generate missing Veo clips
  python3 trailer_forge.py preview   trailer.yaml   # print timeline summary
  python3 trailer_forge.py gen-clips trailer.yaml   # generate Veo clips only

Requirements:
  pip install pillow pyyaml requests
  cd canvas_renderer && npm install   (for Node.js renderer — higher quality text)
  ffmpeg in PATH

Optional (for AI clip generation):
  GEMINI_API_KEY env var  → enables Veo 2 clip generation

See README.md and docs/YAML_REFERENCE.md for full details.
"""

import os, sys, json, time, shutil, tempfile, subprocess, argparse
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

# Font discovery: repo-bundled first, then common system paths
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
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Windows/Fonts/arialbd.ttf",
)
CANVAS_RENDERER = SCRIPT_DIR / "canvas_renderer" / "render_card.js"

# ── Veo ───────────────────────────────────────────────────────────────────────
VEO_BASE  = "https://generativelanguage.googleapis.com/v1beta"
VEO_MODEL = "veo-2.0-generate-001"

# ── Color grades ──────────────────────────────────────────────────────────────
COLOR_GRADES = {
    "none": "",
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

def dur_str(sec): return f"{int(sec//60):02d}:{sec%60:05.2f}"

# ── Font loading ──────────────────────────────────────────────────────────────
def load_font(family, size):
    path = FONT_BEBAS if family == "bebas" else FONT_SANS
    if path and Path(path).exists():
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

# ── Title card rendering (Pillow fallback) ────────────────────────────────────
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
        draw.rectangle([0, 0, W, bar_h],      fill=COLOURS["black"])
        draw.rectangle([0, H-bar_h, W, H],    fill=COLOURS["black"])
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

    total_h = sum(it["h"] for it in items) + gap * (len(items) - 1)
    block_y = safe_cy - total_h // 2
    rule_pad, rx1, rx2 = 20, int(W * 0.12), int(W * 0.88)
    draw.line([(rx1, block_y - rule_pad), (rx2, block_y - rule_pad)],
              fill=COLOURS["gold"], width=2)
    draw.line([(rx1, block_y + total_h + rule_pad), (rx2, block_y + total_h + rule_pad)],
              fill=COLOURS["gold"], width=2)

    cy = block_y
    for it in items:
        mid_cy = cy + it["h"] // 2
        if it["clr"] == COLOURS["gold"]:
            img  = _text_glow(img, W//2, mid_cy, it["txt"], it["font"], it["clr"],
                              glow_color=(180, 140, 20), radius=22)
            draw = ImageDraw.Draw(img)
        else:
            draw.text((W//2 + 2, mid_cy + 3), it["txt"], font=it["font"],
                      fill=(0, 0, 0), anchor="mm")
            draw.text((W//2, mid_cy), it["txt"], font=it["font"],
                      fill=it["clr"], anchor="mm")
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
    draw.text((W//2, int(H * 0.82)),
              "RATED PG-13  ·  FOR CONTENT",
              font=load_font("sans", 22), fill=(75, 75, 95), anchor="mm")

    img  = _add_vignette(img, W, H, strength=160, power=1.6)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,       0, W,    bar_h], fill=COLOURS["black"])
    draw.rectangle([0, H-bar_h, W,        H], fill=COLOURS["black"])
    img.save(out_png)

def render_black(W, H, out_png):
    Image.new("RGB", (W, H), (0, 0, 0)).save(out_png)

# ── Node.js canvas renderer (preferred — better text quality) ─────────────────
def render_with_node(type_, config_dict, W, H, out_png):
    if not CANVAS_RENDERER.exists():
        return False
    r = subprocess.run(
        ["node", str(CANVAS_RENDERER),
         "--type", type_,
         "--config", json.dumps(config_dict),
         "--output", out_png,
         "--width", str(W), "--height", str(H)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        warn(f"Node renderer: {r.stderr[:120]}")
        return False
    return True

# ── PNG → video segment ───────────────────────────────────────────────────────
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
    fi_f     = f"fade=t=in:st=0:d={fade_in}"  if fade_in  else ""
    fo_f     = f"fade=t=out:st={duration-fade_out}:d={fade_out}" if fade_out else ""
    vf       = ",".join(p for p in [scale, grade, bars, fi_f, fo_f] if p)
    run(f'ffmpeg -y -ss {trim_start} -i "{src}" -t {duration} '
        f'-r {fps} -vf "{vf}" '
        f'-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "{out_mp4}"')

# ── Veo 2 clip generation ─────────────────────────────────────────────────────
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
            samples = (poll.get("response", {})
                          .get("generateVideoResponse", {})
                          .get("generatedSamples", []))
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

# ── Audio mixing ──────────────────────────────────────────────────────────────
def mix_audio(music, voice, out, duration, music_vol=0.35, voice_vol=1.0, voice_delay=0.0):
    delay_ms = int(voice_delay * 1000)
    filt = (f"[0]volume={music_vol}[m];"
            f"[1]volume={voice_vol},adelay={delay_ms}|{delay_ms}[v];"
            f"[m][v]amix=inputs=2:duration=first:dropout_transition=2[out]")
    run(f'ffmpeg -y -i "{music}" -i "{voice}" '
        f'-filter_complex "{filt}" -map "[out]" '
        f'-t {duration} -ar 44100 "{out}"')

# ── Assembly ──────────────────────────────────────────────────────────────────
def assemble(manifest_path, generate_missing=True):
    manifest_path = Path(manifest_path).resolve()
    base_dir = manifest_path.parent

    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)

    W, H    = cfg.get("resolution", [1920, 1080])
    fps     = cfg.get("fps", 30)
    grade   = cfg.get("color_grade", "teal_orange")
    out     = base_dir / cfg.get("output", "output.mp4")
    audio   = cfg.get("audio", {})
    grain   = cfg.get("film_grain", True)

    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tf_"))

    segments, total_dur = [], 0.0
    print(f"\n🎬 TRAILER FORGE")
    print(f"   {W}×{H} @ {fps}fps  |  Grade: {grade}  |  Grain: {'on' if grain else 'off'}\n")

    for i, item in enumerate(cfg.get("timeline", [])):
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
            prompt = item.get("prompt", "")

            if not src.exists() and prompt and generate_missing:
                src.parent.mkdir(parents=True, exist_ok=True)
                veo_generate(prompt, str(src))

            if src.exists():
                clip_to_seg(str(src), float(trim[0]), float(trim[1]),
                            fps, W, H, str(seg_out), grade, fi, fo)
                print(f"— {dur:.1f}s ← {src.name}")
            else:
                warn(f"Missing: {src.name} — substituting black")
                render_black(W, H, str(work/f"black_{i}.png"))
                png_to_seg(str(work/f"black_{i}.png"), dur, fps, str(seg_out), 0, 0)
                print(f"— {dur:.1f}s [BLACK]")
        else:
            print(f"unknown type '{kind}', skipping"); continue

        segments.append(str(seg_out))
        total_dur += float(item.get("duration",
                                    (float(item["trim"][1]) - float(item["trim"][0]))
                                    if kind == "veo_clip" else 3.0))

    # Concatenate
    print(f"\n  Concatenating {len(segments)} segments ({dur_str(total_dur)})…")
    concat_txt = work / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{s}'" for s in segments))

    no_audio = work / "no_audio.mp4"
    grain_vf = "noise=alls=6:allf=t,unsharp=3:3:0.4:3:3:0.0" if grain else ""
    vf_arg   = f'-vf "{grain_vf}"' if grain_vf else ""
    run(f'ffmpeg -y -f concat -safe 0 -i "{concat_txt}" '
        f'{vf_arg} -c:v libx264 -preset slow -crf 19 -pix_fmt yuv420p '
        f'-movflags +faststart "{no_audio}"')

    # Audio
    music_path = audio.get("music", "")
    voice_path = audio.get("voiceover", "")
    if music_path and voice_path:
        mp, vp = base_dir / music_path, base_dir / voice_path
        if mp.exists() and vp.exists():
            print(f"  Mixing audio…")
            mixed = work / "mixed.aac"
            mix_audio(str(mp), str(vp), str(mixed), total_dur,
                      float(audio.get("music_vol", 0.35)),
                      float(audio.get("voice_vol", 1.0)),
                      float(audio.get("voice_delay", 0.0)))
            run(f'ffmpeg -y -i "{no_audio}" -i "{mixed}" '
                f'-c:v copy -c:a aac -b:a 192k -shortest '
                f'-movflags +faststart "{out}"')
        else:
            warn("Audio files not found — outputting silent video")
            shutil.copy(no_audio, out)
    else:
        shutil.copy(no_audio, out)

    shutil.rmtree(work, ignore_errors=True)
    size_kb = out.stat().st_size // 1024
    ok(f"Done → {out} ({size_kb}KB, ~{dur_str(total_dur)})")
    return str(out)

# ── Preview ───────────────────────────────────────────────────────────────────
def preview(manifest_path):
    with open(manifest_path) as f:
        cfg = yaml.safe_load(f)
    W, H = cfg.get("resolution", [1920, 1080])
    print(f"\n📋 TIMELINE: {manifest_path}")
    print(f"   {W}×{H} @ {cfg.get('fps',30)}fps | Grade: {cfg.get('color_grade','none')}\n")
    print(f"   {'#':>3}  {'START':>7}  {'END':>7}  {'TYPE':<12}  {'LABEL'}")
    print(f"   {'─'*60}")
    t = 0.0
    for i, item in enumerate(cfg.get("timeline", [])):
        kind = item.get("type", "?")
        trim = item.get("trim", [0, 5])
        dur  = (float(trim[1]) - float(trim[0])) if kind == "veo_clip" else float(item.get("duration", 3))
        if kind == "title_card":
            label = " | ".join(str(l.get("text","")) for l in item.get("lines",[]))[:40]
        elif kind == "veo_clip": label = item.get("file", "?")
        elif kind == "main_title": label = item.get("title", "?")
        else: label = ""
        print(f"   {i+1:>3}  {dur_str(t):>7}  {dur_str(t+dur):>7}  {kind:<12}  {label}")
        t += dur
    print(f"\n   Total: {dur_str(t)}")

# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="trailer-forge",
                                description="Build cinematic video trailers from YAML")
    p.add_argument("command", choices=["build", "assemble", "gen-clips", "preview"])
    p.add_argument("manifest", help="Path to trailer YAML manifest")
    args = p.parse_args()

    if   args.command == "preview":   preview(args.manifest)
    elif args.command == "assemble":  assemble(args.manifest, generate_missing=False)
    else:                             assemble(args.manifest, generate_missing=True)

# ── PLATFORM DELIVERY (NEW) ───────────────────────────────────────────────────
def deliver(video_path, targets=None, **kwargs):
    """
    Multi-platform delivery — one master → all output formats.
    
    targets: list of ["youtube", "telegram", "instagram_feed", "instagram_reel", "tiktok", "theatrical"]
    """
    if not targets:
        targets = ["youtube", "telegram"]
    
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    
    out_dir = video_path.parent / "delivered"
    out_dir.mkdir(exist_ok=True)
    
    deliveries = {
        "youtube":         {"res": "1920x1080", "crf": 18, "container": "mp4", "audio": "192k"},
        "telegram":        {"res": "1280x720",  "crf": 30, "container": "mp4", "audio": "128k", "max_mb": 15},
        "instagram_feed":  {"res": "1080x1080", "crf": 26, "container": "mp4", "audio": "128k"},
        "instagram_reel":  {"res": "1080x1920", "crf": 26, "container": "mp4", "audio": "128k"},
        "tiktok":          {"res": "1080x1920", "crf": 26, "container": "mp4", "audio": "128k", "max_mb": 287},
    }
    
    print(f"\n📦 MULTI-PLATFORM DELIVERY")
    print(f"   Master: {video_path.name}\n")
    
    for target in targets:
        if target not in deliveries:
            warn(f"Unknown target '{target}'"); continue
        
        spec = deliveries[target]
        out_file = out_dir / f"{video_path.stem}_{target}.mp4"
        res = spec["res"]
        crf = spec["crf"]
        abr = spec["audio"]
        
        print(f"  [{target}] {res} (crf={crf}, audio={abr})…", flush=True)
        run(f'ffmpeg -y -i "{video_path}" '
            f'-vf "scale={res.split("x")[0]}:{res.split("x")[1]}:force_original_aspect_ratio=decrease,pad={res.split("x")[0]}:{res.split("x")[1]}:(ow-iw)/2:(oh-ih)/2" '
            f'-c:v libx264 -preset slow -crf {crf} -pix_fmt yuv420p '
            f'-c:a aac -b:a {abr} '
            f'-movflags +faststart -y "{out_file}"')
        
        size_mb = out_file.stat().st_size / (1024*1024)
        ok(f"{out_file.name} ({size_mb:.1f}MB)")
    
    print(f"\n✅ Delivered to: {out_dir}/")

# ── SUBTITLE EXPORT (NEW) ─────────────────────────────────────────────────────
def export_srt(voiceover_json, output_srt="output.srt"):
    """
    Generate SRT subtitles from Whisper JSON output.
    
    Usage: export_srt("whisper_out/voiceover.json", "subtitles.srt")
    """
    try:
        import json
    except:
        print("JSON not available"); return
    
    with open(voiceover_json) as f:
        data = json.load(f)
    
    def ts(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    
    lines = []
    i = 1
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            word = w["word"].strip()
            start = w["start"]
            end = w["end"]
            lines.append(f"{i}\n{ts(start)} --> {ts(end)}\n{word}\n")
            i += 1
    
    Path(output_srt).write_text("\n".join(lines))
    ok(f"Subtitle export: {output_srt} ({i-1} words)")

# ── EXTENDED CLI ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="trailer-forge",
                                description="Build cinematic video trailers from YAML")
    p.add_argument("command",
                   choices=["build","assemble","gen-clips","preview","deliver","export-srt"])
    p.add_argument("manifest", nargs="?", help="Path to trailer YAML manifest")
    p.add_argument("--targets", nargs="+", default=["youtube"],
                   help="Delivery targets: youtube telegram instagram_feed instagram_reel tiktok")
    p.add_argument("--output", default="output.srt", help="SRT output path")
    args = p.parse_args()

    if   args.command == "preview":
        preview(args.manifest)
    elif args.command == "assemble":
        assemble(args.manifest, generate_missing=False)
    elif args.command == "deliver":
        deliver(args.manifest, targets=args.targets)
    elif args.command == "export-srt":
        export_srt(args.manifest, args.output)
    else:
        assemble(args.manifest, generate_missing=True)
