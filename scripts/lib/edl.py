"""EDL contract + the EDL→manifest bridge (design docs/specs/2026-07-11-extract-spine-design.md).

The typed source of truth for the front half's edit decision list. Follows the
hard config-spec pattern — validate-and-raise in `__post_init__`, JSON round-trip —
like `models.py`'s `TrackSpec`/`MusicSpec`. (Distinct from `manifest.py`'s soft
`Manifest` gate, whose `validate()` returns problem strings and never raises.)
The human-facing EDL.md render + interactive authoring are SP3;
this module is what the mechanical extract spine reads. Imports the shared
vocab from models + manifest, the resolve/config helpers from project, the
cast registry from footage, and the two report types it carries —
VarietyReport from moodpreset, ConstraintReport from constraints — none of
models/manifest/project/footage/moodpreset/constraints import edl, so no cycle.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import provenance
from scripts.lib import ramp as ramp_mod
from scripts.lib.constraints import ConstraintReport
from scripts.lib.footage import Cast
from scripts.lib.manifest import DEFAULT_COLOR, LAYOUTS_SUPPORTED, Manifest, validate
from scripts.lib.models import COMPOSITIONS, GRIDS, MOTIONS, RampSpec
from scripts.lib.moodpreset import VarietyReport
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
    zoom: dict | None = None  # {"from": f, "to": f} — a SUBJECT-ANCHORED push-in/pull-out
                              # (design 2026-08-08). NOT validated here: like `pan`, its one
                              # home is the manifest gate reached via preflight, which uses
                              # ZoomSpec as its oracle.
    ramp: dict | None = None  # {"at": s, "factor": f, "ease": s, "hold": s} — a speed
                              # ramp eased around one moment (design 2026-08-09).
                              # UNLIKE `pan`/`zoom`/`hero` this IS validated here, and
                              # deliberately: those three are validated once at the
                              # manifest gate reached via preflight, but the region-
                              # fits-the-window rule needs `dur`, which only this class
                              # has, and play_dur() must be safe to call from anywhere.
                              # RampSpec covers the four numbers; ramp.validate_window
                              # covers the window.
    stabilize: bool = False   # run the vidstab pre-stage before tracking (design
                              # 2026-07-20). EXPLICIT by design and never inferred:
                              # a wade-in shot is handheld in moving water and so is
                              # noisy BY CONSTRUCTION, which means any auto-enable
                              # keyed on measured shake fires most confidently on
                              # exactly the shot the landmine registry forbids
                              # stabilizing. The signal is already in front of
                              # whoever authors this row — FOOTAGE.md prints the
                              # window's shake.
    hero: tuple | str | int | None = None   # seed bbox / rule / track id / cast name (§5.10);
                                            # NOT validated here — see the class docstring: the
                                            # manifest gate reached via preflight is its one home
    white_balance: float = 0.0  # grey-world neutralize toward the common average, FIRST in
                                # the chain; 0 = off — see color.white_balance_arg.
    black_point: float = 0.0    # fraction subtracted from the toe before the grade's gain.
                                # A camera that records a LIFTED black floor (DJI's flat profile
                                # put this footage's darkest 1% at 65.7/255 against 23.1 on the
                                # telephoto beside it) cannot be matched by gain, which scales a
                                # floor rather than moving it. See color.black_point_arg.
    highlight: float = 1.0      # white pulled down to this after the gain; the twin of
                                # black_point at the other end. See color.highlight_arg.
    saturation: float = 1.0     # chroma scale after the gain; the hue-preserving way to
                                # tame an over-vivid source. See color.saturation_arg.
    dip: float = 0.0            # fade in/out to dark grey, seconds. A transition that costs
                                # no duration. See color.dip_arg.
    mid_blue: float = 1.0       # blue scaled in the midtones only; neutralizes sky bounce
                                # on skin. See color.mid_blue_arg.
    shadow_red: float = 0.0     # red toe lift; neutralizes a green/cyan black without
                                # touching skin or a red board. See color.shadow_red_arg.
    tone_src: tuple[float, float, float] | None = None   # this episode's measured
    tone_dst: tuple[float, float, float] | None = None   # (p5, p50, p95) -> the reel's
                                # common profile. Normalizes the SOURCE before any of the
                                # above touches it; see color.tone_arg for why neither
                                # black_point nor highlight can do this job.
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
        if not isinstance(self.stabilize, bool):
            raise ValueError(f"EDLEpisode.stabilize must be true or false, got {self.stabilize!r}")
        if self.ramp is not None:
            ramp_mod.validate_window(
                RampSpec.from_dict(self.ramp), self.dur,
                f"EDLEpisode {self.source} @{self.start:.2f}s")
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
        if isinstance(self.tone_src, list):
            self.tone_src = tuple(self.tone_src)
        if isinstance(self.tone_dst, list):
            self.tone_dst = tuple(self.tone_dst)

    def to_dict(self) -> dict:
        def _j(v: object) -> object:
            return list(v) if isinstance(v, tuple) else v
        return {"source": self.source, "start": self.start, "dur": self.dur,
                "shot_type": self.shot_type, "composition": self.composition, "grid": self.grid,
                "layout": self.layout, "crop_aspect": _j(self.crop_aspect), "crop_scale": self.crop_scale,
                "rect": _j(self.rect), "background": self.background,
                "background_color": self.background_color, "border_px": self.border_px,
                "border_color": self.border_color, "motion": self.motion, "pan": self.pan,
                "zoom": self.zoom,
                "stabilize": self.stabilize, "ramp": self.ramp,
                "hero": _j(self.hero),
                "white_balance": self.white_balance,
                "black_point": self.black_point, "highlight": self.highlight,
                "saturation": self.saturation, "shadow_red": self.shadow_red,
                "mid_blue": self.mid_blue, "dip": self.dip,
                **({"tone_src": list(self.tone_src), "tone_dst": list(self.tone_dst)}
                   if self.tone_src is not None else {}),
                "color_means": list(self.color_means), "processing_notes": self.processing_notes,
                "beat_slot": self.beat_slot}

    def play_dur(self) -> float:
        """How long this episode PLAYS, against `dur`'s how much SOURCE it consumes.

        Equal without a ramp — which is why the codebase managed with one word for
        both until now. The truthful authority for the beat-grid fit, the pacing
        binding, the per-episode length check and the reel length gate (design §1,
        §6). Anything measuring screen time calls this; anything measuring footage
        consumed keeps reading `dur`."""
        if self.ramp is None:
            return self.dur
        return self.dur + ramp_mod.ramp_extra(RampSpec.from_dict(self.ramp), self.dur)


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
    variety: VarietyReport | None = None   # design 2026-08-06 §9. None = never evaluated
                                           # (a hand-authored EDL through the SP1 front door)
    constraints: ConstraintReport | None = None   # design 2026-08-07 §8. None = never
                                                  # evaluated (no CONSTRAINTS.json beside
                                                  # project.json), never "passed"
    provenance: dict = field(default_factory=dict)   # design §4; empty = unstamped

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
        if self.variety is not None and not isinstance(self.variety, VarietyReport):
            raise ValueError(f"EDL.variety must be a VarietyReport or None, got "
                             f"{type(self.variety).__name__} — re-run edit_plan build")
        if self.constraints is not None and not isinstance(self.constraints, ConstraintReport):
            raise ValueError(f"EDL.constraints must be a ConstraintReport or None, got "
                             f"{type(self.constraints).__name__} — re-run edit_plan build")
        if not isinstance(self.provenance, dict):
            raise ValueError(f"EDL.provenance must be an object, got "
                             f"{type(self.provenance).__name__} — re-run edit_plan build "
                             f"to regenerate EDL.json")

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
                   cap=cap if cap is not None else 3, target_dur=d.get("target_dur"),
                   variety=VarietyReport.from_dict(d["variety"]) if d.get("variety") else None,
                   constraints=(ConstraintReport.from_dict(d["constraints"])
                                if d.get("constraints") else None),
                   provenance=d.get(provenance.PROV_KEY) or {})

    @classmethod
    def from_json(cls, path: str | Path) -> "EDL":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the EDL syntax") from e
        # A MISSING block is legal — a hand-authored EDL.json is edl_to_reel's
        # documented front door (extract-spine SP1), and refusing it would delete a
        # designed capability to punish nobody. A block that no longer matches its own
        # contents is something else entirely: the tool's output, edited afterwards.
        if isinstance(d, dict):
            state, detail = provenance.check(d)
            if state == "tampered":
                raise ValueError(
                    f"{path} was edited after edit_plan wrote it ({detail}). Editorial "
                    f"changes belong in selection.json — edit that and re-run "
                    f"`edit_plan build`; raw-JSON surgery bypasses the manifest preflight "
                    f"that catches a window past EOF, a scene-cut straddle, and an "
                    f"unresolved cast pin")
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        d = {"episodes": [e.to_dict() for e in self.episodes],
             "music": self.music, "cast": self.cast, "cap": self.cap,
             "target_dur": self.target_dur,
             "variety": self.variety.to_dict() if self.variety is not None else None,
             "constraints": self.constraints.to_dict() if self.constraints is not None else None}
        if self.provenance:
            d[provenance.PROV_KEY] = dict(self.provenance)
        return d

    def to_markdown(self) -> str:
        total = sum(e.play_dur() for e in self.episodes)
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
            if e.zoom is not None:
                zm = f"zoom {e.zoom.get('from')}→{e.zoom.get('to')}"
                motion = zm if motion == "–" else f"{motion} · {zm}"
            beat = str(e.beat_slot) if e.beat_slot is not None else "–"
            window = f"{e.start:.2f}–{e.start + e.dur:.2f} ({e.dur:.2f}s)"
            notes = e.processing_notes
            if e.ramp is not None:
                notes = (f"⏱ ramp x{1 / e.ramp['factor']:.1f} @{e.ramp['at']:.1f}s "
                         f"(plays {e.play_dur():.2f}s) · {notes}").rstrip(" ·")
            lines.append(f"| {i} | {e.source} | {window} | {e.shot_type} | {e.layout} | "
                         f"{e.composition} | {e.grid} | {motion} | {beat} | {notes} |")
        if self.variety is not None:
            v = self.variety
            lines += ["", f"## Variety — preset `{v.preset}`", "",
                      "| shot | available | used |", "|------|----------:|-----:|"]
            lines += [f"| {s} | {v.available[s]} | {v.used[s]} |" for s in v.available]
            lines += ["", f"ASL {v.asl:.2f}s against the preset's "
                          f"{v.asl_band[0]:.1f}–{v.asl_band[1]:.1f}s band "
                          f"(reported, not enforced)."]
            if v.gaps:
                lines.append(f"**Unused sizes the footage offered:** {', '.join(v.gaps)}.")
            if v.waiver:
                lines.append(f"**Waiver:** {v.waiver}")
        # Rendered only when rules exist: an empty rule list is worth nothing to a human
        # reader, and EDL.json already distinguishes "no file" (null) from "no rules" ([]).
        if self.constraints is not None and self.constraints.rules:
            c = self.constraints
            lines += ["", "## Editorial rules", ""]
            lines += [f"- `{r.get('kind')}` — {r.get('stated')}" for r in c.rules]
            if c.violations:
                lines += [""] + [f"**Broken:** {v.message}" for v in c.violations]
            else:
                lines += ["", f"{len(c.rules)} checked, none broken."]
        return "\n".join(lines)


def write_edl(edl: EDL, path: str | Path, *, selection: str | Path | None = None) -> None:
    """The ONE place an EDL.json is written. Both authoring tools route through it —
    edit_plan projects a selection, match_grade rewrites the tone pair in place — so
    the stamp cannot drift between them; two writers stamping independently is the
    shape that rots. `selection` is the judgment file this cut was projected from;
    its digest rides in the block so a later reader can tell WHICH selection produced
    this EDL."""
    d = edl.to_dict()
    inputs = {"selection": provenance.digest_file(selection)} if selection is not None else {}
    d[provenance.PROV_KEY] = provenance.stamp(d, inputs=inputs)
    Path(path).write_text(json.dumps(d, indent=2))


def to_manifest_dict(ep: EDLEpisode, segment: str, out_path: str,
                     cast: str | None = None) -> dict:
    """Map an EDL row + its extracted segment + output path onto a Manifest-shaped
    dict (the process_episode brief). A deliberate field MAP, not a dump — the
    manifest gate rejects unknown keys. Omits canvas/delivery (the driver fills
    them from the project via resolve_manifest) and model (a manifest default).
    Four fields cross conditionally, on two different predicates: `pan`/`motion`/
    `hero` copy through only when the episode SETS one (not-None), so an absent
    value leaves the key out rather than carrying an explicit null; `stabilize`
    copies through only when TRUE, so a false (its default) leaves the key out
    too. Either way Manifest.from_dict falls to its own None/False default rather
    than the two sides disagreeing about what unset means. EDL-only fields (source/start/dur/shot_type/processing_notes/
    beat_slot) do NOT cross — this map is the documented EDL↔manifest boundary.
    `cast` is EDL.cast, the reel-level registry path — forwarded so a cast-name
    hero resolves per episode while the manifest itself stays a self-contained
    brief (§14.4); omitted when None so Manifest.from_dict falls to its own ""
    default rather than the dict carrying an explicit null."""
    # target_dur is the PLAYED length (design §6), not the source window: process_episode's
    # per-episode length check measures the RETIMED segment on disk (extract's pre-stage
    # already ran ramp.retime on it — see Task 3), and that segment is play_dur() long.
    # Equal to ep.dur without a ramp, so this is a no-op for every unramped episode.
    md: dict = {
        "segment": segment, "out_path": out_path, "target_dur": ep.play_dur(),
        "composition": ep.composition, "grid": ep.grid, "layout": ep.layout,
        "crop_scale": ep.crop_scale, "background": ep.background,
        "background_color": ep.background_color,
        "border_px": ep.border_px, "border_color": ep.border_color,
        "color_means": list(ep.color_means), "white_balance": ep.white_balance,
        "black_point": ep.black_point,
        "highlight": ep.highlight, "saturation": ep.saturation, "shadow_red": ep.shadow_red,
        "mid_blue": ep.mid_blue, "dip": ep.dip,
        **({"tone_src": list(ep.tone_src), "tone_dst": list(ep.tone_dst)}
           if ep.tone_src is not None else {}),
    }
    if ep.crop_aspect is not None:      # None → let Manifest pick canvas/source by layout
        md["crop_aspect"] = list(ep.crop_aspect) if isinstance(ep.crop_aspect, tuple) else ep.crop_aspect
    if ep.rect is not None:
        md["rect"] = list(ep.rect)
    if ep.motion is not None:
        md["motion"] = ep.motion
    if ep.pan is not None:
        md["pan"] = ep.pan
    if ep.zoom is not None:
        md["zoom"] = ep.zoom
    if ep.stabilize:
        md["stabilize"] = True
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
