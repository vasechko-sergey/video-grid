# Editorial-Constraint Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user-stated editorial rule lands in `CONSTRAINTS.json`, is found by convention beside `project.json`, and refuses any cut that breaks it — on every re-cut, with no flag to forget and no waiver to write.

**Architecture:** A new pure `scripts/lib/constraints.py` holds the four-kind rule vocabulary, its load-time refusals, and `evaluate`, which judges a projection of the cut (`Placed` = source + shot + pinned cast name) rather than `EDLEpisode` objects — `edl.py` imports the report type to carry it, so the dependency must run one way. `edit_plan.build_edl` measures (attaching `EDL.constraints`), `edit_plan.write_edit_plan` refuses with its own `constraint-violation` reason. The identity unit is the **shot** (a scene-cut segment), reached through a new `FootageClip.shot_at` beside the existing `room_after`.

**Tech Stack:** Python 3.13, stdlib only. No ffmpeg, no new dependency, no cache version bump, no re-scan.

**Design:** `docs/specs/2026-08-07-editorial-constraints-design.md` — read §2 (the shot as the unit), §4 (module boundary), §5 (the gate), §7 (the four checks) before starting.

## Global Constraints

- **Python is `.venv/bin/python`** (3.13). Scripts run as modules — `pytest.ini` sets `pythonpath = .`, so imports are `from scripts.lib import x`, never relative.
- **Fail loud, never silently default.** Every refusal message names the offending value AND the remedy. This is the repo's `coding-standards.md` contract; a reviewer treats a bare `raise ValueError("bad")` as a defect.
- **Imports at top of file.** No function-local imports.
- **No new dependencies.** stdlib + what `scripts/lib` already imports.
- **Never run an installer** (`brew`, `pip install`, `npm`, `uv`, `setup.sh`). Verification is read-only plus `pytest`. If something appears missing, report it — do not install it.
- **`stated` is required on every rule.** A rule with no origin is a rule the agent invented for itself (design §3).
- **Unmeasurable is never "passed".** A bookend rule whose episode pins no cast name is a **violation**, not a skip (design §7). Absent `CONSTRAINTS.json` → `EDL.constraints is None` = *not evaluated*, never *passed*.
- **No waiver.** Nothing in this slice may add a selection.json key that lets a violated rule through (design §5).
- **Commit per task**, English message, conventional prefix (`feat:`/`test:`/`docs:`), ending with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- **Run the fast suite before every commit:** `.venv/bin/python -m pytest tests/ -m "not integration" -q`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `scripts/lib/footage.py` | + `FootageClip.shot_at` — the shot's `[start, end)`, sharing `room_after`'s boundary rule | 0 |
| `scripts/lib/constraints.py` (new) | `Rule`/`Constraints` contract + load refusals | 1 |
| `scripts/lib/constraints.py` | `Placed`/`Violation`/`ConstraintReport` + `evaluate` and the three checkers | 2 |
| `scripts/lib/edl.py` | `EDL.constraints` carrier: field, round-trip, markdown section | 3 |
| `scripts/edit_plan.py` | the projection, the `rules=` parameter, discovery beside `project.json`, the gate | 4 |
| `tests/integration/test_edit_plan.py` | discovery-by-convention proven end-to-end | 5 |
| `skills/edit-plan/SKILL.md`, `skills/using-montage/SKILL.md`, `CLAUDE.md`, `docs/*` | authoring guidance + registry/status sync | 6 |

---

### Task 0: `FootageClip.shot_at`

**Files:**
- Modify: `scripts/lib/footage.py` (insert directly after `room_after`, which ends at line 211)
- Test: `tests/lib/test_footage.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `FootageClip.shot_at(t: float) -> tuple[float, float]` — the `[start, end)` of the uninterrupted shot containing `t`. Raises `ValueError` for a negative `t` or a `t` at/past `clip.dur`. Tasks 2 and 4 depend on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_footage.py`:

```python
def test_shot_at_no_cuts_is_the_whole_clip():
    clip = FootageClip(source="A.mp4", dur=20.0, res=(1920, 1080), fps=30.0, scene_cuts=[])
    assert clip.shot_at(0.0) == (0.0, 20.0)
    assert clip.shot_at(19.9) == (0.0, 20.0)


def test_shot_at_returns_the_segment_between_the_surrounding_cuts():
    clip = FootageClip(source="A.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       scene_cuts=[10.0, 22.0])
    assert clip.shot_at(3.0) == (0.0, 10.0)
    assert clip.shot_at(15.0) == (10.0, 22.0)
    assert clip.shot_at(25.0) == (22.0, 30.0)


def test_shot_at_on_a_cut_belongs_to_the_later_shot_like_room_after():
    # room_after keeps `c > start`, so a start exactly ON a cut gets the room of the
    # shot that BEGINS there. shot_at must agree, or the two authorities would place
    # the same episode in different shots.
    clip = FootageClip(source="A.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       scene_cuts=[10.0, 22.0])
    assert clip.shot_at(10.0) == (10.0, 22.0)
    assert clip.shot_at(10.0)[1] - 10.0 == clip.room_after(10.0)


def test_shot_at_refuses_a_time_outside_the_clip():
    clip = FootageClip(source="A.mp4", dur=20.0, res=(1920, 1080), fps=30.0)
    with pytest.raises(ValueError, match="past the end"):
        clip.shot_at(20.0)
    with pytest.raises(ValueError, match=">= 0"):
        clip.shot_at(-1.0)
```

