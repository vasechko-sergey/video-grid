# ffmpeg baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox syntax for tracking.

**Goal:** One ffmpeg install carrying every library the pipeline needs, resolved from a
path that `setup.sh` records — and a `setup.sh` that can no longer uninstall a working
binary.

**Architecture:** `setup.sh` installs homebrew-core's keg-only `ffmpeg-full` beside the
core `ffmpeg`, verifies the filters are really there, and writes `config/ffmpeg.env`. A new
`scripts/lib/ffbin.py` resolves the binaries (`$FFMPEG` → that file → PATH, always to an
absolute path) and answers capability questions through one `has_filter`. All 37 argv
literals move onto the resolver, and the landmine AST scan bans them from coming back.

**Tech Stack:** Python 3.13, pytest, bash, homebrew. No new dependencies.

**Spec:** [2026-07-20-ffmpeg-baseline-design.md](../specs/2026-07-20-ffmpeg-baseline-design.md)

---

## Executor rules (read before Task 0)

- **Never run an installer.** No `brew install`, `brew uninstall`, `brew pin`, `pip
  install`, and **never `bash setup.sh`**. Task 5 *edits* `setup.sh`; the user runs it.
  Verification is read-only plus pytest. This applies to every subagent dispatched for
  this plan and must be repeated verbatim in each brief.
- Scripts run as modules: `.venv/bin/python -m pytest`, never `python tests/...`.
- Do not pipe pytest through `tail`; append `; echo "EXIT: $?"`.
- Commit per task as specified. Post-review fixes are **separate follow-up commits**,
  never `git commit --amend`.
