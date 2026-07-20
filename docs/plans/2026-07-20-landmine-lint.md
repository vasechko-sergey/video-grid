# Landmine Lint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the four §12 silent-corruption ffmpeg patterns mechanically impossible to
re-enter, at two layers — a runtime guard in `proc.run` and a static scan of `scripts/`.

**Architecture:** One pure module (`scripts/lib/lint.py`) whose functions take an argv list
and return violation messages. Two consumers: `proc.run` raises on any violation before
`subprocess.run`, and a pytest source scan catches literals on paths no test exercises.
Neither layer subsumes the other — static is complete where it applies but blind through the
three splat sites; runtime sees the assembled truth but only where tests reach.

**Tech Stack:** Python 3.13, pytest, stdlib `re` only. No new dependencies.

**Design:** [2026-07-20-landmine-lint-design.md](../specs/2026-07-20-landmine-lint-design.md)

---

## Context the implementer needs

**Run everything as:** `.venv/bin/python -m pytest ...` from `/Users/serg/git/video-grid`.
Never pipe pytest through `tail`; append `; echo "EXIT: $?"` instead. Scripts run as modules
(`pythonpath = .` in `pytest.ini`). There is no `tests/__init__.py` in `tests/` root and one
must not be added; `tests/lib/__init__.py` does exist.

**Repo conventions** ([coding-standards.md](../coding-standards.md)): imports at top of
file; errors are `ValueError` with a **remedy** in the message (say what to do, not just
what is wrong); pure logic lives in `scripts/lib/`, orchestration in `scripts/`. Whole-object
asserts where practical.

**The baseline suite is 1416 passed, 8 skipped.** Any task that changes that number without
intending to has broken something.

**Do not install anything.** No `brew`, `pip`, `npm`, no `setup.sh`. This plan adds no
dependencies. (`setup.sh` is currently hazardous — see the design's sibling research; it
would uninstall the working ffmpeg.)

---

## File structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/lint.py` (**new**) | Pure predicate. Constants + `check_argv` + four private checks. No I/O. |
| `scripts/lib/proc.py` (modify) | Gains the runtime guard, ~4 lines before `subprocess.run`. |
| `tests/lib/test_lint.py` (**new**) | The predicate: violating + clean argv per check, and the seven real call-site shapes. |
| `tests/lib/test_landmine_scan.py` (**new**) | Static scan over `scripts/**/*.py` + the planted-violation test that pins the self-exemption. |
| `tests/lib/test_proc.py` (modify) | The guard raises **before** `subprocess.run`. |
| `tests/integration/test_pan.py` (modify) | One comment that states the rule backwards. |
| `references/landmines.md` (modify) | Becomes a pointer to §12 rather than a drifting copy. |
| `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md` (modify) | Registry row + status. |

---

## Task 0: `lint.py` — module, constants, and the `lutrgb` check

**Files:**
- Create: `scripts/lib/lint.py`
- Test: `tests/lib/test_lint.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_lint.py`:

```python
from scripts.lib import lint


def test_check_argv_passes_a_clean_command():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "colorchannelmixer=rr=1.0", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_banned_filter_lutrgb_is_reported():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "lutrgb=r=val*1.1", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "lutrgb" in msgs[0]


def test_the_lutrgb_message_names_the_replacement_not_just_the_ban():
    """A ban with no remedy makes the next author guess. §12 names the replacement."""
    cmd = ["ffmpeg", "-vf", "lutrgb=r=val", "out.mp4"]
    assert "colorchannelmixer" in lint.check_argv(cmd)[0]


def test_colorchannelmixer_is_not_mistaken_for_a_banned_filter():
    cmd = ["ffmpeg", "-i", "a.mp4", "-vf", "colorchannelmixer=rr=0.9:gg=1.0:bb=1.1", "o.mp4"]
    assert lint.check_argv(cmd) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.lint'`

- [ ] **Step 3: Create the module**

Create `scripts/lib/lint.py`:

```python
"""Machine-check the §12 silent-corruption patterns in an emitted ffmpeg argv.

Pure: every function takes an argv list and returns a list of violation messages
(empty = clean). No I/O, no ffmpeg, no filesystem.

Two consumers, and neither subsumes the other (design §2):
  * proc.run's runtime guard — sees the ASSEMBLED command, including the graphs
    that reach it through a splat (`*_filter_args(...)`), but only on paths some
    test actually exercises.
  * tests/lib/test_landmine_scan.py — a literal scan of scripts/, complete for
    filter NAMES (they are never computed anywhere in this repo) including on
    paths no test reaches, but blind through those same splats.

See docs/specs/2026-07-20-landmine-lint-design.md.
"""
import re

# design §12: lutrgb renders black frames. colorchannelmixer is the only colour op.
BANNED_FILTERS = ("lutrgb",)


def _banned_filters(cmd: list[str]) -> list[str]:
    return [f"banned filter {b!r} in {a!r} — design §12: lutrgb renders black frames. "
            f"Use colorchannelmixer instead (scripts/lib/color.py mixer_arg builds it)."
            for a in cmd for b in BANNED_FILTERS if b in a]


def check_argv(cmd: list[str]) -> list[str]:
    """Every §12 landmine violation in one ffmpeg argv. Empty list = clean."""
    out: list[str] = []
    for check in (_banned_filters,):
        out.extend(check(cmd))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -m "feat: lint.check_argv refuses the banned lutrgb filter"
```

