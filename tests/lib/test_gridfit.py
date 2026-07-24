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
    # Three 1.9s episodes against 2.0s lines. Cut 0 wants +0.1; if each duration were
    # snapped independently cut 1 would want +0.1 too — but after cut 0 moved, cut 1
    # already sits at 3.8+0.1=3.9 and needs only +0.1 to reach 4.0. The third episode
    # is the tail: nothing follows it, so it never moves.
    f = gridfit.fit_level([1.9, 1.9, 1.9], [0.0, 2.0, 4.0, 6.0],
                          [(-0.5, 0.5)] * 3, 0.5)
    assert f.shifts == pytest.approx((0.1, 0.1, 0.0), abs=1e-9)
    assert f.worst == pytest.approx(0.0, abs=1e-9)
    assert f.fits is True


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
