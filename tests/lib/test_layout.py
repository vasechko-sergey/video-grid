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


def test_fit_shows_the_whole_frame_at_native_resolution():
    rl = layout.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                        CANVAS, GOLDEN, NATIVE)
    assert (rl.crop_w, rl.crop_h) == (1280, 720)
    assert (rl.out_w, rl.out_h) == (1280, 2276)    # subject native, background upscaled
    assert rl.freedom == 0                          # nobody controls composition
    assert rl.rect_px == (0, 778, 1280, 720)        # full width, vertically centred
    assert rl.fast_path is False


def test_fit_with_a_scale_regains_freedom():
    rl = layout.resolve(LayoutSpec(mode="fit", crop_aspect="source", crop_scale=0.9),
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


def test_border_insets_the_content_and_keeps_the_card_where_it_was():
    plain = layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90)),
                           CANVAS, GOLDEN, NATIVE)
    bordered = layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90),
                                         border_px=8), CANVAS, GOLDEN, NATIVE)
    assert plain.rect_px == (40, 356, 720, 720)          # unchanged by this task
    # the card still starts at (40, 356) and is still 720x720 — but rect_px is now
    # the CONTENT, inset by the border on every side
    assert bordered.rect_px == (48, 364, 704, 704)
    assert bordered.border_px == 8 and bordered.border_color == "white"


def test_border_preserves_the_crop_aspect_in_the_content():
    rl = layout.resolve(LayoutSpec(mode="insert", crop_aspect=(4, 5), rect=(0.05, 0.1, 0.90),
                                   border_px=10), CANVAS, GOLDEN, NATIVE)
    _, _, cw, ch = rl.rect_px
    assert abs(cw / ch - 4 / 5) < 0.01


def test_border_wider_than_the_card_fails_loud():
    # NOTE: under NATIVE delivery, canvas_w = crop_w / rw_f, so the outer card
    # width `ow` always tracks crop_w (here 720px, from crop_aspect (1,1) on the
    # 1280x720 golden source) regardless of how small rw_f is -- the canvas grows
    # to keep the card at native (unscaled) size. A tiny rect w (e.g. 0.02) with
    # border_px=100 does NOT overflow (verified: resolves to rect_px=(100,100,520,520)).
    # border_px must exceed ~crop_w/2 (here 720/2=360) to leave no content, so this
    # reuses the standard pinned rect (0.05, 0.25, 0.90) -- ow=720 there too -- with
    # a border comfortably past that threshold.
    with pytest.raises(ValueError, match="narrower than its own two borders"):
        layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90),
                                  border_px=400), CANVAS, GOLDEN, NATIVE)


def test_a_tiny_rect_explodes_the_native_canvas_and_fails_loud():
    # native sizes the canvas so the card is never upscaled: a 5% rect means a
    # canvas 20x the crop. 14400x25600 is not a layout, it is a typo.
    with pytest.raises(ValueError, match="past the 8192px limit"):
        layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.0, 0.0, 0.05)),
                       CANVAS, GOLDEN, NATIVE)


def test_the_same_tiny_rect_is_fine_when_delivery_pins_the_output():
    # the remedy the error names must actually work
    rl = layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.0, 0.0, 0.05)),
                        CANVAS, GOLDEN, Delivery("short_edge", 1080))
    assert rl.out_w == 1080


def test_an_oversized_exact_delivery_is_not_told_to_pin_the_output():
    """A raise must carry a remedy the caller can act on. The native-canvas
    message says "pin the output with delivery exact:WxH" — useless advice for a
    caller whose delivery already IS exact:9000x9000. It also blamed a "native
    delivery" that is not in play."""
    with pytest.raises(ValueError, match="Ask for a smaller exact size"):
        layout.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.9)),
                       CANVAS, GOLDEN, Delivery("exact", (9000, 9000)))


def test_fit_overflow_does_not_suggest_shrinking_a_rect_it_forbids():
    """fit pins rect_w to 1.0 and refuses a rect outright, so "shrink rect w"
    and "move rect y up" are advice it cannot take. A 16:9 crop across a 21:9
    canvas is taller than the canvas: the only levers are the canvas and the crop
    aspect, and the message must say so."""
    with pytest.raises(ValueError, match="Pick a taller canvas, or a wider crop_aspect"):
        layout.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                       (21, 9), GOLDEN, NATIVE)


def test_resolve_carries_the_filler_and_its_colour():
    # reframe reads BOTH off the resolved layout; a pass-through that works by
    # accident is a pass-through that can silently stop working.
    spec = LayoutSpec(mode="fit", crop_aspect="source",
                      background="solid", background_color="#101820")
    rl = layout.resolve(spec, CANVAS, GOLDEN, NATIVE)
    assert (rl.background, rl.background_color) == ("solid", "#101820")


def test_fill_out_dims_match_todays_delivery_on_a_non_golden_canvas():
    # the golden 9:16 crop of 1280x720 evens exactly; 21:9 of 4K does not.
    # resolve must agree with what reframe() computes today: dims(crop_w, crop_h)
    for canvas, src in (((9, 16), (1280, 720)), ((21, 9), (3840, 2160)),
                        ((4, 5), (1920, 1080)), ((1, 1), (1920, 1080))):
        cw, ch = geometry.crop_for((canvas[0], canvas[1]), 1.0, src[0], src[1])
        rl = layout.resolve(LayoutSpec(mode="fill"), canvas, src, NATIVE)
        assert (rl.out_w, rl.out_h) == NATIVE.dims(cw, ch), canvas
