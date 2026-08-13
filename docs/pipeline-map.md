# Montage Conveyor — Pipeline Map

Bird's-eye map of the full **16-stage** montage conveyor (design spec
[§4 flow](specs/2026-07-05-montage-skillset-design.md) / §5 skills). Tick a stage
when it ships. The detailed per-subsystem changelog lives in
[build-status.md](build-status.md); **this** file is the "where are we in the
whole cycle" view — update the status column and the phase checkboxes together.

_Last updated: 2026-08-13._

**Legend:** ✅ built · ◐ partial · ❌ not built · 🔜 next up

## The 16 stages (design §5)

| # | Stage | Output | Status | Module / note | Closed by phase |
|---|-------|--------|:------:|---------------|-----------------|
| 5.1  | using-montage (router) | routing + ensure-env | ✅ | `using-montage` SKILL conducts the built stages footage→reel with the three §4.1 checkpoints; `montage.py` inspector (`next_action`) drives resume-from-`next`; `edl_to_reel` fans out episodes across a bounded thread pool (`jobs`, default 3 — the measured knee, 2026-07-18). **No open sub-items.** | Router + curation |
| 5.2  | footage-intake | `FOOTAGE.json`+`.md` | ✅ | `intake.py`: probe + PySceneDetect + YOLO11-seg + vidstabdetect → activity-unit carve → score → phash cull → `FOOTAGE.json`/`.md` + `cast.json` (SP2); carving is **activity-anchored units** (an activity peak + its lead-in, may overlap) carrying `track_ids` — #3 slice 3a landed 2026-07-25, 3b `edit_plan` span-merge landed 2026-07-26; **parallel + resumable** (`--jobs`, per-clip `.intake_cache`, `--fresh`; bad clip → `intake_report.json`) since 2026-07-25; all CV analysis now runs on a **decode-once 960 proxy** per clip (2026-08-01, ~300× on 4K `vidstabdetect`; analysis-only — originals deliver, cache v3); motion is now **identity-consistent** (median displacement across shared track ids between samples, not the largest bbox's centre — a crowd's person-swap no longer reads as movement) and `score` is a **pool-relative percentile** produced by a separate Phase-2 `score_pool` pass, not a per-clip absolute blend (P3 S3, 2026-08-06, `CACHE_VERSION` 7→8) | — |
| 5.2b | contact-sheet | `SHEETS.md` | ✅ | `contact_sheet.py`: required; overview sheet + `strip` zoom | — |
| 5.3  | reel-brief | `SPEC.md` | ✅ | `reel_brief` SKILL → CLI + typed `Spec` (`scripts/lib/spec.py`) writes `SPEC.md`+`SPEC.json` atop project-init's machine subset (5.3) | Front-half authoring |
| 5.4  | trend-scan | `TRENDS.md` | ❌ | trend cache (TTL 7–10d) | Front-half authoring |
| 5.5  | music-and-mood | `MUSIC.json` | ✅ | beats-core (tempo/beat-grid/RMS energy) ✅ + start_offset intelligence (auto in-point: peak-energy window, vocal-pause start via opt-in demucs / librosa proxy) ✅ + mood-match (local: rank a folder vs SPEC.mood → MUSIC_SHORTLIST) ✅ + sourcing (free/any, network) ✅ | **Phase B — music spine** |
| 5.6  | pacing | `PACING.md` | ✅ | pacing runs **after** edit-plan and FITS the existing cuts onto the coarsest grid level (beat/half-bar/bar/2-bar/phrase) within a ±half-beat allowance — the 2/4/8 ladder is gone (scenario-first pacing, 2026-07-24) | **Phase B — music spine** |
| 5.7  | edit-plan | `EDL.md` | ✅ | `EDL.json` typed contract + `to_manifest_dict` bridge ✅ (SP1); `EDL.md` render + `edit_plan.py` (selection→projection→EDL) + `edit-plan` SKILL ✅ (SP3); a `selection.json` episode may reference a window range `"window": [i, j]` to merge adjacent activity units into one episode (3b, 2026-07-26); a shot-size **variety gate** refuses a cut using zero of a delivered-frame shot size the mood's `SPEC`-resolved preset wants when the footage offers ≥3 (`variety-gap`, overridable only by a written `variety_waiver` — mood-preset-variety, 2026-08-06); `edit_plan build` also reads `CONSTRAINTS.json` beside `project.json`, when present, and refuses (`constraint-violation`, no waiver, before the variety gate) a cut that breaks a user-stated `no_repeat`/`open_with`/`close_with`/`exclude` rule — editorial-constraint memory, 2026-08-07; a hand-authored `EDL.json` through `edl_to_reel`'s SP1 front door never passes through this gate | Front-half authoring |
| 5.8  | extract | `segments/<ep>_raw.mp4` | ✅ | `extract_edl` loop + §5.8 length gate ✅ (SP1); when an episode carries a `ramp`, a retime pre-stage now replaces `ep{i}_raw.mp4` **in place** with a one-pass `setpts`+`fps` retime before tracking ever runs — the same shape as 5.10's vidstab pre-stage and for the same reason: the route must be measured on the pixels that ship (speed ramp, 2026-08-09) | — |
| 5.9  | assemble-draft | `draft.mp4` | ✅ | draft CLI + typed helpers (scripts/draft.py, scripts/lib/draft.py) — concat of raw segments, canvas-fit, processing_notes labels + music bed (SP1b, 5.9) | Front-half authoring |
| 5.10 | **process-episode** 🔒 | `out/<ep>.mp4` | ✅ | track + reframe + storyboard + layouts, orchestrated (loop-1); reframe now applies a per-episode colour **actuator** — 7 grade knobs + an additive auto white-balance + the non-linear `tone` profile-transfer, composed by `color.grade_chain` and riding reframe's **one** encode (colour-as-a-stage, 2026-07-27; the design-§10 match-grade **conductor** — measures every episode's source at its window midpoint, computes one common reel tone target, and auto-authors `tone_src`/`tone_dst` on the episodes that deviate — landed 2026-07-30 as its own optional post-EDL stage, `match-grade`, run after pacing and before `edl_to_reel`: see [the match-grade conductor design](specs/2026-07-30-matchgrade-conductor-design.md)); the crop's savgol smoothing window is now specified in **seconds** and resolved per-clip against its own fps (`pathsmooth.window_frames`, 30fps→7 unchanged, 60fps→15), and an authored `lead` composition is honoured off the subject's own net travel even where `motion.classify` lands in its ambiguous zone, instead of silently rendering as `center` (path-quality cluster, 2026-07-29); a frame move is now one of exactly two things — **subject-anchored** (a `zoom` push-in/pull-out, whose rect is chosen per route sample by the SAME composition rule as any tracked crop, so it stays inside every check) or **scenery** (a `pan`, whose route-less generated path is legitimate only over a window intake MEASURED as holding no people — `FootageWindow.present`, refused above `PAN_PRESENCE_MAX` in `edit_plan.window_to_episode`, never accepted on the author's word) — see [the subject-anchored-moves design](specs/2026-08-08-subject-anchored-moves-design.md) | — |
| 5.11 | episode-postcheck (gate) | — | ✅ | `check_episode` — mechanical gates + an **advisory** colour-fidelity check (subject hue drift source-vs-graded, `passed=None`, out of `overall`; 2026-07-27); the `jitter` gate is now **route-aware** — it discounts the subject's own backtrack (box-filtered over the route's own cadence, `_route_window`) before scoring the crop, and grades an authored `lead` against the same net-travel direction reframe used (path-quality cluster, 2026-07-29); framing/continuity/colour-fidelity all apply to a **subject-anchored** zoom exactly as to any tracked episode — the `freedom == 0` editorial-only arm now excuses only an unzoomed episode, since a push-in creates the freedom a zero-freedom layout lacked — while a **scenery** pan keeps reporting `editorial-only`/`not-checked`, now because intake measured the shot subject-less, not because the author claimed it (subject-anchored moves, 2026-08-08) | — |
| 5.12 | audio-mix | `out/audio` | ✅ | music-only mix ✅ + ambient ducking ✅ + SFX whoosh ✅ (synth whoosh on major transitions, `ReelManifest.sfx`); §5.12 complete | **Phase B — music spine** |
| 5.13 | reel-final-check (gate) | review | ✅ | **Mechanical half ✅ (complete)** — `check_reel`: black/length/colour/variety + loudness (hard), beat + `safe_zones` + `key_action` + `pad_bars` + `transitions` (all advisory — route-geometry/PathMeta checks; the last three landed 2026-07-17). Editorial half ✅ (2026-07-18) — reel-review SKILL dispatches a fresh reviewer subagent → typed REVIEW.json (Finding/Review), human-gated at CP3; **required, not optional, since 2026-08-04** — `montage.py`'s stage table flips `reel-review` to `kind="required"`, so a run is finished when `next_action`'s `next` is `null`, not merely when `delivered` is true (design [2026-08-04-attested-run-design.md](specs/2026-08-04-attested-run-design.md) §8). | Phase B (audio) + Editorial |
| 5.14 | **deliver** | `out/REEL_*.mp4` | ✅ | `deliver.py` — one encode, versioned, hard gate; since 2026-08-04 also **binds** the `ReelReport` to the master it ships (refuses an unbound or mismatched digest — closes fixes-backlog #13) and writes a `REEL_v{n}.attest.json` provenance sidecar beside the encode (both engine stamps, the master/report/reel digests, the EDL's state, every loosened check threshold); `montage status`/`montage verify` read it back (see [the attested-run design](specs/2026-08-04-attested-run-design.md)). **Since 2026-08-08 the router's single `deliver` step is three required stages**, not one: `episodes` (`edl_to_reel --stop-after-episodes` renders every episode, writes `EPISODES.json`, stops), `episode-qc` (one fresh judge subagent per episode, cap 3, judges the delivered clip's composition/colour/impression/path/hero off a frame strip + storyboard + the new `lib/naturalness.py` colour sensor; `episode_qc build` stamps every verdict with the clip's own sha256, never the judge's claim), and `deliver` itself (`edl_to_reel --from-episodes` gates on `EPISODE_QC.json` beside it — incomplete/stale/blocking all refuse before any ffmpeg — then assembles). A reel is never assembled over an episode nobody judged; a reprocessed episode still ships judged one render out of date (design §8) — `build_reel` names it in `reprocessed`, and the attestation's `episode_qc` block records it. See [the episode-qc design](specs/2026-08-08-episode-qc-design.md). **Since 2026-08-13 the reel's look** (a plateau vignette + a bookend fade, `EDL.look` → `ReelManifest.look`, defaulted per mood by `MoodPreset.look`) rides this SAME one encode, exactly like titles — a `-loop 1 -i` mask input plus `-filter_complex` when a vignette is authored, unchanged `-vf` (byte-identical argv to before looks existed) otherwise; because `check_reel` runs on the master *before* this stage applies it, no gate in the conveyor ever sees the look that shipped — see [the cinematic-look design](specs/2026-08-13-cinematic-look-design.md). | — |
| 5.15 | ffmpeg-recipes (reference) | — | ✅ | recipes docs | — |
| 5.16 | titles (optional) | `TITLES.json` | ✅ | agent-authored hook/caption/ending text (`titles.py`/`fonts.py` name-resolve); **renders at deliver** — no titled intermediate; titles now render **motion** — `fade` alpha ramps, `reveal="word"`/`"stair"` (one drawtext per step, each baked at its FINAL x from measured PIL font metrics — never a naive per-word re-centre) — and **colour** (`color`/`scale`/`line_spacing`), and lay out against the **platform's own safe zone** (`y_exprs(platform)` reads `safe_zone_for`, the same table `check_reel` judges the subject against, replacing a frozen generic-zone constant that disagreed with it); `deliver`/`build_reel` thread `platform` through (titles-animations, 2026-07-29); a fourth style, `outline-bold` (heavier border + offset shadow, for bright/busy backgrounds where plain `outline` disappears), landed 2026-08-13 alongside the reel's **look** — vignette overlay, then this stage's drawtext, then the bookend fade share deliver's one filtergraph in that order, measured (a fade placed before drawtext burns a title on over a black frame) — see [the cinematic-look design](specs/2026-08-13-cinematic-look-design.md) | — |

**Runtime utility, not a stage:** `verify-runtime` (2026-08-01) is a startup
preflight that gates `using-montage`'s step 0 — it asserts the `setup.sh`
baseline contract and stops the conveyor before project-init on any required
gap. Deliberately **not** in `V1_STAGES`; produces no run artifact. See
[the verify-runtime design](specs/2026-08-01-verify-runtime-design.md).

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
- [x] **reel retry loop (Phase A.5)** — `build_reel` loop-2 driver; delivered-space `color_correct` convergence; escalate-wins / no-silent-pass.
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
