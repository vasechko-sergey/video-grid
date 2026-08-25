# Run-Dir Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every montage artifact lands in `<footage_root>/montage/`, and the two
stages that could write into the folder intake scans refuse to do so.

**Architecture:** The split already exists — every driver takes explicit path
arguments and no default names the footage root — so no plumbing changes. One new
pure module holds the convention's name and the shared refusal; `intake` and
`draft` call it at their entry; the router skill stops leaving `<run>` undefined.

**Tech Stack:** Python 3.13, pytest, pathlib. No new dependencies.

## Global Constraints

Copied from [the design](../specs/2026-08-25-run-dir-separation-design.md) and the
repo's standing rules:

- The run folder is named **`montage`**, a direct child of the footage root:
  `<footage_root>/montage/`.
- The refusal fires on **equality only**, never containment — `<footage_root>/montage`
  is inside the footage root and MUST pass, or the gate forbids the convention it
  protects.
- Both sides of the comparison go through `Path(...).resolve()`, so a trailing
  slash, a `..` segment, or a symlink cannot spell past the gate.
- It is a **refusal** (`ValueError`), never a warning. The advisory version of this
  rule has been in `using-montage` since §5.1 and prevented none of the 38 artifacts.
- Fail-loud messages name the remedy path. No silent fallback, no waiver flag.
- Scripts run as modules (`pythonpath = .` in `pytest.ini`); Python is
  `.venv/bin/python`.
- Do **not** touch the existing run at `/Users/serg/Downloads/untitled folder/`.
  It is out of scope by decision (design §5).
- Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1` — a one-byte edit can
  match the previous row's size and mtime-second, and CPython then serves a stale
  `.pyc`.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lib/runlayout.py` (new) | The convention's name and the one refusal. Pure: no I/O beyond `Path.resolve()`, no imports from other project modules. |
| `tests/lib/test_runlayout.py` (new) | Unit-pins the predicate, the spelling robustness, the remedy text, and the constant. |
| `scripts/intake.py` | Calls the refusal first thing in `intake()`. |
| `scripts/draft.py` | Calls the refusal first thing in `build_draft()`, on the parent of `out`. |
| `tests/lib/test_intake.py`, `tests/lib/test_draft.py` | The two call-site tests — each must prove the refusal happens **before** any work. |
| `skills/using-montage/SKILL.md` | Defines `<run>`; adds the old-layout resume note. |
| `skills/footage-intake/SKILL.md` | Binds its `<out_dir>`. |
| `README.md`, `CLAUDE.md`, `docs/build-status.md`, `docs/backlog.md` | Convention + registry + status. |

---

### Task 0: `runlayout` — the name and the refusal

**Files:**
- Create: `scripts/lib/runlayout.py`
- Test: `tests/lib/test_runlayout.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RUN_DIRNAME: str` (the literal `"montage"`) and
  `refuse_output_in_footage(footage_root: str, out_dir: str, what: str) -> None`,
  which raises `ValueError` when `out_dir` resolves to `footage_root` and returns
  `None` otherwise. Tasks 1 and 2 both call it.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_runlayout.py`:

```python
import pytest

from scripts.lib import runlayout


def test_the_run_dirname_is_montage():
    """Pinned because three places must agree on it: the refusal's remedy text,
    the using-montage skill, and the README. A rename is a deliberate act."""
    assert runlayout.RUN_DIRNAME == "montage"


def test_writing_into_the_footage_root_itself_is_refused(tmp_path):
    with pytest.raises(ValueError) as e:
        runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path), "the out dir")
    assert "the out dir" in str(e.value)


def test_the_refusal_names_the_remedy_path(tmp_path):
    with pytest.raises(ValueError) as e:
        runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path), "the out dir")
    assert str(tmp_path / "montage") in str(e.value)


def test_the_convention_itself_passes(tmp_path):
    """<footage>/montage is INSIDE the footage root. An containment check instead of
    equality would forbid the very layout this gate exists to protect."""
    runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path / "montage"), "x")


def test_a_deeper_path_under_the_footage_root_passes(tmp_path):
    runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path / "montage" / "out"), "x")


def test_a_sibling_directory_passes(tmp_path):
    runlayout.refuse_output_in_footage(str(tmp_path / "a"), str(tmp_path / "b"), "x")


