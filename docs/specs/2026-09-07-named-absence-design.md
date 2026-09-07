# Named absence — a measurement survives a pass (design)

**Backlog rows:** R7.1 (P1), R7.2 (P1), R6.1 (P2) — all three from
[the first real run's retro](../retro/2026-08-25-first-real-run.md) R6–R7.

**One sentence:** three reports each collapse a *distinguishable absence* into
something that reads as a normal reading, and each throws away a number it had
already computed; this slice makes the absence a state and the measurement
durable. Nothing new blocks.

---

## §0 What the run's own artifacts say

Every number below was read from `/Users/serg/Downloads/untitled folder/`, the
2026-08 run, read-only. Two of the three rows had a premise that needed
correcting, and one finding is new.

### §0.1 R7.1 is confirmed, and the artifact is worse than the row says

The shipped `EDL.json`:

```json
"outro": {"reel_dur": 34.93, "line": null, "fade": 0.3, "tail": 0.0,
          "rung": "unchanged", "moved": 0.0, "brief_len": 45.0, "need": 0.0}
```

`rung: "unchanged"` is written from **four** places, and all four produce a
byte-identical record:

| where | cause |
|---|---|
| `edit_plan.py:326` | `not music.bars` — there is no bar grid, so no fit ever ran |
| `edit_plan.py:334` | the closing episode carries a ramp |
| `edit_plan.py:340` | the closing episode's source is not in `FOOTAGE.json` |
| `outro.fit_outro`'s final `return unchanged` | the ladder ran and no candidate line was legal |

The last one is the only case in which the sentence
`check_reel.py:372` prints — *"the fit chose no bar line (rung 'unchanged')"* —
is true. All four `MUSIC*.json` on disk carry `bars: []`, so the cause that
fired on the real run is the first, and the report asserted the fourth.

`EDL.md` hedges rather than asserts: *"none that the closing shot has room for,
**or** no bar grid at all"* (`edl.py:482`). A disjunction, not a fact — and the
producer knew which.

### §0.2 The row's "22% short, escalated nowhere" — half of it already exists

Correcting the row: `EDL.md` **does** state the distance from the brief, in
every rung, and did so on the real run (line 29):

```
- **line** – · **fade** 0.30s · **reel** 34.93s (+0.00s) · -10.07s vs the brief's 45.0s
```

That half landed with
[deferred-measurements](2026-08-18-deferred-measurements-design.md) §1.
What is missing is not the sentence. It is that **nothing measures the reel
against the brief at any gate**, because:

> `check_reel`'s `length` check compares the master against
> `spec.target_dur`, which `edl_to_reel:266` takes from `EDL.target_dur`, which
> `edit_plan._back_edge_target` computed as `min(realized, spine.target_dur)` —
> a number derived from the cut itself.

The length gate is therefore a **tautology with respect to the brief**: the reel
is checked against the length it happened to be. `SPEC.length_s = 45.0` is
compared to nothing that decides anything. −10.07s (−22.4%) passed every gate
because there was nothing for it to fail.

### §0.3 R7.2's "inverted" is true — of a different file

The row reads: *"`pacing` reported a perfect fit — `dev: 0.0` on all 8 slots —
while the cut rhythm inverted the music's energy curve."* Measured, that
sentence mixes two artifacts, and both halves are real:

| spine | slots | measured | Spearman ρ(dur, energy) | max dev |
|---|--:|--:|--:|--:|
| `PACING.json` — the reel that shipped | 8 | 8/8 | **−0.571** | 0.0000 |
| `pacing_A/PACING.json` — the 18-episode cut it was cut down from | 18 | 18/18 | **+0.509** | 0.0185 |
| `pacing_B/PACING.json` — the same cut, a second window | 18 | 14/18 | +0.484 | 7.1413 |

`dev: 0.0` on all 8 belongs to the shipped spine, whose ρ is **−0.571** — the
*correct* direction, shorter shots where the music is louder. The inversion
belongs to `pacing_A`, the earlier cut, at **+0.509**. The complaint is real;
the two facts come from different files, and no report puts either number
anywhere.

This is what makes the row's own framing exactly right for the wrong reason:
`dev` and `fits` are the entire summary the stage emits, and the two cuts above
are indistinguishable by them (both `fits`, both dev ≈ 0) while differing by
1.08 in the only statistic that describes the thing the operator complained
about.

### §0.4 New: `energy: 0.5` is a sentinel that reads as a measurement

`pacing.fit_spine`:

```python
span = [n[k] for k, b in enumerate(beats) if pos <= b < pos + dur] or [0.5]
e = fmean(span)
```

When **no beat falls inside a slot**, its energy becomes the literal constant
0.5, and `_kind` then labels the slot from that constant. On disk, in
`pacing_B/PACING.json`:

```
slot 0: beats_in=0 -> energy 0.500 kind 'hook'    dev 7.1413
slot 1: beats_in=0 -> energy 0.500 kind 'build'
slot 2: beats_in=0 -> energy 0.500 kind 'build'
slot 3: beats_in=0 -> energy 0.500 kind 'build'
```

`MUSIC_B.json`'s first beat is at **9.7387s**; those four slots end at 7.99s.
Nothing in `Slot`, `PACING.json` or `PACING.md` distinguishes a measured 0.5
from this. `_beat_energy` min-max normalizes to [0, 1] within the track, so a
genuine 0.500 is possible and would be indistinguishable.

**The two halves of this slice are coupled by a number.** `pacing_B`'s Pearson
correlation over all 18 slots is **+0.276**; over the 14 measured ones it is
**+0.160**. The hole in the report biases the statistic that is supposed to
describe the report — which is why §5 and §6 are one slice and not two.

### §0.5 R6.1 is confirmed, and the failure side is also wrong

`check_reel.py:333`:

```python
if dist < spec.variety_min:
    var_ok = False
    fails.append(...)
    worst = dist if worst is None else min(worst, dist)
checks["variety"] = CheckResult("variety", var_ok,
                                {"min_distance": worst} if worst is not None else {})
```

Two defects, not one. A **pass** reports `{}` — the distances were all computed
and none survives. A **fail** reports the minimum over the *failing* pairs
only, never the global minimum. There is no path on which the report says how
close the nearest pair came to `variety_min`.

---

## §1 The shape

**An absence is a state, not a blank; a measurement survives a pass.**

Each of the three reports already computes the number a reader needs, and then
either discards it (R6.1, R7.2) or emits it under a description that is false
for the case at hand (R7.1). This slice adds no sensor and no threshold. Every
change is: *carry what was measured, and name what was not.*

**Explicitly out of scope**, decided with the owner:

- No new blocking gate anywhere. `brief_length` (§4) is advisory.
- No energy-aware ranking of candidate music windows in `build_pacing` — the
  ranking stays `(fit.level_n if fit.fits else 0, -fit.worst)`. The A/B pair on
  disk does not discriminate the two criteria (A wins on both), so any weighting
  between grid quality and energy agreement would be typed, not measured. Filed
  in §7.
- No calibrated threshold on the energy agreement number. It is reported.

---

## §2 `variety` reports what it measured (R6.1)

`min_distance` becomes the **global** minimum across all adjacent pairs, present
in the detail on every path where the check ran at all, beside the pair it came
from and the bar it was judged against:

```json
"variety": {"passed": true,
            "detail": {"min_distance": 14, "pair": [3, 4], "min": 8}}
```

`"min"` is `spec.variety_min`, so a reader can see the margin without holding
the spec. The single-episode arm keeps its existing
`{"status": "n/a", "reason": "single episode"}`.

### §2.1 The failure path is byte-identical, and that is provable

If any pair fails, its distance is `< variety_min`; the global minimum is
`≤` that distance, so the global minimum is itself a failing pair. Minimum-over-
failing-pairs and global-minimum therefore coincide **whenever a failure
exists**, and they differ only when none does.

Two consequences, both load-bearing for the plan:

1. No delivered reel's `overall` can move. The change is observable only in
   `report.json`'s detail on a passing check.
2. **The pass path is the only thing a test can discriminate.** A mutation that
   reverts §2 is invisible to any test built on a failing reel. The test that
   guards this must assert the detail of a *passing* `variety`, and the design
   says so here so the plan cannot accidentally pin it on the fail side.

---

## §3 `outro` names which absence it is (R7.1a)

`OutroFit` gains one field:

```python
cause: str = ""   # WHY this fit is "unchanged". A closed vocabulary, validated
                  # like `rung`. "" = not recorded (an EDL written before this
                  # slice), never "no reason".
```

```python
CAUSES = ("no-bars", "no-episodes", "ramped-closer",
          "closer-not-in-footage", "no-reachable-line")
```

| `cause` | producer | meaning |
|---|---|---|
| `"no-bars"` | `edit_plan._apply_outro`, the `not music.bars` arm | there is no bar grid; **the fit never ran** |
| `"no-episodes"` | `_apply_outro`, the `not episodes` arm | the cut is empty, so there is no closing shot to move |
| `"ramped-closer"` | `_apply_outro`, the ramp arm | the closing episode's `play_dur()` is non-linear in `dur`, so the fit is skipped by design |
| `"closer-not-in-footage"` | `_apply_outro`, the missing-clip arm | the closing shot's room cannot be measured |
| `"no-reachable-line"` | `outro.fit_outro`'s final `return unchanged` | **the fit ran**, and no candidate line was legal |
| `""` | — | not recorded (pre-slice artifact) |

`"no-episodes"` is the fifth cause and it was found while writing the plan, not
while writing this section: `_apply_outro`'s guard is
`if not episodes or not music.bars`, one branch for two unrelated absences. It is
unreachable through `build_edl` today, and lumping it under `"no-bars"` would
re-create in miniature exactly the collapse this field exists to end. One tuple
entry, one ternary.

One wording table, `outro.CAUSE_WHY`, maps each cause (including `""`) to the
clause both readers print. Two readers writing their own sentences for the same
five states is the shape that drifts.

`fit_outro`'s own `if not bars: return unchanged` sets `"no-bars"` as well — the
same fact, so the pure function is self-consistent no matter which caller
reaches it. `_apply_outro` short-circuits before calling it on the real path, so
that branch is reached only by a direct call, and it must still answer
correctly.

**Implementation note the plan must not miss:** `fit_outro` builds ONE
`unchanged` object at the top and returns it from two places that now carry
different causes. The two must be constructed separately (or the second derived
with `dataclasses.replace`); reusing the shared object silently labels a
`"no-reachable-line"` as `"no-bars"` — the exact confusion this field exists to
end.

Validation, in `__post_init__` beside the existing `rung` check:

- `rung != "unchanged"` ⟹ `cause == ""`. A successful fit has no absence to name,
  and a `cause` on a `"gap"` would be a contradiction the record should not be
  able to hold.
- `rung == "unchanged"` ⟹ `cause in CAUSES or cause == ""`. `""` stays legal so
  a pre-slice `EDL.json` loads; every producer in this tree sets a real one.

Three readers stop lying:

- **`check_reel.py:371`** — the `"n/a"` reason becomes cause-specific, read from
  `CAUSE_WHY`, and the detail gains a machine-readable `"cause"` key beside it.
  Only `"no-reachable-line"` keeps today's meaning; every other cause now says the
  fit did not run and why. `""` reads as not-recorded — never a guess.
- **`edl.py:482`** — the `EDL.md` disjunction becomes the cause.
- **`edit_plan`'s `_log` lines** already distinguish all four; they stay as they
  are and now agree with the durable record instead of being the only place it
  existed.

### §3.1 Why the cause lives on `OutroFit` and not in `edit_plan`

Two of the four causes never call `fit_outro` at all — `_apply_outro` builds
`unchanged` itself — and two come from inside the pure function. A field on the
record is the only carrier both producers can reach, and `OutroFit` is already
the thing whose docstring says *"a bare duration cannot say why it is that
length."* This is that sentence's other half.

---

## §4 `brief_length` — the one length not derived from the cut (R7.1b)

### §4.1 The pipe

`SPEC.length_s` already reaches `edit_plan.build_edl` as `brief_len` and stops
there, spent only as `fit_outro`'s tie-breaker. It becomes a first-class
carrier, following `EDL.platform`'s precedent exactly (copied from `Spec` by
`edit_plan`, spent by `edl_to_reel` on the manifest, read by `check_reel`):

