# Retiring the reel's colour-convergence loop — design

**Backlog R2.6.** The reel retry loop's colour arm is deleted, not repaired. The
row asked for "a before/after it must beat, not a threshold it must clear"; the
measurements below say there is nothing to beat, because the check measures the
edit and the corrector moves a different quantity than the check measures. What
replaces it is a reader that can tell the difference: a `colour` axis on
`reel-review`.

---

## §0 — What was measured

Every number here comes from the preserved 2026-06 run
(`/Users/serg/Downloads/untitled folder/`), read-only, through `check_reel`'s own
primitives on the shipped artifacts: the delivered `out/REEL_v2.mp4`, the eight
delivered `out/ep{i}.mp4`, and `out/EPISODES.json`.

### §0.1 The check fires on ordinary edits

`ReelCheckSpec.color_delta_max` defaults to **12.0**. `_rgb_dist` is the **mean
absolute per-channel difference** between two frames — so 12.0 means "two frames
straddling a cut may differ by an average of 12 codes per channel".

The shipped reel's seven cuts:

| cut | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| delta | 31.8 | 22.0 | **11.0** | 20.8 | 37.5 | 51.5 | 28.5 |

**Six of seven exceed the default.** The run's own `EPISODES.json` records
`color_delta_max: 56.0` — the operator raised the ceiling 4.7x, to just above the
worst cut. That is not a tuning; it is the only available way to switch the check
off.

The reason is structural. Two frames straddling a cut belong to **two different
shots**. They differ because the edit put different things next to each other —
which is what a cut is for. Nothing in a whole-frame mean separates "these two
shots show different content" from "these two episodes were graded differently".

### §0.2 The corrector optimises a different quantity than the check measures

The check fails on `delta = _rgb_dist(left, right)` — two frames **adjacent across
one cut**.

The correction is `median / culprit_mean`, where `culprit_mean` is the culprit
episode's whole-frame mean **at its own midpoint** and `median` is the per-channel
median of every episode's midpoint mean.

So the gate measures adjacency and the lever moves each episode toward a reel-wide
central tendency. Even granting the sensor, the loop does not optimise what the
sensor reads.

### §0.3 The pulls real footage demands are far past the fidelity budget

Midpoint means of the shipped reel, the reel median, and the per-channel ratio the
corrector would author if that episode were blamed:

| ep | midpoint mean (R,G,B) | ratio | dist to median |
|---|---|---|---|
| 0 | 70.4, 108.3, 141.0 | **1.414**, 1.035, 0.917 | 14.9 |
| 1 | 101.8, 97.5, 96.8 | 0.978, 1.150, **1.335** | 16.4 |
| 2 | 94.2, 116.2, 132.8 | 1.056, 0.964, 0.973 | 4.4 |
| 3 | 122.1, 128.2, 136.2 | 0.815, 0.874, 0.949 | 15.2 |
| 4 | 97.4, 115.0, 125.6 | 1.023, 0.974, 1.029 | 2.9 |
| 5 | 56.8, 65.8, 72.7 | **1.753, 1.703, 1.778** | 48.5 |
| 6 | 127.1, 109.1, 108.5 | **0.783**, 1.027, 1.191 | 17.1 |
| 7 | 116.3, 136.5, 155.9 | 0.856, 0.821, 0.829 | 22.6 |

(median 99.6, 112.1, 129.2)

The 2026-08-28 grade-delta slice's final review measured what a pull costs the new
blocking `color_fidelity` sensor, on ep2's own subject box mean `(75, 85, 99)`:

| pull | 1.02x | 1.05x | 1.10x | 1.10x on one channel | 1.50x |
|---|---|---|---|---|---|
| dE00 | 0.60 | 1.51 | 3.04 | 3.92 | 16.22 |

against **0.71 dE00** of headroom at the healthiest real episode
(`CheckSpec.grade_delta_max = 5.0`).

ep5 asks for **1.75x on all three channels**. `color.corrected` clamps to
`HI = 1.5`, so the loop would apply the clamp and spend roughly 16 dE00 — twenty
times the budget — and still not reach its target. And ep5 is a legitimately dark
shot (mean 57/66/73) inside a bright reel: the demand is not a colour match at
all, it is an **exposure** change that erases the tonal variation the edit chose.

This is exactly the retro's two recorded failures. Pulling a warm beach shot toward
a bluer reel median IS `median / culprit_mean` doing its job.

### §0.4 The damage is on disk, recorded, and was ignored

