# Sensor provenance — design

**Date:** 2026-09-16
**Status:** design
**Closes:** the dE00 sampling-box row folded into backlog R2.1; the inert
`_report_md` regions gate; the half-covered default `MATCH.md` pin;
`grade_faithful`'s missing sample count.

A reading is a claim about a set of pixels. Four reports in this tree state a
reading without stating which pixels, how many frames, or against what
baseline — and one states a winner among three numbers that tie. This slice
makes each reading name its own provenance, and shares ONE region resolver
between the stage that authors a grade and the sensor that describes it.

---

## §0 What was measured

All numbers below come from the 2026-06 run, read-only: eight delivered
episodes, their frozen routes, path sidecars and pre-grade segments.

### §0.1 The row's premise reproduces, on a second statistic

The folded row says the dE00 sampling box "is mostly background, not the
subject". Measured through today's instrument — the raw source at the route
bbox against the shipped clip at the projected extent, five samples at
fractions of the route's span — over all eight episodes:

| ep | subject (today) | background | crop | subject fraction |
|---|---|---|---|---|
| 0 | 4.29 | 4.96 | 4.95 | 2.06 % |
| 1 | 1.44 | 1.84 | 1.81 | 8.19 % |
| 2 | 2.93 | 2.85 | 2.85 | 3.43 % |
| 3 | 1.20 | 0.80 | 0.83 | 5.49 % |
| 4 | 2.83 | 3.23 | 3.20 | 8.57 % |
| 5 | 1.94 | 1.78 | 1.78 | 9.30 % |
| 6 | 0.89 | 1.31 | 1.14 | 37.54 % |
| 7 | 2.05 | 1.37 | 1.38 | 0.24 % |

The crop's reading equals the background's to within **0.03 on seven of the
eight** episodes. That is the named-regions §0.2 finding — the crop's profile
IS the background's, because the subject is a percent or two of the frame —
reproduced on a completely different statistic. The single exception is ep6,
the 37.5 % subject, where the crop (1.14) sits between subject (0.89) and
background (1.31), exactly as an area-weighted mean must.

So "the whole frame" was never a neutral reference for this sensor either. It
was the water.

### §0.2 The consequence is small wherever the region can be trusted

Premise confirmed does not make the fix valuable. Measured on the render pair
(§0.3) for the four episodes whose plans build:

| ep | subject | background | crop | subject − crop | subject fraction |
|---|---|---|---|---|---|
| 0 | 5.13 | 5.32 | 5.32 | 0.19 | 2.19 % |
| 2 | 3.07 | 2.59 | 2.61 | 0.46 | 2.93 % |
| 4 | 2.15 | 2.21 | 2.21 | 0.06 | 8.17 % |
| 7 | **1.58** | **0.59** | 0.59 | **0.99** | **0.23 %** |

On the three episodes whose box covers 2–8 % of the frame the region choice is
worth 0.06–0.46 dE00. On ep7 it is worth 0.99 — a 2.7× difference — and ep7's
box is 0.23 % of the frame, below `regions.MIN_REGION_FRAC`, the one box the
region resolver refuses to read.

