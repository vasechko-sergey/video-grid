# Montage Conveyor — Pipeline Map

Bird's-eye map of the full **15-stage** montage conveyor (design spec
[§4 flow](specs/2026-07-05-montage-skillset-design.md) / §5 skills). Tick a stage
when it ships. The detailed per-subsystem changelog lives in
[build-status.md](build-status.md); **this** file is the "where are we in the
whole cycle" view — update the status column and the phase checkboxes together.

_Last updated: 2026-07-11._

**Legend:** ✅ built · ◐ partial · ❌ not built · 🔜 next up

## The 15 stages (design §5)

| # | Stage | Output | Status | Module / note | Closed by phase |
|---|-------|--------|:------:|---------------|-----------------|
| 5.1  | using-montage (router) | routing + ensure-env | ◐ | env/`setup.sh` ✅; cap-3 fan-out router ❌ | Router + curation |
| 5.2  | footage-intake | `FOOTAGE.md` | ❌ | scene/people/shake scan + window cull | Front-half authoring |
| 5.3  | reel-brief | `SPEC.md` | ◐ | `project-init` machine subset ✅; full brief ❌ | Front-half authoring |
| 5.4  | trend-scan | `TRENDS.md` | ❌ | trend cache (TTL 7–10d) | Front-half authoring |
| 5.5  | music-and-mood | `MUSIC.json` | ◐ | beats-core (tempo/beat-grid/RMS energy) ✅; mood-match + autonomous sourcing ❌ | **Phase B — music spine** ◐ |
| 5.6  | pacing | `PACING.md` | ❌ | energy spine (shared music↔edit) | **Phase B — music spine** |
| 5.7  | edit-plan | `EDL.md` | ❌ | source+window map, no cutting | Front-half authoring |
| 5.8  | extract | `segments/<ep>_raw.mp4` | ❌ | cut windows once (correct seek); contract exists, skill ❌ | Front-half authoring |
| 5.9  | assemble-draft | `draft.mp4` | ❌ | concat + burnt-in "process here" labels | Front-half authoring |
| 5.10 | **process-episode** 🔒 | `out/<ep>.mp4` | ✅ | track + reframe + storyboard + layouts, orchestrated (loop-1) | — |
| 5.11 | episode-postcheck (gate) | — | ✅ | `check_episode` | — |
| 5.12 | audio-mix | `out/audio` | ◐ | music-only mix (seek+afade+loudnorm −14 LUFS → aac) ✅; ambient ducking + SFX ❌ | **Phase B — music spine** |
| 5.13 | reel-final-check (gate) | review | ◐ | `check_reel` mechanical ✅; loudness (hard) + beat (advisory) now measured ✅; `safe_zones` still ❌ (`passed=None`) | Phase B (audio) + Editorial |
| 5.14 | **deliver** | `out/REEL_*.mp4` | ✅ | `deliver.py` — one encode, versioned, hard gate | — |
| 5.15 | ffmpeg-recipes (reference) | — | ✅ | recipes docs | — |

## Automation loops (design §4.1 ladder)

| Loop | Where | Mechanism | Status |
|------|-------|-----------|:------:|
| **Loop-1** — episode self-check → reprocess-until-pass/escalate | around 5.10/5.11 | `process_episode` + `orchestration.escalation` | ✅ |
| **Loop-2** — reel check → reprocess culprit episode → reassemble → recheck | around 5.13/5.14 | `build_reel` + `reel_orchestration.next_action` (**Phase A.5**) | ✅ |

Two human checkpoints remain unautomated by design (design §4.1): **music choice**
(skill proposes, human influences → Phase B) and **episode choice** (skill proposes
best-fit, human swaps → Router + curation).

## What produces a reel today

The **spine 5.10 → 5.14 is complete** and both automation loops are closed, so a
`REEL_v1` now delivers **with music** end-to-end from locked episode clips:
`build_reel` mixes a music-only stem once the picture passes (seek + afade +
two-pass loudnorm −14 LUFS), `check_reel` gates on loudness (hard) and reports
beat alignment (advisory, non-blocking), and `deliver` muxes the stem into the
export (stream-copy, preserving the measured loudness). What's missing to a
*full* reel: the **front half** (5.2–5.9: intake → brief → trends → edit-plan →
extract → draft) is not built (segments/manifests are supplied by hand / in
tests), and the rest of audio — mood-match/sourcing (5.5), pacing (5.6), ambient
ducking + SFX (5.12) — is not built. When a reel carries no `music`/`audio` (the
silent path, unchanged from Phase A.5), `check_reel` honestly reports
`passed=None` (`"not-checked"`) for beat/loudness rather than a silent pass;
`safe_zones` reports `passed=None` (`"not-implemented"`, genuinely unbuilt)
either way.

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

- [ ] **Phase B — music spine** ◐ — B1+B2 done (2026-07-11): beats-core + music-only mix + loudness/beat gates. Remaining: B3 sourcing, B4 pacing (5.6), ambient/SFX.
- [ ] **Front-half authoring** — stages 5.2 footage-intake, 5.3 reel-brief (full `SPEC.md`), 5.4 trend-scan, 5.7 edit-plan, 5.8 extract, 5.9 assemble-draft. The idea → EDL → segments front door; currently supplied by hand.
- [ ] **Router + curation** — stage 5.1 cap-3 fan-out router; the episode-choice human loop; `cast.json` hero registry (design §6.1a).
- [ ] **Editorial reel-final** — stage 5.13 beyond the mechanical gate: `safe_zones` + structural/editorial review.
- [ ] **Misc engine** — remaining layouts (`fit-solid`, `split`, `pan`); stabilization + tracking-degradation ladder.

---

See also: [build-status.md](build-status.md) (detailed changelog + next action),
[CLAUDE.md](../CLAUDE.md) (doc registry), design spec
[§4 pipeline flow / §5 skills](specs/2026-07-05-montage-skillset-design.md).
