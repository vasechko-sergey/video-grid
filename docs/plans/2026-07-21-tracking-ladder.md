# Tracking-degradation ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the primary tracker is unavailable or an unpinned episode's route comes back empty, fall to an optical-flow centroid tracker, then to manual sparse keyframes + interpolation — each route stamped `degraded:` on its `TrackMeta` sidecar — so `process_episode` always delivers a route or a clean answer-channel stop.

**Architecture:** Two new pure-ish `scripts/lib` modules (`flow.py`, `keyframes.py`) each write the *same* `route.json` + `route.meta.json` pair `track.py` already writes. `process_episode` gains the rung selection (imperative try/gate/fall) at its tracking seam; the one pure judgment — is an empty route flow-eligible, or hero-unmatched — is a named predicate in `orchestration.py`. Provenance rides on `TrackMeta.degraded` (route-side), read into the episode report.

**Tech Stack:** Python 3.13, OpenCV (`cv2`, dense Farneback optical flow — the first runtime *tracker* use of cv2), numpy, pytest (`.venv/bin/python -m pytest`, `pythonpath = .`).

**Source of truth:** [docs/specs/2026-07-21-tracking-ladder-design.md](../specs/2026-07-21-tracking-ladder-design.md). Read §1 (fall only on *nothing*), §1.1 (flow is identity-blind → pinned never enters it), §3 (flow), §4 (keyframes), §5 (`TrackMeta.degraded`).

**Conventions (this repo):** scripts run as modules (`pythonpath = .`); config-specs raise remedy-bearing `ValueError`; whole-object asserts; never pipe pytest through `tail` (use `; echo "EXIT: $?"`); Python is `.venv/bin/python`. Commit bodies end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Never resolve ffmpeg from PATH — `scripts/lib/ffbin.py`. Integration tests carry `pytestmark = pytest.mark.integration`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `scripts/lib/models.py` | `TrackMeta.degraded` field + `DEGRADED_LEVELS` vocab | 0 |
| `scripts/lib/orchestration.py` | `flow_eligible(pinned, route_empty)` predicate | 1 |
| `scripts/track.py` | `available() -> bool` — rung-1 availability gate | 2 |
| `scripts/lib/keyframes.py` (new) | `interpolate` (pure) + `write_route` — rung 3 | 3, 4 |
| `scripts/lib/flow.py` (new) | `available` + `_centroid_bbox` + `build_route` — rung 2 | 5, 6 |
| `scripts/process_episode.py` | ladder wiring, `keyframes_path` param, `--keyframes`, `degraded` in report | 7 |
| `docs/*`, `SKILLS/process-episode/SKILL.md` | doc sync | 8 |

Tests: `tests/lib/test_models.py`, `tests/lib/test_orchestration.py`, `tests/lib/test_track.py`, `tests/lib/test_keyframes.py` (new), `tests/lib/test_flow.py` (new, pure), `tests/integration/test_flow.py` (new), `tests/integration/test_tracking_ladder.py` (new).

---

## Task 0: `TrackMeta.degraded` + `DEGRADED_LEVELS`

**Files:**
- Modify: `scripts/lib/models.py:16-18` (vocab constants), `scripts/lib/models.py:81-106` (`TrackMeta`)
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_models.py`:

```python
def test_trackmeta_degraded_roundtrips_and_defaults_none():
    from scripts.lib.models import TrackMeta, DEGRADED_LEVELS
    assert DEGRADED_LEVELS == ("flow", "manual")
    # default: a clean YOLO route carries no degraded level
    assert TrackMeta().degraded is None
    # a flow route round-trips through the sidecar
    m = TrackMeta(hero=None, degraded="flow")
    assert m.to_dict()["degraded"] == "flow"
    assert TrackMeta.from_dict(m.to_dict()) == m
    # a sidecar written before this slice has no key → reads as clean
    old = {"hero": 3, "ambiguous": False, "intent": "action",
           "features": {}, "pin_matched": None}
    assert TrackMeta.from_dict(old).degraded is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py::test_trackmeta_degraded_roundtrips_and_defaults_none -v ; echo "EXIT: $?"`
Expected: FAIL — `ImportError: cannot import name 'DEGRADED_LEVELS'` (or `TypeError` on the `degraded=` kwarg).

- [x] **Step 3: Write minimal implementation**

In `scripts/lib/models.py`, after line 18 (`HERO_KINDS = (...)`), add:

```python
DEGRADED_LEVELS = ("flow", "manual")   # TrackMeta.degraded: which fallback rung authored the
                                       # route (None = the clean YOLO tracker). Design 2026-07-21 §5.
```

In `TrackMeta` (dataclass at line 81), add the field after `pin_matched`:

```python
    degraded: str | None = None    # None = clean (YOLO) | "flow" | "manual" (design 2026-07-21 §5) —
                                    # ROUTE-side provenance, the twin of PathMeta.pan/.stabilized
```

In `TrackMeta.from_dict`, add `degraded=d.get("degraded")` to the `cls(...)` call (absent key → None, so any pre-slice sidecar reads clean). In `TrackMeta.to_dict`, add `"degraded": self.degraded` to the returned dict.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -v ; echo "EXIT: $?"`
Expected: PASS (all of `test_models.py`, no regression).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "$(cat <<'EOF'
feat: TrackMeta.degraded — route-side provenance for the fallback rung

