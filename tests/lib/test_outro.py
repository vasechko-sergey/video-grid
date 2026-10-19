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
                           rung="gap", moved=pytest.approx(line + 0.5 - 34.044),
                           need=pytest.approx(0.5 + outro.TAIL_MARGIN))


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
                           rung="unchanged", moved=0.0, cause="no-bars")


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


def test_fade_zero_needs_only_the_margin():
    """A brief with no look leaves fade at mix's default, but an authored fade of 0 is
    legal: the reel then ends exactly on the line and TAIL_MARGIN alone is the bar."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.6),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.reel_dur == line and fit.fade == 0.0


def test_gap_rung_tail_exactly_at_the_epsilon_floor_still_counts():
    """Task 7 battery row 1 — coverage hole closed: the named
    test_gap_rung_picks_the_line_with_room_for_the_fade uses a 1.5s tail against a
    0.5s need, nowhere near the `>=`/`>` boundary, so flipping the tail filter's `>=`
    to `>` left EVERY test in this file green. The `- _EPS` slop on that comparison
    means an ordinary decimal tie (tail == need, e.g. both 0.5) passes under EITHER
    operator — `need > need - _EPS` always — so only a tail landing bit-exactly on
    `need - _EPS` tells `>=` apart from `>`. Constructed the SAME way the source
    computes it (line=0.0 so `b - t` has no float cancellation), not a coincidence.

    Re-pointed 2026-08-18: the need is `fade + TAIL_MARGIN` now, so the tie has to be
    built from THAT sum. Left at a bare 0.5 the tail sits 0.05 BELOW the need, the gap
    rung refuses for an ordinary reason, and the row stops testing the operator at
    all — the plan's own self-review caught this before the battery could."""
    need = 0.5 + outro.TAIL_MARGIN
    tail = need - outro._EPS
    fit = outro.fit_outro((0.0,), ((0.0, tail),), reel_dur=0.5, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap"


def test_gap_rung_needs_the_margin_on_top_of_the_fade():
    """Rewritten from test_gap_rung_needs_tail_min_not_just_the_fade (design §1.5): its
    JOB is unchanged — tell the real rule apart from a bare `need = fade` — only the
    scale moved. test_fade_zero_needs_only_the_margin's 0.6s tail clears both, so it
    cannot discriminate; 0.02s of vocal-free space clears fade=0.0 and not the 0.05s
    margin, so only the real floor refuses the gap rung here."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.02),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "no-gap"


def test_the_margin_is_all_a_zero_fade_needs():
    """The companion that stops the margin being mistaken for the old 0.5s floor:
    0.06s of vocal-free space clears it. Under TAIL_MIN=0.5 this same call answered
    'no-gap' — the pair brackets the constant from both sides."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.06),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.reel_dur == line


def test_a_short_fade_inside_a_short_gap_takes_the_gap_rung():
    """design §1.3, the measured inversion, pinned as a regression. One bar line with
    0.35s of vocal-free space after it — the SHORTEST gap offset.vocal_gaps can emit
    (min_gap=0.35) — and the `fun` preset's 0.3s fade. The played tail is
    [line, line+0.3], entirely inside the gap, so the gap rung must take it.

    Under `max(TAIL_MIN, fade)` this fell to no-gap and shipped a 1.50s fade over
    1.15s of singing: the floor made the outcome worse against the very thing it
    protected, because the no-gap rung checks no tail at all."""
    line = 30.0
    fit = outro.fit_outro((line,), ((line, line + 0.35),), reel_dur=30.2, bar_s=BAR,
                          fade=0.3, music_dur=60.0, grow_max=5.0, shrink_max=5.0)
    assert fit.rung == "gap"
    assert fit.fade == 0.3
    assert fit.reel_dur == pytest.approx(line + 0.3)
    assert fit.tail >= fit.fade      # nothing sings under the fade


def test_the_fit_records_the_requirement_it_applied():
    """A bare tail cannot say what it was measured against, and the requirement is no
    longer a module constant a reader can look up: it depends on the fade (design
    §1.6)."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 3.0),), reel_dur=20.3, bar_s=BAR,
                          fade=0.8, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.need == pytest.approx(0.85)


def test_the_no_gap_rung_records_the_requirement_that_refused_it():
    """On no-gap `fade` is already NO_GAP_FADE, so without `need` nothing in the
    artifact can say how much space the gap rung wanted. It is the ORIGINAL fade's
    requirement (0.3 + 0.05), not the long fade's."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.02),), reel_dur=20.3, bar_s=BAR,
                          fade=0.3, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "no-gap"
    assert fit.fade == outro.NO_GAP_FADE
    assert fit.need == pytest.approx(0.35)


def test_need_round_trips_and_an_old_artifact_still_loads():
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 3.0),), reel_dur=20.3, bar_s=BAR,
                          fade=0.8, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert outro.OutroFit.from_dict(fit.to_dict()) == fit
    old = {"reel_dur": 30.0, "line": 29.5, "fade": 0.5, "tail": 1.0, "rung": "gap",
           "moved": 0.0}                       # written before this slice: no `need`
    assert outro.OutroFit.from_dict(old).need == 0.0