@pytest.mark.parametrize("spell", ["trailing_slash", "dot_dot", "symlink"])
def test_the_same_directory_spelled_differently_is_still_refused(tmp_path, spell):
    """Both ends resolve(), so no spelling of the footage root slips past."""
    root = tmp_path / "footage"
    root.mkdir()
    if spell == "trailing_slash":
        other = str(root) + "/"
    elif spell == "dot_dot":
        other = str(root / "sub" / "..")
    else:
        link = tmp_path / "link"
        link.symlink_to(root)
        other = str(link)
    with pytest.raises(ValueError):
        runlayout.refuse_output_in_footage(str(root), other, "x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/lib/test_runlayout.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.runlayout'`

- [ ] **Step 3: Write the implementation**

Create `scripts/lib/runlayout.py`:

```python
"""Where a montage run's artifacts live, and the one rule about where they do not.

The conveyor discovers footage by extension over a FLAT listing of the footage
root (intake.py: `root.iterdir()`, no exclusion). Anything it writes there that
happens to be a video therefore becomes source material on the next scan —
measured 2026-08-19: `draft.mp4` sat among 99 real clips and escaped the scan
only because the scan had already run (design 2026-08-25 §0).

So the run gets its own folder, `<footage_root>/montage/`, and the two stages
that know the footage root and write into a caller-chosen directory refuse to
be pointed at the footage root itself.
"""
from pathlib import Path

RUN_DIRNAME = "montage"       # <footage_root>/montage — see the skills and the README


def refuse_output_in_footage(footage_root: str, out_dir: str, what: str) -> None:
    """Raise unless `out_dir` is somewhere other than the footage root itself.

    EQUALITY, never containment: `<footage_root>/montage` is inside the footage
    root and must pass, or this would forbid the layout it exists to protect.
    Both ends resolve() so a trailing slash, a `..` segment or a symlink cannot
    spell past it.
    """
    root = Path(footage_root).resolve()
    if Path(out_dir).resolve() != root:
        return
    raise ValueError(
        f"{what} resolves to the footage folder itself ({root}) — the conveyor "
        f"would write its output into the directory intake scans for source "
        f"clips, and any .mp4 landing there is taken as footage by the next scan "
        f"(draft.mp4 already did, and went unnoticed). Point it at "
        f"{root / RUN_DIRNAME} instead.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/lib/test_runlayout.py`
Expected: PASS — 9 passed (3 of them from the parametrize).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/runlayout.py tests/lib/test_runlayout.py
git commit -m "feat(runlayout): the run's folder name, and the refusal that keeps output out of the footage"
```

---

### Task 1: `intake` refuses the footage root

**Files:**
- Modify: `scripts/intake.py:464-472` (the head of `intake()`)
- Test: `tests/lib/test_intake.py`

**Interfaces:**
- Consumes: `runlayout.refuse_output_in_footage` from Task 0.
- Produces: nothing new — `intake()` keeps its signature
  `intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS, *, jobs: int = DEFAULT_JOBS, fresh: bool = False)`.

The guard must sit **above** `out.mkdir(...)` and above `ensure_model(MODEL)`.
Below the mkdir it would create the directory it is about to reject; below
`ensure_model` it would download YOLO weights first. The test in Step 1 pins
exactly that ordering, so this is a requirement, not a preference.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_intake.py`:

```python
def test_intake_refuses_an_out_dir_equal_to_the_footage_root(tmp_path):
    with pytest.raises(ValueError, match="footage folder itself"):
        intake.intake(str(tmp_path), str(tmp_path))


def test_intake_refuses_before_doing_any_work(tmp_path):
    """The guard sits above out.mkdir() and above ensure_model(): pointed at the
    footage root, intake must not create a directory or fetch weights first."""
    root = tmp_path / "footage"
    root.mkdir()
    before = set(p.name for p in root.iterdir())
    with pytest.raises(ValueError):
        intake.intake(str(root), str(root))
    assert set(p.name for p in root.iterdir()) == before
```

