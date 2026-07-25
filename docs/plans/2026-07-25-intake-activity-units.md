# Intake activity-units carving (feedback #3, slice 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace intake's equal-interval window carving (`_split_span`) with activity-anchored units — each window is a peak of activity plus its lead-in — carried by a new pure `scripts/lib/carve.py`, and annotate each window with the track ids present in it.

**Architecture:** A pure `lib/carve.py` (mirrors `lib/gridfit.py`) turns a per-span activity curve into `(start, dur)` units: local-maxima peaks (found relative to the clip, no absolute threshold), two candidates per peak (`tight` + `lead-in`), and a max-mean single window for a flat span — never a tiling. `intake.carve_windows` builds the curve per span (2-D bbox displacement where people are present, resampled vidstab camera motion otherwise) and calls carve. The vidstab detect pass moves ahead of carving so a people-less span has its curve at carve time; the magnitudes feed both the curve and the per-window shake. `FootageWindow` gains `track_ids`; `CACHE_VERSION` bumps.

**Tech Stack:** Python 3.13, pytest (`pythonpath = .`), ffmpeg via `scripts/lib/ffbin.py`, libvidstab, ultralytics YOLO11-seg, PySceneDetect, `imagehash`.

---

## Ground rules for the implementer

- Python is `.venv/bin/python` (3.13). Run tests as `.venv/bin/python -m pytest <path> -q` (repo sets `pythonpath = .`; scripts run as modules).
- **Never push.** Commit on this branch only. Each commit body ends with the trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- **Do NOT run any installer** (`brew`/`pip`/`uv`/`apt`/`npm`, `setup.sh`). The environment is already provisioned; verification is read-only + pytest. If a tool seems missing, STOP and report — do not install it.
- Never resolve ffmpeg from `PATH`; production and test argv go through `scripts/lib/ffbin.py`.
- Landmines (do not reintroduce): `-ss` **after** `-i`; `lutrgb` is banned (use `colorchannelmixer`); never stabilize wade-in/out shots. None of these are touched by this slice, but the lint (`scripts/lint.py`) runs in the suite and will catch a violation.
- Design source of truth: [docs/specs/2026-07-25-intake-activity-units-design.md](../specs/2026-07-25-intake-activity-units-design.md). Section refs below (§N) point there.

---

## Task 0: `lib/carve.py` primitives — curves, extrema, peaks

**Files:**
- Create: `scripts/lib/carve.py`
- Test: `tests/lib/test_carve.py`

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_carve.py`:

```python
import pytest
from scripts.lib import carve


def test_subject_curve_is_2d_and_zero_at_gaps():
    centers = [(0.0, 0.0), (3.0, 4.0), None, (0.0, 0.0)]
    # sample 1: hypot(3,4)=5; sample 2: gap → 0; sample 3: prev is a gap → 0
    assert carve.subject_curve(centers) == [0.0, 5.0, 0.0, 0.0]


def test_subject_curve_edges():
    assert carve.subject_curve([]) == []
    assert carve.subject_curve([(1.0, 1.0)]) == [0.0]


def test_camera_curve_samples_frame_magnitudes_at_times():
    mags = [0.0, 9.0, 0.0, 0.0]           # per-frame at fps=1 → frame i at second i
    assert carve.camera_curve(mags, fps=1.0, times=[0.0, 1.0, 3.5]) == [0.0, 9.0, 0.0]
    assert carve.camera_curve([], fps=1.0, times=[0.0, 1.0]) == [0.0, 0.0]


def test_camera_curve_clamps_past_the_last_frame():
    # a sample time beyond the last vidstab frame reads the last magnitude, never IndexErrors
    assert carve.camera_curve([0.0, 9.0], fps=1.0, times=[0.0, 1.0, 5.0]) == [0.0, 9.0, 9.0]


def test_camera_curve_rejects_nonpositive_fps():
    # fps <= 0 would map every sample onto frame 0 — a silent flat curve; refuse it
    with pytest.raises(ValueError):
        carve.camera_curve([1.0, 2.0], fps=0.0, times=[0.0])


def test_local_extrema_are_interior_only():
    curve = [0.0, 2.0, 0.0, 5.0, 1.0]
    assert carve._local_maxima(curve) == [1, 3]
    assert carve._local_minima(curve) == [2]
    assert carve._local_maxima([0.0, 5.0, 5.0, 0.0]) == []   # a flat plateau is not a peak


def test_find_peaks_returns_raw_local_maxima_far_apart():
    # two clear maxima 2.0s apart (> win_min) → both kept, in time order
    curve = [0.0, 3.0, 9.0, 0.0, 4.0, 0.0]        # maxima at idx 2 (9) and idx 4 (4)
    times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    peaks = carve.find_peaks(curve, times, win_min=1.2)
    assert [times[i] for i in peaks] == [2.0, 4.0]


def test_find_peaks_rejects_a_weaker_maximum_within_win_min():
    # finer sampling (0.4s) so two maxima can sit < win_min apart; the greedy
    # strongest-first keeps the stronger and drops the neighbour, far one survives
    curve = [0.0, 9.0, 0.0, 6.0, 0.0, 0.0, 7.0, 0.0]   # maxima idx1(9), idx3(6), idx6(7)
    times = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8]
    peaks = carve.find_peaks(curve, times, win_min=1.2)
    # idx1(t=0.4,9) kept; idx3(t=1.2,6) is 0.8s away (< 1.2) → dropped; idx6(t=2.4,7) far → kept
    assert [times[i] for i in peaks] == [0.4, 2.4]


def test_find_peaks_keeps_the_stronger_of_two_close_peaks():
    # the stronger peak is the LATER one → a plain index-order greedy would keep the
    # earlier weaker one; strongest-first keeps t=1.2, and the final sort orders it
    curve = [0.0, 4.0, 0.0, 9.0, 0.0]
    times = [0.0, 0.4, 0.8, 1.2, 1.6]
    assert [times[i] for i in carve.find_peaks(curve, times, win_min=1.2)] == [1.2]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_carve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.carve'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/lib/carve.py`:

```python
"""Activity-anchored window carving (design 2026-07-25-intake-activity-units §4).

Pure: floats in, (start, dur) spans out. No ffmpeg and no `scripts.intake` import —
a lib module must not depend on a driver, so the band (WIN_MIN/WIN_MAX) is passed
in, never imported. Mirrors lib/gridfit.py. Peaks are LOCAL maxima found relative
to the clip, so no absolute activity threshold is invented (§2) — there is no real
footage to tune one on.
"""
from math import hypot


def subject_curve(centers: list[tuple[float, float] | None]) -> list[float]:
    """Per-sample 2-D displacement of the primary bbox centre, aligned to samples.
    `centers[i]` is (cx, cy) or None (no person that sample). Index 0 has no prior,
    and any sample bordering a gap, are 0.0. Returns RAW pixel displacement — peak
    detection is scale-invariant, so no width normalisation is applied here (and the
    subject/camera curves are never compared on one axis, §3)."""
    if not centers:
        return []
    out = [0.0]
    for i in range(1, len(centers)):
        c0, c1 = centers[i - 1], centers[i]
        out.append(hypot(c1[0] - c0[0], c1[1] - c0[1]) if c0 is not None and c1 is not None else 0.0)
    return out


def camera_curve(mags: list[float], fps: float, times: list[float]) -> list[float]:
    """Resample per-frame vidstab magnitudes to the sample `times` (a people-less
    span's only within-shot signal, §3). Empty mags → a flat zero curve. A
    non-positive fps is refused, not defended around: it maps a time to a frame
    index, so fps <= 0 would collapse every sample onto frame 0 — a silent flat
    curve that then yields wrong peaks (a §12-class silent corruption)."""
    if fps <= 0:
        raise ValueError(f"carve.camera_curve: fps must be positive, got {fps!r} — "
                         "a non-positive fps collapses every sample onto frame 0")
    if not mags:
        return [0.0 for _ in times]
    n = len(mags)
    return [mags[min(int(t * fps), n - 1)] for t in times]


def _local_maxima(curve: list[float]) -> list[int]:
    return [i for i in range(1, len(curve) - 1)
            if curve[i] > curve[i - 1] and curve[i] > curve[i + 1]]


def _local_minima(curve: list[float]) -> list[int]:
    return [i for i in range(1, len(curve) - 1)
            if curve[i] < curve[i - 1] and curve[i] < curve[i + 1]]


def find_peaks(curve: list[float], times: list[float], win_min: float) -> list[int]:
    """Indices of activity peaks: local maxima of the curve, kept strongest first
    with a time spacing of at least `win_min` (the band's floor doubles as the peak
    spacing — the ONLY peak regulator, §4). Returned in time order. The curve is not
    smoothed: on a ~3fps curve a fixed denoise kernel is unvalidatable and redundant
    with this spacing (design §4.1)."""
    maxima = sorted(_local_maxima(curve), key=lambda i: curve[i], reverse=True)
    kept: list[int] = []
    for i in maxima:
        if all(abs(times[i] - times[j]) >= win_min for j in kept):
            kept.append(i)
    return sorted(kept)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_carve.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/carve.py tests/lib/test_carve.py
git commit -F - <<'EOF'
feat: carve.py activity-curve + peak primitives (intake #3 slice 3a)

Pure building blocks for activity-anchored carving: subject_curve (2-D bbox
displacement), camera_curve (resampled vidstab magnitudes), local extrema, and
find_peaks (strongest-first, win_min spacing). Relative maxima on the raw curve,
no absolute activity threshold and no smoothing constant.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 1: `carve.units_for_span` — peak → unit(s), band clamp, flat fallback

**Files:**
- Modify: `scripts/lib/carve.py` (append)
- Test: `tests/lib/test_carve.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_carve.py`:

```python
def _steps(times):
    return [float(t) for t in times]


def test_span_within_band_is_one_whole_unit():
    # 3.0s span (<= WIN_MAX 4.0) → the whole span, no peak logic
    assert carve.units_for_span(0.0, 3.0, [0.0, 1.0, 2.0], [0.0, 5.0, 0.0], 1.2, 4.0) == [(0.0, 3.0)]


def test_span_below_band_is_dropped():
    assert carve.units_for_span(0.0, 0.9, [0.0], [0.0], 1.2, 4.0) == []


def test_long_take_is_not_equal_tiling():
    # 8s take, one clear peak at t=4 with lulls either side → NOT 2x4s or 3x2.67s tiles
    times = _steps(range(9))                       # 0..8 at 1s
    curve = [0, 0, 1, 3, 9, 3, 1, 0, 0]
    units = carve.units_for_span(0.0, 8.0, times, curve, 1.2, 4.0)
    assert units                                   # at least one unit
    assert all(1.2 - 1e-6 <= d <= 4.0 + 1e-6 for _, d in units)
    starts = sorted(s for s, _ in units)
    # equal-interval tiling would start every 2.0s or 2.67s from 0; activity units do not
    assert starts != [0.0, 4.0]
    assert starts != [0.0, 2.0, 4.0, 6.0]


def test_peak_gets_a_lead_in_and_a_tight_candidate():
    # peak at t=4; lull at t=1 (val 0 between rises), settle at t=6
    times = _steps(range(9))
    curve = [3, 0, 2, 5, 9, 5, 0, 2, 3]
    units = carve.units_for_span(0.0, 8.0, times, curve, 1.2, 4.0)
    # a tight ~WIN_MIN window contains the peak; a wider lead-in window also contains it
    assert any(abs(d - 1.2) < 1e-6 and s <= 4.0 <= s + d for s, d in units)   # tight
    assert any(d > 1.2 and s <= 4.0 <= s + d for s, d in units)               # lead-in


