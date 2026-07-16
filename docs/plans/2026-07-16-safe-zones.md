# Safe-zones (§5.13) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `check_reel.safe_zones` from an honest `passed=None` stub into a real, deterministic, **advisory** check that flags a reel episode whose tracked subject lands under the platform's UI chrome — closing stage §5.13.

**Architecture:** Reuse the already-tested `storyboard.marks_at_times` subject→canvas projection (moved to `lib/geometry.py` so a checker need not import a driver). A new `lib/safezones.py` owns a typed `SafeZone` config-spec + a platform-keyed `SAFE_ZONES` table + the pure `evaluate` decision. `check_reel.run` gains `geometry=`/`platform=`; when the per-episode sidecars are present it projects each subject and tests it against the zone, reporting an **advisory** `CheckResult` (joins `_ADVISORY_CHECKS` with `beat` — reported, excluded from `overall`, no `ReelFailure`). `build_reel`/`edl_to_reel` thread the sidecar paths; `titles` rewires its margin presets to the same table.

**Tech Stack:** Python 3, dataclasses (config-spec pattern), pytest (`pythonpath=.`, `integration` marker), ffmpeg (integration only). No new third-party dependency.

**Design:** [docs/specs/2026-07-16-safe-zones-design.md](../specs/2026-07-16-safe-zones-design.md)

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `scripts/lib/geometry.py` | pure crop/projection geometry | **+** `marks_at_times`/`_interp` (moved from storyboard) |
| `scripts/storyboard.py` | contact-sheet driver | re-imports `marks_at_times` from geometry (bodies removed) |
| `scripts/lib/safezones.py` | **new** — safe-zone table + projection + decision | `SafeZone`, `SAFE_ZONES`, `safe_zone_for`, `default_zone`, `subject_marks`, `evaluate` |
| `scripts/lib/models.py` | typed wire-contracts | `ReelEpisode` +`path`/`meta`; `ReelManifest` +`platform`; `_ADVISORY_CHECKS` +`"safe_zones"` |
| `scripts/check_reel.py` | whole-reel mechanical gate | `run(geometry=,platform=)`; compute safe_zones; drop `_NOT_IMPL` |
| `scripts/build_reel.py` | reel retry-loop driver | build geometry list + pass `platform` |
| `scripts/edl_to_reel.py` | EDL→reel sequential driver | wire `path`/`meta` into each `ReelEpisode` |
| `scripts/lib/titles.py` | titles drawtext chain | `_Y_EXPR` from `safezones.default_zone()` |
| `tests/lib/test_geometry.py` | +projection unit test | |
| `tests/lib/test_safezones.py` | **new** — pure unit tests | |
| `tests/lib/test_check_reel.py` | +safe_zones tests; update the stub-status test | |
| `tests/lib/test_models.py` | +path/meta/platform/advisory tests | |
| `tests/lib/test_build_reel.py` | widen mock lambda; +geometry/platform test | |
| `tests/lib/test_edl_to_reel.py` | +path/meta wiring assertion | |
| `tests/lib/test_titles.py` | +margin-source regression pin | |
| `tests/integration/test_safezones.py` | **new** — real-ffmpeg advisory proof | |

**Env:** run every command from the repo root with the project venv:
`.venv/bin/python -m pytest ...`. Scripts run as modules (`pythonpath=.`).

---

### Task 0: Move `marks_at_times` → `lib/geometry.py`

A checker (`check_reel`/`safezones`) must not import a sibling driver (`storyboard`). Move the projection into `lib/geometry.py`. It cannot import `models` at runtime (`models` already imports `geometry.even` → cycle), so the model types are annotated under `TYPE_CHECKING`. `storyboard` re-imports the function, so `storyboard.marks_at_times` still resolves and existing tests are untouched.

**Files:**
- Modify: `scripts/lib/geometry.py:1-4` (imports), append the two functions
- Modify: `scripts/storyboard.py:5` (import), delete `scripts/storyboard.py:57-98`
- Test: `tests/lib/test_geometry.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_geometry.py`:

```python
def test_marks_at_times_projects_subject_into_canvas_fractions():
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    # fill layout, 1000x2000 out; crop 1000x2000 at y=0; subject centre at x=500 (crop-x 0)
    route = [RoutePoint(0.0, 500.0, 900.0, 100.0, 200.0),
             RoutePoint(2.0, 500.0, 900.0, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta(mode="fill", crop_w=1000, crop_h=2000, crop_y=0, src_dims=(1000, 2000),
                    canvas=(1000, 2000), out_dims=(1000, 2000), rect_px=(0, 0, 1000, 2000), freedom=0)
    marks = geometry.marks_at_times(route, path, meta, [0.0, 1.0, 2.0])
    assert marks[0] == (0.5, 0.45)             # x-cx=500 → 0.5 ; y=900/2000 → 0.45
    assert marks == [(0.5, 0.45)] * 3          # constant route → constant marks


def test_marks_at_times_rejects_desync():
    import pytest
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000), (0, 0, 1000, 2000), 0)
    with pytest.raises(ValueError, match="parallel arrays"):
        geometry.marks_at_times([RoutePoint(0.0, 1.0, 1.0, 1.0, 1.0)], CropPath([0, 0]), meta, [0.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py::test_marks_at_times_projects_subject_into_canvas_fractions -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.geometry' has no attribute 'marks_at_times'`

- [ ] **Step 3: Add the functions to `lib/geometry.py`**

Change the top of `scripts/lib/geometry.py` (lines 1-4):

