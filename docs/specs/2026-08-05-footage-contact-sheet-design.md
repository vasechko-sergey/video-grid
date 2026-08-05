# Footage contact sheet — design (2026-08-05)

**Slice S1 of the cinematic-quality playbook's P3 "editorial intelligence"**
(`docs/cinematic-quality-playbook.md` §4 item 3), closing backlog **#12
"look, don't guess"** for the selection half. Stage **5.2b** — between
footage-intake (5.2) and edit-plan (5.7).

**Goal:** give the agent that authors `selection.json` its first look at actual
pixels, and give it a way to zoom into one window when a timing or identity
question needs frames rather than numbers.

---

## 1. The problem, in code coordinates

The edit-plan agent has never seen the footage. Its entire sensory input is
text:

| What it reads | What that actually contains |
|---|---|
| `FOOTAGE.md` (`footage.Footage.to_markdown`) | a table per clip: start, dur, `shot_type`, people, motion, shake, score, `best`, description |
| `description` (`intake._describe`) | a three-token string — `"1 person, medium, dynamic"` |
| `shot_type` (`intake.shot_type`) | close/medium/wide from the primary bbox **area fraction** alone (`CLOSE_AREA=0.30`, `MEDIUM_AREA=0.08`) |

Nothing in `skills/edit-plan/SKILL.md`'s Inputs section is an image. The one
contact sheet in the repo, `scripts/storyboard.py`, samples a **rendered
episode** at delivery resolution and overlays composition grids — a
post-reframe verification tool, downstream of every decision this slice is
about.

The consequences are on the record from the 2026-08-03 run:

- Slow-mo placement took **≥6 corrections** — *"ты опять угадываешь вместо
  того чтобы взять этот кусок и посмотреть"*.
- Hero identity was described, not observed; the agent later conceded
  *"«Шаг назад» я выдумал"*.
- The delivered reel was one shot size end to end (#19) — a judgement no
  amount of `shot_type` text can correct, because the tag says how big the
  bbox was, not whether the moment has a face, a laugh, or a story.

### 1.1 A finding that belongs to S3, recorded here so it is not lost

`intake.score_window` blends four factors, and `_motion_fit` is a triangle
peaking at `MOTION_PEAK = 0.35` with a **zero at static**. A calm
personality moment (motion ≈ 0.05) keeps only ~0.14 of the motion factor,
losing ~0.22 of the 0.25 weight. It still clears `BEST_FLOOR = 0.50` on
presence and stability alone, so such windows are **not** culled — but they
rank below every action window, and `skills/edit-plan/SKILL.md` step 2 tells
the agent to *"pick the best windows (they are already ranked)"*.

That is the mechanism behind the monotony. Fixing it is **S3 (#19 shot
variety)**, not this slice. It is written down here because it dictates one
decision below: §4.2, the sheet defaults to **all** windows, not `best`.

---

## 2. Decisions locked

1. **A separate pass after intake, not inside it.** Thumbnails could ride
   intake's existing per-clip proxy decode almost free, but that costs
   `CACHE_VERSION` 6→7 — a full re-scan of the user's 99 4K clips. A separate
   pass costs ~one decode per clip, once, and **works on a FOOTAGE.json that
   already exists**. It also keeps the boundary clean: intake measures, the
   sheet presents.
2. **Two modes, one module.** `build` (one frame per window, across the
   footage) and `strip` (many frames, inside one window). They share the
   tiler; they differ only in what fills a cell.
3. **Timeline order, not score order.** The scorer already leans toward
   action (§1.1); ordering the sheet by score would point the eye the same
   way. Cells run clip by clip, window index ascending.
4. **All windows by default.** `--best-only` narrows. The sheet exists to
   show what the scorer could not judge; filtering it through the scorer's own
   floor is self-defeating. `best` is not lost — it is drawn as a border.
5. **A required conveyor stage.** `SHEETS.md` joins `V1_STAGES` right after
   `footage-intake`. Per the #15 lesson: a stage that costs nothing to skip is
   not a stage. What this can and cannot enforce is §9.
6. **No new skill.** The build is mechanical — no judgment, nothing to
   brief. `using-montage` runs it; `edit-plan` reads the output. A skill file
   would be ceremony.
7. **`storyboard.py` is untouched.** Different job (grid overlays on a
   rendered episode, full resolution), different sampling, no shared code
   worth extracting.

---

## 3. Module boundary

```
scripts/lib/sheet.py        pure: Cell, tile(), paginate(), label rendering
scripts/contact_sheet.py    driver: FOOTAGE -> times -> frames_rgb -> tile -> PNG + SHEETS.md
```

`scripts/lib/sheet.py` imports **PIL and numpy only** — no ffmpeg, no
`footage`, no run-dir knowledge. It takes RGB ndarrays and label strings and
returns a PIL image. That makes the whole layout half testable on synthetic
arrays, with no fixture and no decode.

```python
@dataclass(frozen=True)
class Cell:
    image: np.ndarray          # HxWx3 uint8 RGB, any size/aspect
    lines: tuple[str, ...]     # 1-2 label lines, rendered under the thumbnail
    marked: bool = False       # draw the `best` border

def tile(cells: Sequence[Cell], *, cols: int = COLS, cell_w: int = CELL_W) -> Image.Image
def paginate(cells: Sequence[Cell], per_sheet: int = PER_SHEET) -> list[list[Cell]]
```

Constants live in `sheet.py`: `CELL_W = 300`, `COLS = 5`, `PER_SHEET = 30`,
`LABEL_H = 34`, `FONT_PX = 13`, `MARK_PX = 3`.

**Fixed cell box, contain-fit.** Each thumbnail is scaled to fit a
`CELL_W × CELL_H` box (`CELL_H = round(CELL_W * 9 / 16)` = 169) preserving its
own aspect, and padded with black. Sources of mixed aspect (a portrait phone
clip beside 16:9 drone footage) therefore tile without a ragged grid, and no
frame is ever distorted.

A full 5×6 sheet is `1500 × 6·(169+34)` = **1500 × 1218** px — inside the
1568-px limit above which an image is downsampled before a model sees it, so
labels stay legible.

Labels render with `fonts.resolve_font()` — the same resolver `titles`/`draft`
use, already a required component of the runtime preflight. A box with no
usable font raises there, with the remedy, exactly as it does for titles.

---

## 4. The overview sheet (`build`)

### 4.1 Sampling

One cell per `FootageWindow`, one frame at the window's **midpoint**
(`w.start + w.dur / 2`). `fps` comes from `FootageClip.fps` — already in
`FOOTAGE.json`, so no extra probe.

Frames are grabbed per clip through `assembly.frames_rgb(src, times, fps)`,
where `src` is `footage_root` joined against the clip's `source` (§5 explains
why the join is required — `source` alone is a bare filename), which selects
exact frames in `_SELECT_CHUNK`-sized batches: **one decode per clip** for the
ordinary case (a clip with >60 windows costs `ceil(n/60)`, by design). This is
the same batched-select pattern that replaced the per-track output seeks in
`_cast_from_original`, which had hung >480 s on 4K.

