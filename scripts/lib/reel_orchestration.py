"""Pure reel-loop decisions (design §3, §4) — the montage §4.1 escalation ladder
one level up from process-episode. `next_action` maps a check_reel report's
`fail_reasons` to exactly one action; build_reel (the shell) executes it. No
ffmpeg, no state: the driver owns per-episode attempt counts and the compounded
colour factor. Mirrors scripts/lib/orchestration.py."""
from dataclasses import dataclass

from scripts.lib.models import ReelFailure

_REPROCESS_CLASS = ("black", "color_across_cuts")


@dataclass(frozen=True)
class ReprocessItem:
    """Reprocess one episode. color_correct is the per-round ratio med/d_i for a
    colour fail (the driver compounds + clamps it), or None for a black clean
    re-encode."""
    idx: int
    color_correct: tuple[float, float, float] | None


@dataclass(frozen=True)
class ReelAction:
    """The outcome of one reel-loop round (design §3): deliver the reel as-is,
    reprocess a set of culprit episodes, or escalate up the chain with a finding.
    Exactly one kind fires per round; the shell dispatches on it."""
    kind: str                          # "deliver" | "reprocess" | "escalate"
    reprocess: tuple[ReprocessItem, ...] = ()
    finding: dict | None = None


def _correction(f: ReelFailure) -> tuple[float, float, float]:
    """Per-channel per-round ratio med/d_i from the colour fail detail (§4). Raw
    ratio only — the driver compounds onto the stored factor and clamps."""
    target = f.detail["target"]
    culprit = f.detail["culprit_mean"]
    return tuple(t / d if d > 0 else 1.0 for t, d in zip(target, culprit))


def next_action(fail_reasons: list[ReelFailure], attempts: dict[int, int], cap: int) -> ReelAction:
    """One decision for the whole reel (design §3). Escalate wins the round: any
    non-auto-fixable or capped failure returns Escalate immediately, so we never
    spend reprocess rounds on a reel that also carries an unfixable fault."""
    if not fail_reasons:
        return ReelAction("deliver")
    items: dict[int, ReprocessItem] = {}   # idx → ReprocessItem; colour wins over a bare black re-encode
    for f in fail_reasons:
        if f.check not in _REPROCESS_CLASS:
            return ReelAction("escalate", finding={
                "reason": "not-auto-fixable", "check": f.check,
                "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                "detail": f.detail})
        if attempts.get(f.episode_idx, 0) >= cap:
            return ReelAction("escalate", finding={
                "reason": "reprocess-capped", "check": f.check, "episode_idx": f.episode_idx,
                "escalate_to": "edit-plan",
                "detail": (f"episode {f.episode_idx} still fails {f.check} after {cap} "
                           "reprocesses — the source window or grade is wrong; fix the segment/EDL")})
        corr = _correction(f) if f.check == "color_across_cuts" else None
        if f.episode_idx not in items or corr is not None:
            items[f.episode_idx] = ReprocessItem(f.episode_idx, corr)
    return ReelAction("reprocess", reprocess=tuple(items[k] for k in sorted(items)))
