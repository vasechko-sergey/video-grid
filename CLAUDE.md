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

- **Done:** design + plan hardened and synced (commits `50350b6`, `c12f992`, `e9be488`, `00cede0`). Task 0 **PARTIAL** (`618be74`) — source files committed, but:
  - `.venv` was created with python 3.10 and is **empty** (install died against a corporate pip mirror) → delete it; `bash setup.sh` recreates with python 3.13 and `PIP_INDEX_URL=https://pypi.org/simple` (both fixes already in the plan's Task 0 setup.sh — write that version first).
  - requirements are still split (`requirements.txt` + `requirements-ml.txt`) → **merge into one** `requirements.txt`, `git rm requirements-ml.txt` — see the plan's Task 0 migration note.
- **Next action:** rewrite Task 0 files per the amended plan → `bash setup.sh` → `.venv/bin/python -m pytest -q` (exit **5** = pass while zero tests exist) → mark Task 0 done → Tasks 1→11 in order (9.5 after 9).
- **Deferred / open:** push `feat/core-engine` to origin as backup (ask Sergei); heavy deps (`ultralytics`) need a normal network — the index-url fix should make pip work anywhere.

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
