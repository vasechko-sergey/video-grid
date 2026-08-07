# Intake motion sensor + pool-relative scoring — design

**Date:** 2026-08-06
**Status:** design
**Slice:** cinematic-quality playbook P3 · S3 (`docs/cinematic-quality-playbook.md` §4
priority 3) — the `_motion_fit` re-tune deliberately deferred by
`docs/specs/2026-08-06-mood-preset-variety-design.md` §1.1
**Predecessors:** S1 contact sheets (2026-08-05), S2 mood presets + shot variety (2026-08-06)

---

## 0. Why this is not the re-tune that was chartered

S2 deferred a re-tune of `_motion_fit` on an explicit ground: no real footage had
been scored, so any new constant would have been invented. S2 then paid the
`CACHE_VERSION` 6→7 cost specifically to make the re-tune free later — the raw
inputs would be on disk, so `score` would be recomputable without a re-scan.

The footage arrived. It did not support a re-tune; it falsified the premise that a
re-tune was the fix.

**The tuning set.** `/Users/serg/Downloads/untitled folder/FOOTAGE.json` — 99 DJI
clips, 1565 windows, 1920×1080@60, one shoot (2026-06-23/25), people in almost
every window. Every number in §1 is measured on it. It is a **v5-era artifact**:
its windows predate `subject_w`/`subject_h`/`present`, so the `present` values in
§1 are reconstructed by inverting `score_window`. "All 1565 land inside [0, 1]" is
not literally the check that passes: the inversion runs on the already-rounded
(3-4dp) `score`/`motion`/`dur`/`shake` fields the file stores, and that compounded
rounding pushes 759/1565 (48.5%) slightly ABOVE 1.0 (max 1.0033) — rounding slack,
not a sign the inversion is unsound. The check that DOES hold across all 1565:
none land below 0 (min 0.001).

Three findings, in ascending order of consequence.

### 1.1 Three of the four score terms cannot rank at all

Contribution to the **spread** of `score` (standard deviation of `weight × factor`
across all 1565 windows), which is what ranking is made of — a term's mean moves
every window equally and changes no ordering:

| term | weight | sd of contribution | mean of contribution |
|---|---|---|---|
| `present` | 0.40 | **0.010** | 0.400 |
| `_motion_fit` | 0.25 | **0.082** | 0.123 |
| `stability` | 0.25 | **0.029** | 0.204 |
| `_dur_fit` | 0.10 | 0.018 | **0.007** |

So `score ≈ 0.61 + 0.25 · _motion_fit`. The ranking *is* the motion term. `score`
sd is 0.089, IQR 0.675–0.803 — one narrow band.

A visible consequence: `BEST_FLOOR = 0.50` is passed by **1559/1565 windows
(99.6%)**. `FootageWindow.best` today carries no scoring signal whatsoever; it is
the phash-dedup survivor flag (1215 of them) wearing a threshold's name.

Each near-constant term is near-constant for its own structural reason, not by
luck of this shoot:

- **`present` is constant by construction.** 1563/1565 windows sit at exactly 1.0.
  Not because the shoot is crowded — because `carve_windows` splits spans *on
  presence transitions*, so a window is homogeneous in presence by construction.
  40% of the score budget is spent on a quantity the carver already guarantees.
- **`_dur_fit` contradicts `carve`.** 76% of windows are exactly 1.20 s = `WIN_MIN`,
  where `_dur_fit` returns an exact **zero**. `carve.units_for_span` emits tight
  minimum-length units; `_dur_fit` prefers `WIN_TARGET` = 2.5 s. Two subsystems
  with opposite preferences, and the carver wins because it runs first.
