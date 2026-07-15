# Build Status

What is built, what is next, and the external assets the build depends on.
**Update after every task** — tick the plan's checkboxes and add/adjust the
relevant bullet here in the same commit.

_Last updated: 2026-07-15._

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
  [`docs/specs/`](./spec/); anna-auth-style standards adopted
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
  hints. **Deferred (NOT built):** descriptor→manifest hero-pin wiring (a later
  plan — `orch.is_seed_pin` still bbox-only), SP1b `draft.mp4`, SP3 authoring,
  SP4 trend-scan.

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

## Next action

- **Front-half continuation — trend-scan, then the real-footage v1 gate**
  (`TRENDS.md` cache, §5.4 — low-priority/YAGNI) — the only front-half stage
  left now that SP1b (assemble-draft, DONE 2026-07-13) has shipped; once it's
  built (or knowingly skipped) the front half is complete enough to run the
  whole `using-montage` conveyor end-to-end on Sergei's real footage — the
  milestone the synthetic goldens stand in for today. **OR**
- **cast → hero-pin wiring** — thread `cast.json` descriptors into episode
  manifests so `orch.is_seed_pin` accepts a cast name (today bbox-only); the
  descriptor continuity re-match (design §6.1a) then has its registry. **OR**
- **Phase B remainder — pacing retry-time auto-fix** (`docs/specs/2026-07-14-pacing-design.md`
  §10 role 2): the one open Phase-B item left now that B1+B2 (music spine,
  DONE 2026-07-11), start-offset intelligence (DONE 2026-07-13), mood-match
  (DONE 2026-07-14), networked sourcing (DONE 2026-07-14), B4 pacing (DONE
  2026-07-14), ambient ducking (DONE 2026-07-15), and SFX whoosh (DONE
  2026-07-15, **closing §5.12**) have all landed — `build_reel`'s `length`
  failure re-timing the spine, needs `build_reel`/`reel_orchestration` work.
  **OR**
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
- **cap-3 parallel fan-out** — the one open 5.1 sub-item now the `using-montage`
  entry-skill has shipped (2026-07-12): parallelise `edl_to_reel`'s sequential
  per-episode `process_episode` loop (concurrency cap 3, design §5.10). **OR**
- **golden-canon armature + landmine lint** — a check that the banned patterns
  (`lutrgb`, `-ss` before `-i`) cannot re-enter the filtergraphs.

**Reel-loop deferrals still open** (design §8 non-goals,
`docs/specs/2026-07-11-reel-retry-loop-design.md`): `variety`/`length`
auto-fix needs the front-half EDL/pacing fixers (not built yet); reprocess is
sequential, not parallel; and the loop has no resumability / Phase A.5
retry-state persistence.

## Deferred / open

- vidstab-capable ffmpeg before stabilization (`bash setup.sh --with-vidstab`).
- descriptor continuity re-match needs ingestion's cast.json.
- cap-3 parallel fan-out remains deferred — the `using-montage` entry-skill shipped
  (2026-07-12); parallelising `edl_to_reel`'s per-episode loop is the open sub-item.

## External assets (outside this repo)

- **Golden fixture source (plan Task 9.5):** session footage + window map at
  `/Users/serg/Downloads/untitled folder/REEL_SOURCES.md` — footage (`MVI_*.MP4`,
  `DJI_*.MP4`, ~128 files) sits in that same folder. `MVI_3739.MP4` (the long
  ride) is the suggested fixture source.
- The Jul 3–5 montage session that this design was reverse-engineered from
  produced Reel A (ODESZA) and Reel B (Billie Eilish); real-footage validation
  happens when Sergei re-montages that footage — user-driven, not a milestone.