No import changes: `tests/lib/test_intake.py` already has `import pytest` and
`from scripts import intake` at its head. Verified 2026-08-25, as was the fact that
**no existing test passes the footage root as its own out dir** — every call in
`tests/lib/test_intake.py` and the three integration files uses a distinct out
directory, so the guard collides with nothing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/lib/test_intake.py -k refuses`
Expected: FAIL — no `ValueError` is raised; the call proceeds into the scan.

- [ ] **Step 3: Write the implementation**

In `scripts/intake.py`, add `runlayout` to the existing `scripts.lib` import line:

```python
from scripts.lib import assembly, carve, footage, intake_cache, reid, runlayout, vidstab
```

Then insert the guard as the FIRST statement of `intake()`, above the `jobs`
check:

```python
def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS, *,
           jobs: int = DEFAULT_JOBS, fresh: bool = False) -> footage.Footage:
    # Before the mkdir and before the weights: a run dir equal to the footage root
    # puts this scan's own outputs into the listing the NEXT scan reads (§0).
    runlayout.refuse_output_in_footage(footage_root, out_dir, "intake's out_dir")
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/lib/test_intake.py`
Expected: PASS, with the two new tests included.

- [ ] **Step 5: Confirm no existing intake test used the collapsed layout**

Run: `.venv/bin/python -m pytest -q tests/lib/test_intake.py tests/integration/test_intake.py tests/integration/test_intake_proxy.py tests/lib/test_intake_cache.py`
Expected: PASS. A red test here means a fixture passed the footage root as its
own out dir — fix the fixture to use a separate directory, never the guard.

- [ ] **Step 6: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "fix(intake): refuse an out_dir equal to the footage root, before the mkdir"
```

---

### Task 2: `draft` refuses to write into the footage root

**Files:**
- Modify: `scripts/draft.py:29-36` (the head of `build_draft()`)
- Test: `tests/lib/test_draft.py`

**Interfaces:**
- Consumes: `runlayout.refuse_output_in_footage` from Task 0.
- Produces: nothing new — `build_draft()` keeps its signature
  `build_draft(edl_path, project_path, footage_root, work_dir, out, *, music=None, font=None)`.

`draft` is the stage that actually fired: it writes an `.mp4`, and the router
points it at `<run>/draft.mp4`. It passes the **parent** of `out`, because the
thing being placed is a file.

The guard goes above `ensure_drawtext()` so the refusal needs no ffmpeg
capability and no EDL on disk — the test calls it with paths that do not exist.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_draft.py`:

```python
import pytest

from scripts import draft as draft_cli


def test_build_draft_refuses_an_out_beside_the_footage(tmp_path):
    """The exact shape that fired: <footage>/draft.mp4 is an .mp4 in the folder
    intake scans, so the next scan takes the QA preview as source material."""
    root = tmp_path / "footage"
    root.mkdir()
    with pytest.raises(ValueError, match="footage folder itself"):
        draft_cli.build_draft(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                              str(root), str(tmp_path / "work"), str(root / "draft.mp4"))


