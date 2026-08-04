"""Typed contracts for the engine (design 2026-07-08): wire types that own their
JSON round-trip, and config-specs that validate in __post_init__ and raise. JSON
on disk is unchanged — to_dict/to_json reproduce the current schema."""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import color
from scripts.lib.geometry import even


COMPOSITIONS = ("lead", "center", "break")
GRIDS = ("thirds", "phi")
MODELS = ("yolo11n-seg.pt", "yolo11s-seg.pt", "yolo11m-seg.pt")
MOTIONS = ("lateral:right", "lateral:left", "head-on", "static")
INTENTS = ("action", "static")
HERO_RULES = ("largest", "leftmost")          # §5.10 rule pins — mechanical, no identity claim
HERO_KINDS = ("bbox", "rule", "track", "cast")
DEGRADED_LEVELS = ("flow", "manual")   # TrackMeta.degraded: which fallback rung authored the
                                       # route (None = the clean YOLO tracker). Design 2026-07-21 §5.


def is_bbox_coord(v: object) -> bool:
    """May `v` be a seed-bbox coordinate? One spelling, two readers — HeroPin's own
    __post_init__ and hero.resolve(), which must agree because resolve() coerces with
    float() before handing over and would otherwise launder past HeroPin's guard.

    Three silent landmines, one per term:
      - isinstance(True, int) is True, so a bare int test lets `hero: [true, ...]`
        become coordinate 1.0.
      - json.loads accepts bare Infinity/-Infinity/NaN and float() passes them
        straight through. _seed_track's IoU then goes nan, matches nobody, and
        surfaces as hero-unmatched — "the pinned person may not be in this episode"
        about a pin that named no pixel.
      - json.loads builds ints of any size, and float() raises OverflowError — NOT
        ValueError — on one past float range. manifest.validate() catches only
        ValueError, so that escapes the soft gate as a crash.

    The magnitude term is a comparison, not math.isfinite(v), on purpose: isfinite
    converts its argument to a double first, so it raises the very OverflowError it
    is meant to catch on the 400-digit int (verified — it closes Infinity/NaN and
    nothing else). int-vs-float comparison is exact and cannot overflow, and NaN
    fails it too, so one term covers both halves. Order matters: the isinstance terms
    must short-circuit first, or abs() lands on a str.
    """
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and abs(v) <= sys.float_info.max)