---

## Task 1: the `-ss` seek-order check

This is the delicate one. The slogan "`-ss` after `-i`" is **not** the rule the codebase
lives by — a naive positional check produces four false positives out of seven hits on the
current, clean tree. Read design §4.2 before writing code.

**Violation ⟺ all four hold:** the `-ss` is input-side, **and** `-t`/`-to` is present, **and**
`-accurate_seek` is absent, **and** `-frames:v` is absent.

**Files:**
- Modify: `scripts/lib/lint.py`
- Test: `tests/lib/test_lint.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_lint.py`:

```python
# --- the -ss seek-order check -------------------------------------------------
# Design §4.2. Each exemption gets its own test, so a mutation deleting any single
# condition turns exactly one of these red.

def test_input_side_ss_on_a_re_encoded_window_is_reported():
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0",
           "-c:v", "libx264", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "-ss" in msgs[0]


def test_output_side_ss_on_a_window_is_clean():
    """-ss AFTER the -i it applies to is the fix, not the landmine."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-ss", "5.0", "-t", "2.0",
           "-c:v", "libx264", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_accurate_seek_exempts_an_input_side_window():
    """§12 lists three remedies and -accurate_seek is one of them (scripts/mix.py)."""
    cmd = ["ffmpeg", "-y", "-accurate_seek", "-ss", "5.0", "-i", "a.wav",
           "-t", "2.0", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_a_still_grab_is_exempt_because_it_is_not_a_cut():
    """scripts/storyboard.py:30 — grabbing one still deep inside a clip is not a cut."""
    cmd = ["ffmpeg", "-y", "-ss", "1.2", "-i", "a.mp4", "-frames:v", "1", "f.png"]
    assert lint.check_argv(cmd) == []


def test_an_open_ended_input_seek_is_exempt_because_it_is_not_a_window():
    """No -t/-to: the command is not cutting a window, so the cut-boundary
    landmine cannot apply."""
    cmd = ["ffmpeg", "-y", "-ss", "1.2", "-i", "a.mp4", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_sseof_is_never_mistaken_for_ss():
    """-sseof contains '-ss' as a prefix, MUST precede -i, and is a different
    option. A substring match flags it — that is a bug in the lint, not a finding.
    Live example: scripts/check_episode.py:24."""
    cmd = ["ffmpeg", "-y", "-sseof", "-0.5", "-i", "a.mp4", "-t", "0.5",
           "-c:v", "libx264", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_ss_is_input_side_when_any_i_follows_it_not_only_the_first():
    """ffmpeg binds -ss to the input AFTER it. In `-i a -ss 5 -i b` the seek is
    input-side for b; a 'before the FIRST -i' test reads it as an output seek and
    misses the violation. scripts/mix.py:207 already builds multi-input commands."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-ss", "5.0", "-i", "b.mp4",
           "-t", "2.0", "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_the_seek_message_names_both_remedies():
    cmd = ["ffmpeg", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c:v", "libx264", "o.mp4"]
    msg = lint.check_argv(cmd)[0]
    assert "output seek" in msg and "accurate_seek" in msg
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: FAIL — 3 of the new tests fail (the two violation tests and the message test);
the exemption tests pass vacuously because no seek check exists yet. **That vacuous pass is
expected and is exactly why Step 5's mutation check is a step and not a suggestion.**

- [ ] **Step 3: Implement**

In `scripts/lib/lint.py`, add after `_banned_filters`:

```python
def _seek_order(cmd: list[str]) -> list[str]:
    """The §12 seek landmine: an input-side -ss on a re-encoded WINDOW puts black
    frames at the cut boundary.

    Comparison is exact-token throughout. Substring matching would flag `-sseof`,
    which starts with `-ss`, must precede `-i` by ffmpeg's own contract, and is a
    different option — a false positive on correct code, which for a guard that
    raises in production is worse than a miss.
    """
    if "-accurate_seek" in cmd:      # §12 names this as one of its three remedies
        return []
    if "-frames:v" in cmd:           # a still grab is not a cut (storyboard.py:30)
        return []
    if "-t" not in cmd and "-to" not in cmd:
        return []                    # not cutting a window ⇒ no cut boundary
    for i, a in enumerate(cmd):
        # Input-side iff some -i FOLLOWS this -ss — not "before the first -i".
        # ffmpeg binds -ss to the input after it, so `-i a -ss 5 -i b` seeks b.
        if a == "-ss" and "-i" in cmd[i + 1:]:
            return ["input-side -ss on a re-encoded window — design §12: this is the "
                    "black-frames-at-a-cut landmine. Move -ss after the -i it applies "
                    "to (output seek), or pass -accurate_seek if the input seek is "
                    "deliberate (see scripts/mix.py:193)."]
    return []
