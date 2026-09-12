# Re-derivable purpose — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put every tool's purpose, and every skill's place in the conveyor, on
the two surfaces that survive a compaction — the tool's own `--help` and the
skill listing's `description:` — and pin all of it against the code so it
cannot drift.

**Architecture:** Every `scripts/*.py` gains `build_parser()`, which turns 46
help surfaces from scrapeable text into walkable objects. Two tests use that
handle: one walks the parsers and demands a description on every surface and a
`help` on every argument; one runs the real `--help` and demands the
description reaches stdout. `montage tools` renders three artifacts from the
same parsers plus `montage.V1_STAGES` — the `references/tools.md` index, each
stage skill's position sentence, and the router's chain — and tests pin the
committed copies byte-for-byte. The 14 skill `description:` lines are rewritten
to trigger plus pointer plus position, shedding the documentation that had
crept into them.

**Tech Stack:** Python 3, `argparse`, `pytest`, `subprocess`. No new
dependency. No ffmpeg, no golden fixture, no `CACHE_VERSION` bump.

**Design:** [2026-09-12-rederivable-purpose-design.md](../specs/2026-09-12-rederivable-purpose-design.md)

---

## Global Constraints

Every task is bound by these. A reviewer checks against them.

1. **Python is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .`
   in `pytest.ini`): `python -m scripts.<name>`, never `python scripts/<name>.py`.
2. **Never install anything.** No `brew`, `pip`, `uv`, `npm`, `apt`, no
   `setup.sh`. Verification is read-only plus `pytest`.
3. **Never `git checkout --`, `git restore`, `git reset --hard` or `git stash`.**
   To undo a mutation of a COMMITTED file use `git show HEAD:<path> > <path>`;
   before mutating an UNCOMMITTED file save your own copy first
   (`cp <path> <path>.bak`) and restore from that.
4. **A mutation battery runs under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte
   edit can match the previous file's size and mtime-second, and CPython then
   serves a stale `.pyc`.
5. **zsh does not word-split an unquoted variable.** A pytest selection held in
   a shell variable arrives as ONE argument and the run prints `no tests ran`,
   which reads exactly like a non-discriminating mutation row. Quote or expand
   explicitly.
6. **`build_parser()` is a pure move.** The same parser, built by the same
   statements in the same order, returned instead of consumed in place. No
   argument is added, removed, reordered, retyped or re-defaulted in Task 1.
   Task 2 and Task 3 add only `description=` and `help=` strings.
7. **Every new assertion message ends with the command that fixes it.** A
   failing index pin must print
   `python -m scripts.montage tools > references/tools.md`, not just a diff.
8. **Commit after every task**, conventional prefix, ending with
   `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Never `--amend` a
   reviewed commit; a post-review fix is its own commit.
9. **Do not touch `/Users/serg/Downloads/untitled folder/`** — the only real
   run, read-only forever.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `scripts/*.py` (31) | modify | each gains `build_parser()`; 20 descriptions and 56 `help=` strings filled |
| `scripts/lib/toolindex.py` | **create** | pure renderers: index rows, the position sentence, the conveyor chain. No I/O. |
| `scripts/montage.py` | modify | a third subcommand, `tools`, printing what `toolindex` renders |
| `references/tools.md` | **create** | the committed index — 46 rows, generated, pinned |
| `skills/*/SKILL.md` (14) | modify | `description:` frontmatter only; bodies untouched |
| `tests/test_cli_help.py` | **create** | the parser walk and the real-`--help` emission check |
| `tests/test_tool_index.py` | **create** | the index pin |
| `tests/test_skills_contract.py` | modify | pointer, position and chain pins |
| `docs/coding-standards.md` | modify | the CLI-description prose standard (§2.3) |
| `CHANGELOG.md`, `.claude-plugin/plugin.json` | modify | 0.9.2 |
| `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md` | modify | close R4.1/R4.2/R4.3, file the four deferred rows |

`scripts/lib/toolindex.py` is a new pure module rather than more code in
`montage.py` for the reason the design gives in §3.3: the renderers are read by
the CLI **and** by three tests, and a pure leaf with no I/O can be imported by
a test without importing a driver.

---

## Task 1: `build_parser()` on all 31 scripts

**Files:**
- Modify: every `scripts/*.py` except `scripts/__init__.py` (31 files)
- Create: `tests/test_cli_help.py`

**Why first:** nothing outside a script can see its parser today — 26 build it
inline in `main()` and 5 inside `if __name__ == "__main__":` with no `main()`
at all. Every later task needs the handle.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_help.py`:

```python
"""Every CLI states what it is for, on the surface an agent can re-derive.

A skill body is context and context is spent; `--help` is one Bash call at any
context age (design 2026-09-12 §0.3). The retro measured an agent reaching for
it after a compaction — 12 of 13 `--help` calls in the following 2 h 17 min —
and finding 5 of 31 top-level parsers and 0 of 15 subcommands with anything to
say (§0.4).

Two instruments, because they answer different questions. The walk below is
EXACT: it reads the parser objects, so no line-wrapped help text has to be
scraped. The subprocess check measures EMISSION — that the real entry point
still routes through `build_parser()` — and asserts only the description,
because `intake` carries three `help` strings using `%(default)s` and argparse
expands them at format time, so raw containment would fail on a correct file.
"""
import argparse
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = sorted(p.stem for p in (ROOT / "scripts").glob("*.py") if p.stem != "__init__")


def surfaces(parser: argparse.ArgumentParser, name: str):
    """Yield (label, parser) for the parser and every subparser under it."""
    yield name, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for key, sub in action.choices.items():
                yield f"{name} {key}", sub


def arguments(parser: argparse.ArgumentParser):
    """Every real argument — `-h` and the subcommand slot are argparse's, not ours."""
    return [a for a in parser._actions
            if not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))]


@pytest.mark.parametrize("name", CLI)
def test_every_script_exposes_build_parser(name):
    mod = importlib.import_module(f"scripts.{name}")
    assert hasattr(mod, "build_parser"), (
        f"scripts/{name}.py has no build_parser() — the parser is built and consumed "
        f"in one breath, so nothing outside can see its 'help' surface. "
        f"Extract it: `def build_parser() -> argparse.ArgumentParser: ... return ap`")
    assert isinstance(mod.build_parser(), argparse.ArgumentParser)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q
```

Expected: **31 failed**, each `scripts/<name>.py has no build_parser()`.

- [ ] **Step 3: Extract the parser in each of the 26 scripts that have a `main()`**

The move, shown on `scripts/mix.py` and identical everywhere:

```python
# before
def main() -> None:
    ap = argparse.ArgumentParser(description="build the reel audio stem from MUSIC.json")
    ap.add_argument("music", help="MUSIC.json path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dur", type=float, required=True, help="reel length (seconds)")
    a = ap.parse_args()
    print(mix(MusicSpec.from_json(a.music), a.out_dir, a.dur))
```

```python
# after
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="build the reel audio stem from MUSIC.json")
    ap.add_argument("music", help="MUSIC.json path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dur", type=float, required=True, help="reel length (seconds)")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    print(mix(MusicSpec.from_json(a.music), a.out_dir, a.dur))
