# Threshold Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the twelve unreachable `ReelCheckSpec`/`CheckSpec` thresholds authorable through one convention file beside `project.json`, where a value without a written reason is refused at load, and carry that reason to the verdict, the attestation and the inspector.

**Architecture:** A new pure `scripts/lib/gates.py` derives its vocabulary from the two dataclasses, validates an authored value by constructing a probe instance and letting the existing `__post_init__` raise, and renders the record. `ReelManifest.gates` carries the whole authored set (both scopes) so the `EPISODES.json` round trip reaches `build_reel`. `edl_to_reel` is the only finder. No threshold's default moves.

**Tech Stack:** Python 3.12, dataclasses, pytest. No new dependency.

## Global Constraints

- **Source of truth:** [docs/specs/2026-09-30-threshold-surface-design.md](../specs/2026-09-30-threshold-surface-design.md). Where this plan and the design disagree, the design governs — report the conflict rather than picking.
- **No threshold default changes.** Not one of the twelve values in `models.py` moves in this slice (design §3).
- **With no `GATES.json` present, every artifact is byte-identical** and every pre-existing test passes untouched. This is the acceptance control, not an aspiration.
- **Refuse, never warn, never store-and-ignore.** Every bad input in design §2.2 raises `ValueError` naming the file path and the remedy, per [coding-standards.md](../coding-standards.md).
- **The vocabulary is DERIVED, never typed.** `gates.FIELDS` comes from `dataclasses.fields()` on the two spec classes minus a named exempt set. A hand-written list of twelve names is a defect in this slice.
- **`PYTHONDONTWRITEBYTECODE=1`** on every mutation-battery run (a one-byte edit can match the previous file's size and mtime-second and CPython serves the stale `.pyc`).
- **zsh does not word-split an unquoted variable** — a pytest selection held in a shell variable arrives as ONE argument and prints `no tests ran`, which reads exactly like a non-discriminating mutation row. Write selections out literally.
- **Scripts run as modules** (`pythonpath = .`); the interpreter is `.venv/bin/python`.
- **Never install anything.** No `brew`/`pip`/`uv`/`npm` install, no `setup.sh`, no `claude plugin update`. Verification is read-only plus `pytest`.
- **Never `git checkout --`, `git restore`, `git reset --hard` or `git stash`.** To undo a mutation of committed content use `git show HEAD:<path> > <path>`; when the file you are mutating is NOT committed, save your own copy first (`cp <path> <path>.bak`) and restore from that. Work on an otherwise-clean tree and re-check `git diff --stat` after restoring.
- **`git add` named paths only, never `git add -A`.**
- **One pre-existing test is RED for a sanctioned reason and is not yours to fix:** `tests/integration/test_verify_runtime.py::test_real_runtime_is_ready`. It stays red until the operator runs `claude plugin update video-grid@video-grid` and restarts Claude Code. That is the 0.14.0 check working as designed. Report suite counts as `N passed / 1 skipped / 1 failed (sanctioned)`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lib/gates.py` | **NEW.** Derived vocabulary, `Gate`/`Gates`, the six refusals, the per-class kwargs subset, the record. Pure; the only IO is `from_json`. |
| `scripts/lib/models.py` | `ReelManifest.gates` field + validation + round trip; `check_spec` applies its own subset. |
| `scripts/process_episode.py` | `process_episode(..., gates=…)` reaching the `CheckSpec` construction at line 565. |
| `scripts/check_episode.py` | `--gates PATH` on the standalone judge; the `black_frames`/`grade_damage` details name an authored bar. |
| `scripts/check_reel.py` | The `loudness`, `grade_faithful` and length details name an authored bar. |
| `scripts/edl_to_reel.py` | The one finder (beside `project_path`), threaded into the pool and onto the manifest. |
| `scripts/build_reel.py` | The reprocess arm passes `rm.gates` through unfiltered. |
| `scripts/lib/provenance.py` | `Attestation.gates`. |
| `scripts/deliver.py` | Fills it. |
| `scripts/montage.py` | `_gates`, the three-state inspector row. |
| `tests/test_gates.py` | **NEW.** The pure module, incl. the derived-vocabulary machine check. |
| `tests/integration/test_threshold_surface.py` | **NEW.** End-to-end, both scopes, and the no-file control. |

---

### Task 1: `scripts/lib/gates.py` — the derived vocabulary and the six refusals

**Files:**
- Create: `scripts/lib/gates.py`
- Create test: `tests/test_gates.py`

**Interfaces:**
- Consumes: `scripts.lib.models.ReelCheckSpec`, `models.CheckSpec`, `models._ADVISORY_CHECKS`.
- Produces: `gates.FIELDS: tuple[str, ...]`, `gates.BLOCKING: frozenset[str]`, `gates.OF_CHECK: dict[str, str]`, `gates.AUTHORED_ELSEWHERE: dict[str, str]`, `gates.Gate(field, value, why)`, `gates.Gates(gates: tuple[Gate, ...])` with `from_dict(d, *, where)` / `from_json(path)` / `to_dict()` / `for_spec(spec_cls) -> dict` / `record() -> list[dict]` / `reasons() -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gates.py
"""The authored-gate surface (design 2026-09-30)."""
import json

import pytest

from dataclasses import fields as dc_fields

from scripts.lib import gates
from scripts.lib.models import CheckSpec, ReelCheckSpec, _ADVISORY_CHECKS


def test_the_vocabulary_is_derived_from_the_two_spec_classes_not_typed():
    # The row's twelve, arrived at from the dataclasses (design §0.6). This test is
    # what fails the day a thirteenth threshold lands without a decision about it.
    names = {f.name for f in dc_fields(ReelCheckSpec)} | {f.name for f in dc_fields(CheckSpec)}
    assert len(names) == 17
    assert set(gates.FIELDS) == names - set(gates.AUTHORED_ELSEWHERE)
    assert len(gates.FIELDS) == 12


def test_every_gateable_field_names_the_check_it_sets_the_bar_for():
    assert set(gates.OF_CHECK) == set(gates.FIELDS)


def test_the_blocking_set_is_derived_from_the_advisory_registry():
    assert gates.BLOCKING == frozenset(
        n for n, c in gates.OF_CHECK.items() if c not in _ADVISORY_CHECKS)
    assert gates.BLOCKING == {"loudness_target", "loudness_tol", "grade_residual_max",
                              "length_retime_max", "black_floor", "black_rel",
                              "entropy_floor"}


def test_an_authored_value_reaches_the_class_that_owns_it():
    g = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "log profile"},
                               "beat_tol": {"value": 0.08, "why": "no click track"}})
    assert g.for_spec(CheckSpec) == {"entropy_floor": 0.85}
    assert g.for_spec(ReelCheckSpec) == {"beat_tol": 0.08}


def test_a_non_object_document_is_refused():
    with pytest.raises(ValueError, match="GATES.json"):
        gates.Gates.from_dict([{"entropy_floor": 0.85}])


def test_an_unknown_field_is_refused_and_the_message_names_the_vocabulary():
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entrpy_floor": {"value": 0.85, "why": "typo"}})
    assert "entrpy_floor" in str(e.value)
    assert "entropy_floor" in str(e.value)


def test_a_field_authored_elsewhere_is_refused_and_the_message_says_where():
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"variety_min": {"value": 4, "why": "short reel"}})
    assert "variety_min" in str(e.value)
    assert "ReelManifest.variety_min" in str(e.value)


def test_an_entry_that_is_a_bare_number_is_refused():
    with pytest.raises(ValueError, match="value.*why|why.*value"):
        gates.Gates.from_dict({"entropy_floor": 0.85})


@pytest.mark.parametrize("why", [None, "", "   ", 7])
def test_a_value_without_a_written_reason_is_refused(why):
    # Design §1: the reason is structurally required, not conventionally expected.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": why}})
    assert "why" in str(e.value)


def test_a_value_the_owning_dataclass_rejects_is_refused_by_that_dataclass():
    # entropy_floor must be a ratio in (0, 1]; the loader does not re-implement that.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entropy_floor": {"value": 1.5, "why": "louder"}})
    msg = str(e.value)
    assert "GATES.json" in msg and "entropy_floor" in msg
    assert "ratio in (0, 1]" in msg     # the existing CheckSpec.__post_init__ text


def test_from_json_names_the_path_it_could_not_load(tmp_path):
    p = tmp_path / "GATES.json"
    p.write_text("{not json")
    with pytest.raises(ValueError) as e:
        gates.Gates.from_json(p)
    assert str(p) in str(e.value)


def test_the_record_carries_value_default_scope_blocking_and_why():
    g = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "log profile"},
                               "beat_tol": {"value": 0.08, "why": "no click track"}})
    by = {r["field"]: r for r in g.record()}
    assert by["entropy_floor"] == {"field": "entropy_floor", "value": 0.85,
                                   "default": 0.90, "scope": "episode",
                                   "blocking": True, "why": "log profile"}
    assert by["beat_tol"] == {"field": "beat_tol", "value": 0.08, "default": 0.05,
                              "scope": "reel", "blocking": False,
                              "why": "no click track"}


