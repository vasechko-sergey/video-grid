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
  with no torch wheel leaves the venv built rather than aborting it (which is why
  demucs stays OUT of `requirements.txt`). **It does not degrade to anything:** since
  2026-08-14 (`1871c48`) demucs is a **required** runtime component and the librosa
  mix-silence proxy is deleted, so a `setup.sh` that warned here produces a runtime
  `verify_runtime` **blocks** until demucs is present. The proxy was removed because
  it did not fail — it answered *wrong* (0 vocal-free spans against demucs's 2 on the
  same track), and a wrong music in-point is silent. yt-dlp (the `any` music-source
  lane) ships in `requirements.txt`. A Jamendo `client_id` is an optional
  non-blocking notice (`config/sourcing.env`), not a flag.
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

**A small fix skips the pipeline.** A change of a task or two — a message, a
guard, a doc line, a mismarked test — is written test-first on its own branch
and gets one review; no design, no plan, no mutation battery. The full cycle is
for a change that adds or moves a contract. (Written 2026-10-13: between the
first real run and that date, slices that closed one row routinely ran a design
with a measurement section, a seven-task plan and a battery of twenty to eighty
mutants, which is how a one-line problem came to cost a day.)

### Spec and plan

Until the slice ships — the version-bump commit ([Versioning](#versioning)) —
spec and plan are kept **in sync**: if they drift, fix both, not one. After that
the two part ways on purpose. A **design** is corrected in place when what it
asserts stops being true — whether the code moved, a measurement was re-derived, or
a claim was found false. A **plan** is the record of what was *planned*, and is not
amended in substance: its account of what was planned stands, while a typo, a dead
link or a factual correction to a pointer is fine. What was *done* is carried by
that slice's per-task commits.

(Until 2026-09-29 this file also asked for the plan's checkboxes to be ticked as
each task landed. It was followed task by task exactly once, by the first plan. At
the close of their own slices, 53, 52, 31, 37 and 14 % of the 91 plans that had
landed were fully ticked, across five date bands from 2026-07-05 to 2026-09-25; the
end state reads 61 of 91 because one commit (`878a713`, 2026-08-06) ticked 27 of the
older ones retroactively. Measured 2026-09-29.)

### Closing a slice — what enters the backlog

**The backlog holds only what a real run showed or what the user asked for.** A
design's `§Deferred` and honest-limits sections, and a reviewer's Minor findings,
stay where they were written — they do not become rows. A deferral that ships a
wrong result *today* is the exception: it is a live defect and enters at once, as
P0.

The rule was the opposite until 2026-10-13: every item in a design's
`§Deferred` had to get a row, after a 2026-08-12 audit found four deferrals that
had left every list (three were live defects — which the P0 exception still
catches). Followed for two months it inverted the queue: each slice closed one
row and filed three to five, the backlog grew from the first real run's 29 rows
to about 230 entries, and of roughly 140 P3 entries only 7 so much as mentioned
the real run — about 96 were design deferrals and 46 review or test findings
(counted 2026-10-13 by splitting P3 on its separators; the split is approximate). Everything filed under
the old rule was parked on 2026-10-13 in
[backlog-parked.md](./backlog-parked.md) — not deleted, not a queue.

**And the same task closes rows out of the file.** A row that a slice finishes
moves to [backlog-closed.md](./backlog-closed.md) carrying the closure note it
was closed with — flipping it to `✅` in place is how the queue became 41%
history by 2026-09-06, which defeats the one thing it is for. The note is worth
carrying rather than deleting: it is the only place that records why the
obstacle a row named turned out not to be the obstacle, and several rows closed
exactly that way.

## Branches & Commits

- Branch per slice: `feat/<slice>` for features, `chore/<...>` / `docs/<...>` for
  polish. Never start work on `main`.
- **Commit per task step** exactly as the plan specifies; the commit message says
  *why*. Co-author trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- After finishing a task: update [build-status.md](./build-status.md) and commit
  it with the task's own code.

## Versioning

The plugin's version is not a signature — it is part of the delivery mechanism.
`/plugin install` unpacks into `cache/video-grid/video-grid/<version>/`, so a slice
that lands without a bump lets a reinstall keep serving the old snapshot. That is
how the required `episode-qc` stage stayed missing from the installed skill set for
**316 commits** (2026-08-25).

Pre-1.0, so `MAJOR` stays at 0:

- **MINOR** (`0.X.0`) — a new capability, or a change in how the conveyor is
  driven: a new stage, a new required artifact, a renamed or removed flag, a
  changed default that alters the output.
- **PATCH** (`0.x.Y`) — fixes and hardening that leave the driving unchanged.
  A gate that refuses input which was already producing wrong results is a PATCH:
  nothing correct stops working.
- **Every merged slice bumps one of the two.** No slice lands with the version
  unmoved — including a **documentation-only** slice (a retro, a backlog refill, a
  rule like this one), which is a PATCH. `CHANGELOG.md` and `CLAUDE.md` ride into
  the plugin cache with everything else, and a change with no recorded version is a
  change nobody can point at.

The MINOR/PATCH line is a judgement, and the judgement is the point of writing it
down. Run-dir separation (0.2.1) is the worked example: it moved where every
artifact lands, which sounds like MINOR — but it added no flag, renamed no
signature, and its code change refuses a layout that was already corrupting the
next scan. The convention itself moved in skill text, which the agent reads. PATCH.

Bumping and saying what changed are **one act**: edit
[../CHANGELOG.md](../CHANGELOG.md) and `.claude-plugin/plugin.json` together.
`tests/test_plugin_manifests.py` asserts the changelog's top heading matches the
manifest, so forgetting either one reddens the suite.

## Documentation Standards

- Hierarchical headers; a `_Last updated:_` date near the top.
- Focus on **why**, not **what** — the code says what; the doc says why it is that
  way and what breaks if you change it.
- Line length ≤ 100 chars; code blocks carry a language hint.
- Link related docs with relative paths; keep each doc focused on one topic.
- `CLAUDE.md` is a **registry** (a Quick Reference table), not a narrative — new
  detail goes in a focused doc and gets one row in the table.

## Skill Standards

A skill's body is resident context, and it runs from the user's footage project,
never from the clone. Three rules follow, each machine-checked in
`tests/test_skill_convention.py` over the body **and** its reference pages —
moving a paragraph to a page must not move it out from under its own check.

- **Every `SKILL.md` carries the resolution preamble verbatim**, and names no
  command or path that is not anchored on `$VG` / `$ROOT`. The preamble resolves
  the recorded clone root once — and the path it reads is joined to the one
  `setup.sh` actually writes, because nothing else binds the two; every step
  then runs as `"$VG" scripts.X` and every reference reads as
  `"$ROOT/references/…"`. A bare `python -m scripts.X` or `python -c` is banned
  outright, with the `python3` and `python scripts/x.py` variants: all of them
  need the clone as working directory, which nothing guarantees, and
  `footage-intake` is why the launcher `cd`s there at all (ultralytics writes
  YOLO weights into `cwd`). Two things are names rather than paths anyone
  opens, and are held to a weaker rule: the frontmatter `description:` (a YAML
  scalar with no shell to expand `$ROOT` in) and the generated stage table,
  every path of which must still appear anchored elsewhere in the same body.
- **A router stage is a page** at `references/using-montage/<stage-key>.md`, one
  per live `V1_STAGES` key, set-equal in both directions with no exemption list.
  The stub in the body carries the command and the pointer to its page; the page
  carries the rest. The stage table above the stubs is generated — regenerate it
  with `"$VG" scripts.montage stages`, never by hand.
- **A body stays under 26 KB** — new material goes on a reference page. The
  number is a budget set from what the 2026-09-14 split measured itself landing
  (`using-montage` 22 268 B, `edit-plan` 18 340 B), not a threshold of anything
  (design 2026-09-14 §3.5). Every design projection of that split was wrong in
  the same direction, so the cap is the measurement, never the projection.

## Working Rules

- Do exactly what is asked — nothing more, nothing less.
- Prefer editing an existing file over creating a new one; flag obsolete files.
- Keep the project modular: pure logic in `scripts/lib/`, orchestration in
  `scripts/`, judgment in `skills/`.

## Related

- [coding-standards.md](./coding-standards.md) · [testing-guide.md](./testing-guide.md)
- [build-status.md](./build-status.md) — what is built and what is next.
