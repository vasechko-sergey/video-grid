# Build Status

What is built, what is next, and the external assets the build depends on.
**Update after every task** — tick the plan's checkboxes and add/adjust the
relevant bullet here in the same commit.

_Last updated: 2026-07-10._

## Done

- **Core engine — plan `docs/plans/2026-07-05-video-grid-core.md`, Tasks 0–11 ALL
  COMPLETE**, final review verdict READY (2026-07-07). 49 tests green (incl.
  golden fixture: real MVI_3739 footage @59.94fps through the full engine).
  Notable amendments beyond plan-verbatim code:
  - vidstab preflight = warning, not blocker (`07d2e68`) — homebrew-core ffmpeg
    lacks libvidstab; core never calls it; process-episode re-checks hard.
  - lib hardening (`341d059`): smooth([])→[], savgol odd-window ordering, on_line
    raises on route/path desync, gain(≤0) raises with remedy.
  - **route-gap desync fix (`a19937f`)**: crop x(t) built from route timestamps,
    not frame index — occlusion gaps no longer desync crop from video timeline;
    empty route fails loud.
  - Golden fixture as-built: window 9.083–10.668s (not lena_ride2) — diagonal
    motion means no 2.5s window in MVI_3739 classifies lateral; see plan Task 9.5.
  - **Hardening round (2026-07-07, fresh-eyes audit, 5 commits `27e3571`→`0c8c283`):**
    proc.run surfaces ffmpeg stderr; check_episode validates composition
    (+`break`=editorial-only) and uses spec-§9 boundary-luma black check; track
    drops id=None frankentracks, probes fps/dims, adds speed+border features;
    reframe caps expr knots (~80), even dims for all canvases, §6.4 Y headroom,
    loud stabilize/fps guards; storyboard hero-marks helper. **68 tests green.**
    Spec/plan/landmines synced same round.

- **process-episode orchestrator DONE (2026-07-08)** — plan
  `docs/plans/2026-07-08-process-episode-orchestrator.md`, Tasks 0–7 via strict
  subagent-driven-development. **122 tests green.** Built: `scripts/lib/manifest.py`
  (validate gate), `scripts/lib/orchestration.py` (contradiction detect +
  retry-ladder + escalation), `scripts/lib/proc.py`, `scripts/process_episode.py`
  (deterministic loop: track→reframe→storyboard→check, threads probed
  canvas/src_dims — **closes the contract note** — times stages, hero marks on
  storyboard), `SKILLS/process-episode/SKILL.md` (subagent: ask-before-start,
  editorial gate, stop-and-report). Golden fixture runs the whole orchestrator
  through real ffmpeg. Review-driven fixes: manifest null/unknown-key/model/color/
  canvas hardening, hero truthiness, centered→on_line alias, project_dir mkdir,
  hero-marks wiring. **Final whole-slice review (`5da32b2`):** verdict READY after
  one Important fix — a named/rule hero (non-tuple) silently suppressed the §6.1a
  hero-ambiguity stop-and-report while never being seeded; introduced
  `orch.is_seed_pin` (non-empty tuple), the single predicate shared by the
  ambiguity gate and the shell's `seed_bbox` gate. **124 tests green.**

- **engine dataclass-hardening DONE (2026-07-09)** — plan
  `docs/plans/2026-07-08-engine-dataclass-hardening.md` + design
  `docs/specs/2026-07-08-engine-dataclass-hardening-design.md`, Tasks 0–10 via
  strict subagent-driven-development (branch `feat/engine-hardening`, commits
  `78e0fb9`..`4509cd6`). **168 tests green incl. 3 real-ffmpeg integration tests
  (2 on the golden ride).** Built `scripts/lib/models.py` — typed wire-contracts
  (`RoutePoint`/`TrackMeta`/`CropPath`/`CheckResult`/`Report`, JSON
  schema-compatible round-trip) + config-specs (`TrackSpec`/`ReframeSpec`/
  `CheckSpec`/`StoryboardSpec`/`Delivery`) that raise on bad construction. Every
  engine script retyped onto specs; `check_episode.run` returns a `Report`,
  `track.build_route`/`reframe.reframe`/`storyboard.build` take specs.
  **Validation principle:** manifest gate stays SOFT (`validate()`→`needs_input`);
  everything below it is HARD (raises). **Fixes:** #1 hero `intent` derived from
  composition/motion (was always "action" → wrong hero on static/center); #2
  lead-over-nonlateral → `stop_and_report` before wasting reframes; #3
  `black_frames` relative gate (near-black AND < 0.35×body-median — dark footage
  no longer false-fails); #4 hero marks at frame-SAMPLE times (was route-index,
  desynced on gaps); #5 Douglas-Peucker iterative (no RecursionError on long
  routes); #F engine resolution/aspect-agnostic — `Delivery` (native/short_edge/
  long_edge/exact), no 9:16/1080×1920 hardcode; #G `color_means` positivity.
  Review-driven fixes: `CheckResult.to_dict` strips stale pass-key; `Delivery`
  guards non-positive crop + clean `from_spec` errors; specs raise `ValueError`
  (not `TypeError`) on wrong-type; `check_episode` body-luma sampling spread
  across clip (was first ~1s → `body_median`=0 defeated the gate). ~~**Known
  limitation:** the storyboard hero-marker's vertical fraction uses `y/src_h`
  (exact only when `crop_h==src_h`, i.e. 9:16-from-landscape).~~ **Resolved by
  layouts (2026-07-10)** — `marks_at_times` divides by `crop_h` and honours
  `crop_y`, both read from the sidecar.

