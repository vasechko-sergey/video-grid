"""Titles writer (design docs/specs/2026-07-13-titles-design.md, §5.16). The thin
mechanical half: from a Spec + the reel length, draft a Titles (the brief's on-screen
text, opening the reel) and write TITLES.json + TITLES.md. Judgment — the
actual words / timing / style — is the titles SKILL's; this is the starting
projection. Mirror of reel_brief.py: contract in lib, driver here."""
import argparse
import json
import math
from pathlib import Path

from scripts.lib.spec import Spec
from scripts.lib import safezones
from scripts.lib.titles import Title, Titles, refuse_zone_overflow


def build_titles(spec: Spec, total_s: float) -> Titles:
    """A starting Titles from a Spec: the brief's on-screen text, opening the reel at the
    top for its first 3s (or the whole reel, if shorter), in font='system' so the draft
    renders on any box. No text in the brief, no titles.

    ONLY spec.text. hook and ending name the opening and closing SHOTS — notes for the
    editor, not copy: the second real run's brief carried source file names and window
    numbers in them, and the old draft put those on screen (retro 2026-10-16 S2).
    total_s (reel length) is the caller's — EDL sum or a probed master — build_titles
    never guesses it."""
    if (isinstance(total_s, bool) or not isinstance(total_s, (int, float))
            or not math.isfinite(total_s) or total_s <= 0):
        raise ValueError(
            f"build_titles total_s must be a positive finite number (seconds), got {total_s!r}")
    if not spec.text.strip():
        return Titles(items=())
    return Titles(items=(Title(text=spec.text, start=0.0, dur=min(3.0, total_s), pos="top"),))


def check_titles(titles: Titles, platform: str = "") -> dict:
    """Refuse a TITLES.json whose ink would land outside the platform's safe zone.

    `build_filterchain` is the chokepoint and keeps the refusal that matters, but it
    runs at DELIVER — after every episode is rendered and the master assembled, so the
    author learns at the most expensive possible moment. Same predicate, same message,
    at the stage where the fix is a one-line edit.

    It has to be its own command rather than a flag on `build`: `build` only ever
    drafts single-line titles, which cannot overflow. The overflow arrives when the
    author hand-edits the JSON afterwards, exactly as the titles SKILL tells them to."""
    refuse_zone_overflow(titles.items, platform)
    return {"status": "ok", "count": len(titles.items),
            "platform": safezones.zone_name(platform)}


def write_titles(titles: Titles, out_dir: str) -> dict:
    """Write TITLES.json + TITLES.md together into out_dir. Returns a status dict."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    tj, tm = Path(out_dir) / "TITLES.json", Path(out_dir) / "TITLES.md"
    titles.write(tj)
    tm.write_text(titles.to_markdown())
    return {"status": "written", "titles": str(tj), "md": str(tm), "count": len(titles.items)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="write TITLES.json + TITLES.md — the reel titles (§5.16)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="draft TITLES from SPEC + reel length",
                       description="draft TITLES.json + TITLES.md from SPEC's on-screen "
                                   "text and the reel's length — the words open the reel at "
                                   "the top; hook and ending are shots, never copy.")
    b.add_argument("--spec", required=True, help="SPEC.json (from reel-brief) — its on-screen text")
    b.add_argument("--total", type=float, required=True, help="reel length, seconds (EDL sum / probed master)")
    b.add_argument("--out-dir", required=True, help="dir for TITLES.json + TITLES.md")
    c = sub.add_parser("check", help="refuse a TITLES.json whose text leaves the safe zone",
                       description="refuse a TITLES.json whose rendered ink leaves the "
                                   "platform's safe zone. Measures the text with real font "
                                   "metrics; deliver burns only what passes.")
    c.add_argument("--titles", required=True, help="TITLES.json to validate")
    c.add_argument("--platform", default="",
                   help="tiktok|reels|shorts — the safe-zone table titles lay out "
                        "against; unset takes the generic margins")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    if a.cmd == "check":
        print(json.dumps(check_titles(Titles.from_json(a.titles), a.platform), indent=2))
        raise SystemExit(0)
    titles = build_titles(Spec.from_json(a.spec), a.total)
    print(json.dumps(write_titles(titles, a.out_dir), indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
