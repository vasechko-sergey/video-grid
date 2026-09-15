# Named regions — design

**Goal:** the reel's tone anchors stop being three percentiles of one
undifferentiated pixel set and become three measurements, each taken over a
region the author named. The nouns are data; the code knows only kinds.

**Scope:** the match-grade conductor only. The two sensors that would read the
same regions (`check_episode`'s advisory dE00 sampling box, and chroma
agreement across episodes) stay in the backlog and get the module for free.

**Source:** `docs/backlog.md` P1 — R2.1, "Grade against named subjects, not the
frame mean", from [the retro](../retro/2026-08-25-first-real-run.md) R2 and
[grade-shipped-pixels](2026-08-30-grade-shipped-pixels-design.md) §3. That slice
closed the row's frame-vs-crop half; this one is the half its own title names.

---

## 0. What is measured

Everything below is read from the only real run (8 delivered episodes, their
routes, their path metas, their source segments). The reading is deliberately
**not** the production ruler: it is Rec.709 luma over `assembly.frames_rgb`,
where `color_measure.crop_percentiles` uses `format=gray`. Absolute codes must
therefore be re-derived by the implementation; every finding below is a
comparison between regions measured the same way, which the choice of ruler does
not move.

### 0.1 The subject is between 0.14% and 37% of the crop

Projected through `geometry.extent_at_times` — the same projection the
safe-zone check and the dE00 sensor already use — and averaged over the three
`color.sample_times` samples:

| ep | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| subject, % of frame | 2.19 | 8.03 | 2.93 | 5.49 | 8.17 | 9.17 | 37.09 | 0.23 |

Median 6.76%, and a **161× spread inside one reel**. Whatever a crop-wide
percentile is measuring, it is not the same mixture twice.

### 0.2 The conductor already grades one named region — the background

Because the subject is small, the crop's profile is the background's profile.
Measured on the delivered clips, `(p5, p50, p95)`:

| ep | crop | background |
|---|---|---|
| 0 | (72.6, 94.2, 165.2) | (72.8, 94.1, 164.2) |
| 4 | (70.8, 107.8, 213.8) | (71.1, 110.0, 209.2) |
| 7 | (54.3, 133.4, 242.6) | (54.3, 133.2, 242.0) |

Seven of eight agree this closely. The exception is ep6, the one episode where
the subject fills 37% of the frame: crop p5 **23.0** against the background's
**75.5** — there, and only there, the subject supplies the dark end.

So the conductor is not measuring "the frame" as a neutral whole. It is
measuring whichever region happens to dominate by area, and on this footage that
is the water. Naming regions does not introduce a bias into a neutral
measurement; it replaces an unnamed one.

### 0.3 No single region is the best reference for all three anchors

Cross-episode standard deviation of each anchor, lower being a more consistent
shared reference, at the 1%-area gate (n=7, ep7 excluded):

| | p5 (toe) | p50 (mid) | p95 (shoulder) |
|---|---|---|---|
| crop | 18.8 | 15.0 | 36.8 |
| subject | **10.0** | 21.0 | 33.5 |
| background | 16.0 | **14.4** | 38.0 |

The subject is the best toe reference and the **worst** mid reference. That is
not a paradox: the dark end of a box around a rider is a wetsuit, a physically
constant thing across a shoot, while the middle of that box is a mixture of
person and whatever water the box also contains. This is the P3 "the sampling
box is mostly background" row, measured.

Nothing is a good shoulder reference. The highlights are specular foam, which is
a property of the wave, not of the grade.

### 0.4 The row's own first noun does not survive measurement

`skin` is a bright band inside the subject. Taking the brightest 30% of the
subject box by rank and the darkest 40% as proxies for skin and wetsuit:

| reference | cross-episode sd |
|---|---|
| subject p5 (plain percentile) | **10.0** |
| darkest 40% of subject, median | 14.9 |
| subject p50 | 21.0 |
| brightest 30% of subject, median | **34.3** |

The wetsuit band is real but **loses to the plain p5 it would replace**, and the
skin band is the worst reference of everything measured here — worse than the
crop's own p95 (36.8). At this shoot's scale a rider's skin is a few hundred
pixels of a 54×69 to 282×840 box.

Two consequences, both load-bearing. A tonal `band` kind is **not** in this
design: it was measured and it lost. And the row's title — three named subjects,
skin first — resolves on this footage to exactly **one** earned anchor.

