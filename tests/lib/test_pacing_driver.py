# tests/lib/test_pacing_driver.py
"""The pacing driver: EDL + FOOTAGE + MUSIC(s) -> the fit report."""
import json

import pytest

from scripts import pacing as driver
from scripts import pacing as pacing_driver
from scripts.lib import pacing as pacing_lib
from scripts.lib.edl import EDL, EDLEpisode, write_edl
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.models import MusicSpec
from scripts.lib.pacing import music_identity


def _write(path, obj):
    path.write_text(json.dumps(obj))
    return str(path)


def _edl(eps):
    return EDL(episodes=tuple(eps))


def _footage_obj(room):
    return Footage(clips=[FootageClip(source="a.mp4", dur=room, res=(1920, 1080), fps=30.0)])


def _write_edl(tmp_path, eps):
    return _write(tmp_path / "EDL.json", _edl(eps).to_dict())


def _footage(tmp_path):
    return _write(tmp_path / "FOOTAGE.json",
                  {"clips": [{"source": "a.mp4", "dur": 30.0, "res": [1920, 1080], "fps": 30.0,
                              "shaky": False, "scene_cuts": [], "windows": []}]})


def _music(tmp_path):
    beats = [i * 0.5 for i in range(40)]
    return _write(tmp_path / "MUSIC.json",
                  {"track": "t.mp3", "start_offset": 0.0, "duration": 20.0, "tempo": 120.0,
                   "beats": beats, "energy": [0.5] * 20, "energy_hz": 1.0})


def _ramped_episode(dur, factor):
    # region = [at - hold/2 - ease, at + hold/2 + ease]; at=dur/2, hold=1.0, ease=0.5
    # centers the region in the window with 1.0s of head/tail room to spare.
    return EDLEpisode(source="a.mp4", start=0.0, dur=dur, shot_type="wide",
                      composition="lead", grid="thirds",
                      ramp={"at": dur / 2, "factor": factor, "ease": 0.5, "hold": 1.0})


def _plain_episode(dur):
    return EDLEpisode(source="a.mp4", start=0.0, dur=dur, shot_type="wide",
                      composition="lead", grid="thirds")


class _Stop(Exception):
    pass


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


def test_the_fitter_receives_played_lengths_not_source_windows(monkeypatch, tmp_path):
    seen = {}

    def spy(durs, beats, energy, hz, tempo, bounds):
        seen["durs"] = list(durs)
        raise _Stop()

    monkeypatch.setattr(driver.pacing, "fit_spine", spy)
    ep = _ramped_episode(dur=4.0, factor=0.4)
    with pytest.raises(_Stop):
        driver.build_pacing(_write_edl(tmp_path, [ep]), _footage(tmp_path),
                            [_music(tmp_path)], str(tmp_path))
    assert seen["durs"] == [pytest.approx(ep.play_dur())]
    assert seen["durs"] != [4.0], "fitting the source window puts every later cut off-beat"


def test_the_shrink_bound_stops_at_the_ramp_region(tmp_path):
    # window 4.0s, region [1.0, 3.0] -> only 1.0s of tail may be trimmed, even
    # though half the window (2.0s) and the allowance might both be larger.
    ep = _ramped_episode(dur=4.0, factor=0.4)
    lo, _hi = driver._bounds(_edl([ep]), _footage_obj(room=10.0), allow=2.0)[0]
    assert lo == pytest.approx(-1.0)


def test_the_shrink_bound_is_unchanged_without_a_ramp(tmp_path):
    ep = _plain_episode(dur=4.0)
    lo, _hi = driver._bounds(_edl([ep]), _footage_obj(room=10.0), allow=2.0)[0]
    assert lo == pytest.approx(-2.0)     # min(allow, dur/2) as before


