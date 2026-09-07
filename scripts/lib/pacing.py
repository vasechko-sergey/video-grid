"""Pacing / fitted spine (design docs/specs/2026-07-24-scenario-first-pacing-design.md §3).

The pure core: given the cut durations the SCENARIO fixed and MUSIC.json's beat grid +
RMS energy curve, snap each out-point onto the coarsest musical grid level it can reach
and emit the fitted spine. Consumed by edit_plan (beat_slot + the snapped dur) and
rendered as PACING.{json,md} by scripts/pacing.py. stdlib only (statistics.fmean) — NO
numpy, NO librosa — so fit_spine is bit-exact and its goldens pin exact slots.

Until 2026-07-24 this module GENERATED lengths from energy (2/4/8 beats per slot), which
capped a slot at 4.6s at 104 BPM and silently truncated any shot that WAS the content —
a surf ride, a trick. Length ownership moved to the footage; what is left here is the
fit."""
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from scripts.lib import gridfit, provenance

KINDS = ("hook", "build", "peak", "release")
_TOL = 1e-6


@dataclass(frozen=True)
class Slot:
    """One fitted span of the spine. `dur` is the episode's own duration plus whatever
    the snap was allowed to add; `line` is the beat time its out-point was matched to
    (None on the tail — the reel's end is not a cut) and `dev` how far it still is from
    that line. `kind` is an energy-band LABEL, not a temporal role and no longer a
    length: a quiet intro and a quiet outro both read 'release'; 'hook' is positional."""
    index: int
    start: float
    dur: float
    energy: float
    kind: str
    line: float | None = None
    dev: float = 0.0
    beats_in: int = -1   # beats of the analysed window that fall inside this slot's
                         # span. 0 => `energy` is fit_spine's `or [0.5]` FALLBACK and
                         # `kind` is a label computed from that constant, not a
                         # measurement. -1 => not recorded (a PACING.json written
                         # before 2026-09-07). _beat_energy min-max normalizes into
                         # [0, 1], so a genuine 0.5 exists and was indistinguishable
                         # from the fallback until this field (design 2026-09-07 §5).

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError(f"Slot.index must be a non-negative int, got {self.index!r}")
        for name in ("start", "dur", "energy", "dev"):
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
        if self.line is not None:
            if isinstance(self.line, bool) or not isinstance(self.line, (int, float)):
                raise ValueError(f"Slot.line must be a beat time in seconds or None "
                                 f"(the tail slot ends the reel, not a cut), got {self.line!r}")
            object.__setattr__(self, "line", float(self.line))
        if self.dev < 0:
            raise ValueError(f"Slot.dev must be >= 0 (it is a distance), got {self.dev}")
        if (isinstance(self.beats_in, bool) or not isinstance(self.beats_in, int)
                or self.beats_in < -1):
            raise ValueError(
                f"Slot.beats_in must be a non-negative count of beats, or -1 for a "
                f"PACING.json written before 2026-09-07 which recorded none; got "
                f"{self.beats_in!r} — re-run pacing to regenerate PACING.json")

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "dur": self.dur,
                "energy": self.energy, "kind": self.kind, "line": self.line, "dev": self.dev,
                "beats_in": self.beats_in}

    @classmethod
    def from_dict(cls, d: dict) -> "Slot":
        # Top level checked FIRST, before `k not in d` — a scalar top level raised a bare
        # TypeError, a list/str one mis-read as "missing key(s)". Slot is read via
        # Spine.from_dict (now guarded), but from_dict is public contract surface and owes
        # ValueError-with-remedy per coding-standards.
        if not isinstance(d, dict):
            raise ValueError(f"Slot.from_dict: expected a slot object with index/start/dur/energy/"
                             f"kind/line/dev fields, got {type(d).__name__} — re-run pacing to "
                             f"regenerate PACING.json")
        missing = [k for k in ("index", "start", "dur", "energy", "kind", "line", "dev") if k not in d]
        if missing:
            raise ValueError(f"Slot.from_dict missing key(s) {missing} — a fitted slot needs "
                             f"index, start, dur, energy, kind, line, dev. A PACING.json "
                             f"written before 2026-07-24 has no fit; re-run pacing")
        return cls(index=d["index"], start=d["start"], dur=d["dur"],
                   energy=d["energy"], kind=d["kind"], line=d["line"], dev=d["dev"],
                   beats_in=d.get("beats_in", -1))


