import pytest

from scripts.lib import matchgrade


def test_common_target_is_the_per_anchor_median_odd_count():
    profiles = [(10.0, 100.0, 200.0), (30.0, 120.0, 210.0), (20.0, 110.0, 220.0)]
    assert matchgrade.common_target(profiles) == (20.0, 110.0, 210.0)


def test_common_target_median_even_count_averages_the_two_middles():
    # statistics.median of an even column averages the two middle values
    profiles = [(10.0, 100.0, 200.0), (30.0, 120.0, 240.0)]
    assert matchgrade.common_target(profiles) == (20.0, 110.0, 220.0)


def test_common_target_widens_a_too_narrow_median_to_the_gap():
    # every episode almost flat around 128 → median (126,128,130) has 2-unit gaps;
    # the SYNTHETIC target is spread to >= TONE_MIN_GAP (6) around the middle anchor.
    profiles = [(126.0, 128.0, 130.0), (126.0, 128.0, 130.0)]
    p5, p50, p95 = matchgrade.common_target(profiles)
    assert p50 == 128.0 and p50 - p5 >= 6.0 and p95 - p50 >= 6.0


def test_common_target_refuses_a_reel_with_no_tonal_range():
    # a median pinned at an edge cannot be spread inside 0-255 → fail loud
    with pytest.raises(ValueError, match="no usable tonal range"):
        matchgrade.common_target([(2.0, 3.0, 4.0), (2.0, 3.0, 4.0)])


def test_common_target_empty_is_refused():
    with pytest.raises(ValueError, match="no profiles"):
        matchgrade.common_target([])
