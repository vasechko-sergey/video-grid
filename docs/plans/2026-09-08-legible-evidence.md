# Legible Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop handing a judge evidence it cannot judge from, and stop letting an
unstated contract cost a whole judging round.

**Architecture:** Four independent halves of one thesis
([design](../specs/2026-09-08-legible-evidence-design.md)). A new pure
`sheet.fit_layout` sizes a strip against its content's aspect and a stated reader
budget; `episode_qc`'s packet records the pixel size of what it hands over and
names the strip it never named; `build_qc` collects every validation complaint in
one pass instead of raising on the first; `intake.surface_crops` picks the
cluster's largest crop as its picture while the descriptor stays the centroid; and
the judge template names both the gates it never named and the extraction six of
eight judges already performed by hand.

**Tech Stack:** Python 3.12, PIL, numpy, pytest. No new dependency. No ffmpeg
argv is built by any code this plan touches.

---

## Global Constraints

Every task below inherits these. They are not suggestions.

- **Never run an installer.** No `brew`, `pip install`, `apt`, `npm`, `uv pip`,
  no `bash setup.sh`. The environment is already provisioned. If something
  appears missing, report it — do not install it.
- **Never discard work with git.** `git checkout --`, `git restore`,
  `git reset --hard` and `git stash` are forbidden. To restore committed
  content use `git show HEAD:<path> > <path>`; when the file you are about to
  mutate is **uncommitted**, save your own copy first
  (`cp <path> <path>.bak`) and restore from that.
- **Run Python as a module** through the repo venv: `.venv/bin/python -m pytest …`.
  `pythonpath = .` is set in `pytest.ini`; scripts are modules
  (`scripts.contact_sheet`, never `scripts/contact_sheet.py`).
- **A mutation battery runs under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit
  can match the previous file's size and mtime-second, and CPython then serves
  the stale `.pyc` — a row reads as non-discriminating when it never ran.
- **zsh does not word-split an unquoted variable.** A pytest selection built in a
  shell variable arrives as ONE argument and prints `no tests ran`, which reads
  exactly like a non-discriminating row. Pass selections literally.
- **Commit after each task**, with the message given in that task's last step.
  Never `git commit --amend`; a follow-up fix is a follow-up commit.
- The design's section numbers (`§2`, `§7.3`, …) refer to
  [2026-09-08-legible-evidence-design.md](../specs/2026-09-08-legible-evidence-design.md).

---

### Task 1: `sheet.fit_layout` and an explicit cell box

**Files:**
- Modify: `scripts/lib/sheet.py`
- Test: `tests/lib/test_sheet.py`

`sheet.tile` serves two callers with opposite needs — `contact_sheet build`
sheets 16:9 source footage at a fixed 5 columns, and `build_strip` sheets one
delivered clip of whatever aspect the project chose. This task makes the cell box
a parameter defaulting to today's values (so `build` is byte-identical) and adds
the pure function that chooses a layout for a strip.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_sheet.py`:

```python
# ---- fit_layout ----

def test_fit_layout_beats_a_single_row_for_portrait_content():
    # Nine 9:16 frames: 5x2 gives a 313px-wide picture; one row of nine gives 174,
    # because a single row spends the whole budget on width and leaves the height
    # unused. The column count is FITTED, not typed (design §2).
    cols, cell_w = sheet.fit_layout(9, 9 / 16)
    assert (cols, cell_w) == (5, 313)


def test_fit_layout_answers_each_aspect_from_the_same_function():
    assert sheet.fit_layout(9, 16 / 9) == (3, 522)
    assert sheet.fit_layout(9, 1.0) == (3, 488)
    assert sheet.fit_layout(6, 9 / 16) == (3, 421)


def test_a_fitted_sheet_lands_inside_the_reader_budget():
    for n, aspect in ((9, 9 / 16), (9, 16 / 9), (9, 1.0), (6, 9 / 16), (1, 9 / 16),
                      (12, 4 / 3), (30, 9 / 16)):
        cols, cell_w = sheet.fit_layout(n, aspect)
        cell_h = round(cell_w / aspect)
        img = sheet.tile([Cell(image=_arr(cell_w, cell_h), lines=("x",))] * n,
                         cols=cols, cell_w=cell_w, cell_h=cell_h)
        assert max(img.size) <= sheet.READER_LONG_SIDE, (n, aspect, img.size)


def test_fit_layout_refuses_a_non_positive_cell_count():
    with pytest.raises(ValueError, match="n must be an int >= 1"):
        sheet.fit_layout(0, 9 / 16)


def test_fit_layout_refuses_a_bool_cell_count():
    with pytest.raises(ValueError, match="n must be an int >= 1"):
        sheet.fit_layout(True, 9 / 16)


def test_fit_layout_refuses_a_non_positive_aspect():
    with pytest.raises(ValueError, match="aspect must be w/h > 0"):
        sheet.fit_layout(9, 0.0)


def test_fit_layout_refuses_a_budget_nothing_fits_in():
    with pytest.raises(ValueError, match="do not fit"):
        sheet.fit_layout(9, 9 / 16, budget=30)


# ---- the cell box is a parameter with an identity default ----

def test_tile_defaults_are_byte_identical_to_the_explicit_box():
    a = sheet.tile(_cells(7))
    b = sheet.tile(_cells(7), cell_w=sheet.CELL_W, cell_h=sheet.CELL_H)
    assert a.tobytes() == b.tobytes()


def test_an_explicit_box_shaped_like_the_content_letterboxes_nothing():
    # A 9:16 frame in a 9:16 box fills it edge to edge; the same frame in the
    # default 16:9 box uses 95 of 300 columns (design §0.1).
    frame = _arr(180, 320, value=200)
    fitted = sheet.tile([Cell(image=frame, lines=("t",))], cell_w=180, cell_h=320)
    assert fitted.getpixel((2, 2)) == (200, 200, 200)
    assert fitted.getpixel((177, 317)) == (200, 200, 200)
    default = sheet.tile([Cell(image=frame, lines=("t",))])
    assert default.getpixel((2, 2)) == (0, 0, 0)          # black padding at the edge
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_sheet.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.sheet' has no attribute 'fit_layout'`,
and `tile() got an unexpected keyword argument 'cell_w'`.

- [ ] **Step 3: Add the budget constant and point `PER_SHEET` at it**

In `scripts/lib/sheet.py`, replace the `PER_SHEET` line with:

```python
READER_LONG_SIDE = 1568            # px — the long-side budget a sheet must stay inside.
# INHERITED, NOT MEASURED (design §7.2). Past this a reader downsamples the whole
# image and the per-frame picture shrinks with it; PER_SHEET's own sizing has assumed
# this number since 2026-08-05. Nothing in this repository can observe a reader's
# image pipeline, so it cannot be measured here — which is why fit_layout maximizes
# UNDER the budget: a wrong value yields a suboptimal sheet, never a broken one.
PER_SHEET = 30                     # COLS * 6 rows: 1500 x 1218 px, inside READER_LONG_SIDE
```

- [ ] **Step 4: Add `fit_layout`**

Insert into `scripts/lib/sheet.py`, immediately after `_truncate` and before `tile`:

```python
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
```

- [ ] **Step 5: Make the cell box a parameter of `_fit` and `tile`**

Replace `_fit`'s signature and body in `scripts/lib/sheet.py`:

```python
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
```

Then in `tile`, change the signature and the four places that read the constants:

```python
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
```

- [ ] **Step 6: Point the existing limit test at the named constant**

In `tests/lib/test_sheet.py`, replace the body of
`test_a_full_sheet_fits_inside_the_image_size_limit`:

```python
def test_a_full_sheet_fits_inside_the_image_size_limit():
    # READER_LONG_SIDE is where a viewer downsamples the image; past it the labels
    # that tie a thumbnail to its window index stop being legible (design §7.2).
    img = sheet.tile(_cells(sheet.PER_SHEET))
    assert max(img.size) <= sheet.READER_LONG_SIDE
```

