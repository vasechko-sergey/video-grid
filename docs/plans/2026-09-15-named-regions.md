# Named regions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the match-grade conductor's three tone anchors each come from a region
the author named in `REGIONS.json`, instead of all three coming from every pixel
of the crop.

**Architecture:** a new pure `scripts/lib/regions.py` owns the declaration
(two closed sets, one free author noun) and the assembly (per-region histogram →
per-anchor value, with two named fallbacks). `color_measure` grows a region-aware
sibling of `crop_percentiles` that reads the SAME single decode. `match_grade`
finds the declaration beside `project.json` — reachable because `ReelGeometry`
starts recording that path — and carries per-anchor provenance into `MATCH.json`
and `MATCH.md`. `color.tone_arg` and every decision function in
`scripts/lib/matchgrade.py` are untouched: three numbers still go in, they are
now taken from three places.

**Tech Stack:** Python 3, numpy (already a `scripts/lib` dependency —
`gradedamage`, `naturalness`, `lookcheck` all take arrays), ffmpeg via
`scripts/lib/ffbin`, pytest.

**Design:** [docs/specs/2026-09-15-named-regions-design.md](../specs/2026-09-15-named-regions-design.md)

## Global Constraints

- `anchor` is one of `("toe", "mid", "shoulder")`; `of` is one of
  `("subject", "background", "crop")`. Anything else is refused at LOAD, by
  name, never stored — the `constraints.py` rule verbatim: "nothing lives in
  [the file] that the machine does not check".
- `toe` is p5, `mid` is p50, `shoulder` is p95. Not configurable. A declaration
  chooses the pixel set, never the percentile.
- `MIN_REGION_FRAC = 0.01`.
- A run with no `REGIONS.json` must produce a **byte-identical** EDL, MATCH.json
  target and MATCH.md target to today's. This is a pinned test, not an intention.
- Every fallback is named in the report with its reason. No silent absorption,
  no waiver, anywhere.
- A measured source profile is never repaired. `matchgrade._repair_gaps` widens
  the SYNTHETIC common target and nothing else.
- Percentiles come from `color.percentiles(hist256)` and from nowhere else —
  one ruler.
- Scripts run as modules (`pythonpath = .`); the interpreter is
  `.venv/bin/python`. Never install anything.
- Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lib/regions.py` | **new.** The declaration contract and the assembly. Pure: numpy arrays and dataclasses in, readings out. No IO except `Regions.from_json`. |
| `tests/lib/test_regions.py` | **new.** Unit tests for both halves. |
| `scripts/reframe.py` | `path_meta(plan, spec, *, stabilized)` extracted from `reframe()` so a caller with no rendered sidecar can build the same `PathMeta`. |
| `scripts/process_episode.py` | `plan_and_meta_ungraded()` — the plan plus its `CropPath`/`PathMeta`, for a caller that runs before any render. |
| `scripts/color_measure.py` | `crop_region_percentiles()` — per-region histograms from the one decode `crop_percentiles` already makes; `measure_crop()` returns profile + provenance. |
| `scripts/lib/models.py` | `ReelGeometry.project` — the path `REGIONS.json` is found beside. |
| `scripts/edl_to_reel.py` | writes that field. |
| `scripts/lib/matchgrade.py` | `ToneDecision.regions` carries the per-anchor provenance into `MATCH.json`. |
| `scripts/match_grade.py` | discovery, threading, and both report halves. |

---

### Task 1: The declaration

**Files:**
- Create: `scripts/lib/regions.py`
- Test: `tests/lib/test_regions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ANCHORS: tuple[str, ...]`, `KINDS: tuple[str, ...]`,
  `AnchorRegion(anchor: str, name: str, of: str)`,
  `Regions(anchors: tuple[AnchorRegion, ...])` with `from_dict`, `from_json`,
  `to_dict`, and `declared(anchor: str) -> AnchorRegion` returning the declared
  row or the implicit `crop` row.

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_regions.py
import json

import pytest

from scripts.lib import regions


def test_a_full_declaration_round_trips():
    d = {"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"},
        {"anchor": "shoulder", "name": "frame", "of": "crop"}]}
    r = regions.Regions.from_dict(d)
    assert r.to_dict() == d
    assert r.declared("toe") == regions.AnchorRegion("toe", "wetsuit", "subject")


def test_an_undeclared_anchor_is_the_crop_and_says_so_in_its_name():
    r = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    assert r.declared("mid") == regions.AnchorRegion("mid", "crop", "crop")


def test_an_unknown_anchor_slot_is_refused_by_name():
    with pytest.raises(ValueError, match="knee"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "knee", "name": "x", "of": "crop"}]})


def test_an_unknown_region_kind_is_refused_by_name():
    with pytest.raises(ValueError, match="sky"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "x", "of": "sky"}]})


def test_an_empty_author_name_is_refused():
    with pytest.raises(ValueError, match="name"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "  ", "of": "subject"}]})


def test_one_anchor_declared_twice_is_refused_at_load():
    with pytest.raises(ValueError, match="toe"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "a", "of": "subject"},
            {"anchor": "toe", "name": "b", "of": "background"}]})


def test_an_extra_field_is_refused_not_ignored():
    with pytest.raises(ValueError, match="band"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "a", "of": "subject", "band": [0, 0.4]}]})


def test_a_non_object_top_level_is_refused():
    with pytest.raises(ValueError, match="REGIONS.json"):
        regions.Regions.from_dict([])


def test_a_missing_anchors_list_is_refused():
    with pytest.raises(ValueError, match="anchors"):
        regions.Regions.from_dict({})


def test_from_json_names_the_file_on_a_syntax_error(tmp_path):
    p = tmp_path / "REGIONS.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match=str(p)):
        regions.Regions.from_json(p)


def test_the_two_closed_sets_and_their_order():
    """ANCHORS' ORDER is load-bearing, not cosmetic: it is the order of a profile
    tuple, so assemble indexes (p5, p50, p95) by it."""
    assert regions.ANCHORS == ("toe", "mid", "shoulder")
    assert regions.KINDS == ("subject", "background", "crop")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_regions.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'scripts.lib.regions'`

- [ ] **Step 3: Write the module's declaration half**

```python
# scripts/lib/regions.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_regions.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/regions.py tests/lib/test_regions.py
git commit -m "feat(regions): the declaration — two closed sets and one author noun"
```

---

### Task 2: The assembly, and its two named fallbacks

**Files:**
- Modify: `scripts/lib/regions.py`
- Test: `tests/lib/test_regions.py`

