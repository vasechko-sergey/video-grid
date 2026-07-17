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


def test_unmatched_pin_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"pin_matched": False},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-unmatched" for f in findings)


def test_unmatched_pin_outranks_no_track():
    # an unmatched pin PRODUCES the empty route, so "hero never detected" would be
    # the wrong diagnosis — it would point at the segment or the model
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"pin_matched": False},
                                          src_w=1920, src_h=1080)
    assert [f["reason"] for f in findings] == ["hero-unmatched"]


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


def test_center_over_nonlateral_is_fine():
    static_route = [dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)]
    findings = orch.detect_contradictions(motion=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="center")
    assert findings == []
