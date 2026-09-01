# Grade sensors: faithfulness vs damage — design

**Date:** 2026-08-31 · **Closes:** backlog P1 rows 1 and 2 (the two colour-gate
deadlocks), P2 `probe grade` cannot predict the gate, P2
`naturalness.evaluate_delta` compares the wrong regions.
**Predecessor:** [grade-shipped-pixels](2026-08-30-grade-shipped-pixels-design.md),
whose §9.8 and §9.9 filed both deadlocks with numbers and no fix.

Two blocking colour gates each stop a *correctly graded* episode and route it
back to the stage that authored the grade. They are different mechanisms with
one root: **each measures the render against a reference that pretends the
declared grade does not exist.**

- `check_episode.color_fidelity` measures how far the grade moved the tracked
  subject, source vs delivered. A grade IS movement, so an intentional grade
  reads as damage. Its premise died the day `match-grade` became required.
- `check_reel.tone_match` measures the delivered percentiles against the target
  the conductor solved for **with every other knob at identity**. Any post-tone
  luma knob displaces the reading.

The fix is not a threshold. It is to notice that two different questions are
being asked through one sensor each, and to give each question its own
reference.

---

## §0 Measurements

Every number below was measured on 2026-08-31 against the 2026-06 run's eight
real episodes, read-only. The run predates the 0.3.1 range contract, so its
segments were copied out and normalized to tv through `extract`'s own filter
pair (`scale=in_range=auto:out_range=tv` + `-color_range tv` + `-pix_fmt
yuv420p`) before anything was rendered. Nothing was written into the run.

### §0.1 The `color_fidelity` deadlock, on real footage

The run's shipped tone pairs are hand-authored `[20, X, 255] → [20, 146, 255]`
— the midpoint only. A **conductor** pair is not that shape: it solves all
three anchors from `color_measure.measure_crop`. Measuring the eight crops and
taking the per-anchor median gives the common target `[52.5, 103.5, 191.5]`,
and authoring each episode's own pair against it:

| ep | deviation | median subject dE00 |
|---|---|---|
| 0 | 29.5 | **6.06** |
| 1 | 50.5 | **5.38** |
| 2 | 19.5 | 3.42 |
| 3 | 34.5 | 2.59 |
| 4 | 23.5 | **5.60** |
| 5 | 68.5 | **11.01** |
| 6 | 29.5 | 0.76 |
| 7 | 51.5 | **12.35** |

**Five of eight cross `grade_delta_max = 5.0`**, two at over twice it. None is
damage. This is the gate firing on the thing the required stage exists to do.

### §0.2 The `tone_match` deadlock, on real footage

All eight episodes carry a post-tone luma knob (`shadow_red` on 7, `mid_blue`
on 4, a non-default `color_means` on all 8). Max-anchor residual against the
target, tone pair alone vs the full declared chain:

| ep | tone only | full chain |
|---|---|---|
| 0 | 8.50 | **12.50** |
| 1 | 4.50 | 4.50 |
| 2 | 2.50 | 3.50 |
| 3 | 2.50 | 2.50 |
| 4 | 1.50 | 3.50 |
| 5 | 3.50 | 3.50 |
| 6 | 2.50 | 2.50 |
| 7 | 4.50 | 3.50 |

The knobs displace the reading by 0 to +4.0 units, and **one of eight** crosses
`tone_match_max = 12.0`. So on this footage the second deadlock is a near miss,
not a fire. What makes it a live hazard is §9.9's synthetic measurement on a
3-band clip — `black_point = 0.05` alone lands 12.0 and `0.10` lands 25.0 —
against a knob whose documented range is `[0, 0.35]` and whose docstring names
a real production case. The precondition is universal; the firing is footage-
dependent, and this footage happens to be gentle.

Note ep0's tone-only residual of 8.50: at the healthy edge the predecessor
already recorded (§0.6, healthy maximum 8.0). Consistent with it, not a new
defect.

### §0.3 The damage statistic: four candidates, one survivor

Three classes, all rendered through this repo's own `probe._plan_for` and
`color_measure.plan_ungraded` so the two sides of every ratio differ **only**
in the colour tail:

- **A** — the eight shipped grades (weak: `shadow_red`, `mid_blue`, `saturation`).
- **B** — the eight realistic conductor pairs from §0.1. Legitimate by
  construction: this is what the required stage authors.
- **C** — six deliberate damages on ep0 and ep4, every value **inside** its
  documented range: `black_point = 0.35` (the legal maximum), `highlight = 0.60`
  (the legal minimum, documented as where the picture reads fogged), and a
  crushing tone pair `[20, 146, 255] → [20, 80, 140]`.

Median over three sample frames of graded ÷ ungraded:

| statistic | A (8) | B (8) | C (6) | B∩C |
|---|---|---|---|---|
| **luma entropy, whole frame, 256 bins** | 0.969 … 1.010 | **0.921** … 1.058 | 0.814 … **0.910** | **none** |
| luma entropy, whole frame, 64 bins | 0.965 … 1.019 | 0.899 … 1.090 | 0.777 … 0.925 | overlap |
| luma entropy, subject box, 64 bins | 0.962 … 1.017 | 0.859 … 1.046 | 0.698 … 0.860 | overlap |
| distinct luma codes, subject box | 0.975 … 1.0 | — | 0.516 … **1.042** | overlap |
| mean \|gradient\|, subject box | 0.914 … 1.065 | — | 0.479 … **1.327** | overlap |

Three findings, each of which changed the design:

**Distinct-code count does not work**, though it is the obvious reading of
"information destroyed" and was the shape this slice set out to build. On the
eight shipped episodes it reads 227–254 out of 256 — pinned against its own
ceiling — and gives 0.968–1.004 across the board while ep7 carries 3.9 % of its
pixels at white, nearly twice `naturalness.BLOWN_FRAC`. Encoder noise and
resampling refill codes faster than a compressive map empties them. Worse, on
`black_point = 0.35` it reads **1.042**: the crush registers as an improvement.
Mean gradient inverts the same way (**1.327**), because a toe lift raises local
contrast while destroying the shadow detail underneath it.

**Entropy is the right quantity and the reason is structural.** Shannon entropy
of the luma histogram is invariant under any *bijective* monotone map — a
relabeling carries the histogram intact — and falls only where the map is
many-to-one. That is precisely "blind to movement, sensitive to destruction",
which is the property the whole sensor needs. Unlike a code count it is
weighted by where the mass actually sits, so a handful of stray pixels cannot
saturate it.

**It must be read on the whole frame, not the subject.** On the subject box,
classes B and C touch (0.859 vs 0.860). The boxes span 2 420 px on ep7 against
890 406 px on ep6 — a 368× range — and a 256-bin histogram over 2 420 samples
is a badly biased entropy estimator. Coarsening to 64 bins does not rescue it;
it makes the whole-frame reading overlap too. The whole delivered frame is
~2 M samples on every episode, so the estimator's bias is constant across the
pool and cancels in the ratio.

### §0.4 The margin, stated plainly

Between B's worst (0.921) and C's best (0.910) the gap is **1.2 %**. A floor at
**0.90** sits 2.1 % below the worst legitimate conductor pair and catches five
of the six damages. The one it does not catch is `highlight = 0.60` on ep0, at
0.910 — the legal minimum of a knob documented as *the boundary of acceptable*.
Passing exactly at the boundary is the correct verdict, not a miss; but a floor
with 2.1 % of headroom is a first cut, and §9 says so.

---

## §1 The rule

**Two questions, two sensors, two references.**

| | question | reference |
|---|---|---|
| **faithfulness** | did the render get the grade that was declared? | the prediction of the **full declared chain** |
| **damage** | does the declared grade destroy information? | the **same episode ungraded**, same geometry, same render path |

Neither reference is identity. That is the whole change.

---

## §2 Faithfulness — `tone_match` becomes `grade_faithful`

`check_reel._tone_match_check` keeps its shape, its `not-bound` accounting, its
batched single-decode read of the master and its escalation to `match-grade`.
One thing changes: what the master's percentiles are compared against.

