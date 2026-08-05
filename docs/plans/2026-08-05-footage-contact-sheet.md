# Footage Contact Sheet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the edit-plan agent its first look at real pixels — an overview
contact sheet across every FOOTAGE window, plus a zoom-in strip inside one
window — and make producing the overview a required conveyor stage.

**Architecture:** A pure tiler (`scripts/lib/sheet.py`: RGB arrays + label
strings in, one PIL image out — no ffmpeg, no FOOTAGE, no run dir) under a thin
driver (`scripts/contact_sheet.py`: sampling, batched decode via
`assembly.frames_rgb`, `sheets/*.png` + `SHEETS.md`). `montage.V1_STAGES` gains
one `required` row after `footage-intake`; `using-montage` runs it and
`edit-plan` reads it.

**Tech Stack:** Python 3.13, Pillow 12, numpy 2, pytest. Frames come from the
existing `scripts/lib/assembly.frames_rgb` batched-select decode; fonts from the
existing `scripts/lib/fonts.resolve_font`. No new dependency.

**Design spec:** [docs/specs/2026-08-05-footage-contact-sheet-design.md](../specs/2026-08-05-footage-contact-sheet-design.md)

## Global Constraints

- **Fail loud, with a remedy.** Every raise names what is wrong AND the command
  or edit that fixes it (`docs/coding-standards.md`). No silent fallbacks.
- **Imports at the top of the module.** No function-level imports except the
  documented heavy-optional-dep pattern (`ultralytics`, `torchreid`) — nothing
  in this slice qualifies.
- **Scripts run as modules**: `python -m scripts.contact_sheet ...`
  (`pythonpath = .` in `pytest.ini`). Python is `.venv/bin/python`.
- **No ffmpeg binary literals.** Anything invoking ffmpeg goes through
  `scripts/lib/ffbin`; `tests/lib/test_landmine_scan.py` AST-scans `scripts/`
  and will fail the build on a bare `"ffmpeg"` string. This slice calls **no
  ffmpeg directly** — it goes through `assembly.frames_rgb`, which already does.
- **Never `-ss`; never `lutrgb`.** The §12 landmines. `frames_rgb` uses
  `select`, so neither can apply here — do not add a seek.
- **`scripts/storyboard.py` is not modified.** Different job (grid overlays on a
  rendered episode at full resolution). Do not "unify" them.
- **`CACHE_VERSION` is not touched.** This slice adds no intake cache key. If
  you find yourself editing `scripts/lib/intake_cache.py`, stop — that is
  explicitly out of scope (design §2.1).
- **Do not install anything.** No `brew`, `pip install`, `npm`, no running
  `setup.sh`. Verification is read-only plus `pytest`.
- **Commit after every task**, message in English, body ending with
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Never
  `git commit --amend` a reviewed commit — post-review fixes are separate
  follow-up commits. Never `git push`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lib/sheet.py` *(new)* | **Pure layout.** `Cell`, `tile`, `paginate`, contain-fit, label truncation, the `best` border. Imports only PIL/numpy/`lib.fonts`. |
| `scripts/contact_sheet.py` *(new)* | **Driver.** `build_sheets` (FOOTAGE → sheets + `SHEETS.md`), `build_strip` (one window → one image), `resolve_window`, CLI with `build`/`strip` subcommands. |
| `scripts/montage.py` *(modify)* | One `Stage` row inserted after `footage-intake`. |
| `tests/lib/test_sheet.py` *(new)* | Pure-layout tests on synthetic ndarrays. No ffmpeg. |
| `tests/lib/test_contact_sheet.py` *(new)* | Driver tests with `frames_rgb` monkeypatched. No ffmpeg. |
| `tests/lib/test_montage.py` *(modify)* | Stage-table assertions + four setups that now need `SHEETS.md`. |
| `tests/integration/test_contact_sheet.py` *(new)* | Real-ffmpeg proof on the `sample_clip` fixture. |
| `skills/using-montage/SKILL.md`, `skills/edit-plan/SKILL.md` *(modify)* | Run it; read it. |
| `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `docs/fixes-backlog.md`, `docs/cinematic-quality-playbook.md` *(modify)* | Registry + status sync. |

---

### Task 0: `scripts/lib/sheet.py` — the pure tiler

**Files:**
- Create: `scripts/lib/sheet.py`
- Test: `tests/lib/test_sheet.py`

**Interfaces:**
- Consumes: `scripts.lib.fonts.resolve_font()` (existing — returns a `.ttf`/`.ttc`
  path, raises `ValueError` with a remedy when none is installed).