```

and extend the tuple in `check_argv`:

```python
    for check in (_banned_filters, _seek_order):
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: PASS (12 tests)

- [ ] **Step 5: Mutation check — each exemption must be load-bearing**

Purge bytecode between mutations and run with bytecode writing off; equal-length
mutations at the same mtime otherwise reuse the previous mutation's `.pyc` and the
battery reports the opposite of the truth.

```bash
find . -path ./.venv -prune -o -name __pycache__ -type d -print0 | xargs -0 rm -rf
```

Apply each mutation to `scripts/lib/lint.py`, run
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_lint.py -q -p no:cacheprovider; echo "EXIT: $?"`,
confirm the named test goes RED, then revert and purge `__pycache__` again.

| # | Mutation | Must turn RED |
|---|----------|---------------|
| 1 | delete the `-accurate_seek` early return | `test_accurate_seek_exempts_an_input_side_window` |
| 2 | delete the `-frames:v` early return | `test_a_still_grab_is_exempt_because_it_is_not_a_cut` |
| 3 | delete the `-t`/`-to` early return | `test_an_open_ended_input_seek_is_exempt_because_it_is_not_a_window` |
| 4 | `a == "-ss"` → `a.startswith("-ss")` | `test_sseof_is_never_mistaken_for_ss` |
| 5 | `"-i" in cmd[i + 1:]` → `"-i" in cmd[i:]` … then check test 2 of the pair | `test_output_side_ss_on_a_window_is_clean` |
| 6 | search only up to the first `-i` (`cmd[i+1:cmd.index("-i")+1]`) | `test_ss_is_input_side_when_any_i_follows_it_not_only_the_first` |

All six must go red. If any stays green, the corresponding test is hollow — fix the test,
not the table.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -m "feat: lint refuses an input-side -ss on a re-encoded window"
```

---

## Task 2: the unbounded synthesized source check

**Files:**
- Modify: `scripts/lib/lint.py`
- Test: `tests/lib/test_lint.py`

**Read design §4.3 first.** This check closes the *hang*, not the *wrong length* — the two
are different failures and requiring `-t` unconditionally would fire on correct code
(`scripts/mix.py:109`). The length stays pinned by the existing
`test_reframe_bounds_every_layout_to_the_source_length`, which must **not** be deleted.

**The substring trap:** `"color="` occurs inside `boxcolor=` and `fontcolor=`, both of which
`scripts/lib/draft.py:28` emits on every draft render. A naive `"color=" in arg` check raises
on correct code. Source names must be matched at a filtergraph-element boundary.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_lint.py`:

```python
# --- the unbounded synthesized source check -----------------------------------

def test_an_unbounded_color_source_is_reported():
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "color=" in msgs[0]


def test_an_output_bound_makes_a_synth_source_clean():
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-t", "3.0", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_a_source_side_duration_makes_a_synth_source_clean():
    """scripts/mix.py:109 — anoisesrc with d= and no -t. The d= IS the whoosh's
    length; there is no real input for it to mismatch."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           "anoisesrc=color=pink:r=48000:d=0.35:a=0.9:seed=7", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_a_synth_source_inside_a_filter_complex_is_seen():
    """reframe emits `color=...` inside -filter_complex, not as an -i value."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "color=c=black:s=64x64:r=30[bg];[bg][0:v]overlay=0:0", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_boxcolor_is_not_mistaken_for_a_color_source():
    """THE substring trap: 'color=' sits inside boxcolor= and fontcolor=, which
    scripts/lib/draft.py:28 emits on every draft render. Matching 'color=' as a
    bare substring raises on correct code — and this guard raises in production."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf",
           ("drawtext=fontfile='/f.ttf':textfile='/t.txt':fontsize=h/24:"
            "fontcolor=white:box=1:boxcolor=black@0.5:x=40:y=40"), "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_a_synth_source_after_a_graph_separator_is_still_seen():
    """The boundary rule must not become 'only at the start of the string'."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "[0:v]scale=64:64[v];testsrc=s=64x64[t];[v][t]overlay=0:0", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: FAIL — the three violation tests fail; the three exemption tests pass vacuously.

