# Engine dataclass-hardening + resolution/aspect-agnostic — Design

**Date:** 2026-07-08
**Status:** approved (brainstorming) → next: writing-plans
**Scope:** Plan 1 of a two-plan split. Plan 2 (`project-init` purpose→aspect) is previewed here (§D) but **not** built by this design.

## Context

A fresh-eyes read of the shipped engine (core plan Tasks 0–11 + the process-episode
orchestrator slice, 124 tests green on `main`) found that the architecture and
fail-loud discipline are strong, but a cluster of latent bugs all live at the
**integration seams** — signal the manifest carries (`composition`/`motion`) that
the orchestrator never forwards to the engine — plus two silent-accept holes in
`validate()`. Separately, the user wants the skill to be **general-purpose video
processing**: no hardcoded delivery aspect (currently 9:16) and no hardcoded
delivery resolution (currently 1080×1920) — both must become choices, and the
engine must impose zero limits. Finally, the scripts parse inputs ad-hoc
(`--canvas 9:16`.split(":"), `--src-dims 1920x1080`, raw route/report dicts); the
user wants typed dataclasses that own their parsing and **raise** on bad state, so
errors surface at construction, not three layers deep.

## Goals

1. **Full dataclass model** — typed wire-contracts (`RoutePoint`, `TrackMeta`,
   `CropPath`, `CheckResult`, `Report`) and config-specs (`TrackSpec`,
   `ReframeSpec`, `CheckSpec`, `StoryboardSpec`) replace every ad-hoc `.split()`
   and raw dict. JSON stays the on-disk wire format via `from_dict`/`to_dict`.
2. **Fix the 5 breakage risks + 2 holes** (§B) found in review, woven into the
   retype of each script (each file touched once, not per-fix).
3. **Resolution- and aspect-agnostic engine** (§C) — the engine accepts any
   `canvas` and any delivery target; zero hardcoded 9:16 / 1080×1920.

## Non-goals (Plan 2 / later)

- `project-init` and the purpose→aspect/quality question, `project.json`, canvas
  inheritance (§D) — belongs to the **ingestion** plan.
- Layouts (`fit-blur`/insert/split/pan), vidstab, optical-flow degradation —
  the **reframe-extensions** plan.
- Descriptor continuity re-match / cast.json — ingestion plan.
- Router cap-3 fan-out — router plan.

## Validation principle (reconciles "raise on error" with §4.1)

- **`Manifest` (user input) stays soft:** `validate()` returns `list[problems]`
  → `needs_input`. Manifest ambiguity is a **question**, not a crash (§4.1
  ask-before-start). Holes #F/#G below land here as *problems*, not exceptions.
- **Everything below a validated manifest is hard:** the config-specs validate in
  `__post_init__` and **raise** with a remedy. Bad *external* input → clean
  `needs_input`; a desync/bug *inside* → immediate exception. One soft seam at the
  user boundary; hard types everywhere within.

---

## A. Data model — `scripts/lib/models.py`

New single module for the cross-script contracts. `from_dict`/`to_dict` preserve
the **exact current JSON schema** (hard constraint — the golden fixture and all
on-disk artifacts must stay byte-compatible).

### Wire-contracts

- **`RoutePoint(t, x, y, w, h: float)`** — one tracked frame. `from_dict`/`to_dict`
  round-trip `{"t","x","y","w","h"}`. A route on disk stays a JSON list; helpers
  `route_from_json(path) -> list[RoutePoint]` and `route_to_json(points, path)`.
- **`TrackMeta(hero: int|None, ambiguous: bool, intent: str, features: dict)`** —
  the `.meta.json` sidecar. Round-trips the current schema.
- **`CropPath(xs: list[int])`** — the per-frame crop-x path (current `path.json`
  is a bare list). `from_json`/`to_json`; `len(path) == len(route)` is enforced
  where consumed (unchanged invariant).
- **`CheckResult(name: str, passed: bool | None, detail: dict)`** — one check.
  `passed=None` = editorial/not-implemented (no pass semantics). `to_dict`:
  `passed is None` → `detail` verbatim (carries `{"status": ...}`); else
  `{**detail, "pass": passed}`. Preserves the existing per-check shape.
- **`Report(checks: dict[str, CheckResult], attempt: int)`** —
  `overall` (property) = `all(c.passed is not False for c in checks.values())`;
  `fail_reasons` (property) = `[name for name,c ... if c.passed is False]`.
  `to_dict` reproduces `{"checks", "overall", "attempt", "fail_reasons"}` exactly.

### Config-specs (validate in `__post_init__`, raise on bad)

