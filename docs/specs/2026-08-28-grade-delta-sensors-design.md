# Grade-damage sensors — design

**Date:** 2026-08-28
**Backlog:** R2.2 (`color_fidelity` cannot see the damage it exists to catch),
R2.5 (the naturalness sensor was never calibrated)
**Status:** design

Two blind colour sensors become one measurement of what the grade did to the
subject, and one measurement of what it did to the frame. The rule underneath
both: **the operator's complaints are about a change, so the sensor must
measure a change** — and where the change cannot be measured against a
trustworthy baseline, the sensor reports and does not stop.

---

## §0 What was measured

Everything below comes from the preserved 2026-06 run
(`/Users/serg/Downloads/untitled folder`), read-only. Two replays re-ran
`check_episode._colour_fidelity`'s own sampling against the run's own
`route.json` / `path.json` / `path.meta.json`, its pre-grade segments
(`work/segments/ep*_raw.mp4`) and its delivered episodes (`out/ep*.mp4`).

### §0.1 The backlog row's own numbers do not reproduce — two artifact sets

R2.2 quotes "0.8°", "null on 2 of the 8 shipped episodes" and "129.4° on
another". Those numbers come from two different directories.

`out/EPISODES.json` names `work/ep{i}/` for every episode's route, path and
sidecar. That set is dated 2026-08-25, records `src_dims` 3840×2160 and carries
the zoom's `crop_ws`/`crop_hs`/`crop_ys`. A second set at `work/reel/ep{i}/` is
dated 2026-08-20/21, records 1920×1080 and has no zoom. It is stale.

| set | `color_fidelity` readings |
|---|---|
| `work/ep*` — **shipped** | 13.4°, 2.4°, 1.9°, not-checked, not-checked, 1.4°, 1.2°, 10.3° |
| `work/reel/ep*` — stale | 175.2°, not-checked, 134.3°, 99.6°, not-checked, 2.9°, not-checked, 140.3° |

So the shipped reel's readings were **1.2°–13.4°, every one under the 25°
threshold, with 2 of 8 not-checked** — the last of which matches the row. The
near-complementary readings the row calls false positives are the stale set's.
The row's "28-code shift" does not appear in either: the largest whole-frame
per-channel mean change across the eight shipped episodes is **18.3** (ep2's
blue), and the largest subject-box change is **9.6**.

This does not weaken the row. It sharpens it: the check was not noisy on the
shipped reel, it was **silent**.

### §0.2 The grade moves luma and chroma; the check kept hue

