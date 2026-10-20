import json
from pathlib import Path

import pytest

from scripts import process_episode
from scripts.lib import models
from scripts.lib import orchestration as orch
from scripts.lib.manifest import Manifest
from scripts.lib.models import Delivery


def test_build_reframe_spec_carries_every_colour_field():
    """The probe renders from this map. A field that falls out here is a field the
    probe shows unchanged while the real render changes it."""
    m = Manifest.from_dict({
        "segment": "s.mp4", "out_path": "o.mp4", "target_dur": 2.0,
        "composition": "lead", "grid": "thirds", "canvas": [9, 16],
        "color_means": [110.0, 120.0, 130.0], "delivery": "short_edge:540",
        "white_balance": 0.4, "black_point": 0.1, "highlight": 0.8,
        "highlight_red": 0.2, "saturation": 1.2, "shadow_red": 0.05,
        "mid_blue": 0.95, "dip": 0.3,
        "tone_src": [18.0, 110.0, 220.0], "tone_dst": [26.0, 118.0, 210.0]})
    spec = process_episode.build_reframe_spec(
        m, Delivery.from_spec(m.delivery), dict(orch.DEFAULT_PARAMS))
    assert (spec.white_balance, spec.black_point, spec.highlight, spec.highlight_red,
            spec.saturation, spec.shadow_red, spec.mid_blue, spec.dip) == (
        0.4, 0.1, 0.8, 0.2, 1.2, 0.05, 0.95, 0.3)
    assert spec.tone_src == (18.0, 110.0, 220.0)
    assert spec.tone_dst == (26.0, 118.0, 210.0)


# ---------------------------------------------------------------------------
# Task 2: process_episode stops at geometry, and can be handed one back
# (design 2026-08-30 §2.1/§2.3).
# ---------------------------------------------------------------------------

def _episode_manifest(tmp_path, **over):
    # composition="break" keeps the contradiction gate's `lead` travel check out
    # of the way — these tests are about the stop_after/prepared_source plumbing,
    # not about whether a route travels far enough to justify a lead composition.
    d = dict(segment=str(tmp_path / "seg.mp4"), out_path=str(tmp_path / "ep.mp4"),
             composition="break", grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


@pytest.fixture(autouse=True)
def _stub_probe(monkeypatch):
    """Every test below reaches `reframe._probe(m.segment)` on its way to (or
    past) the seam under test, and `segment` is never a real file here —
    tests/lib/ is pure unit, no ffmpeg (docs/testing-guide.md). Stubbing the one
    ffprobe call lets the rest of the shell run for real against fakes.

    Also stubs `vidstab.require()` — `manifest.validate()` calls it for real
    (an uncached `ffmpeg -filters` spawn) whenever a manifest sets
    `stabilize=True`, exactly the two tests below that do. Same convention as
    tests/lib/test_manifest.py's `test_a_manifest_without_stabilize_never_probes_ffmpeg`.
    `process_episode.vidstab` is the same `scripts.lib.vidstab` module object
    `manifest.py` imports, so patching it here reaches that call too."""
    monkeypatch.setattr(process_episode.reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 3.0, "yuv420p", "tv"))
    monkeypatch.setattr(process_episode.vidstab, "require", lambda: None)