`work/reel/ep{0..8}/report.json` (2026-08-21) are loop-2's own outputs — nine
episode directories carrying `path.json`, `path.meta.json`, `report.json` and a
storyboard, and **no clip**, because `process_episode` writes to the episode
manifest's `out_path` and the loop overwrites the phase-1 clip in place. `ep0`
reads:

```json
"color_fidelity": {"worst_drift_deg": 175.2, "threshold": 25.0,
                   "exceeded": true, "samples": 1}
```

with `"overall": true` on the same report. The sensor saw it. It was advisory, so
the reel shipped.

The clips those reports describe no longer exist — loop-2 overwrote phase 1, and
the 2026-08-25 run overwrote again — so no before/after in bytes can be recovered.
That is a fact about this evidence, not an argument.

### §0.5 There is no threshold that separates the two cases

Follows from §0.1. A grade mismatch and a content change produce the same signal in
a whole-frame mean, so no ceiling distinguishes them: below ~52 the check fires on
this reel's ordinary cuts, above it the check never fires at all. Re-tuning cannot
help, because the sensor is wrong in kind rather than wrong in calibration.

Detecting a grade mismatch requires a **reference**: either each episode's own
source (which `color_fidelity` now measures per episode) or an authored target
(`matchgrade.common_target`). Comparing two different shots to each other is not
one.

---

## §1 The rule

**A corrector that can only damage the picture is deleted, not bounded.** The
reel-level colour check and its lever go. Reel-level colour agreement stays where
it is actually decidable: authored by `match-grade` before the render, and judged
by a reader who can separate content from grade.

---

## §2 What is deleted

**`scripts/check_reel.py`** — the `color_across_cuts` block (the `if cuts:` arm and
its `else` `n/a` arm), plus `_frame_mean`, `_channel_median` and `_rgb_dist`, whose
only callers it is. `_midpoints` **stays**: the phash variety check uses it.

Removing the key from `checks` is sufficient to remove it from `ReelReport.overall`
— that property already iterates `self.checks` and skips `_ADVISORY_CHECKS`.

**`scripts/lib/reel_orchestration.py`** — `_REPROCESS_CLASS` becomes `("black",)`;
`_correction` and `ReprocessItem.color_correct` are deleted. **The reprocess loop
itself stays** — a black hit is still a reprocess, and it is now the only one.

**`scripts/build_reel.py`** — the `cc` dict, `_compound`, and the `corrected`
import. The comment block at 176-184 documenting the colour interaction goes with
the code it describes.

**Contracts** — `ReelCheckSpec.color_delta_max` and its validation;
`ReelManifest.color_delta_max`, its validation, its `from_dict` read and its
`to_dict` write; `ReelManifest.check_spec`'s third argument.

**`scripts/edl_to_reel.py`** — the `--color-delta-max` flag and its passage through
four signatures (`process_episodes`, `assemble_reel`, `edl_to_reel`, and the
`_build_manifest` `extra` dict), plus the `--from-episodes` refusal listing it.

---

## §3 The cascade this opens

`color_correct` exists **only** for this loop. With the loop's colour arm gone, the
following are dead everywhere and are deleted in the same slice:

- `ReframeSpec.color_correct` and its validation
- `process_episode.process_episode`'s `color_correct` parameter and
  `build_reframe_spec`'s fourth argument
- `reframe.py`'s `if spec.color_correct is not None:` branch
- `color.corrected` — after those two call sites go it has none left. `color.LO`
  and `color.HI` **stay**: `color.gain` reads them.

**This dissolves two filed backlog rows — and leaves a third standing.**

`probe.py:230-245` is a long caveat explaining that `probe grade` cannot see a
`color_correct` the loop applied, and therefore renders frames the real encode will
not match. With no `color_correct`, `probe grade` is faithful **by construction** —
the caveat is deleted rather than satisfied — and with it the P3 row it points at,
which asks to record the applied `color_correct` on `PathMeta` so a re-probe can
reproduce the shipped grade. Nothing in `probe.py` changes but the docstring: it
only ever mentioned `color_correct`, never passed it.

The P2 row describing `build_reel`'s misrouted `colour-correction-rejected`
describes a state that ceases to exist: no pull, so no rejected re-render, so no
clip overwritten by a render nobody recorded, so nothing to attribute. The same
deletion removes the main trigger of `episode-qc-reprocessed`: of the two reasons
to reprocess an episode, only the black hit remains.

**The third row survives and gains weight.** "`probe grade` cannot predict the gate
that stops the run" is about `color_fidelity` being absent from `probe.json`, not
about `color_correct` — a different defect that this slice does not touch. It
matters more after this slice, not less: with the automatic corrector gone,
`probe grade` is the only way to converge a grade without a full render, and it
still cannot show the reading that would stop that render.