- [ ] **Step 7: Run the module's tests**

Run: `.venv/bin/python -m pytest tests/lib/test_sheet.py -q`
Expected: PASS, all of them.

- [ ] **Step 8: Prove the contact sheet did not move**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py tests/integration/test_contact_sheet.py -q`
Expected: PASS except the one strip test Task 2 rewrites
(`test_strip_columns_cap_at_strip_cols` still passes here — `STRIP_COLS` is untouched
in this task). If any `build`-side test fails, the identity default is wrong: stop and
fix it rather than adjusting the test.

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/sheet.py tests/lib/test_sheet.py
git commit -m "feat(sheet): fit_layout, and a cell box that can carry the content's shape

CELL_H is a 16:9 box; a delivered reel is 9:16, so 68% of every strip cell is
black padding. tile/_fit take the box as a parameter defaulting to today's
values (contact_sheet build is byte-identical), and the new pure fit_layout
picks the column count whose cell picture is widest inside READER_LONG_SIDE.

The count is fitted, not typed: nine 9:16 frames want 5x2 at 313px, while one
row of nine gives 174 because a single row leaves the height unused.

READER_LONG_SIDE is inherited from PER_SHEET's own comment and cannot be
measured from inside this pipeline; fit_layout maximizes UNDER it, so a wrong
budget is a suboptimal sheet and never a broken one."
```

---

### Task 2: `build_strip` fits its layout to the clip

**Files:**
- Modify: `scripts/contact_sheet.py`
- Test: `tests/lib/test_contact_sheet.py`

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_contact_sheet.py`, **replace** `test_strip_columns_cap_at_strip_cols`
with the four tests below (the constant it pins is deleted in this task):

```python
def test_strip_fits_its_layout_to_the_clips_own_aspect(tmp_path, monkeypatch):
    seen = {}
    portrait = [np.zeros((640, 360, 3), np.uint8) for _ in range(9)]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: list(portrait))
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    res = contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                    dur=4.0, frames=9, fps=30.0)
    # 9 cells of 360x640 (aspect 0.5625) fit 5 wide at 313px; the source carries
    # 360, above the fitted width, so no cap applies.
    assert (seen["cols"], seen["cell_w"], seen["cell_h"]) == (5, 313, 556)
    assert res["cols"] == 5 and res["cell_px"] == [313, 556]


def test_strip_never_upscales_past_the_sources_own_width(tmp_path, monkeypatch):
    seen = {}
    tiny = [np.zeros((160, 90, 3), np.uint8) for _ in range(9)]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: list(tiny))
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    res = contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                    dur=4.0, frames=9, fps=30.0)
    # the fit would allow 313, the source carries 90; rendering 313 would report an
    # interpolated box as the evidence's resolution (design §7.3)
    assert seen["cell_w"] == 90 and seen["cell_h"] == 160
    assert res["cell_px"] == [90, 160]


def test_strip_of_landscape_content_gets_the_landscape_fit(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)  # 320x180
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0, dur=4.0,
                              frames=9, fps=30.0)
    assert seen["cols"] == 3 and seen["cell_w"] == 320      # fit allows 522, source has 320


def test_strip_refuses_a_decode_that_returned_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: [])
    with pytest.raises(ValueError, match="decoded no frames"):
        contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                  dur=4.0, frames=9, fps=30.0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py -q -k "strip"`
Expected: FAIL — `KeyError: 'cell_w'` on the first three, and no exception raised on
the fourth.

- [ ] **Step 3: Delete `STRIP_COLS`**

In `scripts/contact_sheet.py`, delete these three lines entirely:

```python
STRIP_COLS = 6      # a strip reads left-to-right in time; 6 keeps the row inside the
                    # image-size limit while staying wide enough to see a motion arc.
```

A fixed column count is exactly what forced nine portrait frames through a layout
chosen for landscape ones (design §2).

- [ ] **Step 4: Fit the layout in `build_strip`**

In `scripts/contact_sheet.py`, replace the tail of `build_strip` (from
`images = assembly.frames_rgb(...)` to the `return`) with:

```python
    images = assembly.frames_rgb(source, times, rate)
    if not images:
        raise ValueError(f"strip: decoded no frames from {source} over "
                         f"[{start:.3f}, {start + dur:.3f}]s — the range may sit past "
                         f"the clip's end, or the decode dropped every frame")
    h0, w0 = images[0].shape[:2]
    cols, cell_w = sheet.fit_layout(len(images), w0 / h0)
    # Never upscale. A cell wider than the source frame renders an interpolated
    # picture and would report its BOX as the evidence's resolution; nothing here
    # creates pixels (design §7.3), and cell_px is read by the QC packet.
    cell_w = min(cell_w, w0)
    cell_h = max(1, round(cell_w * h0 / w0))
    cells = [sheet.Cell(image=im, lines=(f"{t:.2f}s",)) for im, t in zip(images, times)]
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.tile(cells, cols=cols, cell_w=cell_w, cell_h=cell_h).save(path)
    return {"status": "written", "strip": str(path), "frames": frames,
            "cols": cols, "cell_px": [cell_w, cell_h],
            "times": [round(t, 3) for t in times]}
```

Also extend `build_strip`'s docstring with one sentence after the existing text:

```
    The layout is FITTED to this clip's own aspect and to sheet.READER_LONG_SIDE
    (design §2) — a delivered 9:16 reel gets a 9:16 cell instead of losing 68% of
    every cell to a 16:9 box — and `cell_px` reports what one frame actually
    rendered at, which is what the QC packet passes to its judge.
```

- [ ] **Step 5: Run the driver's tests**

Run: `.venv/bin/python -m pytest tests/lib/test_contact_sheet.py -q`
Expected: PASS.

- [ ] **Step 6: Run the integration tests**

Run: `.venv/bin/python -m pytest tests/integration/test_contact_sheet.py -q`
Expected: PASS. `test_contact_sheet.py:108` builds a real strip from `sample_clip`
and asserts it exists; if it asserts dimensions, update the expectation to the
fitted values — but read the assertion first: a test asserting the OLD dimensions
is a test that was pinning the defect.

- [ ] **Step 7: Commit**

```bash
git add scripts/contact_sheet.py tests/lib/test_contact_sheet.py
git commit -m "feat(contact_sheet): a strip is laid out for the clip it shows

build_strip takes the aspect from the frames it has already decoded and calls
sheet.fit_layout, so no probe and no new parameter. STRIP_COLS is deleted: a
fixed column count is what forced nine portrait frames through a layout chosen
for landscape ones.

