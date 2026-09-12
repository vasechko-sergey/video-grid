"""project-init CLI: purpose+quality → project.json (design 2026-07-09).

    .venv/bin/python -m scripts.project_init --purpose reel --quality native \
        --project-dir out/myproject
Custom aspect: --purpose custom --canvas 4:5 ; explicit delivery: --delivery exact:1080x1920.
"""
import argparse
from pathlib import Path

from scripts.lib import provenance
from scripts.lib.project import resolve_project


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="write project.json (purpose→aspect/delivery)")
    ap.add_argument("--purpose", required=True,
                    help="reel/shorts/tiktok/youtube/landscape/square/feed/cinema/wide/custom")
    ap.add_argument("--quality", default="native", help="native (default) / social / 4k")
    ap.add_argument("--canvas", default=None, help="explicit W:H (required for --purpose custom)")
    ap.add_argument("--delivery", default=None, help="explicit delivery spec (overrides --quality)")
    ap.add_argument("--notes", default="")
    ap.add_argument("--project-dir", required=True, help="dir to write project.json into")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    if a.canvas:
        try:
            canvas = tuple(int(v) for v in a.canvas.split(":"))
        except ValueError:
            raise ValueError(f"--canvas {a.canvas!r} must be W:H integers, e.g. 4:5") from None
    else:
        canvas = None
    cfg = resolve_project(a.purpose, quality=a.quality, canvas=canvas,
                          delivery=a.delivery, notes=a.notes)
    Path(a.project_dir).mkdir(parents=True, exist_ok=True)
    out = Path(a.project_dir) / "project.json"
    # The run's START stamp: edl_to_reel compares the engine against this and refuses a
    # run that straddles an engine change (design §7).
    cfg.provenance = provenance.stamp(cfg.to_dict())
    cfg.write(out)
    print(str(out))


if __name__ == "__main__":
    main()
