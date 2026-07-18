"""Unit tests for storyboard hero marks (Task 8, layouts).

marks_at_times maps a subject at source (x, y) into OUTPUT-frame fractions by
placing the crop inside meta.rect_px. For `fill` that rect is the whole output,
so it reduces to the old (x - cx) / crop_w; under a composite (fit/insert)
the crop is a card inside a larger canvas and the marker must follow it there —
otherwise it lands off the hero, sometimes on the blurred background entirely.
Pure unit tests (no ffmpeg) — they stay unmarked.
"""
import pytest
from scripts import storyboard
from scripts.lib.models import PathMeta, RoutePoint, CropPath


def _route_and_path():
    route = [RoutePoint(t=i / 10, x=400.0 + i * 10, y=360.0, w=60.0, h=160.0) for i in range(5)]
    path = CropPath([100 + i * 10 for i in range(5)])
    return route, path


def test_marks_for_fill_are_unchanged():
    route, path = _route_and_path()
    meta = PathMeta(mode="fill", crop_w=405, crop_h=720, crop_y=0, src_dims=(1280, 720),
                    canvas=(9, 16), out_dims=(404, 720), rect_px=(0, 0, 404, 720), freedom=875)
    marks = storyboard.marks_at_times(route, path, meta, [0.0])
    assert marks == [((400.0 - 100) / 405, 360.0 / 720)]


_FIT = PathMeta(mode="fit", crop_w=1280, crop_h=720, crop_y=0, src_dims=(1280, 720),
                canvas=(9, 16), out_dims=(1280, 2276), rect_px=(0, 778, 1280, 720),
                freedom=0)


def test_marks_for_a_composite_land_inside_the_rect():
    route, path = _route_and_path()
    # fit: the whole 1280x720 frame sits at y=778 in a 1280x2276 canvas
    (fx, fy), = storyboard.marks_at_times(route, path, _FIT, [0.0])
    # x: the subject is 400px into a 1280px-wide rect that spans the full canvas
    assert fx == pytest.approx((0 + 1280 * (400.0 - 100) / 1280) / 1280)
    # y: the subject is halfway down a 720px rect that starts 778px down a 2276px canvas
    assert fy == pytest.approx((778 + 720 * (360.0 / 720)) / 2276)
    assert 0.0 < fx < 1.0 and 0.0 < fy < 1.0


def test_a_subject_near_the_frame_top_does_not_land_on_the_background():
    """The case above cannot fail: fit's rect spans the full width at rx=0,
    and a subject at the crop's vertical centre maps to the canvas centre either
    way — so the old `y / src_h` formula produces the identical numbers.

    Move the subject to the top of the frame and the two part company. The
    picture begins 778px down a 2276px canvas, i.e. at fy=0.342. The old formula
    puts a subject at y=50 at fy=0.069 — above the picture, on the blurred
    background, where §6.1a's layer-4 reviewer would be reading noise.
    """
    route = [RoutePoint(t=i / 10, x=400.0 + i * 10, y=50.0, w=60.0, h=160.0) for i in range(5)]
    path = CropPath([100 + i * 10 for i in range(5)])
    (_, fy), = storyboard.marks_at_times(route, path, _FIT, [0.0])
    top, bottom = 778 / 2276, (778 + 720) / 2276
    assert fy == pytest.approx((778 + 720 * (50.0 / 720)) / 2276)
    assert top < fy < bottom                       # on the picture
    assert 50.0 / 720 < top                        # ...where the old formula was not


def test_marks_for_a_bordered_insert_land_on_the_picture_not_the_border():
    route, path = _route_and_path()
    # golden insert, border_px=8: a 704x704 card inset at (48, 364) in an 800x1422
    # canvas — the border eats the canvas edge, so the content rect is inset. A
    # mark computed against the whole canvas (or the old crop-only fraction) would
    # drift toward that border; against rect_px it lands on the picture.
    meta = PathMeta(mode="insert", crop_w=720, crop_h=720, crop_y=0, src_dims=(1280, 720),
                    canvas=(9, 16), out_dims=(800, 1422), rect_px=(48, 364, 704, 704), freedom=0)
    (fx, fy), = storyboard.marks_at_times(route, path, meta, [0.0])
    # derived from the formula, not guessed:
    #   fx = (48 + 704 * (400 - 100) / 720) / 800 = 341.333.../800 = 0.42667
    #   fy = (364 + 704 * (360 / 720))     / 1422 = 716/1422       = 0.50352
    assert fx == pytest.approx((48 + 704 * (400.0 - 100) / 720) / 800)
    assert fy == pytest.approx((364 + 704 * (360.0 / 720)) / 1422)
    # and it sits strictly INSIDE the content rect — off the border on every side
    assert 48 / 800 < fx < (48 + 704) / 800
    assert 364 / 1422 < fy < (364 + 704) / 1422
