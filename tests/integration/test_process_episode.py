import json
from pathlib import Path
import pytest
from scripts import process_episode as pe


def _manifest(tmp_path, **over):
    d = dict(segment=str(tmp_path / "seg.mp4"), out_path=str(tmp_path / "ep.mp4"),
             composition="lead", grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def _stub_engine(monkeypatch, tmp_path, *, route=None, report=None, dims=(1920, 1080, 30.0)):
    """Patch track/reframe/storyboard/check_episode with canned behavior and
    record the args the shell passes (to assert the contract threading)."""
    calls = {}
    route = route or [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]

    def fake_build_route(src, out=None, **k):
        Path(out).write_text(json.dumps(route))
        Path(out).with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))
        return route
    monkeypatch.setattr(pe.track, "build_route", fake_build_route)

    monkeypatch.setattr(pe.reframe, "_probe", lambda src: dims)

    def fake_reframe(src, route_path, out, composition, grid, canvas, color_means,
                     stabilize, path_out, max_speed=750.0):
        calls["reframe"] = dict(canvas=canvas, max_speed=max_speed)
        Path(out).write_text("clip")
        Path(path_out).write_text(json.dumps([100] * len(route)))
        return out
    monkeypatch.setattr(pe.reframe, "reframe", fake_reframe)

    monkeypatch.setattr(pe.storyboard, "build",
                        lambda src, out, **k: (Path(out).write_text("sheet"), out)[1])

    default_report = {"checks": {}, "overall": True, "attempt": 1, "fail_reasons": []}

    def fake_run(clip, route_path, path_path, composition, grid, target_dur, out,
                 canvas=(9, 16), src_dims=(1920, 1080), attempt=1):
        calls["check"] = dict(canvas=canvas, src_dims=src_dims, attempt=attempt)
        r = dict(report or default_report); r["attempt"] = attempt
        Path(out).write_text(json.dumps(r))
        return r
    monkeypatch.setattr(pe.check_episode, "run", fake_run)
    return calls


def test_happy_path_returns_mechanical_pass(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path, dims=(3840, 2160, 59.94))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert result["attempt"] == 1
    assert Path(result["clip"]).exists()
    assert Path(result["storyboard"]).exists()
    # contract: check_episode gets the PROBED dims, not the 1920x1080 default
    assert calls["check"]["src_dims"] == (3840, 2160)
    assert calls["check"]["canvas"] == (9, 16)


def test_timings_recorded_per_stage(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert set(result["timings"]) >= {"track", "reframe", "check", "storyboard"}
    assert all(v >= 0 for v in result["timings"].values())


def test_frozen_route_skips_tracking(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    # if a route_path is supplied, build_route must NOT be called (answer channel)
    def boom(*a, **k):
        raise AssertionError("build_route should be skipped when route_path given")
    monkeypatch.setattr(pe.track, "build_route", boom)
    rp = tmp_path / "frozen.json"
    rp.write_text(json.dumps([dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320)
                              for i in range(10)]))
    (tmp_path / "frozen.meta.json").write_text(json.dumps({"ambiguous": False}))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path),
                                route_path=str(rp))
    assert result["status"] == "mechanical_pass"


def test_invalid_manifest_returns_needs_input(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path))
    assert result["status"] == "needs_input"
    assert any("stabilize" in p for p in result["problems"])
    assert result["attempt"] == 0


def test_creates_missing_project_dir(monkeypatch, tmp_path):
    # first real run: a fresh per-episode scratch dir must be created, not crash
    _stub_engine(monkeypatch, tmp_path)
    proj = tmp_path / "work" / "ep01"          # does not exist yet
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(proj))
    assert result["status"] == "mechanical_pass"
    assert proj.is_dir()


def test_max_attempts_zero_rejected(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="max_attempts"):
        pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path),
                           max_attempts=0)


def _report(overall, fail_reasons):
    return {"checks": {}, "overall": overall, "attempt": 1, "fail_reasons": fail_reasons}


