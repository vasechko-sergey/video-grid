import json
from pathlib import Path
import pytest
from scripts import process_episode as pe
from scripts import check_episode, reframe, storyboard, track
from scripts.lib import ffbin, models
from scripts.lib import orchestration as orch
from scripts.lib.footage import DESCRIPTOR_LEN, Cast, CastMember


def _desc(*head: float) -> list[float]:
    """A registry-valid descriptor: DESCRIPTOR_LEN floats — `head`, zero-padded."""
    return list(head) + [0.0] * (DESCRIPTOR_LEN - len(head))


def _manifest(tmp_path, **over):
    d = dict(segment=str(tmp_path / "seg.mp4"), out_path=str(tmp_path / "ep.mp4"),
             composition="lead", grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def _frozen_route(tmp_path):
    """A route on disk, so process_episode skips tracking (the answer channel)."""
    rp = tmp_path / "frozen.json"
    rp.write_text(json.dumps([dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320)
                              for i in range(10)]))
    (tmp_path / "frozen.meta.json").write_text(json.dumps({"ambiguous": False}))
    return str(rp)


def _report(overall, fail_reasons, attempt=1):
    """A real models.Report whose derived .overall/.fail_reasons match the
    given values — Report computes both FROM `checks` now (no more storing
    overall/fail_reasons directly), so the fake must build real CheckResults."""
    checks = {name: models.CheckResult(name, False, {}) for name in fail_reasons}
    assert overall == (not fail_reasons), (
        "_report: overall must be False iff fail_reasons is non-empty")
    return models.Report(checks=checks, attempt=attempt)


def _dur(clip) -> float:
    """The clip's own probed duration. A pan spans the WHOLE episode by
    construction, so a pan-episode manifest's target_dur must equal the
    source's real length, not an arbitrary number the length check would
    then have to reconcile."""
    return check_episode._duration(str(clip))


def _failing_report(name: str) -> models.Report:
    """A Report whose one check failed — for driving the retry ladder directly.

    `jitter` on purpose: it is the one fail_reason orch.escalation would RETRY
    (it is not in _UNFIXABLE and does not pair with a line-lag), so a test built
    on it proves the pan guard fired rather than an unrelated escalation.
    """
    return models.Report(checks={name: models.CheckResult(name, False, {"worst_reversal": 99.0})},
                         attempt=1)


def _stub_engine(monkeypatch, tmp_path, *, route=None, report=None,
                 dims=(1920, 1080, 30.0, 3.0)):
    """Patch track/reframe/storyboard/check_episode with canned behavior and
    record the args the shell passes (to assert the contract threading). The
    fakes mirror the REAL typed signatures (TrackSpec/ReframeSpec/CheckSpec/
    StoryboardSpec in, a genuine models.Report out of check_episode.run) —
    a mocked green suite is only meaningful if the mocks match the engine."""
    calls = {}
    route = route or [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]

    def fake_build_route(spec, out):
        calls["track_intent"] = spec.intent
        calls["track_pin"] = spec.pin
        calls["track_src"] = spec.src
        Path(out).write_text(json.dumps(route))
        Path(out).with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))
        return [models.RoutePoint.from_dict(d) for d in route]
    monkeypatch.setattr(pe.track, "build_route", fake_build_route)

    monkeypatch.setattr(pe.reframe, "_probe", lambda src: dims)

    def fake_reframe(spec, src, route_path, out, path_out, stabilized=False):
        calls["reframe_delivery"] = spec.delivery
        calls["reframe_canvas"] = spec.canvas
        calls["reframe_color_correct"] = spec.color_correct
        calls["reframe_background"] = (spec.layout.background, spec.layout.background_color)
        calls["reframe_src"] = src
        calls["reframe_stabilized"] = stabilized
        calls["reframe_spec"] = spec   # whole spec, so a caller can assert any field
        Path(out).write_text("clip")
        # path length must match the route (real reframe invariant) — the shell
        # reads it back to compute hero marks for the storyboard
        Path(path_out).write_text(json.dumps([100] * len(route)))
        # ...and reframe writes path.meta.json beside path.json; the shell reads
        # it to hand storyboard the SAME crop the checks see (Task 8 layouts).
        sw, sh, _fps, _dur = dims
        models.PathMeta(mode="fill", crop_w=sw, crop_h=sh, crop_y=0, src_dims=(sw, sh),
                        canvas=tuple(spec.canvas), out_dims=(sw, sh),
                        rect_px=(0, 0, sw, sh), freedom=0).write(
            Path(path_out).with_suffix(".meta.json"))
        return out
    monkeypatch.setattr(pe.reframe, "reframe", fake_reframe)

    def fake_storyboard_build(src, out, spec, route=None, path=None, meta=None):
        Path(out).write_text("sheet")
        return out, None
    monkeypatch.setattr(pe.storyboard, "build", fake_storyboard_build)

    default_report = _report(True, [])

    def fake_run(clip, route_path, path_path, spec, out, source=None):
        calls["check"] = dict(attempt=spec.attempt, composition=spec.composition,
                              grid=spec.grid, target_dur=spec.target_dur)
        calls["check_source"] = source
        src_report = report if report is not None else default_report
        r = models.Report(checks=dict(src_report.checks), attempt=spec.attempt)
        r.write(out)
        return r
    monkeypatch.setattr(pe.check_episode, "run", fake_run)
    return calls


