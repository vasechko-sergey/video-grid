# video-grid Core (Composition/Reframe Engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the flagship vertical slice of video-grid — take one raw video fragment plus a rules manifest and produce a composed, numerically-checked 9:16 (or any-canvas) episode clip, with the tracker authoring the crop path and the storyboard verifying it.

**Architecture:** Pure-logic core (geometry, path smoothing, color, checks) is unit-tested with TDD and holds no ffmpeg/ML dependency. Thin integration wrappers (`extract`, `track`, `reframe`, `storyboard`) shell out to ffmpeg / Ultralytics and are covered by integration tests on a synthetic clip fixture. `process-episode` (the subagent) and all upstream/downstream skills are separate follow-on plans; this plan delivers the runnable engine they orchestrate.

**Tech Stack:** Python 3.11 in a skill-local venv; ffmpeg/ffprobe (system); Ultralytics YOLOv11-seg + ByteTrack; numpy, scipy (Savitzky-Golay smoothing), Pillow (contact sheet), pytest. All ML/heavy deps installed into `.venv` by `setup.sh` — never the shared environment.

This plan implements §5.8 (extract), §5.10 tracking/reframe internals, §6 (follow + composition), §9 (thresholds), §10 (color/stab), and the `ffmpeg-recipes`/`landmines`/`editing-canon` references from the design spec (`docs/2026-07-05-montage-skillset-design.md`).

**Repo layout produced by this plan:**
```
scripts/
├── lib/
│   ├── __init__.py
│   ├── geometry.py      # crop size, grid lines, lead/center crop-x, clamp
│   ├── motion.py        # classify route → lateral(dir)/head-on/static
│   ├── pathsmooth.py    # damped velocity-following crop-path smoothing
│   ├── color.py         # gain formula + colorchannelmixer arg
│   └── checks.py        # pure threshold checks over route + path
├── extract.py           # cut EDL window → segment (correct seek args)
├── track.py             # YOLO+ByteTrack → route.json
├── reframe.py           # route + rules → composed clip + path.json
├── storyboard.py        # sampled frames + grid overlay → contact sheet
└── check_episode.py     # run all checks → pass/fail report.json
references/
├── editing-canon.md
├── ffmpeg-recipes.md
└── landmines.md
tests/
├── conftest.py          # synthetic-clip fixture
├── lib/ (unit tests)
└── integration/ (ffmpeg/YOLO tests)
setup.sh
requirements.txt
pytest.ini
```

---

## Task 0: Environment, deps, and test harness

**Files:**
- Create: `requirements.txt`
- Create: `setup.sh`
- Create: `pytest.ini`
- Create: `scripts/lib/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: Write `requirements.txt`**

```text
ultralytics==8.3.0
numpy>=1.26,<2.0
scipy>=1.11
Pillow>=10.0
pytest>=8.0
```

(madmom/essentia/yt-dlp belong to the music plan, not this core plan.)

- [ ] **Step 2: Write `setup.sh` (idempotent venv bootstrap)**

```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SKILL_DIR/.venv"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# YOLO weights cached into models/ on first track.py run (ultralytics auto-download)
mkdir -p "$SKILL_DIR/models"
echo "venv ready: $VENV"
```

- [ ] **Step 3: Make it executable and write `pytest.ini`**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    integration: requires ffmpeg and/or model weights (slow)
```

- [ ] **Step 4: Write `scripts/lib/__init__.py` (empty) and `tests/integration/__init__.py` (empty)**

- [ ] **Step 5: Write `tests/conftest.py` — synthetic clip fixture**

A moving bright box on dark background: gives `extract`/`reframe`/`storyboard`/color checks a real clip without needing footage or person detection.

```python
import subprocess, shutil
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """3s 1920x1080 30fps clip: a bright box sliding left→right on dark bg."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    # box centre x moves from 270 to 1560 over 3s; y fixed; on a dark grey field
    src = "color=c=0x303030:s=1920x1080:d=3:r=30"
    vf = "drawbox=x='200+t*430':y=380:w=140:h=320:color=white:t=fill"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-vf", vf,
         "-t", "3", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True)
    return out
```

- [ ] **Step 6: Run the harness to confirm collection works**

