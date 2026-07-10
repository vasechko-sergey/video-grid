"""Typed contracts for the engine (design 2026-07-08): wire types that own their
JSON round-trip, and config-specs that validate in __post_init__ and raise. JSON
on disk is unchanged — to_dict/to_json reproduce the current schema."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib.geometry import even


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
class PathMeta:
    """What reframe ACTUALLY cut and where it put it — written beside path.json,
    exactly as track.py writes route.meta.json beside route.json.

    check_episode and storyboard read this instead of re-deriving the crop from
    the canvas. Under a non-fill layout the re-derivation is silently wrong: it
    returns the canvas-aspect crop width, divides by it, and reports a verdict
    about a composition that never happened.
    """
    mode: str
    crop_w: int
    crop_h: int
    crop_y: int
    src_dims: tuple[int, int]
    canvas: tuple[int, int]
    out_dims: tuple[int, int]
    rect_px: tuple[int, int, int, int]      # x, y, w, h in output pixels
    freedom: int

    def to_dict(self) -> dict:
        return {"mode": self.mode, "crop_w": self.crop_w, "crop_h": self.crop_h,
                "crop_y": self.crop_y, "src_dims": list(self.src_dims),
                "canvas": list(self.canvas), "out_dims": list(self.out_dims),
                "rect_px": list(self.rect_px), "freedom": self.freedom}

    @classmethod
    def from_dict(cls, d: dict) -> "PathMeta":
        try:
            return cls(mode=d["mode"], crop_w=int(d["crop_w"]), crop_h=int(d["crop_h"]),
                       crop_y=int(d["crop_y"]), src_dims=tuple(d["src_dims"]),
                       canvas=tuple(d["canvas"]), out_dims=tuple(d["out_dims"]),
                       rect_px=tuple(d["rect_px"]), freedom=int(d["freedom"]))
        except KeyError as e:
            raise RuntimeError(
                f"path.meta.json has no field {e} — re-run reframe; it writes the sidecar "
                "in one call, so a partial one means that run died mid-write") from e

    @classmethod
    def from_json(cls, path: str | Path) -> "PathMeta":
        p = Path(path)
        if not p.exists():
            raise RuntimeError(
                f"{p} is missing — re-run reframe; it writes path.meta.json beside "
                "path.json, and the checks read what was actually cropped from it")
        return cls.from_dict(json.loads(p.read_text()))

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


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

    def dims(self, crop_w: float, crop_h: float) -> tuple[int, int]:
        """Even (out_w, out_h) for a composite of size (crop_w, crop_h).

        Takes floats: the native canvas height is `canvas_w * ah / aw` and
        evening either side before the other is derived would drift it.
        """
        if crop_w <= 0 or crop_h <= 0:
            raise ValueError(f"Delivery.dims needs a positive crop, got ({crop_w}, {crop_h})")
        if self.mode == "native":
            return even(crop_w), even(crop_h)
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
        return even(w), even(h)


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


LAYOUT_MODES = ("fill", "fit-blur", "insert")
BACKGROUNDS = ("blur",)


@dataclass
class LayoutSpec:
    """Where the source lands in the canvas (spec §7). Three parameters, not
    three code paths: what to cut (aspect + scale), where to put it (rect), and
    what fills the rest (background).

    `rect` is (x, y, w) in canvas fractions — its HEIGHT is derived from the crop
    aspect, so a rect cannot disagree with what is placed inside it. None means
    full width, vertically centred.

    `fill` constrains crop_aspect and rect but deliberately not crop_scale: a
    scaled-down fill still fills the canvas, trading resolution for the
    horizontal freedom the tracker needs — the same trade fit-blur makes.

    `border_px` may be any non-negative int: the outer card width is already even,
    so the content width `ow - 2*border_px` is even whatever the border's parity.
    """
    mode: str
    crop_aspect: str | tuple[int, int] = "canvas"
    crop_scale: float = 1.0
    rect: tuple[float, float, float] | None = None
    background: str = "blur"
    border_px: int = 0
    border_color: str = "white"

    def __post_init__(self) -> None:
        if self.mode not in LAYOUT_MODES:
            raise ValueError(f"LayoutSpec.mode {self.mode!r} unknown — fill/fit-blur/insert "
                             "(split and pan are separate plans)")
        if self.background not in BACKGROUNDS:
            raise ValueError(f"LayoutSpec.background {self.background!r} unknown — "
                             f"{BACKGROUNDS}; solid lands with fit-solid")
        if not isinstance(self.crop_scale, (int, float)) or not 0.0 < self.crop_scale <= 1.0:
            raise ValueError(f"LayoutSpec.crop_scale must be in (0.0, 1.0], got "
                             f"{self.crop_scale!r} — 1.0 is the largest crop that fits")
        if isinstance(self.crop_aspect, str):
            if self.crop_aspect not in ("canvas", "source"):
                raise ValueError(f"LayoutSpec.crop_aspect {self.crop_aspect!r} unknown — "
                                 "'canvas', 'source', or a (w, h) pair of positive ints")
        elif not (isinstance(self.crop_aspect, tuple) and len(self.crop_aspect) == 2
                  and all(isinstance(v, int) and v > 0 for v in self.crop_aspect)):
            raise ValueError(f"LayoutSpec.crop_aspect {self.crop_aspect!r} invalid — "
                             "'canvas', 'source', or a (w, h) pair of positive ints")
        if self.rect is not None:
            if not (isinstance(self.rect, tuple) and len(self.rect) == 3
                    and all(isinstance(v, (int, float)) for v in self.rect)):
                raise ValueError(f"LayoutSpec.rect must be (x, y, w) canvas fractions or None, "
                                 f"got {self.rect!r} — height derives from the crop aspect")
            x, y, w = self.rect
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0):
                raise ValueError(f"LayoutSpec.rect {self.rect!r}: x/y must be fractions in "
                                 "[0, 1] and w must be in (0, 1]")
            if x + w > 1.0:
                raise ValueError(f"LayoutSpec.rect {self.rect!r}: x + w = {x + w:.3f} > 1.0 — "
                                 "the rect runs off the right edge of the canvas")
        if isinstance(self.border_px, bool) or not isinstance(self.border_px, int) \
                or self.border_px < 0:
            raise ValueError(f"LayoutSpec.border_px must be a non-negative int, got "
                             f"{self.border_px!r} — 0 means no border")
        if not isinstance(self.border_color, str) or not self.border_color:
            raise ValueError(f"LayoutSpec.border_color must be a non-empty ffmpeg colour "
                             f"name or hex, got {self.border_color!r} — e.g. 'white', '#ffffff'")
        if any(c in self.border_color for c in ",:;'[]\\"):
            raise ValueError(f"LayoutSpec.border_color {self.border_color!r} contains a "
                             "character that would break the ffmpeg filtergraph — use a "
                             "colour name like 'white' or a hex literal like '#ffffff'")
        if self.mode == "fill":
            if self.crop_aspect != "canvas":
                raise ValueError("LayoutSpec: fill must use crop_aspect 'canvas' — a fill that "
                                 "crops to another aspect needs a background, i.e. it is fit-blur")
            if self.rect not in (None, (0.0, 0.0, 1.0)):
                raise ValueError(f"LayoutSpec: fill covers the whole canvas, but rect is "
                                 f"{self.rect!r} — a fill with a smaller rect is an insert, "
                                 "and must say so")
            if self.border_px:
                raise ValueError(f"LayoutSpec: fill covers the canvas edge to edge, so a "
                                 f"border has nothing to sit on, got border_px="
                                 f"{self.border_px} — a bordered frame is an insert")
        if self.mode == "fit-blur" and self.rect is not None:
            raise ValueError(f"LayoutSpec: fit-blur spans the full canvas width, so rect must "
                             f"be None, got {self.rect!r} — use insert to place a smaller rect")
        if self.mode == "insert" and self.rect is None:
            raise ValueError("LayoutSpec: insert needs a rect (x, y, w) in canvas fractions — "
                             "without one it is fit-blur")


@dataclass
class ReframeSpec:
    composition: str
    grid: str
    canvas: tuple
    color_means: tuple
    delivery: Delivery
    layout: LayoutSpec = field(default_factory=lambda: LayoutSpec(mode="fill"))
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
        if not isinstance(self.layout, LayoutSpec):
            raise ValueError("ReframeSpec.layout must be a LayoutSpec — "
                             "build it from the manifest's layout fields")
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