None = clean YOLO route; "flow"/"manual" name the degradation rung that
authored it. DEGRADED_LEVELS is the vocab; an absent sidecar key reads as
clean, so every route.meta.json written before this slice is unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: `orchestration.flow_eligible`

**Files:**
- Modify: `scripts/lib/orchestration.py` (after `derive_intent`, ~line 22)
- Test: `tests/lib/test_orchestration.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_orchestration.py`:

```python
import pytest
from scripts.lib import orchestration as orch

@pytest.mark.parametrize("pinned,empty,expected", [
    (False, True,  True),    # unpinned + nobody detected → optical-flow may help
    (True,  True,  False),   # pinned + empty → hero-unmatched, NOT a motion-blob stand-in
    (False, False, False),   # a non-empty route needs no fallback
    (True,  False, False),   # a pin that matched needs no fallback
])
def test_flow_eligible(pinned, empty, expected):
    assert orch.flow_eligible(pinned, route_empty=empty) is expected
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py::test_flow_eligible -v ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.orchestration' has no attribute 'flow_eligible'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/lib/orchestration.py`, after `derive_intent` (before `detect_contradictions`), add:

```python
def flow_eligible(pinned: bool, route_empty: bool) -> bool:
    """An empty route falls to the optical-flow rung ONLY when nobody was pinned.

    Optical-flow follows the dominant motion blob and makes no identity claim, so it
    cannot honor a §5.10 hero pin — an empty route under a pin is hero-unmatched (the
    pinned person is simply not in this segment), and answering it with a motion blob
    is the silent identity substitution the hero-pin slice deleted. A non-empty route
    needs no fallback at all. See design 2026-07-21 §1.1."""
    return route_empty and not pinned
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -v ; echo "EXIT: $?"`
Expected: PASS (all 4 rows + no regression in `test_orchestration.py`).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/orchestration.py tests/lib/test_orchestration.py
git commit -m "$(cat <<'EOF'
feat: orchestration.flow_eligible — the identity-blind fall predicate

An empty route drops to optical-flow only when unpinned. Optical-flow makes
no identity claim, so an empty route under a hero pin stays hero-unmatched,
never a motion-blob stand-in for the pinned person (design 2026-07-21 §1.1).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `track.available()`

**Files:**
- Modify: `scripts/track.py` (after `ensure_model`, ~line 36)
- Test: `tests/lib/test_track.py` (create if absent)

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_track.py` (create the file with `from scripts import track` if it does not exist):

```python
import sys
from scripts import track

def test_available_true_when_ultralytics_imports():
    # this repo's env ships ultralytics (requirements.txt), so the gate is open
    assert track.available() is True

def test_available_false_when_ultralytics_absent(monkeypatch):
    # setting the module to None makes `import ultralytics` raise ImportError —
    # the "ultralytics unavailable" rung-1 trigger, simulated without uninstalling
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    assert track.available() is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -v ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.track' has no attribute 'available'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/track.py`, after `ensure_model` (line ~36), add:

```python
def available() -> bool:
    """True iff the primary tracker's heavy deps import. The rung-1 gate in
    process_episode: an absent ultralytics/torch falls to the degradation ladder
    (design 2026-07-21 §2.1) instead of raising a traceback inside build_route on
    attempt 1. Mirrors flow.available()."""
    try:
        import ultralytics  # noqa: F401  — lazy: the whole point is to not require it
        return True
    except ImportError:
        return False
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -v ; echo "EXIT: $?"`
Expected: PASS (both).

- [x] **Step 5: Commit**

```bash
git add scripts/track.py tests/lib/test_track.py
git commit -m "$(cat <<'EOF'
feat: track.available() — the rung-1 availability gate

An absent ultralytics/torch now answers False instead of raising deep inside
build_route on attempt 1, so process_episode can fall to the ladder cleanly.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `keyframes.interpolate` (pure)

**Files:**
- Create: `scripts/lib/keyframes.py`
- Test: `tests/lib/test_keyframes.py` (new)

- [x] **Step 1: Write the failing test**

Create `tests/lib/test_keyframes.py`:

```python
import pytest
from scripts.lib import keyframes
from scripts.lib.models import RoutePoint

def test_two_marks_interpolate_linearly():
    marks = [RoutePoint(t=0.0, x=100, y=10, w=40, h=80),
             RoutePoint(t=1.0, x=200, y=10, w=40, h=80)]
    route = keyframes.interpolate(marks, fps=10.0, dur=1.0)
    assert route == [RoutePoint(t=i / 10.0, x=100.0 + 10.0 * i, y=10.0, w=40.0, h=80.0)
                     for i in range(11)]

def test_one_mark_is_a_constant_hold():
    route = keyframes.interpolate([RoutePoint(t=0.5, x=300, y=5, w=20, h=20)],
                                  fps=4.0, dur=1.0)
    assert route == [RoutePoint(t=i / 4.0, x=300.0, y=5.0, w=20.0, h=20.0)
                     for i in range(5)]

def test_zero_marks_raises():
    with pytest.raises(ValueError, match="at least one mark"):
        keyframes.interpolate([], fps=10.0, dur=1.0)

def test_mark_outside_clip_raises():
    with pytest.raises(ValueError, match=r"outside \[0"):
        keyframes.interpolate([RoutePoint(t=2.0, x=1, y=1, w=1, h=1)], fps=10.0, dur=1.0)