def test_an_empty_document_is_legal_and_authors_nothing():
    g = gates.Gates.from_dict({})
    assert g.for_spec(ReelCheckSpec) == {} and g.for_spec(CheckSpec) == {}
    assert g.record() == [] and g.to_dict() == {}


def test_to_dict_round_trips_through_from_dict():
    d = {"black_rel": {"value": 0.2, "why": "night shoot"}}
    assert gates.Gates.from_dict(gates.Gates.from_dict(d).to_dict()).to_dict() == d


def test_reasons_maps_field_to_why():
    g = gates.Gates.from_dict({"black_rel": {"value": 0.2, "why": "night shoot"}})
    assert g.reasons() == {"black_rel": "night shoot"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gates.py -q`
Expected: collection error — `No module named 'scripts.lib.gates'`.

- [ ] **Step 3: Write the module**

```python
# scripts/lib/gates.py
"""Authored gate thresholds (design docs/specs/2026-09-30-threshold-surface-design.md).

Twelve thresholds decide whether a reel or an episode ships, and until this module
none of them was reachable from any authoring surface: no flag, no manifest field,
no file. The only way to move a bar was to edit models.py — which is to say, to
patch the engine. A tool whose bars move only by patching it is a tool for the one
shoot its bars were measured on.

Two things here are DERIVED rather than typed, and both must stay that way:

- FIELDS, from the two spec classes' own dataclass fields minus the five names
  authored elsewhere (design §0.6). A threshold added to either class joins
  GATES.json the day it lands, with no second list to update — the property
  provenance.spec_overrides already has, for the same reason.
- BLOCKING, from OF_CHECK against models._ADVISORY_CHECKS. The partition between a
  preference and a waiver has one source, and it is the registry the report itself
  keys on.

A value without a written reason is refused AT LOAD, and that is the whole design
(§1). A blocking bar is a waiver in numeric clothing; this repo has already watched
one widened 12 -> 44 -> 56 until the gate it belonged to was off in all but name
(colour-convergence-retire design §0.1). Requiring the reason structurally is what
separates this from a convention nothing can check.

Pure: dicts in, dicts out. The only IO is from_json.
"""
import json
from dataclasses import dataclass, fields
from pathlib import Path

from scripts.lib.models import CheckSpec, ReelCheckSpec, _ADVISORY_CHECKS

#: Names that sit on a check spec but are authored somewhere else entirely.
#: Refused by name rather than ignored: a value silently dropped here would read
#: as authored, which is the worse of the two failures.
AUTHORED_ELSEWHERE = {
    "target_dur": "the EDL — EDL.target_dur, which edit_plan._back_edge_target "
                  "computes from the footage",
    "variety_min": "the reel manifest — ReelManifest.variety_min, which is the "
                   "'variety_min' key of EPISODES.json. No producer sets it today",
    "composition": "each episode's own manifest (Manifest.composition)",
    "grid": "each episode's own manifest (Manifest.grid)",
    "attempt": "the retry loop's own counter — it is not an author's value",
}

#: field -> the check whose bar it sets. Not documentation: BLOCKING is derived
#: from it, so the advisory/blocking partition has exactly one source.
OF_CHECK = {
    "beat_tol": "beat",
    "clip_tol": "key_action",
    "bar_symmetry_tol": "pad_bars",
    "layout_jump_max": "transitions",
    "chroma_spread_max": "chroma_spread",
    "loudness_target": "loudness",
    "loudness_tol": "loudness",
    "grade_residual_max": "grade_faithful",
    # NOT "brief_length", though that advisory check borrows this value as a band.
    # build_reel reads the same field to decide how much shortfall it ABSORBS by
    # re-timing the target instead of escalating (design §0.1), so widening it
    # converts a blocking length failure into a silent re-target. The blast radius
    # is the driver's, and "length" is the name that carries it.
    "length_retime_max": "length",
    # "black_frames", NOT "black": the episode gate's key is black_frames
    # (check_episode.py:412) and `black` is a REEL check (check_reel.py:436) that
    # reads no threshold. An episode check also has no advisory registry, so it
    # blocks by absence rather than by membership.
    "black_floor": "black_frames",
    "black_rel": "black_frames",
    "entropy_floor": "grade_damage",
}

_OWNER: dict = {}
for _cls in (ReelCheckSpec, CheckSpec):
    for _f in fields(_cls):
        if _f.name not in AUTHORED_ELSEWHERE:
            _OWNER[_f.name] = _cls

#: The twelve, derived (design §0.6).
FIELDS = tuple(sorted(_OWNER))

#: The seven whose bar can stop a delivery.
BLOCKING = frozenset(n for n, c in OF_CHECK.items() if c not in _ADVISORY_CHECKS)

#: The minimum a probe instance of each class needs before an authored value can be
#: handed to its own __post_init__. Every name here is in AUTHORED_ELSEWHERE, which
#: is why the probe can never collide with a gateable field.
_PROBE_BASE = {
    ReelCheckSpec: {"target_dur": 1.0},
    CheckSpec: {"composition": "lead", "grid": "thirds", "target_dur": 1.0},
}

_SCOPE = {ReelCheckSpec: "reel", CheckSpec: "episode"}

_DEFAULTS = {cls: cls(**base) for cls, base in _PROBE_BASE.items()}


@dataclass(frozen=True)
class Gate:
    """One authored threshold and the reason it was authored."""
    field: str
    value: object
    why: str


@dataclass(frozen=True)
class Gates:
    """Every threshold an author moved, with each one's reason.

    Empty is the normal case and means every bar is its default — which is the
    behaviour that shipped before this module and is byte-identical to it.
    """
    gates: tuple[Gate, ...] = ()

    @classmethod
    def from_dict(cls, d: dict, *, where: str = "GATES.json") -> "Gates":
        if not isinstance(d, dict):
            raise ValueError(
                f"{where} must be an object mapping a threshold name to "
                f"{{'value': ..., 'why': ...}}, got {type(d).__name__}")
        out = []
        for name, entry in d.items():
            if name in AUTHORED_ELSEWHERE:
                raise ValueError(
                    f"{where} cannot set {name!r} — it is authored in "
                    f"{AUTHORED_ELSEWHERE[name]}. Setting it here would give it two "
                    f"homes and make one of them silent")
            if name not in _OWNER:
                raise ValueError(
                    f"{where} names {name!r}, which is not a gate threshold. The "
                    f"twelve are: {', '.join(FIELDS)}")
            if not isinstance(entry, dict) or set(entry) != {"value", "why"}:
                raise ValueError(
                    f"{where} entry {name!r} must be an object with exactly 'value' "
                    f"and 'why', got {entry!r}. A bare number is refused: moving a "
                    f"bar without recording why is what this file exists to prevent")
            why = entry["why"]
            if not (isinstance(why, str) and why.strip()):
                raise ValueError(
                    f"{where} entry {name!r} needs a non-empty 'why' — the reason a "
                    f"bar was moved is the record a later reader has to judge the "
                    f"delivery by, and it is required, not encouraged")
            owner = _OWNER[name]
            try:
                owner(**{**_PROBE_BASE[owner], name: entry["value"]})
            except ValueError as e:
                raise ValueError(
                    f"{where} entry {name!r} holds a value {owner.__name__} refuses: "
                    f"{e}") from e
            out.append(Gate(field=name, value=entry["value"], why=why.strip()))
        return cls(gates=tuple(out))

    @classmethod
    def from_json(cls, path: str | Path) -> "Gates":
        p = Path(path)
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{p} is not valid JSON ({e}) — fix the syntax, or "
                             f"delete the file to run every threshold at default") from e
        return cls.from_dict(d, where=str(p))

    def to_dict(self) -> dict:
        return {g.field: {"value": g.value, "why": g.why} for g in self.gates}

    def for_spec(self, spec_cls) -> dict:
        """The kwargs subset `spec_cls` owns — the call site never partitions."""
        return {g.field: g.value for g in self.gates if _OWNER[g.field] is spec_cls}

    def reasons(self) -> dict[str, str]:
        return {g.field: g.why for g in self.gates}

    def record(self) -> list[dict]:
        """The attestation row per authored gate (design §2.4)."""
        return [{"field": g.field, "value": g.value,
                 "default": getattr(_DEFAULTS[_OWNER[g.field]], g.field),
                 "scope": _SCOPE[_OWNER[g.field]],
                 "blocking": g.field in BLOCKING, "why": g.why}
                for g in self.gates]
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_gates.py -q`
Expected: PASS, 18 tests (14 plain plus the 4-case `why` parametrize).

- [ ] **Step 5: Confirm nothing else moved**

Run: `.venv/bin/python -m pytest tests/ -q -x --ignore=tests/integration`
Expected: the pre-existing unit tier, unchanged.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/gates.py tests/test_gates.py
git commit -m "feat: gates.py - the twelve thresholds, derived from the classes that own them"
```

