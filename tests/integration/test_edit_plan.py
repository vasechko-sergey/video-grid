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
from scripts.lib import proc
from scripts.lib.footage import Footage, FootageClip, FootageWindow

pytestmark = pytest.mark.integration


def _fake_track_pe(monkeypatch):
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
        proc.run(["ffmpeg", "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)


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
    codecs = proc.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                       "stream=codec_type", "-of", "csv=p=0", str(out)]).stdout.decode()
    assert "video" in codecs