**Today** it is `tone_target`, and the justification is that percentiles commute
with a monotone map. True, and irrelevant — it holds only while the tone curve
is the last luma operation, and six luma-moving filters follow it.

**New:** `color_measure.crop_percentiles` over the **full** colour block, i.e.
the same `RenderPlan` that `probe._plan_for` builds and `reframe` encodes. The
gate then makes no assumption about the chain's order at all. A post-tone knob
moves prediction and delivery together and cancels.

The prediction is computed **fresh, inside `check_reel`** — never recorded at
render time and read back. A recorded prediction goes stale the moment
`build_reel`'s retry loop re-renders an episode, and a stale binding is this
repo's most repeated wound (`episode_qc`'s digest stamp, `MATCH.md`'s 8-against-
5, `REVIEW.json` two versions old). Cost is one three-frame render per bound
episode, the same order as `probe grade`, paid once per reel.

The source each prediction renders from is resolved through `probe.source_for`,
which already handles the stabilized case correctly — a route measured on
stabilized pixels must be replayed against the stabilized file, and inferring a
filename would silently pick the raw one.

**Threshold.** `ReelCheckSpec.tone_match_max = 12.0` is replaced by
`grade_residual_max`. 12.0 was mid-gap between a healthy maximum of 8.0 and a broken
minimum of 19.5, both measured against the *wrong* reference. Against the right
one the residual is prediction-vs-delivery agreement, which the predecessor
measured at **1 code** (§0.8). The new ceiling is set by measurement in the
plan, not chosen here; the expectation is ~4.0.

### §2.1 It stops checking cross-episode agreement, and that is a demotion

Today's gate compares each bound episode against the reel's **common** target,
so it is weakly an agreement check: everything within 12.0 of one target agrees
within 24.0 of everything else. Against the new reference each episode is
compared to **its own** declaration, and agreement is no longer measured at all.

Two consequences, both taken deliberately:

The check is **renamed `grade_faithful`** and judges **every** episode, not only
the ones bound to the target. Faithfulness is a property of any declaration,
including an empty one, so the `not-bound` skip disappears; `not_checked`
survives only for an episode whose prediction could not be built.

Agreement becomes the **advisory `target_dev`** — `max|prediction − target|` per
bound episode, which is §0.2's full-chain column. It is not blocking, and the
reason is that making it blocking re-opens the deadlock from the other side:
ep0's declared chain lands 12.50 from the target and the only remedy is a
conductor that solves the tone pair **through** the post-tone knobs, which is an
iterative solve and its own slice (§10 row 4). Demoting a signal that is wrong
today (it fires on correct input) to a number that is right is an improvement;
pretending it still gates would not be. §0.2 also bounds what is being given up:
on real footage the knobs displace agreement by at most 4.0 units.

**What it no longer catches, named.** The old reference was independent of the
render path; the new one shares `process_episode.build_reframe_spec` with it.
A bug that drops a field on the way from manifest to `ReframeSpec` now breaks
both sides identically and passes. Mitigation: the old comparison stays in the
report as an **advisory** `target_dev` per episode. The signal remains visible
to a reader and to the QC judge; it stops being a gate, because as a gate it
is wrong. `target_dev` carries both jobs at once — it is the render-path-
independent reading AND the agreement reading.

**Routing.** A faithfulness failure means the pixels did not get the
declaration, so the remedy is a re-render, not a re-authoring: the failure
routes to `process-episode`, not to `match-grade`. It escalates for free —
`reel_orchestration._REPROCESS_CLASS` is `("black",)`, so every non-black reel
failure already escalates rather than looping.

---

## §3 Damage — `color_fidelity` becomes `grade_damage`

The check is renamed because it measures something else now. The retro's
recurring lesson is a bar measuring something other than what it names, and
keeping the old name over new arithmetic would be that defect on purpose.

**Statistic:** Shannon entropy of the delivered frame's luma histogram, 256
bins, graded ÷ ungraded, median over the three sample frames.
**Floor:** `CheckSpec.entropy_floor = 0.90`, one-sided. Blocking.

