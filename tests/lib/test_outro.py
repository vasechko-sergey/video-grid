"""outro.py — the pure outro fit (design docs/specs/2026-08-14-music-outro-fit-design.md)."""
import pytest

from scripts.lib import outro
from scripts.lib.outro import OutroFit

# a 110.294 BPM grid, the 2026-08-03 run's own: bar = 2.176s
BAR = 2.176
BARS = tuple(round(2.548 + i * BAR, 3) for i in range(18))     # 2.548 .. 39.54


def test_bar_seconds_is_four_beats():
    assert outro.bar_seconds(120.0) == pytest.approx(2.0)


def test_window_spans_offsets_and_clips():
    assert outro.window_spans(((3.0, 4.0), (19.0, 30.0)), 12.0, 10.0) == ((7.0, 10.0),)


def test_window_spans_drops_an_empty_intersection():
    assert outro.window_spans(((0.0, 1.0),), 12.0, 10.0) == ()


def test_free_after_inside_a_span():
    assert outro.free_after(((10.0, 12.0),), 10.5) == pytest.approx(1.5)


def test_free_after_outside_every_span_is_zero():
    assert outro.free_after(((10.0, 12.0),), 9.0) == 0.0


def test_gap_rung_picks_the_line_with_room_for_the_fade():
    """The 2026-08-03 case: the reel ends 0.956s past a bar line; the next line up has
    1.50s of vocal-free after it, so the reel grows to line + fade."""
    line = BARS[15]                                    # 35.188 on this synthetic grid
    fit = outro.fit_outro(BARS, ((line, line + 1.5),), reel_dur=34.044, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=11.5, shrink_max=3.0)
    assert fit == OutroFit(reel_dur=line + 0.5, line=line, fade=0.5, tail=1.5,
                           rung="gap", moved=pytest.approx(line + 0.5 - 34.044))


def test_no_gap_rung_lengthens_the_fade():
    """No line leaves room: fall to the nearest line with NO_GAP_FADE, and say so."""
    fit = outro.fit_outro(BARS, (), reel_dur=34.044, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=11.5, shrink_max=3.0)
    assert fit.rung == "no-gap"
    assert fit.fade == outro.NO_GAP_FADE
    assert fit.reel_dur == pytest.approx(fit.line + outro.NO_GAP_FADE)
    assert fit.tail == 0.0


def test_no_gap_re_filters_the_band_with_its_own_fade():
    """The longer fade must not smuggle length past the band. With bar_s tight enough
    that line + NO_GAP_FADE leaves it, the answer is 'unchanged', not 'no-gap'."""
    fit = outro.fit_outro((10.0,), (), reel_dur=10.0, bar_s=0.6, fade=0.5,
                          music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "unchanged" and fit.line is None and fit.reel_dur == 10.0


def test_unchanged_when_no_bars():
    fit = outro.fit_outro((), ((0.0, 5.0),), reel_dur=34.044, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=11.5, shrink_max=3.0)
    assert fit == OutroFit(reel_dur=34.044, line=None, fade=0.5, tail=0.0,
                           rung="unchanged", moved=0.0)


def test_the_music_window_bounds_the_candidates():
    """mix refuses dur > music.duration + 0.1; the fitter must reject the candidate
    instead of letting it crash three stages later."""
    fit = outro.fit_outro((35.0,), ((35.0, 40.0),), reel_dur=34.5, bar_s=BAR, fade=0.5,
                          music_dur=35.2, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "unchanged"


def test_grow_max_bounds_the_extension():
    line = 35.0
    fit = outro.fit_outro((line,), ((line, line + 2.0),), reel_dur=34.0, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=0.2, shrink_max=99.0)
    assert fit.rung == "unchanged"


def test_shrink_max_bounds_the_shortening():
    """Without it a one-bar step down can leave a 2.5s closing shot at 0.3s.

    The line is placed so that BOTH rungs are blocked by shrink_max alone and by
    nothing else: at fade 0.5 the move is -1.50s and at NO_GAP_FADE it is -0.50s, both
    inside the +/-2.176s band, both past the 0.2s the closing shot can give up. The
    tail is 2.0s, so the gap rung would otherwise accept it — shrink_max is the only
    thing saying no, which is what this test is for."""
    line = 32.5
    fit = outro.fit_outro((line,), ((line, line + 2.0),), reel_dur=34.5, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=99.0, shrink_max=0.2)
    assert fit.rung == "unchanged"


def test_shortening_is_searched_too():
    line = 33.0
    fit = outro.fit_outro((line,), ((line, line + 2.0),), reel_dur=34.5, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.moved == pytest.approx(33.5 - 34.5)


def test_the_brief_breaks_the_tie():
    """Two qualifying lines, one either side. Without a brief the smaller move wins;
    with a brief the one closer to SPEC.length_s does."""
    spans = ((32.0, 34.0), (36.0, 38.0))
    kw = dict(bars=(32.0, 36.0), vocal_spans=spans, reel_dur=34.4, bar_s=BAR, fade=0.5,
              music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert outro.fit_outro(**kw).line == 32.0                  # |32.5-34.4| < |36.5-34.4|
    assert outro.fit_outro(**kw, brief_len=36.0).line == 36.0   # |36.5-36| < |32.5-36|


def test_fade_zero_needs_only_tail_min():
    """A brief with no look leaves fade at mix's default, but an authored fade of 0 is
    legal: the reel then ends exactly on the line and TAIL_MIN alone is the bar."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.6),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.reel_dur == line and fit.fade == 0.0


def test_fit_round_trips():
    fit = OutroFit(reel_dur=35.7, line=35.2, fade=0.5, tail=1.5, rung="gap", moved=1.7)
    assert OutroFit.from_dict(fit.to_dict()) == fit


def test_negative_fade_is_refused():
    with pytest.raises(ValueError, match="fade must be"):
        outro.fit_outro(BARS, (), reel_dur=34.0, bar_s=BAR, fade=-1.0, music_dur=42.0,
                        grow_max=1.0, shrink_max=1.0)


def test_non_positive_bar_is_refused():
    with pytest.raises(ValueError, match="bar_s must be"):
        outro.fit_outro(BARS, (), reel_dur=34.0, bar_s=0.0, fade=0.5, music_dur=42.0,
                        grow_max=1.0, shrink_max=1.0)
