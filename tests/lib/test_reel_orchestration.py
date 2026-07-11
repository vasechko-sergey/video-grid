from scripts.lib import reel_orchestration as ro
from scripts.lib.models import ReelFailure


def _color(idx, target, culprit):
    return ReelFailure("color_across_cuts", "reprocess", idx,
                       {"target": target, "culprit_mean": culprit})


def test_no_failures_delivers():
    a = ro.next_action([], {}, cap=3)
    assert a.kind == "deliver"


def test_black_fail_reprocesses_with_no_correction():
    a = ro.next_action([ReelFailure("black", "reprocess", 1, {"t": 4.0})], {}, cap=3)
    assert a.kind == "reprocess"
    assert len(a.reprocess) == 1
    assert a.reprocess[0].idx == 1 and a.reprocess[0].color_correct is None


def test_color_fail_reprocesses_with_the_ratio():
    a = ro.next_action([_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 100.0])], {}, cap=3)
    item = a.reprocess[0]
    assert item.idx == 1
    # per-channel med/d_i
    assert item.color_correct[0] == 120.0 / 150.0
    assert item.color_correct[1] == 1.0
    assert item.color_correct[2] == 120.0 / 100.0


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
    a = ro.next_action([_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])],
                       {1: 3}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped" and a.finding["episode_idx"] == 1


def test_escalate_beats_reprocess_in_a_mixed_round():
    # a fixable colour fail AND an unfixable variety fail in the same report →
    # escalate immediately (fixing colour won't fix the near-duplicate)
    fails = [_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
             ReelFailure("variety", "edit-plan", 2, {"distance": 1})]
    a = ro.next_action(fails, {}, cap=3)
    assert a.kind == "escalate" and a.finding["check"] == "variety"


def test_two_distinct_culprits_batch():
    fails = [ReelFailure("black", "reprocess", 0, {"t": 1.0}),
             _color(2, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    a = ro.next_action(fails, {}, cap=3)
    assert a.kind == "reprocess"
    assert sorted(i.idx for i in a.reprocess) == [0, 2]


def test_black_and_colour_same_episode_dedupe_to_colour():
    # a colour reprocess also re-encodes, so it subsumes the bare black re-encode
    fails = [ReelFailure("black", "reprocess", 1, {"t": 1.0}),
             _color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    a = ro.next_action(fails, {}, cap=3)
    assert len(a.reprocess) == 1
    assert a.reprocess[0].idx == 1 and a.reprocess[0].color_correct is not None


def test_capped_episode_named_even_when_a_fresh_fixable_fail_precedes_it():
    # a fresh fixable colour (ep2) listed before a capped black (ep0): the accumulated
    # ep2 item is discarded and the finding names the CAPPED episode, not ep2.
    fails = [_color(2, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
             ReelFailure("black", "reprocess", 0, {"t": 1.0})]
    a = ro.next_action(fails, {0: 3}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped" and a.finding["episode_idx"] == 0


def test_correction_guards_a_zero_culprit_channel():
    # a fully-black culprit channel (mean 0) can't be lifted by any gain → 1.0 no-op, not a crash
    a = ro.next_action([_color(1, [120.0, 120.0, 120.0], [150.0, 0.0, 120.0])], {}, cap=3)
    item = a.reprocess[0]
    assert item.color_correct[0] == 120.0 / 150.0
    assert item.color_correct[1] == 1.0          # 0-mean channel → no-op, guarded
    assert item.color_correct[2] == 1.0


def test_colour_then_black_same_episode_still_dedupes_to_colour():
    # reverse of the black-then-colour test: colour first, then a bare black on the same
    # episode must NOT overwrite the colour item (a black re-encode is subsumed).
    fails = [_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
             ReelFailure("black", "reprocess", 1, {"t": 1.0})]
    a = ro.next_action(fails, {}, cap=3)
    assert len(a.reprocess) == 1
    assert a.reprocess[0].idx == 1 and a.reprocess[0].color_correct is not None
