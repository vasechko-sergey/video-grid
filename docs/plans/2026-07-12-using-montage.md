# using-montage router (stage 5.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the montage conveyor's front door — a `using-montage` SKILL that conducts the built stages footage→reel with the three §4.1 user checkpoints, backed by a thin deterministic `montage.py` stage-status inspector so resume-for-free is testable.

**Architecture:** `scripts/montage.py` is an **inspector, not a runner** — a typed `Stage` table (`V1_STAGES`) + `next_action(run_dir)` that reports each stage's state (done/next/pending/optional/skip) from artifact presence, plus a `status` CLI. The judgment steps (cast-naming, selection authoring) are agent-interactive, so `SKILLS/using-montage/SKILL.md` runs the stages (invoking sub-skills, sub-processing CLIs) and consults the inspector for the resume/next decision. Mirrors `intake.py` ↔ `footage-intake`: mechanical code, judgment in the SKILL. No stage is re-implemented; the router is purely additive.

**Tech Stack:** Python 3.13, `dataclasses`, `pathlib`, `argparse`, pytest (`pythonpath = .`, run as modules via `.venv/bin/python -m pytest`). No ffmpeg, no network in the new code.

**Spec:** [docs/specs/2026-07-12-using-montage-design.md](../specs/2026-07-12-using-montage-design.md).

---

## File Structure

- **Create `scripts/montage.py`** — the inspector: `Stage` config-spec, `V1_STAGES` ordered table, `_exists` helper, `next_action(run_dir, out_dir=None)`, `main()` (`status` subcommand). One responsibility: report where a run stands. Pure/deterministic.
- **Create `tests/lib/test_montage.py`** — unit tests (repo puts script unit-tests under `tests/lib/`, e.g. `test_edit_plan.py` for `scripts/edit_plan.py`). Covers `Stage` validation, the `V1_STAGES` shape, the `next_action` state matrix, and the `status` CLI.
- **Create `SKILLS/using-montage/SKILL.md`** — the conductor. No test (a skill doc, like `SKILLS/edit-plan/SKILL.md`).
- **Modify `docs/pipeline-map.md`** — 5.1 `◐ → ✅` (entry-skill done; parallel fan-out remains the one open 5.1 sub-item), tally + critical-path diagram.
- **Modify `docs/build-status.md`** — add a "using-montage router (5.1) DONE" entry; narrow the "router" next-action bullet to "cap-3 parallel fan-out" only.
- **Modify `CLAUDE.md`** — Quick Reference rows for this design + plan.
- **Modify `docs/specs/2026-07-05-montage-skillset-design.md`** — a `> Built (2026-07-12)` note under §5.1.

Reused unchanged (no edits): `scripts/{project_init,intake,beats,edit_plan,edl_to_reel}.py`, `build_reel`, `deliver`, and the four existing sub-skills.

---

## Task 0: `Stage` config-spec + `V1_STAGES` table

**Files:**
- Create: `scripts/montage.py`
- Test: `tests/lib/test_montage.py`

The frozen dataclass that describes one conveyor stage (validate-and-raise in `__post_init__`, per the fail-loud contract), plus the ordered v1 table as data.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_montage.py`:

```python
import json
import sys

import pytest

from scripts import montage
from scripts.montage import Stage, V1_STAGES, next_action


def _touch(d, name):
    (d / name).write_text("{}")


# ---- Stage config-spec ----

def test_stage_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        Stage("x", "x.json", "bogus", "runs it", None)


def test_stage_rejects_bad_checkpoint():
    with pytest.raises(ValueError, match="checkpoint"):
        Stage("x", "x.json", "required", "runs it", "bogus")


def test_stage_accepts_good():
    s = Stage("x", "x.json", "required", "runs it", "spec")
    assert s.kind == "required" and s.checkpoint == "spec" and s.in_out is False


# ---- V1_STAGES table ----

def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "reel-brief", "trend-scan",
        "music-and-mood", "pacing", "edit-plan", "deliver"]


