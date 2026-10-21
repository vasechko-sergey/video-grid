"""gridfit — the grid levels and the lines they name (design 2026-07-24 §3)."""
import pytest

from scripts.lib import gridfit


def test_levels_are_coarsest_last_and_are_beat_multiples():
    names = [n for n, _ in gridfit.GRID_LEVELS]
    mults = [m for _, m in gridfit.GRID_LEVELS]
    assert names == ["beat", "half-bar", "bar", "2-bar", "phrase"]
    assert mults == [1, 2, 4, 8, 16]
    assert mults == sorted(mults)


def test_lines_at_takes_every_nth_beat_from_the_phase():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    assert gridfit.lines_at(beats, 4, 0) == [0.0, 2.0]
    assert gridfit.lines_at(beats, 4, 1) == [0.5, 2.5]
    assert gridfit.lines_at(beats, 1, 0) == beats


def test_lines_at_refuses_a_phase_outside_its_level():
    with pytest.raises(ValueError, match="phase"):
        gridfit.lines_at([0.0, 0.5], 2, 2)


def test_lines_at_refuses_a_level_below_one():
    with pytest.raises(ValueError, match="level_n"):
        gridfit.lines_at([0.0, 0.5], 0, 0)


def test_lines_at_refuses_an_empty_beat_grid():
    with pytest.raises(ValueError, match="no beats"):
        gridfit.lines_at([], 1, 0)


def test_allowance_is_half_a_beat():
    assert gridfit.allowance(120.0) == pytest.approx(0.25)
    assert gridfit.allowance(104.16666666666667) == pytest.approx(0.288, abs=1e-3)


def test_allowance_refuses_a_nonpositive_tempo():
    with pytest.raises(ValueError, match="tempo"):
        gridfit.allowance(0)


def test_allowance_refuses_a_bool_tempo():
    # bool is a subclass of int: True == 1 would silently pass as tempo=1 without this guard.
    with pytest.raises(ValueError, match="tempo"):
        gridfit.allowance(True)


def test_lines_at_refuses_a_bool_level():
    with pytest.raises(ValueError, match="level_n"):
        gridfit.lines_at([0.0, 0.5], True, 0)


def test_lines_at_refuses_a_bool_phase():
    with pytest.raises(ValueError, match="phase"):
        gridfit.lines_at([0.0, 0.5], 2, True)


def test_fit_snaps_the_cumulative_cut_not_each_duration():
    # Non-degenerate on purpose: cut 0 is clamped (+0.3, still short of 2.0), leaving a
    # residual. Measured CUMULATIVELY cut 1 sits at 1.5+1.9=3.4 and needs +0.6 (clamped to
    # +0.3); measured INDEPENDENTLY (pos reset to 0 each step) cut 1 sits at 1.9 and needs
    # only +0.1. The shifts differ — (0.3, 0.3, 0.0) cumulative vs (0.3, 0.1, 0.0)
    # independent — so this data distinguishes the two (the old equal-1.9s data did not).
    f = gridfit.fit_level([1.2, 1.9, 1.0], [0.0, 2.0, 4.0, 6.0], [(-1.0, 1.0)] * 3, 0.3)
    assert f.shifts == pytest.approx((0.3, 0.3, 0.0), abs=1e-9)
    assert f.devs == pytest.approx((0.5, 0.3), abs=1e-9)


def test_fit_leaves_the_tail_episode_alone():
    f = gridfit.fit_level([2.4], [0.0, 2.0, 4.0], [(-0.5, 0.5)], 0.5)
    assert f.shifts == (0.0,)
    assert f.devs == ()
    assert f.fits is True


def test_fit_clamps_to_the_allowance_and_reports_the_residual():
    # Cut wants +0.8 but the allowance is 0.3 → it moves 0.3 and stays 0.5 short.
    f = gridfit.fit_level([1.2, 1.0], [0.0, 2.0], [(-1.0, 1.0)] * 2, 0.3)
    assert f.shifts == pytest.approx((0.3, 0.0), abs=1e-9)
    assert f.devs == pytest.approx((0.5,), abs=1e-9)
    assert f.needs == pytest.approx((0.8,), abs=1e-9)
    assert f.fits is False


