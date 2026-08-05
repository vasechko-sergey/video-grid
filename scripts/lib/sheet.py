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
PER_SHEET = 30                     # COLS * 6 rows: 1500 x 1218 px, inside the 1568 limit
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


def _fit(arr: np.ndarray) -> Image.Image:
    """Contain-fit `arr` into a CELL_W x CELL_H black box, aspect preserved. A source
    of any aspect (a portrait phone clip beside 16:9 drone footage) lands in the SAME
    box, so the grid is never ragged and no frame is ever distorted — a stretched
    thumbnail would misinform exactly the composition judgement this sheet exists for."""
    im = Image.fromarray(arr).convert("RGB")
    scale = min(CELL_W / im.width, CELL_H / im.height)
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    box = Image.new("RGB", (CELL_W, CELL_H), _BG)
    box.paste(im.resize((w, h), Image.LANCZOS), ((CELL_W - w) // 2, (CELL_H - h) // 2))
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


def tile(cells: Sequence[Cell], *, cols: int = COLS) -> Image.Image:
    """Lay `cells` out left-to-right, top-to-bottom on black: cell k at column
    k % cols, row k // cols, each occupying exactly CELL_W x (CELL_H + LABEL_H).
    `cols` narrows to len(cells) so a short strip is not padded with empty columns.

    Refuses an empty list: an image with no cells is not a contact sheet, and what an
    empty selection MEANS is the caller's call (the driver says so in SHEETS.md rather
    than writing a blank PNG)."""
    if not cells:
        raise ValueError(
            "sheet.tile: no cells — a sheet needs at least one window. The caller "
            "decides what an empty selection means; it must not become a blank PNG")
    if cols < 1:
        raise ValueError(f"sheet.tile: cols must be >= 1, got {cols}")
    cols = min(cols, len(cells))
    rows = (len(cells) + cols - 1) // cols
    ch = CELL_H + LABEL_H
    canvas = Image.new("RGB", (cols * CELL_W, rows * ch), _BG)
    font = ImageFont.truetype(fonts.resolve_font(), FONT_PX)
    draw = ImageDraw.Draw(canvas)
    for k, cell in enumerate(cells):
        x, y = (k % cols) * CELL_W, (k // cols) * ch
        canvas.paste(_fit(cell.image), (x, y))
        if cell.marked:
            draw.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1],
                           outline=_MARK, width=MARK_PX)
        for i, line in enumerate(cell.lines[:2]):
            draw.text((x + 4, y + CELL_H + 2 + i * (FONT_PX + 2)),
                      _truncate(line, font, CELL_W - 8), font=font, fill=_FG)
    return canvas


def paginate(cells: Sequence[Cell], per_sheet: int = PER_SHEET) -> list[list[Cell]]:
    """Split cells into sheet-sized pages, order preserved. An empty input yields []
    — no page at all, NOT one empty page: tile() refuses an empty page, and the driver
    reports the empty case in SHEETS.md instead of writing a blank PNG."""
    if per_sheet < 1:
        raise ValueError(f"sheet.paginate: per_sheet must be >= 1, got {per_sheet}")
    return [list(cells[i:i + per_sheet]) for i in range(0, len(cells), per_sheet)]
