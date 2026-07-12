# video-grid

AI-assisted video-montage skill set (approach inspired by superpowers; fully
independent). All docs and code in English — built for distribution.

Guidance for Claude Code working in this repo. **This file is a registry:** the
Quick Reference table points to focused docs; detail lives there, not here. The
Known Troubles below stay inline because they fail *silently* — bad pixels, not
a crash — so they must always be in context.

## Quick Reference

| Topic | File | Description |
|-------|------|-------------|
| Design spec | [2026-07-05-montage-skillset-design.md](docs/specs/2026-07-05-montage-skillset-design.md) | The montage skillset design — env, librosa-first music, §4.1 questions/go-back, §6.1a hero identity, golden fixture, degradation ladders, **§12 landmine registry**. |
| Engine hardening design | [2026-07-08-engine-dataclass-hardening-design.md](docs/specs/2026-07-08-engine-dataclass-hardening-design.md) | Typed wire-contracts + config-specs; aspect/resolution-agnostic `Delivery`; soft-manifest / hard-engine validation. |
| Project-init design | [2026-07-09-project-init-design.md](docs/specs/2026-07-09-project-init-design.md) | `purpose→canvas` / `quality→delivery` maps; episode inheritance; `native` default. |
| Layouts design | [2026-07-10-layouts-design.md](docs/specs/2026-07-10-layouts-design.md) | Layout = crop × rect × filler (not five names); `freedom = src_w − crop_w` decides tracking; the `path.meta.json` sidecar. |
| Reel back-half design | [2026-07-10-reel-back-half-design.md](docs/specs/2026-07-10-reel-back-half-design.md) | Silent back half: assemble (lossless master) → check_reel (mechanical gate + machine-readable fail attribution) → deliver (one encode, versioned); Phase A.5 retry loop deferred. |
| Reel retry loop design | [2026-07-11-reel-retry-loop-design.md](docs/specs/2026-07-11-reel-retry-loop-design.md) | Phase A.5: build_reel driver (assemble→check→reprocess→deliver), reel_orchestration ladder, delivered-space color_correct convergence. |
| Music spine design | [2026-07-11-music-spine-design.md](docs/specs/2026-07-11-music-spine-design.md) | Phase B · B1+B2: librosa-first `beats.py` → `MusicSpec`/`MUSIC.json`, music-only `mix.py` stem, loudness-hard/beat-advisory `check_reel` gates; B3 sourcing/B4 pacing deferred. |
| Extract spine design | [2026-07-11-extract-spine-design.md](docs/specs/2026-07-11-extract-spine-design.md) | Front-half SP1: typed `EDL.json` → extract → `build_reel` → `REEL_v1`; EDL contract + `to_manifest_dict` bridge + sequential `edl_to_reel` driver; markdown/authoring → SP3, draft → SP1b, parallel router → 5.1. |
| Footage-intake design | [2026-07-12-footage-intake-design.md](docs/specs/2026-07-12-footage-intake-design.md) | Front-half SP2 (§5.2): raw clips → typed `FOOTAGE.json` + rendered `FOOTAGE.md` scored moment-windows + interactive `cast.json`; `intake.py` = probe + PySceneDetect + YOLO11-seg + vidstabdetect + carve + score + phash cull; first runtime vidstab consumer; hero-pin wiring deferred. |
| Core implementation plan | [2026-07-05-video-grid-core.md](docs/plans/2026-07-05-video-grid-core.md) | Tasks 0–11 (+9.5 golden); follow-on plans at its tail. |
| Layouts plan | [2026-07-10-layouts.md](docs/plans/2026-07-10-layouts.md) | Tasks 0–12: `fit-blur` + `insert`, the bordered card, and the sidecar that stops downstream re-derivation. |
| Reel back-half plan | [2026-07-10-reel-back-half.md](docs/plans/2026-07-10-reel-back-half.md) | Tasks 0–11: the four typed contracts, the concat core, check_reel's four checks, deliver's hard gate + version log, real-ffmpeg golden. |
| Reel retry loop plan | [2026-07-11-reel-retry-loop.md](docs/plans/2026-07-11-reel-retry-loop.md) | Tasks 0–7: color_correct seam, check_reel detail, ReelManifest, next_action, build_reel, real-ffmpeg proofs. |
| Music spine plan | [2026-07-11-music-spine.md](docs/plans/2026-07-11-music-spine.md) | Tasks 0–8: MusicSpec config-spec, beats.py (real-librosa golden), ReelCheckSpec audio thresholds, check_reel loudness+beat gates, mix.py, deliver audio mux, build_reel integration. |
| Extract spine plan | [2026-07-11-extract-spine.md](docs/plans/2026-07-11-extract-spine.md) | Tasks 0–6: EDLEpisode/EDL + bridge, `extract_edl` loop+gate, `edl_to_reel` driver, real-ffmpeg golden, docs. |
| Footage-intake plan | [2026-07-12-footage-intake.md](docs/plans/2026-07-12-footage-intake.md) | Tasks 0–15: `footage.py` contracts, `intake.py` CV units (shot_type/carve/score/shake/YOLO-seg/cull) + driver, cast surfacing/naming, real-ffmpeg golden, SKILL, docs. |
| All plans | [docs/plans/](docs/plans/) | One plan per subsystem (core, orchestrator, engine-hardening, project-init, layouts). |
| Coding standards | [coding-standards.md](docs/coding-standards.md) | Fail-loud contract, imports-at-top, typing, dataclass conventions, banned patterns. |
| Testing guide | [testing-guide.md](docs/testing-guide.md) | TDD, whole-object asserts, real-ffmpeg golden fixtures, markers/layout. |
| Development workflow | [development-workflow.md](docs/development-workflow.md) | Env, commands, superpowers execution protocol, branches/commits, doc standards. |
| Build status & next action | [build-status.md](docs/build-status.md) | What's built, what's next, external assets — **update after every task**. |
| Pipeline map | [pipeline-map.md](docs/pipeline-map.md) | Bird's-eye map of the 15-stage conveyor (design §5) — per-stage build status + the phase roadmap. |

## Source of truth

- The design spec + core plan are the source of truth; **spec and plan stay in
  sync** — if they drift, fix **both**, not one.
- Current status and the next action live in
  [docs/build-status.md](docs/build-status.md); update it (and the plan's
  checkboxes) in the same commit after every task.
- How new work is built (brainstorm → plan → subagent-driven TDD, two-stage
  review) is in [development-workflow.md](docs/development-workflow.md).

## Known troubles (silent-corruption landmines — full registry: design spec §12)

These do **not** fail loud — they quietly corrupt the output, so they live here
in always-loaded context. The conventions that *do* fail loud (fail-loud
contract, scripts-as-modules, `pythonpath = .`, typing) live in
[coding-standards.md](docs/coding-standards.md) and
[testing-guide.md](docs/testing-guide.md).

- ffmpeg seek: `-ss` **after** `-i` for frame-accurate cuts (the black-frames
  landmine was arg order, not 4K).
- `lutrgb` is **banned** (black frames) — `colorchannelmixer` only.
- Never stabilize wade-in/out shots ("rolling ground").
