import math
from scripts.lib import geometry as g

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
