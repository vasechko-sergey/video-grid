"""Footage-intake contracts: scored candidate windows + the cast registry
(design docs/specs/2026-07-12-footage-intake-design.md, stage 5.2).

Hard config-specs — validate-and-raise in __post_init__, JSON round-trip — like
models.py's TrackSpec/MusicSpec and edl.py's EDL (NOT the soft manifest gate).
Mutable on purpose: intake's cull sets FootageWindow.best after construction.
A FootageWindow projects onto an EDLEpisode (source lives on the parent clip),
so 5.7 edit-plan promotes a window to an episode by a mechanical field map.
"""
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import geometry

# The descriptor is a 512-d OSNet person-re-ID embedding (design 2026-08-04),
# L2-normalized, compared by cosine. It lives HERE as the on-disk contract of
# cast.json so a reader validates a descriptor without importing the CV/torch
# stack that produced it — the manifest gate (manifest → hero → footage → edl)
# stays numpy-free and answers in milliseconds. reid.EMBED_DIM mirrors this
# number on the producing side (lib/reid); the two agree by construction.
DESCRIPTOR_LEN = 512


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


SHOT_TYPES = ("close", "medium", "wide")
CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08     # subject-area fractions bounding the three tags

# The three terms intake's window score blends, in the order they are reported.
# Lives here rather than in intake.py because it is an ON-DISK vocabulary: Footage
# validates a FOOTAGE.json against it, and lib may not import a driver (the same
# reason SHOT_TYPES lives here and moodpreset imports it).
SCORE_TERMS = ("present", "motion", "shake")
# ...and the two a PHOTO's score blends. Photos rank among photos only (design
# 2026-10-21 §5): a still's motion and shake are 0 by construction, which beside video
# ranks it last on one term and first on the other.
PHOTO_SCORE_TERMS = ("present", "sharpness")


def shot_type(subject_w: float, subject_h: float) -> str:
    """close/medium/wide from the subject's area as a fraction of the FRAME it is
    measured against. Geometry-agnostic on purpose (design 2026-08-06 §6): intake
    passes source fractions, edit_plan passes delivered ones via delivered_shot,
    and one classifier keeps the two from drifting apart. No subject — (0.0, 0.0) —
    is 'wide', the same answer scenery gets."""
    area = subject_w * subject_h
    if area > CLOSE_AREA:
        return "close"
    if area >= MEDIUM_AREA:
        return "medium"
    return "wide"


def delivered_shot(subject_w: float, subject_h: float, res: tuple[int, int],
                   aspect: tuple[int, int], crop_scale: float = 1.0) -> str:
    """The window's shot size as it will READ in the delivered frame rather than in
    the source one. A 9:16 fill crop of a 16:9 source keeps the height and cuts the
    width, so the subject's area fraction grows by src_w/crop_w — 3.16x for
    3840x2160 — which is why the source-geometry tag cannot discriminate on footage
    shot from a distance (design §1c, §6). The fractions are scale-normalized, so it
    does not matter that intake measured them on the 960 analysis proxy while `res`
    is the original: only the divisor changes, and it changes on both sides."""
    crop_w, crop_h = geometry.crop_for(aspect, crop_scale, *res)
    return shot_type(min(1.0, subject_w * res[0] / crop_w),
                     min(1.0, subject_h * res[1] / crop_h))