- Produces:
  - `Cell(image: np.ndarray, lines: tuple[str, ...], marked: bool = False)` — frozen dataclass
  - `tile(cells: Sequence[Cell], *, cols: int = COLS) -> PIL.Image.Image`
  - `paginate(cells: Sequence[Cell], per_sheet: int = PER_SHEET) -> list[list[Cell]]`
  - constants `CELL_W = 300`, `CELL_H = 169`, `COLS = 5`, `PER_SHEET = 30`,
    `LABEL_H = 34`, `FONT_PX = 13`, `MARK_PX = 3`

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_sheet.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_sheet.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'scripts.lib.sheet'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/lib/sheet.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_sheet.py -q`
Expected: PASS, 18 tests.

- [ ] **Step 5: Mutation check — prove the layout tests bite**

Temporarily change `x, y = (k % cols) * CELL_W, (k // cols) * ch` to
`x, y = (k // cols) * CELL_W, (k % cols) * ch` (transpose). Run the file.
Expected: `test_cell_k_lands_at_column_k_mod_cols_row_k_div_cols` FAILS.
**Revert the change** and re-run to confirm green.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/sheet.py tests/lib/test_sheet.py
git commit -m "feat(sheet): pure contact-sheet tiler — contain-fit cells, labels, pagination"
```

---

### Task 1: `contact_sheet.py` — the `build` overview + `SHEETS.md`

**Files:**
- Create: `scripts/contact_sheet.py`
- Test: `tests/lib/test_contact_sheet.py`

**Interfaces:**
- Consumes: `sheet.Cell` / `sheet.tile` / `sheet.paginate` (Task 0);
  `scripts.lib.footage.Footage.from_json`; `scripts.lib.assembly.frames_rgb(src, times, fps)`.
- Produces:
  - `build_sheets(footage_path: str, out_dir: str, *, best_only: bool = False) -> dict`
    returning `{"status": "written", "sheets": [str], "cells": int, "skipped": [str], "md": str}`
  - module constant `STRIP_COLS = 6` (used by Task 2)

**Context an implementer needs:**
`FootageWindow` carries `start`, `dur`, `shot_type`, `score`, `best`;
`FootageClip` carries `source` (the clip path as intake was given it), `fps`,
`windows`. `Footage.from_json` raises `ValueError` on a corrupt file.
`assembly.frames_rgb(src, times, fps)` returns a list of HxWx3 uint8 arrays
aligned to `times`, decoding once per 60-frame chunk; it raises `RuntimeError`
when a requested time is past the stream end, and the missing-file check inside
`probe_stream` raises `RuntimeError` too.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_contact_sheet.py`:

```python
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _stub_tile(sink):
    """A sheet.tile stand-in that records what it was handed and returns a throwaway
    image, so a test can assert on CELLS (labels, marks, cols) without decoding a
    real sheet."""
    def _tile(cells, **kw):
        sink(cells, kw)
        return Image.new("RGB", (10, 10))
    return _tile


def _grey_frames(src, times, fps):
    return [np.zeros((180, 320, 3), np.uint8) for _ in times]


def _win(start=0.0, dur=2.0, shot="wide", score=0.6, best=True):
    return FootageWindow(start=start, dur=dur, shot_type=shot, people=1,
                         motion=0.3, shake=0.001, description="1 person, wide, calm",
                         score=score, best=best)


def _footage(tmp_path, clips) -> str:
    f = Footage(clips=clips)
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _clip(source="a.mp4", windows=None):
    return FootageClip(source=source, dur=30.0, res=(1920, 1080), fps=30.0,
                       windows=windows if windows is not None else [_win()])


@pytest.fixture
def fake_frames(monkeypatch):
    """Replace the decode with a recorder returning a distinct grey per call, so the
    driver's sampling is observable without ffmpeg."""
    calls = []

    def _frames(src, times, fps):
        calls.append((src, list(times), fps))
        return [np.full((180, 320, 3), 10 + i, dtype=np.uint8) for i in range(len(times))]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    return calls


# ---- sampling ----

def test_one_frame_per_window_at_the_window_midpoint(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=4.0, dur=2.0),
                                            _win(start=10.0, dur=3.0)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert fake_frames == [("a.mp4", [5.0, 11.5], 30.0)]


def test_one_decode_call_per_clip(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip("a.mp4"), _clip("b.mp4")])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert [c[0] for c in fake_frames] == ["a.mp4", "b.mp4"]


def test_cells_run_in_clip_then_window_order_not_score_order(tmp_path, fake_frames):
    # window 0 scores lower than window 1: a score-ordered sheet would swap them.
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, score=0.51),
                                            _win(start=8.0, score=0.99)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert fake_frames[0][1] == [1.0, 9.0]


# ---- selection ----

def test_every_window_is_shown_by_default(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert res["cells"] == 2


def test_best_only_drops_the_rest(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), best_only=True)
    assert res["cells"] == 1
    assert fake_frames[0][1] == [1.0]


# ---- output ----

def test_writes_sheets_and_an_index_that_links_every_one(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=float(i)) for i in range(31)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert len(res["sheets"]) == 2                      # 31 cells at 30 per sheet
    md = (tmp_path / "SHEETS.md").read_text()
    for p in res["sheets"]:
        assert f"sheets/{Path(p).name}" in md
        assert Path(p).exists()
    assert "sheets/sheet_02.png" not in md              # links no sheet it did not write


def test_the_index_says_the_star_is_not_a_ranking_to_follow(tmp_path, fake_frames):
    # the scoring bias (design §1.1) is why a reader must not simply take the top of
    # the list; the index has to say so where the reader is.
    fp = _footage(tmp_path, [_clip()])
    contact_sheet.build_sheets(fp, str(tmp_path))
    md = (tmp_path / "SHEETS.md").read_text()
    assert "not a ranking to follow" in md


def test_labels_carry_the_window_index_and_the_measurements(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(c.lines for c in cells)))
    fp = _footage(tmp_path, [_clip("clips/MVI_3739.mp4",
                                   windows=[_win(start=0.0, dur=3.4, shot="medium",
                                                 score=0.71, best=True),
                                            _win(start=8.0, best=False)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert seen[0] == ("MVI_3739.mp4 #0", "medium · 3.4s · 0.71 ★")
    assert seen[1][0] == "MVI_3739.mp4 #1"
    assert "★" not in seen[1][1]


def test_best_windows_are_marked(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(c.marked for c in cells)))
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert seen == [True, False]


# ---- failure modes ----

def test_a_clip_that_will_not_decode_is_skipped_and_named(tmp_path, monkeypatch):
    def _frames(src, times, fps):
        if src == "bad.mp4":
            raise RuntimeError("bad.mp4 is missing")
        return [np.zeros((180, 320, 3), np.uint8) for _ in times]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    fp = _footage(tmp_path, [_clip("bad.mp4"), _clip("good.mp4")])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert res["skipped"] == ["bad.mp4"]
    assert res["cells"] == 1                             # good.mp4 still sheeted
    md = (tmp_path / "SHEETS.md").read_text()
    assert "Not sheeted" in md and "bad.mp4" in md and "is missing" in md


def test_no_windows_writes_an_honest_index_and_no_png(tmp_path, fake_frames):
    # an absent artifact would wedge next_action on this stage forever; an empty
    # answer is a real answer.
    fp = _footage(tmp_path, [_clip(windows=[_win(best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), best_only=True)
    assert res["sheets"] == [] and res["cells"] == 0
    assert (tmp_path / "SHEETS.md").exists()
    assert "No sheets" in (tmp_path / "SHEETS.md").read_text()
    assert not (tmp_path / "sheets").exists()


def test_a_corrupt_footage_file_fails_loud(tmp_path):
    bad = tmp_path / "FOOTAGE.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError):
        contact_sheet.build_sheets(str(bad), str(tmp_path))


# ---- CLI ----

def test_cli_build_passes_best_only(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_sheets",
                        lambda fp, out, **kw: seen.update(kw) or {"status": "written"})
    monkeypatch.setattr("sys.argv", ["contact_sheet", "build", "--footage", "F.json",
                                     "--out-dir", str(tmp_path), "--best-only"])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen == {"best_only": True}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py -q`
Expected: collection error — `ImportError: cannot import name 'contact_sheet'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/contact_sheet.py`:

```python
"""Footage contact sheets (design docs/specs/2026-08-05-footage-contact-sheet-design.md,
stage 5.2b): the edit-plan agent's first look at actual pixels.

`build` renders ONE frame per FOOTAGE window across the whole shoot -> sheets/*.png +
SHEETS.md, the artifact the router keys on. `strip` renders MANY frames inside ONE
window -> a single image, for the timing and identity questions a single frame cannot
answer. Sampling and I/O live here; the layout is pure in lib/sheet.py.

No ffmpeg argv is built here — frames come from assembly.frames_rgb, which decodes
once per 60-frame chunk with a select filter (never -ss, montage §12).
"""
import argparse
import json
import sys
from pathlib import Path

from scripts.lib import assembly, sheet
from scripts.lib.footage import Footage

STRIP_COLS = 6      # a strip reads left-to-right in time; 6 keeps the row inside the
                    # image-size limit while staying wide enough to see a motion arc.


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _label(source: str, idx: int, w) -> tuple[str, str]:
    """The two label lines of a window's cell: what it is, then how it measured."""
    star = " ★" if w.best else ""
    return (f"{Path(source).name} #{idx}",
            f"{w.shot_type} · {w.dur:.1f}s · {w.score:.2f}{star}")


def _markdown(footage: Footage, n_cells: int, written: list, skipped: list,
              *, best_only: bool) -> str:
    """The index the reader actually opens. It states the scoring bias in place,
    because the ★ column is exactly where a reader would otherwise defer to the
    ranking (design §1.1)."""
    wins = [w for c in footage.clips for w in c.windows]
    n_best = sum(1 for w in wins if w.best)
    scope = "best windows only" if best_only else "every window"
    lines = [
        f"# Contact sheets — {len(footage.clips)} clips, {len(wins)} windows "
        f"({n_best} best), {n_cells} shown ({scope})",
        "",
        "Cells run in timeline order — clip, then window index. ★ marks intake's",
        "`best` (a dedup survivor scoring >= 0.50). It is a fact to weigh, **not a",
        "ranking to follow**: the window score peaks at motion 0.35 and is zero at",
        "static, so calm, personality-forward moments rank below action even when",
        "they are the better cut.",
        "",
    ]
    for path, first, last in written:
        lines += [f"## {path.stem} — {first} … {last}", "",
                  f"![{path.stem}](sheets/{path.name})", ""]
    if not written:
        lines += ["No sheets: no window matched the selection.", ""]
    if skipped:
        lines += ["## Not sheeted", ""]
        lines += [f"- `{src}` — {err}" for src, err in skipped]
        lines += [""]
    return "\n".join(lines)


def build_sheets(footage_path: str, out_dir: str, *, best_only: bool = False) -> dict:
    """FOOTAGE.json -> <out_dir>/sheets/sheet_NN.png + <out_dir>/SHEETS.md.

    One cell per window, one frame at the window's MIDPOINT, in clip-then-index order
    — timeline order, not score order, so the eye is not led by a scorer that already
    leans toward action. Every window by default; best_only narrows.

    A clip that will not decode is skipped, named under "Not sheeted" in SHEETS.md
    with its error, and the remaining clips are still sheeted — aborting the build
    over one bad file would lose every other clip's sheet (intake's
    quarantine-and-report precedent). Skipped, never silently."""
    footage = Footage.from_json(footage_path)
    out = Path(out_dir)
    cells: list[sheet.Cell] = []
    index: list[str] = []
    skipped: list[tuple[str, str]] = []
    for clip in footage.clips:
        picked = [(i, w) for i, w in enumerate(clip.windows) if w.best or not best_only]
        if not picked:
            continue
        times = [w.start + w.dur / 2 for _, w in picked]
        try:
            frames = assembly.frames_rgb(clip.source, times, clip.fps)
        except (RuntimeError, ValueError) as ex:
            _log(f"contact-sheet: {clip.source} skipped — {ex}")
            skipped.append((clip.source, str(ex)))
            continue
        for (i, w), frame in zip(picked, frames):
            cells.append(sheet.Cell(image=frame, lines=_label(clip.source, i, w),
                                    marked=w.best))
            index.append(f"{Path(clip.source).name} #{i}")
    pages = sheet.paginate(cells)
    out.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, str, str]] = []
    at = 0
    for n, page in enumerate(pages):
        (out / "sheets").mkdir(parents=True, exist_ok=True)
        path = out / "sheets" / f"sheet_{n:02d}.png"
        sheet.tile(page).save(path)
        written.append((path, index[at], index[at + len(page) - 1]))
        at += len(page)
    md = out / "SHEETS.md"
    md.write_text(_markdown(footage, len(cells), written, skipped, best_only=best_only))
    return {"status": "written", "sheets": [str(p) for p, _, _ in written],
            "cells": len(cells), "skipped": [s for s, _ in skipped], "md": str(md)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="footage contact sheets (stage 5.2b): look before you cut")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="one frame per FOOTAGE window -> sheets + SHEETS.md")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from footage-intake")
    b.add_argument("--out-dir", required=True, help="dir for SHEETS.md + sheets/")
    b.add_argument("--best-only", action="store_true",
                   help="show only intake's `best` windows (default: every window)")
    a = ap.parse_args()
    result = build_sheets(a.footage, a.out_dir, best_only=a.best_only)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 5: Mutation check — prove the ordering test bites**

Temporarily sort `picked` by score inside `build_sheets`
(`picked.sort(key=lambda p: -p[1].score)` after the list comprehension). Run the file.
Expected: `test_cells_run_in_clip_then_window_order_not_score_order` FAILS.
**Revert** and re-run green.

- [ ] **Step 6: Commit**

```bash
git add scripts/contact_sheet.py tests/lib/test_contact_sheet.py
git commit -m "feat(contact-sheet): build the FOOTAGE overview sheets + SHEETS.md index"
```

---

### Task 2: `strip` — many frames inside one window

**Files:**
- Modify: `scripts/contact_sheet.py` (add `build_strip`, `resolve_window`, the `strip` subparser)
- Test: `tests/lib/test_contact_sheet.py` (append)

**Interfaces:**
- Consumes: `sheet.tile(cells, cols=...)`; `assembly.frames_rgb`;
  `assembly.probe_stream(path).fps`; `Footage.from_json`; `STRIP_COLS` (Task 1).
- Produces:
  - `resolve_window(footage_path: str, source: str, index: int) -> tuple[str, float, float, float]`
    returning `(clip source, start, dur, fps)`
  - `build_strip(source: str, out: str, *, start: float, dur: float, frames: int, fps: float | None = None) -> dict`
    returning `{"status": "written", "strip": str, "frames": int, "times": [float]}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_contact_sheet.py`:

```python
# ---- strip ----

def test_strip_samples_evenly_across_the_range(tmp_path, fake_frames):
    out = tmp_path / "s.png"
    res = contact_sheet.build_strip("a.mp4", str(out), start=10.0, dur=4.0,
                                    frames=4, fps=30.0)
    assert fake_frames == [("a.mp4", [10.5, 11.5, 12.5, 13.5], 30.0)]
    assert res["times"] == [10.5, 11.5, 12.5, 13.5]
    assert out.exists()


def test_strip_labels_each_cell_with_its_absolute_timestamp(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(c.lines for c in cells)))
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=10.0, dur=2.0,
                              frames=2, fps=30.0)
    assert seen == [("10.50s",), ("11.50s",)]


