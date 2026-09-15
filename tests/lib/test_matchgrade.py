import pytest

from scripts.lib import color, matchgrade


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


def test_biased_target_scales_for_the_GAP_bound_not_only_the_0_255_one():
    """Found reviewing this slice's own diff. The first cut scaled only against
    0-255, so on a LOW-CONTRAST reel median nostalgic's +20 on p5 pushed past p50,
    _repair_gaps quietly clamped it back, and k still reported 1.00 — the bias lost
    12-16 luma units while the report claimed it survived whole. Both bounds bind,
    and k must speak for both."""
    t = matchgrade._repair_gaps((49.5, 60.0, 194.5))     # p50-p5 is only 10.5
    got, k = matchgrade.biased_target(t, (20.0, 0.0, -18.0))
    assert k == pytest.approx((10.5 - color.TONE_MIN_GAP) / 20.0)     # the gap, not the ceiling
    assert got[1] - got[0] == pytest.approx(color.TONE_MIN_GAP)       # lands exactly on it
    assert got == pytest.approx((54.0, 60.0, 190.45))
    # and because 20 * 0.225 = 4.5 is under the floor, the report must call it out
    assert matchgrade.bias_ineffective((20.0, 0.0, -18.0), k) is True


def test_tone_decision_round_trips_through_a_dict():
    d = matchgrade.ToneDecision(2, "author", "authored", measured=(10.0, 100.0, 200.0),
                                tone_src=(10.0, 100.0, 200.0), tone_dst=(20.0, 110.0, 210.0))
    assert matchgrade.ToneDecision.from_dict(d.to_dict()) == d


def test_a_skip_round_trips_with_its_null_pair():
    d = matchgrade.ToneDecision(0, "skip", "flat-source", measured=(10.0, 11.0, 12.0))
    assert d.to_dict()["tone_src"] is None
    assert matchgrade.ToneDecision.from_dict(d.to_dict()) == d


def test_match_report_round_trips_through_a_file(tmp_path):
    r = matchgrade.MatchReport(
        target=(76.0, 108.0, 176.0), eps=4.0, edl=str(tmp_path / "EDL.json"),
        decisions=(matchgrade.ToneDecision(0, "author", "authored", measured=(71.0, 102.0, 166.0),
                                           tone_src=(71.0, 102.0, 166.0),
                                           tone_dst=(76.0, 108.0, 176.0)),),
        bias=(20.0, 0.0, -18.0), bias_source="the nostalgic preset", bias_scale=1.0,
        mood="nostalgic")
    p = tmp_path / "MATCH.json"
    r.write(p)
    assert matchgrade.MatchReport.from_json(p) == r


def test_match_report_refuses_a_non_object():
    with pytest.raises(ValueError, match="expected a MATCH.json object"):
        matchgrade.MatchReport.from_dict([1, 2, 3])


def test_match_report_refuses_an_empty_edl_path():
    with pytest.raises(ValueError, match="MatchReport.edl is empty"):
        matchgrade.MatchReport(target=(1.0, 2.0, 3.0), eps=4.0, decisions=(), edl="")


def test_no_drift_when_every_authored_pair_is_still_in_the_edl():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0)),
         matchgrade.ToneDecision(1, "skip", "within-eps", measured=(1.0, 2.0, 3.0))]
    pairs = [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), (None, None)]
    assert matchgrade.tone_drift(d, pairs) == []


def test_a_wiped_pair_is_drift_and_the_reason_names_the_episode():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0))]
    assert matchgrade.tone_drift(d, [(None, None)]) == [
        "episode 0 was authored a tone pair, and the EDL now carries none"]


def test_a_changed_pair_is_drift_and_says_changed_not_wiped():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0))]
    assert matchgrade.tone_drift(d, [((9.0, 9.0, 9.0), (4.0, 5.0, 6.0))]) == [
        "episode 0's tone pair in the EDL is not the one this report authored"]


def test_a_skipped_episode_that_gained_a_pair_is_not_drift():
    # the report asserts nothing about an episode it skipped, so a pair appearing
    # there (a human authoring one by hand) is outside what this report claims
    d = [matchgrade.ToneDecision(0, "skip", "within-eps", measured=(1.0, 2.0, 3.0))]
    assert matchgrade.tone_drift(d, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))]) == []


def test_an_episode_count_change_is_drift_before_any_pair_is_compared():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0)),
         matchgrade.ToneDecision(1, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0))]
    assert matchgrade.tone_drift(d, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))]) == [
        "this report describes 2 episodes and the EDL now has 1 — the cut changed"]


def test_match_report_from_dict_refuses_a_null_eps_with_a_value_error():
    # review finding I-1: eps/bias_scale bypassed the None-safe `d.get(k) or default`
    # pattern used two lines away for bias/bias_source/edl, so an explicit JSON `null`
    # (the key IS present) reached float(None) and raised a bare TypeError instead of
    # the ValueError-with-remedy every other malformed field in this module raises.
    with pytest.raises(ValueError, match="MatchReport.eps"):
        matchgrade.MatchReport.from_dict(
            {"target": [1, 2, 3], "eps": None, "edl": "x.json", "decisions": []})


def test_tone_decision_from_dict_refuses_a_missing_index_with_a_value_error():
    # review finding I-2: index/action/reason were read by bare d["key"] instead of
    # routing through a validated helper the way measured/tone_src/tone_dst do via
    # _triple/_opt_triple, so a decision object missing any of the three raised a bare
    # KeyError instead of the ValueError-with-remedy every other malformed field raises.
    with pytest.raises(ValueError, match="ToneDecision.index"):
        matchgrade.ToneDecision.from_dict(
            {"measured": [1, 2, 3], "action": "skip", "reason": "within-eps"})


def test_tone_decision_round_trips_its_region_rows():
    from scripts.lib import matchgrade
    d = matchgrade.ToneDecision(0, "author", "authored", (10.0, 20.0, 30.0),
                                regions=({"anchor": "toe", "name": "wetsuit",
                                          "of": "subject", "used": "subject",
                                          "fraction": 0.2, "value": 10.0,
                                          "fallback": None},))
    assert matchgrade.ToneDecision.from_dict(d.to_dict()) == d


def test_a_decision_written_before_this_slice_has_no_region_rows():
    from scripts.lib import matchgrade
    d = matchgrade.ToneDecision(0, "skip", "within-eps", (10.0, 20.0, 30.0)).to_dict()
    d.pop("regions")
    assert matchgrade.ToneDecision.from_dict(d).regions == ()
