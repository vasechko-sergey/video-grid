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


TARGET = (20.0, 110.0, 210.0)


def test_plan_authors_a_deviating_valid_episode():
    p = (10.0, 100.0, 150.0)                      # far from TARGET, contrasty
    [d] = matchgrade.plan([p], [False], TARGET)
    assert d.action == "author" and d.reason == "authored"
    assert d.measured == p and d.tone_src == p and d.tone_dst == TARGET


def test_plan_skips_within_eps_with_no_pair_but_keeps_measured():
    p = (21.0, 111.0, 211.0)                      # within eps of TARGET
    [d] = matchgrade.plan([p], [False], TARGET)
    assert d.action == "skip" and d.reason == "within-eps"
    assert d.measured == p                         # measured is carried even on a skip
    assert d.tone_src is None and d.tone_dst is None


def test_plan_skips_a_flat_source():
    p = (126.0, 128.0, 130.0)                     # gaps < 6 → cannot be a src
    [d] = matchgrade.plan([p], [False], TARGET)
    assert d.action == "skip" and d.reason == "flat-source"


def test_plan_respects_a_hand_authored_pair_by_default():
    p = (10.0, 100.0, 150.0)                      # would otherwise author
    [d] = matchgrade.plan([p], [True], TARGET)
    assert d.action == "skip" and d.reason == "hand-authored"
    assert d.measured == p
    assert d.tone_src is None and d.tone_dst is None


def test_plan_force_overrides_hand_authored_and_re_authors():
    p = (10.0, 100.0, 150.0)
    [d] = matchgrade.plan([p], [True], TARGET, force=True)
    assert d.action == "author" and d.tone_src == p and d.tone_dst == TARGET


def test_plan_force_still_skips_a_within_eps_episode():
    # force only bypasses the hand-authored guard, never authors an imperceptible curve
    p = (21.0, 111.0, 211.0)
    [d] = matchgrade.plan([p], [True], TARGET, force=True)
    assert d.action == "skip" and d.reason == "within-eps"


def test_plan_preserves_index_order():
    ps = [(10.0, 100.0, 150.0), (21.0, 111.0, 211.0)]
    ds = matchgrade.plan(ps, [False, False], TARGET)
    assert [d.index for d in ds] == [0, 1]


def test_plan_force_still_skips_a_flat_hand_authored_source():
    # force bypasses ONLY the hand-authored guard; a flat clip still cannot be a src,
    # so it is skipped flat-source with a None pair (driver then CLEARS the stale hand pair).
    p = (126.0, 128.0, 130.0)                      # gaps < 6 → invalid src
    [d] = matchgrade.plan([p], [True], TARGET, force=True)
    assert d.action == "skip" and d.reason == "flat-source"
    assert d.measured == p and d.tone_src is None and d.tone_dst is None


def test_plan_mixed_has_tone_pairs_per_index():
    ps = [(10.0, 100.0, 150.0), (12.0, 102.0, 152.0)]   # both deviate & are contrasty
    ds = matchgrade.plan(ps, [True, False], TARGET)
    assert (ds[0].action, ds[0].reason) == ("skip", "hand-authored")
    assert (ds[1].action, ds[1].reason) == ("author", "authored")
    assert ds[1].tone_src == ps[1] and ds[1].tone_dst == TARGET


def test_plan_refuses_mismatched_parallel_lists():
    with pytest.raises(ValueError, match="parallel lists"):
        matchgrade.plan([(10.0, 100.0, 150.0)], [False, True], TARGET)


def test_biased_target_displaces_and_reports_a_full_scale():
    """The real run's measured median, displaced by the moody vector. k == 1.0
    means the whole displacement survived (design 2026-08-17 §5)."""
    got, k = matchgrade.biased_target((49.5, 100.0, 194.5), (-18.0, -16.0, -8.0))
    assert (got, k) == ((31.5, 84.0, 186.5), 1.0)


def test_biased_target_scales_the_whole_vector_rather_than_clamping_one_anchor():
    """Measured (design §5): at a median of (110, 170, 250) the epic vector cannot
    have its +16 highlight lift, and clamping THAT anchor alone would leave
    'crush the blacks' — a different mood. Scaling keeps the direction and loses
    only magnitude, and k reports how much."""
    got, k = matchgrade.biased_target((110.0, 170.0, 250.0), (-16.0, 0.0, 16.0))
    assert k == pytest.approx(5.0 / 16.0)
    assert got == pytest.approx((105.0, 170.0, 255.0))


def test_biased_target_is_the_identity_at_a_zero_bias():
    """The off switch: no mood -> the median is handed on untouched, so a run
    without --spec authors exactly what it authored before this slice."""
    t = (49.5, 100.0, 194.5)
    assert matchgrade.biased_target(t, (0.0, 0.0, 0.0)) == (t, 1.0)


def test_a_scaled_bias_below_the_floor_is_named_ineffective():
    """5 luma units is under the conductor's own delivery error, so the grade
    cannot show it. The stage does not refuse — it reports (design §5)."""
    assert matchgrade.bias_ineffective((-16.0, 0.0, 16.0), 5.0 / 16.0) is True
    assert matchgrade.bias_ineffective((-16.0, 0.0, 16.0), 1.0) is False
    assert matchgrade.bias_ineffective((0.0, 0.0, 0.0), 1.0) is False
