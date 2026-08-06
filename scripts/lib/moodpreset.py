"""Mood presets (design docs/specs/2026-08-06-mood-preset-variety-design.md §4) —
the playbook §3 spine, carrying exactly the two fields its one consumer reads.

A mood is not one knob: it is a recipe across shot selection, pace, colour, music
and effects. v1 wires the SELECTION half only — `edit_plan` reads `shot_mix` to
decide which shot-size under-use is refusable, and `asl` to report the realized
average shot length against a band. Colour, effects and QC are named follow-ups in
the design's §14, not fields nothing reads.

Pure: stdlib + lib.mood + lib.footage's SHOT_TYPES vocabulary. No IO."""
from dataclasses import dataclass

from scripts.lib import mood
from scripts.lib.footage import SHOT_TYPES


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class MoodPreset:
    """name + the anchor it is matched by + what it asks of the cut.

    `anchor` is None for BALANCED alone: the fallback must stay OUT of the
    nearest-neighbour search, or a mid-range vector would swallow every mood that
    sits between the four named presets."""
    name: str
    anchor: mood.MoodVector | None
    shot_mix: dict[str, float]        # a distribution over SHOT_TYPES, summing to 1.0
    asl: tuple[float, float]          # (lo, hi) seconds — reported, never enforced

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError("MoodPreset.name must be a non-empty string")
        if self.anchor is not None and not isinstance(self.anchor, mood.MoodVector):
            raise ValueError(f"MoodPreset.anchor must be a MoodVector or None (None = the "
                             f"fallback preset, excluded from matching), got {self.anchor!r}")
        if not isinstance(self.shot_mix, dict) or set(self.shot_mix) != set(SHOT_TYPES):
            raise ValueError(f"MoodPreset.shot_mix keys must be exactly {SHOT_TYPES}, got "
                             f"{sorted(self.shot_mix) if isinstance(self.shot_mix, dict) else self.shot_mix!r}")
        for k, v in self.shot_mix.items():
            if not (_num(v) and 0.0 <= v <= 1.0):
                raise ValueError(f"MoodPreset.shot_mix[{k!r}] must be a number in [0, 1], got {v!r}")
        total = sum(self.shot_mix.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"MoodPreset.shot_mix must sum to 1.0 (it is a distribution over "
                             f"{SHOT_TYPES}), got {total}")
        if not (isinstance(self.asl, (tuple, list)) and len(self.asl) == 2
                and all(_num(v) for v in self.asl)):
            raise ValueError(f"MoodPreset.asl must be a (lo, hi) pair of seconds, got {self.asl!r}")
        self.asl = (float(self.asl[0]), float(self.asl[1]))
        if not 0.0 < self.asl[0] < self.asl[1]:
            raise ValueError(f"MoodPreset.asl needs 0 < lo < hi seconds, got {self.asl!r}")


# Hand-tuned FIRST CUT. No footage has been cut against these numbers, so they live
# in this one place and are declared as guesses — the same honesty intake's
# CLUSTER_COS and MAX_CAST carry. Calibrate on the first real run that uses them.
PRESETS: tuple[MoodPreset, ...] = (
    MoodPreset("fun", mood.MoodVector(0.74, 0.84, 0.72),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (1.2, 2.5)),
    MoodPreset("epic", mood.MoodVector(0.80, 0.55, 0.55),
               {"close": 0.25, "medium": 0.35, "wide": 0.40}, (1.5, 3.5)),
    MoodPreset("moody", mood.MoodVector(0.48, 0.22, 0.42),
               {"close": 0.30, "medium": 0.35, "wide": 0.35}, (2.5, 5.0)),
    MoodPreset("nostalgic", mood.MoodVector(0.32, 0.45, 0.34),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (2.0, 4.0)),
)

# The no-match fallback. Its close share is deliberately above WANT_FLOOR: the
# autonomous path skips the optional reel-brief, and skipping a brief must not
# disable a quality gate (design §4.2). "A montage that stays one size reads
# amateur" is a grammar rule, not a mood-specific one.
BALANCED = MoodPreset("balanced", None,
                      {"close": 0.25, "medium": 0.40, "wide": 0.35}, (1.5, 4.0))


def resolve(mood_text: str | None) -> MoodPreset:
    """SPEC.mood -> the nearest named preset; empty or unrecognised -> BALANCED.

    Reuses mood.mood_target's anchor vocabulary rather than introducing a second
    lexicon, so 'fun and playful' resolves the same way here and in the music
    ranking. Because BALANCED is never a match target, `resolve(t).name ==
    "balanced"` is an exact test for 'nothing matched' — which is how the caller
    knows to log the fallback instead of applying it silently."""
    if not (isinstance(mood_text, str) and mood_text.strip()):
        return BALANCED
    target = mood.mood_target(mood_text)
    if target is None:
        return BALANCED
    return min(PRESETS, key=lambda p: mood.distance(p.anchor, target))