def test_fit_clamps_to_the_shot_s_room_before_the_allowance():
    # The allowance would permit +0.8, the shot only has +0.2 left.
    f = gridfit.fit_level([1.2, 1.0], [0.0, 2.0], [(-1.0, 0.2), (-1.0, 1.0)], 1.0)
    assert f.shifts == pytest.approx((0.2, 0.0), abs=1e-9)
    assert f.devs == pytest.approx((0.6,), abs=1e-9)


def test_fit_may_shorten_as_well_as_lengthen():
    f = gridfit.fit_level([2.3, 1.0], [0.0, 2.0], [(-0.5, 0.5)] * 2, 0.5)
    assert f.shifts == pytest.approx((-0.3, 0.0), abs=1e-9)
    assert f.fits is True


def test_fit_refuses_bounds_that_do_not_match_the_episodes():
    with pytest.raises(ValueError, match="bounds"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(-0.5, 0.5)], 0.5)


def test_fit_refuses_a_nonpositive_episode():
    with pytest.raises(ValueError, match="durs"):
        gridfit.fit_level([0.0, 1.0], [0.0, 2.0], [(-0.5, 0.5)] * 2, 0.5)


def test_fit_refuses_an_episode_shortened_out_of_existence():
    with pytest.raises(ValueError, match="bounds"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(-2.0, 0.5), (-0.5, 0.5)], 0.5)


def test_fit_refuses_an_empty_edit():
    with pytest.raises(ValueError, match="durs"):
        gridfit.fit_level([], [0.0, 2.0], [], 0.5)


def test_fit_refuses_an_empty_line_set():
    with pytest.raises(ValueError, match="lines"):
        gridfit.fit_level([1.0, 1.0], [], [(-0.5, 0.5)] * 2, 0.5)


def test_fit_refuses_bounds_whose_low_exceeds_its_high():
    with pytest.raises(ValueError, match="empty"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(0.5, -0.5), (-0.5, 0.5)], 0.5)


def test_fit_refuses_bounds_that_do_not_straddle_the_allowance():
    with pytest.raises(ValueError, match="does not overlap"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(0.5, 1.0), (-0.5, 0.5)], 0.288)


def test_fit_refuses_bounds_that_sit_entirely_below_the_allowance():
    with pytest.raises(ValueError, match="does not overlap"):
        gridfit.fit_level([10.0, 1.0], [0.0, 2.0], [(-1.0, -0.3), (-0.5, 0.5)], 0.288)


@pytest.mark.parametrize("bad", [0, -0.5, True, "0.3", None])
def test_fit_refuses_a_bad_allowance(bad):
    with pytest.raises(ValueError, match="allow must"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(-0.5, 0.5)] * 2, bad)


def _metronome(n, step=0.5):
    return [i * step for i in range(n)]


# _PINNED is "no room to move at all" expressed legally: fit_level refuses allow <= 0
# (it is a musical budget, and zero is not one), so a frozen edit is a pinned bound
# with a negligible allowance rather than a zero one.
_PINNED = 1e-6


def test_best_fit_prefers_the_coarsest_level_that_fits():
    # 2.0s episodes on a 0.5s beat: every level up to "bar" (4 beats = 2.0s) lands
    # exactly, so the coarsest fitting one wins over the finest.
    beats = _metronome(40)
    chosen, rejected = gridfit.best_fit([2.0] * 4, beats, [(-0.2, 0.2)] * 4, 0.25)
    assert chosen.level == "bar"
    assert chosen.fits is True
    assert [f.level for f in rejected] == ["phrase", "2-bar"]


def test_best_fit_falls_to_a_finer_level_and_names_what_it_rejected():
    beats = _metronome(40)
    chosen, rejected = gridfit.best_fit([1.0] * 4, beats, [(-0.1, 0.1)] * 4, 0.1)
    assert chosen.level == "half-bar"
    assert [f.level for f in rejected] == ["phrase", "2-bar", "bar"]
    assert all(f.fits is False for f in rejected)


