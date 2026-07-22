# Plugin packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the repo as a Claude Code plugin so a user adds it and installs it like a normal plugin, and the montage skills run from any working directory — not only from inside the checkout.

**Architecture:** A self dev-marketplace (`.claude-plugin/{plugin,marketplace}.json`) makes the skills discoverable; `SKILLS/` moves to the plugin-convention `skills/`; a single bash launcher `bin/vg` self-resolves the repo root from its own path, guards the venv, and `cd`s there before running `-m scripts.X` (mandatory — ultralytics downloads YOLO weights into `cwd`, design §1.1); every skill call-site routes through it with absolute paths. See [the design](../specs/2026-07-22-plugin-packaging-design.md).

**Tech Stack:** bash, Python 3.13 (`.venv`), pytest, Claude Code plugin manifests (JSON).

---

## File Structure

- **Create** `bin/vg` — the one launch chokepoint (§2.1).
- **Create** `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — manifests (§2.3).
- **Move** `SKILLS/` → `skills/` (§2.4); update the 16 live `SKILLS/` references in `scripts/` + current `docs/`.
- **Modify** the 16 pipeline call-sites in `skills/{using-montage,music-source,music-match,pacing,process-episode,project-init}/SKILL.md` (§2.5).
- **Rewrite** `README.md` for two audiences (§2.6).
- **Create tests** `tests/test_launcher.py`, `tests/test_plugin_manifests.py`, `tests/test_skill_convention.py`.
- **Docs sync** `CLAUDE.md`, `docs/build-status.md`, `docs/development-workflow.md`, `docs/pipeline-map.md` (§2.7).

Each task ends green and is committed separately.

---

### Task 0: `SKILLS/` → `skills/` move + reference sync

**Files:**
- Move: `SKILLS/` → `skills/`
- Modify: `scripts/reel_brief.py:5`, `scripts/process_episode.py:4`, `scripts/reel_review.py:5`, `scripts/lib/project.py:3`, `docs/coding-standards.md:24`, `docs/development-workflow.md:104`, `docs/build-status.md` (10 refs)

- [ ] **Step 1: Move the directory (two-step — macOS is case-insensitive)**

A one-shot `git mv SKILLS skills` can no-op on a case-insensitive filesystem. Go through a temp name:

```bash
git mv SKILLS _skills_tmp
git mv _skills_tmp skills
```

- [ ] **Step 2: Verify the move and that no skill self-references the old path**

```bash
ls skills/ | tr '\n' ' '; echo
grep -rn "SKILLS/" skills/ ; echo "self-refs EXIT: $?"   # expect no output
```
Expected: the 11 skill dirs listed; no `SKILLS/` inside `skills/`.

- [ ] **Step 3: Update the 16 live `SKILLS/` references to `skills/`**

These are docstrings and current docs (the dated `docs/plans/` and `docs/specs/` are historical record — leave them). The token is unique; replace in exactly these files:

```bash
for f in scripts/reel_brief.py scripts/process_episode.py scripts/reel_review.py \
         scripts/lib/project.py docs/coding-standards.md docs/development-workflow.md \
         docs/build-status.md; do
  perl -pi -e 's{SKILLS/}{skills/}g' "$f"
done
```

- [ ] **Step 4: Confirm no live `SKILLS/` reference remains outside history**

```bash
grep -rn "SKILLS/" --include="*.py" --include="*.md" . | grep -vE "docs/plans/|docs/specs/"
echo "remaining EXIT: $?"
```
Expected: no output (grep EXIT 1).

- [ ] **Step 5: Run the full suite — the move must break nothing**

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -5 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: same green as before the move (no test references `SKILLS/`).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: SKILLS/ -> skills/ (plugin-convention skills dir)

The plugin loader scans skills/ (lowercase) at plugin root; move the 11 skill
dirs there and repoint the 16 live SKILLS/ references in scripts docstrings and
current docs. Historical docs/plans and docs/specs keep their as-written paths.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: `bin/vg` launcher (the cwd-independence contract)

**Files:**
- Create: `bin/vg`
- Test: `tests/test_launcher.py`

- [ ] **Step 1: Write the failing tests**

```python
"""bin/vg launcher (design 2026-07-22 §2.1) — the cwd-independence contract.

The launcher is the ONE door skills use to run the pipeline. Two properties no
skill edit can be trusted to preserve, so they are pinned here: it resolves the
repo root from its OWN path (works from any cwd), and it fails loud — naming
setup.sh — when the venv is absent, rather than emitting a raw ENOENT.
"""
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VG = REPO / "bin" / "vg"


