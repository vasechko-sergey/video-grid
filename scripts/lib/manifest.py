"""Episode manifest + machine-checkable validation (§5.10, §4.1).

The manifest is the process-episode subagent's entire brief (§14.4: full task
inline, self-contained). validate() is the deterministic half of "ask before
starting if ambiguous" — missing/contradictory/unsupported fields are caught
here, before any YOLO/ffmpeg runs, so the orchestrator returns needs_input
instead of guessing.
"""
from dataclasses import dataclass

REQUIRED = ("segment", "out_path", "composition", "grid", "canvas", "target_dur")
COMPOSITIONS = ("lead", "center", "break")
GRIDS = ("thirds", "phi")
LAYOUTS_SUPPORTED = ("fill",)          # fit-blur/insert/split/pan → layouts plan
MOTIONS = ("lateral:right", "lateral:left", "head-on", "static")
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

    @classmethod
    def from_dict(cls, d):
        for k in REQUIRED:
            if k not in d:
                raise KeyError(f"manifest missing required field: {k}")
        return cls(
            segment=d["segment"], out_path=d["out_path"],
            composition=d["composition"], grid=d["grid"],
            canvas=tuple(d["canvas"]), target_dur=float(d["target_dur"]),
            layout=d.get("layout", "fill"), motion=d.get("motion"),
            hero=d.get("hero"),
            color_means=tuple(d.get("color_means", DEFAULT_COLOR)),
            stabilize=bool(d.get("stabilize", False)),
            model=d.get("model", DEFAULT_MODEL),
        )


def validate(m):
    """Return a list of human-readable problem strings (empty = ok)."""
    problems = []
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
    if not (isinstance(m.canvas, tuple) and len(m.canvas) == 2):
        problems.append(f"canvas must be [w, h]; got {m.canvas!r}")
    if m.target_dur <= 0:
        problems.append(f"target_dur must be positive; got {m.target_dur}")
    if m.motion is not None and m.motion not in MOTIONS:
        problems.append(f"motion {m.motion!r} unknown — expected one of {MOTIONS} or null")
    return problems