```python
"""Pure crop geometry for the follow algorithm (spec §6.2, §6.4, §6.5)."""
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:                       # runtime import would cycle: models imports geometry.even
    from scripts.lib.models import RoutePoint, CropPath, PathMeta

_Num = TypeVar("_Num", int, float)
```

Append to the end of `scripts/lib/geometry.py`:

```python
def _interp(ts: list[float], xs: list[float], t: float) -> float:
    if t <= ts[0]:
        return xs[0]
    if t >= ts[-1]:
        return xs[-1]
    for i in range(1, len(ts)):
        if t <= ts[i]:
            f = (t - ts[i - 1]) / (ts[i] - ts[i - 1]) if ts[i] != ts[i - 1] else 0.0
            return xs[i - 1] + f * (xs[i] - xs[i - 1])
    return xs[-1]


def marks_at_times(route: "list[RoutePoint]", path: "CropPath", meta: "PathMeta",
                   times: list[float]) -> list[tuple[float, float]]:
    """(fx, fy) subject fractions in the OUTPUT frame at each sample TIME.

    The crop is placed inside `meta.rect_px`, which for `fill` is the whole
    output — so this reduces to the plain (x - cx) / crop_w there, and stays
    correct when the crop is a card in a larger canvas. fy divides by crop_h and
    honours meta.crop_y, so a canvas with vertical freedom maps right too. Route
    x/y and crop-x are interpolated on t so a mark lands on the right frame even
    on a gappy route."""
    if not route or len(route) != len(path):
        raise ValueError(f"route/path must be non-empty parallel arrays, "
                         f"got {len(route)} vs {len(path)}")
    ts = [p.t for p in route]
    xs = [p.x for p in route]
    ys = [p.y for p in route]
    cxs = path.xs
    rx, ry, rw, rh = meta.rect_px
    out_w, out_h = meta.out_dims
    marks = []
    for t in times:
        x = _interp(ts, xs, t)
        y = _interp(ts, ys, t)
        cx = _interp(ts, cxs, t)
        fx = (rx + rw * (x - cx) / meta.crop_w) / out_w
        fy = (ry + rh * (y - meta.crop_y) / meta.crop_h) / out_h
        marks.append((fx, fy))
    return marks
```

- [ ] **Step 4: Point storyboard at the moved function**

In `scripts/storyboard.py`, change line 5 from:

```python
from scripts.lib.geometry import grid_lines
```

to:

```python
from scripts.lib.geometry import grid_lines, marks_at_times
```

Then **delete** the now-duplicate `_interp` (lines 57-66) and `marks_at_times` (lines 69-98) definitions from `scripts/storyboard.py`. Its `build()` still calls `marks_at_times(...)` (now the import).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py tests/integration/test_verify.py tests/integration/test_storyboard.py tests/integration/test_process_episode.py -v`
Expected: PASS — the new geometry tests pass, and the storyboard/verify/process_episode tests that reference `storyboard.marks_at_times` still resolve it through the re-export.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/geometry.py scripts/storyboard.py tests/lib/test_geometry.py
git commit -m "refactor: move marks_at_times projection to lib/geometry (checker can't import a driver)"
```

---

### Task 1: `lib/safezones.py` — `SafeZone` + table + lookup

**Files:**
- Create: `scripts/lib/safezones.py`
- Test: `tests/lib/test_safezones.py`

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_safezones.py`:

```python
import pytest

from scripts.lib import safezones
from scripts.lib.safezones import SafeZone, SAFE_ZONES


def test_safezone_contains_inside_and_outside():
    z = SafeZone(top=0.08, bottom=0.12, left=0.05, right=0.05)
    assert z.contains(0.5, 0.45) is True          # centred subject
    assert z.contains(0.5, 0.95) is False         # under the bottom band (0.95 > 1-0.12)
    assert z.contains(0.97, 0.5) is False          # in the right rail
    assert z.contains(0.05, 0.08) is True          # exact corner is inside (inclusive)


@pytest.mark.parametrize("kw,msg", [
    (dict(top=0.5, bottom=0.1, left=0.05, right=0.05), "top"),        # >= 0.5
    (dict(top=-0.01, bottom=0.1, left=0.05, right=0.05), "top"),      # < 0
    (dict(top=0.1, bottom="x", left=0.05, right=0.05), "bottom"),     # non-numeric
    (dict(top=0.1, bottom=True, left=0.05, right=0.05), "bottom"),    # bool is not a fraction
])
def test_safezone_validation_fails_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        SafeZone(**kw)


def test_safe_zone_for_known_alias_and_default():
    assert safezones.safe_zone_for("tiktok") is SAFE_ZONES["tiktok"]
    assert safezones.safe_zone_for("Instagram") is SAFE_ZONES["reels"]   # alias, case-insensitive
    assert safezones.safe_zone_for("YT") is SAFE_ZONES["shorts"]
    assert safezones.safe_zone_for("") is SAFE_ZONES["generic"]          # empty → generic
    assert safezones.safe_zone_for("myspace") is SAFE_ZONES["generic"]   # unknown → generic


def test_default_zone_is_generic_and_matches_titles_presets():
    z = safezones.default_zone()
    assert z is SAFE_ZONES["generic"]
    assert (z.top, z.bottom) == (0.08, 0.12)      # == titles _Y_EXPR presets
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_safezones.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.safezones'`

- [ ] **Step 3: Write `lib/safezones.py` (table half)**

Create `scripts/lib/safezones.py`:

```python
"""Platform-keyed safe-zone check for §5.13 reel-final. A SafeZone is the UI-chrome
margin table for one platform (canvas fractions); the SAFE region is the rectangle
[left, 1-right] x [top, 1-bottom]. The subject (projected via lib.geometry) must sit
inside it. Advisory — check_reel reports it, never blocks on it. New platforms are
new table entries, not new code (mirrors ExportProfile)."""
from dataclasses import dataclass

from scripts.lib.geometry import marks_at_times
from scripts.lib.models import RoutePoint, CropPath, PathMeta


@dataclass(frozen=True)
class SafeZone:
    """Platform UI-chrome margins as canvas fractions. Values are conservative,
    tunable estimates of where each app draws overlays — they shift across app
    versions, so they live in a table, not a pixel spec."""
    top: float
    bottom: float
    left: float
    right: float

    def __post_init__(self) -> None:
        for name in ("top", "bottom", "left", "right"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v < 0.5:
                raise ValueError(f"SafeZone.{name} must be a fraction in [0.0, 0.5), got {v!r} "
                                 "— a margin at/over half the frame leaves no safe region")

    def contains(self, fx: float, fy: float) -> bool:
        """Is the point (canvas fractions) inside the safe region?"""
        return self.left <= fx <= 1.0 - self.right and self.top <= fy <= 1.0 - self.bottom


SAFE_ZONES: dict[str, SafeZone] = {
    "generic": SafeZone(top=0.08, bottom=0.12, left=0.05, right=0.05),   # == titles presets
    "tiktok":  SafeZone(top=0.08, bottom=0.18, left=0.04, right=0.12),   # tall caption + right rail
    "reels":   SafeZone(top=0.08, bottom=0.16, left=0.04, right=0.11),   # instagram
    "shorts":  SafeZone(top=0.10, bottom=0.14, left=0.04, right=0.11),   # youtube
}
_ALIASES = {"instagram": "reels", "ig": "reels", "reel": "reels",
            "youtube": "shorts", "yt": "shorts"}


def safe_zone_for(platform: str) -> SafeZone:
    """Resolve a free-text platform label to its zone; unknown/empty → generic."""
    key = (platform or "").strip().lower()
    key = _ALIASES.get(key, key)
    return SAFE_ZONES.get(key, SAFE_ZONES["generic"])


def default_zone() -> SafeZone:
    """The generic zone — titles' single margin source (§5.16)."""
    return SAFE_ZONES["generic"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_safezones.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/safezones.py tests/lib/test_safezones.py
git commit -m "feat: SafeZone config-spec + SAFE_ZONES platform table + safe_zone_for/default_zone"
```

---

### Task 2: `lib/safezones.py` — `subject_marks` + `evaluate`

**Files:**
- Modify: `scripts/lib/safezones.py` (append)
- Test: `tests/lib/test_safezones.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_safezones.py`:

```python
from scripts.lib.models import RoutePoint, CropPath, PathMeta


def _geom(x, y):
    # fill 1000x2000; subject centre at (x,y) source px, crop-x 0
    route = [RoutePoint(0.0, x, y, 100.0, 200.0), RoutePoint(2.0, x, y, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000),
                    (0, 0, 1000, 2000), 0)
    return route, path, meta


def test_subject_marks_samples_five_points_across_the_episode():
    route, path, meta = _geom(500.0, 900.0)
    marks = safezones.subject_marks(route, path, meta, dur=2.0)
    assert len(marks) == 5
    assert marks == [(0.5, 0.45)] * 5             # constant route → constant marks


def test_evaluate_passes_when_every_subject_is_inside():
    zone = safezones.safe_zone_for("generic")
    inside = [(0.5, 0.45), (0.33, 0.5)]
    passed, detail = safezones.evaluate([inside, inside], zone)
    assert passed is True and detail["advisory"] is True and detail["episodes"] == 2


def test_evaluate_flags_the_worst_offender_episode():
    zone = safezones.safe_zone_for("tiktok")       # bottom band 0.18
    ep0 = [(0.5, 0.45)]                             # safe
    ep1 = [(0.5, 0.70), (0.5, 0.99)]               # 0.99 is deepest under the caption band
    passed, detail = safezones.evaluate([ep0, ep1], zone)
    assert passed is False
    assert detail["worst_episode"] == 1
    assert detail["worst_mark"] == [0.5, 0.99]
    assert detail["advisory"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_safezones.py::test_subject_marks_samples_five_points_across_the_episode -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.safezones' has no attribute 'subject_marks'`

- [ ] **Step 3: Append `subject_marks` + `evaluate` to `lib/safezones.py`**

```python
_SAFE_SAMPLES = 5


def _sample_times(dur: float) -> list[float]:
    return [(k + 0.5) * dur / _SAFE_SAMPLES for k in range(_SAFE_SAMPLES)]


def subject_marks(route: list[RoutePoint], path: CropPath, meta: PathMeta,
                  dur: float) -> list[tuple[float, float]]:
    """The subject's (fx, fy) canvas fractions at _SAFE_SAMPLES points across the
    episode — the projection lib.geometry already implements, sampled by time."""
    return marks_at_times(route, path, meta, _sample_times(dur))


def evaluate(marks_per_ep: list[list[tuple[float, float]]],
             zone: SafeZone) -> tuple[bool, dict]:
    """Pure decision: flag if any subject mark in any episode falls outside its safe
    region. The report names the worst offender (deepest overshoot) so a human sees
    where. Advisory — the caller never turns this into a ReelFailure."""
    worst = None                                   # (overshoot, episode_idx, fx, fy)
    for i, marks in enumerate(marks_per_ep):
        for fx, fy in marks:
            if not zone.contains(fx, fy):
                over = max(zone.left - fx, fx - (1.0 - zone.right),
                           zone.top - fy, fy - (1.0 - zone.bottom))
                if worst is None or over > worst[0]:
                    worst = (over, i, round(fx, 4), round(fy, 4))
    if worst is None:
        return True, {"episodes": len(marks_per_ep), "advisory": True}
    _, idx, fx, fy = worst
    return False, {"worst_episode": idx, "worst_mark": [fx, fy],
                   "zone": {"top": zone.top, "bottom": zone.bottom,
                            "left": zone.left, "right": zone.right}, "advisory": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_safezones.py -v`
