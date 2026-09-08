"""Contact-sheet tiling (design docs/specs/2026-08-05-footage-contact-sheet-design.md,
stage 5.2b). PURE layout: RGB arrays plus label strings in, one PIL image out. No
ffmpeg, no FOOTAGE, no run-dir knowledge — the whole layout half is therefore testable
on synthetic arrays with no decode and no fixture. Sampling and I/O live in the driver
(scripts/contact_sheet.py).

Not to be confused with scripts/storyboard.py, which sheets a RENDERED episode at
delivery resolution with composition-grid overlays — a post-reframe verification tool,
downstream of every decision this module serves.
"""
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from scripts.lib import fonts

CELL_W = 300                       # thumbnail box width, px
CELL_H = round(CELL_W * 9 / 16)    # 169 — a 16:9 box; any other aspect letterboxes into it
COLS = 5
READER_LONG_SIDE = 1568            # px — the long-side budget a sheet must stay inside.
# INHERITED, NOT MEASURED (design §7.2). Past this a reader downsamples the whole
# image and the per-frame picture shrinks with it; PER_SHEET's own sizing has assumed
# this number since 2026-08-05. Nothing in this repository can observe a reader's
# image pipeline, so it cannot be measured here — which is why fit_layout maximizes
# UNDER the budget: a wrong value yields a suboptimal sheet, never a broken one.
PER_SHEET = 30                     # COLS * 6 rows: 1500 x 1218 px, inside READER_LONG_SIDE
LABEL_H = 34                       # two FONT_PX lines plus padding
FONT_PX = 13
MARK_PX = 3                        # `best` border width

_BG = (0, 0, 0)
_FG = (235, 235, 235)
_MARK = (255, 210, 0)


@dataclass(frozen=True)
class Cell:
    """One thumbnail plus its label. `image` is an HxWx3 uint8 RGB array at ANY size
    and aspect — tile() letterboxes it. `lines` renders under the thumbnail (at most
    two are drawn). `marked` draws the `best` border."""
    image: np.ndarray
    lines: tuple[str, ...]
    marked: bool = False