def test_strip_columns_cap_at_strip_cols(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0, dur=4.0,
                              frames=10, fps=30.0)
    assert seen["cols"] == contact_sheet.STRIP_COLS


def test_strip_probes_fps_when_not_given(tmp_path, fake_frames, monkeypatch):
    monkeypatch.setattr(contact_sheet.assembly, "probe_stream",
                        lambda p: type("I", (), {"fps": 60.0})())
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0, dur=1.0,
                              frames=1)
    assert fake_frames[0][2] == 60.0


def test_strip_refuses_a_non_positive_frame_count(tmp_path):
    with pytest.raises(ValueError, match="frames must be >= 1"):
        contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                  dur=1.0, frames=0, fps=30.0)


def test_strip_refuses_a_non_positive_duration(tmp_path):
    with pytest.raises(ValueError, match="dur must be > 0"):
        contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                  dur=0.0, frames=4, fps=30.0)


# ---- --window sugar ----

def test_resolve_window_returns_the_windows_own_range_and_the_clips_fps(tmp_path):
    fp = _footage(tmp_path, [_clip("clips/MVI_3739.mp4",
                                   windows=[_win(start=1.0, dur=2.0),
                                            _win(start=9.0, dur=3.0)])])
    assert contact_sheet.resolve_window(fp, "clips/MVI_3739.mp4", 1) == \
        ("clips/MVI_3739.mp4", 9.0, 3.0, 30.0)