- **`stability` is compressed, not absent.** The pool's shake spread is real —
  p10 0.0014, p50 0.0030, p90 0.0069, p99 0.0114, max/median = 5.2× — and its
  p10–p99 band sits 2–14× below the `SHAKY_CLIP = 0.02` divisor (2.6% of windows
  sit closer than 2× below it, 11.1% farther than 14× below it — not literally
  "every value"), so `1 − shake/0.02` compresses the realised range down to
  [0.225, 0.995] — not confined to the top ~20% either. The signal exists; the
  absolute scale still discards most of its resolution (confirmed independently:
  stability contributes sd 0.029 against motion's 0.082 at near-equal weight).

### 1.2 `_motion` does not measure motion

`_motion` takes the centroid displacement of the **largest** bbox between
consecutive samples. In a crowd, "largest" switches from one person to another,
and that switch is arithmetically indistinguishable from movement.

The population at the `MOTION_GAIN` ceiling is not the tail of a distribution:

| | saturated (`motion` = 1.0) | rest |
|---|---|---|
| n | 310 (19.8%) | 1255 |
| `people` ≥ 2 | **90.3%** | 57.1% |
| `len(track_ids)` ≥ 2 | **88.7%** | 57.9% |
| median `people` | **4.0** | 2.0 |
| median `len(track_ids)` | **5.0** | 2.0 |

The decile histogram decays cleanly — 355, 233, 167, 99, 64, 44, 39, 28 — and then
**spikes to 321 at the ceiling**. A decaying distribution with a spike at the clip
point is the signature of a saturating artifact, and the crowd asymmetry names its
cause.

`_motion_fit(1.0) = 0.0`, so today those 310 windows score on motion exactly as a
frozen frame does. That accident is the only thing keeping the artifact out of the
top of the ranking.

**This is what makes the chartered slice the wrong one.** Rank-normalising the raw
measurement — the obvious fix for saturation — would remove the accident and
promote the artifact to the top of every crowded clip. A mapping cannot repair a
sensor.

### 1.3 The same contamination carves the windows

`carve.subject_curve` builds its activity curve from the same primary-bbox
centres (`intake.carve_windows` passes `row[2]`). The curve whose peaks decide
**where windows begin and end** is contaminated by the same person-swaps. This is
one bug with two consumers, not two bugs — and the upstream consumer is the more
consequential one.

### 1.4 The bump is free exactly once

The on-disk cache at `<out>/.intake_cache/` is at `version: 5`; the code is at 7.
A full re-scan of all 99 clips is already owed and nothing from the previous run
survives it. Fixing the sensor requires a Phase-1 change and therefore
`CACHE_VERSION` 7→8, which costs **zero additional re-scan if done now** and one
extra full re-scan if deferred. That asymmetry, not the size of the fix, is why
the sensor is in this slice.

---

## 2. What this slice does

Two coupled changes, in the two phases that already exist
(`docs/specs/2026-07-25-intake-parallel-checkpoint-design.md` §2: Phase 1 = the
per-clip cached CV pass, Phase 2 = the cheap deterministic assembly).

- **Phase 1** — the sensor becomes track-consistent (§3). `CACHE_VERSION` 7→8.
- **Phase 2** — scoring becomes pool-relative and moves out of Phase 1 (§4, §5).

The split is not cosmetic: a pool-relative score is *unrepresentable* in Phase 1,
whose whole contract is that a clip's result depends on that clip alone.

---

## 3. The sensor: track-consistent displacement

### 3.1 The timeline carries per-track boxes

`_people_timeline` already reads each detection's track id (it builds the `tids`
list per sample) and then discards the per-track geometry, keeping only the
largest box. The row grows a fifth element:

```
(t, people, primary_bbox, track_ids, boxes_by_tid)
```

`boxes_by_tid` is `{tid: (cx, cy, w, h)}` for that sample, in PROXY pixel space —
the same space `primary_bbox` already lives in. `primary_bbox` stays: it is what
`_build_window` measures `subject_w`/`subject_h` from, and "the largest subject in
frame" is the right question for shot size even when it is the wrong question for
motion.

### 3.2 The primitive

A new pure function in `scripts/lib/carve.py` (it belongs beside
`subject_curve`, its sibling consumer):

```
track_displacements(prev: dict[int, tuple], cur: dict[int, tuple]) -> float
```

- Take the ids present in **both** samples.
- For each, the Euclidean displacement of its own centre.
- Return the **median** across those ids; no shared id returns `0.0`.

The median, not the mean: a residual ID switch inside a crowd perturbs one track,
and the median of five tracks absorbs it while the mean would not. Zero shared ids
returns `0.0` under the same rule that already governs presence gaps — an
unmeasurable interval is not evidence of movement.

A person-swap now contributes nothing, because a swap is not any single track's
own displacement.

### 3.3 Both consumers switch

- `carve.subject_curve` takes per-sample `boxes_by_tid` instead of primary
  centres and builds its curve from `track_displacements`. **Window boundaries
  move.** This is the largest behavioural change in the slice and the reason the
  goldens shift; it is named here so it is read as intended, not diagnosed from a
  diff.
