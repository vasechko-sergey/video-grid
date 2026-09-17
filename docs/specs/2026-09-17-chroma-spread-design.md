# Chroma spread — design

**Closes** the last open half of backlog **R2.1** ("grade against named subjects,
not the frame mean") — the P3 *chroma convergence ACROSS episodes* row folded into
it: *nothing measures whether the episodes agree in colour, only in luma*.

It does not close it the way the row asked. The row asked for a chroma **target**.
§0 shows that an absolute cross-episode chroma target is not measurable on this
footage and names the two independent reasons; what ships instead is the one
chroma claim the artifacts do support — **how far apart the reel's own episodes
are in what the grade did to their colour** — reported as a number and gated by
nothing. The row's premise is confirmed twice over on the way (§0.1, §0.2); its
remedy is refuted (§0.4, §0.5).

---

## §0 What the artifacts say

Every number below is measured on the only real run
(`/Users/serg/Downloads/untitled folder`, read-only), eight delivered episodes,
two cameras: **DJI** (drone) = ep0/2/4/7, **MVI** (Canon) = ep1/3/5/6.

### §0.1 The premise is structural, not a gap someone forgot to fill

`color.tone_arg` writes the **Y plane only** — `lutyuv=y='…'`, U and V untouched,
chroma bit-identical (its own docstring says so, and this design re-read it).
`match_grade` authors `tone_src`/`tone_dst` and nothing else. Therefore **the
only automatic colour stage in the pipeline cannot move chroma at all.**

Every other colour field — `saturation`, `mid_blue`, `shadow_red`,
`highlight_red`, `white_balance`, `black_point`, `highlight`, `dip` — has **no
automatic author anywhere**. They are hand-written into `selection.json` or the
EDL and forwarded verbatim through `edit_plan.window_to_episode` →
`EDLEpisode` → `Manifest` → `process_episode.build_reframe_spec`.

So there is no stage whose output a chroma check would be regulating. The check
regulates a **human**, holding eight knobs, with no number in front of them.

### §0.2 The human already did this work by hand, and the camera line is exact

As shipped in `EDL.json`:

| knob | DJI (ep0, 2, 4, 7) | MVI (ep1, 3, 5, 6) |
|---|---|---|
| `saturation` | 0.92 · 0.88 · 0.88 · 0.95 | 1.00 · 1.00 · 0.95 · 1.00 |
| `mid_blue` | 1.20 · 1.04 · 1.08 · 1.04 | 1.00 · 1.00 · 1.00 · 1.00 |
| `shadow_red` | 0.10 · 0.08 · 0.06 · 0.07 | 0.04 · 0.05 · 0.05 · 0.00 |
| `white_balance` | 0.00 · **0.35** · **0.35** · 0.00 | 0.00 · 0.00 · 0.00 · 0.00 |

Four knobs, four clean separations by camera — `mid_blue` is *exactly* 1.0 on
every Canon episode and above 1.0 on every drone one. The operator was correcting
a cross-camera colour mismatch by hand, per episode, while the automated stage
authored five luma tone pairs and nothing else.

### §0.3 The subject is the noisy region and the background the quiet one

Within-episode spread of the region's mean colour over nine frames of the
delivered clip (max − min, CIE Lab units):

| | subject a\* / b\* | background a\* / b\* |
|---|---|---|
| ep0 | 4.24 / 6.47 | 0.90 / 5.42 |
| ep1 | 2.49 / 3.19 | 1.05 / 0.87 |
| ep2 | 1.73 / 3.89 | 1.12 / 1.88 |
| ep3 | 2.15 / 2.59 | 0.46 / 1.18 |
| ep4 | 4.35 / 6.61 | 0.71 / 0.72 |
| ep5 | 6.47 / 6.82 | 0.30 / 2.17 |
| ep6 | 1.48 / 1.75 | 2.74 / 2.75 |
| ep7 | 3.27 / 1.96 | 0.55 / 0.75 |

This **inverts the parent row's title**. For chroma the stable named region is the
**background**, not the subject: against a cross-episode subject spread of 11.14
(a\*) / 17.00 (b\*) the subject's own frame-to-frame noise reaches 6.47 / 6.82, a
signal-to-noise of 1.7–2.5×. The cause is already a filed row — the subject is the
route's **bbox**, and a box over water is water (named-regions §7 row 2). The
regions do separate real populations: subject a\* is positive on all eight
episodes, background a\* negative on six of eight.

### §0.4 An absolute chroma target cannot be separated from content

Four drone episodes, **ungraded**, rendered through `plan_ungraded`, differ from
each other by **4.87 b\*** over the background region with no grade applied at all.
On the delivered clips, read whole-frame, the within-camera b\* spread is 12.31
(DJI) and 11.17 (MVI) — the **same order** as the gap between the two cameras'
medians (−16.93 vs −4.87). A threshold on absolute chroma
therefore cannot tell "these two shots were rendered differently" from "there is
more ocean in this one".

That is precisely the shape of `color_across_cuts`, deleted 2026-08-29 after its
ceiling was raised 12 → 44 → 56 to silence complaints that were each correct. The
row asks for a target; the measurement says a target would be that knob again.

### §0.5 …and the one referent that *is* the same across episodes is unreadable

The person is the only thing physically common to all eight shots, which is what
would make an absolute target defensible. §0.3 is why it cannot carry one today:
the subject region is a bbox, its noise is 1.7–2.5× against the signal, and
`regions.MIN_REGION_FRAC` refuses it outright on ep7 (0.23 % of frame). Named
regions already measured `skin` as the **worst** reference for tone (cross-episode
sd 34.3). Nothing suggests it is better for chroma, and no evidence exists either
way until the seg-mask row is built.

### §0.6 The grade's own displacement, however, measures cleanly

For each episode, the signed CIEDE2000 components between the **ungraded** and
**graded** renders of the same frames — over the whole crop, the one region every
episode always has:

| | dE00 | dC\* | dH\* | `saturation` / `mid_blue` |
|---|---|---|---|---|
| ep0 | 5.32 | **+2.72** | **+7.84** | 0.92 / **1.20** |
| ep2 | 2.61 | −4.18 | −1.22 | 0.88 / 1.04 |
| ep4 | 2.21 | −2.72 | −0.51 | 0.88 / 1.08 |
| ep7 | 0.59 | −0.66 | −0.53 | 0.95 / 1.04 |

**ep0 is the only episode whose grade raised chroma; the other three lowered it.**
Three siblings sit within **0.71 dH\***; ep0 sits **8.35** away. ep0 is the reel's
**opening** shot, its `mid_blue = 1.20` is hand-typed, and nothing measured it.

Content cancels by construction: the same pixels of the same frame appear on both
sides of the difference. The statistic's own noise over nine frames is **0.06 /
0.08 / 0.19** dC\* for the three quiet episodes (0.10–0.44 dH\*) and 1.81 / 1.91 for
ep0, whose grade is genuinely the strongest. Against a cross-episode spread of
6.90 dC\* / 9.07 dH\* that is a signal-to-noise of **21–36×**, against the absolute
statistic's ~4× *on top of* a content floor it cannot see past (§0.4).

### §0.7 Half the reel has no reading at all, and that is a property of this run

`plan_ungraded` refuses ep1/ep3/ep5/ep6 — all four Canon segments are `pc`, cut
before the 0.3.1 segment range contract. So on the only real run **`grade_damage`
and the dE00 advisory are not-checked on half the reel**, and the four episodes
this design can measure are all one camera. A run cut through today's `extract`
does not have this: the contract normalizes every segment to `tv`. It is not a
defect this slice introduces or can fix — it is why §0.6's table has four rows.

### §0.8 The one chroma actuator that consumes a measurement consumes a constant

`manifest.DEFAULT_COLOR == color.TARGET == (105, 122, 137)`, and all eight episodes
carry the default. So `color.gains_for_means(color_means)` is **exactly identity**
on every real episode, and `white_balance_arg` applies the **same three gains**
(R 1.054 · G 0.998 · B 0.960 at strength 0.35) to any episode regardless of what it
looks like. The grey-world white balance has never measured the footage.

Reviving it naively is a trap, not an opportunity: grey-world over an ocean drags
the water toward grey. This is filed as its own row (§6), not folded in here.

---

## §1 The rule

1. **A reading names its pixels, and a comparison names its baseline.** A chroma
   number that cannot say which frames it differenced is not a measurement.
2. **A difference between two renders of one frame is content-free; a difference
   between two frames is not.** Only the first kind may carry a number about a
   reel.
3. **A check that cannot separate a defect from legitimate variation does not get
   a threshold** — it gets deleted, or it never gets built. §0.4 is that ruling,
   applied before the code exists rather than after its ceiling reaches 56.
4. **A field that cannot be decided is deleted, not qualified** (carried from
   2026-09-16 §1.4). This is why no absolute cross-episode chroma number is
   reported "for the reader to judge".

---

## §2 The contract

### §2.1 The statistic

For one episode: the median over its sampled frames of the signed **dC\*** and
**dH\*** that `colordiff.ciede2000` returns between the mean RGB of the **ungraded**
render and of the **graded** render, over the same pixel set.

Both numbers already exist. `color_fidelity.evaluate` computes exactly them, from
exactly that pair, and `check_episode._subject_delta_advisory` already reports
them per episode as `delta_c` / `delta_h`. **Nothing compares them across
episodes.** This slice adds the comparison, not the measurement.

### §2.2 The pixel set is the crop, and only the crop

The reel-level claim needs ONE pixel set defined identically on every episode.
The crop is the only region that is always present: `subject` falls back by name
(`no-route`, `too-small`) and `background` is not reported at all after a subject
fallback (2026-09-16 §2.3).

The 2026-08-29 objection to whole-frame statistics does **not** transfer: it was
fatal because `color_across_cuts` compared two *different shots*. Here both sides
of the difference are the same shot, so the whole crop is not a mixed population —
it is the complete population, differenced against itself.

`check_episode._subject_delta_advisory` therefore emits `crop_delta_c` /
`crop_delta_h` **only when `region == "subject"`** — when the subject fell back,
`delta_c` / `delta_h` already ARE the crop's, and a second key holding the same
number is the contradiction surface 2026-09-16 §2.3 refused for the background's
fraction. The consumer reads `region` to know which pair to take; that field
exists for exactly this.

### §2.3 The carrier

`ReelEpisode` gains one optional field, `chroma`, carrying either the reading or a
named absence — the same two shapes every check result in this repo already uses:

```
{"delta_c": float, "delta_h": float, "region": "subject" | "crop"}
{"status": "not-checked", "reason": str}
```

`None` (the default) means a manifest written before this field existed, and
`check_reel` reports that as its own named not-checked reason rather than as a
zero. Refused at load if it is neither shape.

It rides `ReelEpisode` and not a parallel list because phase 1 and phase 2 are
separated by `EPISODES.json` on disk: `build_reel` runs in phase 2 and never sees
a phase-1 report. `build_reel`'s retry loop re-runs `check_episode`, so an episode
it reprocesses gets its `chroma` **replaced from the new report** — the value is
never older than the clip beside it.

Zero extra decodes. The pair is rendered exactly once in the pipeline, by
`_grade_damage`, and this is the number it already produced (2026-09-16 §0.3 is
the precedent: do not pay four decodes two lines below a pair that exists).

### §2.4 The check

`check_reel` gains **`chroma_spread`**, advisory (added to
`models._ADVISORY_CHECKS`), with the detail:

```
{"per_episode": {idx: [delta_c, delta_h]},
 "not_checked": {idx: reason},
 "spread_c": float, "spread_h": float, "worst": float,
 "max": spec.chroma_spread_max, "advisory": True}
```

`worst` is `max(spread_c, spread_h)` and carries the verdict. Fewer than two
readable episodes is `{"status": "not-checked", "reason": …}` — a spread over one
number is not a number.

The name claims what it measures and nothing more. It is **not** `chroma_match`:
a uniform grade is not the goal, agreement is, and §0.4 is why agreement has no
number. Naming it after the goal would make the report state a conclusion the
measurement cannot reach.

### §2.5 The threshold

`ReelCheckSpec.chroma_spread_max = 5.0`.

Measured margin on the only real reel: the three episodes graded consistently
span **3.52** dC\* / 0.71 dH\*; adding ep0 takes it to **6.90 / 9.07**. `worst` is
therefore 3.52 without ep0 and 9.07 with it, so the bar sits between them with
**1.48** below and **4.07** above, over a statistic whose own noise is
0.06–0.19 on the quiet episodes. Four episodes, one camera, one shoot — §5 says so
plainly.

Task 6 re-runs the measurement against the suite's own `golden_ride_segment`
fixture during implementation, but that run is a **constructed scenario, not a
calibration**: it is four regrades of ONE 1.58s clip, not four independently
shot episodes, and the separation there is driven by `delta_c`, where the real
reel's was `delta_h`. What the fixture proof establishes is the order of
magnitude and the end-to-end wiring — real pixels, through this constant, to a
passing or failing `CheckResult` — so a test can defend the WIRING. It does not
establish a second, independent calibration of 5.0 against footage the design
has not seen; §5.3 says the same about the bar itself.

One more caution for the next reader: §0.6's table is a 2-decimal **display**
of a full-precision measurement. Recomputing `max(hs) − min(hs)` from the
table's own rounded literals (7.84 and −1.22) gives **9.06**, not this
section's **9.07** — verified directly (`7.84 - (-1.22)` is 9.06 to 20
decimal places, not a floating-point artifact near a rounding boundary).
ep0's own per-frame noise (§0.6: 1.81/1.91, far above its siblings'
0.06–0.19) is consistent with a full-precision median that does not survive
2-decimal display rounding without shifting this subtraction by a cent. Both
numbers are correct, about different things — the full-precision figure this
section quotes, and what the table's own rounded display recomputes to — and
`tests/lib/test_check_reel.py::test_one_episode_graded_the_other_way_fails_the_bar`
pins **9.06** deliberately, because that is what its exact literals compute.
Do not "loosen" that test to 9.07, and do not "fix" this section's 9.07 to
match the table.

