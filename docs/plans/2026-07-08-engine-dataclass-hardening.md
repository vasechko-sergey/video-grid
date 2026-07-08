# Engine dataclass-hardening + resolution/aspect-agnostic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: COMPLETE (2026-07-09)** — all 11 tasks executed via strict subagent-driven-development on branch `feat/engine-hardening` (commits `78e0fb9`..`4509cd6`), **166 tests green incl. 3 real-ffmpeg goldens**. The committed code is the source of truth; the code blocks below are the pre-implementation guide and differ where two-stage review hardened them. **Review-driven deltas beyond the verbatim blocks:** Task 0 — `CheckResult.to_dict` strips a stale `"pass"` key from `detail`. Task 1 — the `long_edge` test expects `(1214,2160)` not `(1216,2160)` (a plan typo; `_even` floors), plus `dims` guards a non-positive crop, `from_spec` raises the module's own "unparseable"/"string" errors, and `native` normalizes a stray value. Task 2 — `_positive_pair`→`_positive_seq(v,n)` (also covers `color_means`), and `max_speed`/`target_dur`/`n`/`grids` type-guard so wrong-type input raises `ValueError` not `TypeError`. Task 3 — `OPTIONAL` gained `"delivery"` (unknown-key guard). Task 5 — the fake `_iter_detections` yields `_FakeBox` objects (box shape), not bare tuples. Task 7 — body-luma sampling uses `fps=(n+2)/duration` (the plan's `/1` only sampled ~1s → `body_median`=0 defeated the gate). Tasks 5–8 landed their tests in the existing `tests/integration/test_{track,reframe,verify}.py`, not new top-level files. **Known limitation:** the storyboard hero-marker's vertical fraction is `y/src_h` (exact only for `crop_h==src_h`, i.e. 9:16-from-landscape); `fx` is always correct — follow-up can thread `crop_h`/`cy`.

**Goal:** Retype the shipped video engine onto typed dataclasses (config-specs that raise on bad state; wire-contracts that own their JSON), fix the 5 integration-seam bugs + 2 validate holes found in review, and make delivery resolution/aspect fully general (zero hardcoded 9:16 / 1080×1920).

**Architecture:** A new `scripts/lib/models.py` holds every cross-script contract — wire types (`RoutePoint`, `TrackMeta`, `CropPath`, `CheckResult`, `Report`) with `from_dict`/`to_dict` that preserve the current JSON schema, and config-specs (`TrackSpec`, `ReframeSpec`, `CheckSpec`, `StoryboardSpec`, `Delivery`) that validate in `__post_init__` and raise. Each engine script (`track`, `reframe`, `check_episode`, `storyboard`, `process_episode`) is retyped to take a spec / return a dataclass instead of positional primitives and raw dicts, with the matching fix woven in. The manifest gate stays **soft** (`validate()` → `needs_input`); everything below it is **hard** (raises). Design spec: `docs/2026-07-08-engine-dataclass-hardening-design.md`.

**Tech Stack:** Python 3.13 (existing `.venv`), stdlib `dataclasses`/`json`, the shipped engine + `scripts/lib/*`, pytest. No new third-party deps.

**Scope boundaries (deferred — documented, not silently missing):**
- **`project-init` purpose→aspect/quality + `project.json` + canvas inheritance** → the *ingestion* plan (design §D). This plan makes the engine ready for any `(canvas, delivery)`; it does not add the asking step. The manifest gains an optional `delivery` field (default `native`) so the engine is drivable now.
- **Layouts / vidstab / optical-flow / descriptor re-match / router cap-3** → their own plans (unchanged from prior scope).

**Schema-compat guardrail:** `to_dict`/`to_json` must produce JSON that `json.loads` reads back to the same structure and values as today (key *order* may differ — irrelevant to `json.loads`). This keeps every on-disk artifact and the **golden real-ffmpeg fixture** green without regenerating fixtures.

**Current JSON schemas (pin these in the round-trips):**
- `route.json`: `[{"t":float,"x":float,"y":float,"w":float,"h":float}, ...]`
- `route.meta.json`: `{"hero":int|null,"ambiguous":bool,"intent":str,"features":{"<id>":{"n","disp","area","speed","border"}}}`
- `path.json`: `[int, ...]` (parallel to route; `len(path)==len(route)`)
- `report.json` (`indent=2`): `{"checks":{"<name>":{...detail,"pass":bool} | {"status":str}},"overall":bool,"attempt":int,"fail_reasons":[str]}`

**Repo layout produced by this plan:**
```
scripts/
├── lib/
│   ├── models.py        # NEW: wire-contracts + config-specs (Delivery, *Spec, RoutePoint, Report, ...)
│   ├── manifest.py      # import enums from models; +delivery field; +color_means positivity (#G)
│   ├── orchestration.py # +derive_intent (#1); detect_contradictions gains composition + #2 finding
│   ├── geometry.py      # unchanged (crop_size already aspect-general)
│   ├── checks.py        # unchanged numeric core (wrapped by check_episode into CheckResult)
│   └── ...
├── track.py             # retype → TrackSpec / list[RoutePoint] / TrackMeta; honor intent (#1)
├── reframe.py           # iterative _simplify (#5); Delivery dims (#F); retype → ReframeSpec
├── check_episode.py     # retype → CheckSpec / Report; relative black gate (#3)
├── storyboard.py        # retype → StoryboardSpec; marks at sample-time (#4)
└── process_episode.py   # build specs; derive+thread intent; delivery; composition→gate; Report
tests/
├── lib/test_models.py            # NEW
├── lib/test_manifest.py          # +delivery/color_means cases
├── lib/test_orchestration.py     # +derive_intent, +#2
├── test_track.py / test_reframe.py / test_check_episode.py / test_storyboard.py  # migrated
└── integration/test_process_episode.py  # migrated; golden pins delivery
```

---

## Task 0: `models.py` — wire-contracts

Pure, TDD. The typed JSON contracts. `to_dict`/`from_dict` round-trip the schemas pinned above.

**Files:**
- Create: `scripts/lib/models.py`
- Create: `tests/lib/test_models.py`

- [x] **Step 1: Write failing tests**