If `tests/lib/test_footage.py` does not already import `pytest`, `FootageClip`, add them at the top of the file in the existing import style.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -k shot_at -q`
Expected: FAIL — `AttributeError: 'FootageClip' object has no attribute 'shot_at'`.

- [ ] **Step 3: Implement**

In `scripts/lib/footage.py`, directly after `room_after`:

```python
    def shot_at(self, t: float) -> tuple[float, float]:
        """The [start, end) of the uninterrupted shot containing `t`.

        The identity unit editorial constraints key on (design
        docs/specs/2026-08-07-editorial-constraints-design.md §2): two episodes carved
        from ONE shot are the same moment even when their spans do not overlap, which
        is the repeat a per-window comparison misses — carve deliberately emits
        overlapping candidate windows, so two indices routinely name one moment.

        Shares room_after's boundary rule (`c > t`, so a `t` exactly ON a cut belongs
        to the shot that BEGINS there): the two must not disagree about where a shot
        ends, or an episode would be legal by one authority and a straddle by the
        other."""
        if not (_num(t) and t >= 0):
            raise ValueError(f"FootageClip.shot_at: t must be a number >= 0 seconds, got {t!r}")
        if t >= self.dur:
            raise ValueError(f"FootageClip.shot_at: t {t} is past the end of "
                             f"{self.source} ({self.dur}s)")
        before = [c for c in self.scene_cuts if c <= t]
        return (float(max(before)) if before else 0.0, float(t + self.room_after(t)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -q`
Expected: PASS, whole file green.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/footage.py tests/lib/test_footage.py
git commit -m "feat(footage): shot_at — the scene-cut segment a time belongs to"
```

---

### Task 1: The rule contract and its load-time refusals

**Files:**
- Create: `scripts/lib/constraints.py`
- Test: `tests/lib/test_constraints.py` (new)

**Interfaces:**
- Consumes: nothing from Task 0.
- Produces, for Tasks 2–4:
  - `KINDS = ("no_repeat", "open_with", "close_with", "exclude")`
  - `SINGLETON_KINDS = ("no_repeat", "open_with", "close_with")`
  - `Rule(kind: str, stated: str, hero: str | None = None, source: str | None = None, window: int | None = None)` with `.to_dict()`
  - `Constraints(rules: tuple[Rule, ...] = ())` with `.from_dict(d)`, `.from_json(path)`, `.to_dict()`

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_constraints.py`:

```python
import json

import pytest
from scripts.lib.constraints import Constraints, Rule


def test_rule_round_trips_only_the_fields_its_kind_owns():
    r = Rule(kind="exclude", stated="этот дубль не брать", source="A.mp4", window=7)
    assert r.to_dict() == {"kind": "exclude", "stated": "этот дубль не брать",
                           "source": "A.mp4", "window": 7}
    assert Rule(kind="no_repeat", stated="эпизоды не должны повторяться").to_dict() == {
        "kind": "no_repeat", "stated": "эпизоды не должны повторяться"}


def test_unknown_kind_is_refused_with_the_vocabulary():
    with pytest.raises(ValueError) as ei:
        Rule(kind="no_adjacent", stated="не два дрона подряд")
    assert "no_adjacent" in str(ei.value) and "no_repeat" in str(ei.value)


def test_blank_stated_is_refused():
    with pytest.raises(ValueError, match="stated"):
        Rule(kind="no_repeat", stated="   ")


def test_missing_required_field_is_refused_naming_it():
    with pytest.raises(ValueError, match="hero"):
        Rule(kind="open_with", stated="Serge opens")
    with pytest.raises(ValueError, match="source"):
        Rule(kind="exclude", stated="skip that take")


def test_a_field_that_does_not_belong_to_the_kind_is_refused():
    # A `hero` on an exclude is not a harmless extra: it reads as "exclude this
    # person", which the rule does not do. Refuse rather than ignore.
    with pytest.raises(ValueError, match="no 'hero'"):
        Rule(kind="exclude", stated="skip", source="A.mp4", hero="Serge")


def test_window_must_be_a_non_negative_int():
    with pytest.raises(ValueError, match="window"):
        Rule(kind="exclude", stated="skip", source="A.mp4", window=-1)
    with pytest.raises(ValueError, match="window"):
        Rule(kind="exclude", stated="skip", source="A.mp4", window=True)


def test_constraints_round_trip_through_dict():
    d = {"rules": [{"kind": "no_repeat", "stated": "no repeats"},
                   {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]}
    c = Constraints.from_dict(d)
    assert [r.kind for r in c.rules] == ["no_repeat", "open_with"]
    assert c.to_dict() == d


def test_a_second_singleton_rule_is_refused_as_a_contradiction():
    with pytest.raises(ValueError, match="singleton"):
        Constraints.from_dict({"rules": [
            {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"},
            {"kind": "open_with", "stated": "no, Anna opens", "hero": "Anna"}]})


def test_a_duplicate_exclude_is_refused_but_two_different_ones_are_fine():
    with pytest.raises(ValueError, match="twice"):
        Constraints.from_dict({"rules": [
            {"kind": "exclude", "stated": "skip", "source": "A.mp4", "window": 1},
            {"kind": "exclude", "stated": "skip again", "source": "A.mp4", "window": 1}]})
    c = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip 1", "source": "A.mp4", "window": 1},
        {"kind": "exclude", "stated": "skip 2", "source": "A.mp4", "window": 2},
        {"kind": "exclude", "stated": "skip B", "source": "B.mp4"}]})
    assert len(c.rules) == 3


def test_unknown_json_key_is_refused_with_the_field_help():
    with pytest.raises(ValueError) as ei:
        Constraints.from_dict({"rules": [
            {"kind": "open_with", "stated": "Serge opens", "heroes": "Serge"}]})
    msg = str(ei.value)
    assert "rules[0]" in msg and "open_with: hero" in msg


@pytest.mark.parametrize("body", ['[]', '"str"', '42', 'null', '{"rules": {}}'])
def test_wrong_shaped_file_raises_valueerror_with_a_remedy(tmp_path, body):
    p = tmp_path / "CONSTRAINTS.json"
    p.write_text(body)
    with pytest.raises(ValueError) as ei:
        Constraints.from_json(str(p))
    assert "rules" in str(ei.value)


def test_corrupt_json_names_the_file(tmp_path):
    p = tmp_path / "CONSTRAINTS.json"
    p.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        Constraints.from_json(str(p))


def test_empty_rule_list_is_legal(tmp_path):
    p = tmp_path / "CONSTRAINTS.json"
    p.write_text(json.dumps({"rules": []}))
    assert Constraints.from_json(str(p)).rules == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_constraints.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.constraints'`.

- [ ] **Step 3: Implement the module's contract half**

Create `scripts/lib/constraints.py`:

```python
"""Editorial-constraint memory (design docs/specs/2026-08-07-editorial-constraints-design.md).

A rule the user stated out loud must survive the conversation that stated it and
bind every re-cut — backlog #14, whose two real breakages (a bookend rule and a
no-repeat rule) were both mechanically checkable and neither checked, because
neither was written anywhere a checker could reach.

The vocabulary is CLOSED and an unknown kind is a load-time refusal, not a stored
note: a file that remembers a rule it cannot enforce converts "forgotten" into
"believed handled", which is worse than no file at all (design §1.4). The honest
cost — a rule outside the four kinds has nowhere to live — is design §10.

Pure: stdlib + footage (an `exclude` resolves its window against the clip's scene
cuts). It deliberately does NOT import edl: edl.py imports ConstraintReport to
carry it, so the dependency runs one way and the caller hands in a projection —
the same boundary moodpreset.VarietyReport draws.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.footage import Footage

KINDS = ("no_repeat", "open_with", "close_with", "exclude")

# Two of a singleton kind can contradict each other (two open_with rules naming
# different heroes can never both hold), so a second one is refused at LOAD —
# once — instead of refusing every cut forever.
SINGLETON_KINDS = ("no_repeat", "open_with", "close_with")

_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # kind -> (required, optional), beside the universal `stated`
    "no_repeat": ((), ()),
    "open_with": (("hero",), ()),
    "close_with": (("hero",), ()),
    "exclude": (("source",), ("window",)),
}
_OWNABLE = ("hero", "source", "window")
_FIELDS_HELP = "; ".join(f"{k}: {', '.join(req + opt) or 'no extra fields'}"
                         for k, (req, opt) in _FIELDS.items())


@dataclass
class Rule:
    """One editorial rule: its kind, the user's own words, and that kind's fields.

    `stated` is required and non-empty on every kind. It is what a refusal quotes
    back, and it is the only thing separating a rule the user gave from one the
    agent invented for itself."""
    kind: str
    stated: str
    hero: str | None = None
    source: str | None = None
    window: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(
                f"Rule.kind {self.kind!r} unknown — expected one of {KINDS}. A rule outside "
                f"this vocabulary cannot be stored: nothing lives in CONSTRAINTS.json that "
                f"the machine does not check. Say so in words instead of writing it down")
        if not (isinstance(self.stated, str) and self.stated.strip()):
            raise ValueError(
                f"Rule.stated must be the rule as it was stated, non-empty (kind "
                f"{self.kind!r}) — a rule with no origin is a rule the agent invented for "
                f"itself")
        required, optional = _FIELDS[self.kind]
        for name in required:
            if getattr(self, name) is None:
                raise ValueError(f"Rule {self.kind!r} needs {name!r} — it takes "
                                 f"{', '.join(required + optional)} beside 'stated'")
        for name in _OWNABLE:
            if getattr(self, name) is not None and name not in required + optional:
                raise ValueError(
                    f"Rule {self.kind!r} has no {name!r} field — it takes "
                    f"{', '.join(required + optional) or 'no fields'} beside 'stated'. "
                    f"An extra field is refused, not ignored: it reads as a rule that is "
                    f"not the one being enforced")
        if self.hero is not None and not (isinstance(self.hero, str) and self.hero.strip()):
            raise ValueError(f"Rule.hero must be a non-empty cast name, got {self.hero!r}")
        if self.source is not None and not (isinstance(self.source, str) and self.source):
            raise ValueError(f"Rule.source must be a non-empty clip path, got {self.source!r}")
        if self.window is not None and (isinstance(self.window, bool)
                                        or not isinstance(self.window, int) or self.window < 0):
            raise ValueError(f"Rule.window must be an int >= 0 (a FOOTAGE window index) or "
                             f"absent, got {self.window!r}")

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "stated": self.stated}
        for name in _OWNABLE:
            if getattr(self, name) is not None:
                d[name] = getattr(self, name)
        return d


@dataclass
class Constraints:
    """The project's editorial rules, in the order they were stated."""
    rules: tuple[Rule, ...] = ()

    def __post_init__(self) -> None:
        self.rules = tuple(self.rules)
        for k, r in enumerate(self.rules):
            if not isinstance(r, Rule):
                raise ValueError(f"Constraints.rules[{k}] must be a Rule, got {type(r).__name__}")
        for kind in SINGLETON_KINDS:
            if sum(1 for r in self.rules if r.kind == kind) > 1:
                raise ValueError(
                    f"CONSTRAINTS.json holds more than one {kind!r} rule, and that kind is a "
                    f"singleton — two of them can contradict, and a contradiction can never be "
                    f"satisfied. Keep the one that holds and delete the rest")
        seen: set = set()
        for r in self.rules:
            if r.kind != "exclude":
                continue
            key = (r.source, r.window)
            if key in seen:
                raise ValueError(f"CONSTRAINTS.json excludes {r.source!r} window {r.window!r} "
                                 f"twice — delete the duplicate rule")
            seen.add(key)

    @classmethod
    def from_dict(cls, d: dict) -> "Constraints":
        # The top level is checked FIRST, before any d.get — this boundary reads
        # user-authored JSON, so it owes its callers ONE documented exception type
        # (the same rule Spec.from_dict and EDL.from_dict follow).
        if not isinstance(d, dict):
            raise ValueError(f"CONSTRAINTS.json must be an object with a 'rules' list, got "
                             f"{type(d).__name__}")
        raw = d.get("rules")
        if not isinstance(raw, list):
            raise ValueError("CONSTRAINTS.json must hold a 'rules' list (use [] for no rules)")
        rules = []
        for k, r in enumerate(raw):
            if not isinstance(r, dict):
                raise ValueError(f"CONSTRAINTS.json rules[{k}] must be an object, got "
                                 f"{type(r).__name__}")
            try:
                rules.append(Rule(**r))
            except TypeError as ex:
                raise ValueError(f"CONSTRAINTS.json rules[{k}] has an unknown or missing field "
                                 f"— {ex}. A rule carries 'kind' + 'stated' plus that kind's "
                                 f"own fields ({_FIELDS_HELP})") from ex
        return cls(rules=tuple(rules))

    @classmethod
    def from_json(cls, path: str | Path) -> "Constraints":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the rule file's syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"rules": [r.to_dict() for r in self.rules]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_constraints.py -q`
Expected: PASS (14 tests).

- [ ] **Step 5: Run the fast suite and commit**

```bash
.venv/bin/python -m pytest tests/ -m "not integration" -q
git add scripts/lib/constraints.py tests/lib/test_constraints.py
git commit -m "feat(constraints): the four-kind rule vocabulary and its load refusals"
```

---

### Task 2: `evaluate` — the three checkers and the report

**Files:**
- Modify: `scripts/lib/constraints.py` (append below `Constraints`)
- Test: `tests/lib/test_constraints.py` (append)

**Interfaces:**
- Consumes: Task 0's `FootageClip.shot_at`; Task 1's `Rule`/`Constraints`.
- Produces, for Tasks 3–4:
  - `Placed(source: str, shot: tuple[float, float], hero: str | None = None)`
  - `Violation(rule_index: int, kind: str, stated: str, message: str)` with `.to_dict()`/`.from_dict()`
  - `ConstraintReport(rules: tuple[dict, ...] = (), violations: tuple[Violation, ...] = ())` with `.ok`, `.to_dict()`, `.from_dict()`
  - `evaluate(rules: Constraints, placed: tuple[Placed, ...], footage: Footage) -> ConstraintReport`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_constraints.py`:

```python
from scripts.lib.constraints import ConstraintReport, Placed, Violation, evaluate
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _footage():
    # A.mp4 has a cut at 10.0: shot [0, 10) and shot [10, 20). Its windows 0 and 1
    # BOTH live in the first shot and do not overlap in time — the repeat a
    # per-window or per-interval comparison misses (design §2).
    return Footage(clips=[
        FootageClip(source="A.mp4", dur=20.0, res=(1920, 1080), fps=30.0, scene_cuts=[10.0],
                    windows=[
                        FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1,
                                      motion=0.3, shake=0.0),
                        FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1,
                                      motion=0.3, shake=0.0),
                        FootageWindow(start=12.0, dur=2.0, shot_type="close", people=1,
                                      motion=0.3, shake=0.0)]),
        FootageClip(source="B.mp4", dur=8.0, res=(1920, 1080), fps=30.0,
                    windows=[FootageWindow(start=1.0, dur=2.0, shot_type="medium", people=1,
                                           motion=0.3, shake=0.0)])])