---

### Task 2: `ReelManifest.gates` — one carrier for both scopes

**Files:**
- Modify: `scripts/lib/models.py` (`ReelManifest` field list, `__post_init__`, `check_spec`, `to_dict`, `from_dict`)
- Test: `tests/lib/test_models.py`

**Interfaces:**
- Consumes: `gates.Gates` from Task 1.
- Produces: `ReelManifest.gates: dict` (the raw `{field: {value, why}}` document, whole set, both scopes); `ReelManifest.check_spec` (a **property**, not a method) applying the reel subset.

**Import note:** `models.py` must NOT import `gates` at module scope — `gates` imports `models`. Import it inside the two methods that need it (`__post_init__`, `check_spec`), which is the same local-import shape `models.py` already uses where a cycle would otherwise form. If you find `models.py` has no such precedent, say so in your report rather than inventing a third pattern.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_reel_manifest_applies_its_authored_reel_gates_to_check_spec(one_episode):
    rm = ReelManifest(episodes=[one_episode], target_dur=10.0,
                      gates={"loudness_tol": {"value": 2.0, "why": "live room"}})
    assert rm.check_spec.loudness_tol == 2.0
    assert rm.check_spec.loudness_target == -14.0        # untouched


def test_a_reel_manifest_carries_episode_gates_without_applying_them(one_episode):
    # The whole set rides here so build_reel's reprocess arm has somewhere to read
    # the episode subset from (design §2.3).
    rm = ReelManifest(episodes=[one_episode], target_dur=10.0,
                      gates={"entropy_floor": {"value": 0.85, "why": "log profile"}})
    assert rm.gates == {"entropy_floor": {"value": 0.85, "why": "log profile"}}
    assert not hasattr(rm.check_spec, "entropy_floor")   # it is not a reel field


def test_gates_round_trip_through_to_dict_and_from_dict(one_episode):
    d = {"black_rel": {"value": 0.2, "why": "night shoot"}}
    rm = ReelManifest(episodes=[one_episode], target_dur=10.0, gates=d)
    assert ReelManifest.from_dict(rm.to_dict()).gates == d


def test_a_corrupt_gates_block_in_episodes_json_is_refused_not_trusted(one_episode):
    # build_reel's plain-list inlet does not pass through edl_to_reel's loader, so
    # the carrier re-validates rather than trusting what it was handed.
    rm = ReelManifest(episodes=[one_episode], target_dur=10.0)
    d = rm.to_dict()
    d["gates"] = {"entropy_floor": 0.85}                   # a bare number
    with pytest.raises(ValueError, match="value"):
        ReelManifest.from_dict(d)


def test_a_manifest_with_no_gates_is_byte_identical_to_one_before_this_slice(one_episode):
    rm = ReelManifest(episodes=[one_episode], target_dur=10.0)
    assert rm.gates == {}
    assert rm.to_dict()["gates"] == {}
```

Use the file's existing episode fixture rather than building a new one; if there is no reusable `ReelEpisode` fixture in `tests/lib/test_models.py`, build the minimal one the neighbouring `ReelManifest` tests already build and say so in your report.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q -k gates`
Expected: FAIL — `ReelManifest.__init__() got an unexpected keyword argument 'gates'`.

- [ ] **Step 3: Implement**

Add the field last in the `ReelManifest` field list, after `provenance` is **not** an option (it has a default factory and so does this — order among defaulted fields is free, but keep `provenance` last for diff legibility, so insert `gates` immediately before it):

```python
    gates: dict = field(default_factory=dict)        # GATES.json as authored — the
                                       # WHOLE set, both scopes, so build_reel's
                                       # reprocess arm can read the episode subset
                                       # after the EPISODES.json round trip and a
                                       # reprocessed episode is not judged against
                                       # a different bar than its siblings (design
                                       # §2.3). check_spec applies only what
                                       # ReelCheckSpec owns.
```

In `__post_init__`, after the existing validation:

```python
        # Validated by constructing Gates, never trusted as handed: build_reel's
        # plain-list inlet and a hand-edited EPISODES.json both reach here without
        # passing edl_to_reel's loader (the OutroFit.from_dict idiom).
        from scripts.lib import gates as gates_lib      # local: gates imports models
        gates_lib.Gates.from_dict(self.gates, where="ReelManifest.gates")
```

`check_spec`:

```python
    def check_spec(self) -> ReelCheckSpec:
        from scripts.lib import gates as gates_lib      # local: gates imports models
        return ReelCheckSpec(self.target_dur, self.variety_min,
                             **gates_lib.Gates.from_dict(
                                 self.gates, where="ReelManifest.gates").for_spec(ReelCheckSpec))
```

`to_dict`: add `"gates": dict(self.gates),` beside `"provenance"`.

> **Correction, made after Task 2 landed:** that instruction is wrong and the
> implementer was right to deviate. Emitting the key unconditionally contradicts
> this plan's own Global Constraint ("with no `GATES.json` present, every artifact
> is byte-identical") and Task 6's control proof. What shipped emits the key only
> when the set is non-empty, the same conditional-emission idiom `PathMeta` uses
> for `max_speed`/`smooth_window_s` and for the same reason. Task 2's test 5
> asserts the key's ABSENCE. Battery row 12's mutation is therefore "delete the
> `if self.gates:` block", which still discriminates.
`from_dict`: add `gates=d.get("gates") or {},`.

- [ ] **Step 3b: Close the vacuous half of refusal 6 — the two specs must validate their own fields**

**Read design §2.2a first; it is new and it governs this step.** Measured on the
real classes: `black_floor` and `black_rel` — two of the seven BLOCKING bars —
have no validation at all and accept `True`, `nan`, `inf`, `"6"`, `None` and `-1`.
And `nan` passes *every* `> 0` guard in both classes (seven further fields),
because the guards read `... or v <= 0` and `nan <= 0` is `False`; `inf` passes the
same seven and `True` passes five. Until this slice none of it was reachable —
there was no way to author any of these values — so `gates.py`'s "let the owning
dataclass raise" refusal is, today, substantially a no-op.

Fix it where the other sixteen range checks already live. **Not in `gates.py`** — a
second copy of validation is exactly what refusal 6 exists to avoid.

Tests first, in `tests/lib/test_models.py`:

```python
@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "6", None, -1, 300])
def test_check_spec_refuses_a_black_floor_that_is_not_a_luma_code(bad):
    with pytest.raises(ValueError, match="black_floor"):
        CheckSpec(composition="lead", grid="thirds", target_dur=1.0, black_floor=bad)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "6", None, -1, 1.5])
def test_check_spec_refuses_a_black_rel_that_is_not_a_fraction(bad):
    with pytest.raises(ValueError, match="black_rel"):
        CheckSpec(composition="lead", grid="thirds", target_dur=1.0, black_rel=bad)


@pytest.mark.parametrize("name", ["beat_tol", "loudness_target", "loudness_tol",
                                  "layout_jump_max", "length_retime_max",
                                  "grade_residual_max", "chroma_spread_max"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_no_reel_threshold_accepts_a_non_finite_number(name, bad):
    # `nan <= 0` is False, so every "or v <= 0" guard in this class passes nan.
    with pytest.raises(ValueError, match=name):
        ReelCheckSpec(target_dur=1.0, **{name: bad})


@pytest.mark.parametrize("name", ["beat_tol", "loudness_target", "loudness_tol",
                                  "layout_jump_max", "length_retime_max"])
def test_no_reel_threshold_accepts_a_bool(name):
    # bool is an int, so True passes every numeric guard as 1.
    with pytest.raises(ValueError, match=name):
        ReelCheckSpec(target_dur=1.0, **{name: True})


def test_every_default_still_constructs(: 
    # The control: widening the guards must refuse only values that were already
    # broken. No default moves in this slice.
    ReelCheckSpec(target_dur=1.0)
    CheckSpec(composition="lead", grid="thirds", target_dur=1.0)
```

(Fix the stray syntax in the last signature — it is `def test_every_default_still_constructs():`. Left visible so you read the block rather than pasting it.)

Then widen the guards. In `CheckSpec.__post_init__`, add — using `math.isfinite`,
with `import math` at the top of `models.py` if it is not already there:

```python
        if (isinstance(self.black_floor, bool)
                or not isinstance(self.black_floor, (int, float))
                or not math.isfinite(self.black_floor)
                or not 0.0 <= self.black_floor <= 255.0):
            raise ValueError(f"CheckSpec.black_floor must be a finite luma code in "
                             f"[0, 255], got {self.black_floor!r}")
        if (isinstance(self.black_rel, bool)
                or not isinstance(self.black_rel, (int, float))
                or not math.isfinite(self.black_rel)
                or not 0.0 <= self.black_rel <= 1.0):
            raise ValueError(f"CheckSpec.black_rel must be a finite fraction of the "
                             f"clip's own body median in [0.0, 1.0], got "
                             f"{self.black_rel!r}")
```