def _stub_mechanical_pass(monkeypatch, route):
    """Fakes reframe.reframe / storyboard.build / check_episode.run enough to
    reach mechanical_pass without real ffmpeg — mirrors (trimmed to what this
    file needs) tests/integration/test_process_episode.py's `_stub_engine`.

    Returns a `calls` dict recording the `src` reframe.reframe received and the
    `source` check_episode.run received — a caller asserting `prepared_source`
    threading needs to see both land on the SAME pixels: reframe encodes them
    and check_episode judges them, two independent readers of the same claim.
    It also records the `CheckSpec` the check was handed (`calls["check_spec"]`):
    the bars a run was judged against are the one thing a gates test has to see — and
    the reasons it was handed beside them (`calls["check_gate_reasons"]`, None when the
    kwarg was not passed at all: a run that authored nothing keeps its call shape)."""
    calls = {}

    def fake_reframe(spec, src, route_path, out, path_out, stabilized=False):
        calls["reframe_src"] = src
        Path(out).write_text("clip")
        Path(path_out).write_text(json.dumps([100] * len(route)))
        models.PathMeta(mode="fill", crop_w=1920, crop_h=1080, crop_y=0,
                        src_dims=(1920, 1080), canvas=tuple(spec.canvas),
                        out_dims=(1920, 1080), rect_px=(0, 0, 1920, 1080),
                        freedom=0).write(Path(path_out).with_suffix(".meta.json"))
        return out
    monkeypatch.setattr(process_episode.reframe, "reframe", fake_reframe)

    def fake_storyboard_build(src, out, spec, route=None, path=None, meta=None):
        Path(out).write_text("sheet")
        return out, None
    monkeypatch.setattr(process_episode.storyboard, "build", fake_storyboard_build)

    def fake_run(clip, route_path, path_path, spec, out, source=None, plans=None,
                 gate_reasons=None):
        calls["check_source"] = source
        calls["check_plans"] = plans
        calls["check_spec"] = spec
        calls["check_gate_reasons"] = gate_reasons
        r = models.Report(checks={}, attempt=spec.attempt)
        r.write(out)
        return r
    monkeypatch.setattr(process_episode.check_episode, "run", fake_run)
    return calls


def test_stop_after_geometry_returns_the_route_and_the_source(tmp_path, monkeypatch):
    """The seam: tracking ran, nothing was encoded."""
    md = _episode_manifest(tmp_path)
    route = [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]

    def fake_build_route(spec, out):
        Path(out).write_text(json.dumps(route))
        Path(out).with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))
    monkeypatch.setattr(process_episode.track, "available", lambda descriptor=False: True)
    monkeypatch.setattr(process_episode.track, "build_route", fake_build_route)

    calls = []
    monkeypatch.setattr(process_episode.reframe, "reframe",
                        lambda *a, **k: calls.append("reframe"))
    res = process_episode.process_episode(md, tmp_path / "ep0", stop_after="geometry")
    assert res["status"] == "geometry"
    assert res["route"] == str(tmp_path / "ep0" / "route.json")
    assert res["source"] == md["segment"]
    assert calls == []                       # the encode never ran


def test_stop_after_geometry_refuses_an_unknown_value(tmp_path):
    res = process_episode.process_episode(_episode_manifest(tmp_path), tmp_path / "ep0",
                                          stop_after="colour")
    assert res["status"] == "needs_input"
    assert "stop_after" in res["problems"][0]


def test_prepared_source_unlocks_stabilize_with_a_frozen_route(tmp_path, monkeypatch):
    """The pairing --from-geometry asserts, and the ONLY way to assert it."""
    md = _episode_manifest(tmp_path)
    md["stabilize"] = True
    project_dir = tmp_path / "ep0"
    project_dir.mkdir(parents=True, exist_ok=True)
    prepared = project_dir / "stabilized.mp4"
    prepared.write_bytes(b"stabilized-fake-bytes")           # write the file
    route_data = [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]
    route = tmp_path / "frozen_route.json"
    route.write_text(json.dumps(route_data))
    route.with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))

    calls = _stub_mechanical_pass(monkeypatch, route_data)   # fake reframe/check(/storyboard)
    monkeypatch.setattr(process_episode.vidstab, "stabilize",
                        lambda *a, **k: pytest.fail("the pre-stage must not re-run"))

    res = process_episode.process_episode(md, project_dir,
                                          route_path=str(route), prepared_source=str(prepared))
    assert res["status"] == "mechanical_pass"
    # the pairing this parameter exists to assert: reframe must encode the SAME
    # pixels the frozen route was measured on, and check_episode must judge
    # those same pixels — not the raw, unstabilized segment. A drop of either
    # is silent (design 2026-07-20 §1: path and route still agree with each
    # other in source coordinates, only the pixels disagree).
    assert calls["reframe_src"] == str(prepared)
    assert calls["check_source"] == str(prepared)
    # grade_damage's plan pair must reach check_episode.run along this path too —
    # it is built from the SAME `src` local the two assertions above already pin,
    # so a None here would mean the retry loop stopped threading it through the
    # prepared_source/stabilize branch specifically.
    assert calls["check_plans"] is not None


