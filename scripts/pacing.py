# scripts/pacing.py
"""Pacing driver (design docs/specs/2026-07-14-pacing-design.md, §5.6): read MUSIC.json,
derive the energy spine, write PACING.{json,md}. A thin driver over the pure
scripts/lib/pacing core — edit-plan then binds its episodes to the spine (--pacing).
The chosen track fragment is the canvas; SPEC.length_s is a cross-check only."""
import argparse
import json
import sys
from pathlib import Path

from scripts.lib import pacing
from scripts.lib.models import MusicSpec
from scripts.lib.spec import Spec

_LEN_TOL = 0.5      # s; SPEC.length_s vs MUSIC.duration cross-check band


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_pacing(music_json: str, out_dir: str, spec_json: str | None = None) -> dict:
    """Derive the energy spine from MUSIC.json → PACING.{json,md} in out_dir. Returns
    {"json": path, "md": path, "spine": Spine}. A SPEC.length_s that disagrees with the
    fragment length is logged (the spine follows the fragment) — never silent."""
    m = MusicSpec.from_json(music_json)
    spine = pacing.build_spine(m.beats, m.energy, m.energy_hz, m.duration, m.tempo)
    if spec_json:
        want = Spec.from_json(spec_json).length_s
        if abs(want - m.duration) > _LEN_TOL:
            _log(f"pacing: SPEC.length_s {want:.1f}s != MUSIC.duration {m.duration:.1f}s — "
                 f"the spine follows the chosen track fragment ({m.duration:.1f}s); "
                 f"re-run beats --auto-start --duration {want:.0f} to re-pick the fragment")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "PACING.json", out / "PACING.md"
    json_path.write_text(json.dumps(spine.to_dict(), indent=2))
    md_path.write_text(spine.to_markdown())
    return {"json": str(json_path), "md": str(md_path), "spine": spine}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="derive the reel's energy spine from MUSIC.json → PACING.{json,md}")
    ap.add_argument("--music", required=True, help="MUSIC.json from music-and-mood (stage 5.5)")
    ap.add_argument("--spec", help="SPEC.json — cross-checks length_s against the fragment (optional)")
    ap.add_argument("--out-dir", required=True, help="where to write PACING.{json,md}")
    a = ap.parse_args()
    res = build_pacing(a.music, a.out_dir, a.spec)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
