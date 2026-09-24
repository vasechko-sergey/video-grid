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
    and check_episode judges them, two independent readers of the same claim."""
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

    def fake_run(clip, route_path, path_path, spec, out, source=None, plans=None):
        calls["check_source"] = source
        calls["check_plans"] = plans
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
