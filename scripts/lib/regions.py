"""Named regions (design docs/specs/2026-09-15-named-regions-design.md).

An anchor is a measurement and a measurement needs a subject. Until this module
all three tone anchors shared one — every pixel of the crop — and design §0.2
shows what that actually resolved to: whichever region was largest, which on the
only real run is the water. Naming regions does not introduce a bias into a
neutral measurement; it replaces an unnamed one.

The vocabulary is CLOSED in both directions and an unknown value is a load-time
refusal, the same rule constraints.py states for editorial rules: nothing lives
in an author's file that the machine does not check. `name` is the exception and
deliberately so — it is the author's noun, carried into the report and never
interpreted. Calling the subject region `wetsuit` is a claim about the footage
that nothing here verifies (design §6).

Pure: dataclasses and numpy arrays in, readings out. The only IO is from_json.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scripts.lib import color

#: The three tone anchors, in profile order: toe is p5, mid is p50, shoulder is
#: p95. The anchor names the STATISTIC and a declaration only chooses the pixel
#: set (design §2.3) — which is why color.tone_arg, _segments, TONE_MIN_GAP and
#: every matchgrade decision function are untouched by this slice: three numbers
#: still go in.
#:
#: The percentiles themselves are NOT a table here. color.percentiles owns them,
#: and a {"toe": 5, ...} dict beside it would be consumed by nothing — assemble
#: indexes a profile tuple by this sequence's own order — so it would read as a
#: knob while being inert, which is the gradedamage.ENTROPY_BINS mistake
#: (design 2026-08-31, fix round 1) wearing a different name.
ANCHORS = ("toe", "mid", "shoulder")

KINDS = ("subject", "background", "crop")

_FIELDS = ("anchor", "name", "of")


@dataclass(frozen=True)
class AnchorRegion:
    """One anchor and the region the author wants it measured over."""
    anchor: str
    name: str
    of: str

    def __post_init__(self) -> None:
        if self.anchor not in ANCHORS:
            raise ValueError(
                f"REGIONS.json anchor {self.anchor!r} unknown — expected one of "
                f"{ANCHORS}. The anchor names the statistic (toe=p5, mid=p50, "
                f"shoulder=p95) and the set is closed")
        if self.of not in KINDS:
            raise ValueError(
                f"REGIONS.json region {self.of!r} unknown — expected one of {KINDS}. "
                f"A kind outside this vocabulary cannot be measured, so it is refused "
                f"rather than stored and silently ignored")
        if not (isinstance(self.name, str) and self.name.strip()):
            raise ValueError(
                f"REGIONS.json anchor {self.anchor!r} needs a non-empty 'name' — it is "
                f"your noun for this region ('wetsuit', 'water') and it is what the "
                f"report prints. The code never interprets it")

    def to_dict(self) -> dict:
        return {"anchor": self.anchor, "name": self.name, "of": self.of}


@dataclass(frozen=True)
class Regions:
    """The project's region declaration, in the order it was written."""
    anchors: tuple[AnchorRegion, ...] = ()

    def __post_init__(self) -> None:
        seen: set = set()
        for a in self.anchors:
            if not isinstance(a, AnchorRegion):
                raise ValueError("Regions.anchors must hold AnchorRegion objects")
            if a.anchor in seen:
                raise ValueError(
                    f"REGIONS.json declares the {a.anchor!r} anchor more than once — two "
                    f"regions cannot both supply one anchor. Keep the one that holds")
            seen.add(a.anchor)

    def declared(self, anchor: str) -> AnchorRegion:
        """The declaration for `anchor`, or the implicit crop row.

        An undeclared anchor is the crop, which is what every anchor was before
        this module existed — so a partial declaration is a real answer, not a
        half-configured state."""
        if anchor not in ANCHORS:
            raise ValueError(f"unknown anchor {anchor!r} — one of {ANCHORS}")
        for a in self.anchors:
            if a.anchor == anchor:
                return a
        return AnchorRegion(anchor, "crop", "crop")

    def to_dict(self) -> dict:
        return {"anchors": [a.to_dict() for a in self.anchors]}

    @classmethod
    def from_dict(cls, d: dict) -> "Regions":
        # The top level is checked FIRST, before any d.get: this boundary reads
        # author-written JSON and owes its callers ONE documented exception type.
        if not isinstance(d, dict):
            raise ValueError(f"REGIONS.json must be an object with an 'anchors' list, "
                             f"got {type(d).__name__}")
        raw = d.get("anchors")
        if not isinstance(raw, list):
            raise ValueError("REGIONS.json must hold an 'anchors' list (use [] to "
                             "declare nothing, which is the same as no file)")
        out = []
        for k, a in enumerate(raw):
            if not isinstance(a, dict):
                raise ValueError(f"REGIONS.json anchors[{k}] must be an object, got "
                                 f"{type(a).__name__}")
            extra = set(a) - set(_FIELDS)
            if extra:
                raise ValueError(
                    f"REGIONS.json anchors[{k}] has unknown field(s) "
                    f"{sorted(extra)} — an anchor carries exactly {list(_FIELDS)}. An "
                    f"extra field is refused, not ignored: it reads as a rule that is "
                    f"not the one being enforced")
            missing = [f for f in _FIELDS if f not in a]
            if missing:
                raise ValueError(f"REGIONS.json anchors[{k}] is missing {missing} — an "
                                 f"anchor carries exactly {list(_FIELDS)}")
            out.append(AnchorRegion(anchor=a["anchor"], name=a["name"], of=a["of"]))
        return cls(anchors=tuple(out))

    @classmethod
    def from_json(cls, path: str | Path) -> "Regions":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the declaration's "
                             f"syntax") from e
        return cls.from_dict(d)


