# tests/lib/test_pacing_driver.py
"""The pacing driver: EDL + FOOTAGE + MUSIC(s) -> the fit report."""
import json

import pytest

from scripts import pacing as driver


def _write(path, obj):
    path.write_text(json.dumps(obj))
    return str(path)


@pytest.fixture
def run_dir(tmp_path):
    beats = [i * 0.5 for i in range(40)]
    _write(tmp_path / "MUSIC.json",
           {"track": "t.mp3", "start_offset": 0.0, "duration": 20.0, "tempo": 120.0,
            "beats": beats, "energy": [0.5] * 20, "energy_hz": 1.0})
    _write(tmp_path / "FOOTAGE.json",
           {"clips": [{"source": "a.mp4", "dur": 30.0, "res": [1920, 1080], "fps": 30.0,
                       "shaky": False, "scene_cuts": [],
                       "windows": [{"start": 0.0, "dur": 2.0, "shot_type": "wide",
                                    "people": 1, "motion": 0.4, "shake": 0.001,
                                    "description": "d", "score": 0.8, "best": True,
                                    "present": 1.0, "subject_w": 0.0, "subject_h": 0.0}]}]})
    _write(tmp_path / "EDL.json",
           {"episodes": [{"source": "a.mp4", "start": 0.0, "dur": 1.9, "shot_type": "wide",
                          "composition": "center", "grid": "thirds"},
                         {"source": "a.mp4", "start": 4.0, "dur": 2.1, "shot_type": "wide",
                          "composition": "center", "grid": "thirds"}],
            "cap": 3})
    return tmp_path


def test_fit_writes_both_artifacts_and_returns_the_spine(run_dir):
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [str(run_dir / "MUSIC.json")], str(run_dir))
    assert (run_dir / "PACING.json").exists()
    assert (run_dir / "PACING.md").exists()
    assert len(res["spine"].slots) == 2


def test_the_report_names_every_rejected_level_with_its_number(run_dir):
    driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                        [str(run_dir / "MUSIC.json")], str(run_dir))
    md = (run_dir / "PACING.md").read_text()
    assert "| level | step | worst | needed | verdict |" in md
    assert "phrase" in md and "beat" in md


def test_the_snapped_durations_stay_inside_the_shot_s_room(run_dir):
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [str(run_dir / "MUSIC.json")], str(run_dir))
    # window at 4.0 in a 30s cut-free clip has 26s of room; the snap is capped by the
    # allowance (0.25s at 120 BPM), not the room.
    assert res["spine"].slots[0].dur == pytest.approx(2.0)


def test_several_music_candidates_are_compared_and_the_best_wins(run_dir):
    shifted = [i * 0.5 + 0.13 for i in range(40)]
    _write(run_dir / "MUSIC_b.json",
           {"track": "t.mp3", "start_offset": 5.0, "duration": 20.0, "tempo": 120.0,
            "beats": shifted, "energy": [0.5] * 20, "energy_hz": 1.0})
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [str(run_dir / "MUSIC.json"), str(run_dir / "MUSIC_b.json")],
                              str(run_dir))
    assert res["music"] == str(run_dir / "MUSIC.json")   # the un-shifted grid lands exactly


def test_an_edl_source_missing_from_footage_fails_loud(run_dir):
    _write(run_dir / "EDL.json",
           {"episodes": [{"source": "ghost.mp4", "start": 0.0, "dur": 1.9,
                          "shot_type": "wide", "composition": "center", "grid": "thirds"}],
            "cap": 3})
    with pytest.raises(ValueError, match="ghost.mp4"):
        driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                            [str(run_dir / "MUSIC.json")], str(run_dir))


def test_off_grid_report_logs_a_remedy_and_lists_each_level_once(tmp_path, capsys):
    # A beat grid with a GAP (no beats between 2.0 and 8.0). The only cut lands at 5.0s,
    # 3.0s from the nearest line — far beyond the half-beat allowance at every level — so
    # nothing fits. This is the degradation the slice exists to make honest.
    # The grid carries 16 beats on purpose: best_fit sweeps every phase of the coarsest
    # level (phrase = 16 beats/line), so a shorter grid leaves that sweep with empty lines.
    beats = ([0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75]      # dense cluster before the gap
             + [8.0, 8.25, 8.5, 8.75, 9.0, 9.25, 9.5, 9.75])   # dense cluster after it
    _write(tmp_path / "MUSIC.json",
           {"track": "t.mp3", "start_offset": 0.0, "duration": 10.0, "tempo": 120.0,
            "beats": beats, "energy": [0.5] * 10, "energy_hz": 1.0})
    _write(tmp_path / "FOOTAGE.json",
           {"clips": [{"source": "a.mp4", "dur": 30.0, "res": [1920, 1080], "fps": 30.0,
                       "shaky": False, "scene_cuts": [],
                       "windows": [{"start": 0.0, "dur": 5.0, "shot_type": "wide",
                                    "people": 1, "motion": 0.4, "shake": 0.001,
                                    "description": "d", "score": 0.8, "best": True,
                                    "present": 1.0, "subject_w": 0.0, "subject_h": 0.0}]}]})
    _write(tmp_path / "EDL.json",
           {"episodes": [{"source": "a.mp4", "start": 0.0, "dur": 5.0, "shot_type": "wide",
                          "composition": "center", "grid": "thirds"},
                         {"source": "a.mp4", "start": 10.0, "dur": 5.0, "shot_type": "wide",
                          "composition": "center", "grid": "thirds"}],
            "cap": 3})
    res = driver.build_pacing(str(tmp_path / "EDL.json"), str(tmp_path / "FOOTAGE.json"),
                              [str(tmp_path / "MUSIC.json")], str(tmp_path))
    assert res["fit"].fits is False
    err = capsys.readouterr().err
    assert "no level fits" in err                          # the actionable remedy fired
    md = (tmp_path / "PACING.md").read_text()
    # Each of the 5 GRID_LEVELS appears exactly once in the fit table (rows carry "beats |").
    rows = [ln for ln in md.splitlines() if ln.startswith("| ") and "beats |" in ln]
    assert len(rows) == 5