- **project-init DONE (2026-07-09)** — plan `docs/plans/2026-07-09-project-init.md`
  + design `docs/specs/2026-07-09-project-init-design.md`, Tasks 0–4 via strict
  subagent-driven-development (branch `feat/project-init`, commits
  `af3753a`..`54dfa35`). **188 tests green incl. a real-ffmpeg native-inheritance
  golden.** The front-door that drives the aspect/resolution-agnostic engine:
  `scripts/lib/project.py` — `ProjectConfig` (raises on bad),
  `PURPOSE_CANVAS`/`QUALITY_DELIVERY` maps (**delivery defaults to `native`** — no
  silent downscale; a 1080 cap is a deliberate social opt-in), `resolve_project`,
  and `resolve_manifest` (episode inherits absent canvas/delivery, explicit
  episode value overrides, null=inherit, no mutation). `scripts/process_episode.py`
  gains `project=` (a `ProjectConfig` or a `project.json` path) applied before
  validation. `scripts/project_init.py` CLI writes `project.json`;
  `SKILLS/project-init/SKILL.md` is the one-time "what's this video for" pass.
  Review-driven: override integration test made load-bearing (21:9),
  `ProjectConfig.from_json` corrupt→ValueError-with-remedy, SKILL description fixed
  ('custom' quality is an explicit `--delivery`). **Reconciliation note:**
  `project.json` is the machine `{canvas, delivery}` subset; the fuller `SPEC.md`
  reel-brief (music/mood/hook/cast) will later populate/supersede it — no conflict.
  cast.json/SPEC.md-brief/router/footage-intake stayed out of scope.