def test_flat_span_is_one_max_mean_window_not_a_tiling():
    # monotone-ish, no interior local max → one WIN_MAX window at the busiest position
    times = _steps(range(11))                      # 0..10 at 1s
    curve = [0, 0, 0, 0, 0, 5, 5, 5, 5, 0, 0]      # busiest around t=5..8
    units = carve.units_for_span(0.0, 10.0, times, curve, 1.2, 4.0)
    assert len(units) == 1
    s, d = units[0]
    assert abs(d - 4.0) < 1e-6                      # exactly WIN_MAX
    assert 4.0 <= s <= 6.0                          # centred on the busy stretch


def test_lead_in_longer_than_the_band_is_clamped_with_the_peak_inside():
    # lull far before the peak (t=1) and peak at t=7 → raw lead-in 6s > WIN_MAX
    times = _steps(range(9))
    curve = [3, 0, 1, 2, 3, 4, 5, 9, 3]            # rises to a peak at t=7, lull at t=1
    units = carve.units_for_span(0.0, 8.0, times, curve, 1.2, 4.0)
    lead = max(units, key=lambda u: u[1])          # the widest unit
    s, d = lead
    assert d <= 4.0 + 1e-6 and s <= 7.0 <= s + d   # band-clamped, peak still inside


def test_units_for_span_refuses_misaligned_or_bad_band():
    import pytest
    with pytest.raises(ValueError):                 # times/curve length mismatch
        carve.units_for_span(0.0, 8.0, [0.0, 1.0], [0.0], 1.2, 4.0)
    with pytest.raises(ValueError):                 # win_min > win_max
        carve.units_for_span(0.0, 8.0, [0.0], [0.0], 5.0, 4.0)


def test_units_for_span_dedups_and_sorts_deterministically():
    # two peaks (t=1.2, t=2.4); the first peak's tight == its lead-in (minima flank it
    # at ±win_min/2), so the exact-dup drop must collapse them; output is (start,dur)-sorted.
    # Drop the dedup → a duplicate (0.6,1.2) survives; drop the sort → order changes.
    times = [0.0, 0.6, 1.2, 1.8, 2.4, 3.0, 3.6, 4.2, 4.8]
    curve = [5.0, 0.0, 9.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0]
    assert carve.units_for_span(0.0, 4.8, times, curve, 1.2, 4.0) == [(0.6, 1.2), (1.8, 1.2), (1.8, 3.0)]


def test_flat_span_tie_breaks_to_the_earliest_window():
    # two equal-mean WIN_MAX windows in a flat span → the earliest wins (strict >);
    # a >= tie-break would pick the later one
    times = _steps(range(11))
    curve = [9.0, 9.0, 9.0, 9.0, 0.0, 0.0, 9.0, 9.0, 9.0, 9.0, 0.0]
    assert carve.units_for_span(0.0, 10.0, times, curve, 1.2, 4.0) == [(0.0, 4.0)]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_carve.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.carve' has no attribute 'units_for_span'`.

- [ ] **Step 3: Write the implementation**

Append to `scripts/lib/carve.py`:

```python
def _clamp_to_band(s: float, e: float, a: float, b: float, p: float,
                   win_min: float, win_max: float) -> tuple[float, float]:
    """Force [s, e] into [win_min, win_max] and inside [a, b], keeping the peak `p`
    in it. Holds the start (the lead-in) and trims/extends the tail first."""
    s = max(a, min(s, p))                 # start no later than the peak, no earlier than a
    e = min(b, max(e, p))                 # end no earlier than the peak, no later than b
    if e - s > win_max:                   # too long: keep the lead-in, trim the tail
        e = s + win_max
        if e < p:                         # the lead-in alone exceeds the band → anchor on the peak
            e = min(b, p)
            s = e - win_max
    if e - s < win_min:                   # too short: extend, preferring to keep the peak inside
        s = max(a, min(s, e - win_min))
        e = min(b, s + win_min)
        if e - s < win_min:               # both span edges crowd it
            s = max(a, e - win_min)
    return (round(s, 3), round(e - s, 3))


def _tight_unit(pk: int, a: float, b: float, times: list[float], win_min: float) -> tuple[float, float]:
    p = times[pk]
    return _clamp_to_band(p - win_min / 2, p + win_min / 2, a, b, p, win_min, win_min)


def _lead_in_unit(pk: int, minima: list[int], a: float, b: float, times: list[float],
                  win_min: float, win_max: float) -> tuple[float, float]:
    p = times[pk]
    befores = [times[m] for m in minima if times[m] < p]
    afters = [times[m] for m in minima if times[m] > p]
    lull = befores[-1] if befores else a           # the approach starts at the last lull before the peak
    settle = afters[0] if afters else b            # ends at the first lull after it (§4)
    return _clamp_to_band(lull, settle, a, b, p, win_min, win_max)


def _flat_unit(a: float, b: float, times: list[float], curve: list[float],
               win_max: float) -> tuple[float, float]:
    """A flat span (no interior peak) yields ONE window of WIN_MAX at the position of
    maximum mean activity — never a tiling (§4.3)."""
    best_s, best_mean = a, -1.0
    for t in times:
        if t + win_max > b + 1e-9:
            break
        vals = [curve[j] for j, tt in enumerate(times) if t <= tt < t + win_max]
        m = sum(vals) / len(vals) if vals else 0.0
        if m > best_mean:
            best_mean, best_s = m, t
    return (round(best_s, 3), round(win_max, 3))


def units_for_span(a: float, b: float, times: list[float], curve: list[float],
                   win_min: float, win_max: float) -> list[tuple[float, float]]:
    """Carve one span [a, b] into activity units (§4). A short span (< win_min) is
    dropped; a span within the band is one whole unit; a longer span is carved on
    its activity peaks (two candidates each) or, if flat, one max-mean window.

    This is the module's public entry (intake.carve_windows calls it), so it
    validates here and the helpers below trust it — the same fail-loud boundary
    gridfit.py draws."""
    if len(times) != len(curve):
        raise ValueError(f"carve.units_for_span: times and curve must align, got "
                         f"{len(times)} times vs {len(curve)} curve samples")
    if not (0 < win_min <= win_max):
        raise ValueError(f"carve.units_for_span: need 0 < win_min <= win_max, got "
                         f"win_min={win_min!r}, win_max={win_max!r}")
    L = b - a
    if L < win_min:
        return []
    if L <= win_max:
        return [(round(a, 3), round(L, 3))]
    peaks = find_peaks(curve, times, win_min)
    if not peaks:
        return [_flat_unit(a, b, times, curve, win_max)]
    minima = _local_minima(curve)
    seen: set = set()
    out: list[tuple[float, float]] = []
    for pk in peaks:
        # candidates are pre-rounded to 3dp by _clamp_to_band, so this exact-equality
        # dedup is reliable — the round() there is load-bearing, not cosmetic (§4.5).
        for unit in (_lead_in_unit(pk, minima, a, b, times, win_min, win_max),
                     _tight_unit(pk, a, b, times, win_min)):
            if unit not in seen:                   # exact-dup drop: a sharp peak makes tight == lead-in
                seen.add(unit)
                out.append(unit)
    out.sort(key=lambda u: (u[0], u[1]))            # deterministic (start, dur) order
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_carve.py -q`
Expected: PASS (all Task 0 + Task 1 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/carve.py tests/lib/test_carve.py
git commit -F - <<'EOF'
feat: carve.units_for_span — peak+lead-in units, flat max-mean fallback

A span within the band is one whole unit; a longer span emits two candidates per
activity peak (tight + lead-in), band-clamped with the peak kept inside; a flat
span yields one WIN_MAX max-mean window, never an equal-interval tiling.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 2: `FootageWindow.track_ids`

**Files:**
- Modify: `scripts/lib/footage.py` (`FootageWindow`: field, `__post_init__`, `to_dict`)
- Test: `tests/lib/test_footage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_footage.py`:

```python
def test_footage_window_track_ids_default_and_roundtrip():
    from scripts.lib.footage import FootageWindow
    w = FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=2,
                      motion=0.3, shake=0.0, track_ids=[3, 7])
    assert w.track_ids == [3, 7]
    assert w.to_dict()["track_ids"] == [3, 7]
    assert FootageWindow(**w.to_dict()).track_ids == [3, 7]
    # default is an empty list (a window with nobody in it)
    assert FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=0,
                         motion=0.0, shake=0.0).track_ids == []


def test_footage_window_track_ids_rejects_bad_values():
    import pytest
    from scripts.lib.footage import FootageWindow
    for bad in [[-1], [True], ["1"], 5]:
        with pytest.raises(ValueError):
            FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=1,
                          motion=0.0, shake=0.0, track_ids=bad)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -q -k track_ids`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'track_ids'`.

- [ ] **Step 3: Write the implementation**

In `scripts/lib/footage.py`, add the field to `FootageWindow` (after `best`):

```python
    best: bool = False
    track_ids: list[int] = field(default_factory=list)
```

Add validation at the end of `FootageWindow.__post_init__` (after the `best` check):

```python
        if not isinstance(self.track_ids, list) or any(
                isinstance(t, bool) or not isinstance(t, int) or t < 0 for t in self.track_ids):
            raise ValueError(f"FootageWindow.track_ids must be a list of ints >= 0 "
                             f"(the track ids present in the window), got {self.track_ids!r}")
```

Add to `FootageWindow.to_dict`'s returned dict (after `"best"`):

```python
                "best": self.best, "track_ids": list(self.track_ids)}
```

(`field` is already imported in footage.py; `FootageClip.from_dict` reconstructs windows via `FootageWindow(**w)`, so the round-trip needs no other change — an old dict without `track_ids` picks up the default.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/footage.py tests/lib/test_footage.py
git commit -F - <<'EOF'
feat: FootageWindow.track_ids — who is in the window (intake #3 slice 3a)

An annotation for a hero thread; names resolve downstream via cast.json. Default
empty, validated as ints >= 0, round-trips through to_dict / from_dict.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 3: timeline carries track ids; `_motion` is 2-D; `_build_window` unions ids

**Files:**
- Modify: `scripts/intake.py` (`_people_timeline`, `_motion`, `_build_window`, add `hypot` import)
- Test: `tests/lib/test_intake.py` (`test_people_timeline_samples_and_counts`, add `_motion`/`_build_window` tests)

- [ ] **Step 1: Update the timeline test and add the new ones**

In `tests/lib/test_intake.py`, replace `test_people_timeline_samples_and_counts` with:

```python
def test_people_timeline_samples_counts_and_track_ids(monkeypatch):
    # 6 frames @ fps 6, SAMPLE_FPS 3 → step 2 → sample frames 0,2,4. subject slides right.
    frames = [_FakeRes([_FakeBox([300 + i * 40, 500, 200, 300], 1)]) for i in range(6)]
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(frames)))
    tl, crops = intake._people_timeline("x.mp4", fps=6.0, res=(1920, 1080))
    assert [n for _, n, _, _ in tl] == [1, 1, 1]        # one person each sampled frame
    assert tl[0][0] == 0.0 and abs(tl[1][0] - 2/6) < 1e-6
    assert tl[0][2][2] == 200                           # primary bbox width threaded through
    assert tl[0][3] == [1]                              # track id present at the sample


def test_motion_is_2d():
    # a purely vertical slide registers now (x-only would have read 0)
    res = (1000, 1000)
    samples = [(0.0, 1, (500, 100, 10, 10), [1]), (1.0, 1, (500, 300, 10, 10), [1])]
    assert intake._motion(samples, res) > 0.0