**Interfaces:**
- Consumes: `ANCHORS`, `KINDS`, `AnchorRegion`, `Regions` from Task 1;
  `scripts.lib.color.percentiles`, `scripts.lib.color.TONE_MIN_GAP`.
- Produces:
  - `MIN_REGION_FRAC = 0.01`
  - `RegionReading(kind: str, fraction: float, profile: tuple[float, float, float] | None)`
  - `measure(frames, extents) -> dict[str, RegionReading]` — `frames` is a
    `(n, h, w)` uint8 numpy array of luma, `extents` a list of `n`
    `(fx0, fy0, fx1, fy1)` output-frame fractions or `None` for "no route".
  - `AnchorReading(anchor: str, name: str, of: str, used: str, fraction: float, value: float, fallback: str | None)`
  - `assemble(decl, readings) -> tuple[tuple[float, float, float], tuple[AnchorReading, ...]]`
  - `FALLBACKS = ("no-route", "too-small", "unorderable")`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/lib/test_regions.py
import numpy as np

from scripts.lib import color


def _frames(rows):
    """(n, h, w) uint8 luma from a list of 2-D lists."""
    return np.array(rows, dtype=np.uint8)


def _split_frame(h=100, w=100, subject=40, bg=200):
    """One frame: a dark 10x10 block top-left in a bright field."""
    f = np.full((h, w), bg, dtype=np.uint8)
    f[0:10, 0:10] = subject
    return f[None, ...]


def test_measure_reports_the_three_regions_and_their_area_fractions():
    out = regions.measure(_split_frame(), [(0.0, 0.0, 0.1, 0.1)])
    assert out["subject"].fraction == pytest.approx(0.01)
    assert out["background"].fraction == pytest.approx(0.99)
    assert out["crop"].fraction == 1.0
    assert out["subject"].profile == (40.0, 40.0, 40.0)
    assert out["background"].profile == (200.0, 200.0, 200.0)


def test_the_crop_region_is_every_pixel_pooled_across_frames():
    f = np.concatenate([_split_frame(), _split_frame(subject=10)])
    out = regions.measure(f, [(0.0, 0.0, 0.1, 0.1)] * 2)
    hist = np.bincount(f.ravel(), minlength=256)[:256]
    assert out["crop"].profile == color.percentiles([int(c) for c in hist])


def test_no_route_leaves_subject_and_background_unmeasured():
    out = regions.measure(_split_frame(), None)
    assert out["subject"].profile is None and out["subject"].fraction == 0.0
    assert out["background"].profile is None
    assert out["crop"].profile is not None


