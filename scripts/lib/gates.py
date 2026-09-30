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

Pure: dicts in, dicts out. The only IO is from_json and the existence check in
beside_project.
"""
import json
from dataclasses import dataclass, fields
from pathlib import Path

# _ADVISORY_CHECKS is private to models, and importing it here is deliberate: it is
# the one place the advisory/blocking partition is written down, and BLOCKING below
# is derived from it. A second copy of that list in this module would be the very
# defect this module exists to remove.
#
# The dependency runs one way: gates imports models, so models must never import
# gates at module scope. Code in models that needs it imports it inside the function
# that uses it.
from scripts.lib.models import CheckSpec, ReelCheckSpec, _ADVISORY_CHECKS

#: Names that sit on a check spec but are authored somewhere else entirely. Each value
#: completes "it is authored in ..." in the refusal, so it has to be true of the tree as
#: it is: variety_min was once described as authored in the EDL, and nothing in edl.py or
#: edl_to_reel.py mentions it. Refused by name rather than ignored: a value silently
#: dropped here would read as authored, which is the worse of the two failures.
AUTHORED_ELSEWHERE: dict[str, str] = {
    "target_dur": "the EDL — EDL.target_dur, which edit_plan._back_edge_target "
                  "computes from the footage",
    "variety_min": "the reel manifest — ReelManifest.variety_min, which is the "
                   "'variety_min' key of EPISODES.json. No producer sets it today",
    "composition": "each episode's own manifest (Manifest.composition)",
    "grid": "each episode's own manifest (Manifest.grid)",
    "attempt": "the retry loop, which counts attempts itself",
}

#: field -> the check whose bar it sets. BLOCKING is derived from this table, so for a
#: reel-scope field the name IS the advisory/blocking partition: a wrong name silently
#: moves a bar across it. For an episode-scope field the name cannot change the answer
#: (episode checks have no advisory registry, since Report.overall lets every failing
#: check block, so they are blocking by absence from _ADVISORY_CHECKS rather than by
#: membership in anything). That makes it documentation, and documentation rots, so
#: tests/test_gates.py checks every entry against the driver that writes the check.
OF_CHECK: dict[str, str] = {
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
    # "black_frames", NOT "black": the episode gate writes checks["black_frames"] in
    # check_episode, and `black` is a REEL check in check_reel that reads no threshold.
    "black_floor": "black_frames",
    "black_rel": "black_frames",
    "entropy_floor": "grade_damage",
}

_OWNER: dict[str, type] = {}
for _cls in (ReelCheckSpec, CheckSpec):
    for _f in fields(_cls):
        if _f.name in AUTHORED_ELSEWHERE:
            continue
        if _f.name in _OWNER:
            raise ValueError(
                f"{_f.name!r} is a field of both {_OWNER[_f.name].__name__} and "
                f"{_cls.__name__}, so a gate for it has no single owner and would reach "
                f"only one of them, silently. Rename one of the fields, or add "
                f"{_f.name!r} to AUTHORED_ELSEWHERE with where it is really authored")
        _OWNER[_f.name] = _cls

#: The gateable thresholds, derived (design §0.6).
FIELDS: tuple[str, ...] = tuple(sorted(_OWNER))

#: The thresholds whose bar can stop a delivery. _ADVISORY_CHECKS is a REEL registry, so an
#: episode-scope field is blocking by absence from it: an episode check that ever turned
#: advisory would be classed blocking here until it gains a registry of its own.
BLOCKING: frozenset[str] = frozenset(
    n for n, c in OF_CHECK.items() if c not in _ADVISORY_CHECKS)

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
    value: int | float
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
                    f"{AUTHORED_ELSEWHERE[name]}. Remove the {name!r} entry from "
                    f"{where}: setting it here would give it two homes and make one "
                    f"of them silent")
            if name not in _OWNER:
                raise ValueError(
                    f"{where} names {name!r}, which is not a gate threshold. The "
                    f"gate thresholds are: {', '.join(FIELDS)}")
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{where} entry {name!r} must be an object with exactly 'value' "
                    f"and 'why', got {entry!r}. A bare value is refused: moving a "
                    f"bar without recording why is what this file exists to prevent")
            why = entry.get("why")
            if not (isinstance(why, str) and why.strip()):
                raise ValueError(
                    f"{where} entry {name!r} needs a non-empty 'why', got {entry!r} — "
                    f"the reason a bar was moved is the record a later reader has to "
                    f"judge the delivery by, and it is required, not encouraged")
            if set(entry) != {"value", "why"}:
                raise ValueError(
                    f"{where} entry {name!r} must have exactly the keys 'value' and "
                    f"'why', got {list(entry)} — add the missing one or remove the "
                    f"extra")
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

    def for_spec(self, spec_cls: type) -> dict:
        """The kwargs subset `spec_cls` owns — the call site never partitions."""
        if not (isinstance(spec_cls, type) and spec_cls in _SCOPE):
            raise ValueError(
                f"Gates.for_spec takes {' or '.join(c.__name__ for c in _SCOPE)}, got "
                f"{spec_cls!r} — any other class owns none of the gates, so it would "
                f"silently get {{}} and every authored bar would be dropped")
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


def beside_project(project_path: str | Path) -> Gates:
    """The gates authored beside `project_path`: GATES.json in the same directory, or an
    empty set when there is none (design §0.5/§2.1).

    The ONE place the convention is spelled. Its readers must agree on where the file is —
    edl_to_reel's phase-1 arms and process_episode's own CLI — because a reader that looked
    somewhere else would judge one episode against a bar its siblings were not judged
    against, in silence (design §2.3). Found by convention and never named by a flag: a flag
    can be dropped on a re-run, and a dropped threshold flag reverts the bar without a word.

    A file that exists and cannot be loaded raises ValueError naming its path, and that is
    never read as 'no gates'. There is no waiver and no fallback to defaults."""
    p = Path(project_path).parent / "GATES.json"
    return Gates.from_json(p) if p.exists() else Gates()