```
Spec.length_s
  -> build_edl(brief_len=)   [already]
  -> EDL.brief_len           [new]
  -> ReelManifest.brief_len  [new]
  -> check_reel.run(brief_len=)  [new]
```

`OutroFit.brief_len` **stays**. It is not a duplicate of `EDL.brief_len` in
kind: `fit_outro` is a pure function and the field is its record of the
tie-breaker it was handed, exactly as `OutroFit.need` records the requirement it
applied. On the `edit_plan` path one writer sets both from one source, so they
cannot drift; a hand-authored SP1 `EDL.json` may legitimately carry an outro
block from elsewhere, and then the two saying different things is information,
not corruption.

### §4.2 The check

A new **advisory** row, added to `models._ADVISORY_CHECKS` and to
`check_reel._UNCHECKED` (for the no-brief case, so a missing brief reads as
not-checked and never as "on target"):

```json
"brief_length": {"passed": false,
                 "detail": {"brief": 45.0, "delivered": 34.93,
                            "gap": -10.07, "gap_frac": -0.224,
                            "budget": 1.5, "advisory": true}}
```

`gap` is signed (negative = short). `gap_frac` is `gap / brief`.

`EDL.brief_len` validates as a positive number or `None` — the same contract
`Spec.length_s` already enforces at the source. That is what makes `gap_frac`'s
division safe without a second guard at the check, and it means a corrupt value
fails where it was accepted rather than as a `ZeroDivisionError` two stages
later.