def _placed(source, shot, hero=None):
    return Placed(source=source, shot=shot, hero=hero)


def test_no_repeat_fires_on_two_episodes_from_one_shot_that_do_not_overlap():
    rules = Constraints.from_dict({"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    placed = (_placed("A.mp4", (0.0, 10.0)), _placed("A.mp4", (0.0, 10.0)))
    rep = evaluate(rules, placed, _footage())
    assert not rep.ok
    assert rep.violations[0].rule_index == 0 and rep.violations[0].kind == "no_repeat"
    assert "episodes 0, 1" in rep.violations[0].message and "A.mp4" in rep.violations[0].message


def test_no_repeat_passes_for_two_different_shots_of_one_clip():
    rules = Constraints.from_dict({"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    placed = (_placed("A.mp4", (0.0, 10.0)), _placed("A.mp4", (10.0, 20.0)))
    rep = evaluate(rules, placed, _footage())
    assert rep.ok and rep.violations == ()
    assert rep.rules == ({"kind": "no_repeat", "stated": "no repeats"},)


def test_bookend_passes_when_the_edge_episode_pins_the_named_hero():
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"},
        {"kind": "close_with", "stated": "Anna closes", "hero": "Anna"}]})
    placed = (_placed("A.mp4", (0.0, 10.0), hero="Serge"),
              _placed("B.mp4", (0.0, 8.0), hero="Anna"))
    assert evaluate(rules, placed, _footage()).ok


def test_bookend_names_the_wrong_hero_it_found():
    rules = Constraints.from_dict({"rules": [
        {"kind": "close_with", "stated": "Anna closes", "hero": "Anna"}]})
    placed = (_placed("A.mp4", (0.0, 10.0), hero="Serge"),
              _placed("B.mp4", (0.0, 8.0), hero="Serge"))
    rep = evaluate(rules, placed, _footage())
    assert not rep.ok and "'Serge'" in rep.violations[0].message and "Anna" in rep.violations[0].message


def test_an_unpinned_edge_episode_is_a_violation_not_a_pass():
    # The S3 lesson, applied here: "cannot tell" must never read as "fine".
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]})
    placed = (_placed("A.mp4", (0.0, 10.0)), _placed("B.mp4", (0.0, 8.0)))
    rep = evaluate(rules, placed, _footage())
    assert not rep.ok
    assert "pins no cast name" in rep.violations[0].message
    assert '"hero": "Serge"' in rep.violations[0].message      # the remedy is mechanical


