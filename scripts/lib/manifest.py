"""Episode manifest + machine-checkable validation (§5.10, §4.1).

The manifest is the process-episode subagent's entire brief (§14.4: full task
inline, self-contained). validate() is the deterministic half of "ask before
starting if ambiguous" — missing/contradictory/unsupported fields are caught
here, before any YOLO/ffmpeg runs, so the orchestrator returns needs_input
instead of guessing.
"""
from dataclasses import dataclass

from scripts.lib import hero as hero_lib   # aliased: this module already has a `hero` FIELD
                                           # (Manifest.hero, and from_dict's local `hero = ...`)
                                           # — a bare `import hero` would be shadowed by that
                                           # local the day a method needs both in one scope, and
                                           # `hero.resolve(...)` reads as a field access at a
                                           # glance next to `m.hero`. hero_lib keeps every call
                                           # site unambiguous.
from scripts.lib import vidstab
from scripts.lib.footage import Cast
from scripts.lib.models import COMPOSITIONS, GRIDS, MODELS, MOTIONS, Delivery, LayoutSpec, PanSpec

REQUIRED = ("segment", "out_path", "composition", "grid", "canvas", "target_dur")
OPTIONAL = ("layout", "motion", "pan", "hero", "cast", "color_means", "stabilize", "model",
            "delivery", "crop_aspect", "crop_scale", "rect", "background", "background_color",
            "border_px", "border_color")
LAYOUTS_SUPPORTED = ("fill", "fit", "insert")   # split → its own plan; pan is not a layout
DEFAULT_COLOR = (105, 122, 137)
DEFAULT_MODEL = "yolo11n-seg.pt"


@dataclass
class Manifest:
    segment: str
    out_path: str
    composition: str
    grid: str
    canvas: tuple
    target_dur: float
    layout: str = "fill"
    motion: str | None = None
    pan: dict | None = None          # {"from": f, "to": f} — a GENERATED crop path
                                     # (design 2026-07-19). Kept as the raw wire dict here
                                     # and built into a PanSpec by process_episode, exactly
                                     # as layout fields are built into a LayoutSpec.
    hero: tuple | str | int | None = None
    cast: str = ""                       # cast.json path — a cast-name hero needs the registry,
                                         # and the manifest is a self-contained brief (§14.4)
    color_means: tuple = DEFAULT_COLOR
    stabilize: bool = False
    model: str = DEFAULT_MODEL
    delivery: str = "native"
    crop_aspect: str | tuple[int, int] = "canvas"
    crop_scale: float = 1.0
    rect: tuple[float, float, float] | None = None
    background: str = "blur"
    background_color: str = "black"
    border_px: int = 0
    border_color: str = "white"

    @classmethod
    def from_dict(cls, d: dict) -> "Manifest":
        # The top level is checked FIRST, before the REQUIRED loop's d.get. from_dict is the
        # HARD half (it raises); the SOFT gate is at its two callers, which turn every raise
        # into needs_input / stop_and_report — both already catch (KeyError, TypeError,
        # ValueError), so this ValueError needs no call-site change and reports softly like
        # the rest. AttributeError was the one type neither caught: it crashed the gate that
        # exists precisely to never crash. ValueError (not KeyError) per coding-standards —
        # KeyError is this function's idiom for a MISSING key, not for a wrong-typed argument.
        if not isinstance(d, dict):
            raise ValueError(f"Manifest.from_dict: expected a manifest object with the required "
                             f"fields {REQUIRED}, got {type(d).__name__} — author the manifest as "
                             f"a JSON object, not a bare value")
        # explicit null counts as absent — LLM-authored JSON emits null for "no value"
        for k in REQUIRED:
            if d.get(k) is None:
                raise KeyError(f"manifest missing required field: {k}")
        unknown = set(d) - set(REQUIRED) - set(OPTIONAL)
        if unknown:
            raise KeyError(f"manifest has unknown field(s) {sorted(unknown)} — typo? "
                           f"optional fields are {OPTIONAL}")
        cm = d.get("color_means")
        hero = d.get("hero")
        if isinstance(hero, list):
            hero = tuple(hero)          # JSON arrays → tuple so the seed-bbox pin survives
        model = d.get("model")
        layout = d.get("layout")        # explicit null → default, like model/color_means
        delivery = d.get("delivery")
        crop_aspect = d.get("crop_aspect")
        if isinstance(crop_aspect, list):
            crop_aspect = tuple(crop_aspect)   # JSON has no tuples — LayoutSpec rejects lists by design
        rect = d.get("rect")
        if isinstance(rect, list):
            rect = tuple(rect)
        crop_scale = d.get("crop_scale")
        background = d.get("background")
        background_color = d.get("background_color")
        border_px = d.get("border_px")
        border_color = d.get("border_color")
        return cls(
            segment=d["segment"], out_path=d["out_path"],
            composition=d["composition"], grid=d["grid"],
            canvas=tuple(d["canvas"]), target_dur=float(d["target_dur"]),
            layout=layout if layout is not None else "fill", motion=d.get("motion"),
            pan=d.get("pan"),
            hero=hero, cast=d.get("cast") or "",
            color_means=tuple(cm) if cm is not None else DEFAULT_COLOR,
            stabilize=bool(d.get("stabilize", False)),
            model=model if model is not None else DEFAULT_MODEL,
            delivery=delivery if delivery is not None else "native",
            crop_aspect=crop_aspect if crop_aspect is not None else (
                "canvas" if (layout or "fill") == "fill" else "source"),
            crop_scale=float(crop_scale) if crop_scale is not None else 1.0,
            rect=rect,
            background=background if background is not None else "blur",
            background_color=background_color if background_color is not None else "black",
            border_px=int(border_px) if border_px is not None else 0,
            border_color=border_color if border_color is not None else "white",
        )