def test_stabilize_still_refuses_a_bare_route(tmp_path):
    md = _episode_manifest(tmp_path)
    md["stabilize"] = True
    res = process_episode.process_episode(md, tmp_path / "ep0", route_path="r.json")
    assert res["status"] == "needs_input"
    assert "stabilize=true cannot be combined" in res["problems"][0]


def test_prepared_source_without_a_route_is_refused(tmp_path):
    res = process_episode.process_episode(_episode_manifest(tmp_path), tmp_path / "ep0",
                                          prepared_source="s.mp4")
    assert res["status"] == "needs_input"
    assert "prepared_source" in res["problems"][0]


# --- 2026-09-24 retry-record Task 2: reconstruct the render, not the declaration ---

def _meta_json(tmp_path, **over):
    """A real path.meta.json on disk. PathMeta's own to_dict writes it, so the file
    this reads is the shape reframe writes — not a hand-built dict that could drift
    from it."""
    pm = models.PathMeta(mode="fill", crop_w=405, crop_h=720, crop_y=0,
                         src_dims=(1280, 720), canvas=(9, 16), out_dims=(404, 720),
                         rect_px=(0, 0, 404, 720), freedom=875, **over)
    p = tmp_path / "path.meta.json"
    p.write_text(json.dumps(pm.to_dict()))
    return p


def test_rendered_params_reads_both_knobs_from_the_sidecar(tmp_path):
    p = _meta_json(tmp_path, max_speed=450.0, smooth_window_s=0.5)
    assert process_episode.rendered_params(p) == {"max_speed": 450.0,
                                                  "smooth_window_s": 0.5}


def test_rendered_params_fills_an_omitted_knob_from_the_defaults(tmp_path):
    # A lag retry moves max_speed and can leave the window exactly at the default,
    # which is then not emitted. The omitted key means "the render used the
    # default" — NOT "ask the manifest", which is what the authored value would
    # wrongly supply (design §2.2).
    p = _meta_json(tmp_path, max_speed=1125.0)
    assert process_episode.rendered_params(p) == {
        "max_speed": 1125.0, "smooth_window_s": orch.DEFAULT_PARAMS["smooth_window_s"]}


def test_rendered_params_reports_a_sidecar_that_says_nothing_as_absence(tmp_path):
    assert process_episode.rendered_params(_meta_json(tmp_path)) is None


def test_rendered_params_reports_a_missing_or_unnamed_sidecar_as_absence(tmp_path):
    # ReelEpisode.meta defaults to "" and a reel manifest may legally carry no
    # sidecar: that is an absence, not a fault.
    assert process_episode.rendered_params("") is None
    assert process_episode.rendered_params(None) is None
    assert process_episode.rendered_params(tmp_path / "gone.json") is None
    # Path("") is truthy (unlike the string "" above) and normalizes to Path("."),
    # which .exists() but is not a file — the case .is_file() exists to catch,
    # instead of falling through to a read that raises IsADirectoryError.
    assert process_episode.rendered_params(Path("")) is None


def test_rendered_params_still_raises_on_a_corrupt_sidecar(tmp_path):
    # A file that EXISTS and will not parse is machine-written content gone wrong.
    # Laundering it into "the defaults, then" hands the caller a plan built on a
    # guess — the exact substitution PathMeta.from_json refuses by design.
    p = tmp_path / "path.meta.json"
    p.write_text("{not json")
    with pytest.raises(RuntimeError, match=r"is corrupt"):
        process_episode.rendered_params(p)


