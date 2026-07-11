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


@dataclass
class EDL:
    """The ordered edit decision list + reel-level knobs. target_dur=None → the
    reel total is the sum of window durations (the length gate then passes by
    construction; a user-set target that disagrees is a real pacing signal)."""
    episodes: tuple[EDLEpisode, ...]
    music: str | None = None       # MUSIC.json path; None → a silent reel (Phase A.5 path)
    cap: int = 3                   # build_reel reprocess cap
    target_dur: float | None = None

    def __post_init__(self) -> None:
        eps = tuple(self.episodes)
        if not eps:
            raise ValueError("EDL.episodes is empty — an EDL needs at least one episode")
        for k, e in enumerate(eps):
            if not isinstance(e, EDLEpisode):
                raise ValueError(f"EDL.episodes[{k}] must be an EDLEpisode")
        self.episodes = eps
        if isinstance(self.cap, bool) or not isinstance(self.cap, int) or self.cap < 1:
            raise ValueError(f"EDL.cap must be an int >= 1, got {self.cap!r}")
        if self.music is not None and not (isinstance(self.music, str) and self.music):
            raise ValueError("EDL.music must be a MUSIC.json path or null, got an empty/non-str value")
        if self.target_dur is not None and (isinstance(self.target_dur, bool)
                or not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0):
            raise ValueError(f"EDL.target_dur must be a positive number or null, got {self.target_dur!r}")

    @classmethod
    def from_dict(cls, d: dict) -> "EDL":
        eps_in = d.get("episodes")
        if not isinstance(eps_in, list):
            raise ValueError("EDL.from_dict: 'episodes' must be a list of episode objects")
        eps = []
        for k, e in enumerate(eps_in):
            if not isinstance(e, dict):
                raise ValueError(f"EDL.from_dict: episodes[{k}] must be an object, got {type(e).__name__}")
            try:
                eps.append(EDLEpisode(**e))       # missing-required / unknown key → TypeError → remedy below
            except TypeError as ex:
                raise ValueError(f"EDL.from_dict: episodes[{k}] has a missing or unknown field — {ex}") from ex
        cap = d.get("cap")
        return cls(episodes=tuple(eps), music=d.get("music"),
                   cap=cap if cap is not None else 3, target_dur=d.get("target_dur"))

    @classmethod
    def from_json(cls, path: str | Path) -> "EDL":
        return cls.from_dict(json.loads(Path(path).read_text()))


def to_manifest_dict(ep: EDLEpisode, segment: str, out_path: str) -> dict:
    """Map an EDL row + its extracted segment + output path onto a Manifest-shaped
    dict (the process_episode brief). A deliberate field MAP, not a dump — the
    manifest gate rejects unknown keys. Omits canvas/delivery (the driver fills
    them from the project via resolve_manifest) and model/stabilize (manifest
    defaults). EDL-only fields (source/start/dur/shot_type/processing_notes/
    beat_slot) do NOT cross — this map is the documented EDL↔manifest boundary."""
    md: dict = {
        "segment": segment, "out_path": out_path, "target_dur": ep.dur,
        "composition": ep.composition, "grid": ep.grid, "layout": ep.layout,
        "crop_scale": ep.crop_scale, "background": ep.background,
        "border_px": ep.border_px, "border_color": ep.border_color,
        "color_means": list(ep.color_means),
    }
    if ep.crop_aspect is not None:      # None → let Manifest pick canvas/source by layout
        md["crop_aspect"] = list(ep.crop_aspect) if isinstance(ep.crop_aspect, tuple) else ep.crop_aspect
    if ep.rect is not None:
        md["rect"] = list(ep.rect)
    if ep.motion is not None:
        md["motion"] = ep.motion
    if ep.hero is not None:
        md["hero"] = list(ep.hero) if isinstance(ep.hero, tuple) else ep.hero
    return md
