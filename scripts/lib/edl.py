"""EDL contract + the EDL→manifest bridge (design docs/specs/2026-07-11-extract-spine-design.md).

The typed source of truth for the front half's edit decision list. Follows the
hard config-spec pattern — validate-and-raise in `__post_init__`, JSON round-trip —
like `models.py`'s `TrackSpec`/`MusicSpec`. (Distinct from `manifest.py`'s soft
`Manifest` gate, whose `validate()` returns problem strings and never raises.)
The human-facing EDL.md render + interactive authoring are SP3;
this module is what the mechanical extract spine reads. Imports the shared
vocab from models + manifest — manifest never imports edl, so no cycle.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.manifest import DEFAULT_COLOR, LAYOUTS_SUPPORTED
from scripts.lib.models import COMPOSITIONS, GRIDS, MOTIONS


@dataclass
class EDLEpisode:
    """One ordered edit-decision row: a source window + its picture intent.
    Layout-parameter cross-validation (crop_scale range, rect bounds, fill-vs-
    border) is NOT duplicated here — it has one home, LayoutSpec, reached via the
    manifest gate in the driver's preflight. This validates only what the manifest
    gate cannot see cheaply (source/window/shot_type) plus flat membership."""
    source: str
    start: float
    dur: float
    shot_type: str
    composition: str
    grid: str
    layout: str = "fill"
    crop_aspect: str | tuple[int, int] | None = None   # None → manifest picks canvas/source by layout
    crop_scale: float = 1.0
    rect: tuple[float, float, float] | None = None
    background: str = "blur"
    border_px: int = 0
    border_color: str = "white"
    motion: str | None = None
    hero: tuple | str | None = None
    color_means: tuple = DEFAULT_COLOR
    processing_notes: str = ""       # authoring metadata → SP1b draft labels; not acted on here
    beat_slot: int | None = None     # authoring metadata → B4 pacing; not acted on here

    def __post_init__(self) -> None:
        if not (isinstance(self.source, str) and self.source):
            raise ValueError("EDLEpisode.source must be a non-empty clip path")
        if isinstance(self.start, bool) or not isinstance(self.start, (int, float)) or self.start < 0:
            raise ValueError(f"EDLEpisode.start must be a number >= 0 (seconds), got {self.start!r}")
        if isinstance(self.dur, bool) or not isinstance(self.dur, (int, float)) or self.dur <= 0:
            raise ValueError(f"EDLEpisode.dur must be a positive number (seconds), got {self.dur!r}")
        if not (isinstance(self.shot_type, str) and self.shot_type):
            raise ValueError("EDLEpisode.shot_type must be a non-empty tag (e.g. 'wide', 'close')")
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"EDLEpisode.composition {self.composition!r} unknown — expected {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"EDLEpisode.grid {self.grid!r} unknown — expected {GRIDS} "
                             "(golden-canon is a static editorial layer, not a tracking grid)")
        if self.layout not in LAYOUTS_SUPPORTED:
            raise ValueError(f"EDLEpisode.layout {self.layout!r} not supported — {LAYOUTS_SUPPORTED} only; "
                             "split and pan land in their own plans")
        if self.motion is not None and self.motion not in MOTIONS:
            raise ValueError(f"EDLEpisode.motion {self.motion!r} unknown — expected one of {MOTIONS} or null")
        if self.beat_slot is not None and (isinstance(self.beat_slot, bool) or not isinstance(self.beat_slot, int)):
            raise ValueError(f"EDLEpisode.beat_slot must be an int index or null, got {self.beat_slot!r}")
        if not (isinstance(self.color_means, (tuple, list)) and len(self.color_means) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
                        for v in self.color_means)):
            raise ValueError(f"EDLEpisode.color_means must be 3 positive channel means [R, G, B]; "
                             f"got {self.color_means!r}")
        self.color_means = tuple(self.color_means)
        if isinstance(self.hero, list):
            self.hero = tuple(self.hero)
        if isinstance(self.crop_aspect, list):
            self.crop_aspect = tuple(self.crop_aspect)
        if isinstance(self.rect, list):
            self.rect = tuple(self.rect)