MIN_AVAIL = 3        # windows of a size below which a zero-use is NOT refusable — one
                     # stray misdetection must not block a reel (design §7)
WANT_FLOOR = 0.20    # shot_mix share at or above which the preset genuinely asks for a size


@dataclass
class VarietyReport:
    """What the cut did with the shot sizes the footage offered.

    Both censuses are measured in the SAME geometry (the project's default framing —
    design §6); comparing a delivered `used` against a source `available` would put
    the two sides of the comparison in different units. `gaps` survives a waiver on
    purpose: the waiver records a decision, it does not delete the finding."""
    preset: str
    available: dict[str, int]
    used: dict[str, int]
    asl: float
    asl_band: tuple[float, float]
    gaps: tuple[str, ...] = ()
    waiver: str | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.preset, str) and self.preset):
            raise ValueError("VarietyReport.preset must be the preset's name")
        for name in ("available", "used"):
            c = getattr(self, name)
            if not isinstance(c, dict) or set(c) != set(SHOT_TYPES):
                raise ValueError(f"VarietyReport.{name} must be a count per {SHOT_TYPES}, got {c!r}")
            for k, v in c.items():
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise ValueError(f"VarietyReport.{name}[{k!r}] must be an int >= 0, got {v!r}")
        if not (_num(self.asl) and self.asl >= 0):
            raise ValueError(f"VarietyReport.asl must be a number >= 0 seconds, got {self.asl!r}")
        if not (isinstance(self.asl_band, (tuple, list)) and len(self.asl_band) == 2
                and all(_num(v) for v in self.asl_band)):
            raise ValueError(f"VarietyReport.asl_band must be a (lo, hi) pair, got {self.asl_band!r}")
        self.asl_band = (float(self.asl_band[0]), float(self.asl_band[1]))
        self.gaps = tuple(self.gaps)
        bad = [g for g in self.gaps if g not in SHOT_TYPES]
        if bad:
            raise ValueError(f"VarietyReport.gaps must name shot types from {SHOT_TYPES}, got {bad}")
        if self.waiver is not None and not (isinstance(self.waiver, str) and self.waiver.strip()):
            raise ValueError(
                "VarietyReport.waiver must be a non-empty reason or null — a blank waiver is a "
                'bypass wearing the costume of a decision. State why the cut stays one size in '
                'selection.json\'s "variety_waiver"')

    @property
    def ok(self) -> bool:
        """A gap with a recorded reason passes; a gap without one does not."""
        return not self.gaps or bool(self.waiver)

    def to_dict(self) -> dict:
        return {"preset": self.preset, "available": dict(self.available),
                "used": dict(self.used), "asl": self.asl, "asl_band": list(self.asl_band),
                "gaps": list(self.gaps), "waiver": self.waiver}

    @classmethod
    def from_dict(cls, d: dict) -> "VarietyReport":
        if not isinstance(d, dict):
            raise ValueError(f"VarietyReport.from_dict: expected an object with preset/available/"
                             f"used fields, got {type(d).__name__} — re-run edit_plan build")
        return cls(preset=d.get("preset"), available=d.get("available"), used=d.get("used"),
                   asl=d.get("asl"), asl_band=d.get("asl_band"),
                   gaps=tuple(d.get("gaps") or ()), waiver=d.get("waiver"))


def evaluate(available: dict[str, int], used: dict[str, int], asl: float,
             preset: MoodPreset, waiver: str | None = None) -> VarietyReport:
    """Refuse only on a size the cut uses ZERO of, that the footage genuinely offers,
    and that the preset genuinely wants (design §7, decision 6). Deviation from the
    target fractions when the size IS used, and the realized ASL, are carried in the
    report for the human and never refused: the machine can prove 'the footage offered
    close-ups and you took none', not that some ideal mix was reachable."""
    gaps = tuple(s for s in SHOT_TYPES
                 if used.get(s, 0) == 0
                 and available.get(s, 0) >= MIN_AVAIL
                 and preset.shot_mix[s] >= WANT_FLOOR)
    return VarietyReport(preset=preset.name,
                         available={s: int(available.get(s, 0)) for s in SHOT_TYPES},
                         used={s: int(used.get(s, 0)) for s in SHOT_TYPES},
                         asl=float(asl), asl_band=preset.asl, gaps=gaps, waiver=waiver)
