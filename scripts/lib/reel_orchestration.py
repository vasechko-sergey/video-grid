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
    reprocess a set of culprit episodes, re-time the target to the reel's real
    length, or escalate up the chain with a finding. Exactly one kind fires per
    round; the shell dispatches on it. `retime` may also ride along with a
    reprocess — the target is adopted before the round's work."""
    kind: str                          # "deliver" | "reprocess" | "escalate" | "retime"
    reprocess: tuple[ReprocessItem, ...] = ()
    finding: dict | None = None
    retime: float | None = None        # new target_dur when a within-band shortfall is absorbed (§3)


def _correction(f: ReelFailure) -> tuple[float, float, float]:
    """Per-channel per-round ratio med/d_i from the colour fail detail (§4). Raw
    ratio only — the driver compounds onto the stored factor and clamps."""
    target = f.detail["target"]
    culprit = f.detail["culprit_mean"]
    return tuple(t / d if d > 0 else 1.0 for t, d in zip(target, culprit))


def _shortfall(f: ReelFailure) -> float | None:
    """target − dur for a length failure, or None when the reel runs LONGER than target.
    An over-length reel is never absorbed: the stem is cut from a fixed music fragment and
    mix.mix refuses dur > music.duration, so re-timing UP would trade a clean escalate for
    a hard raise at the mixer (design §2)."""
    gap = f.detail["target"] - f.detail["dur"]
    return gap if gap > 0 else None


def next_action(fail_reasons: list[ReelFailure], attempts: dict[int, int], cap: int,
                length_retime_max: float = 0.0, outro_fixed: bool = False) -> ReelAction:
    """One decision for the whole reel (design §3). Escalate wins the round: any
    non-auto-fixable or capped failure returns Escalate immediately, so we never
    spend reprocess rounds on a reel that also carries an unfixable fault. `length`
    is auto-fixable in exactly one shape — a shortfall inside length_retime_max,
    absorbed by re-timing the target DOWN to the reel's real length — and only when
    the length was not CHOSEN: an outro-fitted reel (outro_fixed=True) escalates
    instead, with reason "outro-length-chosen", even for a shortfall that would
    otherwise sit inside the band. An over-length reel and a shortfall past the band
    still escalate to pacing regardless of outro_fixed. The 0.0/False defaults
    reproduce the pre-slice behaviour for a caller that passes neither."""
    if not fail_reasons:
        return ReelAction("deliver")
    items: dict[int, ReprocessItem] = {}   # idx → ReprocessItem; colour wins over a bare black re-encode
    retime: float | None = None
    for f in fail_reasons:
        if f.check == "length":
            gap = _shortfall(f)
            absorbable = gap is not None and gap <= length_retime_max
            if absorbable and not outro_fixed:
                retime = f.detail["dur"]   # the reel IS this long — make it the target
                continue
            finding = {"reason": "not-auto-fixable", "check": f.check,
                       "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                       "detail": f.detail}
            if absorbable and outro_fixed:
                # The absorb's premise is "the reel IS that long, so the target was
                # wrong". False when the target was CHOSEN: with an outro fit,
                # target_dur is line + fade, a decision about where the music resolves.
                # mix fades over [master_dur - fade, master_dur], so absorbing keeps the
                # fade at the reel's end and moves the BAR LINE out from under it — and
                # length_retime_max (1.0s) is as wide as the 0.96s miss the outro slice
                # exists to fix (design 2026-08-16 §5).
                finding["reason"] = "outro-length-chosen"
                finding["detail"] = {**f.detail, "why": (
                    "the reel's length was CHOSEN by the outro fit as line + fade, so "
                    "absorbing this shortfall would move the fade off the bar line. Grow "
                    "or re-cut the closing episode — edit-plan and pacing own the "
                    "picture's length; the reel loop cannot invent picture")}
            return ReelAction("escalate", finding=finding)
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
    if items:
        return ReelAction("reprocess", reprocess=tuple(items[k] for k in sorted(items)), retime=retime)
    if retime is not None:
        return ReelAction("retime", retime=retime)
    return ReelAction("deliver")
