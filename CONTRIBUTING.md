# Contributing to trailer-forge

Thanks for wanting to make this better. Keep it simple, keep it fun.

## Getting Started

```bash
git clone https://github.com/hilaryduffrules-hash/trailer-forge
cd trailer-forge
pip install pillow pyyaml requests
cd canvas_renderer && npm install && cd ..
```

## What's Worth Contributing

- **New color grades** — add to `COLOR_GRADES` dict in `trailer_forge.py`
- **New segment types** — implement `render_*` + handle in `assemble()`
- **Better font fallbacks** — especially Windows/macOS paths in `_find_font()`
- **SRT/subtitle overlay** as a first-class segment type
- **Image slideshow** segment type (Ken Burns effect via ffmpeg `zoompan`)
- **Canvas renderer improvements** — `render_card.js` always wins on quality
- **Example YAMLs** — more genres, more vibes

## Coding Style

- Keep it readable over clever
- New segment types go in both the Pillow renderer and the Node canvas renderer
- No external services added without making them clearly optional
- No API keys in code — env vars only
- Test with `python3 trailer_forge.py preview examples/simple.yaml` before submitting

## Pull Request Checklist

- [ ] Works with `assemble` (no API keys required for basic use)
- [ ] New YAML fields documented in `docs/YAML_REFERENCE.md`
- [ ] No hardcoded paths
- [ ] No personal/private information

## Issues

Open issues for bugs, feature requests, and questions. Be specific — include
the YAML snippet and the ffmpeg error if relevant.