def test_build_window_unions_track_ids():
    # disjoint ids per sample → a last-sample-only bug would drop id 2; the union keeps both
    tl = [(0.0, 1, (500, 500, 10, 10), [2]), (1.0, 1, (500, 500, 10, 10), [5])]
    w = intake._build_window((0.0, 2.0), tl, shake=0.0, res=(1000, 1000))
    assert w.track_ids == [2, 5]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q -k "track_ids or motion_is_2d"`
Expected: FAIL — the timeline rows are 3-tuples (`not enough values to unpack`) / `_build_window` returns no `track_ids`.

- [ ] **Step 3: Write the implementation**

In `scripts/intake.py`, add to the imports block (line 9 area):

```python
from math import hypot
```

In `_people_timeline`, update the docstring's timeline shape line — `timeline: [(t, people, primary_bbox)] sampled at ~SAMPLE_FPS (primary = largest bbox).` → `timeline: [(t, people, primary_bbox, track_ids)] sampled at ~SAMPLE_FPS (primary = largest bbox).` — so it stops describing the old 3-tuple. Then replace the sampling append (the `timeline.append((i / fps, len(bbs), primary))` line and the two lines above it) with:

```python
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        tids = sorted({int(b.id[0]) for b in boxes if getattr(b, "id", None) is not None})
        timeline.append((i / fps, len(bbs), primary, tids))
```

Replace `_motion` with the 2-D, 4-tuple version:

```python
def _motion(samples: list, res: tuple[int, int]) -> float:
    centers = [bb for (t, n, bb, tids) in samples if bb is not None]
    if len(centers) < 2:
        return 0.0
    w = res[0] or 1
    disps = [hypot(centers[i][0] - centers[i - 1][0], centers[i][1] - centers[i - 1][1]) / w
             for i in range(1, len(centers))]
    return float(min(1.0, (sum(disps) / len(disps)) * MOTION_GAIN))
```

Replace `_build_window` with the 4-tuple, track-id-unioning version:

```python
def _build_window(span: tuple[float, float], timeline: list, shake: float, res: tuple[int, int]) -> footage.FootageWindow:
    a, d = span
    b = a + d
    samples = [row for row in timeline if a <= row[0] < b]
    people = max((row[1] for row in samples), default=0)
    present = (sum(1 for row in samples if row[1] > 0) / len(samples)) if samples else 0.0
    boxes = [row[2] for row in samples if row[2] is not None]
    primary = max(boxes, key=lambda bb: bb[2] * bb[3]) if boxes else None
    motion = _motion(samples, res)
    shot = shot_type(primary, res)
    score = score_window(present, motion, shake, d)
    track_ids = sorted({tid for row in samples for tid in row[3]})
    return footage.FootageWindow(start=round(a, 3), dur=round(d, 3), shot_type=shot,
                                 people=people, motion=round(motion, 3), shake=round(shake, 4),
                                 description=_describe(people, shot, motion), score=round(score, 3),
                                 track_ids=track_ids)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q -k "track_ids or motion_is_2d or people_timeline"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -F - <<'EOF'
feat: timeline carries track ids; _motion is 2-D; window unions ids

_people_timeline records the track ids per sample (was dropped); _build_window
unions them into FootageWindow.track_ids; _motion measures 2-D bbox displacement
(a turn/cross-step has a vertical component). The score blend and weights are
unchanged — only the motion measurement gains a dimension.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 4: rewire carving to `carve.py`, reorder vidstab detect, bump `CACHE_VERSION`

**Files:**
- Modify: `scripts/intake.py` (`carve_windows` rewrite; delete `_split_span` and `shake_by_window`; `_process_clip` reorder; import `carve`)
- Modify: `scripts/lib/intake_cache.py` (`CACHE_VERSION` 1 → 2)
- Test: `tests/lib/test_intake.py` (rewrite carve tests; retarget `_process_clip`/`intake` monkeypatches from `shake_by_window` to `vidstab.detect`; drop the `shake_by_window` handoff test)
- Test: `tests/lib/test_intake_cache.py` (version-bump invalidation)

- [ ] **Step 1: Rewrite the carve tests and retarget the seams**

In `tests/lib/test_intake.py`:

Replace the four carve tests (`test_carve_long_take_splits_by_length`, `test_carve_splits_on_presence_transition`, `test_carve_short_clip_yields_one_window`, `test_carve_all_short_spans_yields_no_windows`) with the new-signature versions (`carve_windows(scene_cuts, timeline, mags, fps, dur)`; the `_line` helper now builds 4-tuples):

```python
def _line(n_from_to):   # helper: timeline [(t, people, bbox, track_ids)] at 1s steps
    return [(float(t), n, (500, 500, 200, 300) if n else None, [1] if n else [])
            for t, n in n_from_to]


def test_carve_long_take_is_activity_units_not_equal_tiling():
    # a 12s take with two isolated, ASYMMETRIC activity peaks (t=3, t=8): a big jump
    # then a slow settle, so the subject curve has strict maxima (not an equal-value
    # plateau). Equal-interval tiling would emit N windows of ONE duration; activity
    # units vary — restoring _split_span would collapse the duration set to a single value.
    pos = [500, 500, 500, 800, 810, 815, 815, 815, 1115, 1125, 1130, 1130, 1130]
    tl = [(float(t), 1, (pos[t], 500, 200, 300), [1]) for t in range(13)]
    spans = intake.carve_windows([], tl, [], 1.0, 12.0)
    assert spans                                                     # carved something
    assert all(intake.WIN_MIN <= d <= intake.WIN_MAX + 1e-6 for _, d in spans)
    assert len({round(d, 3) for _, d in spans}) > 1                 # NOT one uniform tile size


def test_carve_splits_on_presence_transition():
    # empty 0–3, person 3–6 → boundary at 3
    tl = _line([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)])
    spans = intake.carve_windows([], tl, [], 1.0, 6.0)
    assert any(abs(s - 3.0) < 1e-6 for s, _ in spans)


def test_carve_short_clip_yields_one_window():
    spans = intake.carve_windows([], _line([(0, 1)]), [], 1.0, 0.8)   # < WIN_MIN
    assert spans == [(0.0, 0.8)]


def test_carve_all_short_spans_yields_no_windows():
    spans = intake.carve_windows([1.0, 2.0, 3.0, 4.0, 5.0], _line([(t, 1) for t in range(7)]),
                                 [], 1.0, 6.0)
    assert spans == []


def test_carve_peopleless_span_uses_camera_motion(monkeypatch):
    # no people the whole 8s take → the curve comes from vidstab mags; a mid-clip
    # camera surge (frame 4 at fps 1 → t=4) should anchor a unit that contains t=4
    tl = [(float(t), 0, None, []) for t in range(9)]
    mags = [0, 0, 0, 1, 9, 1, 0, 0, 0]
    spans = intake.carve_windows([], tl, mags, 1.0, 8.0)
    # strict right bound: a subject-only regression → all-zero curve → flat (0.0, 4.0),
    # which touches 4.0 only at its edge; the camera-driven tight window straddles it.
    assert any(s <= 4.0 < s + d for s, d in spans)
```

