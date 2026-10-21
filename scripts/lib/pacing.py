"""Pacing / fitted spine (design docs/specs/2026-07-24-scenario-first-pacing-design.md §3).

The pure core: given the cut durations the SCENARIO fixed and MUSIC.json's beat grid +
RMS energy curve, snap each out-point onto the coarsest musical grid level it can reach
and emit the fitted spine. Consumed by edit_plan (beat_slot + the snapped dur) and
rendered as PACING.{json,md} by scripts/pacing.py. stdlib only (statistics.fmean,
statistics.correlation) — NO numpy, NO librosa — so fit_spine is bit-exact and its
goldens pin exact slots.

Until 2026-07-24 this module GENERATED lengths from energy (2/4/8 beats per slot), which
capped a slot at 4.6s at 104 BPM and silently truncated any shot that WAS the content —
a surf ride, a trick. Length ownership moved to the footage; what is left here is the
fit."""
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import correlation, fmean

from scripts.lib import gridfit, hold, provenance

KINDS = ("hook", "build", "peak", "release")
_TOL = 1e-6


@dataclass(frozen=True)
class Slot:
    """One fitted span of the spine. `dur` is the episode's own duration plus whatever
    the snap was allowed to add; `line` is the beat time its out-point was matched to
    (None on the tail — the reel's end is not a cut) and `dev` how far it still is from
    that line. `kind` is an energy-band LABEL, not a temporal role and no longer a
    length: a quiet intro and a quiet outro both read 'release'; 'hook' is positional.
    `held` marks a slot whose length the grid AUTHORED — a photo or a freeze (design
    2026-10-21 §2.3) — rather than snapped."""
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
    held: bool = False   # emitted only when true, so a video-only PACING.json is
                         # byte-identical to one written before held episodes existed
    hold: int | None = None   # the AUTHORED beat count a held slot was fitted with, None
                              # for the planner's — so binding can refuse an episode whose
                              # `hold` changed since the fit (design 2026-10-21 §2.3).
                              # Emitted only when set, like `held`

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
        if not isinstance(self.held, bool):
            raise ValueError(f"Slot.held must be true or false, got {self.held!r} — re-run "
                             f"pacing to regenerate PACING.json")
        if self.hold is not None:
            if isinstance(self.hold, bool) or not isinstance(self.hold, int) or self.hold < 1:
                raise ValueError(f"Slot.hold must be a whole number of beats >= 1 or null, got "
                                 f"{self.hold!r} — re-run pacing to regenerate PACING.json")
            if not self.held:
                raise ValueError(f"Slot.hold is the authored count of a HELD slot, and slot "
                                 f"{self.index} is not held — re-run pacing to regenerate "
                                 f"PACING.json")

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "dur": self.dur,
                "energy": self.energy, "kind": self.kind, "line": self.line, "dev": self.dev,
                "beats_in": self.beats_in, **({"held": True} if self.held else {}),
                **({"hold": self.hold} if self.hold is not None else {})}

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
                   beats_in=d.get("beats_in", -1), held=d.get("held", False),
                   hold=d.get("hold"))


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
            if s.held:
                n = round(s.dur * self.tempo / 60.0)
                kind += f" · held {n} beat{'' if n == 1 else 's'}"
            lines.append(f"| {s.index} | {s.start:.2f}–{s.start + s.dur:.2f} | "
                         f"{s.dur:.2f} | {energy} | {kind} | {line} | {dev} |")
        if unmeasured:
            lines += ["", f"*{unmeasured} of {len(self.slots)} slots contain no beat of "
                          f"the analysed window, so their energy and kind are not "
                          f"measurements — `fit_spine` falls back to 0.5 and labels "
                          f"from it. A window whose beats start well into the reel is "
                          f"the usual cause.*"]
        if any(s.held for s in self.slots):
            # the kind cell and the count answer two different spans, and a reader who
            # takes them for one sees "release · held 1 beat" contradict "shorter where
            # louder" (design 2026-10-21 §2.1)
            lines += ["", "*A held slot's kind is the energy band of its own span; its beat "
                          "count was planned from the bar that opens it (or authored), so the "
                          "two can disagree.*"]
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


AGREEMENT_MIN_SLOTS = 3   # Spearman over fewer than three ranked points describes
                          # nothing: with two, rho is +1 or -1 by construction.


