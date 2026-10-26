# tests/lib/test_pacing_driver.py
"""The pacing driver: EDL + FOOTAGE + MUSIC(s) -> the fit report."""
import json
from pathlib import Path

import pytest

from scripts import pacing as driver
from scripts import pacing as pacing_driver
from scripts.lib import gridfit, hold
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

    def spy(durs, beats, energy, hz, tempo, bounds, **_kw):
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


def test_the_fit_report_renders_a_computed_agreement_number(tmp_path):
    """The version of this test the fix wave first shipped used three slots, ALL
    measured (used == total == 3) and a perfectly-monotonic rho of exactly -1.0. A
    re-review simulating the three mutations this test exists to catch found it
    discriminates only one: transposing {used}/{total} renders "3 of 3" either way,
    and f"{-1.0:+.2f}" == f"{-1.0:.2f}" — the + flag only changes how a POSITIVE
    value renders, so dropping it from the format spec is invisible when rho is
    negative. Only a genuine sign inversion (abs(rho)) and a swapped ternary were
    actually caught (final review M-2, parked rather than spent on a second fix
    wave).

    This fixture adds a fourth, EXCLUDED slot (beats_in=0) so used=3 != total=4 —
    a transposition now renders "4 of 3" instead of "3 of 4" — while keeping rho
    negative so the sign-inversion catch survives. The dropped-+ mutation needs a
    POSITIVE rho instead (see the sibling test below): abs() of a positive number
    is a no-op, so no single rho value can discriminate both mutations at once."""
    slots = (pacing_lib.Slot(0, 0.0, 1.0, 0.5, "hook", line=1.0, dev=0.0, beats_in=0),
             pacing_lib.Slot(1, 1.0, 4.0, 0.1, "build", line=3.0, dev=0.0, beats_in=4),
             pacing_lib.Slot(2, 5.0, 3.0, 0.5, "build", line=6.0, dev=0.0, beats_in=3),
             pacing_lib.Slot(3, 8.0, 2.0, 0.9, "peak", line=None, dev=0.0, beats_in=2))
    spine = pacing_lib.Spine(slots, 10.0, 120.0)
    fit = gridfit.Fit(level="bar", level_n=2, phase=0, shifts=(0.0, 0.0, 0.0, 0.0),
                      devs=(0.0, 0.0, 0.0), needs=(0.0, 0.0, 0.0), worst=0.0, total=10.0,
                      fits=True)
    md = pacing_driver._report(spine, fit, [], "MUSIC.json", {})
    assert "- **Energy agreement:** -1.00 (Spearman rho, 3 of 4 slots used)" in md


def test_the_fit_report_renders_the_plus_sign_on_a_positive_agreement(tmp_path):
    """Companion to the test above: that one's rho is negative (-1.0), which already
    carries its own sign, so it cannot tell f"{rho:+.2f}" apart from f"{rho:.2f}" —
    the missing case M-2 named. This fixture uses a POSITIVE rho instead, which the
    + flag actually changes the rendering of ("+0.50" against "0.50").

    With exactly three measured slots a Spearman rank correlation can only land on
    +-1.0 or +-0.5 — six permutations of three ranks, no other value is reachable —
    so +0.50 (not +1.0, which a naive off-by-one on the format spec could still get
    right by accident) is the value to aim for: durs rank strictly increasing while
    energies rank (1, 3, 2)."""
    slots = (pacing_lib.Slot(0, 0.0, 2.0, 0.1, "hook", line=2.0, dev=0.0, beats_in=2),
             pacing_lib.Slot(1, 2.0, 3.0, 0.9, "peak", line=5.0, dev=0.0, beats_in=3),
             pacing_lib.Slot(2, 5.0, 4.0, 0.5, "build", line=None, dev=0.0, beats_in=4))
    spine = pacing_lib.Spine(slots, 9.0, 120.0)
    fit = gridfit.Fit(level="bar", level_n=2, phase=0, shifts=(0.0, 0.0, 0.0),
                      devs=(0.0, 0.0), needs=(0.0, 0.0), worst=0.0, total=9.0, fits=True)
    md = pacing_driver._report(spine, fit, [], "MUSIC.json", {})
    assert "- **Energy agreement:** +0.50 (Spearman rho, 3 of 3 slots used)" in md


