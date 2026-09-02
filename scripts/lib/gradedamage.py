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


def _luma(frame: np.ndarray) -> np.ndarray:
    """The rounded, clipped 8-bit luma plane of one HxWx3 uint8 RGB frame — the
    histogram `entropy` reduces to a scalar.

    Its own function so the weight coefficients are directly testable (fix round 1,
    Important 2). `entropy`'s return value is a function of the multiset of bin
    PROBABILITIES only, and is invariant under any relabeling that preserves group
    sizes — that invariance is the whole reason this statistic was chosen, and is
    itself pinned by test_entropy_is_invariant_under_a_bijective_relabeling. The
    same invariance means `entropy` alone cannot catch e.g. an R/B weight
    transposition on any fixture where swapping the two channels does not change
    how many pixels land in each code: testing the coefficients needs the plane
    itself, not the scalar entropy reduces it to."""
    y = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
    return y.round().clip(0, 255).astype(np.uint8)


def entropy(frame: np.ndarray) -> float:
    """Shannon entropy in bits of one HxWx3 uint8 RGB frame's luma histogram.

    Computed directly over the 8-bit code alphabet `_luma` already returns —
    `np.bincount` sizes its own output to the data, so no bin count is threaded
    through here. Design §0.3's comparison against a genuine 64-bin coarsening
    (measured there to make the legitimate and damaging classes overlap) was an
    offline survey over an independently rebucketed histogram; this module
    never expressed that binning in code, and a `minlength=` argument sized to
    a bin count someone might mistake for a live knob only invited the
    confusion (fix round, 2026-09-02) — `minlength` pads `bincount`'s trailing
    zero-count entries, which the next line's `counts > 0` filter strips before
    they can affect anything, so the argument never changed this function's
    return value for any input."""
    counts = np.bincount(_luma(frame).ravel())
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log2(p)).sum())


def _no_negzero(x: float) -> float:
    """Collapse IEEE754 negative zero to positive zero. `entropy` returns exactly
    -0.0 for a fully-concentrated histogram (log2(1) == 0.0, then negated by the
    sum), and a report reading 'ratio: -0.0' or 'plain_bits: -0.0' carries a sign
    no reader should have to interpret, even though -0.0 == 0.0 numerically
    (fix round 1, Important 5)."""
    return 0.0 if x == 0 else x


def evaluate(*, plain: list, graded: list, floor: float) -> dict:
    """The episode's damage verdict: the MEDIAN per-frame entropy ratio against `floor`.

    `plain` and `graded` are parallel: the same frames of the same render, differing
    only in the colour tail. That symmetry is the point — measured directly and
    reproduced five times (design §3, §9.1), a clip-read's entropy comes back
    HIGHER than a render-pair's, because CRF-18 quantization and deblocking SPREAD
    the luma histogram rather than collapse it. So comparing a render against a
    shipped clip would bias the ratio toward LENIENCY, not toward false damage —
    the failure mode symmetry guards against is missing real damage.

    Median, not worst, for the reason color_fidelity.evaluate gives: one atypical
    frame must not decide an episode.

    Rounds once and judges the ROUNDED value, so `below` always agrees with the
    `ratio` the report shows — the same rule color_fidelity.evaluate documents.

    Keyword-only, deliberately (fix round 1, Important 3): this returns
    graded ÷ plain, while the design's §3.1 hands the next task a
    `plans: tuple[RenderPlan, RenderPlan]` documented as `(graded, plain)` — the
    OPPOSITE order. A caller writing `evaluate(*plans, floor)` would invert the
    sensor with no error; keyword-only turns that into a TypeError instead."""
    if len(plain) != len(graded):
        raise ValueError(f"gradedamage.evaluate: plain and graded are parallel lists "
                         f"of the same frames, got {len(plain)} and {len(graded)}")
    if not plain:
        return {"status": "not-checked", "reason": "no frames to compare"}
    pe = [entropy(f) for f in plain]
    ge = [entropy(f) for f in graded]
    # Filtered ONCE, together (fix round 1, Important 5): plain_bits/graded_bits
    # must describe the same frames `ratio`/`frames` do. Computing them from the
    # unfiltered pe/ge let a flat frame excluded from the ratio (it has none —
    # dividing by zero entropy invents one) still drag the reported bits toward
    # its own zero entropy, so a report could show a `plain_bits` figure that
    # belongs to a frame `frames` says was never counted.
    pairs = [(p, g) for p, g in zip(pe, ge) if p > 0]
    if not pairs:
        return {"status": "not-checked",
                "reason": "every ungraded frame is flat — no information to lose"}
    ratios = [g / p for p, g in pairs]
    pe_f = [p for p, _ in pairs]
    ge_f = [g for _, g in pairs]
    r = _no_negzero(round(statistics.median(ratios), 3))
    return {"ratio": r,
            "plain_bits": _no_negzero(round(statistics.median(pe_f), 3)),
            "graded_bits": _no_negzero(round(statistics.median(ge_f), 3)),
            "floor": floor,
            "frames": len(ratios),
            "below": r < floor}