- **`TrackSpec(src, model="yolo11n-seg.pt", seed_bbox=None, intent="action", fps=None)`**
  — `model in MODELS`; `intent in {"action","static"}`; `seed_bbox` is a 4-tuple
  or `None`; else `ValueError` with remedy.
- **`Delivery(mode, value)`** — `mode in {"native","short_edge","long_edge","exact"}`;
  `value` matches mode (`int` for edges, `(w,h)` for exact, `None` for native).
  Method `dims(crop_w, crop_h) -> (out_w, out_h)` returns **even** delivery dims
  (§C). Upscale only when explicitly requested.
- **`ReframeSpec(composition, grid, canvas, color_means, delivery, max_speed=750.0, stabilize=False)`**
  — enum/positivity checks; `color_means` = 3 positive numbers; `stabilize is False`
  (a `True` here is a bug — manifest already refused it → raise).
- **`CheckSpec(composition, grid, target_dur, canvas, src_dims, attempt=1, black_floor=6.0, black_rel=0.35)`**
  — enum/positivity checks; `target_dur > 0`.
- **`StoryboardSpec(n=6, grids=("thirds",), marks=None)`** — `n >= 1`; grids valid.

Scripts (`track`, `reframe`, `check_episode`, `storyboard`, `process_episode`)
take a spec / return a dataclass instead of positional primitives and raw dicts.
CLI `__main__` blocks build the spec from argparse and let `__post_init__` raise.

---

## B. Fixes (woven into the retype)

### #1 — hero `intent` always "action" (wrong person on static/center)

`process_episode` never passes `intent`; `track.build_route` defaults `"action"`
(displacement-weighted), so a still hero loses to a moving bystander on
`center`/`static` episodes. **Fix:** the orchestrator derives `intent` from
**manifest-only** signal and puts it in `TrackSpec`. (It must be manifest-only:
`intent` scores which track becomes the hero *during* `build_route`, before any
hero route exists to `classify()` — so observed motion is unavailable here.)

- `composition == "center"` **or** `manifest.motion` ∈ {`static`, `head-on`}
  → `intent = "static"`;
- `manifest.motion` lateral, **or** motion `None` (infer) with a `lead`/`break`
  composition → `intent = "action"` (the lateral-action default).

Acceptance: a `center` manifest tracks with `intent="static"`; a pure unit test on
the derivation (manifest → intent) + an orchestrator test asserting the
`TrackSpec.intent` passed to `build_route`.

### #2 — `lead` over non-lateral motion burns 3 retries → escalate

A `lead` manifest whose route `classify()`s as static/head-on/diagonal gets a
**centered** crop (`compute_path`) but `on_line` checks the lead line → fails every
attempt; retries only tighten centering → 3 wasted YOLO/ffmpeg passes → misleading
`max-retries`. **Fix:** catch it **before** the loop. `detect_contradictions` gains
the `composition` argument; if `composition == "lead"` and `classify(route)` is not
lateral → finding `composition-motion-mismatch` → `stop_and_report` (no reframe).
Message: "lead composition needs lateral motion; the tracker sees <type> — set
`center`, or fix the window." Acceptance: lead + non-lateral route →
`stop_and_report`, reframe not called.

### #3 — `black_frames` false-positive on dark footage

Current absolute `luma > 8` rejects legit night/fade shots (→ `_UNFIXABLE`
escalate). **Fix:** relative gate. Sample a mid-clip luma reference (median of N interior
frames, default 3, sampled evenly across the clip body); a boundary frame fails
only if it is **both** near-black
(`< black_floor`, default 6) **and** far below the clip body (`< black_rel ×
median`, default 0.35). A real seek-landmine black-cut (boundary ≈ 0, body normal)
fails; a uniformly dark clip (boundary ≈ body) passes. Both thresholds are
`CheckSpec` fields. Acceptance: synthetic dark clip passes; black-boundary clip
fails.

### #4 — hero marker misaligned from its frames

`marks_from_route_path` samples by **route index**; `storyboard._sample_frames`
samples by **output time** (fps filter) — on a route with tracking gaps the green
circle drifts off subject / onto the wrong frame. **Fix:** the marks are computed
at the **same times** the frames are sampled. `storyboard` owns the sample times
`t_k`; marks are `interpolate(route, path, t_k)` — `fx = (x(t_k) − cropx(t_k))/crop_w`,
`fy = y(t_k)/src_h`. Route `t` is authoritative (already carried per point).
Acceptance: on a gappy synthetic route, each mark lands within tolerance of its
frame's true subject position.

### #5 — `_simplify` recursion depth (latent)

