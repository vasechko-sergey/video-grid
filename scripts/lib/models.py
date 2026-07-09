"""Typed contracts for the engine (design 2026-07-08): wire types that own their
JSON round-trip, and config-specs that validate in __post_init__ and raise. JSON
on disk is unchanged — to_dict/to_json reproduce the current schema."""
import json
from dataclasses import dataclass, field
from pathlib import Path


COMPOSITIONS = ("lead", "center", "break")
GRIDS = ("thirds", "phi")
MODELS = ("yolo11n-seg.pt", "yolo11s-seg.pt", "yolo11m-seg.pt")
MOTIONS = ("lateral:right", "lateral:left", "head-on", "static")
INTENTS = ("action", "static")


@dataclass(frozen=True)
class RoutePoint:
    t: float
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_dict(cls, d: dict) -> "RoutePoint":
        return cls(float(d["t"]), float(d["x"]), float(d["y"]),
                   float(d["w"]), float(d["h"]))

    def to_dict(self) -> dict:
        return {"t": self.t, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


def route_from_json(path: str | Path) -> list[RoutePoint]:
    return [RoutePoint.from_dict(d) for d in json.loads(Path(path).read_text())]


def route_to_json(points: list[RoutePoint], path: str | Path) -> None:
    Path(path).write_text(json.dumps([p.to_dict() for p in points]))


@dataclass
class TrackMeta:
    hero: int | None = None        # int track id or None
    ambiguous: bool = False
    intent: str = "action"
    features: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "TrackMeta":
        return cls(hero=d.get("hero"), ambiguous=bool(d.get("ambiguous", False)),
                   intent=d.get("intent", "action"), features=d.get("features", {}))

    def to_dict(self) -> dict:
        return {"hero": self.hero, "ambiguous": self.ambiguous,
                "intent": self.intent, "features": self.features}


@dataclass
class CropPath:
    xs: list[int]                  # list[int], parallel to the route

    @classmethod
    def from_json(cls, path: str | Path) -> "CropPath":
        return cls([int(x) for x in json.loads(Path(path).read_text())])

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps([int(x) for x in self.xs]))

    def __len__(self) -> int:
        return len(self.xs)


@dataclass
class CheckResult:
    name: str
    passed: bool | None            # bool, or None for editorial/not-implemented
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        if self.passed is None:
            return dict(self.detail)               # status-only ({"status": ...})
        return {**{k: v for k, v in self.detail.items() if k != "pass"}, "pass": self.passed}


@dataclass
class Report:
    checks: dict[str, CheckResult]  # {name: CheckResult}
    attempt: int = 1

    @property
    def overall(self) -> bool:
        return all(c.passed is not False for c in self.checks.values())

    @property
    def fail_reasons(self) -> list[str]:
        return [n for n, c in self.checks.items() if c.passed is False]

    def to_dict(self) -> dict:
        return {"checks": {n: c.to_dict() for n, c in self.checks.items()},
                "overall": self.overall, "attempt": self.attempt,
                "fail_reasons": self.fail_reasons}

    @classmethod
    def from_dict(cls, d: dict) -> "Report":
        checks = {}
        for n, cd in d["checks"].items():
            if "pass" in cd:
                checks[n] = CheckResult(n, cd["pass"],
                                        {k: v for k, v in cd.items() if k != "pass"})
            else:
                checks[n] = CheckResult(n, None, dict(cd))
        return cls(checks=checks, attempt=d.get("attempt", 1))

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


@dataclass
class Delivery:
    """Output-dims policy — imposes NO hardcoded resolution or aspect.
    mode: native | short_edge | long_edge | exact."""
    mode: str = "native"
    value: int | tuple[int, int] | None = None   # int for edges, (w, h) exact, None native

    def __post_init__(self) -> None:
        if self.mode not in ("native", "short_edge", "long_edge", "exact"):
            raise ValueError(f"Delivery.mode {self.mode!r} invalid — "
                             "native/short_edge/long_edge/exact")
        if self.mode in ("short_edge", "long_edge"):
            if not (isinstance(self.value, int) and self.value > 0):
                raise ValueError(f"Delivery {self.mode} needs a positive int, got {self.value!r}")
        elif self.mode == "exact":
            v = self.value
            if not (isinstance(v, (tuple, list)) and len(v) == 2
                    and all(isinstance(x, int) and x > 0 for x in v)):
                raise ValueError(f"Delivery exact needs (w, h) positive ints, got {v!r}")
            self.value = (int(v[0]), int(v[1]))
        if self.mode == "native":
            self.value = None

    @classmethod
    def from_spec(cls, s: str | None) -> "Delivery":
        # None | "native" | "short_edge:1080" | "long_edge:2160" | "exact:1080x1920"
        if s is None or s == "native":
            return cls("native", None)
        if not isinstance(s, str):
            raise ValueError(f"delivery spec must be a string or None, got {s!r}")
        if ":" not in s:
            raise ValueError(f"delivery spec {s!r} unparseable — "
                             "native|short_edge:N|long_edge:N|exact:WxH")
        mode, v = s.split(":", 1)
        try:
            if mode == "exact":
                w, h = (int(x) for x in v.lower().split("x"))
                value = (w, h)
            else:
                value = int(v)
        except ValueError as e:
            raise ValueError(f"delivery spec {s!r} unparseable — "
                             "native|short_edge:N|long_edge:N|exact:WxH") from e
        return cls(mode, value)

    @staticmethod
    def _even(n: float) -> int:
        n = int(round(n))
        return n - (n % 2)

    def dims(self, crop_w: int, crop_h: int) -> tuple[int, int]:
        """Even (out_w, out_h) for a crop of size (crop_w, crop_h)."""
        if crop_w <= 0 or crop_h <= 0:
            raise ValueError(f"Delivery.dims needs a positive crop, got ({crop_w}, {crop_h})")
        if self.mode == "native":
            return self._even(crop_w), self._even(crop_h)
        if self.mode == "exact":
            return int(self.value[0]), int(self.value[1])
        ar = crop_w / crop_h
        if self.mode == "short_edge":
            if crop_w <= crop_h:
                w, h = self.value, self.value / ar
            else:
                h, w = self.value, self.value * ar
        else:  # long_edge
            if crop_w >= crop_h:
                w, h = self.value, self.value / ar
            else:
                h, w = self.value, self.value * ar
        return self._even(w), self._even(h)