def test_plan_for_uses_the_given_params_instead_of_the_manifests_authored_window(
        tmp_path, monkeypatch):
    """The replace-not-merge rule. A recorded sidecar is a COMPLETE account of what
    the render used, so an authored smooth_window_s must not win over it — after a
    retry the authored value is precisely what the ladder overrode."""
    seen = {}

    def _fake_plan_render(spec, src, route):
        seen["spec"] = spec
        return "plan"
    monkeypatch.setattr(process_episode.reframe, "plan_render", _fake_plan_render)

    md = _episode_manifest(tmp_path, smooth_window_s=1.2)
    process_episode.plan_for(md, "src.mp4", None,
                             params={"max_speed": 450.0, "smooth_window_s": 0.5})
    assert (seen["spec"].max_speed, seen["spec"].smooth_window_s) == (450.0, 0.5)


def test_plan_for_without_params_still_reads_the_manifests_authored_window(
        tmp_path, monkeypatch):
    """The control on the arm above: params=None must keep today's behaviour
    exactly, or every caller that does not pass params silently changes geometry."""
    seen = {}

    def _fake_plan_render(spec, src, route):
        seen["spec"] = spec
        return "plan"
    monkeypatch.setattr(process_episode.reframe, "plan_render", _fake_plan_render)

    md = _episode_manifest(tmp_path, smooth_window_s=1.2)
    process_episode.plan_for(md, "src.mp4", None)
    assert (seen["spec"].max_speed, seen["spec"].smooth_window_s) == (750.0, 1.2)


def test_plan_ungraded_threads_params_through_to_the_spec(tmp_path, monkeypatch):
    """The plain half of the damage pair must share the graded half's geometry. A
    passthrough that is silently dropped here would compare two crops and call the
    difference a grade."""
    seen = {}

    def _fake_plan_render(spec, src, route):
        seen["spec"] = spec
        return "plan"
    monkeypatch.setattr(process_episode.reframe, "plan_render", _fake_plan_render)

    process_episode.plan_ungraded(_episode_manifest(tmp_path), "src.mp4", None,
                                  params={"max_speed": 450.0, "smooth_window_s": 0.5})
    assert (seen["spec"].max_speed, seen["spec"].smooth_window_s) == (450.0, 0.5)


# --- 2026-09-30 threshold surface Task 3: authored gates reach the CheckSpec ---
# (design 2026-09-30 §2.3.) `gates` is a parameter on purpose — a run policy the operator
# authors in GATES.json — and never a Manifest field, which is something an agent writes
# into an EDL.

def _frozen_episode(tmp_path: Path,
                    monkeypatch: pytest.MonkeyPatch) -> tuple[dict, str, dict]:
    """A manifest, a frozen route for it, and the faked engine: everything a run needs to
    reach the check loop with no tracker and no ffmpeg. Returns (md, route, calls);
    `calls["check_spec"]` is the CheckSpec the check was handed."""
    route_data = [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]
    route = tmp_path / "frozen_route.json"
    route.write_text(json.dumps(route_data))
    route.with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))
    calls = _stub_mechanical_pass(monkeypatch, route_data)
    return _episode_manifest(tmp_path), str(route), calls


def _checked_spec(md: dict, attempt: int = 1, **over: float) -> models.CheckSpec:
    """The CheckSpec the run of `md` builds for `attempt`, with `over` authored on top."""
    return models.CheckSpec(composition=md["composition"], grid=md["grid"],
                            target_dur=md["target_dur"], attempt=attempt, **over)


def test_an_authored_entropy_floor_reaches_the_check_spec(tmp_path, monkeypatch):
    """Whole object: the authored bar moved AND every bar the author did not touch is
    still its default."""
    md, route, calls = _frozen_episode(tmp_path, monkeypatch)
    res = process_episode.process_episode(
        md, tmp_path / "ep0", route_path=route,
        gates={"entropy_floor": {"value": 0.85, "why": "log profile"}})
    assert res["status"] == "mechanical_pass"
    assert calls["check_spec"] == _checked_spec(md, entropy_floor=0.85)