def test_resolve_window_fails_loud_on_an_unknown_source(tmp_path):
    fp = _footage(tmp_path, [_clip("a.mp4")])
    with pytest.raises(ValueError, match="not in"):
        contact_sheet.resolve_window(fp, "typo.mp4", 0)


def test_resolve_window_fails_loud_on_an_out_of_range_index(tmp_path):
    fp = _footage(tmp_path, [_clip("a.mp4")])
    with pytest.raises(ValueError, match="out of range"):
        contact_sheet.resolve_window(fp, "a.mp4", 7)


def test_cli_strip_with_window_resolves_the_same_range_as_explicit_args(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_strip",
                        lambda src, out, **kw: seen.update({"src": src, **kw})
                        or {"status": "written"})
    fp = _footage(tmp_path, [_clip("a.mp4", windows=[_win(start=1.0, dur=2.0),
                                                     _win(start=9.0, dur=3.0)])])
    monkeypatch.setattr("sys.argv", ["contact_sheet", "strip", "--footage", fp,
                                     "--source", "a.mp4", "--window", "1",
                                     "--frames", "8", "--out", str(tmp_path / "s.png")])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen["src"] == "a.mp4" and seen["start"] == 9.0 and seen["dur"] == 3.0
    assert seen["frames"] == 8 and seen["fps"] == 30.0


