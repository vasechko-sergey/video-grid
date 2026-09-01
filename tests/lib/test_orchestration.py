import pytest

from scripts.lib import orchestration as orch


def _route_right():
    # subject slides right across the frame
    return [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]


def test_no_contradictions_when_manifest_matches():
    route = _route_right()
    meta = {"ambiguous": False}
    findings = orch.detect_contradictions(motion="lateral:right",
                                          route=route, track_meta=meta,
                                          src_w=1920, src_h=1080)
    assert findings == []


def test_direction_reversal_is_a_contradiction():
    route = _route_right()          # tracker sees RIGHT
    findings = orch.detect_contradictions(motion="lateral:left",
                                          route=route, track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "motion-mismatch" for f in findings)


def test_ambiguous_hero_without_pin_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None,
                                          route=_route_right(),
                                          track_meta={"ambiguous": True},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-ambiguous" for f in findings)


def test_empty_route_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "no-track" for f in findings)


def test_missing_track_meta_does_not_crash():
    findings = orch.detect_contradictions(motion=None,
                                          route=_route_right(), track_meta=None,
                                          src_w=1920, src_h=1080)
    assert findings == []


# `features` is TrackMeta's per-track dict — non-empty ⇔ the tracker confirmed
# somebody. It is what tells the two empty-route stories apart, so every
# pin_matched=False case below must state it rather than leave it to a default.
_TRACKED = {"1": {"n": 10, "disp": 0.0, "area": 100.0, "speed": 0.0, "border": 0.0}}


def test_unmatched_pin_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"pin_matched": False,
                                                      "features": _TRACKED},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-unmatched" for f in findings)


def test_unmatched_pin_outranks_no_track():
    # an unmatched pin PRODUCES the empty route, so "hero never detected" would be
    # the wrong diagnosis — it would point at the segment or the model. The
    # rationale needs somebody to have BEEN tracked (else the pin produced nothing
    # and the detector did), which is what _TRACKED supplies.
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"pin_matched": False,
                                                      "features": _TRACKED},
                                          src_w=1920, src_h=1080)
    assert [f["reason"] for f in findings] == ["hero-unmatched"]


def test_no_detections_at_all_is_no_track_even_with_a_pin():
    """Empty `features` = the tracker confirmed NOBODY, so the DETECTOR produced the
    empty route, not the pin — and hero-unmatched's pre-emption exists only because
    an unmatched pin produces it. Here that rationale is simply false.

    A rule pin is the plainest proof: `_rule_track({}, "largest")` returns None for
    an empty feats, so pin_matched=False — yet a rule names no person and claims no
    identity, so hero-unmatched's "the pinned person may not be in this episode, or
    the cast descriptor may not survive its lighting" is a diagnosis of a claim the
    pin never made. no-track's "check the segment, model size, or hero pin" is the
    honest one, and it already lists the pin as one of the three things to check.
    """
    for pin_matched in (False, None):
        findings = orch.detect_contradictions(motion=None, route=[],
                                              track_meta={"pin_matched": pin_matched,
                                                          "features": {}},
                                              src_w=1920, src_h=1080)
        assert [f["reason"] for f in findings] == ["no-track"], pin_matched


def test_matched_pin_is_not_a_contradiction():
    findings = orch.detect_contradictions(motion=None, route=_route_right(),
                                          track_meta={"pin_matched": True, "ambiguous": False},
                                          src_w=1920, src_h=1080)
    assert findings == []