def test_anchors_skip_a_held_episode(tmp_path, monkeypatch):
    """A freeze is one frame held: no motion curve to anchor on, like a photo (design
    2026-10-21 §2.3) — and nothing to decode for it either."""
    seen = []
    monkeypatch.setattr(driver.anchors, "measure_curve",
                        lambda src, start, dur: (seen.append((src, start, dur)),
                                                 [0.0, 1.0, 0.0])[1])
    played = _plain_episode(2.0)
    held = EDLEpisode(source="a.mp4", start=2.0 - 1 / 30, dur=2.0, shot_type="wide",
                      composition="lead", grid="thirds", freeze=True)
    driver.build_pacing(_write_edl(tmp_path, [played, held]), _footage(tmp_path),
                        [_music(tmp_path)], str(tmp_path / "out"),
                        footage_root=str(tmp_path), with_anchors=True)
    assert seen == [(str(tmp_path / "a.mp4"), 0.0, 2.0)]


# --- held episodes: the grid authors their length (design 2026-10-21 §2.3) -----------

def _held_footage(tmp_path):
    f = Footage(clips=[
        FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0),
        FootageClip(source="IMG_1.HEIC", dur=hold.HOLD_ROOM, res=(3024, 4032), fps=0.0,
                    kind="photo", windows=[FootageWindow(start=0.0, dur=hold.HOLD_DEFAULT,
                                                         shot_type="medium", people=1,
                                                         motion=0.0, shake=0.0)])])
    return _write(tmp_path / "FOOTAGE.json", f.to_dict())


def _photo(**kw):
    return EDLEpisode(source="IMG_1.HEIC", start=0.0, dur=hold.HOLD_DEFAULT,
                      base_dur=hold.HOLD_DEFAULT, shot_type="medium", composition="center",
                      grid="thirds", **kw)


def _freeze(**kw):
    return EDLEpisode(source="a.mp4", start=4.0 - 1 / 30, dur=hold.HOLD_DEFAULT,
                      base_dur=hold.HOLD_DEFAULT, shot_type="wide", composition="lead",
                      grid="thirds", freeze=True, shutter=True, **kw)


def _held_cut():
    return [EDLEpisode(source="a.mp4", start=0.0, dur=4.0, base_dur=4.0, shot_type="wide",
                       composition="lead", grid="thirds"),
            _freeze(hold=3), _photo(),
            EDLEpisode(source="a.mp4", start=10.0, dur=3.0, base_dur=3.0, shot_type="wide",
                       composition="lead", grid="thirds")]


def test_the_driver_hands_the_fitter_one_held_record_per_episode(monkeypatch, tmp_path):
    seen = {}

    def spy(durs, beats, energy, hz, tempo, bounds, *, held=None):
        seen["held"], seen["bounds"] = held, bounds
        raise _Stop()

    monkeypatch.setattr(driver.pacing, "fit_spine", spy)
    with pytest.raises(_Stop):
        driver.build_pacing(_write_edl(tmp_path, _held_cut()), _held_footage(tmp_path),
                            [_music(tmp_path)], str(tmp_path / "out"))
    assert seen["held"] == [None, gridfit.Held(3, hold.HOLD_MIN, hold.HOLD_ROOM),
                            gridfit.Held(None, hold.HOLD_MIN, hold.HOLD_ROOM), None]
    assert seen["bounds"][1:3] == [(0.0, 0.0), (0.0, 0.0)]


def test_a_video_only_cut_hands_the_fitter_no_held_list_at_all(monkeypatch, run_dir):
    seen = {}

    def spy(durs, beats, energy, hz, tempo, bounds, *, held=None):
        seen["held"] = held
        raise _Stop()

    monkeypatch.setattr(driver.pacing, "fit_spine", spy)
    with pytest.raises(_Stop):
        driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                            [str(run_dir / "MUSIC.json")], str(run_dir))
    assert seen == {"held": None}