def test_exclude_bans_one_shot_when_a_window_is_named():
    rules = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "not that take", "source": "A.mp4", "window": 0}]})
    # window 0 starts at 1.0 -> shot [0, 10). An episode from the LATER shot is fine.
    assert evaluate(rules, (_placed("A.mp4", (10.0, 20.0)),), _footage()).ok
    rep = evaluate(rules, (_placed("A.mp4", (0.0, 10.0)),), _footage())
    assert not rep.ok and "0.00s–10.00s" in rep.violations[0].message


def test_exclude_without_a_window_bans_the_whole_clip():
    rules = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip B entirely", "source": "B.mp4"}]})
    assert evaluate(rules, (_placed("A.mp4", (0.0, 10.0)),), _footage()).ok
    rep = evaluate(rules, (_placed("B.mp4", (0.0, 8.0)),), _footage())
    assert not rep.ok and "the whole clip" in rep.violations[0].message


def test_a_stale_exclude_raises_instead_of_enforcing_nothing():
    gone = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip", "source": "GONE.mp4"}]})
    with pytest.raises(ValueError, match="not in FOOTAGE"):
        evaluate(gone, (_placed("A.mp4", (0.0, 10.0)),), _footage())
    oob = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip", "source": "B.mp4", "window": 9}]})
    with pytest.raises(ValueError, match="has 1 window"):
        evaluate(oob, (_placed("A.mp4", (0.0, 10.0)),), _footage())


def test_report_round_trips_through_dict():
    rules = Constraints.from_dict({"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    rep = evaluate(rules, (_placed("A.mp4", (0.0, 10.0)), _placed("A.mp4", (0.0, 10.0))),
                   _footage())
    back = ConstraintReport.from_dict(rep.to_dict())
    assert back == rep and not back.ok
    assert isinstance(back.violations[0], Violation)


def test_no_rules_reports_an_empty_ok_report():
    rep = evaluate(Constraints(), (_placed("A.mp4", (0.0, 10.0)),), _footage())
    assert rep.ok and rep.rules == () and rep.violations == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_constraints.py -q`
Expected: FAIL — `ImportError: cannot import name 'evaluate' from 'scripts.lib.constraints'`.

- [ ] **Step 3: Implement**

Append to `scripts/lib/constraints.py`:

```python
@dataclass
class Placed:
    """One EDL episode reduced to what a rule can judge.

    `hero` is the cast NAME pinned on the episode, or None when the pin is a bbox,
    a track id, a HERO_RULES string like "largest", or absent — all of which name a
    TRACKING TARGET, not a person. A bookend rule reads None as unsatisfied, never
    as satisfied (design §7): treating "cannot tell" as "fine" would rebuild the
    silent pass this module exists to remove.

    The projection is built by the caller (edit_plan holds both the clip, for
    shot_at, and the episode, for the pin) because importing EDLEpisode here would
    close a cycle with edl.py, which imports ConstraintReport to carry it."""
    source: str
    shot: tuple[float, float]
    hero: str | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.source, str) and self.source):
            raise ValueError("Placed.source must be a non-empty clip path")
        if not (isinstance(self.shot, (tuple, list)) and len(self.shot) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for v in self.shot)):
            raise ValueError(f"Placed.shot must be a (start, end) pair of seconds, got "
                             f"{self.shot!r}")
        self.shot = (float(self.shot[0]), float(self.shot[1]))
        if self.hero is not None and not (isinstance(self.hero, str) and self.hero.strip()):
            raise ValueError(f"Placed.hero must be a cast name or None, got {self.hero!r}")


@dataclass
class Violation:
    """One rule this cut breaks, carrying the words that stated it."""
    rule_index: int
    kind: str
    stated: str
    message: str

    def to_dict(self) -> dict:
        return {"rule_index": self.rule_index, "kind": self.kind,
                "stated": self.stated, "message": self.message}

    @classmethod
    def from_dict(cls, d: dict) -> "Violation":
        if not isinstance(d, dict):
            raise ValueError(f"Violation.from_dict: expected an object, got {type(d).__name__}")
        return cls(rule_index=d.get("rule_index"), kind=d.get("kind"),
                   stated=d.get("stated"), message=d.get("message"))


@dataclass
class ConstraintReport:
    """Which rules bound this cut, and which of them it broke. `rules` echoes the
    rules AS CHECKED, so the artifact carries its own evidence — a later reader sees
    what constrained the cut without reconstructing the session."""
    rules: tuple[dict, ...] = ()
    violations: tuple[Violation, ...] = ()

    def __post_init__(self) -> None:
        self.rules = tuple(self.rules)
        self.violations = tuple(self.violations)
        for k, v in enumerate(self.violations):
            if not isinstance(v, Violation):
                raise ValueError(f"ConstraintReport.violations[{k}] must be a Violation")

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict:
        return {"rules": [dict(r) for r in self.rules],
                "violations": [v.to_dict() for v in self.violations]}

    @classmethod
    def from_dict(cls, d: dict) -> "ConstraintReport":
        if not isinstance(d, dict):
            raise ValueError(f"ConstraintReport.from_dict: expected an object with 'rules' and "
                             f"'violations', got {type(d).__name__} — re-run edit_plan build")
        return cls(rules=tuple(d.get("rules") or ()),
                   violations=tuple(Violation.from_dict(v) for v in (d.get("violations") or ())))


def _no_repeat(placed: tuple[Placed, ...]) -> str | None:
    groups: dict[tuple, list[int]] = {}
    for i, p in enumerate(placed):
        groups.setdefault((p.source, p.shot), []).append(i)
    dups = [(key, idx) for key, idx in groups.items() if len(idx) > 1]
    if not dups:
        return None
    parts = [f"episodes {', '.join(str(i) for i in idx)} are all from {src} "
             f"[{a:.2f}s–{b:.2f}s]" for (src, (a, b)), idx in dups]
    return ("; ".join(parts) + " — one shot, several episodes. Reference a window from a "
            "different shot, or drop the repeat")