def test_launcher_runs_from_a_foreign_cwd(tmp_path):
    """Invoked with cwd OUTSIDE the checkout, bin/vg still resolves ROOT and runs
    `-m scripts.montage` — proving the launcher, not cwd, supplies the root."""
    run = tmp_path / "run"
    run.mkdir()
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    proc = subprocess.run(
        [str(VG), "scripts.montage", "status", "--run-dir", str(run)],
        cwd=str(scratch), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert '"project-init"' in proc.stdout
    assert '"state": "next"' in proc.stdout


def test_launcher_fails_loud_without_a_venv(tmp_path):
    """A copy of the launcher in a tree with no .venv exits non-zero and names
    setup.sh — the mutation dropping the guard would surface a raw ENOENT."""
    fake = tmp_path / "checkout"
    (fake / "bin").mkdir(parents=True)
    shutil.copy(VG, fake / "bin" / "vg")
    (fake / "bin" / "vg").chmod(0o755)
    proc = subprocess.run(
        [str(fake / "bin" / "vg"), "scripts.montage", "status"],
        capture_output=True, text=True)
    assert proc.returncode != 0
    assert "setup.sh" in proc.stderr
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_launcher.py -q -p no:cacheprovider 2>&1 | tail -5 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: FAIL (bin/vg does not exist).

- [ ] **Step 3: Write the launcher**

Create `bin/vg`:

```bash
#!/usr/bin/env bash
# The one place that knows HOW to run the video-grid pipeline (design 2026-07-22 §2.1).
# Self-resolves the repo root from its OWN location so it is correct from any cwd,
# guards the venv (the fail-loud remedy point), then cd's to root — mandatory, not
# cosmetic: ultralytics downloads the YOLO weights by bare name into cwd (design
# §1.1), so PYTHONPATH alone would re-download them into the wrong directory.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "video-grid: no venv at $ROOT/.venv — run: bash \"$ROOT/setup.sh\"" >&2
  exit 1
fi
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m "$@"
```

- [ ] **Step 4: Make it executable**

```bash
chmod +x bin/vg
```

- [ ] **Step 5: Run to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_launcher.py -q -p no:cacheprovider 2>&1 | tail -5 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add bin/vg tests/test_launcher.py
git commit -m "feat: bin/vg — the one cwd-independent launch chokepoint

Self-resolves ROOT from its own path, guards the venv with a setup.sh remedy,
cd's to ROOT (mandatory — ultralytics writes YOLO weights into cwd, design §1.1),
execs .venv/bin/python -m on the module it is handed. Pins cwd-independence and
fail-loud so no skill edit can silently reintroduce the relative-cwd assumption.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Plugin + marketplace manifests

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Test: `tests/test_plugin_manifests.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Plugin + marketplace manifests (design 2026-07-22 §2.3).

Pins the facts a broken manifest fails silently on: valid JSON naming
`video-grid`, a marketplace listing it from the repo root, and `.claude-plugin/`
holding ONLY manifests (the reference's Critical Rule 1 — a skill or script
leaking in there is a structure bug).
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CP = REPO / ".claude-plugin"


def test_plugin_manifest_names_video_grid():
    data = json.loads((CP / "plugin.json").read_text())
    assert data["name"] == "video-grid"
    assert data["version"]
    assert data["description"]


def test_marketplace_lists_the_plugin_from_repo_root():
    data = json.loads((CP / "marketplace.json").read_text())
    entry = next(p for p in data["plugins"] if p["name"] == "video-grid")
    assert entry["source"] == "./"


def test_claude_plugin_holds_only_manifests():
    assert {p.name for p in CP.iterdir()} == {"plugin.json", "marketplace.json"}
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_plugin_manifests.py -q -p no:cacheprovider 2>&1 | tail -5 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: FAIL (`.claude-plugin/` does not exist).

- [ ] **Step 3: Write `.claude-plugin/plugin.json`**

```json
{
  "name": "video-grid",
  "version": "0.1.0",
  "description": "AI-assisted video montage: a folder of raw footage plus a natural-language brief becomes a delivered reel, for any platform. Requires a one-time `bash setup.sh` runtime install.",
  "author": {
    "name": "Sergei Vasechko"
  },
  "homepage": "https://github.com/vasechko-sergey/video-grid",
  "repository": "https://github.com/vasechko-sergey/video-grid"
}
```

- [ ] **Step 4: Write `.claude-plugin/marketplace.json`**

```json
{
  "name": "video-grid",
  "description": "Self dev-marketplace for the video-grid montage plugin.",
  "owner": {
    "name": "Sergei Vasechko"
  },
  "plugins": [
    {
      "name": "video-grid",
      "description": "AI-assisted video montage skill set (project-init -> footage-intake -> edit-plan -> reel).",
      "source": "./",
      "author": {
        "name": "Sergei Vasechko"
      }
    }
  ]
}
```

- [ ] **Step 5: Run to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_plugin_manifests.py -q -p no:cacheprovider 2>&1 | tail -5 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin tests/test_plugin_manifests.py
git commit -m "feat: .claude-plugin manifests — plugin.json + self dev-marketplace

Names the plugin video-grid and lists it from the repo root (source ./), so
\`/plugin marketplace add .\` + \`/plugin install video-grid@video-grid\` works.
.claude-plugin/ carries only the two manifests (plugin-structure Critical Rule 1).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Route every skill call-site through `bin/vg`

**Files:**
- Test: `tests/test_skill_convention.py`
- Modify: `skills/{using-montage,music-source,music-match,pacing,process-episode,project-init}/SKILL.md`

- [ ] **Step 1: Write the failing lint tests**

```python
"""Skill launch convention (design 2026-07-22 §2.5).

Every pipeline command a skill issues must go through bin/vg, never a bare
`.venv/bin/python` (which silently assumes cwd is the checkout — the exact bug
this slice removes). Lints the outcome so a reverted call-site fails loud, and
catches line-wrapped invocations a text-replace would miss.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
# the 6 skills that issue pipeline commands (design §2.5)
RUNNERS = {"using-montage", "music-source", "music-match", "pacing",
           "process-episode", "project-init"}


def test_no_skill_invokes_a_bare_venv_python():
    offenders = sorted(str(p.relative_to(REPO)) for p in SKILLS.glob("*/SKILL.md")
                       if ".venv/bin/python" in p.read_text())
    assert offenders == [], f"skills bypassing bin/vg: {offenders}"


def test_the_runner_skills_route_through_bin_vg():
    for name in sorted(RUNNERS):
        text = (SKILLS / name / "SKILL.md").read_text()
        assert "bin/vg" in text, f"{name} lost its bin/vg launcher"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_skill_convention.py -q -p no:cacheprovider 2>&1 | tail -8 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: FAIL (`test_no_skill_invokes_a_bare_venv_python` lists 6 files; `bin/vg` absent).

- [ ] **Step 3: Add the launcher preamble to each of the 6 runner skills**

Into each of the 6 skills, near its first pipeline invocation (for `using-montage`, at step 0/1 "Ensure env"; for the others, right before their first command), insert this block verbatim (adjust the skill name in the path):

```markdown
**Launcher.** Run every pipeline step through the repo-root launcher `bin/vg`,
never a bare `.venv/bin/python`. Resolve it once: this skill lives at
`<repo>/skills/<name>/`, so the launcher is two levels up. Set
`VG=<repo>/bin/vg` (an absolute path) and pass **absolute** paths for every
footage / run / output directory — `bin/vg` runs from the repo root, so a
relative artifact path would land inside the checkout. If `bin/vg` reports no
venv, the user has not run `bash setup.sh` yet.
```

- [ ] **Step 4: Replace all 16 invocations**

In the same 6 files, replace every `.venv/bin/python -m scripts.X` (16 total; some are line-wrapped, e.g. `using-montage` around the pacing call — the `-m` ends a line and `scripts.pacing` starts the next) with `"$VG" scripts.X`, preserving all arguments. The lint test in Step 6 confirms none were missed, wrapped or not.

For `using-montage` step 0, keep the `bash setup.sh` mention but frame it as the one-time install step, not a per-run command (the launcher's own remedy message covers a missing venv).

- [ ] **Step 5: Sanity-check the replacement count**

```bash
grep -rc "\"\$VG\" scripts\." skills/*/SKILL.md | grep -v ':0' ; echo "---"
grep -rn "\.venv/bin/python" skills/*/SKILL.md ; echo "bare-venv EXIT: $?"
```
Expected: the `"$VG" scripts.` counts sum to 16 across the 6 files; no bare `.venv/bin/python` remains (grep EXIT 1).

- [ ] **Step 6: Run to verify the lint passes**

```bash
.venv/bin/python -m pytest tests/test_skill_convention.py -q -p no:cacheprovider 2>&1 | tail -5 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add skills tests/test_skill_convention.py
git commit -m "feat: skills run the pipeline through bin/vg, not a relative venv

The 16 call-sites across the 6 runner skills (using-montage, music-source,
music-match, pacing, process-episode, project-init) now resolve an absolute VG
launcher from the skill's own base dir and pass absolute footage/run/output
paths. A lint test forbids any bare .venv/bin/python (the cwd-assuming bug) and
requires each runner to reference bin/vg.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: README for two audiences (Use / Develop)

**Files:**
- Rewrite: `README.md`

- [ ] **Step 1: Rewrite `README.md`**

```markdown
# video-grid

Turn a folder of raw footage plus a one-line brief into a finished reel, for any
platform. An AI-assisted montage **skill set** for Claude Code — you describe the
video in plain language; the skills conduct the pipeline (project setup →
footage intake → edit plan → per-episode reframing → assembly → checks →
delivery), stopping only at three review checkpoints.

> **Two halves, both required.** The **plugin** distributes the skills; a one-time
> **`bash setup.sh`** provisions the runtime it drives (a Python venv, a
> full-featured `ffmpeg`, YOLO weights). A plugin install alone cannot make a reel.
> macOS + Homebrew for now.

## Use

**1. Get the runtime.**

```bash
git clone git@github.com:vasechko-sergey/video-grid.git
cd video-grid
bash setup.sh          # venv + ffmpeg-full (drawtext + vidstab) + fonts; weights on first run
```

Optional capability flags compose: `bash setup.sh --with-demucs` (sharper music
in-point) and `--with-sourcing` (fetch tracks from the internet).

**2. Install the plugin** (from inside the clone):

```
/plugin marketplace add .
/plugin install video-grid@video-grid
```

Restart Claude Code so it picks up the skills.

**3. Make a reel.** From *any* project directory, describe what you want:

> "make a 9:16 reel from ~/Movies/trip — upbeat, no titles"

The `using-montage` skill takes over: it sets the project aspect, scans the
footage, plans the edit, renders and checks the reel, and stops at the three
checkpoints (SPEC → EDL → final review) for your approval. Point it at any
footage folder by absolute path; the output lands in that run's `out/`.

Individual stages have their own skills if you want to re-run just one
(`project-init`, `footage-intake`, `edit-plan`, `process-episode`, `music-match`,
`music-source`, `pacing`, `reel-brief`, `titles`, `reel-review`).

## Develop

Working on the code? Start at the **[CLAUDE.md](CLAUDE.md)** registry — it maps to
the [design spec](docs/specs/2026-07-05-montage-skillset-design.md), the
[coding standards](docs/coding-standards.md), the
[testing guide](docs/testing-guide.md), the
[development workflow](docs/development-workflow.md), the
[build status](docs/build-status.md), and the
[pipeline map](docs/pipeline-map.md).

Layout: engine code and CLIs in `scripts/` (run as modules: `bin/vg scripts.X …`,
or `.venv/bin/python -m scripts.X` from the repo root); the interactive/editorial
judgment in `skills/*/SKILL.md`; typed wire-contracts and config-specs in
`scripts/lib/`. New work is design → plan → subagent-driven TDD; every change
keeps the design spec, the plan checkboxes, and `docs/build-status.md` in sync.

```bash
.venv/bin/python -m pytest -q            # the whole suite
.venv/bin/python -m pytest -q -m integration   # the real-ffmpeg / real-weights proofs
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for Use + Develop, with the plugin install flow

Leads with what it is and the two-command runtime + two-command plugin install,
then a plain-language quickstart; a Develop half points at the CLAUDE.md registry.
An honest banner states the plugin ships skills while setup.sh provisions the
runtime — both required, macOS-only for now.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Docs sync + registry + final whole-slice review

**Files:**
- Modify: `CLAUDE.md`, `docs/build-status.md`, `docs/development-workflow.md`, `docs/pipeline-map.md`

- [ ] **Step 1: Add two registry rows to `CLAUDE.md`**

In the Quick Reference table, after the tracking-ladder rows, add:

```markdown
| Plugin packaging design | [2026-07-22-plugin-packaging-design.md](docs/specs/2026-07-22-plugin-packaging-design.md) | Install video-grid as a Claude Code plugin: self dev-marketplace + `SKILLS/`→`skills/` + the `bin/vg` launch chokepoint. **§1 load-bearing:** a skill never assumes `cwd` — it resolves ROOT from its harness-given base dir and hands it to `bin/vg`, which self-resolves and **`cd`s** there (**§1.1:** mandatory, not `PYTHONPATH` — ultralytics writes YOLO weights into `cwd`, a §12 trap). §4 honest half: plugin ≠ runtime (`setup.sh` still required), macOS-only, GitHub-remote marketplace deferred. |
| Plugin packaging plan | [2026-07-22-plugin-packaging.md](docs/plans/2026-07-22-plugin-packaging.md) | Tasks 0–5: `SKILLS/`→`skills/` move + 16 ref sync, `bin/vg` launcher (cwd-independence + fail-loud), `.claude-plugin` manifests, 16 skill call-sites onto the launcher + lint guard, two-audience README, docs sync. |
```

- [ ] **Step 2: Add a build-status entry**

At the top of `docs/build-status.md`'s recent-work section (matching the existing entry style), add a short entry summarizing the slice: the plugin manifests, the `SKILLS/`→`skills/` move, the `bin/vg` chokepoint and why `cd $ROOT` is load-bearing (ultralytics weights), the README, and the honest limits (plugin ≠ runtime, macOS-only, remote marketplace deferred). Note the suite count after Step 4.

- [ ] **Step 3: Note the packaging in `docs/development-workflow.md`**

Near the top env/setup section, add one line: the repo is packaged as a Claude Code plugin (`.claude-plugin/`); skills run the pipeline through `bin/vg` (the cwd-independent launcher), and `bin/vg scripts.X` is the module entrypoint. Confirm the `SKILLS/`→`skills/` reference from Task 0 reads correctly in context.

- [ ] **Step 4: Full suite green**

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -6 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: all green (prior count + the new launcher/manifest/convention tests). Record the number in Step 2's entry.

- [ ] **Step 5: Final whole-slice review**

Dispatch a code-review subagent (superpowers:requesting-code-review) over `main..feat/plugin-packaging`. It must confirm: `bin/vg` is cwd-independent and fails loud; `.claude-plugin/` holds only manifests and names `video-grid`; no skill retains a bare `.venv/bin/python`; the `SKILLS/`→`skills/` move left no dangling live reference; README is accurate about the plugin/runtime split. Address blocking findings as separate follow-up commits (never `--amend`).

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/build-status.md docs/development-workflow.md docs/pipeline-map.md
git commit -m "docs: sync registry, build-status, workflow for plugin packaging

Two CLAUDE.md registry rows (design + plan), a build-status entry recording the
slice and suite count, and a development-workflow note that the repo is a Claude
Code plugin whose skills run through the cwd-independent bin/vg launcher.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** §2.1 bin/vg → Task 1; §2.3 manifests → Task 2; §2.4 move → Task 0; §2.5 call-sites → Task 3; §2.6 README → Task 4; §2.7 docs → Task 5; §5 tests → the three test files across Tasks 1–3; §5 manual smoke → left to the user (README + design note), not asserted by the suite. §1.1's `cd $ROOT` rationale is encoded in `bin/vg` and its test. Covered.

**Placeholder scan:** No TBD/TODO. Task 3 Steps 3–4 describe a prose edit rather than a literal diff (16 call-sites, some line-wrapped, across 6 files) — but the exact preamble text, the exact transformation (`.venv/bin/python -m scripts.X` → `"$VG" scripts.X`), a count sanity-check (Step 5), and a gating lint test (Steps 1/6) make it verifiable, not vague. This is the one place a per-line literal diff is impractical and a machine gate replaces it.

**Type/name consistency:** `VG` / `bin/vg` / `.claude-plugin` / `skills/` / marketplace `video-grid` / install `video-grid@video-grid` are spelled consistently across tasks, tests, README, and manifests. The lint `RUNNERS` set matches the 6 skills named in the design §2.5 and Task 3. `montage status` is the launcher smoke command (verified: exits 0, prints `"project-init"` / `"state": "next"` on an empty run dir).
