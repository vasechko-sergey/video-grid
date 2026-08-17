"""fit -> apply -> fit -> apply is a fixed point (design
docs/specs/2026-08-16-pacing-fixed-point-design.md §3.1, §7).

Real drivers end to end — edit_plan.write_edit_plan and pacing.build_pacing — and no
ffmpeg at all: neither driver decodes a frame. The 'track' is a few bytes on disk
because music_identity only ever HASHES it; nothing here plays it.

Fixture shape copied from tests/integration/test_outro.py (two windows far apart in
one clip, a no-slack spine, one bar line the realized length is 0.2s short of) minus
everything that needed real pixels. The outro fit must actually fire: it is the case
that deadlocked, so a proof where it does not fire proves nothing."""
import json

import pytest

from scripts import edit_plan, pacing as pacing_driver
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.models import MusicSpec

W, H, FPS = 640, 360, 30.0
CLIP_DUR = 20.0
TEMPO = 120.0            # -> outro.bar_seconds == 2.0s, allowance == 0.25s
FADE = 0.5               # mix's own default: no look is authored in selection.json
LINE = 10.2              # the sole bar line; realized is 6.0 + 4.0 = 10.0s
MUSIC_DUR = 20.0


@pytest.fixture
def run_dir(tmp_path):
    f = Footage(clips=[FootageClip(source="a.mp4", dur=CLIP_DUR, res=(W, H), fps=FPS, windows=[
        FootageWindow(start=0.5, dur=6.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=10.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(f.to_dict()))
    (tmp_path / "selection.json").write_text(json.dumps({"episodes": [
        {"source": "a.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "a.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}))
    (tmp_path / "project.json").write_text(json.dumps(
        {"purpose": "reel", "canvas": [1080, 1920], "delivery": "long_edge:240"}))
    track = tmp_path / "t.wav"
    track.write_bytes(b"only ever hashed, never decoded")
    ms = MusicSpec(track=str(track), start_offset=0.0, duration=MUSIC_DUR, tempo=TEMPO,
                   beats=tuple(i * 0.5 for i in range(int(MUSIC_DUR / 0.5))),
                   energy=(0.3,) * 10, energy_hz=2.0, bars=(LINE,),
                   vocal_spans=((LINE, LINE + 1.8),))
    (tmp_path / "MUSIC.json").write_text(json.dumps(ms.to_dict()))
    return tmp_path


def _plan(run_dir, out_name, *, pacing_path=None, music=None):
    out = run_dir / out_name
    res = edit_plan.write_edit_plan(str(run_dir / "FOOTAGE.json"),
                                    str(run_dir / "selection.json"),
                                    str(run_dir / "project.json"), str(out),
                                    pacing_path=pacing_path, music=music)
    assert res["status"] == "written", res
    return out / "EDL.json"


def _fit(run_dir, edl_path, out_name):
    res = pacing_driver.build_pacing(str(edl_path), str(run_dir / "FOOTAGE.json"),
                                     [str(run_dir / "MUSIC.json")], str(run_dir / out_name))
    return res["json"]


def test_fit_then_apply_is_a_fixed_point(run_dir):
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")                                  # 1. the scenario
    spine1 = _fit(run_dir, edl0, "f1")                           # 2. fit it
    edl_a = _plan(run_dir, "pa", pacing_path=spine1, music=music) # 3. apply -> A
    spine2 = _fit(run_dir, edl_a, "f2")                          # 4. re-fit A
    edl_b = _plan(run_dir, "pb", pacing_path=spine2, music=music) # 5. re-apply -> B

    assert edl_a.read_bytes() == edl_b.read_bytes()


def test_the_proof_would_be_vacuous_without_the_outro_fit_firing(run_dir):
    # Guards the fixture, not the code: if the fit stopped firing, the fixed-point
    # test above would still pass and would no longer be testing the deadlock.
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")
    edl_a = EDL.from_json(_plan(run_dir, "pa", music=music,
                                pacing_path=_fit(run_dir, edl0, "f1")))
    assert edl_a.outro is not None and edl_a.outro.rung == "gap"
    assert edl_a.outro.reel_dur == pytest.approx(LINE + FADE)
    assert edl_a.episodes[-1].dur > edl_a.episodes[-1].base_dur


def test_the_refit_spine_is_the_same_spine(run_dir):
    # The mechanism, so a failure of the byte-comparison above is diagnosable:
    # both fits read base_play_dur, so they produce identical slots.
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")
    s1 = _fit(run_dir, edl0, "f1")
    edl_a = _plan(run_dir, "pa", pacing_path=s1, music=music)
    s2 = _fit(run_dir, edl_a, "f2")
    assert json.loads(open(s1).read()) == json.loads(open(s2).read())