In `ReelCheckSpec.__post_init__`, add `isinstance(x, bool)` to the five guards that
lack it (`beat_tol`, `loudness_target`, `loudness_tol`, `layout_jump_max`,
`length_retime_max`) and `math.isfinite` to all seven numeric guards
(those five plus `grade_residual_max`, `chroma_spread_max`). Keep each existing
message; extend the wording to say "finite" where you added the check. Do not
restructure guards that already work — this is an additive widening.

**`math.isfinite` raises on a huge int.** `math.isfinite(10**400)` is
`OverflowError: int too large to convert to float`, not `False` — and
`gates.Gates.from_dict` wraps only `ValueError`, so a 400-digit integer in
`GATES.json` would leak an `OverflowError` naming no file. Either write the guard
so the huge int is refused before `isfinite` sees it (an explicit range check
placed first does this: `0.0 <= 10**400 <= 255.0` is `False` and raises nothing),
or widen `from_dict`'s `except`. Pick one, state which in your report, and add a
test with a literal `10**400`.

**If any pre-existing test breaks**, that is a real finding: report which test
passed a non-finite or boolean threshold and stop rather than loosening the guard
back. I measured that none does, but measure again rather than assume.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/test_check_episode.py -q`
Expected: PASS, including every pre-existing `ReelManifest` and `CheckSpec` test.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelManifest.gates - one carrier for both scopes, re-validated on the round trip"
```

---

### Task 3: the two `CheckSpec` construction sites

**Files:**
- Modify: `scripts/process_episode.py` (signature, docstring, the `CheckSpec(...)` at ~line 565)
- Modify: `scripts/check_episode.py` (`build_parser`, `main`)
- Test: `tests/lib/test_process_episode.py`, `tests/test_check_episode.py`

**Interfaces:**
- Consumes: `gates.Gates` (Task 1).
- Produces: `process_episode.process_episode(manifest_dict, project_dir, ..., gates: dict | None = None)`; `check_episode --gates PATH`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_process_episode.py
def test_an_authored_entropy_floor_reaches_the_check_spec(monkeypatch, ...):
    """The parameter is a run POLICY, not a manifest field — an agent authoring an
    EDL cannot set it, only the operator's GATES.json can (design §2.3)."""
    seen = {}
    monkeypatch.setattr(check_episode, "run", lambda *a, **k: seen.setdefault("spec", a[3]) or _pass())
    process_episode.process_episode(md, str(tmp_path), gates={"entropy_floor": {"value": 0.85, "why": "log"}})
    assert seen["spec"].entropy_floor == 0.85


def test_no_gates_leaves_every_check_spec_field_at_its_default(...):
    ...
    assert seen["spec"].entropy_floor == 0.90 and seen["spec"].black_floor == 6.0


def test_a_reel_scope_gate_handed_to_process_episode_is_ignored_not_crashed(...):
    # for_spec partitions; a caller passing the whole set is the NORMAL case
    # (edl_to_reel and build_reel both do).
    process_episode.process_episode(md, str(tmp_path),
                                    gates={"beat_tol": {"value": 0.08, "why": "no click"}})
    assert seen["spec"].entropy_floor == 0.90
```

```python
# tests/test_check_episode.py
def test_the_gates_flag_moves_the_bar_the_standalone_judge_uses(tmp_path, monkeypatch):
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"black_floor": {"value": 2.0, "why": "night shoot, legitimately dark"}}))
    seen = {}
    monkeypatch.setattr(check_episode, "run", lambda *a, **k: seen.setdefault("spec", a[3]))
    monkeypatch.setattr("sys.argv", ["check_episode", "c.mp4", "p.json", "o.json",
                                     "--target-dur", "3", "--gates", str(tmp_path / "GATES.json")])
    check_episode.main()
    assert seen["spec"].black_floor == 2.0
```

Match the real positional order in `check_episode.build_parser` (`clip`, optional `route`, `path`, `out`) — read it before writing the argv, and report any mismatch with this snippet rather than adjusting the parser.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py tests/test_check_episode.py -q -k gates`
Expected: FAIL — unexpected keyword argument / unrecognized argument.

- [ ] **Step 3: Implement**

`process_episode`: add `gates: dict | None = None` as the last keyword parameter, and at the construction site:

```python
        cspec = CheckSpec(composition=m.composition, grid=m.grid, target_dur=m.target_dur,
                          attempt=attempt,
                          **gates_lib.Gates.from_dict(gates or {},
                                                      where="the gates passed to process_episode"
                                                      ).for_spec(CheckSpec))
```

with `from scripts.lib import gates as gates_lib` at module top (no cycle: `process_episode` is a script, not a `lib` module). Add to the docstring:

```
    `gates` is the authored threshold set (GATES.json, design 2026-09-30) as a
    plain dict, the WHOLE set — for_spec takes the subset CheckSpec owns and
    ignores the rest, so a caller never partitions. A parameter and not a Manifest
    field on purpose: a gate is a run policy the operator authors, not a value an
    agent can write into an EDL. None means every threshold at its default.
```

`check_episode.build_parser`:

```python
    ap.add_argument("--gates", default=None,
                    help="GATES.json — authored thresholds with the reason each was "
                         "moved (design 2026-09-30). A flag here and not a convention "
                         "because the standalone judge has no project.json to look "
                         "beside; a run through edl_to_reel finds the file itself")
```

`check_episode.main`:

```python
    g = gates_lib.Gates.from_json(a.gates) if a.gates else gates_lib.Gates()
    spec = CheckSpec(composition=a.composition, grid=a.grid, target_dur=a.target_dur,
                     attempt=a.attempt, **g.for_spec(CheckSpec))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py tests/test_check_episode.py -q`
Expected: PASS.

- [ ] **Step 5: Regenerate the tool index and re-run its test**

`references/tools.md` is generated from the parsers (`scripts/lib/toolindex.py`); a new flag changes it. Do NOT hand-edit it — regenerate:

```bash
.venv/bin/python -m scripts.montage tools > references/tools.md
```

The staleness guard is `tests/test_tool_index.py` (not `test_cli_help.py`, which checks that parsers carry help text at all). Run both:

Run: `.venv/bin/python -m pytest tests/test_tool_index.py tests/test_cli_help.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/process_episode.py scripts/check_episode.py tests/lib/test_process_episode.py tests/test_check_episode.py references/tools.md
git commit -m "feat: authored gates reach both CheckSpec construction sites"
```

---

### Task 4: `edl_to_reel` is the one finder; `build_reel`'s reprocess reads the carrier

**Files:**
- Modify: `scripts/edl_to_reel.py` (`_phase_one_setup` returns the gates; the pool `kwargs`; the `ReelManifest(...)` construction)
- Modify: `scripts/build_reel.py` (the reprocess `process_episode` call at ~line 241)
- Test: `tests/lib/test_edl_to_reel.py`, `tests/lib/test_build_reel.py`

**Interfaces:**
- Consumes: `ReelManifest.gates` (Task 2), `process_episode(gates=…)` (Task 3).
- Produces: `GATES.json` discovered at `Path(project_path).parent / "GATES.json"`, threaded to the pool and onto `rm.gates`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_edl_to_reel.py
def test_gates_json_beside_project_json_is_found_with_no_flag(tmp_path, ...):
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"loudness_tol": {"value": 2.0, "why": "live room"},
         "entropy_floor": {"value": 0.85, "why": "log profile"}}))
    rm, stop = edl_to_reel._build_manifest(..., project_path=str(tmp_path / "project.json"), ...)
    assert rm.gates == {"loudness_tol": {"value": 2.0, "why": "live room"},
                        "entropy_floor": {"value": 0.85, "why": "log profile"}}
    assert rm.check_spec.loudness_tol == 2.0


def test_the_pool_hands_the_authored_gates_to_every_episode(tmp_path, monkeypatch, ...):
    seen = []
    monkeypatch.setattr(process_episode, "process_episode",
                        lambda md, d, **kw: seen.append(kw.get("gates")) or _pass(md))
    ...
    assert seen == [{"entropy_floor": {"value": 0.85, "why": "log profile"}}] * len(seen)


def test_a_broken_gates_file_stops_the_run_and_names_the_path(tmp_path, ...):
    (tmp_path / "GATES.json").write_text('{"entropy_floor": 0.85}')
    with pytest.raises(ValueError) as e:
        edl_to_reel._build_manifest(...)
    assert str(tmp_path / "GATES.json") in str(e.value)