def _bookend(rule: Rule, placed: tuple[Placed, ...]) -> str | None:
    if not placed:
        return f"the cut has no episodes, so nothing can satisfy {rule.kind} {rule.hero!r}"
    first = rule.kind == "open_with"
    p = placed[0] if first else placed[-1]
    where = "first" if first else "last"
    if p.hero == rule.hero:
        return None
    if p.hero is None:
        return (f"the {where} episode ({p.source}) pins no cast name, so it cannot satisfy "
                f"{rule.kind} {rule.hero!r} — a bbox, a track id and a rule pin like "
                f'"largest" all name a tracking target, not a person. Set '
                f'"hero": "{rule.hero}" on it in selection.json')
    return (f"the {where} episode ({p.source}) pins {p.hero!r}, not {rule.hero!r} — "
            f"reorder the cut or re-pin that episode")


def _exclude(rule: Rule, placed: tuple[Placed, ...], by_source: dict) -> str | None:
    clip = by_source.get(rule.source)
    if clip is None:
        raise ValueError(
            f"CONSTRAINTS.json excludes {rule.source!r}, which is not in FOOTAGE — have "
            f"{sorted(by_source)}. Fix or delete the stale rule: a rule pointing at footage "
            f"that no longer exists must not quietly enforce nothing")
    banned = None
    if rule.window is not None:
        if rule.window >= len(clip.windows):
            raise ValueError(
                f"CONSTRAINTS.json excludes {rule.source!r} window {rule.window}, but the clip "
                f"has {len(clip.windows)} window(s) — fix or delete the stale rule")
        # Both sides of the comparison below come from shot_at on the SAME clip, so the
        # float pair is bit-identical, not merely close; no tolerance is needed or wanted.
        banned = clip.shot_at(clip.windows[rule.window].start)
    hits = [i for i, p in enumerate(placed)
            if p.source == rule.source and (banned is None or p.shot == banned)]
    if not hits:
        return None
    scope = f"[{banned[0]:.2f}s–{banned[1]:.2f}s]" if banned is not None else "the whole clip"
    return (f"episode(s) {', '.join(str(i) for i in hits)} use {rule.source} {scope}, which is "
            f"excluded — pick a different shot")


def evaluate(rules: Constraints, placed: tuple[Placed, ...],
             footage: Footage) -> ConstraintReport:
    """Judge a projected cut against the rules, in the order they were stated.

    A stale `exclude` (a source no longer in FOOTAGE, or a window index past the
    clip's list) RAISES rather than reporting: it is a broken input, not a broken
    cut, and the two must not arrive through the same channel."""
    by_source = {c.source: c for c in footage.clips}
    vio: list[Violation] = []
    for i, r in enumerate(rules.rules):
        if r.kind == "no_repeat":
            msg = _no_repeat(placed)
        elif r.kind in ("open_with", "close_with"):
            msg = _bookend(r, placed)
        else:
            msg = _exclude(r, placed, by_source)
        if msg:
            vio.append(Violation(rule_index=i, kind=r.kind, stated=r.stated, message=msg))
    return ConstraintReport(rules=tuple(r.to_dict() for r in rules.rules),
                            violations=tuple(vio))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_constraints.py -q`
Expected: PASS (24 tests).

- [ ] **Step 5: Run the fast suite and commit**

```bash
.venv/bin/python -m pytest tests/ -m "not integration" -q
git add scripts/lib/constraints.py tests/lib/test_constraints.py
git commit -m "feat(constraints): evaluate — no_repeat, the bookends, exclude"
```

---

### Task 3: `EDL.constraints` — the carrier

**Files:**
- Modify: `scripts/lib/edl.py` (import, the `EDL` field + `__post_init__` check, `from_dict`, `to_dict`, `to_markdown`)
- Test: `tests/lib/test_edl.py`

**Interfaces:**
- Consumes: Task 2's `ConstraintReport`.
- Produces: `EDL(..., constraints: ConstraintReport | None = None)`, round-tripped under the `"constraints"` key and rendered as an `## Editorial rules` section of `EDL.md`. Task 4 sets it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py` (reuse the file's existing episode helper — if it has one named differently from `_ep()`, use that name instead):

```python
from scripts.lib.constraints import ConstraintReport, Violation


def _report(ok=True):
    rules = ({"kind": "no_repeat", "stated": "эпизоды не должны повторяться"},)
    vio = () if ok else (Violation(rule_index=0, kind="no_repeat",
                                   stated="эпизоды не должны повторяться",
                                   message="episodes 0, 1 are all from A.mp4 [0.00s–10.00s]"),)
    return ConstraintReport(rules=rules, violations=vio)


def test_edl_carries_the_constraint_report_through_a_round_trip():
    edl = EDL(episodes=(_ep(),), constraints=_report())
    back = EDL.from_dict(edl.to_dict())
    assert back.constraints == _report() and back.constraints.ok


def test_edl_without_constraints_round_trips_as_none():
    # None means NOT EVALUATED (no CONSTRAINTS.json), never "passed" — the SP1
    # hand-authored front door lands here.
    edl = EDL(episodes=(_ep(),))
    assert edl.to_dict()["constraints"] is None
    assert EDL.from_dict(edl.to_dict()).constraints is None


def test_edl_rejects_a_non_report_constraints_value():
    with pytest.raises(ValueError, match="ConstraintReport"):
        EDL(episodes=(_ep(),), constraints={"rules": []})


def test_markdown_lists_the_rules_and_says_they_held():
    md = EDL(episodes=(_ep(),), constraints=_report()).to_markdown()
    assert "## Editorial rules" in md
    assert "эпизоды не должны повторяться" in md and "no_repeat" in md
    assert "1 checked, none broken" in md


def test_markdown_shows_a_broken_rule():
    md = EDL(episodes=(_ep(),), constraints=_report(ok=False)).to_markdown()
    assert "**Broken:**" in md and "episodes 0, 1" in md


def test_markdown_omits_the_section_when_there_are_no_rules():
    md = EDL(episodes=(_ep(),), constraints=ConstraintReport()).to_markdown()
    assert "## Editorial rules" not in md
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -k constraint -q`
Expected: FAIL — `TypeError: EDL.__init__() got an unexpected keyword argument 'constraints'`.

- [ ] **Step 3: Implement**

In `scripts/lib/edl.py`:

1. Add the import beside the existing `from scripts.lib.moodpreset import VarietyReport`:

```python
from scripts.lib.constraints import ConstraintReport
```

2. Add the field to `EDL`, directly after `variety` and before `provenance`:

```python
    constraints: ConstraintReport | None = None   # design 2026-08-07 §8. None = never
                                                  # evaluated (no CONSTRAINTS.json beside
                                                  # project.json), never "passed"
```

3. In `EDL.__post_init__`, after the `variety` check:

```python
        if self.constraints is not None and not isinstance(self.constraints, ConstraintReport):
            raise ValueError(f"EDL.constraints must be a ConstraintReport or None, got "
                             f"{type(self.constraints).__name__} — re-run edit_plan build")
```

4. In `EDL.from_dict`'s `return cls(...)`, add after the `variety=` line:

```python
                   constraints=(ConstraintReport.from_dict(d["constraints"])
                                if d.get("constraints") else None),
```

5. In `EDL.to_dict`'s literal, after `"variety"`:

```python
             "constraints": self.constraints.to_dict() if self.constraints is not None else None,
```

