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

from scripts.lib.footage import Footage, FootageClip

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
        if self.source is not None and not (isinstance(self.source, str) and self.source.strip()):
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


def _exclude(rule: Rule, placed: tuple[Placed, ...], by_source: dict[str, FootageClip]) -> str | None:
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
        # `banned` and a placed episode's `shot` are both built by shot_at — and
        # shot_at returns the surrounding scene-cut VALUES themselves, never a value
        # derived from `t` (footage.py's shot_at docstring). That, not "same clip",
        # is why the comparison below needs no tolerance: any two times inside the
        # SAME shot produce a bit-identical pair, even when those two calls pass
        # different (non-round) `t`, which is exactly what happens here — `banned`
        # is built from the window's start, `p.shot` from the episode's own start.
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
