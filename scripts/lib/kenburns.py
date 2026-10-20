"""The move over a photo, planned (design docs/specs/2026-10-20-photos-design.md §3).

Pure arithmetic in float photo pixels: which frame of the photo each output frame
shows. lib/still renders it; nothing here reads a pixel.

The move is a HOMOTHETY about the subject's centre P: frame(s) = P + (base - P) * s.
P therefore holds still on screen while the frame closes in around it, and every
frame is a convex combination of the base frame and P, so no frame leaves the photo.
Scale runs log-linear (equal ratios read as equal speed) over a smoothstep, so the
move starts and stops without a jolt; position and scale ride the same curve, which
the homothety gives for free.
"""
import math
from dataclasses import dataclass

from scripts.lib import geometry
from scripts.lib.models import StillSpec

DEFAULT_MOVE = StillSpec(start=1.0, end=0.92)   # an 8.7% push-in: the craft sources' 5-10%
                                                # over a hold (photo research 2026-10-20).
                                                # A CONVENTION, not measured on a photo run.
SUBJECT_MARGIN = 0.05   # of the subject box's own size, per side, that the tightest frame
                        # keeps around it. A convention.


@dataclass(frozen=True)
class Rect:
    """x, y = top-left, in float photo pixels."""
    x: float
    y: float
    w: float
    h: float

    def to_list(self) -> list[float]:
        return [round(self.x, 3), round(self.y, 3), round(self.w, 3), round(self.h, 3)]


@dataclass(frozen=True)
class Plan:
    frames: list[Rect]
    base: Rect
    anchor: tuple[float, float]
    planned: StillSpec
    applied: StillSpec
    note: str            # "" when the move ran as planned


def base_size(photo: tuple[int, int], aspect: tuple[int, int],
              crop_scale: float) -> tuple[float, float]:
    """The largest frame of `aspect` inside the photo, times crop_scale — geometry.crop_for
    without its integer truncation, because the render samples in float."""
    pw, ph = photo
    aw, ah = aspect
    if aw / ah <= pw / ph:
        w, h = ph * aw / ah, float(ph)
    else:
        w, h = float(pw), pw * ah / aw
    return w * crop_scale, h * crop_scale


def _centre(box: Rect) -> tuple[float, float]:
    return box.x + box.w / 2, box.y + box.h / 2


def place(photo: tuple[int, int], size: tuple[float, float], subject: Rect | None,
          composition: str, grid: str) -> Rect:
    """The base frame: the subject's centre at the composition's x — 0.5 for `center`,
    the grid line nearer the subject's own place in the photo for `lead` (so the
    photographer's composition survives the crop) — vertically centred on it, clamped
    inside the photo. `break`, or no subject, centres the frame on the photo."""
    pw, ph = photo
    bw, bh = size
    if subject is None or composition == "break":
        return Rect((pw - bw) / 2, (ph - bh) / 2, bw, bh)
    cx, cy = _centre(subject)
    if composition == "center":
        tf = 0.5
    else:
        left, right = geometry.grid_lines(grid)
        rel = cx / pw
        tf = left if abs(rel - left) <= abs(rel - right) else right
    x = min(max(cx - tf * bw, 0.0), pw - bw)
    y = min(max(cy - bh / 2, 0.0), ph - bh)
    return Rect(x, y, bw, bh)


def anchor(base: Rect, subject: Rect | None) -> tuple[float, float]:
    """The homothety's fixed point: the subject's centre, clamped into the base frame
    (a `break` frame need not contain it), or the base frame's own centre."""
    if subject is None:
        return _centre(base)
    cx, cy = _centre(subject)
    return (min(max(cx, base.x), base.x + base.w), min(max(cy, base.y), base.y + base.h))


def _ratio(num: float, den: float) -> float:
    if num <= 0:
        return 0.0
    return math.inf if den <= 0 else num / den


def hold_scale(base: Rect, p: tuple[float, float], subject: Rect) -> float:
    """The smallest s whose frame P + (base - P)*s still holds the subject box with its
    margin. Above 1.0 the base frame itself cuts the subject, and no move can help."""
    mx, my = subject.w * SUBJECT_MARGIN, subject.h * SUBJECT_MARGIN
    x0, y0 = subject.x - mx, subject.y - my
    x1, y1 = subject.x + subject.w + mx, subject.y + subject.h + my
    px, py = p
    return max(_ratio(px - x0, px - base.x), _ratio(x1 - px, base.x + base.w - px),
               _ratio(py - y0, py - base.y), _ratio(y1 - py, base.y + base.h - py))


def ease(p: float) -> float:
    """Smoothstep: zero velocity at both ends."""
    return p * p * (3.0 - 2.0 * p)


def plan(photo: tuple[int, int], aspect: tuple[int, int], crop_scale: float,
         subject: Rect | None, composition: str, grid: str, move: StillSpec,
         n: int) -> Plan:
    """`n` frames of the move. The tight end is shortened, and the note says so, when it
    would cut the subject; the base frame cutting it already is noted and left alone."""
    if n < 1:
        raise ValueError(f"a photo episode needs at least one frame, got {n}")
    base = place(photo, base_size(photo, aspect, crop_scale), subject, composition, grid)
    p = anchor(base, subject)
    a, b = move.start, move.end
    note = ""
    if subject is not None:
        need = hold_scale(base, p, subject)
        if need > 1.0:
            note = "the subject is larger than the frame, so the base frame already cuts it"
        elif min(a, b) < need:
            tight = round(need, 4)
            note = (f"the move was shortened to {tight} so the subject stays whole "
                    f"(planned {a}->{b})")
            a, b = (max(a, tight), max(b, tight))
    frames = []
    for k in range(n):
        q = ease(k / (n - 1)) if n > 1 else 1.0
        s = a * (b / a) ** q
        frames.append(Rect(p[0] + (base.x - p[0]) * s, p[1] + (base.y - p[1]) * s,
                           base.w * s, base.h * s))
    return Plan(frames=frames, base=base, anchor=p, planned=move,
                applied=StillSpec(start=a, end=b), note=note)
