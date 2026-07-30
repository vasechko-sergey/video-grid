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
    # the SYNTHETIC target is spread to exactly TONE_MIN_GAP (6) around the middle anchor.
    profiles = [(126.0, 128.0, 130.0), (126.0, 128.0, 130.0)]
    assert matchgrade.common_target(profiles) == (122.0, 128.0, 134.0)


def test_common_target_refuses_a_reel_with_no_tonal_range():
    # a median pinned at an edge cannot be spread inside 0-255 → fail loud
    with pytest.raises(ValueError, match="no usable tonal range"):
        matchgrade.common_target([(2.0, 3.0, 4.0), (2.0, 3.0, 4.0)])


def test_common_target_refuses_a_reel_pinned_at_the_bright_edge():
    # mirror of the near-0 case: a median pinned near 255 cannot be spread either
    with pytest.raises(ValueError, match="no usable tonal range"):
        matchgrade.common_target([(250.0, 252.0, 253.0), (250.0, 252.0, 253.0)])


def test_common_target_empty_is_refused():
    with pytest.raises(ValueError, match="no profiles"):
        matchgrade.common_target([])


def test_valid_src_true_for_a_contrasty_profile():
    assert matchgrade.valid_src((10.0, 100.0, 200.0)) is True


def test_valid_src_false_for_a_flat_profile():
    # gaps below TONE_MIN_GAP (6): color.tone_arg would reject it as a source
    assert matchgrade.valid_src((126.0, 128.0, 130.0)) is False


def test_valid_src_boundary_exactly_the_gap_is_valid():
    assert matchgrade.valid_src((100.0, 106.0, 112.0)) is True


def test_needs_tone_false_within_eps():
    # every anchor within MATCH_EPS (4) of the target
    assert matchgrade.needs_tone((102.0, 128.0, 200.0), (100.0, 128.0, 203.0)) is False


def test_needs_tone_true_when_one_anchor_exceeds_eps():
    assert matchgrade.needs_tone((100.0, 128.0, 210.0), (100.0, 128.0, 200.0)) is True


def test_needs_tone_boundary_exactly_eps_is_not_enough():
    # distance == eps is NOT "beyond" — strict >
    assert matchgrade.needs_tone((104.0, 128.0, 200.0), (100.0, 128.0, 200.0),
                                 eps=4.0) is False