def test_a_held_episodes_bounds_are_a_placeholder_the_walk_never_reads():
    f = Footage(clips=[FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0),
                       FootageClip(source="IMG_1.HEIC", dur=hold.HOLD_ROOM,
                                   res=(3024, 4032), fps=0.0, kind="photo")])
    assert driver._bounds(_edl(_held_cut()), f, 0.25) == [
        (-0.25, 0.25), (0.0, 0.0), (0.0, 0.0), (-0.25, 0.25)]


def test_the_fit_report_names_the_held_episodes_and_their_beats(tmp_path):
    res = driver.build_pacing(_write_edl(tmp_path, _held_cut()), _held_footage(tmp_path),
                              [_music(tmp_path)], str(tmp_path / "out"))
    slots = res["spine"].slots
    assert [s.held for s in slots] == [False, True, True, False]
    assert slots[1].dur == pytest.approx(1.5)        # the authored 3 beats at 120 BPM
    # the count it was fitted with rides into PACING.json, so a changed `hold` is refused
    # at binding (design §2.3)
    assert [s.get("hold") for s in json.loads((tmp_path / "out" / "PACING.json")
                                              .read_text())["slots"]] == [None, 3, None, None]
    md = (tmp_path / "out" / "PACING.md").read_text()
    n2 = round(slots[2].dur / 0.5)
    assert (f"- **Held:** 2 of 4 episodes (photos or freezes) — the grid authored their "
            f"lengths in whole beats: episode 1 = 3 beats, episode 2 = "
            f"{n2} beat{'' if n2 == 1 else 's'}") in md


def test_a_video_only_fit_report_says_nothing_about_holds(run_dir):
    driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                        [str(run_dir / "MUSIC.json")], str(run_dir))
    assert "Held" not in (run_dir / "PACING.md").read_text()
    assert "held" not in (run_dir / "PACING.json").read_text()


@pytest.mark.parametrize("beats, tempo, said", [(20, 120.0, "20 beats — 10.00s at 120.0 BPM"),
                                                (1, 200.0, "1 beat — 0.30s at 200.0 BPM")])
def test_an_authored_hold_outside_the_hold_range_at_the_windows_tempo_is_refused(
        tmp_path, beats, tempo, said):
    eps = _held_cut()
    eps[1] = _freeze(hold=beats)
    with pytest.raises(ValueError, match=f"episode 1 authors a hold of {said}"):
        driver.build_pacing(_write_edl(tmp_path, eps), _held_footage(tmp_path),
                            [_music_json(tmp_path, tempo=tempo)], str(tmp_path / "out"))


# --- a fitted reel the music window does not cover (design 2026-10-21 §2.2) ---------------

def _window(tmp_path, name, duration, tempo=120.0, energy=None):
    step = 60.0 / tempo
    ms = MusicSpec(track="t.mp3", start_offset=0.0, duration=duration, tempo=tempo,
                   beats=tuple(i * step for i in range(int(duration / step))),
                   energy=energy or (0.3,) * int(duration), energy_hz=1.0)
    return _write(tmp_path / name, ms.to_dict())


def _photo_cut(**photo):
    return [EDLEpisode(source="a.mp4", start=0.0, dur=4.0, base_dur=4.0, shot_type="wide",
                       composition="lead", grid="thirds"),
            _photo(**photo),
            EDLEpisode(source="a.mp4", start=10.0, dur=3.0, base_dur=3.0, shot_type="wide",
                       composition="lead", grid="thirds")]


def test_a_window_that_covers_the_fitted_reel_outranks_one_it_overruns(tmp_path, capsys):
    edl, footage = _write_edl(tmp_path, _photo_cut()), _held_footage(tmp_path)
    short = _window(tmp_path, "MUSIC_short.json", 8.0)      # the reel fits to 9.0
    whole = _window(tmp_path, "MUSIC_whole.json", 20.0)
    alone = [driver.build_pacing(edl, footage, [w], str(tmp_path / n))["fit"]
             for w, n in ((short, "s"), (whole, "w"))]
    # the premise: on the grid the two fit identically, so only coverage separates them
    assert [(f.level, f.phase, f.fits, f.worst) for f in alone] == [("bar", 0, True, 0.0)] * 2
    capsys.readouterr()
    res = driver.build_pacing(edl, footage, [short, whole], str(tmp_path / "out"))
    assert res["music"] == whole and res["spine"].target_dur == 9.0
    assert "overruns" not in capsys.readouterr().err


