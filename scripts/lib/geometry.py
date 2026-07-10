"""Pure crop geometry for the follow algorithm (spec §6.2, §6.4, §6.5)."""
from typing import TypeVar

_Num = TypeVar("_Num", int, float)

PHI = 1.618033988749895


def even(n: float) -> int:
    """Floor to an even int. Odd dimensions + yuv420p make libx264 fail with
    'width not divisible by 2' (spec §12) — and floor-truncated crop widths
    are odd half the time."""
    i = int(round(n))
    return i - (i % 2)


def crop_for(aspect: tuple[int, int], scale: float, src_w: int, src_h: int) -> tuple[int, int]:
    """Largest crop of `aspect` that fits the source, times `scale`.

    NOT forced even: ffmpeg's crop filter takes odd sizes, and `fill` genuinely
    cuts 405px wide today. Evenness constrains what is scaled and encoded, and
    is applied at the output.
    """
    aw, ah = aspect
    if aw <= 0 or ah <= 0:
        raise ValueError(f"crop aspect must be positive, got {aspect!r} — "
                         "pass 'canvas', 'source', or a (w, h) pair of positive ints")
    if not 0.0 < scale <= 1.0:
        raise ValueError(f"crop_scale must be in (0.0, 1.0], got {scale!r} — "
                         "1.0 is the largest crop of this aspect that fits the source")
    if aw / ah <= src_w / src_h:
        h = src_h
        w = int(src_h * aw / ah)
    else:
        w = src_w
        h = int(src_w * ah / aw)
    return (int(w * scale), int(h * scale))


def freedom(crop_w: int, src_w: int) -> int:
    """Horizontal room the crop can travel in. Zero ⇒ nobody controls composition."""
    if crop_w > src_w:
        raise ValueError(f"crop {crop_w}px is wider than the source {src_w}px — "
                         "crop_for() clamps to the source, so this is a caller bug")
    return src_w - crop_w


def crop_size(canvas_w: float, canvas_h: float, src_w: int, src_h: int) -> tuple[int, int]:
    """Largest crop of canvas aspect that fits inside the source (fill mode)."""
    return crop_for((int(canvas_w), int(canvas_h)), 1.0, src_w, src_h)


def grid_lines(grid: str) -> tuple[float, float]:
    """(left, right) power-line fractions of frame width."""
    if grid == "thirds":
        return (1 / 3, 2 / 3)
    if grid == "phi":
        return (1 - 1 / PHI, 1 / PHI)
    raise ValueError(f"unknown grid: {grid}")


def target_frac(composition: str, direction: str, grid: str) -> float:
    """Fraction of the OUTPUT frame width where the subject should sit."""
    if composition == "center":
        return 0.5
    left, right = grid_lines(grid)
    if composition == "lead":
        # moving right → air ahead on the right → subject on the LEFT line
        return left if direction == "right" else right
    raise ValueError(f"unknown composition: {composition}")


def clamp(v: _Num, lo: _Num, hi: _Num) -> _Num:
    return max(lo, min(hi, v))


def crop_x(subject_x: float, composition: str, direction: str, grid: str,
           crop_w: int, src_w: int) -> int:
    """Left edge of the crop window so the subject lands on its target line."""
    frac = target_frac(composition, direction, grid)
    x = round(subject_x - frac * crop_w)
    return clamp(x, 0, src_w - crop_w)


def crop_y(subject_y: float, crop_h: int, src_h: int) -> int:
    """Static per-episode Y (spec §6.4): no head data in v1, so put the
    subject centre at 0.45*crop_h (slightly above centre = headroom canon).
    No Y freedom (crop_h == src_h) → 0."""
    if crop_h >= src_h:
        return 0
    return clamp(round(subject_y - 0.45 * crop_h), 0, src_h - crop_h)
