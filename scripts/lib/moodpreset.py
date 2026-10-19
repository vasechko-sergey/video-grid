"""Mood presets (design docs/specs/2026-08-06-mood-preset-variety-design.md §4) —
the playbook §3 spine.

A mood is not one knob: it is a recipe across shot selection, pace, colour, music
and effects. Today it wires the SELECTION half (`shot_mix`, `asl` — edit_plan) and
the LOOK half (`look` — the reel's vignette and bookend fade, spent in deliver).
Colour and QC are named follow-ups in the 2026-08-06 design's §14, not fields
nothing reads.

Pure: stdlib + lib.mood + lib.footage's SHOT_TYPES vocabulary + lib.look's
LookSpec. No IO."""
from dataclasses import dataclass, field

from scripts.lib import mood
from scripts.lib.footage import SHOT_TYPES
from scripts.lib.look import LookSpec


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
    look: LookSpec = field(default_factory=LookSpec)   # the reel's finish (design 2026-08-13 §6)
    # (p5, p50, p95) luma-unit displacement of the reel's common tone target (design
    # 2026-08-17 §4). Hand-authored FIRST CUT at ~15-20 units — above the conductor's
    # own measured 6.5-11.5-unit delivery error (§3), which is the real floor and is
    # why a subtle table cannot work here. Spent by match_grade, never by edit_plan.
    tone_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)

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
        if not isinstance(self.look, LookSpec):
            raise ValueError(f"MoodPreset.look must be a LookSpec, got "
                             f"{type(self.look).__name__}")
        if not (isinstance(self.tone_bias, (tuple, list)) and len(self.tone_bias) == 3
                and all(_num(v) for v in self.tone_bias)):
            raise ValueError(f"MoodPreset.tone_bias must be three numbers — a (p5, p50, p95) "
                             f"luma displacement — got {self.tone_bias!r}")
        self.tone_bias = tuple(float(v) for v in self.tone_bias)


# Hand-tuned FIRST CUT. No footage has been cut against these numbers, so they live
# in this one place and are declared as guesses — the same honesty intake's
# CLUSTER_COS and MAX_CAST carry. Calibrate on the first real run that uses them.
# fade_in=0.0 on every row: the reel opens on picture, not black — the first frame
# is the hook a swiping viewer judges, and the second real run's `nostalgic` hook
# faded in from black under one shared fade (retro 2026-10-16 S6). The closing
# fade stays the preset's taste.
PRESETS: tuple[MoodPreset, ...] = (
    MoodPreset("fun", mood.MoodVector(0.74, 0.84, 0.72),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (1.2, 2.5),
               look=LookSpec(vignette=0.00, fade=0.3, fade_in=0.0),
               tone_bias=(10.0, 18.0, 8.0)),        # brighter and airier
    MoodPreset("epic", mood.MoodVector(0.80, 0.55, 0.55),
               {"close": 0.25, "medium": 0.35, "wide": 0.40}, (1.5, 3.5),
               look=LookSpec(vignette=0.30, fade=0.8, fade_in=0.0),
               tone_bias=(-16.0, 0.0, 16.0)),       # wider contrast, both ends
    MoodPreset("moody", mood.MoodVector(0.48, 0.22, 0.42),
               {"close": 0.30, "medium": 0.35, "wide": 0.35}, (2.5, 5.0),
               look=LookSpec(vignette=0.40, fade=1.0, fade_in=0.0),
               tone_bias=(-18.0, -16.0, -8.0)),     # darker and crushed, low key
    MoodPreset("nostalgic", mood.MoodVector(0.32, 0.45, 0.34),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (2.0, 4.0),
               look=LookSpec(vignette=0.25, fade=0.8, fade_in=0.0),
               tone_bias=(20.0, 0.0, -18.0)),       # faded: lifted blacks, pulled highs
)