---

## §3 What does not change

- **No knob is authored.** `match_grade` still authors `tone_src`/`tone_dst` and
  nothing else. This slice adds no automatic chroma actuator, and §0.8 says why
  the dormant one is not it.
- **`tone_arg`, the tone target, `grade_faithful`, `grade_damage`, `target_dev`** —
  untouched. Three luma numbers still go in and come out.
- **`regions.py`** — untouched. The crop needs no mask; `subject_mask` and `refuse`
  keep their two readers.
- **Nothing blocks.** `chroma_spread` is advisory, so the reel's `overall` is
  byte-identical to today's on every reel that would have passed before.

---

## §4 Proofs

1. **The number is the one already computed.** `crop_delta_c` on a fallback
   episode is `==` to its `delta_c`, not `approx` — the same `evaluate` over the
   same pairs (this is why the key is not emitted there at all).
2. **Sign.** Swapping the graded and plain stacks inverts `delta_c`/`delta_h`
   while leaving `delta_e` identical; the existing 2026-09-16 row-13 assertion
   covers the pair, and one new assertion covers `crop_delta_c`'s sign.
3. **Real footage, real spread.** ep0 vs its three siblings reproduces from the
   run's own artifacts: worst 9.07 against a three-episode baseline of 3.52.
4. **Content cancellation.** Two renders of one frame through *identical* chains
   give a displacement of exactly 0.0 on both components — the control that must
   not move.
