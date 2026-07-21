# Build Status

What is built, what is next, and the external assets the build depends on.
**Update after every task** — tick the plan's checkboxes and add/adjust the
relevant bullet here in the same commit.

_Last updated: 2026-07-21._

> Bird's-eye progress across the full 16-stage conveyor:
> [pipeline-map.md](pipeline-map.md). This file is the detailed per-subsystem
> changelog; that one is the stage-by-stage map + phase roadmap.

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
  [`docs/specs/`](./specs/); anna-auth-style standards adopted
  ([coding-standards.md](./coding-standards.md), [testing-guide.md](./testing-guide.md),
  [development-workflow.md](./development-workflow.md)); `CLAUDE.md` became a
  registry; scripts brought into compliance (full type hints, imports-at-top).

- **reel back half DONE (2026-07-11)** — plan `docs/plans/2026-07-10-reel-back-half.md`
  + design `docs/specs/2026-07-10-reel-back-half-design.md`, Tasks 0–11 via strict
  subagent-driven-development (branch `feat/reel-back-half`, commits
  `6c6b1e4`..`8e1d768`). **342 tests green incl. a real-ffmpeg whole-slice golden**
  (`test_reel_backhalf.py`: 2 windows → `process_episode` ×2 → `assemble` →
  `check_reel` → `deliver`). The silent back half of the conveyor: `[locked
  out/<ep>.mp4 …] → assemble → work/master.mp4 → check_reel → deliver →
  out/REEL_v{n}.mp4`, exactly one encode anywhere in it (at deliver). Built
  `scripts/lib/assembly.py` (`probe_stream`/`matches`: all-uniform episodes concat
  losslessly with `-c copy`; an outlier is normalized alone, then copy-concat) +
  typed contracts in `scripts/lib/models.py` — `ExportProfile`/`REEL_H264`,
  `ReelCheckSpec`, `ReelFailure`, `ReelReport` (raise-on-bad-construction + JSON
  round-trip, mirroring `Delivery`/`LayoutSpec`). `scripts/check_reel.py` runs four
  mechanical checks against the master — black, color-across-cuts (mean-RGB delta;
  culprit = the span **farther from the reel's per-channel median**, with a tie —
  every 2-episode reel, whose 2-value median is equidistant from both spans —
  blaming the LATER episode), variety (phash Hamming distance at episode
  midpoints), length — while `beat`/`loudness`/`safe_zones` honestly report
  `CheckResult(passed=None, detail={"status":"not-implemented"})`, **never** a
  silent pass. Every failure emits a machine-readable `ReelFailure` (`check`,
  `episode_idx`, `escalate_to`, `detail`) so a future driver reads the culprit
  straight off the report instead of re-deriving it. `scripts/deliver.py` is the
  **one encode** — `ExportProfile.args()` is its single source of ffmpeg flags —
  behind a **hard gate** (`report.overall is False` → raise, no fix-forward); it
  versions `out/REEL_v{n}.<container>` (never overwrites) and appends a changelog
  line to `out/VERSIONS.md`. **Found beyond the plan:** the shared `sample_clip`
  test fixture's `drawbox` position expressions are inert under ffmpeg 8.1.1 (`t`
  reads as `INT32_MAX`, not frame time) — switched to compositing the moving box
  with `overlay` instead (`fae6209`), a test-fixture-only fix; `testing-guide.md`
  now warns against reintroducing the `drawbox` form. **Deferred → built (Phase
  A.5, see the entry below):** the retry *loop* — `reel_orchestration.next_action`
  (the §4.1 ladder) + the `build_reel` driver (assemble → check → reprocess culprit
  via `process_episode` → recheck → deliver | stop-and-report) + a per-episode
  colour override in `reframe` (shipped as `ReframeSpec.color_correct`) so a
  reprocess can re-grade one episode toward the reel median.

- **reel retry loop (Phase A.5) DONE (2026-07-11)** — plan
  `docs/plans/2026-07-11-reel-retry-loop.md` + design
  `docs/specs/2026-07-11-reel-retry-loop-design.md`, Tasks 0–7 via strict
  subagent-driven-development (branch `feat/reel-retry-loop`, commits
  `39adba0`..`a06a07e`). **389 tests green** (47 new, incl. 2 real-ffmpeg
  tests in `tests/integration/test_reel_retry.py`). `scripts/build_reel.py`
  loops `assemble → check_reel → next_action → reprocess culprit → deliver |
  stop-and-report` over a typed `ReelManifest` (locked episodes, each a
  manifest + clip + **frozen route** — a reprocess reuses it, so colour/black
  fixes never re-track). `reel_orchestration.next_action` is the §4.1 ladder
  one level up, mapping a `check_reel` report to Deliver | Reprocess[...] |
  Escalate. A colour reprocess corrects via `color.corrected()` (composes an
  external per-channel factor onto grade gains, re-clamps to `[LO,HI]`)
  through `ReframeSpec.color_correct`, threaded by `process_episode`'s new
  `color_correct` param (constant across attempts, like `layout`);
  `check_reel`'s colour fail `detail` now carries `target` + `culprit_mean` so
  the driver computes the correction with no re-probe. **Two subtle rules
  define the loop: escalate-wins** (§3) — any non-auto-fixable or capped
  failure escalates immediately, never spending a round on a reel that also
  carries an unfixable fault — **and compound-not-revert** (§4) — each
  round's `med/d_i` ratio compounds onto the episode's *stored* factor
  (`cc[i] ← clamp(cc[i] * med/d_i, LO, HI)`) rather than replacing it, since
  `process_episode` regrades from source every pass and a per-round factor
  alone would revert instead of converging. **Only `black`/`color_across_cuts`
  auto-close**; `variety` (→ edit-plan) and `length` (→ pacing)
  stop-and-report — their front-half fixers (EDL, pacing) aren't built.
  **`build_reel` never delivers a failed reel:** escalate, reprocess-failure,
  and capped-attempts all stop-and-report a machine-readable finding instead.
  **Review-driven:** Task 2's `ReelManifest` validation closed gaps found on
  review (lazy threshold fields, a null-manifest `TypeError`, a bare
  `KeyError` — all now raise `ValueError` with a remedy); Task 3 gained type
  hints + 3 branch-pinning tests; Task 5's `_compound` now reuses
  `color.corrected`.

- **music spine (Phase B · B1+B2) DONE (2026-07-11)** — plan
  `docs/plans/2026-07-11-music-spine.md` + design
  `docs/specs/2026-07-11-music-spine-design.md`. **426 tests green.** Gives the
  reel sound and closes two of `check_reel`'s silent `passed=None` gates.
  Built: `scripts/beats.py` (B1) — librosa `analyze(track, start_offset,
  duration) → MusicSpec` (tempo + reel-relative beat grid + coarse RMS
  energy), CLI writes `MUSIC.json`; `scripts/lib/models.py` gains the
  `MusicSpec` config-spec, `ReelCheckSpec.beat_tol/loudness_target/
  loudness_tol`, `_ADVISORY_CHECKS` (excludes `beat` from `ReelReport.overall`),
  and `ReelManifest.music`; `scripts/check_reel.py` — loudness is a **hard**
  gate (escalates to `audio-mix`), beat is **advisory** (measured, reported,
  never blocking); `scripts/mix.py` (B2) — music-only audio stem: accurate
  seek + afade + two-pass loudnorm −14 LUFS → aac (ambient ducking/SFX
  deferred to when `extract`, §5.8, preserves per-episode audio);
  `scripts/deliver.py` muxes the stem (stream-copy, preserves −14 LUFS);
  `scripts/build_reel.py` builds the stem once after the picture pass,
  re-checks loudness/beat, delivers with audio — `music=None` keeps the
  silent Phase A.5 path unchanged. **Code polish (same-day):** `check_reel`'s
  `_NOT_IMPL` stub was overloaded — it labeled `beat`/`loudness` "not
  implemented" when they are now built and simply have nothing to check on a
  silent reel. Split into `_UNCHECKED` (`beat`/`loudness` → status
  `"not-checked"`, reason names the missing input) and `_NOT_IMPL`
  (`safe_zones` only, genuinely unbuilt) — `passed` stays `None` either way,
  so no control-flow changed, only the honesty of the report. **Deferred (NOT
  built):** B3 autonomous sourcing (`music_find`/`music_fetch`, `music.mode`,
  mood-match), B4 pacing (5.6), ambient ducking/SFX, downbeats/sections/
  spectral/mood, `safe_zones`.

- **extract spine (Front-half SP1) DONE (2026-07-11)** — plan
  `docs/plans/2026-07-11-extract-spine.md` + design
  `docs/specs/2026-07-11-extract-spine-design.md`, Tasks 0–6 via strict
  subagent-driven-development (branch `feat/extract-spine`, commits
  `f7061be`..`ee5f6ba`). **470 tests green.** A hand-authored `EDL.json` now
  drives the whole conveyor to a delivered `REEL_v1.mp4` — no more
  hand-supplied segments or per-episode manifests. Built four units:
  `scripts/lib/edl.py` — `EDLEpisode`/`EDL` typed config-specs (JSON
  round-trip) + `to_manifest_dict` bridge (EDL row → process-episode manifest
  dict; omits canvas/delivery so they inherit); `scripts/extract.py` —
  `extract_edl(edl, footage_root, seg_dir)` loops the untouched single-window
  `extract()` over every EDL episode, plus the §5.8 length gate (segment
  duration must match its window, else raise); `scripts/edl_to_reel.py` — the
  thin SEQUENTIAL driver: load EDL+project → bridge+resolve+preflight →
  `extract_edl` → `process_episode` per episode → assemble a `ReelManifest` →
  `build_reel` → delivered | stop-and-report (CLI);
  `tests/integration/test_front_spine.py` — a real-ffmpeg golden proving the
  EDL→driver→`build_reel`→deliver **wiring**. **Load-bearing invariant:** the
  driver resolves canvas/delivery **once** (bridge → `resolve_manifest`) and
  stores the resolved manifest in each `ReelEpisode`, because `build_reel`'s
  reprocess calls `process_episode.process_episode(...)` **without**
  `project=` — an unresolved manifest would silently lose canvas/delivery on
  any reprocess round. **The golden's honest scope:** `process_episode` is
  faked (a real `route.json` + a copied, re-muxed clip) because the synthetic
  `sample_clip` is a box, not a person, so real YOLO tracking returns an empty
  route — the golden proves the wiring on real bytes (real extract, assemble,
  `check_reel` gates, mix, deliver mux), not pixel-level crop-to-canvas
  correctness (that stays covered by `process_episode`'s own real-footage
  goldens). **Deferred (NOT built):** SP1b `draft.mp4` (labels + music bed,
  §5.9), SP2 footage-intake, SP3 `EDL.md` markdown render + interactive
  edit-plan authoring, SP4 trend-scan, and the cap-3 PARALLEL router +
  episode-choice curation (montage §5.1).