- `intake._motion` aggregates `track_displacements` over the window's samples,
  divided by the analysis width, and stays a fraction in [0, 1] as
  `FootageWindow.motion`'s contract requires.

### 3.4 `MOTION_GAIN` is deleted, not re-tuned

The gain exists only to stretch a small fraction onto [0, 1] so a fixed
triangular preference can be applied to it. §4 replaces that preference with a
rank, and a rank has no scale to choose and no ceiling to saturate against. The
constant is removed rather than re-fitted — re-fitting it on one shoot is the
overfit this design is built to avoid.

Consequence to expect: `FootageWindow.motion` values drop by roughly 10× (the old
median 0.341 corresponds to a raw ≈ 0.034), because the reported number becomes
the measurement instead of the measurement times a display gain. `FOOTAGE.md`
readers — human and agent — must be told (§7).

---

## 4. Scoring: one absolute layer, one relative layer

### 4.1 Factor → desirability

Each factor maps to [0, 1] on the scale its own question deserves. The rule is not
"normalise everything": it is **absolute where the scale is a delivery constraint,
relative where the scale is a property of the footage**.

| factor | scale | why |
|---|---|---|
| `motion` | percentile **within its own clip**, falling back to the pool below `CLIP_POOL_MIN` windows | "the active moment of this shot" is the editorial question; measured within-clip spread is 87% of pool spread, so almost nothing is lost |
| `shake` | percentile across the **pool**, inverted | steadiness is a camera property; comparing a window to the other windows of its own clip asks nothing (§1.1) |
| `present` | absolute fraction, unchanged | its [0, 1] scale already means what it says |
| `dur` | **removed** | §4.3 |

`CLIP_POOL_MIN = 5` windows. Below it a clip has no distribution to speak of —
10 of 99 clips in the tuning set are in that state. First cut, and labelled as one.

### 4.2 The composite is itself a percentile

The weighted blend of the desirabilities is then rank-normalised across the whole
pool, and **that percentile is `FootageWindow.score`**.

One mechanism fixes three separate defects:

- A structurally constant factor (`present`) adds the same amount to every window
  and therefore *cannot* distort the ordering — no weight surgery needed, and no
  factor has to be deleted to stop it doing damage.
- The 0.61 baseline disappears, so `BEST_FLOOR` stops being inert. It becomes a
  percentile cut: `best` finally means "top (1 − `BEST_FLOOR`) of this shoot,
  among dedup survivors".
- Saturation is unrepresentable. A rank has no ceiling.

`cull`'s dedup ordering is monotone in the UNROUNDED rank — but the stored `score`
is `round(sc, 3)` (§4.5), and rounding is not injective: on the design's own
1565-window tuning pool, the 1565 distinct ranks collapse onto 1001 possible 3dp
values, and 72.1% of windows share their rounded score with at least one other
(largest collision group: 2, so only adjacent-rank pairs can swap — §8.9). `cull`'s
sort is stable, so a colliding pair falls back to input order rather than rank
order; the ordering stays deterministic either way, just not always rank-exact
past the rounding.

### 4.3 Duration leaves the quality score

Length is not intake's question. `pacing` fits cut lengths to the music
(`docs/specs/2026-07-24-scenario-first-pacing-design.md`), and the `WIN_MIN`…
`WIN_MAX` band is already enforced structurally by `carve.units_for_span` — no
window outside the band exists to score. What `_dur_fit` adds on top is a
preference for 2.5 s that the carver contradicts 76% of the time.

`W_DUR` and `_dur_fit` are deleted. `WIN_TARGET` goes with them — `_dur_fit` was
its only consumer. `WIN_MIN`/`WIN_MAX` stay: `carve_windows` passes exactly those
two to `carve.units_for_span` as the band it enforces structurally.

### 4.4 Weights after the change

`W_PRESENT`, `W_MOTION`, `W_STABLE` remain, renormalised to sum to 1.0. Because
the composite is rank-normalised (§4.2) and `present` is constant on people-only
footage, the ranking is in practice the motion/stability trade-off; the weights
are what sets it. They stay first cuts — §8.

### 4.5 Where it runs

A new pure module-level function in `scripts/intake.py`:

```
score_pool(clips: list[FootageClip]) -> None      # mutates w.score and w.description
```

called in `intake()` between `footage.Footage(...)` assembly and `cull(...)` —
the same Phase-2 position `cull` already occupies. `_build_window` stops computing
`score`; the field keeps its `0.0` default until Phase 2 fills it.