@dataclass
class FootageWindow:
    start: float
    dur: float
    shot_type: str
    people: int
    motion: float
    shake: float
    description: str = ""
    score: float = 0.0
    best: bool = False
    track_ids: list[int] = field(default_factory=list)
    subject_w: float = 0.0   # primary subject's bbox width as a fraction of the frame width
    subject_h: float = 0.0   # ...and height. 0.0 / 0.0 = no person detected in this window
    present: float = 0.0     # fraction of this window's samples holding >= 1 person

    def __post_init__(self) -> None:
        if not (_num(self.start) and self.start >= 0):
            raise ValueError(f"FootageWindow.start must be a number >= 0 (seconds), got {self.start!r}")
        if not (_num(self.dur) and self.dur > 0):
            raise ValueError(f"FootageWindow.dur must be a positive number (seconds), got {self.dur!r}")
        if not (isinstance(self.shot_type, str) and self.shot_type):
            raise ValueError("FootageWindow.shot_type must be a non-empty tag (e.g. 'wide', 'close')")
        if isinstance(self.people, bool) or not isinstance(self.people, int) or self.people < 0:
            raise ValueError(f"FootageWindow.people must be an int >= 0, got {self.people!r}")
        if not (_num(self.motion) and 0.0 <= self.motion <= 1.0):
            raise ValueError(f"FootageWindow.motion must be a number in [0, 1], got {self.motion!r}")
        if not (_num(self.shake) and self.shake >= 0):
            raise ValueError(f"FootageWindow.shake must be a number >= 0, got {self.shake!r}")
        if not isinstance(self.description, str):
            raise ValueError("FootageWindow.description must be a string")
        if not (_num(self.score) and 0.0 <= self.score <= 1.0):
            raise ValueError(f"FootageWindow.score must be a number in [0, 1], got {self.score!r}")
        if not isinstance(self.best, bool):
            raise ValueError("FootageWindow.best must be a bool")
        if not isinstance(self.track_ids, list) or any(
                isinstance(t, bool) or not isinstance(t, int) or t < 0 for t in self.track_ids):
            raise ValueError(f"FootageWindow.track_ids must be a list of ints >= 0 "
                             f"(the track ids present in the window), got {self.track_ids!r}")
        for name in ("subject_w", "subject_h", "present"):
            v = getattr(self, name)
            if not (_num(v) and 0.0 <= v <= 1.0):
                raise ValueError(
                    f"FootageWindow.{name} must be a number in [0, 1] — subject_w/subject_h "
                    f"are fractions of the frame, present is a fraction of the window's "
                    f"samples; got {v!r}")

    def to_dict(self) -> dict:
        return {"start": self.start, "dur": self.dur, "shot_type": self.shot_type,
                "people": self.people, "motion": self.motion, "shake": self.shake,
                "description": self.description, "score": self.score,
                "best": self.best, "track_ids": list(self.track_ids),
                "subject_w": self.subject_w, "subject_h": self.subject_h,
                "present": self.present}


CLIP_KINDS = ("video", "photo")


