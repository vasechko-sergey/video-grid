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
