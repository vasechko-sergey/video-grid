# Reel-final editorial checks — the §5.13 mechanical-editorial trio (design)

**Related:** montage §5.13 `reel-final-check` (the gate this advances); the
§5.13 `safe_zones` slice (2026-07-16 — the sibling this mirrors exactly: same
route-geometry projection, same advisory policy, same `check_reel` wiring); the
`path.meta.json` sidecar + `lib/geometry.marks_at_times` (the projection reused
and extended); §7 layouts (`crop × rect × filler` — what `pad_bars` and
`transitions` read off `PathMeta`).

**Intent:** build the three still-mechanical checks the §5.13 editorial half
enumerates — **`key_action`** (the tracked subject is not clipped by the frame
edge), **`pad_bars`** (a non-`fill` layout's filler bars are well-formed), and
**`transitions`** (adjacent episodes' layouts don't jump jarringly). All three
are **advisory**, mirroring `safe_zones`: measured and reported into the
`ReelReport`, but excluded from `overall` and emitting no `ReelFailure`, so
`reel_orchestration` / loop-2 are untouched. This is **Slice A** of closing
§5.13; the **agent editorial review** (Slice B — does the reel deliver SPEC's
idea/mood/hook/ending/spine?) is a separate follow-on. §5.13's gate is "both
parts green", so the stage **stays ◐ until Slice B lands** — this slice completes
the mechanical enumeration under it, not the stage. Pipeline tally is unchanged:
**14 ✅ · 1 ◐ · 1 ❌**.

## Scope decisions (locked in brainstorming)

- **Two slices, this is A.** The §5.13 editorial half splits by kind: three
  computable checks (this slice, TDD-Python in `check_reel`) and the agent
  review (Slice B, a prose SKILL + light wiring, modelled on
  `requesting-code-review`). Each is its own spec → plan → implementation cycle,
  matching the repo's one-plan-per-subsystem convention. A never depends on B;
  B consumes A's advisory signals as review inputs.
- **All three advisory.** They join `_ADVISORY_CHECKS` (today `("beat",
  "safe_zones")`): reported, never blocking `overall`, and **never** a
  `ReelFailure`. Rationale, per check: `key_action` is route-geometry (an
  estimate, not pixel truth — a false positive must not refuse a good reel; and
  a reprocess reuses the **frozen** route so it could not move the subject
  anyway — the same actuator-less argument that made `safe_zones` advisory);
  `pad_bars` is a structural sidecar invariant whose only violation is a
  reframe/hand-edit bug, out-of-band from an editorial reprocess; `transitions`
  is an explicit **taste proxy** ("jarring" has no pixel truth). `next_action` /
  `reel_orchestration` / `build_reel` are untouched — **zero blast radius on
  loop-2**.
- **`pad_bars` is structural, from the sidecar — not pixel-CV.** The check reads
  `PathMeta.rect_px` / `out_dims` / `mode` only; it never decodes a frame. This
  matches the repo pattern (route/sidecar geometry, not a runtime detector) and
  is exact and cheap. A pixel-variance "the bars look clean" check was considered
  and rejected for this slice (extra decode + it is itself an estimate).
- **`transitions` reads `PathMeta`, not frame signals.** The spec wording is
  "**layout** transitions not jarring", so the signal is the layout delta across
  a cut (content-rect coverage + centre + `mode`), read off the two episodes'
  `PathMeta`. A phash/luma frame-signal proxy was rejected: it flags good
  contrasty cuts, overlaps the existing hard `color_across_cuts` gate, and
  misses the "layout" the spec names.
- **No new inputs, no new artifacts.** All three consume the per-episode
  `geometry` tuples `check_reel` **already** takes for `safe_zones`
  (`route.json` + `path.json` + `path.meta.json`) plus `durations`. No new CLI
  flag, no new sidecar. The `ReelReport` grows three advisory keys.

## §1 Architecture

Per-episode sidecars already on disk after loop-1 (`process_episode` writes them
into each `epdir`), and already loaded by `check_reel` for `safe_zones`:

| Sidecar | Contract | Carries |
|---------|----------|---------|
| `route.json` | `list[RoutePoint]` | tracked subject bbox `(t,x,y,w,h)` in **source** px |
| `path.json` | `CropPath` | per-frame crop-window left-x in source px |
| `path.meta.json` | `PathMeta` | crop `w/h/y`, `src_dims`, `canvas`, `out_dims`, `rect_px`, `mode`, `freedom` |

The subject→output-frame projection is `lib.geometry.marks_at_times(route,
path, meta, times)` — it returns the subject **centre** `(fx, fy)` in output
fractions. This slice **extends** the projection to the subject's **bounding box
corners** and adds a new pure-decision module for the three checks. `check_reel`
threads the sidecars it already has.

```
lib/geometry.marks_at_times(route, path, meta, times)      → [(fx, fy)]         (exists — centre)
lib/geometry.extent_at_times(route, path, meta, times)     → [(fx0,fy0,fx1,fy1)] (new — bbox corners)
                    │
                    ▼
lib/reel_final.evaluate_key_action(extents_per_ep, clip_tol)      → (bool, dict)   ┐
lib/reel_final.evaluate_pad_bars(metas, bar_symmetry_tol)         → (bool, dict)   ├─ three pure cores
lib/reel_final.evaluate_transitions(metas, layout_jump_max)       → (bool, dict)   ┘
                    │
                    ▼
scripts/check_reel.run(...)  → ReelReport.checks += {key_action, pad_bars, transitions}   (all advisory)
```

`lib/reel_final.py` is a **new** module (keeps `safezones.py` single-purpose;
groups the three siblings). It imports only `lib.geometry` /`lib.models` — no
driver import, pure and unit-testable.

## §2 The three checks

### 2.1 `key_action` — subject not clipped by the frame edge

`RoutePoint` carries the subject bbox `(x, y, w, h)` in **source** px.
`geometry.extent_at_times` projects the two corners `(x − w/2, y − h/2)` and
`(x + w/2, y + h/2)` through the **same** `rect_px` / `crop_w` / `crop_h` /
`crop_y` composite math `marks_at_times` uses, sampled at the same
`_SAFE_SAMPLES` times as `safe_zones`. `evaluate_key_action` flags an episode
when any projected corner falls outside `[0, 1]` by more than `clip_tol` (a
close-up legitimately touches the edge; only a real overshoot is a finding).
Report the worst overshoot and its episode index.

Distinct from `safe_zones`: that projects the **centre** against a platform
UI-chrome margin table; this projects the **extent** against the frame edge
`[0,1]`. Different region, different failure mode; both advisory.

```
detail (fail): {"worst_episode": i, "overshoot": 0.13, "edge": "right", "advisory": True}
detail (pass): {"episodes": n, "advisory": True}
```

### 2.2 `pad_bars` — filler bars well-formed (structural, sidecar-only)

For each episode's `PathMeta`:

- `mode == "fill"` ⇒ `rect_px` is the whole output, there are **no bars** ⇒ this
  episode is n/a (skipped).
- otherwise the content rect `rect_px = (rx, ry, rw, rh)` must lie inside
  `out_dims = (ow, oh)`: `rx ≥ 0`, `ry ≥ 0`, `rx + rw ≤ ow`, `ry + rh ≤ oh` (a
  rect poking outside the frame is a reframe/hand-edit bug), **and** the bars
  must be symmetric within `bar_symmetry_tol` (a canvas fraction): left bar
  `rx` ≈ right bar `ow − (rx + rw)`, top bar `ry` ≈ bottom bar `oh − (ry + rh)`.

`evaluate_pad_bars` returns the worst offender across episodes. If **every**
episode is `fill` (no bars anywhere), the result is n/a (`passed=None`, reason
"no non-fill layout").

```
detail (fail): {"worst_episode": i, "issue": "rect_overflow"|"asymmetric",
                "rect_px": [...], "out_dims": [...], "advisory": True}
```

### 2.3 `transitions` — layout not jarring across a cut

For each adjacent episode pair `(i, i+1)` (reel episodes share the canvas, so
their `out_dims` match and fractions are comparable), a layout-jump score over
their `PathMeta`:

```
area_i        = (rw_i * rh_i) / (ow * oh)          # content coverage fraction
centre_i      = ((rx_i + rw_i/2)/ow, (ry_i + rh_i/2)/oh)
jump = |area_i − area_{i+1}|
     + hypot(centre_i − centre_{i+1})
     + (LAYOUT_MODE_PENALTY if mode_i != mode_{i+1} else 0.0)
```

Flag the cut when `jump > layout_jump_max`. `LAYOUT_MODE_PENALTY` (a module
constant, starting `0.5`) makes a `fill → insert` swap count as a real jump even
when the rect areas happen to align. Report the worst cut. n/a when `< 2`
episodes (like `variety` / `color_across_cuts`). The threshold and penalty are
**unverified first cuts** (advisory — a wrong value over/under-flags but never
refuses a reel); tuning is deferred to real reels (§11 of the montage spec's
"unverified constants" convention).

```
detail (fail): {"worst_cut": i, "jump": 0.71, "modes": ["fill","insert"], "advisory": True}
```

## §3 Wiring — `check_reel` + `ReelCheckSpec`

`ReelCheckSpec` (the config-spec) grows three advisory thresholds, validated in
`__post_init__` (positive; `clip_tol` / `bar_symmetry_tol` fractions in
`[0, 0.5)`):

| Field | Meaning | First-cut default |
|-------|---------|-------------------|
| `clip_tol` | frame-edge overshoot tolerance (fraction) | `0.02` |
| `bar_symmetry_tol` | left/right, top/bottom bar mismatch (fraction) | `0.02` |
| `layout_jump_max` | max un-flagged layout-jump score | `0.6` |

In `check_reel.run`, inside the **existing** `if geometry is not None:` block
that already builds the per-episode route/path/meta objects for `safe_zones`,
reuse those objects to also compute the trio and set three `CheckResult`s:

- `key_action` — from `extent_at_times` per episode → `evaluate_key_action`.
- `pad_bars` — from the `PathMeta` list → `evaluate_pad_bars`.
- `transitions` — from the `PathMeta` list → `evaluate_transitions` (n/a if `<2`).

`_ADVISORY_CHECKS` becomes `("beat", "safe_zones", "key_action", "pad_bars",
"transitions")` — so `overall` is provably unchanged (it already ignores
advisory checks). `_UNCHECKED` gains three "not checked — no per-episode
geometry supplied" entries for the silent path, so a geometry-less reel reports
`passed=None` for each rather than a silent pass, exactly as `safe_zones` does.

**No CLI change.** The three checks ride the same `--geometry` inputs
`build_reel` / `edl_to_reel` already thread; drivers need no edit (they pass
`geometry` through today).

## §4 Testing (TDD)

Pure-core unit tests (the bulk — deterministic geometry, no ffmpeg):

- `extent_at_times`: a centred bbox projects to corners straddling the centre
  mark; a bbox pushed to the source edge projects a corner outside `[0,1]`.
- `evaluate_key_action`: clean (all corners inside) → pass; one corner past
  `clip_tol` → fail with the right `worst_episode` / `edge`; a corner inside
  `clip_tol` of the edge → still pass.
- `evaluate_pad_bars`: symmetric fit-blur → pass; `mode=fill` → n/a;
  rect poking past `out_dims` → `rect_overflow`; lopsided bars past tol →
  `asymmetric`; all-fill reel → n/a.
- `evaluate_transitions`: two identical layouts → pass (jump 0); `fill → insert`
  → fail (the area delta `fill`≈1.0 → card `<1` **plus** the mode penalty clears
  the threshold together — the penalty nudges, it does not flag alone at these
  defaults); a big rect-area jump → fail; single episode → n/a.

Integration (`check_reel`): feed a small multi-episode `geometry` set and assert
the three keys are present, carry the expected `advisory: True`, and that
`overall` is **True even when one of them is False** (the load-bearing advisory
proof). Reuse the geometry the existing `safe_zones` integration test already
builds; a real-ffmpeg golden is **not** needed (these are pure geometry over
sidecars the golden already produces — assert on the report, not on pixels).

## §5 Out of scope (boundaries)

- **Slice B — the agent editorial review.** SPEC-idea / mood / hook / ending /
  spine judgement, findings → fix loop, `using-montage` CP3 wiring. Its own
  spec. This slice's three advisory signals become inputs it can cite.
- **`overall` / `reel_orchestration` / `build_reel` / `deliver` / loop-2** —
  untouched. Advisory by construction.
- **No auto-fix actuator.** Like `safe_zones`, a flagged reel is surfaced to the
  human/agent reviewer; nothing re-reframes on these signals (the route is
  frozen; the layout is the edit-plan's decision).
- **Trend flavor** ("classic base **and** trend flavor") — belongs to Slice B's
  agent judgement and has no source of truth until §5.4 `trend-scan` (YAGNI,
  unbuilt); not this slice.

## §6 Docs impact

- `pipeline-map.md` — 5.13 row: note the three mechanical editorial checks
  landed; stage **stays ◐** (Slice B pending). Tally unchanged.
- `build-status.md` — a bullet under the reel-final work; the "editorial half"
  remaining list drops `key action not clipped` / `pad bars clean` /
  `transitions not jarring`, leaving the agent review.
- `CLAUDE.md` Quick Reference — a row for this design + its plan.
- The montage design §5.13 / line-562 enumeration — mark the three as built
  (advisory), agent review still open.