def test_best_fit_returns_the_least_bad_when_nothing_fits():
    beats = _metronome(40)
    chosen, rejected = gridfit.best_fit([0.7, 0.7, 0.7], beats, [(0.0, 0.0)] * 3, _PINNED)
    assert chosen.fits is False
    assert chosen.worst == min(f.worst for f in rejected + (chosen,))


def test_best_fit_searches_every_phase_of_a_level():
    # Lines every 4th beat; the cut lands on beat index 1, so only phase 1 fits.
    beats = _metronome(40)
    chosen, _ = gridfit.best_fit([0.5, 0.5], beats, [(0.0, 0.0)] * 2, _PINNED,
                                 levels=(("bar", 4),))
    assert chosen.phase == 1
    assert chosen.fits is True


def test_best_fit_the_runs_own_reel_reaches_beat_but_not_phrase():
    """The 2026-07-24 run's real cut lengths (design §3): beat fits, coarser does not.
    The per-cut distances to the nearest phrase line are (0.204, 0.076, 0.076, 0.056,
    0.366) — three cuts near, the hook ~half a phrase off, and the last ride 0.366s past
    the 0.288s allowance is what rejects the level."""
    tempo = 104.16666666666667
    beat = 60.0 / tempo
    beats = [i * beat for i in range(120)]
    durs = [4.98, 9.14, 9.14, 9.16, 8.85, 8.73]
    allow = gridfit.allowance(tempo)
    chosen, rejected = gridfit.best_fit(durs, beats, [(-allow, allow)] * 6, allow)
    assert chosen.level == "beat"
    assert chosen.fits is True
    phrase = next(f for f in rejected if f.level == "phrase")
    assert phrase.fits is False
    assert max(phrase.needs) > allow
    assert phrase.needs == pytest.approx((0.204, 0.076, 0.076, 0.056, 0.366), abs=1e-3)


def test_best_fit_carries_the_level_and_phase_onto_the_returned_fit():
    beats = _metronome(40)
    chosen, _ = gridfit.best_fit([2.0] * 4, beats, [(-0.2, 0.2)] * 4, 0.25)
    assert (chosen.level, chosen.level_n) == ("bar", 4)
    assert 0 <= chosen.phase < chosen.level_n
    assert len(chosen.shifts) == 4


def test_best_fit_refuses_an_empty_level_table():
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1, levels=())


def test_best_fit_refuses_a_level_with_a_beats_per_line_below_one():
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1,
                         levels=(("bar", 0),))


def test_best_fit_refuses_a_bool_beats_per_line():
    # bool is a subclass of int: True == 1 would silently pass as beats-per-line=1.
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1,
                         levels=(("bar", True),))


def test_best_fit_refuses_a_malformed_level_entry():
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1,
                         levels=(("bar", 4, "extra"),))


@pytest.mark.parametrize("bad_name", ["", 123, None])
def test_best_fit_refuses_a_level_without_a_usable_name(bad_name):
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1,
                         levels=((bad_name, 4),))


def test_best_fit_refuses_a_level_table_that_does_not_ascend():
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1,
                         levels=(("2-bar", 8), ("bar", 4)))


def test_best_fit_keeps_the_first_phase_when_two_tie():
    # A cut at 0.75 sits 0.25 from BOTH half-bar grids (phase 0 -> ...0.0/1.0...,
    # phase 1 -> ...0.5/1.5...), so worst and total tie exactly. First phase wins,
    # which is what makes the search deterministic rather than merely stable-looking.
    beats = _metronome(40)
    chosen, _ = gridfit.best_fit([0.75, 1.0], beats, [(0.0, 0.0)] * 2, _PINNED,
                                 levels=(("half-bar", 2),))
    assert chosen.phase == 0
    assert chosen.fits is False


