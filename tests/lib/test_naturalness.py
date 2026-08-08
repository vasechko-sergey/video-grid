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
    """A 16x16 blown frame and a 64x64 clean frame — the SIZE MISMATCH is the point.
    Per-frame averaging gives (1.0 + 0.0) / 2 = 0.5 regardless of how many pixels each
    frame has. A regression that reintroduced pixel-pooling (concatenate every frame's
    pixels, then reduce once — the exact memory defect the module docstring warns
    against) would instead pool 256 blown pixels into a 256+4096=4352-pixel bag:
    256/4352 ~= 0.0588, not 0.5. Equal-sized frames can't tell the two implementations
    apart — both give 0.5 — which is why this fixture no longer uses matched sizes."""
    stats = naturalness.measure([_flat(255, 255, 255, h=16, w=16), _flat(120, 120, 120)])
    assert stats["clip_high"] == [0.5, 0.5, 0.5]
    assert stats["frames"] == 2


def test_channel_order_is_pinned_by_hand_computed_bt601_contrast():
    """clip_high/clip_low/cast/saturation are all order-invariant: none of them move if
    a channel's data is relabeled to a different index. contrast (and therefore `flat`)
    is the only order-sensitive output, and a grey or two-colour fixture can't pin it:
    with two colours, |luma(a) - luma(b)| == |luma(b) - luma(a)|, so a bug that swaps
    which channel gets which BT.601 weight can still land on the same spread. Three
    single-channel colours against a FIXED black baseline avoid that: each patch is 25%
    of the frame (h=16 of 64) over 75% black, comfortably inside both the 5th- and
    95th-percentile bounds, so contrast = p95 - p5 = (patch luma) - 0 = weight * 200
    exactly, for whichever channel that patch lit up:
        R: 0.299 * 200 = 59.8
        G: 0.587 * 200 = 117.4
        B: 0.114 * 200 = 22.8
    A swapped channel index (the classic RGB/BGR mixup — verified against a simulated
    R<->B swap) or a transposed weight (verified against BT.709's 0.2126/0.7152/0.0722)
    changes at least one of these three numbers; the G > R > B ordering the correct
    weights produce is exactly what either bug would break."""
    baseline = _flat(0, 0, 0, h=48)
    r = naturalness.measure([np.concatenate([_flat(200, 0, 0, h=16), baseline])])["contrast"]
    g = naturalness.measure([np.concatenate([_flat(0, 200, 0, h=16), baseline])])["contrast"]
    b = naturalness.measure([np.concatenate([_flat(0, 0, 200, h=16), baseline])])["contrast"]
    assert r == 59.8
    assert g == 117.4
    assert b == 22.8
    assert g > r > b


def test_a_float_frame_is_refused():
    with pytest.raises(ValueError, match="uint8"):
        naturalness.measure([_flat(118, 120, 122).astype(np.float32) / 255.0])


def test_no_frames_is_refused():
    with pytest.raises(ValueError, match="at least one frame"):
        naturalness.measure([])
