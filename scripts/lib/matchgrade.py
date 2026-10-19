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
    no second measure pass.

    `regions` is one row per tone anchor: the author's name for the region, the
    kind declared, the kind actually used, that region's frame fraction, the
    value taken, and the fallback if one fired (design 2026-09-15 §4). Empty on
    a report written before that slice, and empty is not "no fallback fired" —
    it is "this report predates the record".

    Frozen buys equality and a stable repr, not hash: `regions` holds plain
    dicts (JSON's own shape, and what MATCH.json/_report_md's `r["field"]`
    access both want), so `hash()` on a decision that carries rows raises
    TypeError. Nothing hashes a ToneDecision today (review finding 7) — kept
    this way rather than flattened into a hashable nested-tuple shape, which
    would need its own dict<->tuple conversion at both `to_dict` and every
    `_report_md`/MATCH.json reader and buy nothing no caller needs."""
    index: int
    action: str                    # "author" | "skip"
    reason: str                    # "authored" | "within-eps" | "flat-source" | "hand-authored"
    measured: Profile
    tone_src: Profile | None = None
    tone_dst: Profile | None = None
    regions: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"index": self.index, "action": self.action, "reason": self.reason,
                "measured": list(self.measured),
                "tone_src": None if self.tone_src is None else list(self.tone_src),
                "tone_dst": None if self.tone_dst is None else list(self.tone_dst),
                "regions": [dict(r) for r in self.regions]}

    @classmethod
    def from_dict(cls, d: dict) -> "ToneDecision":
        if not isinstance(d, dict):
            raise ValueError(f"ToneDecision.from_dict: expected an object, got "
                             f"{type(d).__name__}")
        return cls(index=_required_int(d.get("index"), "ToneDecision.index"),
                   action=_required_str(d.get("action"), "ToneDecision.action"),
                   reason=_required_str(d.get("reason"), "ToneDecision.reason"),
                   measured=_triple(d.get("measured"), "ToneDecision.measured"),
                   tone_src=_opt_triple(d.get("tone_src"), "ToneDecision.tone_src"),
                   tone_dst=_opt_triple(d.get("tone_dst"), "ToneDecision.tone_dst"),
                   regions=_regions_field(d.get("regions"), "ToneDecision.regions"))


def plan(profiles: list[Profile], has_tone: list[bool], target: Profile,
         *, eps: float = MATCH_EPS, force: bool = False,
         regions: list[tuple[dict, ...]] | None = None) -> list[ToneDecision]:
    """Decide each episode's tone pair against `target`. Guard ORDER is the contract:
    a hand-authored pair is respected first (unless `force`), then a flat source is skipped
    (cannot be a valid src), then a within-eps episode is left untouched, else author (its
    own profile -> the common target). Every decision carries its measured profile.

    `regions` is the driver's per-episode region-row tuple (design 2026-09-15 §4) —
    optional and keyword-only so every caller and test double that predates this
    slice keeps landing on the same empty-tuple default every decision already
    carried, and parallel to `profiles` exactly as `has_tone` already is."""
    if len(profiles) != len(has_tone):
        raise ValueError(f"plan: {len(profiles)} profiles but {len(has_tone)} has_tone flags "
                         "— they must be per-episode parallel lists")
    if regions is not None and len(regions) != len(profiles):
        raise ValueError(f"plan: {len(profiles)} profiles but {len(regions)} region rows "
                         "— they must be per-episode parallel lists")
    out = []
    for i, (p, ht) in enumerate(zip(profiles, has_tone)):
        rows = regions[i] if regions is not None else ()
        if ht and not force:
            out.append(ToneDecision(i, "skip", "hand-authored", measured=p, regions=rows))
        elif not valid_src(p):
            out.append(ToneDecision(i, "skip", "flat-source", measured=p, regions=rows))
        elif not needs_tone(p, target, eps):
            out.append(ToneDecision(i, "skip", "within-eps", measured=p, regions=rows))
        else:
            out.append(ToneDecision(i, "author", "authored", measured=p, tone_src=p,
                                    tone_dst=target, regions=rows))
    return out


TOE_LIFT_WARN = 15.0   # luma units. A first cut, not a measurement: the one case on
                       # record is the second real run's backlit hook, lifted p5 38 → 60
                       # (+22) — a silhouette turned grey, caught only because the agent
                       # ran `probe grade` (retro 2026-10-16 S17). Below the bar a lifted
                       # toe is an ordinary exposure match.


def toe_lifts(pairs: list[tuple[Profile | None, Profile | None]], *,
              offset: float = 0.0) -> list[tuple[int, float, float]]:
    """(index, p5 from, p5 to) for every episode whose tone pair raises the shadows by
    more than TOE_LIFT_WARN beyond `offset`. The conductor cannot tell an underexposed
    shot from one dark on purpose — both read as a low p5 — so it does not refuse; it
    says so, and pinning the episode stays the author's call.

    `pairs` is (tone_src, tone_dst) per episode, as the EDL will ship them — not the
    decisions, so a re-run that leaves last run's pairs alone as hand-authored still
    names them (review finding 3). `offset` is the mood's own displacement of the toe
    (bias p5 x scale): a brief that asks for lifted blacks lifts every episode on
    purpose, and counting it would name most of a `nostalgic` reel (review finding 2)."""
    return [(i, src[0], dst[0]) for i, (src, dst) in enumerate(pairs)
            if src is not None and dst is not None
            and dst[0] - offset - src[0] > TOE_LIFT_WARN]


def _triple(v, what: str) -> Profile:
    """A JSON list of three numbers back into a Profile, refusing anything else by name."""
    if not (isinstance(v, (list, tuple)) and len(v) == 3
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
        raise ValueError(f"{what} must be three numbers (p5, p50, p95), got {v!r}")
    return (float(v[0]), float(v[1]), float(v[2]))


def _opt_triple(v, what: str) -> Profile | None:
    return None if v is None else _triple(v, what)


def _regions_field(v, what: str) -> tuple[dict, ...]:
    """ToneDecision.regions from JSON: absent/null means "predates this record"
    (empty tuple, matching `to_dict`'s own empty-list-on-no-rows shape) — anything
    else must be a list of row objects, refused by name with a remedy exactly like
    every other field on this class (review finding 4: this was the one field that
    skipped that contract, so `"regions": 5` raised a bare TypeError montage's own
    `except (ValueError, OSError)` does not catch, and `"regions": "wetsuit"` would
    have silently become a 7-tuple of one-character strings via a bare `tuple(v)`).

    Each row is copied (`dict(r)`), never aliased: `to_dict` already copies on the
    way out ([dict(r) for r in self.regions]), and handing a frozen ToneDecision a
    reference to the CALLER's own dict is the same aliasing bug from the other
    side — a caller that later mutates the dict it passed in would otherwise mutate
    a value this "immutable" object already returned."""
    if v is None:
        return ()
    if not isinstance(v, list):
        raise ValueError(f"{what} must be a list of objects, got {type(v).__name__} "
                         f"({v!r}) — re-run match-grade to regenerate it")
    for i, r in enumerate(v):
        if not isinstance(r, dict):
            raise ValueError(f"{what}[{i}] must be an object, got {type(r).__name__} "
                             f"({r!r}) — re-run match-grade to regenerate it")
    return tuple(dict(r) for r in v)


def _required_int(v, what: str) -> int:
    """A required integer field, refusing a missing/null/wrong-type value by name — the
    is-None-safe counterpart to `_triple` for a scalar that carries no default, so a
    missing key surfaces the same ValueError-with-remedy as a malformed one instead of
    a bare KeyError out of `d["..."]`."""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{what} is required and must be an integer, got {v!r} — "
                         "re-run match-grade to regenerate it")
    return int(v)


def _required_str(v, what: str) -> str:
    """A required non-empty string field, refusing a missing/null/wrong-type value by
    name — the is-None-safe counterpart to `_triple` for a scalar that carries no
    default, so a missing key surfaces the same ValueError-with-remedy as a malformed
    one instead of a bare KeyError out of `d["..."]`."""
    if not (isinstance(v, str) and v):
        raise ValueError(f"{what} is required and must be a non-empty string, got "
                         f"{v!r} — re-run match-grade to regenerate it")
    return v


def _num_or_default(d: dict, key: str, what: str, default: float) -> float:
    """A number field that defaults only when `key` is genuinely ABSENT from `d` — a
    present-but-`null` value is validated (and refused) like any other malformed field,
    never silently swapped for `default`. `d.get(key, default)` cannot make that
    distinction: when the JSON value is `null` the key IS present, so the built-in
    default never fires and `float(None)` raises a bare TypeError instead of the
    ValueError-with-remedy every other malformed field in this module raises."""
    if key not in d:
        return default
    v = d[key]
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{what} must be a number, got {v!r} — re-run match-grade")
    return float(v)


#: What the conductor could learn about the author's REGIONS.json (design
#: 2026-09-15 §2.1). THREE states, not two, and the third is the point:
#: "graded against the whole crop because you asked for nothing" (`none`) and
#: "graded against the whole crop because I could not look" (`unreachable`) are
#: different claims about the same pixels, and the pixels cannot tell them apart.
#:
#: Closed and enforced by MatchReport.__post_init__. It lives here rather than in
#: lib/regions.py because this is the module that has to VALIDATE it — regions.py
#: imports numpy, and this one's contract is that it does not.
REGIONS_STATES = ("found", "none", "unreachable")


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

    `regions` is which of REGIONS_STATES applied to the author's declaration, and
    `regions_at` its detail — the declaration's path (`found`), the REGIONS.json
    that was looked for and is not there (`none`), or why it could not be looked
    for at all (`unreachable`). Both default to `""`, and an EMPTY `regions` means
    this report PREDATES the field — never "no declaration was found", which is
    the `none` state and says so by name. A claim that survives only as prose in
    MATCH.md cannot be checked, which is the whole reason MATCH.json exists.
    """
    target: Profile
    eps: float
    decisions: tuple[ToneDecision, ...]
    edl: str
    bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bias_source: str = ""
    bias_scale: float = 1.0
    mood: str | None = None
    regions: str = ""
    regions_at: str = ""

    def __post_init__(self) -> None:
        if not (isinstance(self.edl, str) and self.edl):
            raise ValueError("MatchReport.edl is empty — it names the EDL this report's "
                             "decisions were written into, and the freshness check has "
                             "nothing to compare against without it")
        if not all(isinstance(d, ToneDecision) for d in self.decisions):
            raise ValueError("MatchReport.decisions must be ToneDecision objects — build "
                             "them with matchgrade.plan()")
        if self.regions and self.regions not in REGIONS_STATES:
            raise ValueError(
                f"MatchReport.regions {self.regions!r} unknown — expected one of "
                f"{REGIONS_STATES}, or '' for a report written before this field existed. "
                f"A state outside the set would be read as a fourth kind of answer nobody "
                f"can act on")

    def to_dict(self) -> dict:
        return {"target": list(self.target), "eps": self.eps, "edl": self.edl,
                "bias": list(self.bias), "bias_source": self.bias_source,
                "bias_scale": self.bias_scale, "mood": self.mood,
                "regions": self.regions, "regions_at": self.regions_at,
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
                   eps=_num_or_default(d, "eps", "MatchReport.eps", MATCH_EPS),
                   decisions=tuple(ToneDecision.from_dict(x) for x in raw),
                   edl=d.get("edl") or "",
                   bias=_triple(d.get("bias") or [0.0, 0.0, 0.0], "MatchReport.bias"),
                   bias_source=d.get("bias_source") or "",
                   bias_scale=_num_or_default(d, "bias_scale", "MatchReport.bias_scale", 1.0),
                   mood=d.get("mood"),
                   # `or ""` so a null or a missing key both land on "predates the
                   # field" — the one reading that is true of every report written
                   # before design 2026-09-15's review round.
                   regions=d.get("regions") or "",
                   regions_at=d.get("regions_at") or "")

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