def test_coverage_outranks_a_coarser_level(tmp_path):
    edl, footage = _write_edl(tmp_path, _photo_cut()), _held_footage(tmp_path)
    # quiet where the photo sits: it plans 4 beats and reaches the 2-bar line 8 beats on —
    # the coarser fit, on a window the 11.0 s reel then overruns
    short = _window(tmp_path, "MUSIC_short.json", 10.0, energy=(1.0,) * 4 + (0.0,) * 6)
    whole = _window(tmp_path, "MUSIC_whole.json", 20.0)
    alone = [driver.build_pacing(edl, footage, [w], str(tmp_path / n))
             for w, n in ((short, "s"), (whole, "w"))]
    assert [(r["fit"].level, r["fit"].fits, r["spine"].target_dur) for r in alone] == [
        ("2-bar", True, 11.0), ("bar", True, 9.0)]
    res = driver.build_pacing(edl, footage, [short, whole], str(tmp_path / "out"))
    assert res["music"] == whole


def test_a_chosen_window_the_held_lengths_overrun_is_named_with_its_remedy(tmp_path, capsys):
    # an authored 8 beats (4.0 s, the placeholder was 2.0) carries the reel past a 9.0 s
    # window analysed for the scenario's own 9.0 s — on the grid, so the fit itself fits
    res = driver.build_pacing(_write_edl(tmp_path, _photo_cut(hold=8)), _held_footage(tmp_path),
                              [_window(tmp_path, "MUSIC.json", 9.0)], str(tmp_path / "out"))
    assert (res["spine"].target_dur, res["fit"].fits) == (11.0, True)
    assert ("pacing: the fitted reel (11.00s) overruns its music window (9.00s, MUSIC.json) "
            "by 2.00s — the scenario's cuts sum to 9.00s, and the lengths the grid authored "
            "for the 1 held episode grew the reel +2.00s from their placeholders. build_reel "
            "refuses a reel longer than its window: re-analyse with headroom (beats "
            "--auto-start --duration 15) and re-run pacing\n") in capsys.readouterr().err


def test_a_video_only_overrun_is_named_without_blaming_holds(run_dir, capsys):
    driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                        [_window(run_dir, "MUSIC_3s.json", 3.0)], str(run_dir))
    line = next(x for x in capsys.readouterr().err.splitlines() if "overruns" in x)
    assert line == ("pacing: the fitted reel (4.10s) overruns its music window (3.00s, "
                    "MUSIC_3s.json) by 1.10s — the scenario's cuts sum to 4.00s. build_reel "
                    "refuses a reel longer than its window: re-analyse with headroom (beats "
                    "--auto-start --duration 9) and re-run pacing")


@pytest.mark.parametrize("duration, named", [(4.05, False), (3.95, True)])
def test_an_overrun_is_judged_by_build_reels_own_tolerance(run_dir, capsys, duration, named):
    # the cut fits to 4.10 s: 0.05 past a window is inside build_reel's 0.1, 0.15 is not
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [_window(run_dir, "MUSIC_edge.json", duration)], str(run_dir))
    assert res["spine"].target_dur == pytest.approx(4.1)
    assert ("overruns" in capsys.readouterr().err) is named


# --- several candidate windows: each is fitted and checked on its own (design §2.3) -------

def test_every_candidate_window_is_fitted_with_the_held_records(monkeypatch, tmp_path):
    seen, real = [], pacing_lib.fit_spine

    def spy(*a, held=None, **kw):
        seen.append(held)
        return real(*a, held=held, **kw)

    monkeypatch.setattr(driver.pacing, "fit_spine", spy)
    driver.build_pacing(_write_edl(tmp_path, _held_cut()), _held_footage(tmp_path),
                        [_window(tmp_path, "MUSIC_a.json", 20.0),
                         _window(tmp_path, "MUSIC_b.json", 20.0, tempo=100.0)],
                        str(tmp_path / "out"))
    want = [None, gridfit.Held(3, hold.HOLD_MIN, hold.HOLD_ROOM),
            gridfit.Held(None, hold.HOLD_MIN, hold.HOLD_ROOM), None]
    assert seen == [want, want]


