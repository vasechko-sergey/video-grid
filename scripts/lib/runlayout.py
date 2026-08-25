"""Where a montage run's artifacts live, and the one rule about where they do not.

The conveyor discovers footage by extension over a FLAT listing of the footage
root (intake.py: `root.iterdir()`, no exclusion). Anything it writes there that
happens to be a video therefore becomes source material on the next scan —
measured 2026-08-19: `draft.mp4` sat among 99 real clips and escaped the scan
only because the scan had already run (design 2026-08-25 §0).

So the run gets its own folder, `<footage_root>/montage/`, and the two stages
that know the footage root and write into a caller-chosen directory refuse to
be pointed at the footage root itself.
"""
from pathlib import Path

RUN_DIRNAME = "montage"       # <footage_root>/montage — see the skills and the README


def refuse_output_in_footage(footage_root: str, out_dir: str, what: str) -> None:
    """Raise unless `out_dir` is somewhere other than the footage root itself.

    EQUALITY, never containment: `<footage_root>/montage` is inside the footage
    root and must pass, or this would forbid the layout it exists to protect.
    Both ends resolve() so a trailing slash, a `..` segment or a symlink cannot
    spell past it.
    """
    root = Path(footage_root).resolve()
    if Path(out_dir).resolve() != root:
        return
    raise ValueError(
        f"{what} resolves to the footage folder itself ({root}) — the conveyor "
        f"would write its output into the directory intake scans for source "
        f"clips, and any .mp4 landing there is taken as footage by the next scan "
        f"(draft.mp4 already did, and went unnoticed). Point it at "
        f"{root / RUN_DIRNAME} instead.")
