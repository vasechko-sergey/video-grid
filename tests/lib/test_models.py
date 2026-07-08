import json
import pytest
from scripts.lib import models as m


def test_routepoint_roundtrip():
    d = {"t": 0.5, "x": 300.0, "y": 500.0, "w": 140.0, "h": 320.0}
    p = m.RoutePoint.from_dict(d)
    assert (p.t, p.x, p.y, p.w, p.h) == (0.5, 300.0, 500.0, 140.0, 320.0)
    assert p.to_dict() == d


def test_route_json_roundtrip(tmp_path):
    pts = [m.RoutePoint(i / 30, 300 + i, 500, 140, 320) for i in range(3)]
    fp = tmp_path / "route.json"
    m.route_to_json(pts, fp)
    back = m.route_from_json(fp)
    assert [p.to_dict() for p in back] == [p.to_dict() for p in pts]
    assert isinstance(json.loads(fp.read_text()), list)


def test_trackmeta_roundtrip():
    d = {"hero": 3, "ambiguous": True, "intent": "action", "features": {"3": {"n": 5}}}
    tm = m.TrackMeta.from_dict(d)
    assert tm.hero == 3 and tm.ambiguous is True and tm.intent == "action"
    assert tm.to_dict() == d


def test_trackmeta_hero_none():
    tm = m.TrackMeta.from_dict({"hero": None, "ambiguous": False, "intent": "static", "features": {}})
    assert tm.hero is None and tm.to_dict()["hero"] is None


def test_croppath_json_roundtrip(tmp_path):
    fp = tmp_path / "path.json"
    m.CropPath([100, 101, 102]).to_json(fp)
    assert json.loads(fp.read_text()) == [100, 101, 102]
    assert m.CropPath.from_json(fp).xs == [100, 101, 102]
    assert len(m.CropPath([1, 2, 3])) == 3


def test_checkresult_detail_pass_key_does_not_clobber():
    # detail carrying a stale "pass" must not override the real passed flag
    d = m.CheckResult("on_line", True, {"pass": "stale", "ratio": 0.9}).to_dict()
    assert d == {"ratio": 0.9, "pass": True}


def test_report_overall_and_fail_reasons():
    checks = {
        "on_line": m.CheckResult("on_line", True, {"ratio": 0.95}),
        "jitter": m.CheckResult("jitter", False, {"worst_reversal": 9.0}),
        "framing": m.CheckResult("framing", None, {"status": "editorial-only"}),
    }
    r = m.Report(checks=checks, attempt=2)
    assert r.overall is False
    assert r.fail_reasons == ["jitter"]


def test_report_to_dict_schema():
    checks = {
        "on_line": m.CheckResult("on_line", True, {"ratio": 0.95}),
        "framing": m.CheckResult("framing", None, {"status": "editorial-only"}),
    }
    d = m.Report(checks=checks, attempt=1).to_dict()
    assert d["checks"]["on_line"] == {"ratio": 0.95, "pass": True}      # pass-bearing
    assert d["checks"]["framing"] == {"status": "editorial-only"}       # status-only, no pass key
    assert d["overall"] is True and d["attempt"] == 1 and d["fail_reasons"] == []


def test_report_from_dict_roundtrip(tmp_path):
    src = {"checks": {"on_line": {"ratio": 0.9, "pass": True},
                      "black_frames": {"boundary_lumas": [120.0], "pass": False},
                      "horizon": {"status": "not-implemented"}},
           "overall": False, "attempt": 3, "fail_reasons": ["black_frames"]}
    r = m.Report.from_dict(src)
    assert r.overall is False and r.fail_reasons == ["black_frames"] and r.attempt == 3
    fp = tmp_path / "report.json"
    r.write(fp)
    assert json.loads(fp.read_text())["checks"]["on_line"]["pass"] is True
