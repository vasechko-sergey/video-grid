# Montage Conveyor — Pipeline Map

Bird's-eye map of the full **16-stage** montage conveyor (design spec
[§4 flow](specs/2026-07-05-montage-skillset-design.md) / §5 skills). Tick a stage
when it ships. The detailed per-subsystem changelog lives in
[build-status.md](build-status.md); **this** file is the "where are we in the
whole cycle" view — update the status column and the phase checkboxes together.

_Last updated: 2026-07-24._

**Legend:** ✅ built · ◐ partial · ❌ not built · 🔜 next up

## The 16 stages (design §5)

| # | Stage | Output | Status | Module / note | Closed by phase |
|---|-------|--------|:------:|---------------|-----------------|
| 5.1  | using-montage (router) | routing + ensure-env | ✅ | `using-montage` SKILL conducts the built stages footage→reel with the three §4.1 checkpoints; `montage.py` inspector (`next_action`) drives resume-from-`next`; `edl_to_reel` fans out episodes across a bounded thread pool (`jobs`, default 3 — the measured knee, 2026-07-18). **No open sub-items.** | Router + curation |
| 5.2  | footage-intake | `FOOTAGE.json`+`.md` | ✅ | `intake.py`: probe + PySceneDetect + YOLO11-seg + vidstabdetect → sub-scene carve → score → phash cull → `FOOTAGE.json`/`.md` + `cast.json` (SP2); **parallel + resumable** (`--jobs`, per-clip `.intake_cache`, `--fresh`; bad clip → `intake_report.json`) since 2026-07-25 | — |
| 5.3  | reel-brief | `SPEC.md` | ✅ | `reel_brief` SKILL → CLI + typed `Spec` (`scripts/lib/spec.py`) writes `SPEC.md`+`SPEC.json` atop project-init's machine subset (5.3) | Front-half authoring |
| 5.4  | trend-scan | `TRENDS.md` | ❌ | trend cache (TTL 7–10d) | Front-half authoring |
| 5.5  | music-and-mood | `MUSIC.json` | ✅ | beats-core (tempo/beat-grid/RMS energy) ✅ + start_offset intelligence (auto in-point: peak-energy window, vocal-pause start via opt-in demucs / librosa proxy) ✅ + mood-match (local: rank a folder vs SPEC.mood → MUSIC_SHORTLIST) ✅ + sourcing (free/any, network) ✅ | **Phase B — music spine** |
| 5.6  | pacing | `PACING.md` | ✅ | pacing runs **after** edit-plan and FITS the existing cuts onto the coarsest grid level (beat/half-bar/bar/2-bar/phrase) within a ±half-beat allowance — the 2/4/8 ladder is gone (scenario-first pacing, 2026-07-24) | **Phase B — music spine** |
| 5.7  | edit-plan | `EDL.md` | ✅ | `EDL.json` typed contract + `to_manifest_dict` bridge ✅ (SP1); `EDL.md` render + `edit_plan.py` (selection→projection→EDL) + `edit-plan` SKILL ✅ (SP3) | Front-half authoring |
| 5.8  | extract | `segments/<ep>_raw.mp4` | ✅ | `extract_edl` loop + §5.8 length gate ✅ (SP1) | — |
| 5.9  | assemble-draft | `draft.mp4` | ✅ | draft CLI + typed helpers (scripts/draft.py, scripts/lib/draft.py) — concat of raw segments, canvas-fit, processing_notes labels + music bed (SP1b, 5.9) | Front-half authoring |
| 5.10 | **process-episode** 🔒 | `out/<ep>.mp4` | ✅ | track + reframe + storyboard + layouts, orchestrated (loop-1) | — |
| 5.11 | episode-postcheck (gate) | — | ✅ | `check_episode` | — |
| 5.12 | audio-mix | `out/audio` | ✅ | music-only mix ✅ + ambient ducking ✅ + SFX whoosh ✅ (synth whoosh on major transitions, `ReelManifest.sfx`); §5.12 complete | **Phase B — music spine** |
| 5.13 | reel-final-check (gate) | review | ✅ | **Mechanical half ✅ (complete)** — `check_reel`: black/length/colour/variety + loudness (hard), beat + `safe_zones` + `key_action` + `pad_bars` + `transitions` (all advisory — route-geometry/PathMeta checks; the last three landed 2026-07-17). Editorial half ✅ (2026-07-18) — reel-review SKILL dispatches a fresh reviewer subagent → typed REVIEW.json (Finding/Review), human-gated at CP3. | Phase B (audio) + Editorial |
| 5.14 | **deliver** | `out/REEL_*.mp4` | ✅ | `deliver.py` — one encode, versioned, hard gate | — |
| 5.15 | ffmpeg-recipes (reference) | — | ✅ | recipes docs | — |
| 5.16 | titles (optional) | `TITLES.json` | ✅ | agent-authored hook/caption/ending text (`titles.py`/`fonts.py` name-resolve); **renders at deliver** — no titled intermediate | — |

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
| 5.14 | deliver | ✅ | — | — | — |
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
- [ ] **Misc engine** — the tail of the design's §7 five-names list, re-read through the layouts design's crop × rect × filler model. **`fit-solid` landed 2026-07-18** — exactly as the design predicted, a **filler literal**, not a branch (`BACKGROUNDS` gained `solid`, and `reframe` gained a synthesized-`color` background producer alongside the existing blur composite); the one thing the design had not fully priced in was that it **forced the mode rename** `fit-blur` → `fit`, since a second filler made the old mode name self-contradictory the moment an EDL author had to write `{"layout": "fit-blur", "background": "solid"}` — see [the fit-solid design](specs/2026-07-18-fit-solid-design.md). **`pan` landed 2026-07-19** — and, unlike `fit-solid`, it turned out **not to be a layout at all**: its preset row (`fill`'s row, exactly) was already expressible with `crop_scale < 1`, so what was missing was never a mode, only a second, *generated* source for the crop's x(t) — `PanSpec` (two fractions of horizontal freedom) plus `reframe.generate_pan_path`, used instead of a tracked route, with `PathMeta.pan` carrying the provenance so `check_episode`/the contradiction gate never mistake a generated path for an observation — see [the pan design](specs/2026-07-19-pan-design.md). **Stabilization's apply half landed 2026-07-20**: `vidstabtransform` now runs as a pre-stage in `process_episode` — never a filter inside `reframe`'s own chain, because the route is measured on unstabilized pixels and a crop placed from it against transformed pixels would re-inject exactly the shake vidstab removed (see [the stabilize-apply design](specs/2026-07-20-stabilize-apply-design.md) §1) — `stabilize: true` is authored in the EDL (`EDLEpisode.stabilize` → `to_manifest_dict`) and honored end to end. **The tracking-degradation ladder landed 2026-07-21**: an unpinned episode whose route comes back empty (or whose primary tracker is unavailable) now falls to `scripts/lib/flow.py`'s optical-flow centroid tracker (cv2, no ML), then to `scripts/lib/keyframes.py`'s sparse marks + interpolation (the `--keyframes` answer channel), each rung stamped on `TrackMeta.degraded` (`None`/`"flow"`/`"manual"`) — not the reframe-param retry ladder in `orchestration.py`, which was already built; see [the tracking-ladder design](specs/2026-07-21-tracking-ladder-design.md). What's left of the five-names list now: **`split`** is the only genuine remaining *layout* (two sources → two rects; changes the manifest's shape) — the sole remaining item.

---

See also: [build-status.md](build-status.md) (detailed changelog + next action),
[CLAUDE.md](../CLAUDE.md) (doc registry), design spec
[§4 pipeline flow / §5 skills](specs/2026-07-05-montage-skillset-design.md).