def test_a_window_whose_tempo_cannot_play_an_authored_hold_is_dropped_and_said(tmp_path,
                                                                             capsys):
    # one beat is 0.50 s at 120 BPM and 0.30 s at 200 — under HOLD_MIN only in the second.
    # The count is checked "per window": it used to refuse the whole run there, though
    # the first window plays it (final review M2)
    eps = _held_cut()
    eps[1] = _freeze(hold=1)
    res = driver.build_pacing(_write_edl(tmp_path, eps), _held_footage(tmp_path),
                              [_window(tmp_path, "MUSIC_a.json", 20.0),
                               _window(tmp_path, "MUSIC_b.json", 20.0, tempo=200.0)],
                              str(tmp_path / "out"))
    assert Path(res["music"]).name == "MUSIC_a.json"
    err = capsys.readouterr().err
    assert ("pacing: MUSIC_b.json dropped from the candidates — episode 1 authors a hold "
            "of 1 beat — 0.30s at 200.0 BPM (MUSIC_b.json)") in err


def test_an_authored_hold_no_window_can_play_is_refused_naming_each(tmp_path):
    eps = _held_cut()
    eps[1] = _freeze(hold=1)
    with pytest.raises(ValueError) as e:
        driver.build_pacing(_write_edl(tmp_path, eps), _held_footage(tmp_path),
                            [_window(tmp_path, "MUSIC_a.json", 20.0, tempo=200.0),
                             _window(tmp_path, "MUSIC_b.json", 20.0, tempo=190.0)],
                            str(tmp_path / "out"))
    msg = str(e.value)
    assert msg.startswith("pacing: no music window can play every authored hold — ")
    assert "0.30s at 200.0 BPM (MUSIC_a.json)" in msg
    assert "0.32s at 190.0 BPM (MUSIC_b.json)" in msg


def test_a_photo_only_reel_says_every_cut_is_a_held_cut_on_a_beat(tmp_path):
    """Final review M1: no cut of an all-held reel is matched against a level's lines,
    so PACING.md named a phrase level that no cut sits on."""
    res = driver.build_pacing(_write_edl(tmp_path, [_photo()] * 4), _held_footage(tmp_path),
                              [_music(tmp_path)], str(tmp_path / "out"))
    md = Path(res["md"]).read_text()
    assert "- **Level:** beat — every cut is a held cut on a detected beat" in md


def test_an_off_grid_photo_only_reel_does_not_claim_its_cuts_sit_on_beats(tmp_path):
    """Final re-review m1: a window whose beats end before the photos do places the last
    hold past the grid, and the level line must not state as fact what the verdict
    denies."""
    res = driver.build_pacing(_write_edl(tmp_path, [_photo()] * 4), _held_footage(tmp_path),
                              [_window(tmp_path, "MUSIC.json", 3.0)], str(tmp_path / "out"))
    md = Path(res["md"]).read_text()
    assert not res["fit"].fits
    assert "- **Verdict:** OFF-GRID — see below" in md
    assert "on a detected beat" not in md
    off = sum(1 for d in res["fit"].devs if d > gridfit.FIT_EPS)
    assert off >= 1
    assert (f"- **Level:** beat — every cut is a held cut; {off} of {len(res['fit'].devs)} "
            f"are off the detected beats (see below)") in md
    assert "phrase" not in md


def test_a_reel_with_footage_still_reports_its_level_and_phase(tmp_path):
    res = driver.build_pacing(_write_edl(tmp_path, _held_cut()), _held_footage(tmp_path),
                              [_music(tmp_path)], str(tmp_path / "out"))
    fit = res["fit"]
    assert (f"- **Level:** {fit.level} (every {fit.level_n} beat(s), phase {fit.phase})"
            in Path(res["md"]).read_text())