def test_happy_path_returns_mechanical_pass(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path, dims=(3840, 2160, 59.94, 1.584917))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert result["attempt"] == 1
    assert Path(result["clip"]).exists()
    assert Path(result["storyboard"]).exists()
    # wire contract: the shell returns report.to_dict(), not a raw Report —
    # catches a regression that dropped .to_dict() without the slow golden
    assert isinstance(result["report"], dict) and result["report"]["overall"] is True
    # the shell still threads the manifest's editorial intent into CheckSpec.
    # It no longer threads canvas/src_dims: check_episode reads those from the
    # sidecar reframe wrote, which is the point of the layouts work.
    assert calls["check"] == dict(attempt=1, composition="lead", grid="thirds",
                                  target_dur=3.0)


def test_the_manifests_filler_reaches_the_reframe_spec(monkeypatch, tmp_path):
    # The hop from the VALIDATED manifest to the LayoutSpec reframe actually renders
    # with. validate() structurally cannot see a drop here — it builds its OWN oracle
    # LayoutSpec from the manifest fields — so a regression passes the gate clean and
    # every authored colour silently renders as the "black" default. Silent
    # corruption, not a raise, which is why it needs its own pin.
    #
    # The colour is deliberately NON-default: "black" reads back identically whether
    # it was threaded or dropped, so a default-valued fixture would assert nothing.
    # The pair is asserted whole — `background` alone would survive the colour being
    # dropped, and vice versa.
    calls = _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(
        _manifest(tmp_path, composition="break", layout="fit", crop_aspect="source",
                  background="solid", background_color="#101820"),
        project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_background"] == ("solid", "#101820")


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
    # composition (not stabilize) is the trigger: stabilize=True stopped being an
    # unconditional problem once the manifest gate started checking vidstab
    # capability instead of refusing outright (stabilize-apply Task 6) — on a
    # machine that actually has vidstab, it would silently validate clean and this
    # test would assert nothing. An unknown composition is invalid regardless of
    # the host's ffmpeg build.
    _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(_manifest(tmp_path, composition="not-a-real-composition"),
                                project_dir=str(tmp_path))
    assert result["status"] == "needs_input"
    assert any("composition" in p for p in result["problems"])
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
    # route/path/meta ingredients the shell passes in (meta = the path.meta.json
    # sidecar reframe wrote) — assert the shell hands over well-shaped
    # ingredients, then prove the real marks_at_times can turn them into 6 valid
    # (fx, fy) hero marks.
    _stub_engine(monkeypatch, tmp_path)
    captured = {}

    def capture_build(src, out, spec, route=None, path=None, meta=None):
        captured.update(route=route, path=path, meta=meta)
        Path(out).write_text("sheet")
        return out, None
    monkeypatch.setattr(pe.storyboard, "build", capture_build)

    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"

    route, path, meta = captured["route"], captured["path"], captured["meta"]
    assert route and isinstance(route[0], models.RoutePoint)
    assert isinstance(path, models.CropPath) and len(path) == len(route)
    assert isinstance(meta, models.PathMeta) and meta.crop_w > 0

    times = [route[i].t for i in range(6)]
    marks = pe.storyboard.marks_at_times(route, path, meta, times)
    assert len(marks) == 6
    assert all(len(pair) == 2 for pair in marks)   # (fx, fy) fractions


def test_retry_then_pass(monkeypatch, tmp_path):
    # first check fails on_line, second passes → attempt 2, two reframe calls
    _stub_engine(monkeypatch, tmp_path)
    seq = [_report(False, ["on_line"]), _report(True, [])]
    speeds = []

    def fake_run(clip, route_path, path_path, spec, out, source=None):
        r = models.Report(checks=dict(seq[spec.attempt - 1].checks), attempt=spec.attempt)
        r.write(out)
        return r
    monkeypatch.setattr(pe.check_episode, "run", fake_run)

    def fake_reframe(spec, src, route_path, out, path_out, stabilized=False):
        speeds.append(spec.max_speed)
        # path length must match the route (real reframe invariant) — the shell
        # reads it back to compute hero marks for the storyboard; reframe also
        # writes path.meta.json, which the shell reads for the marker mapping
        Path(out).write_text("clip"); Path(path_out).write_text(json.dumps([100] * 10))
        models.PathMeta(mode="fill", crop_w=1920, crop_h=1080, crop_y=0,
                        src_dims=(1920, 1080), canvas=(9, 16), out_dims=(1920, 1080),
                        rect_px=(0, 0, 1920, 1080), freedom=0).write(
            Path(path_out).with_suffix(".meta.json"))
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


def test_bbox_pin_threaded_to_track(monkeypatch, tmp_path):
    # a manifest hero value must reach the TrackSpec as a RESOLVED HeroPin —
    # the shell threads it through hero.resolve(), never the raw manifest value
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path, hero=[900, 500, 120, 300]),
                       project_dir=str(tmp_path))
    assert calls["track_pin"] == models.HeroPin(kind="bbox", bbox=(900.0, 500.0, 120.0, 300.0))


