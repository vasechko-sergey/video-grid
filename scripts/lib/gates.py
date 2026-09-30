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

# _ADVISORY_CHECKS is private to models, and importing it here is deliberate: it is
# the one place the advisory/blocking partition is written down, and BLOCKING below
# is derived from it. A second copy of that list in this module would be the very
# defect this module exists to remove.
#
# The dependency runs one way: gates imports models, so models must never import
# gates at module scope. Code in models that needs it imports it inside the function
# that uses it.
from scripts.lib.models import CheckSpec, ReelCheckSpec, _ADVISORY_CHECKS

#: Names that sit on a check spec but are authored somewhere else entirely.
#: Refused by name rather than ignored: a value silently dropped here would read
#: as authored, which is the worse of the two failures.
AUTHORED_ELSEWHERE: dict[str, str] = {
    "target_dur": "the EDL — EDL.target_dur, which edit_plan._back_edge_target "
                  "computes from the footage",
    "variety_min": "the EDL, carried to the gate as ReelManifest.variety_min",
    "composition": "each episode's own manifest (Manifest.composition)",
    "grid": "each episode's own manifest (Manifest.grid)",
    "attempt": "the retry loop's own counter — it is not an author's value",
}

#: field -> the check whose bar it sets. Not documentation: BLOCKING is derived
#: from it, so the advisory/blocking partition has exactly one source.
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
    "black_floor": "black",
    "black_rel": "black",
    "entropy_floor": "grade_damage",
}

_OWNER: dict[str, type] = {}
for _cls in (ReelCheckSpec, CheckSpec):
    for _f in fields(_cls):
        if _f.name not in AUTHORED_ELSEWHERE:
            _OWNER[_f.name] = _cls

#: The twelve, derived (design §0.6).
FIELDS: tuple[str, ...] = tuple(sorted(_OWNER))

#: The seven whose bar can stop a delivery.
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
                    f"{AUTHORED_ELSEWHERE[name]}. Setting it here would give it two "
                    f"homes and make one of them silent")
            if name not in _OWNER:
                raise ValueError(
                    f"{where} names {name!r}, which is not a gate threshold. The "
                    f"gate thresholds are: {', '.join(FIELDS)}")
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

    def for_spec(self, spec_cls: type) -> dict:
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