Measured on the real run's own case -- nine frames of a 9:16 delivered clip:
95x169 rendered (83x147 after the reader's downscale) becomes 313x556 with the
sheet landing inside the budget, so nothing is downscaled. 3.8x linear, 14.3x area.

The cell is capped at the source's own width: a strip renders a small clip small
rather than upscaling it into a claim, because cell_px is read as the evidence's
resolution downstream."
```

---

### Task 3: The packet names its own pixels

**Files:**
- Modify: `scripts/episode_qc.py`
- Test: `tests/test_episode_qc.py`

`evidence.json` carries eight keys and does not name the strip at all — its path
exists only inside the SKILL's template-fill instruction, so a reader of the packet
alone cannot tell whether one exists.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_episode_qc.py`:

```python
def _stub_strip(monkeypatch, cell_px=(313, 556)):
    """Replace the decode+tile with a recorder, so _evidence's wiring is observable
    without ffmpeg."""
    def _build(src, out, *, start, dur, frames, fps=None):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"strip")
        return {"status": "written", "strip": str(out), "frames": frames,
                "cols": 5, "cell_px": list(cell_px), "times": []}
    monkeypatch.setattr(episode_qc.contact_sheet, "build_strip", _build)


def test_evidence_names_the_strip_and_its_rendered_pixel_size(tmp_path):
    rm = _rm(tmp_path, n=1)
    ep = rm.episodes[0]
    Path(ep.path).parent.mkdir(parents=True, exist_ok=True)
    (Path(ep.path).parent / "storyboard.jpg").write_bytes(b"sb")
    strip = {"strip": str(tmp_path / "qc" / "ep0" / "strip.jpg"), "cell_px": [313, 556]}
    ev = episode_qc._evidence(ep, 0, {"stats": {}}, strip, (1080, 1922))
    assert ev["strip"] == strip["strip"]
    assert ev["strip_px"] == [313, 556]
    # storyboard.build pastes each sampled frame at FULL resolution, so one of its
    # cells IS the delivered clip's own frame (design §3).
    assert ev["storyboard_px"] == [1080, 1922]


def test_evidence_reports_no_storyboard_pixels_when_there_is_no_storyboard(tmp_path):
    rm = _rm(tmp_path, n=1)
    ep = rm.episodes[0]
    Path(ep.path).parent.mkdir(parents=True, exist_ok=True)
    strip = {"strip": "s.jpg", "cell_px": [313, 556]}
    ev = episode_qc._evidence(ep, 0, {"stats": {}}, strip, (1080, 1922))
    assert ev["storyboard"] is None and ev["storyboard_px"] is None
    assert ev["strip_px"] == [313, 556]      # the strip is still reported


def test_pack_writes_the_strips_own_measurements_into_evidence(tmp_path, monkeypatch):
    rm = _rm(tmp_path, n=1)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    Path(rm.episodes[0].path).parent.mkdir(parents=True, exist_ok=True)
    _stub_strip(monkeypatch, cell_px=(222, 395))
    monkeypatch.setattr(episode_qc.assembly, "probe_stream",
                        lambda p: SimpleNamespace(w=1080, h=1922, fps=30.0))
    monkeypatch.setattr(episode_qc.assembly, "probe_duration", lambda p: 4.0)
    monkeypatch.setattr(episode_qc.assembly, "frames_rgb",
                        lambda src, times, fps: [np.zeros((8, 8, 3), np.uint8)])
    monkeypatch.setattr(episode_qc, "_source_reading",
                        lambda ep, graded: {"source": None, "delta": None})
    episode_qc.pack(str(ep_path), str(tmp_path / "qc"))
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert ev["strip"].endswith("strip.jpg")
    assert ev["strip_px"] == [222, 395] and ev["storyboard_px"] is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/test_episode_qc.py -q -k "strip or storyboard_px"`
Expected: FAIL — `_evidence() takes 3 positional arguments but 5 were given`.

- [ ] **Step 3: Widen `_evidence`**

In `scripts/episode_qc.py`, change `_evidence`'s signature and the dict it builds:

```python
def _evidence(ep, i: int, clip_stats: dict, strip: dict,
              clip_px: tuple[int, int]) -> dict:
    """What the judge reads besides the pixels. The episode's declared INTENT is in
    here deliberately: composition is judged against what this episode asked for, never
    against a global rule (design §6)."""
    d = _epdir(ep, i)
    m = ep.manifest
    storyboard = d / "storyboard.jpg"
    out: dict = {
        "idx": i, "clip": ep.clip,
        "intent": {k: m.get(k) for k in ("composition", "grid", "hero", "target_dur",
                                         "layout", "pan", "stabilize", "canvas")},
        # Absent is reported as absent, never as a path that resolves to nothing — the
        # same rule the loop below applies to the other three sidecars, and the one the
        # `hero` axis stands on (design §6): a judge must be able to tell "there was no
        # storyboard" from "there was one".
        "storyboard": str(storyboard) if storyboard.exists() else None,
        # The strip was never named here at all: its path reached the judge only
        # through the SKILL's template fill, so a reader of this file alone could not
        # tell whether one existed (design §3).
        "strip": strip["strip"],
        # The picture size of ONE frame, in each artifact. RENDERED, not what a
        # reader's own downsample leaves — the packet cannot know that. Reported,
        # never gated: there is nothing here to derive a "below X you cannot judge"
        # threshold from, and the point is that the judge can prefer the right
        # artifact and say which one it used (design §3).
        "strip_px": list(strip["cell_px"]),
        # storyboard.build pastes each sampled frame at FULL resolution, so one of its
        # cells IS the delivered clip's own frame — 129x the strip's area rendered,
        # 22x as read (design §0.2).
        "storyboard_px": [clip_px[0], clip_px[1]] if storyboard.exists() else None,
        "naturalness": clip_stats,
    }
```

(The `for name, key in (...)` loop and the `return out` below it are unchanged.)

- [ ] **Step 4: Wire `pack`**

In `scripts/episode_qc.py`, inside `pack`'s per-episode loop, capture the strip's
result and pass both new arguments:

```python
        info = assembly.probe_stream(ep.clip)
        dur = assembly.probe_duration(ep.clip)
        strip = contact_sheet.build_strip(ep.clip, str(d / "strip.jpg"), start=0.0,
                                          dur=dur, frames=frames, fps=info.fps)
        times = color.sample_times(dur, SENSOR_FRAMES)
        stats = naturalness.measure(assembly.frames_rgb(ep.clip, times, info.fps))
        clip_stats = {"stats": stats, "flags": naturalness.evaluate(stats),
                      **_source_reading(ep, stats)}
        (d / "evidence.json").write_text(json.dumps(
            _evidence(ep, i, clip_stats, strip, (info.w, info.h)), indent=2))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_episode_qc.py -q`
Expected: PASS. The two pre-existing storyboard tests
(`test_evidence_reports_a_missing_storyboard_as_none`,
`test_evidence_reports_an_existing_storyboard_path`) call `_evidence` with three
arguments — update those two call sites to pass
`{"strip": "s.jpg", "cell_px": [1, 1]}, (10, 10)`.

- [ ] **Step 6: Commit**

```bash
git add scripts/episode_qc.py tests/test_episode_qc.py
git commit -m "feat(episode_qc): the packet names its own pixels

evidence.json carried eight keys and did not name the strip at all -- its path
reached the judge only through the SKILL's template fill, so a reader of the
packet alone could not tell whether one existed. It now carries `strip`, plus
`strip_px` and `storyboard_px`: the rendered picture size of ONE frame in each
artifact.

No threshold is introduced. There is nothing here to derive a 'below X you
cannot judge' constant from, and a gate on an invented number is the pattern
R2.4 files. The numbers let the judge prefer the right artifact -- the
storyboard is 129x the strip's area rendered -- and say which it used."
```

---

### Task 4: `build_qc` collects every complaint in one pass

**Files:**
- Modify: `scripts/episode_qc.py`
- Test: `tests/test_episode_qc.py`

A judge subagent has already exited by the time `build_qc` runs, so raising on the
first bad finding costs a whole round to learn about the second.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_episode_qc.py`:

```python
def _bad_findings(packets, i, finding):
    d = packets / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps({
        "summary": "s", "reviewer": "r", "findings": [finding]}))


def test_build_names_every_bad_packet_in_one_pass(tmp_path):
    rm = _rm(tmp_path, n=3)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _bad_findings(packets, 0, {"axis": "colour", "severity": "minor",
                               "evidence": "e", "route": "none"})       # no suggestion
    _findings(packets, 1)                                               # fine
    # ep2 has no findings.json at all
    with pytest.raises(ValueError) as e:
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    msg = str(e.value)
    assert "ep0 finding 0" in msg and "suggestion must be a non-empty string" in msg
    assert "ep2" in msg and "has no findings.json" in msg
    assert "ep1" not in msg


def test_build_names_every_bad_finding_inside_one_packet(tmp_path):
    rm = _rm(tmp_path, n=1)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    d = packets / "ep0"
    d.mkdir(parents=True)
    (d / "findings.json").write_text(json.dumps({"summary": "s", "reviewer": "r",
        "findings": [
            {"axis": "framing", "severity": "minor", "evidence": "e",
             "route": "none", "suggestion": "s"},               # bad axis
            {"axis": "colour", "severity": "minor", "evidence": "e",
             "route": "none"},                                  # no suggestion
        ]}))
    with pytest.raises(ValueError) as e:
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    msg = str(e.value)
    assert "ep0 finding 0" in msg and "ep0 finding 1" in msg


