# Plugin runtime-resolution fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the installed plugin run the pipeline (skills resolve the clone via a `setup.sh`-recorded root, not their runtime-less cache copy), and stop the install from copying a 1.1 GB venv (external venv + a `.venv` symlink).

**Architecture:** `setup.sh` builds the venv at an external XDG path and points `<clone>/.venv` at it with a symlink, then records the clone's absolute path to `~/.config/video-grid/root`. The 6 runner skills' launcher preamble reads that file to locate `<clone>/bin/vg`. `bin/vg` and the 16 call-sites are unchanged (the symlink is transparent; `VG` just resolves differently). See [the design](../specs/2026-07-22-plugin-runtime-resolution-design.md).

**Tech Stack:** bash (`setup.sh`, `bin/vg`), Python 3.13 (`.venv`), pytest, Claude Code plugin.

---

## File Structure

- **Modify** `setup.sh` — external venv + `.venv` symlink (+ migration) + recorded-root write.
- **Modify** `.gitignore` — `.venv/` → `.venv` (ignore the symlink too).
- **Create test** `tests/test_setup_runtime.py` — setup.sh emits the external venv, the symlink, the recorded-root.
- **Modify** the 6 runner skills' launcher preamble (`skills/{using-montage,music-source,music-match,pacing,process-episode,project-init}/SKILL.md`) — read the recorded root instead of deriving ROOT from the skill's base dir.
- **Modify** `tests/test_skill_convention.py` — add: each runner reads the recorded-root file.
- **Modify** `README.md` — `/plugin marketplace add .` → `./`; note the runtime lives in the clone.
- **Docs sync** — correct the packaging design §2.2/§4, `docs/build-status.md`, `CLAUDE.md` registry, `docs/development-workflow.md`.

`bin/vg` and `tests/test_launcher.py` are deliberately untouched.

---

### Task 0: `setup.sh` — external venv, `.venv` symlink, recorded root

**Files:**
- Modify: `setup.sh`, `.gitignore`
- Test: `tests/test_setup_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_setup_runtime.py`:

```python
"""setup.sh runtime layout (design 2026-07-22 runtime-resolution §2/§3).

setup.sh is shell, not Python — its real behaviour is a user-run proof (rebuild +
/plugin install). This lints that it EMITS the three operations the fix depends on,
so a regression that drops one fails loud here: an external venv, a `.venv` symlink
into it, and the recorded runtime root outside the tree.
"""
from pathlib import Path

SETUP = (Path(__file__).resolve().parents[1] / "setup.sh").read_text()


def test_venv_is_built_at_an_external_xdg_path():
    assert "XDG_DATA_HOME" in SETUP
    assert "video-grid/venv" in SETUP  # not $SKILL_DIR/.venv any more


def test_dot_venv_is_a_symlink_into_the_external_venv():
    assert "ln -sfn" in SETUP
    # the in-repo .venv is replaced by a link, not a real dir (migration)
    assert '"$SKILL_DIR/.venv"' in SETUP


def test_setup_records_the_runtime_root_outside_the_tree():
    assert "XDG_CONFIG_HOME" in SETUP
    assert "video-grid" in SETUP and "/root" in SETUP
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_setup_runtime.py -q -p no:cacheprovider 2>&1 | tail -6 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: FAIL (`XDG_DATA_HOME`/`ln -sfn`/`XDG_CONFIG_HOME` not in setup.sh yet).

- [ ] **Step 3: Point `VENV` at an external XDG path**

In `setup.sh`, change the `VENV` assignment near the top (currently `VENV="$SKILL_DIR/.venv"`) to:

```bash
# The venv lives OUTSIDE the repo so `/plugin install`'s cp -R does not copy 1.1 GB
# into the plugin cache; <repo>/.venv becomes a symlink to it (below), which keeps
# every `.venv/bin/python` path working. (design 2026-07-22 runtime-resolution §3)
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/video-grid/venv"
```

- [ ] **Step 4: Build the external venv, symlink `<repo>/.venv`, migrate a real one**

Replace the `# --- venv + python deps ---` block (currently:
```bash
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
```
) with:

```bash
# --- venv (external; <repo>/.venv is a symlink to it) + python deps ---
mkdir -p "$(dirname "$VENV")"
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
# Migrate a pre-existing in-repo real venv to the symlink layout, then link. `ln -sfn`
# replaces an existing symlink atomically; a real dir must be removed first (its 1.1 GB
# is exactly what we are moving out of the tree).
if [ -e "$SKILL_DIR/.venv" ] && [ ! -L "$SKILL_DIR/.venv" ]; then
  rm -rf "$SKILL_DIR/.venv"
fi
ln -sfn "$VENV" "$SKILL_DIR/.venv"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
```

- [ ] **Step 5: Record the runtime root at the end**

At the end of `setup.sh`, after `mkdir -p "$SKILL_DIR/models"` and before/around the final `echo "venv ready…"`, add:

```bash
# Record where the runtime lives. Claude Code installs the montage skills by COPYING
# them into a runtime-less plugin cache, so a skill cannot find this checkout from its
# own (copied) location — it reads this file and runs <clone>/bin/vg. Outside the tree
# on purpose. (design 2026-07-22 runtime-resolution §2)
VG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/video-grid"
mkdir -p "$VG_CONFIG"
printf '%s\n' "$SKILL_DIR" > "$VG_CONFIG/root"
echo "recorded runtime root -> $VG_CONFIG/root ($SKILL_DIR)"
```

- [ ] **Step 6: `.gitignore` — ignore the symlink**

In `.gitignore`, change `.venv/` to `.venv` (the trailing-slash form matches only a directory; after this fix `.venv` is a symlink, which git would otherwise want to track):

```
.venv
```

- [ ] **Step 7: Run to verify the lint passes**

```bash
.venv/bin/python -m pytest tests/test_setup_runtime.py -q -p no:cacheprovider 2>&1 | tail -6 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: PASS (3 tests). Do NOT run `setup.sh` itself (it installs system deps; behaviour is the user-run proof).

- [ ] **Step 8: Commit**

```bash
git add setup.sh .gitignore tests/test_setup_runtime.py
git commit -m "feat: setup.sh builds an external venv, symlinks .venv, records the root

The venv moves to \${XDG_DATA_HOME:-~/.local/share}/video-grid/venv and <repo>/.venv
becomes a symlink to it, so /plugin install's cp -R copies a symlink (measured: 0
bytes) instead of 1.1 GB, while every .venv/bin/python path keeps working. setup.sh
also records the clone's abspath to ~/.config/video-grid/root so the montage skills —
copied into a runtime-less plugin cache — can find and run this checkout. .gitignore
ignores the .venv symlink.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1: skills read the recorded root (not their base dir)

**Files:**
- Modify: `skills/{using-montage,music-source,music-match,pacing,process-episode,project-init}/SKILL.md`
- Test: `tests/test_skill_convention.py`

- [ ] **Step 1: Extend the lint test (write the new assertion first)**

In `tests/test_skill_convention.py`, add a third test (keep the two existing ones):

