from scripts.lib import orchestration as orch


def _route_right():
    # subject slides right across the frame
    return [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]


def test_no_contradictions_when_manifest_matches():
    route = _route_right()
    meta = {"ambiguous": False}
    findings = orch.detect_contradictions(motion="lateral:right", hero=None,
                                          route=route, track_meta=meta,
                                          src_w=1920, src_h=1080)
    assert findings == []


def test_direction_reversal_is_a_contradiction():
    route = _route_right()          # tracker sees RIGHT
    findings = orch.detect_contradictions(motion="lateral:left", hero=None,
                                          route=route, track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "motion-mismatch" for f in findings)


def test_ambiguous_hero_without_pin_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None, hero=None,
                                          route=_route_right(),
                                          track_meta={"ambiguous": True},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-ambiguous" for f in findings)


def test_ambiguous_hero_with_pin_is_resolved():
    findings = orch.detect_contradictions(motion=None, hero=(900, 500, 120, 300),
                                          route=_route_right(),
                                          track_meta={"ambiguous": True},
                                          src_w=1920, src_h=1080)
    assert all(f["reason"] != "hero-ambiguous" for f in findings)


def test_empty_route_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None, hero=None, route=[],
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "no-track" for f in findings)


def test_ambiguous_hero_with_empty_pin_is_a_contradiction():
    # a falsy-but-present hero ("" / () / []) is no pin at all → still ambiguous
    for empty in ("", (), []):
        findings = orch.detect_contradictions(motion=None, hero=empty,
                                              route=_route_right(),
                                              track_meta={"ambiguous": True},
                                              src_w=1920, src_h=1080)
        assert any(f["reason"] == "hero-ambiguous" for f in findings), empty


def test_missing_track_meta_does_not_crash():
    findings = orch.detect_contradictions(motion=None, hero=None,
                                          route=_route_right(), track_meta=None,
                                          src_w=1920, src_h=1080)
    assert findings == []


def test_named_or_rule_hero_does_not_resolve_ambiguity():
    # a cast name / rule / garbage hero is truthy but is NOT an applicable seed
    # this slice (cast.json is the ingestion plan) — the shell only seeds a tuple
    # bbox, so a non-tuple hero must NOT silently suppress the §6.1a gate
    for named in ("Lena", {"rule": "largest"}, 42):
        findings = orch.detect_contradictions(motion=None, hero=named,
                                              route=_route_right(),
                                              track_meta={"ambiguous": True},
                                              src_w=1920, src_h=1080)
        assert any(f["reason"] == "hero-ambiguous" for f in findings), named


def test_is_seed_pin_only_true_for_nonempty_tuple():
    assert orch.is_seed_pin((900, 500, 120, 300)) is True
    assert orch.is_seed_pin(()) is False          # empty tuple is no pin
    assert orch.is_seed_pin(None) is False
    assert orch.is_seed_pin("Lena") is False       # cast name → ingestion plan
    assert orch.is_seed_pin({"rule": "largest"}) is False


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
    findings = orch.detect_contradictions(motion=None, hero=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_over_lateral_is_fine():
    route = _route_right()
    findings = orch.detect_contradictions(motion=None, hero=None, route=route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert all(f["reason"] != "composition-motion-mismatch" for f in findings)


def test_center_over_nonlateral_is_fine():
    static_route = [dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)]
    findings = orch.detect_contradictions(motion=None, hero=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="center")
    assert findings == []