@dataclass(frozen=True)
class RoutePoint:
    t: float
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_dict(cls, d: dict) -> "RoutePoint":
        # Top level checked FIRST, before d["t"] — the subscript raised a bare TypeError on a
        # non-dict. route_from_json feeds each element here, so a route.json of bare scalars
        # ([1, 2, ...]) — valid JSON, and route.json is also the §5.10 answer channel a human
        # supplies — reached the four bare readers (check_episode/check_reel/process_episode/
        # reframe) as a crash.
        if not isinstance(d, dict):
            raise ValueError(f"RoutePoint.from_dict: expected a route-point object with t/x/y/w/h "
                             f"fields, got {type(d).__name__} — re-run track to regenerate route.json")
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
    pin_matched: bool | None = None    # None = no pin was given; False = a pin was given and
                                       # nothing matched it → orchestration raises hero-unmatched
    degraded: str | None = None    # None = clean (YOLO) | "flow" | "manual" (design 2026-07-21 §5) —
                                    # ROUTE-side provenance, the twin of PathMeta.pan/.stabilized
    stitched: list[int] = field(default_factory=list)   # ids merged onto the route BEYOND the hero
                                                        # by an ID-switch stitch (design 2026-07-28 §6). [] = clean single id.

    @classmethod
    def from_dict(cls, d: dict) -> "TrackMeta":
        # Top level checked FIRST, before d.get. No production reader today (track.py builds a
        # TrackMeta directly) — but from_dict is public contract surface, and a guard that holds
        # only while nobody calls it is not a guard.
        if not isinstance(d, dict):
            raise ValueError(f"TrackMeta.from_dict: expected a track-meta object with 'hero'/"
                             f"'intent' fields, got {type(d).__name__} — re-run track to "
                             f"regenerate the meta sidecar")
        return cls(hero=d.get("hero"), ambiguous=bool(d.get("ambiguous", False)),
                   intent=d.get("intent", "action"), features=d.get("features", {}),
                   pin_matched=d.get("pin_matched"), degraded=d.get("degraded"),
                   stitched=list(d.get("stitched", [])))

    def to_dict(self) -> dict:
        return {"hero": self.hero, "ambiguous": self.ambiguous,
                "intent": self.intent, "features": self.features,
                "pin_matched": self.pin_matched, "degraded": self.degraded,
                "stitched": self.stitched}


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

    `pan` is the PROVENANCE bit. A generated path has no observation behind it,
    so check_episode must not judge composition against a route (there is none)
    nor report a green `continuity` (checks.continuity([]) returns pass=True —
    the absence is not even loud). One bit here is what keeps those reports
    honest; see design 2026-07-19 §2.1.

    `stabilized` is the other provenance bit. It says the pixels reframe cut were
    already vidstab-corrected, which is what makes the route it cut them by
    trustworthy — that pairing is the load-bearing claim of design 2026-07-20 §1,
    and a reader of the sidecar has no other way to check it.
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
    background: str = "blur"
    pan: bool = False      # True ⇒ the path was GENERATED, not observed (design 2026-07-19 §5)
    stabilized: bool = False   # True ⇒ reframe's `src` was a vidstab pre-stage output, not the
                               # raw segment (design 2026-07-20 §6.2)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "crop_w": self.crop_w, "crop_h": self.crop_h,
                "crop_y": self.crop_y, "src_dims": list(self.src_dims),
                "canvas": list(self.canvas), "out_dims": list(self.out_dims),
                "rect_px": list(self.rect_px), "freedom": self.freedom,
                "background": self.background, "pan": self.pan,
                "stabilized": self.stabilized}

    @classmethod
    def from_dict(cls, d: dict) -> "PathMeta":
        # Top level checked FIRST, before the try. Two distinct failures, two types by design:
        # a non-dict `d` is wrong-TYPE construction → ValueError-with-remedy (coding-standards
        # §37), the from_dict CONTRACT boundary; a dict with a missing/bad FIELD is machine-
        # sidecar corruption → RuntimeError (below), an INTEGRITY check on valid-shaped content.
        # Without this guard the non-dict case fell into the integrity arm and laundered a bare
        # "list indices must be integers" into the message.
        if not isinstance(d, dict):
            raise ValueError(f"PathMeta.from_dict: expected a path.meta.json object with mode/"
                             f"crop_w/crop_h/... fields, got {type(d).__name__} — re-run reframe "
                             f"to regenerate path.meta.json")
        try:
            return cls(mode=d["mode"], crop_w=int(d["crop_w"]), crop_h=int(d["crop_h"]),
                       crop_y=int(d["crop_y"]), src_dims=tuple(d["src_dims"]),
                       canvas=tuple(d["canvas"]), out_dims=tuple(d["out_dims"]),
                       rect_px=tuple(d["rect_px"]), freedom=int(d["freedom"]),
                       # `.get`, uniquely among these fields: a sidecar written before
                       # fit-solid has no `background` key, and `blur` was the only value
                       # the field could have held then — the substitution is provably the
                       # truth for those files, not a guessed default. Every OTHER missing
                       # key stays an integrity failure below.
                       background=d.get("background", "blur"),
                       # Same one-key exemption, same reasoning: a sidecar written before
                       # the pan slice has no `pan` key, and its absence honestly means the
                       # path came from a route — `pan` did not exist as a source yet.
                       pan=d.get("pan", False),
                       # Third key on the same exemption, same reasoning: a sidecar
                       # written before the stabilize slice has no `stabilized` key,
                       # and its absence honestly means the source was raw —
                       # stabilization was refused upstream until then.
                       stabilized=d.get("stabilized", False))
        except KeyError as e:
            raise RuntimeError(
                f"path.meta.json has no field {e} — re-run reframe; it writes the sidecar "
                "in one call, so a partial one means that run died mid-write") from e
        except (TypeError, ValueError) as e:
            # a field is present but unusable: crop_w="abc", src_dims=null. int()
            # and tuple() raise bare, and the caller cannot tell which file to blame
            raise RuntimeError(
                f"path.meta.json holds an unusable field ({e}) — re-run reframe; the "
                "sidecar is machine-written, so a bad type means it was hand-edited "
                "or truncated") from e

    @classmethod
    def from_json(cls, path: str | Path) -> "PathMeta":
        p = Path(path)
        if not p.exists():
            raise RuntimeError(
                f"{p} is missing — re-run reframe; it writes path.meta.json beside "
                "path.json, and the checks read what was actually cropped from it")
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            # the exact case from_dict's message names: reframe died mid-write, so
            # the file is truncated and never parses. Without this, the caller gets
            # a bare JSONDecodeError naming a column, not a file and not a remedy.
            raise RuntimeError(
                f"{p} is corrupt ({e}) — delete it and re-run reframe; it writes the "
                "sidecar in one call, so an unparseable one means that run died "
                "mid-write") from e
        return cls.from_dict(d)

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
        # Top level checked FIRST, before d["checks"] — the subscript raised a bare TypeError on
        # a non-dict. No production reader (check_episode writes report.json via to_dict; nobody
        # reads it back through from_dict), but from_dict is public contract surface and owes
        # ValueError-with-remedy per coding-standards.
        if not isinstance(d, dict):
            raise ValueError(f"Report.from_dict: expected a report object with a 'checks' map, "
                             f"got {type(d).__name__} — re-run check_episode to regenerate the report")
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
            if self.value[0] % 2 or self.value[1] % 2:
                ew, eh = self.value[0] & ~1, self.value[1] & ~1
                raise ValueError(
                    f"Delivery exact needs even dimensions, got {self.value} — "
                    f"h.264 requires both sides divisible by 2 under yuv420p; "
                    f"use ({ew}, {eh}) or ({ew + 2}, {eh + 2})")
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


@dataclass(frozen=True)
class HeroPin:
    """A RESOLVED §5.10 hero pin — the one shape every consumer agrees on.

    The manifest's `hero` is a raw value (tuple / str / int); this is what
    hero.resolve() turns it into, once, at the boundary. Frozen: resolve hands it
    over already-coerced, so nothing downstream re-guesses with isinstance.
    """
    kind: str
    bbox: tuple[float, float, float, float] | None = None
    rule: str = ""
    track_id: int | None = None
    name: str = ""
    descriptor: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in HERO_KINDS:
            raise ValueError(f"HeroPin.kind {self.kind!r} unknown — expected one of {HERO_KINDS}")
        if self.kind == "bbox" and not (isinstance(self.bbox, tuple) and len(self.bbox) == 4
                                        and all(is_bbox_coord(v) for v in self.bbox)):
            raise ValueError(f"HeroPin(kind='bbox').bbox must be a 4-tuple of finite numbers "
                             f"(centre-format x,y,w,h in source px), got {self.bbox!r}")
        if self.kind == "rule" and self.rule not in HERO_RULES:
            raise ValueError(f"HeroPin(kind='rule').rule {self.rule!r} unknown — "
                             f"expected one of {HERO_RULES}")
        if self.kind == "track" and (isinstance(self.track_id, bool)
                                     or not isinstance(self.track_id, int)):
            # isinstance(True, int) is True, so a bare `not isinstance(x, int)` guard
            # would let a bool slip through as a valid id — `hero: true` in a manifest
            # would then silently resolve to track id 1. The explicit bool disjunct
            # closes that gap (its position in the `or` doesn't matter; both are
            # independent conditions).
            raise ValueError(f"HeroPin(kind='track').track_id must be an int, got {self.track_id!r}")
        if self.kind == "cast":
            if not (isinstance(self.name, str) and self.name):
                raise ValueError("HeroPin(kind='cast').name must be a non-empty cast name")
            if not (isinstance(self.descriptor, tuple) and self.descriptor
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            for v in self.descriptor)):
                raise ValueError(f"HeroPin(kind='cast').descriptor must be a non-empty tuple "
                                 f"of numbers, got {self.descriptor!r}")