```python
def test_the_runner_skills_read_the_recorded_root():
    """The launcher path must come from setup.sh's recorded root, not from the
    skill's own base directory — the install copies skills to a runtime-less cache,
    so a base-dir-relative launcher (design §2.2, since corrected) would hit the
    broken cache venv. (design 2026-07-22 runtime-resolution §2)"""
    for name in sorted(RUNNERS):
        text = (SKILLS / name / "SKILL.md").read_text()
        assert "video-grid/root" in text, f"{name} does not read the recorded root"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_skill_convention.py -q -p no:cacheprovider 2>&1 | tail -8 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: FAIL on `test_the_runner_skills_read_the_recorded_root` (preambles still derive from base dir).

- [ ] **Step 3: Replace the launcher preamble in all 6 runner skills**

Each runner skill currently has a `**Launcher.**` block that says "this skill lives at `<repo>/skills/<name>/`, so the launcher is two levels up. Set `VG=<repo>/bin/vg`…". Replace that whole block (in all 6) with this **identical** text (no per-skill name any more):

```markdown
**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.
```

The 16 `"$VG" scripts.X` call-sites do **not** change — only how `VG` is resolved. Leave everything else in each skill untouched.

- [ ] **Step 4: Run to verify all skill-convention lints pass**

```bash
.venv/bin/python -m pytest tests/test_skill_convention.py -q -p no:cacheprovider 2>&1 | tail -6 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: PASS (3 tests). Also confirm no bare interpreter crept back:
```bash
grep -rn "\.venv/bin/python" skills/*/SKILL.md ; echo "bare-venv EXIT: $?"   # expect 1 (none)
grep -rl "two levels up" skills/*/SKILL.md ; echo "stale-wording EXIT: $?"   # expect 1 (none)
```

- [ ] **Step 5: Commit**

```bash
git add skills tests/test_skill_convention.py
git commit -m "fix: skills resolve the launcher from setup.sh's recorded root

The install copies skills into a runtime-less plugin cache, so deriving ROOT from the
skill's own base dir (packaging §2.2) hit the broken cache venv. The 6 runner skills
now read \${XDG_CONFIG_HOME:-~/.config}/video-grid/root to locate <clone>/bin/vg. The
16 call-sites are unchanged — only VG's resolution is. Lint gains a recorded-root check.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: README — the marketplace-add path + runtime note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Fix the marketplace-add command and add a runtime note**

In `README.md`'s Use section, change the install block from:
```
/plugin marketplace add .
/plugin install video-grid@video-grid
```
to:
```
/plugin marketplace add ./
/plugin install video-grid@video-grid
```
(A bare `.` is rejected with "Invalid marketplace source format"; the accepted local form is `./` or an absolute path.)

Then, right after that block, add one line:

```markdown
The plugin distributes the skills; they run this checkout's `bin/vg` (its path is
recorded by `setup.sh`), so keep the clone in place after installing.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README — /plugin marketplace add ./ (bare . is rejected) + runtime note

The first install hit 'Invalid marketplace source format' on a bare '.'; the accepted
local form is './'. Note that the installed skills run this checkout's bin/vg, so the
clone must stay in place.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: docs sync + registry + final review

**Files:**
- Modify: `docs/specs/2026-07-22-plugin-packaging-design.md`, `docs/build-status.md`, `CLAUDE.md`, `docs/development-workflow.md`

- [ ] **Step 1: Correct the packaging design**

In `docs/specs/2026-07-22-plugin-packaging-design.md`, add a short **Correction (2026-07-22)** note under §2.2 and §4 stating that the real `/plugin install` copies skills into a runtime-less cache, so "derive ROOT from the skill's base dir" does not work; the recorded-root anchor (§4, previously deferred) is used instead — see the runtime-resolution design. Do not rewrite the doc; append the correction so the history stays readable.

- [ ] **Step 2: Add a build-status entry**

Read `docs/build-status.md`'s most-recent entry (plugin packaging, 2026-07-22) and add a new entry after it (matching the file's ordering + style): the first real `/plugin install` found the cache-copy break (broken venv → skills fail loud) + 1.1 GB copy; the fix records the runtime root (`setup.sh` → `~/.config/video-grid/root`, skills read it → `<clone>/bin/vg`) and moves the venv external with a `.venv` symlink (cp -R preserves it → lean cache). `bin/vg` unchanged. Note the suite count from Step 4 and that the end-to-end install is a user-run proof.

- [ ] **Step 2b: Add the CLAUDE.md registry rows**

In `CLAUDE.md`'s Quick Reference table, right after the two Plugin-packaging rows, add:

```markdown
| Plugin runtime-resolution fix design | [2026-07-22-plugin-runtime-resolution-design.md](docs/specs/2026-07-22-plugin-runtime-resolution-design.md) | The first real `/plugin install` found it: the install `cp -R`s the repo into a runtime-less cache (broken venv → skills fail loud) and copies 1.1 GB. Fix — `setup.sh` records the clone root (`~/.config/video-grid/root`); the 6 runner skills read it → `<clone>/bin/vg` (packaging §2.2 "derive from base dir" was wrong). Lean — venv goes external + `<clone>/.venv` is a symlink (`cp -R` preserves it). `bin/vg` unchanged. |
| Plugin runtime-resolution fix plan | [2026-07-22-plugin-runtime-resolution.md](docs/plans/2026-07-22-plugin-runtime-resolution.md) | Tasks 0–3: `setup.sh` external venv + symlink + recorded root (+ `.gitignore`), 6 skill preambles read the recorded root, README `.`→`./`, docs sync + packaging-design correction. |
```

- [ ] **Step 3: Note it in `docs/development-workflow.md`**

Where the workflow mentions the plugin/`bin/vg` (added in the packaging slice), add one line: the venv is external (`~/.local/share/video-grid/venv`) with `<repo>/.venv` a symlink to it, and `setup.sh` records the checkout at `~/.config/video-grid/root`. Read the surrounding lines so it fits.

- [ ] **Step 4: Full suite green — record the number**

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -6 ; echo "EXIT: ${PIPESTATUS[0]}"
```
Expected: all green. The pre-fix count was 1611 passed / 2 skipped; this fix ADDS 3 setup-lint tests + 1 skill-convention test = expect ~1615 passed / 2 skipped. Record the actual number in Step 2.

- [ ] **Step 4b: Check off this plan's step checkboxes**

```bash
perl -pi -e 's/- \[ \]/- [x]/g' docs/plans/2026-07-22-plugin-runtime-resolution.md
```
Then revert the one frontmatter line that documents the checkbox syntax back to `- [ ]` (it is not a step), matching the sibling plans' convention.

- [ ] **Step 5: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: sync design correction, build-status, registry for the runtime fix

Corrects the packaging design's §2.2/§4 (the install copies skills to a runtime-less
cache, so base-dir resolution fails — recorded-root is used), adds a build-status
entry and two CLAUDE.md registry rows, and notes the external venv + recorded root in
the development workflow.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Final whole-slice review (orchestrator)**

The orchestrator dispatches a fresh reviewer over `main..fix/plugin-runtime-resolution`: confirm setup.sh emits external venv + symlink (+ migration) + recorded-root and touches nothing it should not; the 6 preambles read the recorded root and the 16 call-sites are unchanged; `bin/vg` + `tests/test_launcher.py` are untouched; README/docs accurate. Blocking findings → separate follow-up commits.

---

## Self-Review

**Spec coverage:** §2 recorded-root → Task 0 (setup.sh write) + Task 1 (skills read); §3 external venv + symlink → Task 0; §4 README `.`→`./` + residual honesty → Task 2 + docs; §5 tests → `test_setup_runtime.py` (setup lint) + `test_skill_convention.py` (recorded-root read) + `test_launcher.py` unchanged + the user-run install proof (noted, not asserted). §1 correction → Task 3 Step 1. Covered.

**Placeholder scan:** none. Task 3 Step 1/2/3 are prose edits to living docs (append a correction, match the build-status/workflow voice) rather than literal diffs — appropriate for those files, and each names exactly what to add.

**Type/name consistency:** the recorded-root path `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root` and the external venv `${XDG_DATA_HOME:-$HOME/.local/share}/video-grid/venv` are spelled identically in setup.sh (Task 0), the skill preamble (Task 1), the lint tests, and the docs. The lint `test_the_runner_skills_read_the_recorded_root` keys on `video-grid/root`, which the preamble contains. `bin/vg` and `tests/test_launcher.py` are explicitly out of scope and stay green.
