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
SUBJECT_MARGIN = 0.05   # of the held box's own size, per side: the most gap the tightest
                        # frame keeps around it (never more than half the base frame's own
                        # gap there — see hold_scale). A convention.
PHOTO_EDGE = 0.005      # of the photo's side: a box this close to the photo's border is
                        # clipped by it (YOLO boxes stop at the image edge). A convention.
HOLD_TOP = 0.5          # the share of a person box, from its TOP, the move keeps whole and
                        # aims at: heads and faces. A push toward a whole standing figure
                        # could not move at all without cutting someone's head (the 2026-10-20
                        # review's case); a portrait push cuts the feet first. A convention
                        # that assumes upright people, which is what a person detector boxes.


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


def held(subject: Rect) -> Rect:
    """The part of the subject the move keeps whole and aims at: its top HOLD_TOP."""
    return Rect(subject.x, subject.y, subject.w, subject.h * HOLD_TOP)


def place(photo: tuple[int, int], size: tuple[float, float], subject: Rect | None,
          composition: str, grid: str) -> Rect:
    """The base frame: the subject's centre at the composition's x — 0.5 for `center`,
    the grid line nearer the subject's own place in the photo for `lead` (so the
    photographer's composition survives the crop) — vertically centred on the part the
    move aims at, clamped inside the photo. `break`, or no subject, centres the frame
    on the photo."""
    pw, ph = photo
    bw, bh = size
    if subject is None or composition == "break":
        return Rect((pw - bw) / 2, (ph - bh) / 2, bw, bh)
    cx, _ = _centre(subject)
    _, cy = _centre(held(subject))
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
    """The homothety's fixed point: the centre of the part the move holds, clamped into
    the base frame (a `break` frame need not contain it), or the base frame's own centre."""
    if subject is None:
        return _centre(base)
    cx, cy = _centre(held(subject))
    return (min(max(cx, base.x), base.x + base.w), min(max(cy, base.y), base.y + base.h))


def _ratio(num: float, den: float) -> float:
    if num <= 0:
        return 0.0
    return math.inf if den <= 0 else num / den


def _sides_cut(base: Rect, box: Rect) -> list[str]:
    eps = 1e-6
    return [name for name, out in (("left", box.x < base.x - eps),
                                   ("right", box.x + box.w > base.x + base.w + eps),
                                   ("top", box.y < base.y - eps),
                                   ("bottom", box.y + box.h > base.y + base.h + eps)) if out]


def _at_photo_edge(photo: tuple[int, int], box: Rect) -> list[str]:
    """Sides of `box` within PHOTO_EDGE of the photo's own border. A detector box there
    is CLIPPED: the person goes on past the edge of the picture, so that side is already
    cut — by the photographer — and holding it whole is not something a move can do."""
    pw, ph = photo
    tx, ty = pw * PHOTO_EDGE, ph * PHOTO_EDGE
    return [name for name, at in (("left", box.x <= tx), ("right", box.x + box.w >= pw - tx),
                                  ("top", box.y <= ty), ("bottom", box.y + box.h >= ph - ty))
            if at]


def hold_scale(base: Rect, p: tuple[float, float], box: Rect,
               open_sides: frozenset[str] = frozenset()) -> float:
    """The smallest s whose frame P + (base - P)*s still holds `box` whole, decided per
    side. A side the base frame already cuts, or one named in `open_sides` (cut by the
    photo's own edge), sets no limit. On every other side the frame keeps a gap of
    SUBJECT_MARGIN of the box's size, or half the gap the base frame had there,
    whichever is smaller — so a head 100 px under the top of the frame still lets it
    move, and a head with no room at all inside the picture does not. Every frame lies
    inside the base frame, so the answer is at most 1.0, meaning no move keeps it whole."""
    eps = 1e-6
    mx, my = box.w * SUBJECT_MARGIN, box.h * SUBJECT_MARGIN
    bx0, by0, bx1, by1 = base.x, base.y, base.x + base.w, base.y + base.h
    x0, y0, x1, y1 = box.x, box.y, box.x + box.w, box.y + box.h
    px, py = p
    need = 0.0
    if x0 >= bx0 - eps and "left" not in open_sides:
        need = max(need, _ratio(px - (x0 - min(mx, (x0 - bx0) / 2)), px - bx0))
    if x1 <= bx1 + eps and "right" not in open_sides:
        need = max(need, _ratio((x1 + min(mx, (bx1 - x1) / 2)) - px, bx1 - px))
    if y0 >= by0 - eps and "top" not in open_sides:
        need = max(need, _ratio(py - (y0 - min(my, (y0 - by0) / 2)), py - by0))
    if y1 <= by1 + eps and "bottom" not in open_sides:
        need = max(need, _ratio((y1 + min(my, (by1 - y1) / 2)) - py, by1 - py))
    return min(need, 1.0)


def ease(p: float) -> float:
    """Smoothstep: zero velocity at both ends."""
    return p * p * (3.0 - 2.0 * p)


def plan(photo: tuple[int, int], aspect: tuple[int, int], crop_scale: float,
         subject: Rect | None, composition: str, grid: str, move: StillSpec,
         n: int) -> Plan:
    """`n` frames of the move. The tight end is shortened, and the note says so, when it
    would cut the upper half of the subject; a base frame that already cuts it is noted,
    and the move still keeps whatever of it the base frame holds."""
    if n < 1:
        raise ValueError(f"a photo episode needs at least one frame, got {n}")
    base = place(photo, base_size(photo, aspect, crop_scale), subject, composition, grid)
    p = anchor(base, subject)
    a, b = move.start, move.end
    notes = []
    if subject is not None:
        h = held(subject)
        cut = _sides_cut(base, h)
        edge = _at_photo_edge(photo, h)
        if not (h.x < base.x + base.w and base.x < h.x + h.w
                and h.y < base.y + base.h and base.y < h.y + h.h):
            notes.append("the subject lies outside the frame")
        elif cut:
            notes.append(f"the base frame already cuts the subject's upper half on the "
                         f"{'/'.join(cut)}")
        if edge:
            notes.append(f"the photo's own edge cuts the subject on the {'/'.join(edge)}")
        need = hold_scale(base, p, h, frozenset(edge))
        if min(a, b) < need:
            tight = math.ceil(need * 1e4) / 1e4
            if tight >= max(a, b):
                notes.append(f"the move was cancelled: no frame tighter than the base "
                             f"keeps the subject's upper half whole (planned {a}->{b})")
            else:
                notes.append(f"the move was shortened to {tight} so the subject's upper "
                             f"half stays whole (planned {a}->{b})")
            a, b = (max(a, tight), max(b, tight))
    note = "; ".join(notes)
    frames = []
    for k in range(n):
        q = ease(k / (n - 1)) if n > 1 else 1.0
        s = a * (b / a) ** q
        frames.append(Rect(p[0] + (base.x - p[0]) * s, p[1] + (base.y - p[1]) * s,
                           base.w * s, base.h * s))
    return Plan(frames=frames, base=base, anchor=p, planned=move,
                applied=StillSpec(start=a, end=b), note=note)