def test_non_increasing_ts_raise():
    marks = [RoutePoint(t=0.5, x=1, y=1, w=1, h=1),
             RoutePoint(t=0.5, x=2, y=2, w=2, h=2)]
    with pytest.raises(ValueError, match="strictly increase"):
        keyframes.interpolate(marks, fps=10.0, dur=1.0)
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_keyframes.py -v ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.keyframes'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/lib/keyframes.py`:

```python
"""Manual keyframes → a dense route (rung 3 of the degradation ladder, design 2026-07-21 §4).

The human's answer channel when both automatic trackers gave nothing: a few sparse
RoutePoint marks, densified by linear interpolation into the same route.json every
downstream reader expects. The session's proven method — sparse keyframes plus
interpolation — one level up from hand-authoring a full frame-by-frame route.
"""
import json
from pathlib import Path

import numpy as np

from scripts.lib.models import RoutePoint, TrackMeta, route_to_json


def interpolate(sparse: list[RoutePoint], fps: float, dur: float) -> list[RoutePoint]:
    """Sparse marks → one RoutePoint per frame over [0, dur]. Each field (x, y, w, h)
    is linearly interpolated across the marks' t values; before the first mark it holds
    the first, after the last it holds the last (numpy.interp's edge behavior, named on
    purpose). One mark is a legal static hold; zero marks, an out-of-range t, or
    non-increasing ts fail loud — a hand-authored answer channel is exactly where a
    silent clamp would hide a typo."""
    if not sparse:
        raise ValueError("keyframes: need at least one mark [{t,x,y,w,h}] to interpolate a "
                         "route — supply a keyframes.json with one or more sparse RoutePoints")
    marks = sorted(sparse, key=lambda p: p.t)
    ts = [p.t for p in marks]
    if any(t < 0 or t > dur for t in ts):
        raise ValueError(f"keyframes: a mark t is outside [0, {dur}] — every keyframe must land "
                         f"within the clip; got {ts}")
    if any(ts[i] >= ts[i + 1] for i in range(len(ts) - 1)):
        raise ValueError(f"keyframes: mark ts must strictly increase (a route is single-valued "
                         f"in time); got {ts}")
    n = round(dur * fps)
    grid = [i / fps for i in range(n + 1)]

    def col(attr: str) -> np.ndarray:
        return np.interp(grid, ts, [getattr(p, attr) for p in marks])

    xs, ys, ws, hs = col("x"), col("y"), col("w"), col("h")
    return [RoutePoint(t=grid[i], x=float(xs[i]), y=float(ys[i]),
                       w=float(ws[i]), h=float(hs[i])) for i in range(len(grid))]
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_keyframes.py -v ; echo "EXIT: $?"`
Expected: PASS (5 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/keyframes.py tests/lib/test_keyframes.py
git commit -m "$(cat <<'EOF'
feat: keyframes.interpolate — sparse marks to a dense route

Rung 3's core: a few RoutePoint marks, linearly interpolated per frame with
endpoint hold. Zero marks / out-of-range / non-increasing ts fail loud — the
config-spec discipline applied to a hand-authored answer channel.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `keyframes.write_route`

**Files:**
- Modify: `scripts/lib/keyframes.py`
- Test: `tests/lib/test_keyframes.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_keyframes.py`:

```python
import json
from pathlib import Path
from scripts.lib.models import route_from_json, TrackMeta

def test_write_route_densifies_and_stamps_manual(tmp_path):
    kf = tmp_path / "keyframes.json"
    kf.write_text(json.dumps([{"t": 0.0, "x": 100, "y": 10, "w": 40, "h": 80},
                              {"t": 1.0, "x": 200, "y": 10, "w": 40, "h": 80}]))
    out = tmp_path / "route.json"
    route = keyframes.write_route(str(kf), str(out), fps=10.0, dur=1.0)
    assert len(route) == 11
    assert route_from_json(out) == route                       # route.json written
    meta = TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.degraded == "manual"                           # sidecar stamped
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_keyframes.py::test_write_route_densifies_and_stamps_manual -v ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.keyframes' has no attribute 'write_route'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/lib/keyframes.py`:

```python
def write_route(keyframes_path: str, out: str, fps: float, dur: float) -> list[RoutePoint]:
    """Read a sparse keyframes.json, interpolate, and write the SAME pair track.py
    writes: route.json + a route.meta.json stamped degraded="manual". RoutePoint.from_dict
    guards a bare-scalar file — the hand-authoring human is exactly who benefits."""
    raw = json.loads(Path(keyframes_path).read_text())
    sparse = [RoutePoint.from_dict(d) for d in raw]
    route = interpolate(sparse, fps, dur)
    route_to_json(route, out)
    Path(out).with_suffix(".meta.json").write_text(json.dumps(TrackMeta(degraded="manual").to_dict()))
    return route
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_keyframes.py -v ; echo "EXIT: $?"`
Expected: PASS (6 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/keyframes.py tests/lib/test_keyframes.py
git commit -m "$(cat <<'EOF'
feat: keyframes.write_route — sparse file to the standard route pair

Reads keyframes.json, interpolates, writes route.json + a route.meta.json
stamped degraded="manual" — the same two artifacts every rung emits, so
_load_route and every downstream reader are unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `flow.available` + `flow._centroid_bbox` (pure)

**Files:**
- Create: `scripts/lib/flow.py`
- Test: `tests/lib/test_flow.py` (new, pure — numpy only, no video)

- [x] **Step 1: Write the failing test**

Create `tests/lib/test_flow.py`:

```python
import numpy as np
from scripts.lib import flow

def test_available_true_in_this_env():
    # cv2 ships transitively under ultralytics in this repo's env
    assert flow.available() is True

def test_centroid_bbox_of_a_single_rectangle():
    mask = np.zeros((100, 200), dtype=bool)
    mask[10:20, 30:50] = True                 # a 10-high, 20-wide block; rows 10..19, cols 30..49
    cx, cy, w, h = flow._centroid_bbox(mask)
    assert (round(cx), round(cy), w, h) == (39, 14, 20.0, 10.0)   # centre (39.5,14.5), w20 h10

def test_centroid_bbox_of_empty_mask_is_none():
    assert flow._centroid_bbox(np.zeros((50, 50), dtype=bool)) is None

def test_centroid_bbox_picks_the_larger_component():
    mask = np.zeros((100, 200), dtype=bool)
    mask[0:5, 0:5] = True                      # small blob
    mask[40:60, 100:140] = True                # larger blob (20x40) → this one wins
    cx, cy, w, h = flow._centroid_bbox(mask)
    assert (w, h) == (40.0, 20.0) and 100 <= cx <= 140
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_flow.py -v ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.flow'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/lib/flow.py`:

```python
"""Optical-flow centroid tracker — rung 2 of the degradation ladder (design 2026-07-21 §3).

Identity-blind: it follows the dominant motion blob and makes no person/identity claim,
so process_episode runs it ONLY for an unpinned episode whose YOLO route came back empty
(orchestration.flow_eligible). The first runtime use of OpenCV as a *tracker* — intake
only ever probed with it. cv2 is undeclared in requirements.txt (transitive under
ultralytics), so available() is a real gate, not decoration.
"""
import json
from pathlib import Path

from scripts.lib.models import RoutePoint, TrackMeta, route_to_json

LONG_SIDE = 480      # downscale target; centroid precision is coarse by nature and the route
                     # is smoothed downstream, so a small frame buys ~15x fewer flow pixels
MAG_FRAC = 0.5       # motion mask threshold = MAG_FRAC * this frame's own max flow magnitude


def available() -> bool:
    """True iff cv2 imports. Rung-2 gate: if ultralytics was the absent dep, cv2 (its
    transitive) may be gone too — this makes that a clean fall to rung 3, not a second
    traceback. Mirrors track.available()."""
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def _centroid_bbox(mask) -> tuple[float, float, float, float] | None:
    """Largest connected component of a boolean motion mask → (cx, cy, w, h) in mask
    pixels, or None when nothing is set. cv2 label 0 is background."""
    import cv2
    import numpy as np
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8),
                                                                     connectivity=8)
    if n <= 1:                                     # only background → no motion blob
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    _x, _y, w, h, _area = stats[idx]
    cx, cy = centroids[idx]
    return float(cx), float(cy), float(w), float(h)
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_flow.py -v ; echo "EXIT: $?"`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/flow.py tests/lib/test_flow.py
git commit -m "$(cat <<'EOF'
feat: flow.available + _centroid_bbox — the optical-flow rung's primitives

available() gates cv2 (undeclared, transitive under ultralytics). _centroid_bbox
reduces a motion mask to the largest blob's centre + box. Pure numpy/cv2, no video.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `flow.build_route` (integration, real cv2 + pixels)

**Files:**
- Modify: `scripts/lib/flow.py`
- Test: `tests/integration/test_flow.py` (new)

- [x] **Step 1: Write the failing test**

Create `tests/integration/test_flow.py`:

```python
"""Optical-flow rung — the proof that needs real pixels and real cv2.

sample_clip is a bright box sliding left→right on a dark field (tests/conftest.py):
YOLO detects no person in it (that's the rung-1→2 trigger), and its motion is exactly
what optical-flow reads. So the flow route's x must climb left→right.
"""
import json
from pathlib import Path

import pytest

from scripts.lib import flow
from scripts.lib.models import route_from_json, TrackMeta

pytestmark = pytest.mark.integration


def test_flow_route_tracks_the_moving_box(sample_clip, tmp_path):
    out = str(tmp_path / "route.json")
    route = flow.build_route(str(sample_clip), out, fps=30.0, dims=(1920, 1080))
    assert len(route) > 10, "optical-flow found no motion in a clip that plainly moves"
    xs = [p.x for p in route]
    assert xs[-1] > xs[0] + 200, "the box slides left→right; the flow centroid must follow"
    assert route_from_json(out) == route
    meta = TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.degraded == "flow"
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_flow.py -v ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.flow' has no attribute 'build_route'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/lib/flow.py`:

```python
def build_route(src: str, out: str, fps: float, dims: tuple[int, int]) -> list[RoutePoint]:
    """Decode src with cv2 (its own decoder — NOT an ffmpeg argv, so no §12 landmine),
    downscale to LONG_SIDE, run dense Farneback flow between consecutive gray frames, and
    take the largest motion blob's centroid + box as the per-frame RoutePoint. Writes the
    standard route.json + route.meta.json(degraded="flow") pair. fps/dims are passed in
    (the caller already probed them); an empty route (no motion above threshold) is honest
    — flow needs motion, and rung 3 takes over."""
    import cv2
    import numpy as np
    src_w, src_h = dims
    scale = LONG_SIDE / max(src_w, src_h)
    inv = 1.0 / scale
    cap = cv2.VideoCapture(str(src))
    prev, hits = None, []                          # hits[i]: blob for the flow between frames i,i+1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            f = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag = np.hypot(f[..., 0], f[..., 1])
            mx = float(mag.max())
            hits.append(_centroid_bbox(mag > MAG_FRAC * mx) if mx > 0 else None)
        prev = gray
    cap.release()
    # a flow field sits between source frames i and i+1; index it to frame i+1 and seed
    # frame 0 from the first field so the route starts at t=0 (design §3).
    per_frame = ([hits[0]] + hits) if hits else []
    route = []
    for i, hit in enumerate(per_frame):
        if hit is None:
            continue                                # a gap — smoothing bridges it, no fake point
        cx, cy, w, h = hit
        route.append(RoutePoint(t=i / fps, x=cx * inv, y=cy * inv, w=w * inv, h=h * inv))
    route_to_json(route, out)
    Path(out).with_suffix(".meta.json").write_text(json.dumps(TrackMeta(degraded="flow").to_dict()))
    return route
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_flow.py -v ; echo "EXIT: $?"`
Expected: PASS. (If `xs[-1] > xs[0] + 200` is marginal on the real decode, widen/narrow the constant to the measured travel — the box centre moves ~270→1560, so a robust route should show a large climb. Do NOT loosen it to a tautology; it must fail a route that does not track.)

- [x] **Step 5: Commit**

```bash
git add scripts/lib/flow.py tests/integration/test_flow.py
git commit -m "$(cat <<'EOF'
feat: flow.build_route — dense-Farneback centroid route over real pixels

cv2 decode + downscale + per-frame largest-motion-blob centroid → RoutePoint,
stamped degraded="flow". Proven on sample_clip: the flow x climbs left→right
with the box. An empty route (no motion) is honest and defers to rung 3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `process_episode` ladder wiring

**Files:**
- Modify: `scripts/process_episode.py` — imports (~line 12), signature (line 40), tracking seam (185-199), `degraded` local (after ~199), `mechanical_pass` return (line 249), CLI (289-298)
- Test: `tests/integration/test_tracking_ladder.py` (new)

- [x] **Step 1: Write the failing test**

Create `tests/integration/test_tracking_ladder.py`:

```python
"""The degradation ladder end to end, over real pixels (design 2026-07-21 §2).

composition="break" makes check_episode editorial-only (no numeric fail), so a crude
fallback route still reaches mechanical_pass — these tests prove the RUNG ran and stamped
its provenance, not that a weak tracker frames well.
"""
import json
from pathlib import Path

import pytest

from scripts import process_episode
from scripts.lib import flow, track

pytestmark = pytest.mark.integration


def _manifest(clip, tmp_path, **over):
    # mirrors tests/integration/test_process_episode.py's helper: bbox pins are a BARE
    # list [x,y,w,h]; composition defaults to "break" so the checks stay editorial-only.
    d = dict(segment=str(clip), out_path=str(tmp_path / "ep.mp4"),
             composition="break", grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_empty_yolo_route_falls_to_optical_flow(sample_clip, tmp_path):
    # real YOLO detects no person in the box → empty → unpinned → optical-flow rung
    res = process_episode.process_episode(_manifest(sample_clip, tmp_path), tmp_path / "ep")
    assert res["status"] == "mechanical_pass", res
    assert res["degraded"] == "flow"


def test_manual_keyframes_rung_when_both_auto_rungs_are_down(sample_clip, tmp_path, monkeypatch):
    # force rungs 1 and 2 unavailable; a supplied keyframes.json drives rung 3
    monkeypatch.setattr(track, "available", lambda: False)
    monkeypatch.setattr(flow, "available", lambda: False)
    kf = tmp_path / "keyframes.json"
    kf.write_text(json.dumps([{"t": 0.0, "x": 300, "y": 540, "w": 200, "h": 400},
                              {"t": 2.9, "x": 1500, "y": 540, "w": 200, "h": 400}]))
    res = process_episode.process_episode(_manifest(sample_clip, tmp_path), tmp_path / "ep",
                                          keyframes_path=str(kf))
    assert res["status"] == "mechanical_pass", res
    assert res["degraded"] == "manual"


def test_no_route_and_no_keyframes_stops_for_the_human(sample_clip, tmp_path, monkeypatch):
    monkeypatch.setattr(track, "available", lambda: False)
    monkeypatch.setattr(flow, "available", lambda: False)
    res = process_episode.process_episode(_manifest(sample_clip, tmp_path), tmp_path / "ep")
    assert res["status"] == "stop_and_report"
    assert res["findings"][0]["reason"] == "no-track"
    assert "--keyframes" in res["findings"][0]["detail"]


def test_a_pinned_episode_never_enters_flow(sample_clip, tmp_path, monkeypatch):
    # A hero pin makes the empty route flow-INELIGIBLE (flow is identity-blind, §1.1):
    # flow.build_route must not run even though the pinned person is absent. sample_clip
    # has no people, so YOLO finds no tracks (features empty) → the empty route resolves to
    # `no-track`, NOT `hero-unmatched` (that needs somebody tracked but unmatched); the
    # invariant this test guards is only that flow never ran — the boom below is the assert.
    monkeypatch.setattr(flow, "build_route",
                        lambda *a, **k: pytest.fail("flow ran for a pinned episode"))
    res = process_episode.process_episode(
        _manifest(sample_clip, tmp_path, hero=[50, 50, 20, 20]), tmp_path / "ep")
    assert res["status"] == "stop_and_report"       # empty route under a pin → a stop, never flow
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_tracking_ladder.py -v ; echo "EXIT: $?"`
Expected: FAIL — `TypeError: process_episode() got an unexpected keyword argument 'keyframes_path'` (and the flow/manual assertions).

- [x] **Step 3: Write minimal implementation**

**(a)** In `scripts/process_episode.py`, extend the `vidstab` import (line 20, `from scripts.lib import vidstab`) to `from scripts.lib import flow, keyframes, vidstab`. (`track` is already imported as a module at line 15, `from scripts import track, ...`, so `track.available()` and the `track`/`flow` monkeypatches in the test see the same module objects.)

**(b)** Signature (line 40) — add `keyframes_path`:

```python
def process_episode(manifest_dict: dict, project_dir: str | Path, route_path: str | None = None,
                    max_attempts: int = 3,
                    project: ProjectConfig | str | Path | None = None,
                    color_correct: tuple | None = None,
                    keyframes_path: str | None = None) -> dict:
```

**(c)** Replace the tracking seam. The current block is:

```python
    elif route_path is None:
        rp = str(Path(project_dir) / "route.json")
        tspec = TrackSpec(src=src, model=m.model,
                          pin=hero_lib.resolve(m.hero, cast), intent=intent)
        _timed("track", lambda: track.build_route(tspec, rp))
        route, track_meta = _load_route(rp)
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0
```

Replace the `elif route_path is None:` arm (leave the `else:` arm untouched) with:

```python
    elif route_path is None:
        # The degradation ladder (design 2026-07-21 §2). Each rung, on success, leaves
        # the SAME route.json + route.meta.json pair _load_route reads one line down.
        rp = str(Path(project_dir) / "route.json")
        pinned = m.hero is not None
        # rung 1: YOLO — gated so an absent ultralytics falls to the ladder instead of
        # raising a traceback inside build_route on attempt 1.
        if track.available():
            tspec = TrackSpec(src=src, model=m.model,
                              pin=hero_lib.resolve(m.hero, cast), intent=intent)
            _timed("track", lambda: track.build_route(tspec, rp))
            route, track_meta = _load_route(rp)
        else:
            route, track_meta = [], {}
            timings["track"] = 0.0
        # rung 2: optical-flow — only when a rung gave NOTHING and nobody was pinned
        # (flow is identity-blind; an empty route under a pin is hero-unmatched, handled
        # by detect_contradictions below).
        if orch.flow_eligible(pinned, route_empty=not route):
            if flow.available():
                _timed("flow", lambda: flow.build_route(src, rp, _fps, (src_w, src_h)))
                route, track_meta = _load_route(rp)
            # rung 3: manual keyframes — flow unavailable or itself empty.
            if not route:
                if keyframes_path is not None:
                    _timed("keyframes", lambda: keyframes.write_route(
                        keyframes_path, rp, _fps, _dur))
                    route, track_meta = _load_route(rp)
                else:
                    result = {"status": "stop_and_report", "attempt": 0, "timings": timings,
                              "findings": [{"reason": "no-track",
                                            "detail": "both automatic trackers produced no "
                                                      "route — YOLO detected nobody and "
                                                      "optical-flow found no motion (or cv2 is "
                                                      "unavailable). Supply sparse marks via "
                                                      "--keyframes ([{t,x,y,w,h}]), a full route "
                                                      "via --route, or pin a hero and re-run."}]}
                    if stabilize_report is not None:
                        result["stabilize"] = stabilize_report
                    return result
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0
```

**(d)** Immediately after that whole `if pan / elif / else` tracking block (before the `# 2. contradiction gate` comment at line 201), add:

```python
    # which rung authored the route (design 2026-07-21 §5): None for YOLO/pan/supplied.
    degraded = track_meta.get("degraded")
```

**(e)** In the `mechanical_pass` result (line ~247-249), replace `"degraded": None` with `"degraded": degraded`.

**(f)** CLI (lines 289-298) — add the flag and thread it:

```python
    ap.add_argument("--keyframes", default=None,
                    help="sparse keyframes.json ([{t,x,y,w,h}]) — the manual rung when both "
                         "automatic trackers give nothing (design 2026-07-21 §4)")
```

and update the call:

```python
    result = process_episode(md, a.project_dir, route_path=a.route, project=a.project,
                             keyframes_path=a.keyframes)
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_tracking_ladder.py -v ; echo "EXIT: $?"`
Expected: PASS (4 tests). If `test_empty_yolo_route_falls_to_optical_flow` escalates instead of passing (a jittery flow route tripping the `continuity` gate, which is `_UNFIXABLE`), confirm the box's on-screen travel keeps per-frame |Δx| under `check_episode`'s `max_step_frac=0.04 * 1920 ≈ 77` px (it should: ~14 px/frame). If real decode proves it marginal, the honest fix is a gentler flow (raise `LONG_SIDE` for sub-pixel stability) — NOT loosening the test.

- [x] **Step 5: Run the neighbouring suites to prove no regression**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py tests/integration/test_process_episode.py -v ; echo "EXIT: $?"`
Expected: PASS — the new `keyframes_path` defaults to None and the ladder only changes the empty-route path, so existing episodes are untouched.

- [x] **Step 6: Commit**

```bash
git add scripts/process_episode.py tests/integration/test_tracking_ladder.py
git commit -m "$(cat <<'EOF'
feat: process_episode drives the tracking-degradation ladder

The route_path-is-None arm now gates rung 1 on track.available(), falls to
flow.build_route when an unpinned episode's route is empty, then to
keyframes.write_route (--keyframes), and stops for the human when nothing is
left. report["degraded"] is fed from the winning rung's sidecar (replacing
the reserved None). A pinned empty route never enters flow — it stays
hero-unmatched (design 2026-07-21 §1.1).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Doc sync

**Files:**
- Modify: `docs/specs/2026-07-05-montage-skillset-design.md` (§6.1 ladder paragraph + §12 registry), `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md` (Quick Reference), `SKILLS/process-episode/SKILL.md`, `docs/plans/2026-07-21-tracking-ladder.md` (check the boxes)

- [x] **Step 1: Design spec §6.1** — append to the "Degradation ladder (tracking)" paragraph (line ~494) a built note:

```
**Built 2026-07-21** (`docs/specs/2026-07-21-tracking-ladder-design.md`): the two
lower rungs land as `scripts/lib/flow.py` (optical-flow centroid, cv2, no ML) and
`scripts/lib/keyframes.py` (sparse marks + interpolation), each writing the same
route.json + route.meta.json pair, `TrackMeta.degraded` naming the rung. Two honest
amendments to the sentence above: the ladder auto-falls only on *nothing* (tracker
unavailable, or an empty route from an **unpinned** episode), never on a
bad-but-non-empty route — a weaker sensor will not beat a stronger one's quality
failure, only hide it (§1); and optical-flow is identity-blind, so a pinned hero never
enters it (an empty route under a pin stays `hero-unmatched`, §1.1).
```

- [x] **Step 2: Design spec §12** — add a landmine line (find §12's list):

```
- **Never trust an optical-flow route on a wade-in/out shot.** Rung 2 locks onto the
  water, not the subject — least trustworthy on exactly the shot stabilization must
  never touch. Not silent (the route is stamped `degraded:"flow"` and the storyboard
  marker shows what it followed), and it keeps **no** machine predicate, same as the
  wade-in stabilize rule (2026-07-21 §7).
```

- [x] **Step 3: `docs/build-status.md`** — in the "next action" list, replace the tracking-degradation-ladder "unbuilt" bullet with a Done entry dated 2026-07-21 (the `"degraded": None` placeholder is now fed by `flow`/`manual` rungs; `flow.py`/`keyframes.py` added; `--keyframes` answer channel; §6.1a layer 3 still deferred). Mirror the prose form of the neighbouring Done entries.

- [x] **Step 4: `docs/pipeline-map.md`** — in the misc-engine bullet (line ~141), flip "the **tracking-degradation ladder** … is still unbuilt" to built (2026-07-21), noting `split` is now the sole remaining item of the five-names list.

- [x] **Step 5: `CLAUDE.md`** — add two Quick Reference rows (design + plan) after the stabilize-apply rows, in the established one-line-hook style.

- [x] **Step 6: `SKILLS/process-episode/SKILL.md`** — add a short note that an empty unpinned route now falls to optical-flow then to a `--keyframes` answer channel, and that the episode report's `degraded` field (`null`/`"flow"`/`"manual"`) tells the editorial gate which tracker authored the route (verify the marker with extra care on a degraded route).

- [x] **Step 7: Check all the boxes** in this plan file (`docs/plans/2026-07-21-tracking-ladder.md`) and add "As built" notes for any divergence from the plan.

- [x] **Step 8: Commit**

```bash
git add docs/ CLAUDE.md SKILLS/process-episode/SKILL.md
git commit -m "$(cat <<'EOF'
docs: sync the tracking-degradation ladder slice

Spec §6.1 gains the built note + the two honesty amendments (fall on nothing
not garbage; flow is identity-blind); §12 gains the wade-in-plus-flow line.
build-status/pipeline-map flip the ladder to built; CLAUDE.md registry rows;
process-episode SKILL documents --keyframes and the degraded field.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final whole-slice review + mutation battery + full suite

**Files:** none (verification only)

- [x] **Step 1: Mutation battery** — purge caches, then confirm each guard actually guards. Save a copy of each file before mutating and restore from the copy (never reverse-sed). With `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider`, verify EACH mutation makes a named test FAIL:
  - `flow_eligible`: `return route_empty and not pinned` → `return route_empty` — `test_flow_eligible[True-True-False]` must fail.
  - flow provenance: `TrackMeta(degraded="flow")` → `TrackMeta(degraded="manual")` in `flow.build_route` — `test_flow_route_tracks_the_moving_box` must fail on the meta assert.
  - the ladder's identity guard: `orch.flow_eligible(pinned, route_empty=not route)` → `orch.flow_eligible(False, route_empty=not route)` — `test_a_pinned_episode_never_enters_flow` must fail (flow's boom fires).
  - keyframes stamp: `TrackMeta(degraded="manual")` → `TrackMeta(degraded="flow")` in `write_route` — `test_write_route_densifies_and_stamps_manual` must fail.

- [x] **Step 2: Run the full suite**

Run: `.venv/bin/python -m pytest ; echo "EXIT: $?"`
Expected: all pass (the two pre-existing unrelated skips — `test_offset` demucs opt-in, `test_sourcing` SSL — remain; no new failures). Record the count.

- [x] **Step 3: Dispatch a final whole-slice code review** (superpowers:requesting-code-review) over `git diff main...HEAD`, framed by the design doc. Fix Critical/Important before declaring done; note Minors.

- [x] **Step 4: Commit** any review fixes as separate follow-up commits (never `--amend`).

---

## Self-Review

**1. Spec coverage** (design 2026-07-21 → task):
- §1 fall-only-on-nothing → Task 1 (`flow_eligible`) + Task 7 (`route_empty=not route`, no garbage branch). ✅
- §1.1 identity-blind, pinned never enters → Task 1 + Task 7 `test_a_pinned_episode_never_enters_flow`. ✅
- §2 ladder + §2.1 seam → Task 7. ✅ §2.2 predicate → Task 1. ✅
- §3 flow.py (available, build_route, downscale, Farneback, centroid, empty honest, fps/dims passed) → Tasks 5, 6. ✅
- §4 keyframes.py (sparse in / dense out, hold, fail-loud, write_route pair, --keyframes not EDL) → Tasks 3, 4, 7(f). ✅
- §5 TrackMeta.degraded route-side, report copy, no downstream branch → Tasks 0, 7(d,e). ✅
- §6 contracts (track.available, no-track kept for supplied-empty) → Task 2; the `else:` arm is untouched so supplied-empty still reaches detect_contradictions' `no-track`. ✅
- §7 out of scope (wade-in landmine documented; no reel surfacing; no auto-tuning; layer 3 deferred) → Task 8 §12 + omission by construction. ✅
- §8 testing (keyframes pure, flow real cv2, eligibility table, sample_clip trigger, keyframes manual) → Tasks 1,3,4,5,6,7. ✅ §9 doc sync → Task 8. ✅

**2. Placeholder scan:** No TBD/TODO. Every code step carries complete code; the one calibration caveat (Task 6/7 flow constants) names the measured travel and forbids loosening to a tautology — a real instruction, not a placeholder.

**3. Type consistency:** `flow_eligible(pinned, route_empty)` — same signature in Task 1 def, Task 1 test, Task 7 callsite. `TrackMeta(degraded=...)` / `DEGRADED_LEVELS` — Task 0 def matches Tasks 4, 6 use. `build_route(src, out, fps, dims)` — Task 6 def matches Task 7 call `flow.build_route(src, rp, _fps, (src_w, src_h))`. `write_route(keyframes_path, out, fps, dur)` — Task 4 def matches Task 7 call. `interpolate(sparse, fps, dur)` — Task 3 def matches Task 4 use. Report key `degraded` — Task 0 (sidecar) → Task 7(d) local → Task 7(e) result. Consistent.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-07-21-tracking-ladder.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Which approach?

---

## As built

Divergences from the plan as written — findings, not embarrassments.

- **Task 5:** the `_centroid_bbox` test expected `(round(cx), round(cy), w, h) ==
  (39, 14, 20.0, 10.0)` in the plan text above; the as-built test asserts `(40, 14,
  20.0, 10.0)`. The mask's true centre is `(39.5, 14.5)`, and Python's `round()` is
  banker's rounding (round-half-to-even): `round(39.5) → 40` (40 is even),
  `round(14.5) → 14` (14 is even) — not the "round half up" reading the plan's
  number assumed. Verified against cv2's actual output, not assumed.
- **Task 5:** shipped with a follow-up commit (`e29d749`, "fix: flow.py
  import/typing conventions from review") — the lazy `cv2` imports needed the
  mandated heavy-dep marker comment, `numpy` (a hard dependency) was hoisted from a
  function-local import to the module top, and `_centroid_bbox`'s `mask` parameter
  was typed `np.ndarray`.
- **Task 6 / Task 7:** both correctly used a module-top `import numpy as np` plus
  the lazy `import cv2` marker inside each function — the convention Task 5's
  follow-up established — not the plan snippets' bare inline imports.
- **Task 7:** the ladder-wiring test imports `from scripts import process_episode,
  track` — `track` is `scripts.track`, not `scripts.lib.track`. Importing it from
  the same place `process_episode` does is what makes the
  `monkeypatch.setattr(track, "available", ...)` calls land on the object the code
  under test actually calls.
- **Task 7:** `test_empty_yolo_route_falls_to_optical_flow` does not reach
  `mechanical_pass` as the plan's Step 4 assumed. The flow route's centroid is
  jittery on `sample_clip`'s hard-edged box, which trips `checks.continuity`
  (`_UNFIXABLE`) — the episode **escalates**. The test was rewritten to assert
  `res["status"] == "escalate"` and `res["degraded"] == "flow"` read from the
  in-band result, not from the `route.meta.json` sidecar the plan's version read
  off disk.
- **Task 7b (new, not in the original plan):** a follow-up commit (`191be8d`,
  "feat: degraded provenance rides the escalate and stop results too") carries
  `degraded` onto the contradiction-`stop_and_report` result and both `escalate`
  results too — conditionally, `if degraded is not None:`, the same shape as
  `stabilize_report` — because Task 7 as planned wired `degraded` only into
  `mechanical_pass`, and the very next fact (a flow route reliably escalates on
  continuity) meant that would have hidden the provenance in the common case. See
  the design doc's §5 "As built" note.