**The region choice matters most exactly where the region is least
trustworthy.** That inverts what the slice should build: not a re-aimed box,
but a gate and a name. A sensor that reads ep7's box and reports 1.58 as "the
subject" is reporting the grade's effect on breaking whitewater under the name
of a person — the same mis-track the named-regions design measured from the
tone side (a subject p50 of 243.5 against the background's 133.2).

### §0.3 The advisory already runs only when the render pair exists — and
re-decodes anyway

`check_episode._subject_delta_advisory` is called from exactly one place:
`_grade_damage`, after its own early return

```python
if plans is None or source is None:
    return CheckResult("grade_damage", None, {"status": "not-checked", ...})
```

so the advisory is **already gated on the (graded, plain) render pair
existing**. Two lines above the call, that pair has already been decoded to RGB
at `color.sample_times(graded_plan.dur)`, in the delivered crop's own geometry.
The advisory ignores it and decodes twice more — the raw source and the shipped
clip — at a different time set, in a different geometry, through four extra
`ffprobe` calls (`_last_sampleable_t`).

Per episode today: 4 decodes and 4 probes for two colour numbers about one
grade. Riding the pair costs **zero coverage** — there is no episode that gets
a dE00 today and would not get one after.

### §0.4 The baseline swap moves the number by up to 0.84

Same four episodes, today's source-vs-clip reading against the render pair's:

| ep | today | render pair | move |
|---|---|---|---|
| 0 | 4.29 | 5.13 | +0.84 |
| 2 | 2.93 | 3.07 | +0.14 |
| 4 | 2.83 | 2.15 | −0.68 |
| 7 | 2.05 | 1.58 | −0.47 |

For scale: the old blocking bar's entire healthy-to-damage separation was
**0.75 dE00** (healthy to 4.29, damage from 5.04; grade-delta-sensors §0.4).
The baseline is worth as much as the class boundary was. The sensor votes on
nothing since 2026-08-31, so this is a change of description and not of
verdict — but it is not a rounding difference, and this design records the
before-and-after rather than claiming equivalence.

Three things separate the two readings: the encode (the shipped clip is
CRF-18; the render pair is pre-encode), the time set (route-span fractions vs
plan fractions), and the source box, which today is **not** intersected with
the crop — on ep6 and ep7 it reads source pixels that never ship, worth 0.02
and 0.11 dE00.

### §0.5 `dominant` is undecidable on three of four real episodes

`color_fidelity.evaluate` reports `dominant`, the component of (luma, chroma,
hue) that moved most — named directly in the QC judge's own template. Measured
across the sample counts this slice moves between (5 today, 3 on the render
pair):

| ep | n | ΔL* | ΔC* | ΔH* | dominant |
|---|---|---|---|---|---|
| 0 | 3 | 0.61 | 3.90 | 4.71 | hue |
| 0 | 5 | 0.68 | 4.27 | 4.22 | **chroma** |
| 2 | 3 | 0.55 | −4.13 | 0.36 | chroma |
| 2 | 5 | 0.54 | −3.99 | 0.18 | chroma |
| 4 | 3 | −0.77 | 0.89 | 0.80 | chroma |
| 4 | 5 | −0.77 | 0.45 | 0.77 | **luma** |
| 7 | 3 | −0.03 | −1.22 | 1.22 | hue |
| 7 | 5 | −0.04 | −1.26 | 1.15 | **chroma** |

It flips on **three of the four** episodes, and in every flip the top two
components are within 0.5 of each other. ep7 at n=3 is an exact tie —
|ΔC\*| = |ΔH\*| = 1.22 at the reported precision — resolved by the order of the
tuple `_COMPONENTS`, not by the data. ep4 at n=5 crowns `luma` at −0.77 over a
`hue` of 0.77: a 0.00 margin at two decimals.

This is not a defect this slice discovers and leaves alone: **this slice moves
the sample count from 5 to 3**, so leaving the field in place means shipping
the flips. The three signed components are already in the report and are the
actual explanation; `dominant` is a ranking of them that cannot be made.

### §0.6 The box never leaves the frame, and two of the function's branches
cannot fire

Projecting **every** route point — 2036 across the eight episodes, not only the
five sampled — into the delivered frame:

| ep | route points | partly outside | fully outside | points under 1 % |
|---|---|---|---|---|
| 0 | 264 | 0 | 0 | 20 |
| 1 | 378 | 0 | 0 | 0 |
| 2 | 347 | 0 | 0 | 0 |
| 3 | 252 | 0 | 0 | 0 |
| 4 | 221 | 0 | 0 | 0 |
| 5 | 347 | 0 | 0 | 0 |
| 6 | 157 | **6** | 0 | 0 |
| 7 | 70 | 0 | 0 | **70** |

No projected box is ever **fully** outside the delivered frame. So
`_box_mean_rgb`'s documented worst case — "collapses to a single pixel at the
nearest edge: a poor measurement of a subject no longer in frame, but a defined
one" — is unreachable on this footage. It is a defence, not a live hazard, and
a mask-based read needs no such fabrication at all: a box with no overlap
contributes no pixels and the fraction says so, which lands on the named
`too-small` instead of on an invented edge colour.

Two more branches in the same function cannot fire:

- `_subject_delta_advisory`'s own `if source is None` — the caller returned on
  that condition already (§0.3).
- Consequently its reason string, `"no source clip or no tracked subject"`, is
  a disjunction whose first half can never be the cause. Same shape as
  `OutroFit.cause` before the named-absence slice: one string for several
  absences, so the reader cannot tell which happened.

ep7 is under 1 % at **all 70** of its route points (0.09–0.70 %), so its
`too-small` verdict is structural, not a sampling accident. ep0 is under 1 % at
20 of 264 — a time-varying case the five-sample read happened to miss entirely
(its sampled fractions were 1.35–3.50 %).

---

## §1 The rule

**A reading names the pixels, the count and the baseline it came from.**

Concretely, for every sensor this slice touches:

1. The pixel set is resolved by ONE rule, shared with the stage that authors
   the grade — `lib/regions.py` — and the reading records which region supplied
   it, at what fraction, and, when the declared region could not, which named
   fallback fired.
2. Both sides of a comparison come from the same baseline. For a grade
   description that is the (graded, plain) render pair, which is already built.
3. A report that states a residual states the sample count it was computed
   over.
4. A field that cannot be decided is deleted, not qualified.

---

## §2 The contract

### §2.1 `regions.subject_mask` and `regions.refuse` — the shared resolver

Two pure functions extracted from `regions.measure`, which already does both
things inline:

```python
def subject_mask(extents, n: int, h: int, w: int) -> tuple[np.ndarray, float]:
    """The tracked subject's (n, h, w) boolean mask and its fraction of that
    volume. `extents` is one (fx0, fy0, fx1, fy1) tuple of OUTPUT-frame
    fractions per frame — geometry.extent_at_times' own return shape."""

def refuse(kind: str, *, located: bool, fraction: float) -> str | None:
    """Why `kind` cannot supply a reading — one of FALLBACKS, or None when it
    can."""
```

`refuse` is the decision `assemble` makes today, lifted verbatim: not located →
`no-route`; not the crop and under `MIN_REGION_FRAC` → `too-small`; otherwise
None. `assemble` calls it, so the tone stage and the damage description cannot
drift apart — and the third fallback, `unorderable`, stays where it is, inside
`assemble`, because it is a property of a three-anchor profile and there is no
profile here.

**Corrected (final review, 2026-09-16): `refuse` takes two inputs, not three.**
As first written here, and as first built, the signature carried a third
parameter — `empty`, "located and holds no pixels" — OR-ed in front of the size
test. It is deleted, because **no production caller can produce it independently
of `fraction`**, so it decided nothing at any live call site: in `measure` a
`None` profile means an empty pixel array, which means a fraction of exactly
0.0; in `check_episode` the emptiness and the fraction are reduced from the SAME
mask; and the crop — the one kind the size gate skips — can never arrive here
empty at all, because `assemble` raises on a profile-less crop before its loop
starts. Measured over the whole suite before the deletion, by wrapping `refuse`
and recording only the calls made from the two production callers: **288
production calls, 16 of them with `empty=True`, every one of the 16 at
`fraction == 0.0`, and the two predicates — with the parameter and without it —
agreed on all 288.** The case itself has not gone anywhere: a located region
holding no pixels still reports `too-small` and still never `no-route`, on the
size test alone.

The test written to cover the parameter was worse than the parameter: it passed
`fraction=0.5` with `empty=True`, a pair no caller reaches, and justified that
with a per-frame emptiness `check_episode` does not compute — it reduces over
the whole stack, and the per-frame case is handled somewhere else entirely, by
`_region_pairs` skipping a frame whose mask slice is empty. §1 rule 4 — a field
that cannot be decided is deleted, not qualified — applies to a function's
parameters as much as to a report's fields, and this slice shipped a violation
of its own rule inside the slice that states it.

`measure` calls `subject_mask`. The tone stage's behaviour does not change; the
proof of that is that every named-regions test stays green untouched.

`REGIONS.json` is **deliberately not read by the dE00 sensor.** A declaration
binds an anchor (`toe`/`mid`/`shoulder`) to a region, and a dE00 has no anchor.
Deriving one — "take the name of whichever anchor declared `subject`" — would
be a rule nobody asked for, and the author's noun would then appear in a report
whose number it did not choose. The sensor reports the KIND it read
(`subject` / `crop`), which is what it actually resolved.

### §2.2 The reading rides `grade_damage`'s render pair

`_subject_delta_advisory` takes the frames instead of the file paths:

```python
def _subject_delta_advisory(plain_frames, graded_frames, times,
                            route_pts, path_obj, meta) -> dict
```

`_grade_damage` already holds all six, and `clip` leaves its signature: it was
passed in for the advisory and for nothing else.

The two stacks must share a shape, and the function refuses a mismatch rather
than broadcasting one: they are two renders of ONE plan pair, so a disagreement
is a caller error, not an input.

Deleted with the file reads:
`_box_mean_rgb`, `_last_sampleable_t`, and `SAMPLE_FRACS` — and with
`SAMPLE_FRACS` goes grade-delta-sensors §9.9's recorded coincidence, since the
five fractions it warns about no longer exist. `episode_qc`'s comment about
that coincidence goes with it.

The `source is None` branch and the `"no source clip or no tracked subject"`
disjunction are deleted too (§0.6): with the frames in hand there is no source
to be missing, and a missing route is now a named `no-route` fallback with a
real reading over the crop beside it.

### §2.3 What the report says

```json
"region": "subject",
"region_fraction": 0.0219,
"region_fallback": null,
"delta_e": 5.13, "delta_l": 0.61, "delta_c": 3.9, "delta_h": 4.71,
"background_fallback": null,
"background_delta_e": 5.32,
"samples": 3,
"advisory_delta_e": true
```

`region` / `region_fraction` / `region_fallback` are the provenance: a reading
taken over the crop because the subject was 0.23 % of the frame now says so,
instead of being attributed to a subject nobody measured.

`region` is what SUPPLIED the number, so it reads `crop` whenever a fallback
fired. `region_fraction` is the fraction of the region that was ASKED for — on a
`too-small` row it is the measured 0.0023, not the crop's 1.0, because the small
number is the evidence for the fallback; on `no-route` it is 0.0, a region that
was never located. That is `AnchorReading.fraction`'s own convention on the tone
side, kept identical so one reader learns it once.

`background_delta_e` is the contamination check the folded row is actually
about, and it costs one extra mask over frames already decoded. On ep0, 5.13
against 5.32 says the grade is global and the box's contamination cost nothing.
On ep7 — before the gate refuses it — 1.58 against 0.59 says the two disagree
by 2.7×, which is the signal that something in that box is not what surrounds
it. It is reported only when the subject supplied the reading: after a fallback
the reading IS the crop, and a "background" beside it would be two names for
one number (§0.1: they agree to 0.03 on seven of eight episodes).

**As built (review fix round 1), `background_fallback` joins it.** This section
as first written had the background supply a number whenever the subject did,
without asking whether the background could be read at all — and it cannot when
the projected bbox covers the whole output frame, which `subject_mask`'s
clamping makes ordinary on a tight reframe. `color_fidelity.evaluate([])`
returns its no-samples shape, so the field came back a bare `null` beside a real
`delta_e`, reading either as "the background did not move" or as an error, with
nothing telling them apart — the exact unnamed absence §1 rule 1 exists to
remove. `background` is a kind in `regions.KINDS` with a fraction of its own, so
it now goes through the SAME `regions.refuse`: `background_fallback` names the
absence from `regions.FALLBACKS` and no number is emitted at all. The
background's own fraction is deliberately NOT reported — it is
`1 - region_fraction` exactly, and a second representation of one number is a
contradiction surface. A subject fallback still drops BOTH keys: the contrast
has nothing to contrast with.

A pan gains a reading it does not have today: `region: "crop"`,
`region_fallback: "no-route"`, and a real dE00 over the whole delivered frame
where today the field is `null`. Strictly more information, and named.

### §2.4 `dominant` is deleted

Per §0.5 and §1.4. `color_fidelity.evaluate` keeps `delta_e` and the three
signed components; `_COMPONENTS` goes with the field it ranked. The QC judge's
template and SKILL, which name `dominant` directly, are rewritten to read the
three components — and to read `region` before `delta_e`, because a number
whose region is `crop` after a `too-small` is not a statement about the
subject.

### §2.5 `grade_faithful` records its sample count

`check_reel._grade_faithful_check` reports a per-episode residual computed over
`color.sample_times(dur)` and states the count nowhere, while `grade_damage`'s
report carries a `frames` key for exactly this reason. It gains `frames`, the
count actually read from the master per episode — not `color.FRAMES`, which
would be a constant echoing itself rather than a record of what ran, and `0`
when no episode could be predicted, which is a true statement that nothing was
read.

This records the MASTER read's count. `build_reel._predict`'s own
`color.sample_times(plan.dur)` on the prediction side is a second, independent
call; recording it too would need a return-shape change on `_predict` and buys
nothing until the two are allowed to differ. Named here so no reader mistakes
one number for both.

### §2.6 Two report surfaces from the previous slice

Both filed by the named-regions Task 7 review, both the same family:

- `match_grade._report_md`'s `if any(d.regions for d in decisions)` gate is
  unreachable for every real input: `regions.assemble` always returns three
  rows, so an undeclared anchor still reports, over the crop. The gate is
  deleted, which needs the stubs in `tests/lib/test_match_grade.py`,
  `tests/integration/test_bound_reports.py` and
  `tests/integration/test_mood_contract.py` to return the real three-row shape
  first. Same settlement the repo reached for `gradedamage.ENTROPY_BINS`.
- `test_write_match_rewrites_the_edl_and_writes_md` pins `MATCH.md` byte-exactly
  but gives its second episode an empty `AnchorReading` tuple, so the one place
  the region table's bytes are held holds one of its two episodes. The second
  stub gets the same three-row shape and the pin is extended.

---

## §3 What does not change

- **The tone stage.** `regions.measure` and `assemble` keep their behaviour
  exactly; the extraction is a refactor whose proof is the existing suite.
- **The verdict.** `grade_damage` still blocks on the entropy ratio against
  `CheckSpec.entropy_floor`, and the dE00 still votes on nothing. No threshold
  anywhere moves.
- **`MIN_REGION_FRAC = 0.01`** stays the convention named-regions §3.1 set, on
  the same evidence, now applied by a second reader. Its own re-measurement row
  stays open.
- **`REGIONS.json`'s vocabulary and refusals.**
- **`color_fidelity.evaluate`'s empty-input guard.** A pure function refusing
  input it cannot describe is a contract, not an inert knob; it is now reachable
  only through a caller passing no frames, which is what its tests do.

---

## §4 Proofs

1. **The refactor is inert for the tone stage.** Every `tests/lib/test_regions.py`
   and `tests/integration/test_named_regions.py` test passes unmodified, and the
   real-footage region proof's `(24, 84, 215)` profile is unchanged.
2. **One resolver, two readers** — a real-ffmpeg episode whose subject is under
   `MIN_REGION_FRAC` reports `too-small` from BOTH the tone assembly and the
   dE00 advisory, from the same fraction.
3. **The reading rides the pair** — the advisory's frames are the objects
   `_grade_damage` already decoded (identity, not equality), and no `ffprobe` or
   decode is issued by the advisory at all. The control: a real episode's
   `grade_damage` verdict is byte-identical before and after.
4. **A pan reports a crop reading named `no-route`**, where today it reports
   `null`.
5. **`background_delta_e` is present with a used subject and absent after a
   fallback**, with a control episode for each.
6. **`grade_faithful.frames` tracks the count actually read** — a test that
   changes the count and sees the field move, not a test that reads the
   constant.
7. **The extended `MATCH.md` pin** holds both episodes' region tables.

Each proof carries a control that must not move.

---

## §5 Honest limits

- **The box is still a box.** Nothing here masks the subject; a bbox over water
  still contains water. That is the separate P2 row (a seg-mask `subject`,
  size M, a cache bump), and this slice does not close it — it makes the box's
  size and the fallback visible, which is what §0.2 says is worth doing on this
  footage.
- **`background_delta_e` has no consumer that must act on it.** It is read by a
  judge who is told to judge the pixels. It is reported because the number is
  already computed and because §0.2 shows it is the only thing that separates a
  contaminated box from a global grade — not because anything downstream
  branches on it.
- **The described quantity changes.** After this slice the dE00 describes the
  DECLARED grade, not the delivered file: the encode is no longer in it (§0.4,
  up to 0.84 dE00 of move). Nothing else measures the encode's colour cost, and
  nothing did before either — the old reading conflated it with the grade
  rather than isolating it.
- **Three samples, not five.** The count matters at the 0.05–0.33 level for
  `delta_e` and decisively for a ranking of components — §0.5's table is the
  evidence for the second half only. **Where the first number is not** (noted
  2026-09-16, Task 6 review): §0.5's table carries the three signed components
  and no `delta_e` column, so the 0.05–0.33 figure comes from the same
  measurement run over the same four episodes and is not shown in any table
  here. Do not reach for §0.4's table instead: its +0.84 / +0.14 / −0.68 /
  −0.47 move the BASELINE (source-vs-clip at n=5 against the render pair at
  n=3) and so conflate the two changes, where 0.05–0.33 is the count alone on
  one baseline. The count is now recorded (`samples`) rather than argued, which
  is what makes a future re-measurement a comparison instead of an argument.
- **`MIN_REGION_FRAC` is still a convention**, now load-bearing for two sensors
  instead of one. On this pool every value between 0.23 % and 2.19 % selects the
  same episode; no run exists that discriminates it.
- **Nothing proves the judge reads `region`.** The same limit the episode-QC
  gate has always carried: presence and naming, never that anyone looked.

---

## §6 Deferred

Each gets a `docs/backlog.md` row before this slice is finished.

1. **A masked `subject`** — unchanged from named-regions §7 row 2, and this
   slice's §5 sharpens why a SECOND sensor now waits on it.

   **Corrected 2026-09-16 (Task 6 review).** This row first read "the remaining
   half of the folded row", which is wrong in the one place it matters: the
   backlog is this repo's single source of priority, and R2.1's folded rows are
   exactly TWO — the dE00 sampling box (closed by this slice) and chroma
   agreement (§6 row 2, still open). The mask is named-regions §7 row 2's own
   P2 row and was never folded into R2.1. The word "half" here meant a second
   thing — what the sampling-box row's CLOSURE leaves behind — and reading it as
   the first sense made two backlog rows cite this section for opposite
   conclusions. What is true: closing the sampling-box row makes the box's SIZE
   and its fallback visible (§0.2); making the box a real subject is the
   separate mask row, and it does not gate R2.1.
2. **Chroma agreement across episodes** — R2.1's other folded half. The
   instrument is now fully in hand (region masks plus an RGB reader over them);
   the TARGET still needs designing, and R2.1 stays `◐` until it exists.
3. **The encode's own colour cost** — isolated by this slice's baseline change
   and measured by nothing. Worth a row only if a run ever shows it mattering.