**Both sides are read from a render, not from the shipped clip.** libx264
quantization lowers entropy on its own and would bias the ratio toward false
damage; rendering both sides through the same path keeps the comparison
symmetric. The consequence is explicit: **damage judges the declared map,
faithfulness judges the delivered pixels.** Between them the declaration and
the delivery are both covered, and neither sensor pretends to cover the other's
half. The size of the x264 entropy bias is measured in the plan and recorded,
so the choice is on the record rather than assumed.

**The escalation becomes correct.** `grade_damage` sits in
`orchestration._UNFIXABLE` and reports `grade-damage`, routing to the episode's
colour block — which was a loop with no exit while any grade tripped it, and is
now the right answer, because the sensor fires only on a grade that destroys
information and the remedy really is to soften the knob.

**dE00 does not disappear.** `lib/colordiff` and the subject sampling stay, and
the median dE00 with its `dominant` component ride the report as advisory
numbers. As a *description* of what a grade did ("the grade lifted exposure")
they are good, and the QC judge reads them. As a gate they were wrong.

### §3.1 Placement

- **New pure `scripts/lib/gradedamage.py`** — `entropy(frame)` and
  `evaluate(plain, graded, floor)`. numpy in, one dict out; no ffmpeg, no
  paths. Same boundary as `lib/naturalness.py`, and its constants live in the
  module for the same stated reason.
- `check_episode.run` gains `plans: tuple[RenderPlan, RenderPlan] | None = None`
  — (graded, plain). `None` reports `not-checked`, exactly the shape `source`
  already uses: non-blocking by default, blocking in practice because
  `process_episode` passes it.
- `process_episode` builds the pair — it already builds the graded plan for
  `reframe`, and `color_measure.plan_ungraded` is the stripped twin, already
  written and already used by `measure_crop`.
- `CheckSpec.grade_delta_max` is **deleted** and `CheckSpec.entropy_floor`
  replaces it. An advisory number needs no ceiling.

---

## §4 What this opens

`grade_damage` fires only on destroyed information; `tone_match` fires only on
a render that disagrees with its declaration. `match-grade` re-authoring the
identical pair no longer re-arms either. Both loops have an exit that is a real
remedy rather than a restatement of the stop.

---

## §5 Two P2 rows that come nearly free

**`probe grade` can now predict both gates.** It already renders the graded
frames and reports `tone_profile`; adding the ungraded render gives it the
damage reading, and the profile it already has IS the faithfulness prediction.
`probe.json` gains `grade_damage` and `predicted_profile`, so an operator
converging on stills sees the two stops coming instead of meeting them after a
full render.

**`naturalness.evaluate_delta` stops comparing the wrong regions.** Its source
reading is a whole segment frame and its graded reading is a reframed crop of
it — the branch's own test records source contrast 0.0 against graded 123.6
with no grade at all. The ungraded render this slice adds *is* the source in
the episode's own crop geometry, so `episode_qc._source_reading` reads it
instead. Advisory either way; it stops being nonsense.

---

## §6 Contracts touched

| file | change |
|---|---|
| `scripts/lib/gradedamage.py` | new — `entropy`, `evaluate`, `ENTROPY_BINS` |
| `scripts/lib/color.py` | `FRAMES` + `sample_times` move here from `color_measure`, which `check_episode` cannot import (cycle) |
| `scripts/reframe.py` | new `plan_frames_rgb(plan, src, times)` — one plan, N decoded frames (named apart from the pre-existing `assembly.frames_rgb`, which reads a finished file at its native size) |
| `scripts/lib/models.py` | `CheckSpec.grade_delta_max` → `entropy_floor = 0.90`; `ReelCheckSpec.tone_match_max` → `grade_residual_max`, re-measured |
| `scripts/check_episode.py` | `color_fidelity` → `grade_damage`; `plans=` parameter; dE00 demoted to advisory |
| `scripts/lib/orchestration.py` | `_UNFIXABLE` / `_UNFIXABLE_REASON` renamed to `grade_damage` |
| `scripts/process_episode.py` | `plan_for` + `plan_ungraded` (moved from `color_measure`, which could not carry them without a cycle); builds and passes the plan pair |
| `scripts/check_reel.py` | `tone_match` → `grade_faithful`: reference swap, every episode judged, advisory `target_dev` |
| `scripts/build_reel.py` | forwards what the fresh prediction needs |
| `scripts/probe.py` | ungraded render; `grade_damage` + `predicted_profile` in `probe.json` |
| `scripts/episode_qc.py` | `_source_reading` reads the crop-geometry ungraded render |

