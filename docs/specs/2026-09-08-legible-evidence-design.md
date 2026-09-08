# Legible evidence — design

**Date:** 2026-09-08 · **Backlog rows:** R10.1, R10.2, R10.6, R10.7 ·
**Source:** [the first real run's retro](../retro/2026-08-25-first-real-run.md) R10

> **Illegible is a state, not a clean pass.**
>
> Three artifacts in this tree are *evidence handed to a judge* — the QC frame
> strip, the cast candidate crop, and the judge's own output contract. Each is
> produced with no model of its reader. A judge that cannot see is
> indistinguishable, downstream, from a judge that looked and found nothing.

---

## §0 · What the measurements overturned

Every claim below was checked against the only real run before anything was
designed. Two of the four rows had premises that needed correcting, and the
correction to R10.1 is the content of this slice rather than a footnote to it.

### §0.1 R10.1's number is a misreading, and nothing regressed

The row says the strip is **"200×406 px per frame"**. `1800 ÷ 9 = 200` and
`406` is the sheet's full height — but the sheet is not one row of nine. Today's
code reproduces the run's strip geometry exactly:

```
9 frames, STRIP_COLS=6 -> 1800x406        (the run's strip.jpg: 1800x406)
```

Six columns of `CELL_W = 300` by two rows of `CELL_H + LABEL_H = 203`. The real
figure is worse than the row's in one direction and better in another, and both
halves matter:

| | rendered | after the reader's downscale to a 1568 long side |
|---|---|---|
| picture per frame | **95×169** | **83×147** |

`CELL_H = round(CELL_W * 9 / 16)` is a **16:9 box**, and every delivered reel in
the run is **9:16**. `_fit` contains by the shorter dimension, so a portrait frame
uses 95 of the box's 300 columns and **68 % of every cell is black padding**. What
that costs is measured in §2: the same pixel budget spent on a box shaped like the
content gives 313×556.

Nothing regressed. `CELL_W`/`CELL_H` have carried these values since `4efe976`
(2026-08-05), and the run used exactly this code.

### §0.2 The same packet already carries a 22× better artifact

`episode_qc.pack` writes `strip.jpg`; `process_episode` had already written
`storyboard.jpg` into the same episode's scratch dir, from the **same file**
(`storyboard.build(m.out_path, …)` — `m.out_path` is the delivered clip). Both
are in the packet, and the judge template tells the judge to "open and look at
both" as equals:

| | grid | frame rendered at | as the reader sees it |
|---|---|---|---|
| `storyboard.jpg` | 4×2 of 6 frames, 4320×3844 | 1080×1922 | **392×698** |
| `strip.jpg` | 6×2 of 9 frames, 1800×406 | 95×169 | **83×147** |

**129× the area rendered, 22.4× as read.** The strip is strictly the worse
artifact at showing pixels; it is better only at carrying nine samples instead
of six and at labelling each with an absolute timestamp.

And `evidence.json` — the packet's own manifest of what is in it — carries eight
keys (`idx`, `clip`, `intent`, `storyboard`, `naturalness`, `checks`, `track`,
`geometry`) and **does not name the strip at all**. Its path exists only inside
the SKILL's template-fill instruction.

### §0.3 The judges did not judge from the strip — six of eight say so

This is the finding that reframes the row. Of the eight surviving judges'
`findings.json` summaries, **six describe building their own evidence**:

- **ep2** — *"opened the 9-frame strip and the 6-panel storyboard, then pulled
  full-resolution frames from the delivered clip at 0.32s, 1.61s, 2.89s, 4.18s
  and 5.47s"*
- **ep7** — *"visible modulation still in the foam at a **3x zoom** on 0.05s and
  1.95s"*
- **ep0** — reconstructed the crop rect from `path.json`; *"my reconstruction
  reproduced the delivered frame's luma mean to 0.1"*
- **ep6** — *"recovered crop_x 1010 -> 1140 across the shot so patches could be
  compared pixel-for-pixel"*
- **ep3**, **ep4** — both "pulled" their own frames

Only ep1 and ep5 show no such signal. The retro's own sentence — *"three judges
reached for tools that do not exist in their harness; one hit `magick not
found`"* — is the visible failure of this same behaviour, not a separate one.

`contact_sheet strip` **already does exactly what they were doing**: any file,
any range, any frame count, one cell per frame labelled with its absolute
timestamp, documented in its own docstring as *"the answer to 'where exactly is
the peak?'"*. The judge template names neither it nor the launcher that runs it.
This is [R4.2](../backlog.md) — a built tool the agent rebuilt privately —
occurring inside one required stage.

### §0.4 R10.2 is not "too small". Presence and legibility are ANTI-correlated

The row says cast candidates are "shown too small to identify". Measured over the
run's 15 candidates, against each one's own recorded on-screen presence:

```
 id presence_s       crop       px
  0      730.7   55x141       7755
  1      479.5   16x19         304
  2      345.0  179x344      61576
  3      307.3   13x15         195
  4      172.2   22x40         880
  5      120.8   13x12         156
 ...
 11       43.0  466x354      164964
 13       31.7  535x373      199555

Spearman(presence, crop area) = -0.486        7 of 15 under 5000 px
```

**The longer a person is on screen, the smaller the crop the operator is shown.**
The person with eight minutes of presence is a **16×19** crop — 304 pixels. The
person with thirty-one seconds is 535×373, **1279× the pixels** of candidate 5.

The mechanism is `_medoid`: the representative crop is the cluster member whose
embedding is closest to the centroid. A person present for 730 s appears across
many clips at many scales, so their centroid averages over all of them and the
medoid is a *middling* view — on a drone shoot, usually a distant one. A person
present for 31 s appears in one close shot, so their cluster's centroid **is**
that close crop. Identity-centrality is not legibility, and nothing said so.

### §0.5 R10.6 and R10.7 confirmed, and R10.7 is larger than filed

`suggestion` appears in `skills/episode-qc/episode-reviewer.md` exactly once, at
line 104, as the placeholder `"..."` inside the output JSON example. The `Rules`
block enumerates `severity`, `route`, `confidence`, `evidence` and the three
forbidden keys — and names neither `suggestion` **nor `axis`**. Both are hard
gates in `EpisodeFinding.__post_init__`. The row named one of the two.

`build_qc` iterates episodes and raises on the **first** bad finding, after every
judge has already exited. One malformed field kills the validation of all eight
episodes and buys back nothing about the other seven. On the run all eight judges
happened to satisfy both unnamed gates, so this never bit — it is a hazard, not a
recorded failure.

---

## §1 · The shape

Four halves, one thesis. Nothing here is a new gate and nothing here lowers one.

1. **§2** — the strip's layout is fitted to its content and to a stated reader
   budget instead of a 16:9 box and a fixed column count.
2. **§3** — the packet records the pixel size of the evidence it hands over, so
   "too small to judge" becomes a readable fact rather than a guess.
3. **§4** — the extraction six of eight judges already performed gets a name.
4. **§5/§6** — the cast crop stops being picked for a purpose it does not serve,
   and the judge's contract is stated in full and checked in one pass.

---

## §2 · The strip's layout follows its content

`sheet.tile` serves two callers with opposite needs: `contact_sheet build`
sheets 16:9 source footage at a fixed 5 columns, and `build_strip` sheets a
delivered clip of whatever aspect the project chose. The 16:9 box is right for
the first and wrong for the second.

**`sheet.tile` gains an explicit cell box, defaulting to today's values**, so
`contact_sheet build` is byte-identical and untouched:

```python
def tile(cells, *, cols=COLS, cell_w=CELL_W, cell_h=CELL_H) -> Image.Image:
```

**A new pure `sheet.fit_layout`** picks the column count whose cell picture is
largest with the whole sheet's long side inside a stated budget:

```python
READER_LONG_SIDE = 1568   # the budget PER_SHEET's comment already assumes; see §7.2

def fit_layout(n: int, aspect: float, *, budget: int = READER_LONG_SIDE) -> tuple[int, int]:
    """(cols, cell_w): over every column count 1..n, the one whose cell picture is
    widest with max(sheet_w, sheet_h) <= budget. `aspect` is w/h of the content, so
    the cell box IS the content's shape and the contain-fit letterboxes nothing."""
```

`build_strip` takes the aspect from the frames it has already decoded
(`images[0].shape`), so no probe and no new parameter, and it caps the cell at
the source's own width — the strip never claims a resolution the footage does not
carry (§7.3). `STRIP_COLS = 6` is deleted; a constant that fixed the column count
is what forced nine portrait frames through a layout chosen for landscape ones.

Measured, for the run's own case — nine frames of a 9:16 delivered clip:

```
today    6x2   picture  95x169 rendered  ->  83x147 as read   (sheet 1800x406)
fitted   5x2   picture 313x556 rendered  ->  313x556          (sheet 1565x1180)
                                             3.8x linear, 14.3x area
```

The fitted sheet lands **at** the budget, so nothing is downscaled and rendered
equals seen. The same function serves every other aspect without a second table:

| content | n | grid | picture |
|---|---|---|---|
| 9:16 | 9 | 5×2 | 313×556 |
| 16:9 | 9 | 3×3 | 522×294 |
| 1:1 | 9 | 3×3 | 488×488 |
| 9:16 | 6 | 3×2 | 421×748 |

Note that one row of nine is **not** the answer — 9×1 gives 174×309, worse than
5×2's 313×556, because a single row spends the whole budget on width and leaves
the height unused. This is why the column count is fitted rather than re-typed.

---

## §3 · The packet names its own pixels

`_evidence` gains three keys:

- **`strip`** — the strip's path. It was never there; the judge learned of the
  strip only from the SKILL's template fill, so a reader of `evidence.json` alone
  could not tell whether one existed (the same "absent is reported as absent"
  rule the storyboard key already follows).
- **`strip_px`** — `[w, h]` of one frame's picture inside the strip, from
  `build_strip`'s own return value.
- **`storyboard_px`** — `[w, h]` of one frame inside the storyboard, which is the
  delivered clip's own dimensions, because `storyboard.build` pastes frames at
  full resolution. Read from the `probe_stream` call `pack` already makes.

**No threshold is introduced.** There is nothing to derive a "below X you cannot
judge composition" constant from, and a gate on an invented number would be
exactly the pattern [R2.4](../backlog.md) files. The numbers are *reported*; what
they let the judge do is prefer the right artifact and say so. The template's
wording follows: the strip is the timeline index, the storyboard is the
composition evidence, and for anything requiring a real look the judge pulls its
own frames (§4).

These are **rendered** sizes. The packet cannot know what the reader's own
pipeline does to an image; §2 exists so that, for the strip, rendered and seen
coincide.

---

## §4 · The extraction gets a name

The judge template gains the launcher preamble every other runner skill already
carries and one command:

```
"$VG" scripts.contact_sheet strip --source <evidence.json "clip"> \
      --out <your own path> --start T --dur D --frames N
```

The judge chooses its own timestamps, which is the half a packed artifact cannot
do — ep2 wanted 0.32/1.61/2.89/4.18/5.47 s and ep7 wanted 0.05 and 1.95 s, and no
`pack`-time sampling would have produced either set.

The template also asks the judge to name in its `summary` what it pulled. That is
**not** a memory mechanism — [R10.5](../backlog.md) (no memory between rounds)
stays open — but a later round's judge reads `EPISODE_QC.md`, and a summary
saying which timestamps were examined is strictly more than today's nothing.

**Why not a new `episode_qc zoom` subcommand:** it would wrap a command that
already exists and would itself have to be named in the same template, so it
solves the naming problem by adding a second thing to name. Filed in §8.

**Why not pack a high-resolution artifact by default:** it pays decode cost on
every episode of every run to guess timestamps that the two judges who wanted
them chose for themselves. Filed in §8.

---

## §5 · The representative crop is the largest, the descriptor is still the centroid

`surface_crops` keeps clustering, keeps the centroid descriptor, keeps the
presence sum and the presence ranking. The cluster's representative crop
becomes its largest-area member's, not its medoid's — and it is **not only the
picture** that moves when the pick changes.

```python
picked.append(replace(_largest(members), descriptor=cent,
                      presence=float(sum(m.presence for m in members))))
```

`replace` overrides exactly the two fields that are properties of the whole
cluster — `descriptor` and `presence` — and nothing else. Every other field
`picked[i]` carries, crop included, comes from whichever member `rep` names:
medoid before this slice, largest-area now. `source`, `conf` and `tid` were
never independent of the picture — they always described the same member the
crop came from — so swapping which member wins moves them together with the
picture, not the picture alone; `save_cast_candidates` writes `source` and
`conf` straight into `cast_candidates.json`. **This is the right shape, not
merely a tolerated side effect**: the manifest's `source`/`conf` now describe
the crop the human is actually looking at, where the medoid pick could have
named a detection on a different clip than the one shown. The identity
mathematics alone is untouched — `descriptor` is still the re-L2-normed mean,
so every downstream consumer of it (`hero.resolve`, `track.build_route`,
`cast.json`) sees exactly what it sees today. What changes is which of the
cluster's own crops the human is shown, and which member's own detection now
accompanies it.

`_largest` reads each member's crop size: `crop_rgb.shape` for the live form,
`Image.open(path).size` for the cached form (a header read, not a decode), and 0
for a member carrying neither — that member simply never wins, rather than
raising.

`save_cast_candidates` records **`crop_px: [w, h]`** per candidate, and the
footage-intake SKILL names it when presenting a candidate to the human. This is
what makes a 13×12 crop a *reported* state instead of an invisible one — see
§7.3: nothing here creates pixels.

This runs entirely in intake's Phase 2 assembly over already-cached per-clip
results (`save_cast_candidates([e for r in ok for e in r.cast], …)`), so
**`CACHE_VERSION` does not move** and no footage is re-scanned.

---

## §6 · The judge's contract is stated in full and checked in one pass

**Stated.** The template's `Rules` block gains the two gates it never named:

- `axis` ∈ (composition, colour, impression, path, hero) — the five judged
  above; a finding on any other axis has nowhere to be routed.
- `suggestion` — non-empty, the concrete change. Not optional: a finding naming
  no change is not actionable, and `episode_qc build` refuses the whole run over
  it.

**Checked in one pass.** `build_qc` stops raising on the first failure. It walks
every episode, validates every finding, collects every complaint with the episode
index and finding index that produced it, and raises once:

```
episode_qc build: 2 of 8 packets are not valid findings files.
  ep1 finding 0: EpisodeFinding.suggestion must be a non-empty string (the change)
  ep1 finding 2: EpisodeFinding.axis 'framing' not in ('composition', 'colour', …)
  ep4: episode 4 has no findings.json in <path> — every episode must be judged …
Re-dispatch the judges named above and re-run build; every complaint from this
run is listed, so one pass names them all.
```

A missing `findings.json` is collected the same way, so one build names every
episode that needs re-dispatching instead of one per round. The refusal itself is
unchanged in strength: a single bad packet still refuses the whole run, because
`EPISODE_QC.json` describes the reel and a partial one would be a reel partly
unjudged.

**Why not an `episode_qc validate` subcommand for the judge to self-check:** the
row asks to "validate the shape early, **or** state it in the template", and
stating it is the root fix — the shape was unstated, not unstateable. Filed in §8.

---

## §7 · The honest half

### §7.1 Nothing here proves a judge looked

The `episode-qc` SKILL's own Boundaries section already says the gate proves the
artifact's presence and its binding to these exact bytes, never that anyone
opened the strip. That is unchanged. An empty `findings` list from a judge that
read nothing still validates, still stamps, still passes. What this slice removes
is the excuse — not the possibility.

### §7.2 The reader's pixel budget is inherited, not measured

`READER_LONG_SIDE = 1568` is taken from the comment already sitting on
`sheet.PER_SHEET` ("1500 x 1218 px, inside the 1568 limit"). **No measurement in
this repository establishes it**, and none can: what a subagent's image pipeline
does to a JPEG is not observable from inside the pipeline. The design is built to
survive the constant being wrong — `fit_layout` is a maximization *under a stated
budget*, so a wrong budget yields a sheet that is smaller or larger than optimal,
never one that is broken, and the 16:9-box defect §0.1 measures is independent of
it entirely.

### §7.3 Nothing here creates pixels

If a person was only ever thirteen pixels tall in the footage, the largest member
of their cluster is still thirteen pixels, and `fit_layout`'s cap on the source's
own width means the strip renders a small clip small rather than upscaling it into
a claim. `crop_px` and `strip_px` exist precisely so that case is *reportable*.
The alternative — upscaling to a minimum display size — was rejected: an
interpolated 13×12 crop looks like evidence and is not.

### §7.4 What stays open

- [R10.5](../backlog.md) — "judge only what changed", and memory between rounds.
  §4's summary line is a byproduct, not a mechanism.
- [R10.9](../backlog.md) — the evidence packet has no digest binding of its own,
  which is how a stale packet reached three judges. Deliberately out of scope:
  that is a provenance question, not a legibility one, and it belongs with the
  slice that gives `provenance.stamp`'s `inputs` its first reader.
- Whether a judge that *can* see finds more. Six of eight already routed around
  the strip, so the honest prediction is that this slice reduces wasted judge
  turns and unblocks the two that did not — not that it changes a verdict.

---

## §8 · What this does not touch

- **`storyboard.py`'s own geometry.** It is already 22× the strip as read.
  Re-tiling six portrait frames 3×2 instead of 4×2 buys 12 % (392×698 → 441×784),
  and `storyboard.build` sits on `process_episode`'s hot path behind a golden.
  Filed.
- **`contact_sheet build`** — the footage overview. Its sources are 16:9 and its
  columns are explicit; `tile`'s new parameters default to today's values, so it
  is byte-identical and no golden moves.
- **`CastEntry`, `intake_cache`, `CACHE_VERSION`.** §5 is a Phase-2 decision over
  cached results.
- **The gate's strength anywhere.** No threshold is added, none is loosened, and
  no waiver is created.

### Deferred (each of these gets a backlog row)

| Item | Why not now |
|---|---|
| `episode_qc zoom` subcommand | Wraps an existing command and would need naming in the same template it exists to serve (§4). |
| Pack a high-resolution artifact by default | Pays decode on every episode to guess timestamps the judges choose themselves (§4). |
| `episode_qc validate` for judge self-check | The row asks "validate early **or** state it"; stating it is the root (§6). |
| Re-tile the storyboard 3×2 for portrait content | 12 % on a hot path behind a golden (§8). |
| Measure `READER_LONG_SIDE` | Not observable from inside the pipeline (§7.2). |