- **layouts DONE (2026-07-10)** — plan `docs/plans/2026-07-10-layouts.md` + design
  `docs/specs/2026-07-10-layouts-design.md`, Tasks 0–12 via strict
  subagent-driven-development (branch `feat/layouts`, commits `7543d95`..`93c0a4d`).
  **284 tests green incl. 14 real-ffmpeg layout goldens.** `fit-blur` and `insert`
  ship, and `fill` still delivers exactly 404×720 on the golden ride from a
  whole-string-pinned filtergraph. Built `scripts/lib/layout.py` — `LayoutSpec`
  (in `models.py`, to avoid a `models→layout→models` cycle) resolves to a frozen
  `ResolvedLayout`, and a layout is now **three parameters** — crop (aspect+scale)
  × rect in canvas × background filler — with the named modes as presets, not code
  branches. `fill` keeps its single-`-vf` fast path; the composites emit one
  `-filter_complex` (`split` → blurred cover background, tracked crop scaled into
  the card, `overlay`). `insert` takes an **opt-in border** (`border_px`,
  `border_color`, default off), and `rect` carries three numbers, not four —
  its height is derived, so a card cannot disagree with what is inside it.
  **Two silent-corruption defects fixed, both of the same class** (a consumer
  re-deriving geometry the engine already knew): `check_episode.run` re-derived
  `crop_w` from the canvas and, under `fit-blur`, judged a composition that never
  happened (405 vs the 1280 actually cut); `storyboard.marks_at_times` mapped the
  §6.1a hero marker as a fraction of the crop, so under a composite the marker
  landed on the blurred background. Both now read one `path.meta.json` sidecar
  (`models.PathMeta`) that `reframe` writes beside `path.json`, mirroring
  `track.py`'s `route.meta.json`. `CheckSpec` **loses** `canvas`/`src_dims` —
  the value has exactly one source now, the code that did the cropping.
  **Freedom, not the layout name, decides the check:** `freedom = src_w − crop_w`,
  and at zero freedom the composition check is `editorial-only` (`passed=None`)
  rather than failed-or-silently-passed. The manifest gate refuses a `lead` whose
  crop provably has no freedom — its **honest limit** is that `crop_aspect: [16,9]`
  on 16:9 footage has the same zero freedom and is not catchable before ffprobe;
  the sidecar's `freedom` is the real safety net. Found beyond the plan: `boxblur`'s
  radius must not exceed `min(out_w,out_h)//4` (yuv420p halves the chroma plane —
  real ffmpeg dies at 64 on a 3840×200 cover); `fill`'s canvas **is** its crop and
  re-deriving it drifted 21:9-of-4K by 2px; a native canvas can explode
  (`rect_w=0.02` → 36000×64000, 2.3 Gpx) so `layout.MAX_SIDE = 8192` guards right
  after `delivery.dims`. **Final review (two reviewers + a mutation battery over
  production code, `72da96f`/`93c0a4d`):** every one of nine mutations was killed
  by a test — except one, and it was the test *named for* this plan's headline
  defect. `test_crop_w_comes_from_the_sidecar_not_the_canvas` used a zero-freedom
  fixture, where `check_episode` short-circuits to `editorial-only` and never
  reaches the `crop_w` arithmetic; it is rebuilt against an `insert` with 840px of
  freedom, where re-deriving the width drops `on_line`'s ratio from 1.0 to 0.0.
  Four error-path holes closed: a manifest that `validate()` accepted could still
  crash the orchestrator (rect overflow / border-eats-card / `MAX_SIDE` all need
  the source dims, so the soft gate cannot see them) — `process_episode` now
  resolves the layout as a **preflight** right after the probe and returns
  `needs_input`, and probes before tracking so a typo fails in ms, not after YOLO;
  the `boxblur` floor `max(2, min(w//60, ceiling))` **defeated its own ceiling**
  when the ceiling was 0 or 1, so the ceiling is applied last (no real canvas
  changes: golden fit-blur 21, insert 13, wide cover 50); `PathMeta.from_json`
  raised a bare `JSONDecodeError` on the truncated sidecar its own message names;
  and two raises named remedies their caller could not act on (an `exact` delivery
  told to "pin the output", a `fit-blur` told to shrink a `rect` it forbids).
  **Fixed (2026-07-10):** `check_episode._black_frames_check` returned `pass=True`
  on a *uniformly* black clip — `worst < black_rel * ref` is `0 < 0` — now the
  relative gate is OR'd with an absolute body-black floor (`ref < black_floor`);
  real-ffmpeg all-black test in `test_verify.py`, design §12 logged. The layout
  goldens still measure boundary luma against their own (stricter) absolute bar —
  left as-is, they guard the render pipeline, not the check. The
  `Delivery("exact", …)` even-dims hole filed here is **now closed**: it was the
  one mode that skipped `geometry.even()`, so an odd side reached `scale=` and
  libx264 failed cryptic; `__post_init__` raises a remedy-carrying `ValueError`
  (exact never silently rounds — 405x721 → "use (404, 720) or (406, 722)"), and
  `from_spec("exact:WxH")` refuses identically. design §12 logged.

- **docs registry + coding standards (2026-07-09)** — specs moved to
  [`docs/specs/`](./spec/); anna-auth-style standards adopted
  ([coding-standards.md](./coding-standards.md), [testing-guide.md](./testing-guide.md),
  [development-workflow.md](./development-workflow.md)); `CLAUDE.md` became a
  registry; scripts brought into compliance (full type hints, imports-at-top).

## Next action

- **cast.json ingestion** (montage design §6.1a / §-line 287): hero registry — one
  interactive naming pass from surfaced crops → name + seg-mask appearance
  descriptor; descriptor wiring into manifests; unlocks cast-name hero pins (today
  `orch.is_seed_pin` only accepts a bbox tuple). **OR**
- **the remaining layouts** — `fit-solid` (a filler, not a branch: add `solid` to
  `BACKGROUNDS`), `split` (two clips → two rects), `pan` (a path over a static
  subject). The three-parameter model was built to absorb these without new code
  paths; `split` is the one that stresses it, since it needs two sources. **OR**
- **stabilization + tracking degradation** — vidstab (never on wade-in/out shots,
  §12) and the optical-flow degradation ladder; removes the matching `validate()`
  refusals. **OR**
- **router** — cap-3 fan-out: resolve project → `resolve_manifest` per episode →
  fan out `process_episode`. **OR**
- **golden-canon armature + landmine lint** — a check that the banned patterns
  (`lutrgb`, `-ss` before `-i`) cannot re-enter the filtergraphs.

## Deferred / open

- vidstab-capable ffmpeg before stabilization (`bash setup.sh --with-vidstab`).
- descriptor continuity re-match needs ingestion's cast.json.
- cap-3 parallel fan-out is the router's job.

## External assets (outside this repo)

- **Golden fixture source (plan Task 9.5):** session footage + window map at
  `/Users/serg/Downloads/untitled folder/REEL_SOURCES.md` — footage (`MVI_*.MP4`,
  `DJI_*.MP4`, ~128 files) sits in that same folder. `MVI_3739.MP4` (the long
  ride) is the suggested fixture source.
- The Jul 3–5 montage session that this design was reverse-engineered from
  produced Reel A (ODESZA) and Reel B (Billie Eilish); real-footage validation
  happens when Sergei re-montages that footage — user-driven, not a milestone.