def test_no_gates_file_means_no_gates_kwarg_at_all(tmp_path, monkeypatch, ...):
    # The pool's kwargs are built "only when it carries something" (edl_to_reel.py:183);
    # an empty set must keep the call shape identical to the pre-slice one.
    ...
    assert all("gates" not in kw for kw in seen_kwargs)
    assert rm.gates == {}
```

```python
# tests/lib/test_build_reel.py
def test_a_reprocess_is_judged_against_the_same_authored_bar_as_its_siblings(...):
    """Without the whole set on the manifest the reprocess arm has nowhere to read
    the episode subset from, and the re-rendered episode is judged against a
    different bar in silence (design §2.3)."""
    rm = ReelManifest(..., gates={"entropy_floor": {"value": 0.85, "why": "log"}})
    seen = []
    monkeypatch.setattr(process_episode, "process_episode",
                        lambda m, d, **kw: seen.append(kw.get("gates")) or _pass())
    ... drive one reprocess round ...
    assert seen == [{"entropy_floor": {"value": 0.85, "why": "log"}}]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py -q -k gates`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `_phase_one_setup`, beside the existing `ProjectConfig.from_json(project_path)`:

```python
    # Found BY CONVENTION beside project.json, no flag — the CONSTRAINTS.json /
    # REGIONS.json rule (design §0.5). A flag can be dropped on a re-run, and a
    # dropped threshold flag reverts the bar in silence, which is the defect
    # EDL.platform shipped with. Read HERE and not at edit_plan time: a bar is
    # discovered to be wrong after a check fails, and re-cutting a reel to change
    # one is absurd.
    gates_path = Path(project_path).parent / "GATES.json"
    authored = gates_lib.Gates.from_json(gates_path) if gates_path.exists() else gates_lib.Gates()
    if authored.gates:
        _log(f"gates: {len(authored.gates)} authored threshold(s) from {gates_path}")
```

Widen the return tuple to carry `authored` and update both callers (`_build_manifest`, `build_geometry`). Thread it into the pool's per-episode `kw`, keeping the "only when it carries something" shape:

```python
        if authored.gates:
            kw["gates"] = authored.to_dict()
```

**Correction, made after Task 3 landed: there is no `Gates.subset`, and there
must not be.** This plan originally told you to add one — a document-shaped
subset — so each driver could hand `process_episode` only the episode half. That
is redundant work at every call site: `process_episode` already partitions
internally with `for_spec`, and `ReelManifest.gates` already holds the whole set.
So the rule is one line: **every caller hands the whole authored document; the
one place a spec is constructed partitions.** The pool passes
`authored.to_dict()`, `build_reel`'s reprocess passes `rm.gates`, and neither
filters. This also makes true the docstring Task 3 already landed on
`process_episode`, which says a caller never partitions.

On the manifest, fill the existing `extra` seam rather than adding a new keyword:

```python
    extra: dict = {}
    if authored.gates:
        extra["gates"] = authored.to_dict()
```

and keep the seam's comment, extending it to say the seam now has its first filler.

In `build_reel`'s reprocess arm:

```python
            res = process_episode.process_episode(
                manifest, epdir, route_path=route,
                gates=rm.gates or None)
```

- [ ] **Step 3b: Close the two authoring surfaces Task 3's report found still unreachable**

The row this slice closes says the twelve are "unreachable from any authoring
surface". Two documented entry points are still unreachable after Task 3, and
leaving them so would make this slice's own acceptance false:

- **`process_episode`'s own CLI** — the hand-driven path
  `skills/process-episode/SKILL.md:71` documents. It already takes `--project`, so
  it gets the **convention lookup**, not a flag: resolve `GATES.json` beside the
  project exactly as `_phase_one_setup` does, and pass it to `process_episode`.
  Factor the two-line discovery into one helper rather than writing it twice —
  `scripts/lib/gates.py` is the natural home (`gates.beside_project(path)`
  returning a `Gates`), and both call sites use it.
- ~~**`check_reel`'s own CLI**~~ — **retracted after Task 4's review measured it.**
  This step told Task 4 to give `check_reel` a `--gates PATH`, and it did, and the
  flag is **inert**: `main` calls `run(master, episodes, spec, report)` with no
  music, audio, geometry, prediction, chroma or `brief_len`, and every one of the
  nine reel-scope thresholds is read only behind one of those. With all nine
  authored at extremes the report and exit code are byte-identical to no file at
  all. That is the knob design §0.2 rejects. **The flag is deleted in the fix
  round.** `check_reel`'s bars are reached through the drivers, which supply those
  inputs. Design §6 now records why its CLI cannot be an authoring surface.

One test each, driven through `main()` with a patched `sys.argv`, asserting the
authored value reaches the constructed spec.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py tests/lib/test_process_episode.py tests/lib/test_check_reel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/edl_to_reel.py scripts/build_reel.py scripts/lib/gates.py tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py tests/test_gates.py
git commit -m "feat: edl_to_reel finds GATES.json beside project.json; the reprocess reads the same bar"
```

---

### Task 5: the reason reaches the verdict, the attestation and the inspector

**Files:**
- Modify: `scripts/check_reel.py` (`_loudness_check`, `_grade_faithful_check`, `_brief_length_check` details; `run` takes the reasons)
- Modify: `scripts/check_episode.py` (the `black_frames` and `grade_damage` details)
- Modify: `scripts/lib/provenance.py` (`Attestation.gates`)
- Modify: `scripts/deliver.py` (fill it)
- Modify: `scripts/montage.py` (`_gates`)
- Test: `tests/lib/test_check_reel.py`, `tests/test_check_episode.py`, `tests/lib/test_provenance.py`, `tests/lib/test_montage.py`

**Interfaces:**
- Consumes: `Gates.record()`, `Gates.reasons()`, `ReelManifest.gates`.
- Produces: an `"authored"` key on the affected check details; `Attestation.gates: list[dict]`; `montage status`'s `gates` block.

**Design §2.4 is the requirement; read it before starting.** The load-bearing half is (1): the artifact that says PASS must also say which bar was moved and why.

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_check_reel.py
def test_an_authored_loudness_band_is_named_in_the_checks_own_detail():
    rep = check_reel.run(..., spec=ReelCheckSpec(target_dur=10.0, loudness_tol=2.0),
                         gate_reasons={"loudness_tol": "live room"})
    a = rep.checks["loudness"].detail["authored"]
    assert a == [{"field": "loudness_tol", "value": 2.0, "default": 1.0, "why": "live room"}]


def test_a_check_whose_bars_were_not_authored_carries_no_authored_key():
    rep = check_reel.run(..., spec=ReelCheckSpec(target_dur=10.0))
    assert "authored" not in rep.checks["loudness"].detail


def test_the_authored_record_rides_a_PASS_not_only_a_failure():
    # The whole point: a moved bar that let the reel through is exactly the case a
    # later reader must be able to see.
    rep = check_reel.run(..., spec=ReelCheckSpec(target_dur=10.0, loudness_tol=6.0),
                         gate_reasons={"loudness_tol": "live room"})
    assert rep.checks["loudness"].passed is True
    assert "authored" in rep.checks["loudness"].detail
```

```python
# tests/lib/test_provenance.py
def test_the_attestation_records_every_authored_gate_with_its_reason_and_scope():
    a = provenance.Attestation(..., gates=gates.Gates.from_dict(
        {"entropy_floor": {"value": 0.85, "why": "log profile"}}).record())
    assert provenance.Attestation.from_dict(a.to_dict()).gates == a.gates
    assert a.gates[0]["blocking"] is True and a.gates[0]["scope"] == "episode"


def test_spec_overrides_is_unchanged_by_this_slice():
    # It answers a different question and must keep working with no GATES.json at
    # all — it is the only reader that sees a variety_min moved by a
    # hand-edited EPISODES.json (NOT an EDL-sourced one: variety_min occurs
    # nowhere in edl.py or edl_to_reel.py).
    ...