# The no-match fallback. Its close share is deliberately above WANT_FLOOR (a skipped
# brief must not disable a quality GATE). Its look field, in contrast, is NEVER what
# reaches a reel: write_edit_plan passes look=None to build_edl whenever resolve()
# returns this preset (preset.name == "balanced" is the exact test), because a skipped
# brief must not silently apply a TASTE, and filling this field with any concrete
# value would be one — a real fade imposes a picture bookend nobody chose, and even
# fade=0.0 would reach build_reel as an AUTHORED zero and switch OFF mix's own 0.5s
# audio bookend (an authored {"vignette": 0, "fade": 0} does exactly that from
# selection.json — see LookSpec's docstring). EDL.look staying None is the only value
# that changes NOTHING about a brief-less run's output, so that is what write_edit_plan
# sends down. This field is LookSpec() only as defence in depth, for a caller that
# reads MoodPreset.look directly rather than going through write_edit_plan's check —
# corrected post-review 2026-08-13 (final-findings.md I-2); it used to read
# LookSpec(vignette=0.0, fade=0.5) and write_edit_plan applied it unconditionally,
# which put a real fade=t=in/fade=t=out pair on every autonomous reel's picture.
#
# tone_bias takes its zero default for exactly the reason spelled out above for look:
# a brief that was skipped or matched nothing must not have a TASTE imposed on it. Here
# the zero is safe in a way LookSpec()'s is not — match_grade tests preset.name against
# "balanced" and never reads this field for the fallback, and a zero displacement is the
# identity through matchgrade.biased_target either way (design 2026-08-17 §1).
BALANCED = MoodPreset("balanced", None,
                      {"close": 0.25, "medium": 0.40, "wide": 0.35}, (1.5, 4.0),
                      look=LookSpec())


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
    purpose: the waiver records a decision, it does not delete the finding. `unmeasured`
    is the census's own blind spot, not a fourth size: it counts how many of the SAME
    windows were measured against a detector that found nothing."""
    preset: str
    available: dict[str, int]
    used: dict[str, int]
    asl: float
    asl_band: tuple[float, float]
    gaps: tuple[str, ...] = ()
    waiver: str | None = None
    # How many of the windows counted in `available` carried no detected subject at
    # all. They ARE in the census, tagged `wide`, and correctly so: shot size is the
    # subject's area fraction and nothing fills the frame (design 2026-09-10 §0.5).
    # The count exists because `available` is otherwise read as a description of the
    # footage — and on a shoot with no people in it, every window lands in `wide` and
    # the census states that the footage offers no close-ups about footage that may be
    # entirely close-ups (§0.2). A subset of the census, never a fourth bucket.
    unmeasured: int = 0

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
        if isinstance(self.unmeasured, bool) or not isinstance(self.unmeasured, int) \
                or self.unmeasured < 0:
            raise ValueError(
                f"VarietyReport.unmeasured must be an int >= 0 (windows in `available` whose "
                f"subject was never detected), got {self.unmeasured!r} — re-run `edit_plan "
                f"build` to regenerate EDL.json")
        total = sum(self.available.values())
        if self.unmeasured > total:
            raise ValueError(
                f"VarietyReport.unmeasured {self.unmeasured} exceeds the {total} windows in "
                f"`available` — the unmeasured windows are a SUBSET of the census (counted in "
                f"it as `wide`), not a fourth bucket beside it. Re-run `edit_plan build` to "
                f"regenerate EDL.json")

    @property
    def ok(self) -> bool:
        """A gap with a recorded reason passes; a gap without one does not."""
        return not self.gaps or bool(self.waiver)

    def to_dict(self) -> dict:
        return {"preset": self.preset, "available": dict(self.available),
                "used": dict(self.used), "asl": self.asl, "asl_band": list(self.asl_band),
                "gaps": list(self.gaps), "waiver": self.waiver, "unmeasured": self.unmeasured}

    @classmethod
    def from_dict(cls, d: dict) -> "VarietyReport":
        if not isinstance(d, dict):
            raise ValueError(f"VarietyReport.from_dict: expected an object with preset/available/"
                             f"used fields, got {type(d).__name__} — re-run edit_plan build")
        return cls(preset=d.get("preset"), available=d.get("available"), used=d.get("used"),
                   asl=d.get("asl"), asl_band=d.get("asl_band"),
                   gaps=tuple(d.get("gaps") or ()), waiver=d.get("waiver"),
                   unmeasured=d.get("unmeasured") or 0)


def evaluate(available: dict[str, int], used: dict[str, int], asl: float,
             preset: MoodPreset, waiver: str | None = None,
             unmeasured: int = 0) -> VarietyReport:
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
                         asl=float(asl), asl_band=preset.asl, gaps=gaps, waiver=waiver,
                         unmeasured=unmeasured)


def reconcile_band(preset: MoodPreset, carved: tuple | None) -> str | None:
    """The preset's asl band against the band the footage was CARVED with.
    None = compatible, or uncheckable; a string = the refusal's problem text.

    Only the LOWER bound is checkable, and that asymmetry is the whole check
    (design 2026-09-03 §4). edit_plan joins adjacent windows through its span
    merge, so a preset ceiling above the carved ceiling is always reachable —
    the reference run shipped a 5.80s episode against a 4.0s carve ceiling, and
    refusing that would be refusing a cut that works. Nothing SPLITS a window, so
    a preset FLOOR below the carved floor asks for a shot length that a normal cut
    has nothing to draw from (final-findings.md M-1: the one exception is a whole
    clip that started shorter than the floor to begin with, kept as a single
    undersized window rather than dropped or padded — carve_windows' short-clip
    fallback, `tests/lib/test_intake.py`'s `test_carve_short_clip_yields_one_window` —
    which is not a source a selection can rely on to supply a mood's worth of shots).

    `carved` is None on a FOOTAGE.json written before 2026-09-03. The check
    cannot run; the caller reports not-checked rather than a pass.
    """
    if carved is None:
        return None
    if preset.asl[0] >= carved[0]:
        return None
    return (f"preset {preset.name!r} wants shots from {preset.asl[0]:.1f}s, but the "
            f"footage was carved with a {carved[0]:.1f}s floor, so nothing splits a "
            f"window to manufacture one shorter than {carved[0]:.1f}s on demand (the "
            f"one exception is a whole clip that was itself shorter than the floor, "
            f"kept as a single undersized window rather than dropped — not a source "
            f"a selection can rely on). Re-scan with `--win-min {preset.asl[0]:g}`, "
            f"choose a mood whose band starts at or above {carved[0]:.1f}s, or drop "
            f"--spec to run without a preset. (The preset's CEILING is not checked: "
            f"span merge joins adjacent windows, so a longer shot is always "
            f"reachable.)")
