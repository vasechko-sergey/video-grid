import pytest

from scripts.lib import checks as ck

def test_on_line_pass_when_subject_on_third():
    # crop_w=600, subject sits at left third (0.333) each frame
    route = [dict(x=200 + 0.333 * 600) for _ in range(30)]  # x = 400
    path = [200] * 30   # crop_x=200 → subject_frac = (400-200)/600 = 0.333
    res = ck.on_line(route, path, crop_w=600, target_frac=1/3, tol=0.05)
    assert res["pass"] is True
    assert res["ratio"] == 1.0

def test_on_line_fail_when_off():
    route = [dict(x=560) for _ in range(30)]   # frac = (560-200)/600 = 0.6
    path = [200] * 30
    res = ck.on_line(route, path, crop_w=600, target_frac=1/3, tol=0.05)
    assert res["pass"] is False

def test_jitter_flags_reversal():
    # moving right: crop_x should be non-decreasing; a big backward step fails
    path = [100, 110, 120, 90, 130]   # -30 reversal
    res = ck.jitter(path, direction="right", max_reversal=10)
    assert res["pass"] is False

def test_jitter_pass_monotonic():
    path = [100, 108, 115, 121, 130]
    res = ck.jitter(path, direction="right", max_reversal=10)
    assert res["pass"] is True

def test_length_within_tolerance():
    assert ck.length(actual=5.3, target=5.0, tol=0.5)["pass"] is True
    assert ck.length(actual=6.0, target=5.0, tol=0.5)["pass"] is False

def test_continuity_flags_teleport():
    # an ID switch reads as an x-teleport in the followed route (spec §6.1a)
    route = [dict(x=100.0 + i * 10) for i in range(10)]
    route[5]["x"] = 900.0
    assert ck.continuity(route, src_w=1920)["pass"] is False

def test_continuity_pass_smooth():
    route = [dict(x=100.0 + i * 10) for i in range(30)]
    assert ck.continuity(route, src_w=1920)["pass"] is True

def test_on_line_rejects_length_mismatch():
    route = [dict(x=400)] * 10
    path = [200] * 9
    with pytest.raises(ValueError, match="length mismatch"):
        ck.on_line(route, path, crop_w=600, target_frac=1/3)

def test_jitter_rejects_invalid_direction():
    with pytest.raises(ValueError, match="direction"):
        ck.jitter([100, 110], direction=None, max_reversal=10)


def _route(xs):
    return [{"x": float(x), "y": 0.0} for x in xs]


def test_jitter_forgives_the_subject_s_own_backtrack():
    # a surfer carving back up the wave: the crop reverses because the SUBJECT did.
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 90, 130])       # subject moved exactly the same way
    assert ck.jitter(path, "right", max_reversal=10)["pass"] is False        # no route: fails
    assert ck.jitter(path, "right", max_reversal=10, route=route)["pass"] is True


def test_jitter_still_fails_chatter_over_a_smooth_subject():
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 130, 140])      # subject never went backwards
    assert ck.jitter(path, "right", max_reversal=10, route=route)["pass"] is False


def test_jitter_fails_the_excess_beyond_the_subject_s_backtrack():
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 115, 130])      # subject reversed 5, crop reversed 30
    res = ck.jitter(path, "right", max_reversal=10, route=route)
    assert res["pass"] is False
    assert res["worst_reversal"] == 25


def test_jitter_route_window_filters_detector_noise_not_subject_motion():
    subj = [100 + 2 * i for i in range(40)]
    noise = [(6 if i % 2 else -6) for i in range(40)]
    route = _route([s + n for s, n in zip(subj, noise)])
    path = [s + n for s, n in zip(subj, noise)]          # crop copies the noise verbatim
    assert ck.jitter(path, "right", 3.0, route=route)["pass"] is True     # blind
    assert ck.jitter(path, "right", 3.0, route=route, route_window=5)["pass"] is False


def test_jitter_route_window_lets_a_smooth_crop_pass_over_a_noisy_route():
    subj = [100 + 2 * i for i in range(40)]
    route = _route([s + (6 if i % 2 else -6) for i, s in enumerate(subj)])
    assert ck.jitter(subj, "right", 3.0, route=route, route_window=5)["pass"] is True


def test_jitter_route_window_of_one_is_the_historical_behaviour():
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 90, 130])
    assert (ck.jitter(path, "right", 10, route=route)
            == ck.jitter(path, "right", 10, route=route, route_window=1))


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, None])
def test_jitter_rejects_a_bad_route_window(bad):
    with pytest.raises(ValueError, match="route_window"):
        ck.jitter([100, 110], "right", 10, route=_route([100, 110]), route_window=bad)


def test_jitter_reports_reversal_count():
    path = [100, 110, 105, 115, 110]               # two reversals
    res = ck.jitter(path, "right", max_reversal=10)
    assert res["reversals"] == 2
