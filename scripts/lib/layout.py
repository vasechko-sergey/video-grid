"""Resolve a LayoutSpec into pixels (spec §7, design 2026-07-10).

The spec says what the episode wants; this says what ffmpeg must do. Keeping
the arithmetic here — and only here — is what lets check_episode and storyboard
read a sidecar instead of each re-deriving the crop and drifting apart.
"""
from dataclasses import dataclass

from scripts.lib import geometry
from scripts.lib.models import Delivery, LayoutSpec

MAX_SIDE = 8192      # x264 tops out far higher, but a canvas this size means a mistake


@dataclass(frozen=True)
class ResolvedLayout:
    mode: str
    crop_aspect: tuple[int, int]
    crop_w: int
    crop_h: int
    freedom: int
    out_w: int
    out_h: int
    rect_px: tuple[int, int, int, int]      # x, y, w, h in output pixels — the CONTENT rect
    background: str
    border_px: int
    border_color: str
    fast_path: bool


def _aspect(spec: LayoutSpec, canvas: tuple[int, int],
            src: tuple[int, int]) -> tuple[int, int]:
    if spec.crop_aspect == "canvas":
        return (canvas[0], canvas[1])
    if spec.crop_aspect == "source":
        return (src[0], src[1])
    return spec.crop_aspect


def resolve(spec: LayoutSpec, canvas: tuple[int, int], src: tuple[int, int],
            delivery: Delivery) -> ResolvedLayout:
    """Native size = the composite at which the inserted frame is NOT upscaled.

    canvas_w = crop_w / rect_w, canvas_h = canvas_w * canvas[1] / canvas[0] — both
    floats. Evenness is applied to each side independently, by Delivery, at the
    output: even(405) * 16/9 would drift 720 into 718.
    """
    aspect = _aspect(spec, canvas, src)
    crop_w, crop_h = geometry.crop_for(aspect, spec.crop_scale, src[0], src[1])
    free = geometry.freedom(crop_w, src[0])

    rx_f, ry_f, rw_f = spec.rect if spec.rect is not None else (0.0, 0.0, 1.0)
    if spec.mode == "fill":
        # the crop already carries the canvas aspect, so the canvas IS the crop.
        # Re-deriving canvas_h from crop_w drifts: a 21:9 crop of 4K is
        # 3840x1645, and 3840 * 9/21 evens to 1646, not 1644.
        canvas_w, canvas_h = float(crop_w), float(crop_h)
    else:
        canvas_w = crop_w / rw_f
        canvas_h = canvas_w * canvas[1] / canvas[0]
    out_w, out_h = delivery.dims(canvas_w, canvas_h)

    # A native delivery never upscales the crop, so it sizes the canvas to
    # crop_w / rect_w — a tiny rect does not make a small card, it makes an
    # enormous canvas (insert 1:1 at rect_w 0.05 → 14400x25600). Refuse the
    # gigapixel encode HERE, before any card arithmetic runs inside it, with an
    # error that names the cause — the silent-swap class this repo keeps loud.
    if out_w > MAX_SIDE or out_h > MAX_SIDE:
        # an `exact` delivery already pins the output, so "pin the output" is not a
        # remedy it can act on — it asked for these dimensions outright
        if delivery.mode == "exact":
            raise ValueError(
                f"delivery exact:{out_w}x{out_h} is past the {MAX_SIDE}px limit — "
                f"that is {out_w * out_h / 1e6:.0f} megapixels per frame. Ask for a "
                "smaller exact size, or raise layout.MAX_SIDE if you truly mean it")
        if rw_f < 1.0:
            raise ValueError(
                f"layout resolves to a {out_w}x{out_h} canvas, past the {MAX_SIDE}px limit — "
                f"a native delivery sizes the canvas so the {crop_w}x{crop_h} crop is never "
                f"upscaled, so rect width {rw_f} blows it up {1 / rw_f:.1f}x. Widen rect w, "
                "or pin the output with delivery short_edge:N / exact:WxH")
        raise ValueError(
            f"layout resolves to a {out_w}x{out_h} canvas, past the {MAX_SIDE}px limit — "
            f"a native delivery sizes the canvas to the {crop_w}x{crop_h} crop at the "
            f"{canvas[0]}:{canvas[1]} canvas aspect, with no rect to shrink it. Pin the output "
            "with delivery short_edge:N / exact:WxH, or use a less extreme canvas aspect")

    if spec.mode == "fill":
        # the fast path is a single scale={out_w}:{out_h} — an anisotropic squash
        # onto the full canvas, with no background to letterbox into. The crop
        # lands edge to edge, whatever its aspect, so the rect IS the canvas. An
        # aspect-preserving rh (even(404 * 720 / 405) = 718) would centre a 2px
        # letterbox that nothing fills, and every hero mark mapped through it
        # would drift — on the one path this plan promised would not change.
        rx, ry, rw, rh = 0, 0, out_w, out_h
    else:
        # rect_px is the CONTENT rect — the border (if any) sits OUTSIDE it, so the
        # outer card keeps the crop aspect, not the content. See design 2026-07-10:
        # a later task writes rect_px into path.meta.json for storyboard/check_episode
        # to place the hero marker; if it were the outer card, the marker would land
        # on the border instead of on the hero.
        b = spec.border_px
        ow = geometry.even(rw_f * out_w)
        cw = ow - 2 * b
        if cw <= 0:
            raise ValueError(
                f"border_px {b} leaves no content: the {ow}px card at rect width "
                f"{rw_f} is narrower than its own two borders — widen rect w, or "
                "shrink border_px")
        ch = geometry.even(cw * crop_h / crop_w)
        oh = ch + 2 * b
        ox = int(round(rx_f * out_w))
        oy = (out_h - oh) // 2 if spec.rect is None else int(round(ry_f * out_h))
        if ox + ow > out_w or oy + oh > out_h:
            # fit-blur pins rect_w to 1.0 and forbids a rect outright, so "shrink
            # rect w" and "move rect y up" are advice it cannot take. Its only
            # levers are the crop aspect and the canvas.
            if spec.rect is None:
                raise ValueError(
                    f"a {crop_w}x{crop_h} crop scaled to the full width of a "
                    f"{out_w}x{out_h} canvas is {oh}px tall and does not fit — the "
                    f"{canvas[0]}:{canvas[1]} canvas is wider than the {aspect[0]}:{aspect[1]} "
                    "crop. Pick a taller canvas, or a wider crop_aspect")
            raise ValueError(
                f"layout rect {spec.rect} at crop aspect {aspect[0]}:{aspect[1]} with "
                f"border_px {b} derives a {ow}x{oh}px card at ({ox}, {oy}), which "
                f"overflows the {out_w}x{out_h} canvas — shrink rect w, move rect y up, "
                "shrink border_px, or pick a taller crop aspect")
        rx, ry, rw, rh = ox + b, oy + b, cw, ch

    return ResolvedLayout(mode=spec.mode, crop_aspect=aspect, crop_w=crop_w, crop_h=crop_h,
                          freedom=free, out_w=out_w, out_h=out_h, rect_px=(rx, ry, rw, rh),
                          background=spec.background, border_px=spec.border_px,
                          border_color=spec.border_color, fast_path=(spec.mode == "fill"))
