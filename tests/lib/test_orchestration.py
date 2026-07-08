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
