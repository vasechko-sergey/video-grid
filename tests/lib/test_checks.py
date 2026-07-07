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
