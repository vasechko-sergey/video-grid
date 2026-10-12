# Montage Conveyor — Pipeline Map

Bird's-eye map of the full **16-stage** montage conveyor (design spec
[§4 flow](specs/2026-07-05-montage-skillset-design.md) / §5 skills). Tick a stage
when it ships. The detailed per-subsystem changelog lives in
[build-status.md](build-status.md); **this** file is the "where are we in the
whole cycle" view — update the status column and the phase checkboxes together.

_Last updated: 2026-10-12._

**Legend:** ✅ built · ◐ partial · ❌ not built · 🔜 next up

## The 16 stages (design §5)

| # | Stage | Output | Status | Module / note | Closed by phase |
|---|-------|--------|:------:|---------------|-----------------|
| 5.1  | using-montage (router) | routing + ensure-env | ✅ | `using-montage` SKILL conducts the built stages footage→reel with the three §4.1 checkpoints; `montage.py` inspector (`next_action`) drives resume-from-`next`; `edl_to_reel` fans out episodes across a bounded thread pool (`jobs`, default 3 — the measured knee, 2026-07-18). **No open sub-items.** | Router + curation |
| 5.2  | footage-intake | `FOOTAGE.json`+`.md` | ✅ | `intake.py`: probe + PySceneDetect + YOLO11-seg + vidstabdetect → activity-unit carve → score → phash cull → `FOOTAGE.json`/`.md` + `cast.json` (SP2); carving is **activity-anchored units** (an activity peak + its lead-in, may overlap) carrying `track_ids` — #3 slice 3a landed 2026-07-25, 3b `edit_plan` span-merge landed 2026-07-26; **parallel + resumable** (`--jobs`, per-clip `.intake_cache`, `--fresh`; bad clip → `intake_report.json`) since 2026-07-25; all CV analysis now runs on a **decode-once 960 proxy** per clip (2026-08-01, ~300× on 4K `vidstabdetect`; analysis-only — originals deliver, cache v3); motion is now **identity-consistent** (median displacement across shared track ids between samples, not the largest bbox's centre — a crowd's person-swap no longer reads as movement) and `score` is a **pool-relative percentile** produced by a separate Phase-2 `score_pool` pass, not a per-clip absolute blend (P3 S3, 2026-08-06, `CACHE_VERSION` 7→8); the carve window band is now a real intake parameter too — `--win-min`/`--win-max` (default `carve.DEFAULT_BAND` 1.2–4.0s) join `intake_cache.clip_key` so a different band is a cache miss, not silently-stale boundaries (`CACHE_VERSION` 8→9), and what was actually carved rides on `Footage.band` for `edit_plan`'s own reconciliation against a mood preset's `asl` floor (mood-contract, 2026-09-03) | — |
| 5.2b | contact-sheet | `SHEETS.md` | ✅ | `contact_sheet.py`: required; overview sheet + `strip` zoom | — |
| 5.3  | reel-brief | `SPEC.md` | ✅ | `reel_brief` SKILL → CLI + typed `Spec` (`scripts/lib/spec.py`) writes `SPEC.md`+`SPEC.json` atop project-init's machine subset (5.3) | Front-half authoring |
| 5.4  | trend-scan | `TRENDS.md` | ❌ | trend cache (TTL 7–10d) | Front-half authoring |
| 5.5  | music-and-mood | `MUSIC.json` | ✅ | beats-core (tempo/beat-grid/RMS energy) ✅ + start_offset intelligence (auto in-point: peak-energy window, vocal-pause start via demucs, **required since 2026-08-14** — the librosa mix-proxy fallback is deleted, it answered wrong rather than failing) ✅ + mood-match (local: rank a folder vs SPEC.mood → MUSIC_SHORTLIST) ✅ + sourcing (free/any, network) ✅ | **Phase B — music spine** |
| 5.6  | pacing | `PACING.md` | ✅ | pacing runs **after** edit-plan and FITS the existing cuts onto the coarsest grid level (beat/half-bar/bar/2-bar/phrase) within a ±half-beat allowance — the 2/4/8 ladder is gone (scenario-first pacing, 2026-07-24). The reel's music **outro** (where it ends, not which lines the cuts land on) is a separate fit that lives in 5.7 edit-plan, not here — see that row | **Phase B — music spine** |
| 5.7  | edit-plan | `EDL.md` | ✅ | `EDL.json` typed contract + `to_manifest_dict` bridge ✅ (SP1); `EDL.md` render + `edit_plan.py` (selection→projection→EDL) + `edit-plan` SKILL ✅ (SP3); a `selection.json` episode may reference a window range `"window": [i, j]` to merge adjacent activity units into one episode (3b, 2026-07-26); a shot-size **variety gate** refuses a cut using zero of a delivered-frame shot size the mood's `SPEC`-resolved preset wants when the footage offers ≥3 (`variety-gap`, overridable only by a written `variety_waiver` — mood-preset-variety, 2026-08-06); `edit_plan build` also reads `CONSTRAINTS.json` beside `project.json`, when present, and refuses (`constraint-violation`, no waiver, before the variety gate) a cut that breaks a user-stated `no_repeat`/`open_with`/`close_with`/`exclude` rule — editorial-constraint memory, 2026-08-07; a hand-authored `EDL.json` through `edl_to_reel`'s SP1 front door never passes through this gate. **Since 2026-08-14**, `edit_plan build --music MUSIC.json` (alongside `--pacing`) fits the reel's LENGTH to a bar line — `lib/outro.fit_outro`'s pure `gap`/`no-gap`/`unchanged` ladder moves only the LAST episode's `dur`, after pacing binds, so `reel_dur == line + fade` starts `mix`'s existing bookend fade exactly on the line with no ffmpeg stage touched (closes backlog #2 — see [the music-outro-fit design](specs/2026-08-14-music-outro-fit-design.md)) | Front-half authoring |
| 5.8  | extract | `segments/<ep>_raw.mp4` | ✅ | `extract_edl` loop + §5.8 length gate ✅ (SP1); when an episode carries a `ramp`, a retime pre-stage now replaces `ep{i}_raw.mp4` **in place** with a one-pass `setpts`+`fps` retime before tracking ever runs — the same shape as 5.10's vidstab pre-stage and for the same reason: the route must be measured on the pixels that ship (speed ramp, 2026-08-09) | — |
| 5.9  | assemble-draft | `draft.mp4` | ✅ | draft CLI + typed helpers (scripts/draft.py, scripts/lib/draft.py) — concat of raw segments, canvas-fit, processing_notes labels + music bed (SP1b, 5.9) | Front-half authoring |
| 5.9b | **episodes-geometry + match-grade** | `GEOMETRY.json` + `MATCH.json` | ✅ | `edl_to_reel --stop-after-geometry` extracts, stabilizes, tracks and gates every episode and **stops before any encode**, writing `GEOMETRY.json` (the stripped manifest, the frozen route, the source reframe will consume, and a `{source,start,dur,ramp}` cut identity); `match_grade build --geometry` then measures each episode's own tracked CROP through `reframe.plan_render` — the pixels that ship — computes ONE common reel tone target and authors `tone_src`/`tone_dst`; `edl_to_reel --from-geometry` renders over those frozen routes with the EDL's current colour block, refusing a cut / build dir / engine that moved. **Both stages are `required`.** `probe grade --geometry` sits in the gap so a grade converges on stills instead of a reel per attempt (grade-shipped-pixels, 2026-08-30 — delivered anchor spread 44/64/120 → 11/6/2). **Since 2026-09-15 each of the three anchors can come from a region the author named**: `REGIONS.json` beside `project.json`, found by convention with no flag (`ReelGeometry.project` records where to look), declares `toe`/`mid`/`shoulder` × `subject`/`background`/`crop` plus the author's own noun for it; `MATCH.md` prints one row per anchor with the region's measured frame fraction and any of three named fallbacks (`no-route`, `too-small`, `unorderable`). Measured on the real reel, taking the toe from the subject moves the common target's p5 by **−23.2** luma on delivered clips and **−33.7** on source against `MATCH_EPS` 4.0, while the mid moves +1.5 and the shoulder 0.0 — and the design's own first noun, `skin`, was measured and **rejected** (cross-episode sd 34.3, worse than the crop's own p95). Absent the file, the same EDL and the same target, byte for byte (the two REPORTS are not — `MATCH.md`/`MATCH.json` gain the declaration line and the per-anchor table on every run, declared or not). See [the named-regions design](specs/2026-09-15-named-regions-design.md) | — |
| 5.10 | **process-episode** 🔒 | `out/<ep>.mp4` | ✅ | track + reframe + storyboard + layouts, orchestrated (loop-1); reframe now applies a per-episode colour **actuator** — 7 grade knobs + an additive auto white-balance + the non-linear `tone` profile-transfer, composed by `color.grade_chain` and riding reframe's **one** encode (colour-as-a-stage, 2026-07-27; the design-§10 match-grade **conductor** — computes one common reel tone target and auto-authors `tone_src`/`tone_dst` on the episodes that deviate — landed 2026-07-30 as its own post-EDL stage, `match-grade`: see [the match-grade conductor design](specs/2026-07-30-matchgrade-conductor-design.md). Since 2026-08-30 it measures each episode's **tracked crop**, not a whole source frame at the window midpoint, which is why it now runs at stage 5.9b between the two halves of the geometry split rather than before tracking — and it is **required**, not optional ([grade-shipped-pixels](specs/2026-08-30-grade-shipped-pixels-design.md))); the crop's savgol smoothing window is now specified in **seconds** and resolved per-clip against its own fps (`pathsmooth.window_frames`, 30fps→7 unchanged, 60fps→15), and an authored `lead` composition is honoured off the subject's own net travel even where `motion.classify` lands in its ambiguous zone, instead of silently rendering as `center` (path-quality cluster, 2026-07-29); a frame move is now one of exactly two things — **subject-anchored** (a `zoom` push-in/pull-out, whose rect is chosen per route sample by the SAME composition rule as any tracked crop, so it stays inside every check) or **scenery** (a `pan`, whose route-less generated path is legitimate only over a window intake MEASURED as holding no people — `FootageWindow.present`, refused above `PAN_PRESENCE_MAX` in `edit_plan.window_to_episode`, never accepted on the author's word) — see [the subject-anchored-moves design](specs/2026-08-08-subject-anchored-moves-design.md) | — |
| 5.11 | episode-postcheck (gate) | — | ✅ | `check_episode` — mechanical gates + a **blocking** `grade_damage` check (renamed from `color_fidelity`, 2026-08-31: the declared grade rendered twice — as declared, and with every colour knob at identity — and judged on whether it DESTROYED information, Shannon entropy of the luma histogram against `CheckSpec.entropy_floor` — 0.90 by default, movable only through the operator's `GATES.json` with a written reason (threshold-surface, 2026-10-05) — not on how far it moved the tracked subject's colour; the old subject median CIEDE2000, 2026-08-28, survives as an advisory DESCRIPTION read by the QC judge, never a verdict — and since 2026-09-16 that description rides `grade_damage`'s OWN `(graded, plain)` render pair rather than re-decoding the raw source and the shipped clip in a different geometry at a different time set, NAMES the pixels it read (`region` `subject`/`crop`, `region_fraction`, and a `region_fallback` of `too-small`/`no-route` resolved by the same `lib/regions` rule the tone stage authors a grade with — so a pan now gets a real crop reading where it used to report `null`), carries `background_delta_e`/`background_fallback` as a contamination check when the subject supplied the reading, and reports the three signed components with NO ranking of them: `dominant` flipped on three of the four real episodes between 3 and 5 samples, with one exact tie broken by tuple order, and is deleted); the `jitter` gate is now **route-aware** — it discounts the subject's own backtrack (box-filtered over the route's own cadence, `_route_window`) before scoring the crop, and grades an authored `lead` against the same net-travel direction reframe used (path-quality cluster, 2026-07-29); framing/continuity/`grade_damage` all apply to a **subject-anchored** zoom exactly as to any tracked episode — the `freedom == 0` editorial-only arm now excuses only an unzoomed episode, since a push-in creates the freedom a zero-freedom layout lacked — while a **scenery** pan keeps framing/continuity reporting `editorial-only`/`not-checked` (now because intake measured the shot subject-less, not because the author claimed it — subject-anchored moves, 2026-08-08); `grade_damage` is not one of those two — it runs regardless, reporting a real entropy verdict plus a real crop-wide dE00 description at `region_fallback: "no-route"` (sensor-provenance, 2026-09-16) | — |
| 5.12 | audio-mix | `out/audio` | ✅ | music-only mix ✅ + ambient ducking ✅ + SFX whoosh ✅ (synth whoosh on major transitions, `ReelManifest.sfx`); §5.12 complete. **Since 2026-08-13** the bookend fade moved off the music fragment onto the MIXED stem (`mix(fade=)`, default 0.5s) — fading only the fragment let `_mix_graph`'s ambient sidechain (keyed on the music) RELEASE as the music fell, swelling the nat-sound into the black; `build_reel` now passes `EDL.look.fade` when a look authors one, so the audio and video bookends share one number — see [the cinematic-look design](specs/2026-08-13-cinematic-look-design.md) §5 | **Phase B — music spine** |
| 5.13 | reel-final-check (gate) | review | ✅ | **Mechanical half ✅ (complete)** — `check_reel`: black/length/variety + loudness + **`grade_faithful`** (renamed from `tone_match`, 2026-08-31 — hard, three frames per episode read off the MASTER against the profile that episode's OWN full declared chain predicts, not a common target solved with every other knob at identity; every episode is judged now, not only ones bound to a target; `ReelCheckSpec.grade_residual_max = 4.0` replaces `tone_match_max = 12.0`; escalates to `process-episode`, not `match-grade` — the pixels did not get the declaration, so the remedy is a re-render; cross-episode agreement is no longer gated at all, surviving only as the advisory `target_dev`; since 2026-09-16 the report also states `frames`, the count actually read from the master per episode — `0` when nothing could be predicted — so a silently changed N is visible rather than inferred from a constant), **`chroma_spread`** (advisory, 2026-09-17 — how far apart the reel's episodes are in what the grade did to their COLOUR: the signed CIEDE2000 dC\*/dH\* between each episode's ungraded and graded render of the SAME crop, `ReelCheckSpec.chroma_spread_max = 5.0`; deliberately not a chroma TARGET — an absolute cross-episode chroma statistic cannot separate a grade mismatch from a different amount of ocean on this footage, design §0.4 — so it measures only whether the grade treated the episodes alike, closing the last open half of R2.1 by measurement rather than by the target the row asked for; see [the chroma-spread design](specs/2026-09-17-chroma-spread-design.md)), beat + `safe_zones` + `key_action` + `pad_bars` + `transitions` (all advisory — route-geometry/PathMeta checks; the last three landed 2026-07-17). The across-cut colour check (`color_across_cuts`) that used to sit in this list is **retired, not tightened** — it compared two different shots, not a grade against a reference, and no threshold separated the two cases (2026-08-29, see [the colour-convergence-retire design](specs/2026-08-29-colour-convergence-retire-design.md)). Editorial half ✅ (2026-07-18) — reel-review SKILL dispatches a fresh reviewer subagent → typed REVIEW.json (Finding/Review), human-gated at CP3, now judging a `colour` axis (routed to `match-grade`) beside the seven editorial ones — the reader that replaced the deleted mechanical check; **required, not optional, since 2026-08-04** — `montage.py`'s stage table flips `reel-review` to `kind="required"`, so a run is finished when `next_action`'s `next` is `null`, not merely when `delivered` is true (design [2026-08-04-attested-run-design.md](specs/2026-08-04-attested-run-design.md) §8). | Phase B (audio) + Editorial |
| 5.14 | **deliver** | `out/REEL_*.mp4` | ✅ | `deliver.py` — one encode, versioned, hard gate; since 2026-08-04 also **binds** the `ReelReport` to the master it ships (refuses an unbound or mismatched digest — closes fixes-backlog #13) and writes a `REEL_v{n}.attest.json` provenance sidecar beside the encode (both engine stamps, the master/report/reel digests, the EDL's state, every loosened check threshold, and — since 2026-10-05 — every threshold an operator authored in `GATES.json`, with its scope, whether it can block, and its reason); `montage status`/`montage verify` read it back (see [the attested-run design](specs/2026-08-04-attested-run-design.md)). **Since 2026-08-08 the router's single `deliver` step is three required stages**, not one: `episodes` (since the 5.9b geometry split, `edl_to_reel --from-geometry` renders every episode over the route `episodes-geometry`/`match-grade` already froze, writes `EPISODES.json`, and stops at the QC seam — `--stop-after-episodes` still exists as the single-phase, hand-driven equivalent that skips the geometry split), `episode-qc` (one fresh judge subagent per episode, cap 3, judges the delivered clip's composition/colour/impression/path/hero off a frame strip + storyboard + the new `lib/naturalness.py` colour sensor; `episode_qc build` stamps every verdict with the clip's own sha256, never the judge's claim), and `deliver` itself (`edl_to_reel --from-episodes` gates on `EPISODE_QC.json` beside it — incomplete/stale/blocking all refuse before any ffmpeg — then assembles). A reel is never assembled over an episode nobody judged. **Since 2026-08-18 it is never DELIVERED over one either**: `build_reel` refuses (`episode-qc-reprocessed`) when its retry loop re-rendered an episode and the manifest says `episode_qc.state == "judged"` — the reprocess overwrites the very `ep{i}.mp4` the verdict was digested from, so the router re-judges exactly those indices and the second pass delivers. The attestation still records `reprocessed_after`, and `montage verify` reads a judged delivery with a non-empty one as `stale`. The `absent` paths (`build_reel`'s own CLI, single-command `edl_to_reel`) still reprocess and still ship unjudged, by design. See [the re-judge design](specs/2026-08-18-episode-qc-rejudge-design.md). See [the episode-qc design](specs/2026-08-08-episode-qc-design.md). **Since 2026-08-13 the reel's look** (a plateau vignette + a bookend fade, `EDL.look` → `ReelManifest.look`, defaulted per mood by `MoodPreset.look`) rides this SAME one encode, exactly like titles — a `-loop 1 -i` mask input plus `-filter_complex` when a vignette is authored, unchanged `-vf` (byte-identical argv to before looks existed) otherwise; `check_reel` runs on the master *before* this stage applies it, so no PRIOR gate ever sees the look that shipped — see [the cinematic-look design](specs/2026-08-13-cinematic-look-design.md). **Since 2026-08-15 `deliver` closes that gap itself**: after the encode, a post-encode look gate (`lib/lookcheck.py`) samples the delivered `REEL_v{n}` against the master at the same timestamps and hard-refuses when a declared vignette/fade did not reach the pixels (titles get a `not-checked` finding, not a check yet) — the file stays on disk to look at, but no attestation is written, so `montage status` reports it unattested. No waiver. See [the frame-probe-look-gate design](specs/2026-08-15-frame-probe-look-gate-design.md) §7. | — |
| 5.15 | ffmpeg-recipes (reference) | — | ✅ | recipes docs | — |
| 5.16 | titles (optional) | `TITLES.json` | ✅ | agent-authored hook/caption/ending text (`titles.py`/`fonts.py` name-resolve); **renders at deliver** — no titled intermediate; titles now render **motion** — `fade` alpha ramps, `reveal="word"`/`"stair"` (one drawtext per step, each baked at its FINAL x from measured PIL font metrics — never a naive per-word re-centre) — and **colour** (`color`/`scale`/`line_spacing`), and lay out against the **platform's own safe zone** (`y_exprs(platform)` reads `safe_zone_for`, the same table `check_reel` judges the subject against, replacing a frozen generic-zone constant that disagreed with it); `deliver`/`build_reel` thread `platform` through (titles-animations, 2026-07-29); a fourth style, `outline-bold` (heavier border + offset shadow, for bright/busy backgrounds where plain `outline` disappears), landed 2026-08-13 alongside the reel's **look** — vignette overlay, then this stage's drawtext, then the bookend fade share deliver's one filtergraph in that order, measured (a fade placed before drawtext burns a title on over a black frame) — see [the cinematic-look design](specs/2026-08-13-cinematic-look-design.md) | — |

**Runtime utility, not a stage:** `verify-runtime` (2026-08-01) is a startup
preflight that gates `using-montage`'s step 0 — it asserts the `setup.sh`
baseline contract and stops the conveyor before project-init on any required
gap. Deliberately **not** in `V1_STAGES`; produces no run artifact. See
[the verify-runtime design](specs/2026-08-01-verify-runtime-design.md).

**Also not a stage:** `probe` (2026-08-15) is an on-demand tool, not a
conveyor stage — no `V1_STAGES` row, no run artifact `using-montage` tracks.
`probe grade` renders 3 frames of ONE episode through `reframe`'s own chain over
its frozen route, so a colour grade converges (edit `selection.json`, re-run
`edit_plan build`, probe, look, repeat — never hand-edit `EDL.json`, which is
stamped and whose tamper refusal `probe`'s own `--edl` inherits) without paying
for a re-render of the episode, let alone the reel. Two modes since 2026-08-30:
`--geometry GEOMETRY.json` is the normal one, run in the 5.9b gap **before
anything has ever been encoded** (it always applies the EDL's current colour
block, and reports `drift_checked: false` because no rendered sidecar exists yet
to check against); `--episodes EPISODES.json --edl EDL.json` is the
already-rendered path, run between `episodes` (5.14's first sub-stage) and
`episode-qc` whenever a QC verdict — or the agent's own eye — flags colour, and
it keeps the drift oracle. `probe.json`'s `tone_profile` is ONE pooled
`(p5, p50, p95)` across all the probe's frames, not a reading per frame, so it
reads straight into a `tone_src`/`tone_dst` pair. `probe look` re-runs the
OTHER half by hand: the post-encode look-gate check `deliver` (5.14) now
hard-refuses on, sampling a delivered reel against its master for a declared
vignette/fade that did not reach the pixels (a declared titles track gets a
`not-checked` finding, not a check yet — §11). See
[the frame-probe-look-gate design](specs/2026-08-15-frame-probe-look-gate-design.md).

## Automation loops (design §4.1 ladder)

| Loop | Where | Mechanism | Status |
|------|-------|-----------|:------:|
| **Loop-1** — episode self-check → reprocess-until-pass/escalate | around 5.10/5.11 | `process_episode` + `orchestration.escalation` | ✅ |
| **Loop-2** — reel check → reprocess culprit episode → reassemble → recheck | around 5.13/5.14 | `build_reel` + `reel_orchestration.next_action` (**Phase A.5**) | ✅ |

Two human checkpoints stay unautomated **by design** (design §4.1). Both gates are
**built** — they are meant to stay human, not waiting on a slice: **music choice**
(skill proposes a ranked shortlist, human picks — `music-match` / `music-source`)
and **episode choice** (skill proposes, human swaps — `using-montage` CP2 "EDL
approval + curation"; the swap is `selection.json` + a re-run, never a hand-edited
`EDL.json`).

## Remaining work — blockers & critical path

A dependency view of the 16 stages: what's left, what **hard-blocks** it, what it
unblocks. `(soft)` = a quality input, not a build prerequisite. Complements the
status table above.

| # | Stage | St | Left to build | Blocked by (hard) · (soft) | Unblocks |
|---|-------|:--:|---------------|----------------------------|----------|
| 5.1 | using-montage router | ✅ | — (fan-out landed 2026-07-18) | — | autonomous v1 |
| 5.2 | footage-intake | ✅ | — (SP2, 2026-07-12) | — | 5.7, 5.3, 5.13 |
| 5.3 | reel-brief | ✅ | — (2026-07-12) | — | 5.7, 5.5 mood |
| 5.4 | trend-scan | ❌ | `TRENDS.md` — YAGNI | none | (soft) 5.5 rank · 5.6 · 5.7 · 5.13 editorial |
| 5.5 | music-and-mood | ✅ | — (2026-07-14) | — | 5.6 |
| 5.6 | pacing | ✅ | — (2026-07-14) | — | (soft) 5.7 |
| 5.7 | **edit-plan** | ✅ | — (SP3, 2026-07-12) | — | **5.1 + autonomy** |
| 5.8 | extract | ✅ | — (SP1) | — | — |
| 5.9 | assemble-draft | ✅ | — (2026-07-13) | none — **5.8 ✅** | QA preview |
| 5.9b | episodes-geometry + match-grade | ✅ | — (grade-shipped-pixels, 2026-08-30; named regions, 2026-09-15) | — | crop-accurate colour; author-named anchor regions; `probe grade --geometry` |
| 5.10 | process-episode 🔒 | ✅ | — | — | — |
| 5.11 | episode-postcheck | ✅ | — | — | — |
| 5.12 | audio-mix | ✅ | — (2026-07-15) | — | richer mix |
| 5.13 | reel-final-check | ✅ | — (2026-07-18) | none · (soft) 5.4 for the "trend flavor" criterion | tighter gate |
| 5.14 | deliver | ✅ | — (now three required router stages: episodes → episode-qc → deliver, 2026-08-08) | — | — |
| 5.15 | ffmpeg-recipes | ✅ | — | — | — |
| 5.16 | titles | ✅ | — (2026-07-13) | — | reel-review CP polish |
| — | cast → hero-pin | ✅ | — (2026-07-16) | none — **5.2 cast.json ✅** | §6.1a layer 3 (continuity re-match) |

**Tally:** 15 ✅ · 0 ◐ · 1 ❌. Both automation loops closed. Every **mechanical**
check the conveyor runs is built, and §5.13's editorial half is now built too
(2026-07-18, the `reel-review` SKILL); what is left is only 5.4 (never started
— YAGNI), the one remaining ❌.

### Critical path to autonomous v1

```
5.2 footage-intake ✅ ──► 5.7 edit-plan ✅ ──► 5.1 using-montage ✅   = autonomy
        │                      ▲  ▲
        └─► 5.3 brief ─────────┘  │  (soft, quality)
    5.5 music ─► 5.6 pacing ──────┘
```

> **Run order vs. dependency (scenario-first pacing, 2026-07-24):** the arrows above are
> the *quality* dependency (pacing informs the final cut), not the run order. The conveyor
> now runs **edit-plan (5.7) BEFORE music (5.5) / pacing (5.6)** — a two-pass edit-plan:
> build the cuts at their material length, let pacing FIT a grid to them, then
> `edit_plan build --pacing` applies the fit. An episode's length comes from its own shot,
> never from a slot invented ahead of the footage.

**The entry-skill closes the autonomous v1 chain:** footage→EDL→reel now runs from
one `using-montage` invocation — it conducts project-init → footage-intake →
edit-plan → edl_to_reel with the three §4.1 checkpoints, resuming from `montage
next_action`. **Stage 5.1 has no open sub-items left**: the cap-3 **parallel**
episode fan-out landed 2026-07-18 (`edl_to_reel` runs episodes across a bounded
thread pool, 1.70× measured). Everything else was parallel **quality**, and most
of it has since shipped (B4 pacing, 5.9 draft, 5.12 ambient+SFX, 5.13 now fully
closed — `safe_zones` 2026-07-16 + `key_action`/`pad_bars`/`transitions`
2026-07-17 + the agent review 2026-07-18 — cast→hero-pin 2026-07-16, and the
Phase B tail — the two length auto-fixes — 2026-07-18). Genuinely open on the
quality side: **5.4 trend-scan** (never started — YAGNI) and the **§7
misc-engine tail** (see the roadmap below).

## What produces a reel today

The **spine 5.10 → 5.14 is complete** and both automation loops are closed, and
now a hand-authored `EDL.json` drives the **whole conveyor**: `edl_to_reel`
bridges each EDL row to a manifest (`to_manifest_dict`), `extract_edl` (§5.8)
cuts every episode's window, `process_episode` runs per episode, and the
assembled `ReelManifest` goes through `build_reel` to a delivered `REEL_v1.mp4`
**with music** end-to-end — `build_reel` mixes a music-only stem once the
picture passes (seek + afade + two-pass loudnorm −14 LUFS), `check_reel` gates
on loudness (hard) and reports beat alignment (advisory, non-blocking), and
`deliver` muxes the stem into the export (stream-copy, preserving the measured
loudness). Segments and per-episode manifests are **no longer hand-supplied**
outside of tests. What's still missing to a *full* reel: **5.4 trend-scan** (the
last front-half stage — YAGNI); the audio spine is complete, with mood-match +
sourcing (5.5), pacing (5.6) and ambient + SFX (5.12) all shipped, and §5.13's
reel-final-check (mechanical **and** editorial) is now fully green. When a
reel carries no `music`/`audio` (the silent path, unchanged
from Phase A.5), `check_reel` honestly reports `passed=None` (`"not-checked"`)
for beat/loudness rather than a silent pass; `safe_zones` now reports an
advisory pass/False computed from the per-episode route geometry, or
`passed=None` (`"not-checked"`) when a reel carries no geometry.

## Phase roadmap

Phase-level shape only. For what happens next, in order, see the queue:
[backlog.md](backlog.md).

### Done

- [x] **Core engine** — track → reframe → storyboard → check; golden fixture on real footage.
- [x] **process-episode orchestrator** — loop-1 shell (contradiction detect + retry ladder + escalation).
- [x] **engine dataclass-hardening** — typed wire-contracts + config-specs; aspect/resolution-agnostic `Delivery`.
- [x] **project-init** — `purpose→canvas` / `quality→delivery`; episode inheritance; `native` default.
- [x] **layouts** — crop × rect × filler; `fit` (blur/solid) + `insert`; the `path.meta.json` sidecar.
- [x] **reel back half** — assemble (lossless master) → check_reel (mechanical gate) → deliver (one encode, versioned).
- [x] **reel retry loop (Phase A.5)** — `build_reel` loop-2 driver; escalate-wins / no-silent-pass. Carried a delivered-space `color_correct` convergence arm until 2026-08-29, when it was retired (not repaired) with the reel-level colour check that drove it — see [the colour-convergence-retire design](specs/2026-08-29-colour-convergence-retire-design.md); the loop itself stays, now reprocessing only a black-frame hit.
- [x] **Phase B — music spine** — beats-core + music-only mix + loudness/beat gates + autonomous sourcing (free/any rights lanes) + the pacing energy spine + ambient ducking + SFX whoosh + the length re-time tail (`build_reel`'s within-band shortfall absorb + `edit_plan`'s pacing-gate back-edge, both landed 2026-07-18 — see [the length re-time design](specs/2026-07-18-length-retime-design.md)). Closed.

### Upcoming

- [ ] **Front-half authoring** ◐ — SP1 (extract spine, 2026-07-11) + SP2 (footage-intake, 2026-07-12) + SP3 (edit-plan, 2026-07-12) done: `EDL.json`→delivered reel, `intake.py` scans raw clips → `FOOTAGE.json`/`.md` scored moment-windows + `cast.json` hero registry, and now `edit_plan.py` projects those windows (via an agent `selection.json`) into the `EDL.json`+`EDL.md` that drives SP1. Remaining: SP4 (trend-scan).
- [x] **Router + curation** ✅ — the **episode-choice human loop is built** (`using-montage` CP2 "EDL approval + curation", 2026-07-12) and stays human by design; `cast.json` ships (5.2, 2026-07-12) and is read back by the cast → hero-pin slice (2026-07-16); and the last item, stage 5.1's **cap-3 parallel fan-out**, landed 2026-07-18 — `edl_to_reel` runs its per-episode loop across a bounded thread pool (`jobs`, default 3). The 3 is measured, not assumed: 1.70× at 3 and nothing at 4, on six real windows through the full `process_episode`. Closed.
- [x] **Editorial reel-final** — stage 5.13's second half. **Both halves are now built**: the mechanical half — `safe_zones` ✅ (2026-07-16) + `key_action`/`pad_bars`/`transitions` ✅ (2026-07-17, all **advisory** — see `docs/specs/2026-07-17-reel-final-editorial-checks-design.md`) — and the **agent review** proper ✅ (2026-07-18, Slice B): the `reel-review` SKILL dispatches a fresh reviewer subagent that judges the delivered reel against SPEC's idea/mood/hook/ending/spine (modelled on `requesting-code-review`) and emits typed findings (`REVIEW.json`), human-gated at CP3 — see `docs/specs/2026-07-18-reel-review-editorial-design.md`. **§5.13 is fully closed.** Its "classic base **and** trend flavor" sub-criterion (`trend_flavor`) is still judged at forced low confidence pending **5.4** — no source of truth until trend-scan lands.
- [ ] **Misc engine** — the tail of the design's §7 five-names list, re-read through the layouts design's crop × rect × filler model. **`fit-solid` landed 2026-07-18** — exactly as the design predicted, a **filler literal**, not a branch (`BACKGROUNDS` gained `solid`, and `reframe` gained a synthesized-`color` background producer alongside the existing blur composite); the one thing the design had not fully priced in was that it **forced the mode rename** `fit-blur` → `fit`, since a second filler made the old mode name self-contradictory the moment an EDL author had to write `{"layout": "fit-blur", "background": "solid"}` — see [the fit-solid design](specs/2026-07-18-fit-solid-design.md). **`pan` landed 2026-07-19** — and, unlike `fit-solid`, it turned out **not to be a layout at all**: its preset row (`fill`'s row, exactly) was already expressible with `crop_scale < 1`, so what was missing was never a mode, only a second, *generated* source for the crop's x(t) — `PanSpec` (two fractions of horizontal freedom) plus `reframe.generate_pan_path`, used instead of a tracked route, with `PathMeta.pan` carrying the provenance so `check_episode`/the contradiction gate never mistake a generated path for an observation — see [the pan design](specs/2026-07-19-pan-design.md). **Stabilization's apply half landed 2026-07-20**: `vidstabtransform` now runs as a pre-stage in `process_episode` — never a filter inside `reframe`'s own chain, because the route is measured on unstabilized pixels and a crop placed from it against transformed pixels would re-inject exactly the shake vidstab removed (see [the stabilize-apply design](specs/2026-07-20-stabilize-apply-design.md) §1) — `stabilize: true` is authored in the EDL (`EDLEpisode.stabilize` → `to_manifest_dict`) and honored end to end. **The tracking-degradation ladder landed 2026-07-21**: an unpinned episode whose route comes back empty (or whose primary tracker is unavailable) now falls to `scripts/lib/flow.py`'s optical-flow centroid tracker (cv2, no ML), then to `scripts/lib/keyframes.py`'s sparse marks + interpolation (the `--keyframes` answer channel), each rung stamped on `TrackMeta.degraded` (`None`/`"flow"`/`"manual"`) — not the reframe-param retry ladder in `orchestration.py`, which was already built; see [the tracking-ladder design](specs/2026-07-21-tracking-ladder-design.md). **Post-occlusion ID-switch stitching landed 2026-07-28**: `build_route` now splices a hero ByteTrack dropped through an occlusion and re-acquired under a fresh id back into ONE route, instead of leaving the crop frozen past the switch, recording the merged ids as `TrackMeta.stitched` (see [the track-stitch design](specs/2026-07-28-track-stitch-design.md)). What's left of the five-names list now: **`split`** is the only genuine remaining *layout* (two sources → two rects; changes the manifest's shape) — the sole remaining item.

---

See also: [build-status.md](build-status.md) (detailed changelog + next action),
[CLAUDE.md](../CLAUDE.md) (doc registry), design spec
[§4 pipeline flow / §5 skills](specs/2026-07-05-montage-skillset-design.md).
