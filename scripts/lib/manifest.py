"""Episode manifest + machine-checkable validation (§5.10, §4.1).

The manifest is the process-episode subagent's entire brief (§14.4: full task
inline, self-contained). validate() is the deterministic half of "ask before
starting if ambiguous" — missing/contradictory/unsupported fields are caught
here, before any YOLO/ffmpeg runs, so the orchestrator returns needs_input
instead of guessing.
"""
from dataclasses import dataclass

from scripts.lib.models import COMPOSITIONS, GRIDS, MODELS, MOTIONS, Delivery

REQUIRED = ("segment", "out_path", "composition", "grid", "canvas", "target_dur")
OPTIONAL = ("layout", "motion", "hero", "color_means", "stabilize", "model", "delivery")
LAYOUTS_SUPPORTED = ("fill",)          # fit-blur/insert/split/pan → layouts plan
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
    hero: object = None
    color_means: tuple = DEFAULT_COLOR
    stabilize: bool = False
    model: str = DEFAULT_MODEL
    delivery: str = "native"

    @classmethod
    def from_dict(cls, d):
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
        return cls(
            segment=d["segment"], out_path=d["out_path"],
            composition=d["composition"], grid=d["grid"],
            canvas=tuple(d["canvas"]), target_dur=float(d["target_dur"]),
            layout=layout if layout is not None else "fill", motion=d.get("motion"),
            hero=hero,
            color_means=tuple(cm) if cm is not None else DEFAULT_COLOR,
            stabilize=bool(d.get("stabilize", False)),
            model=model if model is not None else DEFAULT_MODEL,
            delivery=delivery if delivery is not None else "native",
        )


def validate(m):
    """Return a list of human-readable problem strings (empty = ok)."""
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
        problems.append(f"layout {m.layout!r} not supported in the orchestrator slice — "
                        "fill only; fit-blur/insert/split/pan land in the reframe-extensions plan")
    if m.stabilize:
        problems.append("stabilize=true not supported yet — vidstab lands in the "
                        "reframe-extensions plan (and needs a vidstab-enabled ffmpeg, "
                        "see setup.sh --with-vidstab)")
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
    if m.model not in MODELS:
        problems.append(f"model {m.model!r} unknown — expected one of {MODELS}")
    try:
        Delivery.from_spec(m.delivery)
    except (ValueError, TypeError) as e:
        problems.append(f"delivery {m.delivery!r} invalid — {e}")
    return problems
