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


@dataclass(frozen=True)
class Spine:
    """The ordered energy skeleton (PACING.json). Covers [0, target_dur] exactly —
    slot 0 starts at 0.0, slots are contiguous, durations sum to target_dur, slot 0
    is the hook. Config-spec: a malformed spine fails loud, never mis-binds the edit."""
    slots: tuple
    target_dur: float
    tempo: float

    def __post_init__(self) -> None:
        if not isinstance(self.slots, tuple) or not self.slots:
            raise ValueError("Spine.slots must be a non-empty tuple of Slot — build_spine "
                             "found no beats; check the track/window")
        for want, s in enumerate(self.slots):
            if not isinstance(s, Slot):
                raise ValueError(f"Spine.slots[{want}] must be a Slot, got {s!r}")
            if s.index != want:
                raise ValueError(f"Spine.slots must be index-ordered 0..N-1; position "
                                 f"{want} has index {s.index}")
        if self.slots[0].kind != "hook":
            raise ValueError(f"Spine.slots[0].kind must be 'hook' (hook first, §5.6), "
                             f"got {self.slots[0].kind!r}")
        if abs(self.slots[0].start) > _TOL:
            raise ValueError(f"Spine.slots[0].start must be 0.0 (the reel starts at 0), "
                             f"got {self.slots[0].start}")
        for a, b in zip(self.slots, self.slots[1:]):
            if abs((a.start + a.dur) - b.start) > _TOL:
                raise ValueError(f"Spine slots must be contiguous: slot {a.index} ends at "
                                 f"{a.start + a.dur} but slot {b.index} starts at {b.start}")
        total = sum(s.dur for s in self.slots)
        if abs(total - self.target_dur) > 1e-3:
            raise ValueError(f"Spine slot durations sum to {total}, not target_dur "
                             f"{self.target_dur} — the spine must cover the fragment exactly")
        if isinstance(self.tempo, bool) or not isinstance(self.tempo, (int, float)) or self.tempo <= 0:
            raise ValueError(f"Spine.tempo must be a positive BPM, got {self.tempo!r}")
        object.__setattr__(self, "target_dur", float(self.target_dur))
        object.__setattr__(self, "tempo", float(self.tempo))

    def to_dict(self) -> dict:
        return {"target_dur": self.target_dur, "tempo": self.tempo,
                "slots": [s.to_dict() for s in self.slots]}

    @classmethod
    def from_dict(cls, d: dict) -> "Spine":
        for k in ("target_dur", "tempo", "slots"):
            if k not in d:
                raise ValueError(f"Spine.from_dict missing key {k!r} — a spine needs "
                                 f"target_dur, tempo, slots")
        return cls(slots=tuple(Slot.from_dict(s) for s in d["slots"]),
                   target_dur=d["target_dur"], tempo=d["tempo"])

    @classmethod
    def from_json(cls, path) -> "Spine":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def to_markdown(self) -> str:
        lines = [f"# Pacing — energy spine ({len(self.slots)} slots, "
                 f"{self.target_dur:.1f}s @ {self.tempo:.0f} BPM)", "",
                 "| # | start–end | dur | energy | kind |",
                 "|--:|-----------|----:|-------:|------|"]
        for s in self.slots:
            lines.append(f"| {s.index} | {s.start:.2f}–{s.start + s.dur:.2f} | "
                         f"{s.dur:.2f} | {s.energy:.2f} | {s.kind} |")
        return "\n".join(lines) + "\n"


LOW_BAND, HIGH_BAND = 0.33, 0.66          # normalized-energy band thresholds
SLOW_BEATS, MID_BEATS, FAST_BEATS = 8, 4, 2   # beats per slot by band (cut density ∝ energy)
HOOK_BEATS = 2                            # the first slot: short, attention-grab
_FLAT_EPS = 1e-9                          # energy range below this → treat as uniform


def _kind(n: float) -> str:
    """Normalized energy → band label (peak/build/release; hook is set positionally)."""
    return "peak" if n >= HIGH_BAND else "build" if n >= LOW_BAND else "release"


def _beats_per_slot(n: float) -> int:
    """Normalized energy → slot span in beats — fewer when loud (fast cuts)."""
    return FAST_BEATS if n >= HIGH_BAND else MID_BEATS if n >= LOW_BAND else SLOW_BEATS


def _beat_energy(beats: Sequence[float], energy: Sequence[float], energy_hz: float,
                 duration: float) -> list[float]:
    """Per-beat mean RMS, MIN-MAX normalized within the track → [0,1]. Beat i spans
    [beats[i], beats[i+1]) (the last → duration). A flat track (range < _FLAT_EPS) →
    all 0.5. Relative, not absolute — §12 loudness discipline (the drop is 'loud FOR
    THIS TRACK'; a quiet master still gets a real arc)."""
    edges = list(beats) + [duration]
    raw = []
    for i in range(len(beats)):
        i0 = max(0, round(edges[i] * energy_hz))
        i1 = max(i0 + 1, round(edges[i + 1] * energy_hz))
        seg = energy[i0:i1] or energy[i0:i0 + 1] or energy[-1:]
        raw.append(fmean(seg))
    lo, hi = min(raw), max(raw)
    return [0.5 if (hi - lo) < _FLAT_EPS else (r - lo) / (hi - lo) for r in raw]


def build_spine(beats: Sequence[float], energy: Sequence[float], energy_hz: float,
                duration: float, tempo: float) -> Spine:
    """Fold the beat grid + energy curve into a beat-aligned energy spine (§5.6).
    Greedy left-to-right: the first slot is a HOOK_BEATS hook; thereafter each slot
    spans _beats_per_slot(local energy) beats — fewer when loud (fast cuts), more when
    quiet. Slot boundaries snap to beat times; slot 0 starts at 0.0 and the last slot
    ends at `duration`, so the spine covers [0, duration] exactly. Deterministic
    (stdlib only) — the goldens pin exact slots."""
    if not beats:
        raise ValueError("build_spine got no beats — MUSIC.json analyze() found none; "
                         "check the track/window (a spine needs a beat grid)")
    n = _beat_energy(beats, energy, energy_hz, duration)
    slots: list[Slot] = []
    i = 0
    while i < len(beats):
        first = not slots
        start = 0.0 if first else beats[i]
        if not first and start >= duration - _TOL:   # a beat on the end → no zero-width tail slot
            break
        span = HOOK_BEATS if first else _beats_per_slot(n[i])
        j = min(i + span, len(beats))
        end = duration if j >= len(beats) else beats[j]
        e = fmean(n[i:j])
        slots.append(Slot(len(slots), start, end - start, e, "hook" if first else _kind(e)))
        i = j
    return Spine(tuple(slots), float(duration), float(tempo))
