"""Final reel assembler (чистовик, design §3): ordered locked episodes → one
silent master via lib.assembly. The draft assembler is a later sibling over the
same core."""
import argparse
from scripts.lib import assembly


def main() -> None:
    ap = argparse.ArgumentParser(description="Concat locked episodes into a reel master.")
    ap.add_argument("episodes", nargs="+", help="ordered locked out/<ep>.mp4 paths")
    ap.add_argument("--out", required=True, help="master output path")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--fps", type=float, required=True)
    a = ap.parse_args()
    assembly.assemble(a.episodes, (a.width, a.height), a.fps, a.out)


if __name__ == "__main__":
    main()