@dataclass(frozen=True)
class Spine:
    """The ordered energy skeleton (PACING.json). Covers [0, target_dur] exactly —
    slot 0 starts at 0.0, slots are contiguous, durations sum to target_dur, slot 0
    is the hook. Config-spec: a malformed spine fails loud, never mis-binds the edit."""
    slots: tuple
    target_dur: float
    tempo: float
    music_digest: str = ""   # identity of the analysed music WINDOW this spine was fitted
                             # to (design 2026-08-16 §4): music_identity() of the track
                             # file's own digest plus start_offset and duration. "" = not
                             # recorded — a PACING.json written before this slice, or one
                             # whose track file could not be read — and edit_plan then says
                             # so by name and falls back to comparing tempo, which cannot
                             # see a start_offset change at all.

    def __post_init__(self) -> None:
        if not isinstance(self.slots, tuple) or not self.slots:
            raise ValueError("Spine.slots must be a non-empty tuple of Slot — fit_spine "
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
        if not isinstance(self.music_digest, str):
            raise ValueError(f"Spine.music_digest must be a string (the analysed music "
                             f"window's identity, or '' when it was not recorded), got "
                             f"{self.music_digest!r} — re-run pacing to regenerate PACING.json")
        object.__setattr__(self, "target_dur", float(self.target_dur))
        object.__setattr__(self, "tempo", float(self.tempo))

    def to_dict(self) -> dict:
        return {"target_dur": self.target_dur, "tempo": self.tempo,
                "music_digest": self.music_digest,
                "slots": [s.to_dict() for s in self.slots]}

    @classmethod
    def from_dict(cls, d: dict) -> "Spine":
        # Top level checked FIRST, before `k not in d` — a scalar top level raised a bare
        # TypeError, a list/str one mis-read as "missing key". edit_plan.py:127 reads
        # Spine.from_json with no except, so the bare TypeError crashed the driver.
        if not isinstance(d, dict):
            raise ValueError(f"Spine.from_dict: expected a PACING.json object with target_dur/"
                             f"tempo/slots fields, got {type(d).__name__} — re-run pacing to "
                             f"regenerate PACING.json")
        for k in ("target_dur", "tempo", "slots"):
            if k not in d:
                raise ValueError(f"Spine.from_dict missing key {k!r} — a spine needs "
                                 f"target_dur, tempo, slots")
        return cls(slots=tuple(Slot.from_dict(s) for s in d["slots"]),
                   target_dur=d["target_dur"], tempo=d["tempo"],
                   music_digest=d.get("music_digest", ""))

    @classmethod
    def from_json(cls, path) -> "Spine":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def to_markdown(self) -> str:
        lines = [f"# Pacing — fitted spine ({len(self.slots)} slots, "
                 f"{self.target_dur:.1f}s @ {self.tempo:.0f} BPM)", "",
                 "| # | start–end | dur | energy | kind | line | dev |",
                 "|--:|-----------|----:|-------:|------|-----:|----:|"]
        unmeasured = 0
        for s in self.slots:
            line = f"{s.line:.2f}" if s.line is not None else "–"
            dev = f"{s.dev:.3f}" if s.line is not None else "–"
            # beats_in == -1 is a pre-2026-09-07 spine that did not record the count:
            # print what it has rather than claim it was unmeasured.
            if s.beats_in == 0:
                unmeasured += 1
                energy, kind = "–", "–"
            else:
                energy, kind = f"{s.energy:.2f}", s.kind
            lines.append(f"| {s.index} | {s.start:.2f}–{s.start + s.dur:.2f} | "
                         f"{s.dur:.2f} | {energy} | {kind} | {line} | {dev} |")
        if unmeasured:
            lines += ["", f"*{unmeasured} of {len(self.slots)} slots contain no beat of "
                          f"the analysed window, so their energy and kind are not "
                          f"measurements — `fit_spine` falls back to 0.5 and labels "
                          f"from it. A window whose beats start well into the reel is "
                          f"the usual cause.*"]
        return "\n".join(lines) + "\n"


def music_identity(track: str, start_offset: float, duration: float) -> str:
    """Identity of an analysed music WINDOW — the digest a Spine records and edit_plan
    checks (design 2026-08-16 §4).

    The track file's CONTENT digest (so moving a run directory does not invalidate it)
    plus the window's own in-point and length. Both halves are load-bearing: `tempo`
    alone cannot tell two tracks at the same BPM apart, and neither tempo NOR a
    track-only digest can see the same track analysed at a different `start_offset`,
    which moves every reel-relative grid line while the BPM stays bit-identical.

    Returns "" when the track file cannot be read — a NAMED not-checked, never a
    coincidental match. The caller must say so and fall back rather than treat "" as
    agreement."""
    try:
        track_digest = provenance.digest_file(track)
    except OSError:
        return ""
    return provenance.digest_obj({"track": track_digest,
                                  "start_offset": float(start_offset),
                                  "duration": float(duration)})


LOW_BAND, HIGH_BAND = 0.33, 0.66          # normalized-energy band thresholds
_FLAT_EPS = 1e-9                          # energy range below this → treat as uniform


def _kind(n: float) -> str:
    """Normalized energy → band label (peak/build/release; hook is set positionally)."""
    return "peak" if n >= HIGH_BAND else "build" if n >= LOW_BAND else "release"


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


def fit_spine(durs, beats, energy, energy_hz: float, tempo: float, bounds,
              levels=gridfit.GRID_LEVELS):
    """Fit the cuts the scenario already fixed onto the coarsest reachable grid level.

    Returns (Spine, chosen Fit, rejected Fits). `durs` are the episodes' own durations,
    `bounds` the per-episode (lo, hi) the snap may move each out-point by — the caller
    derives hi from the shot's remaining room (FootageClip.room_after). The allowance is
    half a beat, from `tempo`, and is NOT a function of the level (design §4).

    Slot 0 is the hook positionally; every other kind is an energy label. The spine
    covers [0, sum(fitted durations)] exactly, so Spine's own contiguity and total
    invariants hold by construction."""
    if not list(beats):
        raise ValueError("fit_spine got no beats — MUSIC.json analyze() found none; "
                         "check the track/window (a fit needs a beat grid)")
    allow = gridfit.allowance(tempo)
    fit, rejected = gridfit.best_fit(durs, beats, bounds, allow, levels=levels)
    fitted = [float(d) + s for d, s in zip(durs, fit.shifts)]
    total = sum(fitted)
    n = _beat_energy(beats, energy, energy_hz, total)
    # The grid lines are a function of the chosen level/phase only, not the slot — compute
    # them once, not once per cut.
    grid_lines = gridfit.lines_at(beats, fit.level_n, fit.phase)
    slots, pos = [], 0.0
    for i, dur in enumerate(fitted):
        inside = [n[k] for k, b in enumerate(beats) if pos <= b < pos + dur]
        # `or [0.5]` is a FALLBACK for a slot no beat reaches, not a measurement, and
        # _kind below labels the slot from it. beats_in records the count so a reader
        # can tell the two apart (design 2026-09-07 §0.4).
        e = fmean(inside or [0.5])
        tail = i == len(fitted) - 1
        dev = 0.0 if tail else fit.devs[i]
        # The tail's out-point is the reel's end, not a cut: it has no line to be near.
        line = None
        if not tail:
            want = pos + dur
            line = min(grid_lines, key=lambda L: abs(L - want))
        slots.append(Slot(i, pos, dur, e, "hook" if i == 0 else _kind(e),
                          line=line, dev=dev, beats_in=len(inside)))
        pos += dur
    return Spine(tuple(slots), total, float(tempo)), fit, rejected