def test_cast_pin_threaded_to_track(monkeypatch, tmp_path):
    # a cast-name hero, backed by a real cast.json on disk, must reach the
    # TrackSpec as a resolved "cast" HeroPin carrying the registered descriptor —
    # proves the shell loads the registry AND hands the SAME object to both
    # validate() and the tracking step (not two independent loads that could drift).
    # A cast (identity) pin now legitimately REQUIRES reID (design 2026-08-04 §6), so
    # this "cast pin threads and passes" path presumes reID present — stub it, since
    # the repo env ships no torchreid (the absent case is its own test below).
    calls = _stub_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(pe.reid, "available", lambda: True)
    cast_path = tmp_path / "cast.json"
    cast_path.write_text(json.dumps(Cast(members=[
        CastMember(name="Lena", descriptor=_desc(0.5, 0.5))]).to_dict()))
    result = pe.process_episode(
        _manifest(tmp_path, hero="Lena", cast=str(cast_path)), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert calls["track_pin"] == models.HeroPin(kind="cast", name="Lena",
                                                descriptor=tuple(_desc(0.5, 0.5)))


def test_cast_pin_without_reid_stops_with_reid_unavailable(monkeypatch, tmp_path):
    # The consumer half of the §6 split: a cast (identity) pin needs torchreid re-ID.
    # When the tracker itself IS present but reID is not, the episode STOPS with the
    # honest reid-unavailable remedy — never a misleading no-track (§12), never the
    # identity-blind optical-flow rung. build_route is stubbed to blow up so the test
    # proves the gate short-circuits BEFORE any tracking is attempted.
    _stub_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(pe.track, "_ultra_available", lambda: True)   # tracker present
    monkeypatch.setattr(pe.reid, "available", lambda: False)          # reID absent
    def boom(*a, **k):
        raise AssertionError("build_route must not run for a cast pin when reID is absent")
    monkeypatch.setattr(pe.track, "build_route", boom)
    cast_path = tmp_path / "cast.json"
    cast_path.write_text(json.dumps(Cast(members=[
        CastMember(name="Lena", descriptor=_desc(0.5, 0.5))]).to_dict()))
    result = pe.process_episode(
        _manifest(tmp_path, hero="Lena", cast=str(cast_path)), project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert [f["reason"] for f in result["findings"]] == ["reid-unavailable"]
    assert "setup.sh" in result["findings"][0]["detail"]


def test_unreadable_cast_path_returns_needs_input(monkeypatch, tmp_path):
    # m.cast pointing at a missing file must return needs_input, not crash —
    # Cast.from_json raises OSError (missing) or ValueError (malformed JSON /
    # wrong shape), and both must funnel into the same soft gate every other
    # manifest problem uses
    _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(
        _manifest(tmp_path, hero="Lena", cast=str(tmp_path / "missing_cast.json")),
        project_dir=str(tmp_path))
    assert result["status"] == "needs_input"
    assert any("unreadable" in p for p in result["problems"])
    assert result["attempt"] == 0


def test_non_str_cast_returns_needs_input_instead_of_crashing(monkeypatch, tmp_path):
    # The registry load runs BEFORE validate() (validate needs the loaded Cast as
    # its hero oracle), so it is the one step no gate has vetted. Cast.from_json's
    # first statement is Path(path) — it runs before a byte of JSON is read, and
    # Path(123) raises TypeError, which is NOT in the `except (OSError, ValueError)`
    # surface below. That TypeError escaped process_episode entirely: a crash out of
    # the gate whose whole job is to return problems softly. Reachable straight from
    # this module's own CLI, which json.loads a manifest file.
    _stub_engine(monkeypatch, tmp_path)
    for bad in (123, ["proj/cast.json"], {"path": "x"}):
        result = pe.process_episode(_manifest(tmp_path, hero="Lena", cast=bad),
                                    project_dir=str(tmp_path))
        assert result["status"] == "needs_input", (bad, result)
        assert any("cast" in p for p in result["problems"]), (bad, result)


def test_lead_nonlateral_stops(monkeypatch, tmp_path):
    # a static route under a lead manifest → composition-motion-mismatch, no reframe
    _stub_engine(monkeypatch, tmp_path,
                 route=[dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)])
    def boom(*a, **k): raise AssertionError("reframe must not run on composition mismatch")
    monkeypatch.setattr(pe.reframe, "reframe", boom)
    result = pe.process_episode(_manifest(tmp_path, composition="lead"), project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert any(f["reason"] == "composition-motion-mismatch" for f in result["findings"])


def test_manifest_layout_fields_reach_the_reframe_spec(monkeypatch, tmp_path):
    # the orchestrator's job here is threading, not geometry: whatever the
    # manifest says about the layout must arrive at reframe intact, including
    # the JSON-array-to-tuple conversion the manifest performs.
    seen = {}

    def fake_reframe(spec, src, route_path, out, path_out, stabilized=False):
        seen["layout"] = spec.layout
        raise RuntimeError("stop — this test only cares about the spec we were handed")

    monkeypatch.setattr(pe.reframe, "_probe", lambda src: (1280, 720, 59.94, 1.584917))
    monkeypatch.setattr(pe.reframe, "reframe", fake_reframe)
    manifest = _manifest(tmp_path, composition="break", layout="insert",
                         crop_aspect=[1, 1], rect=[0.05, 0.25, 0.9], border_px=8)
    with pytest.raises(RuntimeError, match="this test only cares"):
        pe.process_episode(manifest, project_dir=str(tmp_path),
                           route_path=_frozen_route(tmp_path))
    assert seen["layout"] == models.LayoutSpec(mode="insert", crop_aspect=(1, 1),
                                               rect=(0.05, 0.25, 0.9), border_px=8)


def test_a_fill_manifest_still_gets_the_default_layout(monkeypatch, tmp_path):
    seen = {}

    def fake_reframe(spec, src, route_path, out, path_out, stabilized=False):
        seen["layout"] = spec.layout
        raise RuntimeError("stop")

    monkeypatch.setattr(pe.reframe, "_probe", lambda src: (1280, 720, 59.94, 1.584917))
    monkeypatch.setattr(pe.reframe, "reframe", fake_reframe)
    with pytest.raises(RuntimeError, match="stop"):
        pe.process_episode(_manifest(tmp_path, composition="break"),
                           project_dir=str(tmp_path), route_path=_frozen_route(tmp_path))
    assert seen["layout"] == models.LayoutSpec(mode="fill")


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
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
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


@pytest.mark.integration
def test_project_native_delivery_end_to_end(tmp_path):
    # a reel (9:16) project with NATIVE delivery + an episode omitting canvas/delivery →
    # inherits → the golden ride renders at the source's native 9:16 crop, not a pinned
    # 1080×1920. Proves the project front-door drives the engine end-to-end through real ffmpeg.
    cfg = pj.resolve_project("reel")                    # (9,16), native
    manifest = dict(segment=str(FIX / "golden_ride.mp4"), out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", target_dur=1.58)   # no canvas/delivery
    result = pe.process_episode(manifest, project_dir=str(tmp_path),
                                route_path=str(FIX / "golden_route.json"), project=cfg)
    assert result["status"] == "mechanical_pass", result
    import json as _j
    probe = _j.loads(pe.check_episode.proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", result["clip"]],
        text=True).stdout)["streams"][0]
    # golden source 1280×720 → 9:16 crop 405×720 → even native → 404×720
    assert (probe["width"], probe["height"]) == (404, 720)


def test_color_correct_is_threaded_into_the_reframe_spec(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path),
                                color_correct=(1.2, 1.0, 0.9))
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_color_correct"] == (1.2, 1.0, 0.9)


def test_color_correct_defaults_to_none(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert calls["reframe_color_correct"] is None


def test_process_episode_threads_colour_and_source(monkeypatch, tmp_path):
    # colour-as-a-stage Task 10: the manifest's nine colour fields must reach
    # ReframeSpec, and the pre-grade segment (`src`, reframe's own input) must
    # reach check_episode.run as source= — the advisory color_fidelity check's
    # only ingredient. validate() structurally cannot catch a drop here (same
    # shape as test_the_manifests_filler_reaches_the_reframe_spec above): it
    # never builds a ReframeSpec of its own to compare against, so a regression
    # would pass the gate clean and every authored grade would silently render
    # as identity. Silent corruption, not a raise — needs its own pin.
    calls = _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(
        _manifest(tmp_path, white_balance=0.5, black_point=0.1, highlight=0.9,
                  saturation=1.1, shadow_red=0.05, mid_blue=0.95, dip=0.2,
                  tone_src=[30, 100, 148], tone_dst=[35, 110, 150]),
        project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    spec = calls["reframe_spec"]
    assert spec.white_balance == 0.5
    assert spec.black_point == 0.1
    assert spec.highlight == 0.9
    assert spec.saturation == 1.1
    assert spec.shadow_red == 0.05
    assert spec.mid_blue == 0.95
    assert spec.dip == 0.2
    assert spec.tone_src == (30, 100, 148)
    assert spec.tone_dst == (35, 110, 150)
    # the check must see the SAME pre-grade segment reframe rendered from —
    # not the manifest's raw segment (they differ once stabilize=True), and
    # not silently None (the default that turns the check not-checked).
    assert calls["check_source"] == calls["reframe_src"]


def test_process_episode_colour_fields_default_identity(monkeypatch, tmp_path):
    # the complement of the test above: a manifest that names none of the nine
    # fields must still reach ReframeSpec at its identity defaults — an episode
    # authored before this slice renders byte-identically (design's whole point).
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    spec = calls["reframe_spec"]
    assert spec.white_balance == 0.0
    assert spec.black_point == 0.0
    assert spec.highlight == 1.0
    assert spec.saturation == 1.0
    assert spec.shadow_red == 0.0
    assert spec.mid_blue == 1.0
    assert spec.dip == 0.0
    assert spec.tone_src is None
    assert spec.tone_dst is None


# --- Task 7: process_episode skips tracking and the contradiction gate for a
# pan, and a generated path is not retryable (design 2026-07-19) ---

def test_pan_episode_never_tracks(sample_clip, tmp_path, monkeypatch):
    # asserts the BRANCH, not an outcome the other branch could also produce
    monkeypatch.setattr(track, "build_route",
                        lambda *a, **k: pytest.fail("a pan must not run the tracker"))
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.2, "to": 0.7}}
    res = pe.process_episode(md, str(tmp_path / "proj"))
    assert res["status"] == "mechanical_pass", res
    assert res["timings"]["track"] == 0.0


def test_pan_episode_writes_no_route_json(sample_clip, tmp_path):
    # an empty route.json would MEAN "the tracker found nobody" — a fabricated
    # observation. Nothing must be written.
    proj = tmp_path / "proj"
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 1.0}}
    pe.process_episode(md, str(proj))
    assert not (proj / "route.json").exists()