#: The fraction of the frame a region must cover to supply an anchor.
#:
#: A CONVENTION, not a measurement (design §3.1): on the only real pool the
#: subject is 0.23% on one episode and 2.19% on the next, so every value in that
#: interval selects the same seven episodes. What justifies a gate at all is not
#: sample size — 0.23% of a 1080x1922 frame is still 4680 pixels — but that a
#: 54x69 tracked box over breaking water is more likely a mis-track than a
#: subject, and what that looks like when it votes is a subject p50 of 243.5
#: against the background's 133.2. gradedamage's own docstring records the same
#: lesson from the other end: the run's subject boxes span 2420 to 890406 px, and
#: a 256-bin estimator over the small end is biased enough to erase a class
#: boundary.
MIN_REGION_FRAC = 0.01

#: Why an anchor is not being read from the region it was declared over. Each is
#: printed in MATCH.md beside the anchor it fired on; none is ever absorbed.
#:
#: CLOSED, and enforced — AnchorReading.__post_init__ refuses anything outside
#: it, exactly as AnchorRegion refuses an anchor outside ANCHORS or a kind
#: outside KINDS. A tuple no constructor consults would read as a third closed
#: vocabulary while being unobservable (rename a literal inside assemble and
#: nothing would notice), which is the gradedamage.ENTROPY_BINS mistake this
#: module's own ANCHORS comment already names.
FALLBACKS = ("no-route", "too-small", "unorderable")


@dataclass(frozen=True)
class RegionReading:
    """One region's share of the frame and its pooled profile.

    `located` is False when the region could not be found at all — a pan episode
    has no route, so it has no subject and no background either, and the anchor
    declared over one falls back as `no-route`.

    `profile` is None when the region holds no pixels. That happens two ways, and
    only `located` tells them apart: the region was never located (above), or it
    WAS located and every projected box clamped to empty — a subject entirely
    outside the delivered frame at all three sample times. The second has a real
    route and a real, measured fraction of 0.0, so it reports `too-small`, not
    `no-route`: an episode that HAS a route must never be told it has none."""
    kind: str
    fraction: float
    profile: tuple[float, float, float] | None
    located: bool = True


@dataclass(frozen=True)
class AnchorReading:
    """What one anchor was taken from, and what was asked for.

    `of` is the declaration; `used` is what actually supplied the number. They
    differ exactly when `fallback` is set, and `fallback` is one of FALLBACKS —
    MATCH.md prints this string verbatim beside the anchor, so an unnamed reason
    would read to a human exactly like a named one."""
    anchor: str
    name: str
    of: str
    used: str
    fraction: float
    value: float
    fallback: str | None = None

    def __post_init__(self) -> None:
        if self.fallback is not None and self.fallback not in FALLBACKS:
            raise ValueError(
                f"AnchorReading.fallback {self.fallback!r} unknown — expected None (the "
                f"declared region supplied this anchor) or one of {FALLBACKS}. Use one of "
                f"those names, or add the new one to regions.FALLBACKS first: the report "
                f"prints this string as-is, so a reason outside the set is a named absence "
                f"nobody named")


