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