def test_v1_stages_kinds_and_flags():
    by = {s.key: s for s in V1_STAGES}
    assert [s.key for s in V1_STAGES if s.kind == "deferred"] == [
        "reel-brief", "trend-scan", "pacing"]
    assert by["music-and-mood"].kind == "optional"
    assert by["deliver"].in_out is True and by["deliver"].artifact == "REEL_v*.*"
    assert by["project-init"].checkpoint == "spec"
    assert by["edit-plan"].checkpoint == "edl"
    assert by["deliver"].checkpoint == "final"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.montage'` (EXIT: non-zero). (Do NOT pipe through `tail` — it masks the exit code.)

- [ ] **Step 3: Write minimal implementation**

Create `scripts/montage.py`:

```python
"""Stage 5.1 router backbone (design docs/specs/2026-07-12-using-montage-design.md):
a deterministic stage-status INSPECTOR for the montage conveyor. It reports where a
(possibly resumed) run stands and which stage is next; it does NOT run stages — the
front-half judgment steps (footage-intake cast-naming, edit-plan selection authoring)
are agent-interactive, so the using-montage SKILL runs the stages and consults
next_action() for the resume/next decision. Mirrors intake.py <-> footage-intake:
mechanical inspection here, judgment in the SKILL."""
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

_KINDS = ("required", "optional", "deferred")
_CHECKPOINTS = (None, "spec", "edl", "final")


@dataclass(frozen=True)
class Stage:
    """One v1-conveyor stage the router sequences. `artifact` is a glob (under the
    run dir, or the out dir when `in_out`) whose presence marks the stage done — the
    resume-for-free marker (design line 510)."""
    key: str
    artifact: str
    kind: str
    runner: str
    checkpoint: str | None
    in_out: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"Stage.kind must be one of {_KINDS}, got {self.kind!r}")
        if self.checkpoint not in _CHECKPOINTS:
            raise ValueError(
                f"Stage.checkpoint must be one of {_CHECKPOINTS}, got {self.checkpoint!r}")


V1_STAGES: tuple[Stage, ...] = (
    Stage("project-init", "project.json", "required",
          "project-init SKILL -> project_init CLI", "spec"),
    Stage("footage-intake", "FOOTAGE.json", "required",
          "footage-intake SKILL -> intake CLI", None),
    Stage("reel-brief", "SPEC.md", "deferred", "5.3 - not built", None),
    Stage("trend-scan", "TRENDS.md", "deferred", "5.4 - not built", None),
    Stage("music-and-mood", "MUSIC.json", "optional",
          "beats CLI (absent -> silent reel)", None),
    Stage("pacing", "PACING.md", "deferred", "5.6 - not built", None),
    Stage("edit-plan", "EDL.json", "required",
          "edit-plan SKILL -> edit_plan build CLI", "edl"),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel CLI", "final", in_out=True),
)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: 6 passed, EXIT: 0. (The `next_action`/CLI tests come in later tasks; only the Task-0 tests exist so far.)

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: montage.py Stage config-spec + V1_STAGES table (router 5.1)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 1: `next_action` — the stage-status inspector

**Files:**
- Modify: `scripts/montage.py`
- Test: `tests/lib/test_montage.py`

Walk `V1_STAGES` over a run dir, mark each stage's state from artifact presence, return the ordered report + `next` + `delivered`. Per-artifact `done` (honest about a broken resume); optional never blocks; deferred always skips.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_montage.py`:

```python
def _state(res, key):
    return next(s["state"] for s in res["stages"] if s["key"] == key)


def test_empty_run_next_is_project_init(tmp_path):
    res = next_action(str(tmp_path))
    assert res["next"] == "project-init"
    assert res["delivered"] is False
    assert _state(res, "project-init") == "next"
    assert _state(res, "footage-intake") == "pending"


def test_deferred_stages_always_skip(tmp_path):
    res = next_action(str(tmp_path))
    for k in ("reel-brief", "trend-scan", "pacing"):
        assert _state(res, k) == "skip"


def test_project_only_next_is_footage(tmp_path):
    _touch(tmp_path, "project.json")
    res = next_action(str(tmp_path))
    assert res["next"] == "footage-intake"
    assert _state(res, "project-init") == "done"


def test_music_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    res = next_action(str(tmp_path))
    assert res["next"] == "edit-plan"
    assert _state(res, "music-and-mood") == "optional"   # absent optional never blocks
    _touch(tmp_path, "MUSIC.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "music-and-mood") == "done"
    assert res2["next"] == "edit-plan"


def test_edl_present_next_is_deliver(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert res["next"] == "deliver"
    assert res["delivered"] is False


def test_delivered_when_reel_in_out(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    out = tmp_path / "out"
    out.mkdir()
    (out / "REEL_v1.mp4").write_text("x")
    res = next_action(str(tmp_path))
    assert res["next"] is None
    assert res["delivered"] is True
    assert _state(res, "deliver") == "done"


def test_broken_resume_surfaces_honestly(tmp_path):
    # EDL present but FOOTAGE missing -> footage-intake is next, edit-plan still 'done'
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "EDL.json")
    res = next_action(str(tmp_path))
    assert res["next"] == "footage-intake"
    assert _state(res, "edit-plan") == "done"
    assert _state(res, "deliver") == "pending"


def test_out_dir_override(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    alt = tmp_path / "delivery"
    alt.mkdir()
    (alt / "REEL_v2.mkv").write_text("x")   # glob matches any container/version
    res = next_action(str(tmp_path), str(alt))
    assert res["delivered"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -k "next_action or empty or deferred or project_only or music or edl_present or delivered or broken or out_dir" -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError`/`TypeError` on `next_action` (defined but empty) or the assertions fail. EXIT: non-zero.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/montage.py` (after `V1_STAGES`):

```python
def _exists(base: Path, glob: str) -> bool:
    """True iff at least one file matches `glob` under `base` (empty glob -> False)."""
    if not glob:
        return False
    return any(base.glob(glob))


def next_action(run_dir: str, out_dir: str | None = None) -> dict:
    """Inspect a run dir -> the ordered v1 stages with each stage's state, the next
    required action, and whether the reel is delivered. out_dir defaults to
    <run_dir>/out (where deliver versions REEL_v{n}). State per stage:
      done     - artifact exists (resume-for-free, design line 510)
      next     - the FIRST required stage whose artifact is missing (run this)
      pending  - a required stage after `next` still missing its artifact
      optional - an optional built stage not yet produced (music); never blocks
      skip     - a deferred stage (reel-brief/trend-scan/pacing); named, not silent
    Returns {"stages":[{key,artifact,kind,state,checkpoint,runner}, ...] in order,
             "next": <stage key | None>, "delivered": <bool>}."""
    run = Path(run_dir)
    out = Path(out_dir) if out_dir is not None else run / "out"
    stages: list[dict] = []
    next_key: str | None = None
    delivered = False
    for st in V1_STAGES:
        base = out if st.in_out else run
        done = _exists(base, st.artifact)
        if st.kind == "deferred":
            state = "skip"
        elif st.kind == "optional":
            state = "done" if done else "optional"
        elif done:
            state = "done"
        elif next_key is None:
            state = "next"
            next_key = st.key
        else:
            state = "pending"
        if st.key == "deliver":
            delivered = done
        stages.append({"key": st.key, "artifact": st.artifact, "kind": st.kind,
                       "state": state, "checkpoint": st.checkpoint, "runner": st.runner})
    return {"stages": stages, "next": next_key, "delivered": delivered}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: 14 passed, EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: montage.next_action stage-status inspector (router 5.1)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `status` CLI

**Files:**
- Modify: `scripts/montage.py`
- Test: `tests/lib/test_montage.py`

