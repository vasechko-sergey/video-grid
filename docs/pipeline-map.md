# Montage Conveyor — Pipeline Map

Bird's-eye map of the full **16-stage** montage conveyor (design spec
[§4 flow](specs/2026-07-05-montage-skillset-design.md) / §5 skills). Tick a stage
when it ships. The detailed per-subsystem changelog lives in
[build-status.md](build-status.md); **this** file is the "where are we in the
whole cycle" view — update the status column and the phase checkboxes together.

_Last updated: 2026-07-14._

**Legend:** ✅ built · ◐ partial · ❌ not built · 🔜 next up

## The 16 stages (design §5)

| # | Stage | Output | Status | Module / note | Closed by phase |
|---|-------|--------|:------:|---------------|-----------------|
| 5.1  | using-montage (router) | routing + ensure-env | ✅ | `using-montage` SKILL conducts the built stages footage→reel with the three §4.1 checkpoints; `montage.py` inspector (`next_action`) drives resume-from-`next`. cap-3 **parallel** fan-out is the one open sub-item | Router + curation |
| 5.2  | footage-intake | `FOOTAGE.json`+`.md` | ✅ | `intake.py`: probe + PySceneDetect + YOLO11-seg + vidstabdetect → sub-scene carve → score → phash cull → `FOOTAGE.json`/`.md` + `cast.json` (SP2) | — |
| 5.3  | reel-brief | `SPEC.md` | ✅ | `reel_brief` SKILL → CLI + typed `Spec` (`scripts/lib/spec.py`) writes `SPEC.md`+`SPEC.json` atop project-init's machine subset (5.3) | Front-half authoring |
| 5.4  | trend-scan | `TRENDS.md` | ❌ | trend cache (TTL 7–10d) | Front-half authoring |
| 5.5  | music-and-mood | `MUSIC.json` | ✅ | beats-core (tempo/beat-grid/RMS energy) ✅ + start_offset intelligence (auto in-point: peak-energy window, vocal-pause start via opt-in demucs / librosa proxy) ✅ + mood-match (local: rank a folder vs SPEC.mood → MUSIC_SHORTLIST) ✅ + sourcing (free/any, network) ✅ | **Phase B — music spine** ◐ |
| 5.6  | pacing | `PACING.md` | ❌ | energy spine (shared music↔edit) | **Phase B — music spine** |
| 5.7  | edit-plan | `EDL.md` | ✅ | `EDL.json` typed contract + `to_manifest_dict` bridge ✅ (SP1); `EDL.md` render + `edit_plan.py` (selection→projection→EDL) + `edit-plan` SKILL ✅ (SP3) | Front-half authoring |
| 5.8  | extract | `segments/<ep>_raw.mp4` | ✅ | `extract_edl` loop + §5.8 length gate ✅ (SP1) | — |
| 5.9  | assemble-draft | `draft.mp4` | ✅ | draft CLI + typed helpers (scripts/draft.py, scripts/lib/draft.py) — concat of raw segments, canvas-fit, processing_notes labels + music bed (SP1b, 5.9) | Front-half authoring |
| 5.10 | **process-episode** 🔒 | `out/<ep>.mp4` | ✅ | track + reframe + storyboard + layouts, orchestrated (loop-1) | — |
| 5.11 | episode-postcheck (gate) | — | ✅ | `check_episode` | — |
| 5.12 | audio-mix | `out/audio` | ◐ | music-only mix (seek+afade+loudnorm −14 LUFS → aac) ✅; ambient ducking + SFX ❌ | **Phase B — music spine** |
| 5.13 | reel-final-check (gate) | review | ◐ | `check_reel` mechanical ✅; loudness (hard) + beat (advisory) now measured ✅; `safe_zones` still ❌ (`passed=None`) | Phase B (audio) + Editorial |
| 5.14 | **deliver** | `out/REEL_*.mp4` | ✅ | `deliver.py` — one encode, versioned, hard gate | — |
| 5.15 | ffmpeg-recipes (reference) | — | ✅ | recipes docs | — |
| 5.16 | titles (optional) | `TITLES.json` | ✅ | agent-authored hook/caption/ending text (`titles.py`/`fonts.py` name-resolve); **renders at deliver** — no titled intermediate | — |

## Automation loops (design §4.1 ladder)

| Loop | Where | Mechanism | Status |
|------|-------|-----------|:------:|
| **Loop-1** — episode self-check → reprocess-until-pass/escalate | around 5.10/5.11 | `process_episode` + `orchestration.escalation` | ✅ |
| **Loop-2** — reel check → reprocess culprit episode → reassemble → recheck | around 5.13/5.14 | `build_reel` + `reel_orchestration.next_action` (**Phase A.5**) | ✅ |

Two human checkpoints remain unautomated by design (design §4.1): **music choice**
(skill proposes, human influences → Phase B) and **episode choice** (skill proposes
best-fit, human swaps → Router + curation).

## Remaining work — blockers & critical path

A dependency view of the 16 stages: what's left, what **hard-blocks** it, what it
unblocks. `(soft)` = a quality input, not a build prerequisite. Complements the
status table above.

