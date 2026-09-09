"""The match-grade conductor's pure core (design 2026-07-30, montage §10). Given every
episode's measured (p5,p50,p95) luma profile, compute ONE common reel target (the
per-anchor median) and decide, per episode, whether a tone pair is worth authoring.
No ffmpeg, no numpy — the driver (match_grade.py) measures; this only decides. Mirrors
color.percentiles / pacing / offset: pure decision here, IO in the driver."""
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import color

Profile = tuple[float, float, float]

MATCH_EPS = 4.0        # luma units (0-255). An episode whose every anchor is within this
                       # of the target gets NO tone pair: below color.TONE_MIN_GAP (6) the
                       # mapping is a near-identity the eye cannot see, so authoring it would
                       # spend the reframe byte-identical fast path for nothing.


def common_target(profiles: list[Profile]) -> Profile:
    """The reel's common tone target: the per-anchor MEDIAN across episodes, gap-repaired
    so color.tone_arg accepts it. Median (not mean) so one blown-out or crushed episode
    cannot drag the target off the group it should represent. Every episode votes — even
    a flat clip that cannot itself receive a tone (valid_src) is a real exposure sample.
    Because each row is ordered (p5<=p50<=p95), the column medians are ordered too, so the
    target is always non-decreasing; only narrow gaps need repair, never an inversion."""
    if not profiles:
        raise ValueError("common_target: no profiles — measure at least one episode")
    t = tuple(statistics.median(p[k] for p in profiles) for k in range(3))
    return _repair_gaps(t)


def _repair_gaps(t: Profile, gap: float = color.TONE_MIN_GAP) -> Profile:
    """Push a target's anchors to >= `gap` around the middle anchor, then REFUSE (fail-loud,
    not clamp) if that widening lands outside 0-255. The target is SYNTHETIC — no episode
    must match it — so widening a too-narrow gap is honest, unlike doing so to a measured
    source. A reel whose median carries no usable range (anchors collapsed at an edge)
    cannot be spread inside 0-255 and is REFUSED, not silently flattened: there is nothing
    to match-grade."""
    p5, p50, p95 = t
    p5, p95 = min(p5, p50 - gap), max(p95, p50 + gap)
    # p50-p5 >= gap and p95-p50 >= gap hold by construction of the min/max above — the only
    # way this can still fail is the widened anchor falling outside 0-255.
    if not (0 <= p5 and p95 <= 255):
        raise ValueError(
            f"common_target: the reel's median profile {t} carries no usable tonal range "
            f"(cannot spread to {gap}-unit gaps inside 0-255) — match-grade has nothing to "
            "normalize; check the footage is not all flat or black")
    return (p5, p50, p95)


MOOD_FLOOR = 10.0      # luma units below which a displacement cannot be seen. Measured
                       # (design 2026-08-17 §3): rendering an episode through the curve the
                       # conductor authors lands 6.5-11.5 units from the target it asked
                       # for, so a displacement smaller than that disappears into the
                       # conductor's own error. Not a taste threshold — a resolution one.


def biased_target(target: Profile, bias: tuple[float, float, float]) -> tuple[Profile, float]:
    """Displace the common target by a mood's `bias`, scaled to stay inside 0-255.

    Returns (displaced target, k) where k in [0, 1] is how much of the asked displacement
    survived. SCALING THE WHOLE VECTOR is the contract, not clamping the offending anchor:
    `epic` is "deep blacks AND bright highs", and clamping only its highlight lift would
    silently ship "crush the blacks", which is a different mood (design §5). Scaling keeps
    the direction and loses magnitude, and k lets the caller say so.

    Measured across eight plausible reel medians: k == 1 on five, and scaling fires only on
    bright targets and only for the two presets that push p95 up — at a median of
    (110, 170, 250), fun keeps 0.62 and epic 0.31 of its vector. moody and nostalgic never
    scale, because both pull inward.

    TWO bounds bind, and the second was missed by this design's first cut: the 0-255
    ceiling AND color.TONE_MIN_GAP between neighbouring anchors. On a low-contrast reel
    median, nostalgic's +20 on p5 pushes past p50; _repair_gaps would quietly clamp it
    back and k would still report 1.00, losing 12-16 luma units while claiming the bias
    survived whole. Scaling against both means _repair_gaps has nothing left to fix here
    and k speaks for the whole displacement.

    A zero bias returns the target unchanged with k == 1.0 — the off switch a run without
    --spec takes, identical to the pre-2026-08-17 conductor."""
    if not any(bias):
        return (tuple(float(v) for v in target), 1.0)
    k = 1.0
    for a, d in zip(target, bias):                       # the 0-255 ceiling
        if d and not (0.0 <= a + d <= 255.0):
            limit = (255.0 - a) / d if d > 0 else (0.0 - a) / d
            k = min(k, max(limit, 0.0))
    for (a0, d0), (a1, d1) in zip(zip(target, bias), list(zip(target, bias))[1:]):
        delta = d1 - d0                                  # how the pair's gap changes per unit k
        if delta < 0:                                    # only a NARROWING pair can bind
            k = min(k, max(((a1 - a0) - color.TONE_MIN_GAP) / -delta, 0.0))
    return _repair_gaps(tuple(a + d * k for a, d in zip(target, bias))), k