`tests/lib/test_models.py`:
```python
import json
import pytest
from scripts.lib import models as m


def test_routepoint_roundtrip():
    d = {"t": 0.5, "x": 300.0, "y": 500.0, "w": 140.0, "h": 320.0}
    p = m.RoutePoint.from_dict(d)
    assert (p.t, p.x, p.y, p.w, p.h) == (0.5, 300.0, 500.0, 140.0, 320.0)
    assert p.to_dict() == d


def test_route_json_roundtrip(tmp_path):
    pts = [m.RoutePoint(i / 30, 300 + i, 500, 140, 320) for i in range(3)]
    fp = tmp_path / "route.json"
    m.route_to_json(pts, fp)
    back = m.route_from_json(fp)
    assert [p.to_dict() for p in back] == [p.to_dict() for p in pts]
    assert isinstance(json.loads(fp.read_text()), list)


def test_trackmeta_roundtrip():
    d = {"hero": 3, "ambiguous": True, "intent": "action", "features": {"3": {"n": 5}}}
    tm = m.TrackMeta.from_dict(d)
    assert tm.hero == 3 and tm.ambiguous is True and tm.intent == "action"
    assert tm.to_dict() == d


def test_trackmeta_hero_none():
    tm = m.TrackMeta.from_dict({"hero": None, "ambiguous": False, "intent": "static", "features": {}})
    assert tm.hero is None and tm.to_dict()["hero"] is None


def test_croppath_json_roundtrip(tmp_path):
    fp = tmp_path / "path.json"
    m.CropPath([100, 101, 102]).to_json(fp)
    assert json.loads(fp.read_text()) == [100, 101, 102]
    assert m.CropPath.from_json(fp).xs == [100, 101, 102]
    assert len(m.CropPath([1, 2, 3])) == 3


def test_report_overall_and_fail_reasons():
    checks = {
        "on_line": m.CheckResult("on_line", True, {"ratio": 0.95}),
        "jitter": m.CheckResult("jitter", False, {"worst_reversal": 9.0}),
        "framing": m.CheckResult("framing", None, {"status": "editorial-only"}),
    }
    r = m.Report(checks=checks, attempt=2)
    assert r.overall is False
    assert r.fail_reasons == ["jitter"]


def test_report_to_dict_schema():
    checks = {
        "on_line": m.CheckResult("on_line", True, {"ratio": 0.95}),
        "framing": m.CheckResult("framing", None, {"status": "editorial-only"}),
    }
    d = m.Report(checks=checks, attempt=1).to_dict()
    assert d["checks"]["on_line"] == {"ratio": 0.95, "pass": True}      # pass-bearing
    assert d["checks"]["framing"] == {"status": "editorial-only"}       # status-only, no pass key
    assert d["overall"] is True and d["attempt"] == 1 and d["fail_reasons"] == []


def test_report_from_dict_roundtrip(tmp_path):
    src = {"checks": {"on_line": {"ratio": 0.9, "pass": True},
                      "black_frames": {"boundary_lumas": [120.0], "pass": False},
                      "horizon": {"status": "not-implemented"}},
           "overall": False, "attempt": 3, "fail_reasons": ["black_frames"]}
    r = m.Report.from_dict(src)
    assert r.overall is False and r.fail_reasons == ["black_frames"] and r.attempt == 3
    fp = tmp_path / "report.json"
    r.write(fp)
    assert json.loads(fp.read_text())["checks"]["on_line"]["pass"] is True
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: FAIL (`module 'scripts.lib.models' has no attribute ...`).

- [x] **Step 3: Implement wire-contracts**

`scripts/lib/models.py`:
```python
"""Typed contracts for the engine (design 2026-07-08): wire types that own their
JSON round-trip, and config-specs that validate in __post_init__ and raise. JSON
on disk is unchanged — to_dict/to_json reproduce the current schema."""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RoutePoint:
    t: float
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_dict(cls, d):
        return cls(float(d["t"]), float(d["x"]), float(d["y"]),
                   float(d["w"]), float(d["h"]))

    def to_dict(self):
        return {"t": self.t, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


def route_from_json(path):
    return [RoutePoint.from_dict(d) for d in json.loads(Path(path).read_text())]


def route_to_json(points, path):
    Path(path).write_text(json.dumps([p.to_dict() for p in points]))


@dataclass
class TrackMeta:
    hero: object = None            # int track id or None
    ambiguous: bool = False
    intent: str = "action"
    features: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d):
        return cls(hero=d.get("hero"), ambiguous=bool(d.get("ambiguous", False)),
                   intent=d.get("intent", "action"), features=d.get("features", {}))

    def to_dict(self):
        return {"hero": self.hero, "ambiguous": self.ambiguous,
                "intent": self.intent, "features": self.features}


@dataclass
class CropPath:
    xs: list                       # list[int], parallel to the route

    @classmethod
    def from_json(cls, path):
        return cls([int(x) for x in json.loads(Path(path).read_text())])

    def to_json(self, path):
        Path(path).write_text(json.dumps([int(x) for x in self.xs]))

    def __len__(self):
        return len(self.xs)


@dataclass
class CheckResult:
    name: str
    passed: object                 # bool, or None for editorial/not-implemented
    detail: dict = field(default_factory=dict)

    def to_dict(self):
        if self.passed is None:
            return dict(self.detail)               # status-only ({"status": ...})
        return {**self.detail, "pass": self.passed}


