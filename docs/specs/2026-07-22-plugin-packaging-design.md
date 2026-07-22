# Plugin packaging — install video-grid as a Claude Code plugin

**Status:** design · 2026-07-22
**Scope:** package the repo so a user *adds it and installs it as an ordinary
Claude Code plugin*, and the montage skills become discoverable and runnable from
**any** working directory — not only from inside the checkout.

## 0. The ask, precisely

Today the skill set works only under two unstated conditions: (a) Claude Code must
*see* the skills, and (b) the current directory must *be* the checkout. Neither is
documented, and the first is not even wired — `SKILLS/` (uppercase) is not a skill
search path, so a fresh Claude Code never discovers `using-montage` at all.

The user's chosen shape: **add the repository, install it like a normal plugin,
the scripts ride along with the skills (no symlink step), and it should be
simple.** This design makes that true instead of aspirational, and writes the
README for two equal audiences (Use / Develop).

## 1. The load-bearing decision — never assume `cwd`; the skill hands the launcher an absolute root

A Claude Code plugin distributes **skills** (discovery). It does **not** provision
the **runtime** — the Python `.venv`, the keg-only `ffmpeg-full`, the YOLO weights.
That runtime is built by `setup.sh` and lives in a checkout. So the plugin and the
runtime may be two things in two different directories, and the whole design turns
on one rule:

> **A skill must never assume the current directory is the checkout.**

Today every skill breaks that rule silently: it runs `.venv/bin/python -m
scripts.X` — a path relative to `cwd`. That resolves only because the author sits
*inside* the clone. Invoked as a plugin from an arbitrary project directory it
fails: no `.venv` there, and `-m scripts.X` finds no `scripts` package.

The fix uses a fact the harness already provides: **Claude is always told a skill's
own base directory** when the skill loads ("Base directory for this skill: …"). In
the supported install the skill lives at `<root>/skills/<name>/`, so the repository
root is two levels up — the skill resolves it to an **absolute** path and hands it
to a launcher. No relative `cwd`, no external config file, no `setup.sh` change.

### 1.1 Why `cwd = ROOT`, not merely `PYTHONPATH=ROOT`

Most of the Python is already cwd-independent: `ffbin` and `catalog` resolve
`config/` through `Path(__file__).resolve().parents[2]`, not `cwd`; no script calls
`chdir`/`getcwd` or writes to a bare relative path (all outputs are `--out-dir`
arguments). So `PYTHONPATH=ROOT python -m scripts.X` *almost* suffices.

The exception is the tracker, and it is a §12-shaped silent trap. Ultralytics
resolves the weights by **bare NAME** (`yolo11n-seg.pt`) and auto-downloads a
missing name **into `cwd`** — an absolute path would defeat the auto-download, so
the name cannot simply be anchored (design §12; `.gitignore` records the same gap).
Run from the wrong `cwd` and ultralytics re-downloads the weights into that
directory — or, under the cap-3 fan-out, multiple workers race to write one file.
The fix is to run with **`cwd = ROOT`**, where the weights already sit, not just to
patch `sys.path`. So the launch convention is a real `cd`, not an environment tweak.

## 2. Components

### 2.1 `bin/vg` — the one launch chokepoint

