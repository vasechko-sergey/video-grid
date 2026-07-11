import numpy as np

from scripts import beats


def test_downsample_bins_and_energy_hz():
    rms = np.arange(10, dtype=float)                          # frame_hz=10 → target 2 → step 5 → 2 bins
    energy, hz = beats._downsample(rms, sr=1000, hop=100, target_hz=2.0)
    assert energy == [2.0, 7.0] and abs(hz - 2.0) < 1e-9


def test_downsample_short_array_single_bin():
    energy, hz = beats._downsample(np.array([1.0, 3.0]), sr=1000, hop=100, target_hz=2.0)  # step 5 > len → 1 bin
    assert energy == [2.0] and hz > 0


def test_downsample_empty_array_no_crash():
    energy, hz = beats._downsample(np.array([], dtype=float), sr=1000, hop=100, target_hz=2.0)
    assert energy == [] and hz > 0
