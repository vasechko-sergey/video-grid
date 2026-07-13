import json
import pytest
from pathlib import Path
from scripts import edl_to_reel


def _project(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def _edl_file(tmp_path, episodes=None, **reel):
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds", crop_scale=0.8)
    doc = {"episodes": episodes or [ep, {**ep, "start": 2.0}], **reel}
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _wire(monkeypatch, pe_results=None, build_result=None):
    """Fake extract_edl / process_episode / build_reel; record what the driver builds."""
    seen = {"segments": [], "pe": [], "rm": None, "build": [], "build_titles": None}

    def fake_extract(edl, footage_root, seg_dir):
        segs = [str(Path(seg_dir) / f"ep{i}_raw.mp4") for i in range(len(edl.episodes))]
        seen["segments"] = segs
        return segs
    monkeypatch.setattr(edl_to_reel.extract, "extract_edl", fake_extract)

    results = iter(pe_results or [])

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        seen["pe"].append({"manifest": manifest, "project_dir": project_dir})
        return next(results, {"status": "mechanical_pass", "clip": manifest["out_path"]})
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)

    def fake_build(rm, out_dir, work_dir, titles=None):
        # titles= is captured into seen["build_titles"] so a test can assert edl_to_reel
        # forwards it here (a silent drop would else pass CI) — not otherwise the subject
        # of this fixture, which mainly checks the extract→episodes→build hand-off.
        seen["rm"] = rm
        seen["build"].append((out_dir, work_dir))
        seen["build_titles"] = titles
        return build_result or {"status": "delivered", "output": f"{out_dir}/REEL_v1.mp4", "report": {}}
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel", fake_build)
    return seen


def test_happy_path_drives_extract_then_episodes_then_build_reel(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  footage_root=str(tmp_path), work_dir=str(tmp_path / "w"),
                                  out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered"
    assert len(seen["pe"]) == 2
    assert all(m["manifest"]["canvas"] == [1080, 1920] for m in seen["pe"])
    rm = seen["rm"]
    assert len(rm.episodes) == 2 and rm.target_dur == 4.0
    assert rm.episodes[0].manifest["canvas"] == [1080, 1920]
    assert rm.episodes[0].route.endswith("ep0/route.json")
    assert rm.cap == 3


def test_edl_music_and_target_override_reach_the_reel_manifest(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, music="M.json", cap=2, target_dur=9.0),
                            _project(tmp_path), str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"),
                            music="OVERRIDE.json")
    rm = seen["rm"]
    assert rm.music == "OVERRIDE.json"
    assert rm.target_dur == 9.0 and rm.cap == 2


def test_titles_forwarded_to_build_reel(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), titles="TITLES.json")
    assert seen["build_titles"] == "TITLES.json"    # titles= forwarded edl_to_reel -> build_reel


def test_bad_episode_preflights_before_any_ffmpeg(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    bad = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
               composition="lead", grid="thirds", crop_scale=1.0, crop_aspect="source")
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path, episodes=[bad]), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "edl-invalid"
    assert res["finding"]["episode_idx"] == 0
    assert seen["segments"] == [] and seen["pe"] == []


def test_episode_failure_stops_and_reports_without_building(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, pe_results=[{"status": "needs_input", "problems": ["ambiguous hero"]}])
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "episode-failed"
    assert res["finding"]["episode_idx"] == 0 and res["finding"]["sub_status"] == "needs_input"
    assert seen["rm"] is None and seen["build"] == []


def test_build_reel_stop_is_passed_through(monkeypatch, tmp_path):
    _wire(monkeypatch, build_result={"status": "stop_and_report", "finding": {"reason": "variety"}})
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "variety"