- **footage-intake (5.2) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-footage-intake.md` + design
  `docs/specs/2026-07-12-footage-intake-design.md`, Tasks 0–15 via strict
  subagent-driven-development (branch `feat/footage-intake`). **522 tests green**
  (+1 vidstab-gated integration golden, skipped without libvidstab).
  `scripts/intake.py` scans a footage folder → `FOOTAGE.json` (typed) +
  `FOOTAGE.md` (rendered): per clip, scored candidate **moment-windows** — probe
  + PySceneDetect scene bounds + one YOLO11-seg + ByteTrack pass (people/tracks/
  masks) + `vidstabdetect` shake, **sub-scene carve** into the episode band
  (scenes alone don't split a long take), present/motion/stability/dur **score**,
  **phash cull** marking the best (dedup by image, not filename). New contracts
  in `scripts/lib/footage.py` — `FootageWindow`/`FootageClip`/`Footage`
  (+`to_markdown`) and `CastMember`/`Cast`; a `FootageWindow` projects onto an
  `EDLEpisode` (5.7's input). The **cast pass**: the single seg pass surfaces
  top-N distinct person crops → `cast_candidates.json` + `cast_crops/`; the
  `footage-intake` SKILL names them interactively → `write_cast` → `cast.json`.
  `assembly.probe_duration` promoted from `extract._probe_dur` (shared). **Intake
  is the repo's first runtime vidstab consumer** — hard preflight + skip-if-absent
  tests. **Review-driven fixes:** carve dropped a shredded clip to one over-band
  window (now yields empty — band invariant held); the cast pass was built but
  **unreachable** (`intake()` discarded crops, `write_cast` took arrays that
  didn't survive the boundary) — wired end-to-end (persist candidates +
  descriptor-based `write_cast`, `(source, track_id)` keys since ByteTrack ids
  restart per clip); `SHAKY_CLIP` width-fraction spec-sync; a `cull` test-fixture
  bug (`imagehash.average_hash` of any uniform image is all-zero); full type
  hints. **Deferred (NOT built):** SP1b `draft.mp4`, SP3 authoring, SP4
  trend-scan; descriptor→manifest hero-pin wiring landed 2026-07-16 as its own
  slice, cast → hero-pin (see below) — `orch.is_seed_pin` was deleted there,
  not left bbox-only.

- **edit-plan spine (Front-half SP3 · 5.7) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-edit-plan-spine.md` + design
  `docs/specs/2026-07-12-edit-plan-spine-design.md`, Tasks 0–7 via strict
  subagent-driven-development (branch `feat/edit-plan-spine`, commits
  `3208f0e`..`796e74f`). **548 tests green** (+1 vidstab-gated integration
  golden, skipped without libvidstab). Closes the critical-path head to
  autonomous v1 (5.2 → **5.7** → 5.1 router). `scripts/lib/edl.py` gains
  `EDLEpisode.to_dict`/`EDL.to_dict` (JSON round-trip serializer),
  `EDL.to_markdown` (the `EDL.md` human map: source/window/shot/layout/comp/
  grid/motion/beat/notes per episode), and `preflight` — the EDL→manifest
  gate extracted verbatim from `edl_to_reel`'s inline step-1 loop, now shared
  by the driver and the new authoring path (`edl_to_reel`'s own tests stay
  green, unchanged). `scripts/edit_plan.py` (new): `window_to_episode`
  projects a scored `FootageWindow`/`FootageClip` (5.2) onto an `EDLEpisode`
  **by reference** — mechanical fields (source/start/dur/shot_type/
  description) copied straight from `FOOTAGE.json`, never retyped, closing
  off the silent-wrong-cut class (montage §12); only editorial fields
  (composition/grid required, layout/motion/hero/… optional) are
  agent-supplied. `build_edl` resolves a `selection.json` (window refs by
  source + integer index, plus editorial fields and reel knobs) into a typed
  `EDL`, fail-loud on an unknown source (lists what's available) or an
  out-of-range window index. `write_edit_plan` + CLI
  (`python -m scripts.edit_plan build`) chains Footage→selection→`build_edl`
  →`preflight`→`EDL.json`+`EDL.md`, writing **nothing** on a preflight
  `stop_and_report`. `SKILLS/edit-plan/SKILL.md` — the writing-plans-style
  **autonomous draft + single review gate** subagent (context recon → author
  `selection.json` → build → present `EDL.md`; edits round-trip through
  `selection.json`, the SKILL never hand-patches `EDL.json`).
  `tests/integration/test_edit_plan.py` — the real-ffmpeg SP3→SP1 golden: a
  hand-written `FOOTAGE.json` + `selection.json` + `project.json` →
  `edit_plan build` → `EDL.json` round-trips and `EDL.md` renders → **the
  same `EDL.json` feeds the existing `edl_to_reel`** on synthesized source
  clips → `status == "delivered"`, `REEL_v1.mp4` exists — proving the
  SP3→SP1 seam on real bytes. **Selection stays the agent's judgment, code
  stays thin** — no Python window-scorer, since 5.2 already scored/culled/
  best-marked the windows; 5.7 only projects references and renders the map.
  **Deferred (NOT built):** full reel-brief `SPEC.md` authoring (§5.3),
  `PACING.md`/`beat_slot` binding (§5.6/B4 — `beat_slot` stays `None`
  without pacing), cap-3 **parallel** router + episode-choice curation
  (§5.1), cast→hero-pin descriptor resolution (`hero` still rides as a bare
  bbox/rule/name string).

- **using-montage router (5.1, entry-skill) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-using-montage.md` + design
  `docs/specs/2026-07-12-using-montage-design.md` (branch `feat/using-montage`).
  Ships the conveyor's front door: `SKILLS/using-montage/SKILL.md` conducts the
  built stages (project-init → footage-intake → [music] → edit-plan → edl_to_reel)
  with the three §4.1 user checkpoints (SPEC · EDL+curation · final review),
  resuming a half-finished run for free and naming any deferred stage on skip.
  Backed by `scripts/montage.py` — a thin deterministic **inspector**
  (`Stage`/`V1_STAGES` + `next_action(run_dir)` reporting each stage's state
  done/next/pending/optional/skip from artifact presence, + a `status` CLI). 15 new
  unit tests (**564 green**, 1 skipped). **Inspector, not runner:** the judgment
  steps (cast-naming, selection authoring) stay agent-interactive, so the SKILL runs
  stages and consults `next_action` for the resume/next decision (mirrors intake.py
  ↔ footage-intake). No stage re-implemented; no new integration golden — the
  SP1/SP3 seam goldens already prove intake→edit→reel on real bytes. **Deferred (NOT
  built):** cap-3 **parallel** episode fan-out (edl_to_reel stays sequential), full
  reel-brief `SPEC.md` (5.3), `draft.mp4` (SP1b), dual-emit "without-music"+sidecar
  (5.14), trend-scan (5.4), pacing (5.6), cast-name hero-pin resolution.

- **reel-brief (5.3, editorial spine) DONE (2026-07-12)** — `scripts/lib/spec.py`
  (`Spec` config-spec: canvas-from-project + gate on mood/hook/length, JSON
  round-trip, `to_markdown`) + `scripts/reel_brief.py` (`build_spec`/`write_reel_brief`
  + CLI) + `SKILLS/reel-brief` (one-question-at-a-time → `SPEC.md`+`SPEC.json`). Router
  flips reel-brief deferred → **optional** (SPEC.md enriches CP1; autonomous path
  intact). Text stage — no ffmpeg, no golden. See `docs/plans/2026-07-12-reel-brief.md`.

- **assemble-draft (5.9, QA-preview spine) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-assemble-draft.md` + design
  `docs/specs/2026-07-13-assemble-draft-design.md`. **603 tests green** (+4
  skipped: the 3 real-ffmpeg draft goldens on a machine whose ffmpeg lacks
  drawtext, +1 pre-existing vidstab-gated). `scripts/draft.py`
  (`build_draft` + CLI): extract each EDL window, burn a canvas-fit (letterbox)
  + `processing_notes` label into every segment, concat via the shared core, mux
  a rough music bed by reusing `mix.mix` — one source of truth for laying music,
  absent music → a silent draft. `scripts/lib/draft.py` — the pure helpers
  (`resolve_font`/`label_text`/`segment_filter`), split out so the drawtext
  `fontfile=` landmine (design §12 — macOS has no fontconfig default) is caught
  in a unit test, not at render. An `ensure_drawtext` runtime preflight fails
  loud with a remedy when the active ffmpeg lacks the filter. `scripts/lib/
  assembly.py` gains a shared `concat()` (extracted verbatim out of `assemble()`,
  behaviour unchanged — the final assembler and the draft now reuse one concat
  core). Router: an **optional** `assemble-draft` Stage in `montage.py`
  (`draft.mp4`, checkpoint `"edl"`, CP2) — never chosen as `next`, so the
  autonomous chain is untouched; `using-montage` offers it as an optional CP2
  preview after edit-plan. Real-ffmpeg golden (`tests/integration/test_draft.py`:
  canvas-fit dims, muxed music bed, silent variant, CLI) behind an autouse
  drawtext skip-guard so the suite stays green on a machine without a
  drawtext-capable ffmpeg; `setup.sh` now ensures one by default (homebrew-ffmpeg
  tap fallback, mirroring the vidstab block).

- **titles (5.16, on-screen text spine) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-titles.md` + design
  `docs/specs/2026-07-13-titles-design.md`. **638 tests green** (+6 skipped:
  the 2 real-ffmpeg titles goldens + the 3 draft goldens on a machine whose
  ffmpeg lacks drawtext, +1 pre-existing vidstab-gated). `scripts/lib/fonts.py`
  — `resolve_font` extracted from `draft.py` plus a name-mode (`FONT_NAMES`):
  a curated cask font resolves by friendly name, unknown/uninstalled fails
  loud with the `--with-fonts` remedy — no silent substitution.
  `scripts/lib/titles.py` — `Title`/`Titles` config-specs + `build_filterchain`
  (one `drawtext` per title, `enable='between(...)'` windows, per-title
  `textfile=`). `scripts/titles.py` — `build_titles` projects `SPEC.hook/text/
  ending` into a starting `Titles` (hook opens, ending closes in the last 3s);
  CLI writes `TITLES.json`+`TITLES.md`. `scripts/deliver.py` gains `titles=` —
  burns the chain into the **one encode** it already runs (silent and
  music-muxed paths both covered, never a second pass); `build_reel`/
  `edl_to_reel` thread `titles=` through. Optional `montage.py` Stage
  (`TITLES.json`, checkpoint `"final"`) — never chosen as `next`; `titles`
  SKILL + `using-montage` CP3 wiring (offered alongside the final reel
  review). `setup.sh --with-fonts` installs a curated set (Montserrat/Inter/
  Bebas Neue/Oswald) on top of the DejaVu floor. Real-ffmpeg golden
  (`tests/integration/test_titles.py`) confirms the burned encode differs
  pixel-for-pixel from an untitled one, both silent and muxed, behind the
  existing drawtext skip-guard. See `docs/plans/2026-07-13-titles.md`.

- **start-offset intelligence (§5.5 sub-slice) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-start-offset-intelligence.md` + design
  `docs/specs/2026-07-13-start-offset-intelligence-design.md`. `scripts/lib/offset.py`
  (`downsample` relocated from beats to break a beats↔vocals cycle; `vocal_gaps`
  relative-threshold pause spans; `best_offset` loudest gap-start window, argmax
  fallback — with a review-fixed invariant so the offset never overruns
  `track_dur − duration`) + `scripts/lib/vocals.py` (`has_demucs`/
  `separate_vocal_energy`, the lone lazy demucs importer) + `scripts/beats.py`
  `choose_offset` driver and CLI `--auto-start` (mutually exclusive with
  `--start-offset`, needs `--duration`). demucs is opt-in (`setup.sh --with-demucs`,
  pulls torch); absent → a logged librosa mix-silence proxy, never a crash. Pure
  decision exhaustively unit-tested; the demucs path is mocked (unit) +
  skip-if-absent (integration `test_offset.py`, real proxy path always runs).
  `analyze()` untouched. **Deferred:** beat-snap of the start, section detection
  (B4 pacing), mood-match/sourcing (B3).

- **mood-match (§5.5 sub-slice, local lane) DONE (2026-07-14)** — plan
  `docs/plans/2026-07-13-mood-match.md` + design
  `docs/specs/2026-07-13-mood-match-design.md`. `scripts/lib/mood.py` — the pure
  core (the `offset.py` analog): `MoodVector` (3 axes energy/brightness/pace,
  validate + JSON round-trip, remedy-bearing `from_dict`), a synonym-rich
  `MOOD_ANCHORS` lexicon, `mood_target` (free-text mood → target, zero-match →
  None), `distance` (weighted Euclidean), `rank`, and `rank_by_drive` (the
  no-target fallback, positive drive under its own key). `scripts/beats.py` gains
  `mood_features(track)` — lazy librosa: tempo → pace, spectral centroid →
  brightness, **peak-normalized** RMS mean → energy (loudness-robust, the §12
  relative-gate discipline). `scripts/mood.py` — the driver: scan a folder →
  `mood_features` each → rank vs `mood_target(SPEC.mood)` (or `rank_by_drive` on a
  zero-match, logged never silent) → `MUSIC_SHORTLIST.{json,md}`; CLI
  `--folder (--spec|--mood) --out-dir`. `SKILLS/music-match` runs it, presents the
  shortlist, the user picks, then the existing `beats --auto-start` writes
  `MUSIC.json`. Pure core exhaustively unit-tested (24); `mood_features` + the
  ranking golden are real-librosa integration tests (synthetic known-answer
  signals, ±tol). **702 tests green.** **Deferred:** B3 autonomous sourcing
  (networked), catalog-metadata mood, a 4th dynamism axis, feature caching.

- **music-sourcing (§5.5 B3, network lanes) DONE (2026-07-14)** — plan
  `docs/plans/2026-07-14-music-sourcing.md` + design
  `docs/specs/2026-07-14-music-sourcing-design.md`. `scripts/lib/catalog.py`
  (`Candidate` + per-source discovery over stdlib `urllib` / an opt-in `yt-dlp`
  module invocation, `preview_clip`) + `scripts/lib/fetch.py` (download + cache +
  sidecar + responsibility log) + `scripts/music_find.py` / `scripts/music_fetch.py`
  drivers reuse the mood engine (`beats.mood_features` + `mood.rank`) to source &
  rank internet tracks into `MUSIC_SHORTLIST`: `free` = ccMixter (no key) /
  Jamendo (keyed upgrade), `any` = YouTube (yt-dlp, default) + iTunes/Deezer
  opt-in, behind an explicit responsibility switch — `any` always logs + records
  `license="unknown (any lane)"`, never silently. `music-source` SKILL runs
  find→pick→fetch; `setup.sh --with-sourcing` installs yt-dlp + interactively
  configures a Jamendo key. **5.5 now fully ✅** — all three `music.mode` rights
  lanes (`local`/`free`/`any`) complete. **740 tests green** (+8 skipped: 3
  drawtext-gated draft-goldens + 2 drawtext-gated titles-goldens on a machine
  whose ffmpeg lacks drawtext, +1 pre-existing vidstab-gated intake golden, +1
  pre-existing demucs-gated offset golden, +1 off-network iTunes sourcing
  smoke). **Deferred:** B4 pacing (5.6), trend-presence ranking (blocked on 5.4
  trend-scan), catalog-metadata mood.

- **pacing (§5.6, B4 energy-spine authoring) DONE (2026-07-14)** — plan
  `docs/plans/2026-07-14-pacing.md` + design
  `docs/specs/2026-07-14-pacing-design.md`. `scripts/lib/pacing.py` — the pure
  core (the `offset.py`/`mood.py` analog): `Slot` (index/start/dur/energy/kind,
  validate + JSON round-trip) + `Spine` (slots/target_dur/tempo, validates
  hook-first/contiguous/duration-sum, `to_dict`/`from_dict`/`from_json`/
  `to_markdown`), band constants (`LOW_BAND`/`HIGH_BAND`, `SLOW_BEATS`/
  `MID_BEATS`/`FAST_BEATS`, `HOOK_BEATS`) + `_kind`/`_beats_per_slot`/
  `_beat_energy` helpers, and `build_spine` — folds the beat grid + RMS energy
  curve into a beat-aligned energy spine, cut density rising with energy (hook
  first). stdlib only (`statistics.fmean`, no numpy/librosa) — bit-exact,
  goldens pin exact slots. `scripts/pacing.py` — the driver: `build_pacing`
  reads `MUSIC.json` → `build_spine` → writes `PACING.{json,md}`, logging a
  `SPEC.length_s`/`MUSIC.duration` mismatch (never silent); CLI mirrors
  `scripts/mood.py`. `scripts/edit_plan.py` gains `build_edl(pacing=)` +
  `--pacing`: binds the i-th selected episode to slot i (`beat_slot=i`,
  `dur←slot.dur`, window start preserved), zip-to-min; a short window keeps
  its own `dur` + logs the shortfall, an episode/slot count mismatch logs an
  over/underflow report — `pacing=None` leaves the existing no-pacing path
  unchanged (the regression guard). `scripts/montage.py`'s `pacing` `Stage`
  flips `deferred → optional`; `SKILLS/pacing/SKILL.md` runs the driver,
  sanity-checks the `PACING.md` arc, then passes `PACING.json` to edit-plan;
  `using-montage` wires it in as an optional step between music-and-mood and
  edit-plan. Real-librosa integration golden
  (`tests/integration/test_pacing.py`): a synthetic quiet-half/loud-half WAV →
  `beats.analyze` → `build_spine` proves the loud half carries more (shorter)
  slots end-to-end. **781 tests green** (+8 skipped, unchanged from
  sourcing: 3 drawtext-gated draft + 2 drawtext-gated titles + 1 vidstab-gated
  intake + 1 demucs-gated offset + 1 off-network sourcing smoke). **B4
  authoring (role 1) complete — §5.6 now ✅.** **Deferred:** the retry-time
  auto-fix (role 2 — `build_reel`'s `length` failure re-timing the spine), the
  pacing-gate back-edge (auto re-pick `start_offset` on a misfit), librosa
  section detection, musical-phrase-aware grouping.

- **ambient ducking (§5.12 audio-mix, ambient sub-slice) DONE (2026-07-15)** —
  plan `docs/plans/2026-07-15-ambient-ducking.md` + design
  `docs/specs/2026-07-15-ambient-ducking-design.md`. Grows the music-spine
  (B2) mixer with a ducked ambient bed built from each clip's preserved
  nat-sound. `scripts/lib/models.py` gains
  `ReelManifest.ambient: bool = True` — the on/off switch (`False` restores
  today's pure-music stem).
  `scripts/mix.py` gains `_build_ambient(segments, tmp_dir)`: per `(segment,
  target_dur)` in EDL order, an audio-bearing segment trims/pads (`apad` +
  `-t dur`) to a uniform 48kHz/stereo/s16 wav, a video-only segment synths
  `anullsrc` silence instead, and `assembly.concat` joins them into one
  reel-length bed (`None` when every segment is silent — a graceful
  music-only fallback, not an error); `mix(segments=)` inserts one
  filtergraph pass between the existing seek+fade and loudnorm passes —
  `sidechaincompress` ducks the ambient (main) under the music (sidechain
  key, via `asplit`), `amix=duration=first` pins the mixed stem to exactly
  the music's `dur` so it can never drift from the picture — before the
  unchanged two-pass loudnorm. `scripts/build_reel.py`'s stem hook gathers
  each episode's `(segment, target_dur)` from its manifest and passes
  `segments` only when `rm.ambient`. **Two real-ffmpeg proofs**
  (`tests/integration/test_ambient.py`): a bed-mixed stem still measures −14
  LUFS, and the ambient's frequency band measurably drops during the loud
  half of a synthetic music track (the duck moves samples, not just wires
  the graph); `tests/integration/test_music_spine.py`'s `build_reel` golden
  now hands real `segment`/`target_dur` manifests, proving the default
  `ambient=True` path survives real — but audioless, since `reframe` renders
  with `-an` — segments end-to-end. **796 tests green** (+8 skipped,
  unchanged from pacing). **Correction:** the pipeline-map's old "blocked by
  extract per-ep audio passthrough" note was stale — `extract` already
  preserves segment audio (§5.8), so no 5.8 change was needed; the ambient
  source is the preserved raw `ep{i}_raw.mp4` segments, never the silent
  locked clips. **Deferred → built (transition SFX sub-slice, see the entry
  below):** SFX (whoosh on transitions) — its own slice; shipped as a pure
  ffmpeg-synth whoosh (no asset) placed on major transitions.

- **transition SFX (§5.12 audio-mix, whoosh sub-slice) DONE (2026-07-15)** —
  plan `docs/plans/2026-07-15-transition-sfx.md` + design
  `docs/specs/2026-07-15-transition-sfx-design.md`. **Closes §5.12** — grows
  the music-spine mixer with a synthesized whoosh on the reel's major
  transitions, no assets shipped or downloaded. `scripts/lib/models.py`
  gains `ReelManifest.sfx: bool = False` — off by default (a deliberate
  stylistic accent, unlike the ambient bed which defaults on).
  `scripts/mix.py` gains `_whoosh(tmp_dir)` (ffmpeg `anoisesrc=color=pink` →
  `bandpass` → `afade` in/out swell, seeded and deterministic) and
  `_build_sfx(durs, tmp_dir)` (a cut is "major" when `max(neighbour dur) >
  _MAJOR_FACTOR * median(durs)`, throttled by `_MIN_GAP` between kept
  whooshes; synthesizes the whoosh once, `adelay` copies it onto each kept
  cut offset, `amix`es onto a silent base pinned to the reel length);
  `mix()` now composes up to three optional layers (music/ambient/sfx)
  across four cases — the music-only and ambient-only filtergraph strings
  stay byte-identical to before this slice (regression-pinned) — with the
  whoosh entering the final `amix` **un-ducked** (an accent, not
  background) at its own `volume`, trimmed to −14 LUFS by the unchanged
  final loudnorm. `scripts/build_reel.py`'s stem hook passes `segments`
  when `rm.ambient or rm.sfx` (SFX needs the episode durations even with
  ambient off) plus `ambient=rm.ambient, sfx=rm.sfx`. **Two real-ffmpeg
  proofs** (`tests/integration/test_sfx.py`): a whoosh-bearing stem still
  measures −14 LUFS, and the whoosh's frequency band measurably spikes at
  the one major cut's timestamp and nowhere else (placement, not just
  wiring). `deliver.py`/`check_reel.py` untouched — one pre-normalized stem
  in, same −14 gate. **812 tests green** (+8 skipped, unchanged from
  ambient ducking). **§5.12 audio-mix is now complete.**

- **safe-zones (§5.13) DONE (2026-07-16)** — plan
  `docs/plans/2026-07-16-safe-zones.md` + design
  `docs/specs/2026-07-16-safe-zones-design.md`. Closes the last unbuilt
  `check_reel` check — §5.13's **mechanical** half; the stage itself stays ◐
  until its editorial half lands (the spec's gate is "both parts green").
  `scripts/lib/safezones.py` — `SafeZone` config-spec +
  `SAFE_ZONES` platform table (`generic`/`tiktok`/`reels`/`shorts`, generic ==
  titles' 0.08/0.12) + `safe_zone_for`/`default_zone` + `subject_marks` (k=5) +
  pure `evaluate` (worst-offender). The subject→canvas projection
  `marks_at_times` moved from `scripts/storyboard.py` to
  `scripts/lib/geometry.py` (a checker must not import a driver; `storyboard`
  re-imports it). `check_reel.run` gains `geometry=`/`platform=`: with the
  frozen per-episode sidecars it projects each subject and tests it against
  the zone, reporting an **advisory** `CheckResult` (joins `_ADVISORY_CHECKS`
  with `beat` — reported, out of `overall`, no `ReelFailure`); `_NOT_IMPL` is
  gone (a geometry-less reel reports `not-checked`). `ReelEpisode` gains
  `path`/`meta`, `ReelManifest` gains `platform` (from `Spec.platform`);
  `build_reel` builds the geometry list once (invariant across colour/black
  reprocess — the route is frozen) and `edl_to_reel` wires the sidecars.
  `titles._Y_EXPR` now derives its margins from `safezones.default_zone()`
  (one authority; rendered exprs unchanged). No auto-fix actuator exists, so
  the check stays advisory by design. **835 passed / 8 skipped** (23 new
  incl. 1 real-ffmpeg proof in `tests/integration/test_safezones.py`).

- **cast → hero-pin (§6.1a ingestion half) DONE (2026-07-16)** — plan
  `docs/plans/2026-07-16-cast-hero-pin.md` + design
  `docs/specs/2026-07-16-cast-hero-pin-design.md`. Makes the manifest's `hero`
  pin mean something: **every** §5.10 pin form now resolves — a seed bbox
  (unchanged IoU match), a rule (`largest`/`leftmost`), an explicit track id,
  or a cast name matched by appearance descriptor — where before only the bbox
  did anything and a rule or cast name silently fell back to intent scoring,
  and `cast.json` (shipped with 5.2) was never read back by anything. Built:
  `scripts/lib/appearance.py` (**new** — `CAST_MATCH`/`build_descriptor`/
  `descriptor_dist`/`crop_and_mask`, moved verbatim out of `intake.py` so a
  driver need not import a driver; `HIST_BINS`/`DESCRIPTOR_LEN` live in
  `lib/footage` — the descriptor's shape is `cast.json`'s contract, and the gate
  path must stay numpy-free) + `scripts/lib/hero.py`
  (**new** — `resolve(hero, cast) -> HeroPin | None`, the one boundary; raises
  with a remedy on anything unresolvable, used both as `manifest.validate()`'s
  oracle and as the shell's real resolution, so validation and behaviour
  cannot drift apart) + `scripts/lib/models.py` (`HERO_RULES`/`HERO_KINDS`
  vocab, the frozen `HeroPin` config-spec, `TrackSpec.seed_bbox` → `pin`,
  `TrackMeta.pin_matched`) + `scripts/track.py` (`_rule_track`/`_id_track`/
  `_descriptor_track` rungs, masks now reach the tracker but are only read on
  the cast path, `build_route` dispatches every pin kind with **no
  fallback** — a pin matching nobody reports `pin_matched=False` and an empty
  route) + `scripts/lib/orchestration.py` (`is_seed_pin` **deleted**;
  `hero-unmatched` fires **before** `no-track` when a track existed and the pin
  missed it — the unmatched pin produced that empty route, so "hero never
  detected" would misdiagnose it; when the detector confirmed nobody at all,
  `no-track` wins instead, since the *detector* produced the empty route
  there, not the pin) +
  `scripts/lib/manifest.py` (`Manifest.cast` path field; `validate(m, cast=)`
  finally gates `hero`, using `hero.resolve` as its oracle — the `LayoutSpec`
  calque) + `scripts/lib/edl.py` (`EDL.cast`; `preflight` loads the registry
  **once** before the episode loop) + `scripts/lib/footage.py`
  (`Cast.from_dict` guards its own top level) + `scripts/process_episode.py`
  (loads the cast, resolves the pin, threads a `HeroPin` into `TrackSpec`) +
  `scripts/edit_plan.py` (`build_edl(cast=)`/`write_edit_plan(cast=)`/
  `--cast`). **Review-driven:** an exact descriptor tie (`d1 == d2`, including
  a perfect 0.0 double-match) is ambiguous, not confident — two tracks
  bit-identical to the pinned cast member is §6.1a mode 1's extreme case, not
  high confidence; `_rule_track` raises on a rule it has no implemented branch
  for rather than silently answering `leftmost` (the exact substitution this
  slice deletes everywhere else); `Cast.from_dict` needed its own top-level
  guard (a syntactically-valid but wrong-shape `cast.json` crashed
  `AttributeError` through preflight's narrow `except (OSError, ValueError)`,
  not caught by it). **Three more from the final review (2026-07-17), all
  registry-shaped — the pin was gated, the file behind it was not:**
  `validate()` now type-checks `Manifest.cast` (the one path field `from_dict`
  passes through raw, so `{"cast": 123}` reached `Cast.from_json` → `Path(123)`
  → a `TypeError` out of the soft gate; the load site needs the guard too, since
  it necessarily runs *before* `validate()`, which needs the loaded `Cast` as its
  oracle); `CastMember.descriptor` is checked against `DESCRIPTOR_LEN`, so a
  stale `cast.json` fails at load instead of passing every gate and detonating in
  `track.build_route` after every window was cut (`descriptor_dist`'s remedy was
  right, its *timing* was wrong — and its message promised a `3 * HIST_BINS`
  check it never made, now corrected to what it does); `Cast` rejects duplicate
  member names, which `resolve` used to answer by list order — a coin flip, and
  a plausible one, since intake dedups at `CAST_DEDUP=0.30` and a human names
  both surfaced crops "Lena". **Five more from completing that same review
  (2026-07-17):** the `hero-unmatched`-before-`no-track` ordering above became
  conditional on `features` (a segment the detector found nobody in now
  reports `no-track`, not `hero-unmatched` — see above); `hero.resolve`'s "no
  cast.json" remedy stopped naming a CLI flag (it is shared by three callers
  with three different registry spellings — `manifest.validate()` has no CLI
  at all, `edit_plan.py` has `--cast`, `track.py` has `--cast-json` — so the
  old "or pass --cast" text was wrong for two of the three and, on `track.py`,
  actively landed a reader in an `ambiguous option` argparse error; it now
  names the `cast` artefact/field instead) and `hero-ambiguous`'s detail text
  now splits on `pin_matched` (nobody pinned + a scoring tie ⇒ "pin a hero" is
  the action; a human's own pin tying two candidates ⇒ telling them to re-pin
  the same way would send them to re-run the exact match that just failed); a
  400-digit JSON int in a bbox pin no longer escapes `manifest.validate()` as
  a bare `OverflowError` (new public `models.is_bbox_coord`, the one
  finite-magnitude predicate `HeroPin` and `hero.resolve` now share); and
  `track.py --seed ''` — an unset shell variable's typical shape — is refused
  by `track._parse_seed` instead of silently downgrading a pinned run to a
  scored one. `tests/integration/test_cast_pin.py` (**new**) is the
  proof over real pixels — YOLO mocked (as every test in this repo mocks it),
  but the fake result carries a real BGR frame and a real model-space mask, so
  `crop_and_mask`, `build_descriptor`, `descriptor_dist` and the descriptor
  rung all execute for real. **§6.1a layer 3** (descriptor continuity
  re-match — intra-episode ID-switch repair) is a separate mechanism this
  slice does not build, but it is now **unblocked**: it needed the cast
  wiring, and the wiring has landed. **960 passed / 8 skipped** (936 at the
  slice's landing, +12 from the first three review fixes, +12 more from
  completing that review above).

- **reel-final editorial checks (§5.13 Slice A) DONE (2026-07-17)** — plan
  `docs/plans/2026-07-17-reel-final-editorial-checks.md` + design
  `docs/specs/2026-07-17-reel-final-editorial-checks-design.md` (branch
  `feat/reel-final-editorial`, commits `0f18c69`..`bcdedbf`). Completes the
  still-**mechanical** enumeration under §5.13's editorial half — three new
  checks, all **advisory** (measured + reported into the `ReelReport`,
  excluded from `overall`, never a `ReelFailure` — zero blast radius on
  loop-2/`reel_orchestration`/`build_reel`/`deliver`), mirroring `safe_zones`'s
  policy exactly: `key_action` (the tracked-subject bbox must not be clipped
  by the frame edge beyond `clip_tol`, via a new `geometry.extent_at_times`
  corner projection + `safezones.subject_extents`), `pad_bars` (non-`fill`
  filler bars well-formed — content rect inside frame, bars symmetric within
  `bar_symmetry_tol`; **structural**, read from the `path.meta` sidecar only,
  no pixels), `transitions` (adjacent-episode layout must not jump jarringly —
  a layout-jump proxy: `|Δcoverage| + centre-shift + a mode-change penalty`
  against `layout_jump_max`, read from `PathMeta` only). New module
  `scripts/lib/reel_final.py` (the three pure `evaluate_*` cores, importing
  only `lib.geometry`/`lib.models` — no driver import); `ReelCheckSpec` grows
  `clip_tol`/`bar_symmetry_tol`/`layout_jump_max`; `_ADVISORY_CHECKS` widens to
  `("beat", "safe_zones", "key_action", "pad_bars", "transitions")`;
  `check_reel.run` wires all three into the existing `geometry` block (no new
  CLI flag — they ride the same `--geometry` inputs `safe_zones` already
  consumes); `_UNCHECKED` gains three silent-path entries so a geometry-less
  reel reports `not-checked`, never a silent pass. **§5.13's gate is "both
  parts green", so the stage stays ◐** — this slice closes the mechanical
  enumeration under the editorial half, not the stage itself; the **agent
  editorial review** (Slice B — does the reel deliver SPEC's idea/mood/hook/
  ending/spine?) **remains open**, its own future spec → plan → implementation
  cycle. Pipeline tally unchanged: **14 ✅ · 1 ◐ · 1 ❌**. **1183 passed / 8
  skipped** (23 new).

- **reel-review editorial (§5.13 Slice B) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-reel-review-editorial.md` + design
  `docs/specs/2026-07-18-reel-review-editorial-design.md`. **Closes §5.13** — both
  parts green, stage ◐ → ✅ (tally 15 ✅ · 0 ◐ · 1 ❌). The agent editorial review:
  at CP3 a fresh reviewer subagent judges the delivered reel against `SPEC`
  (idea/mood/hook/ending/spine/edl_completeness/trend_flavor) and emits typed
  findings, each routed to an existing fixer stage; the human disposes.
  `scripts/lib/review.py` — `Finding` + `Review` config-specs (`REVIEW_AXES`/
  `REVIEW_SEVERITY`/`REVIEW_ROUTES`/`REVIEW_CONFIDENCE` vocabs, `Review.verdict`
  computed property = revise iff any blocking, JSON round-trip, `to_markdown`
  blocking-first). `scripts/reel_review.py` — thin driver: `build_review` validates
  the reviewer's RAW findings (fail-loud on a malformed finding, nothing written) →
  typed `Review`, `write_review` → `REVIEW.json`+`REVIEW.md`, CLI `build`
  (`--findings` list-or-`{summary,findings}` → artifact) — the `selection.json →
  EDL.json` idiom. `SKILLS/reel-review/` — the SKILL (build packet → dispatch
  reviewer → driver → human loop + routing) + `reel-reviewer.md` prompt template
  (the `requesting-code-review` calque); `montage.py` gains an **optional**
  `reel-review` Stage (`REVIEW.json`, checkpoint `final`, never `next`);
  `using-montage` CP3 invokes it. **Human-gated (§4.1)** — `check_reel`/`build_reel`/
  `deliver`/loop-2 untouched; no auto-fix actuator. **`trend_flavor`** is judged
  from general knowledge at forced `confidence=low` (no source until §5.4). Text
  stage — no ffmpeg golden (reel-brief's twin). **33 new unit tests; full suite
  1216 passed / 8 skipped.**

- **length re-time (Phase B tail) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-length-retime.md` + design
  `docs/specs/2026-07-18-length-retime-design.md`. Closes the two auto-fixes
  the pacing design parked together in its scope decision 1
  (`docs/specs/2026-07-14-pacing-design.md` §10) — the last open items of
  **Phase B — music spine**, now ◐ → ✅. Both are the same move at two edges:
  the reel's target length re-times DOWN to what the footage actually
  delivers. **Fix A — `build_reel`** (commits `99864c5`, `c6d32f6`, `ba5e64d`,
  `e3c5dcc`, `2fa0258`): `ReelCheckSpec.length_retime_max = 1.0` (max
  shortfall absorbed, on top of `check_reel`'s newly-named `_LENGTH_TOL = 0.5`
  gate). `reel_orchestration.next_action` gained a 4th `length_retime_max`
  parameter (default `0.0` = pre-slice behaviour), a `ReelAction.retime` field
  and a `"retime"` kind, and `_shortfall()`. `build_reel` keeps the check spec
  in a round-scoped local, adopts `action.retime` BEFORE dispatching on kind,
  logs it to stderr, and `continue`s to re-check — it never patches the
  report, so `deliver`'s hard gate is satisfied by a report the checker
  genuinely produced. **Fix B — `edit_plan`** (commit `5b851ba`):
  `_back_edge_target` sets a paced EDL's `target_dur = min(realized footage,
  spine.target_dur)`; an under-fill re-times down (the montage §4.1
  pacing-gate back-edge), an over-flow clamps to the fragment, both logged.
  **Proof** (commit `460d120`): two real-ffmpeg integration tests — a
  within-band shortfall delivers with a re-timed target; past the band
  escalates. **Load-bearing invariants:** the band is **one-sided** — only a
  SHORTER reel is absorbed, since `mix.mix` refuses a stem longer than the
  analyzed music fragment and `build_reel` cuts the stem at the master's real
  duration, so re-timing UP would trade a clean stop-and-report for a hard
  raise in the mixer; loop-2 stays **mechanical** (locked clips, frozen
  routes, no re-cut, no reach-back into `extract`/`edit_plan`); the delivered
  `reel_report.json` states the re-timed target because `check_reel`
  genuinely **re-ran** — re-checked, never patched; **escalate-wins
  survives** — a capped or unfixable failure alongside an absorbable
  shortfall still escalates, and the pending re-time dies with the round.
  **A bonus fix:** a paced over-flow EDL with no explicit `target_dur`
  previously fell through to `sum(ep.dur)`, passed the length gate, and hit an
  uncaught `ValueError` inside `mix.mix` after a full picture pass — the §4
  clamp turns that into a clean stop-and-report at the reel gate. The final
  whole-slice review found the mirror of that same hole still open — the
  absorb's one-sidedness was anchored to `target_dur`, not to the music
  fragment, so a `target_dur` above `music.duration` could still carry a
  master into `mix`'s raise; `build_reel` now preflights the two and refuses
  an unmixable manifest before any ffmpeg (design §6). **1237 passed / 8
  skipped** (19 new unit + 2 new real-ffmpeg integration tests).
  **Deferred:** re-picking `MUSIC.start_offset` via librosa (`beats.
  choose_offset` stays the manual rung); re-cutting footage inside loop-2;
  auto-fixing an over-length reel; re-deriving a truncated `Spine` for
  `PACING.json`; librosa section detection / phrase-aware grouping.

- **cap-3 parallel episode fan-out (§5.1's last sub-item) DONE (2026-07-18)** —
  plan `docs/plans/2026-07-18-cap3-fanout.md` + design
  `docs/specs/2026-07-18-cap3-fanout-design.md`. **1259 passed / 8 skipped**
  (**+22**: 2 fixture pins, 2 `ensure_model` + 1 MODEL-drift pin, 6 `jobs`
  validation, 6 pool, 3 failure-channel, 2 CLI).
  `scripts/edl_to_reel.py`'s sequential per-episode
  loop becomes `ThreadPoolExecutor(max_workers=jobs)`, default
  `DEFAULT_JOBS = 3`, exposed as `--jobs`. **Stage 5.1 now has no open
  sub-items.**
  **The number was measured, not inherited.** The repo's own docs disagreed:
  montage §5.10 said three saturate the box, `build_reel.py:88` said one does.
  A spike ran six real 2.5 s windows from `MVI_3739` through the full
  `process_episode` (YOLO11-seg → reframe → check → storyboard) at each
  concurrency on a 14-core M-series box: **41.1 s → 27.4 s (1.50×) → 24.2 s
  (1.70×) → 24.4 s (1.68×)** for jobs 1/2/3/4. The knee is exactly 3; at 4,
  per-episode latency reaches 1.85× for no throughput. §5.10 was right;
  `build_reel`'s comment was the wrong one and is corrected in place.
  **Three decisions.** *Threads, not processes* — `process_episode` is torch plus
  subprocess ffmpeg, both of which release the GIL, and the 1.70× is a thread
  measurement. *Run every episode, report the lowest index* — a failing episode
  no longer short-circuits later ones (a deliberate behaviour change, pinned by
  its own test), and the finding is chosen by INDEX so it never depends on
  thread scheduling; a raised setup error keeps its **own type** (`add_note`
  carries the episode) because `edl_to_reel`'s docstring contracts those as
  `ValueError`. **The final review caught the subtle half of this:** the first
  implementation drained the exception channel fully, *then* scanned statuses —
  giving each channel its own lowest-index rule but none *between* them, so a
  raise at episode 2 beat a routable `stop_and_report` at episode 0 and a caller
  branching on `result["status"]` got a traceback instead of a finding. One loop
  over the indices now decides both, and both orderings are tested.
  *`edl_to_reel` only* —
  loop-2's reprocess batch is one or two culprits and was hardened days earlier.
  Named `jobs`, not `cap`: `cap` already means loop-2's reprocess cap
  (`EDL.cap` → `ReelManifest.cap`), read a few statements below.
  **New §12 landmine, required for correctness:** ultralytics auto-downloads a
  bare model NAME on first use, so N cold workers race to write one weights
  file — silent corruption, not a raise. `track.ensure_model` warms every
  distinct model before the pool. A second, subtler entry followed from it: a
  unit test that fakes `process_episode` does **not** thereby avoid ultralytics,
  because the driver calls `ensure_model` itself — left real, `tests/lib/`
  imported torch and would have downloaded 6 MB on a cold CI cache, invisible on
  a dev box that already has the weights. The fixture stubs it.
  **Review-driven:** the fixture's `dict(pe_results or {})` silently coerced the
  old list shape (a one-element list holding a 2-key result dict becomes
  `{"status": "problems"}`, after which every episode falls through to
  `mechanical_pass`) — it now raises, because the coming "every episode runs past
  a failure" test would otherwise have passed hollow. The final review also found
  that the three real-ffmpeg SP1/SP3 goldens had silently acquired a torch
  dependency for the same reason as the unit tier, downloading weights into the
  **repo root** (ultralytics falls back to the CWD when its configured
  `weights_dir` is absent) past a `.gitignore` that only covered `models/`; they
  now stub `ensure_model`, and `yolo11*.pt` is ignored. A `track.MODEL` ==
  `manifest.DEFAULT_MODEL` pin was added: the driver warms the former while every
  worker builds the latter, and drift between two independent literals would
  reinstate the very race the warm-up removes.
  **Mutation-verified three times:** the barrier test goes red under
  `max_workers=1`, the exception-type test goes red when the bare re-raise is
  replaced by a wrapper, and the channel-precedence test goes red against the
  two-pass code.

- **fit-solid (§7 misc-engine, slice A) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-fit-solid.md` + design
  `docs/specs/2026-07-18-fit-solid-design.md`. **1304 passed / 8 skipped**
  (+45 over the 1259 baseline). Makes the background filler a real parameter
  and ships the rename that had to precede it: **`fit-blur` → `fit`**, atomic,
  no alias (the `TrackSpec.seed_bbox → pin` precedent) — a second filler would
  otherwise force an EDL author to write `{"layout": "fit-blur", "background":
  "solid"}`, contradicting itself, with the half that wins (`background`) not
  the half read first. `BACKGROUNDS` gains `solid`; `LayoutSpec` gains
  `background_color` (default `"black"`, validated exactly like `border_color`
  — non-empty, none of `,:;'[]\`); `fill` refuses any filler but blur, since it
  covers the canvas edge to edge and a filler would be an inert setting that
  reads as if it did something. The colour rides the whole authoring path —
  `LayoutSpec` → `ResolvedLayout` → `Manifest` → `EDLEpisode` →
  `to_manifest_dict` → `process_episode`, plus `reframe.py`'s
  `--background`/`--background-color` CLI flags — so it is authorable from
  JSON, not only from Python (a review-caught gap: `process_episode`'s own
  `LayoutSpec` construction had zero coverage of the hop and would have
  silently rendered every authored colour as the default). `PathMeta` gains
  `background`, read from a missing sidecar key as `"blur"` — a one-key
  exemption from the sidecar's otherwise-strict integrity check, justified
  because `blur` was provably the only value the field could ever have held
  before this slice. `reel_final.evaluate_transitions` keys its layout-jump
  penalty on the pair `(mode, background)` instead of `mode` alone, since a
  `(fit, blur)` → `(fit, solid)` cut leaves the mode untouched while the pad's
  appearance changes hard; advisory, so no gate verdict moves.
  **Two landmines, both measured rather than reasoned — the most transferable
  part of this slice, full writeup in design §12:** (1) `color` is an
  **infinite** source, and **both** obvious ways to end it are wrong.
  `overlay=…:shortest=1` terminates but truncates **exactly one frame** off
  every render at any rate (golden fixture: source 95 frames, blur 95, solid
  94; reproduced on synthetic 1s/3s/5s sources) — enough on its own to eat
  `check_reel`'s entire 0.5s length band across ~30 solid episodes. Bounding
  the *source* instead with `color=…:d={duration}` is necessary but **not
  sufficient**: `overlay` inherits the synthesized background's timebase, and
  a 3s/30fps clip renders as 1536s (`container_tb / fps` = 15360/30 = 512).
  The fix is `-t {duration}` on the **output**, applied unconditionally to
  every layout. **The trigger is an exact rate match, not a frame rate** —
  integer rates (24/25/30/50/60) blow up, NTSC fractional ones do not, and
  this repo's 59.94fps fixtures survive only because `f"{fps:.6g}"` mangles
  `60000/1001` into `59.9401` — a **formatting accident**, so a future
  29.97fps fixture added to "cover another rate" would prove nothing (an
  integer-rate proof is the only kind that can see this failure at all). The
  same infinite-source hazard is why `proc.run` now carries a default timeout
  (`DEFAULT_TIMEOUT_S = 900.0`) and raises instead of hanging — measured
  90s-and-killed against a 0.8s normal run, on a machine with no
  `timeout`/`gtimeout` binary to bound it from outside. (2) `background_color`
  reaches an ffmpeg argument and carries `border_color`'s injection surface —
  same guard, because a colour string is not a safe literal just because it
  is short. **Real-ffmpeg proof:** a solid render terminates with duration
  matching the source to within half a frame period, at an **integer** frame
  rate (not just the 59.94fps golden ride — that rate class is exactly what
  the timebase landmine does not trigger on) — `tests/integration/test_reframe.py`;
  a pad pixel is the requested colour, and the same frame under `blur` differs
  — `tests/integration/test_layouts.py`. **Review-driven fixes beyond the plan's own tasks:** three
  test-strength gaps a mutation pass caught with the whole suite still green —
  `proc.run`'s timeout kwarg was asserted as "a positive number" but never
  exercised end-to-end; `-t` being unconditional (so no future filler can
  forget it) had no test forcing it off; and `_background_args`' exhaustiveness
  raise had no test bypassing `LayoutSpec`'s own vocabulary gate to reach it
  directly. **Deferred (by design, non-goals §9):** gradient fill, an
  auto-derived background colour, `split`, `pan`, any `fit-blur` alias.

- **pan (§7 misc-engine, slice B) DONE (2026-07-19)** — plan
  `docs/plans/2026-07-19-pan.md` + design `docs/specs/2026-07-19-pan-design.md`
  (branch `feat/pan`). **1400 passed / 8 skipped** (+96 over the 1304
  baseline). Gives the crop's x(t) a second, *declared* source: a
  constant-velocity pan generated from two fractions of horizontal freedom,
  used *instead of* a tracked route. **Not a layout, despite sitting in the
  design's §7 five-names table** — the layouts model already gives `pan` the
  identical row to `fill` (canvas-aspect crop, whole-canvas rect, no filler),
  so this slice touches `LayoutSpec` not at all; what distinguishes a pan is
  where the crop's x(t) comes from, a motion-source question. Built:
  `PanSpec` (`scripts/lib/models.py` — two fractions `start`/`end` of
  `freedom = src_w − crop_w`, wire keys `from`/`to` since `from` is a Python
  keyword, direction is the sign of `end − start`, no direction vocabulary);
  `reframe.generate_pan_path` — a pure generator with **four** refusals
  (`freedom <= 0`, `dur <= 0`, `x0 == x1` after rounding, `v > max_speed`) and
  deliberately **no smoothing** (`pathsmooth` is for observation noise; a
  generated line has none); `reframe()`'s pan branch, where `route_path`
  becomes optional and **no route is read, and none is written**;
  `PathMeta.pan` — the one-bit provenance the sidecar carries, read with the
  same `.get`-based one-key exemption `background` took; `check_episode`
  branches framing to `editorial-only` and continuity to `not-checked` under
  a pan (jitter/length/black_frames keep running — they judge the rendered
  clip, not an observation); the manifest gate's two refusals (a
  `lead`/`break` composition, since a pan consults no subject; a `hero` pin,
  since a pan follows nobody) with `motion` deliberately **not** refused (the
  canonical pan is `motion: static` *and* a pan — a still subject, a moving
  frame); `process_episode` skips tracking and the contradiction gate outright
  under a pan (a real saving — a whole YOLO pass — and the honest statement
  that no observation exists) and treats a generated path as **not
  retryable** (the ladder's one lever, `max_speed`, is only a ceiling for a
  pan, so a retry would re-render byte-identical pixels, or worse, break on a
  damped ceiling); the EDL authoring path (`EDLEpisode.pan` → `to_manifest_dict`
  → `Manifest.pan`, riding the same rails `background_color` did); and a
  real-ffmpeg pixel proof (`tests/integration/test_pan.py`) that a `0→1` pan
  starts on one edge marker and ends on the other, with a centre-pinned
  control that sees neither.
  **Two measured blast-radius facts, not reasoned:** with `pan=None`,
  `reframe`'s emitted ffmpeg argv is byte-identical to before this slice; and
  a tracked episode's `report.json` is byte-for-byte identical before and
  after the whole slice. **Four landmines, all measured rather than assumed,
  full writeup in design §11/§12:** (1) `pathsmooth.smooth`'s rate limiter
  only bites near `max_speed`, so a realistic slow reveal (192 px/s) survives
  a full smoothing pass with **byte-identical endpoints** — measured: 11 of
  12 endpoint-based tests stayed green under that exact regression, so only a
  test that monkeypatches the smoother to fail on call proves the refusal.
  (2) An empty or fabricated `route.json` is not a neutral placeholder — an
  empty route already means "the tracker found nobody", a fabricated one
  makes `check_episode`'s composition check circular, and
  `checks.continuity([])` returns `pass=True` (its `zip` over an empty route
  never iterates), so the absence is not even loud. (3) `PanSpec` honestly
  refuses `start == end` in **fractions**, but cannot see the `freedom`
  those fractions get multiplied by — a span under half a pixel rounds both
  ends onto the same integer and renders a static frame nobody asked for;
  closed by `generate_pan_path`'s own `x0 == x1` raise, one level down, where
  the pixel arithmetic is visible. (4) `is not None` is not truthiness on a
  dict-valued optional — an empty dict is falsy, so `if m.pan:` silently
  skips validation in `manifest.validate()` and drops the key entirely in
  `edl.to_manifest_dict`; both mutations left the **whole suite green**.
  **Final Task 10 mutation battery: 18 checks against the finished tree, 0
  survivors** — including two escalation-order guards and both
  `is-not-None`-vs-truthiness sites found by review after the original
  14-check plan was written. **Closes §7's `pan` row** — see
  `docs/pipeline-map.md`'s misc-engine bullet for what's left (`split`,
  ~~stabilization's apply half~~ (landed 2026-07-20, see the Done entry below),
  ~~the tracking-degradation ladder~~ (landed 2026-07-21, see the Done entry
  below)).
  **Reel-level support was NOT part of the above — it landed after, as three
  more commits (Tasks 11-13, plan `docs/plans/2026-07-19-pan.md`), because a
  fifth consumer of `route.json` had been missed.** Task 10's audit (design §2)
  counted four readers; a fifth — `check_reel.run`'s geometry section — had
  already landed via two unrelated slices (safe-zones, 2026-07-16;
  reel-final-editorial-checks, 2026-07-17) before this design was even written,
  and nothing re-checked. `edl_to_reel` is the only multi-episode driver this
  slice's own authoring path builds, and every reel it built containing a pan
  episode crashed with `FileNotFoundError` — invisible to every test above,
  since all of them (this slice's own, and check_reel's) stop at a single
  episode. Found only by a final whole-slice review. Fixed by: `c1b3ffd`
  (`ReelEpisode.route: str | None = None` — `None` states a generated path has
  no observation to freeze; an empty *string* stays refused, since that is a
  caller who lost a path, not one who never had one); `caa6505` (`check_reel`
  reads each meta's `pan` bit before it will open a route, contributes an EMPTY
  mark list for a generated episode rather than dropping it — so
  `worst_episode` still names the reel's own index — and states an all-pan
  reel's coverage as `not-checked` instead of passing it vacuously); and the
  `edl_to_reel` fix itself (`route=None if md.get("pan") is not None else
  str(...)`, the same `is not None`-not-truthiness rule as landmine 4, a third
  instance of that exact substitution surviving elsewhere in this slice).
  Proved end to end by two new real-ffmpeg tests in
  `tests/integration/test_front_spine.py` — an all-pan EDL and a mixed
  tracked+pan EDL through the real `edl_to_reel` → `build_reel` → `check_reel`
  wiring, the level nothing exercised before, because
  `tests/lib/test_edl_to_reel.py` fakes `process_episode` entirely and a canned
  status dict never writes or fails to write a route file. **Final: 1415
  passed / 8 skipped** (+2 over the 1413 after `caa6505`, +15 over the 1400
  Task-10 baseline above). Mutation-checked: reverting the `edl_to_reel` fix to
  an unconditional route path turns **only** the two new tests red — nothing
  else in the suite depends on the value, because `check_reel` already branches
  on the meta rather than the route; the `is not None`→truthiness substitution
  stays unreachable here too, since the manifest gate refuses `pan={}` before
  `edl_to_reel` ever builds a `ReelEpisode`.

- **landmine lint DONE (2026-07-20)** — plan
  `docs/plans/2026-07-20-landmine-lint.md` + design
  `docs/specs/2026-07-20-landmine-lint-design.md` (branch `feat/landmine-lint`,
  commits `b02a467`..`908d2e2` plus this docs sync). **1491 passed / 8 skipped**
  (+75 over the 1416 baseline — the pan entry above records 1415 because it
  predates pan's own last fix commit `25ec48e`, which added one test). Closes the
  §11 charter item that three places in this repo committed to and none had
  built. The four §12 patterns that fail **silently** — `lutrgb`, an input-side
  `-ss` on a re-encoded window, an unbounded synthesized lavfi source, and
  `drawtext` without `fontfile=` — are now machine-checked at two layers, and
  `references/landmines.md` stops being a drifted second copy of §12 (17 entries
  against 26, one of them asserting something §12 had struck through as never
  true) and becomes a pointer to it.
  **Built:** `scripts/lib/lint.py` — pure, argv in, violation messages out, no
  I/O; `scripts/lib/proc.py`'s `run()` gains an always-on guard (never behind an
  env flag — a guard that is off in production does not protect production) that
  raises `ValueError` **before** `subprocess.run`, so it sees the *assembled*
  command including the graphs that arrive through a splat. `ValueError` and not
  `RuntimeError` deliberately: `proc.run`'s existing `RuntimeError`s say the
  ENVIRONMENT failed; a landmine says the CALLER is wrong.
  `tests/lib/test_landmine_scan.py` is the static half.
  **The static scan reads AST string literals, not lines — the plan prescribed a
  line-level scan and asserted the tree was clean. It is not.**
  `scripts/lib/color.py:1` and `scripts/check_episode.py:56` both name `lutrgb`
  in prose, documenting the ban at exactly the two places an author would look. A
  line scan cannot tell documenting a ban from violating it, and both escapes
  were worse than the problem — a path allowlist is forbidden by design §6, and
  deleting the documentation makes a landmine undocumentable at its own site.
  Reading the AST dissolves it: comments never enter it, and docstrings are
  subtracted by node identity. **The check measures *emission*, not *mention*** —
  which is what its name always claimed, and the two differ precisely where the
  codebase is most careful.
  **The rules are narrower than the slogans.** A `-ss` violation needs **five**
  conditions together (input-side seek · a `-t`/`-to` window · no
  `-accurate_seek` · no `-frames:v` · not a stream copy); a naive positional
  check produces four false positives out of seven hits on a clean tree, and this
  guard raises in production, so a false positive breaks a live render. The fifth
  condition arrived *after* the first implementation: the message and docstring
  both said *re-encoded* window while nothing checked for re-encoding, so a
  `-c copy` fast trim was flagged — a claim asserted but never verified. Every
  comparison is anchored, because ffmpeg's vocabulary is full of tokens that
  contain shorter tokens (`-sseof` ⊃ `-ss`, `boxcolor=` ⊃ `color=`, `seed=` and
  `pad=` ⊃ `d=`).
  **The choke point the whole runtime layer stands on is itself machine-checked**
  — the scan refuses any module under `scripts/` that imports `subprocess`
  outside `_MAY_IMPORT_SUBPROCESS` (`proc.py`, plus the two documented yt-dlp
  sites `catalog.py`/`fetch.py`). Design §2's "all 35 invocations funnel through
  `proc.run`" was hand-verified at design time — in the one slice whose entire
  thesis is that hand-verified invariants decay. **That constant, not prose, is
  now the authority on the list**, so the two copies cannot drift.
  **`REAL_SITES` grew from the plan's 9 to 22 fixtures**, with the filter strings
  printed from the real builders rather than hand-transcribed. It is the
  regression guard that matters: it proves the predicate matches the codebase
  rather than the slogan. Roughly **30 mutation rows** across the slice; one
  survivor, judged **equivalent** — dropping `[` from `_element`'s separators
  changes the verdict only on `testsrc=…[d=1]`, and ffmpeg link labels are
  identifiers, so that graph is invalid.
  **What this lint does NOT cover** (design §5, stated plainly because a lint
  believed to cover more than it does converts an unexamined risk into a false
  sense of safety):
  - **Ten test-side sites bypass `proc.run`.** Most are read-only ffprobe/raw-frame
    probes that cannot carry these landmines; the one that genuinely emits a
    filtergraph is **`tests/conftest.py:17`**, the session-scoped `sample_clip`
    fixture that roughly twenty tests measure their pixels against. It is correct
    today (`d=` on both sources **and** an output `-t`) and it is still a real
    blind spot — the fixture every pixel proof in the suite is measured against
    is the one command the guard cannot see. `scripts/` funnels through one choke
    point; `tests/` does not have to.
  - **Runtime coverage equals test coverage**, so a splat-assembled graph on an
    unexercised path is covered by **neither** layer. That is the residual hole
    and it is real.
  - **`SYNTH_SOURCES` is a five-entry denylist and it under-covers** — by a
    dozen other infinite lavfi sources (`nullsrc`, `aevalsrc`, `rgbtestsrc`,
    `yuvtestsrc`, `smptebars`, `gradients`, `cellauto`, `life`, `mandelbrot`,
    `allrgb`, `allyuv`, `haldclutsrc`). **`nullsrc` is one keystroke from the
    covered `anullsrc`.** These are misses, not false positives — the safe
    direction — but structurally the same flaw this slice was chartered to fix.
  - **A parameterless `-f lavfi -i color` is not detected.** `color=` and `sine=`
    carry a trailing `=` to disambiguate `color=` from `colorchannelmixer`, so
    the legal, infinite bare forms read clean. A deliberate trade-off, recorded
    because the code cannot express it.
  - **`drawtext` has zero real-argv corroboration on this machine.** This ffmpeg
    is built without libfreetype, so all of its integration tests skip and **not
    one** `drawtext=` argv reaches the predicate across the whole suite. That
    check is pinned by unit tests and by reading both producers — not by
    measurement. A drawtext-capable ffmpeg would close it.
  - **The static layer sees literals**, so a filter name assembled by `%`,
    `.format()` or concatenation would pass it. No such site exists today — every
    filter string in `scripts/` is a constant, an f-string, or a `join()` over
    those — so the completeness claim holds *for this codebase as it stands*, and
    the day someone builds a name a new way it stops holding silently.
  **The slice's most transferable lesson: twelve real defects were found by
  review, and none by the suite going red.** Four were **hollow tests** —
  assertions that held for a reason other than the behaviour they named (a
  `REAL_SITES` label crediting an exemption that never ran; `proc` tests that
  passed with the guard deleted; a real-tree scan asserting `== []`, which also
  passes when literal extraction is broken — now pinned by a positive control
  that requires a known-present filter name to be found). **The technique that
  found what neither the unit tests nor the mutation battery could was running
  the predicate over every argv the real suite issues (~700) and looking at what
  it flagged.** That is how a **masking pair** surfaced: `pad=` contains the
  substring `d=`, so every letterbox argument read as "bounded" and was exempted
  wholesale — a silent miss that was swallowing a false positive in the
  source-name boundary rule. Both mutation rows passed against a predicate that
  was wrong in two places, and fixing only the bound test would have converted a
  quiet miss into a **live raise on every letterbox render**. The two corrections
  had to land together, boundary first, so each commit is green on its own.
  Generalised: **when a check has an early exemption and a detector, a bug in the
  exemption can conceal a bug in the detector — so measure the predicate against
  the codebase, not only against its own fixtures.**
  **Drive-bys:** `tests/integration/test_pan.py:41`'s comment stated the seek
  landmine backwards (introduced by the pan slice, 2026-07-19) and is corrected;
  the two live links that promised `landmines.md` was a list
  (`references/ffmpeg-recipes.md`, `SKILLS/process-episode/SKILL.md`) now point
  at §12. **Deliberately out of scope** (design §7): the even-`scale=`,
  crop-expression-ceiling and dependency-pin family, all of which fail **loud** —
  worth guarding eventually, but adding them would dilute this lint's claim, that
  it catches the landmines which do *not* announce themselves.
  - **Cleanup round (2026-07-20, whole-slice review, commit `c01618b` + this
    docs sync). Final: 1512 passed / 8 skipped** (+21 over the 1491 above). The
    review returned READY TO MERGE with nothing blocking; **all three code
    findings were false positives**, which §6 ranks as the worst direction for a
    guard that raises in production, so they landed before the merge rather than
    after. Two were the same defect one option apart: ffmpeg spells a video copy
    seven ways and `_VIDEO_COPY_FLAGS` knew two, so `-vcodec copy`,
    `-codec:v copy`, `-c:v:0 copy` and `-codec copy` each raised on a correct
    windowed command — re-opening the door §4.2 added condition 5 to shut, one
    spelling over — and `-vframes 1`, the alias every tutorial still teaches, was
    not read as a still grab. Both became `fullmatch` regexes rather than wider
    string tests, because `-acodec`/`-codec:a` end in the same letters and copy
    AUDIO while the video is re-encoded, which is exactly when the landmine
    bites; `-c:0`, bare `-frames` and `-frames:a` stay unmatched on purpose,
    since matching them would EXEMPT a re-encoded window.
    **The third was the fifth instance of the boundary family**, and the first to
    point the other way: `_SYNTH_RE` was anchored only on its left, and string
    start is where that anchor is weakest, because an `-i` value is an element
    too — so `-i testsrc.mp4` read as a synthesized source and raised. Only a
    bare basename bit; the same path written absolutely was clean because `/`
    sits in the lookbehind's reject set, which is precisely what kept it hidden.
    Argv position would settle it but a per-element scan cannot see argv
    position; **spelling can** — a real source is `name` or `name=params`, never
    `name.ext` — so an `=`-less name now needs a `=`, an element separator, or
    end-of-element after it. `color=`/`sine=` were left alone: their trailing `=`
    already spells that requirement, and widening them would have silently
    changed §5's recorded parameterless trade-off.
    **Docs corrections:** §4.3's prose said a source is bounded by a `-t` "on the
    output" while the code accepts one **anywhere** in the argv — the prose was
    wrong and the code right, because `scripts/mix.py:137` ships a `-t` *ahead*
    of its lavfi `-i`; the loose reading's price (a `-t` bound to input #1 leaves
    an unbounded input #2 reading clean, and still hanging) is now recorded in
    §5, along with two measured `drawtext` gaps — a miss when a later filter in
    the same argv element carries `fontfile=`, and the converse false positive
    when a literal `drawtext=` sits inside a quoted `text=` value. **And the
    arithmetic: §12 carries 26 entries, not 28** — the "17 against 28" claim was
    wrong in all three places it appeared (this file, the lint design §9,
    `references/landmines.md`); the 17 was exact. `lint.py`'s comment naming the
    uncovered infinite sources had drifted to ten of twelve and now points at §5
    instead of carrying a third copy — the drift this slice was already bitten by
    twice. Each of the three widenings was mutation-checked in isolation:
    reverting it turns its own new test red and nothing else in the suite.

- **ffmpeg baseline — Tasks 0–7 DONE (2026-07-20)** —
  plan `docs/plans/2026-07-20-ffmpeg-baseline.md` + design
  `docs/specs/2026-07-20-ffmpeg-baseline-design.md` (branch
  `feat/ffmpeg-baseline`, commits `04b7600`..`a789431` + this docs sync).
  **1530 passed / 8 skipped.** One ffmpeg install carrying every library the
  pipeline needs, resolved from a path `setup.sh` records — and a `setup.sh`
  that can no longer uninstall a working binary. Before this slice the box's
  homebrew-core ffmpeg carried neither `libfreetype` nor `libvidstab`, so §5.9
  assemble-draft, §5.16 titles and 5.2 intake's shake score were dead on it and
  three integration tests skipped permanently.
  - **The headline finding is why `setup.sh`'s repair branch was destructive,
    and it is not what the design first said.** The branch guarding
    `brew uninstall --ignore-dependencies ffmpeg` was
    `if ! ffmpeg -filters | grep -q drawtext`, read as "fires when drawtext is
    missing". It is a **tautology**: under the script's own `set -o pipefail`,
    `grep -q` exits at its first match, ffmpeg still has 20KB of a ~36KB filter
    list to write, takes `SIGPIPE` and exits 141, and `pipefail` promotes that
    to the pipeline's status — while a genuinely absent filter exits 1. Both
    arms are non-zero, `!` inverts both, so the check can never report
    "present" and **the uninstall ran on machines where the filter was there**,
    against an `--enable-shared` build that `openai-whisper` and `summarize`
    link. Measured 141 on 5 of 5 runs, 0 without `pipefail`. The branch could
    not have completed either: its own post-install verification used the same
    idiom *without* the `!`, so the guaranteed path was uninstall → compile a
    tap build → abort with a false "drawtext still missing". Registered as a
    **new §12 landmine** (counted, not trusted: §12 is now **27** entries, up
    from the 26 the lint slice measured) and rewritten as design §1; the
    replacement captures the filter list once and matches in-shell.
  - **Built:** `scripts/lib/ffbin.py` — `$FFMPEG`/`$FFPROBE` →
    `config/ffmpeg.env` → `shutil.which`, always an **absolute** path (a machine
    now carries two ffmpeg builds, and a log that names which one ran is the
    difference between seeing a mixed pipeline and inferring it), plus
    `has_filter`/`require_filter`. **The path is frozen at install, the filters
    are probed every time** (design §4): a stale path fails loud through
    `FileNotFoundError`, a stale *capability* record would fail silently — the
    §12 shape — for the ~50ms it would save, and memoizing was dropped on the
    same argument (a test forgetting `cache_clear()` passes for the wrong
    reason). 33 production argv literals (11 files) and 37 integration-test
    literals (16 files) moved onto the resolver.
  - **§5 was the load-bearing half, not tidiness.** Four sites asked "does this
    build have that filter" four ways. Move production onto keg-only
    `ffmpeg-full` and leave the three test guards plus `conftest.sample_clip`
    probing PATH, and they find the *slim* build, skip forever, and report green
    with three integration tests silently uncovered. All four now go through one
    `need_filter` fixture, which also owns both skip reasons (nothing resolves →
    skip, not error). Three machine checks stop the drift back: bare
    `"ffmpeg"`/`"ffprobe"` literals are banned in `scripts/` (AST scan, **exact
    equality** — prose says "ffmpeg" constantly and stays legal) and in
    `tests/integration/`, and **no test anywhere may spell `-filters`**, since an
    independent capability probe is precisely the trap. Filed as a *convention*
    check, deliberately **not** in `check_argv`: a drawtext graph on a build
    without libfreetype exits `No such filter`, which `proc.run` raises loudly,
    so widening the silent-corruption guard with it would dilute what a
    `check_argv` refusal means.
  - **`setup.sh` stops being destructive.** Both `brew uninstall` branches
    deleted outright rather than guarded — `ffmpeg-full` is keg-only (same
    version *and* revision as core ffmpeg, 8.1.2_1), so it installs beside core
    ffmpeg and nothing needs removing. It now verifies rather than assumes (both
    binaries executable, both filters really present) before recording
    `config/ffmpeg.env`, and pins **without** `2>/dev/null || true` — that idiom
    is why the pin the old comments credited with protecting the goldens had
    never once applied. `--with-vidstab` and `--with-fonts` are deleted; both
    fold into baseline (fonts are four small casks, and without them titles
    fails loud). `--with-demucs` / `--with-sourcing` stay opt-in — torch and
    yt-dlp are size, not capability. Three brew gates warn-and-continue so a
    no-brew box still builds its venv, which hoisting `need_brew` had silently
    turned into a hard requirement.
  - **Found by the docs sync (Task 6), beyond the plan's file list:**
    `scripts/lib/fonts.py` still emitted `bash setup.sh --with-fonts` as its
    **runtime** remedy for an uninstalled font — a fail-loud message naming a
    flag this slice deleted — on *both* of its raises, with
    `tests/lib/test_fonts.py` pinning that exact string. **The obvious repair is
    a hollow test, and the mutation check caught it:** retargeting the assertion
    to `match="bash setup.sh"` can never fail, because the stale
    `bash setup.sh --with-fonts` contains it as a substring. Restoring the flag
    left the suite green. The property needs both halves — the installer named
    **and** the dead flag absent — and both raises now carry it (three
    mutations, each killed by exactly one test).  Worse,
    `SKILLS/footage-intake/SKILL.md` told the agent to check vidstab by running
    `ffmpeg -hide_banner -filters` itself, which on a keg-only install probes
    the *wrong build* — §5's trap written into the instructions. Five SKILL/spec
    sites in total plus two runtime strings; historical plans keep their
    original wording, per the `fit-blur`→`fit` precedent.
  - **Task 7 (the proof) is blocked on the user, not on code.**
    `config/ffmpeg.env` does not exist yet — `setup.sh` writes it and has not
    been run — so `ffbin` falls through to PATH and the 8 skips stand. After
    `bash setup.sh` the target is **2 skips, checked by identity**: `test_offset`
    (demucs, opt-in) and `test_sourcing` (an SSL failure unrelated to ffmpeg).
    Any surviving `test_draft`/`test_titles`/`test_intake` skip means the guards
    are probing the wrong binary — invisible in a count. The **goldens are the
    only real test of the design's same-version argument**; if one moves, that is
    a real pixel difference to record, not to re-pin away.

- **stabilize-apply (§5.2/§10 apply half) DONE (2026-07-20)** — plan
  `docs/plans/2026-07-20-stabilize-apply.md` + design
  `docs/specs/2026-07-20-stabilize-apply-design.md` (commits `9ffa33d`..HEAD).
  **1579 passed / 2 skipped.** `stabilize: true` now does something: a
  `vidstabdetect`/`vidstabtransform` pre-stage writes a stabilized copy of the
  segment, and BOTH the tracker and `reframe` read that file — never a filter
  inside `reframe`'s own chain, because the route is measured on unstabilized
  pixels, and a crop placed from it against transformed pixels would re-inject
  exactly the shake vidstab removed while `check_episode` kept confirming the
  framing regardless, since path and route are both in source coordinates and
  agree with each other; only the pixels would disagree (design §1).
  - **Built:** `scripts/lib/vidstab.py` (extracted from `intake.py`, its first
    consumer) — `require`/`detect`/`mean_shake`/`stabilize` + the `.trf`
    primitives, one shared `DETECT_ARGS` so `FOOTAGE.md`'s `shake` column and
    the pre-stage's `before` mean the same thing; `PathMeta.stabilized` fed by
    a keyword-only `reframe(..., *, stabilized=)` parameter (declarative — a
    fact about `src`, not an instruction `reframe` can act on);
    `ReframeSpec.stabilize` deleted outright rather than left refused; the
    manifest gate now calls `vidstab.require()` instead of hardcoding "not
    supported yet"; `EDLEpisode.stabilize` + the `to_manifest_dict` bridge
    (carries the key only when `True`); the `process_episode` pre-stage
    (after the preflights, so a manifest the layout cannot satisfy still
    fails in milliseconds; outside the retry loop, since stabilization is the
    loop's input, not one of its parameters); a frozen-route refusal
    (`stabilize=true` + a supplied `--route` → `needs_input`, since nothing
    records whether that route was measured on raw or stabilized pixels); and
    a `build_reel` fix so a reprocessed stabilized episode withholds its
    frozen route and re-tracks on the re-stabilized segment instead of
    dead-ending as `reprocess-failed`.
  - **`crop=black` → `crop=keep`.** The recorded recipe's `crop=black` fills
    the uncovered border with black, and under a `fill` layout the crop takes
    the source's full height, so that band lands in the delivered frame
    whole. `check_episode`'s black gate compares frame MEDIANS against a
    floor, and a few percent of the frame does not move a median — nothing
    would have caught it. `crop=keep` (also libvidstab's own default) removes
    the failure class instead of adding a check for it.
  - **What the proofs found, not just what they confirmed:**
    - The intake shake golden (`test_intake_real_vidstab_shake`) did **not**
      move when Task 1 unified the detect recipe at `shakiness=8`. Its only
      assertion is `shake >= 0.0` — a structural check with no pinned
      magnitude — and a check outside the suite confirmed why: on the
      synthetic `sample_clip` fixture, vidstabdetect's per-frame local-motion
      data comes back byte-identical across the entire `shakiness` range
      (1–10); only the `.trf` header's recorded parameter differs. The
      synthetic clip is too simple to expose what `shakiness` tunes — real
      footage is expected to differ.
    - `crop=keep` is proven on real pixels to leave no black edge, but the
      first version of that control **passed even against `crop=black`** — it
      controlled nothing. Two compounding reasons, both measured: (1) the
      aggregation — `band.max() > 16` passes as long as one bright pixel
      survives anywhere along an edge, and `crop=black` leaves a wedge, not a
      solid line; (2) the geometry — `zoom=2` pulls the outermost ~8px from
      real content, so the uncovered black band sits inset from the true
      edge, where reading only the outermost row/column never sees it. Fixed
      by reading a dark-pixel **fraction** over a 20px border **ring**, and by
      slowing the synthetic fixture's shake frequency (1.7 → 0.3): a fast
      oscillation is under-tracked, the correction is a few px, and `zoom=2`
      covers it — both crop modes then come out identical, exactly why the
      first version could not tell them apart. Calibrated over three
      rebuilds: `crop=keep`'s worst-frame border dark-fraction is
      0.0006–0.0069 against `crop=black`'s 0.3235, a threshold of 0.05 sitting
      cleanly between them. `test_stabilization_actually_reduces_the_shake`'s
      own margin on the same fixture: before ≈ 0.066, after ≈ 0.040, a ~40%
      reduction.
    - The frozen-route × stabilize collision (an open question the design had
      parked to final review) surfaced as soon as Task 8 wired `stabilize`
      into `to_manifest_dict`: `build_reel`'s reprocess loop was still passing
      loop-1's frozen route into a now-`stabilize: true` manifest, and
      `process_episode` correctly refuses that pair — so every reel
      reprocessing a stabilized episode dead-ended as `reprocess-failed`.
      Fixed by having `build_reel` withhold the route at the reprocess call
      for a stabilized episode (it re-tracks on the re-stabilized segment
      instead — one extra YOLO pass on the rare reprocess path) while leaving
      `ReelEpisode.route` itself populated, since `check_reel`'s geometry
      section still reads it.

- **tracking-degradation ladder (§6.1) DONE (2026-07-21)** — plan
  `docs/plans/2026-07-21-tracking-ladder.md` + design
  `docs/specs/2026-07-21-tracking-ladder-design.md` (commits `babad02`..HEAD).
  **1601 passed / 2 skipped.** `process_episode`'s reserved `"degraded": None`
  placeholder is now fed: an unpinned episode whose route comes back empty (or
  whose primary tracker is unavailable) falls to `scripts/lib/flow.py`'s
  optical-flow centroid tracker (cv2, no ML deps), then to
  `scripts/lib/keyframes.py`'s sparse marks + interpolation (the new
  `--keyframes` answer channel) — each rung stamped on `TrackMeta.degraded`
  (`None`/`"flow"`/`"manual"`). The identity-blind guard
  (`orchestration.flow_eligible`) keeps a pinned hero out of the flow rung
  entirely: an empty route under a pin stays `hero-unmatched`, never a
  motion-blob stand-in.
  - **Built:** `TrackMeta.degraded` + `DEGRADED_LEVELS`; `track.available()`
    (the rung-1 gate, symmetric with `flow.available()`);
    `scripts/lib/keyframes.py` (`interpolate`/`write_route`);
    `scripts/lib/flow.py` (`available`/`_centroid_bbox`/`build_route`, dense
    Farneback optical flow over real cv2 — the first runtime *tracker* use of
    OpenCV); the `process_episode` ladder wiring + `--keyframes` CLI flag.
  - **As-built fact worth recording:** `degraded` rides ALL post-tracking
    terminal results, not only `mechanical_pass` — a follow-up commit
    (`191be8d`) carries it onto the contradiction-`stop_and_report` result and
    both `escalate` results too, conditionally, the same shape as
    `stabilize_report`. Reason: a flow route's centroid is jittery on hard
    edges and reliably trips the `_UNFIXABLE` continuity gate, so the common
    outcome for a flow-rung episode is an **escalate**, not a
    `mechanical_pass` — restricting the stamp to `mechanical_pass` would have
    hidden the provenance in exactly the case a human most needs it. The
    integration proof asserts `degraded == "flow"` on an escalate result and
    `degraded == "manual"` on a `mechanical_pass` (the interpolated keyframe
    route is smooth by construction and clears continuity).
  - §6.1a layer 3 (descriptor continuity re-match — mid-episode ID-switch
    repair) is unchanged by this slice and stays its own slice.

## Next action

- **Front-half continuation — trend-scan, then the real-footage v1 gate**
  (`TRENDS.md` cache, §5.4 — low-priority/YAGNI) — the only front-half stage
  left now that SP1b (assemble-draft, DONE 2026-07-13) has shipped; once it's
  built (or knowingly skipped) the front half is complete enough to run the
  whole `using-montage` conveyor end-to-end on Sergei's real footage — the
  milestone the synthetic goldens stand in for today. **OR**
- **`split`** — the one genuinely remaining item of the design's §7
  five-names list (two clips → two rects; changes the manifest's shape). The
  three-parameter layout model was built to absorb it without a new code
  path, and it is the one that will actually stress that model, since it
  needs two sources — unlike `fit-solid` (2026-07-18) and `pan` (2026-07-19),
  both of which turned out to need no new layout code at all; see the two
  Done entries above. **OR**
- ~~**stabilization's apply half + tracking degradation**~~ — **both landed**:
  the apply half **2026-07-20** (see the Done entry above) — `vidstabtransform`
  now runs as a pre-stage in `process_episode`, feeding the same stabilized file
  to both the tracker and `reframe`, wired through the manifest capability gate
  and the EDL authoring path; and the **tracking-degradation ladder 2026-07-21**
  (see the Done entry above) — an unpinned episode's empty route (or an
  unavailable primary tracker) now falls to `scripts/lib/flow.py`'s
  optical-flow centroid tracker, then to `scripts/lib/keyframes.py`'s manual
  keyframes, each rung stamped on `TrackMeta.degraded`; *not* the reframe-param
  retry ladder in `orchestration.py`, which was already built. **OR**
- **the real-footage v1 gate** — run the whole `using-montage` conveyor
  end-to-end on Sergei's own footage. Every seam golden today is synthetic
  (`sample_clip` is a box, not a person, so the SP1/SP3 goldens honestly fake
  `process_episode`); the engine's own `MVI_3739` fixtures are the only real
  pixels in the suite. This is the milestone the synthetic goldens stand in for.
  **OR**
- **golden-canon armature** — the storyboard's dynamic-symmetry overlay (root
  rectangle + diagonals + reciprocals + the "eye" horizontals/verticals,
  `references/editing-canon.md`). Still unbuilt: `geometry.grid_lines` knows
  `thirds` and `phi` and **raises** on `golden-canon`, and `storyboard._overlay`'s
  palette has no entry for it — the vocabulary is accepted as a *static editorial*
  grid (`manifest.py:135`, `edl.py:69` both refuse it as a tracking target) but
  nothing draws it. ~~+ landmine lint~~ — **the lint half landed 2026-07-20**
  (see the Done entry above); the two were only ever paired here by proximity.

**Phase B is now closed (2026-07-18)** — the length re-time slice
(`docs/specs/2026-07-18-length-retime-design.md`) landed the last two
auto-fixes the pacing design had parked (§10): `build_reel`'s within-band
length-shortfall absorb and `edit_plan`'s pacing-gate back-edge. See the Done
entry above.

**Reel-loop deferrals still open** (design §8 non-goals,
`docs/specs/2026-07-11-reel-retry-loop-design.md`): `variety` auto-fix still
needs the front-half EDL fixer (`length` landed 2026-07-18 — see the Done
entry above); reprocess is sequential, not parallel; and the loop has no
resumability / Phase A.5 retry-state persistence.

## Deferred / open

- ~~vidstab-capable ffmpeg (`bash setup.sh --with-vidstab`)~~ — **the flag is
  gone and vidstab is baseline since 2026-07-20** (see the ffmpeg-baseline entry
  above): `ffmpeg-full` carries `libvidstab`, so 5.2 intake's `vidstabdetect`
  shake score gets its filter from a plain `bash setup.sh`. It remains a **hard**
  runtime gate (`vidstab.require()`, extracted from intake's old
  `_require_vidstab` when `process_episode` became a second consumer). ~~The
  *apply* half (`vidstabtransform`) is what remains unbuilt.~~ **The apply half
  landed 2026-07-20 too** (see the Done entry above): a pre-stage in
  `process_episode`, never a filter in `reframe`'s chain.
- §6.1a layer 3 (descriptor continuity re-match — mid-episode ID-switch
  repair) is now **unblocked**: the cast wiring it needed landed with cast →
  hero-pin (2026-07-16, see Done above). A different mechanism (per-frame
  descriptor jump + x-teleport + area jump ⇒ split the route, re-match the
  pieces) against a different failure mode than this slice fixed; the design
  assigns it to the process-episode plan as the natural follow-on.
- ~~cap-3 parallel fan-out remains deferred~~ — **landed 2026-07-18** (see the Done
  entry). `build_reel`'s loop-2 reprocess batch stays sequential by decision, not
  by oversight: batches are typically one or two culprits, so the fan-out's 1.70×
  has little to bite on there.

## External assets (outside this repo)

- **Golden fixture source (plan Task 9.5):** session footage + window map at
  `/Users/serg/Downloads/untitled folder/REEL_SOURCES.md` — footage (`MVI_*.MP4`,
  `DJI_*.MP4`, ~128 files) sits in that same folder. `MVI_3739.MP4` (the long
  ride) is the suggested fixture source.
- The Jul 3–5 montage session that this design was reverse-engineered from
  produced Reel A (ODESZA) and Reel B (Billie Eilish); real-footage validation
  happens when Sergei re-montages that footage — user-driven, not a milestone.

- **ffmpeg baseline — Task 7, the proof (2026-07-20)** — `bash setup.sh` run against
  the rewritten script: verified both filters, recorded `config/ffmpeg.env`, pinned;
  core `ffmpeg` untouched and `openai-whisper`/`summarize` still installed. Suite
  **1539 passed / 2 skipped** — exactly the two predicted (demucs opt-in, an SSL
  certificate failure unrelated to this slice). The six drawtext/vidstab skips are
  gone, which is design §5's trap proven closed rather than merely argued. **No
  golden moved**, so §2's "same version, same revision" argument survives its only
  real test. What did break was better: `test_intake_real_vidstab_shake` failed on
  its **first-ever execution** — libvidstab writes a BINARY `.trf` (magic `TRF1`) by
  default while `_parse_trf` reads the ASCII serializer, so the shake path had never
  worked on any machine and no machine could see it. Fixed with the filter's own
  `fileformat=ascii` rather than a reverse-engineered binary reader (guessing that
  layout risks silently wrong shake magnitudes — the §12 class); `_read_trf` now
  checks the magic on bytes so `_parse_trf`'s fail-loud promise is reachable at all,
  which it was not while `read_text()` raised `UnicodeDecodeError` several frames
  earlier. See design §12.
