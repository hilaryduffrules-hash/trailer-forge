#!/usr/bin/env python3
"""
sync_yaml.py — Extract Whisper word timestamps and calculate frame-perfect
segment durations for trailer-forge YAML manifests.

The key insight: in trailer-forge, segments are sequential. The cumulative
sum of all preceding segment durations must equal the Whisper timestamp for
the word you want to appear at that cut. This tool does the math for you.

Usage:
    # Print all word timestamps
    python3 tools/sync_yaml.py whisper_out/voiceover.json

    # Find specific cue words and compute segment durations
    python3 tools/sync_yaml.py whisper_out/voiceover.json \\
        --cues "wonders=SOME BUILD WONDERS." \\
               "trebuchet=SOME GET TREBUCHET'D." \\
               "best=BY THEIR BEST FRIEND." \\
               --offset 0.2

    # Output YAML stubs for each cue
    python3 tools/sync_yaml.py whisper_out/voiceover.json \\
        --cues "wonders:SOME BUILD WONDERS." "night:ONE NIGHT." \\
               "legendary:ONE LEGENDARY GAME." \\
        --yaml
"""

import json
import sys
import argparse
from pathlib import Path


def load_words(whisper_json: str) -> list[dict]:
    """Load word-level timestamps from Whisper JSON output."""
    data = json.loads(Path(whisper_json).read_text())
    words = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word":  w["word"].strip(),
                "start": round(w["start"], 3),
                "end":   round(w["end"],   3),
            })
    return words


def find_cue(words: list[dict], target: str) -> tuple[float, float] | None:
    """
    Find the first word matching `target` (case-insensitive substring).
    Returns (start, end) or None.
    """
    target_lower = target.lower()
    for w in words:
        if target_lower in w["word"].lower():
            return w["start"], w["end"]
    return None


def print_all_words(words: list[dict]):
    """Print full word table with timestamps."""
    print(f"\n{'START':>8}  {'END':>8}  WORD")
    print("-" * 40)
    for w in words:
        print(f"  {w['start']:6.3f}s  {w['end']:6.3f}s  {w['word']}")


def compute_durations(cue_list: list[tuple[str, str, str]],
                      words: list[dict],
                      offset: float = 0.0) -> list[dict]:
    """
    Given a list of (word_to_find, label, text), compute the segment duration
    for each cue so it starts at exactly that word's timestamp.

    cue_list: [(search_word, label, card_text), ...]
    offset:   initial time offset (e.g. 0.2 for a leading black segment)

    Returns list of segment dicts with:
        start, duration, ends_at, label, text, hit_word, hit_start
    """
    results = []
    prev_end = offset

    for search_word, label, text in cue_list:
        hit = find_cue(words, search_word)
        if hit is None:
            print(f"  ⚠️  Could not find '{search_word}' in Whisper output", file=sys.stderr)
            continue
        hit_start, hit_end = hit
        duration = round(hit_start - prev_end, 3)
        if duration <= 0:
            print(
                f"  ⚠️  '{search_word}' at {hit_start}s would require negative duration "
                f"(prev_end={prev_end}s) — adjust cue order or add leading clip",
                file=sys.stderr,
            )
            duration = 0.001
        results.append({
            "start":     prev_end,
            "duration":  duration,
            "ends_at":   round(prev_end + duration, 3),
            "label":     label,
            "text":      text,
            "hit_word":  search_word,
            "hit_start": hit_start,
        })
        prev_end = round(prev_end + duration, 3)

    return results


def print_timing_table(segments: list[dict]):
    """Print a human-readable sync timing table."""
    print(f"\n{'START':>8}  {'DUR':>6}  {'ENDS':>8}  {'SYNC':>8}  SEGMENT")
    print("-" * 72)
    for s in segments:
        sync_marker = f"← '{s['hit_word']}' ✓" if abs(s['ends_at'] - s['hit_start']) < 0.01 else \
                      f"← '{s['hit_word']}' ({s['hit_start']:.3f}s)"
        print(f"  {s['start']:6.3f}s  {s['duration']:5.3f}s  {s['ends_at']:6.3f}s  {sync_marker:20s}  {s['label']}")


def print_yaml_stubs(segments: list[dict], offset: float):
    """Print YAML title_card stubs for each segment."""
    print(f"\n# ─── GENERATED YAML STUBS ──────────────────────────────────────────")
    if offset > 0:
        print(f"\n  - type: black")
        print(f"    duration: {offset:.2f}  # leading offset")
    for s in segments:
        print(f"\n  # {s['start']:.2f}s ✓ — VO '{s['hit_word']}' at {s['hit_start']:.3f}s")
        print(f"  - type: title_card")
        print(f"    duration: {s['duration']:.3f}  # tune: adjust to set next card's start")
        print(f"    lines:")
        print(f'      - text: "{s["text"]}"')
        print(f"        font: bebas")
        print(f"        size: 80")
        print(f"        color: \"#e8d5a3\"")


def main():
    parser = argparse.ArgumentParser(
        description="Extract Whisper timestamps and compute frame-perfect segment durations."
    )
    parser.add_argument("whisper_json", help="Path to Whisper output JSON (word_timestamps=True)")
    parser.add_argument(
        "--cues", nargs="+", metavar="WORD:LABEL:TEXT",
        help=(
            "Cue definitions: word_to_find:Label:Card text. "
            "Each segment's duration is computed so it ends at that word's timestamp. "
            "Example: --cues 'wonders:WONDERS CARD:SOME BUILD WONDERS.' 'night:NIGHT CARD:ONE NIGHT.'"
        ),
    )
    parser.add_argument("--offset", type=float, default=0.0,
                        help="Initial time offset in seconds (e.g. 0.2 for a black segment). Default: 0")
    parser.add_argument("--yaml", action="store_true", help="Print YAML stubs for each segment")
    args = parser.parse_args()

    words = load_words(args.whisper_json)

    if not args.cues:
        print_all_words(words)
        return

    cue_list = []
    for cue in args.cues:
        parts = cue.split(":", 2)
        if len(parts) < 2:
            print(f"  ⚠️  Invalid cue format '{cue}' — expected WORD:LABEL or WORD:LABEL:TEXT", file=sys.stderr)
            continue
        search_word = parts[0]
        label       = parts[1]
        text        = parts[2] if len(parts) > 2 else label
        cue_list.append((search_word, label, text))

    segments = compute_durations(cue_list, words, offset=args.offset)
    print_timing_table(segments)

    if args.yaml:
        print_yaml_stubs(segments, args.offset)

    # Summary
    total = args.offset + sum(s["duration"] for s in segments)
    print(f"\n  Computed {len(segments)} segments | cumulative: {total:.3f}s | VO total: {words[-1]['end']:.3f}s")


if __name__ == "__main__":
    main()
