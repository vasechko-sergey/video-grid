# Development Workflow

Environment, commands, and the execution protocol for video-grid. Adapted from
the anna-auth workflow doc to a superpowers-driven Python skill set.

_Last updated: 2026-07-20._

## Environment

- **Python 3.13** in a skill-local `.venv`. One `requirements.txt`, one pypi
  index. Bootstrap with `bash setup.sh` — **one install, no capability flags.**
- **Packaged as a Claude Code plugin** (`.claude-plugin/`) — skills run the
  pipeline through `bin/vg`, the cwd-independent launcher; `bin/vg scripts.X`
  (equivalently `.venv/bin/python -m scripts.X` from the repo root) is the
  module entrypoint. The venv lives **outside** the repo
  (`~/.local/share/video-grid/venv`) with `<repo>/.venv` a symlink to it (so
  `/plugin install`'s copy stays lean), and `setup.sh` records this checkout at
  `~/.config/video-grid/root` so the installed (copied-away) skills find and run
  it.
- **One ffmpeg carrying every library the pipeline needs.** `setup.sh` installs
  homebrew-core's `ffmpeg-full`, which is the same version and revision as core
  `ffmpeg` but ships `libfreetype` (drawtext — §5.9 draft labels, §5.16 titles)
  and `libvidstab` (§5.2 intake's shake score). It is **keg-only**, so it lands
  beside core `ffmpeg` instead of replacing it — nothing is ever uninstalled, and
  a machine's other ffmpeg dependents keep working.
- **Consequence: the binaries are not on PATH, and the code does not look there
  first.** `scripts/lib/ffbin.py` resolves them — `$FFMPEG`/`$FFPROBE`, then the
  `config/ffmpeg.env` that `setup.sh` writes, then `shutil.which` — always to an
  absolute path. Never hard-code `"ffmpeg"` in an argv: on a keg-only install
  that silently selects the *wrong* build, and a machine check in
  [`tests/lib/test_landmine_scan.py`](../tests/lib/test_landmine_scan.py)
  rejects the literal in `scripts/`. Ask `ffbin.has_filter` about capabilities
  rather than shelling out — that probe is the seam where production and the
  test guards can drift onto different binaries.
- **The PATH rung is the portability fallback,** not the normal path: `setup.sh`
  is macOS/homebrew-only, so a Linux box has no `config/ffmpeg.env` and must
  still import. `$FFMPEG` is the override for CI or for bisecting a build.
- **Fonts are baseline too.** drawtext needs an actual `.ttf`/`.ttc` on disk as
  well as the filter — the two are decoupled, and it needs an explicit
  `fontfile=`. macOS ships Arial/Helvetica, so the floor is normally already
  met; `setup.sh` installs DejaVu if no system font is found rather than
  dead-ending the user, plus the curated title set (Montserrat, Inter, Bebas
  Neue, Oswald) that §5.16 resolves **by name**, not path. Naming an
  uninstalled font makes `deliver` fail loud — never a silent fallback to a
  different font. Every script fails loud with a remedy if a binary, filter, or
  font is missing.
- **All installed at baseline (no opt-in flags):** demucs (torch, 2–3 GB; the
  phrase-aware music in/out-point) installs with **warn-and-continue** — a platform
  with no torch wheel degrades to the librosa mix-silence proxy rather than aborting
  the venv (which is why it stays OUT of `requirements.txt`); yt-dlp (the `any`
  music-source lane) ships in `requirements.txt`. A Jamendo `client_id` is an
  optional non-blocking notice (`config/sourcing.env`), not a flag.
- `setup.sh` is **macOS/homebrew only for now** (cross-platform auto-install is a
  TODO), and warns-and-continues without brew so the venv still gets built. The
  runtime code is already portable — `scripts/lib/fonts.py` `FONT_CANDIDATES`
  carries Linux font paths, `ffbin` falls through to PATH, and `--font PATH`
  overrides on any OS.

See [the ffmpeg baseline design](specs/2026-07-20-ffmpeg-baseline-design.md) for
why the path is frozen at install time while the filters are probed at runtime,
every time.

## Commands

```bash
bash setup.sh                                   # ffmpeg-full + fonts + .venv + requirements
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

### Closing a slice — the deferral rule

**A slice is not finished until every item in its design's `§Deferred` has a row
in [backlog.md](./backlog.md).** The slice's own docs-sync task carries this;
write the rows there, with a priority, a status and a size.

This exists because on 2026-08-12 an audit of all 28 design deferral sections
found four items that had left every list, three of them shipping as live
defects. Every document recorded them — designs, build-status, the fixes backlog,
the pipeline map — and none of them was a *queue*, so an item escaped a design's
deferred list only when a human happened to re-read that design. One deferral
(`smooth_window_s`) was written down twice and rediscovered by accident three
weeks later.

Nothing machine-checks this rule; a lint that matched prose deferrals to rows
would be guessing at both ends. It is a convention that survives only by being on
this checklist.

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
  `scripts/`, judgment in `skills/`.

## Related

- [coding-standards.md](./coding-standards.md) · [testing-guide.md](./testing-guide.md)
- [build-status.md](./build-status.md) — what is built and what is next.