`_describe`'s dynamic/calm word moves with it. That word is a comparison
(`motion >= MOTION_PEAK`) and every comparison in this design is now pool-relative,
so it cannot be produced by a per-clip worker. `description` is assembled in
Phase 2 alongside the score.

**The determinism invariant is preserved and must be re-proven, not assumed.**
`score_pool` reads only the assembled clip list, which `intake()` already re-sorts
into `paths` order before use — so output stays byte-identical at any `--jobs` and
any cache mix (`docs/specs/2026-07-25-intake-parallel-checkpoint-design.md`'s
central invariant). The integration proof that pins it must cover a run whose
scores are pool-relative.

---

## 5. Contract and cache

- **`CACHE_VERSION` 7→8.** Phase 1's timeline and `_motion` both change; a cached
  v7 `ClipResult` cannot supply the new measurement.
- **`FootageWindow` gains no field.** `motion` keeps its name, contract and [0, 1]
  range, and changes meaning (raw fraction, no gain). `score` keeps its name,
  contract and [0, 1] range, and changes meaning (pool percentile). `description`
  and `score` change producer (Phase 1 → Phase 2).
- **No legacy-artifact refusal is added.** S2 added one keyed on the *presence* of
  `present`, and it still fires for pre-S2 files. This slice adds no new key, so a
  v7-era `FOOTAGE.json` loads without complaint and its `score` column silently
  means the old thing. That gap is recorded as a limit (§8.4), not papered over:
  the meaning changed without the shape changing, and shape is all `from_dict` can
  see.

---

## 6. Validation

### 6.1 The unit proof (synthetic, deterministic)

A timeline in which the largest bbox alternates between two **stationary** people
must yield ≈ 0 motion. Today it yields the maximum. This is the whole bug in one
assertion, and it is a test that provably reddens against the current code.

### 6.2 The real-footage proof (required, cannot be substituted)

`FOOTAGE.json` holds aggregates only — no per-sample displacements — so no
re-analysis of the existing file can validate a new sensor. The proof needs a real
CV run over real clips.

Acceptance criteria, fixed in advance so the run cannot be read charitably after
the fact:

1. The ceiling spike is gone: no accumulation of windows at `motion` = 1.0 (was
   310 windows, 19.8% — §1.2's own table. 321/20.5% is a DIFFERENT quantity, the
   `motion >= 0.95` histogram bin one step down from the ceiling, not the ceiling
   itself).
2. The crowd asymmetry collapses: the share of windows with `people` ≥ 2 among the
   top motion decile approaches the pool share (was 90.3% vs 57.1%).
3. `score` is approximately uniform on [0, 1] — a percentile's defining property,
   and a cheap check that the rank layer is wired at all.
4. `best` selects approximately (1 − `BEST_FLOOR`) of dedup survivors, not 99.6%
   of everything.

A subset of clips is sufficient for 1 and 2; 3 and 4 need the full pool, since
they are statements about the pool.

### 6.3 Goldens

Window boundaries move (§3.3), so the synthetic intake goldens re-pin. A re-pin is
expected here and is not evidence of a regression — but it must be a **re-pin with
the diff read**, not a blind re-record.

---

## 7. Documentation that must change with the code

`score`'s meaning is consumed by an agent, so a stale sentence is a silent
behaviour change:

- `skills/edit-plan/SKILL.md` — its guidance currently states the score "peaks at
  motion 0.35", which describes the deleted triangular preference.
- `skills/footage-intake/SKILL.md` — describes the columns of `FOOTAGE.md`.
- `footage.Footage.to_markdown` — the `score` and `motion` columns now carry
  different quantities; the table's own legend must say so.
- `scripts/contact_sheet.py` — prints `score` per cell and explains `best` in its
  header ("a dedup survivor scoring >= 0.50").

---

## 8. Honest limits

**8.1 One shoot, one camera, one situation.** Every measurement here comes from a
single drone shoot with people in almost every frame. Percentile normalisation is
the structural defence — it removes absolute constants from the ranking path — but
`CLIP_POOL_MIN`, the surviving weights, and `BEST_FLOOR`'s new percentile value are
first cuts calibrated on that one pool. The precedent is `SHAKY_CLIP` and
`CLUSTER_COS`, both still first cuts for the same reason. `CLIP_POOL_MIN`'s failure
mode is a STEP, not a gradient: a clip's 5th window moves its `motion_fit` from a
narrow slice of the POOL's spread to the full [0, 1] of its OWN clip's spread in
one step — worth up to `W_MOTION` (0.28) of the blend — and 10 of 99 clips in the
tuning pool sit on the far side of that cliff (§4.1).

