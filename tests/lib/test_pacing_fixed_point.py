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
from scripts.lib import hold
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


# --- with photos and a freeze: the grid authors their lengths (design 2026-10-21 §2.3) -
#
# A held length is a function of the music and of the positions the scenario's own
# lengths produce, never of a previous bind — so the round trip must still be a fixed
# point. The energy steps quiet -> mid -> loud so the holds take different counts, and
# each case's bar line sits 0.2s past its realized length so the outro fit fires.

def _photo(name):
    return FootageClip(source=name, dur=hold.HOLD_ROOM, res=(3024, 4032), fps=0.0,
                       kind="photo", windows=[FootageWindow(
                           start=0.0, dur=hold.HOLD_DEFAULT, shot_type="medium", people=1,
                           motion=0.0, shake=0.0)])


def _held_run_dir(tmp_path, *, closer):
    f = Footage(clips=[
        FootageClip(source="a.mp4", dur=CLIP_DUR, res=(W, H), fps=FPS, windows=[
            FootageWindow(start=0.5, dur=6.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0),
            FootageWindow(start=10.0, dur=4.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0)]),
        _photo("IMG_1.HEIC"), _photo("IMG_2.HEIC")])
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(f.to_dict()))
    eps = [{"source": "a.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
           {"freeze": True, "hold": 4},   # authored: the slot carries the count it was
                                          # fitted with, and the re-apply must bind it
           {"source": "IMG_1.HEIC", "window": 0, "composition": "center", "grid": "thirds"},
           {"source": "IMG_2.HEIC", "window": 0, "composition": "center", "grid": "thirds"}]
    if closer == "video":
        eps.append({"source": "a.mp4", "window": 1, "composition": "lead", "grid": "thirds"})
    (tmp_path / "selection.json").write_text(json.dumps({"episodes": eps}))
    (tmp_path / "project.json").write_text(json.dumps(
        {"purpose": "reel", "canvas": [1080, 1920], "delivery": "long_edge:240"}))
    track = tmp_path / "t.wav"
    track.write_bytes(b"only ever hashed, never decoded")
    line = 14.2 if closer == "video" else 10.2
    ms = MusicSpec(track=str(track), start_offset=0.0, duration=MUSIC_DUR, tempo=TEMPO,
                   beats=tuple(i * 0.5 for i in range(int(MUSIC_DUR / 0.5))),
                   energy=(0.1,) * 16 + (0.5,) * 12 + (0.9,) * 12, energy_hz=2.0,
                   bars=(line,), vocal_spans=((line, line + 1.8),))
    (tmp_path / "MUSIC.json").write_text(json.dumps(ms.to_dict()))
    return tmp_path


@pytest.mark.parametrize("closer", ["video", "photo"])
def test_a_cut_with_photos_and_a_freeze_is_a_fixed_point(tmp_path, closer):
    run_dir = _held_run_dir(tmp_path, closer=closer)
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")
    spine1 = _fit(run_dir, edl0, "f1")
    edl_a = _plan(run_dir, "pa", pacing_path=spine1, music=music)
    spine2 = _fit(run_dir, edl_a, "f2")
    edl_b = _plan(run_dir, "pb", pacing_path=spine2, music=music)

    assert edl_a.read_bytes() == edl_b.read_bytes()
    assert json.loads(open(spine1).read()) == json.loads(open(spine2).read())


@pytest.mark.parametrize("closer", ["video", "photo"])
def test_the_held_proof_would_be_vacuous_if_the_grid_did_not_move_the_holds(tmp_path, closer):
    # Guards the fixture: the holds must leave their 2.0s placeholder, take whole beats,
    # and the outro fit must fire — otherwise the byte comparison above proves nothing new
    run_dir = _held_run_dir(tmp_path, closer=closer)
    edl0 = _plan(run_dir, "p0")
    a = EDL.from_json(_plan(run_dir, "pa", music=str(run_dir / "MUSIC.json"),
                            pacing_path=_fit(run_dir, edl0, "f1")))
    held = [e for e in a.episodes if e.held()]
    assert len(held) == 3 and {e.dur for e in held} != {hold.HOLD_DEFAULT}
    placed = held if closer == "video" else held[:-1]     # the outro grows a held closer
    assert all(e.dur / 0.5 == round(e.dur / 0.5) for e in placed)
    if closer == "video":
        # the last photo keeps its planned 2 beats; before the [k/2, 2k] band it was
        # bound to 10 to reach a phrase line (design §2.2)
        assert held[-1].dur == 1.0
    assert a.outro is not None and a.outro.rung == "gap" and a.outro.moved > 0
    # the freeze's frame is resolved from the bound predecessor, after the fit
    assert a.episodes[1].start == pytest.approx(0.5 + a.episodes[0].dur - 1 / FPS)