def test_cli_strip_requires_a_range_or_a_window(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["contact_sheet", "strip", "--source", "a.mp4",
                                     "--out", str(tmp_path / "s.png")])
    with pytest.raises(SystemExit):
        contact_sheet.main()
    assert "--start/--dur" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py -q -k "strip or resolve_window"`
Expected: FAIL — `AttributeError: module 'scripts.contact_sheet' has no attribute 'build_strip'`.

- [ ] **Step 3: Write the implementation**

Add to `scripts/contact_sheet.py`, above `main`:

```python
def resolve_window(footage_path: str, source: str, index: int) -> tuple[str, float, float, float]:
    """(clip source, start, dur, fps) for one FOOTAGE window — the --window sugar over
    an explicit --start/--dur. A source not in FOOTAGE fails loud listing the ones that
    ARE there (build_edl's precedent for a mistyped source: a typo must not surface as
    a FileNotFound deep inside a decode)."""
    footage = Footage.from_json(footage_path)
    by_source = {c.source: c for c in footage.clips}
    clip = by_source.get(source)
    if clip is None:
        raise ValueError(f"strip: source {source!r} is not in {footage_path} — have "
                         f"{sorted(by_source)}")
    if not 0 <= index < len(clip.windows):
        raise ValueError(f"strip: window {index} out of range for {source} "
                         f"(has {len(clip.windows)})")
    w = clip.windows[index]
    return clip.source, w.start, w.dur, clip.fps


def build_strip(source: str, out: str, *, start: float, dur: float, frames: int,
                fps: float | None = None) -> dict:
    """Many frames inside ONE range -> a single image, one cell per frame labelled with
    its ABSOLUTE timestamp, so a chosen frame converts straight into a `start_offset`
    for selection.json. This is the answer to "where exactly is the peak?" that one
    midpoint frame on the overview sheet cannot give.

    Not a conveyor stage: it writes only where --out says and leaves no artifact
    behind, because it is asked for when a question arises."""
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise ValueError(f"strip: frames must be >= 1, got {frames!r}")
    if dur <= 0:
        raise ValueError(f"strip: dur must be > 0 seconds, got {dur!r}")
    rate = fps if fps is not None else assembly.probe_stream(source).fps
    times = [start + (k + 0.5) * dur / frames for k in range(frames)]
    images = assembly.frames_rgb(source, times, rate)
    cells = [sheet.Cell(image=im, lines=(f"{t:.2f}s",)) for im, t in zip(images, times)]
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.tile(cells, cols=min(frames, STRIP_COLS)).save(path)
    return {"status": "written", "strip": str(path), "frames": frames,
            "times": [round(t, 3) for t in times]}
```

Replace `main` with:

```python
def main() -> None:
    ap = argparse.ArgumentParser(
        description="footage contact sheets (stage 5.2b): look before you cut")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="one frame per FOOTAGE window -> sheets + SHEETS.md")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from footage-intake")
    b.add_argument("--out-dir", required=True, help="dir for SHEETS.md + sheets/")
    b.add_argument("--best-only", action="store_true",
                   help="show only intake's `best` windows (default: every window)")
    s = sub.add_parser("strip", help="many frames inside ONE window -> one image")
    s.add_argument("--source", required=True,
                   help="clip path, or the FOOTAGE clip source when --footage is given")
    s.add_argument("--out", required=True, help="the image to write")
    s.add_argument("--frames", type=int, default=12, help="how many frames to sample")
    s.add_argument("--start", type=float, help="range start, seconds")
    s.add_argument("--dur", type=float, help="range length, seconds")
    s.add_argument("--footage", help="FOOTAGE.json — with --window, resolves the range")
    s.add_argument("--window", type=int, help="window index into --footage's clip")
    a = ap.parse_args()
    if a.cmd == "build":
        result = build_sheets(a.footage, a.out_dir, best_only=a.best_only)
    else:
        if a.footage is not None and a.window is not None:
            src, start, dur, fps = resolve_window(a.footage, a.source, a.window)
        elif a.start is not None and a.dur is not None:
            src, start, dur, fps = a.source, a.start, a.dur, None
        else:
            ap.error("strip needs either --start/--dur or --footage with --window")
        result = build_strip(src, a.out, start=start, dur=dur, frames=a.frames, fps=fps)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)
```

- [ ] **Step 4: Run the whole driver test file**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py -q`
Expected: PASS, 25 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/contact_sheet.py tests/lib/test_contact_sheet.py
git commit -m "feat(contact-sheet): strip mode — many frames inside one window, timestamped"
```

---

### Task 3: Real-ffmpeg proof

**Files:**
- Create: `tests/integration/test_contact_sheet.py`

**Interfaces:**
- Consumes: `contact_sheet.build_sheets`, `contact_sheet.build_strip` (Tasks 1-2);
  the session fixture `sample_clip` from `tests/conftest.py` — a 3 s
  1920×1080 30 fps clip with a white box sliding left→right on dark grey.

**Context:** integration tests carry `@pytest.mark.integration` (declared in
`pytest.ini`). The `sample_clip` fixture already skips when ffmpeg does not
resolve, so no extra guard is needed. There is no filter dependency here —
`frames_rgb` uses `select`, which every ffmpeg build has, so `need_filter` is
not required.

- [ ] **Step 1: Write the tests**

Create `tests/integration/test_contact_sheet.py`:

```python
"""Real-ffmpeg proof for the footage contact sheet (design
docs/specs/2026-08-05-footage-contact-sheet-design.md). The unit tests fake the decode;
these run it, so the frames on the sheet are the frames in the clip."""
import json

