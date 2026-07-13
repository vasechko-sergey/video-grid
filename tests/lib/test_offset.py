import numpy as np

from scripts.lib import offset


def test_downsample_bins_and_energy_hz():
    rms = np.arange(10, dtype=float)                          # frame_hz=10 → target 2 → step 5 → 2 bins
    energy, hz = offset.downsample(rms, sr=1000, hop=100, target_hz=2.0)
    assert energy == [2.0, 7.0] and abs(hz - 2.0) < 1e-9


def test_downsample_short_array_single_bin():
    energy, hz = offset.downsample(np.array([1.0, 3.0]), sr=1000, hop=100, target_hz=2.0)  # step 5 > len → 1 bin
    assert energy == [2.0] and hz > 0


def test_downsample_empty_array_no_crash():
    energy, hz = offset.downsample(np.array([], dtype=float), sr=1000, hop=100, target_hz=2.0)
    assert energy == [] and hz > 0


def test_vocal_gaps_finds_the_quiet_span():
    # hz=2 → each sample = 0.5s. Loud, loud, then 4 quiet samples (2.0s ≥ min_gap), loud.
    env = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    assert offset.vocal_gaps(env, hz=2.0) == ((1.0, 3.0),)   # samples 2..5 → [1.0s, 3.0s)


def test_vocal_gaps_drops_a_sub_min_gap_dip():
    # at hz=10 one below-thresh sample = 0.1s < min_gap 0.35 → a between-words dip, dropped
    assert offset.vocal_gaps([1.0, 0.0, 1.0], hz=10.0) == ()


def test_vocal_gaps_all_loud_returns_empty():
    assert offset.vocal_gaps([1.0, 1.0, 1.0], hz=2.0) == ()


def test_vocal_gaps_all_zero_is_one_full_span():
    assert offset.vocal_gaps([0.0, 0.0, 0.0, 0.0], hz=2.0) == ((0.0, 2.0),)


def test_vocal_gaps_relative_threshold_scales():
    # a quiet master (peak 0.02) still yields the gap — relative bar, not absolute
    env = [0.02, 0.02, 0.0, 0.0, 0.0, 0.0, 0.02]
    assert offset.vocal_gaps(env, hz=2.0) == ((1.0, 3.0),)


def test_vocal_gaps_empty_envelope():
    assert offset.vocal_gaps([], hz=2.0) == ()


def test_best_offset_track_shorter_than_reel():
    assert offset.best_offset([1.0, 2.0], mix_hz=2.0, gaps=(), duration=5.0, track_dur=1.0) == 0.0


def test_best_offset_picks_gap_start_over_raw_peak():
    # mix_hz=2 → 8 samples = 4s. Peak energy in samples 2..5 (t=1.0..3.0). duration=2s
    # (4 samples), latest = 4-2 = 2.0s. A gap starts at t=1.0 → window [1.0,3.0] = the peak.
    mix = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((1.0, 1.5),),
                              duration=2.0, track_dur=4.0) == 1.0


def test_best_offset_drops_a_gap_that_starts_too_late():
    # gap starts at 3.0s but latest usable start is 2.0s → dropped → argmax fallback picks 1.0s
    mix = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((3.0, 3.5),),
                              duration=2.0, track_dur=4.0) == 1.0


def test_best_offset_no_gaps_falls_back_to_argmax():
    mix = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=(),
                              duration=2.0, track_dur=4.0) == 1.0


def test_best_offset_chooses_the_louder_of_two_gap_windows():
    # two gaps: one leads into quiet, one leads into the loud region → pick the loud one
    mix = [1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0]          # loud in the second half
    # gaps at t=0.0 (window [0,2] quiet) and t=1.5 (window [1.5,3.5] catches the loud tail)
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((0.0, 0.5), (1.5, 2.0)),
                              duration=2.0, track_dur=4.0) == 1.5


def test_best_offset_never_exceeds_latest_on_argmax_fallback():
    # regression for the round()-overshoot bug: a fractional latest*mix_hz must not push
    # the argmax grid past track_dur - duration (that would crash mix.py's duration guard)
    mix = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]   # rising → rightmost window wins
    off = offset.best_offset(mix, mix_hz=2.0, gaps=(), duration=2.0, track_dur=4.3)
    assert off <= 4.3 - 2.0 + 1e-9                        # was 2.5 (> 2.3) before the fix


def test_vocal_gaps_keeps_a_run_exactly_min_gap_long():
    env = [1.0] + [0.0] * 7 + [1.0]                      # 7 samples / 20 Hz = 0.35s == min_gap
    assert offset.vocal_gaps(env, hz=20.0) == ((0.05, 0.40),)


def test_best_offset_keeps_a_gap_starting_exactly_at_latest():
    # loud FIRST half → the global argmax window is at start 0.0. If the boundary
    # candidate (gap start == latest) were dropped (a <=→< mutation) it would fall to
    # argmax and return 0.0. Asserting 2.0 pins that the exactly-at-latest gap is KEPT.
    mix = [9.0, 9.0, 9.0, 9.0, 1.0, 1.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((2.0, 2.5),),
                              duration=2.0, track_dur=4.0) == 2.0


def test_best_offset_clamps_a_gap_start_within_epsilon_slack():
    # a gap starting a hair past latest (inside the 1e-9 filter slack) is kept, but the
    # returned offset must be clamped to latest so it never overruns track_dur - duration.
    off = offset.best_offset([9.0, 9.0, 9.0, 9.0, 1.0, 1.0, 1.0, 1.0], mix_hz=2.0,
                             gaps=((2.0 + 1e-10, 2.5),), duration=2.0, track_dur=4.0)
    assert off == 2.0                                     # clamped down from 2.0000000001
