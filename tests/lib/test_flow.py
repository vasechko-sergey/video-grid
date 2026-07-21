import numpy as np
from scripts.lib import flow

def test_available_true_in_this_env():
    # cv2 ships transitively under ultralytics in this repo's env
    assert flow.available() is True

def test_centroid_bbox_of_a_single_rectangle():
    mask = np.zeros((100, 200), dtype=bool)
    mask[10:20, 30:50] = True                 # a 10-high, 20-wide block; rows 10..19, cols 30..49
    cx, cy, w, h = flow._centroid_bbox(mask)
    # cv2 returns the exact centre (39.5, 14.5). Python's round() is banker's rounding
    # (round-half-to-even): round(39.5) -> 40 (40 is even), round(14.5) -> 14 (14 is
    # even) — NOT (39, 14) as a naive "round half up" reading would suggest. Verified
    # against cv2's actual output rather than assumed.
    assert (round(cx), round(cy), w, h) == (40, 14, 20.0, 10.0)   # centre (39.5,14.5), w20 h10

def test_centroid_bbox_of_empty_mask_is_none():
    assert flow._centroid_bbox(np.zeros((50, 50), dtype=bool)) is None

def test_centroid_bbox_picks_the_larger_component():
    mask = np.zeros((100, 200), dtype=bool)
    mask[0:5, 0:5] = True                      # small blob
    mask[40:60, 100:140] = True                # larger blob (20x40) → this one wins
    cx, cy, w, h = flow._centroid_bbox(mask)
    assert (w, h) == (40.0, 20.0) and 100 <= cx <= 140
