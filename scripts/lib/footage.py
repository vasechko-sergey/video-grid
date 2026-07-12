"""Footage-intake contracts: scored candidate windows + the cast registry
(design docs/specs/2026-07-12-footage-intake-design.md, stage 5.2).

Hard config-specs — validate-and-raise in __post_init__, JSON round-trip — like
models.py's TrackSpec/MusicSpec and edl.py's EDL (NOT the soft manifest gate).
Mutable on purpose: intake's cull sets FootageWindow.best after construction.
A FootageWindow projects onto an EDLEpisode (source lives on the parent clip),
so 5.7 edit-plan promotes a window to an episode by a mechanical field map.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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

    def to_dict(self) -> dict:
        return {"start": self.start, "dur": self.dur, "shot_type": self.shot_type,
                "people": self.people, "motion": self.motion, "shake": self.shake,
                "description": self.description, "score": self.score, "best": self.best}


@dataclass
class FootageClip:
    source: str
    dur: float
    res: tuple[int, int]
    fps: float
    shaky: bool = False
    scene_cuts: list[float] = field(default_factory=list)
    windows: list[FootageWindow] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (isinstance(self.source, str) and self.source):
            raise ValueError("FootageClip.source must be a non-empty clip path")
        if not (_num(self.dur) and self.dur > 0):
            raise ValueError(f"FootageClip.dur must be a positive number, got {self.dur!r}")
        if isinstance(self.res, list):
            self.res = tuple(self.res)
        if not (isinstance(self.res, tuple) and len(self.res) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in self.res)):
            raise ValueError(f"FootageClip.res must be (w, h) positive ints, got {self.res!r}")
        if not (_num(self.fps) and self.fps > 0):
            raise ValueError(f"FootageClip.fps must be a positive number, got {self.fps!r}")
        if not isinstance(self.shaky, bool):
            raise ValueError("FootageClip.shaky must be a bool")
        self.scene_cuts = [float(t) for t in self.scene_cuts]
        for k, w in enumerate(self.windows):
            if not isinstance(w, FootageWindow):
                raise ValueError(f"FootageClip.windows[{k}] must be a FootageWindow")

    @classmethod
    def from_dict(cls, d: dict) -> "FootageClip":
        wins_in = d.get("windows", [])
        if not isinstance(wins_in, list):
            raise ValueError("FootageClip.from_dict: 'windows' must be a list")
        wins = []
        for k, w in enumerate(wins_in):
            if not isinstance(w, dict):
                raise ValueError(f"FootageClip.from_dict: windows[{k}] must be an object")
            try:
                wins.append(FootageWindow(**w))
            except TypeError as ex:
                raise ValueError(f"FootageClip.from_dict: windows[{k}] has a missing or unknown field — {ex}") from ex
        try:
            return cls(**{**d, "windows": wins})       # unknown top-level key → TypeError → remedy
        except TypeError as ex:
            raise ValueError(f"FootageClip.from_dict: missing or unknown field — {ex}") from ex

    def to_dict(self) -> dict:
        return {"source": self.source, "dur": self.dur, "res": list(self.res), "fps": self.fps,
                "shaky": self.shaky, "scene_cuts": self.scene_cuts,
                "windows": [w.to_dict() for w in self.windows]}


@dataclass
class Footage:
    clips: list[FootageClip] = field(default_factory=list)

    def __post_init__(self) -> None:
        for k, c in enumerate(self.clips):
            if not isinstance(c, FootageClip):
                raise ValueError(f"Footage.clips[{k}] must be a FootageClip")

    @classmethod
    def from_dict(cls, d: dict) -> "Footage":
        clips_in = d.get("clips", [])
        if not isinstance(clips_in, list):
            raise ValueError("Footage.from_dict: 'clips' must be a list")
        clips = []
        for k, c in enumerate(clips_in):
            if not isinstance(c, dict):
                raise ValueError(f"Footage.from_dict: clips[{k}] must be an object")
            clips.append(FootageClip.from_dict(c))
        return cls(clips=clips)

    @classmethod
    def from_json(cls, path: str | Path) -> "Footage":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the FOOTAGE syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"clips": [c.to_dict() for c in self.clips]}

    def ranked_windows(self) -> list[tuple["FootageClip", "FootageWindow"]]:
        pairs = [(c, w) for c in self.clips for w in c.windows]
        return sorted(pairs, key=lambda cw: cw[1].score, reverse=True)

    def to_markdown(self) -> str:
        wins = [w for c in self.clips for w in c.windows]
        n_best = sum(1 for w in wins if w.best)
        lines = [f"# Footage — {len(self.clips)} clips, {len(wins)} windows ({n_best} best)", ""]
        for c in self.clips:
            flag = " · shaky" if c.shaky else ""
            lines.append(f"## {c.source}  ({c.dur:.1f}s · {c.res[0]}×{c.res[1]} @{c.fps:g}{flag})")
            if c.scene_cuts:
                lines.append("scene cuts: " + ", ".join(f"{t:.2f}" for t in c.scene_cuts))
            lines.append("| start | dur | shot | people | motion | shake | score | best | description |")
            lines.append("|-------|-----|------|--------|--------|-------|-------|:----:|-------------|")
            for w in c.windows:
                star = "★" if w.best else ""
                lines.append(f"| {w.start:.2f} | {w.dur:.2f} | {w.shot_type} | {w.people} | "
                             f"{w.motion:.2f} | {w.shake:.2f} | {w.score:.2f} | {star} | {w.description} |")
            lines.append("")
        return "\n".join(lines)


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
            raise ValueError("CastMember.descriptor must be a non-empty list of numbers (color histogram)")
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

    @classmethod
    def from_dict(cls, d: dict) -> "Cast":
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