def test_build_draft_accepts_an_out_inside_the_run_dir(tmp_path):
    """Must NOT raise the run-dir refusal for <footage>/montage/draft.mp4. It still
    fails on the missing EDL — a different error, which is the point."""
    root = tmp_path / "footage"
    (root / "montage").mkdir(parents=True)
    with pytest.raises(Exception) as e:
        draft_cli.build_draft(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                              str(root), str(tmp_path / "work"),
                              str(root / "montage" / "draft.mp4"))
    assert "footage folder itself" not in str(e.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/lib/test_draft.py -k "refuses or accepts"`
Expected: the first test FAILS (no `ValueError` about the footage folder — it
raises something else about the missing EDL or drawtext instead).

- [ ] **Step 3: Write the implementation**

In `scripts/draft.py`, add `runlayout` to the `scripts.lib` imports, then make it
the first statement of `build_draft()`:

```python
    # The stage that fired: draft.mp4 beside the footage becomes footage (§0).
    runlayout.refuse_output_in_footage(footage_root, str(Path(out).parent),
                                       "draft.mp4's directory")
    ensure_drawtext()
```

`Path` is already imported at `scripts/draft.py:9`, so only `runlayout` joins
line 12's `from scripts.lib import ...`. The new test file imports do change:
`tests/lib/test_draft.py` currently has only `from scripts.lib import draft`, which
is the LIB module — `scripts/draft.py` is a different module, hence the
`draft_cli` alias in Step 1.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/lib/test_draft.py tests/integration/test_draft.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/draft.py tests/lib/test_draft.py
git commit -m "fix(draft): refuse an --out whose directory is the footage root"
```

---

### Task 3: the convention, written where the agent reads it

**Files:**
- Modify: `skills/using-montage/SKILL.md:32-35`, and §6's resume handling
- Modify: `skills/footage-intake/SKILL.md:40`
- Modify: `README.md:54`
- Modify: `CLAUDE.md` (Quick Reference table)

Only these two skills change. `<run>` appears in nine `SKILL.md` files, but the
other seven substitute it as a placeholder and stay correct for free;
`footage-intake` is the exception because it writes an unbound `<out_dir>`.

- [ ] **Step 1: Define `<run>` in the router skill**

In `skills/using-montage/SKILL.md`, replace the paragraph beginning "Point
**every** stage's output at one **run dir**" with:

```markdown
The **run dir** is `<footage_root>/montage` — always, and never the footage
folder itself. The conveyor discovers footage by extension over a flat listing of
the footage root, so an artifact written there that happens to be a video becomes
source material on the next scan (`draft.mp4` did exactly this). `intake` and
`draft` now refuse a path that resolves to the footage root; the refusal names
the remedy.

Point **every** stage's output at that one run dir so the inspector sees a
coherent run: `project_init --project-dir <run>`, `intake <footage_root> <run>`,
`reel_brief build --project <run>/project.json --out-dir <run>`,
`edit_plan build --out-dir <run>`,
`edl_to_reel --work-dir <run>/work --out-dir <run>/out`.
```

- [ ] **Step 2: Add the old-layout resume note**

In the same file, in step 1 ("Locate the run"), append:

```markdown
   **A run from before the `montage/` convention** lives directly in the footage
   folder. If `<run>` is empty but `<footage_root>/project.json` exists, say so
   and ask which to use — starting fresh silently would re-scan every clip.
```

- [ ] **Step 3: Bind the intake skill's out dir**

In `skills/footage-intake/SKILL.md`, in step 2 ("Scan"), change the invocation
line to name the value:

```markdown
2. **Scan.** `python -m scripts.intake <footage_root> <out_dir>`, where
   `<out_dir>` is `<footage_root>/montage` — the run dir, never the footage
   folder itself (intake refuses that outright: its own outputs would be read as
   source clips by the next scan). This writes
```

- [ ] **Step 4: Update the README**

In `README.md`, replace line 54's tail so the sentence reads:

```markdown
footage folder by absolute path; every artifact lands in one `montage/` folder
beside the clips, and the finished reel in `montage/out/`.
```

- [ ] **Step 5: Add the registry rows**

In `CLAUDE.md`'s Quick Reference table, add two rows next to the other design/plan
pairs:

```markdown
| Run-dir separation design | [2026-08-25-run-dir-separation-design.md](docs/specs/2026-08-25-run-dir-separation-design.md) | Every artifact into `<footage_root>/montage/`. **§0 is the point:** this is not tidiness — intake discovers footage by extension over a flat `root.iterdir()` with no exclusion, and `draft.mp4` is written into the run dir by the conveyor itself, so a re-scan carves windows out of the user's own cuts; the 2026-06 run escaped only by timing (99 clips scanned 2026-08-19, the draft written 2026-08-20). The split needed no plumbing — every driver path arg is explicit and no default names the footage root — only the missing rule that `<run>` must not BE the footage folder. Refusal (not a warning) at the two stages that know the footage root and write into a caller-chosen directory, on **equality never containment**. §5: migrating the existing run would not have been a `mv` (57 absolute paths in `EPISODES.json` alone). |
| Run-dir separation plan | [2026-08-25-run-dir-separation.md](docs/plans/2026-08-25-run-dir-separation.md) | Tasks 0–4: `lib/runlayout.py` (`RUN_DIRNAME` + the shared refusal), the `intake` guard above the mkdir, the `draft` guard on the parent of `--out`, the two skills that actually define the path, and a 7-row mutation battery. |
```

- [ ] **Step 6: Commit**

```bash
git add skills/using-montage/SKILL.md skills/footage-intake/SKILL.md README.md CLAUDE.md
git commit -m "docs: the run dir is <footage_root>/montage, written where the agent reads it"
```

---

### Task 4: the mutation battery, the whole suite, and the status sync

**Files:**
- Modify: `docs/build-status.md`, `docs/backlog.md`

**Interfaces:**
- Consumes: everything from Tasks 0–3.
- Produces: nothing importable.

- [ ] **Step 1: Run the mutation battery**

For each row: apply the mutation, run the named test, confirm it goes RED,
then restore the file by rewriting the original content (never `git checkout --`,
`git restore`, `git reset --hard`, or `git stash`). Run every row with
`PYTHONDONTWRITEBYTECODE=1`.

| # | Mutation | Must redden |
|---|---|---|
| 1 | `runlayout`: `if ... != root: return` → `if ... == root: return` | `test_writing_into_the_footage_root_itself_is_refused` |
| 2 | `runlayout`: drop `.resolve()` on the `out_dir` side | `test_the_same_directory_spelled_differently_is_still_refused` (all three spellings) |
| 3 | `runlayout`: equality → containment (`root == t or root in t.parents`) | `test_the_convention_itself_passes` |
| 4 | `runlayout`: `RUN_DIRNAME = "runs"` | `test_the_run_dirname_is_montage` **and** `test_the_refusal_names_the_remedy_path` |
| 5 | `intake`: move the guard below `out.mkdir(...)` | `test_intake_refuses_before_doing_any_work` |
| 6 | `draft`: delete the `refuse_output_in_footage` call | `test_build_draft_refuses_an_out_beside_the_footage` |
| 7 | `draft`: pass `out` instead of `str(Path(out).parent)` | `test_build_draft_refuses_an_out_beside_the_footage` |

A row that does **not** redden is a coverage hole: add or sharpen a test until it
does, and record what was missing. Do not soften the row.

- [ ] **Step 2: Run the whole suite**

```bash
find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Expected: the pre-slice baseline of **3060 passed, 1 skipped** plus the new
tests — 9 from Task 0 (6 plain plus a 3-way parametrize) and 4 from Tasks 1–2,
none removed, so **3073 passed, 1 skipped**. No golden may move; a moved golden means a stage's output
path changed, which this slice does not do.

- [ ] **Step 3: Sync build-status**

Append a Done entry to `docs/build-status.md` naming: the `<footage_root>/montage`
convention, the two refusal call sites, the 2026-08-19 measurement that made this
a correctness fix rather than housekeeping (99 clips scanned, 100 videos present,
`draft.mp4` written a day after the scan), the mutation battery's result, and the
two honest limits — a hand-copied reel among the footage is still scanned, and a
pre-convention run no longer resumes without the skill's prompt.

- [ ] **Step 4: Add the backlog rows for what this slice defers**

In `docs/backlog.md`, add under P3:

```markdown
| ○ | **Migrate a pre-convention run into `montage/`** — not a `mv`: artifacts carry absolute paths to other artifacts (`out/EPISODES.json` 57, `cast_candidates.json` 15, `cast.json` 10, each `.intake_cache/*/clip.json` 52), so a move breaks the QC digest bindings and the delivery attestation that exist to notice exactly that. A path-rewriting migration, if it is ever wanted. | M | [run-dir-separation](specs/2026-08-25-run-dir-separation-design.md) §5 |
| ○ | **A rendered video hand-copied among the footage is still scanned** — the gate proves the run dir is not the footage dir; it cannot prove no `.mp4` in the footage folder is pipeline output, because an `.mp4` is an `.mp4`. Would need content provenance (an attestation sidecar lookup at scan time), which is a slice, not a guard. | M | [run-dir-separation](specs/2026-08-25-run-dir-separation-design.md) §6 |
```

- [ ] **Step 5: Commit**

```bash
git add docs/build-status.md docs/backlog.md
git commit -m "docs: run-dir separation — battery result, status, and the two deferrals"
```

---

## Self-Review

**1. Spec coverage.**

| Spec section | Task |
|---|---|
| §0 the corruption mechanism | motivates 1 and 2; recorded in Task 3's registry row and Task 4's status entry |
| §1 architecture already supports it | no task needed — that is the finding that makes the slice small |
| §2 the layout, `<run>/..` is the footage root | Task 3 (definition), Task 0 (`RUN_DIRNAME`) |
| §3 the gate, two call sites, equality, resolve | Tasks 0, 1, 2 |
| §4 build table rows 1–6 | Tasks 0, 1, 2, 3 |
| §5 existing run out of scope | Global Constraints + Task 4 Step 4's backlog row |
| §6 honest limits | Task 4 Steps 3 and 4 |

No gaps.

**2. Placeholder scan.** No "TBD"/"TODO"/"add error handling"/"similar to Task N".
Every code step carries the code; every test step carries the test.

**3. Type consistency.** `refuse_output_in_footage(footage_root: str, out_dir: str,
what: str) -> None` and `RUN_DIRNAME: str` are defined in Task 0 and used with
those exact names and argument orders in Tasks 1, 2 and the Task 4 battery. The
`what` label differs per call site by design (`"intake's out_dir"`,
`"draft.mp4's directory"`) and both tests match on the shared substring
`"footage folder itself"`, so a label change cannot silently break them.

**4. One thing the battery is watching for.** Task 1 Step 5 exists because the
guard could collide with an existing fixture that passes the footage root as its
own out dir. If that happens the fixture is wrong, not the guard — the whole
point is that this layout was never safe.