def _profile(pixels) -> tuple[float, float, float]:
    """(p5, p50, p95) through color.percentiles — the ONE ruler (design §2.3).

    A 256-bin histogram of 8-bit luma and the same percentile function
    color_measure._percentiles_from_gray calls, so the `crop` region's reading is
    equal to crop_percentiles' own reading and not merely close to it."""
    hist = np.bincount(pixels.ravel(), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def subject_mask(extents, n: int, h: int, w: int) -> tuple[np.ndarray, float]:
    """The tracked subject's (n, h, w) boolean mask, and its fraction of that volume.

    `extents` is one (fx0, fy0, fx1, fy1) tuple of OUTPUT-frame fractions per
    frame — geometry.extent_at_times' own return shape.

    Shared by this region's two readers (design 2026-09-16 §2.1): the tone stage,
    through measure() below, and check_episode's grade description, which means
    over the same mask in RGB instead of luma. ONE rule, so the fraction a
    fallback is decided on is the same number on both sides.
    """
    if len(extents) != n:
        raise ValueError(f"regions.subject_mask: {n} frames but {len(extents)} extents "
                         "— they must be parallel, one extent per sampled frame")
    mask = np.zeros((n, h, w), dtype=bool)
    for i, (fx0, fy0, fx1, fy1) in enumerate(extents):
        # Clamped, not refused: extent_at_times projects the tracked bbox, and a
        # subject that walks partly out of the delivered frame is ordinary. What
        # is left inside is what ships, so it is what gets measured. A box with no
        # overlap at all contributes NO pixels — never a fabricated edge sample,
        # which is what the check_episode box reader it replaces used to do
        # (design §0.6).
        x0, y0 = max(0, int(fx0 * w)), max(0, int(fy0 * h))
        x1, y1 = min(w, int(fx1 * w)), min(h, int(fy1 * h))
        if x1 > x0 and y1 > y0:
            mask[i, y0:y1, x0:x1] = True
    return mask, float(mask.mean())


def refuse(kind: str, *, located: bool, fraction: float) -> str | None:
    """Why `kind` cannot supply a reading — one of FALLBACKS, or None when it can.

    The decision assemble() used to make inline, lifted so check_episode's grade
    description makes the SAME one (design 2026-09-16 §2.1). `unorderable` is
    deliberately not here: it is a property of a three-anchor profile, and a
    single reading has none.

    A located region that holds NO pixels — a subject entirely outside the
    delivered frame — reports `too-small` and never `no-route`: it HAS a route,
    and an empty mask has a real, measured fraction of exactly 0.0, which the
    size gate below already refuses. Saying `no-route` for it would state
    something false about the episode.

    That case arrived with an `empty` parameter of its own and lost it at the
    slice's final review (correction 2026-09-16, design §2.1). It was deleted
    rather than documented, because no caller could produce it independently of
    `fraction` and so it decided nothing: in measure() a None profile means an
    empty pixel array, which means a fraction of exactly 0.0; in check_episode
    both the emptiness and the fraction are reduced from the SAME mask; and the
    crop — the one kind the size gate skips — can never arrive here empty at all,
    because assemble() raises on a profile-less crop before the loop starts.
    Measured over the whole suite before the deletion: 288 production calls, 16
    of them empty, every one at fraction 0.0, and the two predicates agreed on
    all 288. A third input that decides nothing reads as a rule while being
    unobservable — the settlement this repo already reached for
    gradedamage.ENTROPY_BINS and for _report_md's regions gate — and it invites a
    future third reader to plumb it from a per-frame source and get an answer
    assemble() would not give for the same region.

    The crop is never gated on size: every fallback lands there, so a refused
    crop would have nowhere to fall back to.
    """
    if kind not in KINDS:
        raise ValueError(f"regions.refuse: unknown kind {kind!r} — one of {KINDS}")
    if not located:
        return "no-route"
    if kind != "crop" and fraction < MIN_REGION_FRAC:
        return "too-small"
    return None


def measure(frames, extents) -> dict[str, RegionReading]:
    """Every region's reading from one already-decoded stack of luma frames.

    `frames` is (n, h, w) uint8 — the rendered crop, at the delivery's own size.
    `extents` is one (fx0, fy0, fx1, fy1) tuple of OUTPUT-frame fractions per
    frame (geometry.extent_at_times' own return shape), or None when the episode
    has no route to locate a subject with.

    The subject mask is the route's bbox, not a segmentation: a box over water
    contains water, which is exactly why design §0.3 measures the subject as the
    WORST mid reference and the best toe one."""
    frames = np.asarray(frames)
    if frames.ndim != 3:
        raise ValueError(f"regions.measure: frames must be (n, h, w), got shape "
                         f"{frames.shape}")
    n, h, w = frames.shape
    crop = RegionReading("crop", 1.0, _profile(frames))
    if extents is None:
        return {"subject": RegionReading("subject", 0.0, None, located=False),
                "background": RegionReading("background", 0.0, None, located=False),
                "crop": crop}
    mask, frac = subject_mask(extents, n, h, w)
    sub = frames[mask]
    bg = frames[~mask]
    return {"subject": RegionReading("subject", frac,
                                     _profile(sub) if sub.size else None),
            "background": RegionReading("background", 1.0 - frac,
                                        _profile(bg) if bg.size else None),
            "crop": crop}


def assemble(decl: "Regions", readings: dict[str, RegionReading]
             ) -> tuple[tuple[float, float, float], tuple[AnchorReading, ...]]:
    """The episode's (p5, p50, p95) and where each anchor came from.

    Two fallbacks, both named, neither silent (design §3):

    A region that could not be located (`no-route`) or that covers less than
    MIN_REGION_FRAC of the frame (`too-small`) does not supply its anchor; the
    crop does, and the row records what was asked for beside what was used.
    `no-route` is decided on RegionReading.located and NEVER on a missing
    profile: a located region that holds no pixels — a subject entirely outside
    the delivered frame — has a route, and reporting `no-route` for it would say
    something false about the episode. It reports `too-small` at its real,
    measured fraction of 0.0.

    A profile assembled from several regions is not obliged to increase. If it
    does not increase by color.TONE_MIN_GAP the WHOLE episode falls back to its
    crop profile — not the offending anchor alone. Repairing is what
    matchgrade._repair_gaps does to the SYNTHETIC common target, and its
    docstring already says why that is legitimate there and nowhere else: no
    episode has to match the target, so widening it invents nothing, while
    widening a measured source would author a curve from a number no frame
    contains. Falling back per-anchor is rejected for a smaller reason: a mixed
    profile whose toe came from a region and whose mid came from the crop is a
    third thing, neither the declaration nor the default, and a fallback should
    land somewhere a reader can name."""
    crop = readings["crop"]
    if crop.profile is None:
        raise ValueError("regions.assemble: the crop region has no profile — every "
                         "fallback lands there, so there is nothing to fall back to")
    rows = []
    for anchor in ANCHORS:
        want = decl.declared(anchor)
        r = readings[want.of]
        idx = ANCHORS.index(anchor)     # 0/1/2 — the anchor's own slot in a profile
        # ONE rule, shared with check_episode's grade description (design §2.1).
        # A located region that holds no pixels reaches this with a real, measured
        # fraction of exactly 0.0 — profile-None and fraction-0.0 are the same
        # fact here — so the size gate alone names it `too-small`. See refuse() on
        # why that case stopped carrying a parameter of its own.
        fb = refuse(want.of, located=r.located, fraction=r.fraction)
        rows.append(AnchorReading(anchor, want.name, want.of,
                                  "crop" if fb else want.of, r.fraction,
                                  crop.profile[idx] if fb else r.profile[idx], fb))
    profile = tuple(r.value for r in rows)
    # The check guards the ASSEMBLY: it does not run when the assembly already IS
    # the crop. Without that condition a flat crop — every pixel one value, which
    # no declaration caused and no fallback can fix — reports three `unorderable`
    # rows that changed nothing. A flat source is matchgrade.valid_src's business
    # and is skipped downstream as `flat-source` (design §3.2).
    if profile != crop.profile and not all(
            b - a >= color.TONE_MIN_GAP for a, b in zip(profile, profile[1:])):
        rows = [AnchorReading(a.anchor, a.name, a.of, "crop", a.fraction,
                              crop.profile[i], "unorderable")
                for i, a in enumerate(rows)]
        profile = crop.profile
    return profile, tuple(rows)