```

```python
# tests/lib/test_montage.py
def test_status_names_the_three_gates_states(tmp_path):
    assert montage._gates(tmp_path) == {"present": False, "gates": [], "error": None}
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"beat_tol": {"value": 0.08, "why": "no click track"}}))
    assert montage._gates(tmp_path)["gates"][0]["field"] == "beat_tol"
    (tmp_path / "GATES.json").write_text("{broken")
    out = montage._gates(tmp_path)
    assert out["present"] is True and out["gates"] == [] and out["error"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_provenance.py tests/lib/test_montage.py -q -k "gates or authored"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`check_reel.run` gains `gate_reasons: dict[str, str] | None = None`, and one small helper used by each affected check:

```python
def _authored(spec, reasons: dict, *names) -> list[dict]:
    """The rows of `names` this run moved off their default, with the reason each
    was moved (design §2.4). Empty when nothing was authored, and the caller then
    omits the key entirely rather than writing `"authored": []` — an empty list
    reads as "we looked and there was nothing", which is true but noisy on every
    check of every clean run."""
    base = _DEFAULT_REEL_SPEC          # ReelCheckSpec(target_dur=1.0), built once
    return [{"field": n, "value": getattr(spec, n), "default": getattr(base, n),
             "why": reasons[n]}
            for n in names
            if n in reasons and getattr(spec, n) != getattr(base, n)]
```

Attach in `_loudness_check` (`loudness_target`, `loudness_tol`), `_grade_faithful_check` (`grade_residual_max`), `_brief_length_check` (`length_retime_max`), and the `chroma_spread` check (`chroma_spread_max`). The same shape, keyed on `CheckSpec`'s own defaults, goes in `check_episode` for `black_frames` (`black_floor`, `black_rel`) and `grade_damage` (`entropy_floor`) — put the helper where both can reach it without a cycle, which is `gates.py` itself:

```python
def authored_rows(spec, reasons: dict, *names) -> list[dict]: ...
```

Thread the reasons at **three** sites. An earlier correction of mine said four; `edl_to_reel` is not one of them — it never calls either check's `run` (verified). `edl_to_reel`/`build_reel` pass `gate_reasons=Gates.from_dict(rm.gates).reasons()` into `check_reel.run`; `process_episode` passes the episode reasons into `check_episode.run`; **`check_episode.main` is the fourth and is easy to miss** — Task 3 left it holding a loaded `Gates` as `g`, and without `g.reasons()` there a `check_episode --gates f.json` run writes a verdict with a moved bar and no reason beside it, which is exactly the gap design §2.4 item 1 exists to close. `check_reel.main` is **not** one of them: Task 4's review measured its `--gates` flag inert and the fix round deleted it, so there is no loaded `Gates` there to take reasons from. Reuse the existing parameter-passing shape at each call site; if `check_episode.run`'s signature has no room without churn, say so in your report with what you did instead.

`Attestation` gains `gates: list[dict] = field(default_factory=list)` with `to_dict`/`from_dict` entries beside `look_checks`, plus a docstring line. `deliver` fills it from the manifest it already holds.

**`probe.py` is a fourth consumer and it must predict against the bar the gate
will use.** `probe.py:245` and `:338` read
`CheckSpec.__dataclass_fields__["entropy_floor"].default` to predict
`grade_damage` without a reel re-render. Design §0.3's census missed them because
it grepped for `CheckSpec(` and these construct nothing. A prediction against a
different bar than the gate is worse than no prediction. `probe_grade` holds
`rm.gates`; `probe_geometry` holds only `geo.project`, which may not resolve —
there, report a **named absence** (the repo's own doctrine, design 2026-09-07)
rather than silently predicting against the default.

`montage._gates` mirrors `montage._constraints` exactly — including catching the load refusal *in the inspector only*, with that function's own reasoning quoted for why an unreadable file must not read as "no gates". Wire it into `status`'s output beside `constraints`. **It must also say which
phase froze the set.** Phase 2 (`--from-episodes`) carries what phase 1b wrote
into `EPISODES.json` and never re-reads `GATES.json` — correctly, since that set
is the record of which bars judged these clips and re-reading it would let a bar
move between the judging and the attestation that binds it (design §6). But an
operator editing the file between phases sees no effect, so when an
`EPISODES.json` exists, compare its `gates` block against the file on disk and
say plainly when they differ and what that means.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/test_check_episode.py tests/lib/test_provenance.py tests/lib/test_montage.py tests/test_deliver.py tests/lib/test_deliver.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole unit tier**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_reel.py scripts/check_episode.py scripts/lib/gates.py scripts/lib/provenance.py scripts/deliver.py scripts/montage.py scripts/edl_to_reel.py scripts/build_reel.py scripts/process_episode.py tests/
git commit -m "feat: an authored bar is named beside the verdict it bought, in the attestation and in status"
```

---

### Task 6: end-to-end proofs, both scopes, with the control that must not move

**Files:**
- Create: `tests/integration/test_threshold_surface.py`

**Interfaces:** consumes everything above; produces no new production code.

**Drive phase 1b, not only phase 1a.** `render_from_geometry` (`--from-geometry`)
is the arm the router renders through, and phase 1a is the one arm where
`check_episode` does NOT run — it stops at the geometry boundary before a
`CheckSpec` exists. (The single-pass arm runs the check in full too.) A
proof that never reaches phase 1b would have passed against a slice that was
inert on the real path, which is exactly what Task 4 found and fixed.
`tests/integration/test_grade_shipped_pixels.py` has `_run`, `_geometry` and
`_render` helpers to reuse. Note also that `provenance.overrides` is no longer
`[]` once a reel-scope gate is authored, so the control proof's "byte-identical"
claim holds only for the **no-gates** run; with gates authored, `EPISODES.json`
differs in exactly `gates` and `overrides`, which is §2.4 item 2 working.

Use the suite's existing real-footage fixtures (`golden_ride_segment`, the `fake_render` conftest factory) rather than building new ones. Read `tests/conftest.py` and one neighbouring integration module (`tests/integration/test_front_spine.py` is the closest shape) before writing.

- [ ] **Step 1: Write the four proofs**

```python
def test_an_authored_entropy_floor_changes_the_bar_end_to_end(tmp_path, ...):
    """Episode scope, through edl_to_reel, to the report on disk."""
    # A floor of 0.999 must FAIL an episode that passes at 0.90 — a bar moved the
    # WRONG way, so the proof cannot pass by accident on an already-passing render.
    ...
    assert report["checks"]["grade_damage"]["passed"] is False
    # NOTE: CheckResult.to_dict FLATTENS the detail ({**detail, "pass": ...}), so on
    # disk the key is checks[name]["authored"], not checks[name]["detail"]["authored"].
    assert report["checks"]["grade_damage"]["authored"] == [
        {"field": "entropy_floor", "value": 0.999, "default": 0.90,
         "why": "deliberately unreachable, to prove the bar moved"}]


def test_an_authored_reel_bar_survives_the_episodes_json_round_trip(tmp_path, ...):
    """Reel scope: edl_to_reel --stop-after-episodes, then build_reel from the
    EPISODES.json alone. build_reel never sees project.json, so if the value did
    not ride the manifest it is gone."""
    ...
    assert rm_reloaded.check_spec.loudness_tol == 2.0


def test_every_refusal_fires_end_to_end_with_the_path_in_the_message(tmp_path, ...):
    for doc, needle in [('[]', 'must be an object'),
                        ('{"nope": {"value": 1, "why": "x"}}', 'not a gate threshold'),
                        ('{"variety_min": {"value": 4, "why": "x"}}', 'ReelManifest.variety_min'),
                        ('{"entropy_floor": 0.85}', "'value' and 'why'"),
                        ('{"entropy_floor": {"value": 0.85, "why": "  "}}', 'non-empty'),
                        ('{"entropy_floor": {"value": 1.5, "why": "x"}}', 'ratio in (0, 1]')]:
        ...
        assert str(gates_path) in msg and needle in msg


def test_with_no_gates_file_the_run_is_identical(tmp_path, ...):
    """The control. Same inputs, GATES.json absent: EPISODES.json byte-identical to
    a run made before this slice, and no 'authored' key anywhere in the reports."""
    ...
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_threshold_surface.py -q`
Expected: PASS, 4 tests (the third parametrized or looped over six documents).

- [ ] **Step 3: Full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `N passed / 1 skipped / 1 failed`. The one failure must be `test_real_runtime_is_ready` and nothing else. If any other test is red, stop and report — do not proceed.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_threshold_surface.py
git commit -m "test: threshold surface end to end - both scopes, six refusals, and the control"
```

---

### Task 7: the mutation battery, the docs, the version

**Files:**
- Modify: `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`, `CLAUDE.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`
- Modify: `skills/using-montage/` (the stage page that names `CONSTRAINTS.json`), `skills/edit-plan/`, `skills/verify-runtime/` as the sweep finds them
- Modify: `docs/plans/2026-09-30-threshold-surface.md` (this file — correct any row whose pointer running it proves wrong)

- [ ] **Step 1: Run the mutation battery**

Each row: apply the mutation, run the named selection, confirm RED, restore with `git show HEAD:<path> > <path>`, re-check `git diff --stat` is empty. Every run under `PYTHONDONTWRITEBYTECODE=1`. Write selections out literally — an unquoted shell variable arrives as one argument and prints `no tests ran`.

| # | mutation | file | expect | named test |
|---|---|---|---|---|
| 1 | `FIELDS` hardcoded to a 12-name literal | `gates.py` | RED | **Corrected during Task 1, which ran this row early.** A literal that is correct today cannot fail an equality assertion, exactly as this row warned. Task 1 closed it with a test that adds a field to a synthetic spec class in a subprocess and asserts the derived vocabulary follows; use that test's name as it landed, not this row's original pointer |
| 2 | `BLOCKING` computed with `in _ADVISORY_CHECKS` instead of `not in` | `gates.py` | RED | `test_the_blocking_set_is_derived_from_the_advisory_registry` |
| 3 | `OF_CHECK["length_retime_max"]` → `"brief_length"` | `gates.py` | RED | same — this is design §0.1's whole correction; if no test discriminates it, that is a coverage hole and needs one |
| 4 | the `AUTHORED_ELSEWHERE` check moved BELOW the `_OWNER` check | `gates.py` | RED | `test_a_field_authored_elsewhere_is_refused_and_the_message_says_where` (an elsewhere-name is not in `_OWNER`, so the wrong error fires) |
| 5 | `why.strip()` → `why` (accept whitespace) | `gates.py` | RED | `test_a_value_without_a_written_reason_is_refused[   ]` |
| 6 | the probe-construction `try` deleted | `gates.py` | RED | `test_a_value_the_owning_dataclass_rejects_is_refused_by_that_dataclass` |
| 7 | `set(entry) != {"value","why"}` → `"value" not in entry` | `gates.py` | RED | **Corrected during Task 1.** The original pointer (`test_a_value_without_a_written_reason_is_refused[None]`) cannot see this mutation — a missing `why` is caught by the `why` check either way. Task 1 added `test_an_entry_that_is_not_exactly_value_and_why_is_refused`, which is the discriminating one |
| 8 | `for_spec` returns everything, ignoring `_OWNER` | `gates.py` | RED | `test_an_authored_value_reaches_the_class_that_owns_it` |
| 9 | `record()`'s `default` read off the authored value | `gates.py` | RED | `test_the_record_carries_value_default_scope_blocking_and_why` |
| 10 | `ReelManifest.__post_init__`'s `Gates.from_dict` call deleted | `models.py` | RED | `test_a_corrupt_gates_block_in_episodes_json_is_refused_not_trusted` |
| 11 | `check_spec` drops the `**for_spec(...)` splat | `models.py` | RED | `test_a_reel_manifest_applies_its_authored_reel_gates_to_check_spec` |
| 12 | `to_dict` omits `"gates"` | `models.py` | RED | `test_gates_round_trip_through_to_dict_and_from_dict` |
| 13 | `process_episode`'s `**for_spec(CheckSpec)` dropped | `process_episode.py` | RED | `test_an_authored_entropy_floor_reaches_the_check_spec` |
| 14 | `edl_to_reel`'s finder reads `Path(project_path) / "GATES.json"` (not `.parent`) | `edl_to_reel.py` | RED | `test_gates_json_beside_project_json_is_found_with_no_flag` |
| 15 | the pool's `kw["gates"]` assignment deleted | `edl_to_reel.py` | RED | `test_the_pool_hands_the_authored_gates_to_every_episode` |
| 16 | `extra["gates"]` assignment deleted | `edl_to_reel.py` | RED | `test_an_authored_reel_bar_survives_the_episodes_json_round_trip` |
| 17 | `build_reel`'s reprocess drops `gates=` | `build_reel.py` | RED | `test_a_reprocess_is_judged_against_the_same_authored_bar_as_its_siblings` |
| 18 | `_authored` filters on `n in reasons` only, dropping the `!= default` test | `check_reel.py`/`gates.py` | RED | `test_a_check_whose_bars_were_not_authored_carries_no_authored_key` — **predicted uncertain:** a reason present with an unchanged value may be unreachable through the drivers (the loader only records fields an author wrote, and writing the default value is legal but odd). If it comes back GREEN, say whether the guard is unreachable-by-construction (report it, consider deleting the clause) or a real hole (close it with a test) |
| 19 | `Attestation.to_dict` omits `"gates"` | `provenance.py` | RED | `test_the_attestation_records_every_authored_gate_with_its_reason_and_scope` |
| 20 | `montage._gates`'s `except ValueError` arm returns `{"present": False, ...}` | `montage.py` | RED | `test_status_names_the_three_gates_states` |
| 21 | `CheckSpec.black_rel`'s new guard deleted | `models.py` | RED | `test_check_spec_refuses_a_black_rel_that_is_not_a_fraction` — and confirm the value then loads through `gates.Gates.from_dict`, which is what makes the row about refusal 6 rather than about a dataclass |
| 22 | `math.isfinite` dropped from `ReelCheckSpec.loudness_tol` | `models.py` | RED | `test_no_reel_threshold_accepts_a_non_finite_number[inf-loudness_tol]` |
| 23 | `isinstance(self.beat_tol, bool)` dropped | `models.py` | RED | `test_no_reel_threshold_accepts_a_bool[beat_tol]` |
| 24 | the episode floor judged at `max(floor, 0.90)` **inside `gradedamage.evaluate`** — i.e. DOWNSTREAM of the report's own echo of `floor` | `gradedamage.py` | RED | **Added after Task 6's review, which found this survives everything.** Loosening is what a `GATES.json` is FOR, and no proof exercised that direction; tightening cannot distinguish "the value arrived" from "it was clamped". **Upstream vs downstream of the echo is the whole distinction**, and Task 6's implementer corrected me on it: a clamp at the CALL SITE dies on an existing test that reads `floor` off the report, because the echoed value moves with it. Only a clamp below the echo survives, and only the waiver proof kills it |
| 25 | the reel max judged at `min(max, 4.0)` at the comparison itself, downstream of the echo | `check_reel.py` | RED | same. Measured to survive the whole unit tier AND 72 neighbouring integration tests, which is the Task 4 "inert on the real path" shape one hop deeper |
| 26 | `rm.gates = {}` immediately before `build_reel` inside `assemble_reel` | `edl_to_reel.py` | RED | **Added after Task 6's review.** `assemble_reel` is the `--from-episodes` entry the router actually delivers through, and design §6's claim that phase 2 carries the frozen set was untested at any tier. Needs the phase-2 proof Task 6's fix round adds |
| 27 | `rm.gates = {}` inside `_episodes_ready`, the writer both phase-1 arms end with | `edl_to_reel.py` | RED | same proof |

Task 1 ran rows 1-9 early, while it still owned the tests, and reports 35 of 36 of its own rows red with one presentational green (an unsorted `FIELDS`). Re-run them here anyway on the integrated tree — a row that discriminated in isolation can stop discriminating once a later task adds a caller.

Report the roll-call: RED outright / closed with a new test / confirmed non-discriminating with its reason. **A GREEN row is either a documented non-discrimination or a real coverage hole — never silently accepted.** Any row whose named test turns out not to see its own mutation is a plan defect: correct the row in this file rather than leaving the wrong pointer for the next reader.

- [ ] **Step 1b: Amend the imports section of `docs/coding-standards.md`**

Task 2 found the standard has no case for this: its Imports section forbids a
function-local import except for a heavy optional dependency, and `models.py` had
no precedent for one. But `gates.py` derives `FIELDS` and `BLOCKING` from
`ReelCheckSpec`/`CheckSpec` **at import time**, so it cannot defer its own import
— which leaves `models.py` as the only side where the cycle can be broken. The
local import in `ReelManifest.check_spec` is correct and is not the exception the
standard names. Add the case: a module-scope import cycle whose other side cannot
defer, with the requirement that the import carries a comment saying which side
cannot defer and why (the one in `check_spec` is the model).

- [ ] **Step 2: Sweep the tree for statements this slice made false**

`grep` for text asserting that a threshold is unreachable, that `spec_overrides` can report only `variety_min`, or that `check_spec` takes two fields. **Also confirm one sentence that shipped one task early on purpose:** `check_episode --gates`'s help text says `edl_to_reel` finds the file itself, which Task 3 landed and Task 4 Step 3 makes true. Re-read it against what Task 4 actually built. Check at minimum: `docs/specs/2026-09-29-unenforced-rules-design.md` §0.6 (the row that promoted this), `scripts/lib/provenance.py:99`'s docstring, `scripts/lib/models.py`'s `check_spec`, and every skill page naming `CONSTRAINTS.json` or `REGIONS.json` as "the convention files" — there are now three. Correct each in place.

**Four targets Task 5's review named, verified to still be stale:**

- `docs/backlog.md:57` — the open P1 row still says "twelve of the eighteen" and
  lists `loudness_target` among them. This row is the one Step 4 closes to the
  archive, so correct the counts in the closure note rather than in place.
- Design §2.4 item 1 describes `"authored": {value, default, why}`; what shipped
  is a **list** of `{field, value, default, why}` rows, per the brief. It also names
  five checks, while D1's derived-from-`OF_CHECK` map widened it to the advisory
  peers and `length`. Correct the design in place — it is the source of truth.
- **"No waiver anywhere" for `grade_damage` is now false** in three places:
  `references/using-montage/episodes.md:26`, `skills/match-grade/SKILL.md:295` and
  `:299`. There is now exactly one waiver and it requires a written reason; say
  that, rather than deleting the sentence.
- `references/edit-plan/grade-convergence.md` should document `probe.json`'s
  `gates: "not-read"` key, which is the named absence a reader has to be able to
  recognise.

- [ ] **Step 3: Skills**

`skills/process-episode/SKILL.md` (~line 71) documents the hand-driven CLI path;
add one sentence that it now reads `GATES.json` beside `--project`. Battery row
14's mutation site moved to `gates.beside_project`; its named test still kills it.

The stage page that documents `edl_to_reel` gains `GATES.json`: where it lives, that the reason is required, and that a blocking bar's reason lands in the attestation. Keep it short — the body-size budget from the reachable-instructions slice is machine-checked (no body over 26 KB); if a page is near it, put the detail on a `references/` page and link it.

- [ ] **Step 4: Backlog and build status**

Close the P1 row to `docs/backlog-closed.md` with the closure note this slice earned. **The row filed twelve thresholds as one population, and the partition is the design — but the counts it states are wrong twice over, and the note must carry the measured ones:**

- **Eleven authorable, not twelve.** `loudness_target` left the vocabulary: it is a rendered set-point, not a bar — `mix.py:16` bakes `_TARGET_LUFS = -14.0` into the `loudnorm` filter and `mix.mix` takes no target, so authoring it alone moves the ruler and not the thing measured, and fails every reel (design §0.2a).
- **Six blocking, five advisory**, with `length_retime_max` blocking through the driver's shortfall absorb rather than through the advisory check that also reads it.
- The row's claim that `spec_overrides` "can only ever report `variety_min`" is generous: it cannot report even that, because it runs once in phase 1 on the manifest phase 1 just built, so a hand-edited `EPISODES.json` is invisible to it (§0.4). `Attestation.overrides` has been `[]` on every delivery, by construction.
- The platform-loudness table is **not** dismissed as "four identical rows": §0.2a makes it the only shape that can move the mixer and the gate together, and it is filed P2 for that reason.

Fold R2.4 into the same note: the instrument it asked for existed and had nothing to report. File the three §7 deferrals as new rows. **Re-count the archive by hand** — `grep -c '^| [✅⊘]'` is wrong in two directions (registry note). The last hand count was **73 entries / 74 rows at 2026-09-29**.

- [ ] **Step 4b: File the rows the review loop turned up, which no §7 deferral covers**

These came out of the task reviews, not the design, so they are not in §7 and
would otherwise leave every list — the deferral rule's own failure mode:

- `json.loads` raises a bare `ValueError: Exceeds the limit (4300 digits)` on an
  integer over 4300 digits, and `Gates.from_json` catches only `JSONDecodeError`,
  so the message names no file. Same class as the deferred non-UTF-8 item; the
  400-digit case is clean. **P3, S.**
- `target_dur` on `ReelCheckSpec`, `CheckSpec` **and** `EDL.target_dur` accepts
  `nan`, `inf` and `True`. Not reachable through `GATES.json` — it is exempt — but
  reachable three other ways: `check_episode --target-dur nan` and
  `check_reel --target-dur nan` (argparse `type=float` accepts it), a hand-edited
  `EDL.json`, and a hand-edited `EPISODES.json` (`NaN`/`Infinity`/`true` all load).
  It fails **closed** — `checks.length` and `check_reel`'s length gate both compute
  `abs(x - target) <= tol`, which is `False` for `nan` — so it is a gap, not a live
  defect. **P3, S.**
- **The waiver direction is proven for two of the eleven bars, one per scope**
  (`entropy_floor` and `grade_residual_max`). A clamp at another bar's own
  comparison site — `black_floor`, `loudness_tol`, `length_retime_max` and the rest
  — is not reached at the integration tier. This is a coverage statement, not a
  defect: the mechanism is shared, and Task 6's two proofs are what established
  that a clamp below the report's echo is invisible to everything else. A row so
  the next reader knows which bars are actually exercised end to end. **P3, S.**
- **Three untested threshold boundaries**, found as the only surviving mutants of
  a 79-row kill matrix over `models.py`'s guards: nothing constructs
  `loudness_tol == 0`, `clip_tol == 0`/`bar_symmetry_tol == 0` (their lower edge),
  or `entropy_floor == 1.0` (its upper edge). All three pre-date this slice; the
  same boundary on the other five `> 0` bars is pinned by existing tests. Two
  scoped re-reviews then widened the set with everything else that survives the
  whole unit tier at these guards: `black_floor`'s upper bound (255 -> 256),
  `grade_residual_max` and `chroma_spread_max` drifting `<= 0` to `<= 1`,
  `loudness_tol` drifting `<= 0` to `<= -1`, `Gates.from_dict`'s `raise ... from e`
  unpinned, and `ReelManifest.to_dict` returning the live `gates` dict rather than a
  copy (an aliasing class, not a boundary — its output goes straight to
  `json.dumps`, so nothing reaches it today). All pre-date this slice. One row.
  **P4, XS.**
- `gates.py`'s `_OWNER` loop resolves a name present on BOTH spec classes by
  raising (Task 1 fix round 1) — but `Gates` validation still lives only in
  `from_dict`, so a directly constructed `Gate("bogus", 1, "")` bypasses all six
  refusals and dies later as a bare `KeyError`. No sanctioned caller does it.
  **P4, XS.**
- A duplicate key in `GATES.json` silently keeps the last entry and the first
  entry's reason vanishes; a non-UTF-8 `GATES.json` raises `UnicodeDecodeError`
  with no path. **P4, XS.**

- [ ] **Step 4c: The vocabulary is eleven, not twelve — sweep for the old count**

Task 5 measured `loudness_target` to be a rendered set-point rather than a bar
(design §0.2a: `mix.py:16` hardcodes `_TARGET_LUFS = -14.0` into the `loudnorm`
filter and `mix.mix` takes no target, so authoring it moves the ruler and not the
thing measured, and every reel then fails). It is now in `AUTHORED_ELSEWHERE`.
Sweep every document and test for "twelve", "12 fields" and the old blocking count
of seven — the design's §0.1 table, §0.6 arithmetic and §7 are already corrected;
`gates.py`'s docstring, the skills and any test asserting a literal count are not
necessarily. The derived assertions need no change, which is the point of deriving
them.

- [ ] **Step 5: Version**

MINOR — new contract fields (`ReelManifest.gates`, `Attestation.gates`), a new CLI flag, no breaking change: **0.15.0**. Bump `.claude-plugin/plugin.json` and add the `CHANGELOG.md` entry. The heading must be `## X.Y.Z — YYYY-MM-DD` (`tests/test_plugin_manifests.py` enforces both the format and that the top entry matches the manifest).

- [ ] **Step 6: Full suite and commit**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `N passed / 1 skipped / 1 failed (test_real_runtime_is_ready, sanctioned)`.

```bash
git add docs/ CLAUDE.md CHANGELOG.md .claude-plugin/plugin.json skills/ references/
git commit -m "docs: close the threshold-surface P1 - the partition is the design; 0.15.0"
```

---

## Self-Review

**1. Spec coverage.** §0.1 partition → Task 1 `OF_CHECK`/`BLOCKING` + battery rows 2–3. §0.2 no platform table → Task 7 deferral. §0.3 the three with nowhere to be written → Task 3. §0.4 `spec_overrides` → Task 5 (left untouched, tested as such). §0.5 convention idiom → Task 4. §0.6 derived vocabulary → Task 1 + battery row 1. §1 reason required → Task 1 refusal 5 + battery row 5. §2.1–2.3 contract → Tasks 1–4. §2.4 three surfaces → Task 5. §2.5 one shape → Task 1. §3 nothing changes → the Global Constraints control + Task 6's fourth proof. §5 acceptance → Task 6. §7 deferrals → Task 7 Step 4. **Covered.**

**2. Placeholder scan.** Task 6's test bodies carry `...` where the fixture wiring goes; that is deliberate and each is accompanied by a named fixture to read first, because inventing integration scaffolding that does not match `tests/conftest.py` is worse than pointing at it. Every production snippet is complete. Task 5's `_authored` helper is complete. No "add error handling", no "similar to Task N".

**3. Type consistency.** `Gates.for_spec` returns kwargs — and is the ONLY partitioner. **A document-shaped `Gates.subset` was in this plan and was deleted after Task 3 (see the correction in Task 4); do not add it.** Every caller hands the whole document. `ReelManifest.gates` is the document shape everywhere. `process_episode(gates=…)` takes the document. `record()` rows carry `field/value/default/scope/blocking/why`; `_authored`/`authored_rows` rows carry `field/value/default/why` (no `scope`/`blocking` — the check already knows both). **That difference is deliberate and is the one thing most likely to be "fixed" into a bug: do not unify them.**

**4. Known weak point.** Battery row 1 may not be able to discriminate a correct literal, and row 18's guard may be unreachable by construction. Both are flagged in the table with what to do instead of assuming RED — per the standing rule that a row predicted RED whose named test cannot see its own mutation is a plan defect, not a surprise.
