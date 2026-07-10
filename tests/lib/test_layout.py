import pytest
from scripts.lib import geometry
from scripts.lib import layout
from scripts.lib.models import Delivery, LayoutSpec

NATIVE = Delivery("native", None)
GOLDEN = (1280, 720)          # the golden fixture's source dims
CANVAS = (9, 16)


def test_fill_resolves_to_todays_numbers():
    rl = layout.resolve(LayoutSpec(mode="fill"), CANVAS, GOLDEN, NATIVE)
    assert (rl.crop_w, rl.crop_h) == (405, 720)
    assert (rl.out_w, rl.out_h) == (404, 720)      # exactly what Delivery gives today
    assert rl.rect_px == (0, 0, 404, 720)          # the squash covers the whole canvas
    assert rl.freedom == 875
    assert rl.fast_path is True


def test_fill_rect_is_the_whole_canvas_however_it_is_spelled():
    # the fast path stretches the crop onto the canvas; an aspect-preserving
    # rect would letterbox 2px that no background fills
    a = layout.resolve(LayoutSpec(mode="fill"), CANVAS, GOLDEN, NATIVE)
    b = layout.resolve(LayoutSpec(mode="fill", rect=(0.0, 0.0, 1.0)), CANVAS, GOLDEN, NATIVE)
    assert a.rect_px == b.rect_px == (0, 0, a.out_w, a.out_h)


def test_fit_blur_shows_the_whole_frame_at_native_resolution():
    rl = layout.resolve(LayoutSpec(mode="fit-blur", crop_aspect="source"),
                        CANVAS, GOLDEN, NATIVE)
    assert (rl.crop_w, rl.crop_h) == (1280, 720)
    assert (rl.out_w, rl.out_h) == (1280, 2276)    # subject native, background upscaled
    assert rl.freedom == 0                          # nobody controls composition
    assert rl.rect_px == (0, 778, 1280, 720)        # full width, vertically centred
    assert rl.fast_path is False


def test_fit_blur_with_a_scale_regains_freedom():
    rl = layout.resolve(LayoutSpec(mode="fit-blur", crop_aspect="source", crop_scale=0.9),
                        CANVAS, GOLDEN, NATIVE)
    assert rl.crop_w == 1152
    assert rl.freedom == 128                        # the tracker has room again


def test_insert_places_a_square_card():
    rl = layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90)),
                        CANVAS, GOLDEN, NATIVE)
    assert (rl.crop_w, rl.crop_h) == (720, 720)
    assert (rl.out_w, rl.out_h) == (800, 1422)
    assert rl.rect_px == (40, 356, 720, 720)        # scale into the card is identity
    assert rl.freedom == 560
    assert rl.fast_path is False


def test_resolve_rejects_a_rect_whose_derived_height_overflows():
    # a 1:1 card at 90% width is 720px tall; pushed to y=0.9 it runs off the bottom
    spec = LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.90, 0.90))
    with pytest.raises(ValueError, match="overflows"):
        layout.resolve(spec, CANVAS, GOLDEN, NATIVE)


def test_fill_out_dims_match_todays_delivery_on_a_non_golden_canvas():
    # the golden 9:16 crop of 1280x720 evens exactly; 21:9 of 4K does not.
    # resolve must agree with what reframe() computes today: dims(crop_w, crop_h)
    for canvas, src in (((9, 16), (1280, 720)), ((21, 9), (3840, 2160)),
                        ((4, 5), (1920, 1080)), ((1, 1), (1920, 1080))):
        cw, ch = geometry.crop_size(canvas[0], canvas[1], src[0], src[1])
        rl = layout.resolve(LayoutSpec(mode="fill"), canvas, src, NATIVE)
        assert (rl.out_w, rl.out_h) == NATIVE.dims(cw, ch), canvas
