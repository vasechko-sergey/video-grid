import pytest
from scripts.lib import layout
from scripts.lib.models import Delivery, LayoutSpec

NATIVE = Delivery("native", None)
GOLDEN = (1280, 720)          # the golden fixture's source dims
CANVAS = (9, 16)


def test_fill_resolves_to_todays_numbers():
    rl = layout.resolve(LayoutSpec(mode="fill"), CANVAS, GOLDEN, NATIVE)
    assert (rl.crop_w, rl.crop_h) == (405, 720)
    assert (rl.out_w, rl.out_h) == (404, 720)      # exactly what Delivery gives today
    assert rl.freedom == 875
    assert rl.fast_path is True


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