def test_build_still_refuses_the_whole_run_over_one_bad_packet(tmp_path):
    rm = _rm(tmp_path, n=2)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _bad_findings(packets, 1, {"axis": "colour", "severity": "catastrophic",
                               "evidence": "e", "route": "none", "suggestion": "s"})
    with pytest.raises(ValueError, match="severity 'catastrophic'"):
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    # EPISODE_QC.json describes the REEL; a partial one would be a reel partly
    # unjudged, so collecting complaints must not weaken the refusal.
    assert not (tmp_path / "EPISODE_QC.json").exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/test_episode_qc.py -q -k "one_pass or inside_one_packet or whole_run"`
Expected: FAIL — the first two, because the raise happens on ep0 and never reaches
ep2 (`assert "ep2" in msg`).

- [ ] **Step 3: Rewrite `build_qc`**

Replace `build_qc` in `scripts/episode_qc.py`:

```python
def build_qc(episodes_path: str, packets: str) -> ReelQC:
    """Validate every episode's raw findings into a typed ReelQC. The clip digest is
    computed HERE from the file on disk — whatever `clip_digest` the judge's file
    carries is ignored, which is what turns "this episode was judged" into "this
    RENDER was judged" (design 2026-08-08 §7).

    Every complaint from one run is collected and raised TOGETHER (design 2026-09-08
    §6). The judges have all exited by the time this runs, so raising on the first bad
    finding buys nothing about the other seven episodes and costs a whole round to
    learn about the second. The refusal's STRENGTH is unchanged: one bad packet still
    refuses the whole run, because EPISODE_QC.json describes the reel and a partial one
    would be a reel partly unjudged."""
    rm = ReelManifest.from_json(episodes_path)
    verdicts: list[EpisodeVerdict] = []
    problems: list[str] = []
    for i, ep in enumerate(rm.episodes):
        try:
            raw = _raw(packets, i)                 # read once: three reads = three failure surfaces
        except ValueError as e:
            problems.append(f"  ep{i}: {e}")
            continue
        findings = raw.get("findings") or []
        if not isinstance(findings, (tuple, list)):
            problems.append(f"  ep{i}: 'findings' must be a JSON list, got "
                            f"{type(findings).__name__}")
            continue
        built: list[EpisodeFinding] = []
        before = len(problems)
        for k, f in enumerate(findings):
            try:
                built.append(EpisodeFinding.from_dict(f))
            except ValueError as e:
                problems.append(f"  ep{i} finding {k}: {e}")
        if len(problems) != before:
            continue                               # a packet with a bad finding builds no verdict
        try:
            verdicts.append(EpisodeVerdict(
                idx=i, clip=ep.clip, clip_digest=provenance.digest_file(ep.clip),
                findings=tuple(built),
                summary=raw.get("summary") or "", reviewer=raw.get("reviewer") or ""))
        except (ValueError, OSError) as e:
            problems.append(f"  ep{i}: {e}")
    if problems:
        raise ValueError(
            f"episode_qc build: {len(problems)} complaint(s) across "
            f"{len(rm.episodes)} packets.\n" + "\n".join(problems)
            + "\nEvery complaint from this run is listed above, so one pass names them "
              "all. Fix or re-dispatch the judges named, then re-run build.")
    return ReelQC(episodes=tuple(verdicts))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_episode_qc.py -q`
Expected: PASS, including the pre-existing `test_build_refuses_an_unjudged_episode`
— its `match="episode 1 has no findings.json"` is a `re.search`, which still hits
inside the `  ep1: …` line.

- [ ] **Step 5: Run the integration suite for this stage**

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/episode_qc.py tests/test_episode_qc.py
git commit -m "fix(episode_qc): one build pass names every bad packet

build_qc raised on the first bad finding, after every judge had already exited.
One malformed field killed the validation of all eight episodes and bought
nothing about the other seven -- the controller learned about one problem per
round, and each round is a fresh judge budget.

It now walks every episode, validates every finding, and raises once with the
episode index and finding index that produced each complaint. A missing
findings.json is collected the same way.

The refusal's strength is unchanged: one bad packet still refuses the whole run,
because EPISODE_QC.json describes the reel and a partial one would be a reel
partly unjudged."
```

---

### Task 5: The representative crop is the largest, the descriptor is still the centroid

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

Measured over the run's 15 candidates, presence and crop area are anti-correlated
(Spearman **−0.486**): the person with 479 s on screen was surfaced as a **16×19**
crop while the one with 32 s got 535×373. `_medoid` picks the member closest to the
cluster's embedding centroid, and identity-centrality is not legibility.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_intake.py`:

```python
def test_the_representative_crop_is_the_largest_not_the_medoid():
    # Three members of ONE identity. The medoid (closest to the centroid) carries a
    # tiny crop; another member carries a big one. Presence and crop area are
    # anti-correlated on real footage (Spearman -0.486, design §0.4), so the pick
    # must be by pixels, not by embedding centrality.
    from scripts.lib.intake_cache import CastEntry
    tiny = np.zeros((12, 13, 3), "uint8")            # 13x12 -- the run's worst
    big = np.full((373, 535, 3), 200, "uint8")
    mid = np.zeros((80, 60, 3), "uint8")
    d = _desc(1.0)
    entries = [CastEntry("a.mp4", 1, 0.9, list(d), presence=9.0, crop_rgb=tiny),
               CastEntry("a.mp4", 2, 0.9, list(d), presence=1.0, crop_rgb=big),
               CastEntry("a.mp4", 3, 0.9, list(d), presence=1.0, crop_rgb=mid)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert len(picked) == 1
    assert picked[0].crop_rgb.shape[:2] == (373, 535)


def test_the_representative_descriptor_is_still_the_centroid():
    # The picture changes; the identity mathematics does not. Every downstream
    # consumer (hero.resolve, track.build_route, cast.json) reads `descriptor`.
    from scripts.lib.intake_cache import CastEntry
    big = np.full((300, 300, 3), 200, "uint8")
    entries = [CastEntry("a.mp4", 1, 0.9, _emb(0), presence=5.0,
                         crop_rgb=np.zeros((4, 4, 3), "uint8")),
               CastEntry("a.mp4", 2, 0.9, _emb(0), presence=5.0, crop_rgb=big)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert picked[0].descriptor == _emb(0)           # the re-L2-normed mean, unchanged
    assert picked[0].presence == 10.0                # summed, unchanged
    assert picked[0].crop_rgb.shape[:2] == (300, 300)


def test_a_member_with_no_crop_never_wins_the_representative_slot():
    from scripts.lib.intake_cache import CastEntry
    small = np.zeros((4, 4, 3), "uint8")
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), presence=9.0),   # no crop at all
               CastEntry("a.mp4", 2, 0.9, _desc(1.0), presence=1.0, crop_rgb=small)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert picked[0].crop_rgb is not None            # the 4x4 wins over nothing


def test_a_cached_form_crop_is_sized_from_its_png(tmp_path):
    from scripts.lib.intake_cache import CastEntry
    wide = tmp_path / "wide.png"
    _Img.fromarray(np.full((200, 400, 3), 180, "uint8")).save(wide)
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), presence=9.0,
                         crop_rgb=np.zeros((10, 10, 3), "uint8")),
               CastEntry("a.mp4", 2, 0.9, _desc(1.0), presence=1.0, crop=str(wide))]
    picked = intake.surface_crops(entries, max_cast=8)
    assert picked[0].crop == str(wide)               # the cached PNG's header decided it


def test_save_cast_candidates_records_each_crops_pixel_size(tmp_path):
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((19, 16, 3), "uint8"); red[:, :, 0] = 255      # 16x19, the run's ep1
    blue = np.zeros((373, 535, 3), "uint8"); blue[:, :, 2] = 255
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), crop_rgb=red),
               CastEntry("b.mp4", 1, 0.8, _desc(0.0, 1.0), crop_rgb=blue)]
    manifest = intake.save_cast_candidates(entries, str(tmp_path))
    by_source = {m["source"]: m for m in manifest}
    assert by_source["a.mp4"]["crop_px"] == [16, 19]
    assert by_source["b.mp4"]["crop_px"] == [535, 373]
    # read from the file the human will actually open, not from the entry
    for m in manifest:
        assert _Img.open(m["crop"]).size == tuple(m["crop_px"])
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q -k "representative or no_crop_never_wins or cached_form_crop_is_sized or records_each_crops"`
Expected: FAIL — the medoid wins the first, and `KeyError: 'crop_px'` on the last.

