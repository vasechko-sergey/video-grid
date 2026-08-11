import math

import pytest

from scripts.lib import ramp
from scripts.lib.models import RampSpec

SPEC = RampSpec(at=2.0, factor=0.4, ease=0.5, hold=1.0)   # region [1.0, 3.0]
DUR = 4.0


def test_speed_is_exactly_one_outside_the_region():
    assert ramp.speed_at(0.0, SPEC) == 1.0
    assert ramp.speed_at(0.99, SPEC) == 1.0
    assert ramp.speed_at(3.01, SPEC) == 1.0
    assert ramp.speed_at(DUR, SPEC) == 1.0


def test_speed_is_exactly_factor_across_the_plateau():
    for t in (1.5, 2.0, 2.5):
        assert ramp.speed_at(t, SPEC) == pytest.approx(0.4)


def test_the_ease_is_monotonic_and_meets_both_ends():
    # cosine ease: 1.0 at the region edge, `factor` at the plateau edge, and
    # strictly decreasing between. The midpoint is the arithmetic mean.
    assert ramp.speed_at(1.0, SPEC) == pytest.approx(1.0)
    assert ramp.speed_at(1.25, SPEC) == pytest.approx(0.7)
    assert ramp.speed_at(1.5, SPEC) == pytest.approx(0.4)
    xs = [ramp.speed_at(1.0 + 0.05 * i, SPEC) for i in range(11)]
    assert all(a >= b for a, b in zip(xs, xs[1:]))


def test_knots_span_the_window_and_start_at_zero():
    ts, o = ramp.knots(SPEC, DUR)
    assert len(ts) == len(o)
    assert ts[0] == 0.0 and ts[-1] == pytest.approx(DUR)
    assert o[0] == 0.0


def test_knots_are_anchored_to_the_region_not_spread_evenly():
    # design §3.2: the flats and the plateau each get ONE interval (the trapezoid
    # is exact on a constant), and every subdivision is spent inside an ease.
    ts, _o = ramp.knots(SPEC, DUR)          # region [1.0, 3.0], plateau [1.5, 2.5]
    for boundary in (0.0, 1.0, 1.5, 2.5, 3.0, 4.0):
        assert any(abs(t - boundary) < 1e-9 for t in ts), f"{boundary} not a knot"
    # nothing between 0.0 and the region start, or across the plateau
    assert not [t for t in ts if 1e-9 < t < 1.0 - 1e-9]
    assert not [t for t in ts if 1.5 + 1e-9 < t < 2.5 - 1e-9]
    assert len(ts) == 2 * ramp.RAMP_EASE_KNOTS + 4


def test_knots_drop_zero_width_segments():
    # hold=0 collapses the plateau; a region flush with the window collapses a flat
    ts, _o = ramp.knots(RampSpec(at=2.0, factor=0.5, ease=2.0, hold=0.0), 4.0)
    assert len(ts) == len(set(ts)), "a duplicated knot means a zero-width interval"
    assert ts[0] == 0.0 and ts[-1] == pytest.approx(4.0)
    assert len(ts) == 2 * ramp.RAMP_EASE_KNOTS + 1   # both flats and the plateau gone


def test_output_time_is_strictly_increasing():
    _ts, o = ramp.knots(SPEC, DUR)
    assert all(b > a for a, b in zip(o, o[1:]))


def test_ramp_extra_matches_an_independent_simpson_integration():
    def simpson(f, a, b, n=20000):
        h = (b - a) / n
        s = f(a) + f(b)
        for i in range(1, n):
            s += (4 if i % 2 else 2) * f(a + i * h)
        return s * h / 3

    lo, hi = SPEC.at - SPEC.hold / 2, SPEC.at + SPEC.hold / 2
    ease_int = simpson(lambda t: 1.0 / ramp.speed_at(t, SPEC), lo - SPEC.ease, lo)
    exact = ((lo - SPEC.ease) + ease_int + (hi - lo) / SPEC.factor + ease_int
             + (DUR - (hi + SPEC.ease))) - DUR
    # anchored knots converge to machine precision — the cosine ease's derivative
    # vanishes at both ends, so Euler-Maclaurin's correction terms all die and the
    # trapezoid rule converges exponentially rather than as O(h^2) (design §3.2).
    assert ramp.ramp_extra(SPEC, DUR) == pytest.approx(exact, abs=1e-9)