```

Everything between `ArgumentParser(` and `parse_args()` moves verbatim into
`build_parser()`; everything after `parse_args()` stays in `main()`. Nothing
else changes (Global Constraint 6).

**Two files need care, and only these two:**

`scripts/intake.py` — `main` takes `argv` and passes it through. Keep that:

```python
def main(argv: list[str] | None = None) -> None:
    a = build_parser().parse_args(argv)
    f = intake(a.footage_root, a.out_dir, a.sample_fps, jobs=a.jobs, fresh=a.fresh,
               band=(a.win_min, a.win_max))
    print(f"{len(f.clips)} clips, {sum(len(c.windows) for c in f.clips)} windows → {a.out_dir}")
```

`scripts/track.py` — the four pin flags sit in a
`ap.add_mutually_exclusive_group()`. The group is constructed inside
`build_parser()` with the rest; the comment above it moves with it unchanged.
The post-`parse_args` pin-resolution chain stays in `main()`.

- [ ] **Step 4: Give the 5 scripts without a `main()` one**

`scripts/check_episode.py`, `scripts/extract.py`, `scripts/process_episode.py`,
`scripts/reframe.py`, `scripts/storyboard.py` build their parser directly under
`if __name__ == "__main__":`. Shown on `scripts/storyboard.py`:

```python
# before
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--grids", default="thirds,phi")
    a = ap.parse_args()
    spec = StoryboardSpec(n=a.n, grids=tuple(a.grids.split(",")))
    build(a.src, a.out, spec)
```

```python
# after
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--grids", default="thirds,phi")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    spec = StoryboardSpec(n=a.n, grids=tuple(a.grids.split(",")))
    build(a.src, a.out, spec)


if __name__ == "__main__":
    main()
```

The descriptions stay empty here — Task 2 fills them. This task is the move
only.

- [ ] **Step 5: Run the test and watch it pass**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q
```

Expected: **31 passed**.

- [ ] **Step 6: Add the emission check**

Append to `tests/test_cli_help.py`:

```python
@pytest.mark.parametrize("name", CLI)
def test_the_real_entry_point_routes_through_build_parser(name):
    """`--help` through `python -m` must emit what build_parser() declares.

    This is what catches a correct build_parser() that main() no longer calls —
    the walk above would still pass on a parser nothing runs."""
    mod = importlib.import_module(f"scripts.{name}")
    declared = mod.build_parser().description
    run = subprocess.run([sys.executable, "-m", f"scripts.{name}", "--help"],
                         capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, (
        f"python -m scripts.{name} --help exited {run.returncode}: {run.stderr.strip()}")
    if declared:
        assert " ".join(declared.split()) in " ".join(run.stdout.split()), (
            f"scripts/{name}.py declares a description in build_parser() that its "
            f"--help does not print — main() is not using build_parser()")
```

The `if declared:` guard is what lets this land in Task 1 while five
descriptions are still empty; Task 2 makes it unconditional.

- [ ] **Step 7: Run both and commit**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q
```

Expected: **62 passed** in roughly 8 s (the 31-module `--help` sweep measured
7.29 s).

```bash
.venv/bin/python -m pytest -q
```

Expected: the full suite green, **3656 passed, 1 skipped** or better.

```bash
git add scripts tests/test_cli_help.py
git commit -m "refactor(cli): every script exposes build_parser()

46 help surfaces become walkable objects instead of scrapeable text. A pure
move: the same parser, built by the same statements, returned instead of
consumed in place. The five scripts that built their parser directly under
__main__ gain a main() so every script has the same two-function shape.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: every surface states its purpose

**Files:**
- Modify: `scripts/check_episode.py`, `scripts/extract.py`, `scripts/reframe.py`,
  `scripts/storyboard.py`, `scripts/track.py` (the 5 with no description)
- Modify: `scripts/contact_sheet.py`, `scripts/draft.py`, `scripts/edit_plan.py`,
  `scripts/episode_qc.py`, `scripts/match_grade.py`, `scripts/montage.py`,
  `scripts/probe.py`, `scripts/reel_brief.py`, `scripts/reel_review.py`,
  `scripts/titles.py` (the 15 subcommands)
- Modify: `tests/test_cli_help.py`

**Why:** 5 of 31 top-level parsers print no purpose, and **0 of 15**
subcommands do — all fifteen pass `add_parser(help=…)`, which renders only in
the parent's listing, so `probe grade --help` states nothing about itself
(design §0.4).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_help.py`:

```python
@pytest.mark.parametrize("name", CLI)
def test_every_help_surface_states_a_purpose(name):
    """A subparser's own --help shows `description`, never `help`.

    `help=` renders in the PARENT's subcommand listing. Passing only `help=` —
    the state of all 15 subcommands before this slice — leaves the surface an
    agent reaches by drilling in completely blank (design §0.4)."""
    mod = importlib.import_module(f"scripts.{name}")
    blank = [label for label, parser in surfaces(mod.build_parser(), name)
             if not (parser.description or "").strip()]
    assert blank == [], (
        f"{blank} print no description on their own --help. A subcommand needs "
        f"description=, not only help=: help= renders in the parent's listing.")
```

and make the emission check unconditional by replacing `if declared:` with
`assert declared, f"scripts/{name}.py declares no description"` followed by the
existing containment assertion.

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q -k "states_a_purpose"
```

Expected: **15 failed** — one failure per file, since the test is
parametrized by script. The 5 with no top-level description
(`check_episode`, `extract`, `reframe`, `storyboard`, `track`) plus the 10
that own the 15 blank subcommands (`contact_sheet`, `draft`, `edit_plan`,
`episode_qc`, `match_grade`, `montage`, `probe`, `reel_brief`,
`reel_review`, `titles`).

- [ ] **Step 3: Fill the 5 missing top-level descriptions**

```python
# scripts/check_episode.py
    ap = argparse.ArgumentParser(
        description="judge one rendered episode mechanically — composition, path "
                    "quality, black frames, grade damage → report.json. Reads the "
                    "clip with its route.json and path.json; process_episode runs "
                    "it after every reframe attempt and the retry ladder reads the "
                    "verdict.")
```

```python
# scripts/extract.py
    ap = argparse.ArgumentParser(
        description="cut one EDL window out of a source clip into a standalone "
                    "segment, normalized to tv range — the pipeline's canonical "
                    "form. edl_to_reel runs it per episode before any tracking.")
```

```python
# scripts/reframe.py
    ap = argparse.ArgumentParser(
        description="compose one episode — crop a segment over its route into the "
                    "delivery canvas, applying layout, colour and any generated pan "
                    "→ the episode clip plus a path.meta.json sidecar. Driven by "
                    "process_episode; this is where every pixel of an episode is "
                    "decided.")
```

```python
# scripts/storyboard.py
    ap = argparse.ArgumentParser(
        description="render a grid-overlaid contact sheet of one clip for editorial "
                    "verification → one .jpg. process_episode writes one per "
                    "episode; the QC judge reads it beside the frame strip.")
```

```python
# scripts/track.py
    ap = argparse.ArgumentParser(
        description="track the episode's subject through a segment → route.json, "
                    "the per-frame subject box every later stage composes against. "
                    "Takes one hero pin in any of four spellings; process_episode "
                    "runs it before reframe.")
```

- [ ] **Step 4: Give all 15 subcommands a `description`**

Each keeps its existing `help=` (the parent's listing) and gains a
`description=` (its own `--help`).

```python
# scripts/contact_sheet.py
    b = sub.add_parser("build", help="one frame per FOOTAGE window -> sheets + SHEETS.md",
                       description="one frame per FOOTAGE.json window, tiled into sheets "
                                   "in timeline order → the sheets plus SHEETS.md. The "
                                   "required look-before-you-cut stage between intake "
                                   "and edit-plan.")
    s = sub.add_parser("strip", help="many frames inside ONE window -> one image",
                       description="many frames from inside ONE window — or any file and "
                                   "time range — tiled into a single image. Use it to "
                                   "look closer at a window the sheets flagged, or at a "
                                   "delivered clip.")
```

```python
# scripts/draft.py
    b = sub.add_parser("build", help="build draft.mp4 from an EDL.json + project.json",
                       description="concat the EDL's raw segments into draft.mp4 with "
                                   "processing-note labels and a rough music bed. A QA "
                                   "preview — nothing downstream consumes it.")
```

```python
# scripts/edit_plan.py
    b = sub.add_parser("build", help="build EDL.json + EDL.md from a selection",
                       description="project a selection.json over FOOTAGE.json's windows "
                                   "into EDL.json + EDL.md — the cut. Gates on the "
                                   "variety census, CONSTRAINTS.json and the length band "
                                   "before it writes anything.")
```

```python
# scripts/episode_qc.py
    p = sub.add_parser("pack", help="one evidence dir per episode (strip + storyboard + numbers)",
                       description="write one evidence directory per episode — a frame "
                                   "strip of the delivered clip, its storyboard, its "
                                   "mechanical report, a colour reading, and the clip's "
                                   "own digest. A judge subagent reads what this writes.")
    b = sub.add_parser("build", help="validate every judge's findings.json -> EPISODE_QC.json + .md",
                       description="validate every judge's findings.json into "
                                   "EPISODE_QC.json + .md, stamping each verdict with the "
                                   "clip digest read from disk. Refuses a verdict whose "
                                   "clip was re-rendered after it was packed.")
```

```python
# scripts/match_grade.py
    b = sub.add_parser("build", help="measure every episode → common target → author tone pairs",
                       description="measure every episode's tracked crop, compute one "
                                   "common reel tone target, and author tone_src/tone_dst "
                                   "on the episodes that deviate past --eps → a rewritten "
                                   "EDL.json plus MATCH.json and MATCH.md.")
```

```python
# scripts/montage.py
    st = sub.add_parser("status", help="report which conveyor stage is next in a run dir",
                        description="report which conveyor stage is next in a run "
                                    "directory, and how far the artifacts on disk already "
                                    "reach. Read-only — it inspects, it never runs a stage.")
    vf = sub.add_parser("verify", help="re-hash delivered reels against their attestations (CP3)",
                        description="re-hash every delivered reel against its attestation "
                                    "and report any that no longer match. Read-only — the "
                                    "CP3 check that a delivery is the file its report "
                                    "describes.")
```

```python
# scripts/probe.py
    g = sub.add_parser("grade", help="render+measure N frames of one episode over its frozen route",
                       description="render and measure N frames of one episode over its "
                                   "frozen route, through the same chain the real encode "
                                   "uses → probe.jpg + probe.json. Converges a colour "
                                   "grade without re-rendering the reel.")
    lk = sub.add_parser("look", help="re-check a delivered reel against its master",
                        description="re-check a delivered reel against its master for a "
                                    "declared vignette, bookend fade and title ink — the "
                                    "same gate deliver runs after its encode, runnable by "
                                    "hand.")
```

```python
# scripts/reel_brief.py
    b = sub.add_parser("build", help="build SPEC.json + SPEC.md from brief fields",
                       description="write SPEC.json + SPEC.md from the brief's fields — "
                                   "mood, hook, length, music intent, cast. Gates on mood, "
                                   "hook and length; refuses more than one reel.")
```

```python
# scripts/reel_review.py
    b = sub.add_parser("build", help="validate the reviewer's raw findings -> REVIEW.json + REVIEW.md",
                       description="validate the reviewer subagent's raw findings into "
                                   "REVIEW.json + REVIEW.md, stamping the reel's own "
                                   "digest read from disk. The CP3 editorial verdict.")
```

```python
# scripts/titles.py
    b = sub.add_parser("build", help="draft TITLES from SPEC + reel length",
                       description="draft TITLES.json + TITLES.md from SPEC and the reel's "
                                   "length — hook, mid text and ending, positioned inside "
                                   "the platform's safe zone.")
    c = sub.add_parser("check", help="refuse a TITLES.json whose text leaves the safe zone",
                       description="refuse a TITLES.json whose rendered ink leaves the "
                                   "platform's safe zone. Measures the text with real font "
                                   "metrics; deliver burns only what passes.")
```

The existing variable names in each file are whatever that file already uses —
keep them; only the `add_parser(...)` call gains the keyword.

- [ ] **Step 5: Run the test and watch it pass**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q
```

Expected: **93 passed**.

- [ ] **Step 6: See the defect gone with your own eyes**

```bash
.venv/bin/python -m scripts.probe grade --help
.venv/bin/python -m scripts.extract --help
```

Expected: each now prints a description paragraph under its usage block.
`probe grade` printed none before this step.

- [ ] **Step 7: Commit**

```bash
git add scripts tests/test_cli_help.py
git commit -m "feat(cli): every help surface states what it is for

5 of 31 top-level parsers printed no description, and 0 of 15 subcommands
did — all fifteen passed add_parser(help=), which renders only in the
parent's listing, so `probe grade --help` said nothing about itself.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: every argument states what it is

**Files:**
- Modify: 17 `scripts/*.py`
- Modify: `tests/test_cli_help.py`

**Why:** 56 of 210 arguments carry no `help`, and the deficit is concentrated
where the surface is thinnest — **20 of 27 positionals (74%)** against 36 of
183 flags (20%). A flag carries some meaning in its own name; a positional
renders as a bare word (design §0.4).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_help.py`:

```python
@pytest.mark.parametrize("name", CLI)
def test_every_argument_says_what_it_is(name):
    """Positionals first: they are 74% of the deficit and carry the least
    meaning in their own name. `--target-dur` says 'a target duration' before
    anything explains it; `src` says nothing at all (design §0.4)."""
    mod = importlib.import_module(f"scripts.{name}")
    blank = [f"{label}: {a.dest}"
             for label, parser in surfaces(mod.build_parser(), name)
             for a in arguments(parser) if not (a.help or "").strip()]
    assert blank == [], f"{blank} render with no help text under their surface's --help"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q -k "says_what_it_is"
```

Expected: **17 failed**, listing 56 arguments in total.

- [ ] **Step 3: Fill all 56**

```python
# scripts/assemble.py
    ap.add_argument("--width", type=int, required=True, help="master pixel width")
    ap.add_argument("--height", type=int, required=True, help="master pixel height")
    ap.add_argument("--fps", type=float, required=True,
                    help="master frame rate — every episode must already match it")
```

```python
# scripts/beats.py
    ap.add_argument("track", help="the audio file to analyse")
    g.add_argument("--start-offset", type=float, default=0.0,
                   help="in-point in the track, seconds (default 0)")
    ap.add_argument("--duration", type=float, default=None,
                    help="window length, seconds (default: the whole track)")
```

```python
# scripts/check_episode.py
    ap.add_argument("clip", help="the rendered episode .mp4 to judge")
    ap.add_argument("path", help="path.json — the per-frame crop rect reframe recorded")
    ap.add_argument("out", help="report.json output path")
    ap.add_argument("--composition", default="lead",
                    help="the rule the subject is judged against: lead | center | thirds")
    ap.add_argument("--grid", default="thirds", help="the guide grid: thirds | phi")
    ap.add_argument("--target-dur", type=float, required=True,
                    help="the length this episode was cut to, seconds")
    ap.add_argument("--attempt", type=int, default=1,
                    help="which retry attempt this is, 1-based — recorded in the report")
```

```python
# scripts/check_reel.py
    ap.add_argument("master", help="the assembled reel master to judge")
    ap.add_argument("--target-dur", type=float, required=True,
                    help="the reel's intended length, seconds")
    ap.add_argument("--report", required=True, help="ReelReport JSON output path")
```

```python
# scripts/color_measure.py
    ap.add_argument("clip", help="the clip to measure")
```

```python
# scripts/deliver.py
    ap.add_argument("master", help="the checked reel master to deliver")
    ap.add_argument("--out-dir", required=True,
                    help="deliveries dir — append-only, nothing ever deletes it")
    ap.add_argument("--changelog", default="",
                    help="one line recorded in the version log beside the delivery")
```

```python
# scripts/draft.py
    b.add_argument("--edl", required=True, help="EDL.json — the cut to preview")
```

```python
# scripts/extract.py
    ap.add_argument("src", help="source clip the EDL window refers to")
    ap.add_argument("out", help="segment .mp4 output path")
    ap.add_argument("--start", type=float, required=True,
                    help="window start in the source, seconds")
    ap.add_argument("--dur", type=float, required=True, help="window length, seconds")
```

```python
# scripts/intake.py
    ap.add_argument("footage_root", help="dir of raw clips to scan — never the run dir")
    ap.add_argument("out_dir", help="where FOOTAGE.json and FOOTAGE.md go")
    ap.add_argument("--sample-fps", type=float, default=SAMPLE_FPS,
                    help="analysis sampling rate, frames per second (default %(default)s)")
```

```python
# scripts/mix.py
    ap.add_argument("--out-dir", required=True, help="where the audio stem goes")
```

```python
# scripts/music_fetch.py
    ap.add_argument("--mode", required=True, choices=("free", "any"),
                    help="free = CC sources only | any = YouTube and friends, "
                         "copyrighted and the user's responsibility")
```

```python
# scripts/probe.py
    g.add_argument("--index", type=int, required=True, help="which episode, 0-based")
    g.add_argument("--frames", type=int, default=color.FRAMES,
                   help="how many frames to render and measure")
    lk.add_argument("master", help="the reel master the delivery was encoded from")
    lk.add_argument("delivered", help="the delivered reel to re-check")
    lk.add_argument("--vignette", type=float, default=0.0,
                    help="the vignette strength that was declared, 0..0.6")
    lk.add_argument("--fade", type=float, default=0.0,
                    help="the bookend fade that was declared, seconds per end")
    lk.add_argument("--titles", action="store_true",
                    help="also check that title ink reached the pixels")
```

```python
# scripts/project_init.py
    ap.add_argument("--notes", default="", help="free text recorded in project.json")
```

```python
# scripts/reel_brief.py
    b.add_argument("--notes", default="", help="free text recorded in SPEC.json")
```

```python
# scripts/reframe.py
    ap.add_argument("src", help="the segment to compose")
    ap.add_argument("route", nargs="?", default=None,
                    help="route.json from track — omit for a generated --pan")
    ap.add_argument("out", help="episode .mp4 output path")
    ap.add_argument("--composition", default="lead",
                    help="where the subject sits: lead | center | thirds")
    ap.add_argument("--grid", default="thirds", help="the guide grid: thirds | phi")
    ap.add_argument("--canvas", default="9:16", help="delivery aspect as W:H")
    ap.add_argument("--color", default="105,122,137",
                    help="grey-world white-balance reference as R,G,B")
    ap.add_argument("--crop-scale", type=float, default=1.0,
                    help="crop size as a fraction of the maximum, 0..1")
    ap.add_argument("--border-px", type=int, default=0,
                    help="insert only: border width in pixels")
    ap.add_argument("--border-color", default="white",
                    help="insert only: ffmpeg colour name or hex")
    ap.add_argument("--path-out", required=True,
                    help="path.json output path — the per-frame crop rect this render used")
```

```python
# scripts/storyboard.py
    ap.add_argument("src", help="the clip to sheet")
    ap.add_argument("out", help="sheet .jpg output path")
    ap.add_argument("--n", type=int, default=8, help="how many frames to sample")
    ap.add_argument("--grids", default="thirds,phi",
                    help="comma-separated overlays: thirds,phi")
```

```python
# scripts/track.py
    ap.add_argument("src", help="the segment to track through")
    ap.add_argument("out", help="route.json output path")
```

- [ ] **Step 4: Run and count**

```bash
.venv/bin/python -m pytest tests/test_cli_help.py -q
```

Expected: **124 passed**.

```bash
.venv/bin/python -m scripts.extract --help
```

Expected: every positional and every flag now carries a sentence — the `src` /
`out` pair that printed as two bare words in design §0.4 now says what each is.

- [ ] **Step 5: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -q
```

Expected: green, no golden moved (no argv, filter or pixel changed).

```bash
git add scripts tests/test_cli_help.py
git commit -m "feat(cli): every argument says what it is

56 of 210 arguments carried no help, 20 of 27 positionals among them. A
flag carries some meaning in its own name; a positional renders as a bare
word — `src`, `out`, `clip`, `route`, `master`.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: the index, the position sentence and the chain — generated

**Files:**
- Create: `scripts/lib/toolindex.py`
- Modify: `scripts/montage.py`
- Create: `references/tools.md`
- Create: `tests/test_tool_index.py`

**Why:** a hand-written index drifts, and the router's hand-written chain
**already has** — three of its fifteen names are not stage keys (design §0.6).

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_index.py`:

```python
"""The tool index is generated, and the committed copy is pinned to it.

A stale index is worse than no index: it reads as authority. The precedent is
tests/test_plugin_manifests.py, whose own comment records the cost — a
version-keyed install path let episode-qc stay missing for 316 commits.
"""
from pathlib import Path

from scripts.lib import toolindex

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references/tools.md"


def test_the_committed_index_matches_what_the_renderer_produces():
    assert INDEX.read_text() == toolindex.render_index(), (
        "references/tools.md is stale — regenerate it:\n"
        "    python -m scripts.montage tools > references/tools.md")


def test_every_help_surface_has_a_row():
    text = INDEX.read_text()
    for label in toolindex.surface_labels():
        assert f"`{label}`" in text, f"{label} is a help surface with no index row"


def test_the_index_lists_no_arguments():
    rows = [ln for ln in INDEX.read_text().splitlines() if ln.startswith("| `")]
    offenders = [ln for ln in rows if " --" in ln]
    assert offenders == [], (
        f"{len(offenders)} index rows name a flag. --help answers 'how'; the "
        f"index answers 'which'. Duplicating arguments is how an index lies.")


def test_the_script_to_stage_map_names_only_real_stages():
    """STAGES_OF_SCRIPT is hand-written — the one thing in this slice that is.

    A script's module name is not its stage key for four of them (`intake` is
    `footage-intake`, `beats` is `music-and-mood`, `draft` is
    `assemble-draft`) and `edl_to_reel` runs three stages. That mapping cannot
    be derived, so it is typed — and therefore pinned."""
    from scripts import montage
    real = {s.key for s in montage.V1_STAGES}
    named = {k for keys in toolindex.STAGES_OF_SCRIPT.values() for k in keys}
    assert named <= real, (
        f"{sorted(named - real)} are in STAGES_OF_SCRIPT but not in V1_STAGES")
    scripts = {p.stem for p in (ROOT / "scripts").glob("*.py")}
    assert set(toolindex.STAGES_OF_SCRIPT) <= scripts, (
        f"{sorted(set(toolindex.STAGES_OF_SCRIPT) - scripts)} are mapped to a "
        f"stage but are not scripts")


def test_every_built_stage_is_claimed_by_some_script():
    """A stage nobody runs would show as an index row that never appears."""
    from scripts import montage
    built = {s.key for s in montage.V1_STAGES if s.kind != "deferred"}
    claimed = {k for keys in toolindex.STAGES_OF_SCRIPT.values() for k in keys}
    assert built - claimed == set(), (
        f"{sorted(built - claimed)} are built stages that no script claims in "
        f"STAGES_OF_SCRIPT — either the map is stale or the stage has no runner")
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_tool_index.py -q
```

Expected: `ModuleNotFoundError: No module named 'scripts.lib.toolindex'`.

- [ ] **Step 3: Write the pure renderers**

Create `scripts/lib/toolindex.py`:

```python
"""Render the tool index, each skill's conveyor position, and the router's chain.

Pure — no I/O, no argv. Three readers: `montage tools`, tests/test_tool_index.py
and tests/test_skills_contract.py. The facts come from two places that already
exist: each script's own build_parser() and montage.V1_STAGES. Nothing here is
typed twice, which is the point — the router's hand-written chain had already
drifted from the registry it describes (design §0.6)."""
import argparse
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Skills that are not conveyor stages, and what they are instead (design §0.7).
#: The mapping is not 1:1 in either direction: 9 of 14 skills are stage keys,
#: 5 are not, and 7 stages have no same-named skill. Inventing a predecessor
#: for verify-runtime would be worse than omitting one.
STAGES_OF_SCRIPT: dict[str, tuple[str, ...]] = {
    # A script's module name is NOT its stage key: four of them differ, and one
    # script runs three stages. Measured — `intake` is the `footage-intake`
    # stage, `beats` is `music-and-mood`, `draft` is `assemble-draft`, and
    # `edl_to_reel` runs `episodes-geometry`, `episodes` and `deliver`. A
    # name.replace("_", "-") lookup silently reports "—" for all four.
    "project_init": ("project-init",),
    "intake": ("footage-intake",),
    "contact_sheet": ("contact-sheet",),
    "reel_brief": ("reel-brief",),
    "edit_plan": ("edit-plan",),
    "beats": ("music-and-mood",),
    "pacing": ("pacing",),
    "edl_to_reel": ("episodes-geometry", "episodes", "deliver"),
    "match_grade": ("match-grade",),
    "draft": ("assemble-draft",),
    "titles": ("titles",),
    "episode_qc": ("episode-qc",),
    "reel_review": ("reel-review",),
}

SKILL_ROLES: dict[str, str] = {
    "using-montage": "the router itself — it conducts every stage",
    "verify-runtime": "step 0, before every stage",
    "music-match": "serves the music-and-mood stage",
    "music-source": "serves the music-and-mood stage",
    "process-episode": "a per-episode worker under the episodes stage",
}


def cli_names() -> list[str]:
    return sorted(p.stem for p in (ROOT / "scripts").glob("*.py") if p.stem != "__init__")


def _surfaces(parser: argparse.ArgumentParser, name: str):
    yield name, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for key, sub in action.choices.items():
                yield f"{name} {key}", sub


def surface_labels() -> list[str]:
    out = []
    for name in cli_names():
        mod = importlib.import_module(f"scripts.{name}")
        out.extend(label for label, _ in _surfaces(mod.build_parser(), name))
    return out


def _one_line(text: str) -> str:
    """Collapse a wrapped description to one cell, and cut at the first full stop
    so a row is a row. The full text stays in --help, which is the point."""
    flat = " ".join((text or "").split())
    head = flat.split(". ", 1)[0]
    return head.rstrip(".") if head else ""


def render_index() -> str:
    from scripts import montage
    stage_of = {s.key: s for s in montage.V1_STAGES}
    lines = [
        "# Tool index",
        "",
        "**Generated — do not edit.** Regenerate with:",
        "",
        "    python -m scripts.montage tools > references/tools.md",
        "",
        "One row per `--help` surface. It answers *which tool*; `--help` answers",
        "*how do I run it*, and this file deliberately lists no arguments.",
        "",
        "| surface | stage | writes | purpose |",
        "|---|---|---|---|",
    ]
    for name in cli_names():
        mod = importlib.import_module(f"scripts.{name}")
        keys = STAGES_OF_SCRIPT.get(name, ())
        stage = ", ".join(f"`{k}`" for k in keys) or "—"
        writes = ", ".join(f"`{stage_of[k].artifact}`" for k in keys) or "—"
        for label, parser in _surfaces(mod.build_parser(), name):
            lines.append(f"| `{label}` | {stage} | {writes} | {_one_line(parser.description)} |")
    return "\n".join(lines) + "\n"


def position(stage_key: str) -> str:
    """The generated sentence a stage skill's description carries verbatim.

    Names the DECLARED order, not what a given run executes — an optional stage
    is skipped and only the router's chain shows which (design §2.5, §5)."""
    from scripts import montage
    live = [s.key for s in montage.V1_STAGES if s.kind != "deferred"]
    i = live.index(stage_key)
    if i == 0:
        return f"Conveyor position: first, before {live[1]}."
    if i == len(live) - 1:
        return f"Conveyor position: after {live[i - 1]}, last."
    return f"Conveyor position: after {live[i - 1]}, before {live[i + 1]}."


def chain() -> str:
    """The router's whole path. Brackets come from Stage.kind, never typed."""
    from scripts import montage
    parts = [s.key if s.kind == "required" else f"[{s.key}]"
             for s in montage.V1_STAGES if s.kind != "deferred"]
    return "Conveyor: " + " -> ".join(parts) + "."
```

- [ ] **Step 4: Add the `tools` subcommand**

In `scripts/montage.py`'s `build_parser()`, beside `status` and `verify`:

```python
    tl = sub.add_parser("tools", help="print the tool index (references/tools.md)",
                        description="print the generated tool index — one row per --help "
                                    "surface, naming which tool does what and which "
                                    "conveyor stage it belongs to. references/tools.md is "
                                    "this output, committed.")
```

`tl` takes no arguments. In `main()`, beside the existing dispatch:

```python
    if a.cmd == "tools":
        print(toolindex.render_index(), end="")
        return
```

with `from scripts.lib import toolindex` at the top, alongside the other
`scripts.lib` imports.

- [ ] **Step 5: Generate the index and run the tests**

```bash
.venv/bin/python -m scripts.montage tools > references/tools.md
.venv/bin/python -m pytest tests/test_tool_index.py -q
```

Expected: **5 passed**, and `references/tools.md` holds 46 data rows.

```bash
grep -c '^| `' references/tools.md
```

Expected: `46`.

- [ ] **Step 6: Prove the pin bites**

```bash
cp references/tools.md references/tools.md.bak
printf '| `bogus` | — | — | not a tool |\n' >> references/tools.md
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_tool_index.py::test_the_committed_index_matches_what_the_renderer_produces -q
```

Expected: **FAIL**, and the message names the regenerate command.

```bash
mv references/tools.md.bak references/tools.md
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_tool_index.py -q
```

Expected: **5 passed**. (`references/tools.md` is uncommitted at this point, so
the safe restore is the `.bak` copy made above — never `git checkout --`.)

- [ ] **Step 7: Commit**

```bash
.venv/bin/python -m pytest -q
git add scripts/lib/toolindex.py scripts/montage.py references/tools.md tests/test_tool_index.py
git commit -m "feat(montage): a generated tool index, and the order rendered from the registry

references/tools.md is 46 rows, one per --help surface, generated from each
script's own build_parser() plus montage.V1_STAGES and pinned byte-for-byte
by a test. It lists no arguments: --help answers how, the index answers
which, and duplicating the flags is how an index starts lying.

toolindex.position() and toolindex.chain() render what Task 5's skill
descriptions carry. Brackets come from Stage.kind rather than being typed,
because the router's hand-written chain had already drifted from the
registry it describes — three of its fifteen names are not stage keys.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: the skill descriptions — trigger, pointer, position

**Files:**
- Modify: all 14 `skills/*/SKILL.md` — the `description:` line only
- Modify: `tests/test_skills_contract.py`

**Why:** 6172 of the 14 descriptions' 7244 characters are detail that is
resident in every session whether any tool is reached or not. A pointer costs
32 characters; the index it names costs nothing until read (design §2.4/§2.6).

**Bodies are not touched.** Only the frontmatter `description:` line changes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skills_contract.py`:

```python
import re

from scripts.lib import toolindex

SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
POINTER = "Tool index: references/tools.md."


def _description(path: Path) -> str:
    m = re.search(r"^description:\s*(.+)$", path.read_text(), re.M)
    assert m, f"{path} has no description: line"
    return m.group(1)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_every_skill_points_at_the_tool_index(skill):
    """The one rung always in context. A tool an agent has not already thought
    of is unreachable from --help, which requires typing its name first."""
    assert POINTER in _description(skill), (
        f"{skill.parent.name}'s description does not carry {POINTER!r} — the "
        f"index is only reachable from a surface that survives a compaction")


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_every_skill_states_its_conveyor_place(skill):
    """A stage skill carries its generated position; a non-stage skill says
    what it is instead. Inventing a predecessor for verify-runtime would be
    worse than omitting one (design §0.7)."""
    name, desc = skill.parent.name, _description(skill)
    if name in toolindex.SKILL_ROLES:
        role = toolindex.SKILL_ROLES[name]
        # Case-insensitive: a role that opens a sentence is capitalised there
        # ("Serves the music-and-mood stage.") and lowercase in the table.
        assert role.lower() in desc.lower(), (
            f"{name} is not a conveyor stage; its description must say what it "
            f"is instead: {role!r}")
    else:
        assert toolindex.position(name) in desc, (
            f"{name}'s description does not carry its generated position "
            f"sentence verbatim: {toolindex.position(name)!r}")


def test_the_router_carries_the_generated_chain():
    desc = _description(ROOT / "skills/using-montage/SKILL.md")
    assert toolindex.chain() in desc, (
        f"using-montage's description does not carry the chain rendered from "
        f"V1_STAGES: {toolindex.chain()!r}")
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_skills_contract.py -q -k "index or conveyor or chain"
```

Expected: **29 failed** — 14 pointer, 14 position, 1 chain.

- [ ] **Step 3: Rewrite all 14 `description:` lines**

Each replaces the whole `description:` line. Nothing else in the file moves.

```
# skills/project-init/SKILL.md
description: Start here — the montage's first step: learn what the video is for and set its aspect and delivery quality, writing project.json. Every episode inherits canvas and delivery unless it overrides. Required — nothing runs before it. Conveyor position: first, before footage-intake. Tool index: references/tools.md.
```

```
# skills/footage-intake/SKILL.md
description: Conveyor stage — scan a folder of raw clips into scored moment-windows (FOOTAGE.json/.md) and, when people matter, name the heroes into cast.json. Needs project.json. Required — feeds edit-plan. Conveyor position: after project-init, before contact-sheet. Tool index: references/tools.md.
```

```
# skills/reel-brief/SKILL.md
description: Conveyor stage — the editorial brief: interrogate the idea one question at a time and write SPEC.md + SPEC.json (mood, hook, length, music intent, cast). Approved by the user at CP1. Optional — the autonomous path skips it. Conveyor position: after contact-sheet, before edit-plan. Tool index: references/tools.md.
```

```
# skills/edit-plan/SKILL.md
description: Conveyor stage — author the cut: turn FOOTAGE.json's scored windows into EDL.json + EDL.md, the map edl_to_reel drives to a reel. Needs FOOTAGE.json and project.json. Required — its output drives the whole conveyor. Conveyor position: after reel-brief, before music-and-mood. Tool index: references/tools.md.
```

```
# skills/music-match/SKILL.md
description: Pick the reel's track from a LOCAL folder of candidates by mood-fit, ranked into MUSIC_SHORTLIST.md for the user to choose from. Serves the music-and-mood stage. Optional — skip when a track is already chosen; see music-source for the network lanes. Tool index: references/tools.md.
```

```
# skills/music-source/SKILL.md
description: Source the reel's track from the internet by mood: discover candidates (free = CC; any = YouTube and friends, copyrighted and the user's responsibility), rank, download, and write MUSIC.json. Serves the music-and-mood stage. Optional — see music-match for a local folder. Tool index: references/tools.md.
```

```
# skills/pacing/SKILL.md
description: Conveyor stage — fit the cuts edit-plan already chose onto the music's beat grid (PACING.json/.md); re-run edit-plan build --pacing to apply. The footage owns each cut's length; pacing only picks which musical lines they land on. Optional — a music-less reel skips it. Conveyor position: after music-and-mood, before episodes-geometry. Tool index: references/tools.md.
```

```
# skills/match-grade/SKILL.md
description: Conveyor stage — the match-grade conductor: measure every episode's tracked crop, compute one common reel tone target, and author tone_src/tone_dst on the episodes that deviate. Required. Conveyor position: after episodes-geometry, before assemble-draft. Tool index: references/tools.md.
```

```
# skills/titles/SKILL.md
description: Conveyor stage — the reel's on-screen text: turn hook, text and ending into a timed, positioned titles track (TITLES.json/.md) that deliver burns into its one encode. Optional — the autonomous path skips it. Conveyor position: after assemble-draft, before episodes. Tool index: references/tools.md.
```

```
# skills/episode-qc/SKILL.md
description: Conveyor stage — the per-episode quality gate between rendering and delivery: pack an evidence directory per episode, dispatch one judge subagent each, and validate their findings into EPISODE_QC.json. Required; no waiver. Conveyor position: after episodes, before deliver. Tool index: references/tools.md.
```

```
# skills/reel-review/SKILL.md
description: Conveyor stage — the reel's final editorial review at CP3: a fresh reviewer subagent judges the delivered reel against SPEC, findings validated into REVIEW.json + REVIEW.md and routed to the stage that owns each fix. Human-gated. Required. Conveyor position: after deliver, last. Tool index: references/tools.md.
```

```
# skills/process-episode/SKILL.md
description: Per-episode worker — turn one approved EDL episode manifest into a checked, reframed clip at its chosen canvas and delivery (track -> reframe -> storyboard -> postcheck). Driven by edl_to_reel, one subagent per episode; not invoked directly. A per-episode worker under the episodes stage. Tool index: references/tools.md.
```

```
# skills/verify-runtime/SKILL.md
description: Preflight — verify the video-grid runtime is fully installed and print the exact command to fix any gap: deps, ffmpeg, drawtext and vidstab filters, font, YOLO weights, demucs. Read-only, never installs. Required — step 0, before every stage. Tool index: references/tools.md.
```

```
# skills/using-montage/SKILL.md
description: Router — the montage conveyor's front door: a folder of raw footage plus a natural-language brief ("a 9:16 reel from this trip, no music") becomes a delivered reel. Use when the user wants a reel from footage — the router itself — it conducts every stage in order, stops at the three checkpoints, resumes a half-finished run, and names any stage it skips. Required — the entry point. Conveyor: project-init -> footage-intake -> contact-sheet -> [reel-brief] -> edit-plan -> [music-and-mood] -> [pacing] -> episodes-geometry -> match-grade -> [assemble-draft] -> [titles] -> episodes -> episode-qc -> deliver -> reel-review. Tool index: references/tools.md.
```

- [ ] **Step 4: Run the test and watch it pass**

```bash
.venv/bin/python -m pytest tests/test_skills_contract.py -q
```

Expected: green, 29 new assertions among them.

If the chain assertion fails, print what the renderer wants and paste it
verbatim — never hand-edit the chain:

```bash
.venv/bin/python -c "from scripts.lib import toolindex; print(toolindex.chain())"
```

- [ ] **Step 5: Measure the saving**

```bash
.venv/bin/python - <<'EOF'
import re, pathlib
tot = 0
for p in sorted(pathlib.Path("skills").glob("*/SKILL.md")):
    tot += len(re.search(r"^description:\s*(.+)$", p.read_text(), re.M).group(1))
print(f"{tot} chars (~{tot // 4} tokens) — was 7244 (~1811)")
EOF
```

Expected: **4569 chars, ~1142 tokens — −37%**, about 668 tokens freed in every
session. (The design projected −29% against a 350-character target; the
finished set averages 302 excluding the router, so the real figure beats it.)

- [ ] **Step 6: Commit**

```bash
git add skills tests/test_skills_contract.py
git commit -m "feat(skills): descriptions carry a trigger, a pointer and a place

6172 of the 14 descriptions' 7244 characters were detail resident in every
session whether any tool was reached or not — episode-qc alone spent 989 on
digest stamping, a concurrency cap and five named axes, none of which helps
decide whether to invoke it. Now each carries what triggers, one pointer at
the index, and its conveyor position rendered from V1_STAGES and pinned.

7244 -> 4569 characters, ~1811 -> ~1142 tokens: -37%, about 668 tokens
freed in every session. Bodies untouched.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: the mutation battery, the standard, and the docs

**Files:**
- Modify: `docs/coding-standards.md`
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`,
  `docs/pipeline-map.md`

- [ ] **Step 1: Run the mutation battery**

Every row runs under `PYTHONDONTWRITEBYTECODE=1` (Global Constraint 4). For
each: apply the mutation, run the named selection, expect **FAIL**, restore.
Restore a committed file with `git show HEAD:<path> > <path>`; for the
uncommitted `references/tools.md` use the `.bak` copy pattern from Task 4.

| # | mutation | selection | expect |
|---|---|---|---|
| 1 | delete `build_parser` from `scripts/mix.py`, inlining it back into `main()` | `tests/test_cli_help.py::test_every_script_exposes_build_parser` | FAIL |
| 2 | keep `build_parser()` in `scripts/mix.py` but make `main()` build its own parser with a different description | `tests/test_cli_help.py::test_the_real_entry_point_routes_through_build_parser` | FAIL |
| 3 | drop `description=` from `scripts/extract.py` | `tests/test_cli_help.py::test_every_help_surface_states_a_purpose` | FAIL |
| 4 | drop `description=` from `probe`'s `grade` subparser, keeping `help=` | `tests/test_cli_help.py::test_every_help_surface_states_a_purpose` | FAIL |
| 5 | drop `help=` from `reframe`'s `src` positional | `tests/test_cli_help.py::test_every_argument_says_what_it_is` | FAIL |
| 6 | drop `help=` from `deliver`'s `--changelog` flag | `tests/test_cli_help.py::test_every_argument_says_what_it_is` | FAIL |
| 7 | set `scripts/track.py`'s description to `"   "` (whitespace) | `tests/test_cli_help.py::test_every_help_surface_states_a_purpose` | FAIL |
| 8 | append a bogus row to `references/tools.md` | `tests/test_tool_index.py::test_the_committed_index_matches_what_the_renderer_produces` | FAIL |
| 9 | add a `--flag` mention into one index row | `tests/test_tool_index.py::test_the_index_lists_no_arguments` | FAIL |
| 9b | point `STAGES_OF_SCRIPT["intake"]` at `("intake",)` — the naive `name.replace("_","-")` answer | `tests/test_tool_index.py::test_the_script_to_stage_map_names_only_real_stages` | FAIL |
| 9c | delete the `"beats"` row from `STAGES_OF_SCRIPT` | `tests/test_tool_index.py::test_every_built_stage_is_claimed_by_some_script` | FAIL |
| 10 | reorder two entries in `montage.V1_STAGES` | `tests/test_skills_contract.py::test_every_skill_states_its_conveyor_place` | FAIL |
| 11 | flip one `Stage.kind` from `required` to `optional` | `tests/test_skills_contract.py::test_the_router_carries_the_generated_chain` | FAIL |
| 12 | delete the pointer from `skills/titles/SKILL.md`'s description | `tests/test_skills_contract.py::test_every_skill_points_at_the_tool_index` | FAIL |
| 13 | give `verify-runtime` a fabricated `Conveyor position:` sentence and remove its role phrase | `tests/test_skills_contract.py::test_every_skill_states_its_conveyor_place` | FAIL |
| 14 | rename `toolindex.position`'s "first" branch to emit `after —` | `tests/test_skills_contract.py::test_every_skill_states_its_conveyor_place` | FAIL |

**Rows 9, 13 and 14 are flagged uncertain** and may come back GREEN:

- Row 9 depends on the generated rows never containing ` --` naturally. If a
  description legitimately names a flag, the row is vacuous — and the finding
  is then that the check cannot fire, which must be **reported, not papered
  over**. Either tighten the description or delete the test with the reason
  recorded.
- Row 13 discriminates on the **role** half, not the position half: the test
  branches on `name in SKILL_ROLES` first and never calls `position()` for a
  non-stage skill. So the mutation must remove the role phrase — adding a
  fabricated `Conveyor position:` sentence alone changes nothing and the row
  would come back GREEN for the wrong reason. Confirm which half fired by
  reading the assertion message, not by assuming.
- Row 14 fails only if `project-init`'s description is compared against the
  mutated renderer. Confirm the selection actually reaches `project-init`.

Any row that comes back GREEN is a coverage hole: close it with a NEW test
that discriminates, and record which row found it.

- [ ] **Step 2: Write the prose standard**

Add to `docs/coding-standards.md`, under the CLI section (create one if absent):

```markdown
## CLI help

Every `argparse` parser and subparser carries a `description`, and every
argument carries a `help`. Both are machine-checked by
`tests/test_cli_help.py`, and a subparser needs `description=` in addition
to `help=` — `help=` renders only in the parent's subcommand listing.

A description states **what the tool reads, what it writes, and when to run
it**. The arguments already carry the input formats, so the description
carries the purpose and the moment. This half is **not** machine-checked:
no honest predicate separates a description that merely also cites a design
section from one that substitutes the citation for a statement (design
2026-09-12 §3.7). It is a review item.

`references/tools.md` is generated — never hand-edit it. Regenerate with
`python -m scripts.montage tools > references/tools.md`.
```

- [ ] **Step 3: Bump to 0.9.2**

`.claude-plugin/plugin.json`: `"version": "0.9.2"`.

`CHANGELOG.md`, new top entry:

```markdown
## 0.9.2 — a tool's purpose is re-derivable

PATCH: no behaviour changes, no argv changes, no pixel moves. What changes
is what the product can tell its own operator.

- Every `scripts/*.py` exposes `build_parser()`; 46 help surfaces are now
  walkable objects rather than scrapeable text.
- 5 top-level parsers and **all 15 subcommands** gained a description.
  `probe grade --help` printed nothing about itself before this.
- 56 of 210 arguments gained `help` — 20 of 27 positionals among them.
- `references/tools.md`: a generated 46-row index, printed by
  `montage tools` and pinned byte-for-byte by a test.
- All 14 skill descriptions rewritten to trigger plus pointer plus a
  conveyor position rendered from `V1_STAGES`: 7244 → 4569 characters,
  **−37%**, about 668 tokens freed in every session.
- Closes backlog R4.1, R4.2 and R4.3.
```

- [ ] **Step 4: Close the three rows and file the four new ones**

In `docs/backlog.md`, move R4.1, R4.2 and R4.3 to `docs/backlog-closed.md`
with closure notes. R4.2's note must record what the measurement found:

> **Closed 2026-09-12 by "Re-derivable purpose", and its stated cause was not
> the cause.** Both examples were named in the skills *before* the run —
> `CONSTRAINTS` 12 days early (`be86b75`), `scripts.probe` 3 days early
> (`a820c55`) — so naming was never the binding constraint. `probe`'s real
> cause is in the retro's own text three sections above this row: its CLI
> required `--episodes EPISODES.json`, which only exists after every episode is
> encoded, while the operator wanted colour *before* the render; that
> precondition was removed in 0.6.0 by `probe grade --geometry`. What shipped
> instead is the instrument the row's diagnosis missed — an index on the one
> rung that survives a compaction.

Add the four deferred rows from design §6:

| priority | row |
|---|---|
| P2, M | the two biggest skill bodies load whole (43 KB + 41 KB, no reference subfiles) and are lost to compaction — progressive disclosure is its own slice |
| P3, S | `Stage.runner` names a tool and nothing checks the tool exists; `trend-scan`'s runner is the literal `"5.4 - not built"`, so any check needs a deferred exemption |
| P3, S | ten CLI descriptions substitute a repo-internal pointer (`stage 5.2b`, `§5.13 Slice B`) for a statement; no honest machine predicate separates them, so it is a prose pass |
| P3, S | the index as its own skill, reachable by name with no path — costs a fifteenth row in the always-resident listing and gives the content a second home |
| P3, M | the index answers *which tool*, never *is this the moment* — that judgement stays in the perishable body |

- [ ] **Step 5: Sync the registry and the status**

`CLAUDE.md` Quick Reference gains two rows (design and plan), in the same
format as the rest.

`docs/build-status.md` gains a Done entry naming the two overturned premises
(§0.1's lead times and §0.6's already-drifted chain) and the measured −37%.

`docs/pipeline-map.md`: no stage changed, so this file changes only if it
names the skill descriptions. Check with
`grep -n "description" docs/pipeline-map.md` and leave it alone if it does not.

- [ ] **Step 6: Full suite and commit**

```bash
.venv/bin/python -m pytest -q
```

Expected: green, at least 3656 + the new tests.

```bash
git add -A
git commit -m "docs: 0.9.2 — a tool's purpose is re-derivable

Closes R4.1, R4.2 and R4.3. R4.2's stated cause was not the cause: both of
its examples were named in the skills before the run, and probe's real
blocker — a CLI that required a completed render — was removed in 0.6.0.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** §2.1 → Task 2. §2.2 → Task 3. §2.3 → Task 6 Step 2 (prose
standard, deliberately unenforced). §2.4 → Task 4 + Task 5. §2.5 → Task 4's
`position`/`chain` + Task 5. §2.6's measurement → Task 5 Step 5. §3.1 → Task 1.
§3.2 → Tasks 1–3. §3.3 → Task 4. §3.4/§3.5 → Task 5's three tests. §3.6 → the
`cli_names()` / `SKILLS` glob in both test files. §3.7 → nothing is built, and
Task 6 Step 2 records why. §6's five rows → Task 6 Step 4.

**Placeholder scan.** Every description and every `help` string is written out
in full — 20 descriptions in Task 2, 56 arguments in Task 3, 14 skill
descriptions in Task 5. `toolindex.py` is complete. The one place the plan says
"replace that body" is Task 4 Step 1, where the first sketch of
`test_the_index_lists_no_arguments` is immediately followed by the concrete
form to use; the implementer writes the second, not the first.

**Type consistency.** `build_parser() -> argparse.ArgumentParser` everywhere.
`surfaces()`/`arguments()` in `tests/test_cli_help.py` and `_surfaces()` in
`toolindex.py` are deliberately separate copies of the same four lines: the
test must not import the module it is checking the output of, or a bug in the
walk would hide itself on both sides — the same reasoning the grade-sensor
slice recorded for `grade_faithful`'s shared prediction path (design §9.4 of
2026-08-31).