**8.2 `score` stops being comparable across shoots.** Deliberate. A percentile
answers "how does this window rank in this footage", and no consumer asks
anything else. The cost is that "this whole shoot is weak" becomes unsayable in
this number, and nothing in the pipeline will notice it is unsayable.

**8.3 `present` stays dead until someone shoots B-roll.** It is kept, not deleted,
precisely because deleting a factor on the evidence of one people-saturated shoot
is the overfit this design exists to avoid. On a mixed shoot `present` does not
merely "start mattering": at `W_PRESENT = 0.44`, a people-less window's blend caps
at 0.56 (`W_MOTION + W_STABLE`, its best possible motion and stability) while a
people-full window's blend floors at 0.44 (`W_PRESENT` alone, its worst) — so
`best`, the top half of the pool, would skew almost entirely to people windows
regardless of how those windows move or hold steady. Until B-roll exists, `present`
contributes a constant and this asymmetry stays invisible.

**8.4 A v7 `FOOTAGE.json` loads silently with the old meaning.** §5 adds no new
required key, because the change is semantic and `from_dict` can only see shape.
Anyone holding a pre-slice file gets old-meaning numbers in new-meaning columns
with no warning. The mitigation is the `CACHE_VERSION` bump forcing a re-scan for
anyone who re-runs intake — which is not the same as a refusal, and is weaker.

**8.5 The sensor fix is verified on aggregate statistics, not ground truth.**
§6.2's criteria prove the artifact's *signature* is gone. They do not prove the
new numbers are correct, because no hand-labelled motion ground truth exists for
this footage. A sensor that returned 0.0 everywhere would pass criterion 1 and
fail 3 — the criteria are chosen so no single degenerate answer passes all four —
but "passes all four" is still weaker than "is right".

**8.6 The residual ID-switch problem is reduced, not solved.** `track_displacements`
defeats the *largest-box swap*. It does not defeat a genuine ByteTrack ID switch
that reassigns one person's id mid-window: the old id disappears, the new one has
no predecessor, and both drop out of the shared-id set. The median across the
remaining tracks absorbs it in a crowd; in a two-person window it can halve the
sample count. `track.stitch_ids` (2026-07-28) solves the analogous problem for
routes and is **not** reused here — it operates on a route's segments, not on an
intake timeline.

**8.7 Nothing here makes the ranking editorially right.** It removes a measurement
artifact and a set of terms that could not rank. Whether the resulting order
matches what a human editor would pick is unmeasured, and S1's contact sheets exist
precisely because that question is answered by looking, not by a number.

**8.8 The "dynamic" word is CLIP-relative, not pool-relative.** `_describe`
receives the motion RANK that `score_pool` already resolved for that window — for
a clip at or above `CLIP_POOL_MIN` that rank is the percentile *within that clip*
(§4.1), not across the pool. §4.5's "every comparison in this design is now
pool-relative" is imprecise on this one point. Consequence: a completely static
clip still has roughly half its windows labelled "dynamic" in `FOOTAGE.md` —
`_percentile_rank` spreads whatever noise floor a calm clip has across the full
[0, 1] range, and `DYNAMIC_RANK = 0.5` cuts that range in half regardless of the
clip's absolute stillness.

**8.9 `round(score, 3)` quantises the percentile.** On the design's own
1565-window tuning pool, adjacent ranks are `1/1564 ≈ 0.00064` apart — finer than
three decimal places. `score_pool`'s `round(sc, 3)` (§4.5) buckets that continuum
into ~1001 possible values, so above roughly 1000 windows in a pool, distinct
ranks collapse onto the same displayed score. `cull`'s sort is stable, so nothing
non-deterministic follows from it — but the percentile itself is silently
quantised past that pool size.