def energy_agreement(slots: Sequence[Slot]) -> tuple[float | None, int, int, str]:
    """Spearman rho between a slot's DURATION and its music energy, over the slots
    whose energy was actually measured (design 2026-09-07 §6).

    Negative = shorter shots where the music is louder. Returns
    (rho, used, total, reason); `rho` is None exactly when `reason` is non-empty —
    never a silent 0.0, which would read as "no relationship" for a spine that was
    never measurable at all.

    A DESCRIPTION, not a verdict. No threshold has been measured: the only two real
    cuts on record are -0.571 (the reel that shipped) and +0.509 (the 18-episode cut
    it was cut down from), one shoot and one song, and nothing says where a line
    would go. Reporting only `dev` and `fits` made those two indistinguishable, which
    is the whole of retro R7.2.

    Ranked, not linear: the question is ordinal, and eight points do not support a
    fitted slope. statistics.correlation keeps this module's stdlib-only promise.

    Held slots are excluded too (design 2026-10-21 §2.3): a held length is derived FROM
    the energy by the grid's planner, so ranking it would report the planner agreeing
    with itself.

    beats_in == 0 slots are excluded — their energy is fit_spine's 0.5 fallback, and
    including them moves the number (on the real run's pacing_B, +0.276 over all 18
    slots against +0.160 over the 14 measured ones). beats_in == -1 is INCLUDED: it
    means the count was not recorded, not that it was zero, and excluding every slot
    of a pre-2026-09-07 spine would report "not measurable" for one that is merely
    unlabelled."""
    total = len(slots)
    usable = [s for s in slots if s.beats_in != 0 and not s.held]
    held_n = sum(1 for s in slots if s.held)
    if len(usable) < AGREEMENT_MIN_SLOTS:
        # Three distinct shortfalls share this arm: too few slots exist at all, or enough
        # exist but too many were excluded — as unmeasured, or as held. len(usable) ==
        # total means every slot IS usable and the count is simply too small to rank —
        # saying "only 2 of 2 slots carry a measured energy" there would name the wrong
        # shortfall (final review I-4): nothing was excluded, there just aren't three.
        if len(usable) == total:
            why = (f"the spine has only {total} slots and {AGREEMENT_MIN_SLOTS} are needed "
                   f"to rank")
        elif held_n:
            why = (f"only {len(usable)} of {total} slots carry a measured energy and a "
                   f"length the footage owns — {held_n} are held, and a held length is "
                   f"derived FROM the energy, so ranking it would report the planner "
                   f"agreeing with itself; {AGREEMENT_MIN_SLOTS} are needed to rank")
        else:
            why = (f"only {len(usable)} of {total} slots carry a measured energy, and "
                   f"{AGREEMENT_MIN_SLOTS} are needed to rank")
        return None, len(usable), total, why
    durs = [s.dur for s in usable]
    ens = [s.energy for s in usable]
    # correlation() raises StatisticsError when either input is constant, and under
    # method="ranked" that is exactly `len(set(...)) == 1`: ranking maps distinct
    # values to distinct ranks and ties to a shared one, so constant ranks means every
    # value was tied. Own the refusal here rather than let it escape into _report.
    if len(set(durs)) == 1 or len(set(ens)) == 1:
        return None, len(usable), total, (
            "every measured slot has the same duration or the same energy, so there "
            "is no ordering to correlate")
    return correlation(durs, ens, method="ranked"), len(usable), total, ""


def hold_planner(beats: Sequence[float], energy: Sequence[float], energy_hz: float,
                 tempo: float) -> Callable[[float, tuple[int, ...]], int]:
    """The grid's answer to "how many beats should this held episode take?" (design
    2026-10-21 §2.1) — the `plan(pos, run)` gridfit's held walk calls.

    It reads the music's per-beat energy over the next bar from the in-point (the four
    beats from `pos`), labels it with this module's own bands, turns the band's target
    seconds (hold.BAND_HOLD) into beats, and varies the count inside a run. A rising
    build therefore shortens the holds by itself: the drop is read through the bands,
    not through a separate detector. The normalization runs ONCE, over the beats alone
    (the fitted length is not known yet), so the planner cannot depend on the fit it is
    part of."""
    period = 2.0 * gridfit.allowance(tempo)      # one beat: the walk's own period
    norm = _beat_energy(beats, energy, energy_hz, beats[-1] + period)
    k_lo, k_hi = hold.count_range(period, hold.HOLD_MIN, hold.HOLD_ROOM)

    def plan(pos: float, run: tuple[int, ...]) -> int:
        bar = [norm[k] for k, b in enumerate(beats) if pos - 1e-6 <= b < pos + 4 * period]
        if bar:
            e = fmean(bar)
        else:   # past the analysed window: the nearest beat speaks for the bar
            e = norm[min(range(len(beats)), key=lambda k: abs(beats[k] - pos))]
        k = hold.beats_for(hold.BAND_HOLD[_kind(e)], period, hold.HOLD_MIN, hold.HOLD_ROOM)
        return hold.vary(k, run, k_lo, k_hi)

    return plan


def fit_spine(durs, beats, energy, energy_hz: float, tempo: float, bounds,
              levels=gridfit.GRID_LEVELS, *, held=None):
    """Fit the cuts the scenario already fixed onto the coarsest reachable grid level.

    Returns (Spine, chosen Fit, rejected Fits). `durs` are the episodes' own durations,
    `bounds` the per-episode (lo, hi) the snap may move each out-point by — the caller
    derives hi from the shot's remaining room (FootageClip.room_after). The allowance is
    half a beat, from `tempo`, and is NOT a function of the level (design §4).

    Slot 0 is the hook positionally; every other kind is an energy label. The spine
    covers [0, sum(fitted durations)] exactly, so Spine's own contiguity and total
    invariants hold by construction.

    `held` (design 2026-10-21 §2) is one gridfit.Held or None per episode: a held
    episode's length is authored by the grid through hold_planner, not snapped, and its
    slot carries `held=True`. None = every episode is footage, the fit as it was."""
    if not list(beats):
        raise ValueError("fit_spine got no beats — MUSIC.json analyze() found none; "
                         "check the track/window (a fit needs a beat grid)")
    allow = gridfit.allowance(tempo)
    plan = None if held is None else hold_planner(beats, energy, energy_hz, tempo)
    fit, rejected = gridfit.best_fit(durs, beats, bounds, allow, levels=levels,
                                     held=held, plan=plan)
    is_held = [False] * len(fit.shifts) if held is None else [h is not None for h in held]
    authored = [None] * len(fit.shifts) if held is None else [
        None if h is None else h.beats for h in held]
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
            # a held cut INSIDE a run was chosen among the detected beats, not the lines
            # (gridfit._held_cut), and its dev is to that beat — name the same point
            ref = beats if is_held[i] and is_held[i + 1] else grid_lines
            line = min(ref, key=lambda L: abs(L - want))
        slots.append(Slot(i, pos, dur, e, "hook" if i == 0 else _kind(e),
                          line=line, dev=dev, beats_in=len(inside), held=is_held[i],
                          hold=authored[i]))
        pos += dur
    return Spine(tuple(slots), total, float(tempo)), fit, rejected
