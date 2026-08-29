"""Real-ffmpeg SP3→SP1 seam (design docs/specs/2026-07-12-edit-plan-spine-design.md):
a selection.json + FOOTAGE.json → edit_plan build → EDL.json → the existing
edl_to_reel → a delivered REEL_v1.mp4. Real edit_plan + real extract/assemble/
check_reel/deliver; process_episode's mechanical middle is faked because the
synthetic sample_clip is a box, not a person (real YOLO returns an empty route —
same reason test_front_spine fakes it). Proves the selection → EDL → reel WIRING
on real bytes, not pixel-level crop correctness."""
import json
from pathlib import Path

import pytest

from scripts import edit_plan, edl_to_reel
from scripts.lib import ffbin, proc
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage, FootageClip, FootageWindow

pytestmark = pytest.mark.integration


def _fake_track_pe(monkeypatch):
    def fake_pe(manifest, project_dir, route_path=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
        # real process_episode writes path.json + path.meta.json beside route.json on every
        # mechanical_pass (reframe emits both); mirror that so build_reel's frozen safe_zones
        # geometry reads real files. CropPath [0] is parallel to the single route point above;
        # a plain fill sidecar at the 1920x1080 source dims (safe_zones is advisory — these
        # tests don't assert it, so the values need only be valid, not "safe").
        (Path(project_dir) / "path.json").write_text(json.dumps([0]))
        (Path(project_dir) / "path.meta.json").write_text(json.dumps(
            {"mode": "fill", "crop_w": 1920, "crop_h": 1080, "crop_y": 0,
             "src_dims": [1920, 1080], "canvas": [1920, 1080], "out_dims": [1920, 1080],
             "rect_px": [0, 0, 1920, 1080], "freedom": 0}))
        proc.run([ffbin.ffmpeg(), "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    # process_episode is faked, but edl_to_reel calls track.ensure_model ITSELF above
    # the pool — unstubbed, this ffmpeg golden also constructs a real YOLO (importing
    # torch, and downloading 6MB on a cold cache) for a tracking pass it never runs.
    monkeypatch.setattr(edl_to_reel.track, "ensure_model", lambda m: None)


def _footage_json(tmp_path, source):
    # two windows far apart → the box sits at very different x → distinct phash (variety)
    f = Footage(clips=[FootageClip(source=source, dur=3.0, res=(1920, 1080), fps=30.0, windows=[
        FootageWindow(start=0.2, dur=1.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=1.8, dur=1.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _selection_json(tmp_path, source):
    sel = {"episodes": [
        {"source": source, "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": source, "window": 1, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}]}
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(sel))
    return str(p)


def _project_json(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def test_selection_becomes_edl_becomes_reel(sample_clip, tmp_path, monkeypatch):
    fj = _footage_json(tmp_path, sample_clip.name)
    sj = _selection_json(tmp_path, sample_clip.name)
    pj = _project_json(tmp_path)
    plan_out = tmp_path / "plan"

    res = edit_plan.write_edit_plan(fj, sj, pj, str(plan_out))
    assert res["status"] == "written", res
    edl_path = plan_out / "EDL.json"
    assert edl_path.exists() and (plan_out / "EDL.md").exists()
    assert "# Edit plan — 2 episodes" in (plan_out / "EDL.md").read_text()

    _fake_track_pe(monkeypatch)
    reel = edl_to_reel.edl_to_reel(
        str(edl_path), pj, footage_root=str(sample_clip.parent),
        work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"))
    assert reel["status"] == "delivered", reel
    out = Path(reel["output"])
    assert out.exists() and out.name == "REEL_v1.mp4"
    codecs = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v", "-show_entries",
                       "stream=codec_type", "-of", "csv=p=0", str(out)]).stdout.decode()
    assert "video" in codecs


def _span_footage_json(tmp_path, source):
    # three windows in one 3s shot (no scene cut) → a [0,1] span merges the first two,
    # window 2 stays single; the two episodes sit at different x so phash variety holds
    f = Footage(clips=[FootageClip(source=source, dur=3.0, res=(1920, 1080), fps=30.0, windows=[
        FootageWindow(start=0.2, dur=0.7, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=1.1, dur=0.7, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=2.1, dur=0.7, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _span_selection_json(tmp_path, source):
    sel = {"episodes": [
        {"source": source, "window": [0, 1], "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": source, "window": 2, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}]}
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(sel))
    return str(p)


def test_span_selection_becomes_edl_becomes_reel(sample_clip, tmp_path, monkeypatch):
    fj = _span_footage_json(tmp_path, sample_clip.name)
    sj = _span_selection_json(tmp_path, sample_clip.name)
    pj = _project_json(tmp_path)
    plan_out = tmp_path / "plan"

    res = edit_plan.write_edit_plan(fj, sj, pj, str(plan_out))
    assert res["status"] == "written", res
    edl_path = plan_out / "EDL.json"
    edl = json.loads(edl_path.read_text())
    assert len(edl["episodes"]) == 2
    # episode 0 is the merged span: from window 0's start (0.2) to window 1's end (1.8)
    assert edl["episodes"][0]["start"] == 0.2 and edl["episodes"][0]["dur"] == pytest.approx(1.6)

    _fake_track_pe(monkeypatch)
    reel = edl_to_reel.edl_to_reel(
        str(edl_path), pj, footage_root=str(sample_clip.parent),
        work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"))
    assert reel["status"] == "delivered", reel
    out = Path(reel["output"])
    assert out.exists() and out.name == "REEL_v1.mp4"


def _variety_footage_json(tmp_path, source):
    # 3 close windows (subject fills 80% of the frame each way) + 6 wide (2%x5%) on
    # one 4K clip. geometry.crop_for((9, 16), 1.0, 3840, 2160) == (1215, 2160): the
    # close windows stay close after a 9:16 crop (area 0.8*0.8=0.64, clamped, either
    # way > CLOSE_AREA 0.30) and the wide windows stay wide (area 0.001 source /
    # 0.0032 delivered, both under MEDIUM_AREA 0.08) — so only "close" can gap.
    windows = (
        [FootageWindow(start=float(i), dur=0.5, shot_type="close", people=1, motion=0.3,
                       shake=0.0, subject_w=0.8, subject_h=0.8) for i in range(3)]
        + [FootageWindow(start=float(10 + i), dur=0.5, shot_type="wide", people=1, motion=0.3,
                         shake=0.0, subject_w=0.02, subject_h=0.05) for i in range(6)])
    f = Footage(clips=[FootageClip(source=source, dur=20.0, res=(3840, 2160), fps=30.0,
                                   windows=windows)])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _variety_selection(source):
    # windows 3, 4, 5 are the first three "wide" windows above — the cut takes only
    # those, leaving all 3 "close" windows (0, 1, 2) and 3 more "wide" ones unused.
    return {"episodes": [
        {"source": source, "window": w, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}
        for w in (3, 4, 5)]}


def test_sp3_stops_on_a_variety_gap_then_passes_with_a_waiver(tmp_path):
    """A cut that ignores every close window the footage offers is refused; the same
    cut with a stated reason is written, and the reason lands INSIDE the stamped
    EDL.json where it cannot be quietly revised (design §8)."""
    source = "clip.mp4"
    fp = _variety_footage_json(tmp_path, source)
    selection = _variety_selection(source)
    sp = tmp_path / "selection.json"
    sp.write_text(json.dumps(selection))
    pp = _project_json(tmp_path)      # purpose "reel" -> 9:16 canvas

    stop = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "variety-gap"
    assert not (tmp_path / "EDL.json").exists()

    sp.write_text(json.dumps({**selection, "variety_waiver": "close windows are out of focus"}))
    ok = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert ok["status"] == "written"

    edl = EDL.from_json(tmp_path / "EDL.json")        # provenance check passes
    assert edl.variety.gaps == ("close",)
    assert edl.variety.waiver == "close windows are out of focus"
    assert "## Variety" in (tmp_path / "EDL.md").read_text()


def _geo_footage_json(tmp_path, source):
    # 3 "borderline" windows at 10%x30% of the frame (area 0.030) + 3 genuinely wide
    # ones (2%x5%, area 0.001) on one 4K clip. At 16:9 (no crop scaling) the
    # borderline windows read `wide` (0.030 < MEDIUM_AREA 0.08); at 9:16
    # (geometry.crop_for scales width by 3840/1215 = 3.16x) their area becomes
    # 0.0948, crossing into `medium`. The genuinely-wide windows stay `wide` in
    # either geometry (design §6).
    windows = (
        [FootageWindow(start=float(i), dur=0.5, shot_type="wide", people=1, motion=0.3,
                       shake=0.0, subject_w=0.1, subject_h=0.3) for i in range(3)]
        + [FootageWindow(start=float(10 + i), dur=0.5, shot_type="wide", people=1, motion=0.3,
                         shake=0.0, subject_w=0.02, subject_h=0.05) for i in range(3)])
    f = Footage(clips=[FootageClip(source=source, dur=20.0, res=(3840, 2160), fps=30.0,
                                   windows=windows)])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _geo_selection(source):
    # windows 3, 4, 5 are the genuinely-wide ones — the cut never references the
    # borderline windows 0, 1, 2 at all, in EITHER canvas.
    return {"episodes": [
        {"source": source, "window": w, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}
        for w in (3, 4, 5)]}


def _project_json_16x9(tmp_path):
    p = tmp_path / "project_16x9.json"
    p.write_text(json.dumps({"purpose": "youtube", "canvas": [1920, 1080], "delivery": "native"}))
    return str(p)


def test_sp3_delivered_geometry_is_what_decides(tmp_path):
    """The SAME footage passes 16:9 and stops 9:16 — proof the gate reads the crop,
    not the source frame. A subject at 3% of the source frame is `wide` in source
    geometry and `medium` once a 9:16 crop is taken (design §6)."""
    source = "clip.mp4"
    fp = _geo_footage_json(tmp_path, source)
    sp = tmp_path / "selection.json"
    sp.write_text(json.dumps(_geo_selection(source)))
    pp_16x9 = _project_json_16x9(tmp_path)
    pp_9x16 = _project_json(tmp_path)      # purpose "reel" -> 9:16 canvas, same helper test1 uses

    wide_canvas = edit_plan.write_edit_plan(str(fp), str(sp), str(pp_16x9), str(tmp_path))
    assert wide_canvas["status"] == "written"          # nothing but wide exists at 16:9
    tall = edit_plan.write_edit_plan(str(fp), str(sp), str(pp_9x16), str(tmp_path / "b"))
    assert tall["finding"]["reason"] == "variety-gap"  # the same windows read `medium`


def _repeat_footage_json(tmp_path, source):
    # One 20s clip with a cut at 10.0s. Windows 0 and 1 live in the SAME shot and do
    # not overlap in time; window 2 is in the later shot.
    windows = [
        FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                      shake=0.0, subject_w=0.4, subject_h=0.5),
        FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                      shake=0.0, subject_w=0.4, subject_h=0.5),
        FootageWindow(start=12.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                      shake=0.0, subject_w=0.4, subject_h=0.5)]
    f = Footage(clips=[FootageClip(source=source, dur=20.0, res=(1920, 1080), fps=30.0,
                                   scene_cuts=[10.0], windows=windows)])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def test_sp3_refuses_a_repeat_the_user_forbade_and_records_the_rule_when_it_holds(tmp_path):
    """A rule stated once, in a file nobody passes on the command line, still binds:
    edit_plan finds CONSTRAINTS.json beside project.json, refuses the cut that breaks
    it, writes nothing, and — once the cut is fixed — records the rule inside the
    stamped EDL.json (design §6, §8)."""
    source = "clip.mp4"
    fp = _repeat_footage_json(tmp_path, source)
    pp = _project_json(tmp_path)          # writes project.json into tmp_path
    (tmp_path / "CONSTRAINTS.json").write_text(json.dumps(
        {"rules": [{"kind": "no_repeat", "stated": "эпизоды не должны повторяться"}]}))
    sp = tmp_path / "selection.json"
    sp.write_text(json.dumps({"episodes": [
        {"source": source, "window": w, "composition": "lead", "grid": "thirds"}
        for w in (0, 1)]}))               # both from the shot [0, 10)

    stop = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "constraint-violation"
    assert not (tmp_path / "EDL.json").exists()

    sp.write_text(json.dumps({"episodes": [
        {"source": source, "window": w, "composition": "lead", "grid": "thirds"}
        for w in (0, 2)]}))               # one from each shot
    ok = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert ok["status"] == "written"

    edl = EDL.from_json(tmp_path / "EDL.json")        # provenance check passes
    assert edl.constraints.ok
    # a TUPLE of dicts: to_dict writes a JSON list, and ConstraintReport.from_dict
    # normalises it back with tuple(...) — the same round-trip shape `rules` has in memory
    assert edl.constraints.rules == ({"kind": "no_repeat",
                                      "stated": "эпизоды не должны повторяться"},)
    assert "## Editorial rules" in (tmp_path / "EDL.md").read_text()