- [ ] **Step 3: Implement**

In `scripts/lib/lint.py`, add near the top, under `BANNED_FILTERS`:

```python
# lavfi sources that never send end-of-stream unless bounded (design §12).
SYNTH_SOURCES = ("color=", "testsrc", "anullsrc", "anoisesrc", "sine=")

# A source NAME, not a parameter that merely ends in one. `color=` occurs inside
# `boxcolor=`/`fontcolor=` (scripts/lib/draft.py:28 emits both on every draft
# render), so the name must start a filtergraph element: string start, or just
# after a graph separator. Matching it as a bare substring raises on correct code.
_SYNTH_RE = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(
    re.escape(s) for s in SYNTH_SOURCES) + r")")
```

and after `_seek_order`:

```python
def _unbounded_source(cmd: list[str]) -> list[str]:
    """The §12 infinite-source hang: an unbounded `color`/`testsrc`/`anullsrc`
    never sends end-of-stream, so the encode runs until something kills it —
    measured at 90s-and-killed against a 0.8s normal run.

    Bounded means EITHER an output `-t`/`-to` OR a source-side `d=`/`duration=`.
    Both stop the hang. Only `-t` also fixes the LENGTH (a `d=` frame count need
    not match a real input's — 96 rendered against a source's 95), and that half
    stays pinned by test_reframe_bounds_every_layout_to_the_source_length. Two
    failures, two guards; do not collapse them.
    """
    if "-t" in cmd or "-to" in cmd:
        return []
    out = []
    for a in cmd:
        m = _SYNTH_RE.search(a)
        if m and "d=" not in a and "duration=" not in a:
            out.append(
                f"unbounded synthesized source {m.group()!r} in {a!r} — design §12: "
                "a lavfi source with no duration never sends end-of-stream, so the "
                "encode runs until it is killed. Bound the OUTPUT with -t (preferred: "
                "it also fixes the frame count) or give the source a d=.")
    return out
```

and extend `check_argv`:

```python
    for check in (_banned_filters, _seek_order, _unbounded_source):
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: PASS (18 tests)

- [ ] **Step 5: Mutation check**

Purge `__pycache__` between mutations, as in Task 1 Step 5.

| # | Mutation | Must turn RED |
|---|----------|---------------|
| 1 | `_SYNTH_RE` → plain `any(s in a for s in SYNTH_SOURCES)` | `test_boxcolor_is_not_mistaken_for_a_color_source` |
| 2 | lookbehind → `^` anchor (`re.compile(r"^(?:...)")`) | `test_a_synth_source_after_a_graph_separator_is_still_seen` |
| 3 | drop the `"d=" not in a` term | `test_a_source_side_duration_makes_a_synth_source_clean` |
| 4 | drop the `-t`/`-to` early return | `test_an_output_bound_makes_a_synth_source_clean` |

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -m "feat: lint refuses an unbounded synthesized lavfi source"
```

---

## Task 3: the `drawtext` font check

**Files:**
- Modify: `scripts/lib/lint.py`
- Test: `tests/lib/test_lint.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_lint.py`:

```python
# --- the drawtext font check --------------------------------------------------

def test_drawtext_without_fontfile_is_reported():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "drawtext=text='hi':fontsize=24",
           "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "fontfile" in msgs[0]


def test_drawtext_with_fontfile_is_clean():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf",
           "drawtext=fontfile='/f.ttf':text='hi':fontsize=24", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_each_drawtext_in_a_chain_needs_its_own_font():
    """scripts/lib/titles.py:152 joins per-title drawtext pieces with ','. Asking
    whether the WHOLE string contains 'fontfile=' passes a chain where only the
    first piece has one — and the fontless title is the one that renders garbage."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf",
           ("drawtext=fontfile='/f.ttf':text='a':x=0:y=0,"
            "drawtext=text='b':x=0:y=100"), "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: FAIL — the two violation tests fail.

- [ ] **Step 3: Implement**

In `scripts/lib/lint.py`, after `_unbounded_source`:

```python
def _drawtext_font(cmd: list[str]) -> list[str]:
    """§12: drawtext without an explicit fontfile= fails, or picks garbage on
    macOS — the filter and the font are decoupled.

    Split on the filter name so EACH drawtext is judged on its own segment.
    scripts/lib/titles.py:152 joins per-title pieces with ',', so a whole-string
    test would pass a chain in which only the first piece carries a font.
    """
    out = []
    for a in cmd:
        for seg in a.split("drawtext=")[1:]:
            if "fontfile=" not in seg:
                out.append(
                    f"drawtext without fontfile= in {a!r} — design §12: drawtext and "
                    "its font are decoupled, so with no explicit path it fails or "
                    "picks a garbage face on macOS. Resolve one with "
                    "scripts/lib/fonts.py resolve() and pass fontfile='<path>'.")
    return out