@dataclass
class FootageClip:
    """One source file. A `photo` (design 2026-10-20 §1) is a clip with one window, no
    scene cuts and no frame rate: `fps` is 0.0 for it, and `dur` is how long it may be
    held (intake's PHOTO_ROOM), not a length it has. `res` is the upright, capped raster
    the decoder hands back, which is what every reader of the photo sees."""
    source: str
    dur: float
    res: tuple[int, int]
    fps: float
    shaky: bool = False
    scene_cuts: list[float] = field(default_factory=list)
    windows: list[FootageWindow] = field(default_factory=list)
    kind: str = "video"
    group: str | None = None    # a photo's burst/near-duplicate group id (design 2026-10-21 §5)

    def __post_init__(self) -> None:
        if not (isinstance(self.source, str) and self.source):
            raise ValueError("FootageClip.source must be a non-empty clip path")
        if self.kind not in CLIP_KINDS:
            raise ValueError(f"FootageClip.kind must be one of {CLIP_KINDS}, got {self.kind!r}")
        if not (_num(self.dur) and self.dur > 0):
            raise ValueError(f"FootageClip.dur must be a positive number, got {self.dur!r}")
        if isinstance(self.res, list):
            self.res = tuple(self.res)
        if not (isinstance(self.res, tuple) and len(self.res) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in self.res)):
            raise ValueError(f"FootageClip.res must be (w, h) positive ints, got {self.res!r}")
        if self.kind == "photo":
            if not (_num(self.fps) and self.fps == 0):
                raise ValueError(f"FootageClip.fps must be 0.0 for a photo — a still has no "
                                 f"frame rate, and a number here would read as one; got "
                                 f"{self.fps!r}")
            if self.scene_cuts or self.shaky:
                raise ValueError("FootageClip: a photo has no scene cuts and cannot be shaky")
        elif not (_num(self.fps) and self.fps > 0):
            raise ValueError(f"FootageClip.fps must be a positive number, got {self.fps!r}")
        if not isinstance(self.shaky, bool):
            raise ValueError("FootageClip.shaky must be a bool")
        if not isinstance(self.scene_cuts, list):
            raise ValueError(f"FootageClip.scene_cuts must be a list of numbers (seconds), "
                             f"got {self.scene_cuts!r} — re-run footage-intake to regenerate FOOTAGE.json")
        for k, t in enumerate(self.scene_cuts):
            if not (_num(t) and t >= 0):
                raise ValueError(f"FootageClip.scene_cuts[{k}] must be a number >= 0 (seconds), "
                                 f"got {t!r} — re-run footage-intake to regenerate FOOTAGE.json")
        self.scene_cuts = [float(t) for t in self.scene_cuts]
        if not isinstance(self.windows, list):
            raise ValueError(f"FootageClip.windows must be a list of FootageWindow, "
                             f"got {self.windows!r} — re-run footage-intake to regenerate FOOTAGE.json")
        for k, w in enumerate(self.windows):
            if not isinstance(w, FootageWindow):
                raise ValueError(f"FootageClip.windows[{k}] must be a FootageWindow")
        if self.group is not None:
            if not (isinstance(self.group, str) and self.group):
                raise ValueError(f"FootageClip.group must be a non-empty string (a photo "
                                 f"group id such as 'g1'), or absent for a photo in no "
                                 f"group; got {self.group!r} — re-run footage-intake to "
                                 f"regenerate FOOTAGE.json")
            if self.kind != "photo":
                raise ValueError(f"FootageClip.group: only a photo is grouped (a burst or "
                                 f"its near-identical retakes); {self.source} is a "
                                 f"{self.kind} — re-run footage-intake to regenerate "
                                 f"FOOTAGE.json")

    @classmethod
    def from_dict(cls, d: dict) -> "FootageClip":
        # Top level checked FIRST, before d.get — see Footage.from_dict below for why this
        # boundary owes its callers ONE documented exception type. Footage.from_dict already
        # checks each clip is an object before delegating here, so this guard is for the
        # direct caller: from_dict is public contract surface, and a guard that depends on
        # every caller having checked first is not a guard.
        if not isinstance(d, dict):
            raise ValueError(f"FootageClip.from_dict: expected a FOOTAGE.json clip object with a "
                             f"'windows' list, got {type(d).__name__} — re-run footage-intake to "
                             f"regenerate FOOTAGE.json")
        wins_in = d.get("windows", [])
        if not isinstance(wins_in, list):
            raise ValueError("FootageClip.from_dict: 'windows' must be a list")
        wins = []
        for k, w in enumerate(wins_in):
            if not isinstance(w, dict):
                raise ValueError(f"FootageClip.from_dict: windows[{k}] must be an object")
            if "present" not in w:
                raise ValueError(
                    f"FootageClip.from_dict: windows[{k}] predates the 2026-08-06 shot-size "
                    f"fields (missing 'present') — re-run footage-intake to rescan. The "
                    f"fields carry 0.0 defaults so the object would build, but it would then "
                    f"claim 'no people anywhere' and the variety gate would read that as a "
                    f"monotone footage set")
            try:
                wins.append(FootageWindow(**w))
            except TypeError as ex:
                raise ValueError(f"FootageClip.from_dict: windows[{k}] has a missing or unknown field — {ex}") from ex
        try:
            return cls(**{**d, "windows": wins})       # unknown top-level key → TypeError → remedy
        except TypeError as ex:
            raise ValueError(f"FootageClip.from_dict: missing or unknown field — {ex}") from ex

    def to_dict(self) -> dict:
        d = {"source": self.source, "dur": self.dur, "res": list(self.res), "fps": self.fps,
             "shaky": self.shaky, "scene_cuts": self.scene_cuts,
             "windows": [w.to_dict() for w in self.windows]}
        if self.kind != "video":       # omitted for video: every FOOTAGE.json and cache
            d["kind"] = self.kind      # entry written before photos stays byte-identical
        if self.group is not None:     # omitted for a lone photo, and for every video
            d["group"] = self.group
        return d

    def room_after(self, start: float) -> float:
        """Seconds available after `start` inside the SAME uninterrupted shot.

        Running an episode into this room is not stretching footage — no frame is slowed
        or repeated, the shot simply runs longer. intake carves a take into activity
        units that may overlap and need not tile it (2026-07-25 activity-units §2), so a
        window boundary is not a partition line — the room after a start is what the shot
        itself offers. A scene cut does mark something, and running across one would
        splice two different shots into one episode — so the room stops there."""
        if not (_num(start) and start >= 0):
            raise ValueError(f"FootageClip.room_after: start must be >= 0 seconds, "
                             f"got {start!r}")
        if start >= self.dur:
            raise ValueError(f"FootageClip.room_after: start {start} is past the end of "
                             f"{self.source} ({self.dur}s)")
        after = [c for c in self.scene_cuts if c > start]
        return float((min(after) if after else self.dur) - start)

    def shot_at(self, t: float) -> tuple[float, float]:
        """The [start, end) of the uninterrupted shot containing `t`.

        The identity unit editorial constraints key on (design
        docs/specs/2026-08-07-editorial-constraints-design.md §2): two episodes carved
        from ONE shot are the same moment even when their spans do not overlap, which
        is the repeat a per-window comparison misses — carve deliberately emits
        overlapping candidate windows, so two indices routinely name one moment.

        Both bounds are the surrounding CUT VALUES themselves (0.0 / the clip's own
        `dur` when there is none on that side) — never a value derived from `t` — so
        every `t` inside the same shot returns a bit-identical pair. That is the
        property `no_repeat`/`exclude` actually depend on: two episodes placed at
        different in-points inside one shot must key alike, or the repeat they form
        would compare unequal and slip past the check silently.

        Shares room_after's boundary rule (`c > t`, so a `t` exactly ON a cut belongs
        to the shot that BEGINS there): the two must not disagree about where a shot
        ends, or an episode would be legal by one authority and a straddle by the
        other."""
        if not (_num(t) and t >= 0):
            raise ValueError(f"FootageClip.shot_at: t must be a number >= 0 seconds, got {t!r}")
        if t >= self.dur:
            raise ValueError(f"FootageClip.shot_at: t {t} is past the end of "
                             f"{self.source} ({self.dur}s)")
        before = [c for c in self.scene_cuts if c <= t]
        after = [c for c in self.scene_cuts if c > t]
        return (float(max(before)) if before else 0.0,
                float(min(after)) if after else float(self.dur))