def test_retry_then_pass(monkeypatch, tmp_path):
    # first check fails on_line, second passes → attempt 2, two reframe calls
    _stub_engine(monkeypatch, tmp_path)
    seq = [_report(False, ["on_line"]), _report(True, [])]
    speeds = []

    def fake_run(clip, route_path, path_path, composition, grid, target_dur, out,
                 canvas=(9, 16), src_dims=(1920, 1080), attempt=1):
        r = dict(seq[attempt - 1]); r["attempt"] = attempt
        Path(out).write_text(json.dumps(r))
        return r
    monkeypatch.setattr(pe.check_episode, "run", fake_run)

    def fake_reframe(src, route_path, out, composition, grid, canvas, color_means,
                     stabilize, path_out, max_speed=750.0):
        speeds.append(max_speed)
        Path(out).write_text("clip"); Path(path_out).write_text("[]")
        return out
    monkeypatch.setattr(pe.reframe, "reframe", fake_reframe)

    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert result["attempt"] == 2
    assert speeds[1] > speeds[0]          # on_line fail raised max_speed on retry


def test_three_fails_escalate(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path,
                 report=_report(False, ["on_line"]))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "escalate"
    assert result["escalate_to"] == "edit-plan"
    assert result["reason"] == "max-retries"
    assert result["attempt"] == 3


def test_unfixable_fail_escalates_first_attempt(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path, report=_report(False, ["length"]))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "escalate"
    assert result["reason"] == "unfixable-by-reframe"
    assert result["attempt"] == 1


def test_motion_mismatch_stops_and_reports(monkeypatch, tmp_path):
    # tracker route goes right; manifest declares left → stop_and_report, no reframe
    _stub_engine(monkeypatch, tmp_path)
    def boom(*a, **k):
        raise AssertionError("reframe must not run when the manifest is contradicted")
    monkeypatch.setattr(pe.reframe, "reframe", boom)
    result = pe.process_episode(_manifest(tmp_path, motion="lateral:left"),
                                project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert any(f["reason"] == "motion-mismatch" for f in result["findings"])


def test_ambiguous_hero_stops_and_reports(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path)
    def fake_build_route(src, out=None, **k):
        Path(out).write_text(json.dumps(
            [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]))
        Path(out).with_suffix(".meta.json").write_text(json.dumps({"ambiguous": True}))
        return []
    monkeypatch.setattr(pe.track, "build_route", fake_build_route)
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert any(f["reason"] == "hero-ambiguous" for f in result["findings"])


def test_corrupt_meta_sidecar_fails_loud(monkeypatch, tmp_path):
    # a present-but-malformed .meta.json drives the hero gate → fail loud, not a raw JSONDecodeError
    _stub_engine(monkeypatch, tmp_path)
    rp = tmp_path / "frozen.json"
    rp.write_text(json.dumps([dict(t=0, x=500, y=540, w=140, h=320)]))
    (tmp_path / "frozen.meta.json").write_text("{not valid json")
    with pytest.raises(ValueError, match="corrupt"):
        pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path),
                           route_path=str(rp))


FIX = Path(__file__).parent.parent / "fixtures"


@pytest.mark.integration
def test_golden_ride_through_orchestrator(tmp_path):
    # real 59.94fps clip + frozen route → the whole orchestrator, real ffmpeg
    manifest = dict(segment=str(FIX / "golden_ride.mp4"),
                    out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", canvas=[9, 16],
                    target_dur=1.58)
    result = pe.process_episode(manifest, project_dir=str(tmp_path),
                                route_path=str(FIX / "golden_route.json"))
    assert result["status"] == "mechanical_pass", result
    assert result["report"]["checks"]["on_line"]["pass"] is True
    assert result["report"]["checks"]["continuity"]["pass"] is True
    assert Path(result["clip"]).exists()
    assert Path(result["storyboard"]).exists()
    assert result["timings"]["reframe"] > 0