### §4.3 `passed` borrows a budget rather than inventing a threshold

`passed = abs(gap) <= _LENGTH_TOL + spec.length_retime_max` — on the defaults,
`0.5 + 1.0 = 1.5s`.

That sum is not a new constant and not a guess: it is **exactly what the
pipeline already declares it will absorb without saying anything.**
`_LENGTH_TOL` is the length gate's own band and `length_retime_max` is the
further shortfall `build_reel` will silently re-time the target by
(`reel_orchestration`'s `retime` rung). Beyond their sum, the system's own rules
say a length difference stops being quiet. Applying that budget to
brief-versus-delivered is an **analogy**, not an identity — §7 records it as
one.

The borrowed budget is deliberately applied **symmetrically**, though the budget
it is borrowed from is not. `reel_orchestration._shortfall` absorbs a shortfall
only; an over-length reel always escalates, and the reason is mechanical and
local — the stem is cut from a fixed music fragment and `mix.mix` refuses
`dur > music.duration`, so re-timing UP would trade a clean escalate for a hard
raise at the mixer. That reason does not transfer: a reel longer than its brief
is not blocked by anything, it is merely not the reel that was asked for. So
`brief_length` treats +10s and −10s alike, and the asymmetry stays where its
cause is.

On the real run: `|−10.07| > 1.5` → `passed: false`. This is the first thing in
the tree that says so.

---

## §5 `Slot` says when its energy was not measured (R7.2a)

```python
beats_in: int = -1   # beats of the analysed window that fall inside this slot's
                     # span. 0 => `energy` is fit_spine's `or [0.5]` fallback and
                     # `kind` is a label computed from it, not a measurement.
                     # -1 => not recorded (a PACING.json written before this slice).
```

Validated as a non-negative int or exactly `-1`.

**`energy` and `kind` do not change.** `kind` cannot carry this state — slot 0 of
`pacing_B` is simultaneously unmeasured and positionally `"hook"`, and `Spine`'s
own invariant requires `slots[0].kind == "hook"`. `energy: None` would break the
`0.0 <= energy <= 1.0` contract and every consumer of it. The fact rides in its
own field; the **readers** change:

- `Spine.to_markdown` prints `–` in the `energy` and `kind` cells when
  `beats_in == 0`, and appends one line under the table naming how many slots
  were unmeasured and what that means. `beats_in == -1` prints the values as
  today, because a pre-slice artifact genuinely does not know.
- The agreement number (§6) is computed over `beats_in > 0` slots only.

`Slot.from_dict` defaults the key rather than requiring it, matching
`Spine.music_digest` and `OutroFit.need`: an old `PACING.json` loads, and reads
as not-recorded rather than as zero.

---

## §6 The energy-agreement number (R7.2b)

A pure function in `lib/pacing.py`, stdlib only like the rest of the module:

```python
def energy_agreement(slots) -> tuple[float | None, int, int, str]:
    """Spearman rho between slot duration and slot energy, over MEASURED slots.

    Returns (rho, used, total, reason). rho is None when it cannot be computed,
    and `reason` then names why — never a silent 0.0."""
```

`statistics.correlation(durs, energies, method="ranked")` — Spearman, so eight
points are ranked rather than fitted, and no numpy enters a module whose
docstring promises bit-exactness.

`rho is None` with a named reason when: fewer than 3 measured slots, or either
series is constant (`correlation` raises `StatisticsError` on a constant input,
so this is a refusal the function must own rather than let escape).

Rendered into `_report`'s header, beside the existing `Verdict` line:

```
- **Verdict:** fits
- **Energy agreement:** -0.57 (Spearman rho over 8 of 8 measured slots)
  Negative = shorter shots where the music is louder. A DESCRIPTION, not a
  verdict — no threshold has been measured (design 2026-09-07 §7).
```

**Not stored on `Spine`.** It is a pure function of the slots, and a stored copy
would be a golden re-pin plus a second thing to keep in step for a derived
number. `PACING.md` is what a reader of this stage reads.

---

## §7 The honest half

- **The agreement number has no calibrated threshold, and N is 8–18 slots.** It
  separates the run's own two cuts (−0.571 against +0.509) and says nothing
  about where a line would go. One shoot, one song, two cuts. It is reported
  precisely because nobody can defend a bar for it yet.
- **`beats_in` fixes the report, not the fit.** A music window whose beats begin
  at 9.74s is still accepted: `pacing_B` slot 0 carries `dev: 7.14` and
  `build_pacing` ranks windows on grid quality alone. Filed, not fixed — and
  the sibling row (energy-aware window ranking) is filed with it, because the
  A/B pair on disk agrees on both criteria and so cannot weigh them.
- **`brief_length`'s budget is an analogy.** `_LENGTH_TOL + length_retime_max`
  is declared for delivered-versus-target and is being applied to
  delivered-versus-brief. It is the least-invented number available, not a
  measured answer to how far a reel may drift from its brief — and it is
  applied symmetrically where the original is one-sided, for the reason in
  §4.3.
- **`brief_length` will be red often, and that is the finding.** No stage aims
  at `SPEC.length_s`: `edit_plan` targets the fitted scenario's own length, and
  the brief reaches the machinery only as `fit_outro`'s tie-breaker. A row that
  is frequently false here is reporting a real gap in the conveyor, not
  misfiring — but it does mean this check earns its keep as a number, not as a
  verdict, and if it proves pure noise on the next run the honest move is to
  demote `passed` to `None`, not to widen the budget.
- **§2's change is untestable on the failure path by construction** (§2.1). A
  guard must be written against a passing `variety`, and no mutation of the
  fail path can be caught by this slice's own tests because there is nothing
  there to catch.
- **Nothing machine-checks the principle.** "A measurement survives a pass"
  binds the three checks this slice touches and no future one. It is a
  convention, like the backlog rule it sits beside, and it is worth saying that
  out loud rather than implying a gate exists.
- **`cause` is set by the producers in this tree only.** A hand-authored
  `EDL.json` through the SP1 front door can carry `rung: "unchanged"` with
  `cause: ""` forever, and that reads correctly as not-recorded. No refusal was
  added, for the same reason the front door has none elsewhere.

---

## §8 What this does not touch

`check_reel`'s `overall`, every blocking gate, `reel_orchestration`'s routing,
the reprocess loop, every ffmpeg stage, and `fit_spine`'s arithmetic. The only
behaviour a delivered reel can notice is one additional advisory row in
`report.json`.
