import numpy as np

from scripts.lib import appearance


def _crop(rgb):
    """A 4x4 crop of one solid colour."""
    return np.full((4, 4, 3), rgb, dtype=np.uint8)


def test_descriptor_is_l1_normalized():
    d = appearance.build_descriptor(_crop((200, 10, 10)), None)
    assert len(d) == 3 * appearance.HIST_BINS
    assert abs(sum(d) - 1.0) < 1e-9


def test_descriptor_dist_range_is_zero_to_two():
    red = appearance.build_descriptor(_crop((250, 0, 0)), None)
    # cyan, not blue: (0, 0, 250) still shares red's zero G-channel bin, so it is
    # NOT fully disjoint from red (dist 4/3) — cyan differs from red in all three
    # channels, giving genuinely disjoint per-channel histogram supports.
    cyan = appearance.build_descriptor(_crop((0, 250, 250)), None)
    assert appearance.descriptor_dist(red, red) == 0.0
    # disjoint supports → the maximum
    assert abs(appearance.descriptor_dist(red, cyan) - 2.0) < 1e-9


def test_descriptor_uses_mask_pixels_only():
    # left half red (masked in), right half blue (masked out) → the descriptor
    # must equal the all-red one: the mask cuts the background away (§6.1a)
    crop = np.zeros((4, 4, 3), dtype=np.uint8)
    crop[:, :2] = (250, 0, 0)
    crop[:, 2:] = (0, 0, 250)
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[:, :2] = 255
    assert appearance.build_descriptor(crop, mask) == appearance.build_descriptor(_crop((250, 0, 0)), None)


def test_descriptor_falls_back_to_whole_crop_when_mask_is_empty():
    crop = _crop((250, 0, 0))
    assert appearance.build_descriptor(crop, np.zeros((4, 4), dtype=np.uint8)) == \
           appearance.build_descriptor(crop, None)


def test_crop_and_mask_without_orig_img_is_none():
    class _Res:
        orig_img = None
    assert appearance.crop_and_mask(_Res(), 0, object()) == (None, None)


def test_cast_match_is_below_the_distance_maximum():
    assert 0.0 < appearance.CAST_MATCH < 2.0