def bias_ineffective(bias: tuple[float, float, float], k: float,
                     floor: float = MOOD_FLOOR) -> bool:
    """True when scaling has taken the bias's LARGEST component under the floor — the grade
    cannot show it, so the report must (design §5). Judged on the largest component because
    a mood's smaller axes ride along with its dominant one."""
    return bool(any(bias)) and max(abs(d) for d in bias) * k < floor


def valid_src(profile: Profile, gap: float = color.TONE_MIN_GAP) -> bool:
    """Can this measured profile be a tone_src? color.tone_arg needs strictly increasing
    anchors >= `gap` apart. A low-contrast clip cannot, and its contrast cannot be invented
    — so the conductor SKIPS it (flat-source) rather than fabricate a source."""
    return all(b - a >= gap for a, b in zip(profile, profile[1:]))


def needs_tone(profile: Profile, target: Profile, eps: float = MATCH_EPS) -> bool:
    """True iff the max per-anchor distance to `target` exceeds `eps` — far enough to be
    worth a curve. Within eps: leave the episode byte-identical."""
    return max(abs(a - b) for a, b in zip(profile, target)) > eps


@dataclass(frozen=True)
class ToneDecision:
    """Per-episode planning outcome — the measured profile (always, for MATCH.md), what to
    author, and (when not) why. author -> tone_src/tone_dst carry the pair; within-eps/flat
    -> None (the driver CLEARS a stale pair on a --force re-conduct); hand-authored -> the
    driver leaves the episode as-is. `measured` is carried so the report and the driver need
    no second measure pass."""
    index: int
    action: str                    # "author" | "skip"
    reason: str                    # "authored" | "within-eps" | "flat-source" | "hand-authored"
    measured: Profile
    tone_src: Profile | None = None
    tone_dst: Profile | None = None

    def to_dict(self) -> dict:
        return {"index": self.index, "action": self.action, "reason": self.reason,
                "measured": list(self.measured),
                "tone_src": None if self.tone_src is None else list(self.tone_src),
                "tone_dst": None if self.tone_dst is None else list(self.tone_dst)}

    @classmethod
    def from_dict(cls, d: dict) -> "ToneDecision":
        if not isinstance(d, dict):
            raise ValueError(f"ToneDecision.from_dict: expected an object, got "
                             f"{type(d).__name__}")
        return cls(index=int(d["index"]), action=str(d["action"]), reason=str(d["reason"]),
                   measured=_triple(d.get("measured"), "ToneDecision.measured"),
                   tone_src=_opt_triple(d.get("tone_src"), "ToneDecision.tone_src"),
                   tone_dst=_opt_triple(d.get("tone_dst"), "ToneDecision.tone_dst"))


def plan(profiles: list[Profile], has_tone: list[bool], target: Profile,
         *, eps: float = MATCH_EPS, force: bool = False) -> list[ToneDecision]:
    """Decide each episode's tone pair against `target`. Guard ORDER is the contract:
    a hand-authored pair is respected first (unless `force`), then a flat source is skipped
    (cannot be a valid src), then a within-eps episode is left untouched, else author (its
    own profile -> the common target). Every decision carries its measured profile."""
    if len(profiles) != len(has_tone):
        raise ValueError(f"plan: {len(profiles)} profiles but {len(has_tone)} has_tone flags "
                         "— they must be per-episode parallel lists")
    out = []
    for i, (p, ht) in enumerate(zip(profiles, has_tone)):
        if ht and not force:
            out.append(ToneDecision(i, "skip", "hand-authored", measured=p))
        elif not valid_src(p):
            out.append(ToneDecision(i, "skip", "flat-source", measured=p))
        elif not needs_tone(p, target, eps):
            out.append(ToneDecision(i, "skip", "within-eps", measured=p))
        else:
            out.append(ToneDecision(i, "author", "authored", measured=p, tone_src=p, tone_dst=target))
    return out


