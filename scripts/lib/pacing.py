"""Pacing / energy spine (design docs/specs/2026-07-14-pacing-design.md, §5.6, Phase B4).

The pure core: fold MUSIC.json's beat grid + RMS energy curve into a beat-aligned
energy spine — an ordered list of Slots whose length is inverse to local energy
(cut density rises with the music), hook first. Consumed by edit_plan (beat_slot +
per-episode target length) and rendered as PACING.{json,md} by scripts/pacing.py.
stdlib only (statistics.fmean) — NO numpy, NO librosa — so build_spine is bit-exact
and its goldens pin exact slots. Owns the spine value-space, exactly as offset.py
owns the envelope space and mood.py the vector space; imports nothing from the repo."""
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

KINDS = ("hook", "build", "peak", "release")
_TOL = 1e-6


@dataclass(frozen=True)
class Slot:
    """One beat-aligned span of the spine. `dur` becomes the bound episode's target
    window length; `kind` is an energy-band label (not a temporal role — a quiet
    intro and a quiet outro both read 'release'; 'hook' is the sole positional one)."""
    index: int
    start: float
    dur: float
    energy: float
    kind: str

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError(f"Slot.index must be a non-negative int, got {self.index!r}")
        for name in ("start", "dur", "energy"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"Slot.{name} must be a number, got {v!r}")
            object.__setattr__(self, name, float(v))
        if self.start < 0:
            raise ValueError(f"Slot.start must be >= 0, got {self.start}")
        if self.dur <= 0:
            raise ValueError(f"Slot.dur must be > 0 (a zero-width slot means two beats "
                             f"coincide — the beat grid is malformed), got {self.dur}")
        if not 0.0 <= self.energy <= 1.0:
            raise ValueError(f"Slot.energy must be in [0, 1], got {self.energy}")
        if self.kind not in KINDS:
            raise ValueError(f"Slot.kind {self.kind!r} not in {KINDS}")

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "dur": self.dur,
                "energy": self.energy, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "Slot":
        missing = [k for k in ("index", "start", "dur", "energy", "kind") if k not in d]
        if missing:
            raise ValueError(f"Slot.from_dict missing key(s) {missing} — a slot needs "
                             f"index, start, dur, energy, kind")
        return cls(index=d["index"], start=d["start"], dur=d["dur"],
                   energy=d["energy"], kind=d["kind"])
