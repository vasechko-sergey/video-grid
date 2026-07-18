"""The three still-mechanical §5.13 editorial checks (design
2026-07-17-reel-final-editorial-checks). Each is a pure decision over data the
reel already carries (subject-extent projections + per-episode PathMeta), and
each is ADVISORY: check_reel reports it into the ReelReport but it is excluded
from `overall` and never becomes a ReelFailure — zero blast radius on loop-2.
Companion to lib.safezones (the fourth §5.13 advisory check)."""
import math

from scripts.lib.models import PathMeta

LAYOUT_MODE_PENALTY = 0.5      # a layout change — mode (fill↔insert) or filler
                               # (blur↔solid) — adds this to the layout-jump score


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


def evaluate_pad_bars(metas: list[PathMeta], bar_symmetry_tol: float) -> tuple[bool | None, dict]:
    """Structural filler-bar check from the sidecar only (no pixels). For each
    non-`fill` episode: the content rect must lie inside the output frame, and the
    bars must be symmetric within `bar_symmetry_tol` (a canvas fraction). `fill`
    episodes have no bars (skipped); an all-`fill` reel is n/a. Advisory."""
    worst = None                                   # (severity, ep_idx, issue, rect, out)
    n_bars = 0
    for i, meta in enumerate(metas):
        if meta.mode == "fill":
            continue
        n_bars += 1
        rx, ry, rw, rh = meta.rect_px
        ow, oh = meta.out_dims
        overflow = max(-rx, -ry, (rx + rw) - ow, (ry + rh) - oh)
        if overflow > 0:
            sev = overflow / max(ow, oh)
            if worst is None or sev > worst[0]:
                worst = (sev, i, "rect_overflow", [rx, ry, rw, rh], [ow, oh])
            continue
        asym = max(abs(rx - (ow - (rx + rw))) / ow, abs(ry - (oh - (ry + rh))) / oh)
        if asym > bar_symmetry_tol and (worst is None or asym > worst[0]):
            worst = (asym, i, "asymmetric", [rx, ry, rw, rh], [ow, oh])
    if n_bars == 0:
        return None, {"status": "n/a", "reason": "no non-fill layout", "advisory": True}
    if worst is None:
        return True, {"bars": n_bars, "advisory": True}
    _, idx, issue, rect, out = worst
    return False, {"worst_episode": idx, "issue": issue, "rect_px": rect,
                   "out_dims": out, "advisory": True}


def _layout_of(meta: PathMeta) -> tuple[float, float, float, str]:
    """(coverage-fraction, centre-fx, centre-fy, layout-identity) of one episode.

    The identity is (mode, background), not mode alone: a cut from (fit, blur) to
    (fit, solid) leaves the geometry untouched while the pad's appearance changes
    hard, and a penalty keyed on mode would call that "unchanged".
    """
    rx, ry, rw, rh = meta.rect_px
    ow, oh = meta.out_dims
    return ((rw * rh) / (ow * oh), (rx + rw / 2) / ow, (ry + rh / 2) / oh,
            f"{meta.mode}+{meta.background}")


def evaluate_transitions(metas: list[PathMeta], layout_jump_max: float) -> tuple[bool | None, dict]:
    """Flag a cut whose layout jumps beyond `layout_jump_max`: |Δcoverage| +
    centre shift + a LAYOUT_MODE_PENALTY when the mode changes. Reads PathMeta
    only (reel episodes share the canvas, so fractions are comparable). n/a for a
    single episode. Advisory — 'jarring' is a taste proxy, never a gate."""
    if len(metas) < 2:
        return None, {"status": "n/a", "reason": "single episode", "advisory": True}
    worst = None                                   # (jump, cut_idx, [mode_i, mode_j])
    for i in range(len(metas) - 1):
        a0, cx0, cy0, m0 = _layout_of(metas[i])
        a1, cx1, cy1, m1 = _layout_of(metas[i + 1])
        jump = abs(a0 - a1) + math.hypot(cx0 - cx1, cy0 - cy1) + (LAYOUT_MODE_PENALTY if m0 != m1 else 0.0)
        if jump > layout_jump_max and (worst is None or jump > worst[0]):
            worst = (jump, i, [m0, m1])
    if worst is None:
        return True, {"cuts": len(metas) - 1, "advisory": True}
    jump, idx, modes = worst
    return False, {"worst_cut": idx, "jump": round(jump, 4), "modes": modes, "advisory": True}
