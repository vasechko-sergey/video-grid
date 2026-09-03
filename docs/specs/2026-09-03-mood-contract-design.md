# The mood contract — a mood word declares only what it commands

**Backlog:** P1 rows R1.1, R1.2, R1.3 (all three from
[the first real run's retro](../retro/2026-08-25-first-real-run.md) §R1).
**Version:** 0.8.0 — new contract fields and a `CACHE_VERSION` bump.

One word in the brief — `SPEC.mood` — today reaches four different places.
Two of them it commands honestly (`shot_mix` gates variety, `look` is
authorable and says where it came from). Two it does not: it silently orders
a colour grade nobody asked for, and it declares a length band it has no
power over. This slice makes the word's reach match its authority.

---

## §0 · What was measured, and what it overturned

Every number below comes from the 2026-06 run's own artifacts, read
read-only. Three of the five overturned a premise this slice started with.

### §0.1 · The pool sits on the FLOOR, not the ceiling

1508 windows carved from 99 clips:

| | count | share |
|---|---:|---:|
| at the 1.2 s floor (`≤ 1.21`) | 1099 | **72.9%** |
| at the 4.0 s ceiling (`≥ 3.99`) | 3 | **0.2%** |

Median window **1.20 s** — the floor exactly. 92.1% of all windows fall in
`[1, 2)`.

The cause is `carve._tight_unit`, which builds a window of width exactly
`win_min` centred on each activity peak. Every peak yields two candidates —
a tight one and a lead-in one — and the tight one is `win_min` by
construction, so the floor is not a bound the carver approaches, it is a
value the carver *emits*.

**This overturned the queued premise.** R1.2 reads "the length band needs a
floor, a wider ceiling"; the backlog row and this design's own first draft
both attacked the ceiling. The ceiling is reached by three windows in
fifteen hundred.

### §0.2 · The footage had the room

Scene spans (scene-cut to scene-cut), same 99 clips: **92.9%** run longer
than 4.0 s, median span **15.98 s**, longest **44.5 s**. Nothing about this
footage forced short windows. The carver chose them.

### §0.3 · The delivered reel already exceeds the ceiling

The run's eight delivered episodes: 4.51 / 5.27 / 5.80 / 3.35 / 3.69 /
5.78 / 2.63 / 2.00 s. Median **4.10**, mean **4.13**, longest **5.80**.

**Five of eight are longer than `WIN_MAX = 4.0`** — `edit_plan`'s span
merge (`"window": [i, j]`, 2026-07-26) joins adjacent windows and is used
routinely, not exceptionally. So the ceiling does not bind the shipped cut
in any sense: it is already routed around, by a mechanism built for exactly
that.

This is the asymmetry the whole slice turns on: **windows can be joined but
never split.** A mood that wants longer shots is always satisfiable. A mood
that wants shots shorter than the carved floor is not satisfiable at all.

### §0.4 · The preset band was BELOW what the cut produced

`nostalgic` declares `asl` (2.0, 4.0). The realized average shot length was
**4.37 s** — above its own declared ceiling, recorded in `EDL.variety` and
acted on by nothing (R1.3).

So the operator's "pull toward two seconds" is not visible in the delivered
reel, whose median shot is 4.10 s. Whatever produced that impression, the
`asl` band did not: it never bound anything, and the cut overshot it.

### §0.5 · The band is not in the cache key

`intake_cache.clip_key` keys on `(path, sample_fps, model, proxy_long_side,
reid_model, CACHE_VERSION)`. `carve_windows` runs inside `_process_clip`
(`intake.py:410`) — cached Phase 1. `WIN_MIN`/`WIN_MAX` are module
constants read at `intake.py:91`.

Change either constant today and every cached clip still answers with
boundaries carved under the old band, silently. This is the one live defect
in the area, and it is the only reason part B survives §0.1.

---

## §1 · The rule

**A mood word may command only what it can be held to.**

Concretely: anything the preset decides must be either (a) overridable by an
explicit authored value, or (b) checked against what the pipeline can
actually deliver — and a preset field that is neither must stop being
declared. `look` already satisfies (a). `shot_mix` already satisfies (b).
`tone_bias` satisfies neither, and `asl` satisfies neither.

---

## §2 · A — `tone_bias` becomes authorable (R1.1)

`Spec` gains `tone_bias: tuple | None = None`, three luma displacements
(p5, p50, p95) validated exactly as `MoodPreset.tone_bias` is.

`match_grade.conduct` reads the authored value when it is not `None`, and
the preset's otherwise:

```python
# today's line, unchanged, as the fallback arm:
#   preset.tone_bias if preset is not None and preset.name != "balanced" else (0, 0, 0)
bias = spec.tone_bias if spec.tone_bias is not None else <today's line>
```

`None` and `(0, 0, 0)` are **different**: `None` means "not authored, take
the preset's taste", `(0, 0, 0)` means "no displacement" — the way to say
*this mood, but leave my colour alone*. A default of `(0, 0, 0)` would make
the second inexpressible, which is the shape `look` already got right
(`moodpreset.BALANCED`'s own comment carries the same reasoning).

`MATCH.md` names the source in its mood line — `from SPEC.tone_bias` or
`from the nostalgic preset`. Today it prints the displacement without ever
saying where it came from, which is the "silently" half of R1.1.

**Unchanged:** `balanced` still imposes nothing, a run without `--spec`
still authors what it authored before, and the `mood-bias-ineffective`
report line still fires on a displacement the footage had no room for.

---

## §3 · B — the window band becomes an intake parameter (R1.2)

**Scope, stated honestly:** this part does not make shots longer. §0.1 and
§0.3 rule that out — the ceiling binds three windows in 1508 and the shipped
cut already exceeds it. What this part fixes is §0.5: a band that can be
changed at all, and that cannot be changed *silently*.

`WIN_MIN, WIN_MAX` become `DEFAULT_BAND = (1.2, 4.0)`. The band flows as a
parameter through the one path that reads it:

```
intake(…, band)  →  _process_clip(…, band)  →  carve_windows(…, band)
                 →  carve.units_for_span(…, win_min, win_max)
```

`carve.units_for_span` already takes the band as arguments — the module was
built this way deliberately ("a lib module must not depend on a driver",
`carve.py:4`), so the plumbing stops at `intake`.

CLI gains `--win-min` / `--win-max`, defaulting to `DEFAULT_BAND`, so
nothing about a default run changes.

**The band joins `intake_cache.clip_key`.** A different band is a cache
MISS, not silently stale boundaries. `CACHE_VERSION` 8→9 so the reason is
recorded rather than inferred from a key that happens to differ.

`Footage` gains `band: tuple | None` — what was actually carved, written
beside the clips, so a downstream consumer reads the band instead of
assuming the constant.

**The price, named:** the first intake after this slice re-scans the whole
pool, because the old cache entries carry a key without the band term. On
the reference pool that is 99 clips. This is the cost of the key being
honest, and it is paid once.

---

## §4 · C — the two bands are reconciled before the cut (R1.3)

There are now two bands: what the mood wants (`MoodPreset.asl`) and what
was carved (`Footage.band`). `write_edit_plan` reconciles them before the
variety gate.

**Only the lower bound is checkable.** §0.3's asymmetry decides this:
`edit_plan` can join adjacent windows, so a preset ceiling above the carved
ceiling is always satisfiable and must NOT be refused — `moody` (2.5, 5.0)
against a carved (1.2, 4.0) is legal, and the run's own 5.80 s episode
proves it. But no stage splits a window, so a preset floor below the carved
floor asks for a shot length that does not exist anywhere in
`FOOTAGE.json`:

```
preset.asl[0] < footage.band[0]   →  refuse
```

The refusal names all three numbers and the remedies: re-scan with a lower
`--win-min`, choose a different mood, or drop `--spec`.

**A missing band is said out loud.** A `FOOTAGE.json` written before this
slice carries no `band`, so the reconciliation cannot run. It reports
`not-checked` with the reason, exactly as `check_reel` does for a check it
could not perform — never a silent green.

**Honest scope of the check.** At the current defaults it fires on nothing:
carved floor 1.2 against preset floors of 1.2 / 1.5 / 2.0 / 2.5. It becomes
live the moment an operator raises `--win-min`, which is precisely the knob
§3 introduces — the check exists to catch a contradiction the new parameter
makes possible, not one the shipped defaults contain.

---

## §5 · Contracts

| Contract | Change |
|---|---|
| `Spec` | `+ tone_bias: tuple \| None = None` |
| `Footage` | `+ band: tuple \| None = None` |
| `intake` | `DEFAULT_BAND`; `band` parameter; `--win-min` / `--win-max` |
| `intake_cache` | `clip_key` gains the band; `CACHE_VERSION` 8→9 |
| `MoodPreset` | unchanged — `asl` stays, and now has a consumer |

No stage's ffmpeg changes and no render moves — the band decides window
BOUNDARIES, not any encode. On a default run two artifacts change:
`FOOTAGE.json` gains one field, and every `.intake_cache/*/clip.json` is
rewritten under the new key (§3's one-time re-scan).

---

## §6 · Proofs

1. **`tone_bias` authored beats the preset** — a `Spec` carrying an explicit
   triple against a `nostalgic` brief conducts to the authored displacement,
   and `MATCH.md` says `from SPEC.tone_bias`.
2. **An explicit zero disables** — `[0, 0, 0]` conducts to the unbiased
   median, byte-identical to a run with no `--spec` at all. The control that
   must not move: `None` still takes the preset's taste.
3. **A changed band misses the cache** — two `intake` runs over one clip,
   same everything but the band, produce two cache entries and different
   window boundaries. The control: the same band twice hits the cache and
   returns byte-identical windows.
4. **A default run is unchanged** — `intake` with no band flags produces the
   windows the current code produces, and the golden fixture does not move.
5. **The floor contradiction refuses** — a preset floor below the carved
   floor stops `write_edit_plan` with all three numbers named. The control:
   a preset ceiling ABOVE the carved ceiling passes, because span merge
   reaches it (§0.3).
6. **A band-less `FOOTAGE.json` reports not-checked** — and the reason names
   the artifact's age, not a pass.

---

## §7 · Honest limits

- **No number here was measured against taste.** 1.2/4.0 stay the default.
  This slice makes the band selectable and impossible to change silently; it
  does not make it *right*. R1.2's second half — "the right numbers are
  unknown and genre-dependent; they must be measured, not typed" — is still
  open, and stays in the backlog after this lands.
- **The operator's "pull toward two seconds" is not explained by this
  slice.** §0.4 measured the delivered reel at a 4.10 s median shot with the
  band overshot, so whatever produced that impression, neither the `asl`
  band nor `WIN_MAX` did. A separate backlog row carries the question.
- **The reconciliation proves a premise, never a result.** It can show "this
  mood wants shots the footage does not contain". It cannot show that the
  shots the cut chose suit the mood — the realized `asl` is still reported
  and still refused by nothing, which is the deliberate reading of R1.3's
  "either it gates or it stops declaring a band": it now declares something
  that is checked, at the only edge where checking is sound.
- **`tone_bias` is reel-level**, like `look`. A per-episode override stays
  in P4 by the same argument the look one does.
- **The check is unreachable at shipped defaults** (§4), so its first real
  exercise is an operator raising `--win-min`. Until then it is proven only
  by its tests.

---

## §8 · Deferred — these get backlog rows

1. Measure the band against real footage and genre (R1.2's second half).
2. Explain the "pull toward two seconds" against the run's own drafts, since
   §0.4 rules out the two mechanisms the retro named.
3. `_tight_unit` emits a window of exactly `win_min` per peak, which is why
   72.9% of the pool is one length (§0.1). Whether a tight candidate should
   scale with the peak's own width is a carve-sensor question, untouched
   here.
4. Gate the realized `asl`, if a run ever shows the reported overshoot
   mattering (§7).
