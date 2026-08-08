"""The colour-naturalness sensor (design docs/specs/2026-08-08-episode-qc-design.md §5)."""
import numpy as np
import pytest

from scripts.lib import naturalness


def _flat(r, g, b, h=64, w=64):
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[:, :, 0], f[:, :, 1], f[:, :, 2] = r, g, b
    return f


def test_a_neutral_mid_grey_frame_reads_clean():
    stats = naturalness.measure([_flat(118, 120, 122)])
    flags = naturalness.evaluate(stats)
    assert stats["cast"] < 0.02
    assert flags["blown_highlights"] is False and flags["crushed_blacks"] is False
    assert flags["colour_cast"] is False and flags["oversaturated"] is False


def test_a_red_frame_reads_as_a_cast_and_oversaturated():
    flags = naturalness.evaluate(naturalness.measure([_flat(220, 40, 40)]))
    assert flags["colour_cast"] is True
    assert flags["oversaturated"] is True


def test_white_pixels_read_as_blown_and_black_ones_as_crushed():
    blown = np.concatenate([_flat(255, 255, 255, h=16), _flat(120, 120, 120, h=48)])
    crushed = np.concatenate([_flat(0, 0, 0, h=16), _flat(120, 120, 120, h=48)])
    assert naturalness.evaluate(naturalness.measure([blown]))["blown_highlights"] is True
    assert naturalness.evaluate(naturalness.measure([crushed]))["crushed_blacks"] is True


def test_a_single_tone_frame_reads_flat_and_a_full_ramp_does_not():
    flat = naturalness.measure([_flat(120, 120, 120)])
    ramp = np.repeat(np.arange(256, dtype=np.uint8).reshape(1, 256, 1), 3, axis=2)
    ramp = np.repeat(ramp, 64, axis=0)
    assert naturalness.evaluate(flat)["flat"] is True
    assert naturalness.evaluate(naturalness.measure([ramp]))["flat"] is False


def test_frames_are_averaged_not_concatenated():
    """Two frames, one blown and one clean: the reported fraction is their MEAN, so a
    single bad frame in a long episode does not read as a blown episode."""
    stats = naturalness.measure([_flat(255, 255, 255), _flat(120, 120, 120)])
    assert stats["clip_high"] == [0.5, 0.5, 0.5]
    assert stats["frames"] == 2


def test_no_frames_is_refused():
    with pytest.raises(ValueError, match="at least one frame"):
        naturalness.measure([])