def test_pan_episode_skips_the_contradiction_gate(sample_clip, tmp_path, monkeypatch):
    # with no observation there is nothing to contradict; running the gate on an
    # empty route would fire `no-track`, whose remedy ("check the segment, model
    # size, or hero pin") misdescribes a deliberate choice
    monkeypatch.setattr(orch, "detect_contradictions",
                        lambda *a, **k: pytest.fail("no observation ⇒ nothing to contradict"))
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 1.0}}
    assert pe.process_episode(md, str(tmp_path / "p"))["status"] == "mechanical_pass"


def test_pan_episode_storyboard_draws_no_hero_marker(sample_clip, tmp_path, monkeypatch):
    seen = {}
    real = storyboard.build

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(storyboard, "build", spy)
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 1.0}}
    pe.process_episode(md, str(tmp_path / "p"))
    assert seen["route"] is None


def test_a_bad_pan_comes_back_as_needs_input(sample_clip, tmp_path):
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": 2.0, "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 9.0}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "needs_input"
    assert any("[0.0, 1.0]" in p for p in res["problems"])


def test_a_failing_pan_escalates_instead_of_retrying(sample_clip, tmp_path, monkeypatch):
    # The retry ladder tunes max_speed, which for a generated path is only the
    # speed ceiling — a retry re-renders byte-identical pixels. Worse, a jitter
    # fail multiplies max_speed by 0.6, so attempt 2 would hit
    # generate_pan_path's ceiling raise as a traceback out of the loop.
    calls = []
    real = reframe.reframe
    monkeypatch.setattr(reframe, "reframe",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    # force a mechanical failure the ladder would otherwise retry
    monkeypatch.setattr(check_episode, "run", lambda *a, **k: _failing_report("jitter"))
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 1.0}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "escalate"
    assert res["reason"] == "pan-not-retryable"
    assert len(calls) == 1, "a generated path must be rendered once, not three times"