Expected: PASS (all Task 1 + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/safezones.py tests/lib/test_safezones.py
git commit -m "feat: safezones.subject_marks (k=5 projection) + evaluate (advisory worst-offender decision)"
```

---

### Task 3: `models.py` — `ReelEpisode.path/meta`, `ReelManifest.platform`, advisory

**Files:**
- Modify: `scripts/lib/models.py` — `_ADVISORY_CHECKS` (632), `ReelEpisode` (683-690), `ReelManifest` (693-759)
- Test: `tests/lib/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_reel_episode_path_meta_round_trip():
    rm = m.ReelManifest.from_dict(_reel_dict(episodes=[
        {"manifest": {}, "clip": "c.mp4", "route": "r.json", "path": "p.json", "meta": "pm.json"}]))
    assert rm.episodes[0].path == "p.json" and rm.episodes[0].meta == "pm.json"


def test_reel_episode_path_meta_default_empty():
    rm = m.ReelManifest.from_dict(_reel_dict())
    assert rm.episodes[0].path == "" and rm.episodes[0].meta == ""    # backward compatible


def test_reel_manifest_rejects_a_lone_sidecar():
    with pytest.raises(ValueError, match="path and meta must both"):
        m.ReelManifest.from_dict(_reel_dict(episodes=[
            {"manifest": {}, "clip": "c.mp4", "route": "r.json", "path": "p.json"}]))   # meta missing


def test_reel_manifest_platform_default_and_set():
    assert m.ReelManifest.from_dict(_reel_dict()).platform == ""
    assert m.ReelManifest.from_dict(_reel_dict(platform="tiktok")).platform == "tiktok"


def test_reelreport_overall_excludes_advisory_safe_zones():
    rr = m.ReelReport(checks={"safe_zones": m.CheckResult("safe_zones", False, {"advisory": True})})
    assert rr.overall is True          # advisory False never blocks the reel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py::test_reel_episode_path_meta_round_trip tests/lib/test_models.py::test_reelreport_overall_excludes_advisory_safe_zones -v`
Expected: FAIL — `TypeError: ReelEpisode.__init__() got an unexpected keyword argument 'path'` and the advisory test fails (`overall is False`).

- [ ] **Step 3: Edit `models.py`**

Change `_ADVISORY_CHECKS` (line 632):

```python
_ADVISORY_CHECKS = ("beat", "safe_zones")   # measured + reported but non-blocking (design §5)
```

Change `ReelEpisode` (lines 683-690) to add the two fields:

```python
@dataclass(frozen=True)
class ReelEpisode:
    """One entry in a ReelManifest: the per-episode manifest (so a reprocess can
    rebuild it), the locked clip loop-1 produced, and the frozen route.json (a
    reprocess reuses it — colour/black fixes never move the track). `path`/`meta`
    are the frozen path.json / path.meta.json sidecars — safe_zones (§5.13) projects
    the subject through them; empty = geometry unavailable (safe_zones not-checked)."""
    manifest: dict
    clip: str
    route: str
    path: str = ""
    meta: str = ""
```

In `ReelManifest.__post_init__`, inside the `for k, e in enumerate(self.episodes):` loop, after the existing `route` check (line 720-722), add:

```python
            if bool(e.path) != bool(e.meta):
                raise ValueError(f"ReelManifest.episodes[{k}]: path and meta must both be set or "
                                 "both empty — a lone sidecar cannot project the subject for safe_zones")
```

Add the `platform` field to `ReelManifest` (after `sfx`, line 706):

```python
    platform: str = ""                 # UI safe-zone table key (§5.13); "" → generic; from Spec.platform
```

Add the platform guard in `__post_init__` (after the `sfx` guard, ~line 732):

```python
        if not isinstance(self.platform, str):
            raise ValueError(f"ReelManifest.platform must be a string label (e.g. 'tiktok'), "
                             f"got {self.platform!r}")
```

In `ReelManifest.from_dict`, change the `ReelEpisode(...)` construction (lines 751-752) and the `cls(...)` return (lines 754-759):

```python
        eps = [ReelEpisode(manifest=_load_manifest(e.get("manifest")),
                           clip=e.get("clip", ""), route=e.get("route", ""),
                           path=e.get("path", ""), meta=e.get("meta", ""))
               for e in eps_in]
        return cls(episodes=eps, target_dur=d.get("target_dur"),
                   variety_min=d.get("variety_min", 8),
                   color_delta_max=d.get("color_delta_max", 12.0),
                   cap=d.get("cap", 3), changelog=d.get("changelog", ""),
                   music=d.get("music"), ambient=d.get("ambient", True),
                   sfx=d.get("sfx", False), platform=d.get("platform", ""))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -v`
Expected: PASS (new tests + all existing model tests — the `ReelEpisode` positional construction in other tests still works because `path`/`meta` default to `""`).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelEpisode.path/meta + ReelManifest.platform + safe_zones advisory"
```

---

### Task 4: `check_reel.py` — compute safe_zones (advisory), drop `_NOT_IMPL`

**Files:**
- Modify: `scripts/check_reel.py` — imports (16-23), `run` signature + body (126-209)
- Test: `tests/lib/test_check_reel.py`

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_check_reel.py`, **replace** `test_beat_loudness_not_checked_safe_zones_not_implemented` (lines 61-76) with:

```python
def test_beat_loudness_safe_zones_not_checked_when_silent(tmp_path, monkeypatch):
    # distinct hashes so the variety check passes (see the color/variety tests).
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    # all three now read "not-checked" — beat/loudness lack audio, safe_zones lacks geometry.
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None
        assert rep.checks[name].detail["status"] == "not-checked"
    assert rep.overall is True
    assert rep.wall_s >= 0.0 and rep.episode_count == 2
```

Then append the computed-check tests:

```python
def _write_geom(dir_path, x, y):
    """Write route.json / path.json / path.meta.json (fill 1000x2000; subject centre
    (x,y) source px, crop-x 0) and return the (route, path, meta) path triple."""
    import json
    from pathlib import Path
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "route.json").write_text(json.dumps(
        [{"t": 0.0, "x": x, "y": y, "w": 100.0, "h": 200.0},
         {"t": 3.0, "x": x, "y": y, "w": 100.0, "h": 200.0}]))
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": "fill", "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": [0, 0, 1000, 2000], "freedom": 0}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


def test_safe_zones_passes_when_every_subject_is_framed_safely(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # fy 0.45 safe
            _write_geom(tmp_path / "ep1", 500.0, 900.0)]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True
    assert rep.checks["safe_zones"].detail["advisory"] is True


def test_safe_zones_flags_low_subject_but_stays_advisory(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # safe
            _write_geom(tmp_path / "ep1", 500.0, 1960.0)]     # fy 0.98 → under tiktok caption band
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1
    assert rep.overall is True          # advisory — a False safe_zones never blocks the reel
    assert not [f for f in rep.fail_reasons if f.check == "safe_zones"]   # no ReelFailure emitted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py::test_safe_zones_flags_low_subject_but_stays_advisory -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'geometry'`

- [ ] **Step 3: Edit `check_reel.py`**

Change the imports block (lines 16-23):

```python
from scripts.lib import proc, safezones
from scripts.lib.models import (CheckResult, CropPath, MusicSpec, PathMeta, ReelCheckSpec,
                                ReelFailure, ReelReport, route_from_json)

# beat/loudness/safe_zones ARE implemented — they fall through to "not-checked" only when
# the reel lacks the input each needs (music/audio for beat/loudness, per-episode geometry
# for safe_zones). Nothing is genuinely "not-implemented" anymore.
_UNCHECKED = {"beat": "not checked — no MUSIC.json supplied (silent reel)",
              "loudness": "not checked — no audio stem supplied (silent reel)",
              "safe_zones": "not checked — no per-episode geometry supplied"}
```

(This deletes the old `_NOT_IMPL = {...}` line.)

Change the `run` signature (line 126-127):

```python
def run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str,
        music: MusicSpec | None = None, audio: str | None = None,
        geometry: list[tuple[str, str, str]] | None = None, platform: str = "") -> ReelReport:
```

After the `if music is not None:` block (after line 199) and before the `_UNCHECKED` loop (line 201), insert:

```python
    if geometry is not None:
        zone = safezones.safe_zone_for(platform)
        marks_per_ep = [safezones.subject_marks(route_from_json(r), CropPath.from_json(p),
                                                PathMeta.from_json(m), dur)
                        for (r, p, m), dur in zip(geometry, durations)]
        passed, detail = safezones.evaluate(marks_per_ep, zone)
        checks["safe_zones"] = CheckResult("safe_zones", passed, detail)
```

**Delete** the `_NOT_IMPL` fill loop (lines 203-204):

```python
    for name, reason in _NOT_IMPL.items():
        checks.setdefault(name, CheckResult(name, None, {"status": "not-implemented", "reason": reason}))
```

(The `_UNCHECKED` loop at 201-202 now fills `safe_zones` too when geometry is absent.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "feat: check_reel computes safe_zones (advisory) from per-episode geometry; drop _NOT_IMPL"
```

---

### Task 5: `build_reel.py` + `edl_to_reel.py` — thread geometry + platform

**Files:**
- Modify: `scripts/build_reel.py:44` (the `check_reel.run` call) + add the geometry list (before the loop, ~line 38)
- Modify: `scripts/edl_to_reel.py:47-48`
- Test: `tests/lib/test_build_reel.py`, `tests/lib/test_edl_to_reel.py`

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_build_reel.py`, **widen** the `_wire` mock lambda (line 38) so it tolerates + records the new kwargs:

```python
    def fake_run(m, e, s, o, music=None, audio=None, geometry=None, platform=""):
        seen["geometry"] = geometry
        seen["platform"] = platform
        return rq.pop(0)
    monkeypatch.setattr(build_reel.check_reel, "run", fake_run)
```

and add `"geometry": None, "platform": None` initialisation to the `seen` dict (line 29):

```python
    seen = {"deliver": [], "reprocess": [], "titles": [], "geometry": None, "platform": ""}
```

Add a new test (uses `_rm`, whose episodes have empty path/meta → geometry stays None; and a geometry-carrying variant):

```python
def test_build_reel_passes_platform_and_omits_geometry_without_sidecars(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["geometry"] is None          # _rm episodes carry no path/meta → no geometry
    assert seen["platform"] == ""            # _rm sets no platform → generic


def test_build_reel_builds_geometry_and_platform_when_sidecars_present(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    eps = [ReelEpisode(manifest={"segment": "s.mp4"}, clip="c0.mp4", route="r0.json",
                       path="p0.json", meta="pm0.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, platform="tiktok")
    build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["geometry"] == [("r0.json", "p0.json", "pm0.json")]
    assert seen["platform"] == "tiktok"
```

In `tests/lib/test_edl_to_reel.py`, after the existing route assertion (line 62), add:

```python
    assert rm.episodes[0].path.endswith("ep0/path.json")
    assert rm.episodes[0].meta.endswith("ep0/path.meta.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py::test_build_reel_builds_geometry_and_platform_when_sidecars_present -v`
Expected: FAIL — `seen["geometry"]` is `None` / `KeyError` (build_reel doesn't build or pass geometry yet).

- [ ] **Step 3: Edit `build_reel.py`**

In `build_reel`, after `audio: str | None = None` (line 37) and before `need_assemble = True` (line 38), add:

```python
    geometry = ([(e.route, e.path, e.meta) for e in rm.episodes]   # frozen sidecars — constant across rounds
                if all(e.path and e.meta for e in rm.episodes) else None)
```

Change the `check_reel.run` call (line 44):

```python
        report = check_reel.run(master, clips, rm.check_spec, report_path,
                                music=music, audio=audio, geometry=geometry, platform=rm.platform)
```

- [ ] **Step 4: Edit `edl_to_reel.py`**

Change the `ReelEpisode` construction (lines 47-48):

```python
        episodes.append(ReelEpisode(manifest=md, clip=res["clip"],
                                    route=str(Path(epdir) / "route.json"),
                                    path=str(Path(epdir) / "path.json"),
                                    meta=str(Path(epdir) / "path.meta.json")))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py tests/lib/test_edl_to_reel.py -v`
Expected: PASS (new + existing — the `_wire_music`/`_wire` fixtures already tolerate the extra kwargs).

- [ ] **Step 6: Commit**

```bash
git add scripts/build_reel.py scripts/edl_to_reel.py tests/lib/test_build_reel.py tests/lib/test_edl_to_reel.py
git commit -m "feat: build_reel threads per-episode geometry + platform to check_reel; edl_to_reel wires path/meta"
```

---

### Task 6: `titles` — margins from the shared table

**Files:**
- Modify: `scripts/lib/titles.py:115-119`
- Test: `tests/lib/test_titles.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_titles.py`:

```python
def test_titles_margins_are_sourced_from_the_safe_zone_table():
    # genuine fail-first: titles._Z does not exist until the rewire, so this raises
    # AttributeError before Step 3 — value-based checks would coincide (generic == 0.08/0.12).
    from scripts.lib import titles, safezones
    assert titles._Z is safezones.default_zone()
    assert titles._Y_EXPR["top"] == f"h*{safezones.default_zone().top}"
    assert titles._Y_EXPR["bottom"] == f"h-th-h*{safezones.default_zone().bottom}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py::test_titles_margins_are_sourced_from_the_safe_zone_table -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.titles' has no attribute '_Z'` (the margins are still the hardcoded literals).

- [ ] **Step 3: Edit `titles.py`**

Replace the `_Y_EXPR` block (lines 115-119) with a table-derived one:

```python
from scripts.lib import safezones
_Z = safezones.default_zone()
_Y_EXPR: dict[str, str] = {          # safe-margin presets from the shared SafeZone table (§5.13/§5.16)
    "top": f"h*{_Z.top}",
    "center": "(h-th)/2",
    "bottom": f"h-th-h*{_Z.bottom}",
}
```

Add the import near the other imports (line 12 area) — the `from scripts.lib import safezones` line may live either at the top with the other imports or immediately above `_Z`; keep it above `_Z`. Ensure the top-of-file imports stay grouped (move `from scripts.lib import safezones` up next to `from scripts.lib.fonts import resolve_font` if the linter prefers).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py tests/integration/test_titles.py -v`
Expected: PASS — the new pin passes, and the existing `test_build_filterchain_positions_and_styles` still finds `"y=h*0.08"` / `"y=h-th-h*0.12"` (generic top/bottom are `0.08`/`0.12`, so the rendered expressions are unchanged).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/titles.py tests/lib/test_titles.py
git commit -m "refactor: titles _Y_EXPR margins from safezones.default_zone (one margin authority)"
```

---

### Task 7: real-ffmpeg integration proof

**Files:**
- Create: `tests/integration/test_safezones.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_safezones.py`:

```python
"""Real-ffmpeg proof for §5.13 safe_zones: a low-framed subject is flagged (advisory)
on a genuinely assembled master, and the reel still passes overall (deliver's gate is
overall, which advisory checks never drop). Mirrors tests/integration/test_ambient.py."""
import json
import shutil
from pathlib import Path

import pytest

from scripts import check_reel
from scripts.lib import assembly
from scripts.lib.models import ReelCheckSpec


def _solid(path, color, secs):
    from scripts.lib import proc
    proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x568:d={secs}:r=30",
              "-pix_fmt", "yuv420p", str(path)])
    return str(path)


def _write_geom(dir_path, y):
    """route/path/path.meta sidecars: fill 1000x2000, subject centre x=500 (crop-x 0),
    vertical y in source px. Returns the (route, path, meta) path triple."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "route.json").write_text(json.dumps(
        [{"t": 0.0, "x": 500.0, "y": y, "w": 100.0, "h": 200.0},
         {"t": 1.0, "x": 500.0, "y": y, "w": 100.0, "h": 200.0}]))
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": "fill", "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": [0, 0, 1000, 2000], "freedom": 0}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


@pytest.mark.integration
def test_safe_zones_flags_low_subject_without_blocking_delivery(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    clips = [_solid(tmp_path / "c0.mp4", "red", 1.0), _solid(tmp_path / "c1.mp4", "blue", 1.0)]
    master = str(tmp_path / "master.mp4")
    assembly.assemble(clips, (320, 568), 30.0, master)               # a genuinely assembled master
    geom = [_write_geom(tmp_path / "ep0", 900.0),                    # fy 0.45 — safe
            _write_geom(tmp_path / "ep1", 1960.0)]                   # fy 0.98 — under the caption band
    rep = check_reel.run(master, clips, ReelCheckSpec(target_dur=2.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False                 # ep1 subject under UI chrome
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1
    assert rep.overall is True                                      # advisory → deliver's gate still opens
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/python -m pytest tests/integration/test_safezones.py -v`
Expected: PASS (assembles a real master, computes safe_zones from the hand-written sidecars).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_safezones.py
git commit -m "test: real-ffmpeg proof — safe_zones flags a low subject, advisory never blocks delivery"
```

---

### Task 8: docs sync + final whole-slice review

**Files:**
- Modify: `docs/pipeline-map.md`, `docs/build-status.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/specs/2026-07-10-reel-back-half-design.md`, `docs/specs/2026-07-11-music-spine-design.md`, `docs/specs/2026-07-13-titles-design.md`, `CLAUDE.md`

- [ ] **Step 1: `docs/pipeline-map.md`**

- Row 5.13 (line 29): status `◐ → ✅`; note becomes: `check_reel mechanical ✅; loudness (hard) + beat (advisory) ✅; safe_zones (advisory: route-geom subject vs platform SafeZone table) ✅ — §5.13 complete`.
- Blockers row 5.13 (line 65): `◐ → ✅`, "Left to build" → `— (2026-07-16)`.
- Tally (line 71): `14 ✅ · 1 ◐ · 1 ❌` → `15 ✅ · 0 ◐ · 1 ❌`.
- The "only 5.13 safe_zones and cast→hero-pin stay genuinely open" prose (lines 88-89) → drop safe_zones; cast→hero-pin remains the open quality item.
- "What produces a reel today" (line 108-109): the `safe_zones` `not-implemented` clause → `safe_zones` now reports an advisory pass/False from the per-episode route (or `not-checked` when a reel carries no geometry).
- Roadmap "Editorial reel-final" bullet (line 128): mark `safe_zones` done; leave structural/editorial review as the remaining editorial follow-on.
- Bump `_Last updated_` (line 9) to `2026-07-16`.

- [ ] **Step 2: `docs/build-status.md`**

Add a new DONE entry at the top of the changelog list:

```markdown
- **safe-zones (§5.13) DONE (2026-07-16)** — plan
  `docs/plans/2026-07-16-safe-zones.md` + design
  `docs/specs/2026-07-16-safe-zones-design.md`. Closes the last unbuilt
  `check_reel` check. `scripts/lib/safezones.py` — `SafeZone` config-spec +
  `SAFE_ZONES` platform table (`generic`/`tiktok`/`reels`/`shorts`, generic ==
  titles' 0.08/0.12) + `safe_zone_for`/`default_zone` + `subject_marks` (k=5) +
  pure `evaluate` (worst-offender). The subject→canvas projection
  `marks_at_times` moved from `scripts/storyboard.py` to `scripts/lib/geometry.py`
  (a checker must not import a driver; `storyboard` re-imports it). `check_reel.run`
  gains `geometry=`/`platform=`: with the frozen per-episode sidecars it projects
  each subject and tests it against the zone, reporting an **advisory** `CheckResult`
  (joins `_ADVISORY_CHECKS` with `beat` — reported, out of `overall`, no
  `ReelFailure`); `_NOT_IMPL` is gone (nothing is unimplemented now — a
  geometry-less reel reports `not-checked`). `ReelEpisode` gains `path`/`meta`,
  `ReelManifest` gains `platform` (from `Spec.platform`); `build_reel` builds the
  geometry list once (invariant across colour/black reprocess — the route is frozen)
  and `edl_to_reel` wires the sidecars. `titles._Y_EXPR` now derives its margins
  from `safezones.default_zone()` (one authority; rendered exprs unchanged). No
  auto-fix actuator exists, so the check stays advisory by design. **N tests green**
  (M new incl. 1 real-ffmpeg proof in `tests/integration/test_safezones.py`).
```

(Fill `N`/`M` from the Step 4 suite run.) Update any Next-action pointer that still names `safe_zones` as pending.

- [ ] **Step 3: master spec `docs/specs/2026-07-05-montage-skillset-design.md`**

- §5.13/§584 (line ~584): the "**safe-zones** remains deferred, reporting `not-implemented`" clause → "**safe-zones** (advisory) — the tracked subject, projected into canvas coords, tested against a platform `SafeZone` table; reports an advisory pass/False, or `not-checked` when a reel carries no per-episode geometry (built 2026-07-16)."
- §5.13 checks line (line ~542): leave "subject in safe-zone" but note it is the advisory, route-geometry check; "layout transitions not jarring" / "pad bars clean" stay editorial follow-ons.

- [ ] **Step 4: flip the "deferred" notes in the three specs**

- `docs/specs/2026-07-10-reel-back-half-design.md` (lines ~152, ~252): the `safe_zones` `not-implemented`/"needs per-episode route" rows → note it is built (2026-07-16) as an advisory route-geometry check.
- `docs/specs/2026-07-11-music-spine-design.md` (lines ~26, ~344): "`safe_zones` stays deferred / honest `passed=None`" → built 2026-07-16 (advisory).
- `docs/specs/2026-07-13-titles-design.md` (lines ~7, ~161, ~171): safe-zones is no longer deferred — titles now resolve their margins from the shared `SafeZone` table (`safezones.default_zone()`); the full pixel-level gate is still a non-goal (this is subject-route geometry, not pixel CV).

- [ ] **Step 5: `CLAUDE.md` registry**

Add two rows to the Quick Reference table (after the Transition-SFX rows):

```markdown
| Safe-zones design | [2026-07-16-safe-zones-design.md](docs/specs/2026-07-16-safe-zones-design.md) | §5.13 final check: route-geom subject → canvas (reuse `marks_at_times`) vs platform `SafeZone` table; **advisory** (no auto-fix — reprocess reuses the frozen route); `SAFE_ZONES` + titles rewired to it; closes 5.13. |
| Safe-zones plan | [2026-07-16-safe-zones.md](docs/plans/2026-07-16-safe-zones.md) | Tasks 0-8: move `marks_at_times`→geometry, `safezones.py` (SafeZone/table/evaluate), models path/meta+platform+advisory, check_reel geometry/platform, build_reel/edl_to_reel wiring, titles margin rewire, real-ffmpeg proof, docs sync. |
```

Update the Music-spine registry row's tail if it still claims safe_zones deferred (it names the §5.12 SFX close; leave unless it mentions safe_zones).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: all green (unit + integration where ffmpeg present), `EXIT: 0`. Record the pass/skip counts and backfill `N`/`M` in the build-status entry (Step 2).

- [ ] **Step 7: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: sync safe-zones (§5.13) — 5.13 ✅, tally 15✅·0◐·1❌, specs+registry"
```

- [ ] **Step 8: Final whole-slice review**

Dispatch a final reviewer over the whole branch diff (`git diff main...HEAD`) against the design. Verify, on real ffmpeg where relevant:
- the moved `marks_at_times` is byte-equivalent behaviour (storyboard golden unchanged);
- `safe_zones` is advisory end-to-end — a `False` never drops `overall` and never emits a `ReelFailure`; `reel_orchestration`/`next_action` untouched;
- geometry is invariant across a colour/black reprocess round (same sidecars reused);
- `_NOT_IMPL` is gone and a geometry-less reel reports `not-checked`, never a silent pass;
- titles' rendered `-vf` expressions are unchanged (generic zone == old presets);
- full suite green.

Address blocking findings in separate follow-up commits (never `--amend`).

---

## Self-Review

**1. Spec coverage:**
- §1 architecture / files → Tasks 0-8 (the File Structure table maps 1:1).
- §2 SafeZone + table → Task 1.
- §3 projection + subject_marks + evaluate → Task 0 (projection move) + Task 2.
- §4 check_reel wiring (geometry/platform, advisory, drop _NOT_IMPL) → Task 4.
- §5 contracts (ReelEpisode.path/meta, ReelManifest.platform, _ADVISORY_CHECKS) → Task 3.
- §6 drivers + reprocess-invariance → Task 5.
- §7 titles rewire → Task 6.
- §8 edge cases → covered by Task 2/4 tests (single-episode, partial-geometry→None, unknown platform→generic).
- §9 landmine notes (no new ffmpeg, projection move byte-preserving, advisory load-bearing) → Task 0 verify + Task 8 review.
- §10 testing → each task's tests + Task 7 integration.
- §11 non-goals → respected (no CV, no bbox-extent, no hard gate, generic-zone titles).
- §12 doc sync → Task 8.
No gaps.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". The only deferred literals are `N`/`M` test counts in the build-status prose (Task 8 Step 2), which are explicitly backfilled from the Step 6 suite run — a value to measure, not a code placeholder.

**3. Type consistency:**
- `marks_at_times(route, path, meta, times)` — defined Task 0, called by `safezones.subject_marks` (Task 2) and `check_reel` (Task 4) with the same argument order.
- `subject_marks(route, path, meta, dur)` → `evaluate(marks_per_ep, zone) -> (bool, dict)` — consistent Task 2 ↔ Task 4.
- `safe_zone_for(platform) -> SafeZone`, `default_zone() -> SafeZone` — Task 1, used Task 4 + Task 6.
- `check_reel.run(..., geometry=None, platform="")` — Task 4 signature matches the `build_reel` call (Task 5) and the widened test lambda (Task 5).
- `ReelEpisode(manifest, clip, route, path="", meta="")` — Task 3 definition matches `edl_to_reel` construction (Task 5) and `build_reel`'s `[(e.route, e.path, e.meta) ...]` (Task 5).
- `geometry` type is `list[tuple[str, str, str]]` everywhere (Task 4 sig, Task 5 build, Task 4/7 test `_write_geom` returns a 3-tuple).
No mismatches.

## Execution Handoff

Plan complete and saved to `docs/plans/2026-07-16-safe-zones.md`. Subagent-Driven execution (fresh subagent per task + two-stage review) per the repo's established workflow.