@dataclass
class Footage:
    clips: list[FootageClip] = field(default_factory=list)
    band: tuple | None = None        # (win_min, win_max) this scan carved with
    scoring: dict | None = None      # what each score term separated (design 2026-09-10 §4)

    def __post_init__(self) -> None:
        for k, c in enumerate(self.clips):
            if not isinstance(c, FootageClip):
                raise ValueError(f"Footage.clips[{k}] must be a FootageClip")
        if self.band is not None:
            if not (isinstance(self.band, (tuple, list)) and len(self.band) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            for v in self.band)
                    and 0 < self.band[0] <= self.band[1]):
                raise ValueError(
                    f"Footage.band must be (win_min, win_max) seconds with "
                    f"0 < win_min <= win_max, or null on an artifact written before "
                    f"2026-09-03. Got {self.band!r} — re-run footage-intake to "
                    f"regenerate FOOTAGE.json")
            self.band = (float(self.band[0]), float(self.band[1]))
        if self.scoring is not None:
            s = self.scoring
            if not (isinstance(s, dict)
                    and {"windows", "separated"} <= set(s) <= {"windows", "separated", "photos"}):
                raise ValueError(
                    f"Footage.scoring must be {{'windows': int, 'separated': {{term: int}}}} "
                    f"(plus an optional 'photos' block of the same shape), or null on an "
                    f"artifact written before 2026-09-10. Got {s!r} — re-run footage-intake "
                    f"to regenerate FOOTAGE.json")
            out = _separation(s, SCORE_TERMS, "Footage.scoring")
            if "photos" in s:
                p = s["photos"]
                if not isinstance(p, dict) or set(p) != {"windows", "separated"}:
                    raise ValueError(
                        f"Footage.scoring['photos'] must be {{'windows': int, 'separated': "
                        f"{{term: int}}}} over {PHOTO_SCORE_TERMS} — the photos' own pool. "
                        f"Got {p!r} — re-run footage-intake to regenerate FOOTAGE.json")
                out["photos"] = _separation(p, PHOTO_SCORE_TERMS, "Footage.scoring['photos']")
            self.scoring = out

    @classmethod
    def from_dict(cls, d: dict) -> "Footage":
        # The top level is checked FIRST, before d.get: this boundary reads user-supplied
        # JSON, so it owes its callers ONE documented exception type (ValueError-with-
        # remedy, per coding-standards). Without this, a valid-JSON-but-wrong-shape top
        # level (a bare array/string/number/bool/null) reached d.get and raised a bare
        # AttributeError — and write_edit_plan (scripts/edit_plan.py) has no except around
        # Footage.from_json at all, so it crashed the driver instead of naming a remedy.
        if not isinstance(d, dict):
            raise ValueError(f"Footage.from_dict: expected a FOOTAGE.json object with a 'clips' "
                             f"list, got {type(d).__name__} — re-run footage-intake to regenerate "
                             f"FOOTAGE.json")
        clips_in = d.get("clips", [])
        if not isinstance(clips_in, list):
            raise ValueError("Footage.from_dict: 'clips' must be a list")
        clips = []
        for k, c in enumerate(clips_in):
            if not isinstance(c, dict):
                raise ValueError(f"Footage.from_dict: clips[{k}] must be an object")
            clips.append(FootageClip.from_dict(c))
        return cls(clips=clips, band=d.get("band"), scoring=d.get("scoring"))

    @classmethod
    def from_json(cls, path: str | Path) -> "Footage":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the FOOTAGE syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"clips": [c.to_dict() for c in self.clips],
                "band": None if self.band is None else list(self.band),
                "scoring": None if self.scoring is None else {
                    "windows": self.scoring["windows"],
                    "separated": dict(self.scoring["separated"]),
                    # omitted without photos, so a video-only FOOTAGE.json is byte-identical
                    **({"photos": {"windows": self.scoring["photos"]["windows"],
                                   "separated": dict(self.scoring["photos"]["separated"])}}
                       if "photos" in self.scoring else {})}}

    def ranked_windows(self) -> list[tuple["FootageClip", "FootageWindow"]]:
        pairs = [(c, w) for c in self.clips for w in c.windows]
        return sorted(pairs, key=lambda cw: cw[1].score, reverse=True)

    def to_markdown(self) -> str:
        wins = [w for c in self.clips for w in c.windows]
        n_best = sum(1 for w in wins if w.best)
        photos = [c for c in self.clips if c.kind == "photo"]
        size = Counter(c.group for c in photos if c.group is not None)
        # every wording below changes only when photos exist, so a video-only FOOTAGE.md
        # stays byte-identical
        split = bool(photos) or (self.scoring is not None and "photos" in self.scoring)
        counted = ""
        if photos:
            counted = f" · {_n(len(photos), 'photo')}"
            if size:
                counted += f", {sum(size.values())} in {_n(len(size), 'group')}"
        within = ("its kind in THIS footage set — a video window's among the video windows, "
                  "a photo's among the photos (design 2026-10-21 §5) — never an absolute "
                  "quality bar, and never comparable to another shoot's numbers, nor a "
                  "photo's to a video's." if split else
                  "THIS footage set (design 2026-08-06-intake-motion-scoring §4.2) — never an "
                  "absolute quality bar, and never comparable to another shoot's numbers.")
        lines = [f"# Footage — {len(self.clips)} clips, {len(wins)} windows ({n_best} best)"
                 f"{counted}", "",
                 f"`score` is a percentile within {within} `motion` is mean per-sample "
                 "subject displacement as a fraction of frame width.", ""]
        if self.scoring is not None:
            n, sep = self.scoring["windows"], self.scoring["separated"]
            if not (split and n == 0):          # a photo-only pool has no video line
                lines += [f"Each blend term's `separated` count is how many of "
                          f"{'the video windows' if split else 'those windows'} it "
                          "told apart. A term near zero contributed nothing to THIS pool's "
                          "ordering — it is not a quality signal here, whatever its weight "
                          "(design 2026-09-10 §4): "
                          + ", ".join(f"**{t}** {sep[t]}/{n}" for t in SCORE_TERMS) + ".", ""]
            if "photos" in self.scoring:
                pn, psep = self.scoring["photos"]["windows"], self.scoring["photos"]["separated"]
                lines += ["A photo's `score` is its percentile among the PHOTOS only — a still "
                          "has no motion or shake, which beside video would rank it last on "
                          "one and first on the other (design 2026-10-21 §5). Its two terms: "
                          + ", ".join(f"**{t}** {psep[t]}/{pn}" for t in PHOTO_SCORE_TERMS)
                          + ".", ""]
        for c in self.clips:
            flag = " · shaky" if c.shaky else ""
            if c.kind == "photo":
                grouped = (f" · group {c.group} ({_n(size[c.group], 'photo')})"
                           if c.group is not None else "")
                lines.append(f"## {c.source}  (photo · {c.res[0]}×{c.res[1]} · may hold up "
                             f"to {c.dur:.1f}s){grouped}")
            else:
                lines.append(f"## {c.source}  ({c.dur:.1f}s · {c.res[0]}×{c.res[1]} @{c.fps:g}{flag})")
            if c.scene_cuts:
                lines.append("scene cuts: " + ", ".join(f"{t:.2f}" for t in c.scene_cuts))
            lines.append("| # | start | dur | shot | people | motion | shake | score | best | description |")
            lines.append("|---|-------|-----|------|--------|--------|-------|-------|:----:|-------------|")
            for i, w in enumerate(c.windows):
                star = "★" if w.best else ""
                lines.append(f"| {i} | {w.start:.2f} | {w.dur:.2f} | {w.shot_type} | {w.people} | "
                             f"{w.motion:.4f} | {w.shake:.4f} | {w.score:.2f} | {star} | {w.description} |")
            lines.append("")
        return "\n".join(lines)