def test_a_pan_with_an_unfixable_failure_keeps_that_reason(sample_clip, tmp_path, monkeypatch):
    # THE ORDERING PIN. orch.escalation must run BEFORE the pan guard, so a
    # reason that actually describes the failure wins over the generic
    # "a generated path is not retryable". `length` is in orch's _UNFIXABLE, so
    # escalation returns a reason on attempt 1 and the pan guard must not
    # overwrite it. Hoisting the guard above escalation turns this red and
    # nothing else — measured.
    calls = []
    real = reframe.reframe
    monkeypatch.setattr(reframe, "reframe", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(check_episode, "run", lambda *a, **k: _failing_report("length"))
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 1.0}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "escalate"
    assert res["reason"] == "unfixable-by-reframe"   # NOT pan-not-retryable
    assert len(calls) == 1


def test_a_pan_hands_reframe_no_route_path(sample_clip, tmp_path, monkeypatch):
    # This slice's thesis stated as a contract rather than left implicit: under a
    # pan the shell hands over NO route path at all. Unobservable through behaviour
    # today — reframe dispatches on spec.pan and check_episode on meta.pan, so
    # neither consumer looks at route_path's nullness — which is exactly why it
    # needs its own pin: the day one of them does, a phantom path would be a
    # fabricated observation, and nothing else in the suite would notice.
    #
    # The shell passes all five arguments POSITIONALLY (route_path 3rd); the named
    # parameter below binds it under either call style, so this asserts the
    # ARGUMENT the shell hands over rather than the spelling of the call.
    seen = {}
    real = reframe.reframe

    def spy(spec, src, route_path, out, path_out, stabilized=False):
        seen["route_path"] = route_path
        return real(spec, src, route_path, out, path_out, stabilized=stabilized)
    monkeypatch.setattr(reframe, "reframe", spy)
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.0, "to": 1.0}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "mechanical_pass", res
    assert seen["route_path"] is None


def test_a_tracked_episode_still_retries(sample_clip, tmp_path, monkeypatch):
    # the guard must NOT change the tracked path — this is the regression half
    calls = []
    real = reframe.reframe
    monkeypatch.setattr(reframe, "reframe",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(check_episode, "run", lambda *a, **k: _failing_report("jitter"))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([{"t": i / 30, "x": 640, "y": 360, "w": 100, "h": 200}
                                 for i in range(30)]))
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5}
    res = pe.process_episode(md, str(tmp_path / "p"), route_path=str(route))
    assert res["status"] == "escalate"
    assert res["reason"] == "max-retries"
    assert len(calls) == 3


def test_an_empty_pan_comes_back_as_needs_input(sample_clip, tmp_path):
    # The end-to-end half of the same guarantee. The shell builds
    # PanSpec.from_dict(m.pan) bare, so if the gate ever stopped catching an
    # empty pan this would be a traceback rather than a status dict.
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": 2.0, "layout": "fill", "crop_scale": 0.5,
          "pan": {}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "needs_input"
    assert any("from" in p and "to" in p for p in res["problems"])


