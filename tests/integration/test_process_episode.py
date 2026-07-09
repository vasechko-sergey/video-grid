import json
from pathlib import Path
import pytest
from scripts import process_episode as pe
from scripts.lib import models


def _manifest(tmp_path, **over):
    d = dict(segment=str(tmp_path / "seg.mp4"), out_path=str(tmp_path / "ep.mp4"),
             composition="lead", grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def _report(overall, fail_reasons, attempt=1):
    """A real models.Report whose derived .overall/.fail_reasons match the
    given values — Report computes both FROM `checks` now (no more storing
    overall/fail_reasons directly), so the fake must build real CheckResults."""
    checks = {name: models.CheckResult(name, False, {}) for name in fail_reasons}
    assert overall == (not fail_reasons), (
        "_report: overall must be False iff fail_reasons is non-empty")
    return models.Report(checks=checks, attempt=attempt)


def _stub_engine(monkeypatch, tmp_path, *, route=None, report=None, dims=(1920, 1080, 30.0)):
    """Patch track/reframe/storyboard/check_episode with canned behavior and
    record the args the shell passes (to assert the contract threading). The
    fakes mirror the REAL typed signatures (TrackSpec/ReframeSpec/CheckSpec/
    StoryboardSpec in, a genuine models.Report out of check_episode.run) —
    a mocked green suite is only meaningful if the mocks match the engine."""
    calls = {}
    route = route or [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]

    def fake_build_route(spec, out):
        calls["track_intent"] = spec.intent
        calls["track_seed_bbox"] = spec.seed_bbox
        Path(out).write_text(json.dumps(route))
        Path(out).with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))
        return [models.RoutePoint.from_dict(d) for d in route]
    monkeypatch.setattr(pe.track, "build_route", fake_build_route)

    monkeypatch.setattr(pe.reframe, "_probe", lambda src: dims)

    def fake_reframe(spec, src, route_path, out, path_out):
        calls["reframe_delivery"] = spec.delivery
        calls["reframe_canvas"] = spec.canvas
        Path(out).write_text("clip")
        # path length must match the route (real reframe invariant) — the shell
        # reads it back to compute hero marks for the storyboard
        Path(path_out).write_text(json.dumps([100] * len(route)))
        return out
    monkeypatch.setattr(pe.reframe, "reframe", fake_reframe)

    def fake_storyboard_build(src, out, spec, route=None, path=None, crop_w=None, src_h=None):
        Path(out).write_text("sheet")
        return out, None
    monkeypatch.setattr(pe.storyboard, "build", fake_storyboard_build)

    default_report = _report(True, [])

    def fake_run(clip, route_path, path_path, spec, out):
        calls["check"] = dict(canvas=spec.canvas, src_dims=spec.src_dims, attempt=spec.attempt)
        src_report = report if report is not None else default_report
        r = models.Report(checks=dict(src_report.checks), attempt=spec.attempt)
        r.write(out)
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
    # wire contract: the shell returns report.to_dict(), not a raw Report —
    # catches a regression that dropped .to_dict() without the slow golden
    assert isinstance(result["report"], dict) and result["report"]["overall"] is True
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


def test_malformed_manifest_returns_needs_input(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, tmp_path)
    # missing required field → KeyError inside from_dict, must become needs_input
    d = _manifest(tmp_path); del d["composition"]
    r = pe.process_episode(d, project_dir=str(tmp_path))
    assert r["status"] == "needs_input" and r["attempt"] == 0
    # unknown/typo'd field → KeyError
    r = pe.process_episode(_manifest(tmp_path, stablize=True), project_dir=str(tmp_path))
    assert r["status"] == "needs_input"
    # wrong-type canvas (bare int) → TypeError
    r = pe.process_episode(_manifest(tmp_path, canvas=9), project_dir=str(tmp_path))
    assert r["status"] == "needs_input"


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


def test_storyboard_gets_hero_marks(monkeypatch, tmp_path):
    # §6.1a layer 4: the storyboard must carry per-frame hero marks so the
    # editorial gate can confirm "right person" — the SKILL promises this
    # artifact. marks are now computed INSIDE storyboard.build from the
    # route/path/crop_w/src_h ingredients the shell passes in — assert the
    # shell hands over well-shaped ingredients, then prove the real
    # marks_at_times can turn them into 6 valid (fx, fy) hero marks.
    _stub_engine(monkeypatch, tmp_path)
    captured = {}

    def capture_build(src, out, spec, route=None, path=None, crop_w=None, src_h=None):
        captured.update(route=route, path=path, crop_w=crop_w, src_h=src_h)
        Path(out).write_text("sheet")
        return out, None
    monkeypatch.setattr(pe.storyboard, "build", capture_build)

    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"

    route, path, crop_w, src_h = (captured["route"], captured["path"],
                                  captured["crop_w"], captured["src_h"])
    assert route and isinstance(route[0], models.RoutePoint)
    assert isinstance(path, models.CropPath) and len(path) == len(route)
    assert crop_w > 0 and src_h > 0

    times = [route[i].t for i in range(6)]
    marks = pe.storyboard.marks_at_times(route, path, crop_w, src_h, times)
    assert len(marks) == 6
    assert all(len(pair) == 2 for pair in marks)   # (fx, fy) fractions