Run: `.venv/bin/python -m pytest -q` (after `bash setup.sh`)
Expected: `no tests ran` (0 tests collected) with exit 0.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt setup.sh pytest.ini scripts/lib/__init__.py tests/conftest.py tests/integration/__init__.py
git commit -m "chore: venv bootstrap, deps, and pytest harness with synthetic clip fixture"
```

---

## Task 1: `geometry.py` — crop size, grid lines, crop-x target

This is the pure heart of the follow algorithm (spec §6.2, §6.4, §6.5). Fully TDD.

**Files:**
- Create: `tests/lib/__init__.py`
- Create: `tests/lib/test_geometry.py`
- Create: `scripts/lib/geometry.py`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_geometry.py`:
```python
import math
from scripts.lib import geometry as g

def test_crop_size_9x16_from_1080p():
    # 9:16 crop out of a 1920x1080 source: full height, width = round(1080*9/16)
    assert g.crop_size(9, 16, 1920, 1080) == (607, 1080)

def test_crop_size_1x1_from_1080p():
    assert g.crop_size(1, 1, 1920, 1080) == (1080, 1080)

def test_grid_lines_thirds():
    assert g.grid_lines("thirds") == (1/3, 2/3)

def test_grid_lines_phi():
    left, right = g.grid_lines("phi")
    assert math.isclose(left, 1 - 1/1.618, abs_tol=1e-3)   # ~0.382
    assert math.isclose(right, 1/1.618, abs_tol=1e-3)       # ~0.618

def test_target_frac_lead_right_thirds():
    # subject moving right → sits on LEFT third
    assert math.isclose(g.target_frac("lead", "right", "thirds"), 1/3)

def test_target_frac_lead_left_thirds():
    assert math.isclose(g.target_frac("lead", "left", "thirds"), 2/3)

def test_target_frac_center():
    assert g.target_frac("center", "right", "thirds") == 0.5

def test_crop_x_lead_right_offsets_ahead():
    # moving right, subject at x=900, crop_w=607, thirds → subject on left third
    x = g.crop_x(subject_x=900, composition="lead", direction="right",
                 grid="thirds", crop_w=607, src_w=1920)
    # crop_x = 900 - (1/3)*607 = 900 - 202.33 = 697.67 → 698
    assert x == 698

def test_crop_x_clamped_low():
    x = g.crop_x(subject_x=50, composition="lead", direction="right",
                 grid="thirds", crop_w=607, src_w=1920)
    assert x == 0

def test_crop_x_clamped_high():
    x = g.crop_x(subject_x=1900, composition="lead", direction="left",
                 grid="thirds", crop_w=607, src_w=1920)
    assert x == 1920 - 607
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.geometry'`

- [ ] **Step 3: Write `scripts/lib/geometry.py`**

```python
"""Pure crop geometry for the follow algorithm (spec §6.2, §6.4, §6.5)."""

PHI = 1.618033988749895


def crop_size(canvas_w, canvas_h, src_w, src_h):
    """Largest crop of canvas aspect that fits inside the source (fill mode)."""
    if canvas_w / canvas_h <= src_w / src_h:
        h = src_h
        w = round(src_h * canvas_w / canvas_h)
    else:
        w = src_w
        h = round(src_w * canvas_h / canvas_w)
    return (w, h)


def grid_lines(grid):
    """(left, right) power-line fractions of frame width."""
    if grid == "thirds":
        return (1 / 3, 2 / 3)
    if grid == "phi":
        return (1 - 1 / PHI, 1 / PHI)
    raise ValueError(f"unknown grid: {grid}")


def target_frac(composition, direction, grid):
    """Fraction of the OUTPUT frame width where the subject should sit."""
    if composition == "center":
        return 0.5
    left, right = grid_lines(grid)
    if composition == "lead":
        # moving right → air ahead on the right → subject on the LEFT line
        return left if direction == "right" else right
    raise ValueError(f"unknown composition: {composition}")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def crop_x(subject_x, composition, direction, grid, crop_w, src_w):
    """Left edge of the crop window so the subject lands on its target line."""
    frac = target_frac(composition, direction, grid)
    x = round(subject_x - frac * crop_w)
    return clamp(x, 0, src_w - crop_w)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/lib/__init__.py tests/lib/test_geometry.py scripts/lib/geometry.py
git commit -m "feat: crop geometry (grid lines, lead/center target, clamped crop-x)"
```

---

## Task 2: `motion.py` — classify route into lateral/head-on/static

Spec §6.2 `motion`. Pure, TDD.

**Files:**
- Create: `tests/lib/test_motion.py`
- Create: `scripts/lib/motion.py`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_motion.py`:
```python
from scripts.lib import motion as m

# a route point: dict(t, x, y, w, h) — subject bbox centre x/y and bbox w/h
def _route(points):
    return [dict(t=t, x=x, y=y, w=w, h=h) for (t, x, y, w, h) in points]

