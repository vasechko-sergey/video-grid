# Intake activity-units carving (feedback #3, slice 3a) — design

Feedback #3: intake's window carving splits a long continuous take into
**equal-interval** chunks. `_split_span` (scripts/intake.py) cuts any span longer
than `WIN_MAX` into `n = round(length / WIN_TARGET)` pieces of `length / n` — the
boundaries land at arbitrary time multiples (2.41s, 4.82s, …), attached to
nothing in the footage. The downstream code already apologises for this in
prose: `FootageClip.room_after` ("a window boundary inside a shot marks
nothing") and `window_to_episode` ("the window grid is a SCORING artifact, not
an editorial one … in-points are multiples of that arbitrary size — 2.41s on one
drone clip, the difference between cutting on a cross-step and cutting through
it"). The scenario-first slice (2026-07-24) added `start_offset` as a *workaround*
for exactly this.

This design replaces equal-interval carving with **activity-anchored units**.

## 0. Scope — 3a here, 3b next

The feature splits along a subsystem boundary (agreed with the user):

- **3a (this design): intake only.** Carving finds activity and emits units;
  each unit is directly usable as one episode.
- **3b (its own slice, deferred): `edit_plan` gains `span [i..j]`** — an episode
  that merges several adjacent units plus the connective footage between them
  ("turn + drive + turn" → one episode). 3b is out of scope here. §9 records the
  one fact 3a must respect so 3b stays cheap.

3a touches `scripts/intake.py`, a new pure `scripts/lib/carve.py`,
`scripts/lib/footage.py` (one field), and `scripts/lib/intake_cache.py`
(`CACHE_VERSION` bump). It does **not** touch `score_window`, `edit_plan`, or the
reel back half.

## 1. Why carve at all — the three purposes (load-bearing)

Carving is not "cut the clip into pieces." It serves three jobs, and the model
below is chosen because it serves all three at once:

1. **Find good moments (activity).** Today windows do *not* seek activity —
   `carve_windows` tiles (scene-cut ∪ presence-transition, then equal chunks) and
   `score_window` ranks the tiles by motion *after the fact*. Activity is sorted,
   never sought. That is the defect.
2. **Surface heroes (possibly several).** Already built and **independent of
   carving**: one YOLO-seg pass yields both the timeline and `crops_by_track`;
   `surface_crops` clusters descriptors into up to eight distinct identities →
   `cast_candidates.json` → the human names them → `cast.json`. The only gap: a
   window does not record **who is in it** (it carries `people` as a count, not
   identities). The montage is **mixed** (hero-driven *or* moment-driven, per the
   user), so this is an **annotation**, not the driver of carving.
3. **Yield editing-ready units, not a bag of activity (a story).** A cross-step
   is good; the *approach into* the cross-step plus the cross-step is better. A
   unit must have internal shape — a lead-in, then the action.

## 2. The model — a unit is an activity peak plus its lead-in

Purposes 1 and 3 converge on one idea:

> A window is a **peak of activity together with the lead-in before it**. Detect
> the peak (purpose 1); the editing unit runs from the lull *before* the peak
> through the peak (purpose 3).

Everything the user asked for falls out of this one shape:

- **activity** = the peak;
- **story** = lull → peak (approach → action);
- **overlap / merge** = a unit (3a) or a span of units (3b) covering more than one
  peak;
- **multi-scale** = two candidates on the same peak — `tight` (the action alone)
  and `lead-in` (approach + action);
- **hero thread** = the per-unit `track_ids` annotation, filtered downstream.

Peaks are found **relative to the clip** (local maxima of the activity curve), so
there is **no absolute activity threshold** to invent — critical, because no real
footage exists to tune one on (design 2026-07-20 §5, and the `SHAKY_CLIP`
precedent). Noise peaks are not gated by a magic number; they carry low `motion`,
score low, and sink under the existing `score` + `cull`.

## 3. The activity curve `a(t)`

Computed per **span** (the runs already produced by the scene-cut ∪
presence-transition boundaries in `carve_windows`), sampled at `SAMPLE_FPS`:

- **People in the span** → 2-D displacement of the primary bbox centre between
  consecutive samples. Today `_motion` uses the **x** component only; a turn or a
  cross-step has a vertical component too, so the curve uses the Euclidean
  displacement `hypot(dx, dy)`, normalised by frame width as `_motion` already
  does.
- **No people in the span** → camera motion from the vidstab per-frame
  magnitudes, resampled to `SAMPLE_FPS`. This is the *only* within-shot signal a
  drone/scenery span has — and it is exactly the "drone clip" the
  `window_to_episode` docstring named.

Presence is roughly constant **within** a span (a presence change *is* a span
boundary), so each span has a single curve source. Peaks are local maxima **inside
one span**, so the two sources are never compared on the same axis — no
cross-source scaling problem.

Caveat (pre-existing, inherited from `_motion`): the "primary" bbox is the
largest one *per sample*, so with two people the primary can flip between them
sample-to-sample and register spurious displacement. An identity-stable
per-hero curve is precisely the hero-driven carve the "mixed" decision put out of
scope (§1, purpose 2); 3a does not fix it and does not make it worse.

## 4. Peaks → units (the algorithm)

Per span `[a, b]`, length `L = b - a`, curve `c` over its samples. This replaces
`_split_span` and lives in the pure `scripts/lib/carve.py`:

- **`L < WIN_MIN`** → `[]` (too short — unchanged from today; `carve_windows`
  still keeps a single sub-`WIN_MIN` *whole clip* as one window via its existing
  `len(raw) == 1` guard).
- **`WIN_MIN ≤ L ≤ WIN_MAX`** → one unit `(a, L)` — the whole span already fits
  the band; a peak inside a short span needs no split (unchanged intent).
- **`L > WIN_MAX`** (where equal-tiling used to fire):
  1. Local maxima of `c`; greedily keep the strongest first, rejecting any within
     `WIN_MIN` of an already-kept peak → peaks `P` (by time). The `WIN_MIN` greedy
     spacing is the **only** peak regulator: close or noisy maxima are thinned by
     keeping the stronger, so no smoothing constant is invented (§9). The curve is
     **not** smoothed — on a ~3fps curve a fixed denoise kernel is both
     unvalidatable (no footage) and redundant with this spacing, since a kernel
     wide enough to merge adjacent maxima already spans more than `WIN_MIN`.
  2. **`P` empty (a flat span)** → **do not tile.** Emit **one** `WIN_MAX` unit at
     the position of maximum mean activity (slide a `WIN_MAX` window over the span,
     pick the start with the highest mean `c`). Density ∝ activity: a flat span
     yields one low-scoring candidate, not `n` filler tiles.
  3. **For each peak `p` in `P`**, emit two candidates, each clamped into
     `[WIN_MIN, WIN_MAX]` with the peak kept inside:
     - **`lead-in`**: start at the nearest local **minimum before** `p` (the lull;
       `a` if none), end at the nearest local minimum **after** `p` (the settle;
       `b` if none), then clamp to the band.
     - **`tight`**: a `WIN_MIN` window centred on `p`, clamped to the span.
  4. Drop exact-duplicate `(start, dur)` pairs before returning (a sharp isolated
     peak makes `tight` == `lead-in`; dropping the dup here saves a phash call —
     `cull` would also remove it later, by image).

The band `[WIN_MIN, WIN_MAX]` and the `WIN_MIN` peak spacing are the *only*
regulators of unit count; there is no separate density knob.

## 5. Hero annotation

`FootageWindow` gains `track_ids: list[int]` — the track ids present during the
unit. Data-flow change: `_people_timeline` must carry per-sample track ids
(today its timeline row is `(t, people_count, primary_bbox)` — the ids are
computed for `crops_by_track` and then dropped). The row becomes
`(t, people_count, primary_bbox, track_ids)`; `_build_window` unions the ids over
the unit's samples.

Names are **not** resolved at intake — a window carries ids; the id→name mapping
happens downstream through `cast.json`, exactly as hero pins already resolve
(§6.1a). Peak detection is by **overall** activity (§2), never per-hero — this is
the "mixed" choice: the annotation enables a hero thread without making carving
hero-dependent.

## 6. Ordering / data flow

The vidstab **detect** pass moves **before** carving: a people-less span's curve
(§3) needs the per-frame magnitudes *at carve time*, and today
`shake_by_window` runs the detect only after windows exist. `_process_clip`
computes the magnitudes once and feeds them to **both** the activity curve and
`shake_by_window` (which stops detecting internally and takes the magnitudes as a
parameter). One detect pass, two consumers — no measurement changes, the same
`vidstab.DETECT_ARGS` recipe (`shakiness=8`, design 2026-07-20 §5).

New `_process_clip` order: probe → scene_bounds → `_people_timeline` →
**vidstab.detect (once)** → carve (curve from timeline+mags) → `shake_by_window`
(reuses mags) → `_build_window` → phash/descriptor.

## 7. Cull and cost

`cull` is **unchanged**. It ranks by score and removes near-duplicates by the
**midpoint phash** (`DEDUP_DIST = 8`), so it is agnostic to time overlap: two
overlapping units with the *same* midpoint image collapse to one; two with
*different* midpoints (a `tight` and a `lead-in`, or two peaks) both survive —
which is the intent. All windows still land in `FOOTAGE.json`; `cull` only sets
`best`.

**Honest cost.** More units → more `_phash_at` calls (one ffmpeg seek per unit
midpoint), which partially eats slice B's parallel-scan win (#4). It is bounded:
≤ `2 × (span_len / WIN_MIN)` candidates per long span, and the exact-dup drop
(§4.5) trims the isolated-peak case. No count cap is added — a cap would be a
magic number with no footage to justify it (§9); if profiling on real footage
later shows pain, the peak spacing is the knob (raise `WIN_MIN` → `WIN_TARGET`).

## 8. Schema and cache

- `FootageWindow` gains `track_ids: list[int]` (default `[]`), validated in
  `__post_init__` (list of non-negative ints), serialised in `to_dict` and
  reconstructed in the `from_dict` path — including the `intake_cache` clip.json
  round-trip.
- `CACHE_VERSION` bumps (slice B's escape valve, cited in that design). Every old
  per-clip cache entry — carved by the equal-interval logic, without
  `track_ids` — invalidates and re-processes. No migration.

## 9. What 3a does NOT do (the honest half)

- **No `span [i..j]` merge.** Multi-peak episodes ("turn + drive + turn") are
  **3b**, in `edit_plan`. 3a keeps them cheap by one invariant it must not break:
  **units never cross a scene cut** (they are carved strictly inside a span, and
  a scene cut is a span boundary). `room_after` already stops a span at the next
  scene cut, so 3b's merge validation is already written.
- **The `score_window` blend is untouched.** Peak-anchored units carry higher
  motion by construction, so the existing weights still rank them sensibly;
  re-weighting the blend (e.g. a dedicated "peak prominence" factor) is a possible
  future tune, not 3a. One input does change: `_motion` (the per-window motion the
  blend consumes) goes from x-only to 2-D `hypot(dx, dy)` — the same dimension the
  curve gains (§3), because leaving the score 1-D while the carve is 2-D is exactly
  the split-brain the vidstab one-recipe note warns against. The blend, its
  weights, and `_dur_fit`/`_motion_fit` are unchanged; only the motion measurement
  gains a dimension, so the golden window scores re-pin (§10).
- **`start_offset` stays.** Its rationale softens (in-points are peak-anchored
  now, not arbitrary multiples), but it remains the fine-tune for shifting an
  in-point within a unit. Its docstring and `room_after`'s are updated to stop
  citing "tiling by length" as the reason windows are meaningless — they are not,
  after 3a.
- **No new tuned constant.** The carve introduces **zero** numeric knobs that
  would need footage to set. Peaks are relative local maxima; the lull/settle that
  bound a lead-in are relative curve extrema; unit count is regulated only by the
  band `[WIN_MIN, WIN_MAX]` and the `WIN_MIN` peak spacing, all of which predate
  3a. The smoothing kernel that an earlier draft carried was dropped (§4.1): it
  was unvalidatable and redundant with the greedy spacing. The one *choice* left is
  which extremum bounds a lead-in (the nearest local minimum) — a relative rule,
  not a threshold.
- **Flat-span coverage is deliberately thin.** A long flat B-roll span surfaces
  as **one** candidate (§4.2), not a tiling. If the editor needs more of it, that
  is `start_offset` (now) or a 3b span (later). "Density ∝ activity" means a dull
  take yields few windows on purpose.
- **No real footage.** Every threshold that would need footage to set is absent
  by construction; correctness is proven on synthetic curves (§10).

## 10. Testing

- **Pure `carve.py` on synthetic curves.** The whole peak→unit pipeline
  (local-maxima + greedy `WIN_MIN` spacing incl. the close-maxima rejection,
  lead-in/tight construction, band clamps with the peak kept inside, the flat-span
  max-mean fallback, the exact-dup drop) is pure over a hand-built list of floats.
  Deterministic, no ffmpeg, no footage. This is where the algorithm is pinned,
  including the mutation-style
  cases (a peak at a span edge, a plateau, two peaks `WIN_MIN`-apart, a curve that
  is monotone).
- **Real-ffmpeg integration golden.** The existing intake golden clip re-runs end
  to end (real seg + vidstab + phash); its pinned windows update to the
  activity-unit output, and the cache byte-identical-on-resume proof (slice B)
  still holds with the new `CACHE_VERSION`.
- **The equal-interval test dies.** The current `carve_windows` test pinning
  `length / n` tiling is rewritten to the new behaviour; a guard asserts a long
  synthetic take no longer produces equal-length pieces.

## 11. File-by-file change map

- **`scripts/lib/carve.py`** (new, pure): `activity_curve`, `find_peaks`,
  `units_for_span` (the §4 algorithm) + the flat-span fallback. Mirrors
  `lib/gridfit.py`.
- **`scripts/intake.py`**: `_split_span` deleted; `carve_windows` calls
  `carve.units_for_span`; `_motion` → 2-D (or a shared helper in `carve.py`);
  `_people_timeline` carries per-sample track ids; `shake_by_window` takes
  magnitudes instead of detecting; `_process_clip` reorders (§6); `_build_window`
  unions `track_ids`.
- **`scripts/lib/footage.py`**: `FootageWindow.track_ids` + validation + to/from
  dict; `room_after` docstring de-cites tiling.
- **`scripts/lib/intake_cache.py`**: `CACHE_VERSION` bump.
- **`scripts/edit_plan.py`**: `window_to_episode` docstring softens the
  `start_offset` rationale (no behaviour change).
- **Docs**: `CLAUDE.md` registry row, `docs/build-status.md`,
  `docs/pipeline-map.md`, `skills/footage-intake/SKILL.md` (units, not tiles).

## 12. Landmine watch

- **The reorder must not change the per-window shake number.** `shake_by_window`
  must average the *same* magnitudes over the *same* window frame ranges as today
  — only the *source* of the magnitudes moves (computed once, passed in). A test
  pins a window's shake unchanged across the refactor.
- **Removing tiling is the fix, not a regression.** The equal-interval branch is
  the corrupt-silently behaviour (§1); its deletion is the point. The guard test
  (§10) makes its return visible.
- **`CACHE_VERSION` bump is mandatory**, not optional — an un-bumped cache would
  silently serve equal-interval windows without `track_ids` and fail
  reconstruction or, worse, half-reconstruct.