Douglas-Peucker is pure recursion; a long segment (>~1000 frames) can
`RecursionError` before the eps-cap engages. **Fix:** iterative DP with an explicit
stack. Acceptance: a 5000-point synthetic path simplifies without error.

### #F — canvas not enforced / not general (hole)

Engine special-cases `canvas == (9,16)` → 1080×1920 and otherwise scales to
crop-native. **Fix:** delete the special case; delivery dims come from
`Delivery.dims()` (§C), any aspect. `validate()` no longer needs a 9:16 assumption.

### #G — `color_means` positivity unchecked (hole)

`validate()` checks `len == 3` but not positivity; a `0`/negative mean passes and
crashes late in `color.gain`. **Fix:** add positivity to `Manifest.validate()`
(soft → `needs_input`), and `ReframeSpec.__post_init__` also guards it (hard, since
by then the manifest passed). Acceptance: `color_means=[0,122,137]` → `needs_input`
problem, no ffmpeg run.

---

## C. Resolution- and aspect-agnostic delivery

`crop_size` is already aspect-general; only the output dims were hardcoded. The
engine now imposes **zero** delivery limits — `ReframeSpec.delivery` decides:

- **`native`** (default when unset) — deliver the crop at its own pixels
  (even-adjusted), no upscale, no quality loss. A 4K source's 9:16 crop delivers
  at 1215×2160.
- **`short_edge = N`** / **`long_edge = N`** — scale so that edge is N, the other
  derived from the crop aspect, both rounded even.
- **`exact = (W, H)`** — explicit dims (must be even).

`Delivery.dims(crop_w, crop_h)` is pure and unit-tested across aspects
((9,16)→1080×1920 via `short_edge=1080`; (16,9)→1920×1080; (1,1)→1080×1080;
(4,5)→1080×1350) and native. No `1080`/`1920`/`9:16` literal survives in the
engine.

---

## D. Plan 2 preview — `project-init` (NOT built here)

`project-init` asks two things once, at project start, and writes `project.json`:

- **purpose → aspect:** reel/shorts/tiktok = 9:16, youtube/landscape = 16:9,
  square/feed = 1:1, cinema = 21:9, custom = explicit `w:h`.
- **quality → delivery:** reel-1080 (`short_edge=1080`), landscape-4K
  (`long_edge=2160`), source-native (`native`), or explicit.

`project.json` carries `{canvas, delivery}` (later also `cast.json`). Episode
manifests **inherit** both; a manifest field overrides per-episode (rare). This is
where "learn what the video is for" lives. Plan 1 makes the engine ready for any
`(canvas, delivery)`; Plan 2 chooses them. Belongs to the ingestion plan.

---

## E. Testing & migration

- **Byte-compat is the guardrail:** `to_dict` reproduces the current JSON schema
  exactly, so route/path/report/meta on disk and the **golden real-ffmpeg
  fixture** stay green without regenerating fixtures.
- **Golden pins `delivery`:** the golden manifest sets an explicit `delivery`
  (e.g. `exact=(1080,1920)`) so its numeric checks stay deterministic regardless
  of the `native` default. `on_line`/`continuity` are computed in route/geometry
  space and are robust to delivery-pixel changes.
- **Tests migrate to dataclasses:** routes built as `list[RoutePoint]`, reports
  read as `Report`. Existing test intent preserved.
- **New tests:** intent derivation; `composition-motion-mismatch` stop-and-report;
  dark-vs-black relative gate (both directions); marker-at-sample-time on a gappy
  route; iterative DP on a 5000-point path; `Delivery.dims` across aspects +
  native; `color_means` positivity → `needs_input`; every spec's `__post_init__`
  raise path.

## F. Risks / tuned defaults (call out, easy to change)

- **#3 thresholds** `black_floor=6`, `black_rel=0.35` — defaults in `CheckSpec`,
  tunable; the *shape* (relative gate) is the fix, the numbers are calibration.
- **Delivery default `native`** — chosen so the general-purpose engine never
  silently upscales; Plan 2's project-init will usually set an explicit target.
- **Single `models.py`** — one module for all contracts + specs; split later only
  if it grows unwieldy.

## Acceptance criteria (whole plan)

1. No raw `.split()` input parsing or bare route/report dicts remain in `scripts/`.
2. Every config-spec raises (with remedy) on invalid construction; the manifest
   gate stays soft (`needs_input`).
3. All 5 review bugs and both holes are fixed, each with a test.
4. The engine contains no hardcoded aspect or resolution; `Delivery` drives dims.
5. Golden real-ffmpeg fixture green; full suite green (existing intent preserved).