6. In `EDL.to_markdown`, after the whole `if self.variety is not None:` block and before `return "\n".join(lines)`:

```python
        # Rendered only when rules exist: an empty rule list is worth nothing to a human
        # reader, and EDL.json already distinguishes "no file" (null) from "no rules" ([]).
        if self.constraints is not None and self.constraints.rules:
            c = self.constraints
            lines += ["", "## Editorial rules", ""]
            lines += [f"- `{r.get('kind')}` — {r.get('stated')}" for r in c.rules]
            if c.violations:
                lines += [""] + [f"**Broken:** {v.message}" for v in c.violations]
            else:
                lines += ["", f"{len(c.rules)} checked, none broken."]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: PASS, whole file green.

- [ ] **Step 5: Run the fast suite and commit**

```bash
.venv/bin/python -m pytest tests/ -m "not integration" -q
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat(edl): carry the constraint report into EDL.json and EDL.md"
```

---

### Task 4: the projection, the discovery, and the gate

**Files:**
- Modify: `scripts/edit_plan.py` (imports, `_placed`, `build_edl`, `write_edit_plan`)
- Test: `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: Task 0's `shot_at`, Task 1's `Constraints`, Task 2's `Placed`/`evaluate`, Task 3's `EDL.constraints`.
- Produces: `build_edl(..., rules: Constraints | None = None)` (keyword-only, beside `aspect`/`preset`) and `write_edit_plan`'s `{"status": "stop_and_report", "finding": {"reason": "constraint-violation", …}}`.

**Naming note for the implementer:** the parameter is `rules`, not `constraints`, because `EDL.constraints` is the *report* while this is the *rule set* — the same split as `preset` (input) → `variety` (report). Task 6 syncs the design's §5 snippet to this name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`:

```python
from scripts.lib.constraints import Constraints


def _cut_footage():
    # One clip, a cut at 10.0. Windows 0 and 1 sit in the SAME shot [0, 10) without
    # overlapping; window 2 is in the later shot [10, 20).
    return Footage(clips=[_clip(source="A.mp4", dur=20.0, scene_cuts=[10.0], windows=[
        FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=12.0, dur=2.0, shot_type="close", people=1, motion=0.3,
                      shake=0.0)])])


def _two_from_one_shot():
    return {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}


def _no_repeat_rules():
    return Constraints.from_dict({"rules": [
        {"kind": "no_repeat", "stated": "эпизоды не должны повторяться"}]})


def test_build_edl_without_rules_leaves_constraints_unevaluated():
    edl = edit_plan.build_edl(_cut_footage(), _two_from_one_shot())
    assert edl.constraints is None


def test_build_edl_measures_a_repeat_but_does_not_refuse():
    edl = edit_plan.build_edl(_cut_footage(), _two_from_one_shot(), rules=_no_repeat_rules())
    assert edl.constraints is not None and not edl.constraints.ok
    assert edl.constraints.violations[0].kind == "no_repeat"


def test_build_edl_passes_two_episodes_from_different_shots():
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 2, "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(_cut_footage(), sel, rules=_no_repeat_rules())
    assert edl.constraints.ok


def test_a_rule_pin_does_not_satisfy_a_bookend():
    # "largest" is a HERO_RULES tracking target, not a person — it must project to
    # None, so the bookend rule refuses instead of being fooled by the string.
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]})
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead",
                         "grid": "thirds", "hero": "largest"}]}
    edl = edit_plan.build_edl(_cut_footage(), sel, rules=rules)
    assert not edl.constraints.ok and "pins no cast name" in edl.constraints.violations[0].message


def test_a_cast_name_pin_satisfies_a_bookend():
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]})
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead",
                         "grid": "thirds", "hero": "Serge"}]}
    assert edit_plan.build_edl(_cut_footage(), sel, rules=rules).constraints.ok


def _write_rules(tmp_path, rules_dict):
    (tmp_path / "CONSTRAINTS.json").write_text(json.dumps(rules_dict))


def test_write_edit_plan_finds_the_rule_file_beside_project_json_and_refuses(tmp_path):
    fj, sj, pj = _write_inputs(tmp_path, _two_from_one_shot(), footage=_cut_footage())
    _write_rules(tmp_path, {"rules": [{"kind": "no_repeat",
                                       "stated": "эпизоды не должны повторяться"}]})
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "constraint-violation"
    assert "эпизоды не должны повторяться" in res["finding"]["problems"][0]
    assert not (out / "EDL.json").exists() and not (out / "EDL.md").exists()


def test_write_edit_plan_without_a_rule_file_writes_and_leaves_constraints_null(tmp_path):
    fj, sj, pj = _write_inputs(tmp_path, _two_from_one_shot(), footage=_cut_footage())
    out = tmp_path / "out"
    assert edit_plan.write_edit_plan(fj, sj, pj, str(out))["status"] == "written"
    assert json.loads((out / "EDL.json").read_text())["constraints"] is None


def test_write_edit_plan_records_the_rules_that_held(tmp_path):
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 2, "composition": "lead", "grid": "thirds"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel, footage=_cut_footage())
    _write_rules(tmp_path, {"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    out = tmp_path / "out"
    assert edit_plan.write_edit_plan(fj, sj, pj, str(out))["status"] == "written"
    edl = EDL.from_json(str(out / "EDL.json"))
    assert edl.constraints.ok and edl.constraints.rules[0]["stated"] == "no repeats"
    assert "## Editorial rules" in (out / "EDL.md").read_text()


def test_a_broken_rule_outranks_a_variety_gap(tmp_path):
    # Both gates would fire on this cut (one shot twice, and it takes no close
    # window while the footage offers three). The USER's rule is the reported one.
    close = [FootageWindow(start=float(12 + i), dur=0.5, shot_type="close", people=1,
                           motion=0.3, shake=0.0, subject_w=0.8, subject_h=0.8)
             for i in range(3)]
    wide = [FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0, subject_w=0.02, subject_h=0.05),
            FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0, subject_w=0.02, subject_h=0.05)]
    footage = Footage(clips=[_clip(source="A.mp4", dur=20.0, res=(3840, 2160),
                                   scene_cuts=[10.0], windows=wide + close)])
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel, footage=footage)
    _write_rules(tmp_path, {"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    res = edit_plan.write_edit_plan(fj, sj, pj, str(tmp_path / "out"))
    assert res["finding"]["reason"] == "constraint-violation"


def test_write_edit_plan_propagates_a_corrupt_rule_file(tmp_path):
    fj, sj, pj = _write_inputs(tmp_path, _two_from_one_shot(), footage=_cut_footage())
    (tmp_path / "CONSTRAINTS.json").write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        edit_plan.write_edit_plan(fj, sj, pj, str(tmp_path / "out"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "constraint or rule or shot" -q`
Expected: FAIL — `build_edl() got an unexpected keyword argument 'rules'`.

- [ ] **Step 3: Implement**

In `scripts/edit_plan.py`:

1. Extend the imports:

```python
from scripts.lib.constraints import Constraints, Placed, evaluate as check_constraints
from scripts.lib.models import HERO_RULES
```

(`evaluate` is aliased because `moodpreset.evaluate` is already called in this file; two bare `evaluate`s would read as one function.)

2. Add the projection helper directly above `build_edl`:

```python
def _placed(clip: FootageClip, ep: EDLEpisode) -> Placed:
    """Project one episode onto what an editorial rule can judge (design §4).

    A hero reaches the projection only when it is a cast NAME: a str that is not one
    of models.HERO_RULES. A bbox tuple, a track id, and "largest" all name a tracking
    target rather than a person, so they project to None — which a bookend rule reads
    as unsatisfied, never as satisfied."""
    hero = ep.hero if isinstance(ep.hero, str) and ep.hero not in HERO_RULES else None
    return Placed(source=ep.source, shot=clip.shot_at(ep.start), hero=hero)
```

3. In `build_edl`'s signature, add `rules` beside the other keyword-only knobs:

```python
def build_edl(footage: Footage, selection: dict, pacing: Spine | None = None,
              cast: str | None = None, *, aspect: tuple[int, int] | None = None,
              preset: MoodPreset | None = None,
              rules: Constraints | None = None) -> EDL:
```

4. Add this paragraph at the end of `build_edl`'s docstring:

```
    `rules` (design 2026-08-07, keyword-only) are the project's editorial constraints.
    When supplied, every episode is projected onto a `Placed` as it is resolved and
    constraints.evaluate compares the cut against the rules into the returned
    EDL.constraints. Absent rules leave EDL.constraints None, which reads as "not
    evaluated", never as "passed". As with variety, build_edl only MEASURES; the
    refusal lives one level up in write_edit_plan, so a caller building an EDL in
    memory still gets the finding.
```

5. Inside `build_edl`, collect the projection in the existing episode loop. Add `placed: list[Placed] = []` beside `episodes: list[EDLEpisode] = []`, and replace the loop's final `episodes.append(...)` line with:

```python
        ep = window_to_episode(clip, fw, start_offset=start_offset, **ed)
        episodes.append(ep)
        placed.append(_placed(clip, ep))
```

6. After the `variety = ...` block and before the `return EDL(...)`:

```python
    # After pacing: binding rewrites `dur` only, which none of the four rule kinds
    # reads — but evaluating the FINAL episode list keeps the report describing the
    # EDL that is actually written.
    cons = check_constraints(rules, tuple(placed), footage) if rules is not None else None
```

7. Extend the `return EDL(...)` call with `constraints=cons`.

8. In `write_edit_plan`, load the rules right after `cfg = ProjectConfig.from_json(project_path)`:

```python
    rules_path = Path(project_path).parent / "CONSTRAINTS.json"
    rules = Constraints.from_json(rules_path) if rules_path.exists() else None
    if rules is not None:
        _log(f"constraints: {len(rules.rules)} editorial rule(s) from {rules_path}")
```

9. Pass it through the `build_edl(...)` call: `rules=rules`.

10. Immediately after that call — **before** the variety block — add the gate:

```python
    c = edl.constraints
    if c is not None and not c.ok:
        # The user's own stated rule outranks the preset's inference, so its finding is
        # the one the caller sees. No waiver exists by design: the only way past is the
        # user editing or deleting the rule (design §5).
        return {"status": "stop_and_report",
                "finding": {"reason": "constraint-violation", "episode_idx": None,
                            "problems": [f"{v.stated} ({v.kind}): {v.message}"
                                         for v in c.violations]}}
```

11. Extend `write_edit_plan`'s docstring with:

```
    Editorial constraints (design 2026-08-07) are found BY CONVENTION beside
    project.json as CONSTRAINTS.json — there is no flag to forget. Absent means no
    rules; present means enforced on every invocation, which is what makes a stated
    rule survive a re-cut. A broken rule stops here with its own reason
    `constraint-violation`, before the variety gate and before preflight, and there is
    no waiver: the rule is the user's, not the agent's to overrule.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q`
Expected: PASS, whole file green.

- [ ] **Step 5: Run the fast suite and commit**

```bash
.venv/bin/python -m pytest tests/ -m "not integration" -q
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat(edit-plan): enforce CONSTRAINTS.json found beside project.json"
```

---

### Task 5: the end-to-end proof

**Files:**
- Modify: `tests/integration/test_edit_plan.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 0–4. Produces nothing new.

Why this exists on top of Task 4's unit tests: the discovery path (`project.json`'s
directory → `CONSTRAINTS.json`) and the "nothing written" guarantee are the two
things a wiring regression would break silently, and this file is where the SP3
stage is exercised the way the router runs it.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_edit_plan.py`, mirroring the variety test above it:

```python
def _repeat_footage_json(tmp_path, source):
    # One 20s clip with a cut at 10.0s. Windows 0 and 1 live in the SAME shot and do
    # not overlap in time; window 2 is in the later shot.
    windows = [
        FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                      shake=0.0, subject_w=0.4, subject_h=0.5),
        FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                      shake=0.0, subject_w=0.4, subject_h=0.5),
        FootageWindow(start=12.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                      shake=0.0, subject_w=0.4, subject_h=0.5)]
    f = Footage(clips=[FootageClip(source=source, dur=20.0, res=(1920, 1080), fps=30.0,
                                   scene_cuts=[10.0], windows=windows)])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def test_sp3_refuses_a_repeat_the_user_forbade_and_records_the_rule_when_it_holds(tmp_path):
    """A rule stated once, in a file nobody passes on the command line, still binds:
    edit_plan finds CONSTRAINTS.json beside project.json, refuses the cut that breaks
    it, writes nothing, and — once the cut is fixed — records the rule inside the
    stamped EDL.json (design §6, §8)."""
    source = "clip.mp4"
    fp = _repeat_footage_json(tmp_path, source)
    pp = _project_json(tmp_path)          # writes project.json into tmp_path
    (tmp_path / "CONSTRAINTS.json").write_text(json.dumps(
        {"rules": [{"kind": "no_repeat", "stated": "эпизоды не должны повторяться"}]}))
    sp = tmp_path / "selection.json"
    sp.write_text(json.dumps({"episodes": [
        {"source": source, "window": w, "composition": "lead", "grid": "thirds"}
        for w in (0, 1)]}))               # both from the shot [0, 10)

    stop = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "constraint-violation"
    assert not (tmp_path / "EDL.json").exists()

    sp.write_text(json.dumps({"episodes": [
        {"source": source, "window": w, "composition": "lead", "grid": "thirds"}
        for w in (0, 2)]}))               # one from each shot
    ok = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert ok["status"] == "written"

    edl = EDL.from_json(tmp_path / "EDL.json")        # provenance check passes
    assert edl.constraints.ok
    # a TUPLE of dicts: to_dict writes a JSON list, and ConstraintReport.from_dict
    # normalises it back with tuple(...) — the same round-trip shape `rules` has in memory
    assert edl.constraints.rules == ({"kind": "no_repeat",
                                      "stated": "эпизоды не должны повторяться"},)
    assert "## Editorial rules" in (tmp_path / "EDL.md").read_text()
```

- [ ] **Step 2: Run it — with Tasks 0–4 in place it must pass**

Run: `.venv/bin/python -m pytest tests/integration/test_edit_plan.py -k constraint -q`
Expected: PASS — this task adds no production code, so a failure here is a real wiring gap in Task 4. Fix `edit_plan.py`, never the test.

- [ ] **Step 3: Run the whole integration file and commit**

```bash
.venv/bin/python -m pytest tests/integration/test_edit_plan.py -q
git add tests/integration/test_edit_plan.py
git commit -m "test(edit-plan): the rule file binds a re-cut end-to-end"
```