@dataclass
class TrackSpec:
    src: str
    model: str = "yolo11n-seg.pt"
    pin: HeroPin | None = None     # a RESOLVED hero pin (hero.resolve), never a raw manifest value
    intent: str = "action"
    fps: float | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.src, str) and self.src):
            raise ValueError("TrackSpec.src must be a non-empty path")
        if self.model not in MODELS:
            raise ValueError(f"TrackSpec.model {self.model!r} not in {MODELS}")
        if self.intent not in INTENTS:
            raise ValueError(f"TrackSpec.intent {self.intent!r} not in {INTENTS}")
        if self.pin is not None and not isinstance(self.pin, HeroPin):
            raise ValueError(f"TrackSpec.pin must be a HeroPin or None, got {self.pin!r} — "
                             f"resolve the manifest's raw hero through hero.resolve() first")


@dataclass(frozen=True)
class PanSpec:
    """A generated, constant-velocity camera move (design 2026-07-19).

    `start`/`end` are fractions of the crop's AVAILABLE HORIZONTAL FREEDOM
    (`freedom = src_w - crop_w`), not of the source width: 0.0 puts the crop hard
    left, 1.0 hard right. Freedom is the right denominator because it is what
    actually exists to travel, and it is already the number the layouts model
    uses to decide whether a composition is controllable at all.

    DIRECTION IS THE SIGN of `end - start`. No direction vocabulary exists — that
    would be a second spelling for what the numbers already say, and this repo
    has just spent a slice deleting a name that duplicated a parameter
    (`fit-blur` -> `fit`).

    WIRE NAMES DIFFER FROM FIELD NAMES, uniquely in this repo: the JSON keys are
    `from`/`to`, because that is what reads correctly in an EDL, while `from` is
    a Python keyword and cannot be a field name. A `from_`-with-underscore field
    would leak that constraint into the wire contract. `from_dict`/`to_dict`
    carry the mapping, and it lives in exactly one place. Do not "fix" this.
    """
    start: float
    end: float

    def __post_init__(self) -> None:
        for name, v in (("start", self.start), ("end", self.end)):
            # bool BEFORE int: isinstance(True, int) is True, so {"from": true}
            # would otherwise silently mean 1.0
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(
                    f"PanSpec.{name} must be a number in [0.0, 1.0] — a fraction of the "
                    f"crop's horizontal freedom, where 0.0 is hard left and 1.0 hard "
                    f"right; got {v!r}")
            # NO float() here. json.loads builds ints of any size and float()
            # raises OverflowError — NOT ValueError — on one past float range;
            # manifest.validate()'s soft gate catches only ValueError, so that
            # would escape as a crash. int-vs-float comparison is exact, cannot
            # overflow, and NaN fails it too. Same landmine is_bbox_coord closes.
            if not 0.0 <= v <= 1.0:
                raise ValueError(
                    f"PanSpec.{name} must be within [0.0, 1.0] — a fraction of the crop's "
                    f"horizontal freedom, not a pixel offset; got {v!r}")
        if self.start == self.end:
            raise ValueError(
                f"PanSpec start and end are both {self.start!r} — a pan that does not move "
                "is not a pan. Give it an extent, or drop the `pan` field to let the "
                "tracked route place the crop instead")

    def to_dict(self) -> dict:
        return {"from": self.start, "to": self.end}

    @classmethod
    def from_dict(cls, d: dict) -> "PanSpec":
        if not isinstance(d, dict):
            raise ValueError(
                f"PanSpec.from_dict: expected an object with 'from' and 'to' fractions, "
                f"got {type(d).__name__} — write pan as {{\"from\": 0.0, \"to\": 1.0}}")
        missing = [k for k in ("from", "to") if k not in d]
        if missing:
            raise ValueError(
                f"PanSpec.from_dict: missing {', '.join(missing)} — pan needs both "
                "'from' and 'to' as fractions of the crop's horizontal freedom")
        return cls(start=d["from"], end=d["to"])