5. **Not-checked, named.** A `pc` segment produces `{"status": "not-checked"}` with
   the plan's own refusal as the reason, on the episode AND in the reel detail —
   never a 0.0 that reads as "the grade moved nothing".
6. **Advisory.** A reel whose `chroma_spread` fails still reports `overall` true.
7. **Fewer than two readings** is not-checked, not a spread of 0.0.

---

## §5 Honest limits

1. **Uniformity is not agreement.** The check measures whether the grade treated
   the episodes alike. Two episodes with identical displacement can still look
   nothing like each other, and two with different displacements can be exactly
   right if they started apart. The quantity the row asked for — do the delivered
   episodes agree in colour — remains unmeasured, and §0.4 is the reason, not an
   omission. Luma is in the same position: cross-episode agreement there survives
   only as the advisory `target_dev` (2026-08-31 §2.1).
2. **The remedy exists for half the findings.** `saturation_arg` is a clean,
   hue-preserving chroma scaler, so a dC\* divergence has an actuator. A dH\*
   divergence — ep0's case, the one real finding — has none: `mid_blue` and
   `shadow_red` are per-channel curves, not hue rotations. The report can name
   what moved without naming what to turn.
3. **Four episodes, one camera, one shoot.** §0.7: the Canon half is unreadable on
   this run. `chroma_spread_max` is a first cut with a 1.48/1.90 margin around it,
   and no pool discriminates it. The suite's own `golden_ride_segment` proof (Task
   6, §2.5) does not change this: it confirms the order of magnitude and the
   wiring end to end, not a second calibration — its four measurements are
   regrades of one clip, not four shot episodes, and the effect that separates
   them is `delta_c`, not the real reel's `delta_h`.
