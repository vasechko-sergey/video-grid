import numpy as np
import pytest
from scripts.lib import gradedamage


def _flat(v: int, h: int = 8, w: int = 8) -> np.ndarray:
    return np.full((h, w, 3), v, dtype=np.uint8)


def _ramp(h: int = 16, w: int = 16) -> np.ndarray:
    """A frame whose luma covers many distinct codes."""
    g = np.tile(np.linspace(20, 220, w, dtype=np.uint8), (h, 1))
    return np.dstack([g, g, g])


def test_entropy_of_a_flat_frame_is_zero():
    assert gradedamage.entropy(_flat(128)) == pytest.approx(0.0)


def test_entropy_of_a_ramp_is_positive():
    assert gradedamage.entropy(_ramp()) > 3.0


def test_entropy_is_invariant_under_a_bijective_relabeling():
    """The whole reason this statistic was chosen: a monotone bijection carries the
    histogram intact, so movement alone must not read as damage."""
    a = _ramp()
    b = (a.astype(np.int16) + 20).clip(0, 255).astype(np.uint8)   # +20 codes, no collisions
    assert gradedamage.entropy(b) == pytest.approx(gradedamage.entropy(a))


def test_luma_weights_are_not_transposed():
    """Fix round 1, Important 2: every fixture in this file is achromatic
    (np.dstack([g, g, g])), so on an R=G=B frame any weights summing to 1 give
    the identical result and an R/B transposition passes every other test here.

    A frame half pure green, half pure blue has a two-code luma histogram whose
    codes pin the coefficients directly: 0.587*255 = 149.685 -> round -> 150 for
    green, 0.114*255 = 29.07 -> round -> 29 for blue (measured; the reviewer's
    own dispatch named 149, which is the FLOORED value — round() correctly
    carries .685 up to 150). Green's code does not move under an R/B swap (its R
    and B channels are both 0, so only the untouched G weight matters), but
    blue's would move from 29 to 0.299*255 = 76.245 -> 76 — a different code,
    not merely a relabeling, since entropy() cannot distinguish a relabeling from
    the correct weights on a two-equal-group histogram either way. Testing this
    needs the plane itself, hence `_luma`, not the scalar `entropy` reduces it to."""
    h, w = 8, 8
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[: h // 2, :, 1] = 255           # top half: pure green (0, 255, 0)
    frame[h // 2 :, :, 2] = 255           # bottom half: pure blue (0, 0, 255)
    y = gradedamage._luma(frame)
    assert set(np.unique(y).tolist()) == {150, 29}
    assert set(np.unique(y[: h // 2]).tolist()) == {150}
    assert set(np.unique(y[h // 2 :]).tolist()) == {29}


def test_entropy_falls_under_a_many_to_one_map():
    # w=64, not the fixture's default 16: at w=16 the ramp's codes are ~13.3 apart,
    # wider than the //8*8 quantization bin, so no two codes ever land in the same
    # bin and entropy does not move at all (measured: 4.0 -> 4.0). Widened so the
    # collapse this test exists to demonstrate actually happens (measured: 6.0 -> 4.671).
    a = _ramp(w=64)
    b = ((a.astype(np.int16) // 8) * 8).astype(np.uint8)          # 8:1 quantization
    assert gradedamage.entropy(b) < gradedamage.entropy(a) - 1.0


def test_evaluate_passes_a_relabeling():
    a = [_ramp(), _ramp(), _ramp()]
    b = [(f.astype(np.int16) + 20).clip(0, 255).astype(np.uint8) for f in a]
    d = gradedamage.evaluate(plain=a, graded=b, floor=0.90)
    assert d["ratio"] == pytest.approx(1.0, abs=1e-3)
    assert d["below"] is False
    assert d["frames"] == 3


def test_evaluate_reports_the_median_ratio_not_the_mean_min_or_max(monkeypatch):
    """Fix round 1, Critical 1: every OTHER multi-frame test in this file builds its
    ratio list from bit-identical repeated frames ([1.0, 1.0, 1.0] or
    [0.7785, 0.7785, 0.7785]), against which median/mean/min/max/`ratios[0]` all
    return the same number — confirmed by temporarily swapping `statistics.median`
    for `statistics.mean` at gradedamage.py's `r = ...` line and watching every
    other test in this file still pass.

    Mirrors color_fidelity's own test_the_description_is_the_median_not_the_worst
    (tests/lib/test_color_fidelity.py, renamed 2026-08-31 §3 when that module's dE00
    stopped voting) but with three DISTINCT values, not two tied survivors and one
    outlier: two equal survivors would make median and max coincide, and this test
    would then fail to notice `evaluate` using max.

    Stubbed ratios [0.99, 0.40, 0.95] -> sorted [0.40, 0.95, 0.99]:
      median = 0.95  (the correct aggregator, asserted below)
      mean   = 0.78
      min    = 0.40
      max    = 0.99
    All four are distinct, so substituting any of the other three for median
    changes the reported `ratio`. Verified by hand for this fix: editing
    gradedamage.py to use statistics.mean, then min(ratios), then max(ratios) in
    turn (restoring via `git show HEAD:scripts/lib/gradedamage.py >
    scripts/lib/gradedamage.py` between edits, never checkout/restore/reset) turns
    this test red every time; median is the only one of the four that leaves it
    green."""
    values = iter([1.0, 1.0, 1.0, 0.99, 0.40, 0.95])   # plain x3, then graded x3
    monkeypatch.setattr(gradedamage, "entropy", lambda frame: next(values))
    d = gradedamage.evaluate(plain=[_ramp(), _ramp(), _ramp()],
                             graded=[_ramp(), _ramp(), _ramp()], floor=0.90)
    assert d["ratio"] == 0.95
    assert d["ratio"] != pytest.approx(0.78)      # mean would report this
    assert d["ratio"] != 0.40                     # min would report this
    assert d["ratio"] != 0.99                     # max would report this
    assert d["below"] is False


def test_evaluate_fails_a_quantization():
    # w=64 — see test_entropy_falls_under_a_many_to_one_map for why the fixture's
    # default width does not exercise a many-to-one map at all.
    a = [_ramp(w=64), _ramp(w=64), _ramp(w=64)]
    b = [((f.astype(np.int16) // 8) * 8).astype(np.uint8) for f in a]
    d = gradedamage.evaluate(plain=a, graded=b, floor=0.90)
    assert d["below"] is True
    assert d["ratio"] < 0.90


def test_evaluate_judges_the_rounded_ratio_it_reports(monkeypatch):
    """A report reading 'ratio: 0.9, floor: 0.9, below: true' is a contradiction no
    reader can act on — color_fidelity.evaluate documented the same round-then-judge
    rule before its own verdict was retired (design 2026-08-31 §3); this module is
    now the one place that rule still has a threshold to protect.

    The monkeypatch below replaces the brief's own bisection, on the controller's
    instruction (fix round 1, Important 4: that authorization was given in the
    original Task 0 dispatch message's own ambiguity-resolution note, not written
    into the brief file itself — this docstring previously, and wrongly, said the
    latter). The brief's bisection searches for a quantization step whose raw
    ratio sits just under 0.90 but rounds to it, by bisecting on this fixture's
    default (w=16) ramp. Measured, it converges on ratio 0.906 — not a value that
    rounds to the floor at all, so it never reaches the contradiction this test
    exists to pin. Stubbing `entropy` to hand back two fixed values makes the
    boundary exact and deterministic instead of dependent on where this ramp's
    quantization steps happen to fall."""
    values = iter([1.0, 0.8996])              # raw ratio 0.8996 -> rounds to 0.900
    monkeypatch.setattr(gradedamage, "entropy", lambda frame: next(values))
    d = gradedamage.evaluate(plain=[_ramp()], graded=[_ramp()], floor=0.90)
    assert d["ratio"] == 0.90
    assert d["below"] is (d["ratio"] < d["floor"])
    assert d["below"] is False   # the raw 0.8996 < 0.90 would say True — the rounded value must win


def test_evaluate_is_keyword_only():
    """Fix round 1, Important 3: the design's §3.1 hands a LATER task a
    `plans: tuple[RenderPlan, RenderPlan]` documented as `(graded, plain)` — the
    OPPOSITE of this function's own `graded / plain` order. A future
    `evaluate(*plans, floor)` would silently invert the sensor; keyword-only
    makes that a TypeError at the call instead of a wrong number in a report."""
    a, b = [_ramp()], [_ramp()]
    with pytest.raises(TypeError):
        gradedamage.evaluate(a, b, 0.90)


def test_evaluate_reports_not_checked_on_no_frames():
    d = gradedamage.evaluate(plain=[], graded=[], floor=0.90)
    assert d["status"] == "not-checked"
    assert "below" not in d


def test_evaluate_refuses_mismatched_lists():
    with pytest.raises(ValueError, match="parallel"):
        gradedamage.evaluate(plain=[_ramp()], graded=[_ramp(), _ramp()], floor=0.90)


def test_evaluate_reports_not_checked_when_the_ungraded_frame_is_flat():
    """A flat ungraded frame has zero entropy and no ratio exists. Reporting a
    division result would be inventing one."""
    d = gradedamage.evaluate(plain=[_flat(128)], graded=[_flat(200)], floor=0.90)
    assert d["status"] == "not-checked"


def test_evaluate_bits_and_frames_describe_the_same_subset():
    """Fix round 1, Important 5: plain_bits/graded_bits used to come from the
    UNFILTERED per-frame entropies while `ratio`/`frames` came from the p>0
    subset, so a report could show a `plain_bits` figure that belongs to a frame
    `frames` says was never counted. Demonstrated case: two flat plain frames
    (entropy 0.0, excluded — dividing by zero entropy invents a ratio) beside one
    real one. Before this fix, `plain_bits` read as the median of all three
    (dominated by the two zeros); after it, `plain_bits`/`graded_bits` are the
    median of the ONE frame `frames` actually counts."""
    plain = [_flat(128), _flat(90), _ramp()]
    graded = [_flat(200), _flat(210), _ramp()]
    d = gradedamage.evaluate(plain=plain, graded=graded, floor=0.90)
    assert d["frames"] == 1
    assert d["plain_bits"] == gradedamage.entropy(_ramp())
    assert d["graded_bits"] == gradedamage.entropy(_ramp())
    assert d["ratio"] == pytest.approx(1.0)


def test_evaluate_never_reports_a_negative_zero():
    """Fix round 1, Important 5: `entropy` returns exactly -0.0 for a flat frame
    (log2(1) == 0.0, negated), and dividing a flat GRADED frame's -0.0 by a real
    plain entropy carries the sign into `ratio` — total destruction should read
    as a clean 0.0, not '-0.0'. repr()/str() is the only way to see the sign:
    -0.0 == 0.0 is True in Python, so a plain equality assert would not catch it."""
    d = gradedamage.evaluate(plain=[_ramp()], graded=[_flat(128)], floor=0.90)
    assert d["ratio"] == 0.0
    assert str(d["ratio"]) == "0.0"          # not "-0.0"
    assert d["below"] is True
    assert d["frames"] == 1