@pytest.mark.parametrize("nothing", [None, {}], ids=["None", "empty-set"])
def test_no_gates_leaves_every_check_spec_field_at_its_default(tmp_path, monkeypatch, nothing):
    """The control: the plumbing injects nothing when nothing was authored. Both spellings
    of "nothing" are real — build_reel's reprocess hands over None for an empty episode
    subset, and ReelManifest.gates is {} when unauthored (leaving the parameter out is the
    call every pre-existing test makes). What the defaults ARE is pinned by
    tests/lib/test_models.py, so a recalibrated default fails there and this test fails
    only if the plumbing itself puts something in."""
    md, route, calls = _frozen_episode(tmp_path, monkeypatch)
    res = process_episode.process_episode(md, tmp_path / "ep0", route_path=route,
                                          gates=nothing)
    assert res["status"] == "mechanical_pass"
    assert calls["check_spec"] == _checked_spec(md)


def test_a_reel_scope_gate_handed_to_process_episode_is_ignored_not_crashed(
        tmp_path, monkeypatch):
    """for_spec partitions, so a caller handing over the WHOLE authored set is the normal
    case (edl_to_reel and build_reel both do). A reel-scope key must reach no CheckSpec
    and must not raise."""
    md, route, calls = _frozen_episode(tmp_path, monkeypatch)
    res = process_episode.process_episode(
        md, tmp_path / "ep0", route_path=route,
        gates={"beat_tol": {"value": 0.08, "why": "no click track"}})
    assert res["status"] == "mechanical_pass"
    assert calls["check_spec"] == _checked_spec(md)


@pytest.mark.parametrize("stop_after", [None, "geometry"], ids=["full-run", "geometry-run"])
def test_a_malformed_gate_set_is_refused_before_any_encode(tmp_path, monkeypatch, stop_after):
    """The set is parsed once at the very top of the run, not where the CheckSpec is built —
    that sits inside the retry loop, after tracking and an encode. Nothing ran: no reframe,
    no check, and not even the scratch directory. A geometry run never builds a CheckSpec at
    all, so only a parse placed before its seam refuses it there. A parse moved below the
    mkdir, below tracking, below the geometry return or into the loop body is refused too
    late, and fails here."""
    md, route, calls = _frozen_episode(tmp_path, monkeypatch)
    with pytest.raises(ValueError,
                       match=r"^the gates passed to process_episode entry 'entropy_floor'"):
        process_episode.process_episode(md, tmp_path / "ep0", route_path=route,
                                        stop_after=stop_after,
                                        gates={"entropy_floor": 0.85})      # no reason
    assert calls == {}
    assert not (tmp_path / "ep0").exists()


def test_the_authored_bar_rides_every_retry_attempt_not_only_the_first(tmp_path, monkeypatch):
    """Design §2.3 exists because a bar that silently differs between attempts, or between
    siblings, is the defect. A lone failing jitter on attempt 1 is retried, and the CheckSpec
    the second attempt is judged against must carry the authored value as well."""
    md, route, _ = _frozen_episode(tmp_path, monkeypatch)
    passing_run = process_episode.check_episode.run      # the faked check _frozen_episode installed
    specs = []

    def fail_once(clip, route_path, path_path, spec, out, source=None, plans=None,
                  gate_reasons=None):
        specs.append(spec)
        if len(specs) > 1:
            return passing_run(clip, route_path, path_path, spec, out,
                               source=source, plans=plans, gate_reasons=gate_reasons)
        report = models.Report(checks={"jitter": models.CheckResult("jitter", False, {})},
                               attempt=spec.attempt)
        report.write(out)
        return report
    monkeypatch.setattr(process_episode.check_episode, "run", fail_once)

    res = process_episode.process_episode(
        md, tmp_path / "ep0", route_path=route,
        gates={"entropy_floor": {"value": 0.85, "why": "log profile"}})

    assert res["status"] == "mechanical_pass" and res["attempt"] == 2
    assert specs == [_checked_spec(md, attempt=1, entropy_floor=0.85),
                     _checked_spec(md, attempt=2, entropy_floor=0.85)]


