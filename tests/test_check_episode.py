"""Unit tests for check_episode's pure pixel-sampling helper — a synthetic
numpy frame is all `_box_mean_rgb` needs, so this needs no ffmpeg and does not
belong in tests/integration/test_color_fidelity.py.

_box_mean_rgb's clamp is asymmetric by construction and was NOT symmetric
before fix round 2 (2026-08-28 grade-delta-sensors Task 2 review): x0/y0 were
only lower-bounded (`max(0, x0)`), so a box beginning past the frame's right or
bottom edge left x0 (or y0) sitting beyond the frame. The subsequent x1/y1
clamp could then only shrink DOWN to that same out-of-range x0/y0, producing an
empty slice — and `.mean()` of an empty array returns (nan, nan, nan) with only
a RuntimeWarning, never a raise. The fix clamps x0/y0 into [0, w-1]/[0, h-1]
FIRST, so they can never sit past the frame themselves, before x1/y1 are
clamped relative to them.
"""
import numpy as np

from scripts import check_episode


def test_box_entirely_past_the_right_edge_reproduces_the_reported_case():
    """The reviewer's own repro: box (700, 100, 750, 150) against a 640x360
    frame — x0 and x1 both past the right edge (640). The fixed clamp
    collapses this to the frame's single rightmost column; fill that column
    with a known colour so the result is a real, predictable RGB rather than
    (nan, nan, nan)."""
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[:, 639] = (200, 100, 50)          # the rightmost column, known colour
    r, g, b = check_episode._box_mean_rgb(frame, (700, 100, 750, 150))
    assert not any(np.isnan(v) for v in (r, g, b)), (r, g, b)
    assert (r, g, b) == (200.0, 100.0, 50.0)


def test_box_entirely_past_the_bottom_edge():
    """y0 and y1 both past the frame's height (20): collapses to the bottom row."""
    frame = np.zeros((20, 10, 3), dtype=np.uint8)
    frame[19, :] = (5, 15, 25)              # the bottom row, known colour
    r, g, b = check_episode._box_mean_rgb(frame, (2, 25, 8, 30))
    assert not any(np.isnan(v) for v in (r, g, b)), (r, g, b)
    assert (r, g, b) == (5.0, 15.0, 25.0)


def test_box_entirely_left_and_above_with_negative_coordinates():
    """All four coordinates negative: collapses to the single top-left pixel
    (0, 0) — not the top-left corner of some wider clamped region. (This side
    of the clamp was already lower-bounded correctly before the fix; kept here
    as a regression pin so a future rewrite of the clamp can't break it while
    fixing the other side.)"""
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[0, 0] = (9, 99, 199)               # the one pixel this must land on
    r, g, b = check_episode._box_mean_rgb(frame, (-30, -20, -10, -5))
    assert (r, g, b) == (9.0, 99.0, 199.0)


def test_normal_in_bounds_box_reads_the_predicted_mean():
    """No clamping at all: a box straddling two known colour halves must read
    their exact analytic mean, so the fix didn't disturb the ordinary path."""
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:, 5:] = (100, 100, 100)           # right half of the frame
    # box=(3,2,7,6): cols 3,4 (left half, 0) + 5,6 (right half, 100), rows 2-5.
    r, g, b = check_episode._box_mean_rgb(frame, (3, 2, 7, 6))
    assert (r, g, b) == (50.0, 50.0, 50.0)
