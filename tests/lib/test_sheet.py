import numpy as np
import pytest

from scripts.lib import sheet
from scripts.lib.sheet import Cell


def _arr(w: int, h: int, value: int = 128) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def _cells(n: int, **kw) -> list[Cell]:
    return [Cell(image=_arr(320, 180), lines=(f"clip #{i}", "wide · 2.0s · 0.60"), **kw)
            for i in range(n)]


# ---- geometry ----

def test_one_cell_sheet_is_one_cell_box_plus_its_label():
    img = sheet.tile(_cells(1))
    assert img.size == (sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)


def test_a_full_sheet_is_cols_wide_and_ceil_rows_tall():
    img = sheet.tile(_cells(sheet.PER_SHEET))
    rows = sheet.PER_SHEET // sheet.COLS
    assert img.size == (sheet.COLS * sheet.CELL_W,
                        rows * (sheet.CELL_H + sheet.LABEL_H))


def test_a_partial_last_row_still_gets_a_whole_row():
    img = sheet.tile(_cells(6))            # 5 + 1 -> two rows
    assert img.size == (sheet.COLS * sheet.CELL_W,
                        2 * (sheet.CELL_H + sheet.LABEL_H))


def test_fewer_cells_than_cols_narrows_the_canvas():
    img = sheet.tile(_cells(3))
    assert img.size == (3 * sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)


def test_cols_is_honoured_for_the_strip_layout():
    img = sheet.tile(_cells(6), cols=3)
    assert img.size == (3 * sheet.CELL_W, 2 * (sheet.CELL_H + sheet.LABEL_H))


def test_a_full_sheet_fits_inside_the_image_size_limit():
    # 1568px is where a viewer downsamples the image; past it the labels that tie a
    # thumbnail to its window index stop being legible (design §3).
    img = sheet.tile(_cells(sheet.PER_SHEET))
    assert max(img.size) <= 1568


# ---- contain-fit ----

def test_cell_k_lands_at_column_k_mod_cols_row_k_div_cols():
    # only cell 7 is white: with cols=5 it must sit at column 2 of row 1. Index 7 is
    # chosen deliberately — for k=6 a transposed (k//cols, k%cols) lands on the SAME
    # square, so a 6 here would let the bug through.
    cells = [Cell(image=_arr(300, 169, 0), lines=("x",)) for _ in range(10)]
    cells[7] = Cell(image=_arr(300, 169, 255), lines=("x",))
    px = sheet.tile(cells).load()
    x = 2 * sheet.CELL_W + sheet.CELL_W // 2
    y = 1 * (sheet.CELL_H + sheet.LABEL_H) + sheet.CELL_H // 2
    assert px[x, y] == (255, 255, 255)
    assert px[sheet.CELL_W // 2, sheet.CELL_H // 2] == (0, 0, 0)


def test_a_portrait_source_letterboxes_without_distortion():
    # a 9:16 frame in a 16:9 box keeps its aspect: white pillar centred on black.
    img = sheet.tile([Cell(image=_arr(180, 320, 255), lines=("x",))])
    px = img.load()
    assert px[sheet.CELL_W // 2, sheet.CELL_H // 2] == (255, 255, 255)   # centre: image
    assert px[1, sheet.CELL_H // 2] == (0, 0, 0)                          # edge: padding


def test_a_wider_than_16_9_source_letterboxes_top_and_bottom():
    img = sheet.tile([Cell(image=_arr(400, 100, 255), lines=("x",))])
    px = img.load()
    assert px[sheet.CELL_W // 2, sheet.CELL_H // 2] == (255, 255, 255)
    assert px[sheet.CELL_W // 2, 1] == (0, 0, 0)


# ---- labels + marks ----

def test_an_overlong_label_is_truncated_not_bled_into_the_neighbour():
    long = "M" * 400
    img = sheet.tile([Cell(image=_arr(320, 180, 0), lines=(long,)),
                      Cell(image=_arr(320, 180, 0), lines=("",))])
    px = img.load()
    # the label band of cell 1 (x in [CELL_W, 2*CELL_W)) must be untouched black
    band = [px[x, sheet.CELL_H + sheet.LABEL_H // 2]
            for x in range(sheet.CELL_W + 2, 2 * sheet.CELL_W - 2)]
    assert set(band) == {(0, 0, 0)}


def test_only_the_first_two_label_lines_are_drawn():
    two = sheet.tile([Cell(image=_arr(320, 180, 0), lines=("aaa", "bbb"))])
    three = sheet.tile([Cell(image=_arr(320, 180, 0), lines=("aaa", "bbb", "ccc"))])
    assert two.tobytes() == three.tobytes()


def test_marked_draws_a_border_and_leaves_the_thumbnail_centre_alone():
    plain = sheet.tile([Cell(image=_arr(320, 180, 100), lines=("x",))])
    marked = sheet.tile([Cell(image=_arr(320, 180, 100), lines=("x",), marked=True)])
    assert plain.tobytes() != marked.tobytes()
    assert marked.load()[sheet.CELL_W // 2, sheet.CELL_H // 2] == (100, 100, 100)


# ---- refusals + pagination ----

def test_tile_refuses_an_empty_cell_list():
    with pytest.raises(ValueError, match="needs at least one window"):
        sheet.tile([])


def test_tile_refuses_a_non_positive_cols():
    with pytest.raises(ValueError, match="cols must be >= 1"):
        sheet.tile(_cells(2), cols=0)


def test_paginate_splits_on_the_page_size():
    assert [len(p) for p in sheet.paginate(_cells(31))] == [sheet.PER_SHEET, 1]
    assert [len(p) for p in sheet.paginate(_cells(30))] == [sheet.PER_SHEET]


def test_paginate_of_nothing_is_no_pages_not_one_blank_page():
    assert sheet.paginate([]) == []


def test_paginate_refuses_a_non_positive_page_size():
    with pytest.raises(ValueError, match="per_sheet must be >= 1"):
        sheet.paginate(_cells(2), per_sheet=0)


# ---- determinism ----

def test_tiling_the_same_cells_twice_is_byte_identical():
    cells = _cells(7)
    assert sheet.tile(cells).tobytes() == sheet.tile(cells).tobytes()
