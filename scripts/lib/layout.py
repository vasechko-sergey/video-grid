"""Resolve a LayoutSpec into pixels (spec §7, design 2026-07-10).

The spec says what the episode wants; this says what ffmpeg must do. Keeping
the arithmetic here — and only here — is what lets check_episode and storyboard
read a sidecar instead of each re-deriving the crop and drifting apart.
"""
from dataclasses import dataclass

from scripts.lib import geometry
from scripts.lib.models import Delivery, LayoutSpec


@dataclass(frozen=True)
class ResolvedLayout:
    mode: str
    crop_aspect: tuple[int, int]
    crop_w: int
    crop_h: int
    freedom: int
    out_w: int
    out_h: int
    rect_px: tuple[int, int, int, int]      # x, y, w, h in output pixels
    background: str
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
    canvas_w = crop_w / rw_f
    canvas_h = canvas_w * canvas[1] / canvas[0]
    out_w, out_h = delivery.dims(canvas_w, canvas_h)

    if spec.mode == "fill":
        # the fast path is a single scale={out_w}:{out_h} — an anisotropic squash
        # onto the full canvas, with no background to letterbox into. The crop
        # lands edge to edge, whatever its aspect, so the rect IS the canvas. An
        # aspect-preserving rh (even(404 * 720 / 405) = 718) would centre a 2px
        # letterbox that nothing fills, and every hero mark mapped through it
        # would drift — on the one path this plan promised would not change.
        rx, ry, rw, rh = 0, 0, out_w, out_h
    else:
        rw = geometry.even(rw_f * out_w)
        rh = geometry.even(rw * crop_h / crop_w)
        rx = int(round(rx_f * out_w))
        ry = (out_h - rh) // 2 if spec.rect is None else int(round(ry_f * out_h))
        if rx + rw > out_w or ry + rh > out_h:
            raise ValueError(
                f"layout rect {spec.rect} at crop aspect {aspect[0]}:{aspect[1]} derives a "
                f"{rw}x{rh}px card at ({rx}, {ry}), which overflows the {out_w}x{out_h} "
                "canvas — shrink rect w, move rect y up, or pick a taller crop aspect")

    return ResolvedLayout(mode=spec.mode, crop_aspect=aspect, crop_w=crop_w, crop_h=crop_h,
                          freedom=free, out_w=out_w, out_h=out_h, rect_px=(rx, ry, rw, rh),
                          background=spec.background, fast_path=(spec.mode == "fill"))