def test_best_fit_survives_a_grid_shorter_than_the_coarsest_stride():
    # 12 beats is fewer than the phrase level's 16-beat stride, so phases 12..15 yield
    # empty line slices. best_fit must SKIP those phases, not raise "got no lines" — a
    # short reel still fits at a finer level rather than crashing during the coarse sweep.
    # Three episodes (two cuts, at 1.0s and 2.0s): with <16 beats every phrase phase is a
    # lone beat, and no single line can satisfy two spread cuts — so phrase genuinely
    # fails here rather than fitting trivially the way one cut on the dense grid would.
    beats = [i * 0.5 for i in range(12)]      # 0.0 .. 5.5
    chosen, rejected = gridfit.best_fit([1.0, 1.0, 1.0], beats, [(-0.25, 0.25)] * 3, 0.25)
    assert chosen.fits is True
    assert chosen.level in ("beat", "half-bar", "bar")
    # phrase was still evaluated on its non-empty phases (0..11), just didn't win
    assert any(f.level == "phrase" for f in rejected)


# --- held episodes: the grid AUTHORS the length (design 2026-10-21 §2.2) ---------------

_BEATS_120 = [i * 0.5 for i in range(80)]          # a 120 BPM grid: allowance 0.25, beat 0.5
_BAR_120 = gridfit.lines_at(_BEATS_120, 4, 0)       # 0.0, 2.0, 4.0, ...


def _h(beats=None, lo=1 / 3, hi=8.0):
    return gridfit.Held(beats, lo, hi)


def _never(pos, run):
    raise AssertionError(f"the planner was asked at {pos} — an authored hold outranks it")


def test_a_run_of_planned_holds_lands_every_cut_on_a_detected_beat():
    calls = []

    def plan(pos, run):
        calls.append((pos, run))
        return 3                                    # 1.5 s: on a beat, never on a bar line

    durs = [2.0, 2.0, 2.0, 2.0, 2.0]
    held = [None, _h(), _h(), _h(), None]
    f = gridfit.fit_level(durs, _BAR_120, [(-0.25, 0.25)] * 5, 0.25,
                          beats=_BEATS_120, held=held, plan=plan)
    # video to 2.0; holds to 3.5 and 5.0 (beats inside the run); the run's last hold
    # chooses the level's line nearest 6.5 — 6.0 — so the cut back to footage is a bar
    assert f.shifts == pytest.approx((0.0, -0.5, -0.5, -1.0, 0.0), abs=1e-12)
    assert f.devs == (0.0, 0.0, 0.0, 0.0)
    assert f.needs == (0.0, 0.0, 0.0, 0.0)
    assert f.fits is True
    # `run` is the counts already USED in this run, and it resets at footage
    assert calls == [(2.0, ()), (3.5, (3,)), (5.0, (3, 3))]


def test_the_runs_last_hold_keeps_a_beat_and_its_deviation_when_no_line_is_in_range():
    lines = [0.0, 30.0]                              # no line within HOLD_ROOM of the hold
    f = gridfit.fit_level([2.0, 2.0, 2.0], lines, [(-0.25, 0.25)] * 3, 0.25,
                          beats=_BEATS_120, held=[_h(), _h(), None],
                          plan=lambda pos, run: 3)
    assert f.shifts == pytest.approx((-0.5, -0.5, 0.0), abs=1e-12)
    # inside the run the deviation is to the nearest BEAT; at the run's end to the
    # nearest LINE, so it counts against the level
    assert f.devs == pytest.approx((0.0, 3.0), abs=1e-12)
    assert f.fits is False


def test_the_runs_last_hold_falls_back_to_the_beat_nearest_its_target_not_the_target():
    # beats every 1.0 s against a 0.5 s period: the 3-beat target 1.5 is no beat, so the
    # fallback lands on a detected beat (1.0, the earlier of a tie), not on 1.5
    beats = [float(i) for i in range(20)]
    f = gridfit.fit_level([2.0, 2.0], [0.0, 19.0], [(-0.25, 0.25)] * 2, 0.25,
                          beats=beats, held=[_h(), None], plan=lambda pos, run: 3)
    assert f.shifts == pytest.approx((-1.0, 0.0), abs=1e-12)
    assert f.devs == pytest.approx((1.0,), abs=1e-12)        # to the line at 0.0


def test_a_run_of_holds_starts_counting_afresh_after_footage():
    calls = []

    def plan(pos, run):
        calls.append(run)
        return 2

    held = [_h(), _h(), None, _h(), _h(), None]
    gridfit.fit_level([2.0] * 6, _BEATS_120, [(-0.25, 0.25)] * 6, 0.25,
                      beats=_BEATS_120, held=held, plan=plan)
    assert calls == [(), (2,), (), (2,)]


