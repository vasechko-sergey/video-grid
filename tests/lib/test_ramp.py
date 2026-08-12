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


def test_the_ease_follows_the_cosine_shape_not_a_straight_line():
    # Coverage hole found by the Task 9 mutation battery: swapping the cosine
    # ease for a straight line (p instead of (1-cos(pi*p))/2) survived the test
    # above. Both shapes agree at p=0 and p=1 by construction, and — the
    # coincidence that hides the mutation — at the EXACT midpoint p=0.5 too,
    # since cos(pi*0.5) == 0 makes (1-cos(pi*0.5))/2 == 0.5 == p. Monotonicity
    # holds for a straight line just as it does for the cosine, so nothing in
    # the test above can tell the two shapes apart. Off-centre is where they
    # diverge: the cosine's derivative vanishes at both ends, so it spends LESS
    # of the speed change near the edges and MORE in the middle — a quarter of
    # the way into the ease it has moved only ~14.6% of the way to `factor`,
    # not the 25% a straight line would give.
    p = 0.25
    lo = SPEC.at - SPEC.hold / 2.0
    t = (lo - SPEC.ease) + p * SPEC.ease
    want_cosine = 1.0 + (SPEC.factor - 1.0) * (1.0 - math.cos(math.pi * p)) / 2.0
    assert ramp.speed_at(t, SPEC) == pytest.approx(want_cosine, abs=1e-9)
    would_be_linear = 1.0 + (SPEC.factor - 1.0) * p
    assert ramp.speed_at(t, SPEC) != pytest.approx(would_be_linear, abs=1e-3)


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


def test_retime_issues_one_setpts_fps_pass_through_proc_run(monkeypatch):
    seen = []
    monkeypatch.setattr(ramp.proc, "run", lambda cmd, **kw: seen.append(cmd))
    monkeypatch.setattr(ramp.ffbin, "ffmpeg", lambda: "/bin/ffmpeg")
    ramp.retime("in.mp4", "out.mp4", SPEC, DUR, 60.0)
    assert len(seen) == 1, "a retime is ONE ffmpeg pass"
    cmd = seen[0]
    vf = cmd[cmd.index("-vf") + 1]
    # single-quoted: the expression's own commas must not split the filter chain
    # into separate ffmpeg filters — ffmpeg's own parser strips the quotes it finds.
    assert vf.startswith("setpts='("), "the setpts expression must open single-quoted"
    quoted_expr, _, _suffix = vf.partition(",fps=")
    assert quoted_expr.endswith("'"), "the setpts expression must be closed (quoted) before ,fps="
    assert vf.endswith(",fps=60"), "setpts alone yields VFR — fps= is mandatory"
    assert "-an" in cmd, "slowed audio is pitch garbage; the segment goes silent"
    assert "-ss" not in cmd


def test_retime_refuses_before_spending_an_encode(monkeypatch):
    monkeypatch.setattr(ramp.proc, "run",
                        lambda *a, **k: pytest.fail("refused specs must not encode"))
    monkeypatch.setattr(ramp.ffbin, "ffmpeg", lambda: "/bin/ffmpeg")
    with pytest.raises(ValueError, match="unique frames per second"):
        ramp.retime("in.mp4", "out.mp4",
                    RampSpec(at=1.0, factor=0.5, ease=0.3, hold=0.2), 3.0, 30.0)


def test_the_retime_argv_passes_the_landmine_lint():
    # What this proves: proc.run's always-on check_argv guard does not refuse a
    # real retime render — the production guarantee that matters, since proc.run
    # raises before spending an encode on anything check_argv flags.
    #
    # It does NOT exercise _element's quote-aware parsing (the fix that stopped a
    # quoted if(lt(...)) from being misread as a comma-separated filter chain,
    # design 2026-08-08 as-built) — two reviewers independently established that
    # check_argv never even calls _element on this argv. _unbounded_source needs a
    # SYNTH_SOURCES name (color=/testsrc/anullsrc/anoisesrc/sine=), _zoompan_defaults
    # needs "zoompan=", and _seek_order returns immediately because neither "-t"
    # nor "-to" is present — none of those trigger strings occur here, so the loops
    # that would call _element never run. The only check doing real work on this
    # argv is the always-on lutrgb scan, and it finds nothing either. The quote-aware
    # parsing itself is exercised by the "_element is quote-aware" section of
    # tests/lib/test_lint.py, built from the real reframe._xexpr emitter — not here.
    from scripts.lib import lint
    expr = ramp.setpts_expr(SPEC, DUR)
    cmd = ["/bin/ffmpeg", "-y", "-v", "error", "-i", "in.mp4",
           "-vf", f"setpts='({expr})/TB',fps=60", "-c:v", "libx264",
           "-crf", "8", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", "out.mp4"]
    assert lint.check_argv(cmd) == []


def _eval_expr(expr: str, t: float) -> float:
    """Evaluate one of ffmpeg's `if(lt(T,a),b,c)` expressions in Python, for tests.

    ffmpeg's `if` and `lt` are ordinary function calls and the rest is arithmetic,
    so binding those two names plus `T` is enough — no parsing. `if` is a Python
    keyword, hence the rename; `if(` appears nowhere else in the expression."""
    env = {"_if": lambda c, a, b: a if c else b,
           "lt": lambda a, b: a < b, "T": t}
    return float(eval(expr.replace("if(", "_if("),   # noqa: S307 - test-only
                      {"__builtins__": {}}, env))