- Commit bodies end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/ffbin.py` *(new)* | Resolve `ffmpeg`/`ffprobe` to absolute paths; `has_filter` / `require_filter`. The single place that may name the binaries as literals. |
| `tests/lib/test_ffbin.py` *(new)* | Rung precedence, absolute-path guarantee, fail-loud, `has_filter`. |
| `scripts/*.py`, `scripts/lib/assembly.py` | 37 argv literals → `ffbin.ffmpeg()` / `ffbin.ffprobe()`. 11 files. |
| `scripts/draft.py`, `scripts/intake.py` | Capability gates become `require_filter` wrappers. |
| `tests/conftest.py`, 3 integration guards | Probe the *resolved* binary, not PATH. |
| `tests/lib/test_landmine_scan.py` | Fifth check: a literal exactly `"ffmpeg"`/`"ffprobe"` is banned in `scripts/`. |
| `setup.sh` | Install `ffmpeg-full`, verify, record, pin. Both destructive branches deleted. |
| `.gitignore` | `config/ffmpeg.env`. |

---

### Task 0: `lib/ffbin.py` — resolve the binaries

**Files:**
- Create: `scripts/lib/ffbin.py`
- Test: `tests/lib/test_ffbin.py`

- [x] **Step 1: Write the failing tests**

```python
"""ffbin resolves the binaries the pipeline runs (design 2026-07-20 §3)."""
import pytest

from scripts.lib import ffbin


def test_the_environment_variable_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG", "/from/env/ffmpeg")
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=/from/file/ffmpeg\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    assert ffbin.ffmpeg() == "/from/env/ffmpeg"


def test_the_config_file_beats_PATH(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=/from/file/ffmpeg\nFFPROBE=/from/file/ffprobe\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    assert ffbin.ffmpeg() == "/from/file/ffmpeg"
    assert ffbin.ffprobe() == "/from/file/ffprobe"


def test_a_missing_config_falls_through_to_PATH(monkeypatch, tmp_path):
    # the portability rung: setup.sh is macOS-only, so a Linux box has no config
    # file and import must still work (design §3).
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ffbin.ffmpeg() == "/usr/bin/ffmpeg"


# As built: REPLACED. This assertion cannot fail against an absolute mock — it
# cannot tell "returned which's result" from "returned something absolute", and the
# realistic mutation it claims to guard is already pinned by the test above. Worse,
# it hid a real gap: shutil.which returns a RELATIVE path when PATH carries a
# relative entry, and _resolve passed it straight through, so the docstring's
# "always absolute" promise was false. The shipped test mocks which to "./ffmpeg"
# and asserts the result is absolute; _resolve gained os.path.abspath.
def test_the_PATH_rung_yields_an_absolute_path_not_a_bare_name(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/opt/x/{name}")
    assert ffbin.ffmpeg().startswith("/")


def test_an_empty_value_in_the_file_is_not_a_path(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ffbin.ffmpeg() == "/usr/bin/ffmpeg"


def test_nothing_resolves_fails_loud_with_the_remedy(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="bash setup.sh"):
        ffbin.ffmpeg()
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_ffbin.py -q ; echo "EXIT: $?"`
Expected: collection error — `ModuleNotFoundError: scripts.lib.ffbin`.

- [x] **Step 3: Implement**

```python
"""Resolve the ffmpeg/ffprobe binaries the pipeline runs (design 2026-07-20 §3).

setup.sh installs a full-featured ffmpeg (drawtext + vidstab) and records where it
put it, because homebrew's ffmpeg-full is keg-only and never lands on PATH. This
module reads that record.

The PATH is frozen at install time; the FILTERS are probed at runtime, every time
(design §4). A stale path fails loud — the file is gone and subprocess raises. A
stale capability record would fail SILENTLY: the code would skip its own gate on a
false premise, which is the §12 failure shape this repo exists to avoid.
"""
import os
import shutil
from pathlib import Path

from scripts.lib import proc

# repo-root/config — mirrors catalog._SOURCING_ENV, and gitignored for the same
# reason: the resolved path is per-machine, not per-checkout.
_FFMPEG_ENV = Path(__file__).resolve().parents[2] / "config" / "ffmpeg.env"


def _from_file(key: str) -> str | None:
    """`KEY=value` out of config/ffmpeg.env, or None. Same shape as sourcing.env."""
    if not _FFMPEG_ENV.exists():
        return None
    for line in _FFMPEG_ENV.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip() or None
    return None


def _resolve(key: str, binary: str) -> str:
    """$KEY -> config/ffmpeg.env -> PATH. Always an ABSOLUTE path.

    The PATH rung goes through shutil.which rather than returning a bare name, so
    a log or an error message always names the binary that actually ran — the
    machine may carry two ffmpeg builds and mixing them is the thing worth seeing.
    """
    for candidate in (os.environ.get(key), _from_file(key)):
        if candidate:
            return candidate
    found = shutil.which(binary)
    if found:
        return found
    raise ValueError(
        f"cannot find {binary}: ${key} is unset, {_FFMPEG_ENV} has no {key}=, and "
        f"{binary} is not on PATH — run `bash setup.sh`, which installs ffmpeg-full "
        f"and records where it landed")


def ffmpeg() -> str:
    return _resolve("FFMPEG", "ffmpeg")


def ffprobe() -> str:
    return _resolve("FFPROBE", "ffprobe")
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_ffbin.py -q ; echo "EXIT: $?"`
Expected: `6 passed`, EXIT 0.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/ffbin.py tests/lib/test_ffbin.py
git commit -m "feat: ffbin resolves ffmpeg/ffprobe to an absolute path

homebrew's ffmpeg-full is keg-only, so the build carrying drawtext and vidstab
never reaches PATH. setup.sh records where it landed; this reads that record,
with \$FFMPEG overriding it and PATH as the portability fallback for boxes where
the macOS-only setup.sh never ran.

Always absolute — a machine can carry two ffmpeg builds, and a log that says
which one ran is the difference between seeing a mixed pipeline and inferring it."
```

---

### Task 1: `has_filter` + the two production gates

**Files:**
- Modify: `scripts/lib/ffbin.py`
- Modify: `scripts/draft.py:19-27` (`ensure_drawtext`)
- Modify: `scripts/intake.py:56-61` (`_require_vidstab`), `scripts/intake.py:148`
- Modify: `scripts/lib/manifest.py:186` — **As built:** a *third* `--with-vidstab` remedy
  (inside the `stabilize=true` refusal) that this list originally missed. Found only by
  grepping all of `scripts/` rather than the two files named here. Grep, do not trust
  the list.
- Test: `tests/lib/test_ffbin.py`, existing `tests/test_draft.py`, `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_ffbin.py`:

```python
def _filters(monkeypatch, text: str):
    """Stand in for `ffmpeg -filters` output."""
    class _R:
        stdout = text.encode()
    monkeypatch.setattr(ffbin.proc, "run", lambda cmd, **kw: _R())


def test_has_filter_true_when_the_build_lists_it(monkeypatch):
    _filters(monkeypatch, " T.. drawtext   V->V   Draw text on top of video.\n")
    assert ffbin.has_filter("drawtext") is True


def test_has_filter_false_when_it_does_not(monkeypatch):
    _filters(monkeypatch, " ... scale   V->V   Scale the input video.\n")
    assert ffbin.has_filter("vidstabdetect") is False


def test_require_filter_is_silent_when_present(monkeypatch):
    _filters(monkeypatch, " T.. drawtext   V->V   Draw text.\n")
    assert ffbin.require_filter("drawtext", "run `bash setup.sh`") is None


def test_require_filter_fails_loud_carrying_binary_and_remedy(monkeypatch):
    _filters(monkeypatch, " ... scale   V->V   Scale.\n")
    monkeypatch.setenv("FFMPEG", "/opt/slim/ffmpeg")
    with pytest.raises(ValueError, match="/opt/slim/ffmpeg.*vidstabdetect.*setup.sh"):
        ffbin.require_filter("vidstabdetect", "run `bash setup.sh`")
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_ffbin.py -q ; echo "EXIT: $?"`
Expected: 4 failures, `AttributeError: module 'scripts.lib.ffbin' has no attribute 'has_filter'`.

- [x] **Step 3: Implement**

Append to `scripts/lib/ffbin.py`:

```python
def has_filter(name: str) -> bool:
    """Is `name` in the resolved ffmpeg's filter list?

    The ONE place this question is asked. Four sites used to ask it four ways —
    two production gates and three test guards — and the moment production moved
    to a different binary than the guards probed, those guards would have skipped
    forever against a working pipeline: a green suite with three integration tests
    silently uncovered (design §5).

    Deliberately uncached: see design §4 on why a stale answer is worth more than
    the 50ms it would save.
    """
    out = proc.run([ffmpeg(), "-hide_banner", "-filters"]).stdout
    return name.encode() in out


def require_filter(name: str, remedy: str) -> None:
    """Fail loud when the resolved build lacks `name`, naming the binary."""
    if not has_filter(name):
        raise ValueError(f"{ffmpeg()} has no {name} filter — {remedy}")
```

Rewrite `scripts/draft.py` `ensure_drawtext` (drop the `ffmpeg` parameter — the resolver
is now the single source of that answer, and a caller-supplied binary was the seam that
let production and tests disagree):

```python
def ensure_drawtext() -> None:
    """Fail loud if the resolved ffmpeg lacks drawtext — the draft label burn needs
    it, and a missing filter otherwise surfaces as a cryptic 'No such filter:
    drawtext' mid-render."""
    ffbin.require_filter(
        "drawtext",
        "the draft labels need it. Run `bash setup.sh`, which installs ffmpeg-full "
        "(libfreetype included)")
```

Rewrite `scripts/intake.py` `_require_vidstab`:

```python
def _require_vidstab() -> None:
    """Intake is the repo's first runtime vidstab consumer — fail loud with the remedy."""
    ffbin.require_filter(
        "vidstabdetect",
        "footage-intake measures shake with it. Run `bash setup.sh`, which installs "
        "ffmpeg-full (libvidstab included)")
```

And at `scripts/intake.py:148`, the `.trf` header error still says `run bash setup.sh
--with-vidstab`. That flag is being deleted (Task 5) — change it to `bash setup.sh`.

Add `ffbin` to the `from scripts.lib import ...` line in both files.

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_ffbin.py tests/test_draft.py tests/lib/test_intake.py -q ; echo "EXIT: $?"`

Expected: all pass. (**As built:** the path is `tests/lib/test_intake.py`; there is no
`tests/test_intake.py`.)

`tests/test_draft.py:14` fakes the filter list by patching `draft.proc`. **As built: that
patch never goes red, and the reason is worth knowing.** `draft.proc` and `ffbin.proc` are
the *same module object* — Python caches modules, so every name bound to `scripts.lib.proc`
shares one object and patching through any of them patches all of them. The retarget to
`ffbin.proc` is therefore about making the test *read* correctly, not about keeping it
green. `tests/lib/test_intake.py` has two tests with the identical pattern; retarget those
too.

- [x] **Step 5: Verify no `--with-vidstab` string survives in `scripts/`**

Run: `grep -rn 'with-vidstab' scripts/ ; echo "EXIT: $?"`
Expected: no matches (EXIT 1).

- [x] **Step 6: Commit**

```bash
git add scripts/lib/ffbin.py scripts/draft.py scripts/intake.py tests/
git commit -m "feat: one chokepoint answers 'does this build have that filter'

Four sites asked it four ways: two production gates shelling out and grepping,
three test guards each running their own subprocess. That is not untidiness — it
is the slice's one genuinely silent failure. Point production at ffmpeg-full and
leave the guards probing PATH, and they find no drawtext and no vidstab and skip
forever while production works: a green suite with three integration tests
quietly uncovered.

ensure_drawtext loses its ffmpeg parameter. A caller-supplied binary was exactly
the seam that let production and tests disagree about which build they meant."
```

---

### Task 2: the production argv literals move onto the resolver

**Files (11):** `scripts/track.py`, `check_reel.py`, `intake.py`, `reframe.py`,
`check_episode.py`, `storyboard.py`, `deliver.py`, `extract.py`, `mix.py`, `draft.py`,
`scripts/lib/assembly.py`

Mechanical. In each file add `ffbin` to the existing `from scripts.lib import ...` line,
then replace argv literals:

- `"ffmpeg"` → `ffbin.ffmpeg()` (29 sites)
- `"ffprobe"` → `ffbin.ffprobe()` (8 sites)

Representative diff (`scripts/extract.py:17`):

```python
    cmd = [
        ffbin.ffmpeg(), "-y", "-i", src,
```

- [x] **Step 1: Enumerate the sites, so the count is checked not assumed**

```bash
grep -rn '"ffmpeg"' scripts/ | grep -v 'scripts/lib/proc.py' | grep -v 'scripts/lib/ffbin.py'
grep -rn '"ffprobe"' scripts/ | grep -v 'scripts/lib/ffbin.py'
```

**As built: 25 + 8 = 33 replacements, not the 34 this step originally predicted — and the
way that number was wrong is the point.**

The original text said "27 pre-slice minus draft.py:19's default parameter = 26". Two
errors compounded. It counted a raw grep, which includes `ffbin.py`'s own
`_resolve("FFMPEG", "ffmpeg")` — the one literal Step 4 of *this same task* says must
survive. And it was computed against the pre-slice tree, before Task 1 also dissolved
`intake.py`'s `["ffmpeg", "-hide_banner", "-filters"]` probe into `ffbin.has_filter`.

So the count moves under you: Task 0 *adds* two literals (ffbin's own), Task 1 *removes*
two. Both exclusions above are needed, and the honest instruction is the one at the top of
this step — enumerate and count what you actually see, then reconcile against Step 4.

`scripts/lib/proc.py`'s two matches are inside **comments**, not string literals. Leave
them: they explain the guard, Python never sees them, and — relevant to Task 4 — the AST
scan cannot see them either, so `proc.py` needs no exemption.

- [x] **Step 2: Replace, file by file**

- [x] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`

Expected: EXIT 0, **8 skipped**, and a passed count *no lower* than the previous task's.
Do not pin the passed number — see "On counting" below. Nothing about behaviour changes
here: with no `config/ffmpeg.env` present, the PATH rung resolves to the same binary that
the literals named.

- [x] **Step 4: Verify no argv literal survives**

```bash
grep -rn '"ffmpeg"\|"ffprobe"' scripts/ ; echo "EXIT: $?"
```
Expected: only `scripts/lib/proc.py` comment lines and `scripts/lib/ffbin.py`.

- [x] **Step 5: Commit**

```bash
git add scripts/
git commit -m "refactor: every ffmpeg/ffprobe invocation resolves its own binary

37 argv literals across 11 files. Behaviour is unchanged on a machine with no
config/ffmpeg.env: the PATH rung resolves to the same binary the literals named,
and the suite holds at 1512/8. What changes is that argv[0] is now an absolute
path, so the lint sees the real command and proc.run's failure messages echo
something you can paste into a shell."
```

---

### Task 3: the test guards stop probing PATH

**Files:**
- Modify: `tests/conftest.py:8-21`
- Modify: `tests/integration/test_intake.py:21-25,66`
- Modify: `tests/integration/test_draft.py:20-23`
- Modify: `tests/integration/test_titles.py:19-22`

This is the task design §5 calls load-bearing. Get it wrong and the slice reports success
while three integration tests skip forever.

- [x] **Step 1: Rewrite `conftest.sample_clip`**

Replace `shutil.which("ffmpeg")` with a resolver call and the direct `subprocess.run` with
`proc.run`:

```python
from scripts.lib import ffbin, proc

@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """3s 1920x1080 30fps clip: a bright box sliding left→right on dark bg."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    ...
    proc.run([binary, "-y", "-f", "lavfi", "-i", bg, ...])
```

Keep the existing `drawbox`-is-inert comment verbatim — it records a live §12 landmine.

- [x] **Step 2: One shared fixture, three thin users**

**As built — read this before writing code; the original plan mis-described these guards.**
`test_draft.py` and `test_titles.py` do not use `skipif`: each has an **autouse fixture**
`_need_drawtext`. And all three guards open with `shutil.which("ffmpeg")`, which is a second
bare-name PATH probe hiding inside the first.

That `which` pre-check is why a shared fixture earns its place rather than three copies.
Deleting it naively changes behaviour: on a box with no ffmpeg at all, `ffbin.has_filter`
now raises `ValueError` (fail-loud, by design), so a test that used to *skip* would *error*.
Both skip conditions — "nothing resolves" and "filter absent" — belong in one place.

In `tests/conftest.py`:

```python
@pytest.fixture
def need_filter():
    """Skip unless the RESOLVED ffmpeg carries `name`.

    Both skip reasons live here. ffbin.has_filter fails loud when nothing
    resolves at all, which is right for production and wrong for a test run on a
    box without ffmpeg — that should skip, not error.
    """
    def _need(name: str) -> None:
        try:
            present = ffbin.has_filter(name)
        except (ValueError, RuntimeError) as e:
            pytest.skip(str(e))
        if not present:
            pytest.skip(f"ffmpeg lacks the {name} filter (run: bash setup.sh)")
    return _need
```

`test_draft.py` and `test_titles.py` each collapse to:

```python
@pytest.fixture(autouse=True)
def _need_drawtext(need_filter):
    need_filter("drawtext")
```

`test_intake.py`'s guard is a **collection-time `skipif`**, so it cannot take a fixture —
it stays a module-level function delegating to the same one implementation:

```python
def _has_vidstab() -> bool:
    try:
        return ffbin.has_filter("vidstabdetect")
    except (ValueError, RuntimeError):
        return False
```

Update `test_intake.py:66`'s skip reason: `--with-vidstab` -> `bash setup.sh`. Drop the now
unused `shutil` / `subprocess` imports from all three files.

- [x] **Step 3: Machine-check that no test reinvents the probe**

The anti-hollow step. The original plan proposed three meta-tests, one per guard, each
extracting a helper so that a forced `has_filter=False` could be observed. **That is more
code than the property is worth and it pins the wrong thing** — it covers only the guards
that exist today, while the failure mode is a *future* test file growing its own probe.

Pin the property directly. The tell is universal: there is no way to ask ffmpeg what it
supports without passing `-filters`.

```python
def test_no_test_runs_its_own_filter_probe():
    """Design section 5: a guard that probes PATH itself finds the slim build,
    skips forever, and reports green while three integration tests go uncovered.

    tests/lib/test_ffbin.py fakes proc.run's OUTPUT rather than running a probe,
    so it never spells the flag; that asymmetry is what makes this checkable.
    """
    guilty = [f"{p}:{i}" for p in sorted(Path("tests").rglob("*.py"))
              for i, line in enumerate(p.read_text().splitlines(), 1)
              if "-filters" in line]
    assert guilty == [], (
        f"ask ffbin.has_filter instead of probing ffmpeg directly: {guilty}")
```

Put it in `tests/lib/test_ffbin.py`. **Verify it can fail**: drop `"-filters"` into a
scratch test file, confirm red, remove it.

- [x] **Step 4: Run**

Run: `.venv/bin/python -m pytest -q -rs ; echo "EXIT: $?"`

Expected: EXIT 0 and **still 8 skipped** on a machine without ffmpeg-full — the guards now
consult the resolver, but the resolver still finds the slim PATH binary. **The skip count
drops only after the user installs ffmpeg-full (Task 7).**

- [x] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: guards and the sample clip probe the resolved binary

Design §5's trap, closed. These four sites each ran their own subprocess against
whatever PATH meant. Once production moved to ffmpeg-full they would have gone on
probing the slim build, found no drawtext and no vidstab, and skipped forever
against a pipeline that worked — silent loss of coverage, which is the one
genuinely quiet failure this slice can introduce.

The added guard-follows-the-resolver tests exist because the obvious version of
this change is untestable by its own suite: a guard that ignored has_filter would
pass everything else here."
```

---

### Task 3b: the integration suite runs the same binary production does

**Added mid-slice.** Task 3's implementer found that Task 2 moved literals in `scripts/`
only, so test *bodies* still name the binaries. Measured: **37 sites across 16 files** under
`tests/integration/` — sine-tone builds, test-clip synthesis, `ffprobe` codec and duration
reads.

**Why this is not scope creep.** Post-install those helpers run PATH's *slim* build while
production runs `ffmpeg-full`. Nothing is silently uncovered — none of them needs drawtext
or vidstab, so this is not a repeat of §5's trap. What it damages is **Task 7's proof**.
Task 7 reads the goldens as the only real test of design §2's "same version, same revision"
argument. A golden whose fixture was built by one build and whose output came from another
cannot answer that question: if it holds, it proves cross-build agreement rather than the
thing claimed; if it moves, the cause is ambiguous. The suite must exercise the
configuration the user will actually run.

The cheap alternative — prepending ffmpeg-full's directory to `PATH` inside `conftest` —
is rejected. It would fix the binary without fixing the *path*: tests would stop exercising
the resolution production uses, so a broken `ffbin` would leave them green. That is the
hollow-verification shape this slice has already had to correct four times.

**Files:** the 16 under `tests/integration/` carrying `"ffmpeg"` / `"ffprobe"` argv literals.

**`tests/lib/` is exempt, and the reason is not laziness:**
- `test_lint.py` (69 hits) — its `REAL_SITES` fixtures are *printed output from the real
  builders*. The literals **are** the test data; resolving them would destroy the fixture.
- `test_proc.py` — tests the wrapper's timeout/error handling, not the pipeline. Its
  `["ffprobe", "-version"]` calls work identically on either build, and several of its
  commands are deliberately fake (`a.mp4`) and never execute.

- [x] **Step 1: Enumerate**

```bash
grep -rn '"ffmpeg"\|"ffprobe"' tests/integration/ | wc -l    # 37 at time of writing
```

Count what you see; do not trust this number. Task 2's equivalent step was wrong twice.

- [x] **Step 2: Replace**

Same substitution as Task 2: add `ffbin` to the `from scripts.lib import ...` line, then
`"ffmpeg"` → `ffbin.ffmpeg()`, `"ffprobe"` → `ffbin.ffprobe()`. Read each line — some are
inside `subprocess.run` rather than `proc.run`, and a few build commands across multiple
lines.

- [x] **Step 3: Widen the machine check to argv literals**

`tests/lib/test_ffbin.py` already bans the probe flag everywhere under `tests/`. Add a
sibling banning bare binary names under `tests/integration/` only, with the `tests/lib/`
exemption stated above as its docstring. Reuse the assembled-needle and non-vacuity
techniques already in that file — the flag check documents why both are needed.

- [x] **Step 4: Run**

`.venv/bin/python -m pytest -q -rs ; echo "EXIT: $?"`
Expected: EXIT 0, **still 8 skipped**, same identity. Passed count not pinned.

- [x] **Step 5: Commit**

---

### Task 4: the AST scan bans the literals from returning

**Files:**
- Modify: `tests/lib/test_landmine_scan.py`

- [x] **Step 1: Write the failing tests**

```python
_NAMES_THE_BINARIES = SCRIPTS / "lib" / "ffbin.py"
_BANNED_BARE = ("ffmpeg", "ffprobe")


def _exact(banned: str, paths: list[Path]) -> list[str]:
    """`file:line` for every non-docstring literal EQUAL to `banned`.

    Equality, not the substring test _guilty uses. Docstrings and error messages
    say the word "ffmpeg" constantly and must stay legal; no prose string is ever
    exactly those six characters. Same mention-versus-emission line the filter
    checks already had to draw.
    """
    return [f"{p}:{line}" for p in paths
            for line, text in _literals(p.read_text()) if text == banned]


@pytest.mark.parametrize("banned", _BANNED_BARE)
def test_no_script_names_a_binary_instead_of_resolving_it(banned):
    guilty = _exact(banned, _sources(skip=_NAMES_THE_BINARIES))
    assert guilty == [], (
        f"bare {banned!r} in argv goes to PATH, which on a keg-only ffmpeg-full "
        f"install is the WRONG build — use ffbin.{banned}(): {guilty}")


def test_prose_naming_a_binary_is_not_an_emission(tmp_path):
    """The discriminator: equality, not substring."""
    (tmp_path / "m.py").write_text(
        'X = "ffmpeg is not on PATH"\nY = "run ffprobe by hand"\n')
    assert _exact("ffmpeg", _sources(tmp_path, skip=tmp_path / "none.py")) == []


def test_a_bare_binary_literal_is_caught(tmp_path):
    (tmp_path / "m.py").write_text('cmd = ["ffmpeg", "-y"]\n')
    assert len(_exact("ffmpeg", _sources(tmp_path, skip=tmp_path / "none.py"))) == 1


def test_the_binary_exemption_is_one_file_wide(tmp_path):
    """ffbin.py must name them; nothing else may hide behind that hole."""
    (tmp_path / "ffbin.py").write_text('B = "ffmpeg"\n')
    (tmp_path / "other.py").write_text('B = "ffmpeg"\n')
    found = _exact("ffmpeg", _sources(tmp_path, skip=tmp_path / "ffbin.py"))
    assert len(found) == 1 and "other.py" in found[0]
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_landmine_scan.py -q ; echo "EXIT: $?"`
Expected: `NameError: _exact` / `_NAMES_THE_BINARIES`.

- [x] **Step 3: Implement** — add the constants and `_exact` above.

- [x] **Step 4: Run**

Run: `.venv/bin/python -m pytest tests/lib/test_landmine_scan.py -q ; echo "EXIT: $?"`
Expected: all pass. If `test_no_script_names_a_binary...` is red, Task 2 missed a site —
fix the site, not the test.

- [x] **Step 5: Mutation checks — steps, not suggestions**

Purge bytecode first (equal-length edits at the same mtime reuse stale `.pyc`):

```bash
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
export PYTHONDONTWRITEBYTECODE=1
```

Run each with `.venv/bin/python -m pytest tests/lib/test_landmine_scan.py -q -p no:cacheprovider`:

| # | Mutation | Must |
|---|----------|------|
| 1 | `_exact`'s `text == banned` → `banned in text` | **FAIL** — else prose is banned and the discriminator is untested |
| 2 | Delete `test_no_script_names_a_binary_instead_of_resolving_it` | n/a — instead revert one Task 2 site to `"ffmpeg"`; the scan must **FAIL** |
| 3 | `_sources(skip=_NAMES_THE_BINARIES)` → `_sources()` | **FAIL** — the default skip is `lint.py`, so `ffbin.py` would be scanned |

Count `FAILED` **and** `ERROR` lines — a battery that greps only `FAILED` reads a collection
error as green. Revert each mutation before the next.

- [x] **Step 6: Commit**

```bash
git add tests/lib/test_landmine_scan.py
git commit -m "test: ban bare ffmpeg/ffprobe literals in scripts/

Regression prevention, and filed as exactly that. The tempting story is 'wrong
binary -> silent corruption', but tracing it says otherwise: run a drawtext graph
on a build without libfreetype and ffmpeg exits 'No such filter', which proc.run
turns into a loud RuntimeError. So this is a convention check and it lives in the
AST scan only — deliberately NOT in check_argv, which is chartered for patterns
that corrupt output silently and runs on every production command. Widening it
with a rule that misses that bar would dilute what a check_argv refusal means.

Equality, not substring: docstrings say 'ffmpeg' constantly and stay legal."
```

---

### Task 5: `setup.sh` stops being destructive

**Files:**
- Modify: `setup.sh` (delete lines 53-61 and 103-114; rewrite the install; fix line 119)
- Modify: `.gitignore`
- Modify: `scripts/lib/proc.py:61-62` (the `FileNotFoundError` remedy)

**Do not run this script.** Edit only.

- [x] **Step 1: Delete both destructive branches**

Remove the drawtext block (`setup.sh:53-61`) and the vidstab block entirely. Both contain
`brew uninstall --ignore-dependencies ffmpeg`, which strips a `--enable-shared` build that
`openai-whisper` and `summarize` link against. With a keg-only formula nothing needs
removing, so the safest version of that code is none of it.

- [x] **Step 2: Replace with install + verify + record**

```bash
# ffmpeg: ONE build carrying every library the pipeline needs — libfreetype for
# drawtext (§5.9 draft labels, §5.16 titles) and libvidstab for stabilization.
# homebrew-core's ffmpeg-full is the SAME version and revision as core ffmpeg, so
# the build swaps while the source does not; it is keg-only, so it installs beside
# core ffmpeg rather than replacing it. Nothing is ever uninstalled here: core
# ffmpeg has its own dependents (openai-whisper, summarize) and removing it with
# --ignore-dependencies leaves them linked against libraries that are gone.
FFMPEG_BIN="$(brew --prefix 2>/dev/null)/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE_BIN="$(brew --prefix 2>/dev/null)/opt/ffmpeg-full/bin/ffprobe"
if [ ! -x "$FFMPEG_BIN" ]; then
  need_brew ffmpeg-full
  echo "installing ffmpeg-full (keg-only; drawtext + vidstab; core ffmpeg untouched)..."
  brew install ffmpeg-full
fi

# VERIFY, do not assume. The formula's dependency list names freetype and
# libvidstab, which is evidence, not observation. A setup script that trusts its
# own success is how the silent `brew pin ... || true` below went unnoticed for
# months.
[ -x "$FFMPEG_BIN" ]  || { echo "ERROR: $FFMPEG_BIN missing after install"; exit 1; }
[ -x "$FFPROBE_BIN" ] || { echo "ERROR: $FFPROBE_BIN missing after install"; exit 1; }
for filt in drawtext vidstabdetect; do
  "$FFMPEG_BIN" -hide_banner -filters 2>/dev/null | grep -q "$filt" || {
    echo "ERROR: ffmpeg-full has no '$filt' filter — the install is not usable"; exit 1; }
done

mkdir -p "$SKILL_DIR/config"
printf 'FFMPEG=%s\nFFPROBE=%s\n' "$FFMPEG_BIN" "$FFPROBE_BIN" > "$SKILL_DIR/config/ffmpeg.env"
echo "recorded config/ffmpeg.env -> $FFMPEG_BIN"
```

- [x] **Step 3: Fix the pin**

`setup.sh:119` currently reads `brew pin ffmpeg 2>/dev/null || true` and has never once
applied — `brew list --pinned` is empty. Replace:

```bash
# Pin so `brew upgrade` cannot drift the version out from under the goldens. NOT
# `|| true`: that idiom is why the previous pin silently never took.
if command -v brew >/dev/null; then brew pin ffmpeg-full; fi
```

- [x] **Step 4: Delete `--with-vidstab` and `--with-fonts`**

Remove both from the arg scan and the `WANT_*` variables. Move the four title casks
(`font-montserrat`, `font-inter`, `font-bebas-neue`, `font-oswald`) into the unconditional
path, keeping the already-installed guard on each. `--with-demucs` and `--with-sourcing`
stay exactly as they are.

- [x] **Step 5: `.gitignore`**

```
# per-machine ffmpeg-full paths that setup.sh records — never committed
config/ffmpeg.env
```

- [x] **Step 6: `proc.py`'s remedy**

`scripts/lib/proc.py:61-62` tells the user to `brew install ffmpeg`. That is now the wrong
remedy — it installs the slim build. Change to `bash setup.sh`.

- [x] **Step 7: Syntax-check without executing**

```bash
bash -n setup.sh ; echo "EXIT: $?"
grep -c 'brew uninstall' setup.sh   # expect 0
grep -c 'with-vidstab\|with-fonts' setup.sh   # expect 0
```

- [x] **Step 8: Suite still green**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`

- [x] **Step 9: Commit**

```bash
git add setup.sh .gitignore scripts/lib/proc.py
git commit -m "fix: setup.sh installs ffmpeg-full instead of destroying ffmpeg

Both branches running 'brew uninstall --ignore-dependencies ffmpeg' are deleted.
The drawtext one was not opt-in and fired on any bare 'bash setup.sh' where the
filter was missing — which is the current state of the development machine — 
against a --enable-shared build that openai-whisper and summarize link against.
ffmpeg-full is keg-only, so nothing needs removing at all.

The install now verifies rather than assumes: it checks both binaries exist and
both filters are really present before recording the paths. The formula's
dependency list is evidence, not observation.

And the pin loses its '2>/dev/null || true'. That idiom is why the pin the
comments credited with protecting the goldens had never applied once —
'brew list --pinned' was empty."
```

---

### Task 6: docs sync

**Files:** `docs/development-workflow.md:10-28`, `docs/build-status.md`, `CLAUDE.md`
(registry rows), `docs/specs/2026-07-05-montage-skillset-design.md` (§12 if a landmine
entry is warranted)

**As built: that list is a third of the real one, and the misses were the load-bearing
ones.** A `--with-vidstab|--with-fonts` sweep of the *whole tree* (not just `docs/`) found
two **runtime** strings and five live instruction sites the list did not name:

- `scripts/lib/fonts.py` raised `run \`bash setup.sh --with-fonts\`` as its fail-loud
  remedy for an uninstalled font — Task 5 deleted the flag and left the message that names
  it — with `tests/lib/test_fonts.py` asserting `match="--with-fonts"`, so the suite was
  *pinning* the stale remedy. **The obvious repair is hollow.** Retargeting the assertion
  to `match="bash setup.sh"` cannot fail: the stale `bash setup.sh --with-fonts` contains
  it as a substring, and restoring the flag left the suite green — measured, not reasoned.
  The real property is two-sided (installer named **and** dead flag absent), and both of
  `resolve_font`'s raises carried the stale text, so both are now pinned. Three mutations,
  each killed by exactly one test.
- `SKILLS/footage-intake/SKILL.md` instructed the agent to check for vidstab by running
  `ffmpeg -hide_banner -filters` itself. On a keg-only install that probes the **wrong
  build** — design §5's trap, written into the prose rather than the code.
- `SKILLS/titles/SKILL.md` (×2), `SKILLS/using-montage/SKILL.md`,
  `docs/specs/2026-07-12-using-montage-design.md` (×2), `scripts/titles.py`'s docstring,
  and two `CLAUDE.md` Titles rows.

**Historical plans and superseded designs keep their original wording**, per the
`fit-blur`→`fit` precedent: the fit-solid slice renamed the mode and did not retro-edit
`docs/plans/2026-07-10-layouts.md` or the layouts design. `using-montage-design.md` is the
exception because every router-touching slice amends it, so it is live text.

Also note `docs/build-status.md`'s "Deferred / open" list carried
`bash setup.sh --with-vidstab` as an open item — a forward-looking section, so it is
corrected, unlike the dated Done entries above it.

- [x] **Step 1:** `development-workflow.md` — the Environment section still documents
  `--with-vidstab` and `--with-fonts` and says "the core never calls vidstab". Rewrite for
  one baseline install. Bump `_Last updated:_` to 2026-07-20.
- [x] **Step 2:** `CLAUDE.md` — add design + plan rows to the Quick Reference table.
- [x] **Step 3:** `build-status.md` — record the slice and the new skip baseline.
- [x] **Step 4:** Tick this plan's checkboxes.
- [x] **Step 5:** Commit.

---

### Task 7: the proof (requires the user's install)

**Blocked on the user running `brew install ffmpeg-full` and `bash setup.sh`.** Do not run
either. Ask, then wait.

- [x] **Step 1: Confirm the record exists**

```bash
cat config/ffmpeg.env
.venv/bin/python -c "from scripts.lib import ffbin; print(ffbin.ffmpeg(), ffbin.ffprobe())"
```

- [x] **Step 2: Confirm the filters are live**

```bash
.venv/bin/python -c "from scripts.lib import ffbin; print(ffbin.has_filter('drawtext'), ffbin.has_filter('vidstabdetect'))"
```
Expected: `True True`.

- [x] **Step 3: The skip-count proof**

Run: `.venv/bin/python -m pytest -q -rs ; echo "EXIT: $?"`

Expected: EXIT 0 and **exactly 2 skips, and specifically these two** —

- `tests/integration/test_offset.py` — needs demucs, which stays opt-in (design §8)
- `tests/integration/test_sourcing.py` — SSL certificate verification failure, an
  environment defect unrelated to this slice

Read the `-rs` list and check the *identity* of the survivors, not just the count. Any
`test_draft`, `test_titles` or `test_intake` skip still present means the guards are probing
the wrong binary and Task 3 did not land — which is precisely the failure design §5 says
this slice can introduce, and it is invisible in a count.

#### On counting

**Do not pin the passed number, in this task or any other.** Every task here adds tests, so
the total is a moving target: an earlier draft of this plan predicted "1518 passed" as the
*final* figure, and Task 0 alone reached 1518 by adding its own six. A target that a third
of the way through the slice already matches by coincidence cannot distinguish success from
anything else — and asserting it would have read as proof.

The claims worth checking are which skips survive, that EXIT is 0, and that the passed count
never *drops*.

- [x] **Step 4: The goldens are the version argument's only real test**

Design §2 argues the build swap is safe because version and revision are identical. The
goldens are the instrument. If any moves, **record the finding — do not re-pin it away**;
a moved golden is a real pixel difference and the spec's §11 says so.

- [x] **Step 5: Whole-slice review, then `superpowers:finishing-a-development-branch`.**