A tiny bash launcher is the single place that knows *how* to run the pipeline,
mirroring `ffbin.has_filter` ("the ONE place this question is asked"). It
self-resolves `ROOT` from **its own** location (`bin/vg` ⇒ `ROOT = dirname/..`),
guards that the venv exists (the fail-loud remedy point), `cd`s there, and `exec`s
the venv interpreter on the module it is handed:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -x "$ROOT/.venv/bin/python" ] || {
  echo "video-grid: no venv at $ROOT/.venv — run: bash \"$ROOT/setup.sh\"" >&2; exit 1; }
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m "$@"
```

Self-resolution makes `bin/vg` authoritative for its own tree and correct even when
called directly or from any `cwd`. It fixes both cwd hazards — module import and the
ultralytics weights — in one audited, tested spot, so the 16 skill call-sites carry
no `cd`/venv boilerplate, and a missing runtime fails loud with the exact remedy
instead of a raw `ENOENT`.

### 2.2 How a skill finds the launcher — from its own base directory

The skill does not read `cwd` and does not read an external file. It uses the base
directory the harness gives it: the repository root is two levels above
`skills/<name>/`, so

```
VG="<resolved-skill-base>/../../bin/vg"      # resolve to an absolute path once
```

`bin/vg` then re-derives `ROOT` authoritatively from that path (2.1), so even a
slightly-off derivation cannot run against the wrong tree — it either hits the right
`bin/vg` or fails loud with "no such file." No silent fallback.

This works because the supported install co-locates skills and runtime in one
checkout (§3). Decoupling them — a plugin discovered from a cache while the runtime
lives in a separate clone — is the deferred GitHub-remote case (§4), and only that
case needs a recorded-root anchor outside the tree.

**Correction (2026-07-22):** wrong — the first real `/plugin install` showed the
*local* `directory` marketplace decouples them too. `/plugin install` copies the
skills into a runtime-less cache, so a base-dir derivation always resolves to that
broken copy, never the clone; there is no install where §2.2 as written works. The
recorded-root anchor this section deferred to §4's GitHub-remote case is used
instead, unconditionally — see
[2026-07-22-plugin-runtime-resolution-design.md](2026-07-22-plugin-runtime-resolution-design.md).

### 2.3 Plugin manifests

- `.claude-plugin/plugin.json` — `name: video-grid`, `version`, `description`,
  `author`, `homepage`/`repository`
  (`https://github.com/vasechko-sergey/video-grid`). Skills auto-discover from
  `skills/`; no MCP/hooks/commands in v1.
- `.claude-plugin/marketplace.json` — a self dev-marketplace, one plugin,
  `source: "./"`. This is what makes `/plugin marketplace add <clone>` work
  (developing-claude-code-plugins, plugin-structure.md §"Development Marketplace").

