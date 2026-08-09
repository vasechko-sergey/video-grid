import math
import pytest
from scripts.lib import geometry
from scripts.lib import geometry as g
from scripts.lib.models import RoutePoint, CropPath, PathMeta

def test_crop_size_9x16_from_1080p():
    # 9:16 crop out of a 1920x1080 source: full height, width = int(1080*9/16)
    # = 607 (the session value). round() would give 608 — wrong on purpose here.
    assert g.crop_size(9, 16, 1920, 1080) == (607, 1080)

def test_crop_size_1x1_from_1080p():
    assert g.crop_size(1, 1, 1920, 1080) == (1080, 1080)

def test_grid_lines_thirds():
    assert g.grid_lines("thirds") == (1/3, 2/3)

def test_grid_lines_phi():
    left, right = g.grid_lines("phi")
    assert math.isclose(left, 1 - 1/1.618, abs_tol=1e-3)   # ~0.382
    assert math.isclose(right, 1/1.618, abs_tol=1e-3)       # ~0.618

def test_target_frac_lead_right_thirds():
    # subject moving right → sits on LEFT third
    assert math.isclose(g.target_frac("lead", "right", "thirds"), 1/3)

def test_target_frac_lead_left_thirds():
    assert math.isclose(g.target_frac("lead", "left", "thirds"), 2/3)

def test_target_frac_center():
    assert g.target_frac("center", "right", "thirds") == 0.5

def test_crop_x_lead_right_offsets_ahead():
    # moving right, subject at x=900, crop_w=607, thirds → subject on left third
    x = g.crop_x(subject_x=900, composition="lead", direction="right",
                 grid="thirds", crop_w=607, src_w=1920)
    # crop_x = 900 - (1/3)*607 = 900 - 202.33 = 697.67 → 698
    assert x == 698

def test_crop_x_clamped_low():
    x = g.crop_x(subject_x=50, composition="lead", direction="right",
                 grid="thirds", crop_w=607, src_w=1920)
    assert x == 0

def test_crop_x_clamped_high():
    x = g.crop_x(subject_x=1900, composition="lead", direction="left",
                 grid="thirds", crop_w=607, src_w=1920)
    assert x == 1920 - 607

def test_crop_y_no_freedom_is_zero():
    assert g.crop_y(subject_y=500, crop_h=1080, src_h=1080) == 0

def test_crop_y_headroom_045():
    # crop_h=608 out of 1080: subject centre at 0.45*608=273.6 from crop top
    assert g.crop_y(subject_y=500, crop_h=608, src_h=1080) == round(500 - 0.45 * 608)

def test_crop_y_clamped():
    assert g.crop_y(subject_y=20, crop_h=608, src_h=1080) == 0
    assert g.crop_y(subject_y=1070, crop_h=608, src_h=1080) == 1080 - 608


def test_crop_for_canvas_aspect_matches_crop_size():
    # the golden fixture: 9:16 out of 1280x720 -> 405 wide (odd, and that is correct)
    assert geometry.crop_for((9, 16), 1.0, 1280, 720) == (405, 720)
    assert geometry.crop_for((9, 16), 1.0, 1280, 720) == geometry.crop_size(9, 16, 1280, 720)


def test_crop_for_source_aspect_is_the_whole_frame():
    assert geometry.crop_for((1280, 720), 1.0, 1280, 720) == (1280, 720)


def test_crop_for_square_aspect():
    assert geometry.crop_for((1, 1), 1.0, 1280, 720) == (720, 720)


def test_crop_for_scale_shrinks_both_sides():
    assert geometry.crop_for((1280, 720), 0.5, 1280, 720) == (640, 360)


def test_crop_for_rejects_bad_scale():
    with pytest.raises(ValueError, match="crop_scale"):
        geometry.crop_for((9, 16), 0.0, 1280, 720)
    with pytest.raises(ValueError, match="crop_scale"):
        geometry.crop_for((9, 16), 1.5, 1280, 720)


def test_crop_for_rejects_bad_aspect():
    with pytest.raises(ValueError, match="positive"):
        geometry.crop_for((0, 16), 1.0, 1280, 720)
    with pytest.raises(ValueError, match="positive"):
        geometry.crop_for((9, 0), 1.0, 1280, 720)
    with pytest.raises(ValueError, match="positive"):
        geometry.crop_for((-9, 16), 1.0, 1280, 720)
    with pytest.raises(ValueError, match="positive"):
        geometry.crop_for((9, -16), 1.0, 1280, 720)


def test_crop_for_rejects_a_nonpositive_source():
    with pytest.raises(ValueError, match="crop source must be positive"):
        geometry.crop_for((9, 16), 1.0, 0, 720)
    with pytest.raises(ValueError, match="crop source must be positive"):
        geometry.crop_for((9, 16), 1.0, 1280, 0)
    with pytest.raises(ValueError, match="crop source must be positive"):
        geometry.crop_for((9, 16), 1.0, -1280, 720)


def test_freedom_is_source_width_minus_crop_width():
    assert geometry.freedom(405, 1280) == 875
    assert geometry.freedom(1280, 1280) == 0


def test_freedom_rejects_a_crop_wider_than_the_source():
    with pytest.raises(ValueError, match="wider than the source"):
        geometry.freedom(1300, 1280)