def test_the_shrink_bound_never_empties_the_interval_at_a_flush_ramp_edge(tmp_path):
    # Final-review finding: at=0.8, factor=0.5, ease=0.3, hold=0.6 puts the ramp
    # region's tail EXACTLY at the window's own end (0.8 + 0.3 + 0.3 == 1.4 == dur) —
    # so ramp.tail_room's subtraction rounds to a float hair NEGATIVE (-2.22e-16)
    # instead of the mathematical 0.0. And a window flush with its shot's end (room
    # == dur, the ordinary case for a clip's LAST window) makes `hi` exactly 0.0 too.
    # Unfloored, `shrink` goes negative and `lo` turns POSITIVE — bounds[0] ==
    # (2.22e-16, 0.0), an EMPTY interval gridfit.fit_level refuses as "a caller bug",
    # even though this is an entirely ordinary decimal-authored ramp on a legal EDL.
    # The exact reproducer from the review (room=dur=1.4 matches FootageClip(dur=1.4)
    # with ep.start=0.0 and no scene cuts, since room_after then returns dur - start).
    ep = EDLEpisode(source="a.mp4", start=0.0, dur=1.4, shot_type="wide",
                    composition="lead", grid="thirds",
                    ramp={"at": 0.8, "factor": 0.5, "ease": 0.3, "hold": 0.6})
    lo, hi = driver._bounds(_edl([ep]), _footage_obj(room=1.4), allow=2.0)[0]
    assert lo <= hi, f"empty interval ({lo!r}, {hi!r}) — gridfit.fit_level would refuse it"
    assert lo == pytest.approx(0.0, abs=1e-9)


def test_the_extend_bound_is_unchanged_by_a_ramp(tmp_path):
    # Outside the region the speed is exactly 1, so extending the played length by
    # d costs d of source — `room - dur` is already right in source seconds.
    ramped = _ramped_episode(dur=4.0, factor=0.4)
    plain = _plain_episode(dur=4.0)
    _lo_r, hi_r = driver._bounds(_edl([ramped]), _footage_obj(room=4.5), allow=2.0)[0]
    _lo_p, hi_p = driver._bounds(_edl([plain]), _footage_obj(room=4.5), allow=2.0)[0]
    assert hi_r == pytest.approx(hi_p) == pytest.approx(0.5)


def _grid(bpm, n=400):
    return [i * 60.0 / bpm for i in range(n)]


def _fit(durs, bpm):
    spine, _f, _r = pacing_lib.fit_spine(durs, _grid(bpm), [0.5] * 800, 2.0, bpm,
                                         [(-2.0, 2.0)] * len(durs))
    return [round(s.dur, 4) for s in spine.slots], [s.line for s in spine.slots]


def test_refitting_an_already_fitted_edit_lands_on_different_beats():
    # design §1.2, the measurement this slice exists to remove. Kept as a pin on
    # fit_spine itself: the function is NOT idempotent across windows, and it does
    # not have to be — the fix is that nobody feeds it its own output any more.
    scenario = [5.77, 3.41, 6.02, 4.88]
    fitted_to_128, _ = _fit(scenario, 128.0)
    assert fitted_to_128 == [5.625, 3.2812, 6.0938, 4.88]
    from_fitted, lines_a = _fit(fitted_to_128, 110.0)
    from_scenario, lines_b = _fit(scenario, 110.0)
    beat = 60.0 / 110.0
    assert [round(x / beat) for x in lines_a[:-1]] == [10, 16, 27]
    assert [round(x / beat) for x in lines_b[:-1]] == [11, 17, 28]
    assert round(sum(from_fitted) - sum(from_scenario), 4) == -0.5455


def _edl_json(tmp_path, *, dur, base_dur, source="a.mp4"):
    """Two episodes: the first out-point is a real CUT the grid can snap, the second
    is the tail, which fit_spine never snaps (line=None). A single-episode EDL would
    make every assertion below vacuous."""
    def ep(d, b):
        return EDLEpisode(source=source, start=0.0, dur=d, base_dur=b,
                          shot_type="wide", composition="lead", grid="thirds")
    p = tmp_path / "EDL.json"
    write_edl(EDL(episodes=(ep(dur, base_dur), ep(3.0, 3.0 if base_dur else None))), p)
    return str(p)