### 0.5 The move is 23 to 34 luma codes, all of it in the toe

The common target, computed by the existing `matchgrade.common_target` over the
eight profiles, today versus with the toe taken from the subject and the mid from
the background:

| measured on | today | regional | move |
|---|---|---|---|
| delivered clips, 8 episodes (7 regional, ep7 gated) | (56.5, 107.8, 194.2) | (33.3, 109.3, 194.2) | **(−23.2, +1.5, 0.0)** |
| source segments, 4 readable (3 regional, ep7 gated) | (68.1, 108.6, 193.9) | (34.4, 110.1, 193.9) | **(−33.7, +1.5, 0.0)** |

Against a `MATCH_EPS` of 4.0 the toe moves by five to eight times the threshold
and the other two anchors do not move at all. The direction is deeper blacks —
which is the operator's own complaint from the retro ("washed out, shadows
gone") arriving a second time, by a mechanism independent of the `nostalgic`
preset's `tone_bias` that retro named: **even at zero bias, a target whose toe
is set by water sits 23 to 34 codes above where the wetsuit is.**

### 0.6 Half the run's source segments cannot be re-measured at all

`plan_ungraded` refuses four of the eight (`ep1`, `ep3`, `ep5`, `ep6`):

    color_range is pc (full, 0-255) and this pipeline's col…

They predate the 0.3.1 segment range contract. This is why §0.5's source row
reads four episodes and why §0.3's consistency table is taken from delivered clips: the
comparison between regions is sound on either, but the absolute source profiles
of half the reel are unreadable by today's code. It is the same class as the
open `golden_ride.mp4` row, on a run instead of a fixture.

---

## 1. Thesis

An anchor is a measurement, and a measurement needs a subject. Today all three
anchors share one subject — every pixel of the crop — and §0.2 shows what that
actually resolves to: whichever region is largest. The fix is not to measure the
subject *instead*; §0.3 shows that would make exposure agreement worse. The fix
is that **which region supplies which anchor is a declaration**, and the
declaration is data.

The author writes the nouns. The code knows three region kinds and three anchor
slots, and can say for each one which region it took, how much of the frame that
region covered, and — when it could not use the region asked for — what it used
instead and why.

---

## 2. The contract

### 2.1 The declaration

`REGIONS.json` beside `project.json`, found by convention, no flag — the same
shape `CONSTRAINTS.json` already establishes for author data the conveyor must
not be able to forget.

```json
{"anchors": [
  {"anchor": "toe",      "name": "wetsuit", "of": "subject"},
  {"anchor": "mid",      "name": "water",   "of": "background"},
  {"anchor": "shoulder", "name": "frame",   "of": "crop"}]}
```

Absent, the conductor behaves exactly as it does today: all three anchors from
`crop`. That path must be byte-identical, not merely equivalent.

Reaching it takes one new field. `match_grade build` takes only `--geometry`, and
`GEOMETRY.json` does not record where `project.json` was — so `ReelGeometry`
starts carrying it, stored verbatim exactly as `ReelGeometry.edl` is. A
`--regions` flag is rejected for the reason `edit_plan` rejects one for
constraints: a flag can be forgotten, and a forgotten flag here silently reverts
the grade to whole-crop anchors. A `GEOMETRY.json` written before this slice
carries no project, and that is a **third** state the report must keep distinct
from "no declaration" — "graded against the whole crop because you asked for
nothing" and "graded against the whole crop because I could not look" are
different claims about the same pixels.

### 2.2 Two closed sets and one free string

`anchor` is one of `toe` | `mid` | `shoulder`. `of` is one of `subject` |
`background` | `crop`. Anything else is refused **at load**, by name, the way
`constraints.py` refuses an unknown kind — never stored and silently unenforced.

`name` is the author's noun. The code never interprets it; it carries it into
the report so a reader sees "toe from `wetsuit` (subject, 2.19% of frame)"
instead of "toe from subject". Calling the subject region `wetsuit` is a claim
about the footage that nothing verifies (§6).

Each anchor may be declared at most once, and an undeclared anchor takes `crop`.

### 2.3 The anchor names the statistic; the region names the pixels

