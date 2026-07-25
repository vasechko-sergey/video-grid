# tests/integration/test_scenario_first.py
"""The slice's proof over real pixels: a reel whose episodes keep their measured
durations end to end, and a spine that never invents one."""
import json

import pytest

from scripts import edit_plan, pacing as pacing_driver
from scripts.lib import ffbin, proc

pytestmark = pytest.mark.integration

_LONG = 7.3      # a "ride": longer than any slot the deleted 2/4/8 ladder could make


def _clip(path, dur):
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"testsrc=size=320x180:rate=30:duration={dur}", "-pix_fmt", "yuv420p",
              str(path)])


def test_a_ride_keeps_its_length_through_fit_and_bind(tmp_path):
    src = tmp_path / "ride.mp4"
    _clip(src, 20.0)
    beats = [i * 0.5 for i in range(80)]
    (tmp_path / "MUSIC.json").write_text(json.dumps(
        {"track": "t.mp3", "start_offset": 0.0, "duration": 40.0, "tempo": 120.0,
         "beats": beats, "energy": [0.5] * 40, "energy_hz": 1.0}))
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(
        {"clips": [{"source": "ride.mp4", "dur": 20.0, "res": [320, 180], "fps": 30.0,
                    "shaky": False, "scene_cuts": [],
                    "windows": [{"start": 0.0, "dur": _LONG, "shot_type": "wide",
                                 "people": 1, "motion": 0.4, "shake": 0.0,
                                 "description": "ride", "score": 0.9, "best": True}]}]}))
    (tmp_path / "EDL.json").write_text(json.dumps(
        {"episodes": [{"source": "ride.mp4", "start": 0.0, "dur": _LONG,
                       "shot_type": "wide", "composition": "center", "grid": "thirds"},
                      {"source": "ride.mp4", "start": 10.0, "dur": 5.0,
                       "shot_type": "wide", "composition": "center", "grid": "thirds"}],
         "cap": 3}))

    res = pacing_driver.build_pacing(str(tmp_path / "EDL.json"),
                                     str(tmp_path / "FOOTAGE.json"),
                                     [str(tmp_path / "MUSIC.json")], str(tmp_path))
    spine = res["spine"]
    # The ride reaches a line by moving at most half a beat, and NOTHING truncates it to
    # the 4 x 0.5s = 2.0s a "peak" slot used to be.
    assert spine.slots[0].dur == pytest.approx(_LONG, abs=0.25)
    assert spine.slots[0].dur > 4.6

    selection = {"episodes": [{"source": "ride.mp4", "window": 0,
                               "composition": "center", "grid": "thirds"}]}
    from scripts.lib.footage import Footage
    edl = edit_plan.build_edl(Footage.from_json(str(tmp_path / "FOOTAGE.json")),
                              selection, pacing=spine)
    assert edl.episodes[0].dur == pytest.approx(spine.slots[0].dur)
    assert edl.episodes[0].beat_slot == 0


def test_a_spine_from_another_edit_is_refused_not_applied(tmp_path):
    from scripts.lib import pacing as core
    from scripts.lib.footage import Footage
    _clip(tmp_path / "ride.mp4", 20.0)
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(
        {"clips": [{"source": "ride.mp4", "dur": 20.0, "res": [320, 180], "fps": 30.0,
                    "shaky": False, "scene_cuts": [],
                    "windows": [{"start": 0.0, "dur": _LONG, "shot_type": "wide",
                                 "people": 1, "motion": 0.4, "shake": 0.0,
                                 "description": "ride", "score": 0.9, "best": True}]}]}))
    foreign = core.Spine((core.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0),), 2.0,
                         120.0)
    selection = {"episodes": [{"source": "ride.mp4", "window": 0,
                               "composition": "center", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="fitted to a different"):
        edit_plan.build_edl(Footage.from_json(str(tmp_path / "FOOTAGE.json")),
                            selection, pacing=foreign)
