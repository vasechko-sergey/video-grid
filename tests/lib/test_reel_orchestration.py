from scripts.lib import reel_orchestration as ro
from scripts.lib.models import ReelFailure


def test_no_failures_delivers():
    a = ro.next_action([], {}, cap=3)
    assert a.kind == "deliver"


def test_black_fail_reprocesses_with_no_correction():
    a = ro.next_action([ReelFailure("black", "reprocess", 1, {"t": 4.0})], {}, cap=3)
    assert a.kind == "reprocess"
    assert len(a.reprocess) == 1
    assert a.reprocess[0].idx == 1


def test_variety_escalates_to_edit_plan():
    f = ReelFailure("variety", "edit-plan", 1, {"pair": [0, 1], "distance": 2})
    a = ro.next_action([f], {}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["escalate_to"] == "edit-plan" and a.finding["episode_idx"] == 1


def test_length_escalates_to_pacing():
    f = ReelFailure("length", "pacing", None, {"dur": 7.0, "target": 6.0})
    a = ro.next_action([f], {}, cap=3)
    assert a.kind == "escalate" and a.finding["escalate_to"] == "pacing"


def test_capped_episode_escalates():
    # episode 1 already reprocessed `cap` times → escalate, don't loop forever
    a = ro.next_action([ReelFailure("black", "reprocess", 1, {"t": 1.0})],
                       {1: 3}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped" and a.finding["episode_idx"] == 1


def test_escalate_beats_reprocess_in_a_mixed_round():
    # a fixable black fail AND an unfixable variety fail in the same report →
    # escalate immediately (fixing black won't fix the near-duplicate)
    fails = [ReelFailure("black", "reprocess", 1, {"t": 1.0}),
             ReelFailure("variety", "edit-plan", 2, {"distance": 1})]
    a = ro.next_action(fails, {}, cap=3)
    assert a.kind == "escalate" and a.finding["check"] == "variety"


def test_two_distinct_culprits_batch():
    fails = [ReelFailure("black", "reprocess", 0, {"t": 1.0}),
             ReelFailure("black", "reprocess", 2, {"t": 1.0})]
    a = ro.next_action(fails, {}, cap=3)
    assert a.kind == "reprocess"
    assert sorted(i.idx for i in a.reprocess) == [0, 2]


def test_capped_episode_named_even_when_a_fresh_fixable_fail_precedes_it():
    # a fresh fixable black (ep2) listed before a capped black (ep0): the accumulated
    # ep2 item is discarded and the finding names the CAPPED episode, not ep2.
    fails = [ReelFailure("black", "reprocess", 2, {"t": 1.0}),
             ReelFailure("black", "reprocess", 0, {"t": 1.0})]
    a = ro.next_action(fails, {0: 3}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped" and a.finding["episode_idx"] == 0


def _length(dur, target):
    return ReelFailure("length", "pacing", None, {"dur": dur, "target": target})


def test_within_band_shortfall_retimes_to_the_reels_real_length():
    # the reel is 0.7s SHORT of target, inside a 1.0s band → accept the real length
    a = ro.next_action([_length(11.3, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "retime"
    assert a.retime == 11.3
    assert a.reprocess == () and a.finding is None


def test_shortfall_past_the_band_still_escalates():
    a = ro.next_action([_length(10.5, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "escalate"
    assert a.finding["check"] == "length" and a.finding["escalate_to"] == "pacing"
    assert a.retime is None


def test_over_length_reel_is_never_absorbed_even_inside_the_band():
    # the one-sided proof: the SAME 0.7s gap that re-times as a shortfall must escalate
    # when the reel runs LONG — mix refuses a stem longer than its fragment (design §2)
    a = ro.next_action([_length(12.7, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "escalate" and a.finding["check"] == "length"


def test_within_band_shortfall_rides_along_with_a_black_reprocess():
    fails = [_length(11.3, 12.0),
             ReelFailure("black", "reprocess", 1, {"t": 1.0})]
    a = ro.next_action(fails, {}, cap=3, length_retime_max=1.0)
    assert a.kind == "reprocess"
    assert a.reprocess[0].idx == 1
    assert a.retime == 11.3          # adopted first so length stops re-firing while the black fix converges


def test_escalate_still_wins_over_an_absorbable_shortfall():
    # a capped black fail alongside a within-band shortfall → escalate; the pending
    # re-time is discarded with the round (the reel never delivers on an unfixable fault)
    fails = [_length(11.3, 12.0),
             ReelFailure("black", "reprocess", 1, {"t": 1.0})]
    a = ro.next_action(fails, {1: 3}, cap=3, length_retime_max=1.0)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped"
    assert a.retime is None


def test_length_band_defaults_to_zero_so_an_unaware_caller_keeps_escalating():
    # the pure core's conservative default: opting in lives in the spec the driver threads
    a = ro.next_action([_length(11.3, 12.0)], {}, cap=3)
    assert a.kind == "escalate" and a.finding["check"] == "length"


def test_shortfall_exactly_at_the_band_is_absorbed_the_edge_is_inclusive():
    # the absorb window is (gate 0.5s, band 1.0s] — CLOSED at the top, so a gap of exactly
    # the band re-times rather than escalating. Pinned because a threshold's edge is where
    # an off-by-one hides (the pacing _kind/_beats_per_slot band-boundary ethos).
    a = ro.next_action([_length(11.0, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "retime" and a.retime == 11.0


# --- pacing-fixed-point Task 4: outro_fixed refuses the absorb (design 2026-08-16 §5/§6) ---
# NOTE: the task brief's snippet defined a new `_length_fail(dur, target)` helper whose body
# is IDENTICAL to this file's own `_length` (above) — reused `_length` instead of adding a
# duplicate beside it. `next_action` is called via the file's own `ro.` alias, not bare, for
# the same reason.

def test_a_within_band_shortfall_is_absorbed_without_an_outro():
    a = ro.next_action([_length(9.4, 10.0)], {}, 3, 1.0, False)
    assert (a.kind, a.retime) == ("retime", 9.4)


def test_a_within_band_shortfall_escalates_when_the_outro_chose_the_length():
    a = ro.next_action([_length(9.4, 10.0)], {}, 3, 1.0, True)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "outro-length-chosen"
    assert a.finding["escalate_to"] == "pacing"
    assert a.finding["detail"]["dur"] == 9.4
    assert "line + fade" in a.finding["detail"]["why"]


def test_a_past_the_band_shortfall_still_reads_not_auto_fixable_with_an_outro():
    # outro_fixed must not relabel a failure it did not cause.
    a = ro.next_action([_length(8.0, 10.0)], {}, 3, 1.0, True)
    assert a.finding["reason"] == "not-auto-fixable"


def test_an_over_length_reel_is_unchanged_by_outro_fixed():
    for fixed in (False, True):
        a = ro.next_action([_length(11.0, 10.0)], {}, 3, 1.0, fixed)
        assert a.finding["reason"] == "not-auto-fixable"


def test_a_colour_failure_is_no_longer_reprocessable():
    """The colour corrector is retired (design 2026-08-29 §2). Anything that is not a
    black hit escalates instead of being handed a per-channel pull: the pull moved each
    episode's whole-frame mean toward the reel median, which on real footage demanded
    1.41x on one episode's red and 1.75x on all three of another's — against 0.71 dE00
    of headroom, where 1.10x on one channel already costs 3.92."""
    # NOTE: called via the file's own `ro.` alias, not bare `reel_orchestration.` — see the
    # pacing-fixed-point NOTE above; the brief's snippet uses the bare name, but this file
    # imports it as `ro`.
    f = ReelFailure("color_across_cuts", "reprocess", 0,
                    {"target": [130.0, 120.0, 130.0], "culprit_mean": [160.0, 120.0, 130.0]})
    a = ro.next_action([f], {}, 3, 1.0, False)
    assert a.kind == "escalate"
    assert a.reprocess == ()


def test_a_black_failure_still_reprocesses_and_carries_only_an_index():
    b = ReelFailure("black", "reprocess", 1, {"t": 2.0})
    a = ro.next_action([b], {}, 3, 1.0, False)
    assert a.kind == "reprocess"
    assert a.reprocess == (ro.ReprocessItem(1),)


def test_outro_refusal_wins_over_a_simultaneous_reprocess_class_failure():
    # mirrors test_within_band_shortfall_rides_along_with_a_black_reprocess (above),
    # which proves that WITHOUT an outro fit a within-band shortfall rides along with a
    # black reprocess (kind == "reprocess", retime carried on the action). With
    # outro_fixed=True the same pairing must not merge into a reprocess round at all —
    # the outro refusal escalates immediately, and nothing about the black fail (which
    # would otherwise be perfectly fixable on its own) leaks a retime into the result.
    fails = [_length(9.4, 10.0),
             ReelFailure("black", "reprocess", 1, {"t": 1.0})]
    a = ro.next_action(fails, {}, 3, 1.0, True)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "outro-length-chosen"
    assert a.retime is None
    assert a.reprocess == ()