import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib import sheet
from scripts.lib.footage import Footage, FootageClip, FootageWindow

pytestmark = pytest.mark.integration


def _footage(tmp_path, source: str, windows) -> str:
    f = Footage(clips=[FootageClip(source=source, dur=3.0, res=(1920, 1080), fps=30.0,
                                   windows=windows)])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _win(start, dur, best=True, shot="wide"):
    return FootageWindow(start=start, dur=dur, shot_type=shot, people=1, motion=0.3,
                         shake=0.001, description="1 person, wide, calm", score=0.7,
                         best=best)


def test_build_writes_a_real_sheet_of_the_real_frames(sample_clip, tmp_path):
    fp = _footage(tmp_path, str(sample_clip),
                  [_win(0.0, 1.0), _win(1.0, 1.0), _win(2.0, 1.0)])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert res["cells"] == 3 and res["skipped"] == []
    assert len(res["sheets"]) == 1
    img = Image.open(res["sheets"][0])
    assert img.size == (3 * sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)
    assert max(img.size) <= 1568
    md = (tmp_path / "SHEETS.md").read_text()
    assert "sheets/sheet_00.png" in md and "3 windows" in md


def test_the_sheet_carries_the_moving_box_at_three_different_places(sample_clip, tmp_path):
    # the fixture's white box slides left->right, so the three midpoint frames differ.
    # A sheet that grabbed the SAME frame three times (the failure mode a keyframe-near
    # seek would produce) puts the box at the same x in every cell.
    fp = _footage(tmp_path, str(sample_clip),
                  [_win(0.0, 1.0), _win(1.0, 1.0), _win(2.0, 1.0)])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    px = Image.open(res["sheets"][0]).convert("RGB").load()
    y = sheet.CELL_H // 2
    centres = []
    for c in range(3):
        xs = [x for x in range(c * sheet.CELL_W, (c + 1) * sheet.CELL_W)
              if px[x, y][0] > 200]
        assert xs, f"cell {c} shows no white box"
        centres.append(sum(xs) / len(xs) - c * sheet.CELL_W)
    assert centres[0] < centres[1] < centres[2]


def test_best_only_narrows_the_real_build(sample_clip, tmp_path):
    fp = _footage(tmp_path, str(sample_clip),
                  [_win(0.0, 1.0, best=True), _win(1.5, 1.0, best=False)])
    res = contact_sheet.build_sheets(fp, str(tmp_path), best_only=True)
    assert res["cells"] == 1
    assert Image.open(res["sheets"][0]).size == (sheet.CELL_W,
                                                 sheet.CELL_H + sheet.LABEL_H)


def test_a_missing_clip_is_quarantined_and_the_good_one_still_sheets(sample_clip, tmp_path):
    f = Footage(clips=[
        FootageClip(source=str(tmp_path / "gone.mp4"), dur=3.0, res=(1920, 1080),
                    fps=30.0, windows=[_win(0.0, 1.0)]),
        FootageClip(source=str(sample_clip), dur=3.0, res=(1920, 1080), fps=30.0,
                    windows=[_win(0.0, 1.0)])])
    fp = tmp_path / "FOOTAGE.json"
    fp.write_text(json.dumps(f.to_dict()))
    res = contact_sheet.build_sheets(str(fp), str(tmp_path))
    assert res["skipped"] == [str(tmp_path / "gone.mp4")]
    assert res["cells"] == 1 and len(res["sheets"]) == 1
    assert "Not sheeted" in (tmp_path / "SHEETS.md").read_text()


def test_strip_renders_the_requested_frames_in_time_order(sample_clip, tmp_path):
    out = tmp_path / "strip.png"
    res = contact_sheet.build_strip(str(sample_clip), str(out), start=0.0, dur=3.0,
                                    frames=6)
    assert res["times"] == sorted(res["times"]) and len(res["times"]) == 6
    img = Image.open(out)
    assert img.size == (6 * sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)


def test_strip_window_sugar_matches_the_explicit_range(sample_clip, tmp_path):
    fp = _footage(tmp_path, str(sample_clip), [_win(0.0, 1.0), _win(1.0, 1.5)])
    src, start, dur, fps = contact_sheet.resolve_window(fp, str(sample_clip), 1)
    a = contact_sheet.build_strip(src, str(tmp_path / "a.png"), start=start, dur=dur,
                                  frames=4, fps=fps)
    b = contact_sheet.build_strip(str(sample_clip), str(tmp_path / "b.png"), start=1.0,
                                  dur=1.5, frames=4)
    assert a["times"] == b["times"]
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_contact_sheet.py -q`
Expected: PASS, 6 tests (or SKIPPED if ffmpeg does not resolve on this box).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_contact_sheet.py
git commit -m "test(contact-sheet): real-ffmpeg proof that the sheet shows the real frames"
```

---

### Task 4: The router — a required stage after `footage-intake`

**Files:**
- Modify: `scripts/montage.py:39-67` (the `V1_STAGES` tuple)
- Modify: `tests/lib/test_montage.py`

**Interfaces:**
- Consumes: the existing `Stage` dataclass (`key`, `artifact`, `kind`, `runner`,
  `checkpoint`, `in_out`) — no code change to `next_action`; the new stage is data.
- Produces: `V1_STAGES` with `"contact-sheet"` at index 2.

