"""The match-grade conductor's pure core (design 2026-07-30, montage §10). Given every
episode's measured (p5,p50,p95) luma profile, compute ONE common reel target (the
per-anchor median) and decide, per episode, whether a tone pair is worth authoring.
No ffmpeg, no numpy — the driver (match_grade.py) measures; this only decides. Mirrors
color.percentiles / pacing / offset: pure decision here, IO in the driver."""
import statistics
from dataclasses import dataclass

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

    A zero bias returns the target unchanged with k == 1.0 — the off switch a run without
    --spec takes, identical to the pre-2026-08-17 conductor."""
    if not any(bias):
        return (tuple(float(v) for v in target), 1.0)
    k = 1.0
    for a, d in zip(target, bias):
        if d and not (0.0 <= a + d <= 255.0):
            limit = (255.0 - a) / d if d > 0 else (0.0 - a) / d
            k = min(k, max(limit, 0.0))
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