- [ ] **Step 3: Replace `_medoid` with `_crop_area` + `_largest`**

In `scripts/intake.py`, **delete** `_medoid` entirely (its only call site is
`surface_crops`, replaced in the next step) and put these in its place:

```python
def _crop_area(e: CastEntry) -> int:
    """Pixel area of a member's crop, in either CastEntry form: the live array's
    shape, or the cached PNG's header (Image.open reads the header, not the pixels).
    A member carrying neither answers 0 and so never wins, rather than raising —
    save_cast_candidates is where a crop-less entry is refused, at the point it would
    have to write one."""
    if e.crop_rgb is not None:
        h, w = e.crop_rgb.shape[:2]
        return int(w) * int(h)
    if e.crop:
        try:
            with Image.open(e.crop) as im:
                w, h = im.size
        except (OSError, ValueError):
            return 0
        return int(w) * int(h)
    return 0


def _largest(members: list[CastEntry]) -> CastEntry:
    """The member whose crop carries the most pixels — the one a HUMAN can name.

    Deliberately NOT the medoid this replaced. The medoid is the member closest to the
    cluster's embedding centroid, and identity-centrality is not legibility: measured
    over the 2026-06 run's 15 candidates, presence and crop area are ANTI-correlated
    (Spearman -0.486). The person with 479 s on screen was surfaced as a 16x19 crop —
    304 pixels — while the one with 32 s got 535x373, because a long presence averages
    over many distances and its centroid lands on a middling, usually distant, view
    (design §0.4).

    max() returns the first maximum, so a tie goes to the earlier member and the pick
    is deterministic."""
    return max(members, key=_crop_area)
```

- [ ] **Step 4: Point `surface_crops` at it**

In `scripts/intake.py`, inside `surface_crops`'s cluster loop, replace the two lines

```python
        rep = _medoid(members, cent)
```

with

```python
        rep = _largest(members)
```

and update the docstring's second line:

```python
    """Cluster ALL tracks' embeddings into real identities (agglomerative, average
    linkage, cosine, cut at CLUSTER_COS), one CastEntry per cluster: descriptor =
    centroid (mean, re-L2-normed), representative crop = the LARGEST member's (design
    2026-09-08 §5 — the medoid picked for embedding centrality, which is
    anti-correlated with legibility), presence = sum over members. Ranked by presence
    (design §4.1); capped at max_cast with a logged drop — never a silent cap."""
```

- [ ] **Step 5: Record the crop's size in the manifest**

In `scripts/intake.py`, inside `save_cast_candidates`'s loop, after the crop is
written and before `manifest.append`:

```python
        # Read back from the file the human will actually open, not from the entry:
        # crop_px is what makes "too small to name" a reported state instead of an
        # invisible one (design §5/§7.3). Nothing here creates pixels — if a person
        # was only ever 13px tall, the largest member is still 13px.
        with Image.open(dest) as im:
            crop_w, crop_h = im.size
        manifest.append({"id": i, "source": e.source, "conf": round(float(e.conf), 3),
                         "presence": round(float(e.presence), 2),
                         "crop": dest, "crop_px": [crop_w, crop_h],
                         "descriptor": e.descriptor})
```

- [ ] **Step 6: Run the module's tests**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS. `test_surface_clusters_by_identity_and_ranks_by_presence` and
`test_surface_crops_dedups_identities` must still pass **unchanged** — they assert
the descriptor and the clustering, which this task does not touch.

- [ ] **Step 7: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "fix(intake): surface the crop a human can name, not the medoid

Measured over the real run's 15 candidates, presence and crop area are
ANTI-correlated: Spearman -0.486. The person with 479 s on screen was surfaced
as a 16x19 crop -- 304 pixels -- and the one with 32 s got 535x373, 1279x the
pixels of the worst. A long presence averages over many distances, so its
cluster centroid lands on a middling, usually distant, view, and _medoid picked
exactly that.

The representative crop becomes the cluster's largest member's. The descriptor
is still the re-L2-normed centroid and the presence is still the sum, so every
downstream consumer sees what it sees today. save_cast_candidates records
crop_px, read back from the file the human opens, which is what makes a 13x12
crop a reported state instead of an invisible one.

Runs entirely in intake's Phase 2 over cached results: CACHE_VERSION does not
move and no footage is re-scanned."
```

---

### Task 6: The skills name the gates and the extraction

**Files:**
- Modify: `skills/episode-qc/episode-reviewer.md`
- Modify: `skills/episode-qc/SKILL.md`
- Modify: `skills/footage-intake/SKILL.md`
- Test: `tests/test_skills_contract.py` (create)

`suggestion` appears in the reviewer template exactly once, at line 104, as the
placeholder `"..."` inside the output JSON example. The `Rules` block names neither
it nor `axis`, and both are hard gates. Six of eight judges pulled their own
full-resolution frames; `contact_sheet strip` does exactly that and is named nowhere.

- [ ] **Step 1: Write the failing test**

Create `tests/test_skills_contract.py`:

```python
"""The judge template must state the contract episode_qc validates.

R10.7: `suggestion` was hard-gated by EpisodeFinding and appeared in
skills/episode-qc/episode-reviewer.md only as a placeholder inside the output JSON
example, never in the Rules block that enumerates the other four fields. A judge
learns the shape from the Rules, spends its whole budget, and is rejected after it
has exited. Nothing machine-checked the template against the dataclass; this does."""
from dataclasses import fields
from pathlib import Path

from scripts.lib.episode_qc import QC_AXES, EpisodeFinding

ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = ROOT / "skills/episode-qc/episode-reviewer.md"


def _rules_block() -> str:
    text = _TEMPLATE.read_text()
    start = text.index("## Rules")
    end = text.index("## Write your output", start)
    return text[start:end]


def test_every_gated_finding_field_is_named_in_the_rules_block():
    rules = _rules_block()
    missing = [f.name for f in fields(EpisodeFinding) if f"`{f.name}`" not in rules]
    assert missing == [], (
        f"{missing} are validated by EpisodeFinding but not named in the template's "
        f"Rules block — a judge cannot satisfy a gate it was never told about")


def test_the_five_axes_are_named_in_the_rules_block():
    rules = _rules_block()
    assert all(a in rules for a in QC_AXES)


def test_the_template_names_the_extraction_tool():
    # Six of eight judges on the real run pulled their own full-resolution frames;
    # one hit `magick not found`. contact_sheet strip does exactly that (design §0.3).
    text = _TEMPLATE.read_text()
    assert "scripts.contact_sheet strip" in text
    assert "$VG" in text
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/test_skills_contract.py -q`
Expected: FAIL — `['suggestion'] are validated by EpisodeFinding but not named…`
and the extraction assertions.

- [ ] **Step 3: State the two unnamed gates**

In `skills/episode-qc/episode-reviewer.md`, in the `## Rules` block, insert after
the `severity` bullet and before the `route` bullet:

```
- `axis` ∈ (composition, colour, impression, path, hero) — the five judged
  above, and only those. A finding on any other axis has no stage to be
  routed to and `episode_qc build` refuses the whole run over it.
```