**Why the tests below change:** `next_action` returns the FIRST required stage
whose artifact is missing. Four existing tests build a run with `project.json`
+ `FOOTAGE.json` and assert `next == "edit-plan"`; with a required
`contact-sheet` in between, `next` is now `contact-sheet` until `SHEETS.md`
exists. Those setups gain a `SHEETS.md` touch — the assertion they were
written to make (an optional stage never blocks) is preserved exactly.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_montage.py`, replace the body of `test_v1_stages_order_and_keys`:

```python
def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "contact-sheet", "reel-brief", "trend-scan",
        "edit-plan", "music-and-mood", "pacing", "match-grade", "assemble-draft", "titles",
        "deliver", "reel-review"]
```

Add to `test_v1_stages_kinds_and_flags` (anywhere in its body):

```python
    assert by["contact-sheet"].kind == "required"
    assert by["contact-sheet"].artifact == "SHEETS.md"
    assert by["contact-sheet"].checkpoint is None
    assert by["contact-sheet"].in_out is False
```

Append these new tests at the end of the file:

```python
# ---- contact-sheet required before edit-plan (design 2026-08-05 §6) ----

def test_footage_without_sheets_asks_for_the_contact_sheet(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    assert next_action(str(tmp_path))["next"] == "contact-sheet"


def test_the_sheet_unblocks_edit_plan(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    _touch(tmp_path, "SHEETS.md")
    res = next_action(str(tmp_path))
    assert res["next"] == "edit-plan"
    assert _state(res, "contact-sheet") == "done"


def test_the_sheet_comes_after_the_footage_it_sheets_and_before_the_cut():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("footage-intake") < keys.index("contact-sheet")
    assert keys.index("contact-sheet") < keys.index("edit-plan")


def test_no_footage_still_asks_for_intake_first(tmp_path):
    # the sheet is not reachable before the FOOTAGE it reads
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "SHEETS.md")
    assert next_action(str(tmp_path))["next"] == "footage-intake"
```

Patch the four existing setups so they keep testing what they were written to
test. In `test_music_optional_absent_then_present`,
`test_pacing_optional_absent_then_present`, and
`test_a_run_with_footage_but_no_edl_asks_for_edit_plan_not_music`, add the
sheet artifact right after the `FOOTAGE.json` line:

```python
    _touch(tmp_path, "SHEETS.md")     # contact-sheet is required and comes first
```

In `test_a_run_with_footage_but_no_edl_asks_for_edit_plan_not_music` the file
uses raw writes rather than `_touch`; add the matching line:

```python
    (tmp_path / "SHEETS.md").write_text("{}")
```

- [ ] **Step 2: Run to verify the new ones fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: FAIL — `test_v1_stages_order_and_keys` mismatch (no `contact-sheet`
in the list), `KeyError: 'contact-sheet'`, and the four `next` assertions.

- [ ] **Step 3: Insert the stage**

In `scripts/montage.py`, insert between the `footage-intake` and `reel-brief`
rows of `V1_STAGES`:

```python
    # required, not optional (design 2026-08-05 §2.5): a run must not reach the cut
    # having never produced one frame of the footage it is about to cut. It gates the
    # PRESENCE of the sensor, not its use — see the design's §9 honest limit.
    Stage("contact-sheet", "SHEETS.md", "required",
          "contact_sheet build CLI (run by using-montage; edit-plan reads the sheets)",
          None),
```

- [ ] **Step 4: Run the router tests**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite for collateral damage**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS; the only pre-existing skips are demucs, the iTunes network
test, and the weights-gated reID test. If anything else fails, it is a real
break in this task — fix it here, do not defer it.

- [ ] **Step 6: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat(montage): contact-sheet becomes a required stage between intake and edit-plan"
```

---

### Task 5: Skills and docs sync

**Files:**
- Modify: `skills/using-montage/SKILL.md`
- Modify: `skills/edit-plan/SKILL.md`
- Modify: `CLAUDE.md` (Quick Reference table)
- Modify: `docs/build-status.md`
- Modify: `docs/pipeline-map.md`
- Modify: `docs/fixes-backlog.md` (#12)
- Modify: `docs/cinematic-quality-playbook.md` (§4 priority 3)

**Interfaces:**
- Consumes: the CLI surface from Tasks 1-2 and the stage key from Task 4.
- Produces: no code. Documentation must state the §9 honest limit, not a stronger claim.

**Context on skill call sites — two different conventions, do not mix them:**

- `using-montage` is one of the six **runner** skills. It resolves the launcher
  once in its preamble (`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"`)
  and issues every command as `"$VG" scripts.X ...` — **no `-m`**, `bin/vg`
  takes the module name directly. Its stages are entries in a numbered list,
  not `###` headings.
- `edit-plan` is **not** a runner skill; it documents commands in the
  `python -m scripts.edit_plan build ...` form. Match the file you are editing.
- `tests/test_skill_convention.py` fails the build on any skill containing
  `.venv/bin/python`, and on a runner skill that loses `bin/vg` or the
  recorded-root line. Run it after editing.

- [ ] **Step 1: `using-montage` — run it and look**

In `skills/using-montage/SKILL.md`, insert a new numbered step directly after
the footage-intake step (renumbering the ones below it), in the same shape as
its neighbours:

```markdown
N. **contact-sheet** — if `next`. `"$VG" scripts.contact_sheet build
   --footage <run>/FOOTAGE.json --out-dir <run>`. Then **read every sheet it
   wrote** — `SHEETS.md` links them. This is the only point in the conveyor
   where you see the raw footage; every later stage works from your reading of
   it, so a skipped look is a guess propagated through the whole reel. The
   sheets do not replace `FOOTAGE.md` — the table carries the numbers, the
   sheets carry what the numbers cannot say. Read both, and offer the sheets
   to the user at CP1 alongside the brief.
```

- [ ] **Step 2: `edit-plan` — read it before selecting**

In `skills/edit-plan/SKILL.md`, add to the **Inputs** list:

```markdown
- **`SHEETS.md` + `sheets/*.png`** (required, from contact-sheet) — one
  thumbnail per window, in timeline order. **Read every sheet before you
  select.** `shot_type` is bbox area and `description` is three generated
  tokens; neither can tell you whether a moment has a face, a laugh, or a
  story. The frames can.
```

And to **Procedure** step 1 (Recon), append:

```markdown
   Read `SHEETS.md` and every sheet it links. When a window's exact in-point
   matters — the peak of a manoeuvre, the frame a person turns to camera —
   zoom in before deciding:

       python -m scripts.contact_sheet strip --footage FOOTAGE.json \
         --source MVI_3739.mp4 --window 2 --frames 12 --out w2.png

   Each cell is labelled with its absolute timestamp; subtract the window's
   start to get the `start_offset` for that frame.
```

In step 2, after "Pick the best windows (they are already ranked)", add:

```markdown
   The ranking is not the answer. The window score peaks at motion 0.35 and is
   zero at static, so a calm, personality-forward moment ranks below action
   even when it is the better cut. Pick from what the sheets show.
```

- [ ] **Step 3: `CLAUDE.md` — two registry rows**

Insert after the intake frame-grab batch rows:

```markdown
| Footage contact-sheet design | [2026-08-05-footage-contact-sheet-design.md](docs/specs/2026-08-05-footage-contact-sheet-design.md) | P3 slice S1 (#12 look-don't-guess): the edit-plan agent's first look at pixels — `lib/sheet.py` pure tiler + `contact_sheet.py` `build` (one frame per window, timeline order, **all** windows by default) / `strip` (many frames in ONE window). A separate pass after intake, NOT inside it (a cache bump would cost a full re-scan). `SHEETS.md` is a **required** stage between intake and edit-plan. §1.1 records the scoring bias that makes the ranking untrustworthy (`_motion_fit` is zero at static) — fixing it is S3. §9 is the honest half: the stage gates the sensor's PRESENCE, never proof that anyone looked. |
| Footage contact-sheet plan | [2026-08-05-footage-contact-sheet.md](docs/plans/2026-08-05-footage-contact-sheet.md) | Tasks 0–5: `lib/sheet.py` tiler, `build` + `SHEETS.md` + quarantine, `strip` + `--window` sugar, real-ffmpeg proof, the required `V1_STAGES` row + four patched router setups, skills/docs sync. |
```

- [ ] **Step 4: `docs/build-status.md` + `docs/pipeline-map.md`**

In `build-status.md`, add the slice to the Done list with its date and both
doc paths, in the same shape as the entry above it, and update the "next
action" line to name the next P3 slice (S2+S3, mood presets + shot variety).

In `pipeline-map.md`, add a `5.2b contact-sheet` row between `5.2
footage-intake` and `5.7 edit-plan`, marked ✅ with the artifact `SHEETS.md`
and the note "required; overview sheet + `strip` zoom".

- [ ] **Step 5: `docs/fixes-backlog.md` #12 and the playbook**

Rewrite #12's status line to:

```markdown
**Status:** ◐ PARTIALLY LANDED 2026-08-05 (the selection half) — design
`docs/specs/2026-08-05-footage-contact-sheet-design.md` + plan
`docs/plans/2026-08-05-footage-contact-sheet.md`. `contact_sheet build` is now
a **required** stage between footage-intake and edit-plan: a run cannot reach
the cut without having produced a contact sheet of every window, and
`contact_sheet strip` answers the timing/identity questions a single frame
cannot. The edit-plan skill reads both. **What this does NOT do** (design §9):
it gates the PRESENCE of the sensor, not its use — no mechanism can prove an
agent looked at an image it was handed. The remaining half is the per-episode
QC agent (#3), which judges rendered frames rather than merely producing them.
```

In `docs/cinematic-quality-playbook.md` §4, mark priority 3's first component
landed and leave #19/#3/#14 open, naming this slice's spec and plan.

- [ ] **Step 6: Verify docs and skills still lint**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py tests/lib/test_lint.py tests/test_plugin_manifests.py -q`
Expected: PASS.

- [ ] **Step 7: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS with only the three known environmental skips.

- [ ] **Step 8: Commit**

```bash
git add skills/using-montage/SKILL.md skills/edit-plan/SKILL.md CLAUDE.md \
        docs/build-status.md docs/pipeline-map.md docs/fixes-backlog.md \
        docs/cinematic-quality-playbook.md
git commit -m "docs(contact-sheet): registry rows, backlog #12 partial-landing, skills read the sheets"
```

---

## Self-review notes

**Spec coverage.** §2.1 separate pass → Task 1 (no `intake_cache` touch,
Global Constraints). §2.2 two modes → Tasks 1-2. §2.3 timeline order → Task 1
Step 5 mutation check. §2.4 all-by-default → Task 1
`test_every_window_is_shown_by_default`. §2.5 required stage → Task 4. §2.6 no
new skill → Task 5 wires the two existing ones. §2.7 storyboard untouched →
Global Constraints. §3 boundary → Tasks 0-1 file split. §4.1 midpoint +
one-decode-per-clip → Task 1 tests 1-2. §4.2 label + star → Task 1. §4.3
outputs → Task 1. §5 strip incl. the `--source` dual meaning → Task 2
`resolve_window`. §6 wiring → Tasks 4-5. §7 all four failure modes → Task 1
(bad clip, empty set, corrupt FOOTAGE) and Task 0 (`resolve_font` raises). §8
tests → Tasks 0, 1, 2, 3, 4. §9 honest limits → Task 5 Step 5 wording. §10
deferrals → nothing implemented, nothing claimed.

**No `next_action` code change** is required — the stage is data in an existing
table, which is why Task 4 has no implementation step beyond the tuple insert.
