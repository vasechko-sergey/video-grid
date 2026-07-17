"""The three still-mechanical §5.13 editorial checks (design
2026-07-17-reel-final-editorial-checks). Each is a pure decision over data the
reel already carries (subject-extent projections + per-episode PathMeta), and
each is ADVISORY: check_reel reports it into the ReelReport but it is excluded
from `overall` and never becomes a ReelFailure — zero blast radius on loop-2.
Companion to lib.safezones (the fourth §5.13 advisory check)."""
import math

from scripts.lib.models import PathMeta

LAYOUT_MODE_PENALTY = 0.5      # a mode change (fill↔insert) adds this to the layout-jump score


def evaluate_key_action(extents_per_ep: list[list[tuple[float, float, float, float]]],
                        clip_tol: float) -> tuple[bool, dict]:
    """Flag if any episode's tracked-subject bbox corner leaves the output frame
    [0,1] by more than `clip_tol` (a close-up legitimately touches the edge). The
    report names the deepest overshoot, its edge, and episode. Advisory."""
    worst = None                                   # (overshoot, ep_idx, edge)
    for i, extents in enumerate(extents_per_ep):
        for fx0, fy0, fx1, fy1 in extents:
            for over, edge in ((-fx0, "left"), (fx1 - 1.0, "right"),
                               (-fy0, "top"), (fy1 - 1.0, "bottom")):
                if over > clip_tol and (worst is None or over > worst[0]):
                    worst = (over, i, edge)
    if worst is None:
        return True, {"episodes": len(extents_per_ep), "advisory": True}
    over, idx, edge = worst
    return False, {"worst_episode": idx, "overshoot": round(over, 4), "edge": edge,
                   "advisory": True}
