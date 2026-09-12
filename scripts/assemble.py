"""Final reel assembler (чистовик, design §3): ordered locked episodes → one
silent master via lib.assembly. Its draft sibling is scripts/draft.py — a labelled
QA preview over the same lib.assembly.concat core (montage §5.9)."""
import argparse
from scripts.lib import assembly


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Concat locked episodes into a reel master.")
    ap.add_argument("episodes", nargs="+", help="ordered locked out/<ep>.mp4 paths")
    ap.add_argument("--out", required=True, help="master output path")
    ap.add_argument("--width", type=int, required=True, help="master pixel width")
    ap.add_argument("--height", type=int, required=True, help="master pixel height")
    ap.add_argument("--fps", type=float, required=True,
                    help="master frame rate — every episode must already match it")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    assembly.assemble(a.episodes, (a.width, a.height), a.fps, a.out)


if __name__ == "__main__":
    main()