def test_ambiguity_fires_even_with_a_pin():
    # a cast pin matching two look-alikes: the pin is what is ambiguous, so the
    # gate MUST fire — the old is_seed_pin suppression had this exactly backwards
    findings = orch.detect_contradictions(motion=None, route=_route_right(),
                                          track_meta={"pin_matched": True, "ambiguous": True},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-ambiguous" for f in findings)


def test_ambiguous_pin_is_not_told_to_pin_a_hero():
    """The remedy IS the next action, so it must differ by whether a pin was given.

    pin_matched=None is "nobody pinned, scoring tied" → "pin a hero" is the action.
    pin_matched=True + ambiguous is only ever produced by the cast rung
    (_descriptor_track): the human DID pin, and that pin tied — so "pin a hero ...
    and retry" tells them to re-run the exact thing that just failed.
    """
    pinned = orch.detect_contradictions(motion=None, route=_route_right(),
                                        track_meta={"pin_matched": True, "ambiguous": True},
                                        src_w=1920, src_h=1080)
    unpinned = orch.detect_contradictions(motion=None, route=_route_right(),
                                          track_meta={"pin_matched": None, "ambiguous": True},
                                          src_w=1920, src_h=1080)
    assert [f["reason"] for f in pinned] == ["hero-ambiguous"]      # same machine-readable reason
    assert pinned[0]["detail"] != unpinned[0]["detail"]             # different next action
    assert "pin a hero" not in pinned[0]["detail"]                  # they already did
    assert "pin a hero" in unpinned[0]["detail"]                    # here it IS the action


def test_default_params():
    assert orch.DEFAULT_PARAMS["max_speed"] == 750.0


def test_on_line_fail_raises_speed():
    p = orch.adjust_reframe_params({"max_speed": 750.0}, ["on_line"])
    assert p["max_speed"] > 750.0          # crop lagged the line → let it catch up


def test_jitter_fail_lowers_speed():
    p = orch.adjust_reframe_params({"max_speed": 750.0}, ["jitter"])
    assert p["max_speed"] < 750.0          # too twitchy → damp harder


def test_unfixable_reasons_escalate_immediately():
    # length/continuity/black_frames can't be fixed by reframe params
    esc = orch.escalation(attempt=1, fail_reasons=["length"], max_attempts=3)
    assert esc is not None and esc["escalate_to"] == "edit-plan"


def test_conflicting_fails_escalate_immediately():
    # on_line wants faster, jitter wants slower — unsatisfiable by speed alone
    esc = orch.escalation(attempt=1, fail_reasons=["on_line", "jitter"], max_attempts=3)
    assert esc is not None


def test_fixable_fail_retries_until_cap():
    assert orch.escalation(attempt=1, fail_reasons=["on_line"], max_attempts=3) is None
    assert orch.escalation(attempt=2, fail_reasons=["on_line"], max_attempts=3) is None
    esc = orch.escalation(attempt=3, fail_reasons=["on_line"], max_attempts=3)
    assert esc is not None and esc["reason"] == "max-retries"


def test_centered_fail_adjusts_like_on_line():
    # centered is on_line at target_frac=0.5 — same crop-lag signal (center comp)
    p = orch.adjust_reframe_params({"max_speed": 750.0}, ["centered"])
    assert p["max_speed"] > 750.0


def test_centered_jitter_conflict_escalates():
    esc = orch.escalation(attempt=1, fail_reasons=["centered", "jitter"], max_attempts=3)
    assert esc is not None and esc["reason"] == "conflicting-framing-fails"


def test_derive_intent_from_manifest():
    # center or declared static/head-on → static; lateral or infer+lead → action
    assert orch.derive_intent("center", None) == "static"
    assert orch.derive_intent("lead", "static") == "static"
    assert orch.derive_intent("lead", "head-on") == "static"
    assert orch.derive_intent("lead", "lateral:right") == "action"
    assert orch.derive_intent("lead", None) == "action"          # infer → lateral-action default
    assert orch.derive_intent("break", None) == "action"


def test_lead_over_nonlateral_is_a_contradiction():
    # lead composition but the tracker route is not lateral → stop_and_report, no wasted reframes
    static_route = [dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)]  # no dx
    findings = orch.detect_contradictions(motion=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_over_lateral_is_fine():
    route = _route_right()
    findings = orch.detect_contradictions(motion=None, route=route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert all(f["reason"] != "composition-motion-mismatch" for f in findings)


def _diagonal():
    """Crosses the frame AND grows toward the camera — classify's ambiguous zone,
    which answers "static" even though |dx| is 30% of frame width."""
    return [dict(t=i / 60, x=855 + 579 * i / 59, y=300,
                 w=116 + 21 * i / 59, h=149 + 240 * i / 59) for i in range(60)]


def test_lead_is_allowed_when_the_subject_travels_even_if_classify_says_static():
    from scripts.lib.motion import classify
    route = _diagonal()
    assert classify(route, 1920, 1080)[0] == "static"          # the premise
    findings = orch.detect_contradictions(motion=None, route=route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert not any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_is_allowed_when_the_subject_travels_left():
    # the mirror of the rightward case: classify still says "static" (ambiguous zone),
    # but the subject travels — leftward. Guards the abs() in `travels`: without it,
    # dx=-579 fails `>= 288` and the lead is wrongly refused.
    from scripts.lib.motion import classify
    route = [dict(t=i / 60, x=1434 - 579 * i / 59, y=300,
                  w=116 + 21 * i / 59, h=149 + 240 * i / 59) for i in range(60)]
    assert classify(route, 1920, 1080)[0] == "static"          # still the ambiguous zone
    findings = orch.detect_contradictions(motion=None, route=route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert not any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_is_still_refused_when_the_subject_does_not_travel():
    parked = [dict(t=i / 60, x=900 + i * 0.2, y=300, w=120, h=300) for i in range(60)]
    findings = orch.detect_contradictions(motion=None, route=parked,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_over_a_plain_lateral_shot_is_unchanged():
    findings = orch.detect_contradictions(motion=None, route=_route_right(),
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert not any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_center_over_nonlateral_is_fine():
    static_route = [dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)]
    findings = orch.detect_contradictions(motion=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="center")
    assert findings == []


@pytest.mark.parametrize("pinned,empty,expected", [
    (False, True,  True),    # unpinned + nobody detected → optical-flow may help
    (True,  True,  False),   # pinned + empty → hero-unmatched, NOT a motion-blob stand-in
    (False, False, False),   # a non-empty route needs no fallback
    (True,  False, False),   # a pin that matched needs no fallback
])
def test_flow_eligible(pinned, empty, expected):
    assert orch.flow_eligible(pinned, route_empty=empty) is expected


def test_jitter_fail_also_widens_the_smoothing_window():
    # the knob that actually reaches this failure: the jitter check fires on
    # low-amplitude reversals that sit under any max_speed the ladder reaches
    p = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["jitter"])
    assert p["smooth_window_s"] > orch.DEFAULT_PARAMS["smooth_window_s"]


def test_smoothing_window_ladder_is_bounded():
    p = dict(orch.DEFAULT_PARAMS)
    for _ in range(20):
        p = orch.adjust_reframe_params(p, ["jitter"])
    assert p["smooth_window_s"] == orch.SMOOTH_WINDOW_S_MAX


def test_line_lag_narrows_the_window_but_never_below_the_default():
    wide = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["jitter"])
    back = orch.adjust_reframe_params(wide, ["on_line"])
    assert back["smooth_window_s"] < wide["smooth_window_s"]
    assert back["smooth_window_s"] >= orch.DEFAULT_PARAMS["smooth_window_s"]


def test_line_lag_floor_binds_from_the_default():
    # one on_line nudge from the default: x/2 == 0.125 unfloored, which the floor
    # must lift back to the default — deleting max(DEFAULT, ...) drops it to 0.125
    p = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["on_line"])
    assert p["smooth_window_s"] == orch.DEFAULT_PARAMS["smooth_window_s"]


def test_adjust_fills_a_partial_params_dict():
    # a caller that only knows about max_speed still gets both knobs back...
    p = orch.adjust_reframe_params({"max_speed": 300.0}, ["jitter"])
    assert set(p) == set(orch.DEFAULT_PARAMS)
    # ...and its OWN value survives the fill (proves {**DEFAULT, **params} order,
    # not the reversed spread that would clobber it back to 750.0)
    assert p["max_speed"] == 300.0 * 0.6


# --- housekeeping Task 1: adjust_reframe_params gains a `floor` (design §1.2) ---
# NOTE: the task brief's snippets called adjust_reframe_params(...) bare, but this
# file imports the module aliased (`from scripts.lib import orchestration as orch`,
# top of file) with no bare name ever bound — swapped to orch.adjust_reframe_params(...),
# matching every other call in this file.

def test_lag_halves_the_window_but_never_below_the_authored_floor():
    p = orch.adjust_reframe_params({"smooth_window_s": 0.6}, ["on_line"], floor=0.6)
    assert p["smooth_window_s"] == 0.6          # 0.3 would discard the author's ask


def test_floor_none_keeps_todays_default_floor():
    p = orch.adjust_reframe_params({"smooth_window_s": 0.3}, ["on_line"])
    assert p["smooth_window_s"] == 0.25         # DEFAULT_PARAMS floor, unchanged


def test_floor_at_or_under_the_ceiling_leaves_the_jitter_branch_alone():
    # Below SMOOTH_WINDOW_S_MAX the jitter widening is untouched by an authored floor.
    # 0.1, deliberately: it doubles to 0.2, well clear of the 0.6 floor under test. A
    # start of 0.3 would double to exactly 0.6, and a mutation that leaked `floor` into
    # this branch as another max() would then produce 0.6 either way and pass unseen.
    with_floor = orch.adjust_reframe_params({"smooth_window_s": 0.1}, ["jitter"], floor=0.6)
    without_floor = orch.adjust_reframe_params({"smooth_window_s": 0.1}, ["jitter"])
    assert with_floor["smooth_window_s"] == without_floor["smooth_window_s"] == 0.2


@pytest.mark.parametrize("authored", [0.8, 1.2, 2.0])
def test_jitter_never_narrows_a_window_wider_than_the_ceiling(authored):
    # The other end of the same discard the `floor` exists to stop, found by the
    # whole-branch review. SMOOTH_WINDOW_S_MAX is 0.7 but the EDL/manifest/ReframeSpec
    # band is (0, 2.0], so a plain min(0.7, ...) turned an authored 0.8/1.2/2.0 into
    # 0.7 — the WIDENING branch narrowing the author's ask. Unreachable before the
    # window became authorable, because params always started at 0.25.
    p = orch.adjust_reframe_params({"smooth_window_s": authored}, ["jitter"], floor=authored)
    assert p["smooth_window_s"] == authored


def test_jitter_still_refuses_to_widen_past_the_ceiling_on_its_own():
    # The ladder's own initiative is still capped at 0.7 — only an author may exceed it.
    p = orch.adjust_reframe_params({"smooth_window_s": 0.5}, ["jitter"])
    assert p["smooth_window_s"] == orch.SMOOTH_WINDOW_S_MAX == 0.7


# --- Task 3 (design 2026-08-28 §3): grade_damage becomes unfixable-by-reframe ---
# (renamed from color_fidelity 2026-08-31 §3: the dE00 verdict became an entropy
# ratio, but the "reframe can't fix a colour fault" reasoning is unchanged.)

def test_a_colour_failure_escalates_immediately_with_its_own_reason():
    """Reframe params are geometry knobs; no value of max_speed or smooth_window_s
    moves a colour. Without this the episode is re-rendered at full resolution three
    times before escalating, and then escalates naming only what cannot fix it."""
    esc = orch.escalation(attempt=1, fail_reasons=["grade_damage"])
    assert esc is not None
    assert esc["reason"] == "grade-damage"
    assert esc["escalate_to"] == "edit-plan"


def test_an_upstream_failure_still_outranks_the_colour_reason():
    """A segment that is the wrong length is the more upstream fault; reporting
    'grade-damage' there would send the author to the colour block for a problem
    the colour block cannot fix. The order of _UNFIXABLE decides, not the order the
    checks happened to run in."""
    esc = orch.escalation(attempt=1, fail_reasons=["grade_damage", "length"])
    assert esc["reason"] == "unfixable-by-reframe"


def test_colour_is_listed_as_unfixable():
    assert "grade_damage" in orch._UNFIXABLE


def test_grade_damage_is_unfixable_and_names_its_own_remedy():
    # NOTE: the brief for this test named `orchestration.next_action(...).kind` /
    # `.finding` — that API lives in scripts/lib/reel_orchestration.py (reel-level
    # retry), not this per-episode module, which escalates through `escalation()`
    # returning a plain dict. Adapted to the real API; the claim under test
    # (grade_damage is unfixable-by-reframe and names its own "grade-damage"
    # remedy) is unchanged, and is also covered above by
    # test_a_colour_failure_escalates_immediately_with_its_own_reason.
    esc = orch.escalation(attempt=1, fail_reasons=["grade_damage"], max_attempts=3)
    assert esc is not None
    assert esc["escalate_to"] == "edit-plan"
    assert esc["reason"] == "grade-damage"


def test_color_fidelity_is_no_longer_a_known_unfixable():
    assert "color_fidelity" not in orch._UNFIXABLE
