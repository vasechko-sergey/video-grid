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