def _fit(arr: np.ndarray, cell_w: int, cell_h: int) -> Image.Image:
    """Contain-fit `arr` into a cell_w x cell_h black box, aspect preserved. A source
    of any aspect (a portrait phone clip beside 16:9 drone footage) lands in the SAME
    box, so the grid is never ragged and no frame is ever distorted — a stretched
    thumbnail would misinform exactly the composition judgement this sheet exists for.

    When the box already carries the content's own aspect (sheet.fit_layout picks one
    that does), the fit is exact and nothing is letterboxed."""
    im = Image.fromarray(arr).convert("RGB")
    scale = min(cell_w / im.width, cell_h / im.height)
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    box = Image.new("RGB", (cell_w, cell_h), _BG)
    box.paste(im.resize((w, h), Image.LANCZOS), ((cell_w - w) // 2, (cell_h - h) // 2))
    return box


def _truncate(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    """Shorten `text` with a trailing ellipsis until it fits `max_w` px. A long clip
    name must not bleed into the neighbouring cell: the label is the ONLY thing tying
    a thumbnail back to its window index."""
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def fit_layout(n: int, aspect: float, *, budget: int = READER_LONG_SIDE) -> tuple[int, int]:
    """(cols, cell_w) for `n` cells of `aspect` (w/h): the column count whose cell
    PICTURE is widest with the whole sheet's long side inside `budget`.

    The count is fitted rather than typed because the answer depends on both n and the
    aspect and is not monotone in either. Nine 9:16 frames want 5 columns (a 313px
    picture); one row of nine gives 174, because a single row spends the entire budget
    on width and leaves the height unused (design §2).

    The cell box carries the CONTENT's aspect, so tile's contain-fit letterboxes
    nothing — that is the point, and it is why a caller sheeting MIXED aspects
    (contact_sheet build, whose sources range from portrait phone clips to 16:9 drone
    footage) must keep the default 16:9 box instead. This is for a strip of ONE clip.

    Truncates rather than rounds the picture width, so the sheet is always <= budget
    and never one pixel past it. Ties go to the smaller column count, so the answer is
    deterministic."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"sheet.fit_layout: n must be an int >= 1, got {n!r}")
    if isinstance(aspect, bool) or not isinstance(aspect, (int, float)) or aspect <= 0:
        raise ValueError(f"sheet.fit_layout: aspect must be w/h > 0, got {aspect!r}")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError(f"sheet.fit_layout: budget must be an int >= 1, got {budget!r}")
    best_cols, best_w = 1, 0
    for cols in range(1, n + 1):
        rows = (n + cols - 1) // cols
        by_width = budget / cols                          # the sheet's width bound
        by_height = (budget / rows - LABEL_H) * aspect    # its height bound, less the label
        cell_w = int(min(by_width, by_height))
        if cell_w > best_w:
            best_cols, best_w = cols, cell_w
    if best_w < 1:
        raise ValueError(
            f"sheet.fit_layout: {n} cells of aspect {aspect:.3f} do not fit a "
            f"{budget}px budget at any column count — every layout leaves under one "
            f"pixel of picture per cell")
    return best_cols, best_w


def tile(cells: Sequence[Cell], *, cols: int = COLS,
         cell_w: int = CELL_W, cell_h: int = CELL_H) -> Image.Image:
    """Lay `cells` out left-to-right, top-to-bottom on black: cell k at column
    k % cols, row k // cols, each occupying exactly cell_w x (cell_h + LABEL_H).
    `cols` narrows to len(cells) so a short strip is not padded with empty columns.

    The box defaults to the module's 16:9 CELL_W/CELL_H, so the footage contact sheet
    is unchanged; a strip passes its own content's shape from sheet.fit_layout.

    Refuses an empty list: an image with no cells is not a contact sheet, and what an
    empty selection MEANS is the caller's call (the driver says so in SHEETS.md rather
    than writing a blank PNG)."""
    if not cells:
        raise ValueError(
            "sheet.tile: no cells — a sheet needs at least one window. The caller "
            "decides what an empty selection means; it must not become a blank PNG")
    if cols < 1:
        raise ValueError(f"sheet.tile: cols must be >= 1, got {cols}")
    if cell_w < 1 or cell_h < 1:
        raise ValueError(f"sheet.tile: cell box must be positive, got {cell_w}x{cell_h}")
    cols = min(cols, len(cells))
    rows = (len(cells) + cols - 1) // cols
    ch = cell_h + LABEL_H
    canvas = Image.new("RGB", (cols * cell_w, rows * ch), _BG)
    font = ImageFont.truetype(fonts.resolve_font(), FONT_PX)
    draw = ImageDraw.Draw(canvas)
    for k, cell in enumerate(cells):
        x, y = (k % cols) * cell_w, (k // cols) * ch
        canvas.paste(_fit(cell.image, cell_w, cell_h), (x, y))
        if cell.marked:
            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1],
                           outline=_MARK, width=MARK_PX)
        for i, line in enumerate(cell.lines[:2]):
            draw.text((x + 4, y + cell_h + 2 + i * (FONT_PX + 2)),
                      _truncate(line, font, cell_w - 8), font=font, fill=_FG)
    return canvas


def paginate(cells: Sequence[Cell], per_sheet: int = PER_SHEET) -> list[list[Cell]]:
    """Split cells into sheet-sized pages, order preserved. An empty input yields []
    — no page at all, NOT one empty page: tile() refuses an empty page, and the driver
    reports the empty case in SHEETS.md instead of writing a blank PNG."""
    if per_sheet < 1:
        raise ValueError(f"sheet.paginate: per_sheet must be >= 1, got {per_sheet}")
    return [list(cells[i:i + per_sheet]) for i in range(0, len(cells), per_sheet)]