def _footage_json(tmp_path, *, source="a.mp4", clip_dur=20.0, window_dur=4.0):
    f = Footage(clips=[FootageClip(source=source, dur=clip_dur, res=(640, 360), fps=30.0,
                                   windows=[FootageWindow(start=0.0, dur=window_dur,
                                                          shot_type="wide", people=1,
                                                          motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _music_json(tmp_path, tempo=120.0, duration=20.0, track=None):
    # The beat count is DERIVED from the window, never hardcoded: MusicSpec refuses a
    # beat outside [0, duration], and at 110 BPM a hardcoded 40 beats overruns a 20s
    # window ("has 20.18… outside [0, 20.0]").
    if track is None:
        track = tmp_path / "t.wav"
        track.write_bytes(b"not really audio, only hashed")
    step = 60.0 / tempo
    ms = MusicSpec(track=str(track), start_offset=0.0, duration=duration, tempo=tempo,
                   beats=tuple(i * step for i in range(int(duration / step))),
                   energy=(0.3,) * 10, energy_hz=2.0)
    p = tmp_path / "MUSIC.json"
    p.write_text(json.dumps(ms.to_dict()))
    return str(p)


def test_build_pacing_fits_the_scenario_length_not_the_bound_one(tmp_path):
    # The opening episode was bound to 4.4 and the scenario said 4.0. At 120 BPM the
    # grid has a line at exactly 4.0, so a spine fitted to the scenario needs no shift
    # at all — while one fitted to 4.4 snaps up to 4.5.
    edl = _edl_json(tmp_path, dur=4.4, base_dur=4.0)
    res = pacing_driver.build_pacing(edl, _footage_json(tmp_path),
                                     [_music_json(tmp_path)], str(tmp_path / "out"))
    assert [s.dur for s in res["spine"].slots] == [4.0, 3.0]
    assert res["spine"].target_dur == 7.0


def test_build_pacing_falls_back_to_the_bound_length_without_a_base(tmp_path):
    edl = _edl_json(tmp_path, dur=4.4, base_dur=None)
    res = pacing_driver.build_pacing(edl, _footage_json(tmp_path),
                                     [_music_json(tmp_path)], str(tmp_path / "out"))
    assert [s.dur for s in res["spine"].slots] == [4.5, 3.0]
    assert res["spine"].target_dur == 7.5


def test_the_grow_bound_is_measured_from_the_scenario_length(tmp_path):
    # room_after(0.0) is 4.1s, and the scenario window is 4.0 -> 0.1s of grow room.
    # Reading the BOUND 4.4 instead would compute a NEGATIVE room and clamp to 0,
    # forbidding a growth the shot actually has.
    edl = _edl_json(tmp_path, dur=4.4, base_dur=4.0)
    footage = _footage_json(tmp_path, clip_dur=4.1)
    lo, hi = pacing_driver._bounds(EDL.from_json(edl), Footage.from_json(footage), 0.25)[0]
    assert (round(lo, 4), round(hi, 4)) == (-0.25, 0.1)


def test_build_pacing_records_the_music_window_identity(tmp_path):
    mj = _music_json(tmp_path)
    res = pacing_driver.build_pacing(_edl_json(tmp_path, dur=4.0, base_dur=4.0),
                                     _footage_json(tmp_path), [mj], str(tmp_path / "out"))
    m = MusicSpec.from_json(mj)
    assert res["spine"].music_digest == music_identity(m.track, m.start_offset, m.duration)


def test_build_pacing_says_so_when_the_track_cannot_be_hashed(tmp_path, capsys):
    mj = _music_json(tmp_path, track=tmp_path / "gone.wav")
    res = pacing_driver.build_pacing(_edl_json(tmp_path, dur=4.0, base_dur=4.0),
                                     _footage_json(tmp_path), [mj], str(tmp_path / "out"))
    assert res["spine"].music_digest == ""
    assert "records no music_digest" in capsys.readouterr().err


def test_build_pacing_warns_when_the_edl_has_no_base_dur(tmp_path, capsys):
    # Final review Finding 1: this is where a base_dur-less EDL.json is actually
    # READ, so this is where the warning belongs — edit_plan._bind_pacing's arm
    # note (see test_bind_pacing_names_the_arm_when_an_episode_has_no_base_dur) only
    # fires for a directly hand-built no-base_dur episode, never for the population
    # that reaches the refusal via a stale PACING.json like this one.
    edl = _edl_json(tmp_path, dur=4.4, base_dur=None)
    pacing_driver.build_pacing(edl, _footage_json(tmp_path), [_music_json(tmp_path)],
                               str(tmp_path / "out"))
    err = capsys.readouterr().err
    assert "predates the 2026-08-16 fixed-point slice" in err
    assert "rebuild the EDL WITHOUT --pacing/--music" in err


# --- energy_agreement reaches the fit report (design 2026-09-07-named-absence-design.md
# §7) --------------------------------------------------------------------------------


def test_the_fit_report_states_the_energy_agreement_beside_the_verdict(tmp_path):
    beats = [i * 0.5 for i in range(40)]
    energy = [0.1] * 20 + [0.9] * 20
    spine, fit, rejected = pacing_lib.fit_spine([4.0, 2.0], beats, energy, 1.0, 120.0,
                                                [(-0.25, 0.25)] * 2)
    md = pacing_driver._report(spine, fit, rejected, "MUSIC.json", {})
    assert "- **Energy agreement:**" in md
    assert "A DESCRIPTION, not a verdict" in md