def test_the_reasons_reach_the_check_that_names_the_bars_it_judged_by(tmp_path, monkeypatch):
    """check_episode can only name a moved bar if it is handed the reason, and this is the call
    that hands it (design 2026-09-30 §2.4 item 1). The WHOLE authored set goes through, both
    scopes — the same rule as the gates themselves: the callee partitions and no caller does.
    The control is inside the test, so the instrument has just been shown able to see the
    kwarg before it is trusted to report its absence: a run that authored nothing is handed
    none, and keeps the call shape it had before gates existed."""
    md, route, calls = _frozen_episode(tmp_path, monkeypatch)
    process_episode.process_episode(
        md, tmp_path / "ep0", route_path=route,
        gates={"entropy_floor": {"value": 0.85, "why": "log profile"},
               "beat_tol": {"value": 0.08, "why": "no click track"}})
    assert calls["check_gate_reasons"] == {"entropy_floor": "log profile",
                                           "beat_tol": "no click track"}
    process_episode.process_episode(md, tmp_path / "ep1", route_path=route)
    assert calls["check_gate_reasons"] is None


def test_a_falsy_wrong_typed_gate_set_is_refused_not_read_as_no_gates(tmp_path, monkeypatch):
    """Only None means "no gates". `[]`, false, 0, "" and 0.0 are as wrong-typed as `[1]`,
    and `gates or {}` reads all five as absent — every authored bar silently back at its
    default, the defect ReelManifest.from_dict's own gates key already refuses. One test,
    not five: each value takes the same branch, so the loop names which were accepted."""
    md, route, calls = _frozen_episode(tmp_path, monkeypatch)
    accepted = []
    for bad in ([], False, 0, "", 0.0):
        try:
            process_episode.process_episode(md, tmp_path / "ep0", route_path=route, gates=bad)
        except ValueError as e:
            assert str(e).startswith("the gates passed to process_episode must be an object")
        else:
            accepted.append(bad)
    assert not accepted, f"process_episode read {accepted!r} as no gates"


def test_an_episode_manifest_cannot_carry_gates(tmp_path):
    """A gate is a run policy the operator authors, not a value an agent can write into an
    EDL, so `gates` is a parameter of process_episode and NOT a Manifest field. That holds
    today by omission and nothing else says so: adding the field would be a tidy-looking
    simplification that hands every EDL author the operator's pen."""
    md = _episode_manifest(tmp_path, gates={"entropy_floor": {"value": 0.85, "why": "x"}})
    res = process_episode.process_episode(md, tmp_path / "ep0")
    assert res["status"] == "needs_input"
    assert "unknown field(s) ['gates']" in res["problems"][0]


# --- threshold-surface Task 4, Step 3b: the hand-driven CLI finds GATES.json too ---
# (design 2026-09-30 §2.3.) skills/process-episode/SKILL.md documents this CLI as the way to
# drive ONE episode by hand. A re-render that judged against defaults while edl_to_reel
# judged its siblings against the authored bar would be the silent different-bar defect the
# build_reel reprocess arm exists to close, reached by the other door.

CLI_GATES_DOC = {"entropy_floor": {"value": 0.85, "why": "log profile"},
                 "loudness_tol": {"value": 2.0, "why": "live room"}}    # both scopes: the whole
                                                                        # document goes through


def _drive_main(monkeypatch, tmp_path, *argv):
    """Run process_episode.main() over `argv` with the episode run itself faked, and return the
    keyword arguments it was handed. What is under test is which gates the CLI found and passed;
    the run itself needs no files."""
    seen = {}

    def fake(md, project_dir, **kw):
        seen.update(kw)
        return {"status": "mechanical_pass"}
    monkeypatch.setattr(process_episode, "process_episode", fake)
    manifest = tmp_path / "episode.json"
    manifest.write_text("{}")
    monkeypatch.setattr("sys.argv", ["process_episode", str(manifest),
                                     "--project-dir", str(tmp_path / "scratch"), *argv])
    with pytest.raises(SystemExit) as e:
        process_episode.main()
    assert e.value.code == 0
    return seen