`toe` is p5, `mid` is p50, `shoulder` is p95 — unchanged, and not configurable.
A declaration chooses the pixel set, never the percentile. This is the whole
reason the change is small: `color.tone_arg`, `_segments`, `TONE_MIN_GAP`,
`matchgrade.common_target`, `valid_src`, `needs_tone` and `plan` are all
untouched. Three numbers still go in; they are now taken from three places.

### 2.4 `lib/regions.py`

A new pure module: declarations in, per-region pixel masks and statistics out.
No ffmpeg, no IO, no argv — the driver decodes, this decides, mirroring
`matchgrade` beside `match_grade` and `pacing` beside `scripts/pacing`.

It owns: parsing and refusing a declaration; resolving `subject` to the route's
projected extent at each sample time via `geometry.extent_at_times`; deriving
`background` as the complement and `crop` as everything; the area fraction of
each region; and the assembled profile with its per-anchor provenance.

No new computer vision. `subject` is the bbox the route already carries,
projected by the same function two existing checks already project it with.

That projection needs a `CropPath` and a `PathMeta`, and **at conductor time
neither exists on disk.** Measured: `process_episode` returns at its
`stop_after == "geometry"` arm before `reframe()` runs, and `reframe()` is what
writes `path.json` and `path.meta.json`; the conductor runs in the gap between
`--stop-after-geometry` and `--from-geometry`. Both therefore come from the
`RenderPlan`, which already carries every field `reframe()` fills the sidecar
from — so `reframe`'s sidecar construction is extracted into one builder both
callers use. A conductor rebuilding that map would be a second implementation of
the render's own geometry, which is the risk `plan_render`'s docstring already
names.

### 2.5 Where it is read

`color_measure.measure_crop` gains the region declaration and returns the
profile plus its provenance; `match_grade`'s conductor passes what it loaded and
carries the provenance into the report. Nothing else in the conveyor changes.

---

## 3. The three fallbacks

All are named absences, in the sense the
[named-absence](2026-09-07-named-absence-design.md) slice established: the report
says which one fired and why, and none is silently absorbed. Two of them are
about a region that cannot speak; the third is about an assembly that will not
order.

### 3.1 A region that cannot be located, or is too small to speak

An episode under a pan has no route — `plan_render` generates its crop path and
reads no observation — so it has no subject and no background either. An anchor
declared over one of those falls back to `crop` with the reason `no-route`. This
is distinct from a region that WAS located and found tiny, which carries a real
fraction and a real (but untrustworthy) profile.

A region supplying an anchor must cover at least `MIN_REGION_FRAC` of the frame,
averaged over the sample times. Below it, that anchor falls back to `crop` with
the reason `too-small`, and the report records the region, its measured fraction,
and the fallback.

`MIN_REGION_FRAC = 0.01`. This number is a **convention, not a measurement**:
on this pool only ep7 (0.23%) is below any plausible gate and the next episode up
is at 2.19%, so every value in that interval selects the same seven episodes.
What justifies a gate at all is not sample size — 0.23% of a 1080×1922 frame is
still 4680 pixels — but that a 54×69 tracked box over breaking water is more
likely a mis-track than a subject, and §0.3's ep7 reading (subject p50 **243.5**
against the background's 133.2) is what that looks like when it votes.

`gradedamage`'s own docstring records the same lesson from the other end, and
independently: the run's subject boxes span 2420 to 890406 px, and a 256-bin
entropy estimator over the small end is biased far enough to erase a class
boundary — which is why that sensor reads the whole frame and never the box.
A small region is not a quiet signal; it is an unreliable one.

### 3.2 A profile that will not order

Three anchors from three regions are not obliged to increase. If the assembled
profile is not strictly increasing with `color.TONE_MIN_GAP` between neighbours,
the **whole episode** falls back to its crop profile, with the reason recorded —
not the offending anchor alone, and never repaired.

The check guards the ASSEMBLY, so it does not run when the assembled profile
already equals the crop's. Without that condition a flat crop — every pixel one
value, which no declaration caused and no fallback can fix — would be reported as
three `unorderable` fallbacks that changed nothing. A flat source is
`matchgrade.valid_src`'s business and is already skipped downstream as
`flat-source`; this fallback exists only for a profile the regions made.