and after the `confidence` bullet:

```
- `suggestion` — REQUIRED, non-empty: the concrete change that would fix what
  you found. A finding that names no change is not actionable, and
  `episode_qc build` refuses the whole run over it. "Consider revisiting the
  framing" is not a suggestion; "re-render at crop_scale 1.0" is.
```

- [ ] **Step 4: Name the extraction and the two pixel sizes**

In `skills/episode-qc/episode-reviewer.md`, replace the whole `## What shipped`
section with:

```
## What shipped
Frame strip: {STRIP_PATH} — {STRIP_PX} px per frame, sampled across the
DELIVERED clip in timeline order and labelled with absolute timestamps. This is
the **timeline index**: it tells you WHEN, at a size chosen to fit a whole
episode in one image.

Storyboard: {STORYBOARD_PATH} — {STORYBOARD_PX} px per frame, with the
composition grid and the hero marker on every sampled frame when one was
tracked. This is the **composition evidence**; it is far larger per frame than
the strip and is what you judge framing from.

Both sizes are in `evidence.json` as `strip_px` and `storyboard_px`. They are
RENDERED sizes — your own viewer may downsample further.

**When you need a closer look, take one.** Do not guess from a thumbnail and do
not reach for a tool that is not here. Resolve the launcher once —

    VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"

— and pull any frames you want from the delivered clip itself
(`evidence.json`'s `clip`), at timestamps YOU choose:

    "$VG" scripts.contact_sheet strip --source <evidence.json "clip"> \
          --out <a path of your own> --start <seconds> --dur <seconds> --frames <n>

A short `--dur` around one moment gives you a near-full-resolution look at it.
Name in your summary which timestamps you pulled and why — the next round's
judge reads it.
```

- [ ] **Step 5: Tell the dispatcher to fill the two new placeholders**

In `skills/episode-qc/SKILL.md`, in step 2, replace the sentence beginning
"For each episode `i`, fill …" with:

```
   episode `i`, fill `skills/episode-qc/episode-reviewer.md` with THAT
   episode's own `<run>/reels/<reel>/episodes/qc/ep{i}/evidence.json` — which now names its
   own artifacts: `strip`, `strip_px`, `storyboard`, `storyboard_px`. Fill
   `{STRIP_PATH}`/`{STRIP_PX}` and `{STORYBOARD_PATH}`/`{STORYBOARD_PX}` from
   those four keys, and pass nothing else. A judge reads only its own episode:
```

and in step 1, after the `evidence.json` sentence, add:

```
   `evidence.json` also records what each pixel artifact actually rendered at
   (`strip_px`, `storyboard_px`) — reported, never gated. A judge that needs a
   closer look pulls its own frames with `contact_sheet strip`; the template
   tells it how.
```

- [ ] **Step 6: Name `crop_px` in the cast pass**

In `skills/footage-intake/SKILL.md`, step 3, replace the first sentence with:

```
3. **Cast pass — only when people matter to the reel.** Read
   `cast_candidates.json` and look at each `candidate_*.png`. Each entry
   records `crop_px` — the crop's real pixel size. **Say it out loud when you
   show a small one**: on the 2026-06 run seven of fifteen candidates were
   under 5000 px total and three were about 13x13, and the operator was asked
   to name them anyway. A candidate too small to identify is a candidate to
   skip, not to guess at; nothing upscales it, because an interpolated 13x12
   crop looks like evidence and is not.
```

- [ ] **Step 7: Run the contract test and the skill suites**

Run: `.venv/bin/python -m pytest tests/test_skills_contract.py -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest tests/ -q -k "skill or plugin"`
Expected: PASS — several tests assert every skill's frontmatter and cross-links.

- [ ] **Step 8: Commit**

```bash
git add skills/episode-qc/episode-reviewer.md skills/episode-qc/SKILL.md \
        skills/footage-intake/SKILL.md tests/test_skills_contract.py
git commit -m "docs(skills): name the gates the judge was measured against

`suggestion` was hard-gated by EpisodeFinding and appeared in the reviewer
template exactly once -- as the placeholder \"...\" inside the output JSON
example. The Rules block enumerated severity/route/confidence/evidence and named
neither `suggestion` nor `axis`, and both refuse the whole run.

Both are now stated, and tests/test_skills_contract.py machine-checks the Rules
block against EpisodeFinding's own fields, so a field added later cannot go
unstated the same way.

The template also names the extraction six of eight judges already performed by
hand -- contact_sheet strip against the delivered clip, at timestamps the judge
chooses -- and reports what each packed artifact rendered at, so the judge can
tell the timeline index from the composition evidence."
```

---

### Task 7: Real-pixel proof, each with a control that must not move

**Files:**
- Test: `tests/integration/test_legible_evidence.py` (create)

The claim this slice rests on is that a cell shaped like its content letterboxes
nothing. That is a statement about pixels and is proven on pixels.

- [ ] **Step 1: Write the proof**

Create `tests/integration/test_legible_evidence.py`:

```python
"""Real-ffmpeg proof that a strip cell shaped like its content carries picture edge
to edge, and that the footage contact sheet did not move (design §2, §8).

Each claim has a control that must NOT move.
"""
import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib import ffbin, proc, sheet

pytestmark = pytest.mark.integration


def _solid_clip(path, w, h, seconds=3, colour="red"):
    """A solid-colour clip at an exact size. `d=` bounds the lavfi source itself, so
    there is no infinite input to cut short (fit-solid §4), and the pix_fmt + range
    pair is the one the §12 registry requires."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c={colour}:s={w}x{h}:d={seconds}:r=30",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(path)])
    return str(path)


def _is_red(px):
    r, g, b = px
    return r > 150 and g < 90 and b < 90


def test_a_portrait_strips_cell_carries_picture_edge_to_edge(tmp_path):
    src = _solid_clip(tmp_path / "portrait.mp4", 360, 640)
    out = tmp_path / "strip.png"
    res = contact_sheet.build_strip(src, str(out), start=0.0, dur=2.0, frames=9)
    cw, ch = res["cell_px"]
    img = Image.open(out).convert("RGB")

    assert max(img.size) <= sheet.READER_LONG_SIDE          # inside the budget
    assert img.size == (res["cols"] * cw,
                        2 * (ch + sheet.LABEL_H))           # 9 cells at 5 wide -> 2 rows

    # THE claim: the first cell's picture reaches both of its own side edges. Under a
    # 16:9 box a 9:16 frame uses 95 of 300 columns and these two pixels are black.
    assert _is_red(img.getpixel((1, ch // 2)))
    assert _is_red(img.getpixel((cw - 2, ch // 2)))
    # and its label strip below is still background, so the cell height is right
    assert img.getpixel((cw // 2, ch + sheet.LABEL_H - 2)) == (0, 0, 0)


def test_control_a_landscape_strip_is_still_letterbox_free(tmp_path):
    # The control: 16:9 content was ALREADY edge to edge in the 16:9 box. If this
    # moves, the change broke the case it was not supposed to touch.
    src = _solid_clip(tmp_path / "wide.mp4", 640, 360)
    out = tmp_path / "wide_strip.png"
    res = contact_sheet.build_strip(src, str(out), start=0.0, dur=2.0, frames=9)
    cw, ch = res["cell_px"]
    img = Image.open(out).convert("RGB")
    assert _is_red(img.getpixel((1, ch // 2)))
    assert _is_red(img.getpixel((cw - 2, ch // 2)))


def test_control_the_default_cell_box_still_letterboxes_a_portrait_frame(tmp_path):
    # The control on the CONTACT SHEET's side: sheet.tile's defaults are unchanged,
    # so a portrait thumbnail in the mixed-aspect overview still lands in a 16:9 box
    # with black at its left edge. Byte-identical behaviour, deliberately kept
    # (design §8) -- that sheet mixes aspects and a ragged grid would be worse.
    import numpy as np
    frame = np.full((320, 180, 3), 200, np.uint8)
    img = sheet.tile([sheet.Cell(image=frame, lines=("t",))])
    assert img.size == (sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)
    assert img.getpixel((1, sheet.CELL_H // 2)) == (0, 0, 0)


def test_a_strip_never_renders_more_pixels_than_the_source_carries(tmp_path):
    src = _solid_clip(tmp_path / "small.mp4", 96, 160)
    out = tmp_path / "small_strip.png"
    res = contact_sheet.build_strip(src, str(out), start=0.0, dur=2.0, frames=9)
    assert res["cell_px"] == [96, 160]           # the fit would allow far more
    img = Image.open(out).convert("RGB")
    assert img.size == (res["cols"] * 96, 2 * (160 + sheet.LABEL_H))
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/integration/test_legible_evidence.py -q`
Expected: PASS, all five.

