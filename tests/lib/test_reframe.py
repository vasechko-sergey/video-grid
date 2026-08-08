import pytest

from scripts import reframe
from scripts.lib import layout
from scripts.lib.models import Delivery, LayoutSpec


def _diagonal_route(n=60, x0=855.0, x1=1434.0):
    """The measured shape of a surfer riding ACROSS and TOWARD a beach-side telephoto:
    dx is 30% of frame width (lateral needs 15%) AND the box grows 3.1x (head-on needs
    1.6x), so motion.classify lands in its ambiguous zone and answers "static"."""
    return [dict(t=i / 60, x=x0 + (x1 - x0) * i / (n - 1), y=300.0,
                 w=116 + 21 * i / (n - 1), h=149 + 240 * i / (n - 1)) for i in range(n)]


def test_classify_calls_the_diagonal_shot_static():
    from scripts.lib.motion import classify
    assert classify(_diagonal_route(), 1920, 1080) == ("static", None)


def test_authored_lead_is_honoured_when_the_shot_classifies_static():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    lead = compute_path(route, "lead", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    centred = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    assert lead != centred
    mid = len(route) // 2
    assert abs((route[mid]["x"] - lead[mid]) / 497 - 1 / 3) < 0.02


def test_authored_lead_takes_its_direction_from_the_route():
    from scripts.reframe import compute_path
    right = _diagonal_route()
    left = _diagonal_route(x0=1434.0, x1=855.0)
    mid = len(right) // 2
    pr = compute_path(right, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_ws=[497] * len(right))
    pl = compute_path(left, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_ws=[497] * len(left))
    assert abs((right[mid]["x"] - pr[mid]) / 497 - 1 / 3) < 0.02   # travelling right
    assert abs((left[mid]["x"] - pl[mid]) / 497 - 2 / 3) < 0.02    # travelling left


def test_break_and_center_still_ignore_the_direction_rescue():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    a = compute_path(route, "break", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    b = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    assert a == b


def test_smooth_window_reaches_the_smoother():
    # a wider savgol window must visibly change the path over a noisy route —
    # proves the new parameter is actually threaded into pathsmooth.smooth
    from scripts.reframe import compute_path
    route = [dict(t=i / 60, x=900 + (30 if i % 2 else -30), y=500, w=140, h=320)
             for i in range(40)]
    tight = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                         ("static", None), max_step=99, crop_ws=[497] * len(route),
                         smooth_window=5)
    wide = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=99, crop_ws=[497] * len(route),
                        smooth_window=21)
    assert tight != wide


def test_authored_lead_on_a_degenerate_route_falls_back_to_centre():
    # a 1-point route has no travel direction → an authored lead must take the SAFE
    # centre clamp, not crop_x with classify_direction's arbitrary "right" default.
    # Guards the `len(route) >= 2` conjunct: dropping it makes the rescue fire on a
    # directionless route.
    from scripts.reframe import compute_path
    one = [dict(t=0.0, x=900.0, y=300.0, w=140.0, h=320.0)]
    lead = compute_path(one, "lead", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=12.5, crop_ws=[497])
    centred = compute_path(one, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_ws=[497])
    assert lead == centred


def test_compute_path_places_each_sample_at_its_own_width():
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    wide = reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                                ("static", None), max_step=1e9, crop_ws=[800, 400])
    # a centred crop puts the subject mid-rect: 1000 - 800/2 = 600, then 1000 - 400/2 = 800
    assert wide == [600, 800]


def test_compute_path_refuses_a_width_list_that_is_not_parallel_to_the_route():
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    with pytest.raises(ValueError, match="parallel"):
        reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                             ("static", None), max_step=1e9, crop_ws=[800])


def test_compute_path_refuses_more_widths_than_route_samples():
    # the guard is a length INEQUALITY (!=), not "too few": a too-SHORT list is
    # pinned above. If the guard ever weakened to `<`, a too-LONG crop_ws would
    # slip through silently (zip just drops the extra tail) — this pins the
    # other direction so that mutant can't hide.
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    with pytest.raises(ValueError, match="parallel"):
        reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                             ("static", None), max_step=1e9, crop_ws=[800, 400, 200])


def test_compute_path_lead_places_each_sample_at_its_own_width():
    # the brief's own new test only exercises the center/break clamp branch
    # (g.clamp); `lead` under lateral motion runs the OTHER line (g.crop_x),
    # which zips route against crop_ws separately — nothing else pins that
    # branch varying by width too, not just a constant repeated one.
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    path = reframe.compute_path(route, "lead", "thirds", (1080, 1920), (3840, 2160),
                                ("lateral", "right"), max_step=1e9, crop_ws=[900, 300])
    # lead+right targets the LEFT third line: x - crop_w/3 → 1000-300=700, 1000-100=900
    assert path == [700, 900]


def test_xexpr_emits_the_variable_it_is_given():
    e = reframe._xexpr([0, 100], [0.0, 1.0], var="it")
    assert "it" in e and "(t-" not in e


def test_filter_args_inserts_the_zoompan_between_crop_and_scale():
    # Delivery.mode has no "1080" — native/short_edge/long_edge/exact only (models.py
    # __post_init__). The assertions below only check filter-string ORDER, not the
    # resolved layout's numbers, so "native" (the placeholder used the same way
    # throughout test_layout.py/test_models.py) resolves a valid fast-path layout.
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("native"))
    args = reframe._filter_args(rl, "0", 0, "", 30.0, 3.0,
                                zoom_args="zoompan=z='1':x='0':y='0':d=1:s=8x8:fps=30")
    chain = args[1]
    assert chain.index("crop=") < chain.index("zoompan=") < chain.index("scale=")


def test_filter_args_without_a_zoom_is_unchanged():
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("native"))
    assert (reframe._filter_args(rl, "0", 0, "", 30.0, 3.0)
            == reframe._filter_args(rl, "0", 0, "", 30.0, 3.0, zoom_args=""))
    assert "zoompan" not in reframe._filter_args(rl, "0", 0, "", 30.0, 3.0)[1]