```

and extend `check_argv`:

```python
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font):
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: PASS (21 tests)

- [ ] **Step 5: Mutation check**

| # | Mutation | Must turn RED |
|---|----------|---------------|
| 1 | `for seg in a.split("drawtext=")[1:]` → `if "drawtext=" in a and "fontfile=" not in a` | `test_each_drawtext_in_a_chain_needs_its_own_font` |
| 2 | `[1:]` → `[0:]` | `test_drawtext_with_fontfile_is_clean` (segment 0 is the prefix, never has a font) |

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -m "feat: lint refuses a drawtext with no explicit fontfile"
```

---

## Task 4: the seven real call-site shapes

The predicate is only worth having if it matches **the codebase**, not the slogan. These
fixtures are the regression guard that proves it. Design §4.2's table is their source.

**Files:**
- Test: `tests/lib/test_lint.py`

- [ ] **Step 1: Write the tests**

Append to `tests/lib/test_lint.py`:

```python
# --- every real call site in the tree must lint clean -------------------------
# Design §4.2's table, as executable fixtures. If a future edit to the predicate
# starts firing on production code, THIS is what goes red — before the guard has
# a chance to raise in the middle of somebody's render.

REAL_SITES = {
    "extract.py:18 — output seek on a window": [
        "ffmpeg", "-y", "-i", "src.mp4", "-ss", "3.5", "-t", "2.0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "out.mp4"],
    "check_reel.py:65 — output seek, still grab": [
        "ffmpeg", "-y", "-i", "reel.mp4", "-ss", "1.5", "-frames:v", "1", "f.png"],
    "storyboard.py:36 — input seek, still grab, no window": [
        "ffmpeg", "-y", "-ss", "1.2", "-i", "src.mp4", "-frames:v", "1", "f00.png"],
    "mix.py:193 — input seek on a window, accurate_seek": [
        "ffmpeg", "-y", "-accurate_seek", "-ss", "12.5", "-i", "track.mp3",
        "-t", "18.0", "-af", "afade=t=in:st=0:d=0.5", "frag.wav"],
    "check_episode.py:24 — sseof": [
        "ffmpeg", "-y", "-sseof", "-0.5", "-i", "clip.mp4", "-vf", "fps=6/0.5",
        "-f", "image2", "l%03d.png"],
    "mix.py:75 — anullsrc bounded by -t": [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "2.5", "-c:a", "pcm_s16le", "amb.wav"],
    "mix.py:109 — anoisesrc bounded by d=": [
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "anoisesrc=color=pink:r=48000:d=0.35:a=0.9:seed=7",
        "-af", "bandpass=f=1200:width_type=q:w=0.7",
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", "whoosh.wav"],
    "reframe.py:380 — solid background, d= and -t": [
        "ffmpeg", "-y", "-i", "src.mp4", "-filter_complex",
        ("color=c=black:s=1080x1920:r=30:d=2.000000[bg];"
         "[0:v]crop=608:1080:x='100':y=0,scale=1080:1920[fg];"
         "[bg][fg]overlay=0:0,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
         "fps=30,format=yuv420p"),
        "-t", "2.000000", "-c:v", "libx264", "-crf", "18", "-an", "out.mp4"],
    "draft.py:56 — drawtext label with a resolved font": [
        "ffmpeg", "-y", "-i", "seg.mp4", "-vf",
        ("scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,"
         "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p,"
         "drawtext=fontfile='/System/Library/Fonts/Helvetica.ttc':"
         "textfile='/w/l0.txt':fontsize=h/24:fontcolor=white:box=1:"
         "boxcolor=black@0.5:boxborderw=12:x=40:y=h-th-40"),
        "-c:v", "libx264", "out.mp4"],
}


@pytest.mark.parametrize("name", sorted(REAL_SITES))
def test_every_real_call_site_lints_clean(name):
    assert lint.check_argv(REAL_SITES[name]) == [], name
```

Add `import pytest` to the top of the file if it is not there already.

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -q; echo "EXIT: $?"`
Expected: PASS (30 tests). **If any of these fail, the predicate is wrong — fix the
predicate, never the fixture.** The fixtures are transcriptions of shipped commands; a
fixture edited to satisfy a wrong predicate destroys the only evidence that the lint matches
reality.

- [ ] **Step 3: Commit**

```bash
git add tests/lib/test_lint.py
git commit -m "test: every real ffmpeg call site in the tree lints clean"
```

---

## Task 5: the runtime guard in `proc.run`

**Files:**
- Modify: `scripts/lib/proc.py`
- Test: `tests/lib/test_proc.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_proc.py`:

```python
def test_run_refuses_a_command_carrying_a_landmine(monkeypatch):
    """The guard must fire BEFORE the command executes. Asserting on the outcome
    would pass for the wrong reason (ffmpeg failing on its own), so subprocess.run
    is monkeypatched to fail if it is called at all — the shape §12's smoothing
    entry prescribes, for the same reason."""
    def _never(*a, **k):
        raise AssertionError("subprocess.run was reached — the guard did not fire")
    monkeypatch.setattr(proc.subprocess, "run", _never)
    with pytest.raises(ValueError, match="lutrgb"):
        proc.run(["ffmpeg", "-y", "-i", "a.mp4", "-vf", "lutrgb=r=val", "out.mp4"])


def test_run_lets_a_clean_command_through(monkeypatch):
    seen = {}
    def _fake(cmd, **k):
        seen["cmd"] = cmd
        return "ok"
    monkeypatch.setattr(proc.subprocess, "run", _fake)
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "colorchannelmixer=rr=1.0", "o.mp4"]
    assert proc.run(cmd) == "ok"
    assert seen["cmd"] == cmd


def test_the_refusal_reports_every_violation_not_only_the_first(monkeypatch):
    """Two landmines in one command should surface together — fixing one and
    re-running to discover the next is a slow way to learn."""
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: pytest.fail("guard did not fire"))
    with pytest.raises(ValueError) as e:
        proc.run(["ffmpeg", "-y", "-ss", "1.0", "-i", "a.mp4", "-t", "2.0",
                  "-vf", "lutrgb=r=val", "out.mp4"])
    assert "lutrgb" in str(e.value) and "-ss" in str(e.value)


def test_the_refusal_is_a_value_error_not_a_runtime_error(monkeypatch):
    """proc.run's RuntimeErrors describe the ENVIRONMENT failing (binary missing,
    timeout, non-zero exit). A landmine is the CALLER being wrong — a programming
    error, which every config-spec in models.py raises ValueError for."""
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: pytest.fail("guard did not fire"))
    with pytest.raises(ValueError):
        proc.run(["ffmpeg", "-vf", "lutrgb=r=val", "o.mp4"])
```

Ensure `tests/lib/test_proc.py` imports `pytest` and `from scripts.lib import proc`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_proc.py -q; echo "EXIT: $?"`
Expected: FAIL — `subprocess.run was reached — the guard did not fire`

- [ ] **Step 3: Implement**

In `scripts/lib/proc.py`, add to the imports at the top:

```python
from scripts.lib import lint
```

and insert at the very start of `run`'s body, **before** `kwargs.setdefault`:

```python
    # Always on, never behind an env flag. The obvious argument for gating this is
    # "keep production fast" — a handful of string scans over a ~20-element list,
    # against a command that runs for seconds to minutes. The saving is
    # unmeasurable and a guard that is off in production does not protect
    # production. Refusing to run a command that will silently corrupt the output
    # beats running it (design §3).
    problems = lint.check_argv(cmd)
    if problems:
        raise ValueError(
            "refusing to run a command carrying a design §12 landmine:\n  "
            + "\n  ".join(problems)
            + f"\ncommand: {' '.join(map(str, cmd))}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_proc.py -q; echo "EXIT: $?"`
Expected: PASS

- [ ] **Step 5: Check for an import cycle**

`lint.py` imports only `re`, so `proc → lint` cannot cycle. Confirm:

Run: `.venv/bin/python -c "from scripts.lib import proc; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/proc.py tests/lib/test_proc.py
git commit -m "feat: proc.run refuses a command carrying a §12 landmine"
```

---

## Task 6: the static source scan

Runtime coverage equals test coverage. This layer catches a banned **literal** on a path no
test exercises — which is where runtime is blind and static is complete, because filter names
are never computed anywhere in this repo.

**Files:**
- Create: `tests/lib/test_landmine_scan.py`

- [ ] **Step 1: Write the tests**

Create `tests/lib/test_landmine_scan.py`:

```python
"""Static half of the landmine lint: no banned filter LITERAL may appear in
scripts/, on any path, whether or not a test exercises it.

Scans scripts/ only, never tests/ — the existing ban assertions (e.g.
tests/integration/test_reframe.py:449 `assert "lutrgb" not in args[1]`)
legitimately contain the literal. Tests are covered at runtime through proc.run
instead. See docs/specs/2026-07-20-landmine-lint-design.md §6.
"""
from pathlib import Path

import pytest

from scripts.lib import lint

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# The one file that must be skipped: it DECLARES the banned tokens. The skip is a
# hole by construction, so it is exactly one file wide and pinned by
# test_the_self_exemption_is_one_file_wide below.
_DEFINES_THE_BAN = SCRIPTS / "lib" / "lint.py"


# Root and skip are PARAMETERS, not module globals reached by monkeypatch:
# `tests/` has no __init__.py (testing-guide.md forbids adding one), so
# "tests.lib.test_landmine_scan.SCRIPTS" is not an importable dotted path and a
# string-target monkeypatch would fail to resolve.
def _sources(root: Path = SCRIPTS, skip: Path | None = None) -> list[Path]:
    skip = _DEFINES_THE_BAN if skip is None else skip
    return [p for p in sorted(root.rglob("*.py")) if p != skip]


def test_the_scan_actually_finds_files():
    """A glob that silently matches nothing would make every scan below pass
    vacuously — the failure mode this whole file exists to prevent."""
    found = _sources()
    assert len(found) > 20
    assert any(p.name == "reframe.py" for p in found)


@pytest.mark.parametrize("banned", lint.BANNED_FILTERS)
def test_no_script_emits_a_banned_filter(banned):
    guilty = [f"{p}:{i}" for p in _sources()
              for i, line in enumerate(p.read_text().splitlines(), 1)
              if banned in line]
    assert guilty == [], f"{banned!r} present in: {guilty}"


def test_the_self_exemption_is_one_file_wide(tmp_path):
    """Plant a violation in a DIFFERENT file and prove the scan still catches it.
    Without this, widening the skip to a directory (or to lib/) would go unnoticed
    and the static layer would quietly stop covering anything."""
    fake = tmp_path / "scripts"
    (fake / "lib").mkdir(parents=True)
    (fake / "lib" / "lint.py").write_text('BANNED_FILTERS = ("lutrgb",)\n')
    (fake / "renderer.py").write_text('VF = "lutrgb=r=val*1.1"\n')
    guilty = [p.name for p in _sources(fake, fake / "lib" / "lint.py")
              if "lutrgb" in p.read_text()]
    assert guilty == ["renderer.py"]
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/lib/test_landmine_scan.py -q; echo "EXIT: $?"`
Expected: PASS (3 tests). The tree is currently clean, so
`test_no_script_emits_a_banned_filter` passes on the first run — that is correct, not a
missing red phase; Step 3 supplies the red.

- [ ] **Step 3: Prove the scan is not vacuous**

Temporarily add `_X = "lutrgb=r=val"` to `scripts/lib/color.py`, run the file again, and
confirm `test_no_script_emits_a_banned_filter` goes RED naming `color.py`. Then remove it and
confirm green. A scan that cannot fail is not a scan.

- [ ] **Step 4: Commit**

```bash
git add tests/lib/test_landmine_scan.py
git commit -m "test: no script may carry a banned filter literal, exercised or not"
```

---

## Task 7: the whole suite under the live guard

This is the real proof and it is not a formality. `proc.run` now inspects **every** ffmpeg
command the suite issues — all 35 production sites plus every integration test. If the
predicate is wrong anywhere, real commands start raising here.

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: **1416 passed, 8 skipped** plus the new tests from Tasks 0–6 (37 or so), EXIT 0.

- [ ] **Step 2: If anything fails, diagnose in this order**

1. Is it a `ValueError: refusing to run a command carrying a design §12 landmine`? Then the
   predicate has a false positive. **Fix `lint.py`, and add the offending argv to
   `REAL_SITES` in `tests/lib/test_lint.py`** so it can never regress. Do not add a path
   allowlist — design §4.2 is explicit that exemptions are earned by properties of the
   command.
2. Is it an import error? Check the `proc → lint` import added in Task 5.
3. Anything else is unrelated to this slice; report it rather than absorbing it.

- [ ] **Step 3: Commit if anything changed**

```bash
git add -A
git commit -m "fix: <what the live guard caught>"
```

If nothing changed, skip the commit and say so in the task report.

---

## Task 8: docs sync and the two drive-by corrections

**Files:**
- Modify: `tests/integration/test_pan.py` (the backwards comment, ~line 41)
- Modify: `references/landmines.md`
- Modify: `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`

- [ ] **Step 1: Fix the inverted comment**

`tests/integration/test_pan.py:40-41` states the banned pattern is "`-ss` AFTER `-i`" — the
reverse of every other source in the repo, introduced by the pan slice (2026-07-19). The test
itself uses `-sseof` and is correct; only the comment is wrong.

Replace:

```python
        # -sseof BEFORE -i is the established form in this repo (check_episode
        # uses it); the banned pattern is `-ss` AFTER `-i` for frame-accurate cuts
```

with:

```python
        # -sseof BEFORE -i is the established form in this repo (check_episode
        # uses it) and is a DIFFERENT option that must precede -i. The §12 landmine
        # is an input-side `-ss` on a re-encoded window — scripts/lib/lint.py holds
        # the predicate; this command trips none of its four conditions.
```

- [ ] **Step 2: Turn `references/landmines.md` into a pointer**

Its header claims two incompatible things — "Copied verbatim from design spec §12" **and**
"this is the canonical list" — and neither is true: 17 entries against §12's 28, and its
`ultralytics` entry still asserts something §12 has since struck through as "never true".
Re-syncing produces a duplicate that drifts again.

Replace the whole file with:

```markdown
# Landmine registry — pointer

_Last updated: 2026-07-20._

**The registry lives in design spec §12**, in
[docs/specs/2026-07-05-montage-skillset-design.md](../docs/specs/2026-07-05-montage-skillset-design.md).
It is the single canonical list; add entries there.

This file used to carry a copy that claimed to be verbatim and was not — it had
drifted to 17 entries against §12's 28, and still asserted an `ultralytics` detail
§12 had struck through as never true. A second copy of a safety-critical list is a
second thing to forget to update, so it is now a pointer rather than a duplicate.

Four of §12's entries are **machine-checked** and can no longer re-enter the
codebase silently — `lutrgb`, input-side `-ss` on a re-encoded window, an unbounded
synthesized lavfi source, and `drawtext` without `fontfile=`. The predicate is
[scripts/lib/lint.py](../scripts/lib/lint.py); the reasoning, and an explicit list
of what it does **not** cover, is in
[the landmine lint design](../docs/specs/2026-07-20-landmine-lint-design.md).

The rest of §12 stays human: entries like "never stabilize a wade-in shot" are
judgment about content, and nothing in the codebase classifies a wade shot.
```

Then check nothing that links here breaks: `grep -rn "landmines.md" --include=*.md .`
and fix any link whose surrounding sentence promised a list rather than a pointer.

- [ ] **Step 3: Add the CLAUDE.md registry row**

In the Quick Reference table, after the `pan` rows:

```markdown
| Landmine lint design | [2026-07-20-landmine-lint-design.md](docs/specs/2026-07-20-landmine-lint-design.md) | §11's chartered lint: four §12 silent-corruption patterns machine-checked at two layers — `proc.run`'s always-on runtime guard (the assembled argv, all 35 sites) + a static scan of `scripts/` (complete for literals, blind through splats). The slogan "`-ss` after `-i`" is **not** the rule the code lives by — the real predicate is written down here for the first time. |
| Landmine lint plan | [2026-07-20-landmine-lint.md](docs/plans/2026-07-20-landmine-lint.md) | Tasks 0–8: `lint.py` + four checks, the seven real call-site fixtures, `proc.run`'s guard, the static scan, the whole-suite proof, docs. Mutation checks are steps, not suggestions. |
```

- [ ] **Step 4: Update build-status and pipeline-map**

In `docs/build-status.md`: add a Done entry for the slice, and **remove "golden-canon
armature + landmine lint" from the Next-action list** — the lint half is now built. Say
plainly what it does not cover (design §5): `tests/conftest.py:17` bypasses `proc.run`;
runtime coverage equals test coverage; a splat-assembled graph on an unexercised path is
covered by neither layer. Bump `_Last updated:_` to 2026-07-20.

In `docs/pipeline-map.md`: the lint is cross-cutting, not a stage — no status-table row
changes. Bump `_Last updated:_` to 2026-07-20 only if you touch the file.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: same count as Task 7, EXIT 0.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: sync the landmine lint slice; landmines.md becomes a pointer"
```

---

## Self-review notes (author's, for the reviewer)

- **Spec coverage:** §4.1→Task 0, §4.2→Task 1, §4.3→Task 2, §4.4→Task 3, §2/§4.2 table→Task
  4, §3→Task 5, §2/§6→Task 6, §8→Tasks 0–6, §9→Task 8. §5 (gaps) and §7 (out of scope) are
  documentation-only and land in Task 8 Step 4.
- **The one thing most likely to go wrong** is a false positive surfacing in Task 7 on a
  command shape not in design §4.2's table. That is why Task 7 has an explicit diagnosis
  order and why its remedy is "fix the predicate and add the shape to `REAL_SITES`", never
  "allowlist the path".
- **`SYNTH_SOURCES` is a guess about coverage, not about correctness.** It lists the five
  lavfi sources this repo actually uses. A source it does not name (`smptebars`, `life`,
  `cellauto`) would go unchecked — a miss, not a false positive, and the safe direction.
