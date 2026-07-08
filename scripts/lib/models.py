"""Typed contracts for the engine (design 2026-07-08): wire types that own their
JSON round-trip, and config-specs that validate in __post_init__ and raise. JSON
on disk is unchanged — to_dict/to_json reproduce the current schema."""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RoutePoint:
    t: float
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_dict(cls, d):
        return cls(float(d["t"]), float(d["x"]), float(d["y"]),
                   float(d["w"]), float(d["h"]))

    def to_dict(self):
        return {"t": self.t, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


def route_from_json(path):
    return [RoutePoint.from_dict(d) for d in json.loads(Path(path).read_text())]


def route_to_json(points, path):
    Path(path).write_text(json.dumps([p.to_dict() for p in points]))


@dataclass
class TrackMeta:
    hero: object = None            # int track id or None
    ambiguous: bool = False
    intent: str = "action"
    features: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d):
        return cls(hero=d.get("hero"), ambiguous=bool(d.get("ambiguous", False)),
                   intent=d.get("intent", "action"), features=d.get("features", {}))

    def to_dict(self):
        return {"hero": self.hero, "ambiguous": self.ambiguous,
                "intent": self.intent, "features": self.features}


@dataclass
class CropPath:
    xs: list                       # list[int], parallel to the route

    @classmethod
    def from_json(cls, path):
        return cls([int(x) for x in json.loads(Path(path).read_text())])

    def to_json(self, path):
        Path(path).write_text(json.dumps([int(x) for x in self.xs]))

    def __len__(self):
        return len(self.xs)


@dataclass
class CheckResult:
    name: str
    passed: object                 # bool, or None for editorial/not-implemented
    detail: dict = field(default_factory=dict)

    def to_dict(self):
        if self.passed is None:
            return dict(self.detail)               # status-only ({"status": ...})
        return {**self.detail, "pass": self.passed}


@dataclass
class Report:
    checks: dict                   # {name: CheckResult}
    attempt: int = 1

    @property
    def overall(self):
        return all(c.passed is not False for c in self.checks.values())

    @property
    def fail_reasons(self):
        return [n for n, c in self.checks.items() if c.passed is False]

    def to_dict(self):
        return {"checks": {n: c.to_dict() for n, c in self.checks.items()},
                "overall": self.overall, "attempt": self.attempt,
                "fail_reasons": self.fail_reasons}

    @classmethod
    def from_dict(cls, d):
        checks = {}
        for n, cd in d["checks"].items():
            if "pass" in cd:
                checks[n] = CheckResult(n, cd["pass"],
                                        {k: v for k, v in cd.items() if k != "pass"})
            else:
                checks[n] = CheckResult(n, None, dict(cd))
        return cls(checks=checks, attempt=d.get("attempt", 1))

    def write(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