LAYOUT_MODES = ("fill", "fit", "insert")
BACKGROUNDS = ("blur", "solid")


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
    horizontal freedom the tracker needs — the same trade fit makes.

    `border_px` may be any non-negative int: the outer card width is already even,
    so the content width `ow - 2*border_px` is even whatever the border's parity.
    """
    mode: str
    crop_aspect: str | tuple[int, int] = "canvas"
    crop_scale: float = 1.0
    rect: tuple[float, float, float] | None = None
    background: str = "blur"
    background_color: str = "black"      # `solid` only — an ffmpeg colour name or hex
    border_px: int = 0
    border_color: str = "white"

    def __post_init__(self) -> None:
        if self.mode not in LAYOUT_MODES:
            raise ValueError(f"LayoutSpec.mode {self.mode!r} unknown — fill/fit/insert "
                             "(split is a separate plan)")
        if self.background not in BACKGROUNDS:
            raise ValueError(f"LayoutSpec.background {self.background!r} unknown — "
                             f"{BACKGROUNDS}")
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
        if not isinstance(self.background_color, str) or not self.background_color:
            raise ValueError(f"LayoutSpec.background_color must be a non-empty ffmpeg colour "
                             f"name or hex, got {self.background_color!r} — e.g. 'black', "
                             "'#000000'")
        if any(c in self.background_color for c in ",:;'[]\\"):
            raise ValueError(f"LayoutSpec.background_color {self.background_color!r} contains a "
                             "character that would break the ffmpeg filtergraph — use a "
                             "colour name like 'black' or a hex literal like '#000000'")
        if self.mode == "fill":
            if self.crop_aspect != "canvas":
                raise ValueError("LayoutSpec: fill must use crop_aspect 'canvas' — a fill that "
                                 "crops to another aspect needs a background, i.e. it is fit")
            if self.rect not in (None, (0.0, 0.0, 1.0)):
                raise ValueError(f"LayoutSpec: fill covers the whole canvas, but rect is "
                                 f"{self.rect!r} — a fill with a smaller rect is an insert, "
                                 "and must say so")
            if self.border_px:
                raise ValueError(f"LayoutSpec: fill covers the canvas edge to edge, so a "
                                 f"border has nothing to sit on, got border_px="
                                 f"{self.border_px} — a bordered frame is an insert")
            if self.background != "blur":
                raise ValueError(f"LayoutSpec: fill covers the canvas edge to edge, so there is "
                                 f"no background to fill, got background="
                                 f"{self.background!r} — a filler needs fit or insert")
        if self.mode == "fit" and self.rect is not None:
            raise ValueError(f"LayoutSpec: fit spans the full canvas width, so rect must "
                             f"be None, got {self.rect!r} — use insert to place a smaller rect")
        if self.mode == "insert" and self.rect is None:
            raise ValueError("LayoutSpec: insert needs a rect (x, y, w) in canvas fractions — "
                             "without one it is fit")


@dataclass
class ReframeSpec:
    composition: str
    grid: str
    canvas: tuple
    color_means: tuple
    delivery: Delivery
    layout: LayoutSpec = field(default_factory=lambda: LayoutSpec(mode="fill"))
    max_speed: float = 750.0
    smooth_window_s: float = 0.25  # savgol span over the tracked path, IN SECONDS. max_speed
                                   # caps how FAR the crop may move per frame; this sets over how
                                   # long a wobble is averaged away. They are not interchangeable: a
                                   # low-amplitude, high-frequency hitch (the jitter check's whole
                                   # subject) already sits under any max_speed the ladder reaches,
                                   # so damping speed cannot touch it. Seconds and not frames
                                   # because it is a filter cutoff — see pathsmooth.window_frames,
                                   # resolved against the clip's own fps at render time.
    color_correct: tuple | None = None
    white_balance: float = 0.0  # grey-world neutralize toward the common channel average,
                                # FIRST in the chain; 0 = off (identity), so an episode
                                # authored before this renders byte-identically — see
                                # color.white_balance_arg.
    black_point: float = 0.0   # subtracted from the toe BEFORE the gain — see color.black_point_arg.
                               # 0.0 emits no filter at all, so every episode authored before this
                               # field existed renders the same command it always did.
    highlight: float = 1.0     # white pulled down to this AFTER the gain — see
                               # color.highlight_arg. 1.0 emits no curve at all.
    saturation: float = 1.0    # chroma scale AFTER the gain — see color.saturation_arg.
                               # 1.0 emits nothing. The one hue-preserving way to pull an
                               # over-vivid source (aerial sky/water) toward a tamer one.
    shadow_red: float = 0.0    # red toe lifted by this at black, back to identity by a
                               # quarter scale — see color.shadow_red_arg. The one knob that
                               # neutralizes a green/cyan black without touching skin or a
                               # red board. 0.0 emits no filter.
    mid_blue: float = 1.0      # blue scaled by this in the MIDTONES only — see
                               # color.mid_blue_arg. Neutralizes sky bounce on skin without
                               # touching shadows or foam. 1.0 emits no filter.
    dip: float = 0.0           # fade in from / out to a dark grey for this many seconds —
                               # see color.dip_arg. A transition that costs no duration.
    # (p5, p50, p95) of this episode's own crop, and the common profile the reel carries
    # them onto. Runs FIRST, before the gain — profile, then level, which is the order
    # the two stages actually depend on. None on both leaves the chain exactly as it was.
    tone_src: "tuple[float, float, float] | None" = None
    tone_dst: "tuple[float, float, float] | None" = None
    pan: "PanSpec | None" = None

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
        if (isinstance(self.smooth_window_s, bool)
                or not isinstance(self.smooth_window_s, (int, float))
                or not 0 < self.smooth_window_s <= 2.0):
            raise ValueError(
                f"ReframeSpec.smooth_window_s must be a span in seconds in (0, 2.0], got "
                f"{self.smooth_window_s!r} — it is a filter cutoff, and a window longer than "
                "a couple of seconds stops following the subject rather than smoothing it")
        if (isinstance(self.white_balance, bool) or not isinstance(self.white_balance, (int, float))
                or not 0 <= self.white_balance <= 1):
            raise ValueError(f"ReframeSpec.white_balance must be a fraction in [0, 1], "
                             f"got {self.white_balance!r}")
        if (isinstance(self.black_point, bool)
                or not isinstance(self.black_point, (int, float))
                or not 0 <= self.black_point <= 0.35):
            raise ValueError(f"ReframeSpec.black_point must be a fraction in [0, 0.35], "
                             f"got {self.black_point!r}")
        if (isinstance(self.dip, bool) or not isinstance(self.dip, (int, float))
                or not 0 <= self.dip <= 0.5):
            raise ValueError(f"ReframeSpec.dip must be seconds in [0, 0.5], got {self.dip!r}")
        if (isinstance(self.mid_blue, bool) or not isinstance(self.mid_blue, (int, float))
                or not 0.80 <= self.mid_blue <= 1.20):
            raise ValueError(f"ReframeSpec.mid_blue must be a fraction in [0.80, 1.20], "
                             f"got {self.mid_blue!r}")
        if (isinstance(self.shadow_red, bool) or not isinstance(self.shadow_red, (int, float))
                or not 0 <= self.shadow_red <= 0.20):
            raise ValueError(f"ReframeSpec.shadow_red must be a fraction in [0, 0.20], "
                             f"got {self.shadow_red!r}")
        if (isinstance(self.saturation, bool) or not isinstance(self.saturation, (int, float))
                or not 0.5 <= self.saturation <= 1.5):
            raise ValueError(f"ReframeSpec.saturation must be a fraction in [0.5, 1.5], "
                             f"got {self.saturation!r}")
        if (isinstance(self.highlight, bool) or not isinstance(self.highlight, (int, float))
                or not 0.6 <= self.highlight <= 1.0):
            raise ValueError(f"ReframeSpec.highlight must be a fraction in [0.6, 1.0], "
                             f"got {self.highlight!r}")
        if (self.tone_src is None) != (self.tone_dst is None):
            raise ValueError("ReframeSpec.tone_src and tone_dst come as a pair — a source "
                             "profile with no target (or a target with no source) names no "
                             "transfer; set both or neither")
        if self.tone_src is not None:
            color.tone_arg(tuple(self.tone_src), tuple(self.tone_dst))   # validates both
        if self.color_correct is not None and not _positive_seq(self.color_correct, 3):
            raise ValueError(f"ReframeSpec.color_correct must be 3 positive per-channel "
                             f"factors or None, got {self.color_correct!r}")
        if self.pan is not None and not isinstance(self.pan, PanSpec):
            raise ValueError(
                f"ReframeSpec.pan must be a PanSpec or None, got {type(self.pan).__name__} — "
                "build it with PanSpec.from_dict({'from': …, 'to': …}); a pan replaces the "
                "tracked route as the source of the crop's x(t)")


@dataclass
class CheckSpec:
    composition: str
    grid: str
    target_dur: float
    attempt: int = 1
    black_floor: float = 6.0
    black_rel: float = 0.35
    hue_drift_max: float = 25.0   # deg: advisory subject hue-drift ceiling (color_fidelity, §7)

    def __post_init__(self) -> None:
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"CheckSpec.composition {self.composition!r} not in {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"CheckSpec.grid {self.grid!r} not in {GRIDS}")
        if not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0:
            raise ValueError(f"CheckSpec.target_dur must be a positive number, got {self.target_dur!r}")
        if (isinstance(self.hue_drift_max, bool) or not isinstance(self.hue_drift_max, (int, float))
                or self.hue_drift_max <= 0):
            raise ValueError(f"CheckSpec.hue_drift_max must be a positive number of degrees, "
                             f"got {self.hue_drift_max!r}")


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


@dataclass
class ExportProfile:
    """One typed export profile (design §2). New platforms are new instances,
    not new code. Silent by default (acodec None → -an); Phase B sets acodec."""
    vcodec: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    pix_fmt: str = "yuv420p"
    # Tag the delivered range explicitly. yuv420p means limited by convention, but a
    # convention is not a tag: an untagged file is read as limited by some players and
    # full by others, and a platform's re-encode guesses too. assembly.DELIVERY_RANGE
    # is what the master is assembled in — deliver must not quietly ship something else.
    color_range: str = "tv"
    container: str = "mp4"
    faststart: bool = True
    fps: float | None = None
    maxrate_kbps: int | None = None
    acodec: str | None = None
    abitrate_kbps: int | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.vcodec, str) and self.vcodec):
            raise ValueError("ExportProfile.vcodec must be a non-empty codec name")
        if isinstance(self.crf, bool) or not isinstance(self.crf, int) or not 0 <= self.crf <= 51:
            raise ValueError(f"ExportProfile.crf must be an int in 0..51, got {self.crf!r}")
        if not (isinstance(self.pix_fmt, str) and self.pix_fmt):
            raise ValueError("ExportProfile.pix_fmt must be a non-empty pixel format")
        if self.color_range not in ("tv", "pc"):
            raise ValueError(f"ExportProfile.color_range must be 'tv' (limited) or 'pc' "
                             f"(full), got {self.color_range!r}")
        if not (isinstance(self.container, str) and self.container):
            raise ValueError("ExportProfile.container must be a non-empty container name")
        if self.fps is not None and not (isinstance(self.fps, (int, float))
                                         and not isinstance(self.fps, bool) and self.fps > 0):
            raise ValueError(f"ExportProfile.fps must be a positive number or None, got {self.fps!r}")
        if self.maxrate_kbps is not None and not (isinstance(self.maxrate_kbps, int)
                                                  and not isinstance(self.maxrate_kbps, bool)
                                                  and self.maxrate_kbps > 0):
            raise ValueError(f"ExportProfile.maxrate_kbps must be a positive int or None, got {self.maxrate_kbps!r}")
        if self.acodec is not None and not (isinstance(self.acodec, str) and self.acodec):
            raise ValueError("ExportProfile.acodec must be a non-empty codec name or None")
        if self.abitrate_kbps is not None:
            if self.acodec is None:
                raise ValueError("ExportProfile.abitrate_kbps is set but acodec is None — a bitrate "
                                 "with no audio codec cannot be applied; set acodec or clear abitrate_kbps")
            if isinstance(self.abitrate_kbps, bool) or not isinstance(self.abitrate_kbps, int) \
                    or self.abitrate_kbps <= 0:
                raise ValueError(f"ExportProfile.abitrate_kbps must be a positive int or None, got {self.abitrate_kbps!r}")

    def args(self) -> list[str]:
        """ffmpeg OUTPUT args (no -i, no output path). The one place the encode
        landmines live — yuv420p, faststart; deliver adds no scale (even dims come
        in from the master by construction)."""
        a = ["-c:v", self.vcodec, "-crf", str(self.crf), "-preset", self.preset,
             "-pix_fmt", self.pix_fmt, "-color_range", self.color_range]
        if self.maxrate_kbps is not None:
            a += ["-maxrate", f"{self.maxrate_kbps}k", "-bufsize", f"{2 * self.maxrate_kbps}k"]
        if self.fps is not None:
            a += ["-r", str(self.fps)]
        if self.acodec is None:
            a += ["-an"]
        else:
            a += ["-c:a", self.acodec]
            if self.abitrate_kbps is not None:
                a += ["-b:a", f"{self.abitrate_kbps}k"]
        if self.faststart:
            a += ["-movflags", "+faststart"]
        return a


REEL_H264 = ExportProfile()


@dataclass
class ReelCheckSpec:
    """Thresholds for the whole-reel mechanical gate (design §4), mirrors CheckSpec."""
    target_dur: float
    variety_min: int = 8               # min phash Hamming distance between adjacent episodes
    color_delta_max: float = 12.0      # §9 across-cut mean-RGB delta ceiling
    beat_tol: float = 0.05             # advisory: max cut-vs-beat deviation (s) that still reads "on beat"
    loudness_target: float = -14.0     # EBU R128 integrated LUFS target (montage §5.12)
    loudness_tol: float = 1.0          # ± band around the target
    clip_tol: float = 0.02             # advisory: frame-edge overshoot fraction tolerated before key_action flags
    bar_symmetry_tol: float = 0.02     # advisory: max left/right (top/bottom) pad-bar mismatch (canvas fraction)
    layout_jump_max: float = 0.6       # advisory: max layout-jump score across a cut before transitions flags
    length_retime_max: float = 1.0     # max shortfall (target − dur) build_reel absorbs by
                                       # re-timing the target to the reel's real length (§3)

    def __post_init__(self) -> None:
        if not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0:
            raise ValueError(f"ReelCheckSpec.target_dur must be a positive number, got {self.target_dur!r}")
        if isinstance(self.variety_min, bool) or not isinstance(self.variety_min, int) or self.variety_min < 0:
            raise ValueError(f"ReelCheckSpec.variety_min must be a non-negative int, got {self.variety_min!r}")
        if not isinstance(self.color_delta_max, (int, float)) or self.color_delta_max <= 0:
            raise ValueError(f"ReelCheckSpec.color_delta_max must be a positive number, got {self.color_delta_max!r}")
        if not isinstance(self.beat_tol, (int, float)) or self.beat_tol <= 0:
            raise ValueError(f"ReelCheckSpec.beat_tol must be a positive number of seconds, got {self.beat_tol!r}")
        if not isinstance(self.loudness_target, (int, float)):
            raise ValueError(f"ReelCheckSpec.loudness_target must be a number (LUFS), got {self.loudness_target!r}")
        if not isinstance(self.loudness_tol, (int, float)) or self.loudness_tol <= 0:
            raise ValueError(f"ReelCheckSpec.loudness_tol must be a positive number, got {self.loudness_tol!r}")
        for name in ("clip_tol", "bar_symmetry_tol"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v < 0.5:
                raise ValueError(f"ReelCheckSpec.{name} must be a fraction in [0.0, 0.5), got {v!r}")
        if not isinstance(self.layout_jump_max, (int, float)) or self.layout_jump_max <= 0:
            raise ValueError(f"ReelCheckSpec.layout_jump_max must be a positive number, got {self.layout_jump_max!r}")
        if not isinstance(self.length_retime_max, (int, float)) or self.length_retime_max <= 0:
            raise ValueError(f"ReelCheckSpec.length_retime_max must be a positive number of "
                             f"seconds, got {self.length_retime_max!r}")


@dataclass
class MusicSpec:
    """MUSIC.json — the lean music analysis a reel is cut to (design §2, Phase B).
    Config-spec: validates on construction so a malformed track spec fails loud,
    not into a silent mis-mix. Beats are reel-relative (0.0 = reel start)."""
    track: str
    start_offset: float
    duration: float
    tempo: float
    beats: tuple[float, ...]
    energy: tuple[float, ...]
    energy_hz: float

    def __post_init__(self) -> None:
        if not (isinstance(self.track, str) and self.track):
            raise ValueError("MusicSpec.track must be a non-empty path to the audio file")
        if not isinstance(self.start_offset, (int, float)) or self.start_offset < 0:
            raise ValueError(f"MusicSpec.start_offset must be >= 0 seconds, got {self.start_offset!r}")
        if not isinstance(self.duration, (int, float)) or self.duration <= 0:
            raise ValueError(f"MusicSpec.duration must be a positive number of seconds, got {self.duration!r}")
        if not isinstance(self.tempo, (int, float)) or self.tempo <= 0:
            raise ValueError(f"MusicSpec.tempo must be a positive BPM, got {self.tempo!r}")
        if not isinstance(self.beats, (tuple, list)):
            raise ValueError("MusicSpec.beats must be a list of reel-relative beat times (seconds); a "
                             "null/scalar means analyze() didn't run or the MUSIC.json is malformed")
        try:
            self.beats = tuple(float(b) for b in self.beats)
        except (TypeError, ValueError):
            raise ValueError("MusicSpec.beats must contain only numeric beat times (seconds) — a "
                             "non-numeric entry means the MUSIC.json is malformed") from None
        if not self.beats:
            raise ValueError("MusicSpec.beats is empty — analyze() found no beats; check the track/window")
        if list(self.beats) != sorted(self.beats):
            raise ValueError("MusicSpec.beats must be ascending — analyze() emits them in time order")
        for b in self.beats:
            if not (0.0 <= b <= self.duration):
                raise ValueError(f"MusicSpec.beats has {b} outside [0, {self.duration}] — beats are "
                                 "reel-relative; a stray value means the analysis window is wrong")
        if not isinstance(self.energy, (tuple, list)):
            raise ValueError("MusicSpec.energy must be a list of RMS values; a null/scalar means "
                             "analyze() didn't run or the MUSIC.json is malformed")
        try:
            self.energy = tuple(float(e) for e in self.energy)
        except (TypeError, ValueError):
            raise ValueError("MusicSpec.energy must contain only numeric RMS values — a non-numeric "
                             "entry means the MUSIC.json is malformed") from None
        if not self.energy:
            raise ValueError("MusicSpec.energy is empty — analyze() produced no RMS curve")
        if not isinstance(self.energy_hz, (int, float)) or self.energy_hz <= 0:
            raise ValueError(f"MusicSpec.energy_hz must be a positive sample rate, got {self.energy_hz!r}")

    def to_dict(self) -> dict:
        return {"track": self.track, "start_offset": self.start_offset, "duration": self.duration,
                "tempo": self.tempo, "beats": list(self.beats),
                "energy": list(self.energy), "energy_hz": self.energy_hz}

    @classmethod
    def from_dict(cls, d: dict) -> "MusicSpec":
        # The top level is checked FIRST, before the .get calls below: those defaults hand
        # __post_init__ something it can reject with a remedy, but only once `d` is a dict at all
        # — a bare array/string/number/bool/null raised AttributeError out of all four bare
        # from_json readers (build_reel, mix, draft, pacing) instead.
        if not isinstance(d, dict):
            raise ValueError(f"MusicSpec.from_dict: expected a MUSIC.json object with 'beats'/"
                             f"'energy' lists, got {type(d).__name__} — re-run beats to regenerate "
                             f"MUSIC.json")
        # .get with validation-tripping defaults → a missing key surfaces a remedy, not a bare KeyError.
        # beats/energy pass through raw (not tuple()-wrapped) so __post_init__ guards a null/scalar with a
        # remedy instead of a bare TypeError from tuple(None) — the malformed-MUSIC.json case (design §2).
        return cls(track=d.get("track", ""), start_offset=d.get("start_offset", 0.0),
                   duration=d.get("duration", 0.0), tempo=d.get("tempo", 0.0),
                   beats=d.get("beats", ()), energy=d.get("energy", ()),
                   energy_hz=d.get("energy_hz", 0.0))

    @classmethod
    def from_json(cls, path: str | Path) -> "MusicSpec":
        return cls.from_dict(json.loads(Path(path).read_text()))


@dataclass
class ReelFailure:
    """One attributed reel-check failure (design §177 machine-readable). The
    Phase A.5 driver reads escalate_to/episode_idx straight off this."""
    check: str
    escalate_to: str                        # "reprocess" | "edit-plan" | "pacing"
    episode_idx: int | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"check": self.check, "escalate_to": self.escalate_to,
                "episode_idx": self.episode_idx, "detail": self.detail}

    @classmethod
    def from_dict(cls, d: dict) -> "ReelFailure":
        # Top level checked FIRST, before d["check"] — the subscript raised a bare TypeError on
        # a non-dict. Read via ReelReport.from_dict (now guarded); from_dict is public contract
        # surface and owes ValueError-with-remedy.
        if not isinstance(d, dict):
            raise ValueError(f"ReelFailure.from_dict: expected a reel-failure object with check/"
                             f"escalate_to fields, got {type(d).__name__} — re-run check_reel to "
                             f"regenerate the reel report")
        return cls(check=d["check"], escalate_to=d["escalate_to"],
                   episode_idx=d.get("episode_idx"), detail=d.get("detail", {}))


_ADVISORY_CHECKS = ("beat", "safe_zones", "key_action", "pad_bars", "transitions")   # measured + reported but non-blocking (design §5)


@dataclass
class ReelReport:
    """Whole-reel check artifact (design §2). Reuses CheckResult; overall is a
    property — a None check never fails, and an advisory check (in _ADVISORY_CHECKS,
    e.g. beat) never blocks even when False (design §5), mirroring the episode Report."""
    checks: dict[str, CheckResult]
    fail_reasons: list[ReelFailure] = field(default_factory=list)
    episode_count: int = 0
    wall_s: float = 0.0                      # §11 binding: wall-time in every check report
    # sha256 of the master this report actually measured (design §4). deliver refuses
    # a report that does not bind to the file being shipped — check_reel is the only
    # producer and always sets it, so an empty value means the report was not written
    # by check_reel.
    master_digest: str = ""

    @property
    def overall(self) -> bool:
        return all(c.passed is not False
                   for n, c in self.checks.items() if n not in _ADVISORY_CHECKS)

    def to_dict(self) -> dict:
        return {"checks": {n: c.to_dict() for n, c in self.checks.items()},
                "overall": self.overall,
                "fail_reasons": [f.to_dict() for f in self.fail_reasons],
                "episode_count": self.episode_count, "wall_s": self.wall_s,
                "master_digest": self.master_digest}

    @classmethod
    def from_dict(cls, d: dict) -> "ReelReport":
        # Top level checked FIRST, before d["checks"] — the subscript raised a bare TypeError on
        # a non-dict. deliver.py:94 reads ReelReport.from_dict(json.loads(...)) with no except,
        # so it crashed deliver on a wrong-shaped --report file.
        if not isinstance(d, dict):
            raise ValueError(f"ReelReport.from_dict: expected a reel-report object with a 'checks' "
                             f"map, got {type(d).__name__} — re-run check_reel to regenerate the "
                             f"reel report")
        checks = {}
        for n, cd in d["checks"].items():
            if "pass" in cd:
                checks[n] = CheckResult(n, cd["pass"], {k: v for k, v in cd.items() if k != "pass"})
            else:
                checks[n] = CheckResult(n, None, dict(cd))
        return cls(checks=checks,
                   fail_reasons=[ReelFailure.from_dict(f) for f in d.get("fail_reasons", [])],
                   episode_count=d.get("episode_count", 0), wall_s=d.get("wall_s", 0.0),
                   master_digest=d.get("master_digest", ""))

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def _load_manifest(m: dict | str) -> dict:
    """A reel-manifest episode's `manifest` is either an inline dict or a path to
    an episode manifest JSON (both forms are valid; §2)."""
    if isinstance(m, dict):
        return m
    if isinstance(m, str):
        return json.loads(Path(m).read_text())
    raise ValueError(f"reel-manifest episode 'manifest' must be an inline dict or a path to "
                     f"a manifest JSON, got {m!r}")


@dataclass(frozen=True)
class ReelEpisode:
    """One entry in a ReelManifest: the per-episode manifest (so a reprocess can
    rebuild it), the locked clip loop-1 produced, and the frozen route.json (a
    reprocess reuses it — colour/black fixes never move the track). `path`/`meta`
    are the frozen path.json / path.meta.json sidecars — safe_zones (§5.13) projects
    the subject through them; empty = geometry unavailable (safe_zones not-checked).

    `route` is None when the episode's path was GENERATED — a pan (design
    2026-07-19). There is then no observation to freeze and no route.json on disk:
    process_episode deliberately writes none, because an empty route.json already
    means "the tracker ran and found nobody". `path`/`meta` are still set for a pan
    — reframe wrote both sidecars, and they are as real as any tracked episode's;
    only the route is absent.
    """
    manifest: dict
    clip: str
    route: str | None = None
    path: str = ""
    meta: str = ""


@dataclass
class ReelManifest:
    """Typed input to build_reel (design §2). Episodes are already locked by
    loop-1 (process_episode); build_reel loops assemble/check/reprocess over them.
    Validates hard — an empty list or a missing clip/route is a caller bug."""
    episodes: list[ReelEpisode]
    target_dur: float
    variety_min: int = 8
    color_delta_max: float = 12.0
    cap: int = 3
    changelog: str = ""
    music: str | None = None           # MUSIC.json path (design §6); None → a silent reel, as Phase A.5
    ambient: bool = True               # duck each clip's nat-sound under the music (§5.12); False → pure-music stem
    sfx: bool = False                  # whoosh on major transitions (§5.12); default off (opt-in stylistic accent)
    platform: str = ""                 # UI safe-zone table key (§5.13); "" → generic; from Spec.platform
    provenance: dict = field(default_factory=dict)   # run-level record threaded to deliver (§6)

    def __post_init__(self) -> None:
        if not self.episodes:
            raise ValueError("ReelManifest.episodes is empty — a reel needs at least one "
                             "locked episode; produce them with process_episode first")
        for k, e in enumerate(self.episodes):
            if not isinstance(e, ReelEpisode):
                raise ValueError(f"ReelManifest.episodes[{k}] must be a ReelEpisode")
            if not isinstance(e.manifest, dict):
                raise ValueError(f"ReelManifest.episodes[{k}].manifest must be a dict — the "
                                 "per-episode manifest a reprocess rebuilds the episode from")
            if not (isinstance(e.clip, str) and e.clip):
                raise ValueError(f"ReelManifest.episodes[{k}].clip is empty — the locked clip path")
            # route is None under a pan: the path was GENERATED, so there is no
            # observation to freeze and process_episode wrote no route.json. An
            # empty STRING is still a bug — that is a caller who meant to pass a
            # path and lost it, which None states deliberately and "" does not.
            if e.route is not None and not (isinstance(e.route, str) and e.route):
                raise ValueError(f"ReelManifest.episodes[{k}].route must be a route.json path "
                                 "or None (None = a generated pan path, which has no route); "
                                 "got an empty or non-string value")
            if bool(e.path) != bool(e.meta):
                raise ValueError(f"ReelManifest.episodes[{k}]: path and meta must both be set or "
                                 "both empty — a lone sidecar cannot project the subject for safe_zones")
        if isinstance(self.cap, bool) or not isinstance(self.cap, int) or self.cap < 1:
            raise ValueError(f"ReelManifest.cap must be an int >= 1, got {self.cap!r}")
        if self.music is not None and not (isinstance(self.music, str) and self.music):
            raise ValueError("ReelManifest.music must be a MUSIC.json path or None, got an empty/non-str value")
        if not isinstance(self.ambient, bool):
            raise ValueError(f"ReelManifest.ambient must be a bool (True → duck ambient under "
                             f"music, False → pure-music stem), got {self.ambient!r}")
        if not isinstance(self.sfx, bool):
            raise ValueError(f"ReelManifest.sfx must be a bool (True → whoosh on major "
                             f"transitions, False → no SFX), got {self.sfx!r}")
        if not isinstance(self.platform, str):
            raise ValueError(f"ReelManifest.platform must be a string label (e.g. 'tiktok'), "
                             f"got {self.platform!r}")
        if not isinstance(self.provenance, dict):
            raise ValueError(f"ReelManifest.provenance must be an object, got "
                             f"{type(self.provenance).__name__}")
        self.check_spec  # forces ReelCheckSpec validation of target_dur/variety_min/color_delta_max

    @property
    def check_spec(self) -> ReelCheckSpec:
        return ReelCheckSpec(self.target_dur, self.variety_min, self.color_delta_max)

    @classmethod
    def from_dict(cls, d: dict) -> "ReelManifest":
        # Top level checked FIRST, before d.get — 'episodes' and each element were validated
        # while `d` itself was not, so a wrong-shaped reel manifest raised a bare AttributeError
        # out of build_reel.py's bare from_json call.
        if not isinstance(d, dict):
            raise ValueError(
                f"ReelManifest.from_dict: expected a reel-manifest object with an 'episodes' "
                f"list, got {type(d).__name__} — produce it with process_episode first")
        eps_in = d.get("episodes")
        if not isinstance(eps_in, list):
            raise ValueError(
                "ReelManifest.from_dict: 'episodes' must be a list of "
                "{manifest, clip, route} objects; produce them with process_episode first")
        for k, e in enumerate(eps_in):
            if not isinstance(e, dict):
                raise ValueError(
                    f"ReelManifest.from_dict: episodes[{k}] must be a "
                    "{manifest, clip, route} object, got a non-object")
        eps = [ReelEpisode(manifest=_load_manifest(e.get("manifest")),
                           clip=e.get("clip", ""), route=e.get("route", ""),
                           path=e.get("path", ""), meta=e.get("meta", ""))
               for e in eps_in]
        return cls(episodes=eps, target_dur=d.get("target_dur"),
                   variety_min=d.get("variety_min", 8),
                   color_delta_max=d.get("color_delta_max", 12.0),
                   cap=d.get("cap", 3), changelog=d.get("changelog", ""),
                   music=d.get("music"), ambient=d.get("ambient", True),
                   sfx=d.get("sfx", False), platform=d.get("platform", ""),
                   provenance=d.get("provenance") or {})

    @classmethod
    def from_json(cls, path: str | Path) -> "ReelManifest":
        return cls.from_dict(json.loads(Path(path).read_text()))
