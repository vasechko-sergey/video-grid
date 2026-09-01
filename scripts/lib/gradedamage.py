"""Grade damage (design docs/specs/2026-08-31-grade-sensor-references-design.md §3):
does the declared colour chain DESTROY information, as opposed to moving it?

Pure — numpy arrays in, one dict out. The caller renders the two frame sets and
the caller decides; this module owns the statistic and what the numbers are called.

This replaces a subject dE00 gate that could not tell a grade from damage, because
a grade IS movement and dE00 measures movement. Shannon entropy of the luma
histogram is invariant under any BIJECTIVE monotone map — a relabeling carries the
histogram intact — and falls only where the map is many-to-one. That is exactly
"blind to movement, sensitive to destruction".

Measured (design §0.3) against three classes on the reference run: legitimate
conductor pairs land 0.921-1.058 and deliberate damage at legal knob extremes lands
0.814-0.910. Two obvious alternatives were measured and rejected: a distinct-code
count is pinned at 227-254 of 256 on real footage and reads black_point=0.35 as
1.042 (the crush registers as an improvement), and mean gradient inverts the same
way at 1.327.

Read on the WHOLE frame, never the subject box. Measured (§0.3): the run's subject
boxes span 2420 to 890406 px, a 368x range, and a 256-bin entropy estimator over
2420 samples is biased far enough to erase the class boundary. The whole delivered
frame is ~2M samples on every episode, so the bias is constant across the pool and
cancels in the ratio."""
import statistics

import numpy as np

ENTROPY_BINS = 256      # one bin per 8-bit code. Coarsening to 64 was measured and
                        # makes the two classes overlap (design §0.3).


def entropy(frame: np.ndarray) -> float:
    """Shannon entropy in bits of one HxWx3 uint8 RGB frame's luma histogram."""
    y = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
    counts = np.bincount(y.round().clip(0, 255).astype(np.uint8).ravel(),
                         minlength=ENTROPY_BINS)
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log2(p)).sum())


def evaluate(plain: list, graded: list, floor: float) -> dict:
    """The episode's damage verdict: the MEDIAN per-frame entropy ratio against `floor`.

    `plain` and `graded` are parallel: the same frames of the same render, differing
    only in the colour tail. That symmetry is the point — libx264 quantization lowers
    entropy on its own, so comparing a render against a shipped clip would bias the
    ratio toward false damage.

    Median, not worst, for the reason color_fidelity.evaluate gives: one atypical
    frame must not decide an episode.

    Rounds once and judges the ROUNDED value, so `below` always agrees with the
    `ratio` the report shows — the same rule color_fidelity.evaluate documents."""
    if len(plain) != len(graded):
        raise ValueError(f"gradedamage.evaluate: plain and graded are parallel lists "
                         f"of the same frames, got {len(plain)} and {len(graded)}")
    if not plain:
        return {"status": "not-checked", "reason": "no frames to compare"}
    pe = [entropy(f) for f in plain]
    ge = [entropy(f) for f in graded]
    ratios = [g / p for p, g in zip(pe, ge) if p > 0]
    if not ratios:
        return {"status": "not-checked",
                "reason": "every ungraded frame is flat — no information to lose"}
    r = round(statistics.median(ratios), 3)
    return {"ratio": r,
            "plain_bits": round(statistics.median(pe), 3),
            "graded_bits": round(statistics.median(ge), 3),
            "floor": floor,
            "frames": len(ratios),
            "below": r < floor}