### 4.2 What goes on it

Every window, in clip order then window-index order. `--best-only` restricts
to `w.best` (dedup survivor with `score >= BEST_FLOOR`). The decode cost is
identical either way — only the number of sheets changes — so the default is
the informative one.

Cell label, two lines:

```
MVI_3739 #2
medium · 3.4s · 0.71 ★
```

`best` is marked twice, by two separate mechanisms: the label text appends the
`★` glyph, and — independently — `marked=True` draws a plain `MARK_PX` gold
rectangle outline around the cell (no star in the outline itself). The star is
a **fact to weigh**, not a ranking to follow — `SHEETS.md` says so in as many
words, because §1.1 is precisely why the ranking should not be obeyed blindly.

### 4.3 Output

```
<out_dir>/sheets/sheet_00.png   … sheet_NN.png
<out_dir>/SHEETS.md
```

`SHEETS.md` is the artifact the router keys on and the agent's entry point:

```markdown
# Contact sheets — 99 clips, 512 windows (198 best)

Cells are in timeline order — clip, then window index. ★ marks intake's
`best` (a dedup survivor scoring >= 0.50). It is a fact to weigh, not a
ranking to follow: the window score peaks at motion 0.35 and is zero at
static, so calm, personality-forward moments rank below action even when
they are the better cut.

## sheet_00 — MVI_3739 #0 … MVI_3812 #4
![sheet_00](sheets/sheet_00.png)
```

...one section per sheet, plus a **Not sheeted** section when any clip was
skipped (§7).

### 4.4 CLI

```bash
python -m scripts.contact_sheet build --footage FOOTAGE.json --footage-root clips/ --out-dir .
python -m scripts.contact_sheet build --footage FOOTAGE.json --footage-root clips/ --out-dir . --best-only
```

`--footage-root` is required: it is the dir `FOOTAGE.json`'s `source` entries
(bare filenames — §5) resolve against, the same convention `edl_to_reel` and
`draft` already use for `EDL.source`.

---

## 5. The strip (`strip`)

Many frames inside **one** window — the answer to "where exactly is the peak
for the slow-mo?" and "who is that?", the two questions the run kept guessing
at.

