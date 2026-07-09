# Development Workflow

Environment, commands, and the execution protocol for video-grid. Adapted from
the anna-auth workflow doc to a superpowers-driven Python skill set.

_Last updated: 2026-07-09._

## Environment

- **Python 3.13** in a skill-local `.venv`. One `requirements.txt`, one pypi
  index. Bootstrap with `bash setup.sh` (adds `--with-vidstab` for a
  stabilization-capable ffmpeg; the core never calls vidstab).
- Requires `ffmpeg` + `ffprobe` on PATH. Every script fails loud with a remedy if
  a binary is missing (`brew install ffmpeg`).

## Commands

```bash
bash setup.sh                                   # create .venv, install requirements
.venv/bin/python -m scripts.<name> --help       # run any script (as a module, never by path)
.venv/bin/python -m pytest -q                    # full test suite
.venv/bin/python -m pytest -q -m "not integration"   # skip real-ffmpeg tests
```

- **Scripts run as modules** (`-m scripts.<name>`); pass explicit paths, never
  rely on cwd. See [coding-standards.md](./coding-standards.md).

## Execution Protocol

New work follows the superpowers pipeline — one subsystem per cycle:

1. **brainstorming** → a design/spec in
   [`docs/specs/`](./specs/) (`YYYY-MM-DD-<topic>-design.md`).
2. **writing-plans** → a bite-sized, TDD plan in
   [`docs/plans/`](./plans/) (`YYYY-MM-DD-<topic>.md`).
3. **subagent-driven-development** → a fresh implementer subagent per task
   (test-first, watch-fail, implement, pass, commit), then a two-stage review per
   task: **spec-compliance first, then code-quality**, with fix loops until both
   pass. Continuous — no check-ins between tasks. A whole-slice review closes the
   cycle.

Spec and plan are kept **in sync** — if they drift, fix both, not one.

## Branches & Commits

- Branch per slice: `feat/<slice>` for features, `chore/<...>` / `docs/<...>` for
  polish. Never start work on `main`.
- **Commit per task step** exactly as the plan specifies; the commit message says
  *why*. Co-author trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- After finishing a task: tick its checkboxes in the plan and update
  [build-status.md](./build-status.md); commit both.

## Documentation Standards

- Hierarchical headers; a `_Last updated:_` date near the top.
- Focus on **why**, not **what** — the code says what; the doc says why it is that
  way and what breaks if you change it.
- Line length ≤ 100 chars; code blocks carry a language hint.
- Link related docs with relative paths; keep each doc focused on one topic.
- `CLAUDE.md` is a **registry** (a Quick Reference table), not a narrative — new
  detail goes in a focused doc and gets one row in the table.

## Working Rules

- Do exactly what is asked — nothing more, nothing less.
- Prefer editing an existing file over creating a new one; flag obsolete files.
- Keep the project modular: pure logic in `scripts/lib/`, orchestration in
  `scripts/`, judgment in `SKILLS/`.

## Related

- [coding-standards.md](./coding-standards.md) · [testing-guide.md](./testing-guide.md)
- [build-status.md](./build-status.md) — what is built and what is next.
