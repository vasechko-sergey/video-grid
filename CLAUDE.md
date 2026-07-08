# video-grid

AI-assisted video-montage skill set (approach inspired by superpowers; fully independent). All docs and code in English — built for distribution.

## Source of truth

- **Design spec:** `docs/2026-07-05-montage-skillset-design.md` — amended 2026-07-06: env (python 3.13, single requirements, pypi index), librosa-first music, §4.1 questions/go-back protocol, §6.1a hero identity, golden fixture, degradation ladders.
- **Core implementation plan:** `docs/plans/2026-07-05-video-grid-core.md` — Tasks 0–11 (+9.5 golden); follow-on plans listed at its tail.
- Spec and plan are in sync as of commit `00cede0`. If they drift, fix **both**, not one.

## Execution protocol

- Execute the core plan with **superpowers:subagent-driven-development**: fresh implementer per task, TDD (test first, watch it fail), two-stage review per task (spec compliance → code quality), continuous — no check-ins between tasks.
- Branch: `feat/core-engine`. Commit per task step exactly as the plan specifies.
- After finishing a task: tick its checkboxes in the plan file and update **Status** below; commit both.

## Status (update after every task)

- **Done:** core plan Tasks 0–11 ALL COMPLETE, final review verdict READY (2026-07-07). 49 tests green (incl. golden fixture: real MVI_3739 footage @59.94fps through the full engine). Notable amendments beyond plan-verbatim code:
  - vidstab preflight = warning, not blocker (`07d2e68`) — homebrew-core ffmpeg lacks libvidstab; core never calls it; process-episode re-checks hard.
  - lib hardening (`341d059`): smooth([])→[], savgol odd-window ordering, on_line raises on route/path desync, gain(≤0) raises with remedy.
  - **route-gap desync fix (`a19937f`)**: crop x(t) built from route timestamps, not frame index — occlusion gaps no longer desync crop from video timeline; empty route fails loud.
  - Golden fixture as-built: window 9.083–10.668s (not lena_ride2) — diagonal motion means no 2.5s window in MVI_3739 classifies lateral; see plan Task 9.5 note.
  - **Hardening round (2026-07-07, fresh-eyes audit, 5 commits `27e3571`→`0c8c283`):** proc.run surfaces ffmpeg stderr; check_episode validates composition (+`break`=editorial-only) and uses spec-§9 boundary-luma black check; track drops id=None frankentracks, probes fps/dims, adds speed+border features; reframe caps expr knots (~80), even dims for all canvases, §6.4 Y headroom, loud stabilize/fps guards; storyboard hero-marks helper. **68 tests green.** Spec/plan/landmines synced same round.
- **process-episode orchestrator slice DONE (2026-07-08)** — plan `docs/plans/2026-07-08-process-episode-orchestrator.md`, Tasks 0–7 via strict subagent-driven-development (implementer → spec-review → code-quality-review + fix loops per task). **122 tests green.** Built: `scripts/lib/manifest.py` (validate gate), `scripts/lib/orchestration.py` (contradiction detect + retry-ladder + escalation), `scripts/lib/proc.py`, `scripts/process_episode.py` (deterministic loop: track→reframe→storyboard→check, threads probed canvas/src_dims — **closes the contract note** — times stages, hero marks on storyboard), `SKILLS/process-episode/SKILL.md` (subagent: ask-before-start, editorial gate, stop-and-report). Golden fixture runs the whole orchestrator through real ffmpeg. Review-driven fixes: manifest null/unknown-key/model/color/canvas hardening, hero truthiness, centered→on_line alias, project_dir mkdir, hero-marks wiring.
- **Next action:** next follow-on plan — **reframe-extensions** (layouts fit-blur/insert/split/pan + vidstab + optical-flow degradation + landmine lint; removes the matching `validate()` refusals), OR ingestion (`cast.json`) / router (cap-3 fan-out). Scope split chosen 2026-07-08: orchestrator-first, engine extensions second.
- **Deferred / open:** vidstab-capable ffmpeg before stabilization (`bash setup.sh --with-vidstab`); descriptor continuity re-match needs ingestion's cast.json; cap-3 parallel fan-out is the router's job.

## External assets (outside this repo)

- **Golden fixture source (plan Task 9.5):** session footage + window map at
  `/Users/serg/Downloads/untitled folder/REEL_SOURCES.md` — footage (`MVI_*.MP4`, `DJI_*.MP4`, ~128 files) sits in that same folder. `MVI_3739.MP4` (the long ride) is the suggested fixture source.
- The Jul 3–5 montage session that this design was reverse-engineered from produced Reel A (ODESZA) and Reel B (Billie Eilish); real-footage validation happens when Sergei re-montages that footage — user-driven, not a milestone.

## Hard rules (full registry: design spec §12)

- ffmpeg seek: `-ss` **after** `-i` for frame-accurate cuts (the black-frames landmine was arg order, not 4K).
- `lutrgb` is **banned** (black frames) — `colorchannelmixer` only.
- Scripts run as modules — `.venv/bin/python -m scripts.<name>`; explicit paths always, never cwd.
- `pytest.ini` must keep `pythonpath = .` (no `tests/__init__.py`).
- Never stabilize wade-in/out shots ("rolling ground").
- Every script fails loud with a remedy ("ffmpeg not found → brew install ffmpeg").