def _triple(v, what: str) -> Profile:
    """A JSON list of three numbers back into a Profile, refusing anything else by name."""
    if not (isinstance(v, (list, tuple)) and len(v) == 3
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
        raise ValueError(f"{what} must be three numbers (p5, p50, p95), got {v!r}")
    return (float(v[0]), float(v[1]), float(v[2]))


def _opt_triple(v, what: str) -> Profile | None:
    return None if v is None else _triple(v, what)


@dataclass(frozen=True)
class MatchReport:
    """MATCH.json — the conductor's decisions in machine-readable form (design §2).

    MATCH.md said "8/8 episodes authored a tone pair" while the EDL written an hour
    later carried five, and nothing could check the claim because the claim was prose
    (design §0.1). This is the same content MATCH.md renders, in the form a reader can
    compare against the EDL — every other stage in the conveyor writes X.json + X.md,
    and match-grade was one of only two that did not.

    `edl` is the path this conductor wrote back into, stored exactly as write_match
    received it — the same verbatim-not-resolved rule ReelGeometry.edl follows.
    """
    target: Profile
    eps: float
    decisions: tuple[ToneDecision, ...]
    edl: str
    bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bias_source: str = ""
    bias_scale: float = 1.0
    mood: str | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.edl, str) and self.edl):
            raise ValueError("MatchReport.edl is empty — it names the EDL this report's "
                             "decisions were written into, and the freshness check has "
                             "nothing to compare against without it")
        if not all(isinstance(d, ToneDecision) for d in self.decisions):
            raise ValueError("MatchReport.decisions must be ToneDecision objects — build "
                             "them with matchgrade.plan()")

    def to_dict(self) -> dict:
        return {"target": list(self.target), "eps": self.eps, "edl": self.edl,
                "bias": list(self.bias), "bias_source": self.bias_source,
                "bias_scale": self.bias_scale, "mood": self.mood,
                "decisions": [d.to_dict() for d in self.decisions]}

    @classmethod
    def from_dict(cls, d: dict) -> "MatchReport":
        if not isinstance(d, dict):
            raise ValueError(f"MatchReport.from_dict: expected a MATCH.json object, got "
                             f"{type(d).__name__} — produce it with `match_grade build`")
        raw = d.get("decisions")
        if not isinstance(raw, list):
            raise ValueError("MatchReport.decisions must be a JSON list — re-run match-grade")
        return cls(target=_triple(d.get("target"), "MatchReport.target"),
                   eps=float(d.get("eps", MATCH_EPS)),
                   decisions=tuple(ToneDecision.from_dict(x) for x in raw),
                   edl=d.get("edl") or "",
                   bias=_triple(d.get("bias") or [0.0, 0.0, 0.0], "MatchReport.bias"),
                   bias_source=d.get("bias_source") or "",
                   bias_scale=float(d.get("bias_scale", 1.0)),
                   mood=d.get("mood"))

    @classmethod
    def from_json(cls, path: str | Path) -> "MatchReport":
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run `match_grade build`") from e

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def tone_drift(decisions: Sequence[ToneDecision],
               pairs: Sequence[tuple[Profile | None, Profile | None]]) -> list[str]:
    """Which of this report's authored pairs the EDL no longer carries — [] when the
    report still describes the EDL (design §2).

    The instrument is the PAIRS, not a digest of the EDL, and that is deliberate:
    match_grade rewrites the EDL itself and `edit_plan build --pacing` legitimately
    rewrites it again afterwards, so a whole-file digest would fire on the sanctioned
    rewrite exactly as loudly as on the wipe — and a gate that cries wolf gets its
    ceiling raised (design §1, the R2.4 mechanism measured on color_delta_max).

    A `skip` decision asserts nothing about that episode's pair, so a pair appearing
    where one was skipped is not drift. Comparison is exact equality: both sides are
    the same floats round-tripped through json, and a re-conducted episode rewrites
    this report too.

    `pairs` is per-episode (tone_src, tone_dst) read from the EDL as it is NOW —
    supplied by the caller as plain data so this module keeps its no-IO contract and
    montage's inspector need not import the EDL contract (whose from_json refuses a
    tampered file, which must not take the whole status report down with it).
    """
    if len(decisions) != len(pairs):
        return [f"this report describes {len(decisions)} episodes and the EDL now has "
                f"{len(pairs)} — the cut changed"]
    out: list[str] = []
    for d, (src, dst) in zip(decisions, pairs):
        if d.action != "author":
            continue
        if src is None and dst is None:
            out.append(f"episode {d.index} was authored a tone pair, and the EDL now "
                       f"carries none")
        elif (src, dst) != (d.tone_src, d.tone_dst):
            out.append(f"episode {d.index}'s tone pair in the EDL is not the one this "
                       f"report authored")
    return out
