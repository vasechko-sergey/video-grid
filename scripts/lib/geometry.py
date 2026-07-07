"""Pure crop geometry for the follow algorithm (spec §6.2, §6.4, §6.5)."""

PHI = 1.618033988749895


def crop_size(canvas_w, canvas_h, src_w, src_h):
    """Largest crop of canvas aspect that fits inside the source (fill mode)."""
    if canvas_w / canvas_h <= src_w / src_h:
        h = src_h
        w = int(src_h * canvas_w / canvas_h)   # floor: 1080*9/16 -> 607 (session value)
    else:
        w = src_w
        h = int(src_w * canvas_h / canvas_w)
    return (w, h)


def grid_lines(grid):
    """(left, right) power-line fractions of frame width."""
    if grid == "thirds":
        return (1 / 3, 2 / 3)
    if grid == "phi":
        return (1 - 1 / PHI, 1 / PHI)
    raise ValueError(f"unknown grid: {grid}")


def target_frac(composition, direction, grid):
    """Fraction of the OUTPUT frame width where the subject should sit."""
    if composition == "center":
        return 0.5
    left, right = grid_lines(grid)
    if composition == "lead":
        # moving right → air ahead on the right → subject on the LEFT line
        return left if direction == "right" else right
    raise ValueError(f"unknown composition: {composition}")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def crop_x(subject_x, composition, direction, grid, crop_w, src_w):
    """Left edge of the crop window so the subject lands on its target line."""
    frac = target_frac(composition, direction, grid)
    x = round(subject_x - frac * crop_w)
    return clamp(x, 0, src_w - crop_w)
