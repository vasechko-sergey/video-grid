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