def test_a_pan_with_no_freedom_comes_back_as_needs_input(sample_clip, tmp_path):
    # crop_scale 1.0 on a canvas-aspect fill still leaves freedom, so use the one
    # spelling that provably has none: crop_aspect 'source' at full scale
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": 2.0, "layout": "fit", "crop_aspect": "source", "crop_scale": 1.0,
          "pan": {"from": 0.0, "to": 1.0}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "needs_input"
    assert any("crop_scale" in p for p in res["problems"])


# --- Task 7: process_episode runs the stabilization pre-stage (design 2026-07-20 §1):
# ONE vidstab pass into <project_dir>/stabilized.mp4, and BOTH the tracker and reframe
# read that file — route and pixels one coordinate system by construction. ---


def _stub_vidstab(monkeypatch, *, stabilize=lambda src, out, dims, fps, dur: (0.031, 0.004)):
    """Neutralise the two vidstab entry points a stabilize=true run touches:
    require() (validate() spawns a real `ffmpeg -filters` otherwise — pe.vidstab
    IS manifest_lib.vidstab, one module object, so patching it here covers both)
    and stabilize() (the pre-stage's two ffmpeg passes)."""
    monkeypatch.setattr(pe.vidstab, "require", lambda: None)
    monkeypatch.setattr(pe.vidstab, "stabilize", stabilize)


def test_stabilize_feeds_the_same_file_to_tracker_and_reframe(monkeypatch, tmp_path):
    # THE §1 INVARIANT. The tracker and reframe must read the SAME file. Feeding the
    # tracker the raw segment while reframe reads the stabilized one is the exact
    # failure this ordering exists to prevent: the route would live in the source
    # coordinate system and the pixels would not, so the crop would re-inject the
    # shake vidstab removed — and check_episode would confirm the framing regardless,
    # because path and route are both in source coordinates and agree with each other.
    calls = _stub_engine(monkeypatch, tmp_path)
    _stub_vidstab(monkeypatch)
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass", result
    assert calls["track_src"] == calls["reframe_src"]
    assert calls["track_src"].endswith("stabilized.mp4")
    assert calls["reframe_stabilized"] is True


def test_the_preflight_probe_stays_on_the_original_segment(monkeypatch, tmp_path):
    # The preflight probe exists so a manifest the layout cannot satisfy fails in
    # milliseconds. Moving it after stabilization would spend the two ffmpeg passes
    # before the cheap refusal — so it must be handed the RAW segment, not the
    # not-yet-written stabilized.mp4.
    dims = (1920, 1080, 30.0, 3.0)
    _stub_engine(monkeypatch, tmp_path, dims=dims)
    _stub_vidstab(monkeypatch)
    probed = {}

    def spy_probe(src):
        probed["src"] = src
        return dims
    monkeypatch.setattr(pe.reframe, "_probe", spy_probe)
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass", result
    assert probed["src"].endswith("seg.mp4")
    assert not probed["src"].endswith("stabilized.mp4")


def test_the_before_and_after_reach_the_result(monkeypatch, tmp_path):
    # the residual measurement is a stage-level fact, riding out on the result beside
    # `timings` (design §6.3) — never inside Report, where a check_reel consumer
    # would be tempted to gate on a number this slice ships no threshold for.
    _stub_engine(monkeypatch, tmp_path)
    _stub_vidstab(monkeypatch)
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass", result
    assert result["stabilize"] == {"before": 0.031, "after": 0.004}


def test_an_unstabilized_episode_never_runs_the_pre_stage(monkeypatch, tmp_path):
    # the default manifest carries stabilize=False, so the pre-stage must not fire,
    # no measurement must appear, and both consumers must read the raw segment.
    calls = _stub_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(pe.vidstab, "stabilize",
                        lambda *a, **k: pytest.fail("stabilize=False must not run the pre-stage"))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert "stabilize" not in result
    assert calls["reframe_stabilized"] is False
    assert calls["reframe_src"] == calls["track_src"]
    assert calls["reframe_src"].endswith("seg.mp4")


def test_the_pre_stage_runs_once_not_once_per_retry(monkeypatch, tmp_path):
    # stabilization is the loop's INPUT, not one of its parameters — it runs once,
    # and the three reframe/check retries all read the one stabilized file. The
    # measurement also rides out on the escalate terminal, not just mechanical_pass.
    _stub_engine(monkeypatch, tmp_path, report=_report(False, ["on_line"]))
    n = {"count": 0}

    def counting(src, out, dims, fps, dur):
        n["count"] += 1
        return (0.031, 0.004)
    _stub_vidstab(monkeypatch, stabilize=counting)
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path))
    assert result["status"] == "escalate"          # on_line retries 3x, then max-retries
    assert result["reason"] == "max-retries"
    assert result["attempt"] == 3
    assert n["count"] == 1
    assert result["stabilize"] == {"before": 0.031, "after": 0.004}