---

## §7 Proofs

Each with a control that must not move.

1. Real ffmpeg: a conductor pair on real footage passes `grade_damage` and
   fails the OLD `color_fidelity` — the deadlock, demonstrated and removed.
2. Real ffmpeg: `black_point = 0.35` fails `grade_damage`; the same episode
   ungraded passes.
3. Real ffmpeg: an episode carrying a post-tone knob passes the new
   `tone_match`; the same reel with its colour block dropped after authoring
   fails it.
4. `tone_match`'s new ceiling, measured prediction-vs-master on a real encode.
5. The x264 entropy bias, measured: clip-read vs render-read on one episode.
6. Byte-identity: an ungraded episode's render is unchanged by this slice.

---

## §8 Rejected

**Reorder `grade_chain` so tone is last.** Makes `tone_match`'s original
justification unconditionally true for free, and would guarantee the reel's
common target regardless of creative knobs — a real argument. Rejected because
it fixes one deadlock and not the other, changes what every knob after it
acts on (today they see tone-normalized input; reordered they would see the raw
source, and `highlight`'s knee is a fixed 0.55 either way), moves goldens, and buys nothing the prediction reference does not already buy.

**A per-episode written waiver.** Cheapest exit from both loops. Rejected: "no
waiver" is load-bearing in `episode_qc`, `constraints` and the variety gate,
and a sensor that needs waivers on correct input is a broken sensor, not a
strict one.

**Recording the prediction at render time.** Zero cost at check time. Rejected
on staleness: `build_reel`'s retry re-renders an episode after its record was
written.

---

## §9 Honest limits

**§9.1 The margin is 1.2 % and the negative class is six synthetic points.**
Classes B and C come from eight episodes of one shoot and six knob extremes on
two of them. `0.90` is a first cut with 2.1 % of headroom below the worst
legitimate pair. It will move on the next real run, and a run that moves it is
worth more than any further synthesis here.

**§9.2 `highlight = 0.60` passes.** At 0.910 it clears a 0.90 floor. Argued
above as correct — it is the documented boundary of acceptable — but a reader
should know the sensor does not stop a fog authored exactly at the legal edge.

**§9.3 Entropy is blind to chroma.** A grade that destroys colour while leaving
the luma histogram intact reads clean. `naturalness`'s source-relative
saturation and cast flags are the only cover, they are advisory, and their bars
are set against the run that IS the complaint (own P2 row).

**§9.4 Faithfulness shares a code path with the render.** Stated in §2 and
mitigated by the advisory `target_dev`, not closed.

**§9.5 Damage never reads the shipped clip.** By construction, per §3. The
encode's own contribution is covered by the black gate and the look gate, not
by this one.

**§9.6 Nobody has looked at any of this on a screen.** Every number here is a
histogram statistic. Whether a reel that passes both gates looks right is the
QC judge's question and no measurement in this slice answers it.

---

## §10 Deferred

Each of these gets a backlog row before this slice is finished.

1. **Re-derive `entropy_floor` on a run whose negative class is real footage,
   not synthesized knob extremes** (P2/S). Blocked on a run graded after R1.1.
2. **A chroma-damage sensor** (P3/M). §9.3 — the half entropy cannot see.
3. **Make the faithfulness reference independent of `build_reframe_spec`**
   (P3/M). §9.4 — would need a second, separately-written path from manifest to
   chain, which is a cure worth less than the disease until something breaks.
4. **Let the conductor solve the tone pair THROUGH the post-tone knobs, then
   re-block agreement** (P2/M). §2.1 — `match_grade` measures at identity and
   the knobs then displace the result by up to 4.0 units on real footage and
   12.50 on ep0. An iterative solve would let `target_dev` become a gate again.
