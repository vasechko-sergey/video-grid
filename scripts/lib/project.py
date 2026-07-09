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

    def __post_init__(self) -> None:
        if self.purpose not in PURPOSE_CANVAS:
            raise ValueError(f"ProjectConfig.purpose {self.purpose!r} not in {sorted(PURPOSE_CANVAS)}")
        if not (isinstance(self.canvas, (tuple, list)) and len(self.canvas) == 2
                and all(isinstance(v, (int, float)) and v > 0 for v in self.canvas)):
            raise ValueError(f"ProjectConfig.canvas must be [w, h] positive, got {self.canvas!r}")
        self.canvas = tuple(self.canvas)
        if self.delivery is None:
            self.delivery = "native"
        try:
            Delivery.from_spec(self.delivery)
        except (ValueError, TypeError) as e:
            raise ValueError(f"ProjectConfig.delivery {self.delivery!r} invalid — {e}") from e

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConfig":
        # pass raw values through; __post_init__ produces clean ValueError-with-remedy
        # for missing/None/garbage (never a bare KeyError/TypeError)
        return cls(purpose=d.get("purpose"), canvas=d.get("canvas"),
                   delivery=d.get("delivery"), notes=d.get("notes") or "")

    def to_dict(self) -> dict:
        return {"purpose": self.purpose, "canvas": list(self.canvas),
                "delivery": self.delivery, "notes": self.notes}

    @classmethod
    def from_json(cls, path: str | Path) -> "ProjectConfig":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run project-init to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def resolve_project(purpose: str, quality: str = "native",
                    canvas: tuple[int, int] | None = None, delivery: str | None = None,
                    notes: str = "") -> ProjectConfig:
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


def resolve_manifest(episode_dict: dict, config: ProjectConfig) -> dict:
    """Fill canvas/delivery from the project when the episode omits them (missing
    OR explicit JSON null → inherit, matching the manifest's null-is-absent rule);
    an explicit episode value wins (override). Returns a NEW dict; never mutates."""
    out = dict(episode_dict)
    if out.get("canvas") is None:
        out["canvas"] = list(config.canvas)
    if out.get("delivery") is None:
        out["delivery"] = config.delivery
    return out