def test_a_runs_last_hold_that_reaches_no_line_rejects_the_level():
    # a 60-beat level: every phase's next line after the video cut is 30 s on, far past
    # HOLD_ROOM — the run's last hold keeps a beat, misses, and the fit falls to the beat
    # level, as for any cut that cannot reach a line
    chosen, rejected = gridfit.best_fit([2.0, 2.0, 2.0], _BEATS_120, [(-0.25, 0.25)] * 3,
                                        0.25, levels=(("beat", 1), ("long", 60)),
                                        held=[None, _h(), None], plan=lambda pos, run: 2)
    assert (chosen.level, chosen.fits) == ("beat", True)
    assert [(f.level, f.fits) for f in rejected] == [("long", False)]
    assert rejected[0].devs[1] == rejected[0].worst > gridfit.FIT_EPS     # the hold's miss


def test_an_authored_hold_is_never_moved_to_a_line():
    durs, bounds = [2.0, 2.0, 2.0], [(-0.25, 0.25)] * 3
    authored = gridfit.fit_level(durs, _BAR_120, bounds, 0.25, beats=_BEATS_120,
                                 held=[None, _h(beats=3), None], plan=_never)
    planned = gridfit.fit_level(durs, _BAR_120, bounds, 0.25, beats=_BEATS_120,
                                held=[None, _h(), None], plan=lambda pos, run: 3)
    # both target 3.5; the planned one is pulled to the bar line at 4.0, the authored
    # one stays on its beat and its distance to the line counts against the level
    assert authored.shifts == pytest.approx((0.0, -0.5, 0.0), abs=1e-12)
    assert authored.devs == pytest.approx((0.0, 0.5), abs=1e-12)
    assert planned.shifts == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert planned.devs == (0.0, 0.0)


def test_a_held_tail_is_placed_on_a_beat_and_its_shift_is_not_forced_to_zero():
    f = gridfit.fit_level([2.0, 2.0], _BAR_120, [(-0.25, 0.25)] * 2, 0.25,
                          beats=_BEATS_120, held=[None, _h()], plan=lambda pos, run: 3)
    assert f.shifts == pytest.approx((0.0, -0.5), abs=1e-12)
    assert f.devs == (0.0,)          # the tail is the reel's end, not a cut


def test_the_count_a_run_records_is_the_one_actually_used():
    # beats every 1.0 s against a 0.5 s period (a half-time detection): a 3-beat target
    # at 1.5 ties between 1.0 and 2.0, the earlier wins, and that is 2 beats, not 3
    calls = []

    def plan(pos, run):
        calls.append((pos, run))
        return 3

    beats = [float(i) for i in range(20)]
    f = gridfit.fit_level([2.0, 2.0, 2.0], beats, [(-0.25, 0.25)] * 3, 0.25,
                          beats=beats, held=[_h(), _h(), _h()], plan=plan)
    assert calls[:2] == [(0.0, ()), (1.0, (2,))]
    assert f.shifts[0] == pytest.approx(-1.0)


def test_past_the_last_beat_the_target_itself_is_used_and_clamped_into_the_range():
    beats = [0.0]
    f = gridfit.fit_level([2.0], beats, [(0.0, 0.0)], 0.25, beats=beats,
                          held=[_h()], plan=lambda pos, run: 3)
    assert f.shifts == pytest.approx((-0.5,))                       # out at 1.5
    f = gridfit.fit_level([2.0], beats, [(0.0, 0.0)], 0.25, beats=beats,
                          held=[_h()], plan=lambda pos, run: 20)
    assert f.shifts == pytest.approx((6.0,))                        # 10.0 clamped to 8.0


def test_the_hold_range_is_inclusive_and_forgives_float_noise():
    # a 20-beat target at 10.0 s: the beat at exactly HOLD_ROOM (8.0) is in range...
    f = gridfit.fit_level([2.0], _BEATS_120, [(0.0, 0.0)], 0.25, beats=_BEATS_120,
                          held=[_h()], plan=lambda pos, run: 20)
    assert f.shifts == (6.0,)
    # ...and so is one a float hair past the range's end (the 1e-9 slack), not 7.5
    f = gridfit.fit_level([2.0], _BEATS_120, [(0.0, 0.0)], 0.25, beats=_BEATS_120,
                          held=[_h(hi=8.0 - 1e-12)], plan=lambda pos, run: 20)
    assert f.shifts == (6.0,)