24 samples (8 episodes × 3, the code's own 0.25/0.5/0.75 of the route span):

- largest luma change of any sample: **6.7 codes**; largest per-channel: 9.6
- **9 of 24 samples returned `None`** — chroma below `GREY_EPS = 10`
- ep2 @4.33s: subject chroma **19.2 → 9.3**, halved by the grade → reported `None`
- ep4 @0.92s: subject chroma **1.5 → 6.3**, quadrupled → reported `None`
- ep0 @1.13s: chroma **15.8 → 27.5**, +74% → reported 12.4°, under threshold

`color_fidelity`'s docstring states the invariance as a feature: hue is
"invariant to exposure … and to saturation". The grade is an exposure and
saturation move. **The quantity that moved most is the quantity the check
discards, and the grey floor then discards the one it keeps.**

### §0.3 CIEDE2000 answers every sample

The same 24 pairs through sRGB→Lab→ΔE00 produce a number for all 24 —
`not-checked` disappears as a state. Median of |component| per sample, with
damage simulated at the magnitudes the retro recorded for R2.6:

| case | \|ΔL*\| | \|ΔC*\| | \|ΔH*\| |
|---|---|---|---|
| as shipped | 1.03 | 1.53 | 0.80 |
| +43 B−R push (2026-08-20) | 1.51 | 9.83 | **10.96** |
| 33.8 R−B swing (ep6, 2026-08-22) | 1.44 | 6.76 | **9.31** |
| +28 luma lift | **10.78** | 1.42 | 0.77 |
| chroma halved ("washed out") | 1.05 | **2.18** | 0.54 |

### §0.4 A per-component bar does not work; the per-episode ΔE00 median does

Per-episode medians of |ΔH*| refute the obvious gate:

| | per episode |
|---|---|
| as shipped | 3.36, 0.62, 0.26, 0.96, 1.50, 0.41, 0.46, 1.45 |
| +43 B−R | 3.76, 16.25, **0.29**, 3.57, 5.79, 14.77, 16.09, 12.56 |

A blue push against an already-blue subject (ep2's box means
`[75, 85, 99]`) moves **chroma, not hue** — 0.29 after the push. Any |ΔH*| bar
either misses those episodes or fires on the healthy 3.36.

ΔE00 over the whole colour difference does separate. Measured through the
production sampling path (§2.2 — `assembly.frames_rgb`, 5 samples at
0.1/0.3/0.5/0.7/0.9 of the route span), per-episode **median**:

| case | per-episode median ΔE00 | min | max |
|---|---|---|---|
| as shipped | 4.29, 1.44, 2.93, 1.20, 2.83, 1.94, 0.89, 2.05 | 0.89 | **4.29** |
| 33.8 R−B swing | 9.78, 11.08, 5.04, 8.95, 8.37, 10.87, 10.05, 10.19 | **5.04** | 11.08 |
| +28 luma lift | 10.07, 12.03, 10.26, 10.71, 8.36, 8.64, 11.78, 5.91 | **5.91** | 12.03 |
| +43 B−R push | 11.07, 13.64, 6.59, 10.74, 10.25, 13.25, 12.61, 12.25 | **6.59** | 13.64 |
| blacks lifted 0.15 | 7.01, 10.58, 9.20, 9.34, 5.88, 9.23, 9.68, 2.56 | 2.56 | 10.58 |
| blacks lifted 0.10 | 5.94, 7.34, 6.31, 6.20, 3.65, 5.83, 6.63, 2.25 | 2.25 | 7.34 |
| chroma halved | 2.17, 3.57, 5.42, 1.25, 2.80, 1.84, 5.74, 3.17 | 1.25 | 5.74 |
| chroma × 0.7 | 2.62, 2.23, 4.54, 0.84, 2.75, 1.02, 3.29, 2.85 | 0.84 | 4.54 |

The gap between "as shipped" (max 4.29) and the three damage classes
(min 5.04) is the whole basis of the blocking threshold, and §9.1 prices it.

### §0.5 `naturalness` was measuring the ocean

From the run's own `qc/ep*/evidence.json` and a re-measure of the pre-grade
segments at the same five fractions:

| flag | bar | measured on the run | verdict |
|---|---|---|---|
| `colour_cast` | `CAST_MAX = 0.08` | fired on **6 of 8** graded episodes; **6 of 8 SOURCES already exceed it** (source casts 0.023–0.366) | measures the scene, not the grade |
| `flat` | `FLAT_SPREAD = 40.0` | actual contrasts 85.96–188.94 | unreachable |
| `oversaturated` | `SAT_MAX = 0.60` | actual saturations 0.108–0.497, and the test is one-sided | unreachable, and blind to desaturation |
| `crushed_blacks` | `CRUSHED_FRAC = 0.05` | max actual 0.0131 | never fired |
| `blown_highlights` | `BLOWN_FRAC = 0.02` | ep7 at 0.0369 | fired once, plausibly |

(The retro says `colour_cast` fired on 7 of 8; the packed evidence says 6 —
ep1 at 0.0282 and ep3 at 0.0580 are both under the bar.)

A grey-world assumption cannot hold on a seascape. The blue cast is in the
footage; the grade did not put it there.

Source-vs-graded deltas of the same three quantities, across the shipped run
and each simulated damage:

| case | Δcast | Δsaturation | Δcontrast |
|---|---|---|---|
| as shipped | −0.0766 … +0.0597 | −0.1026 … +0.0316 | −16.61 … +24.50 |
| +43 B−R | +0.0748 … +0.2390 | +0.1301 … +0.3084 | −16.61 … +24.50 |
| +28 luma | −0.1092 … +0.0356 | −0.1600 … −0.0287 | −16.61 … +23.38 |
| chroma halved | −0.2032 … +0.0067 | −0.2418 … −0.0599 | −17.79 … +24.19 |
| blacks lifted 0.10 | −0.1091 … +0.0394 | −0.1597 … −0.0257 | −26.99 … +5.96 |
| blacks lifted 0.15 | −0.1325 … +0.0306 | −0.1887 … −0.0437 | −32.92 … −3.23 |

Δcontrast is unmoved by three of the four simulations, because a uniform luma
lift and a chroma change do not alter the luma p95−p5 spread. It moves only
under lifted blacks — that is, only under the operator's own "shadows gone",
and under nothing else.

### §0.6 There is no clean negative class for "washed out"

The eight shipped episodes are the reel the operator called washed out. ep1
loses **16.61** of luma contrast and ep2 loses **0.103** of saturation *as
delivered*. So the "healthy" column above is a trustworthy negative class for
the hue-push and luma-lift incidents (2026-08-20 and 2026-08-22 were separate
events, recorded separately) and **is not one** for desaturation or lifted
blacks: any bar drawn to have zero false positives against it is drawn against
a baseline that already contains the defect.

That measurement, not a preference, is why the desaturation and contrast
sensors stay advisory.

---

## §1 The rule

A grade is a change. A sensor that judges the graded frame alone is judging the
footage; a sensor that judges a change must keep every component the change can
land in. So:

1. **Subject, source→graded**: one colour-difference number that keeps luma,
   chroma and hue, and discards no sample. Blocking.
2. **Frame, source→graded**: the three stylistic quantities as deltas, never as
   absolutes. Advisory, because §0.6.
3. **Frame, absolute**: only what measures destroyed information — clipping at
   white and at black. Those are absolute by nature: a blown sky is blown
   whatever the source held.

---

## §2 The blocking half

### §2.1 `lib/colordiff.py` — new, pure

One responsibility: colour-difference arithmetic. `math` only; no numpy, no new
dependency.

```python
def rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]
def ciede2000(lab1, lab2) -> tuple[float, float, float, float]   # (dE00, dL*, dC*, dH*)
```

sRGB with the D65 white point and the standard piecewise linearization.
`ciede2000` returns the total alongside its three signed components, because
the components are the explanation the report needs (§2.3) and recomputing them
in the caller would duplicate the formula's own intermediate terms.

### §2.2 Sampling: one decode per file, five samples

`check_episode._region_mean_rgb` runs **one ffmpeg output-seek per sample per
file** — six decodes per episode for three samples. `assembly.frames_rgb`
already batches an arbitrary set of frames into a single decode (2026-08-02),
and routes around the `select`-before-`fps=` landmine by construction.

So `_region_mean_rgb` is replaced by a per-file batch: `frames_rgb(src, times,
fps)` once for the segment, once for the clip, box means taken from the returned
arrays. Five samples then cost **two** decodes per episode instead of six for
three. The sample fractions become 0.1/0.3/0.5/0.7/0.9 of the route span, and
every threshold in §0.4 was measured through exactly this path.

`frames_rgb` raises when a requested time is at or past the stream end, so each
time is clamped to `dur - 1/fps` before the call.

The route's timestamps and the delivered clip share one time base even for a
ramped episode: `ramp.retime` runs as an extract pre-stage, so tracking and
reframe both see already-retimed pixels (speed-ramp design §2). No remap is
needed here, and adding one would be wrong.

### §2.3 `lib/color_fidelity.py` — rewritten

`hue`, `hue_drift` and `GREY_EPS` are **deleted**. The grey floor is what
discarded 9 of 24 samples, and ΔE00 needs no floor: near-grey pairs have small
C*, and the formula's own `S_H` term already weighs their hue term down.

```python
def sample_deltas(pairs) -> list[tuple[float, float, float, float]]
def evaluate(pairs, delta_max: float) -> dict
```

`evaluate` reports, per episode:

```json
{"delta_e": 2.83, "delta_l": -2.15, "delta_c": 0.08, "delta_h": 1.38,
 "threshold": 5.0, "samples": 5, "dominant": "luma"}
```

(ep4's own medians, measured — the shipped grade pulled its subject 2.15 L*
darker and left chroma alone.)

Every figure is the **median** over the episode's samples — measured in §0.4 to
be the statistic that separates, where the worst sample does not. `dominant`
names whichever of the three components is largest in absolute value, so the
report says *what* moved: `luma` reads as an exposure move, `hue` as a cast,
`chroma` as a saturation move.

The verdict is `delta_e > delta_max`, and `CheckResult.passed` becomes a real
boolean. `not-checked` survives only where it is true today — no source clip,
or no tracked subject (a pan).

### §2.4 The threshold

`CheckSpec.hue_drift_max` (25.0 degrees) is replaced by
`CheckSpec.grade_delta_max: float = 5.0`.

5.0 sits in the gap measured in §0.4: the eight shipped episodes reach 4.29,
and the three damage classes start at 5.04. The bar is deliberately placed
toward the damage side of the midpoint (4.665) rather than on it, because for a
gate calibrated on one shoot a false stop is the expensive error and a miss
leaves the status quo. That choice costs sensitivity and the numbers say so:
the healthy maximum sits **14% below** the bar, while the tightest damage case
clears it by **0.8%**.

Against the bar, of eight episodes each: **0** as shipped, **8** under a
33.8 R−B swing, **8** under +28 luma, **8** under a +43 B−R push, **6** with
blacks lifted 0.15, **5** with blacks lifted 0.10, **2** with chroma halved,
**0** with chroma at 0.7.

A live control that the bar tolerates a real authored grade: ep1 ships a tone
pair `[20, 135.4, 255] → [20, 146, 255]`, a **+10.6-code** mid lift, and its
ΔE00 median is **1.44** — under a third of the bar.

---

## §3 The escalation seam

Making the check blocking without touching `orchestration` would be a defect,
not an omission. `process_episode` feeds `report.fail_reasons` to
`orch.escalation` and `orch.adjust_reframe_params`; neither knows
`color_fidelity`, so the episode would be **re-rendered up to three times at
full resolution while the ladder nudges `max_speed` and `smooth_window_s`** —
geometry knobs that cannot move a colour by construction.

So `color_fidelity` joins `orchestration._UNFIXABLE` beside `length`,
`continuity` and `black_frames`, and `escalation` gains a reason of its own:

```python
{"escalate_to": "edit-plan", "reason": "grade-damage", "fail_reasons": [...]}
```

`"unfixable-by-reframe"` is true but useless here — it names what cannot fix
the problem instead of what can. The remedy is the episode's colour block
(`white_balance` / `saturation` / `shadow_red` / `mid_blue` / the tone pair),
which the EDL owns, so `edit-plan` remains the right destination.

### §3.1 The interaction with `build_reel`'s colour convergence

This is the one interaction the rest of this design never analysed. It was
found by the whole-branch review, and the numbers below were re-measured
through this branch's own `colordiff`.

Phase A.5's retry loop has a colour actuator of its own. On a
`color_across_cuts` failure `build_reel` compounds a per-channel ratio into its
in-memory `cc[idx]` (`scripts/build_reel.py:152`, through
`color.corrected`'s `[0.7, 1.5]` clamp) and re-renders the episode via
`process_episode(..., color_correct=…)`. `check_episode` then measures **that
render against the pre-grade segment** — so the loop's own pull is, to this
sensor, grade movement, indistinguishable from any other.

What a pull costs, on design §0's ep2 subject box mean `(75, 85, 99)`:

| correction | dE00 it contributes |
|---|---|
| 1.02 uniform | 0.60 |
| 1.05 uniform | 1.51 |
| 1.10 uniform | 3.04 |
| 1.10 on one channel | 3.92 |
| 1.50 (`color.corrected`'s clamp) | 16.22 |

The healthy maximum measured in §0.4 is 4.29, so an episode sitting there has
**0.71 dE00** of headroom before the bar — about a 1.02x pull.

**It is a stop, not a deadlock and not a loop.** Colour is `_UNFIXABLE`, so
`process_episode` escalates on attempt 1 rather than retrying, and `build_reel`
returns `stop_and_report` / `reprocess-failed`
(`scripts/build_reel.py:167-171`). Nothing spins. Three things are still wrong,
and none is fixed in this slice:

1. **The attribution is misrouted.** The finding routes to `edit-plan` and
   `check_episode`'s docstring names the episode's colour block — but the pull
   came from `build_reel`'s in-memory `cc` dict, and the EDL's colour fields
   are unchanged and correct. Editing them is the wrong action. The real
   remedies are `match-grade` (converge the episodes *before* the reel loop has
   to pull), a wider `--color-delta-max`, or accepting the mismatch.
2. **Phase A.5 colour convergence is effectively disabled for the reels it
   exists for.** A mixed-camera reel is exactly the one whose episodes need the
   largest pulls, and 0.71 dE00 of headroom does not buy one.
3. **A rejected re-render still lands on disk.** `reframe` writes `m.out_path`
   (`scripts/process_episode.py:396`) before `check_episode.run` reads it
   (`:400`), and `build_reel`'s early return at `:167` happens **before**
   `reprocessed.add(item.idx)` at `:174`. So the run stops with `ep{i}.mp4`
   overwritten by the render that was just rejected, and `reprocessed` not
   recording it. This is caught downstream — `episode_qc.gate`'s stale-digest
   arm (`scripts/lib/episode_qc.py:223-227`) refuses on the next
   `--from-episodes`, because the clip no longer hashes to what was judged — so
   it is **not** a silent bypass. But nothing in the stop report says a clip was
   rewritten, so the operator learns it from the next stage rather than from
   this one.

There is **no test for this interaction at all** today. That, and the
misrouted attribution, are backlog rows rather than a fix here: naming the
right remedy means a new finding kind (`colour-correction-rejected`, routed to
`match-grade`), which is a slice.

---

## §4 The advisory half

`lib/naturalness.py` keeps `measure` unchanged — it already returns every
quantity needed, and `probe.py` and `episode_qc.py` both read its shape.

`evaluate(stats)` keeps its signature and returns **only the two absolute
flags**:

```python
{"blown_highlights": ..., "crushed_blacks": ...}
```

`CAST_MAX`, `SAT_MAX` and `FLAT_SPREAD` are deleted along with the three flags
they gated: one measured the scene, two were unreachable (§0.5).

A new function takes their place:

```python
def evaluate_delta(src: dict, grd: dict) -> dict
```

returning `{"cast_shift": bool, "saturation_shift": bool, "contrast_drop": bool}`
against three new constants:

| constant | value | healthy range (§0.5) | fires on |
|---|---|---|---|
| `CAST_DELTA_MAX` | 0.08 | max \|Δ\| 0.0766 | 7 of 8 under a +43 B−R push |
| `SAT_DELTA_MAX` | 0.12 | −0.1026 … +0.0316 | 8 of 8 push, 5 of 8 chroma-halved, 5 of 8 lifted |
| `CONTRAST_DROP_MAX` | 20.0 | min −16.61 | 4 of 8 with blacks lifted 0.15 |

`cast_shift` and `saturation_shift` are two-sided; `contrast_drop` is signed —
a *gain* in luma spread is not a defect, and testing its magnitude would flag
every episode that gained contrast legitimately (ep6 gained 24.50).

`CAST_DELTA_MAX` reuses the old `CAST_MAX`'s number. That is a coincidence
worth naming rather than a lineage: 0.08 is where the shipped run's own delta
range (max 0.0766) stops, and the fact that the discarded absolute bar sat at
the same value says nothing about either.

Nothing here can fail an episode. §0.6 is the reason: two of the three deltas
are calibrated against a baseline that contains the defect they look for.

---

## §5 The consumer

`episode_qc.pack` already holds the pre-grade segment — `ep.manifest["segment"]`
— and has never read it. It gains a second `frames_rgb` + `measure` pass over
the segment at the same five fractions, and the evidence packet grows two keys:

```json
"naturalness": {"stats": {...}, "flags": {...},
                "source": {...}, "delta": {...}}
```

`source` is the segment's own reading and `delta` is `evaluate_delta`'s three
flags. The judge then argues from what the grade *did*, not from what the
footage *is* — which is the whole of R2.5.

"The same five fractions" is a coincidence, not a contract.
`episode_qc.SENSOR_FRAMES = 5` at `(k+0.5)/5` produces the same numbers as
`check_episode.SAMPLE_FRACS`, but **of different quantities** — clip duration
here, route span there — and **nothing in code ties them**. Either could move
without the other noticing. See §9.9.

`probe.py` is untouched: `measure` and `evaluate(stats)` keep their signatures,
and it loses the three flags that never worked.

**It is not untouched because it has nothing to compare against** — an earlier
draft of this section said so and was wrong. `scripts/probe.py:265` already does
`src = source_for(md, epdir)`, which returns exactly the file `check_episode`
compares against, and handles the stabilized case *more* carefully than
`episode_qc` does (§9.8). The machinery is there; wiring a `color_fidelity`
reading into `probe.json` is **deferred**, not impossible.

The consequence is workflow-level and worth naming. `probe grade` is the tool
`skills/edit-plan/SKILL.md` hands the operator to converge a grade **without a
full render**, and it is now the one tool in the loop that cannot predict the
gate that stops the run: an operator converges on `probe.jpg`, and the full
render then escalates as `grade-damage`. That is a backlog row (§10).

---

## §6 What is deliberately not changed

**The sampling box.** The subject box is mostly background — a person's bbox
over water is water. Both sides cover the same content (the source's route bbox
and its projection into the delivered frame), so the *delta* is a valid
measurement of what the grade did to that region; but "the subject" is a claim
the sampling does not support. That is R2.1, and it stays R2.1.

A cheap candidate fix was measured and **rejected on its own numbers**:
narrowing both boxes to their inner 50% improves the healthy maximum of
\|ΔH*\| from 4.93 to 3.49 and *worsens* \|ΔL*\| from 2.72 to 3.57. It does not
pay, so the full box stays by measurement rather than by omission.

**The absolute clipping bars.** `BLOWN_FRAC` and `CRUSHED_FRAC` keep their
values. One fired once and plausibly; the other never fired on footage that
never crushed. Neither has been shown wrong, and changing an untested number to
another untested number buys nothing.

**`check_reel`'s `color_across_cuts`.** Whole-frame means across a cut are R2.1's
territory, not this slice's.

---

## §7 Contract changes

| where | change |
|---|---|
| `CheckSpec.hue_drift_max: float = 25.0` | → `CheckSpec.grade_delta_max: float = 5.0`, same positive-number validation |
| `Report.checks["color_fidelity"].passed` | `None` → a real boolean (or `None` when not-checked) |
| `orchestration._UNFIXABLE` | `+ "color_fidelity"` |
| `naturalness.evaluate` | five flags → two |
| `naturalness` constants | `CAST_MAX`/`SAT_MAX`/`FLAT_SPREAD` deleted; `CAST_DELTA_MAX`/`SAT_DELTA_MAX`/`CONTRAST_DROP_MAX` added |
| `episode_qc` evidence | `naturalness` gains `source` and `delta` |

`CheckSpec` is a config-spec, so the rename is atomic: no alias, no deprecation
window. A `report.json` written before this slice keeps its old `color_fidelity`
detail shape and nothing reads it back (`Report.from_dict` has no production
caller).

---

## §8 Proofs

1. **`colordiff` against published CIEDE2000 reference pairs.** The Sharma et
   al. test set has known ΔE00 values; a subset pins the implementation
   independently of this codebase.
2. **Real-ffmpeg: a graded clip against its own source.** Build a segment and a
   deliberately damaged grade of it, and assert `evaluate` crosses the bar —
   with a **control** that an undamaged re-encode does not.
3. **The grey case that used to vanish.** A near-grey subject pair returns a
   number, not `not-checked`.
4. **The escalation seam.** A `color_fidelity` failure escalates on the first
   attempt with reason `grade-damage`, and `adjust_reframe_params` is never
   asked to fix it. Mutating `_UNFIXABLE` back must turn this red.
5. **`naturalness.evaluate_delta` on the run's own measured ranges**, each of
   the three bars with a value either side.
6. **`episode_qc.pack` writes `source` and `delta`** into the evidence packet,
   over a real two-file pair.

---

## §9 Honest limits

### §9.1 The blocking bar is one shoot wide — and rendered by an older engine

Every number in §0.4 comes from eight episodes of one shoot, one grade, and
damage that was *simulated* by transforming the delivered pixels at the
magnitudes the retro recorded — not from a second real incident. The whole gap
between the healthy maximum (4.29) and the tightest damage (5.04) is **0.75
units, 17% of the healthy maximum**. A different camera, a different scene
palette or a stronger house grade could move either edge past it.

**The sharper limitation is not "one shoot" but "one engine".** Those artifacts
were produced *before* the segment-range contract (R2.0/R2.3, landed
2026-08-27, released as 0.3.1), which added
`scale=in_range=auto:out_range=tv` + `-color_range tv` to `extract` and with it
fixed the `lutyuv` range bug. That slice's own measurement: the tone transfer
missed by **8.5 codes** on a full-range source and **1.5** on a limited one, and
**67 of the reference pool's 99 clips are full-range**.

The two sides of this sensor are not affected equally. The *source* side should
read near-identically either way — a range tag is honoured on decode, and
0.3.1's own measured quantization price is at most 1 code. The *delivered* side
of every pc-sourced episode moves by up to the transfer error the range fix
removed, roughly **7 codes**. Measured through this branch's own `colordiff`, a
uniform 7-code shift on a mid tone is **2.10–2.65 dE00** (2.48 on §0's own ep2
box mean `(75, 85, 99)`) — **more than three times** the entire 0.75-unit
healthy-to-damage gap the bar sits in.

**5.0 does not move on this observation.** The number stands until something
re-measures it; shifting a calibrated bar on an inference would replace a
measured number with a guessed one. What would settle it: re-run
`check_episode._colour_fidelity` over the eight episodes **re-extracted under
the 0.3.1 contract**, and compare their per-episode medians against the
0.89–4.29 recorded in §0.4. That is folded into the second-calibration-shoot
row in the backlog.

### §9.2 The gate cannot tell a strong grade from damage

ΔE00 measures magnitude, not intent. A deliberate mood grade heavy enough to
move the subject 5 units will trip it, correctly reporting that the subject
moved 5 units. This is exactly why R2.6 needs a before/after it must beat rather
than a threshold it must clear, and why that row is not closed by this one. The
live control in §2.4 shows a +10.6-code authored tone pair landing at 1.44, so
the headroom is real — but it is headroom, not immunity.

### §9.3 The mean of a region is not a colour in the frame

`box_mean` averages RGB over a box before converting to Lab. The grade is
non-linear, so the mean of the graded pixels is not the grade of the mean. The
sensor detects gross movement and will under-report a grade that pushes two
halves of a box in opposite directions.

### §9.4 The advisory bars are drawn against a contaminated baseline

§0.6: the negative class for desaturation and lifted blacks is the reel the
operator complained about. `SAT_DELTA_MAX` and `CONTRAST_DROP_MAX` are set to
have zero false positives against footage that already carries the defect, so
they are, if anything, too loose. They will need re-deriving on the first run
graded after R1.1 splits pace from look.

### §9.5 Five samples is still five samples

The median of five box means across a two-to-six-second episode is a coarse
description of what a grade did over time. A grade that damages only the
episode's opening second can hide behind four healthy samples.

### §9.6 None of this says the reel looks good

Both sensors answer "did the colour move, and where". Neither answers "is this
the right colour". CP3 and the QC judge remain the first place anyone looks.

### §9.7 `evaluate_delta` compares two different regions

`episode_qc._source_reading` measures the **whole segment frame**;
`episode_qc.pack` measures the whole **delivered** frame, which is a reframed
crop of it — often 9:16 out of 16:9. The difference between those two regions
is not the grade, and `evaluate_delta` cannot tell the two apart.

This branch's own test measures the magnitude:
`tests/integration/test_episode_qc.py` records **source contrast 0.0 against
graded contrast 123.6 with no grade applied at all**, against a
`CONTRAST_DROP_MAX` of 20.0. It reads `False` only because `contrast_drop` is
signed and this particular crop happened to *gain* contrast. Invert the
geometry — a crop landing on flat sky out of a contrasty source — and
`contrast_drop` fires on a crop.

This is the same class of error §0.5 diagnosed in `CAST_MAX`: **a bar measuring
something other than what it names.** §0.5's own healthy range already reaches
+24.50 in the gain direction and attributes it to "gained contrast
legitimately", which this measurement cannot distinguish from the crop. The fix
— measure the source over the episode's crop rect rather than the whole frame —
is a backlog row (§10), not a change here. Meanwhile the flag stays advisory,
which is the only reason this is a limitation and not a live defect.

### §9.8 The two colour sensors do not share a baseline

`check_episode` compares against the file reframe actually consumed, which for
a **stabilized** episode is `<project_dir>/stabilized.mp4`
(`scripts/process_episode.py:279`), not the raw segment.
`episode_qc._source_reading` always reads `ep.manifest["segment"]`. So on a
stabilized episode the blocking sensor and the advisory one are describing
changes from two different starting points. `probe.source_for` already
resolves this correctly and routing `episode_qc` through it would fix it —
a backlog row (§10).

### §9.9 The five fractions agree by coincidence

`check_episode.SAMPLE_FRACS = (0.1, 0.3, 0.5, 0.7, 0.9)` and
`episode_qc.SENSOR_FRAMES = 5` at `(k+0.5)/5` produce identical fractions, of
different quantities (route span vs clip duration), with **nothing in code
tying them**. Either can move without the other noticing. This design does not
depend on the agreement; it is recorded here so no later reader mistakes it for
a contract.

---

## §10 Deferred

Each of these gets a backlog row:

1. **Re-derive the advisory bars on a clean run** (§9.4) — after R1.1, when a
   reel exists whose "washed out" is not baked into the baseline.
2. **Sample count and placement** (§9.5) — five fractions is a guess; with the
   batched decode the marginal cost of more is one PNG each, so the right
   number is measurable rather than argued.
3. **A second calibration shoot for the blocking bar** (§9.1).
4. **Correct R2.2's own numbers in the backlog** (§0.1) — the row quotes the
   stale artifact set, and the retro's `colour_cast` count is 6 of 8, not 7.
5. **`blown_highlights` / `crushed_blacks` remain uncalibrated** (§6) — one
   data point and zero respectively.

Added by the whole-branch review, after the eight tasks landed:

6. **The colour-convergence stop names the wrong remedy** (§3.1) — a
   `build_reel` pull that trips the gate routes to `edit-plan` and an EDL
   colour block that is unchanged and correct. It needs a finding of its own
   (`colour-correction-rejected`, routed to `match-grade`), and a stop report
   that says a clip was rewritten. **There is no test for this interaction at
   all** — that is part of the same row.
7. **`probe grade` cannot predict the gate that stops the run** (§5) — it
   already resolves the pre-grade side via `source_for`, so a `color_fidelity`
   reading over the probe's own frames against `src` is wiring, not new
   machinery.
8. **`evaluate_delta` measures the source over the whole frame and the grade
   over a crop** (§9.7) — measure the source over the episode's crop rect.
9. **The two colour sensors disagree on the baseline for a stabilized
   episode** (§9.8) — route `episode_qc._source_reading` through
   `probe.source_for`.
10. **`check_episode._last_sampleable_t`'s one-frame clamp may be too tight**
    — `assembly._LAST_FRAME_MARGIN_S` records a measured case where a probed
    container duration overstated the true last frame by a **full frame**,
    which is exactly the margin this clamp leaves. A suspicion, not a
    confirmed defect: it is only reachable when the route span exceeds the
    clip, and it fails loud rather than silently. Measure before moving it.