@dataclass
class Report:
    checks: dict                   # {name: CheckResult}
    attempt: int = 1

    @property
    def overall(self):
        return all(c.passed is not False for c in self.checks.values())

    @property
    def fail_reasons(self):
        return [n for n, c in self.checks.items() if c.passed is False]

    def to_dict(self):
        return {"checks": {n: c.to_dict() for n, c in self.checks.items()},
                "overall": self.overall, "attempt": self.attempt,
                "fail_reasons": self.fail_reasons}

    @classmethod
    def from_dict(cls, d):
        checks = {}
        for n, cd in d["checks"].items():
            if "pass" in cd:
                checks[n] = CheckResult(n, cd["pass"],
                                        {k: v for k, v in cd.items() if k != "pass"})
            else:
                checks[n] = CheckResult(n, None, dict(cd))
        return cls(checks=checks, attempt=d.get("attempt", 1))

    def write(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: PASS (8 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: models.py wire-contracts (RoutePoint/TrackMeta/CropPath/Report)"
```

---

## Task 1: `models.Delivery` — resolution/aspect-agnostic dims (#F)

Pure, TDD. The zero-limit delivery policy. Any aspect; `native` never upscales.

**Files:**
- Modify: `scripts/lib/models.py`
- Modify: `tests/lib/test_models.py`

- [x] **Step 1: Write failing tests**

Append to `tests/lib/test_models.py`:
```python
def test_delivery_short_edge_across_aspects():
    # crop aspect drives the derived edge; short edge pinned to 1080; even dims
    assert m.Delivery("short_edge", 1080).dims(1215, 2160) == (1080, 1920)   # 9:16
    assert m.Delivery("short_edge", 1080).dims(1920, 1080) == (1920, 1080)   # 16:9
    assert m.Delivery("short_edge", 1080).dims(1000, 1000) == (1080, 1080)   # 1:1
    assert m.Delivery("short_edge", 1080).dims(864, 1080) == (1080, 1350)    # 4:5


def test_delivery_long_edge():
    assert m.Delivery("long_edge", 2160).dims(1215, 2160) == (1216, 2160)    # long=height
    assert m.Delivery("long_edge", 1920).dims(1920, 1080) == (1920, 1080)


def test_delivery_native_even_no_upscale():
    assert m.Delivery("native").dims(1215, 2160) == (1214, 2160)   # even-adjusted, no scale
    assert m.Delivery("native").dims(607, 1080) == (606, 1080)


def test_delivery_exact():
    assert m.Delivery("exact", (1080, 1920)).dims(999, 999) == (1080, 1920)


def test_delivery_from_spec():
    assert m.Delivery.from_spec(None).mode == "native"
    assert m.Delivery.from_spec("native").mode == "native"
    assert m.Delivery.from_spec("short_edge:1080") == m.Delivery("short_edge", 1080)
    assert m.Delivery.from_spec("exact:1080x1920") == m.Delivery("exact", (1080, 1920))


def test_delivery_rejects_bad():
    with pytest.raises(ValueError, match="mode"):
        m.Delivery("weird")
    with pytest.raises(ValueError, match="short_edge"):
        m.Delivery("short_edge", -5)
    with pytest.raises(ValueError, match="exact"):
        m.Delivery("exact", (1080,))
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k delivery -q`
Expected: FAIL (`Delivery` undefined).

- [x] **Step 3: Implement `Delivery`**

Append to `scripts/lib/models.py`:
```python
@dataclass
class Delivery:
    """Output-dims policy — imposes NO hardcoded resolution or aspect.
    mode: native | short_edge | long_edge | exact."""
    mode: str = "native"
    value: object = None           # int for edges, (w, h) for exact, None for native

    def __post_init__(self):
        if self.mode not in ("native", "short_edge", "long_edge", "exact"):
            raise ValueError(f"Delivery.mode {self.mode!r} invalid — "
                             "native/short_edge/long_edge/exact")
        if self.mode in ("short_edge", "long_edge"):
            if not (isinstance(self.value, int) and self.value > 0):
                raise ValueError(f"Delivery {self.mode} needs a positive int, got {self.value!r}")
        elif self.mode == "exact":
            v = self.value
            if not (isinstance(v, (tuple, list)) and len(v) == 2
                    and all(isinstance(x, int) and x > 0 for x in v)):
                raise ValueError(f"Delivery exact needs (w, h) positive ints, got {v!r}")
            self.value = (int(v[0]), int(v[1]))

    @classmethod
    def from_spec(cls, s):
        # None | "native" | "short_edge:1080" | "long_edge:2160" | "exact:1080x1920"
        if s is None or s == "native":
            return cls("native", None)
        if ":" in s:
            mode, v = s.split(":", 1)
            if mode == "exact":
                w, h = (int(x) for x in v.lower().split("x"))
                return cls("exact", (w, h))
            return cls(mode, int(v))
        raise ValueError(f"delivery spec {s!r} unparseable — "
                         "native|short_edge:N|long_edge:N|exact:WxH")

    @staticmethod
    def _even(n):
        n = int(round(n))
        return n - (n % 2)

    def dims(self, crop_w, crop_h):
        """Even (out_w, out_h) for a crop of size (crop_w, crop_h)."""
        if self.mode == "native":
            return self._even(crop_w), self._even(crop_h)
        if self.mode == "exact":
            return int(self.value[0]), int(self.value[1])
        ar = crop_w / crop_h
        if self.mode == "short_edge":
            if crop_w <= crop_h:
                w, h = self.value, self.value / ar
            else:
                h, w = self.value, self.value * ar
        else:  # long_edge
            if crop_w >= crop_h:
                w, h = self.value, self.value / ar
            else:
                h, w = self.value, self.value * ar
        return self._even(w), self._even(h)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: models.Delivery — resolution/aspect-agnostic output dims (#F)"
```

---

## Task 2: `models` config-specs — raise on bad state

Pure, TDD. `TrackSpec`, `ReframeSpec`, `CheckSpec`, `StoryboardSpec` + the shared enum tuples. Each validates in `__post_init__`.

**Files:**
- Modify: `scripts/lib/models.py`
- Modify: `tests/lib/test_models.py`

- [x] **Step 1: Write failing tests**

Append to `tests/lib/test_models.py`:
```python
def test_trackspec_defaults_and_validation():
    s = m.TrackSpec(src="seg.mp4")
    assert s.model == "yolo11n-seg.pt" and s.intent == "action" and s.seed_bbox is None
    with pytest.raises(ValueError, match="model"):
        m.TrackSpec(src="s.mp4", model="bogus.pt")
    with pytest.raises(ValueError, match="intent"):
        m.TrackSpec(src="s.mp4", intent="cinematic")
    with pytest.raises(ValueError, match="seed_bbox"):
        m.TrackSpec(src="s.mp4", seed_bbox=(1, 2, 3))
    m.TrackSpec(src="s.mp4", seed_bbox=(1, 2, 3, 4))   # 4-tuple ok


def test_reframespec_validation():
    ok = dict(composition="lead", grid="thirds", canvas=(9, 16),
              color_means=(105, 122, 137), delivery=m.Delivery("native"))
    m.ReframeSpec(**ok)
    with pytest.raises(ValueError, match="composition"):
        m.ReframeSpec(**{**ok, "composition": "hero"})
    with pytest.raises(ValueError, match="color_means"):
        m.ReframeSpec(**{**ok, "color_means": (105, 0, 137)})     # #G positivity
    with pytest.raises(ValueError, match="stabilize"):
        m.ReframeSpec(**{**ok, "stabilize": True})
    with pytest.raises(ValueError, match="canvas"):
        m.ReframeSpec(**{**ok, "canvas": (9, 0)})


def test_checkspec_defaults():
    s = m.CheckSpec(composition="lead", grid="thirds", target_dur=3.0,
                    canvas=(9, 16), src_dims=(1920, 1080))
    assert s.attempt == 1 and s.black_floor == 6.0 and s.black_rel == 0.35
    with pytest.raises(ValueError, match="target_dur"):
        m.CheckSpec(composition="lead", grid="thirds", target_dur=0,
                    canvas=(9, 16), src_dims=(1920, 1080))


def test_storyboardspec_validation():
    assert m.StoryboardSpec().n == 6
    with pytest.raises(ValueError, match="n"):
        m.StoryboardSpec(n=0)
    with pytest.raises(ValueError, match="grid"):
        m.StoryboardSpec(grids=("golden",))
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k spec -q`
Expected: FAIL.

- [x] **Step 3: Implement enums + specs**

Prepend the enum tuples near the top of `scripts/lib/models.py` (after imports):
```python
COMPOSITIONS = ("lead", "center", "break")
GRIDS = ("thirds", "phi")
MODELS = ("yolo11n-seg.pt", "yolo11s-seg.pt", "yolo11m-seg.pt")
MOTIONS = ("lateral:right", "lateral:left", "head-on", "static")
INTENTS = ("action", "static")
```

Append the specs to `scripts/lib/models.py`:
```python
def _positive_pair(v):
    return (isinstance(v, (tuple, list)) and len(v) == 2
            and all(isinstance(x, (int, float)) and x > 0 for x in v))


@dataclass
class TrackSpec:
    src: str
    model: str = "yolo11n-seg.pt"
    seed_bbox: object = None
    intent: str = "action"
    fps: object = None

    def __post_init__(self):
        if not (isinstance(self.src, str) and self.src):
            raise ValueError("TrackSpec.src must be a non-empty path")
        if self.model not in MODELS:
            raise ValueError(f"TrackSpec.model {self.model!r} not in {MODELS}")
        if self.intent not in INTENTS:
            raise ValueError(f"TrackSpec.intent {self.intent!r} not in {INTENTS}")
        if self.seed_bbox is not None and not (
                isinstance(self.seed_bbox, tuple) and len(self.seed_bbox) == 4):
            raise ValueError(f"TrackSpec.seed_bbox must be a 4-tuple or None, "
                             f"got {self.seed_bbox!r}")


@dataclass
class ReframeSpec:
    composition: str
    grid: str
    canvas: tuple
    color_means: tuple
    delivery: Delivery
    max_speed: float = 750.0
    stabilize: bool = False

    def __post_init__(self):
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"ReframeSpec.composition {self.composition!r} not in {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"ReframeSpec.grid {self.grid!r} not in {GRIDS}")
        if not _positive_pair(self.canvas):
            raise ValueError(f"ReframeSpec.canvas must be [w, h] positive, got {self.canvas!r}")
        if not (len(self.color_means) == 3
                and all(isinstance(v, (int, float)) and v > 0 for v in self.color_means)):
            raise ValueError(f"ReframeSpec.color_means must be 3 positive means, "
                             f"got {self.color_means!r}")
        if not isinstance(self.delivery, Delivery):
            raise ValueError("ReframeSpec.delivery must be a Delivery")
        if self.max_speed <= 0:
            raise ValueError(f"ReframeSpec.max_speed must be positive, got {self.max_speed}")
        if self.stabilize:
            raise ValueError("ReframeSpec.stabilize must be False — the manifest refuses "
                             "stabilize upstream (needs_input); a True here is a bug")


@dataclass
class CheckSpec:
    composition: str
    grid: str
    target_dur: float
    canvas: tuple
    src_dims: tuple
    attempt: int = 1
    black_floor: float = 6.0
    black_rel: float = 0.35

    def __post_init__(self):
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"CheckSpec.composition {self.composition!r} not in {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"CheckSpec.grid {self.grid!r} not in {GRIDS}")
        if self.target_dur <= 0:
            raise ValueError(f"CheckSpec.target_dur must be positive, got {self.target_dur}")
        if not _positive_pair(self.canvas):
            raise ValueError(f"CheckSpec.canvas must be [w, h] positive, got {self.canvas!r}")
        if not _positive_pair(self.src_dims):
            raise ValueError(f"CheckSpec.src_dims must be [w, h] positive, got {self.src_dims!r}")


@dataclass
class StoryboardSpec:
    n: int = 6
    grids: tuple = ("thirds",)
    marks: object = None

    def __post_init__(self):
        if self.n < 1:
            raise ValueError(f"StoryboardSpec.n must be >= 1, got {self.n}")
        for g in self.grids:
            if g not in GRIDS:
                raise ValueError(f"StoryboardSpec.grid {g!r} not in {GRIDS}")
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: models config-specs (Track/Reframe/Check/Storyboard) that raise on bad state"
```

---

## Task 3: `manifest.py` — import enums from models, `delivery` field, `color_means` positivity (#G)

DRY the enums (single source in `models`), add the optional `delivery` field (default `native`; Plan 2 populates it from `project.json`), and add `color_means` positivity to the **soft** gate (#G).

**Files:**
- Modify: `scripts/lib/manifest.py`
- Modify: `tests/lib/test_manifest.py`

- [x] **Step 1: Write failing tests**

Append to `tests/lib/test_manifest.py`:
```python
def test_delivery_defaults_native():
    m = mf.Manifest.from_dict(_ok_dict())
    assert m.delivery == "native"


def test_delivery_passthrough():
    m = mf.Manifest.from_dict(_ok_dict(delivery="short_edge:1080"))
    assert m.delivery == "short_edge:1080"
    assert mf.validate(m) == []


def test_validate_bad_delivery():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(delivery="huge:9999x")))
    assert any("delivery" in p for p in problems)


def test_validate_color_means_nonpositive():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(color_means=[0, 122, 137])))
    assert any("color_means" in p for p in problems)
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py -k "delivery or color_means" -q`
Expected: FAIL.

- [x] **Step 3: Implement**

In `scripts/lib/manifest.py`, replace the local enum block with an import from `models` and delete the now-duplicated tuples (`COMPOSITIONS`, `GRIDS`, `MODELS`, `MOTIONS`):
```python
from scripts.lib.models import (COMPOSITIONS, GRIDS, MODELS, MOTIONS, Delivery)
LAYOUTS_SUPPORTED = ("fill",)          # kept local — a manifest-slice refusal, not a model enum
```

Add `delivery` to the dataclass (after `model`):
```python
    delivery: str = "native"
