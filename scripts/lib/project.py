"""Project config: purpose→aspect, quality→delivery, learned once at project
start (design 2026-07-09). Determinism here; the interactive asking lives in
SKILLS/project-init/SKILL.md. Episode manifests inherit canvas/delivery from the
project unless they override."""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.models import Delivery

PURPOSE_CANVAS = {
    "reel": (9, 16), "shorts": (9, 16), "tiktok": (9, 16),
    "youtube": (16, 9), "landscape": (16, 9),
    "square": (1, 1), "feed": (1, 1),
    "cinema": (21, 9), "wide": (21, 9),
    "custom": None,                       # explicit canvas required
}
QUALITY_DELIVERY = {
    "native": "native",                   # DEFAULT — crop's own pixels, no scale, no loss
    "social": "short_edge:1080",          # deliberate downscale for social / small file
    "4k": "long_edge:2160",               # normalize/upscale to 4K delivery
}


@dataclass
class ProjectConfig:
    purpose: str
    canvas: tuple
    delivery: str
    notes: str = ""

    def __post_init__(self):
        if self.purpose not in PURPOSE_CANVAS:
            raise ValueError(f"ProjectConfig.purpose {self.purpose!r} not in {sorted(PURPOSE_CANVAS)}")
        if not (isinstance(self.canvas, (tuple, list)) and len(self.canvas) == 2
                and all(isinstance(v, (int, float)) and v > 0 for v in self.canvas)):
            raise ValueError(f"ProjectConfig.canvas must be [w, h] positive, got {self.canvas!r}")
        self.canvas = tuple(self.canvas)
        try:
            Delivery.from_spec(self.delivery)
        except (ValueError, TypeError) as e:
            raise ValueError(f"ProjectConfig.delivery {self.delivery!r} invalid — {e}") from e

    @classmethod
    def from_dict(cls, d):
        return cls(purpose=d["purpose"], canvas=tuple(d["canvas"]),
                   delivery=d["delivery"], notes=d.get("notes") or "")

    def to_dict(self):
        return {"purpose": self.purpose, "canvas": list(self.canvas),
                "delivery": self.delivery, "notes": self.notes}

    @classmethod
    def from_json(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def write(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def resolve_project(purpose, quality="native", canvas=None, delivery=None, notes=""):
    """Deterministic purpose+quality → ProjectConfig. `custom` purpose requires an
    explicit `canvas=(w, h)`; an explicit `delivery` overrides the quality map.
    Raises ValueError-with-remedy on unknown purpose/quality or a missing custom canvas."""
    if purpose not in PURPOSE_CANVAS:
        raise ValueError(f"purpose {purpose!r} unknown — one of {sorted(PURPOSE_CANVAS)}")
    if purpose == "custom":
        if canvas is None:
            raise ValueError("purpose 'custom' needs an explicit canvas=(w, h)")
        cv = tuple(canvas)
    else:
        cv = PURPOSE_CANVAS[purpose]
    if delivery is not None:
        dv = delivery
    elif quality in QUALITY_DELIVERY:
        dv = QUALITY_DELIVERY[quality]
    else:
        raise ValueError(f"quality {quality!r} unknown — one of {sorted(QUALITY_DELIVERY)} "
                         "or pass an explicit delivery=")
    return ProjectConfig(purpose=purpose, canvas=cv, delivery=dv, notes=notes)