def test_stop_and_report_carries_the_stabilize_measurement(monkeypatch, tmp_path):
    # The contradiction gate's stop_and_report is the third pre-stage terminal
    # (beside mechanical_pass and escalate) that must ride the residual measurement
    # out beside `timings` — a stabilized episode that then contradicts its manifest
    # still reports what the pre-stage measured. Mirrors
    # test_motion_mismatch_stops_and_reports with stabilize on; without the
    # conditional at that return, a refactor could drop the measurement silently.
    _stub_engine(monkeypatch, tmp_path)
    _stub_vidstab(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("reframe must not run when the manifest is contradicted")
    monkeypatch.setattr(pe.reframe, "reframe", boom)
    result = pe.process_episode(_manifest(tmp_path, motion="lateral:left", stabilize=True),
                                project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert any(f["reason"] == "motion-mismatch" for f in result["findings"])
    assert result["stabilize"] == {"before": 0.031, "after": 0.004}


def test_a_pan_episode_can_also_be_stabilized(sample_clip, tmp_path, monkeypatch):
    # design §2.1: pan and stabilize compose. A pan tracks nobody, so §1's coordinate
    # argument does not apply to it — but a pan over shaky footage is still shaky. The
    # pre-stage runs, reframe reads the stabilized file, and the tracker never runs.
    import shutil
    monkeypatch.setattr(track, "build_route",
                        lambda *a, **k: pytest.fail("a pan must not run the tracker"))

    def fake_stabilize(src, out, dims, fps, dur):
        shutil.copy(src, out)     # real reframe reads `out`, so it must be a real clip
        return (0.031, 0.004)
    _stub_vidstab(monkeypatch, stabilize=fake_stabilize)

    seen = {}
    real = reframe.reframe

    def spy(spec, src, route_path, out, path_out, stabilized=False):
        seen["src"] = src
        seen["stabilized"] = stabilized
        return real(spec, src, route_path, out, path_out, stabilized=stabilized)
    monkeypatch.setattr(reframe, "reframe", spy)

    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": _dur(sample_clip), "layout": "fill", "crop_scale": 0.5,
          "pan": {"from": 0.2, "to": 0.7}, "stabilize": True}
    res = pe.process_episode(md, str(tmp_path / "proj"))
    assert res["status"] == "mechanical_pass", res
    assert res["stabilize"] == {"before": 0.031, "after": 0.004}
    assert seen["src"].endswith("stabilized.mp4")
    assert seen["stabilized"] is True


def test_stabilize_with_a_frozen_route_is_refused(monkeypatch, tmp_path):
    # A supplied --route was measured against unknown pixels; applying it to the
    # stabilized copy re-injects the shake vidstab removed (design §1). validate()
    # structurally cannot catch it — route_path is not a manifest field — so the
    # shell refuses, and the refusal must land BEFORE the two ffmpeg passes.
    _stub_engine(monkeypatch, tmp_path)
    _stub_vidstab(monkeypatch, stabilize=lambda *a, **k: pytest.fail(
        "the refusal must come before the pre-stage spends the passes"))
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path),
                                route_path=_frozen_route(tmp_path))
    assert result["status"] == "needs_input"
    assert result["attempt"] == 0
    joined = " ".join(result["problems"]).lower()
    assert "route" in joined
    assert "shake" in joined or "re-inject" in joined
    # the remedy names both actionable fixes without assuming tracking (a pan never
    # tracks, so "drop --route so tracking runs on it" would misdescribe it)
    assert "drop --route" in joined and "stabilize off" in joined


# --- --keyframes answer-channel conflicts (design 2026-07-21 §2): the manual rung
# drives the RAW, unpinned, unstabilized, un-pre-routed segment in source coordinates.
# Three inputs contradict that channel and validate() cannot see any of them
# (keyframes_path is not a manifest field), so the shell refuses each loudly rather
# than silently drop the marks — the anti-pattern these three tests pin. ---


def test_a_hero_pin_with_keyframes_is_refused(monkeypatch, tmp_path):
    # A hero pin and hand-authored keyframes both answer "which subject": the pin tells
    # the automatic tracker whom to follow, the keyframes ARE the human answering it
    # directly, so the pin is moot the moment they are drawn. Passing both used to
    # silently drop the keyframes — they sit under flow_eligible, False for a pin — with
    # no signal they were ignored. Optical-flow's identity-blindness (§1.1) excludes a
    # pinned episode from rung 2; rung 3 is excluded here for a DIFFERENT, louder reason.
    _stub_engine(monkeypatch, tmp_path)
    kf = tmp_path / "keyframes.json"
    kf.write_text(json.dumps([{"t": 0.0, "x": 300, "y": 540, "w": 200, "h": 400}]))
    result = pe.process_episode(_manifest(tmp_path, hero=[50, 50, 20, 20]),
                                project_dir=str(tmp_path), keyframes_path=str(kf))
    assert result["status"] == "needs_input"
    assert result["attempt"] == 0
    joined = " ".join(result["problems"]).lower()
    assert "hero pin" in joined and "--keyframes" in joined
    # the remedy names both actionable fixes: drop the pin (keyframes ARE the identity)
    # or drop the keyframes (let the pinned tracker run)
    assert "drop the hero pin" in joined and "drop --keyframes" in joined