A `status` subcommand that prints `next_action(...)` as JSON and exits 0 — a status query, not a gate. Tested by monkeypatching `sys.argv` and calling `main()` (the repo's CLI-test pattern, see `tests/lib/test_project.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_montage.py`:

```python
def test_status_cli_prints_json_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["montage", "status", "--run-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        montage.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next"] == "project-init"
    assert payload["delivered"] is False


def test_status_cli_out_dir_override(tmp_path, monkeypatch, capsys):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    alt = tmp_path / "delivery"
    alt.mkdir()
    (alt / "REEL_v1.mp4").write_text("x")
    monkeypatch.setattr(sys, "argv",
                        ["montage", "status", "--run-dir", str(tmp_path),
                         "--out-dir", str(alt)])
    with pytest.raises(SystemExit) as e:
        montage.main()
    assert e.value.code == 0
    assert json.loads(capsys.readouterr().out)["delivered"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -k status -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.montage' has no attribute 'main'`. EXIT: non-zero.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/montage.py`:

```python
def main() -> None:
    ap = argparse.ArgumentParser(
        description="montage router status inspector (stage 5.1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status",
                       help="report which conveyor stage is next in a run dir")
    s.add_argument("--run-dir", required=True,
                   help="the project/run dir where stage artifacts land")
    s.add_argument("--out-dir", default=None,
                   help="delivery dir (default <run-dir>/out)")
    a = ap.parse_args()
    print(json.dumps(next_action(a.run_dir, a.out_dir), indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: 16 passed, EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: montage status CLI (router 5.1)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `SKILLS/using-montage/SKILL.md` — the conductor

**Files:**
- Create: `SKILLS/using-montage/SKILL.md`

The front-door skill. No code, no test — a skill doc, matching the house style of `SKILLS/edit-plan/SKILL.md` (frontmatter `name`/`description`, then Overview / When to Use / Process / Boundaries). It sequences the built stages, surfaces the three checkpoints, resumes from `montage status`, and names deferred stages on skip.

- [ ] **Step 1: Write the file**

Create `SKILLS/using-montage/SKILL.md` verbatim:

```markdown
---
name: using-montage
description: The montage conveyor's front door — use when a folder of raw footage plus a natural-language brief ("a 9:16 reel from this trip, no music") should become a delivered reel. The "1% chance a montage skill applies -> invoke it" router: ensure the env, then conduct the built stages (project-init -> footage-intake -> [music] -> edit-plan -> edl_to_reel) in order, stopping only at the three user checkpoints, resuming a half-finished run for free, and naming any stage it skips. Stage 5.1.
---

# using-montage (stage 5.1)

## Overview

You are the **conductor** of the montage conveyor. One invocation turns a footage
folder + a brief into `out/REEL_v1.mp4`, by running the stages that are already
built — you never re-implement a stage, and you never silently skip one. The
mechanical spans are CLIs; the judgment (what the brief means, which cut is right,
does the reel read) is yours and the sub-skills'.

**Core principle:** sequence, checkpoint, resume. Run built stages in order;
surface the three user gates (design §4.1); resume from wherever the run's
artifacts already reach; and when a stage is deferred/unbuilt, say so in one line
rather than pretending it ran.

## When to Use

Use at the **front** of a montage: raw clips exist and the user wants a reel. Not
for re-running a single stage — invoke that stage's own skill (`project-init`,
`footage-intake`, `edit-plan`, `process-episode`) directly. One `using-montage`
run covers the whole conveyor for one project/aspect.

## The Process

Announce on entry: **"Using using-montage to conduct footage -> reel."**

Point **every** stage's output at one **run dir** so the inspector sees a coherent
run: `project_init --project-dir <run>`, `intake <root> <run>`,
`edit_plan --out-dir <run>`, `edl_to_reel --work-dir <run>/work --out-dir <run>/out`.

0. **Ensure env.** `bash setup.sh` (add `--with-vidstab` — footage-intake is the
   first runtime vidstab consumer, §5.2).

1. **Locate the run.** `python -m scripts.montage status --run-dir <run>` prints
   the ordered stages, each with a `state`, plus the `next` stage. **Resume from
   `next`** — a stage whose artifact already exists is done; do not redo it. Read
   the brief and parse intent into params (table below).

2. **project-init** — if `next`. `.venv/bin/python -m scripts.project_init
   --purpose <p> --quality <q> --project-dir <run>` (custom aspect:
   `--purpose custom --canvas W:H`). **Checkpoint 1 — SPEC approval:** read back the
   resolved `{canvas, delivery}` and the intent you parsed; confirm before moving on.

3. **footage-intake** — if `next`. Invoke the **footage-intake** skill (it scans ->
   `FOOTAGE.json`/`FOOTAGE.md` and, when people matter, runs the interactive
   cast-naming -> `cast.json`). Point its out-dir at `<run>`.

4. **music-and-mood (optional).** If the brief names a track or asks for music,
   `.venv/bin/python -m scripts.beats <track> --out <run>/MUSIC.json
   [--start-offset S --duration D]`, then pass `<run>/MUSIC.json` to edit-plan. On
   "no music" / "без музыки", leave it unset — the reel is silent (a valid path).

5. **edit-plan** — if `next`. Invoke the **edit-plan** skill (it authors
   `selection.json`, runs `edit_plan build` -> `EDL.json` + `EDL.md`). **Checkpoint
   2 — EDL approval + curation:** show the user `EDL.md`. To swap or re-order an
   episode, edit `selection.json` and re-run the build — never hand-edit `EDL.json`.
   There is **no `draft.mp4`** in v1 (deferred) — the `EDL.md` map is the approval
   surface; say so plainly.

6. **edl_to_reel.** `.venv/bin/python -m scripts.edl_to_reel <run>/EDL.json
   --project <run>/project.json --footage-root <footage_root>
   --work-dir <run>/work --out-dir <run>/out [--music <run>/MUSIC.json]`. This runs
   the whole back half (extract -> process-episode ×N -> assemble -> check_reel ->
   deliver). **Checkpoint 3 — final review:** present `out/REEL_v1.mp4` and the
   `check_reel` report. A `stop_and_report` (a failed gate) is surfaced verbatim —
   never fixed forward; route it to the culprit stage's skill.

## Reading the brief (intent -> param)

The user speaks free text; you pass **explicit args** — the user never types flags.

| Said | -> |
|------|----|
| "reel"/"shorts"/"9:16" · "youtube"/"16:9" · "square"/"1:1" · "cinema"/"21:9" | `project_init --purpose` |
| "4k" · "1080"/"social" · "native"/(unstated) | `project_init --quality` |
| a track path / "with music" | `beats ... --out MUSIC.json` -> edit-plan `music` |
| "no music" / "без музыки" | leave `MUSIC.json` unset (silent reel) |
| "classic" <-> "trend" | edit-plan editorial guidance |

Mixed/unstated intent (e.g. "a reel AND a youtube cut") -> ask; one project is one
aspect (project-init's own "ask, don't guess").

## Boundaries

- The **three checkpoints** (SPEC, EDL, final review) are the ONLY user-facing
  gates (§4.1); everything else is a machine gate inside the sub-stages.
- **Deferred stages are named, not skipped silently:** reel-brief (`SPEC.md`, 5.3),
  trend-scan (5.4), pacing (`PACING.md`, 5.6 — `beat_slot` stays unset), and the
  `draft.mp4` (SP1b) are not built; say so when you pass over them.
- You never re-implement a stage and never hand-edit a generated artifact
  (`EDL.json` regenerates from `selection.json`; `FOOTAGE.json`/`project.json` from
  their writers).
- **Not built here:** the cap-3 **parallel** episode fan-out — `edl_to_reel`
  processes episodes sequentially; parallelising it is a later slice.
```

- [ ] **Step 2: Verify the frontmatter + suite**

Run: `head -3 SKILLS/using-montage/SKILL.md && .venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: the frontmatter `---` / `name: using-montage` lines print; the full suite is green (EXIT: 0) — no code changed, this confirms nothing broke.

- [ ] **Step 3: Commit**

```bash
git add SKILLS/using-montage/SKILL.md
git commit -m "feat: using-montage SKILL — the router conductor (5.1)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Docs sync + registry + final whole-slice review

**Files:**
- Modify: `docs/pipeline-map.md`
- Modify: `docs/build-status.md`
- Modify: `CLAUDE.md`
- Modify: `docs/specs/2026-07-05-montage-skillset-design.md`

Bring the always-loaded docs in step with the shipped router, add the registry rows, and run the final whole-slice review over `main..HEAD`.

- [ ] **Step 1: `docs/pipeline-map.md` — flip 5.1**

In the "15 stages" table, change the 5.1 row Status `◐ → ✅` and its note to:

```
| 5.1  | using-montage (router) | routing + ensure-env | ✅ | `using-montage` SKILL conducts the built stages footage->reel with the three §4.1 checkpoints; `montage.py` inspector (`next_action`) drives resume-from-`next`. cap-3 **parallel** fan-out is the one open sub-item | Router + curation |
```

In "Remaining work — blockers & critical path", change the 5.1 row to:

```
| 5.1 | using-montage router | ✅ | cap-3 **parallel** fan-out only (sub-item) | — | autonomous v1 |
```

Update the **Tally** line from `7 ✅ · 5 ◐ · 3 ❌` to `8 ✅ · 4 ◐ · 3 ❌`.

In "Critical path to autonomous v1", change the diagram + prose so the router is ✅ and the remaining hard item is only the parallel fan-out:

```
5.2 footage-intake ✅ ──► 5.7 edit-plan ✅ ──► 5.1 using-montage ✅   = autonomy
```

Replace the "Hard chain left: 5.1." paragraph with: **the entry-skill closes the autonomous v1 chain** — footage→EDL→reel now runs from one `using-montage` invocation; the only open 5.1 sub-item is the cap-3 **parallel** episode fan-out (a perf slice, `edl_to_reel` stays sequential today), not a v1 blocker.

- [ ] **Step 2: `docs/build-status.md` — add the entry, narrow the next-action**

Add a new bullet at the top of "Done" (mirroring the prior DONE entries' shape):

```
- **using-montage router (5.1, entry-skill) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-using-montage.md` + design
  `docs/specs/2026-07-12-using-montage-design.md`. Ships the conveyor's front
  door: `SKILLS/using-montage/SKILL.md` conducts the built stages
  (project-init -> footage-intake -> [music] -> edit-plan -> edl_to_reel) with the
  three §4.1 user checkpoints, resuming a half-finished run for free and naming any
  deferred stage on skip. Backed by `scripts/montage.py` — a thin deterministic
  **inspector** (`Stage`/`V1_STAGES` + `next_action(run_dir)` reporting each stage's
  state done/next/pending/optional/skip from artifact presence, + a `status` CLI).
  Inspector, not runner: the judgment steps (cast-naming, selection authoring) stay
  agent-interactive, so the SKILL runs stages and consults `next_action` for the
  resume/next decision (mirrors intake.py <-> footage-intake). No stage
  re-implemented; no new integration golden (the SP1/SP3 seam goldens already prove
  intake->edit->reel on real bytes). **Deferred (NOT built):** cap-3 **parallel**
  episode fan-out (edl_to_reel stays sequential), full reel-brief `SPEC.md` (5.3),
  `draft.mp4` (SP1b), dual-emit "without-music"+sidecar (5.14), trend-scan (5.4),
  pacing (5.6).
```

In "Next action", replace the `**router** — cap-3 fan-out …` bullet with:

```
- **cap-3 parallel fan-out** — the one open 5.1 sub-item: parallelise
  `edl_to_reel`'s sequential per-episode `process_episode` loop (concurrency cap 3,
  design §5.10), leaving the just-shipped `using-montage` entry-skill as the
  conductor. **OR**
```

Also update the `_Last updated:_` date to `2026-07-12` if not already.

- [ ] **Step 3: `CLAUDE.md` — registry rows**

In the Quick Reference table, add two rows (next to the other spine rows):

```
| Router entry-skill design | [2026-07-12-using-montage-design.md](docs/specs/2026-07-12-using-montage-design.md) | Stage 5.1 front door: `using-montage` SKILL conducts footage->reel with the three §4.1 checkpoints; thin `montage.py` `next_action` inspector for resume-from-`next`; inspector-not-runner; cap-3 parallel fan-out deferred. |
| Router entry-skill plan | [2026-07-12-using-montage.md](docs/plans/2026-07-12-using-montage.md) | Tasks 0–4: `montage.py` (`Stage`/`V1_STAGES`/`next_action`/`status` CLI), `using-montage` SKILL, docs sync. |
```

- [ ] **Step 4: `docs/specs/2026-07-05-montage-skillset-design.md` — §5.1 Built note**

Immediately after the §5.1 paragraph (the `**Natural-language overrides:**` line), insert:

```
> **Built (2026-07-12, entry-skill):** `SKILLS/using-montage/SKILL.md` conducts the
> built stages (project-init -> footage-intake -> [music] -> edit-plan ->
> edl_to_reel) with the three §4.1 checkpoints, backed by `scripts/montage.py` — a
> deterministic stage-status **inspector** (`next_action`) so resume-for-free (line
> 510) is testable. Inspector, not runner: judgment steps stay in the sub-skills.
> The cap-3 **parallel** episode fan-out (§5.10) is deferred — `edl_to_reel` is
> sequential. See `docs/plans/2026-07-12-using-montage.md`.
```

- [ ] **Step 5: Verify the suite + commit the docs**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: full suite green (EXIT: 0) — the montage tests added (16) on top of the prior 548 → **564 passed, 1 skipped** (vidstab-gated).

```bash
git add docs/pipeline-map.md docs/build-status.md CLAUDE.md \
  docs/specs/2026-07-05-montage-skillset-design.md
git commit -m "docs: sync pipeline-map/build-status/registry for using-montage router (5.1)" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Final whole-slice review**

Dispatch a code-review subagent over the whole slice (`git diff main..HEAD`). Confirm the invariants: (a) `montage.py` is pure/deterministic (no ffmpeg/network); (b) `Stage` fails loud on bad `kind`/`checkpoint`; (c) `next_action`'s per-artifact `done` surfaces a broken resume honestly (the `test_broken_resume` case); (d) the SKILL names every deferred stage and never hand-edits a generated artifact; (e) no existing stage behaviour changed (reused-as-is files untouched). Fix any Important/Critical finding in a follow-up commit (not `--amend`), re-review, then the branch is ready to finish.

---

## Self-Review

**1. Spec coverage** (against `docs/specs/2026-07-12-using-montage-design.md`):
- §2.1 `Stage` config-spec + validation → Task 0. ✓
- §2.2 `V1_STAGES` table → Task 0. ✓
- §2.3 `next_action` (all five states, per-artifact done, out_dir default, delivered) → Task 1. ✓
- §2.4 `status` CLI → Task 2. ✓
- §3 SKILL (process, checkpoints, intent→param, boundaries, run-dir co-location) → Task 3. ✓
- §4 Testing (unit matrix; no integration golden, decision noted) → Tasks 0–2 + Task 4 Step 5. ✓
- §7 Docs to sync (pipeline-map, build-status, CLAUDE.md, spec §5.1) → Task 4. ✓
- §5 Non-goals (parallel fan-out etc.) — asserted as "deferred/not built" in the SKILL boundaries + docs, no task builds them. ✓

**2. Placeholder scan:** no TBD/TODO; every code + test + doc step shows literal content; commands are exact with expected output. ✓

**3. Type consistency:** `Stage(key, artifact, kind, runner, checkpoint, in_out=False)` used identically in Task 0's table and tests; `next_action(run_dir, out_dir=None) -> dict` with keys `stages`/`next`/`delivered` and per-stage `{key,artifact,kind,state,checkpoint,runner}` consistent across Tasks 1–2 tests and the CLI; `_exists(base: Path, glob: str)` matches its call sites; test counts accumulate 6 → 14 → 16 coherently. ✓