def _n(k: int, noun: str) -> str:
    return f"{k} {noun}" + ("" if k == 1 else "s")


def _separation(s: dict, terms: tuple[str, ...], where: str) -> dict:
    """One separation report's `windows` and `separated`, validated and normalised —
    the shape the video pool and the photo pool share (design 2026-09-10 §4)."""
    n = s["windows"]
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError(f"{where}['windows'] must be an int >= 0, got {n!r} — re-run "
                         f"footage-intake to regenerate FOOTAGE.json")
    sep = s["separated"]
    if not isinstance(sep, dict) or set(sep) != set(terms):
        raise ValueError(f"{where}['separated'] must carry one count per {terms}, got "
                         f"{sep!r} — re-run footage-intake to regenerate FOOTAGE.json")
    for k in terms:
        v = sep[k]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= n:
            raise ValueError(f"{where}['separated'][{k!r}] must be an int in [0, {n}] — a "
                             f"term cannot separate more windows than the pool holds; got "
                             f"{v!r} — re-run footage-intake to regenerate FOOTAGE.json")
    return {"windows": n, "separated": {k: int(sep[k]) for k in terms}}


@dataclass
class CastMember:
    name: str
    descriptor: list[float]
    notes: str = ""
    ref_crops: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError("CastMember.name must be a non-empty string")
        if not (isinstance(self.descriptor, list) and self.descriptor
                and all(_num(v) for v in self.descriptor)):
            raise ValueError("CastMember.descriptor must be a non-empty list of numbers "
                             "(an OSNet person-re-ID embedding)")
        # The registry is the ONE boundary a foreign descriptor crosses, so its shape
        # is checked here, at load. Without this, a stale cast.json passed every gate
        # — Cast.from_json, hero.resolve, manifest.validate, edl.preflight — and only
        # died in appearance.descriptor_dist, deep inside tracking, after every window
        # had been cut. A typo'd cast NAME fails in milliseconds; a stale descriptor
        # must fail the same way, through the same channel, with the same remedy.
        if len(self.descriptor) != DESCRIPTOR_LEN:
            raise ValueError(f"CastMember {self.name!r}: descriptor must be {DESCRIPTOR_LEN} floats "
                             f"(an OSNet person-re-ID embedding), got {len(self.descriptor)} — a "
                             f"24-d colour histogram is a stale pre-2026-08-04 cast.json; re-run "
                             f"footage-intake to regenerate it "
                             f"(the footage-intake skill, or `bin/vg scripts.intake <footage_root> <out_dir>`)")
        if not isinstance(self.notes, str):
            raise ValueError("CastMember.notes must be a string")
        if not (isinstance(self.ref_crops, list) and all(isinstance(p, str) for p in self.ref_crops)):
            raise ValueError("CastMember.ref_crops must be a list of path strings")
        self.descriptor = [float(v) for v in self.descriptor]

    def to_dict(self) -> dict:
        return {"name": self.name, "descriptor": self.descriptor,
                "notes": self.notes, "ref_crops": self.ref_crops}