def test_stabilize_with_keyframes_is_refused(monkeypatch, tmp_path):
    # The same coordinate-mismatch class as the frozen-route refusal above, milder: the
    # human authors marks in the RAW segment's coordinates, but stabilization feeds
    # reframe a per-frame-shifted copy, so the crop lands off by the displacement vidstab
    # removed. Sparse linear marks cannot re-inject the high-frequency shake the --route
    # refusal exists for — but it is the same class, and there is no correct way to
    # hand-author against the stabilized scratch. Refuse symmetrically, and — like the
    # route refusal — BEFORE the pre-stage spends the ffmpeg passes.
    _stub_engine(monkeypatch, tmp_path)
    _stub_vidstab(monkeypatch, stabilize=lambda *a, **k: pytest.fail(
        "the refusal must come before the pre-stage spends the passes"))
    kf = tmp_path / "keyframes.json"
    kf.write_text(json.dumps([{"t": 0.0, "x": 300, "y": 540, "w": 200, "h": 400}]))
    result = pe.process_episode(_manifest(tmp_path, stabilize=True),
                                project_dir=str(tmp_path), keyframes_path=str(kf))
    assert result["status"] == "needs_input"
    assert result["attempt"] == 0
    joined = " ".join(result["problems"]).lower()
    assert "stabilize" in joined and "--keyframes" in joined
    assert "shake" in joined
    assert "stabilize off" in joined and "drop --keyframes" in joined


def test_a_frozen_route_with_keyframes_is_refused(monkeypatch, tmp_path):
    # --route supplies a COMPLETE frozen route (tracking skipped entirely) and
    # --keyframes supplies sparse marks that would AUTHOR one: two competing route
    # sources. Today --route silently wins and the keyframes are dropped — the third
    # same-class gap, closed for a complete invariant.
    _stub_engine(monkeypatch, tmp_path)
    kf = tmp_path / "keyframes.json"
    kf.write_text(json.dumps([{"t": 0.0, "x": 300, "y": 540, "w": 200, "h": 400}]))
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path),
                                route_path=_frozen_route(tmp_path), keyframes_path=str(kf))
    assert result["status"] == "needs_input"
    assert result["attempt"] == 0
    joined = " ".join(result["problems"]).lower()
    assert "--route" in joined and "--keyframes" in joined


# --- process_episode builds and preflights the ZoomSpec (design 2026-08-08, Task 10):
# unlike a pan, a zoom still needs a tracked route (it anchors the rect to the tracked
# subject, design §1), so its own preflight must run before tracking too, not only before
# the encode — mirrors the pan preflight above, one layer simpler (zoom.validate needs no
# path generation). ---


def test_a_bad_zoom_comes_back_as_needs_input(sample_clip, tmp_path, monkeypatch):
    # A >20x upsample (crop_w=303 tightened to 15px against a 302px delivery) is past the
    # measured 1.5x ceiling zoom.validate refuses. What this pins is the ORDERING, not just
    # the outcome: build_route is stubbed to fail the test if it is ever called, so this
    # goes red under either plausible regression —
    #   1. the preflight call is deleted outright: the zoom is then silently threaded into
    #      ReframeSpec with nothing to stop it, tracking runs (tripping the stub) and the
    #      episode either renders wrong or dies on reframe's OWN internal zoom_lib.validate
    #      (reframe.py line ~467) as an uncaught ValueError instead of a clean status dict;
    #   2. the preflight call survives but is moved past tracking (e.g. into the retry loop,
    #      "after the encode" instead of before it) — same stub trip, even though the final
    #      status would still come back needs_input.
    # A pan needs no such stub (it never tracks, valid or not); a zoom does, which is
    # exactly the cost this preflight exists to avoid paying for a doomed one.
    monkeypatch.setattr(track, "build_route",
                        lambda *a, **k: pytest.fail(
                            "an impossible zoom must be refused before tracking runs"))
    md = {"segment": str(sample_clip), "out_path": str(tmp_path / "o.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [9, 16],
          "target_dur": 2.0, "layout": "fill", "crop_scale": 0.5,
          "zoom": {"from": 1.0, "to": 0.05}}
    res = pe.process_episode(md, str(tmp_path / "p"))
    assert res["status"] == "needs_input"
    assert res["attempt"] == 0
    assert any("upsampling" in p for p in res["problems"])


def test_a_valid_zoom_reaches_the_reframe_spec(monkeypatch, tmp_path):
    # The complement of the refusal test above, same shape as
    # test_the_manifests_filler_reaches_the_reframe_spec: validate() structurally cannot
    # catch a drop here (it never builds a ReframeSpec to compare against), so a
    # regression that builds `zoom` and preflights it correctly but forgets `zoom=zoom` in
    # the ReframeSpec(...) call would pass every gate clean and silently render every
    # authored zoom as a plain, unmoving crop. Silent corruption, not a raise — needs its
    # own pin. from=1.0/to=0.7 is comfortably inside every zoom.validate ceiling at this
    # manifest's resolved layout (crop_w=607, out_w=606 — see the direct computation this
    # test's numbers were checked against), so it must reach mechanical_pass.
    calls = _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(_manifest(tmp_path, zoom={"from": 1.0, "to": 0.7}),
                                project_dir=str(tmp_path))
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_spec"].zoom == models.ZoomSpec(start=1.0, end=0.7)


def test_no_zoom_still_defaults_to_none(monkeypatch, tmp_path):
    # The regression half: an episode that never mentions `zoom` must reach ReframeSpec
    # with zoom=None, exactly as before this slice — the whole existing suite already
    # relies on this implicitly, but pins it explicitly beside the two tests above.
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert calls["reframe_spec"].zoom is None