Replace the `shake_by_window` handoff test (`test_shake_by_window_hands_detect_the_clip_and_the_clip_s_own_length`) with a `_process_clip`-level detect-once test:

```python
def test_process_clip_detects_shake_once_before_carving(monkeypatch):
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1000, h=1080, fps=1.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    tl = [(float(i), 1, (500, 500, 300, 300), [1]) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS: (tl, {}))
    seen = []

    def fake_detect(src, trf, dur):
        seen.append((src, dur))
        return [0.0] * 8

    monkeypatch.setattr(intake.vidstab, "detect", fake_detect)
    monkeypatch.setattr(intake, "_phash_at",
                        lambda clip, t: imagehash.average_hash(_Img.new("L", (8, 8), 0)))
    intake._process_clip("/foot/a.mp4", intake.SAMPLE_FPS)
    assert seen == [("/foot/a.mp4", 8.0)]     # detect once, with the clip's OWN length
```

In `test_intake_builds_footage_and_writes` and `test_process_clip_returns_clip_phashes_and_cast`, the `_people_timeline` stub `tl` must be 4-tuples and the `shake_by_window` monkeypatch must become a `vidstab.detect` + `vidstab.require` stub. Replace, in BOTH tests, the `tl = [...]` line and the `shake_by_window` monkeypatch with:

```python
    tl = [(float(i), 1, (500, 500, 300, 300), [1]) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS: (tl, {}))  # keep the crops arg each test already uses
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    monkeypatch.setattr(intake.vidstab, "detect", lambda src, trf, dur: [0.0] * 8)
```