**8.10 `_percentile_rank` ties on BIT equality, not mathematical equality.** Its
tie test is exact `==` (`values[order[j + 1]] == values[order[i]]`), so two blends
that are mathematically equal but reached that value by different arithmetic paths
can fail to compare equal: with `present` fixed at 1.0, `W_PRESENT*present +
W_MOTION*0.25 + W_STABLE*0.5` is `0x1.4cccccccccccdp-1`, while the same three
numbers with the motion/stability ranks SWAPPED (`W_PRESENT*present + W_MOTION*0.5
+ W_STABLE*0.25`) is `0x1.4cccccccccccep-1` — one ULP apart, both equal to 0.65 as
a real number. Such windows get adjacent ranks instead of sharing a mid-rank. This
is still deterministic — the same inputs in the
same order always produce the same output, so the cross-`--jobs` byte-identity
invariant (`docs/specs/2026-07-25-intake-parallel-checkpoint-design.md`'s central
invariant) does not break — but "equal inputs give equal ranks" (§4.2) holds only
for bit-identical floats, not for every pair a human would call equal.

**8.11 The largest behavioural change has no real-bytes coverage.**
Window-boundary movement (§3.3) and `score_pool` ranking ACROSS multiple windows
are proven only by synthetic unit fixtures — never through the real ffmpeg decode
path. `tests/conftest.py`'s `sample_clip` is a 3 s clip with no scene cut, and
`WIN_MAX` is 4.0 s, so `carve.units_for_span`'s `L <= win_max` branch makes exactly
ONE window unavoidable for any real-bytes intake test built on it, whatever the
activity curve does — both real-bytes integration goldens (§6.3) carry exactly one
window per clip for this reason. This is a FIXTURE CHOICE, not a law: a
`sample_clip` longer than `WIN_MAX` would make `L > win_max` and route a real-bytes
test through the multi-window carving path, at the cost of a slower/bigger
fixture. Nobody has made that trade yet (§9) — but this slice's two central
behavioural changes are exactly the ones the current fixture cannot reach.

**8.12 A genuine mid-window ID switch reads as a lull, not just a thinned
sample.** `carve.track_displacements` returns `0.0` when two samples share no
track id (§3.2), and `carve.subject_curve` feeds those zeros straight into the
curve that decides WHERE WINDOW BOUNDARIES FALL (§3.3). Verified against the
shipped code: a 4-sample window carrying constant 30 px/sample motion, with one
mid-window ID switch (track 1 for samples 0-1, track 2 for samples 2-3, sharing no
id across the switch), gives `subject_curve` `[0.0, 30.0, 0.0, 30.0]` instead of
the true `[0.0, 30.0, 30.0, 30.0]` — a spurious local minimum at index 2, exactly
where `carve._lead_in_unit` looks for a lull/settle boundary. `_motion`
under-reports the same window by 33% (mean of `[30, 0, 30]` = 20 against the true
mean of `[30, 30, 30]` = 30). ID churn correlates with crowding and occlusion —
the same population the OLD sensor over-reported (90.3% multi-person at the
ceiling, §1.2) — so this slice may have traded a positive crowd bias in the SCORE
for a negative one in the BOUNDARIES, in both consumers of `track_displacements`.
§6.2's four acceptance criteria cannot detect this: criterion 2 asks whether the
crowd share in the top motion decile "approaches the pool share", and a crowd
share pushed BELOW the pool share — this artifact's direction — reads as success,
indistinguishable from a genuinely fixed sensor. §8.6 already records the
shared-id thinning as a limit of the motion NUMBER; this item is about the
BOUNDARIES, which §1.3 names as the more consequential of the two consumers.

---

## 9. Deferred

- **A `sample_clip` fixture longer than `WIN_MAX`**, so a real-bytes intake test
  can reach `carve.units_for_span`'s multi-window carving path and exercise
  window-boundary movement and multi-window `score_pool` ranking on real
  ffmpeg-decoded pixels (§8.11) — the highest-value item here, since it is the
  only way a real-bytes test could ever catch the §8.12 ID-switch boundary
  artifact.
- **Re-tuning the surviving weights against editorial judgement** — needs a human
  ranking of real windows to fit against. Nothing here provides one.
- **A semantic version marker on `FOOTAGE.json`** that would let `from_dict` refuse
  a file whose columns mean something older (§8.4). It is a general fix to a
  general problem — every future meaning change wants it — and belongs in its own
  slice rather than being invented here for one case.
- **The hero-conditioned re-scan** (S2 design §14) — unchanged in scope and still
  blocked on a face detector, a new download, and a new `verify_runtime` gate.
- **Per-track motion in `FootageWindow`** — the primitive computes per-track
  displacements and then discards all but the median. Storing the spread would let
  a consumer distinguish "everyone moved" from "one person moved", which is an
  editorial distinction with no consumer today.