def test_an_all_footage_held_list_fits_exactly_as_no_held_list():
    durs, bounds = [1.2, 1.9, 1.0], [(-1.0, 1.0)] * 3
    lines = [0.0, 2.0, 4.0, 6.0]
    assert (gridfit.fit_level(durs, lines, bounds, 0.3, beats=lines, held=[None] * 3,
                              plan=_never)
            == gridfit.fit_level(durs, lines, bounds, 0.3))


def test_a_held_episodes_bounds_are_never_read():
    # (5.0, 6.0) does not straddle the allowance — a caller bug on footage, never read
    # on a held episode, so not refused there
    f = gridfit.fit_level([2.0, 2.0, 2.0], _BAR_120, [(-0.25, 0.25), (5.0, 6.0), (0.0, 0.0)],
                          0.25, beats=_BEATS_120, held=[None, _h(), None],
                          plan=lambda pos, run: 4)
    assert f.fits is True
    with pytest.raises(ValueError, match="does not overlap"):
        gridfit.fit_level([2.0, 2.0, 2.0], _BAR_120,
                          [(-0.25, 0.25), (5.0, 6.0), (0.0, 0.0)], 0.25)


def test_best_fit_passes_the_beats_and_the_held_walk_through():
    # inside the run the hold lands on 3.0, a detected beat no bar line passes through,
    # and the run's last hold reaches the bar line at 4.0 — so bar fits
    chosen, _ = gridfit.best_fit([2.0, 2.0, 2.0, 2.0], _BEATS_120, [(-0.25, 0.25)] * 4,
                                 0.25, levels=(("beat", 1), ("bar", 4)),
                                 held=[None, _h(), _h(), None], plan=lambda pos, run: 2)
    assert (chosen.level, chosen.phase, chosen.fits) == ("bar", 0, True)
    assert chosen.shifts == pytest.approx((0.0, -1.0, -1.0, 0.0), abs=1e-12)


@pytest.mark.parametrize("kw, match", [
    (dict(held=[_h()]), "one entry per episode"),
    (dict(held=[None, _h()], plan=None), "plan"),
    (dict(held=[None, _h()], plan=3), "plan"),
    (dict(held=[None, _h()], beats=()), "beats"),
    (dict(held=[None, (1, 0.3, 8.0)]), "Held or None"),
    (dict(plan=lambda pos, run: 2), "without `held`"),
])
def test_fit_level_refuses_a_malformed_held_walk(kw, match):
    args = dict(beats=_BEATS_120, plan=lambda pos, run: 2, held=None)
    args.update(kw)
    with pytest.raises(ValueError, match=match):
        gridfit.fit_level([2.0, 2.0], _BAR_120, [(-0.25, 0.25)] * 2, 0.25, **args)


@pytest.mark.parametrize("bad", [0, -1, 2.0, True, None])
def test_fit_level_refuses_a_planner_that_returns_no_count(bad):
    if bad is None:
        bad = "4"
    with pytest.raises(ValueError, match="plan returned"):
        gridfit.fit_level([2.0, 2.0], _BAR_120, [(-0.25, 0.25)] * 2, 0.25,
                          beats=_BEATS_120, held=[_h(), None], plan=lambda pos, run: bad)


@pytest.mark.parametrize("kw, match", [
    (dict(beats=0), "beats"), (dict(beats=True), "beats"), (dict(beats=2.0), "beats"),
    (dict(lo=0.0), "lo"), (dict(lo=True), "lo"), (dict(lo=3.0, hi=2.0), "lo"),
    (dict(hi="8"), "hi"),
])
def test_held_refuses_a_bad_record(kw, match):
    args = dict(beats=None, lo=1 / 3, hi=8.0)
    args.update(kw)
    with pytest.raises(ValueError, match=match):
        gridfit.Held(**args)
