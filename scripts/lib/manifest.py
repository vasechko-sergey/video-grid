"""Episode manifest + machine-checkable validation (§5.10, §4.1).

The manifest is the process-episode subagent's entire brief (§14.4: full task
inline, self-contained). validate() is the deterministic half of "ask before
starting if ambiguous" — missing/contradictory/unsupported fields are caught
here, before any YOLO/ffmpeg runs, so the orchestrator returns needs_input
instead of guessing.
"""
import dataclasses
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
from scripts.lib.models import (COMPOSITIONS, GRIDS, MODELS, MOTIONS, Delivery, LayoutSpec,
                                PanSpec, ZoomSpec)

REQUIRED = ("segment", "out_path", "composition", "grid", "canvas", "target_dur")
OPTIONAL = ("layout", "motion", "pan", "zoom", "hero", "cast", "color_means", "white_balance",
            "black_point", "highlight", "highlight_red", "tone_src", "tone_dst", "saturation",
            "shadow_red", "mid_blue", "dip", "smooth_window_s",
            "stabilize", "still", "freeze", "model",
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
    zoom: dict | None = None         # {"from": f, "to": f} — a SUBJECT-ANCHORED push-in
                                     # (design 2026-08-08). Raw wire dict here, built into a
                                     # ZoomSpec by process_episode, exactly as `pan` is.
    hero: tuple | str | int | None = None
    cast: str = ""                       # cast.json path — a cast-name hero needs the registry,
                                         # and the manifest is a self-contained brief (§14.4)
    color_means: tuple = DEFAULT_COLOR
    white_balance: float = 0.0
    black_point: float = 0.0
    highlight: float = 1.0
    highlight_red: float = 0.0
    saturation: float = 1.0
    shadow_red: float = 0.0
    mid_blue: float = 1.0
    dip: float = 0.0
    smooth_window_s: float | None = None   # savgol span in seconds over the tracked path —
                                           # the retry ladder's starting value and its
                                           # lag-branch floor; None = ReframeSpec's own
                                           # 0.25 default. See orchestration.adjust_reframe_params.
    tone_src: tuple[float, float, float] | None = None
    tone_dst: tuple[float, float, float] | None = None
    stabilize: bool = False
    still: bool = False              # the segment is a rendered PHOTO (design 2026-10-20 §5):
                                     # its move is already in the pixels, so nobody tracks it
                                     # and reframe crops the whole segment. Set by
                                     # edl.to_manifest_dict from the source's extension.
    freeze: bool = False             # the segment is ONE frame of the previous episode, held
                                     # (design 2026-10-21 §3), over a held route edl_to_reel
                                     # built. Video in every other respect; set by
                                     # edl.to_manifest_dict from EDLEpisode.freeze, because
                                     # below the EDL nothing else can tell a held frame from a
                                     # played window, and the conductor, check_episode and the
                                     # QC judge each treat it differently (final review I1–I3).
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
            pan=d.get("pan"), zoom=d.get("zoom"),
            hero=hero, cast=d.get("cast") or "",
            color_means=tuple(cm) if cm is not None else DEFAULT_COLOR,
            white_balance=float(d.get("white_balance") or 0.0),
            black_point=float(d.get("black_point") or 0.0),
            highlight=float(d["highlight"]) if d.get("highlight") is not None else 1.0,
            highlight_red=float(d["highlight_red"]) if d.get("highlight_red") is not None else 0.0,
            saturation=float(d["saturation"]) if d.get("saturation") is not None else 1.0,
            shadow_red=float(d["shadow_red"]) if d.get("shadow_red") is not None else 0.0,
            mid_blue=float(d["mid_blue"]) if d.get("mid_blue") is not None else 1.0,
            dip=float(d["dip"]) if d.get("dip") is not None else 0.0,
            # raw passthrough, NOT float(...) — validate() is the oracle that checks the
            # type (isinstance-bool-first) and the band; a coercing from_dict would turn
            # a JSON `true` into 1.0 and a stray "0.5" into 0.5, both silently IN band,
            # defeating that check before it ever runs (mirrors `hero`'s raw passthrough).
            smooth_window_s=d.get("smooth_window_s"),
            tone_src=tuple(d["tone_src"]) if d.get("tone_src") is not None else None,
            tone_dst=tuple(d["tone_dst"]) if d.get("tone_dst") is not None else None,
            stabilize=bool(d.get("stabilize", False)),
            # raw, like smooth_window_s: validate() checks the type, and bool() would read
            # the string "false" as True
            still=d.get("still", False) if d.get("still") is not None else False,
            freeze=d.get("freeze", False) if d.get("freeze") is not None else False,
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
    # ReframeSpec is the HARD backstop (scripts/lib/models.py); here it is the soft gate's
    # oracle, same band and message shape, so a value this gate accepts can never be one
    # ReframeSpec later rejects deep in the retry loop.
    if m.smooth_window_s is not None and (
            isinstance(m.smooth_window_s, bool)
            or not isinstance(m.smooth_window_s, (int, float))
            or not 0 < m.smooth_window_s <= 2.0):
        problems.append(
            f"smooth_window_s must be a span in seconds in (0, 2.0] or null, got "
            f"{m.smooth_window_s!r} — it is a filter cutoff, and a window longer than "
            "a couple of seconds stops following the subject")
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
            # This alone is design §2.2's "pan with a hero pin OR CAST NAME" refusal:
            # `hero` carries every pin flavour (bbox, track id, cast-name string), so
            # "cast name" is already `m.hero is not None`, whatever it holds. A prior
            # version of this gate ALSO fired on bare `m.cast` — the reel-level
            # cast.json PATH that edl.to_manifest_dict (edl.py) stamps onto every
            # episode once an EDL declares a registry, present whether or not THIS
            # episode names a hero — which refused every scenery pan in such an EDL
            # with a message naming a pin that did not exist. Found in the final
            # whole-branch review; removed rather than widened, since this arm was
            # always sufficient and the other one was never correct.
            problems.append(
                "a hero pin cannot be combined with a pan: the pin says 'follow this "
                f"person' and the pan says 'follow nobody'. Drop `hero` ({m.hero!r}) to "
                "keep the pan, or drop `pan` to track the hero")
    if m.zoom is not None:
        if m.pan is not None:
            problems.append(
                "zoom and pan on one episode: a zoom anchors the rect to a tracked subject "
                "and a pan declares there is none. Keep one")
        # ZoomSpec is the HARD backstop; here it is the soft gate's oracle — the same
        # PanSpec/LayoutSpec pattern used above. One constructor for validation and for
        # the shell's real build, so the two cannot drift apart.
        try:
            ZoomSpec.from_dict(m.zoom)
        except ValueError as e:
            problems.append(str(e))
    if not isinstance(m.still, bool):
        problems.append(f"still must be true or false, got {m.still!r}")
    elif m.still:
        # The same refusals EDLEpisode makes for a photo source, again here because a
        # hand-written manifest reaches process_episode without an EDL (design §5).
        carried = [k for k, v in (("pan", m.pan), ("zoom", m.zoom), ("hero", m.hero),
                                  ("motion", m.motion),
                                  ("smooth_window_s", m.smooth_window_s),
                                  ("stabilize", m.stabilize or None)) if v is not None]
        if carried:
            problems.append(
                f"a still episode cannot carry {', '.join(carried)}: its move is rendered "
                f"into the segment and nothing is tracked on it — drop them, or drop "
                f"`still` if the segment is video")
    if not isinstance(m.freeze, bool):
        problems.append(f"freeze must be true or false, got {m.freeze!r}")
    elif m.freeze:
        # The EDL's own refusals (EDLEpisode._refuse_what_a_freeze_cannot_carry), again here
        # for the still's reason: a hand-written manifest reaches process_episode without an
        # EDL. The hero stays — the held route follows whom the previous episode followed.
        carried = [k for k, v in (("pan", m.pan), ("zoom", m.zoom), ("motion", m.motion),
                                  ("smooth_window_s", m.smooth_window_s),
                                  ("stabilize", m.stabilize or None),
                                  ("still", m.still if m.still is True else None))
                   if v is not None]
        if carried:
            problems.append(
                f"a freeze episode cannot carry {', '.join(carried)}: it holds one frame of "
                f"the previous episode, so there is no time to move, smooth or stabilize, "
                f"and it is video, not a photo — drop them, or drop `freeze`")
    if m.model not in MODELS:
        problems.append(f"model {m.model!r} unknown — expected one of {MODELS}")
    try:
        Delivery.from_spec(m.delivery)
    except (ValueError, TypeError) as e:
        problems.append(f"delivery {m.delivery!r} invalid — {e}")
    return problems


# The colour block, as it crosses edl.to_manifest_dict. A CLOSED set, because a
# caller that re-applies a fresh block must DROP these first: to_manifest_dict
# omits highlight_red, tone_src and tone_dst at their identity, so a plain merge
# would keep a value the author has just deleted from the EDL.
COLOUR_KEYS = ("color_means", "white_balance", "black_point", "highlight",
               "highlight_red", "saturation", "shadow_red", "mid_blue", "dip",
               "tone_src", "tone_dst")

# The value Manifest.from_dict falls back to for each of COLOUR_KEYS when the JSON
# key is absent or explicitly null. DERIVED from Manifest's dataclass fields rather
# than hand-copied, so this cannot drift the day someone edits a default above.
# Safe only because every Manifest field uses a plain `= value` default, never
# `field(default_factory=...)` — a default_factory field's own .default is
# dataclasses.MISSING and would poison this map silently. Re-check that invariant
# before ever widening COLOUR_KEYS.
COLOUR_IDENTITY = {f.name: f.default for f in dataclasses.fields(Manifest)
                   if f.name in COLOUR_KEYS}


def strip_colour(md: dict) -> dict:
    """`md` with every colour field at its identity value — the same episode,
    ungraded. The measuring path plans a render from this so the reading is of the
    footage, not of a grade already applied; the geometry path stores it so a
    changed CUT can be told from a changed GRADE (design 2026-08-30 §2.2)."""
    out = {k: v for k, v in md.items() if k not in COLOUR_KEYS}
    out.update(COLOUR_IDENTITY)
    return out
