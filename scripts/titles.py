"""Titles writer (design docs/specs/2026-07-13-titles-design.md, §5.16). The thin
mechanical half: from a Spec + the reel length, draft a Titles (hook opens, ending
closes, text as a mid caption) and write TITLES.json + TITLES.md. Judgment — the
actual words / timing / style — is the titles SKILL's; this is the starting
projection. Mirror of reel_brief.py: contract in lib, driver here."""
import argparse
import json
import math
from pathlib import Path

from scripts.lib.spec import Spec
from scripts.lib.titles import Title, Titles


def build_titles(spec: Spec, total_s: float) -> Titles:
    """A sensible starting Titles from a Spec: the hook opens [0, 2], spec.text (when
    set) a mid caption, spec.ending (when set) a closing title in the last 3s. All
    font='system' so the draft renders on any box, curated set or not. total_s (reel length) is
    the caller's — EDL sum or a probed master — build_titles never guesses it."""
    if (isinstance(total_s, bool) or not isinstance(total_s, (int, float))
            or not math.isfinite(total_s) or total_s <= 0):
        raise ValueError(
            f"build_titles total_s must be a positive finite number (seconds), got {total_s!r}")
    items: list[Title] = [Title(text=spec.hook, start=0.0, dur=min(2.0, total_s), pos="top")]
    if spec.text.strip():
        mid = max(0.0, total_s / 2 - 1.0)
        items.append(Title(text=spec.text, start=mid, dur=min(2.0, total_s - mid), pos="bottom"))
    if spec.ending.strip():
        start = max(0.0, total_s - 3.0)
        items.append(Title(text=spec.ending, start=start, dur=total_s - start, pos="center"))
    return Titles(items=tuple(items))


def write_titles(titles: Titles, out_dir: str) -> dict:
    """Write TITLES.json + TITLES.md together into out_dir. Returns a status dict."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    tj, tm = Path(out_dir) / "TITLES.json", Path(out_dir) / "TITLES.md"
    titles.write(tj)
    tm.write_text(titles.to_markdown())
    return {"status": "written", "titles": str(tj), "md": str(tm), "count": len(titles.items)}


def main() -> None:
    ap = argparse.ArgumentParser(description="write TITLES.json + TITLES.md — the reel titles (§5.16)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="draft TITLES from SPEC + reel length")
    b.add_argument("--spec", required=True, help="SPEC.json (from reel-brief) — hook/text/ending source")
    b.add_argument("--total", type=float, required=True, help="reel length, seconds (EDL sum / probed master)")
    b.add_argument("--out-dir", required=True, help="dir for TITLES.json + TITLES.md")
    a = ap.parse_args()
    titles = build_titles(Spec.from_json(a.spec), a.total)
    print(json.dumps(write_titles(titles, a.out_dir), indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