---

### Task 6: skills, docs, the mutation battery, and the full suite

**Files:**
- Modify: `skills/edit-plan/SKILL.md`, `skills/using-montage/SKILL.md`
- Modify: `CLAUDE.md` (two registry rows), `docs/build-status.md`, `docs/pipeline-map.md`, `docs/fixes-backlog.md`, `docs/cinematic-quality-playbook.md`
- Modify: `docs/specs/2026-08-07-editorial-constraints-design.md` (§5's parameter name)

- [ ] **Step 1: Run the mutation battery**

Each item below applies ONE change to the shipped code, runs
`.venv/bin/python -m pytest tests/ -m "not integration" -q`, records which tests fail,
then reverts with `git checkout -- <file>`. A mutation that no test catches is a
coverage hole: add the missing test before continuing. Record the table in the commit
message body or the task report.

| # | mutation | must be caught by |
|---|----------|-------------------|
| 1 | `constraints._no_repeat` keys on `(p.source, p.shot[0])` → `(p.source,)` | the two-different-shots test (would false-positive) |
| 2 | `_no_repeat` keys on the episode's start instead of the shot | `test_no_repeat_fires_on_two_episodes_from_one_shot_that_do_not_overlap` |
| 3 | `_bookend` returns `None` when `p.hero is None` | `test_an_unpinned_edge_episode_is_a_violation_not_a_pass` |
| 4 | `edit_plan._placed` drops the `not in HERO_RULES` clause | `test_a_rule_pin_does_not_satisfy_a_bookend` |
| 5 | `footage.shot_at` uses `c < t` instead of `c <= t` | `test_shot_at_on_a_cut_belongs_to_the_later_shot_like_room_after` |
| 6 | `write_edit_plan`'s gate moved AFTER the variety block | `test_a_broken_rule_outranks_a_variety_gap` |
| 7 | `write_edit_plan` logs the violation and continues instead of returning | the "nothing written" asserts in Task 4 and Task 5 |
| 8 | `Constraints.__post_init__` drops the singleton check | `test_a_second_singleton_rule_is_refused_as_a_contradiction` |
| 9 | missing file → `Constraints()` instead of `None` | `test_write_edit_plan_without_a_rule_file_writes_and_leaves_constraints_null` |

- [ ] **Step 2: Update `skills/edit-plan/SKILL.md`**

Add a section after the existing variety-gate guidance:

```markdown
## Editorial rules the user stated (CONSTRAINTS.json)

`edit_plan build` reads `CONSTRAINTS.json` from the folder holding `project.json`.
There is no flag: if the file is there, its rules bind this cut and every re-cut.
A broken rule stops the build with `"reason": "constraint-violation"` and writes
nothing. **There is no waiver** — the rule is the user's, so only the user changes
or deletes it. Report the refusal verbatim and fix the cut.

When the user states an editorial rule, write it down immediately, in their own
words:

```json
{"rules": [
  {"kind": "no_repeat", "stated": "эпизоды не должны повторяться"},
  {"kind": "open_with", "hero": "Serge", "stated": "дрон-сцена с Сержем открывает"},
  {"kind": "close_with", "hero": "Anna", "stated": "вторая дрон-сцена закрывает"},
  {"kind": "exclude", "source": "clips/DJI_0042.MP4", "window": 7, "stated": "этот дубль не брать"}
]}
```

- `no_repeat` — no two episodes from one shot (a scene-cut segment). Two windows of
  the same drone pass are a repeat even when their spans do not overlap.
- `open_with` / `close_with` — the first / last episode must pin that cast name.
  A bbox, a track id, or `"largest"` does NOT satisfy it: those name a tracking
  target, not a person. Pin the name.
- `exclude` — with `window`, bans that window's whole shot; without it, the clip.

Only these four kinds exist, and an unknown `kind` is refused at load. If the user
states a rule that does not fit — "don't put two drone shots back to back" — say so
out loud instead of inventing a field: it cannot be stored, so it cannot be enforced.
```

- [ ] **Step 3: Update `skills/using-montage/SKILL.md`**

At the checkpoints where the user gives editorial feedback (CP1/CP2 and the CP3
review), add:

```markdown
When the user states an editorial rule that must hold across re-cuts ("one hero
opens, the other closes", "no repeated episodes", "don't use that take"), append it
to `CONSTRAINTS.json` beside `project.json` before continuing — see the edit-plan
SKILL for the four kinds. `edit_plan build` enforces it on every later cut without
being told. A rule outside the four kinds cannot be stored: tell the user it will
not be enforced instead of leaving them to assume it is.
```

- [ ] **Step 4: Sync the design's §5 parameter name**

In `docs/specs/2026-08-07-editorial-constraints-design.md` §5, change
`build_edl(..., constraints: Constraints | None = None)` to
`build_edl(..., rules: Constraints | None = None)` and add the half-sentence
"(named `rules`, since `EDL.constraints` is the report it produces)".

- [ ] **Step 5: Update the docs**

- `CLAUDE.md` — two rows in the Quick Reference table, in the house style (one row
  for the design, one for the plan), placed after the intake motion-scoring rows.
- `docs/build-status.md` — a Done entry (what shipped, the four kinds, the discovery
  convention, no waiver, and the §10 limits: `edl_to_reel` bypasses the gate, and a
  rule outside the vocabulary has nowhere to live) + strike #14 from the Next-action
  list, leaving the hero-conditioned re-scan and #3 per-episode QC as what remains
  of P3. Update `_Last updated:_`.
- `docs/pipeline-map.md` — note on stage 5.7 that it now reads `CONSTRAINTS.json`.
- `docs/fixes-backlog.md` #14 — status `✅ LANDED 2026-08-07`, naming the design and
  plan, and stating plainly which half is enforced (the four kinds) and which is not.
- `docs/cinematic-quality-playbook.md` §4 priority 3 — move #14 out of the open list.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: everything green, no golden moved (this slice changes no measurement and
no artifact that an existing golden pins — an `EDL.json` gains a `"constraints":
null` key, so if a golden pins the EDL dict WHOLE it will move; re-pin it only after
confirming the only difference is that key).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs(editorial-constraints): skills, registry, status, backlog"
```

---

## Self-Review

**Spec coverage:** §1 (persist + bind every re-cut) → Tasks 4, 6; §2 (the shot unit)
→ Task 0; §3 (file + vocabulary + refusals) → Task 1; §4 (module + projection
boundary) → Tasks 2, 4; §5 (measure/refuse split, no waiver, order vs variety) →
Task 4; §6 (discovery) → Tasks 4, 5; §7 (the four checks) → Task 2; §8 (the record)
→ Task 3; §9 (validation) → Tasks 0–5; §10/§11 (honest limits, deferred) → Task 6's
docs.

**Placeholders:** none — every step carries its code or its exact edit.

**Type consistency:** `Rule`/`Constraints` (Task 1) are consumed unchanged by
`evaluate` (Task 2), `EDL.constraints` (Task 3) and `build_edl(rules=)` (Task 4).
`Placed(source, shot, hero)` is produced by `edit_plan._placed` and consumed by the
three checkers. `ConstraintReport.ok` is the single pass/fail predicate used by both
`write_edit_plan` and `to_markdown`.