def test_ramp_extra_is_zero_without_a_ramp():
    assert ramp.ramp_extra(None, DUR) == 0.0


def test_ramp_extra_is_bit_identical_across_window_lengths():
    # design §2: with the region enclosed, the extra is CONSTANT in dur, and §3.2's
    # anchored knots make that true of the APPROXIMATION too, not just the exact
    # integral. This is what makes _bind_pacing's `dur = slot.dur - extra` exact.
    # Evenly spaced knots fail this by 3.3ms and would corrupt every bound length.
    vals = {ramp.ramp_extra(SPEC, d) for d in (3.5, 4.0, 6.0, 9.0)}
    assert len(vals) == 1, f"extra drifts with the window length: {sorted(vals)}"


def test_a_factor_of_one_adds_no_time():
    assert ramp.ramp_extra(RampSpec(at=1.0, factor=1.0, ease=0.3, hold=0.0),
                           3.0) == pytest.approx(0.0, abs=1e-9)


def test_tail_room_is_the_gap_between_the_region_end_and_the_window_end():
    assert ramp.tail_room(SPEC, DUR) == pytest.approx(1.0)   # region ends at 3.0
    assert ramp.tail_room(None, DUR) == DUR


def test_setpts_expr_reconstructs_the_same_knots_it_was_built_from():
    # The expression is piecewise-linear THROUGH the knots, so evaluating it at a
    # knot must return that knot's own value — record and render agree by
    # construction (design §3.3).
    ts, o = ramp.knots(SPEC, DUR)
    expr = ramp.setpts_expr(SPEC, DUR)
    for t, want in zip(ts, o):
        assert _eval_expr(expr, t) == pytest.approx(want, abs=1e-5)


def test_setpts_expr_is_single_valued_and_needs_no_shell_quoting_itself():
    # It contains commas (inside if(lt(...))) — the CALLER must single-quote it
    # inside the -vf string (design §10). The expression itself carries no quotes,
    # so it can be embedded without escaping.
    expr = ramp.setpts_expr(SPEC, DUR)
    assert "," in expr
    assert "'" not in expr and '"' not in expr


def test_max_factor_is_the_floor_over_the_source_rate():
    assert ramp.max_factor(60.0) == pytest.approx(0.4)
    assert ramp.max_factor(30.0) == pytest.approx(0.8)


def test_require_playable_accepts_exactly_the_floor():
    ramp.require_playable(RampSpec(at=1.0, factor=0.4, ease=0.3, hold=0.2),
                          60.0, "ep0")   # 60 * 0.4 == 24.0 exactly


def test_require_playable_refuses_below_the_floor_and_names_the_remedy():
    spec = RampSpec(at=1.0, factor=0.5, ease=0.3, hold=0.2)
    with pytest.raises(ValueError) as ei:
        ramp.require_playable(spec, 30.0, "ep0")
    msg = str(ei.value)
    assert "ep0" in msg and "15.0 unique frames" in msg and "0.8" in msg


def test_validate_window_accepts_a_region_flush_with_both_edges():
    ramp.validate_window(RampSpec(at=2.0, factor=0.5, ease=1.0, hold=2.0),
                         4.0, "ep0")   # region exactly [0.0, 4.0]


def test_validate_window_refuses_a_region_starting_before_the_window():
    with pytest.raises(ValueError, match="starts 0.30s before"):
        ramp.validate_window(RampSpec(at=0.5, factor=0.5, ease=0.5, hold=0.6),
                             4.0, "ep0")


def test_validate_window_refuses_a_region_running_past_the_window():
    with pytest.raises(ValueError, match="ends 0.50s past"):
        ramp.validate_window(SPEC, 2.5, "ep0")   # region ends 3.0, window 2.5


def _eval_expr(expr: str, t: float) -> float:
    """Evaluate one of ffmpeg's `if(lt(T,a),b,c)` expressions in Python, for tests.

    ffmpeg's `if` and `lt` are ordinary function calls and the rest is arithmetic,
    so binding those two names plus `T` is enough — no parsing. `if` is a Python
    keyword, hence the rename; `if(` appears nowhere else in the expression."""
    env = {"_if": lambda c, a, b: a if c else b,
           "lt": lambda a, b: a < b, "T": t}
    return float(eval(expr.replace("if(", "_if("),   # noqa: S307 - test-only
                      {"__builtins__": {}}, env))