| # | Stage | St | Left to build | Blocked by (hard) · (soft) | Unblocks |
|---|-------|:--:|---------------|----------------------------|----------|
| 5.1 | using-montage router | ✅ | cap-3 **parallel** fan-out only (sub-item) | — | autonomous v1 |
| 5.2 | footage-intake | ✅ | — (SP2, 2026-07-12) | — | 5.7, 5.3, 5.13 |
| 5.3 | reel-brief | ✅ | — (2026-07-12) | — | 5.7, 5.5 mood |
| 5.4 | trend-scan | ❌ | `TRENDS.md` — YAGNI | none | (soft) 5.3, 5.7 |
| 5.5 | music-and-mood | ✅ | — (2026-07-14) | — | 5.6 |
| 5.6 | pacing | ❌ | `PACING.md` (B4) | **5.5 MUSIC.json** (beats-core ✅ → buildable now) | (soft) 5.7 |
| 5.7 | **edit-plan** | ✅ | — (SP3, 2026-07-12) | — | **5.1 + autonomy** |
| 5.8 | extract | ✅ | — (SP1) | — | — |
| 5.9 | assemble-draft | ✅ | — (2026-07-13) | none — **5.8 ✅** | QA preview |
| 5.10 | process-episode 🔒 | ✅ | — | — | — |
| 5.11 | episode-postcheck | ✅ | — | — | — |
| 5.12 | audio-mix | ◐ | ambient duck + SFX | **extract per-ep audio passthrough** (small 5.8 change) | richer mix |
| 5.13 | reel-final-check | ◐ | `safe_zones` + editorial | none for safe_zones · (soft) 5.2 faces ✅ | tighter gate |
| 5.14 | deliver | ✅ | — | — | — |
| 5.15 | ffmpeg-recipes | ✅ | — | — | — |
| 5.16 | titles | ✅ | — (2026-07-13) | — | reel-review CP polish |
| — | cast → hero-pin | ❌ | `cast.json` descriptors → manifests; `is_seed_pin` bbox→name | none — **5.2 cast.json ✅** | cast-name hero pins |

**Tally:** 12 ✅ · 2 ◐ · 2 ❌. Both automation loops closed.

### Critical path to autonomous v1

```
5.2 footage-intake ✅ ──► 5.7 edit-plan ✅ ──► 5.1 using-montage ✅   = autonomy
        │                      ▲  ▲
        └─► 5.3 brief ─────────┘  │  (soft, quality)
    5.5 music ─► 5.6 pacing ──────┘
```

**The entry-skill closes the autonomous v1 chain:** footage→EDL→reel now runs from
one `using-montage` invocation — it conducts project-init → footage-intake →
edit-plan → edl_to_reel with the three §4.1 checkpoints, resuming from `montage
next_action`. The only open 5.1 sub-item is the cap-3 **parallel** episode fan-out
(a perf slice — `edl_to_reel` stays sequential today), **not a v1 blocker**.
Everything else (B4, 5.9 draft, 5.12 ambient, 5.13 safe_zones, cast→hero-pin) is
parallel **quality**.

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
outside of tests. What's still missing to a *full* reel: the rest of the
**front half** — 5.2 footage-intake and 5.4 trend-scan — plus
the rest of audio: mood-match/sourcing (5.5), pacing (5.6), ambient ducking +
SFX (5.12). When a reel carries no `music`/`audio` (the silent path, unchanged
from Phase A.5), `check_reel` honestly reports `passed=None` (`"not-checked"`)
for beat/loudness rather than a silent pass; `safe_zones` reports
`passed=None` (`"not-implemented"`, genuinely unbuilt) either way.

## Phase roadmap

### Done

- [x] **Core engine** — track → reframe → storyboard → check; golden fixture on real footage.
- [x] **process-episode orchestrator** — loop-1 shell (contradiction detect + retry ladder + escalation).
- [x] **engine dataclass-hardening** — typed wire-contracts + config-specs; aspect/resolution-agnostic `Delivery`.
- [x] **project-init** — `purpose→canvas` / `quality→delivery`; episode inheritance; `native` default.
- [x] **layouts** — crop × rect × filler; `fit-blur` + `insert`; the `path.meta.json` sidecar.
- [x] **reel back half** — assemble (lossless master) → check_reel (mechanical gate) → deliver (one encode, versioned).
- [x] **reel retry loop (Phase A.5)** — `build_reel` loop-2 driver; delivered-space `color_correct` convergence; escalate-wins / no-silent-pass.

### Upcoming

- [ ] **Phase B — music spine** ◐ — B1+B2+B3 done (B3 landed 2026-07-14): beats-core + music-only mix + loudness/beat gates + autonomous sourcing (free/any rights lanes). Remaining: B4 pacing (5.6), ambient/SFX.
- [ ] **Front-half authoring** ◐ — SP1 (extract spine, 2026-07-11) + SP2 (footage-intake, 2026-07-12) + SP3 (edit-plan, 2026-07-12) done: `EDL.json`→delivered reel, `intake.py` scans raw clips → `FOOTAGE.json`/`.md` scored moment-windows + `cast.json` hero registry, and now `edit_plan.py` projects those windows (via an agent `selection.json`) into the `EDL.json`+`EDL.md` that drives SP1. Remaining: SP4 (trend-scan).
- [ ] **Router + curation** — stage 5.1 cap-3 fan-out router; the episode-choice human loop; `cast.json` hero registry (design §6.1a).
- [ ] **Editorial reel-final** — stage 5.13 beyond the mechanical gate: `safe_zones` + structural/editorial review.
- [ ] **Misc engine** — remaining layouts (`fit-solid`, `split`, `pan`); stabilization + tracking-degradation ladder.

---

See also: [build-status.md](build-status.md) (detailed changelog + next action),
[CLAUDE.md](../CLAUDE.md) (doc registry), design spec
[§4 pipeline flow / §5 skills](specs/2026-07-05-montage-skillset-design.md).