def test_the_cli_finds_gates_json_beside_the_project_it_was_given(
        tmp_path, monkeypatch, capsys):
    """Beside `--project`, found by convention exactly as edl_to_reel finds it. The manifest
    and the scratch dir sit elsewhere, so a lookup beside either of THEM finds nothing.

    And it SAYS so, as edl_to_reel does (count, which bars, which project.json): `--project`
    is optional on this CLI, so a GATES.json that was not picked up — no flag, or the wrong
    one — reads as silence and judges against the defaults. The document goes through whole,
    both scopes, because process_episode partitions where a spec is built."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "GATES.json").write_text(json.dumps(CLI_GATES_DOC))
    seen = _drive_main(monkeypatch, tmp_path, "--project", str(run / "project.json"))
    assert seen["gates"] == CLI_GATES_DOC
    err = capsys.readouterr().err
    assert "2 authored threshold(s) (entropy_floor, loudness_tol)" in err
    assert str(run / "project.json") in err


def test_the_cli_hands_its_keyframes_file_on(tmp_path, monkeypatch):
    """`--keyframes` is the manual tracking rung's answer channel (tracking-ladder design), and
    the call that forwards it is the one this slice added `gates=` to. The Task 7 AST sweep
    dropped the forward and the whole unit tier stayed green: the flag was parsed and ignored."""
    kf = tmp_path / "keyframes.json"
    seen = _drive_main(monkeypatch, tmp_path, "--keyframes", str(kf))
    assert seen["keyframes_path"] == str(kf)


def test_the_cli_hands_no_gates_when_no_file_sits_beside_the_project(
        tmp_path, monkeypatch, capsys):
    """The common case — every run that authored no gates — and the one a lookup written
    without an existence check would break. A guard, and green before the lookup existed,
    because nothing read a file then either. It says nothing either: an announcement printed
    for an empty set would be noise on every run."""
    run = tmp_path / "run"
    run.mkdir()
    seen = _drive_main(monkeypatch, tmp_path, "--project", str(run / "project.json"))
    assert not seen.get("gates")           # None and {} both mean "no gates in force"
    assert "authored threshold" not in capsys.readouterr().err


def test_the_cli_without_a_project_never_goes_looking_for_a_gates_file(
        tmp_path, monkeypatch, capsys):
    """No --project means no project.json to look beside, and a guess from the working
    directory would be a second, silent way to move a bar. A GATES.json in exactly the place a
    guess would try — the cwd, which is also beside episode.json — changes nothing. A guard,
    and green before the lookup existed, because nothing looked anywhere then either."""
    (tmp_path / "GATES.json").write_text(json.dumps(CLI_GATES_DOC))
    monkeypatch.chdir(tmp_path)
    assert not _drive_main(monkeypatch, tmp_path).get("gates")
    assert "authored threshold" not in capsys.readouterr().err


def test_the_cli_refuses_a_broken_gates_file_beside_the_project_and_names_it(
        tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "GATES.json").write_text(json.dumps({"entropy_floor": 0.85}))     # no reason
    with pytest.raises(ValueError) as e:
        _drive_main(monkeypatch, tmp_path, "--project", str(run / "project.json"))
    assert str(run / "GATES.json") in str(e.value)


# --- still (design 2026-10-20 §5) ---------------------------------------------------

@pytest.mark.parametrize("kw", [dict(route_path="route.json"), dict(keyframes_path="k.json")])
def test_a_still_takes_no_route_and_no_marks(tmp_path, kw):
    res = process_episode.process_episode(_episode_manifest(tmp_path, still=True), tmp_path, **kw)
    assert res["status"] == "needs_input"
    assert "a still episode takes no --route or --keyframes" in res["problems"][0]


def test_a_still_is_not_tracked_and_stops_at_geometry_with_no_route(tmp_path, monkeypatch):
    monkeypatch.setattr(process_episode.track, "build_route",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("tracked a still")))
    monkeypatch.setattr(process_episode.orch, "detect_contradictions",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("gated a still")))
    res = process_episode.process_episode(_episode_manifest(tmp_path, still=True), tmp_path,
                                          stop_after="geometry")
    assert res["status"] == "geometry" and res["route"] is None
