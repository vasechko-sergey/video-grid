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


def test_white_pixels_read_as_blown_and_black_ones_as_crushed():
    blown = np.concatenate([_flat(255, 255, 255, h=16), _flat(120, 120, 120, h=48)])
    crushed = np.concatenate([_flat(0, 0, 0, h=16), _flat(120, 120, 120, h=48)])
    assert naturalness.evaluate(naturalness.measure([blown]))["blown_highlights"] is True
    assert naturalness.evaluate(naturalness.measure([crushed]))["crushed_blacks"] is True


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
    a channel's data is relabeled to a different index. contrast is the only
    order-sensitive output, and a grey or two-colour fixture can't pin it:
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


def test_evaluate_reports_only_the_two_absolute_flags():
    """A cast, a flat frame and a saturated one are properties of the FOOTAGE, not of
    the grade: on the reference run 6 of 8 SOURCES already exceeded the old CAST_MAX
    before any grade ran (design §0.5). Only destroyed information stays absolute.

    This is also the only fixture left in the suite that exercises _frame_stats' cast
    and saturation formulas against a genuinely colourful, saturated frame — the
    red-cast test that used to cover them (indirectly, through colour_cast/
    oversaturated) was deleted along with those two flags. So pin the numbers
    themselves, not just the surviving flag set. _flat(220, 40, 40) is one constant
    colour, so both are exact fractions by hand:
      means = [220, 40, 40] -> neutral = (220+40+40)/3 = 100
      cast = max(|220/100-1|, |40/100-1|, |40/100-1|) = max(1.2, 0.6, 0.6) = 1.2
      saturation = (max-min)/max = (220-40)/220 = 180/220 = 9/11 = 0.81818... -> 0.8182
    """
    stats = naturalness.measure([_flat(220, 40, 40)])
    assert stats["cast"] == pytest.approx(1.2)
    assert stats["saturation"] == pytest.approx(0.8182)
    flags = naturalness.evaluate(stats)
    assert set(flags) == {"blown_highlights", "crushed_blacks"}


def _stats(cast, saturation, contrast):
    return {"cast": cast, "saturation": saturation, "contrast": contrast}


def test_a_grade_that_changed_nothing_raises_no_delta_flag():
    d = naturalness.evaluate_delta(_stats(0.30, 0.45, 100.0), _stats(0.30, 0.45, 100.0))
    assert d == {"cast_shift": False, "saturation_shift": False, "contrast_drop": False}


def test_a_strong_source_cast_alone_raises_nothing():
    """0.30 is four times the old absolute bar and is simply what a seascape looks
    like. The grade left it where it was, so nothing fires."""
    d = naturalness.evaluate_delta(_stats(0.30, 0.45, 100.0), _stats(0.32, 0.45, 100.0))
    assert d["cast_shift"] is False


def test_cast_shift_is_two_sided_and_bars_at_the_measured_value():
    hi = naturalness.evaluate_delta(_stats(0.10, 0.30, 100.0), _stats(0.19, 0.30, 100.0))
    lo = naturalness.evaluate_delta(_stats(0.19, 0.30, 100.0), _stats(0.10, 0.30, 100.0))
    assert hi["cast_shift"] is True and lo["cast_shift"] is True
    near = naturalness.evaluate_delta(_stats(0.10, 0.30, 100.0), _stats(0.177, 0.30, 100.0))
    assert near["cast_shift"] is False           # 0.077 — the shipped run's own maximum
    assert naturalness.CAST_DELTA_MAX == 0.08


def test_saturation_shift_is_two_sided_and_catches_a_desaturation():
    assert naturalness.SAT_DELTA_MAX == 0.12
    lost = naturalness.evaluate_delta(_stats(0.10, 0.40, 100.0), _stats(0.10, 0.24, 100.0))
    gained = naturalness.evaluate_delta(_stats(0.10, 0.24, 100.0), _stats(0.10, 0.40, 100.0))
    assert lost["saturation_shift"] is True and gained["saturation_shift"] is True
    ok = naturalness.evaluate_delta(_stats(0.10, 0.40, 100.0), _stats(0.10, 0.297, 100.0))
    assert ok["saturation_shift"] is False       # 0.103 — the shipped run's own maximum


def test_contrast_drop_is_signed_because_a_gain_is_not_a_defect():
    """The reference run's ep6 GAINED 24.5 of luma spread legitimately; testing the
    magnitude would flag it. Only a loss counts."""
    assert naturalness.CONTRAST_DROP_MAX == 20.0
    lost = naturalness.evaluate_delta(_stats(0.1, 0.3, 120.0), _stats(0.1, 0.3, 90.0))
    gained = naturalness.evaluate_delta(_stats(0.1, 0.3, 90.0), _stats(0.1, 0.3, 120.0))
    assert lost["contrast_drop"] is True
    assert gained["contrast_drop"] is False
    near = naturalness.evaluate_delta(_stats(0.1, 0.3, 120.0), _stats(0.1, 0.3, 103.4))
    assert near["contrast_drop"] is False        # 16.6 — the shipped run's own maximum


def test_the_absolute_style_bars_are_gone():
    """Deleted, not lowered: each measured either the scene rather than the grade, or
    sat where its own footage could never reach (design §0.5)."""
    for name in ("CAST_MAX", "SAT_MAX", "FLAT_SPREAD"):
        assert not hasattr(naturalness, name)