def test_lateral_right():
    r = _route([(0, 300, 500, 140, 320), (1, 800, 500, 145, 322),
                (2, 1300, 500, 148, 320)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("lateral", "right")

def test_lateral_left():
    r = _route([(0, 1300, 500, 140, 320), (1, 800, 500, 140, 320),
                (2, 300, 500, 140, 320)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("lateral", "left")

def test_head_on_growth():
    # x roughly stable, bbox area grows a lot → approaching camera
    r = _route([(0, 950, 500, 100, 200), (1, 955, 480, 180, 380),
                (2, 960, 460, 300, 640)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("head-on", None)

def test_static():
    r = _route([(0, 950, 500, 140, 320), (1, 952, 501, 141, 319),
                (2, 949, 500, 140, 320)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("static", None)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_motion.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `scripts/lib/motion.py`**

```python
"""Classify a subject route into motion type (spec §6.2)."""

LATERAL_FRAC = 0.15   # net |dx| > 15% of width → lateral
GROWTH_RATIO = 1.6    # bbox area grows ≥1.6x → head-on


def classify(route, src_w, src_h, lateral_frac=LATERAL_FRAC,
             growth_ratio=GROWTH_RATIO):
    if len(route) < 2:
        return ("static", None)
    first, last = route[0], route[-1]
    dx = last["x"] - first["x"]
    area0 = max(1, first["w"] * first["h"])
    area1 = last["w"] * last["h"]
    growth = area1 / area0

    if abs(dx) >= lateral_frac * src_w and growth < growth_ratio:
        return ("lateral", "right" if dx > 0 else "left")
    if growth >= growth_ratio and abs(dx) < lateral_frac * src_w:
        return ("head-on", None)
    return ("static", None)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_motion.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/lib/test_motion.py scripts/lib/motion.py
git commit -m "feat: motion classification (lateral/head-on/static from route)"
```

---

## Task 3: `pathsmooth.py` — damped velocity-following crop path

Spec §6.1 point 3: the smoother that reproduces the hand-tuned "hold on slow start, accelerate with the subject". Pure, TDD.

**Files:**
- Create: `tests/lib/test_pathsmooth.py`
- Create: `scripts/lib/pathsmooth.py`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_pathsmooth.py`:
```python
from scripts.lib import pathsmooth as p

def test_constant_stays_constant():
    raw = [700.0] * 30
    out = p.smooth(raw, max_step=10, window=5)
    assert all(abs(v - 700.0) < 1e-6 for v in out)

def test_step_is_rate_limited():
    # a hard jump must not move faster than max_step per frame
    raw = [0.0] * 5 + [100.0] * 25
    out = p.smooth(raw, max_step=10, window=1)  # window=1 → no savgol, pure limiter
    steps = [abs(out[i] - out[i - 1]) for i in range(1, len(out))]
    assert max(steps) <= 10 + 1e-6

def test_reaches_target_eventually():
    raw = [0.0] * 2 + [100.0] * 40
    out = p.smooth(raw, max_step=10, window=1)
    assert abs(out[-1] - 100.0) < 1.0

def test_length_preserved():
    raw = [float(i) for i in range(50)]
    assert len(p.smooth(raw, max_step=10, window=7)) == 50
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_pathsmooth.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `scripts/lib/pathsmooth.py`**

```python
"""Damped velocity-following smoothing of a raw crop-x path (spec §6.1)."""
import numpy as np
from scipy.signal import savgol_filter


def _rate_limit(raw, max_step):
    out = [float(raw[0])]
    for target in raw[1:]:
        prev = out[-1]
        delta = target - prev
        if delta > max_step:
            delta = max_step
        elif delta < -max_step:
            delta = -max_step
        out.append(prev + delta)
    return out


def smooth(raw, max_step, window=7, polyorder=2):
    """Rate-limit then (optionally) Savitzky-Golay smooth the path.

    max_step: max crop-x change per frame (px) — the damping.
    window:   savgol window (odd, >polyorder). window<=1 skips savgol.
    """
    limited = _rate_limit(list(raw), max_step)
    if window is None or window <= 1 or len(limited) < window:
        return limited
    win = window if window % 2 == 1 else window + 1
    if win <= polyorder:
        return limited
    return list(savgol_filter(np.asarray(limited), win, polyorder))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_pathsmooth.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/lib/test_pathsmooth.py scripts/lib/pathsmooth.py
git commit -m "feat: damped velocity-following crop-path smoothing"
```

---

## Task 4: `color.py` — normalize-to-middle gain + mixer arg

Spec §10. Pure, TDD.

**Files:**
- Create: `tests/lib/test_color.py`
- Create: `scripts/lib/color.py`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_color.py`:
```python
import math
from scripts.lib import color as c

def test_gain_no_change_when_on_target():
    assert math.isclose(c.gain(measured=105, target=105), 1.0, abs_tol=1e-6)

def test_gain_boosts_dark_channel():
    # measured below target → gain > 1
    val = c.gain(measured=90, target=105)  # 1 + 0.55*(105/90 - 1) = 1.0917
    assert math.isclose(val, 1.0917, abs_tol=1e-3)

def test_gain_clamped_low():
    assert c.gain(measured=1000, target=105) == 0.7

def test_gain_clamped_high():
    assert c.gain(measured=1, target=105) == 1.5

def test_mixer_arg_format():
    arg = c.mixer_arg(1.092, 1.028, 1.063)
    assert arg == "colorchannelmixer=rr=1.092:gg=1.028:bb=1.063"

def test_targets_from_means():
    rr, gg, bb = c.gains_for_means(measured=(90, 118, 130))
    # defaults target R105/G122/B137
    assert math.isclose(rr, c.gain(90, 105), abs_tol=1e-6)
    assert math.isclose(gg, c.gain(118, 122), abs_tol=1e-6)
    assert math.isclose(bb, c.gain(130, 137), abs_tol=1e-6)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `scripts/lib/color.py`**

```python
"""Soft normalize-to-middle color (spec §10). lutrgb is banned; use mixer."""

TARGET = (105, 122, 137)   # R, G, B middle tone
STRENGTH = 0.55
LO, HI = 0.7, 1.5


def gain(measured, target, strength=STRENGTH, lo=LO, hi=HI):
    g = 1 + strength * (target / measured - 1)
    return max(lo, min(hi, g))


def gains_for_means(measured, target=TARGET):
    return tuple(gain(m, t) for m, t in zip(measured, target))


def mixer_arg(rr, gg, bb):
    return f"colorchannelmixer=rr={rr:.3f}:gg={gg:.3f}:bb={bb:.3f}"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/lib/test_color.py scripts/lib/color.py
git commit -m "feat: normalize-to-middle color gain + colorchannelmixer arg"
```

---

## Task 5: `checks.py` — pure threshold checks over route + path

Spec §9 (the parts computable from route + crop-path, no video decode). On-line/centered, jitter, length. Frame-level checks (black, color) come in Task 9's integration. TDD.

**Files:**
- Create: `tests/lib/test_checks.py`
- Create: `scripts/lib/checks.py`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_checks.py`:
```python
from scripts.lib import checks as ck

def test_on_line_pass_when_subject_on_third():
    # crop_w=600, subject sits at left third (0.333) each frame
    route = [dict(x=200 + 0.333 * 600) for _ in range(30)]  # x = 400
    path = [200] * 30   # crop_x=200 → subject_frac = (400-200)/600 = 0.333
    res = ck.on_line(route, path, crop_w=600, target_frac=1/3, tol=0.05)
    assert res["pass"] is True
    assert res["ratio"] == 1.0

def test_on_line_fail_when_off():
    route = [dict(x=560) for _ in range(30)]   # frac = (560-200)/600 = 0.6
    path = [200] * 30
    res = ck.on_line(route, path, crop_w=600, target_frac=1/3, tol=0.05)
    assert res["pass"] is False

def test_jitter_flags_reversal():
    # moving right: crop_x should be non-decreasing; a big backward step fails
    path = [100, 110, 120, 90, 130]   # -30 reversal
    res = ck.jitter(path, direction="right", max_reversal=10)
    assert res["pass"] is False

def test_jitter_pass_monotonic():
    path = [100, 108, 115, 121, 130]
    res = ck.jitter(path, direction="right", max_reversal=10)
    assert res["pass"] is True

def test_length_within_tolerance():
    assert ck.length(actual=5.3, target=5.0, tol=0.5)["pass"] is True
    assert ck.length(actual=6.0, target=5.0, tol=0.5)["pass"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `scripts/lib/checks.py`**

```python
"""Pure numeric checks over route + crop path (spec §9)."""


def on_line(route, path, crop_w, target_frac, tol=0.05):
    ok = 0
    for pt, cx in zip(route, path):
        frac = (pt["x"] - cx) / crop_w
        if abs(frac - target_frac) <= tol:
            ok += 1
    ratio = ok / max(1, len(route))
    return {"pass": ratio >= 0.9, "ratio": ratio}


def centered(route, path, crop_w, tol=0.05):
    return on_line(route, path, crop_w, target_frac=0.5, tol=tol)


def jitter(path, direction, max_reversal):
    sign = 1 if direction == "right" else -1
    worst = 0.0
    for i in range(1, len(path)):
        step = (path[i] - path[i - 1]) * sign      # forward = positive
        if step < 0:
            worst = max(worst, -step)
    return {"pass": worst <= max_reversal, "worst_reversal": worst}


def length(actual, target, tol=0.5):
    return {"pass": abs(actual - target) <= tol, "delta": actual - target}
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/lib/test_checks.py scripts/lib/checks.py
git commit -m "feat: pure route/path checks (on-line, centered, jitter, length)"
```

---

## Task 6: `extract.py` — cut a window with correct seek args

Spec §5.8 + §12 landmine. Integration (needs ffmpeg + the sample fixture).

**Files:**
- Create: `scripts/extract.py`
- Create: `tests/integration/test_extract.py`

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_extract.py`:
```python
import json, subprocess
import pytest
from scripts import extract

def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])

@pytest.mark.integration
def test_extract_window_duration(sample_clip, tmp_path):
    out = tmp_path / "seg.mp4"
    extract.extract(src=str(sample_clip), start=1.0, dur=1.5, out=str(out))
    assert out.exists()
    assert abs(_duration(out) - 1.5) < 0.15   # frame-accurate re-encode
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_extract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.extract'`

- [ ] **Step 3: Write `scripts/extract.py`**

Correct seek: `-ss` AFTER `-i` (output seek) + re-encode → frame-accurate, no black frames (the landmine was arg order, not 4K).

```python
"""Cut an EDL window into a standalone fragment (spec §5.8, §12)."""
import argparse, subprocess


def extract(src, start, dur, out, crf=18):
    # output-seek (-ss after -i) + re-encode → frame-accurate, no black frames
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ss", f"{start}", "-t", f"{dur}",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-an", out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    a = ap.parse_args()
    extract(a.src, a.start, a.dur, a.out)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_extract.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/extract.py tests/integration/test_extract.py
git commit -m "feat: extract window with output-seek (frame-accurate, no black frames)"
```

---

## Task 7: `track.py` — YOLO+ByteTrack → route.json

Spec §6.1 point 1. Integration; unit-tested via a monkeypatched detector so the geometry pipeline is covered without downloading weights.

**Files:**
- Create: `scripts/track.py`
- Create: `tests/integration/test_track.py`

- [ ] **Step 1: Write the failing test (monkeypatched detector)**

`tests/integration/test_track.py`:
```python
import json
from scripts import track

class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]  # cls 0 = person

def test_route_from_frames(monkeypatch, tmp_path):
    # fake per-frame detections: subject slides right
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    route = track.build_route(src="ignored.mp4", fps=30, out=str(out))
    assert len(route) == 10
    assert route[0]["x"] == 300 and route[-1]["x"] == 300 + 9 * 50
    assert json.loads(out.read_text())[0]["x"] == 300
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.track'`

- [ ] **Step 3: Write `scripts/track.py`**

`_iter_detections` isolates the Ultralytics call so tests can patch it; `build_route` picks the largest persistent person track and records its centre + bbox per frame.

```python
"""Track the primary subject → route.json (spec §6.1)."""
import argparse, json
from pathlib import Path

MODEL = str(Path(__file__).resolve().parent.parent / "models" / "yolo11n-seg.pt")


def _iter_detections(src, model_path=MODEL):
    """Yield (frame_index, [boxes]) using Ultralytics YOLO+ByteTrack.

    Isolated for testability; boxes expose .xywh, .id, .cls like ultralytics.
    """
    from ultralytics import YOLO
    model = YOLO(model_path)
    for i, res in enumerate(model.track(src, stream=True, persist=True,
                                        classes=[0], tracker="bytetrack.yaml",
                                        verbose=False)):
        yield i, (res.boxes if res.boxes is not None else [])


def build_route(src, fps, out, model_path=MODEL):
    # pick the track id that appears in the most frames (the hero)
    per_frame = []
    counts = {}
    for idx, boxes in _iter_detections(src, model_path=model_path):
        dets = []
        for b in boxes:
            x, y, w, h = [float(v) for v in b.xywh[0]]
            tid = int(b.id[0]) if b.id is not None else -1
            dets.append((tid, x, y, w, h))
            counts[tid] = counts.get(tid, 0) + 1
        per_frame.append((idx, dets))
    hero = max(counts, key=counts.get) if counts else None

    route = []
    for idx, dets in per_frame:
        pick = next((d for d in dets if d[0] == hero), None) or (
            max(dets, key=lambda d: d[3] * d[4]) if dets else None)
        if pick:
            _, x, y, w, h = pick
            route.append(dict(t=idx / fps, x=x, y=y, w=w, h=h))
    Path(out).write_text(json.dumps(route))
    return route


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=30.0)
    a = ap.parse_args()
    build_route(a.src, a.fps, a.out)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/track.py tests/integration/test_track.py
git commit -m "feat: subject tracking (YOLO+ByteTrack) -> route.json, hero-track selection"
```

---

## Task 8: `reframe.py` — route + rules → composed clip + path.json

Spec §5.10, §6. Ties geometry + motion + pathsmooth + color into an ffmpeg crop. Integration.

**Files:**
- Create: `scripts/reframe.py`
- Create: `tests/integration/test_reframe.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_reframe.py`:
```python
import json, subprocess
import pytest
from scripts import reframe

def _dims(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return (s["width"], s["height"])

def test_compute_path_lead_right():
    # pure path computation (no ffmpeg): subject slides right → crop_x rises
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="lead", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25)
    assert len(path) == 20
    assert path[-1] >= path[0]                  # crop follows subject right
    assert all(0 <= x <= 1920 - 607 for x in path)

@pytest.mark.integration
def test_reframe_output_dims(sample_clip, tmp_path):
    # build a route matching the fixture's sliding box (x = 200 + t*430 + w/2)
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(90)]
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep.mp4"
    reframe.reframe(src=str(sample_clip), route_path=str(rpath), out=str(out),
                    composition="lead", grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(tmp_path / "path.json"))
    assert _dims(out) == (1080, 1920)
    assert (tmp_path / "path.json").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.reframe'`

- [ ] **Step 3: Write `scripts/reframe.py`**

```python
"""Compose one episode: route + rules → cropped/colored clip (spec §6)."""
import argparse, json, subprocess
from pathlib import Path
from scripts.lib import geometry as g
from scripts.lib import pathsmooth, color
from scripts.lib.motion import classify


def compute_path(route, composition, grid, canvas, src, motion, max_step):
    crop_w, _ = g.crop_size(canvas[0], canvas[1], src[0], src[1])
    _, direction = motion if motion[0] == "lateral" else (motion[0], "right")
    raw = [g.crop_x(pt["x"], composition, direction, grid, crop_w, src[0])
           for pt in route]
    if composition == "center" or motion[0] != "lateral":
        # center / head-on / static: aim crop centre at subject, no lead
        raw = [g.clamp(round(pt["x"] - crop_w / 2), 0, src[0] - crop_w)
               for pt in route]
    return [int(round(x)) for x in pathsmooth.smooth(raw, max_step=max_step)]


def _xexpr(path, fps):
    # piecewise-constant ffmpeg x(t) expression from per-frame crop_x
    # nested if(lt(t,..)) — compact enough for a short episode
    expr = str(path[-1])
    for i in range(len(path) - 1, 0, -1):
        expr = f"if(lt(t,{i/fps:.4f}),{path[i-1]},{expr})"
    return expr


def reframe(src, route_path, out, composition, grid, canvas,
            color_means, stabilize, path_out, fps=30, src_dims=(1920, 1080)):
    route = json.loads(Path(route_path).read_text())
    motion = classify(route, src_dims[0], src_dims[1])
    path = compute_path(route, composition, grid, canvas, src_dims, motion,
                        max_step=25)
    Path(path_out).write_text(json.dumps(path))

    crop_w, crop_h = g.crop_size(canvas[0], canvas[1], src_dims[0], src_dims[1])
    out_w = 1080 if canvas == (9, 16) else crop_w
    out_h = 1920 if canvas == (9, 16) else crop_h
    rr, gg, bb = color.gains_for_means(color_means)
    xexpr = _xexpr(path, fps)
    vf = (f"crop={crop_w}:{crop_h}:x='{xexpr}':y=0,"
          f"scale={out_w}:{out_h},{color.mixer_arg(rr, gg, bb)},"
          f"fps={fps},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("route"); ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--canvas", default="9:16")
    ap.add_argument("--color", default="105,122,137")
    ap.add_argument("--stabilize", action="store_true")
    ap.add_argument("--path-out", required=True)
    a = ap.parse_args()
    cw, ch = (int(v) for v in a.canvas.split(":"))
    means = tuple(float(v) for v in a.color.split(","))
    reframe(a.src, a.route, a.out, a.composition, a.grid, (cw, ch),
            means, a.stabilize, a.path_out)
```

Note: stabilization (vidstab two-pass, §10) and layout modes beyond `fill` (§7) are deliberately out of this core task — they extend `reframe.py` in the follow-on process-episode plan. The `stabilize` flag is threaded now but only `False` is exercised here.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/reframe.py tests/integration/test_reframe.py
git commit -m "feat: reframe engine (route+rules -> crop path + colored 9:16 clip)"
```

---

## Task 9: `storyboard.py` + `check_episode.py` — verification layer

Spec §6.1 point 4 + §9 (frame-level black/color checks + wire pure checks). Integration.

**Files:**
- Create: `scripts/storyboard.py`
- Create: `scripts/check_episode.py`
- Create: `tests/integration/test_verify.py`

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_verify.py`:
```python
import json
import pytest
from scripts import storyboard, check_episode

@pytest.mark.integration
def test_storyboard_creates_sheet(sample_clip, tmp_path):
    out = tmp_path / "sheet.jpg"
    storyboard.build(src=str(sample_clip), out=str(out), n=6,
                     grids=("thirds", "phi"))
    assert out.exists() and out.stat().st_size > 0

@pytest.mark.integration
def test_check_episode_reports(sample_clip, tmp_path):
    # a route+path where subject is centered → centered check should pass
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [540 - 607 // 2] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    report = check_episode.run(clip=str(sample_clip), route_path=str(rp),
                               path_path=str(pp), composition="center",
                               grid="thirds", target_dur=3.0,
                               out=str(tmp_path / "report.json"))
    assert report["checks"]["centered"]["pass"] is True
    assert "black_frames" in report["checks"]
    assert report["overall"] in (True, False)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_verify.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.storyboard'`

- [ ] **Step 3: Write `scripts/storyboard.py`**

```python
"""Contact sheet with grid overlays for verification/editorial (spec §6.1)."""
import argparse, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.lib.geometry import grid_lines


def _duration(src):
    import json as _j
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", src], capture_output=True, text=True, check=True)
    return float(_j.loads(r.stdout)["format"]["duration"])


def _sample_frames(src, n, tmp):
    rate = max(1, n) / max(0.001, _duration(src))
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-vf", f"fps={rate}",
         "-frames:v", str(n), f"{tmp}/f%02d.png"],
        check=True, capture_output=True)
    return sorted(Path(tmp).glob("f*.png"))


def _overlay(img, grids):
    d = ImageDraw.Draw(img); w, h = img.size
    palette = {"thirds": (0, 255, 255), "phi": (255, 128, 0)}
    for grid in grids:
        left, right = grid_lines(grid)
        for fx in (left, right):
            d.line([(fx * w, 0), (fx * w, h)], fill=palette.get(grid), width=2)
        d.line([(0, (1/3) * h), (w, (1/3) * h)], fill=palette.get(grid), width=1)
    return img


def build(src, out, n=8, grids=("thirds",)):
    with tempfile.TemporaryDirectory() as tmp:
        frames = _sample_frames(src, n, tmp)
        imgs = [_overlay(Image.open(f).convert("RGB"), grids) for f in frames]
        if not imgs:
            raise RuntimeError("no frames sampled")
        cols = min(len(imgs), 4)
        rows = (len(imgs) + cols - 1) // cols
        tw, th = imgs[0].size
        sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
        for i, im in enumerate(imgs):
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
        sheet.save(out, quality=90)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--grids", default="thirds,phi")
    a = ap.parse_args()
    build(a.src, a.out, a.n, tuple(a.grids.split(",")))
```

- [ ] **Step 4: Write `scripts/check_episode.py`**

```python
"""Run mechanical episode checks → report.json (spec §9)."""
import argparse, json, subprocess, re
from pathlib import Path
from scripts.lib import checks, geometry


def _duration(clip):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", clip], capture_output=True, text=True,
        check=True)
    return float(out.stdout.strip())


def _black_frames(clip):
    out = subprocess.run(
        ["ffmpeg", "-i", clip, "-vf", "blackdetect=d=0.05:pic_th=0.98",
         "-an", "-f", "null", "-"], capture_output=True, text=True)
    return len(re.findall(r"black_start", out.stderr))


def run(clip, route_path, path_path, composition, grid, target_dur, out,
        crop_w=607, direction="right"):
    route = json.loads(Path(route_path).read_text())
    path = json.loads(Path(path_path).read_text())
    results = {}

    if composition == "center":
        results["centered"] = checks.centered(route, path, crop_w)
    elif composition == "lead":
        left, right = geometry.grid_lines(grid)
        tf = left if direction == "right" else right
        results["on_line"] = checks.on_line(route, path, crop_w, tf)
    results["jitter"] = checks.jitter(path, direction, max_reversal=crop_w * 0.005)
    results["length"] = checks.length(_duration(clip), target_dur)
    results["black_frames"] = {"pass": _black_frames(clip) == 0}

    overall = all(v.get("pass", True) for v in results.values())
    report = {"checks": results, "overall": overall}
    Path(out).write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("route"); ap.add_argument("path")
    ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--target-dur", type=float, required=True)
    a = ap.parse_args()
    run(a.clip, a.route, a.path, a.composition, a.grid, a.target_dur, a.out)
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_verify.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add scripts/storyboard.py scripts/check_episode.py tests/integration/test_verify.py
git commit -m "feat: storyboard overlay + episode checks (on-line/centered/jitter/length/black)"
```

---

## Task 10: Reference docs

Spec §6.3, §6.5, §10, §12. These are consumed by process-episode and the checks; write them now so the follow-on plans reference stable files.

**Files:**
- Create: `references/editing-canon.md`
- Create: `references/ffmpeg-recipes.md`
- Create: `references/landmines.md`

- [ ] **Step 1: Write `references/landmines.md`** — copy the §12 registry verbatim (lutrgb→black; seek-arg order not 4K; OpenCV HSV→YOLO; wade-in stabilization→rolling ground; ImageMagick montage tile reorder; load-all-frames OOM; vidstabdetect 255 warning cosmetic).

- [ ] **Step 2: Write `references/ffmpeg-recipes.md`** — the exact command snippets used by the scripts: output-seek extract, crop+scale+colorchannelmixer, vidstab two-pass (`vidstabdetect`→`vidstabtransform`, with the "not on wade-in" note), blackdetect, concat. Each with a one-line "why".

- [ ] **Step 3: Write `references/editing-canon.md`** — classic canon (thirds, headroom, lead room, 180°, cut-on-action, match/J/L cuts, continuity, contrast) + the grid library table (thirds 0.333/0.667, phi 0.382/0.618, golden-canon-grid armature) from §6.5. Mark thirds as the tracking default and golden-canon-grid as the static/editorial layer.

- [ ] **Step 4: Commit**

```bash
git add references/
git commit -m "docs: editing-canon, ffmpeg-recipes, landmines references"
```

---

## Task 11: End-to-end core smoke test

Prove the whole slice runs: extract → track (mocked) → reframe → storyboard → check on the synthetic fixture.

**Files:**
- Create: `tests/integration/test_e2e_core.py`

- [ ] **Step 1: Write the end-to-end test**

`tests/integration/test_e2e_core.py`:
```python
import json
import pytest
from scripts import extract, reframe, storyboard, check_episode

@pytest.mark.integration
def test_core_pipeline(sample_clip, tmp_path):
    seg = tmp_path / "seg.mp4"
    extract.extract(str(sample_clip), start=0.2, dur=2.0, out=str(seg))

    # route tracing the fixture box centre (x = 200 + t*430 + 70)
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(60)]
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))

    ep = tmp_path / "ep.mp4"; pp = tmp_path / "path.json"
    reframe.reframe(str(seg), str(rp), str(ep), composition="lead",
                    grid="thirds", canvas=(9, 16), color_means=(105, 122, 137),
                    stabilize=False, path_out=str(pp))

    storyboard.build(str(ep), str(tmp_path / "sheet.jpg"), n=6,
                     grids=("thirds", "phi"))

    report = check_episode.run(str(ep), str(rp), str(pp), composition="lead",
                               grid="thirds", target_dur=2.0,
                               out=str(tmp_path / "report.json"))
    assert ep.exists()
    assert (tmp_path / "sheet.jpg").exists()
    assert report["checks"]["black_frames"]["pass"] is True
    assert "on_line" in report["checks"]
```

- [ ] **Step 2: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_e2e_core.py -q`
Expected: PASS (1 passed)

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all unit tests pass; integration tests pass (or skip cleanly if ffmpeg absent).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_e2e_core.py
git commit -m "test: end-to-end core pipeline smoke (extract->reframe->storyboard->check)"
```

---

## Follow-on plans (not in this plan)

Each is its own spec→plan→build cycle, and each produces working software on its own:

1. **process-episode subagent** — wraps this engine in the subagent loop (manifest in, retry until postcheck passes, self-review gate); adds vidstab stabilization + layout modes (`fit-blur`, `insert`, `split`, `pan`) + `break`/`phi`/`golden-canon` handling to `reframe.py`.
2. **Ingestion** — footage-intake (`intake.py`), reel-brief, trend-scan.
3. **Music** — music-and-mood (`beats.py`, `music_find.py`, `music_fetch.py`), pacing.
4. **Assembly & delivery** — edit-plan, assemble-draft, audio-mix, reel-final-check, deliver.
5. **Router & checks discipline** — using-montage, montage-debugging, the Verification Iron Law tables.