Repairing is what `matchgrade._repair_gaps` does to the synthetic common target,
and its docstring already says why that is legitimate there and nowhere else: no
episode has to match the target, so widening it invents nothing. A measured
source profile is a reading of real pixels; widening it would author a curve from
a number no frame contains. Falling back per-anchor is rejected for a smaller
reason: a mixed profile whose toe came from a region and whose mid came from the
crop is a third thing, neither the declaration nor the default, and the fallback
should land somewhere a reader can name.

On the eight real episodes no profile inverts. The guard has no positive
instance and is there because nothing in the contract prevents one.

---

## 4. The report

`MATCH.json` and `MATCH.md` gain, per episode, one row per anchor: the anchor,
the author's name for it, the kind, the region's measured frame fraction, the
value taken, and — when one fired — the fallback and its reason.

`MATCH.md` also states the declaration it ran under, or that none was found, so
a reel graded against the default is distinguishable from one graded against a
declaration that happened to match the default.

---

## 5. What does not change

- `color.tone_arg` and its LUT, `_segments`, `TONE_TOP_SLOPE`, `TONE_MIN_GAP`.
- `matchgrade.common_target`, `_repair_gaps`, `valid_src`, `needs_tone`, `plan`,
  `biased_target` and the mood bias — a bias still displaces the common target,
  and it now displaces a target whose toe means something.
- `check_episode.grade_damage`, `check_reel.grade_faithful`, and the advisory
  dE00. Moving the dE00 sampling box onto these regions is the next slice.
- Every episode without a `REGIONS.json`, byte for byte.

---

## 6. The honest half

**One anchor of three is earned.** The mid moved +1.5 and the shoulder 0.0
(§0.5). The per-anchor declaration is built general because the assignment is a
three-entry loop either way, not because two thirds of it were measured to help —
on other footage the mid may matter and this shoot cannot say.

**The row's first noun is gone.** Skin is the worst reference measured (§0.4),
and no stage after this one names it. The row asked for three named subjects; the
footage supports one.

**The consistency numbers are from graded pixels.** Four of eight source segments
are refused by the range guard (§0.6), so §0.3's table is measured on delivered
clips, which already carry each episode's authored tone pair, saturation 0.92,
`shadow_red` 0.1 and `mid_blue` 1.2. The toe's direction and magnitude reproduce
on the four readable sources; the cross-episode spreads do not have a source-side
reading at all.

**The ruler is not the production ruler.** §0 uses Rec.709 luma over
`frames_rgb`; the conductor uses `format=gray`. Comparisons between regions hold;
absolute codes must be re-derived through `crop_percentiles`.

**`subject` is a box, not a mask.** A box over water contains water, which is
exactly why its p50 is the worst mid reference. The seg masks the intake model
already computes are discarded and have been since 2026-08-04; a masked subject
is a real improvement this design does not make.

**One route, one subject.** An episode's route follows one tracked thing, so
`subject` means "whoever this episode follows". Naming a second person in the
same frame is unreachable without a second route.

**Nothing verifies a name.** `{"name": "wetsuit", "of": "subject"}` asserts that
the dark end of this episode's tracked box is a wetsuit. If the rider is in white
that day, the declaration is wrong and every report will faithfully print
`wetsuit`.

**The gate proves a region was used, never that it was the right region.** As
with every stage in this conveyor, presence is checkable and judgement is not.

---

## 7. Deferred

Each of these gets a `docs/backlog.md` row before this slice is finished.

1. **A tonal `band` inside a region.** Measured and rejected here (§0.4):
   `dark40` sd 14.9 against the plain p5's 10.0, `bright30` 34.3. Re-open only
   with footage where a band beats the percentile it would replace — and with an
   answer to its circularity, since a band defined by rank on the pixels being
   graded re-selects different pixels after the grade.
2. **A masked `subject`.** The seg model already runs at intake and its masks are
   dropped. A mask would raise the subject's p50 consistency, which §0.3 measures
   as the worst of six numbers. Costs a cache bump or a fresh seg pass.
3. **The dE00 sampling box onto these regions** — the folded P3 row, now with a
   module to read.
4. **Chroma agreement across episodes** — the other folded P3 row. Needs a target
   design, which this slice does not provide.
5. **Re-extract the run's segments through today's `extract`** so §0.3 can be
   re-measured on source (§0.6).
6. **`MIN_REGION_FRAC` on a pool that discriminates it** (§3.1).
