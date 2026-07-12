import json

import pytest
from scripts import edit_plan
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _clip(**kw):
    d = dict(source="MVI_3739.mp4", dur=22.0, res=(1920, 1080), fps=30.0,
             windows=[FootageWindow(start=2.1, dur=4.0, shot_type="close", people=1,
                                    motion=0.4, shake=0.01, description="lena nose")])
    d.update(kw)
    return FootageClip(**d)


def test_window_to_episode_copies_mechanical_fields_by_reference():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds")
    assert ep.source == "MVI_3739.mp4"                      # from the parent clip
    assert ep.start == 2.1 and ep.dur == 4.0                # from the window, not retyped
    assert ep.shot_type == "close"                          # window.shot_type default
    assert ep.processing_notes == "lena nose"                # window.description seed
    assert ep.composition == "lead" and ep.grid == "thirds"


def test_window_to_episode_forwards_editorial_and_overrides_defaults():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center", grid="phi",
                                     layout="insert", motion="lateral:right", hero=[10, 20, 30, 40],
                                     shot_type="wide", processing_notes="custom")
    assert ep.layout == "insert" and ep.motion == "lateral:right" and ep.hero == (10, 20, 30, 40)
    assert ep.shot_type == "wide"                           # editorial override wins over window default
    assert ep.processing_notes == "custom"


def test_window_to_episode_unknown_editorial_key_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="bogus"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds", bogus=1)


def test_window_to_episode_missing_required_composition_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="composition"):
        edit_plan.window_to_episode(clip, clip.windows[0], grid="thirds")


def _footage():
    return Footage(clips=[
        _clip(source="A.mp4", windows=[
            FootageWindow(start=0.5, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
            FootageWindow(start=5.0, dur=3.0, shot_type="close", people=1, motion=0.5, shake=0.0)]),
        _clip(source="B.mp4", windows=[
            FootageWindow(start=1.0, dur=2.5, shot_type="medium", people=2, motion=0.2, shake=0.0)])])


def test_build_edl_resolves_refs_and_projects_in_order():
    sel = {"episodes": [
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds", "motion": "static"}]}
    edl = edit_plan.build_edl(_footage(), sel)
    assert isinstance(edl, EDL) and len(edl.episodes) == 2
    assert edl.episodes[0].source == "B.mp4" and edl.episodes[0].start == 1.0    # by reference
    assert edl.episodes[1].source == "A.mp4" and edl.episodes[1].start == 5.0 and edl.episodes[1].dur == 3.0
    assert edl.episodes[1].motion == "static"


def test_build_edl_carries_reel_knobs():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}],
           "music": "MUSIC.json", "cap": 2, "target_dur": 6.0}
    edl = edit_plan.build_edl(_footage(), sel)
    assert edl.music == "MUSIC.json" and edl.cap == 2 and edl.target_dur == 6.0


def test_build_edl_defaults_cap_when_absent():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    assert edit_plan.build_edl(_footage(), sel).cap == 3


def test_build_edl_unknown_source_raises_listing_available():
    sel = {"episodes": [{"source": "Z.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"'Z\.mp4' not in FOOTAGE.*A\.mp4.*B\.mp4"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_out_of_range_window_raises_with_count():
    sel = {"episodes": [{"source": "B.mp4", "window": 3, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="window 3 out of range for B.mp4 .has 1."):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_missing_episodes_raises():
    with pytest.raises(ValueError, match="non-empty list"):
        edit_plan.build_edl(_footage(), {"episodes": []})


def test_build_edl_bad_window_type_raises():
    sel = {"episodes": [{"source": "A.mp4", "window": "first", "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'window' must be an integer"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_rejects_bool_window_not_index_one():
    # True is an int in Python — the guard must reject it, not treat it as window 1
    sel = {"episodes": [{"source": "A.mp4", "window": True, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'window' must be an integer"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_non_dict_episode_raises():
    with pytest.raises(ValueError, match="must be an object"):
        edit_plan.build_edl(_footage(), {"episodes": ["not-a-dict"]})


def test_build_edl_bad_source_type_raises():
    sel = {"episodes": [{"source": 5, "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'source' must be a clip path string"):
        edit_plan.build_edl(_footage(), sel)


def _write_inputs(tmp_path, sel):
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(_footage().to_dict()))
    (tmp_path / "selection.json").write_text(json.dumps(sel))
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return (str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
            str(tmp_path / "project.json"))


def test_write_edit_plan_writes_both_files_and_round_trips(tmp_path):
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "written" and res["episodes"] == 2
    assert (out / "EDL.json").exists() and (out / "EDL.md").exists()
    edl = EDL.from_json(str(out / "EDL.json"))                 # round-trips through the contract
    assert edl.episodes[0].source == "A.mp4" and edl.episodes[1].source == "B.mp4"
    assert "# Edit plan — 2 episodes" in (out / "EDL.md").read_text()


def test_write_edit_plan_bad_episode_stops_and_writes_nothing(tmp_path):
    # ep1 is fill+border → LayoutSpec rejects it in preflight
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi",
         "layout": "fill", "border_px": 5}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "edl-invalid"
    assert res["finding"]["episode_idx"] == 1
    assert not (out / "EDL.json").exists() and not (out / "EDL.md").exists()   # nothing written


def test_write_edit_plan_corrupt_selection_raises(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(_footage().to_dict()))
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    (tmp_path / "selection.json").write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        edit_plan.write_edit_plan(str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
                                  str(tmp_path / "project.json"), str(tmp_path / "out"))