(In `test_process_clip_returns_clip_phashes_and_cast` keep its `{1: (0.9, red, ...)}` crops dict rather than `{}`.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q -k "carve or process_clip or builds_footage"`
Expected: FAIL — `carve_windows()` takes 3 positional args but 5 were given / `_split_span` still tiles.

- [ ] **Step 3: Write the implementation**

In `scripts/intake.py`, add `carve` to the lib import (line 20):

```python
from scripts.lib import assembly, carve, footage, intake_cache, vidstab
```

Replace `carve_windows` and delete `_split_span` (the whole `_split_span` function) with:

```python
def carve_windows(scene_cuts: list[float],
                  timeline: list[tuple[float, int, tuple[float, float, float, float] | None, list[int]]],
                  mags: list[float], fps: float, dur: float) -> list[tuple[float, float]]:
    """scene_cuts ∪ presence-transitions bound the raw spans; each span is carved on
    its activity curve by carve.units_for_span (design 2026-07-25-intake-activity-units
    §4). A span with people uses 2-D bbox displacement; a people-less span uses the
    resampled vidstab magnitudes. A single sub-WIN_MIN shot stays one whole window;
    a clip shredded into many too-short spans yields NO windows (empty is valid)."""
    bounds = {0.0, float(dur)}
    for t in scene_cuts:
        if 0.0 < t < dur:
            bounds.add(float(t))
    prev = None
    for row in timeline:
        t, n = row[0], row[1]
        present = n > 0
        if prev is not None and present != prev and 0.0 < t < dur:
            bounds.add(float(t))
        prev = present
    edges = sorted(bounds)
    raw = list(zip(edges, edges[1:]))
    spans: list[tuple[float, float]] = []
    for a, b in raw:
        samples = [row for row in timeline if a <= row[0] < b]
        times = [row[0] for row in samples] or [a]
        if any(row[1] > 0 for row in samples):
            centers = [(row[2][0], row[2][1]) if row[2] is not None else None for row in samples]
            curve = carve.subject_curve(centers)
        else:
            curve = carve.camera_curve(mags, fps, times)
        spans.extend(carve.units_for_span(a, b, times, curve, WIN_MIN, WIN_MAX))
    if not spans and len(raw) == 1:          # a single short shot (dur < WIN_MIN) — keep the whole clip
        a, b = raw[0]
        spans = [(round(a, 3), round(b - a, 3))]
    return spans
```

Delete the entire `shake_by_window` function (its `require()` + `detect` move into `_process_clip`; the windowing stays in `_windowed_shake`, which is unchanged).

In `_process_clip`, replace the carve/shake lines:

```python
    timeline, crops = _people_timeline(path, info.fps, res, sample_fps)
    spans = carve_windows(cuts, timeline, dur)
    shakes = shake_by_window(path, spans, info.fps, res, dur)
    windows = [_build_window(sp, timeline, sh, res) for sp, sh in zip(spans, shakes)]
```

with:

```python
    timeline, crops = _people_timeline(path, info.fps, res, sample_fps)
    vidstab.require()
    with tempfile.TemporaryDirectory() as d:
        mags = vidstab.detect(path, str(Path(d) / "t.trf"), dur)
    spans = carve_windows(cuts, timeline, mags, info.fps, dur)
    shakes = _windowed_shake(mags, spans, info.fps, res[0])
    windows = [_build_window(sp, timeline, sh, res) for sp, sh in zip(spans, shakes)]
```

In `scripts/lib/intake_cache.py`, bump the version and update its comment:

```python
# invalidates every cached clip in one move ... The #3 window-band slice bumps
# this (v1 → v2: activity-unit carving + FootageWindow.track_ids). An
# all-or-nothing version beats a per-field logic hash nobody can audit.
CACHE_VERSION = 2
```

- [ ] **Step 4: Add the cache-invalidation test**

Append to `tests/lib/test_intake_cache.py`:

```python
def test_a_version_1_entry_is_a_miss(tmp_path):
    # a cache written under the old CACHE_VERSION must not be trusted by v2 code
    from scripts.lib import intake_cache
    src = tmp_path / "a.mp4"; src.write_bytes(b"x")
    out = tmp_path / "out"; out.mkdir()
    d = out / ".intake_cache" / "a.mp4"; d.mkdir(parents=True)
    key = intake_cache.clip_key(str(src), 3.0, _M)
    stale = {**key, "version": 1}
    (d / "clip.json").write_text(json.dumps(
        {"key": stale, "clip": {"source": "a.mp4", "dur": 1.0, "res": [2, 2], "fps": 1.0,
                                "shaky": False, "scene_cuts": [], "windows": []},
         "phashes": [], "cast": []}))
    assert intake_cache.load(str(out), str(src), 3.0, _M) is None
```

(`_M` and `json` are already defined/imported in this test module.)

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_intake_cache.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/intake.py scripts/lib/intake_cache.py tests/lib/test_intake.py tests/lib/test_intake_cache.py
git commit -F - <<'EOF'
feat: carve on activity units, detect shake once before carving

carve_windows builds a per-span activity curve (2-D bbox displacement, or
resampled vidstab magnitudes for a people-less span) and delegates to
carve.units_for_span — _split_span's equal-interval tiling is deleted. The
vidstab detect pass moves into _process_clip so a people-less span has its curve
at carve time; the magnitudes feed both the curve and _windowed_shake, so
shake_by_window collapses away. CACHE_VERSION 1 -> 2 invalidates the old carve.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 5: de-cite the tiling in docstrings; re-pin the real-ffmpeg golden; full suite

**Files:**
- Modify: `scripts/lib/footage.py` (`room_after` docstring), `scripts/edit_plan.py` (`window_to_episode` docstring)
- Modify: `tests/integration/test_intake.py` (re-pin windows to the activity-unit output)
- Test (run only): whole suite

- [ ] **Step 1: Update the two docstrings (no behaviour change)**

In `scripts/lib/footage.py`, `room_after`, replace the sentence citing tiling:

Old:
```
    or repeated, the shot simply runs longer. intake carves a continuous take into
    WIN_TARGET-sized windows by LENGTH, not by content (its own docstring: "MVI_3739
    = 1 ride → 3 windows"), so a window boundary inside a shot marks nothing. A
    scene cut does mark something, and running across one would splice two different
    shots into one episode — so the room stops there."""
```
New:
```
    or repeated, the shot simply runs longer. intake carves a take into activity
    units that may overlap and need not tile it (2026-07-25 activity-units §2), so a
    window boundary is not a partition line — the room after a start is what the shot
    itself offers. A scene cut does mark something, and running across one would
    splice two different shots into one episode — so the room stops there."""
```

In `scripts/edit_plan.py`, `window_to_episode`, replace the `start_offset` rationale paragraph:

Old:
```
    `start_offset` moves the in-point later inside the SAME shot. It exists because the
    window grid is a SCORING artifact, not an editorial one: intake carves a continuous
    take into WIN_TARGET-sized windows BY LENGTH (see FootageClip.room_after), so without an
    offset the only reachable in-points are multiples of that arbitrary size — 2.41s on
    one drone clip here, which was the difference between cutting on a cross-step and
    cutting through it. It shifts the in-point ONLY; `dur` still comes from the window
```
New:
```
    `start_offset` moves the in-point later inside the SAME shot — the fine-tune atop
    intake's activity units (2026-07-25 activity-units): a unit is anchored on an
    activity peak with its lead-in, but the exact frame to cut on can still sit a beat
    inside it, and an offset reaches it without re-carving. It shifts the in-point
    ONLY; `dur` still comes from the window
```

- [ ] **Step 2: Run the affected unit suites (docstrings are inert, so these stay green)**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py tests/lib/test_edit_plan.py -q`
Expected: PASS (no behaviour changed).

- [ ] **Step 3: Re-pin the integration golden**

Run the intake integration test to see the new activity-unit output, then update its window assertions to match:

Run: `.venv/bin/python -m pytest tests/integration/test_intake.py -q`
Expected: initially FAIL on the window count / window fields that the old equal-interval carve produced.

Read `tests/integration/test_intake.py`. For each assertion that pins the number of windows or a specific window's `start`/`dur`/`score`/`motion`, replace the literal with the value the current run produces (the run is deterministic — real ffprobe/PySceneDetect/vidstab/phash on the fixture clip). Keep every *structural* assertion (band membership `WIN_MIN <= dur <= WIN_MAX`, `best` set on a survivor, `track_ids` is a list, FOOTAGE.json/.md written, the byte-identical-on-resume proof) — only the numeric pins move. Do not weaken an assertion to make it pass; if a window now carries `track_ids`, add an assertion that pins them.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (the suite ran ~1764 tests green before this slice; expect that count plus the new tests, minus the deleted `shake_by_window` test). No golden other than intake's should move; if one does, STOP and investigate — nothing outside intake should change behaviour.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/footage.py scripts/edit_plan.py tests/integration/test_intake.py
git commit -F - <<'EOF'
test: re-pin the intake golden to activity units; de-cite tiling in docstrings

room_after and window_to_episode no longer justify themselves by intake's
equal-interval tiling — windows are activity units now. The intake integration
golden re-pins to the new deterministic window set; structural assertions
(band membership, best, track_ids) are unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 6: docs sync + final whole-slice review

**Files:**
- Modify: `CLAUDE.md` (registry rows), `docs/build-status.md`, `docs/pipeline-map.md`, `skills/footage-intake/SKILL.md`
- Modify: `docs/plans/2026-07-25-intake-activity-units.md` (tick the boxes)

- [ ] **Step 1: Add the registry rows to `CLAUDE.md`**

In the Quick Reference table, add two rows (design + plan) after the intake parallel+checkpoint rows:

```markdown
| Intake activity-units design | [2026-07-25-intake-activity-units-design.md](docs/specs/2026-07-25-intake-activity-units-design.md) | Feedback #3 slice 3a: `_split_span` equal-interval tiling → activity-anchored units in a pure `lib/carve.py` (peak + lead-in, tight/lead-in candidates, flat-span max-mean; peaks are LOCAL maxima, no absolute threshold — no footage to tune). Curve = 2-D bbox displacement where people are present, resampled vidstab camera motion otherwise; vidstab detect reorders ahead of carve. `FootageWindow.track_ids` annotates who is in a unit (mixed hero/moment). `CACHE_VERSION` 1→2. **3b (`edit_plan` span [i..j] merge) deferred.** |
| Intake activity-units plan | [2026-07-25-intake-activity-units.md](docs/plans/2026-07-25-intake-activity-units.md) | Tasks 0–6: `carve.py` primitives + `units_for_span`, `FootageWindow.track_ids`, timeline track ids + 2-D `_motion` + `_build_window`, `carve_windows` rewrite + detect reorder + `CACHE_VERSION` bump, docstring de-cite + golden re-pin, docs sync. |
```

- [ ] **Step 2: Update `docs/build-status.md`**

Add a "Done" entry dated 2026-07-25 for slice 3a (activity-unit carving; `lib/carve.py`; `track_ids`; detect reorder; `CACHE_VERSION` 2; 3b deferred), mirroring the format of the existing entries. If a "current date" line exists, leave it at 2026-07-25.

- [ ] **Step 3: Update `docs/pipeline-map.md`**

In the stage 5.2 (footage-intake) row/notes, record that carving is now activity-anchored units (peak + lead-in) with `track_ids`, and that #3 slice 3a landed 2026-07-25 (3b deferred). Bump any "last updated" date to 2026-07-25.

- [ ] **Step 4: Update `skills/footage-intake/SKILL.md`**

Where it describes windows/carving, replace the equal-interval description with: windows are activity units (an activity peak plus its lead-in, may overlap) and carry `track_ids` (who is in the unit; names resolve via cast.json). Note a flat span yields one representative window, not a tiling. Keep the `--jobs`/`--fresh`/`intake_report.json` text.

- [ ] **Step 5: Run the docs-affecting checks and the whole suite once more**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. (Some repos test skill/doc references; if a doc-reference test exists it must stay green.)

- [ ] **Step 6: Tick every `- [ ]` in this plan to `- [x]`, then commit**

```bash
git add CLAUDE.md docs/build-status.md docs/pipeline-map.md skills/footage-intake/SKILL.md docs/plans/2026-07-25-intake-activity-units.md
git commit -F - <<'EOF'
docs: register intake activity-units slice 3a; sync build-status, pipeline-map, SKILL

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

- [ ] **Step 7: Final whole-slice review**

Dispatch a fresh whole-slice code review (base = this branch's fork point from `main`, head = HEAD) per `superpowers:requesting-code-review`. Focus the reviewer on: the carve introduces NO new tuned constant (peaks and lull/settle are raw relative extrema; the only choice is which extremum bounds a lead-in); the band clamp keeps the peak inside in every branch; `carve.py` imports nothing from `scripts.intake`; the detect reorder feeds the SAME magnitudes to the curve and `_windowed_shake` (no per-window shake number changed for a given window range); `CACHE_VERSION` bumped. Address Critical/Important findings as separate follow-up commits (never `--amend`).

---

## Self-Review

**1. Spec coverage.** §2 model (peak + lead-in) → Task 1 `units_for_span`. §3 curve (2-D subject / camera) → Task 0 `subject_curve`/`camera_curve` + Task 4 `carve_windows` source selection. §4 algorithm (greedy peaks + close-maxima rejection, tight+lead-in, flat max-mean, exact-dup drop) → Tasks 0–1. §5 hero annotation (timeline track ids, `track_ids`, downstream name resolution) → Tasks 2–3. §6 detect reorder → Task 4. §7 cull unchanged / cost bounded → Task 4 (cull untouched; 2 candidates/peak + `win_min` spacing). §8 schema + cache → Tasks 2, 4. §9 honest half: `score_window` blend untouched but `_motion` 2-D → Task 3; `start_offset` stays, docstrings de-cited → Task 5; flat-span thinness → Task 1 `_flat_unit`. §10 testing (synthetic curves + golden re-pin) → Tasks 0/1 + Task 5. §11 file map → all tasks. §12 landmines (shake number invariant, tiling deletion visible via the not-equal-tiling guard, `CACHE_VERSION` mandatory) → Task 3 (`test_build_window`), Task 1/4 (guard), Task 4 (bump + invalidation test). No gaps.

**2. Placeholder scan.** No TBD/TODO; every code step shows complete code; the golden re-pin (Task 5 Step 3) names the exact procedure (run → replace numeric pins, keep structural assertions) rather than pre-inventing fixture-dependent numbers, which is correct — those values are only knowable from the deterministic run.

**3. Type consistency.** `carve.units_for_span(a, b, times, curve, win_min, win_max)` is called with `(a, b, times, curve, WIN_MIN, WIN_MAX)` in Task 4. `carve.subject_curve(centers)`, `carve.camera_curve(mags, fps, times)`, `carve.find_peaks(curve, times, win_min)` match their definitions. Timeline rows are 4-tuples `(t, n, bb, tids)` consistently across `_people_timeline`, `carve_windows`, `_build_window`, `_motion`, and every test `_line`/`tl`. `FootageWindow(..., track_ids=...)` matches the field added in Task 2. `carve_windows` signature `(scene_cuts, timeline, mags, fps, dur)` matches its call in `_process_clip` and every rewritten test. `_windowed_shake(mags, windows, fps, w)` (existing) is called with `(mags, spans, info.fps, res[0])`.
