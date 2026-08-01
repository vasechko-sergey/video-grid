import numpy as np
import pytest

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


def test_descriptor_dist_rejects_a_length_mismatch():
    # two operands of different lengths must fail loud: zip() would truncate to the
    # shorter one and return a plausible-but-wrong distance — a silently wrong hero,
    # not a crash. This is a caller-error backstop, not the stale-cast.json gate:
    # footage.CastMember owns the descriptor's SHAPE and rejects a stale registry at
    # load (see test_castmember_rejects_a_wrong_length_descriptor), which is why the
    # "re-run footage-intake" remedy lives there and not in this message.
    full = appearance.build_descriptor(_crop((250, 0, 0)), None)
    with pytest.raises(ValueError, match="length mismatch") as ex:
        appearance.descriptor_dist(full, full[:-1])
    assert "24" in str(ex.value) and "23" in str(ex.value)      # both lengths, so the caller can see which
    assert "build_descriptor" in str(ex.value)                  # the remedy, not just the diagnosis


def test_descriptor_dist_promises_only_the_check_it_makes():
    # The message used to read "(both must be 3 * HIST_BINS = 24)" while the code
    # only compared len(a) to len(b) — descriptor_dist([0.5, 0.5], [0.5, 0.5])
    # returned 0.0 with no complaint, so the message promised a check that was not
    # there. Equal lengths ARE the honest precondition of an L1 distance, and it is
    # the one the code enforces; "a descriptor is 24 floats" has exactly one home,
    # footage.DESCRIPTOR_LEN, at the boundary a foreign descriptor actually crosses.
    # Re-checking it here would be a second spelling AND a guard no wired path can
    # reach — both operands already come from build_descriptor or a validated
    # CastMember. So: the message tells the truth instead.
    assert appearance.descriptor_dist([0.5, 0.5], [0.5, 0.5]) == 0.0
    assert appearance.descriptor_dist([1.0, 0.0], [0.0, 1.0]) == 2.0
    with pytest.raises(ValueError) as ex:
        appearance.descriptor_dist([0.5, 0.5], [1.0])
    assert "3 * HIST_BINS" not in str(ex.value)


def test_crop_and_mask_without_orig_img_is_none():
    class _Res:
        orig_img = None
    assert appearance.crop_and_mask(_Res(), 0, object()) == (None, None)


def test_cast_match_is_below_the_distance_maximum():
    assert 0.0 < appearance.CAST_MATCH < 2.0


def test_crop_bbox_extracts_scaled_region():
    import numpy as np
    from scripts.lib import appearance
    frame = np.zeros((100, 200, 3), dtype="uint8")
    frame[40:60, 90:110] = 255                        # a white 20x20 block, centre (100,50)
    crop = appearance.crop_bbox(frame, (100.0, 50.0, 20.0, 20.0), scale=1.0)
    assert crop.shape == (20, 20, 3) and crop.mean() == 255


def test_crop_bbox_scales_a_proxy_box_up_to_original():
    import numpy as np
    from scripts.lib import appearance
    frame = np.zeros((200, 400, 3), dtype="uint8")    # original 2x the proxy
    frame[80:120, 180:220] = 255
    crop = appearance.crop_bbox(frame, (100.0, 50.0, 20.0, 20.0), scale=2.0)  # proxy box, 2x
    assert crop.shape == (40, 40, 3) and crop.mean() == 255