```

In `from_dict`, carry it (explicit null → default, like `model`):
```python
        delivery = d.get("delivery")
        # ... in the cls(...) call:
        delivery=delivery if delivery is not None else "native",
```

In `validate`, add the two checks (append before `return problems`):
```python
    if not (isinstance(m.color_means, tuple) and len(m.color_means) == 3
            and all(isinstance(v, (int, float)) and v > 0 for v in m.color_means)):
        problems.append(f"color_means must be 3 positive channel means [R, G, B]; "
                        f"got {m.color_means!r}")
    try:
        Delivery.from_spec(m.delivery)
    except (ValueError, TypeError) as e:
        problems.append(f"delivery {m.delivery!r} invalid — {e}")
```

(Delete the old `color_means` length-only check so there is one positivity check, not two.)

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py -q`
Expected: PASS (existing + 4 new).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/manifest.py tests/lib/test_manifest.py
git commit -m "feat: manifest imports enums from models, +delivery field, +color_means positivity (#G)"
```

---

## Task 4: `orchestration.py` — `derive_intent` (#1) + `detect_contradictions` composition/#2

Pure, TDD. The two orchestration decisions that fix wrong-hero (#1) and lead-vs-nonlateral (#2).

**Files:**
- Modify: `scripts/lib/orchestration.py`
- Modify: `tests/lib/test_orchestration.py`

- [x] **Step 1: Write failing tests**

Append to `tests/lib/test_orchestration.py`:
```python
def test_derive_intent_from_manifest():
    # center or declared static/head-on → static; lateral or infer+lead → action
    assert orch.derive_intent("center", None) == "static"
    assert orch.derive_intent("lead", "static") == "static"
    assert orch.derive_intent("lead", "head-on") == "static"
    assert orch.derive_intent("lead", "lateral:right") == "action"
    assert orch.derive_intent("lead", None) == "action"          # infer → lateral-action default
    assert orch.derive_intent("break", None) == "action"


