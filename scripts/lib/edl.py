"""EDL contract + the EDL→manifest bridge (design docs/specs/2026-07-11-extract-spine-design.md).

The typed source of truth for the front half's edit decision list. Follows the
hard config-spec pattern — validate-and-raise in `__post_init__`, JSON round-trip —
like `models.py`'s `TrackSpec`/`MusicSpec`. (Distinct from `manifest.py`'s soft
`Manifest` gate, whose `validate()` returns problem strings and never raises.)
The human-facing EDL.md render + interactive authoring are SP3;
this module is what the mechanical extract spine reads. Imports the shared
vocab from models + manifest, the resolve/config helpers from project, and the
cast registry from footage — none of models/manifest/project/footage import
edl, so no cycle.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.footage import Cast
from scripts.lib.manifest import DEFAULT_COLOR, LAYOUTS_SUPPORTED, Manifest, validate
from scripts.lib.models import COMPOSITIONS, GRIDS, MOTIONS
from scripts.lib.project import ProjectConfig, resolve_manifest


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
    background_color: str = "black"
    border_px: int = 0
    border_color: str = "white"
    motion: str | None = None
    pan: dict | None = None   # {"from": f, "to": f} — a GENERATED crop path (design
                              # 2026-07-19). NOT validated here: like `hero` and the
                              # layout params, its one home is the manifest gate
                              # reached via preflight, which uses PanSpec as its oracle.
    hero: tuple | str | int | None = None   # seed bbox / rule / track id / cast name (§5.10);
                                            # NOT validated here — see the class docstring: the
                                            # manifest gate reached via preflight is its one home
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
                             "split lands in its own plan, and a pan is not a layout — "
                             "set the `pan` field instead")
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

    def to_dict(self) -> dict:
        def _j(v: object) -> object:
            return list(v) if isinstance(v, tuple) else v
        return {"source": self.source, "start": self.start, "dur": self.dur,
                "shot_type": self.shot_type, "composition": self.composition, "grid": self.grid,
                "layout": self.layout, "crop_aspect": _j(self.crop_aspect), "crop_scale": self.crop_scale,
                "rect": _j(self.rect), "background": self.background,
                "background_color": self.background_color, "border_px": self.border_px,
                "border_color": self.border_color, "motion": self.motion, "pan": self.pan,
                "hero": _j(self.hero),
                "color_means": list(self.color_means), "processing_notes": self.processing_notes,
                "beat_slot": self.beat_slot}


@dataclass
class EDL:
    """The ordered edit decision list + reel-level knobs. target_dur=None → the
    reel total is the sum of window durations (the length gate then passes by
    construction; a user-set target that disagrees is a real pacing signal)."""
    episodes: tuple[EDLEpisode, ...]
    music: str | None = None       # MUSIC.json path; None → a silent reel (Phase A.5 path)
    cast: str | None = None        # cast.json path; needed only when an episode pins a cast name
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
        if self.cast is not None and not (isinstance(self.cast, str) and self.cast):
            raise ValueError("EDL.cast must be a cast.json path or null, got an empty/non-str value")
        if self.target_dur is not None and (isinstance(self.target_dur, bool)
                or not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0):
            raise ValueError(f"EDL.target_dur must be a positive number or null, got {self.target_dur!r}")

    @classmethod
    def from_dict(cls, d: dict) -> "EDL":
        # The top level is checked FIRST, before d.get: this boundary reads user-supplied JSON,
        # so it owes its callers ONE documented exception type (ValueError-with-remedy, per
        # coding-standards). Without this, a valid-JSON-but-wrong-shape top level (a bare
        # array/string/number/bool/null) reached d.get and raised a bare AttributeError, which
        # neither reader (edl_to_reel.py, draft.py) catches — they call from_json bare.
        if not isinstance(d, dict):
            raise ValueError(f"EDL.from_dict: expected an EDL.json object with an 'episodes' list, "
                             f"got {type(d).__name__} — re-run edit-plan to regenerate EDL.json")
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
        return cls(episodes=tuple(eps), music=d.get("music"), cast=d.get("cast"),
                   cap=cap if cap is not None else 3, target_dur=d.get("target_dur"))

    @classmethod
    def from_json(cls, path: str | Path) -> "EDL":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the EDL syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"episodes": [e.to_dict() for e in self.episodes],
                "music": self.music, "cast": self.cast, "cap": self.cap, "target_dur": self.target_dur}

    def to_markdown(self) -> str:
        total = sum(e.dur for e in self.episodes)
        head = f"# Edit plan — {len(self.episodes)} episodes, {total:.1f}s"
        if self.target_dur is not None:
            head += f" · target {self.target_dur:.1f}s"
        lines = [head, "",
                 "| # | source | window | shot | layout | comp | grid | motion | beat | notes |",
                 "|---|--------|--------|------|--------|------|------|--------|:----:|-------|"]
        for i, e in enumerate(self.episodes):
            motion = e.motion if e.motion is not None else "–"
            if e.pan is not None:
                # the camera move rides the same column as the subject's motion —
                # they describe different things and can both be present
                pan = f"pan {e.pan.get('from')}→{e.pan.get('to')}"
                motion = pan if motion == "–" else f"{motion} · {pan}"
            beat = str(e.beat_slot) if e.beat_slot is not None else "–"
            window = f"{e.start:.2f}–{e.start + e.dur:.2f} ({e.dur:.2f}s)"
            lines.append(f"| {i} | {e.source} | {window} | {e.shot_type} | {e.layout} | "
                         f"{e.composition} | {e.grid} | {motion} | {beat} | {e.processing_notes} |")
        return "\n".join(lines)


def to_manifest_dict(ep: EDLEpisode, segment: str, out_path: str,
                     cast: str | None = None) -> dict:
    """Map an EDL row + its extracted segment + output path onto a Manifest-shaped
    dict (the process_episode brief). A deliberate field MAP, not a dump — the
    manifest gate rejects unknown keys. Omits canvas/delivery (the driver fills
    them from the project via resolve_manifest) and model/stabilize (manifest
    defaults). `pan` crosses the boundary the same way `motion`/`hero` do below:
    copied through only when the episode sets one, so an absent pan leaves the
    key out of the dict rather than carrying an explicit null — Manifest.from_dict
    then falls to its own None default. EDL-only fields (source/start/dur/
    shot_type/processing_notes/beat_slot) do NOT cross — this map is the
    documented EDL↔manifest boundary.
    `cast` is EDL.cast, the reel-level registry path — forwarded so a cast-name
    hero resolves per episode while the manifest itself stays a self-contained
    brief (§14.4); omitted when None so Manifest.from_dict falls to its own ""
    default rather than the dict carrying an explicit null."""
    md: dict = {
        "segment": segment, "out_path": out_path, "target_dur": ep.dur,
        "composition": ep.composition, "grid": ep.grid, "layout": ep.layout,
        "crop_scale": ep.crop_scale, "background": ep.background,
        "background_color": ep.background_color,
        "border_px": ep.border_px, "border_color": ep.border_color,
        "color_means": list(ep.color_means),
    }
    if ep.crop_aspect is not None:      # None → let Manifest pick canvas/source by layout
        md["crop_aspect"] = list(ep.crop_aspect) if isinstance(ep.crop_aspect, tuple) else ep.crop_aspect
    if ep.rect is not None:
        md["rect"] = list(ep.rect)
    if ep.motion is not None:
        md["motion"] = ep.motion
    if ep.pan is not None:
        md["pan"] = ep.pan
    if ep.hero is not None:
        md["hero"] = list(ep.hero) if isinstance(ep.hero, tuple) else ep.hero
    if cast is not None:
        md["cast"] = cast
    return md


def preflight(edl: EDL, cfg: ProjectConfig, seg_dir: str,
              out_dir: str) -> tuple[list[dict], dict | None]:
    """Resolve + gate every EDL episode against the project BEFORE any ffmpeg.
    For each episode: bridge to a manifest dict, inherit canvas/delivery from the
    project, then Manifest.from_dict + validate. Returns (resolved manifest dicts,
    None) when all pass, or (dicts-so-far, stop) where stop is a machine-readable
    stop_and_report naming the first invalid episode. validate() itself never
    touches the filesystem (it checks layout params/dims and resolves the hero pin
    against an already-loaded registry, not file existence — this is what lets it
    fail in ms). The one exception is EDL.cast: preflight reads it once, here,
    before the loop — never per-episode, so a 12-episode EDL does not read the
    registry 12 times — and hands the loaded Cast to every validate() call below.
    seg_dir/out_dir may still be placeholder paths."""
    mds: list[dict] = []
    cast = None
    if edl.cast is not None:
        try:
            cast = Cast.from_json(edl.cast)
        except (OSError, ValueError) as e:
            # Cast.from_json's whole failure surface: OSError (missing/unreadable file) or
            # ValueError (bad syntax, bad top-level shape, bad members) — it guards its own
            # top level, so a malformed registry arrives here as one documented type rather
            # than an exception zoo. Deliberately NOT widened past those two: a clause that
            # cannot fire reads as protection while protecting nothing.
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": None,
                                     "problems": [f"EDL.cast {edl.cast!r} is unreadable — {e}"]}}
    for i, ep in enumerate(edl.episodes):
        seg = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        md = resolve_manifest(to_manifest_dict(ep, seg, str(Path(out_dir) / f"ep{i}.mp4"),
                                               cast=edl.cast), cfg)
        try:
            m = Manifest.from_dict(md)
        except (KeyError, TypeError, ValueError) as e:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": i, "problems": [str(e)]}}
        problems = validate(m, cast=cast)
        if problems:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": i, "problems": problems}}
        mds.append(md)
    return mds, None