def test_even_floors_to_even():
    assert geometry.even(405) == 404
    assert geometry.even(720) == 720
    assert geometry.even(2275.6) == 2276


def test_marks_at_times_projects_subject_into_canvas_fractions():
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    # fill layout, 1000x2000 out; crop 1000x2000 at y=0; subject centre at x=500 (crop-x 0)
    route = [RoutePoint(0.0, 500.0, 900.0, 100.0, 200.0),
             RoutePoint(2.0, 500.0, 900.0, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta(mode="fill", crop_w=1000, crop_h=2000, crop_y=0, src_dims=(1000, 2000),
                    canvas=(1000, 2000), out_dims=(1000, 2000), rect_px=(0, 0, 1000, 2000), freedom=0)
    marks = geometry.marks_at_times(route, path, meta, [0.0, 1.0, 2.0])
    assert marks[0] == (0.5, 0.45)             # x-cx=500 → 0.5 ; y=900/2000 → 0.45
    assert marks == [(0.5, 0.45)] * 3          # constant route → constant marks


def test_marks_at_times_rejects_desync():
    import pytest
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000), (0, 0, 1000, 2000), 0)
    with pytest.raises(ValueError, match="parallel arrays"):
        geometry.marks_at_times([RoutePoint(0.0, 1.0, 1.0, 1.0, 1.0)], CropPath([0, 0]), meta, [0.0])


def test_extent_at_times_projects_bbox_corners_straddling_the_centre():
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    # fill 1000x2000; subject 100x200 centred at (500, 900) → centre mark (0.5, 0.45)
    route = [RoutePoint(0.0, 500.0, 900.0, 100.0, 200.0),
             RoutePoint(2.0, 500.0, 900.0, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000),
                    (0, 0, 1000, 2000), 0)
    ext = geometry.extent_at_times(route, path, meta, [0.0, 2.0])
    # left/top = (450/1000, 800/2000), right/bottom = (550/1000, 1000/2000)
    assert ext[0] == (0.45, 0.4, 0.55, 0.5)
    assert ext == [(0.45, 0.4, 0.55, 0.5)] * 2      # constant route → constant extents


def test_extent_at_times_pushes_a_corner_past_the_frame_when_subject_hugs_the_edge():
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    # subject centre x=980, w=100 → right edge 1030 → fx1 = 1.03 (clipped by the frame)
    route = [RoutePoint(0.0, 980.0, 900.0, 100.0, 200.0),
             RoutePoint(2.0, 980.0, 900.0, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000),
                    (0, 0, 1000, 2000), 0)
    (fx0, fy0, fx1, fy1), _ = geometry.extent_at_times(route, path, meta, [0.0, 2.0])
    assert fx1 == 1.03 and fx0 == 0.93


def test_extent_at_times_rejects_desync():
    import pytest
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000), (0, 0, 1000, 2000), 0)
    with pytest.raises(ValueError, match="parallel arrays"):
        geometry.extent_at_times([RoutePoint(0.0, 1.0, 1.0, 1.0, 1.0)], CropPath([0, 0]), meta, [0.0])


def _zoom_meta(**over):
    base = dict(mode="fill", crop_w=1000, crop_h=2000, crop_y=0,
                src_dims=(4000, 2000), canvas=(1000, 2000), out_dims=(1000, 2000),
                rect_px=(0, 0, 1000, 2000), freedom=3000,
                crop_ws=[1000, 500], crop_hs=[2000, 1000], crop_ys=[0, 500])
    base.update(over)
    return PathMeta(**base)


def test_marks_use_the_recorded_width_at_that_time():
    route = [RoutePoint(t=0.0, x=500.0, y=1000.0, w=100.0, h=200.0),
             RoutePoint(t=1.0, x=500.0, y=1000.0, w=100.0, h=200.0)]
    path = CropPath([0, 250])
    fx, _ = geometry.marks_at_times(route, path, _zoom_meta(), [1.0])[0]
    # tight rect: (500 - 250) / 500 = 0.5 of the output, not (500 - 250) / 1000 = 0.25
    assert fx == pytest.approx(0.5)


def test_extents_use_the_recorded_rect_at_that_time():
    route = [RoutePoint(t=0.0, x=500.0, y=1000.0, w=100.0, h=200.0),
             RoutePoint(t=1.0, x=500.0, y=1000.0, w=100.0, h=200.0)]
    path = CropPath([0, 250])
    fx0, fy0, fx1, fy1 = geometry.extent_at_times(route, path, _zoom_meta(), [1.0])[0]
    assert fx1 - fx0 == pytest.approx(100 / 500)      # bbox width over the TIGHT rect
    assert fy1 - fy0 == pytest.approx(200 / 1000)


def test_an_unzoomed_meta_still_uses_its_scalars():
    route = [RoutePoint(t=0.0, x=500.0, y=1000.0, w=100.0, h=200.0),
             RoutePoint(t=1.0, x=500.0, y=1000.0, w=100.0, h=200.0)]
    path = CropPath([0, 250])
    meta = _zoom_meta(crop_ws=None, crop_hs=None, crop_ys=None)
    fx, _ = geometry.marks_at_times(route, path, meta, [1.0])[0]
    assert fx == pytest.approx(0.25)