def test_retry_then_pass(monkeypatch, tmp_path):
    # first check fails on_line, second passes → attempt 2, two reframe calls
    _stub_engine(monkeypatch, tmp_path)
    seq = [_report(False, ["on_line"]), _report(True, [])]
    speeds = []

    def fake_run(clip, route_path, path_path, spec, out):
        r = models.Report(checks=dict(seq[spec.attempt - 1].checks), attempt=spec.attempt)
        r.write(out)
        return r
    monkeypatch.setattr(pe.check_episode, "run", fake_run)

    def fake_reframe(spec, src, route_path, out, path_out):
        speeds.append(spec.max_speed)
        # path length must match the route (real reframe invariant) — the shell
        # reads it back to compute hero marks for the storyboard
        Path(out).write_text("clip"); Path(path_out).write_text(json.dumps([100] * 10))
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
    def fake_build_route(spec, out):
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


def test_intent_derived_for_center(monkeypatch, tmp_path):
    # §6.1a / #1: intent must be derived from the manifest and threaded into
    # the TrackSpec BEFORE tracking runs (it picks the hero during tracking)
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path, composition="center"), project_dir=str(tmp_path))
    assert calls["track_intent"] == "static"


def test_delivery_threaded_to_reframe(monkeypatch, tmp_path):
    # #F: the manifest's delivery spec must reach ReframeSpec, not be dropped
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path, delivery="exact:1080x1920"),
                       project_dir=str(tmp_path))
    assert calls["reframe_delivery"].mode == "exact"


def test_seed_bbox_threaded_to_track(monkeypatch, tmp_path):
    # a tuple hero pin must reach the TrackSpec as the tracker seed
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path, hero=[900, 500, 120, 300]),
                       project_dir=str(tmp_path))
    assert calls["track_seed_bbox"] == (900, 500, 120, 300)


def test_lead_nonlateral_stops(monkeypatch, tmp_path):
    # a static route under a lead manifest → composition-motion-mismatch, no reframe
    _stub_engine(monkeypatch, tmp_path,
                 route=[dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)])
    def boom(*a, **k): raise AssertionError("reframe must not run on composition mismatch")
    monkeypatch.setattr(pe.reframe, "reframe", boom)
    result = pe.process_episode(_manifest(tmp_path, composition="lead"), project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert any(f["reason"] == "composition-motion-mismatch" for f in result["findings"])


FIX = Path(__file__).parent.parent / "fixtures"


@pytest.mark.integration
def test_golden_ride_through_orchestrator(tmp_path):
    # real 59.94fps clip + frozen route → the whole orchestrator, real ffmpeg
    manifest = dict(segment=str(FIX / "golden_ride.mp4"),
                    out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", canvas=[9, 16],
                    target_dur=1.58,   # golden clip is ~1.585s; length check tol is ±0.5s
                    delivery="exact:1080x1920")
    result = pe.process_episode(manifest, project_dir=str(tmp_path),
                                route_path=str(FIX / "golden_route.json"))
    assert result["status"] == "mechanical_pass", result
    assert result["report"]["checks"]["on_line"]["pass"] is True
    assert result["report"]["checks"]["continuity"]["pass"] is True
    assert Path(result["clip"]).exists()
    assert Path(result["storyboard"]).exists()
    assert result["timings"]["reframe"] > 0

    import json as _j
    probe = _j.loads(pe.check_episode.proc.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", result["clip"]],
        text=True).stdout)["streams"][0]
    assert (probe["width"], probe["height"]) == (1080, 1920)


from scripts.lib import project as pj


def test_project_inherits_canvas_and_delivery(monkeypatch, tmp_path):
    # a youtube (16:9) project + an episode WITHOUT canvas/delivery → inherits;
    # the non-9:16 canvas + native delivery reach the ReframeSpec (mocked engine)
    calls = _stub_engine(monkeypatch, tmp_path)
    cfg = pj.resolve_project("youtube")                 # (16,9), native
    d = _manifest(tmp_path); del d["canvas"]            # omit canvas → inherit
    result = pe.process_episode(d, project_dir=str(tmp_path), project=cfg)
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_canvas"] == (16, 9)
    assert calls["reframe_delivery"].mode == "native"


def test_project_episode_canvas_overrides(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    cfg = pj.resolve_project("youtube")                 # project says 16:9
    # episode canvas differs from BOTH the project (16:9) and the _manifest default
    # (9:16), so this can only pass if the episode's explicit value actually wins
    result = pe.process_episode(_manifest(tmp_path, canvas=[21, 9]),
                                project_dir=str(tmp_path), project=cfg)
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_canvas"] == (21, 9)           # episode wins


def test_project_from_json_path(monkeypatch, tmp_path):
    # project= may be a path to project.json, not just a ProjectConfig
    _stub_engine(monkeypatch, tmp_path)
    pj.resolve_project("square").write(tmp_path / "project.json")
    d = _manifest(tmp_path); del d["canvas"]
    result = pe.process_episode(d, project_dir=str(tmp_path),
                                project=str(tmp_path / "project.json"))
    assert result["status"] == "mechanical_pass"