```bash
# explicit range — no --footage-root: --source is a real filesystem path already
python -m scripts.contact_sheet strip --source clips/MVI_3739.mp4 \
  --start 12.4 --dur 3.0 --frames 12 --out strip.png

# sugar: resolve the range from a FOOTAGE window
python -m scripts.contact_sheet strip --footage FOOTAGE.json --footage-root clips/ \
  --source MVI_3739.mp4 --window 2 --frames 12 --out strip.png
```

`--source` is a filesystem path when `--footage` is absent (used as-is, no
root needed), and the exact `FootageClip.source` key — a **bare filename**,
since intake stores only `Path(path).name`, never the path it was given —
when `--footage` is present; `--footage-root` (required together with
`--footage`/`--window`) is the dir that name resolves against, so `resolve_window`
can return something the caller can actually decode, not the bare name alone.
A `--source` that matches no clip in `FOOTAGE.json` fails loud, listing the
sources it has (the `build_edl` precedent for a mistyped source). A resolved
path absent from disk fails loud too, naming `footage_root` and `source`
separately (`extract.extract_edl`'s precedent), so a user sees which half is
wrong.

`--frames` samples evenly across the range (`start + (k + 0.5) * dur / n`,
the `storyboard._sample_times` convention). Each cell is labelled with its
absolute timestamp (`12.52s`) so a chosen frame converts straight into a
`start_offset` for `selection.json`. Columns: `min(frames, 6)`.

The strip writes only where `--out` says. It is **not** a stage and leaves no
conveyor artifact — it is asked for when a question arises.

---

## 6. Conveyor wiring

`montage.V1_STAGES` gains one entry, directly after `footage-intake`:

```python
Stage("contact-sheet", "SHEETS.md", "required",
      "contact_sheet build CLI (run by using-montage; edit-plan reads the sheets)",
      None),
```

It sits there rather than immediately before `edit-plan` because it depends on
nothing but `FOOTAGE.json` — which means the sheets exist in time to be shown
at **CP1**, alongside the brief conversation, not only at CP2.

Two skills change:

- **`using-montage`** — the step after footage-intake runs the build and
  **looks at every sheet** before moving on. The sheets are also offered to
  the user at CP1.
- **`edit-plan`** — step 1 (Recon) lists `SHEETS.md` + its sheets as a
  required read beside `FOOTAGE.md`, and step 2 gains the instruction to pick
  from what the frames show, not from the score column alone. The `strip`
  command is documented there as the way to resolve a timing question into a
  `start_offset`.

No stage's artifact, contract, or gate changes. `next_action` needs no code
change — the new stage is data in the existing table.

---

## 7. Failure modes

- **A clip that will not decode** is skipped, its windows omitted, and the
  clip named under a **Not sheeted** heading in `SHEETS.md` with the error
  (trimmed to its last meaningful line — a `proc.run` failure banner runs to
  ~30 lines, and a `SHEETS.md` with many skips must not become thousands of
  lines over it). Aborting the whole build over one bad file would lose the
  other 98 clips' sheets; this mirrors intake's quarantine-and-report
  precedent (`intake_report.json`). Skipped, but never silently.
- **Every clip with a candidate window failing to decode** is a different
  failure, not a bigger version of the one above: it is the signature of a
  wrong `--footage-root`, a moved footage folder, or a broken ffmpeg install
  — not one corrupt file among many. `build_sheets` raises instead of writing
  a `SHEETS.md` that looks like a normal, if thin, success; no `SHEETS.md` is
  written at all. This is what keeps §9's presence gate honest — without it, a
  wrong root produced a `SHEETS.md` with zero cells that `next_action` still
  read as "done".
- **A window whose midpoint lies past the stream end** surfaces as
  `frames_rgb`'s existing `RuntimeError` naming the frame numbers. It means
  `FOOTAGE.json` disagrees with the file on disk, which is a re-run of intake,
  not something a viewer should paper over — so it is reported as a clip-level
  skip with that message. Because `frames_rgb` decodes every window of a clip
  in one batched call, this one bad window skips the WHOLE clip, not just
  itself (§10 — deferred, not this slice).
- **No windows at all** (an empty or `--best-only`-emptied set — nothing was
  ever a candidate, as opposed to every candidate failing, above) writes a
  `SHEETS.md` that says so and produces no PNGs. The stage is then "done"
  with an honest empty answer rather than a missing artifact that would
  wedge `next_action` forever.
- **No usable font** → `fonts.resolve_font()` raises with its remedy.

---

## 8. Testing

**`lib/sheet.py` — pure, no fixture, no ffmpeg:**
- `tile` places cell *k* at `(k % cols, k // cols)` and returns the computed
  canvas size for 1, 5, 6, and 30 cells.
- contain-fit: a 4:3 and a 9:16 array both land in the same box, undistorted,
  black-padded.
- `paginate` splits 30/31/0 cells into the expected page counts.
- an over-long label is truncated to the cell width rather than overflowing
  into the neighbour.
- `marked=True` changes pixels at the border and nowhere else.
- determinism: tiling the same cells twice yields identical bytes.

**Driver — real ffmpeg on the repo fixture:**
- `build` over a small hand-made `FOOTAGE.json` writes the expected number of
  sheets, each of the expected dimensions; `SHEETS.md` links every PNG
  written and no PNG that was not.
- every cell label carries its window index, and the sheet order is clip then
  index (asserted against the FOOTAGE order, not re-derived).
- `--best-only` drops the non-`best` windows and nothing else.
- a clip path that does not exist lands under **Not sheeted** and the other
  clip's sheet is still written.
- every candidate window failing to decode (a wrong `footage_root` among
  them) raises and writes no `SHEETS.md`, proved distinct from the
  genuinely-empty-selection case, which still writes the honest-empty one.
- the FOOTAGE fixture these tests write carries a bare filename `source` plus
  a separate `footage_root`, matching what `intake.py` actually produces —
  not an absolute path standing in for both, which would pass against a
  driver that never joined a root at all.
- `strip` produces one image with `--frames` cells whose timestamps ascend,
  and `--window` resolves to the same range as the explicit `--start/--dur`.

**Router:** `next_action` reports `contact-sheet` as `next` on a run that has
`FOOTAGE.json` and no `SHEETS.md`, and does not point at `edit-plan` until it
exists.

---

## 9. Honest limits

- **The conveyor can force the sheet to exist. It cannot prove the agent
  looked at it.** This stage gates the presence of the artifact — `SHEETS.md`
  on disk — not the use of it, and presence is not the same claim as "holds a
  frame". Calling it a quality gate would be the same overclaim the
  attested-run slice had to retract from the backlog. What the gate actually
  buys: a run can no longer reach `edit-plan` without a `SHEETS.md`, and (§7)
  `build_sheets` refuses to write one that silently claims success when every
  candidate window failed to decode — it raises instead, naming the likely
  cause (a wrong `--footage-root`, a moved footage folder, a broken ffmpeg
  install). Only a genuinely empty selection (no windows at all, or
  `--best-only` matching none) still earns a `SHEETS.md` with zero frames —
  that answer is real, not a masked failure, and an absent artifact would
  wedge the router on this stage forever.
- **One frame per window is a sample, not the window.** A midpoint frame can
  miss a wipeout two seconds later. That is what `strip` is for, and why the
  sheet's label carries the window's duration.
- **The sheet does not show the delivered framing.** A 16:9 source cell is not
  what a 9:16 reel will keep. Drawing a centred crop guide was considered and
  rejected in §10 — it would be a confident lie, since the real crop follows a
  hero route that does not exist yet at selection time.
- **`shot_type` is still bbox area.** Seeing the frames does not change the
  tag; it lets a human or an agent overrule it. Making variety an actual
  objective is S3.

---

## 10. Deferred, with reasons

- **A 9:16 (or platform) crop guide on each cell.** The shipped crop is
  route-driven and the route is computed downstream of selection; a centred
  guide would misinform in exactly the cases that matter (a subject entering
  from frame edge). Revisit with S5, where a per-episode QC agent judges
  composition against a route that exists.
- **A third mode: a contact sheet of the delivered reel.** Useful for CP3, but
  it overlaps `reel-review` (S5) and `storyboard.py`; deciding its shape
  belongs with that slice.
- **Caching thumbnails inside intake.** Nearly free at runtime, but costs
  `CACHE_VERSION` 6→7 and a full re-scan. Revisit only if a cache bump is
  already being paid for another reason.
- **Per-window multi-frame cells on the overview** (a 3-frame mini-strip per
  cell). Same decode cost, but at 300 px a cell that holds three frames holds
  none of them legibly. The `strip` mode covers the need without the
  compromise.
- **A per-window catch around the batched `frames_rgb` call.** Today one
  window whose midpoint lies past the stream end drops the WHOLE clip's sheet
  (§7), because `build_sheets` decodes every window of a clip in one
  `frames_rgb` call and the whole call raises when any single frame number is
  past the stream end. Design-sanctioned for this slice — it is still a
  clip-level skip, reported like any other decode failure — but it is a
  sharper edge than the other skip causes (a single stale window can cost an
  otherwise-good clip its whole sheet). Catching per-window instead of
  per-clip belongs with the next slice that touches this loop.