---

## §4 What replaces it: a `colour` axis on `reel-review`

`scripts/lib/review.py` gains two entries in two closed tuples:

```python
REVIEW_AXES   += ("colour",)          # spelled as episode_qc.QC_AXES already spells it
REVIEW_ROUTES += ("match-grade",)
```

`Finding.__post_init__` already validates membership generically, so no validation
code changes.

`skills/reel-review/reel-reviewer.md` gains one axis line beside the seven existing
ones, and its `route ∈ (...)` line gains `match-grade`.
`skills/reel-review/SKILL.md` gains a routing-map row: `match-grade` → re-run the
`match-grade` SKILL, then `edl_to_reel`.

**No new evidence is gathered.** The reviewer's packet already grabs "the hook
frame, the ending frame, and one mid-frame per episode" — the same frames it judges
composition from. Colour rides them.

**Why a reader and not a sensor.** §0.5's obstacle is that content and grade are
inseparable in a whole-frame statistic. They are not inseparable to something that
looks at the picture and knows, from `EDL.md`, what the shot is supposed to be. The
axis is ordinary: it may be `blocking` (⇒ verdict `revise`), and the human disposes,
exactly like the other seven.

---

## §5 What is NOT replaced

After this slice **no automated stage measures whether the rendered episodes agree
with each other.** Stated precisely, because each of these is easy to mistake for
coverage:

| stage | what it does | what it does not do |
|---|---|---|
| `match-grade` | measures every episode's **source** at its window midpoint, computes one common target, authors the same `tone_dst` on each deviating episode | never measures the result; agreement is authored, not verified |
| `reframe.verify_tone` | pushes a 256-step ramp through the curve, refuses a non-monotone transfer | checks the curve's **shape**, not that the target was reached |
| `color_fidelity` | median CIEDE2000, delivered vs its **own** pre-grade segment, blocking | structurally blind to whether two episodes agree |
| `episode-qc` | one judge per episode, that episode's frame strip | no cross-episode view |
| `reel-review` | now judges `colour` across the reel from stills | a judgement, not a measurement |

The hole is real, and this slice does not create it: `color_across_cuts` never
verified agreement either (§0.1-§0.2), so deleting it makes an existing hole
visible rather than opening a new one.

Closing it properly is the next slice, and it is filed: measure the grade on the
**pixels that ship**. `match-grade` runs before `edl_to_reel`, and the crop is born
inside tracking, so today `measure_profile` reads a whole source frame — its own
recorded honest limit. Reordering fixes it at no extra tracking cost (tracking
already happens exactly once per episode; `scripts/track.py` is already standalone,
`process_episode` already accepts a supplied `--route`, and `geometry._rect_at`
already resolves the rect at a time). With the target measured on the shipped crop,
`tone_arg` maps that crop's own p5/p50/p95 onto `tone_dst`, so a correct render's
delivered profile **must** land on the target — and a convergence check over three
frames per episode against one target becomes content-independent by construction.
That slice absorbs backlog R2.1 and R3.1, which are the same problem.

---

## §6 Contract changes

| contract | change | effect on existing artifacts |
|---|---|---|
| `ReelCheckSpec` | `color_delta_max` removed | a positional third argument now raises |
| `ReelManifest` | `color_delta_max` removed from the dataclass, `from_dict` and `to_dict` | an `EPISODES.json` carrying the key is **silently ignored** — `from_dict` reads named keys, so an unknown one is dropped |
| `ReframeSpec` | `color_correct` removed | a caller passing it now raises |
| `ReelReport` | `checks` no longer carries a `color_across_cuts` entry | a consumer indexing it by name raises; the repo has none outside tests |
| `edl_to_reel` CLI | `--color-delta-max` removed | argparse fails loud on an unrecognised argument |

The `EPISODES.json` case is the only silent one, and it is deliberate: the key
records a ceiling for a check that no longer exists, so ignoring it cannot mislead
about anything that still runs. It is named here because "silently ignored" is a
claim that has to be made on purpose.

---

## §7 What is edited rather than deleted

**`provenance.spec_overrides`** is generic — every dataclass field whose value
differs from a default-constructed instance's, exempting `target_dur`. It keeps
working; `color_delta_max` was merely the field four tests used as their example
(`test_provenance.py:77,108`, `test_deliver.py:220,233`,
`test_edl_to_reel.py:948-951`). They re-point at `variety_min`. The mechanism is
not touched.