def test_the_margin_is_two_bins_of_the_vocal_envelope():
    """TAIL_MARGIN is not taste — it is the boundary quantization of the sensor that
    produces the spans it is compared against (design §1.5). vocals._SPAN_HZ is 40 Hz,
    so two bins is 0.05s. outro.py must NOT import vocals (its docstring promises no
    audio IO), so the derivation lives here, machine-checked, instead of in a comment
    that could go stale."""
    from scripts.lib import vocals
    assert outro.TAIL_MARGIN == pytest.approx(2.0 / vocals._SPAN_HZ)
    assert not hasattr(outro, "TAIL_MIN"), "TAIL_MIN is deleted, not renamed in place"


def test_the_earlier_line_wins_an_exact_tie():
    """pick()'s secondary tie-break (design §5's "then toward the earlier line") had
    no test: the 18-bar BARS fixture never produces an exact numeric tie. Two lines
    equidistant from reel_dur, no brief -> the earlier one wins."""
    spans = ((9.0, 10.0), (11.0, 12.0))
    fit = outro.fit_outro((9.0, 11.0), spans, reel_dur=10.5, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.line == 9.0


def test_fit_round_trips():
    fit = OutroFit(reel_dur=35.7, line=35.2, fade=0.5, tail=1.5, rung="gap", moved=1.7)
    assert OutroFit.from_dict(fit.to_dict()) == fit


def test_fit_round_trips_the_brief_length():
    """brief_len rides the carrier so EDL.md can state the distance from SPEC.length_s
    (design §6/§7; final review I-3). It must survive to_dict/from_dict like every
    other field, not be recomputed by a reader who no longer has the brief."""
    fit = OutroFit(reel_dur=35.7, line=35.2, fade=0.5, tail=1.5, rung="gap",
                   moved=1.7, brief_len=30.0)
    assert fit.to_dict()["brief_len"] == 30.0
    assert OutroFit.from_dict(fit.to_dict()) == fit


def test_a_pre_brief_len_artifact_still_loads():
    """An EDL.json written before this field existed carries no `brief_len` key; it
    reads as "no brief", never as 0.0 (which would render as a false distance)."""
    assert OutroFit.from_dict({"reel_dur": 35.7, "line": 35.2, "fade": 0.5,
                               "tail": 1.5, "rung": "gap", "moved": 1.7}).brief_len is None


@pytest.mark.parametrize("bars, spans, want_rung", [
    ((35.188,), ((35.188, 36.7),), "gap"),      # rung 1: a line with room for the fade
    ((), (), "unchanged"),                      # rung 3: no grid at all
])
def test_every_rung_carries_the_brief_length_it_was_given(bars, spans, want_rung):
    """All three rungs, not just the one that moved: the distance from the brief is
    exactly as worth reporting when NOTHING could be fitted."""
    fit = outro.fit_outro(bars, spans, reel_dur=34.044, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=11.5, shrink_max=3.0, brief_len=30.0)
    assert fit.rung == want_rung and fit.brief_len == 30.0


def test_the_no_gap_rung_carries_the_brief_length_too():
    fit = outro.fit_outro(BARS, (), reel_dur=34.044, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=11.5, shrink_max=3.0, brief_len=30.0)
    assert fit.rung == "no-gap" and fit.brief_len == 30.0


def test_negative_fade_is_refused():
    with pytest.raises(ValueError, match="fade must be"):
        outro.fit_outro(BARS, (), reel_dur=34.0, bar_s=BAR, fade=-1.0, music_dur=42.0,
                        grow_max=1.0, shrink_max=1.0)


def test_non_positive_bar_is_refused():
    with pytest.raises(ValueError, match="bar_s must be"):
        outro.fit_outro(BARS, (), reel_dur=34.0, bar_s=0.0, fade=0.5, music_dur=42.0,
                        grow_max=1.0, shrink_max=1.0)


# --- final review Finding 2: reel_dur required when rung != "unchanged" ---------------

@pytest.mark.parametrize("bad", [0.0, -1.0, None, "10.7", True])
def test_reel_dur_must_be_a_positive_number_when_the_rung_chose_a_length(bad):
    with pytest.raises(ValueError, match="reel_dur must be a positive number"):
        OutroFit(reel_dur=bad, line=10.0, fade=0.5, tail=1.0, rung="gap", moved=0.0)


def test_reel_dur_is_unconstrained_for_an_unchanged_rung():
    # "unchanged" carries no promise about reel_dur; check_reel's own branch for it
    # never reads the key, so 0.0 (from_dict's default) stays legitimate here.
    OutroFit(reel_dur=0.0, line=None, fade=0.5, tail=0.0, rung="unchanged", moved=0.0)


def test_from_dict_refuses_a_gap_rung_missing_reel_dur():
    # The exact malformed shape from the final review: {"rung": "gap"} used to
    # round-trip clean through OutroFit.from_dict (reel_dur silently defaulted to
    # 0.0) and only crashed three stages later, inside check_reel, with a bare
    # KeyError on outro["reel_dur"] — a fail-loud contract violation. Refusing it
    # HERE, at the shape/rung oracle ReelManifest already calls, is what closes
    # that gap instead of moving it.
    with pytest.raises(ValueError, match="reel_dur must be a positive number"):
        OutroFit.from_dict({"rung": "gap"})


def test_no_bars_and_no_reachable_line_are_different_causes():
    """Both return rung 'unchanged'; until 2026-09-07 the two records were
    byte-identical, and check_reel asserted "the fit chose no bar line" for runs
    where no fit ever ran (design §0.1)."""
    no_bars = outro.fit_outro([], [], reel_dur=10.0, bar_s=2.0, fade=0.3,
                              music_dur=30.0, grow_max=1.0, shrink_max=1.0)
    assert (no_bars.rung, no_bars.cause) == ("unchanged", "no-bars")
    # bars exist but every one is more than a bar away from the cut's length, so the
    # ladder runs and the +/- one-bar band rejects all of them.
    unreachable = outro.fit_outro([40.0, 42.0], [], reel_dur=10.0, bar_s=2.0, fade=0.3,
                                  music_dur=60.0, grow_max=1.0, shrink_max=1.0)
    assert (unreachable.rung, unreachable.cause) == ("unchanged", "no-reachable-line")


def test_a_successful_fit_carries_no_cause():
    """A fit that chose a bar line has no absence to name."""
    fit = outro.fit_outro([9.7], [(0.0, 5.0), (9.0, 20.0)], reel_dur=10.0, bar_s=2.0,
                          fade=0.3, music_dur=30.0, grow_max=1.0, shrink_max=1.0)
    assert fit.rung == "gap" and fit.cause == ""


def test_a_cause_beside_a_chosen_rung_is_refused():
    with pytest.raises(ValueError, match="must be '' when rung is"):
        outro.OutroFit(reel_dur=10.0, line=9.7, fade=0.3, tail=1.0, rung="gap",
                       moved=0.0, cause="no-bars")


def test_an_unknown_cause_is_refused():
    with pytest.raises(ValueError, match="OutroFit.cause must be one of"):
        outro.OutroFit(reel_dur=10.0, line=None, fade=0.3, tail=0.0, rung="unchanged",
                       moved=0.0, cause="because")


def test_an_edl_written_before_this_slice_loads_with_no_cause():
    """'' is not-recorded, never 'no reason'. Pre-2026-09-07 EDL.json must load."""
    fit = outro.OutroFit.from_dict({"reel_dur": 34.93, "line": None, "fade": 0.3,
                                    "tail": 0.0, "rung": "unchanged", "moved": 0.0,
                                    "brief_len": 45.0, "need": 0.0})
    assert fit.cause == ""


def test_the_cause_round_trips():
    fit = outro.OutroFit(reel_dur=10.0, line=None, fade=0.3, tail=0.0,
                         rung="unchanged", moved=0.0, cause="ramped-closer")
    assert outro.OutroFit.from_dict(fit.to_dict()) == fit
    assert fit.to_dict()["cause"] == "ramped-closer"


def test_every_cause_has_a_clause_and_so_does_the_unrecorded_one():
    """Both readers (check_reel's outro reason, EDL.md's outro section) print from
    CAUSE_WHY. A cause with no clause would render as a KeyError or a blank."""
    assert set(outro.CAUSE_WHY) == set(outro.CAUSES) | {""}
    assert all(v.strip() for v in outro.CAUSE_WHY.values())
    # edl.py APPENDS ", so the reel keeps its footage-derived length and the music ends
    # mid-phrase" to whichever of these renders standalone (its own docstring says so).
    # A clause that itself ends in ", so ..." reproduces "...so no fit ever ran, so the
    # reel keeps..." with this whole suite green — a reviewer-found defect (final
    # review M-3) that only a check on the table itself, not on any one rendering,
    # catches. All six current values satisfy it.
    assert not any(", so " in v for v in outro.CAUSE_WHY.values())


def test_a_fitted_record_without_its_fade_is_refused_not_defaulted_to_a_dead_cut():
    """retro 2026-10-16 S18: build_reel closes the music on a fitted rung's fade, so a
    hand-written {"rung": "gap", ...} with no fade must fail at load, not KeyError after
    the whole picture loop — and must not quietly become a 0.0 fade either."""
    with pytest.raises(ValueError, match="'fade'"):
        OutroFit.from_dict({"rung": "gap", "reel_dur": 6.0, "line": 4.5})
    assert OutroFit.from_dict({"rung": "unchanged"}).fade == 0.0   # nothing reads it there


# --- retro 2026-10-16 S7: no bar grid falls back to the beat grid ---------------------
# By the second run's agent's count 6 of 32 calm candidates carried a bar grid; the
# chosen track had none, the fit stayed "unchanged", and the reel cut the song
# mid-phrase under a 0.8 s fade. Three reviews flagged it; the operator swapped tracks.

def test_a_beat_grid_fit_lands_on_a_beat_under_the_longer_fade():
    beats = tuple(round(0.5 * k, 3) for k in range(0, 100))   # 120 BPM
    fit = outro.fit_outro(beats, ((0.0, 9.6),), 10.0, outro.bar_seconds(120.0), 0.8,
                          music_dur=40.0, grow_max=3.0, shrink_max=3.0, grid="beat")
    assert fit.grid == "beat" and fit.rung == "gap"
    assert fit.fade == outro.NO_GAP_FADE                    # a beat is not a phrase end
    assert fit.line in beats and fit.reel_dur == pytest.approx(fit.line + outro.NO_GAP_FADE)


def test_the_grid_rides_the_record_only_when_it_is_the_beat():
    bar = OutroFit(reel_dur=6.0, line=4.5, fade=0.5, tail=1.0, rung="gap", moved=0.3)
    assert "grid" not in bar.to_dict() and bar.grid == "bar"
    beat = OutroFit(reel_dur=6.0, line=4.5, fade=1.5, tail=1.0, rung="gap", moved=0.3,
                    grid="beat")
    assert beat.to_dict()["grid"] == "beat" and OutroFit.from_dict(beat.to_dict()) == beat
    with pytest.raises(ValueError, match="grid"):
        OutroFit(reel_dur=6.0, line=4.5, fade=1.5, tail=1.0, rung="gap", moved=0.3,
                 grid="phrase")



def test_a_falsy_grid_is_refused_not_read_as_bar():
    with pytest.raises(ValueError, match="grid"):
        OutroFit.from_dict({"reel_dur": 6.0, "line": 4.5, "fade": 1.5, "rung": "gap",
                            "grid": ""})