def test_lead_over_nonlateral_is_a_contradiction():
    # lead composition but the tracker route is not lateral → stop_and_report, no wasted reframes
    static_route = [dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)]  # no dx
    findings = orch.detect_contradictions(motion=None, hero=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_over_lateral_is_fine():
    route = _route_right()
    findings = orch.detect_contradictions(motion=None, hero=None, route=route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert all(f["reason"] != "composition-motion-mismatch" for f in findings)


def test_center_over_nonlateral_is_fine():
    static_route = [dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)]
    findings = orch.detect_contradictions(motion=None, hero=None, route=static_route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="center")
    assert findings == []
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -k "intent or nonlateral or composition" -q`
Expected: FAIL.

- [x] **Step 3: Implement**

Add `derive_intent` to `scripts/lib/orchestration.py`:
```python
def derive_intent(composition, motion):
    """Hero-scoring intent from MANIFEST signal only (§6.1a). Must be manifest-
    only: intent picks the hero DURING tracking, before a hero route exists to
    classify(). center, or a declared static/head-on motion → 'static' (size +
    duration win); lateral, or infer with a lead/break composition → 'action'."""
    if composition == "center":
        return "static"
    if motion in ("static", "head-on"):
        return "static"
    return "action"
```

Change `detect_contradictions` to accept `composition` and add the #2 finding. New signature and the added block (place the new check after the hero-ambiguous block, before the `if motion:` block):
```python
def detect_contradictions(motion, hero, route, track_meta, src_w, src_h, composition=None):
    ...
    if composition == "lead":
        obs_type, _ = classify(route, src_w, src_h)
        if obs_type != "lateral":
            findings.append({"reason": "composition-motion-mismatch",
                             "detail": f"composition 'lead' needs lateral motion, but the "
                                       f"tracker sees {obs_type} — set composition to "
                                       f"'center', or fix the window/segment"})
    ...
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q`
Expected: PASS (existing + new).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/orchestration.py tests/lib/test_orchestration.py
git commit -m "feat: derive_intent (#1) + lead-over-nonlateral contradiction (#2)"
```

---

## Task 5: `track.py` — retype to `TrackSpec` / `RoutePoint` / `TrackMeta`, honor intent (#1)

`build_route` takes a `TrackSpec` (carrying `intent`), returns `list[RoutePoint]`, writes a `TrackMeta` sidecar. The `intent` default of `"action"` is gone from the call path — the caller (Task 9) supplies the derived value.

**Files:**
- Modify: `scripts/track.py`
- Modify/Create: `tests/test_track.py` (migrate existing track tests)

- [x] **Step 1: Write/adjust the failing test**

In `tests/test_track.py`, add a test that pins the spec API + `RoutePoint` return (keep existing `_pick_hero`/`_seed_track` unit tests unchanged):
```python
from scripts.lib import models


def test_build_route_uses_spec_and_returns_routepoints(monkeypatch, tmp_path):
    # two tracks: id 1 stands still (big), id 2 crosses fast. intent must decide.
    frames = []
    for i in range(6):
        frames.append((i, [(1, 900, 500, 300, 600), (2, 100 + i * 200, 500, 120, 300)]))
    monkeypatch.setattr(track, "_iter_detections", lambda src, model_path=None: iter(frames))
    monkeypatch.setattr(track, "_probe_meta", lambda src: (30.0, 1920, 1080))

    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="seg.mp4", intent="static", fps=30.0)
    route = track.build_route(spec, out=str(out))
    assert route and isinstance(route[0], models.RoutePoint)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.hero == 1                      # static intent → the still, large subject
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_track.py -q`
Expected: FAIL (`build_route` signature).

- [x] **Step 3: Implement the retype**

Change `build_route` to take a `TrackSpec`. New signature + body wiring (keep `_iter_detections`, `_seed_track`, `_track_features`, `_pick_hero`, `_probe_meta` as-is):
```python
from scripts.lib.models import RoutePoint, TrackMeta, TrackSpec

def build_route(spec, out):
    fps, src_w, src_h = (spec.fps, None, None)
    if fps is None:
        fps, src_w, src_h = _probe_meta(spec.src)
    per_frame = []
    for idx, boxes in _iter_detections(spec.src, model_path=spec.model):
        dets = []
        for b in boxes:
            if b.id is None:
                continue
            x, y, w, h = [float(v) for v in b.xywh[0]]
            dets.append((int(b.id[0]), x, y, w, h))
        per_frame.append((idx, dets))

    feats = _track_features(per_frame, src_w=src_w, src_h=src_h)
    hero, ambiguous = None, False
    if spec.seed_bbox is not None:
        hero = _seed_track(per_frame, spec.seed_bbox)
    if hero is None:
        hero, ambiguous = _pick_hero(feats, spec.intent)

    meta = TrackMeta(hero=hero, ambiguous=ambiguous, intent=spec.intent,
                     features={str(k): {kk: f[kk] for kk in
                                        ("n", "disp", "area", "speed", "border")}
                               for k, f in feats.items()})
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta.to_dict()))

    route = []
    for idx, dets in per_frame:
        pick = next((d for d in dets if d[0] == hero), None)
        if pick:
            _, x, y, w, h = pick
            route.append(RoutePoint(t=idx / fps, x=x, y=y, w=w, h=h))
    from scripts.lib.models import route_to_json
    route_to_json(route, out)
    return route
```

Update `__main__` to build a `TrackSpec` from argv (the `--seed`/`--intent`/`--model`/`--fps` args map onto the spec fields):
```python
    seed = tuple(float(v) for v in a.seed.split(",")) if a.seed else None
    spec = TrackSpec(src=a.src, model=a.model, seed_bbox=seed, intent=a.intent, fps=a.fps)
    build_route(spec, a.out)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_track.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/track.py tests/test_track.py
git commit -m "refactor: track.build_route takes TrackSpec, returns RoutePoints, honors intent (#1)"
```

---

## Task 6: `reframe.py` — iterative `_simplify` (#5) + `Delivery` dims (#F) + retype to `ReframeSpec`

Three changes in one file: make Douglas-Peucker iterative (no recursion limit), replace the 1080×1920 hardcode with `Delivery.dims`, and take a `ReframeSpec` + `list[RoutePoint]`.

**Files:**
- Modify: `scripts/reframe.py`
- Modify/Create: `tests/test_reframe.py`

- [x] **Step 1: Write failing tests**

In `tests/test_reframe.py`:
```python
from scripts.lib import models


def test_simplify_iterative_no_recursion_on_long_path():
    # a saw-tooth 5000-frame path would blow Python's recursion limit if DP recursed
    times = [i / 30 for i in range(5000)]
    path = [i % 7 for i in range(5000)]
    knots = reframe._simplify(path, times)          # must not raise RecursionError
    assert knots[0][0] == times[0] and knots[-1][0] == times[-1]


def test_reframe_delivery_dims_native(monkeypatch, tmp_path):
    # native delivery on a 4K source → crop-native even dims, NOT 1080x1920
    route = [models.RoutePoint(i / 30, 1900 + i * 5, 1080, 200, 480) for i in range(10)]
    models.route_to_json(route, tmp_path / "r.json")
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0))
    captured = {}
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **k: captured.setdefault("cmd", cmd))
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=models.Delivery("native"))
    reframe.reframe(spec, "src.mp4", str(tmp_path / "r.json"), str(tmp_path / "out.mp4"),
                    str(tmp_path / "path.json"))
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "scale=1214:2160" in vf          # 4K 9:16 crop 1215x2160 → even native, no upscale
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_reframe.py -k "iterative or delivery" -q`
Expected: FAIL.

- [x] **Step 3a: Iterative `_simplify` (#5)**

Replace the recursive `dp` inside `_simplify` with an explicit stack (same eps-cap loop around it):
```python
    def run(eps):
        keep = {0, len(pts) - 1}
        stack = [(0, len(pts) - 1)]
        while stack:
            lo, hi = stack.pop()
            if hi - lo < 2:
                continue
            (t0, x0), (t1, x1) = pts[lo], pts[hi]
            worst, wi = 0.0, None
            for i in range(lo + 1, hi):
                t, x = pts[i]
                xh = x0 + (x1 - x0) * ((t - t0) / (t1 - t0)) if t1 != t0 else x0
                if abs(x - xh) > worst:
                    worst, wi = abs(x - xh), i
            if worst > eps and wi is not None:
                keep.add(wi)
                stack.append((lo, wi))
                stack.append((wi, hi))
        return [pts[i] for i in sorted(keep)]
```

- [x] **Step 3b: `Delivery` dims (#F) + `ReframeSpec` retype**

`src`/`route_path`/`out`/`path_out` stay explicit args (per-call I/O, not config); only the tuning primitives live in `spec`. New signature and changed body (keep `compute_path`, `_xexpr`, `_probe`, `color`, `geometry`):
```python
from scripts.lib.models import ReframeSpec, RoutePoint, CropPath, route_from_json

def reframe(spec, src, route_path, out, path_out):
    src_w, src_h, fps = _probe(src)
    route = route_from_json(route_path)              # list[RoutePoint]
    if not route:
        raise ValueError(f"route {route_path} is empty — tracker found no hero frames; "
                         "check route.meta.json (ambiguous? wrong seed pin?) before reframing")
    route_dicts = [p.to_dict() for p in route]       # compute_path/classify still take dicts
    motion = classify(route_dicts, src_w, src_h)
    path = compute_path(route_dicts, spec.composition, spec.grid, spec.canvas,
                        (src_w, src_h), motion, max_step=spec.max_speed / fps)
    CropPath(path).to_json(path_out)

    crop_w, crop_h = g.crop_size(spec.canvas[0], spec.canvas[1], src_w, src_h)
    out_w, out_h = spec.delivery.dims(crop_w, crop_h)      # #F: was hardcoded 1080x1920
    rr, gg, bb = color.gains_for_means(spec.color_means)
    times = [p.t for p in route]
    xexpr = _xexpr(path, times)
    mean_y = sum(p.y for p in route) / len(route)
    cy = g.crop_y(mean_y, crop_h, src_h)
    vf = (f"crop={crop_w}:{crop_h}:x='{xexpr}':y={cy},"
          f"scale={out_w}:{out_h},{color.mixer_arg(rr, gg, bb)},"
          f"fps={fps:.6g},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    proc.run(cmd)
    return out
```
Delete the `if stabilize:` block (stabilize is refused at the manifest gate and by `ReframeSpec.__post_init__`; it never reaches here). Delete the `if canvas == (9,16): 1080,1920 else ...` block (replaced by `delivery.dims`).

Update `__main__` to build a `ReframeSpec` + `Delivery` from argv:
```python
    cw, ch = (int(v) for v in a.canvas.split(":"))
    means = tuple(float(v) for v in a.color.split(","))
    spec = ReframeSpec(composition=a.composition, grid=a.grid, canvas=(cw, ch),
                       color_means=means, delivery=Delivery.from_spec(a.delivery))
    reframe(spec, a.src, a.route, a.out, a.path_out)
```
Add `--delivery` (default `None`) to the argparser; drop `--stabilize`.

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_reframe.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/reframe.py tests/test_reframe.py
git commit -m "refactor: reframe takes ReframeSpec; iterative DP (#5); Delivery dims, no 9:16/1080 hardcode (#F)"
```

---

## Task 7: `check_episode.py` — retype to `CheckSpec` / `Report` + relative black gate (#3)

`run` takes a `CheckSpec`, returns a `Report`. Black-frame check goes relative (floor + mid-clip median).

**Files:**
- Modify: `scripts/check_episode.py`
- Modify/Create: `tests/test_check_episode.py`

- [x] **Step 1: Write failing tests**

```python
from scripts.lib import models


def test_boundary_black_relative_passes_uniformly_dark(monkeypatch):
    # dark night clip: boundary ~10, body ~12 -> NOT a defect
    monkeypatch.setattr(check_episode, "_frame_lumas",
                        lambda clip, where, n=3: [10.0, 11.0] if where == "boundary" else [12.0, 12.0])
    res = check_episode._black_frames_check("clip.mp4", black_floor=6.0, black_rel=0.35)
    assert res["pass"] is True


def test_boundary_black_relative_fails_black_cut(monkeypatch):
    # seek-landmine: boundary ~0, body ~120 -> defect
    monkeypatch.setattr(check_episode, "_frame_lumas",
                        lambda clip, where, n=3: [0.5, 0.2] if where == "boundary" else [120.0, 118.0])
    res = check_episode._black_frames_check("clip.mp4", black_floor=6.0, black_rel=0.35)
    assert res["pass"] is False


def test_run_returns_report(monkeypatch, tmp_path):
    route = [models.RoutePoint(i / 30, 300 + i * 90, 500, 140, 320) for i in range(10)]
    models.route_to_json(route, tmp_path / "route.json")
    models.CropPath([300 + i * 90 - 200 for i in range(10)]).to_json(tmp_path / "path.json")
    monkeypatch.setattr(check_episode, "_duration", lambda clip: 3.0)
    monkeypatch.setattr(check_episode, "_black_frames_check",
                        lambda clip, **k: {"pass": True, "boundary_lumas": [120.0]})
    spec = models.CheckSpec(composition="lead", grid="thirds", target_dur=3.0,
                            canvas=(9, 16), src_dims=(1920, 1080))
    report = check_episode.run(str(tmp_path / "clip.mp4"), str(tmp_path / "route.json"),
                               str(tmp_path / "path.json"), spec, str(tmp_path / "report.json"))
    assert isinstance(report, models.Report)
    assert "on_line" in report.checks and report.attempt == 1
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_check_episode.py -q`
Expected: FAIL.

- [x] **Step 3: Implement**

Add luma helpers + the relative gate, replacing `_boundary_luma`:
```python
def _frame_lumas(clip, where, n=3):
    """Mean luma of n frames at 'boundary' (head+tail) or 'body' (interior)."""
    import tempfile
    from PIL import Image, ImageStat
    lumas = []
    with tempfile.TemporaryDirectory() as tmp:
        if where == "boundary":
            proc.run(["ffmpeg", "-y", "-i", clip, "-frames:v", str(n), f"{tmp}/head%02d.png"])
            proc.run(["ffmpeg", "-y", "-sseof", "-0.5", "-i", clip, f"{tmp}/tail%02d.png"])
            files = sorted(Path(tmp).glob("head*.png")) + sorted(Path(tmp).glob("tail*.png"))[-n:]
        else:  # body: sample the interior via an even fps grab, drop the extremes
            proc.run(["ffmpeg", "-y", "-i", clip, "-vf", f"fps={n + 2}/1",
                      "-frames:v", str(n + 2), f"{tmp}/b%02d.png"])
            files = sorted(Path(tmp).glob("b*.png"))[1:-1]
        for f in files:
            lumas.append(ImageStat.Stat(Image.open(f).convert("L")).mean[0])
    return lumas


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _black_frames_check(clip, black_floor=6.0, black_rel=0.35):
    boundary = _frame_lumas(clip, "boundary")
    body = _frame_lumas(clip, "body") or boundary
    ref = _median(body)
    # a boundary frame is a defect only if near-black AND far below the clip body
    worst = min(boundary) if boundary else ref
    is_black = worst < black_floor and worst < black_rel * ref
    return {"pass": not is_black, "boundary_lumas": [round(l, 1) for l in boundary],
            "body_median": round(ref, 1)}
```

Retype `run` to take a `CheckSpec` and return a `Report` (assemble `CheckResult`s):
```python
from scripts.lib.models import CheckResult, Report, route_from_json, CropPath

def run(clip, route_path, path_path, spec, out):
    route = [p.to_dict() for p in route_from_json(route_path)]
    path = CropPath.from_json(path_path).xs
    crop_w, _ = geometry.crop_size(spec.canvas[0], spec.canvas[1],
                                   spec.src_dims[0], spec.src_dims[1])
    _, direction = classify(route, spec.src_dims[0], spec.src_dims[1])
    direction = direction or "right"
    checks = {}
    if spec.composition == "center":
        d = checks_mod.centered(route, path, crop_w)
        checks["centered"] = CheckResult("centered", d["pass"], {k: v for k, v in d.items() if k != "pass"})
    elif spec.composition == "lead":
        left, right = geometry.grid_lines(spec.grid)
        tf = left if direction == "right" else right
        d = checks_mod.on_line(route, path, crop_w, tf)
        checks["on_line"] = CheckResult("on_line", d["pass"], {k: v for k, v in d.items() if k != "pass"})
    elif spec.composition == "break":
        checks["framing"] = CheckResult("framing", None, {"status": "editorial-only"})
    else:
        raise ValueError(f"unknown composition: {spec.composition!r}")

    dj = checks_mod.jitter(path, direction, max_reversal=max(2.0, crop_w * 0.005))
    checks["jitter"] = CheckResult("jitter", dj["pass"], {k: v for k, v in dj.items() if k != "pass"})
    dc = checks_mod.continuity(route, spec.src_dims[0])
    checks["continuity"] = CheckResult("continuity", dc["pass"], {k: v for k, v in dc.items() if k != "pass"})
    dl = checks_mod.length(_duration(clip), spec.target_dur)
    checks["length"] = CheckResult("length", dl["pass"], {k: v for k, v in dl.items() if k != "pass"})
    bf = _black_frames_check(clip, black_floor=spec.black_floor, black_rel=spec.black_rel)
    checks["black_frames"] = CheckResult("black_frames", bf["pass"], {k: v for k, v in bf.items() if k != "pass"})
    checks["horizon"] = CheckResult("horizon", None, {"status": "not-implemented"})
    checks["head_power_point"] = CheckResult("head_power_point", None, {"status": "not-implemented"})

    report = Report(checks=checks, attempt=spec.attempt)
    report.write(out)
    return report
```
Import the numeric module under an alias to avoid the name clash: `from scripts.lib import checks as checks_mod`. Update `__main__` to build a `CheckSpec` from argv and pass it.

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_check_episode.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/check_episode.py tests/test_check_episode.py
git commit -m "refactor: check_episode takes CheckSpec, returns Report; relative black-frame gate (#3)"
```

---

## Task 8: `storyboard.py` — retype to `StoryboardSpec` + marks at sample-time (#4)

`build` takes a `StoryboardSpec`; the hero marks are computed at the **same times** the frames are sampled, by interpolating route/path on `t` (not by route index).

**Files:**
- Modify: `scripts/storyboard.py`
- Modify/Create: `tests/test_storyboard.py`

- [x] **Step 1: Write failing tests**

```python
from scripts.lib import models


def test_marks_at_times_interpolates_on_t():
    # route with a time GAP: index-sampling would misplace the mark; time-sampling won't
    route = [models.RoutePoint(0.0, 100, 500, 100, 200),
             models.RoutePoint(0.1, 200, 500, 100, 200),
             models.RoutePoint(1.0, 1000, 500, 100, 200)]   # big gap in t
    path = models.CropPath([0, 100, 900])
    marks = storyboard.marks_at_times(route, path, crop_w=200, src_h=1000,
                                      times=[0.0, 0.5, 1.0])
    # at t=1.0: x=1000, crop_x=900 -> fx=(1000-900)/200=0.5 ; fy=500/1000=0.5
    assert abs(marks[-1][0] - 0.5) < 1e-6 and abs(marks[-1][1] - 0.5) < 1e-6
    assert len(marks) == 3


def test_build_marks_align_to_sampled_frames(monkeypatch, tmp_path):
    # build samples n frames by TIME; it must derive marks at those same times
    route = [models.RoutePoint(i / 10, 100 + i * 90, 500, 100, 200) for i in range(11)]
    path = models.CropPath([50 + i * 90 for i in range(11)])
    monkeypatch.setattr(storyboard, "_duration", lambda src: 1.0)
    seen = {}

    def fake_sample(src, n, tmp, times):     # new signature: sample AT given times
        seen["times"] = times
        for i in range(n):
            (Path(tmp) / f"f{i:02d}.png").write_bytes(b"")
        return sorted(Path(tmp).glob("f*.png"))
    monkeypatch.setattr(storyboard, "_sample_frames", fake_sample)
    monkeypatch.setattr(storyboard.Image, "open", lambda f: _Img())   # stub PIL
    spec = models.StoryboardSpec(n=4, grids=("thirds",))
    storyboard.build(str(tmp_path / "clip.mp4"), str(tmp_path / "sheet.jpg"),
                     spec, route=route, path=path)
    assert len(seen["times"]) == 4
```

(Provide a tiny `_Img` stub in the test module with `.convert`, `.size`, paste no-ops as needed, or assert only on `seen["times"]` and skip the PIL path with an early return in `build` when `route`/`path` given but frames are stubs. Keep the stub minimal.)

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_storyboard.py -q`
Expected: FAIL.

- [x] **Step 3: Implement**

Add time-interpolated marks and make sampling time-driven:
```python
from scripts.lib.models import StoryboardSpec, RoutePoint, CropPath

def _interp(ts, xs, t):
    if t <= ts[0]:
        return xs[0]
    if t >= ts[-1]:
        return xs[-1]
    for i in range(1, len(ts)):
        if t <= ts[i]:
            f = (t - ts[i - 1]) / (ts[i] - ts[i - 1]) if ts[i] != ts[i - 1] else 0.0
            return xs[i - 1] + f * (xs[i] - xs[i - 1])
    return xs[-1]


def marks_at_times(route, path, crop_w, src_h, times):
    """(fx, fy) subject fractions in the OUTPUT frame at each sample TIME —
    interpolate route x/y and crop-x on t, so marks align with the frames
    storyboard samples by time (fixes index/time desync on gappy routes)."""
    if not route or len(route) != len(path):
        raise ValueError(f"route/path must be non-empty parallel arrays, "
                         f"got {len(route)} vs {len(path)}")
    ts = [p.t for p in route]
    xs = [p.x for p in route]
    ys = [p.y for p in route]
    cxs = path.xs
    marks = []
    for t in times:
        x = _interp(ts, xs, t)
        y = _interp(ts, ys, t)
        cx = _interp(ts, cxs, t)
        marks.append(((x - cx) / crop_w, y / src_h))
    return marks


def _sample_times(dur, n):
    return [(k + 0.5) * dur / n for k in range(n)]
```

Change `_sample_frames` to accept explicit `times` (seek each), and `build` to take a `StoryboardSpec` and optional `route`/`path`, computing marks internally at the sample times:
```python
def _sample_frames(src, n, tmp, times):
    files = []
    for i, t in enumerate(times):
        f = f"{tmp}/f{i:02d}.png"
        proc.run(["ffmpeg", "-y", "-ss", f"{t}", "-i", src, "-frames:v", "1", f])
        files.append(Path(f))
    return files


def build(src, out, spec, route=None, path=None, crop_w=None, src_h=None):
    """Contact sheet + grid/hero-mark overlays. When route/path/crop_w/src_h are
    all given, marks are computed at the SAME sample times as the frames (fixes
    #4); otherwise spec.marks (if any) is used positionally."""
    dur = _duration(src)
    times = _sample_times(dur, spec.n)
    marks = spec.marks
    if None not in (route, path, crop_w, src_h):
        marks = marks_at_times(route, path, crop_w, src_h, times)
    with tempfile.TemporaryDirectory() as tmp:
        frames = _sample_frames(src, spec.n, tmp, times)
        imgs = [_overlay(Image.open(f).convert("RGB"), spec.grids,
                         mark=(marks[i] if marks and i < len(marks) else None))
                for i, f in enumerate(frames)]
        if not imgs:
            raise RuntimeError("no frames sampled")
        cols = min(len(imgs), 4)
        rows = (len(imgs) + cols - 1) // cols
        tw, th = imgs[0].size
        sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
        for i, im in enumerate(imgs):
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
        sheet.save(out, quality=90)
    return out, times
```

Sampling and marking now live in one place (the point of #4): `build` computes `times` once, derives `marks` at those same times when `route`/`path`/`crop_w`/`src_h` are supplied, and returns `(out, times)`. Update `__main__` to build a `StoryboardSpec` (`--n`/`--grids`), and **delete the old index-based `marks_from_route_path`** — Task 9 no longer calls it.

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_storyboard.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/storyboard.py tests/test_storyboard.py
git commit -m "refactor: storyboard takes StoryboardSpec; hero marks at sample-time, not route-index (#4)"
```

---

## Task 9: `process_episode.py` — build specs, derive+thread intent, delivery, composition→gate, consume `Report`

The shell now constructs the typed specs, derives `intent` (#1), passes `composition` to the contradiction gate (#2), threads `delivery`, and reads a `Report` object.

**Files:**
- Modify: `scripts/process_episode.py`
- Modify: `tests/integration/test_process_episode.py`

- [x] **Step 1: Adjust the failing tests**

Update the stubs in `tests/integration/test_process_episode.py` to the new signatures (the shell drives `track.build_route(spec, out=...)`, `reframe.reframe(spec, src, route, out, path_out)`, `check_episode.run(clip, route, path, spec, out) -> Report`, `storyboard.build(src, out, spec, route=, path=, crop_w=, src_h=)`), and add:
```python
def test_intent_derived_for_center(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)      # _stub_engine records TrackSpec.intent
    pe.process_episode(_manifest(tmp_path, composition="center"), project_dir=str(tmp_path))
    assert calls["track_intent"] == "static"


def test_delivery_threaded_to_reframe(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path, delivery="exact:1080x1920"),
                       project_dir=str(tmp_path))
    assert calls["reframe_delivery"].mode == "exact"


def test_lead_nonlateral_stops(monkeypatch, tmp_path):
    # a static route under a lead manifest → composition-motion-mismatch, no reframe
    _stub_engine(monkeypatch, tmp_path,
                 route=[dict(t=i / 30, x=500, y=500, w=140, h=320) for i in range(10)])
    def boom(*a, **k): raise AssertionError("reframe must not run on composition mismatch")
    monkeypatch.setattr(pe.reframe, "reframe", boom)
    result = pe.process_episode(_manifest(tmp_path, composition="lead"), project_dir=str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert any(f["reason"] == "composition-motion-mismatch" for f in result["findings"])
```
(Extend `_stub_engine` to capture `TrackSpec.intent`, the `ReframeSpec.delivery`, and to return a `Report` from the fake `check_episode.run`.)

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -q`
Expected: FAIL.

- [x] **Step 3: Implement the shell wiring**

Rewrite the body of `process_episode` to build specs (imports: `from scripts.lib.models import TrackSpec, ReframeSpec, CheckSpec, StoryboardSpec, Delivery, route_from_json, CropPath`). Key changed sections:

Tracking with a derived-intent `TrackSpec`:
```python
    intent = orch.derive_intent(m.composition, m.motion)
    delivery = Delivery.from_spec(m.delivery)
    if route_path is None:
        rp = str(Path(project_dir) / "route.json")
        tspec = TrackSpec(src=m.segment, model=m.model,
                          seed_bbox=m.hero if orch.is_seed_pin(m.hero) else None,
                          intent=intent)
        _timed("track", lambda: track.build_route(tspec, out=rp))
        route, track_meta = _load_route(rp)
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0
```

Contradiction gate with `composition` (the existing one-time probe
`src_w, src_h, _fps = reframe._probe(m.segment)` stays, right before this — it
feeds the gate, `CheckSpec.src_dims`, and `crop_size`):
```python
    findings = orch.detect_contradictions(m.motion, m.hero, route, track_meta,
                                          src_w, src_h, composition=m.composition)
```

Reframe/check loop with specs (note `_load_route` still returns route as list-of-dicts for the gate; the engine reads its own typed route from `rp`):
```python
    rspec_base = dict(composition=m.composition, grid=m.grid, canvas=m.canvas,
                      color_means=m.color_means, delivery=delivery)
    for attempt in range(1, max_attempts + 1):
        rspec = ReframeSpec(**rspec_base, max_speed=params["max_speed"])
        _timed("reframe", lambda: reframe.reframe(rspec, m.segment, rp, m.out_path, path_out))
        cspec = CheckSpec(composition=m.composition, grid=m.grid, target_dur=m.target_dur,
                          canvas=m.canvas, src_dims=(src_w, src_h), attempt=attempt)
        report = _timed("check", lambda: check_episode.run(m.out_path, rp, path_out, cspec,
                                                           str(Path(project_dir) / "report.json")))
        if report.overall:
            sheet = str(Path(project_dir) / "storyboard.jpg")
            crop_w, _ = geometry.crop_size(m.canvas[0], m.canvas[1], src_w, src_h)
            route_pts = route_from_json(rp)
            path_obj = CropPath.from_json(path_out)
            sspec = StoryboardSpec(n=6, grids=(m.grid,))
            _timed("storyboard", lambda: storyboard.build(
                m.out_path, sheet, sspec, route=route_pts, path=path_obj,
                crop_w=crop_w, src_h=src_h))
            return {"status": "mechanical_pass", "clip": m.out_path, "report": report.to_dict(),
                    "storyboard": sheet, "attempt": attempt, "timings": timings, "degraded": None}
        esc = orch.escalation(attempt, report.fail_reasons, max_attempts)
        if esc:
            return {"status": "escalate", **esc, "report": report.to_dict(),
                    "attempt": attempt, "timings": timings}
        params = orch.adjust_reframe_params(params, report.fail_reasons)
```
(`report.to_dict()` on the way out preserves the existing return contract — callers/tests still see a dict under `result["report"]`.) `storyboard.build` now returns `(out, times)`; ignore the tuple's second element (or capture and discard).

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -q`
Expected: PASS (mocked paths; golden runs in Task 10).

- [x] **Step 5: Commit**

```bash
git add scripts/process_episode.py tests/integration/test_process_episode.py
git commit -m "refactor: process_episode builds typed specs; intent (#1), delivery, composition gate (#2)"
```

---

## Task 10: Golden fixture pins `delivery`, full-suite + docs sync

Pin the golden manifest's `delivery` so its numeric checks stay deterministic, run the whole suite incl. real ffmpeg, and sync docs.

**Files:**
- Modify: `tests/integration/test_process_episode.py` (golden manifest)
- Modify: `docs/2026-07-08-engine-dataclass-hardening-design.md` (mark Built), `CLAUDE.md`, `README.md`

- [x] **Step 1: Pin the golden delivery + assert dims**

In `test_golden_ride_through_orchestrator`, add `delivery="exact:1080x1920"` to the manifest and assert the delivered clip dims via ffprobe:
```python
    manifest = dict(segment=str(FIX / "golden_ride.mp4"), out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", canvas=[9, 16],
                    target_dur=1.58, delivery="exact:1080x1920")
    ...
    assert result["status"] == "mechanical_pass", result
    # delivery honored exactly (aspect-agnostic engine, pinned for determinism)
    import json as _j
    probe = _j.loads(pe.reframe.proc.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", result["clip"]],
        text=True).stdout)["streams"][0]
    assert (probe["width"], probe["height"]) == (1080, 1920)
```

- [x] **Step 2: Run the full suite (incl. integration)**

Run: `.venv/bin/python -m pytest -q -m "integration or not integration"`
Expected: PASS (all — migrated unit + mocked shell + real-ffmpeg golden). If the golden's numeric checks drift, confirm `on_line`/`continuity` are computed in route space and unaffected; only fix a genuine regression.

- [x] **Step 3: Grep for dead hardcodes**

Run: `grep -rn "1080\|1920\|lutrgb\|\.split(\":\")\|\.split(\"x\")" scripts/ | grep -v test`
Expected: no `1080`/`1920` literal in `scripts/` (delivery owns dims); no `lutrgb`; no ad-hoc `.split(":")`/`.split("x")` outside argparse `__main__` blocks that build a spec. Fix any stragglers.

- [x] **Step 4: Sync docs**

- `docs/2026-07-08-engine-dataclass-hardening-design.md`: add a short "Built (YYYY-MM-DD, commit)" note at the top.
- `CLAUDE.md` Status: new bullet — engine dataclass-hardening done, N tests green, the 5 fixes + 2 holes closed, engine aspect/resolution-agnostic; **Next action** → Plan 2 (ingestion / project-init purpose→aspect).
- `README.md`: note the engine is now general-purpose (any aspect/resolution), driven by typed specs.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_process_episode.py docs/ CLAUDE.md README.md
git commit -m "test+docs: golden pins delivery + asserts dims; sync status for engine-hardening"
```

---

## Notes for the executor

- **TDD discipline:** every task is test-first → watch fail → implement → pass → commit. Do not batch.
- **Schema-compat is sacred:** if a migrated test needs the on-disk JSON to change shape, stop — the round-trip is wrong, not the fixture.
- **Manifest stays soft:** never make `Manifest.from_dict`/`validate` raise for user-input problems; those are `needs_input`. Only the internal `*Spec.__post_init__` raise.
- **`classify`/`compute_path`/`checks.*` still consume route **dicts*** this plan (they are pure numeric and unchanged); the engine converts `RoutePoint → dict` at the boundary. A later cleanup can push `RoutePoint` deeper, out of scope here.
- **Hard rules (design §12) unchanged:** `-ss` after `-i`; `lutrgb` banned; scripts run as modules; `pythonpath = .`; never stabilize wade-in/out; fail loud with a remedy.
```