`.claude-plugin/` holds **only** manifests (the reference's Critical Rule 1);
skills and scripts stay at plugin root.

### 2.4 `SKILLS/` → `skills/`

A real move (not a symlink — the user's "scripts ride with the skill, no linking":
the plugin bundles `skills/` and `scripts/` together, and installing the plugin
brings both). `skills/` (lowercase) is the plugin convention the loader scans. The
~8 live references to `SKILLS/` in current docstrings/docs are updated; the dated
`docs/plans/` and `docs/specs/` are historical record and left as written.

### 2.5 Skill invocation convention

The 16 call-sites in 6 skills (`using-montage` 6, `music-source` 4, `music-match`
2, `pacing` 2, `process-episode` 1, `project-init` 1) change from

```
.venv/bin/python -m scripts.X <relative args>
```
to a self-sufficient two lines each skill resolves for itself:
```
VG="<skill-base>/../../bin/vg"          # absolute; every skill with call-sites does this
"$VG" scripts.X <ABSOLUTE args>
```

Each of the 6 skills resolves `VG` on its own, so a sub-skill invoked standalone
(e.g. `process-episode` called directly) still works — nothing is *inherited* from
`using-montage`. What `using-montage` conducts across the run is the shared set of
**absolute** footage/run/output paths, not the launcher. Every footage/output/run
path a skill passes becomes absolute — the launcher's `cd $ROOT` means a relative
artifact path would now land inside the checkout, which is exactly the bug we are
removing.

### 2.6 README — two equal audiences

- **Use:** what it is → install (`git clone` → `bash setup.sh` → `/plugin
  marketplace add .` → `/plugin install video-grid`) → quickstart (open any
  project, "make a 9:16 reel from ~/Movies/trip"). One honest banner: the plugin
  distributes the skills, `setup.sh` provisions the runtime — both are required,
  and it is macOS/homebrew for now.
- **Develop:** the CLAUDE.md registry pointer, the test command, the
  design→plan→TDD workflow.

### 2.7 Docs sync

CLAUDE.md registry (design + plan rows), `docs/build-status.md`,
`docs/pipeline-map.md`, `docs/development-workflow.md` (the `SKILLS/`→`skills/`
mentions and a short "packaged as a plugin" note), `docs/coding-standards.md` (its
one `SKILLS/` reference).

## 3. Install flow (what the user actually does)

```
git clone git@github.com:vasechko-sergey/video-grid.git
cd video-grid
bash setup.sh                       # venv + ffmpeg-full + fonts + weights-on-first-run
/plugin marketplace add .           # the self dev-marketplace
/plugin install video-grid          # skills now discoverable everywhere
# then, from ANY directory:
#   "make a 9:16 reel from ~/Movies/trip, upbeat, no titles"
```

Two commands of runtime, two of plugin, then use from anywhere.

## 4. What this does NOT do (the honest half)

- **A plugin install alone cannot make a reel.** It ships skills, not a `.venv`,
  not `ffmpeg-full`, not weights. `setup.sh` is not optional and the README says so
  in a banner, not a footnote.
- **macOS/homebrew only**, inheriting `setup.sh`'s existing limitation. `bin/vg` is
  bash; Windows needs the polyglot wrapper (developing-claude-code-plugins
  `references/polyglot-hooks.md`) — deferred, same stance as `setup.sh`.
- **No GitHub-remote marketplace yet.** `/plugin marketplace add
  vasechko-sergey/video-grid` from GitHub would clone into the plugin cache, where
  the `.venv` would have to be rebuilt on **every version bump** — wrong for a
  heavy runtime, and the skill's base-directory derivation (2.2) would point at the
  cache, which has no venv. The supported path is the local-clone dev-marketplace
  above. Making the remote path work is a distribution follow-up: record the
  runtime root outside the tree (`~/.config/video-grid/root`, written by `setup.sh`)
  and have skills read it instead of deriving from their base. Mechanically small,
  deliberately deferred.
- **No LICENSE is added** here (the repo has none). `plugin.json` omits the
  `license` field until one exists — adding it is a separate, trivial follow-up.
- **The scripts are not split per-skill.** "Scripts ride with the skill" is
  satisfied by bundling one shared `scripts/` package beside `skills/` in the
  plugin; `scripts.lib.*` is imported across skills and must stay one package.

**Correction (2026-07-22):** the "deferred" framing above was wrong — the first
real `/plugin install` found the **local** `directory` marketplace hits the same
runtime-less-cache problem this section assigned only to the GitHub-remote case.
The recorded-root anchor is therefore not a future follow-up; it is built now. See
[2026-07-22-plugin-runtime-resolution-design.md](2026-07-22-plugin-runtime-resolution-design.md).

## 5. Testing

Packaging is lighter than an engine slice, and some proofs need the user's own
Claude Code (like the ffmpeg-baseline proof, FB Task 7). Split honestly:

**Automated (pytest / shell, in-suite):**
- `bin/vg` cwd-independence: from a scratch `cwd` (e.g. `/tmp`), `bin/vg
  scripts.montage status --run-dir <tmp>` resolves ROOT, imports `scripts`, and
  runs — proving the launcher, not `cwd`, supplies the root. Dropping the `cd` (a
  mutation) must fail this.
- `bin/vg` fail-loud: pointed at a tree with no `.venv`, it exits non-zero and
  names `bash setup.sh` — a raw `ENOENT` would not.
- Manifests are valid JSON and name `video-grid`; `.claude-plugin/` contains only
  the two manifests.
- The move left no live `SKILLS/` reference in `scripts/` or current `docs/`
  (grep), and the full suite stays green (no test references `SKILLS/` — verified
  at design time).
- Lint parity with the repo's ethos: no skill call-site still spells a bare
  relative `.venv/bin/python` — the launcher is the only door.

**Manual smoke (needs the user's install):** `/plugin marketplace add .` →
`/plugin install video-grid` → from a foreign directory, a one-line montage brief
reaches `out/REEL_v1.mp4`. Documented in the plan as a user-run proof, not asserted
green by the suite.

## 6. Out of scope / follow-ups

- GitHub-remote marketplace + the recorded-root anchor and venv story for the
  plugin cache (§4).
- Cross-platform `setup.sh`/`bin/vg` (Linux/Windows).
- Adding a LICENSE and its `plugin.json` field.
- Splitting the self dev-marketplace out into a standalone marketplace repo (only
  matters once there is a second plugin to list).