If `test_a_portrait_strips_cell_carries_picture_edge_to_edge` fails on the
`img.size` assertion, print `res` and re-derive the expected grid from
`sheet.fit_layout(9, 360/640)` rather than adjusting the pixel assertions — the
pixel assertions are the proof and must not be relaxed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_legible_evidence.py
git commit -m "test: real pixels prove the cell carries picture edge to edge

The slice rests on a claim about pixels -- a cell shaped like its content
letterboxes nothing -- so it is proven on real decoded frames, with three
controls that must not move: 16:9 content was already edge to edge and still is,
sheet.tile's defaults still letterbox a portrait thumbnail in the mixed-aspect
contact sheet, and a source smaller than the fit renders at its own size."
```

---

### Task 8: Mutation battery, version bump, docs

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `docs/backlog.md`,
  `docs/backlog-closed.md`, `docs/build-status.md`, `CLAUDE.md`

- [ ] **Step 1: Run the full suite and record the number**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: all green. Record the exact `N passed, M skipped` line — the task's
report quotes it, and the pre-branch baseline was `3510 passed, 1 skipped`.

- [ ] **Step 2: Run the mutation battery**

Fourteen rows. For each: apply the mutation, run the named selection, confirm RED,
restore with `git show HEAD:<path> > <path>`, and confirm `git diff --quiet <path>`.
Run every selection under `PYTHONDONTWRITEBYTECODE=1`. Pass selections literally —
zsh does not word-split an unquoted variable, and a selection arriving as one
argument prints `no tests ran`, which reads exactly like a non-discriminating row.

| # | Mutation | Selection expected to go RED |
|---|---|---|
| 1 | `fit_layout` returns `(n, int(budget / n))` — one row always | `tests/lib/test_sheet.py -k fit_layout` |
| 2 | `fit_layout` drops the height bound: `cell_w = int(by_width)` | `tests/lib/test_sheet.py -k "fitted_sheet or fit_layout"` |
| 3 | `fit_layout` uses `round(...)` instead of `int(...)` | `tests/lib/test_sheet.py -k "fit_layout or fitted_sheet"` |
| 4 | `fit_layout` ties go to the LARGER column count (`>=`) | `tests/lib/test_sheet.py -k fit_layout` |
| 5 | `tile`'s defaults become `cell_w=200, cell_h=200` | `tests/lib/test_sheet.py tests/integration/test_legible_evidence.py` |
| 6 | `build_strip` drops `cell_w = min(cell_w, w0)` | `tests/lib/test_contact_sheet.py -k strip` + `tests/integration/test_legible_evidence.py` |
| 7 | `build_strip` passes `cell_w=sheet.CELL_W, cell_h=sheet.CELL_H` | `tests/integration/test_legible_evidence.py` |
| 8 | `_evidence` omits `strip_px` | `tests/test_episode_qc.py -k strip` |
| 9 | `_evidence` reports `storyboard_px` unconditionally | `tests/test_episode_qc.py -k storyboard_px` |
| 10 | `build_qc` `continue` → `break` after the first problem | `tests/test_episode_qc.py -k one_pass` |
| 11 | `build_qc` never raises (drop the `if problems:` block) | `tests/test_episode_qc.py -k "one_pass or whole_run or unjudged"` |
| 12 | `_largest` → `min(members, key=_crop_area)` | `tests/lib/test_intake.py -k representative` |
| 13 | `surface_crops` uses `_largest(members).descriptor` for `descriptor=` | `tests/lib/test_intake.py -k "descriptor or clusters_by_identity"` |
| 14 | Delete the `suggestion` bullet from the template's Rules block | `tests/test_skills_contract.py` |

Two rows are **expected to be interesting rather than certain** and must be
reported honestly whichever way they land:

- **Row 3** (`round` vs `int`) only discriminates if some fitted layout lands
  exactly on a fractional boundary where rounding up pushes the sheet past the
  budget. If it comes back GREEN, that is a real coverage gap: add a `fit_layout`
  case whose truncation is load-bearing, or state in the report that no legal
  input reaches the boundary and the guard is belt-and-braces.
- **Row 4** (tie-break direction) only discriminates if some `(n, aspect)` in the
  pinned table has two column counts giving the same `cell_w`. If GREEN, say so
  and record that the tie-break is documented but unpinned.

Any row that comes back GREEN and is not one of those two is a coverage hole:
close it with a NEW test in the same commit, and say in the report which test was
added and why the existing ones could not see the mutation.

- [ ] **Step 3: Bump the version**

Edit `.claude-plugin/plugin.json`: `"version": "0.8.1"` → `"version": "0.8.2"`.

PATCH, not MINOR, by the rule in
[development-workflow.md](development-workflow.md#versioning): this slice adds no
flag, renames no signature, changes no stage order and adds no required artifact.
It changes artifact *contents* and fixes evidence that was already the wrong size.
Run-dir separation (0.2.1) is the worked precedent.

- [ ] **Step 4: Write the changelog entry**

Prepend to `CHANGELOG.md`, above the current top entry:

```markdown
## 0.8.2 — 2026-09-08 · Illegible is a state, not a clean pass

Three artifacts in this tree are evidence handed to a judge — the QC frame strip,
the cast candidate crop, and the judge's own output contract — and each was
produced with no model of its reader. Backlog R10.1, R10.2, R10.6, R10.7.

Two of the four rows' premises needed correcting, and one correction is the
content of the slice:

- **R10.1's number was a misreading.** Today's code reproduces the run's strip
  byte-exactly (1800×406 = 6 cols × 2 rows of 300×203); the real per-frame picture
  is 95×169, and 83×147 after the reader's downscale. Nothing had regressed. 68 %
  of every cell was black because `CELL_H` is a 16:9 box and a delivered reel is
  9:16.
- **Six of eight judges say in their own summaries that they pulled their own
  full-resolution frames**, one of them hitting `magick not found`.
  `contact_sheet strip` already does exactly that and was named nowhere in the
  template. That, not the cell size, is R10.1.
- **R10.2 is not "too small".** Over the run's 15 candidates,
  Spearman(presence, crop area) = **−0.486**: the person with 479 s on screen was
  a 16×19 crop, the one with 32 s got 535×373.
- **R10.7 was larger than filed** — the Rules block named neither `suggestion`
  nor `axis`, and both refuse the whole run.

**Changed**
- `sheet.fit_layout` picks the column count whose cell picture is widest inside a
  named `READER_LONG_SIDE`; `sheet.tile`/`_fit` take the cell box as a parameter
  defaulting to today's values, so the footage contact sheet is byte-identical.
  `contact_sheet.STRIP_COLS` is deleted. On the run's own case, 95×169 becomes
  313×556 with the sheet landing inside the budget — 3.8× linear, 14.3× area.
- `episode_qc`'s packet names the strip it never named and records `strip_px` and
  `storyboard_px`, the rendered per-frame size of each artifact. Reported, never
  gated — no threshold is introduced.
- `episode_qc.build` collects every validation complaint across every packet and
  raises once, with the episode and finding index for each. The refusal's strength
  is unchanged: one bad packet still refuses the whole run.