4. **The bbox is still a bbox.** §0.3/§0.5 stand: the subject region cannot carry a
   chroma claim until it is a mask. This slice does not need it — the crop does
   the work — but it does not advance it either.
5. **Nothing proves anyone read the number.** Same limit every advisory in this
   repo carries. `reel-review`'s `colour` axis is where a human meets it.
6. **The statistic is a mean over a region, not a distribution.** A grade that
   pushes half the frame red and half cyan reads as zero displacement. No sample
   on this run does that; nothing rules it out.

---

## §6 Deferred — filed as rows

1. **`color_means` is never measured, so the grey-world white balance applies one
   fixed cast correction to every episode** (§0.8). Closing it means measuring
   per-episode channel means over a named region AND answering what neutral means
   on footage that is mostly ocean. A slice, not a chore.
2. **An absolute cross-episode chroma target, blocked on the seg mask** (§0.4,
   §0.5). Re-open when the subject is a mask and a pool exists where a subject
   reference beats the crop it would replace — the same bar named-regions set for
   the rejected tonal `band`.
3. **A per-episode chroma actuator the conductor could solve through** (§5.2).
   Today no automatic stage writes any chroma knob; a target without an actuator
   would be a gate with no remedy, which is the `tone_match` deadlock.
4. **Re-derive `chroma_spread_max` on a reel whose episodes are readable on both
   cameras** (§0.7, §5.3).