@dataclass
class Cast:
    members: list[CastMember] = field(default_factory=list)

    def __post_init__(self) -> None:
        for k, m in enumerate(self.members):
            if not isinstance(m, CastMember):
                raise ValueError(f"Cast.members[{k}] must be a CastMember")
        # A registry maps a NAME to one identity — that is the whole point of the
        # file, and hero.resolve is its only reader. Two members under one name map
        # it to neither: resolve returned whichever happened to be listed first, so
        # the route followed a coin flip nobody could see. Checked HERE rather than
        # in resolve because it is the type's invariant, not the pin's — which also
        # means intake.write_cast (where a human names two surfaced crops "Lena")
        # fails during the naming pass, before cast.json ever reaches disk, and
        # resolve's first match is the ONLY match by construction.
        names = [m.name for m in self.members]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"Cast has duplicate member name(s) {dupes} — a cast name must "
                             f"identify exactly one person, and a hero pin resolves against it. "
                             f"Give them distinct names ('Lena', 'Lena (wetsuit)'), or keep one "
                             f"entry if the crops show the same person in different shots.")

    @classmethod
    def from_dict(cls, d: dict) -> "Cast":
        # The top level is checked FIRST, before d.get: this boundary reads user-supplied
        # JSON, so it owes its callers ONE documented exception type (ValueError-with-
        # remedy, per coding-standards). Without this, a valid-JSON-but-wrong-shape top
        # level (a bare array/string/number/bool/null) reached d.get and raised a bare
        # AttributeError, which every caller would have to enumerate from memory.
        if not isinstance(d, dict):
            raise ValueError(f"Cast.from_dict: expected a cast.json object with a 'members' list, "
                             f"got {type(d).__name__} — re-run footage-intake to regenerate cast.json")
        ms_in = d.get("members", [])
        if not isinstance(ms_in, list):
            raise ValueError("Cast.from_dict: 'members' must be a list")
        ms = []
        for k, m in enumerate(ms_in):
            if not isinstance(m, dict):
                raise ValueError(f"Cast.from_dict: members[{k}] must be an object")
            try:
                ms.append(CastMember(**m))
            except TypeError as ex:
                raise ValueError(f"Cast.from_dict: members[{k}] has a missing or unknown field — {ex}") from ex
        return cls(members=ms)

    @classmethod
    def from_json(cls, path: str | Path) -> "Cast":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the cast syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"members": [m.to_dict() for m in self.members]}