def test_assemble_takes_each_anchor_from_its_declared_region():
    readings = {
        "subject": regions.RegionReading("subject", 0.2, (10.0, 20.0, 30.0)),
        "background": regions.RegionReading("background", 0.8, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (10.0, 120.0, 200.0)      # subject p5, background p50, crop p95
    assert [r.of for r in rows] == ["subject", "background", "crop"]
    assert [r.name for r in rows] == ["wetsuit", "water", "crop"]
    assert all(r.fallback is None for r in rows)


def test_a_region_under_the_area_gate_falls_back_to_crop_and_is_named():
    readings = {
        "subject": regions.RegionReading("subject", 0.002, (250.0, 251.0, 252.0)),
        "background": regions.RegionReading("background", 0.998, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    toe = rows[0]
    assert toe.fallback == "too-small" and toe.used == "crop"
    assert toe.of == "subject" and toe.fraction == pytest.approx(0.002)


def test_an_unmeasured_region_falls_back_as_no_route():
    readings = {
        "subject": regions.RegionReading("subject", 0.0, None),
        "background": regions.RegionReading("background", 0.0, None),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert rows[0].fallback == "no-route"


def test_an_unorderable_profile_drops_the_WHOLE_episode_to_the_crop():
    # toe from a BRIGHT subject would land above the background's own p50
    readings = {
        "subject": regions.RegionReading("subject", 0.3, (150.0, 200.0, 240.0)),
        "background": regions.RegionReading("background", 0.7, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert [r.fallback for r in rows] == ["unorderable"] * 3
    assert [r.used for r in rows] == ["crop"] * 3


def test_a_profile_inside_the_gap_but_ordered_is_still_unorderable():
    # ordered, but the toe sits closer than TONE_MIN_GAP to the mid
    gap = color.TONE_MIN_GAP
    readings = {
        "subject": regions.RegionReading("subject", 0.3, (110.0 - gap / 2, 0.0, 0.0)),
        "background": regions.RegionReading("background", 0.7, (0.0, 110.0, 0.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert rows[0].fallback == "unorderable"


def test_no_declaration_is_three_crop_anchors_and_no_fallback():
    readings = {
        "subject": regions.RegionReading("subject", 0.2, (10.0, 20.0, 30.0)),
        "background": regions.RegionReading("background", 0.8, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    profile, rows = regions.assemble(regions.Regions(), readings)
    assert profile == (50.0, 110.0, 200.0)
    assert all(r.used == "crop" and r.fallback is None for r in rows)


def test_a_flat_crop_is_not_reported_as_three_unorderable_fallbacks():
    """A uniform crop cannot order, and no declaration caused that. Reporting it
    as a region fallback would blame the declaration for the footage; a flat
    source is matchgrade.valid_src's business and is skipped downstream as
    `flat-source`."""
    readings = {
        "subject": regions.RegionReading("subject", 0.0, None),
        "background": regions.RegionReading("background", 0.0, None),
        "crop": regions.RegionReading("crop", 1.0, (100.0, 100.0, 100.0))}
    profile, rows = regions.assemble(regions.Regions(), readings)
    assert profile == (100.0, 100.0, 100.0)
    assert all(r.fallback is None for r in rows)


def test_the_area_gate_is_one_percent():
    assert regions.MIN_REGION_FRAC == 0.01
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_regions.py -q`
Expected: 10 failures, `AttributeError: module 'scripts.lib.regions' has no attribute 'measure'`

- [ ] **Step 3: Write the assembly half**

Append to `scripts/lib/regions.py` (and add `import numpy as np` and
`from scripts.lib import color` to the imports at the top):

```python
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
FALLBACKS = ("no-route", "too-small", "unorderable")


@dataclass(frozen=True)
class RegionReading:
    """One region's share of the frame and its pooled profile.

    `profile` is None when the region could not be located at all — a pan
    episode has no route, so it has no subject and no background either. That is
    distinct from a region that was located and found tiny, which carries a real
    fraction and a real (but untrustworthy) profile."""
    kind: str
    fraction: float
    profile: tuple[float, float, float] | None


@dataclass(frozen=True)
class AnchorReading:
    """What one anchor was taken from, and what was asked for.

    `of` is the declaration; `used` is what actually supplied the number. They
    differ exactly when `fallback` is set."""
    anchor: str
    name: str
    of: str
    used: str
    fraction: float
    value: float
    fallback: str | None = None


def _profile(pixels) -> tuple[float, float, float]:
    """(p5, p50, p95) through color.percentiles — the ONE ruler (design §2.3).

    A 256-bin histogram of 8-bit luma and the same percentile function
    color_measure._percentiles_from_gray calls, so the `crop` region's reading is
    equal to crop_percentiles' own reading and not merely close to it."""
    hist = np.bincount(pixels.ravel(), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


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
        return {"subject": RegionReading("subject", 0.0, None),
                "background": RegionReading("background", 0.0, None),
                "crop": crop}
    if len(extents) != n:
        raise ValueError(f"regions.measure: {n} frames but {len(extents)} extents — "
                         "they must be parallel, one extent per sampled frame")
    mask = np.zeros((n, h, w), dtype=bool)
    for i, (fx0, fy0, fx1, fy1) in enumerate(extents):
        # Clamped, not refused: extent_at_times projects the tracked bbox, and a
        # subject that walks partly out of the delivered frame is ordinary. What
        # is left inside is what ships, so it is what gets measured.
        x0, y0 = max(0, int(fx0 * w)), max(0, int(fy0 * h))
        x1, y1 = min(w, int(fx1 * w)), min(h, int(fy1 * h))
        if x1 > x0 and y1 > y0:
            mask[i, y0:y1, x0:x1] = True
    frac = float(mask.mean())
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
        if r.profile is None:
            rows.append(AnchorReading(anchor, want.name, want.of, "crop", r.fraction,
                                      crop.profile[idx], "no-route"))
        elif want.of != "crop" and r.fraction < MIN_REGION_FRAC:
            rows.append(AnchorReading(anchor, want.name, want.of, "crop", r.fraction,
                                      crop.profile[idx], "too-small"))
        else:
            rows.append(AnchorReading(anchor, want.name, want.of, want.of, r.fraction,
                                      r.profile[idx], None))
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_regions.py -q`
Expected: 22 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/regions.py tests/lib/test_regions.py
git commit -m "feat(regions): per-region readings and the two named fallbacks"
```

---

### Task 3: A PathMeta a caller can build before any render

**Files:**
- Modify: `scripts/reframe.py:594-657` (the `reframe()` body)
- Modify: `scripts/process_episode.py:60-84` (beside `plan_for`/`plan_ungraded`)
- Test: `tests/integration/test_reframe.py`, `tests/integration/test_matchgrade.py`

**Why this task exists (measured):** `process_episode(stop_after="geometry")`
returns at `scripts/process_episode.py:437`, **before** `reframe()` runs — and
`path.json` / `path.meta.json` are written by `reframe()`. The conductor runs
between `--stop-after-geometry` and `--from-geometry`, so at conductor time
those files do not exist. `geometry.extent_at_times` needs both objects. They
must therefore come from the `RenderPlan`, which already carries every field
`reframe()` fills the sidecar from.

**Interfaces:**
- Consumes: `reframe.RenderPlan`, `reframe.plan_render`,
  `process_episode.plan_ungraded`.
- Produces:
  - `reframe.path_meta(plan: RenderPlan, spec: ReframeSpec, *, stabilized: bool) -> PathMeta`
  - `process_episode.plan_and_meta_ungraded(manifest_dict: dict, src: str, route: str | None) -> tuple[reframe.RenderPlan, CropPath, PathMeta]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_reframe.py — append
def test_path_meta_builds_the_same_sidecar_reframe_writes(tmp_path, golden_ride_segment):
    """The extraction's whole point: one builder, two callers. If reframe kept its
    own copy the conductor would measure a geometry the render does not use."""
    from scripts import reframe
    from scripts.lib.models import PathMeta
    spec, src, route = _spec_src_route(tmp_path, golden_ride_segment)
    reframe.reframe(spec, src, route, str(tmp_path / "ep.mp4"),
                    str(tmp_path / "path.json"), stabilized=False)
    written = PathMeta.from_json(str(tmp_path / "path.meta.json"))
    built = reframe.path_meta(reframe.plan_render(spec, src, route), spec,
                              stabilized=False)
    assert built == written
```

`_spec_src_route` builds a `fill`-layout `ReframeSpec` over `golden_ride_segment`
plus a written `route.json`. This file already assembles those three inline in
its existing render tests — lift that into a module-level helper as the first
step, so the new test and the old ones cannot describe different geometries.

```python
# tests/lib/test_process_episode_plans.py — append
def test_plan_and_meta_ungraded_needs_no_rendered_sidecar(tmp_path, golden_ride_segment):
    """Measured: stop_after='geometry' returns at process_episode.py:437, before
    reframe runs — and reframe is what writes path.json. At conductor time the
    sidecar does not exist. This is the guard on that."""
    from scripts import process_episode
    md = _md(golden_ride_segment)
    route = str(tmp_path / "route.json")
    Path(route).write_text(json.dumps(
        [dict(t=0.0, x=960.0, y=540.0, w=120.0, h=120.0),
         dict(t=1.0, x=960.0, y=540.0, w=120.0, h=120.0)]))
    plan, path, meta = process_episode.plan_and_meta_ungraded(
        md, golden_ride_segment, route)
    assert len(path) == len(plan.path)
    assert meta.out_dims == (plan.rl.out_w, plan.rl.out_h)
    assert not (tmp_path / "path.json").exists()     # writes nothing
    assert not (tmp_path / "path.meta.json").exists()
```

`_md(seg)` is this file's existing one-line manifest factory. Add `json` and
`from pathlib import Path` to its imports if absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py tests/lib/test_process_episode_plans.py -q`
Expected: FAIL — `AttributeError: module 'scripts.reframe' has no attribute 'path_meta'`

- [ ] **Step 3: Extract the builder in `scripts/reframe.py`**

Add above `reframe()`:

```python
def path_meta(plan: RenderPlan, spec: ReframeSpec, *, stabilized: bool) -> PathMeta:
    """The sidecar this plan's render would write.

    Extracted from reframe() so a caller that has not rendered — the match-grade
    conductor, which runs between --stop-after-geometry and --from-geometry, when
    path.meta.json does not yet exist — can project the tracked subject through
    the SAME geometry the render will use. A caller rebuilding this map would be
    a second implementation of the render's own geometry, which is the risk
    plan_render's docstring already names.
    """
    return PathMeta(mode=plan.rl.mode, crop_w=plan.rl.crop_w, crop_h=plan.rl.crop_h,
                    crop_y=plan.cy, src_dims=(plan.src_w, plan.src_h),
                    canvas=spec.canvas, out_dims=(plan.rl.out_w, plan.rl.out_h),
                    rect_px=plan.rl.rect_px, freedom=plan.rl.freedom,
                    background=plan.rl.background,
                    pan=spec.pan is not None, stabilized=stabilized,
                    crop_ws=plan.crop_ws if spec.zoom is not None else None,
                    crop_hs=plan.crop_hs if spec.zoom is not None else None,
                    crop_ys=plan.crop_ys if spec.zoom is not None else None)
```

Then replace the inline `PathMeta(...)` block at the end of `reframe()` with:

```python
    path_meta(plan, spec, stabilized=stabilized).write(
        Path(path_out).with_suffix(".meta.json"))
```

- [ ] **Step 4: Add the plan+meta helper in `scripts/process_episode.py`**

Beside `plan_ungraded`:

```python
def plan_and_meta_ungraded(manifest_dict: dict, src: str,
                           route: str | None) -> tuple[reframe.RenderPlan, CropPath, PathMeta]:
    """`plan_ungraded` plus the CropPath and PathMeta its render would write.

    For a caller that must place the tracked subject inside the crop BEFORE the
    crop has been rendered — the conductor, which runs at the geometry seam where
    process_episode returns before reframe and so before path.json exists. Writes
    nothing."""
    m = manifest_lib.Manifest.from_dict(manifest_lib.strip_colour(manifest_dict))
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        params["smooth_window_s"] = m.smooth_window_s
    spec = build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    plan = reframe.plan_render(spec, src, route)
    return plan, CropPath(plan.path), reframe.path_meta(plan, spec, stabilized=m.stabilize)
```

Add `CropPath` and `PathMeta` to this module's imports from `scripts.lib.models`
if they are not already there.

- [ ] **Step 5: Run the whole reframe + matchgrade suite**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py tests/lib/test_process_episode_plans.py tests/lib/test_reframe.py -q`
Expected: all pass, including the pre-existing sidecar tests — the extraction must
move no byte of the written file.

- [ ] **Step 6: Commit**

```bash
git add scripts/reframe.py scripts/process_episode.py tests/integration/test_reframe.py tests/lib/test_process_episode_plans.py
git commit -m "refactor(reframe): one PathMeta builder, reachable before the render"
```

---

### Task 4: The region-aware ruler, from the same single decode

**Files:**
- Modify: `scripts/color_measure.py:138-165`
- Test: `tests/integration/test_color_measure.py`

**Interfaces:**
- Consumes: `regions.measure`, `regions.assemble`, `regions.Regions` (Tasks 1–2);
  `process_episode.plan_and_meta_ungraded` (Task 3); `geometry.extent_at_times`.
- Produces:
  - `color_measure.crop_region_frames(plan, src, times) -> np.ndarray` — the
    `(n, out_h, out_w)` uint8 luma stack, byte-checked exactly as
    `_percentiles_from_gray` checks it.
  - `color_measure.measure_crop(manifest_dict, src, route, *, decl=None, frames=color.FRAMES) -> tuple[Profile, tuple[regions.AnchorReading, ...]]`
    — **the return shape changes**: it was a bare `Profile`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_color_measure.py — append

def _subject_episode(tmp_path):
    """(src, manifest_dict, route_json): a crop with real tonal spread AND a dark
    subject inside it, so the toe can move while the mid and shoulder cannot.

    640x1280. The top 640 rows are excluded by the crop exactly as in
    _banded_episode (canvas [1,1] over a 640x1280 source crops 640x640, and
    geometry.crop_y places it against the route's mean y of 960). The cropped half
    is three sub-bands — 80 / 140 / 200 — so the crop's own profile is
    (80, 140, 200): ordered, gaps far above color.TONE_MIN_GAP. A 120x120 box at
    luma 20 sits inside the darkest sub-band at the route's bbox.

    The box is 14400 px of the crop's 409600 — 3.52%, above MIN_REGION_FRAC and
    below 5%, which is what makes the two readings differ: the crop's p5 is 80
    (only 3.52% of it is darker) while the subject region is entirely the box, so
    its p5 is 20. The mid and shoulder are untouched by construction, which is the
    control the toe test needs."""
    src = tmp_path / "subject.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", "color=c=0x303030:s=640x640:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0x505050:s=640x214:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0x8c8c8c:s=640x213:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0xc8c8c8:s=640x213:d=2:r=30",
              "-filter_complex",
              "[0][1][2][3]vstack=inputs=4,"
              "drawbox=x=260:y=900:w=120:h=120:color=0x141414@1:t=fill",
              "-frames:v", "60", "-pix_fmt", "yuv420p", "-color_range", "tv", str(src)])
    md = {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
          "grid": "thirds", "canvas": [1, 1], "target_dur": 2.0}
    route_path = tmp_path / "subject_route.json"
    route_path.write_text(json.dumps(
        [dict(t=0.0, x=320.0, y=960.0, w=120.0, h=120.0),
         dict(t=2.0, x=320.0, y=960.0, w=120.0, h=120.0)]))
    return str(src), md, str(route_path)


def test_the_crop_region_reading_equals_crop_percentiles_exactly(tmp_path):
    """The byte-identical default path, pinned. If the region ruler and the
    pooled-histogram ruler ever disagree there are two rulers, which is the one
    thing this module's docstring forbids."""
    from scripts import process_episode
    from scripts.lib import regions
    src, md, route = _subject_episode(tmp_path)
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, src, route)
    times = color.sample_times(plan.dur)
    pooled = color_measure.crop_percentiles(plan, src, times)
    stack = color_measure.crop_region_frames(plan, src, times)
    assert regions.measure(stack, None)["crop"].profile == pooled


def test_measure_crop_with_no_declaration_returns_the_old_profile(tmp_path):
    from scripts import process_episode
    src, md, route = _subject_episode(tmp_path)
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, src, route)
    profile, rows = color_measure.measure_crop(md, src, route)
    assert profile == color_measure.crop_percentiles(
        plan, src, color.sample_times(plan.dur))
    assert [r.used for r in rows] == ["crop", "crop", "crop"]
    assert all(r.fallback is None for r in rows)


def test_a_subject_declaration_moves_the_toe_and_nothing_else(tmp_path):
    from scripts.lib import regions
    src, md, route = _subject_episode(tmp_path)
    plain, _ = color_measure.measure_crop(md, src, route)
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    toned, rows = color_measure.measure_crop(md, src, route, decl=decl)
    assert toned[1:] == plain[1:]                  # the control: mid and shoulder
    assert toned[0] < plain[0] - 30, (toned, plain)
    assert rows[0].of == "subject" and rows[0].used == "subject"
    assert rows[0].fallback is None
    assert 0.02 < rows[0].fraction < 0.06


def test_a_pan_episode_has_no_route_and_falls_back_named(tmp_path):
    from scripts.lib import regions
    src, md = _pan_episode(tmp_path)
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = color_measure.measure_crop(md, src, None, decl=decl)
    assert rows[0].fallback == "no-route"
    assert profile == color_measure.measure_crop(md, src, None)[0]
```

`_pan_episode` and `_banded_episode` already exist in this file. Two of its
existing tests unpack `measure_crop`'s return as a bare triple and MUST be
updated for the two-value return in this task, not in a follow-up:
`test_measure_crop_reads_the_footage_not_a_grade_already_authored` and
`test_measure_crop_works_on_a_pan_episode`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_color_measure.py -q`
Expected: FAIL — `AttributeError: module 'scripts.color_measure' has no attribute
'crop_region_frames'`, and a `TypeError` unpacking `measure_crop`'s single triple
into two names.

- [ ] **Step 3: Write the implementation**

Replace `measure_crop` in `scripts/color_measure.py` and add its sibling:

```python
def crop_region_frames(plan: "reframe.RenderPlan", src: str, times: list[float]):
    """The (n, out_h, out_w) uint8 luma stack crop_percentiles pools into one
    histogram — the SAME decode, kept per-frame so a mask can be applied.

    One ffmpeg call, exactly as crop_percentiles makes: a region reading must not
    cost a second decode, and must not read different pixels than the pooled
    reading it has to agree with. The select is appended at the END through
    with_tail: before the chain's own `fps=` it would emit one frame N times
    (§12)."""
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src,
                    *plan.with_tail(f"{color.select_frames(times, plan.fps)},format=gray"),
                    "-t", f"{plan.dur:.6f}", "-vsync", "0",
                    "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    w, h = plan.rl.out_w, plan.rl.out_h
    want = len(times) * w * h
    if len(raw) != want:
        got = len(raw) / (w * h) if w and h else float("nan")
        raise RuntimeError(
            f"crop_region_frames({src}): asked for {len(times)} frames of {w}x{h} "
            f"gray ({want} bytes), got {len(raw)} bytes ({got:g} frames) — a frame "
            f"is missing or duplicated; check the select expression's position")
    return np.frombuffer(raw, dtype=np.uint8).reshape(len(times), h, w)


def measure_crop(manifest_dict: dict, src: str, route: str | None, *,
                 decl: "regions.Regions | None" = None,
                 frames: int = color.FRAMES
                 ) -> tuple[tuple[float, float, float], tuple["regions.AnchorReading", ...]]:
    """The episode's (p5, p50, p95), ungraded, each anchor from its declared
    region — plus one AnchorReading per anchor saying where it came from.

    The REGION is design 2026-08-30's: the episode's own tracked crop, the pixels
    that actually ship. Which part of that crop supplies which anchor is design
    2026-09-15's, and `decl=None` means all three come from the whole crop, which
    is what every anchor was before that slice.

    Costs one decode whether or not a declaration is present. The subject's
    location comes from the RenderPlan rather than path.meta.json because this
    runs at the geometry seam, where process_episode has returned before reframe
    and the sidecar does not exist yet (plan_and_meta_ungraded)."""
    plan, path, meta = process_episode.plan_and_meta_ungraded(manifest_dict, src, route)
    times = color.sample_times(plan.dur, frames)
    stack = crop_region_frames(plan, src, times)
    extents = None
    if route is not None:
        pts = [RoutePoint(**p) for p in json.loads(Path(route).read_text())]
        extents = geometry.extent_at_times(pts, path, meta, times)
    readings = regions.measure(stack, extents)
    return regions.assemble(decl if decl is not None else regions.Regions(), readings)
```

Add to this module's imports: `json`, `from pathlib import Path`,
`from scripts.lib import geometry, regions`, and
`from scripts.lib.models import RoutePoint`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_color_measure.py -q`
Expected: all pass — the four new tests plus the file's pre-existing ones, two of
which were updated for the new return shape in Step 3.

- [ ] **Step 5: Commit**

```bash
git add scripts/color_measure.py tests/integration/test_color_measure.py
git commit -m "feat(color_measure): per-region anchors from the one decode"
```

---

### Task 5: `REGIONS.json` becomes reachable from the conductor

**Files:**
- Modify: `scripts/lib/models.py:1467-1510` (`ReelGeometry`)
- Modify: `scripts/edl_to_reel.py` (`build_geometry`, where `ReelGeometry` is constructed)
- Test: `tests/lib/test_models.py`, `tests/integration/test_grade_shipped_pixels.py`

**Why:** `REGIONS.json` sits beside `project.json` at the run root
(`RunLayout.project`), exactly as `CONSTRAINTS.json` does — one file moves both.
`match_grade build` takes only `--geometry`, and `GEOMETRY.json` does not record
where `project.json` was. A `--regions` flag is rejected for the reason
`edit_plan` rejects one for constraints: a flag can be forgotten, and a forgotten
flag silently reverts the grade to whole-crop anchors. So phase 1a, which already
takes `--project`, records it.

**Interfaces:**
- Consumes: `ReelGeometry` from `scripts.lib.models`.
- Produces: `ReelGeometry.project: str = ""` — stored VERBATIM, never resolved,
  the same rule `ReelGeometry.edl` follows. Empty means a GEOMETRY.json written
  before this slice.

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_models.py — append
def test_reel_geometry_carries_the_project_path_verbatim():
    from scripts.lib.models import ReelGeometry
    g = _reel_geometry(edl="out/EDL.json", project="../montage/project.json")
    assert g.to_dict()["project"] == "../montage/project.json"
    assert ReelGeometry.from_dict(g.to_dict()).project == "../montage/project.json"


def test_a_geometry_written_before_this_slice_has_no_project_and_is_still_valid():
    from scripts.lib.models import ReelGeometry
    d = _reel_geometry(edl="out/EDL.json").to_dict()
    d.pop("project", None)
    assert ReelGeometry.from_dict(d).project == ""
```

`_reel_geometry(**over)` does not exist yet in `tests/lib/test_models.py` — that
file builds `ReelGeometry(...)` inline in each of its four geometry tests. Add it
as the first step of this task, taking `edl` and `project` keywords over one
minimal `EpisodeGeometry`, and move those four tests onto it: a contract growing a
field is exactly when four hand-written constructions start drifting.

```python
# tests/integration/test_grade_shipped_pixels.py — append
def test_stop_after_geometry_records_the_project_it_was_given(tmp_path, golden_ride_segment):
    """Without it REGIONS.json is unreachable from match_grade, which takes only
    --geometry."""
    from scripts.lib.models import ReelGeometry
    geo_path = _stop_after_geometry(tmp_path, golden_ride_segment)
    geo = ReelGeometry.from_json(geo_path)
    assert Path(geo.project).name == "project.json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k reel_geometry tests/integration/test_grade_shipped_pixels.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'project'`

- [ ] **Step 3: Add the field**

In `ReelGeometry`, after `edl`:

```python
    project: str = ""
```

In its docstring, after the `provenance` paragraph:

```
    `project` is the project.json phase 1a was given, stored VERBATIM exactly as
    `edl` is (design 2026-08-30 §2.2). It exists so match_grade can find
    REGIONS.json beside it without a flag — `edit_plan` finds CONSTRAINTS.json
    the same way and for the same reason: a flag can be forgotten, and a
    forgotten flag here silently reverts the grade to whole-crop anchors. Empty
    on a GEOMETRY.json written before design 2026-09-15; the conductor reports
    that as a named absence rather than as "no declaration".
```

In `to_dict`, after the `edl` key:

```python
        if self.project:
            d["project"] = self.project
```

In `from_dict`, add `project=d.get("project") or ""` to the constructor call.

- [ ] **Step 4: Write the field in `scripts/edl_to_reel.py`**

Find where `build_geometry` constructs `ReelGeometry(...)` and add
`project=str(project) if project else ""` using the `project` argument that
function already receives (`edl_to_reel.py:722` passes `a.project` into it).

`_stop_after_geometry(tmp_path, segment)` in
`tests/integration/test_grade_shipped_pixels.py` is that file's existing driver
call for phase 1a — reuse it; if it is inline, lift it to a module-level helper
first.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/integration/test_grade_shipped_pixels.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/models.py scripts/edl_to_reel.py tests/lib/test_models.py tests/integration/test_grade_shipped_pixels.py
git commit -m "feat(geometry): record the project path so REGIONS.json needs no flag"
```

---

### Task 6: The conductor reads the declaration and reports it

**Files:**
- Modify: `scripts/lib/matchgrade.py` (`ToneDecision`)
- Modify: `scripts/match_grade.py` (`conduct`, `_report_md`, `write_match`)
- Test: `tests/integration/test_matchgrade.py`, `tests/lib/test_matchgrade.py`

**Interfaces:**
- Consumes: `regions.Regions`, `regions.AnchorReading` (Tasks 1–2);
  `color_measure.measure_crop`'s new two-value return (Task 4);
  `ReelGeometry.project` (Task 5).
- Produces: `ToneDecision.regions: tuple[dict, ...] = ()` — one serialized
  `AnchorReading` per anchor, carried into `MATCH.json`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_matchgrade.py — append
def test_no_regions_file_leaves_the_target_byte_identical(tmp_path, monkeypatch):
    """The pinned default path (Global Constraints). A run with no declaration
    must produce the same target, the same EDL and the same MATCH.json as before
    this slice."""
    before = _write_match_with_fake_measurements(tmp_path, decl_file=None)
    after = _write_match_with_fake_measurements(tmp_path, decl_file=None)
    assert before["target"] == after["target"]
    assert all(d["regions"] == [] for d in _match_json(tmp_path)["decisions"])


def test_a_regions_file_beside_project_json_is_found_with_no_flag(tmp_path, monkeypatch):
    (tmp_path / "REGIONS.json").write_text(json.dumps({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]}))
    result = _write_match_with_fake_measurements(tmp_path, decl_file="REGIONS.json")
    assert result["regions"] == str(tmp_path / "REGIONS.json")
    rows = _match_json(tmp_path)["decisions"][0]["regions"]
    assert rows[0] == {"anchor": "toe", "name": "wetsuit", "of": "subject",
                       "used": "subject", "fraction": 0.2, "value": 10.0,
                       "fallback": None}


def test_a_geometry_with_no_project_says_so_rather_than_reporting_no_declaration(tmp_path):
    result = _write_match_with_fake_measurements(tmp_path, project=None)
    assert result["regions"] == "unreachable"
    assert "GEOMETRY.json records no project" in (tmp_path / "MATCH.md").read_text()


def test_the_report_prints_the_fallback_and_its_reason(tmp_path):
    result = _write_match_with_fake_measurements(tmp_path, decl_file="REGIONS.json",
                                                 subject_fraction=0.002)
    md = (tmp_path / "MATCH.md").read_text()
    assert "too-small" in md and "wetsuit" in md and "0.2%" in md
```

`_write_match_with_fake_measurements` monkeypatches `match_grade.measure_crop`
to return a fixed `(profile, rows)` pair built through `regions.assemble`, writes
a minimal GEOMETRY.json + EDL, calls `write_match`, and returns its status dict.
`_match_json` reads the written MATCH.json. Both belong in this module beside the
existing `measure_crop` monkeypatch helpers, which must be updated for the new
two-value return.

```python
# tests/lib/test_matchgrade.py — append
def test_tone_decision_round_trips_its_region_rows():
    from scripts.lib import matchgrade
    d = matchgrade.ToneDecision(0, "author", "authored", (10.0, 20.0, 30.0),
                                regions=({"anchor": "toe", "name": "wetsuit",
                                          "of": "subject", "used": "subject",
                                          "fraction": 0.2, "value": 10.0,
                                          "fallback": None},))
    assert matchgrade.ToneDecision.from_dict(d.to_dict()) == d


def test_a_decision_written_before_this_slice_has_no_region_rows():
    from scripts.lib import matchgrade
    d = matchgrade.ToneDecision(0, "skip", "within-eps", (10.0, 20.0, 30.0)).to_dict()
    d.pop("regions")
    assert matchgrade.ToneDecision.from_dict(d).regions == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py tests/integration/test_matchgrade.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'regions'`

- [ ] **Step 3: Carry the provenance on `ToneDecision`**

In `scripts/lib/matchgrade.py`, add to the dataclass:

```python
    regions: tuple[dict, ...] = ()
```

and to its docstring:

```
    `regions` is one row per tone anchor: the author's name for the region, the
    kind declared, the kind actually used, that region's frame fraction, the
    value taken, and the fallback if one fired (design 2026-09-15 §4). Empty on
    a report written before that slice, and empty is not "no fallback fired" —
    it is "this report predates the record".
```

In `to_dict`, add `"regions": [dict(r) for r in self.regions]`. In `from_dict`,
add `regions=tuple(d.get("regions") or ())`.

`plan()` takes the rows as a new parallel list and attaches them:

```python
def plan(profiles: list[Profile], has_tone: list[bool], target: Profile,
         *, eps: float = MATCH_EPS, force: bool = False,
         regions: list[tuple[dict, ...]] | None = None) -> list[ToneDecision]:
```

with `rows = (regions[i] if regions is not None else ())` attached to every
`ToneDecision` it builds, and the existing length check extended to `regions`
when it is not None.

- [ ] **Step 4: Thread it through `scripts/match_grade.py`**

`conduct` gains `decl: regions_lib.Regions | None = None` and unpacks the pair:

```python
    measured = [measure_crop(eg.manifest, eg.source, eg.route, decl=decl)
                for eg in geo.episodes]
    profiles = [p for p, _ in measured]
    region_rows = [tuple(_row_dict(r) for r in rows) for _, rows in measured]
```

with a module-level

```python
def _row_dict(r: "regions_lib.AnchorReading") -> dict:
    """One AnchorReading as MATCH.json carries it. Rounded where it is printed:
    a fraction to four places is 0.01% resolution, which is finer than the gate
    it is compared against."""
    return {"anchor": r.anchor, "name": r.name, "of": r.of, "used": r.used,
            "fraction": round(r.fraction, 4), "value": round(r.value, 1),
            "fallback": r.fallback}
```

and `matchgrade.plan(..., regions=region_rows)`.

`write_match` finds the declaration:

```python
def _find_regions(geo: ReelGeometry) -> tuple["regions_lib.Regions | None", str]:
    """The declaration beside project.json, and what to say about it.

    Three states, and they are three (design §4): a declaration was found; the
    project is known and holds none; or GEOMETRY.json predates the recorded
    project and the file cannot be reached at all. The third must not read as
    the second — "graded against the whole crop because you asked for nothing"
    and "graded against the whole crop because I could not look" are different
    claims about the same pixels."""
    if not geo.project:
        return None, "unreachable"
    p = Path(geo.project).parent / "REGIONS.json"
    if not p.exists():
        return None, ""
    return regions_lib.Regions.from_json(p), str(p)
```

`write_match` calls it, passes `decl` to `conduct`, puts `"regions": where` in
its status dict, and hands `where` to `_report_md`.

`_report_md` gains `regions_at: str = ""` and, after the target line:

```python
    if regions_at == "unreachable":
        head += ("\n\nGEOMETRY.json records no project, so REGIONS.json could not be "
                 "looked for — every anchor is the whole crop. Re-run "
                 "`edl_to_reel --stop-after-geometry` to record it.")
    elif regions_at:
        head += f"\n\nAnchors declared in {regions_at}."
    else:
        head += "\n\nNo REGIONS.json — every anchor is the whole crop."
```

and, per episode, a region table after the existing decision table:

```python
    if any(d.regions for d in decisions):
        lines += ["", "| # | anchor | region | kind | % of frame | value | fallback |",
                  "|---|--------|--------|------|-----------:|------:|----------|"]
        for d in decisions:
            for r in d.regions:
                fb = r["fallback"] or "—"
                lines.append(f"| {d.index} | {r['anchor']} | {r['name']} | {r['of']} "
                             f"| {r['fraction'] * 100:.1f}% | {r['value']:.0f} | {fb} |")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py tests/integration/test_matchgrade.py tests/integration/test_bound_reports.py tests/integration/test_mood_contract.py -q`
Expected: all pass. The last two monkeypatch `measure_crop` and must be updated
for its two-value return — that update is part of this task, not a follow-up.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/matchgrade.py scripts/match_grade.py tests/lib/test_matchgrade.py tests/integration/
git commit -m "feat(match-grade): anchors from declared regions, provenance in both reports"
```

---

### Task 7: The real proof, the battery, and the docs

**Files:**
- Test: `tests/integration/test_named_regions.py` (create)
- Modify: `CLAUDE.md`, `docs/build-status.md`, `docs/backlog.md`,
  `docs/pipeline-map.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`,
  `skills/match-grade/SKILL.md`

- [ ] **Step 1: Write the real-ffmpeg end-to-end proof, each claim with a control**

```python
# tests/integration/test_named_regions.py
"""Real ffmpeg. Three claims, each with a control that must NOT move."""
import json
from pathlib import Path

import pytest

from scripts import color_measure, match_grade
from scripts.lib import regions


@pytest.mark.integration
def test_a_declared_subject_toe_moves_the_toe_and_only_the_toe(tmp_path, golden_ride_segment):
    """Design §0.5's headline, on the fixture: naming the subject as the toe
    reference moves p5 and leaves p50/p95 bit-identical. The control is the
    second and third anchors — if they move, the declaration is not doing what
    it says."""
    manifest, src, route = _episode_inputs(tmp_path, golden_ride_segment)
    plain, plain_rows = color_measure.measure_crop(manifest, src, route)
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    toned, rows = color_measure.measure_crop(manifest, src, route, decl=decl)
    assert toned[1] == plain[1] and toned[2] == plain[2]        # control
    assert rows[0].used == "subject" and rows[0].fallback is None
    assert plain_rows[0].used == "crop"


@pytest.mark.integration
def test_the_region_ruler_and_the_pooled_ruler_agree_on_the_crop(tmp_path, golden_ride_segment):
    """One ruler (Global Constraints). The control is that this is the SAME
    decode: both readings come from one ffmpeg call's bytes."""
    from scripts import process_episode
    from scripts.lib import color
    manifest, src, route = _episode_inputs(tmp_path, golden_ride_segment)
    plan, _, _ = process_episode.plan_and_meta_ungraded(manifest, src, route)
    times = color.sample_times(plan.dur)
    stack = color_measure.crop_region_frames(plan, src, times)
    assert regions.measure(stack, None)["crop"].profile == \
        color_measure.crop_percentiles(plan, src, times)


@pytest.mark.integration
def test_a_run_with_no_declaration_writes_the_same_edl_and_target(tmp_path, golden_ride_segment):
    """The byte-identical default path, through the real driver. The control is
    a second run WITH a declaration, which must differ — otherwise the first
    assertion passes because nothing is wired at all."""
    geo, edl = _geometry_and_edl(tmp_path, golden_ride_segment)
    a = match_grade.write_match(geo)
    before = Path(edl).read_bytes()
    b = match_grade.write_match(geo, force=True)
    assert Path(edl).read_bytes() == before
    assert a["target"] == b["target"] and a["regions"] == ""
    (Path(geo).parent / "REGIONS.json").write_text(json.dumps({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]}))
    c = match_grade.write_match(geo, force=True)
    assert c["target"] != a["target"]                            # control
```

`_episode_inputs` is `tests/integration/test_color_measure.py`'s `_subject_episode`
(Task 4) — import it or copy it; a synthetic subject is what makes the toe claim
discriminating, and `golden_ride_segment` carries no tracked person.
`_geometry_and_edl` builds a one-episode GEOMETRY.json + EDL over that source,
modelled on `tests/integration/test_matchgrade.py`'s existing
`_whole_frame_geometry(tmp_path, sources, dur)` and `_ep(source)`, with a
`project.json` written at the path the geometry records so `_find_regions` can
reach it. Use the range-normalized `golden_ride_segment` anywhere the ride
fixture is wanted — the raw `tests/fixtures/golden_ride.mp4` is `pc` and
`plan_render` refuses it (open backlog row).

Run: `.venv/bin/python -m pytest tests/integration/test_named_regions.py -q`
Expected: 3 passed

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: no failures. Record the pass/skip counts in the task report — the
previous landing was 3401 passed / 1 skipped plus everything added since.

- [ ] **Step 3: Run the mutation battery**

Every row runs `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <selection> -q`
after the edit and must go RED. Restore with `git checkout` is **forbidden**;
restore committed content with `git show HEAD:<path> > <path>`, and for an
uncommitted file save a copy first (`cp <path> <path>.bak`). Quote every
selection — zsh does not word-split an unquoted variable, so a bare `$SEL`
arrives as one argument and pytest prints `no tests ran`, which reads exactly
like a non-discriminating row.

| # | Mutation | Must fail |
|---|---|---|
| 1 | `regions.MIN_REGION_FRAC` 0.01 → 0.0 | `test_a_region_under_the_area_gate_falls_back_to_crop_and_is_named` |
| 2 | `regions.MIN_REGION_FRAC` 0.01 → 0.5 | `test_a_subject_declaration_moves_the_toe_and_nothing_else` |
| 3 | `assemble`: index every anchor's value at `0` instead of its own slot | `test_assemble_takes_each_anchor_from_its_declared_region` |
| 4 | `assemble`'s unorderable branch: fall back per-anchor instead of whole-episode | `test_an_unorderable_profile_drops_the_WHOLE_episode_to_the_crop` |
| 5 | `assemble`: drop the `TONE_MIN_GAP` term, keep only strict increase | `test_a_profile_inside_the_gap_but_ordered_is_still_unorderable` |
| 6 | `assemble`: treat `profile is None` as fraction 0 (merge `no-route` into `too-small`) | `test_an_unmeasured_region_falls_back_as_no_route` |
| 7 | `assemble`: drop the `profile != crop.profile` condition on the ordering check | `test_a_flat_crop_is_not_reported_as_three_unorderable_fallbacks` |
| 8 | `measure`: build the subject mask from `fx1,fy1,fx0,fy0` (swap corners) | `test_measure_reports_the_three_regions_and_their_area_fractions` |
| 9 | `measure`: return `background` as the full frame instead of `~mask` | `test_measure_reports_the_three_regions_and_their_area_fractions` |
| 10 | `_profile`: use `np.percentile` instead of `color.percentiles` | `test_the_crop_region_reading_equals_crop_percentiles_exactly` |
| 11 | `crop_region_frames`: check `len(raw) % (w*h) == 0` instead of the exact count | a new test asking for 3 frames from a stub returning 2 — **write it if none exists** |
| 12 | `crop_region_frames`: prepend the select to the chain string instead of appending it through `with_tail` (the §12 landmine, deliberately) | `test_the_region_ruler_and_the_pooled_ruler_agree_on_the_crop` |
| 13 | `Regions.declared`: return the first declaration regardless of anchor | `test_an_undeclared_anchor_is_the_crop_and_says_so_in_its_name` |
| 21 | `ANCHORS`: reorder to `("mid", "toe", "shoulder")` | `test_the_two_closed_sets_and_their_order` AND `test_assemble_takes_each_anchor_from_its_declared_region` |
| 14 | `Regions.from_dict`: ignore unknown fields instead of refusing | `test_an_extra_field_is_refused_not_ignored` |
| 15 | `Regions.__post_init__`: drop the duplicate-anchor check | `test_one_anchor_declared_twice_is_refused_at_load` |
| 16 | `reframe.path_meta`: pass `crop_ws=plan.crop_ws` unconditionally | `test_path_meta_builds_the_same_sidecar_reframe_writes` |
| 17 | `ReelGeometry.to_dict`: write `project` resolved (`str(Path(...).resolve())`) | `test_reel_geometry_carries_the_project_path_verbatim` |
| 18 | `_find_regions`: return `""` instead of `"unreachable"` for an empty project | `test_a_geometry_with_no_project_says_so_rather_than_reporting_no_declaration` |
| 19 | `_row_dict`: drop the `fallback` key | `test_the_report_prints_the_fallback_and_its_reason` |
| 20 | `ToneDecision.from_dict`: default `regions` to `None` instead of `()` | `test_a_decision_written_before_this_slice_has_no_region_rows` |

A row that comes back GREEN is a coverage hole, not a passing row: close it with
a new test in the same task and record which row found it.

- [ ] **Step 4: Sync the docs**

- `CLAUDE.md` Quick Reference: two rows (design + plan) in the colour block,
  after the grade-sensor-references rows, each with the one-line summary this
  repo's rows carry — including §0.4's finding that the row's own first noun
  loses to the percentile it would replace.
- `docs/build-status.md`: a Done entry naming the measured toe move (−23.2
  delivered / −33.7 source), the one earned anchor, and the two named fallbacks.
- `docs/backlog.md`: R2.1 stays `◐` — its `skin` half is answered by measurement
  and closed as won't-do-on-this-footage, its region half ships. Add the six
  §7 deferred rows. Move nothing to the archive that is not actually closed.
- `docs/pipeline-map.md`: the `match-grade` stage line gains the declaration.
- `CHANGELOG.md` + `.claude-plugin/plugin.json`: **0.10.0** (a new contract file
  and a changed `measure_crop` signature). `tests/test_plugin_manifests.py`
  enforces that the top entry matches the manifest.
- `skills/match-grade/SKILL.md`: what `REGIONS.json` is, where it goes, the two
  closed sets, and that `name` is the author's noun which nothing verifies.

- [ ] **Step 5: Run the whole suite once more**

Run: `.venv/bin/python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_named_regions.py CLAUDE.md docs/ CHANGELOG.md .claude-plugin/plugin.json skills/
git commit -m "docs: 0.10.0 — an anchor is a measurement, and a measurement has a subject"
```