**`tests/integration/test_reel_retry.py`** carries two proofs. **(A)**
"`color_correct` moves real pixels toward the target" is a proof of the deleted
feature and goes with it. **(B)** "`build_reel` wires probe → assemble → check_reel
→ deliver end-to-end on real files" is the only real-ffmpeg end-to-end proof of the
driver and **must survive**, re-driven by a reel that passes rather than by a
colour failure.

A reprocess-then-pass proof cannot honestly be rebuilt on the black arm: a black
hit that is in the source survives a clean re-encode, so the loop would exhaust
rather than converge. The reprocess path keeps the unit-level coverage it already
has in `tests/lib/test_build_reel.py`, re-pointed at black.

---

## §8 Proofs

1. **`check_reel` no longer reports the check.** A reel whose cuts differ far past
   the old default returns a report with no `color_across_cuts` key and
   `overall: true`.
2. **The reprocess loop still works for black.** `next_action` returns a
   `reprocess` for a black failure, with `ReprocessItem` carrying an index and
   nothing else.
3. **A colour failure can no longer be constructed.** `_REPROCESS_CLASS` holds only
   `"black"`, so a `ReelFailure` naming any other check routes to escalate.
4. **`ReframeSpec` refuses `color_correct`.** The keyword is gone; passing it raises
   `TypeError`.
5. **Real-ffmpeg (B) survives.** `build_reel` drives assemble → check_reel → deliver
   on real encoded clips.
6. **The reviewer contract accepts the new axis and route, and still refuses
   everything outside the tuples.** A `Finding` with `axis="colour"`,
   `route="match-grade"` round-trips; `axis="color"` (the other spelling) raises.

---

## §9 Honest limits

**§9.1 The measurement rests on one reel.** Seven cuts, eight episodes, one shoot,
one pair of cameras. §0.5's claim that no separating threshold exists is an argument
from the sensor's construction, corroborated by 6-of-7 at the default — not a survey
of footage.

**§9.2 The replacement proves that someone looked, never that the grade is right.**
Exactly like `episode-qc`'s judge and every other editorial axis. There is no
number behind it.

**§9.3 The reviewer judges colour from one frame per episode.** A single frame can
be an outlier — a wave, a cloud, a specular flash — and read as a grade shift; and
drift *within* one shot is invisible. The remedy if the axis proves noisy on a real
run is cheap and already built (`contact_sheet strip` takes any file and any range,
labels cells with absolute timestamps), which is why it is a backlog row and not
work done in advance of evidence.

**§9.4 The `colour` axis is the only one with no machine signal to cite.** `spine`
cites `PACING.json`, `mood` cites `MUSIC.json`, and Slice A gives `key_action` /
`pad_bars` / `transitions`. After this deletion colour has none. The numbers exist
— `color_fidelity` writes `delta_e`/`delta_l`/`delta_c`/`delta_h` per episode — but
they live in `build/ep{i}/report.json`, which every render wipes, and `ReelEpisode`
carries no pointer to a report. `EPISODE_QC.json` is a candidate source in a
non-wiped bucket; filed, not built here.

**§9.5 Reel-level colour is now unmeasured, by choice.** §5 states what each
remaining stage does and does not do. The claim of this slice is that removing a
sensor whose every real firing was wrong leaves the system better informed, not
worse — but it does leave it *less* instrumented, and that is the trade.

**§9.6 `reel-review` is where the axis lives, and a reel can reach delivery without
it.** The stage is required by the attested-run governance and human-gated at CP3,
which means a human decides — including deciding to ship. No waiver is added and
none is removed; the axis inherits exactly the enforcement the stage already has.

---

## §10 Deferred → backlog

| item | priority | size |
|---|---|---|
| **Grade the pixels that ship.** Track-first reordering of `edl_to_reel` phase 1, `measure_profile` over a rect, and a convergence check of three frames per episode against one common target. Absorbs R2.1 and R3.1. | P1 | L |
| **Give the reviewer more frames per episode** if the `colour` axis proves noisy — `contact_sheet strip` over each episode's span in the delivered reel. Evidence first. | P3 | S |
| **Put a per-episode grade-movement table in the reviewer's packet** so the `colour` axis can cite a number (§9.4). `EPISODE_QC.json` is the candidate source. | P3 | S |

**Dissolved, not closed** (§3) — two rows describe code this slice deletes:
`build_reel`'s misrouted `colour-correction-rejected` with its untested interaction
(P2), and recording the applied `color_correct` on `PathMeta` so a re-probe can
reproduce the shipped grade (P3).

**Explicitly NOT dissolved** — "`probe grade` cannot predict the gate that stops the
run" (P2) is about `color_fidelity` missing from `probe.json`. It survives this
slice untouched and is more load-bearing after it, since `probe grade` becomes the
only cheap way to converge a grade.