- `intake.surface_crops` surfaces the cluster's largest crop instead of its
  medoid; the descriptor is still the re-L2-normed centroid, so no downstream
  consumer changes. `cast_candidates.json` records `crop_px`. Phase 2 only —
  `CACHE_VERSION` does not move and no footage is re-scanned.
- The judge template states `axis` and `suggestion`, names the extraction, and
  distinguishes the timeline index from the composition evidence.
  `tests/test_skills_contract.py` machine-checks the Rules block against
  `EpisodeFinding`'s own fields.

**Honest limits** — nothing here proves a judge looked; `READER_LONG_SIDE` is
inherited from `PER_SHEET`'s own comment and cannot be measured from inside this
pipeline (`fit_layout` maximizes *under* it, so a wrong budget is a suboptimal
sheet and never a broken one); and nothing creates pixels — if a person was only
ever 13 px tall, `crop_px` is what makes that reportable.
```

- [ ] **Step 5: Close the four rows into the archive**

In `docs/backlog.md`, delete the R10.1 row from **P1** and the R10.2, R10.6 and
R10.7 rows from **P2**. In `docs/backlog-closed.md`, add all four with the closure
note that says what each row's own premise got wrong:

- **R10.1** — closed 2026-09-08 by "Legible evidence". The row's "200×406 px per
  frame" was a misreading of the sheet's dimensions (6×2 cells of 300×203, not one
  row of nine); the real figure is 95×169, and 83×147 as read, and nothing had
  regressed since 2026-08-05. The fix that mattered was not the cell size: six of
  eight judges say in their own summaries that they pulled their own
  full-resolution frames, and `contact_sheet strip` — which does exactly that — was
  named nowhere in their template.
- **R10.2** — closed 2026-09-08. Not "too small": Spearman(presence, crop area) =
  −0.486 over the run's 15 candidates. `_medoid` picked for embedding centrality,
  which is anti-correlated with legibility. The pick changed; nothing upscales.
- **R10.6** — closed 2026-09-08. `build_qc` now collects every complaint in one
  pass. The row's "or state it in the template" half is R10.7.
- **R10.7** — closed 2026-09-08, and larger than filed: the Rules block named
  neither `suggestion` **nor `axis`**, and both are hard gates. Now stated, and
  machine-checked against the dataclass so a later field cannot go unstated.

Update the archive's own count line and the `Look there for what a row was closed
by` sentence in `docs/backlog.md` if it quotes a number.

- [ ] **Step 6: File the five deferrals**

Add to `docs/backlog.md` **P3**, under a suitable group:

```
`episode_qc zoom` subcommand — wraps contact_sheet strip and would itself need
naming in the same template it exists to serve (legible-evidence §4/§8) ·
pack a high-resolution artifact per episode by default — pays decode on every
episode to guess timestamps the judges choose themselves (legible-evidence §4/§8) ·
`episode_qc validate` so a judge can check its own findings.json before it stops —
R10.6 asked "validate early OR state it", and stating it was the root
(legible-evidence §6/§8) ·
re-tile the storyboard 3×2 for portrait content — 392×698 → 441×784, 12 % on
process_episode's hot path behind a golden (legible-evidence §8) ·
measure READER_LONG_SIDE — not observable from inside this pipeline, so the 1568
stays inherited from PER_SHEET's own comment (legible-evidence §7.2)
```

- [ ] **Step 7: Update the registry and the status**

In `CLAUDE.md`'s Quick Reference table, add two rows after the named-absence pair:

```markdown
| Legible evidence design | [2026-09-08-legible-evidence-design.md](docs/specs/2026-09-08-legible-evidence-design.md) | R10.1/R10.2/R10.6/R10.7: three artifacts handed to a judge, none sized against its reader. **§0 is the artifact half and it overturns two rows.** R10.1's "200×406 px per frame" is a misreading of the sheet's dimensions — today's code reproduces the run's strip byte-exactly at 1800×406 (6 cols × 2 rows of 300×203), the real picture is 95×169 and **83×147 as read**, and nothing regressed since 2026-08-05; what is real is that `CELL_H` is a 16:9 box and a delivered reel is 9:16, so **68 % of every cell is black**, and that the SAME packet already carries a storyboard of the SAME clip at **129× the area rendered, 22.4× as read**. The row's actual content is §0.3: **six of eight judges say in their own summaries that they pulled their own full-resolution frames** (ep2 names five timestamps, ep7 a "3x zoom", ep0/ep6 reconstruct the crop rect) and one hit `magick not found` — `contact_sheet strip` does exactly this and is named nowhere in their template, which is R4.2 inside one required stage. R10.2 is not "too small" either: **Spearman(presence, crop area) = −0.486**, the person with 479 s on screen surfaced as a **16×19** crop against 535×373 for the one with 32 s, because `_medoid` picks for embedding centrality. §7 is the honest half: nothing proves a judge looked, `READER_LONG_SIDE` is inherited from `PER_SHEET`'s own comment and is not observable from inside the pipeline, and nothing creates pixels — `crop_px` exists to make a 13 px person *reportable*. |
| Legible evidence plan | [2026-09-08-legible-evidence.md](docs/plans/2026-09-08-legible-evidence.md) | Tasks 1–8: `sheet.fit_layout` + `READER_LONG_SIDE` + a cell box parameterized with an identity default (contact sheet byte-identical), `build_strip`'s fitted layout + the never-upscale cap + `STRIP_COLS` deleted, the packet's `strip`/`strip_px`/`storyboard_px`, `build_qc`'s one-pass complaint collection, `_largest` replacing `_medoid` with the centroid descriptor untouched + `crop_px`, the three skills + a `tests/test_skills_contract.py` that machine-checks the Rules block against `EpisodeFinding`'s own fields, five real-pixel proofs each with a control that must not move, and a 14-row mutation battery with two rows flagged as expected-uncertain rather than assumed discriminating. |
```

In `docs/build-status.md`, add the Done entry for 0.8.2 in the same shape as the
entries above it, and update the "next action" line.

- [ ] **Step 8: Run the whole suite once more**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: all green, and at least as many passing as Step 1 recorded.

- [ ] **Step 9: Commit**

```bash
git add CHANGELOG.md .claude-plugin/plugin.json docs/backlog.md \
        docs/backlog-closed.md docs/build-status.md CLAUDE.md
git commit -m "docs: 0.8.2 — illegible is a state, not a clean pass

Closes R10.1, R10.2, R10.6, R10.7 into the archive with what each row's own
premise got wrong: R10.1's pixel figure was a misreading of the sheet's
dimensions and nothing had regressed, R10.2 is anti-correlation rather than
smallness, and R10.7 named one of the two unstated gates.

Five deferrals filed: the zoom subcommand, a packed high-resolution artifact, a
judge-side validate, the storyboard re-tile, and measuring READER_LONG_SIDE."
```

---

## Self-review

Run against the design before reporting the plan finished.

- **Spec coverage.** §2 → Tasks 1–2. §3 → Task 3. §4 → Task 6. §5 → Task 5.
  §6 → Tasks 4 and 6. §7 → Task 8's changelog "Honest limits" and the design
  itself. §8's Deferred table → Task 8 Step 6, one backlog row each.
- **No placeholders.** Every code step carries the code. The two skill-text steps
  carry the exact replacement prose.
- **Type consistency.** `fit_layout` returns `(cols, cell_w)` in Task 1 and is
  unpacked that way in Task 2. `build_strip` returns `cell_px` as a two-element
  list, read as `strip["cell_px"]` in Task 3 and asserted as a list in Tasks 2 and
  7. `_evidence(ep, i, clip_stats, strip, clip_px)` is called with five arguments
  in Task 3's `pack` and in all four of its tests.
- **The two pre-existing `_evidence` tests** are named in Task 3 Step 5 as call
  sites that must be widened — they are the only ones outside the new tests.