def _positive_seq(v: object, n: int) -> bool:
    return (isinstance(v, (tuple, list)) and len(v) == n
            and all(isinstance(x, (int, float)) and x > 0 for x in v))


@dataclass
class TrackSpec:
    src: str
    model: str = "yolo11n-seg.pt"
    seed_bbox: tuple[float, float, float, float] | None = None
    intent: str = "action"
    fps: float | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.src, str) and self.src):
            raise ValueError("TrackSpec.src must be a non-empty path")
        if self.model not in MODELS:
            raise ValueError(f"TrackSpec.model {self.model!r} not in {MODELS}")
        if self.intent not in INTENTS:
            raise ValueError(f"TrackSpec.intent {self.intent!r} not in {INTENTS}")
        if self.seed_bbox is not None and not (
                isinstance(self.seed_bbox, tuple) and len(self.seed_bbox) == 4):
            raise ValueError(f"TrackSpec.seed_bbox must be a 4-tuple or None, "
                             f"got {self.seed_bbox!r}")


@dataclass
class ReframeSpec:
    composition: str
    grid: str
    canvas: tuple
    color_means: tuple
    delivery: Delivery
    max_speed: float = 750.0
    stabilize: bool = False

    def __post_init__(self) -> None:
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"ReframeSpec.composition {self.composition!r} not in {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"ReframeSpec.grid {self.grid!r} not in {GRIDS}")
        if not _positive_seq(self.canvas, 2):
            raise ValueError(f"ReframeSpec.canvas must be [w, h] positive, got {self.canvas!r}")
        if not _positive_seq(self.color_means, 3):
            raise ValueError(f"ReframeSpec.color_means must be 3 positive means, "
                             f"got {self.color_means!r}")
        if not isinstance(self.delivery, Delivery):
            raise ValueError("ReframeSpec.delivery must be a Delivery")
        if not isinstance(self.max_speed, (int, float)) or self.max_speed <= 0:
            raise ValueError(f"ReframeSpec.max_speed must be a positive number, got {self.max_speed!r}")
        if self.stabilize:
            raise ValueError("ReframeSpec.stabilize must be False — the manifest refuses "
                             "stabilize upstream (needs_input); a True here is a bug")


@dataclass
class CheckSpec:
    composition: str
    grid: str
    target_dur: float
    canvas: tuple
    src_dims: tuple
    attempt: int = 1
    black_floor: float = 6.0
    black_rel: float = 0.35

    def __post_init__(self) -> None:
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"CheckSpec.composition {self.composition!r} not in {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"CheckSpec.grid {self.grid!r} not in {GRIDS}")
        if not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0:
            raise ValueError(f"CheckSpec.target_dur must be a positive number, got {self.target_dur!r}")
        if not _positive_seq(self.canvas, 2):
            raise ValueError(f"CheckSpec.canvas must be [w, h] positive, got {self.canvas!r}")
        if not _positive_seq(self.src_dims, 2):
            raise ValueError(f"CheckSpec.src_dims must be [w, h] positive, got {self.src_dims!r}")


@dataclass
class StoryboardSpec:
    n: int = 6
    grids: tuple = ("thirds",)
    marks: list[tuple[float, float]] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.n, int) or self.n < 1:
            raise ValueError(f"StoryboardSpec.n must be an int >= 1, got {self.n!r}")
        if not isinstance(self.grids, (tuple, list)) or not all(isinstance(g, str) for g in self.grids):
            raise ValueError(f"StoryboardSpec.grids must be a list/tuple of grid names, got {self.grids!r}")
        for g in self.grids:
            if g not in GRIDS:
                raise ValueError(f"StoryboardSpec.grid {g!r} not in {GRIDS}")