def validate(m: Manifest, cast: Cast | None = None) -> list[str]:
    """Return a list of human-readable problem strings (empty = ok).

    `cast` is the LOADED registry, handed in by the caller: this gate does no
    I/O (see the crop_aspect note below), so it cannot read m.cast itself.
    """
    problems = []
    if not (isinstance(m.segment, str) and m.segment):
        problems.append("segment must be a non-empty path")
    if not (isinstance(m.out_path, str) and m.out_path):
        problems.append("out_path must be a non-empty path")
    if m.composition not in COMPOSITIONS:
        problems.append(f"composition {m.composition!r} unknown — expected {COMPOSITIONS}")
    if m.grid not in GRIDS:
        problems.append(f"grid {m.grid!r} unknown — expected {GRIDS} "
                        "(golden-canon is a static editorial layer, not a tracking target)")
    if m.layout not in LAYOUTS_SUPPORTED:
        problems.append(f"layout {m.layout!r} not supported — fill/fit/insert only; "
                        "split lands in its own plan, and a pan is not a layout — "
                        "set the `pan` field instead")
    if m.layout in LAYOUTS_SUPPORTED:
        # LayoutSpec is the HARD backstop; here it is the soft gate's oracle. Its
        # ValueError (unknown mode/bg, bad scale/aspect/rect, fill+border, list
        # instead of tuple) becomes a problem string — the gate never raises.
        try:
            LayoutSpec(mode=m.layout, crop_aspect=m.crop_aspect, crop_scale=m.crop_scale,
                       rect=m.rect, background=m.background,
                       background_color=m.background_color,
                       border_px=m.border_px, border_color=m.border_color)
        except ValueError as e:
            problems.append(str(e))
        else:
            # Zero horizontal freedom is decidable here for exactly one spelling:
            # a source-aspect crop at full scale IS the whole frame, whatever the
            # footage. It is NOT decidable for crop_aspect [16, 9] on 16:9
            # footage, which has the same zero freedom — the gate would have to
            # probe the file, and this gate runs before YOLO. Do not "fix" it to
            # probe here. The sidecar's `freedom` is the real safety net:
            # check_episode turns the composition check editorial when it is zero.
            if (m.composition == "lead" and m.crop_scale == 1.0
                    and m.crop_aspect == "source"):
                problems.append(
                    "composition 'lead' has no horizontal freedom: crop_aspect 'source' at "
                    "crop_scale 1.0 shows the whole frame — set crop_scale below 1.0, or "
                    "composition to 'break'")
    # `cast` is a PATH, checked with the same predicate segment/out_path get above
    # ("" = absent, the documented default). It is the one field from_dict passes
    # through raw — canvas/target_dur/crop_scale/border_px are all coerced there and
    # so cannot arrive as garbage, but `cast=d.get("cast") or ""` coerces nothing, so
    # {"cast": 123} reaches this gate intact. It has to be caught HERE and not merely
    # downstream: Cast.from_json would hand 123 to Path() before reading a byte of
    # JSON and raise TypeError, which is not in any caller's except surface.
    if not isinstance(m.cast, str):
        problems.append(f"cast must be a cast.json path string (or absent); got {m.cast!r}")
    # hero.resolve is the HARD backstop; here it is the soft gate's oracle, exactly
    # like LayoutSpec above. Its ValueError (a malformed pin, a cast name with no
    # registry, a name absent from the cast) becomes a problem string — the gate
    # never raises. One function for validation and for the shell's real
    # resolution, so the two cannot drift apart.
    try:
        hero_lib.resolve(m.hero, cast)
    except ValueError as e:
        problems.append(str(e))
    # Stabilization is implemented (design 2026-07-20) — what is left to check is
    # whether THIS ffmpeg can do it. Same soft-manifest / hard-engine pairing the
    # layout uses: a problem string here so the shell returns needs_input with a
    # remedy, and vidstab.require() again in the engine as the hard backstop.
    #
    # Guarded on the flag because require() spawns a real `ffmpeg -filters`
    # (ffbin.has_filter is uncached on purpose), and validate() runs in a great
    # many tests that have nothing to do with vidstab.
    if m.stabilize:
        try:
            vidstab.require()
        except ValueError as e:
            problems.append(str(e))
    if not (isinstance(m.canvas, tuple) and len(m.canvas) == 2
            and all(isinstance(v, (int, float)) and v > 0 for v in m.canvas)):
        problems.append(f"canvas must be [w, h] with positive numbers; got {m.canvas!r}")
    if not (isinstance(m.color_means, tuple) and len(m.color_means) == 3
            and all(isinstance(v, (int, float)) and v > 0 for v in m.color_means)):
        problems.append(f"color_means must be 3 positive channel means [R, G, B]; "
                        f"got {m.color_means!r}")
    if m.target_dur <= 0:
        problems.append(f"target_dur must be positive; got {m.target_dur}")
    if m.motion is not None and m.motion not in MOTIONS:
        problems.append(f"motion {m.motion!r} unknown — expected one of {MOTIONS} or null")
    if m.pan is not None:
        # PanSpec is the HARD backstop; here it is the soft gate's oracle — the same
        # LayoutSpec/hero.resolve pattern used twice above. One constructor for
        # validation and for the shell's real build, so the two cannot drift apart.
        try:
            PanSpec.from_dict(m.pan)
        except ValueError as e:
            problems.append(str(e))
        if m.composition in ("lead", "break"):
            problems.append(
                f"composition {m.composition!r} cannot be combined with a pan: 'lead' and "
                "'break' are SUBJECT-RELATIVE framing rules, and a pan positions the crop "
                "by its own law without consulting any subject. Set composition to 'center' "
                "(read as 'no framing rule'), or drop the pan")
        if m.hero is not None:
            problems.append(
                "a hero pin cannot be combined with a pan: the pin says 'follow this "
                f"person' and the pan says 'follow nobody'. Drop `hero` ({m.hero!r}) to "
                "keep the pan, or drop `pan` to track the hero")
    if m.model not in MODELS:
        problems.append(f"model {m.model!r} unknown — expected one of {MODELS}")
    try:
        Delivery.from_spec(m.delivery)
    except (ValueError, TypeError) as e:
        problems.append(f"delivery {m.delivery!r} invalid — {e}")
    return problems
