"""Subject-anchored zoom geometry (design 2026-08-08 §3).

A zoom is a RECT PATH, not a generated one: the layout's crop is the widest rect
the move ever needs (both ends of a ZoomSpec are <= 1.0), every sample cuts a
smaller rect inside it, and that rect's POSITION still comes from the tracked
route through the same composition rule. This module owns the arithmetic only —
reframe owns the ffmpeg strings, the sidecar and the route.
"""
from scripts.lib import geometry as g
from scripts.lib.models import ZoomSpec

ZOOM_MAX_RATE = 0.5   # crop-width fractions per second. FIRST CUT, uncalibrated against any
                      # real shoot (design §10). It exists to catch the absurd — a typo that
                      # turns 0.7 into 0.07 — not to police taste, exactly as PanSpec's speed
                      # cap does for a whip pan.

ZOOM_MAX_UPSCALE = 1.5   # how far past 1:1 a push-in may resample. NOT zero, and the reason is
                         # measured: a 9:16 crop of a 16:9 4K source is 1215px wide against a
                         # 1080px delivery, so refusing every upsample would cap the reel format
                         # this engine exists for at 1.125x — below visibility (design §6). Also
                         # a FIRST CUT: nobody has judged a 1.5x push-in on real graded footage.


def validate(spec: ZoomSpec, crop_w: int, out_w: int, dur: float) -> None:
    """Refuse a zoom this episode cannot carry (design §6, refusals 4-6).

    The refusals that need the EPISODE's numbers and so cannot live on ZoomSpec
    itself: it validates its own two fractions, this validates them against a
    duration, a crop and a delivery width. `ValueError` is the ONLY exception
    this may raise for any `ZoomSpec` and any non-negative crop_w/out_w/dur —
    a crop that tightens to zero (or fewer) pixels is refused on its own,
    BEFORE the upsample-ratio message below ever divides by it, because a rect
    with no width is a different defect from one that is merely resampled too
    far, and blurring the two into one message would mean either skipping the
    ratio or dividing by zero.
    """
    if dur <= 0:
        raise ValueError(
            f"a zoom needs a duration to travel across and this episode has {dur}s — "
            "the scale would have to change instantaneously. Check the segment probes "
            "to a real duration, or drop the `zoom` field")
    rate = abs(spec.end - spec.start) / dur
    if rate > ZOOM_MAX_RATE:
        raise ValueError(
            f"zoom {spec.start}->{spec.end} over {dur:.3f}s is {rate:.3g} of the crop "
            f"width per second, past the {ZOOM_MAX_RATE} ceiling — that is a lurch, not a "
            "move. Narrow the from->to span, give the episode a longer duration, or check "
            "for a mistyped fraction")
    tightest = int(crop_w / (1.0 / min(spec.start, spec.end)))
    if tightest <= 0:
        raise ValueError(
            f"zoom {spec.start}->{spec.end} tightens the {crop_w}px crop to {tightest}px — "
            "that is not a rectangle. Zoom less far, use a wider base crop, or check for "
            "a mistyped fraction")
    floor = out_w / ZOOM_MAX_UPSCALE
    if tightest < floor:
        raise ValueError(
            f"zoom {spec.start}->{spec.end} tightens the {crop_w}px crop to {tightest}px "
            f"against a {out_w}px delivery — {out_w / tightest:.2f}x upsampling, past the "
            f"{ZOOM_MAX_UPSCALE}x this engine will ship. Past it the reel carries magnified "
            "pixels that were never resolved. Zoom less far, or deliver narrower")


def scales(spec: ZoomSpec, times: list[float]) -> list[float]:
    """s(t), the crop-width fraction in force at each sample — linear in time over
    the route's OWN span, so a zoom always completes exactly at the episode's end."""
    if len(times) < 2:
        raise ValueError(
            f"a zoom needs at least two samples to interpolate across, got {len(times)} — "
            "the route is too short to carry a move")
    t0, t1 = times[0], times[-1]
    if t1 <= t0:
        raise ValueError(
            f"a zoom needs an increasing time span, got {t0} to {t1} — the route's "
            "timestamps are not ordered; re-run tracking")
    k = (spec.end - spec.start) / (t1 - t0)
    return [spec.start + k * (t - t0) for t in times]


def rects(spec: ZoomSpec, crop_w: int, crop_h: int, crop_y: int, src_h: int,
          times: list[float]) -> tuple[list[int], list[int], list[int]]:
    """(widths, heights, top edges) per sample — WHAT FFMPEG WILL CUT, recorded so
    no consumer re-derives it (design §4).

    Each is `int(base / z)`, NOT `round(base * s)`: zoompan is handed `z` and cuts
    `iw/z`, so defining the record from z removes the systematic half of any
    disagreement with the render. The rounding residual remains and is measured,
    not asserted away (design §10).

    The top edge keeps the BASE rect's vertical centre, so a push-in tightens
    around the same point the layout chose rather than drifting up the frame.
    """
    centre_y = crop_y + crop_h / 2
    ws: list[int] = []
    hs: list[int] = []
    ys: list[int] = []
    for s in scales(spec, times):
        z = 1.0 / s
        w = int(crop_w / z)
        h = int(crop_h / z)
        ws.append(w)
        hs.append(h)
        ys.append(int(g.clamp(round(centre_y - h / 2), 0, src_h - h)))
    return ws, hs, ys


def z_expr(spec: ZoomSpec, t0: float, t1: float, var: str = "it") -> str:
    """z(t) = 1/s(t) as a CLOSED-FORM ffmpeg expression.

    Not routed through reframe's piecewise-linear knot builder, for two
    disqualifying reasons (design §3.3): that builder formats knots at `.1f`,
    which would quantize a 1.4286 zoom to 1.4 and put the recorded widths ~30px
    from the rendered rect; and z = 1/s is hyperbolic, so a two-knot linear
    approximation is 6.6% wrong at the midpoint of a 1.0->0.6 push-in.

    Cannot divide by zero: s is linear between two ends both in (0, 1], so it is
    bounded below by min(start, end) > 0.
    """
    if t1 <= t0:
        raise ValueError(f"z_expr needs t1 > t0, got {t0} to {t1}")
    k = (spec.end - spec.start) / (t1 - t0)
    return f"1/({spec.start:.6f}+({k:.6f})*({var}-{t0:.4f}))"
