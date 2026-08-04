import numpy as np
import pytest

from scripts.lib import appearance


def test_descriptor_dist_is_cosine_range_zero_to_two():
    v = [1.0] + [0.0] * 511
    opp = [-1.0] + [0.0] * 511
    orth = [0.0, 1.0] + [0.0] * 510
    assert appearance.descriptor_dist(v, v) == 0.0
    assert abs(appearance.descriptor_dist(v, orth) - 1.0) < 1e-9
    assert abs(appearance.descriptor_dist(v, opp) - 2.0) < 1e-9


def test_descriptor_dist_rejects_length_mismatch():
    with pytest.raises(ValueError, match="length"):
        appearance.descriptor_dist([1.0, 0.0], [1.0])


def test_crop_from_result_bgr_to_rgb_and_bbox():
    # orig_img is BGR; a red pixel is stored (0,0,255) and must come back (255,0,0)
    frame_bgr = np.zeros((10, 10, 3), np.uint8)
    frame_bgr[:, :] = (0, 0, 255)                       # BGR red

    class _Res:  orig_img = frame_bgr
    class _Box:  xywh = [[5.0, 5.0, 4.0, 4.0]]          # centre-format

    crop = appearance.crop_from_result(_Res(), _Box())
    assert crop.shape == (4, 4, 3)
    assert tuple(crop[0, 0]) == (255, 0, 0)             # RGB red


def test_crop_from_result_none_without_pixels():
    class _Res:  orig_img = None
    assert appearance.crop_from_result(_Res(), object()) is None


def test_cast_match_is_below_the_distance_maximum():
    assert 0.0 < appearance.CAST_MATCH < 2.0


def test_crop_bbox_extracts_scaled_region():
    frame = np.zeros((100, 200, 3), dtype="uint8")
    frame[40:60, 90:110] = 255                        # a white 20x20 block, centre (100,50)
    crop = appearance.crop_bbox(frame, (100.0, 50.0, 20.0, 20.0), scale=1.0)
    assert crop.shape == (20, 20, 3) and crop.mean() == 255


def test_crop_bbox_scales_a_proxy_box_up_to_original():
    frame = np.zeros((200, 400, 3), dtype="uint8")    # original 2x the proxy
    frame[80:120, 180:220] = 255
    crop = appearance.crop_bbox(frame, (100.0, 50.0, 20.0, 20.0), scale=2.0)  # proxy box, 2x
    assert crop.shape == (40, 40, 3) and crop.mean() == 255