**Five defects this self-review found in its own first draft**, recorded
because the last slice's every Critical finding originated in the plan and not
in the implementers' work:

1. `render_index` looked a stage up by `name.replace("_", "-")`. **Measured
   wrong for four scripts** — `intake` is the `footage-intake` stage, `beats` is
   `music-and-mood`, `draft` is `assemble-draft`, and `edl_to_reel` runs three
   stages — and the failure is silent: those rows would simply print `—`.
   Replaced by the explicit `STAGES_OF_SCRIPT`, which is then pinned (below).
2. The role assertion compared case-sensitively against descriptions that open
   a sentence with the role ("Serves the music-and-mood stage."), so three of
   the five non-stage skills would have failed on capitalisation alone.
3. Task 4 Step 1 carried a sketch of `test_the_index_lists_no_arguments`
   followed by "replace that body" — a placeholder by the writing-plans
   definition. The sketch is deleted; only the form to write remains.
4. Task 2 Step 2 predicted 10 failures where the test is parametrized by
   script and produces 15.
5. Battery row 13's uncertainty note claimed `position()` would raise for
   `verify-runtime`. It never runs: the test branches on `SKILL_ROLES` first.
   The row discriminates on the role half, and the note now says so — a row
   that passes for a reason the plan did not predict is the shape the last
   slice's three GREEN rows all had.

**Three weak points, named rather than hidden.**

1. **Task 1 touches 31 files in one commit.** It is mechanical and Global
   Constraint 6 makes the diff checkable line by line, but a reviewer should
   read it as 31 small diffs and confirm no argument moved, changed type or
   changed default. The suite is the backstop: any behaviour change breaks an
   existing integration test.
2. **`STAGES_OF_SCRIPT` is the one hand-written fact in a slice about not
   hand-writing facts.** It cannot be derived — a script's module name is not
   its stage key, and one script runs three stages — so it is typed, and then
   pinned from both sides: every value must be a real `V1_STAGES` key, and
   every built stage must be claimed by some script. Rows 9b and 9c of the
   battery exist to prove both halves bite.
3. **Battery rows 9, 13 and 14 are flagged uncertain, and the flag is the
   point.** The last slice's three unanticipated GREEN rows all had one shape —
   a fixture where two values coincide — and were only found by running them.
   Do not assume any of the fourteen discriminates; run each and record the
   result.
