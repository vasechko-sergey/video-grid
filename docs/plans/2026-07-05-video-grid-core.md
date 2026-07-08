# video-grid Core (Composition/Reframe Engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the flagship vertical slice of video-grid — take one raw video fragment plus a rules manifest and produce a composed, numerically-checked 9:16 (or any-canvas) episode clip, with the tracker authoring the crop path and the storyboard verifying it.

> **Hardening round (2026-07-07, post-completion fresh-eyes audit):** commits `27e3571` (proc.run stderr surfacing), `51aed46` (composition validation, boundary-luma black check, jitter guard), `2ac39a2` (drop id=None detections, fps/dims probe, speed+border features), `e59cdea` (knot cap, even dims for all canvases, §6.4 Y headroom, loud stabilize/fps guards), `0c8c283` (break center-tracks, hero-marks helper). Suite: **68 passed**. Code blocks below are synced to the hardened versions; per-task "Expected: N passed" counts reflect the original TDD sequence and are historical.

**Architecture:** Pure-logic core (geometry, path smoothing, color, checks) is unit-tested with TDD and holds no ffmpeg/ML dependency. Thin integration wrappers (`extract`, `track`, `reframe`, `storyboard`) shell out to ffmpeg / Ultralytics and are covered by integration tests on a synthetic clip fixture. `process-episode` (the subagent) and all upstream/downstream skills are separate follow-on plans; this plan delivers the runnable engine they orchestrate.

**Tech Stack:** Python **3.13** in a skill-local venv (`PYTHON` env overrides); ffmpeg/ffprobe (system — must include vidstab filters); Ultralytics YOLOv11-seg + ByteTrack; numpy, scipy (Savitzky-Golay smoothing), Pillow (contact sheet), pytest. **One `requirements.txt` for the whole pipeline** — tests mock the heavy parts, the conveyor needs everything. Installed into `.venv` by `setup.sh` — never the shared environment.

**CLI convention:** scripts run as modules — `.venv/bin/python -m scripts.reframe …` (plain `python scripts/reframe.py` breaks `scripts.lib` imports); every script takes explicit paths, never assumes cwd.

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
├── fixtures/            # golden real clip + frozen route (Task 9.5)
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

- [x] **Step 1: Write `requirements.txt`**

```text
numpy>=1.26
scipy>=1.11
Pillow>=10.0
pytest>=8.0
librosa>=0.10
ultralytics>=8.3
scenedetect>=0.6
imagehash>=4.3
yt-dlp
requests>=2.31
```

One file, the full pipeline set (user decision): tests mock the detector and lazy-import the heavy deps, but the conveyor needs them all installed. No `<2.0` numpy pin — python 3.13 wheels are numpy 2.x. madmom/essentia/demucs are deliberately absent: essentia is out of v1, madmom/demucs are documented optional upgrades (design §5.5).

**Migration note (repo reality):** commit `618be74` split deps into `requirements.txt` + `requirements-ml.txt` — merge back into one `requirements.txt` and `git rm requirements-ml.txt`. The existing `.venv` was created with python 3.10 — delete and recreate with 3.13.

- [x] **Step 2: Write `setup.sh` (idempotent venv bootstrap)**

```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SKILL_DIR/.venv"
PYTHON="${PYTHON:-python3.13}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"   # corporate mirrors time out off-VPN

command -v "$PYTHON" >/dev/null || { echo "ERROR: $PYTHON not found -> brew install python@3.13 (or set PYTHON=...)"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not found -> brew install ffmpeg"; exit 1; }
ffmpeg -hide_banner -filters 2>/dev/null | grep -q vidstab || echo "WARNING: ffmpeg lacks vidstab filters (unused by core; needed for stabilization in process-episode) -> brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libvidstab"

if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# YOLO weights cached into models/ on first track.py run (ultralytics auto-download by NAME)
mkdir -p "$SKILL_DIR/models"
echo "venv ready: $VENV ($("$VENV/bin/python" -V))"
```

- [x] **Step 3: Make it executable and write `pytest.ini`**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
markers =
    integration: requires ffmpeg and/or model weights (slow)
```

`pythonpath = .` is load-bearing: there is no `tests/__init__.py`, so without it every `from scripts.lib import …` fails with `ModuleNotFoundError` (landmine, design §12).

- [x] **Step 4: Write `scripts/lib/__init__.py` (empty) and `tests/integration/__init__.py` (empty)**

- [x] **Step 5: Write `tests/conftest.py` — synthetic clip fixture**

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

- [x] **Step 6: Run the harness to confirm collection works**

Run: `.venv/bin/python -m pytest -q` (after `bash setup.sh`)
Expected: `no tests ran` — pytest exits **5** when zero tests are collected; that IS the pass condition here (exit 0 arrives once Task 1 adds tests).

- [x] **Step 7: Commit**

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

- [x] **Step 1: Write the failing tests**

`tests/lib/test_geometry.py`:
```python
import math
from scripts.lib import geometry as g

def test_crop_size_9x16_from_1080p():
    # 9:16 crop out of a 1920x1080 source: full height, width = int(1080*9/16)
    # = 607 (the session value). round() would give 608 — wrong on purpose here.
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

def test_crop_y_no_freedom_is_zero():
    assert g.crop_y(subject_y=500, crop_h=1080, src_h=1080) == 0

def test_crop_y_headroom_045():
    # crop_h=608 out of 1080: subject centre at 0.45*608=273.6 from crop top
    assert g.crop_y(subject_y=500, crop_h=608, src_h=1080) == round(500 - 0.45 * 608)

def test_crop_y_clamped():
    assert g.crop_y(subject_y=20, crop_h=608, src_h=1080) == 0
    assert g.crop_y(subject_y=1070, crop_h=608, src_h=1080) == 1080 - 608
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.geometry'`

- [x] **Step 3: Write `scripts/lib/geometry.py`**

```python
"""Pure crop geometry for the follow algorithm (spec §6.2, §6.4, §6.5)."""

PHI = 1.618033988749895


def crop_size(canvas_w, canvas_h, src_w, src_h):
    """Largest crop of canvas aspect that fits inside the source (fill mode)."""
    if canvas_w / canvas_h <= src_w / src_h:
        h = src_h
        w = int(src_h * canvas_w / canvas_h)   # floor: 1080*9/16 -> 607 (session value)
    else:
        w = src_w
        h = int(src_w * canvas_h / canvas_w)
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


def crop_y(subject_y, crop_h, src_h):
    """Static per-episode Y (spec §6.4): no head data in v1, so put the
    subject centre at 0.45*crop_h (slightly above centre = headroom canon).
    No Y freedom (crop_h == src_h) → 0."""
    if crop_h >= src_h:
        return 0
    return clamp(round(subject_y - 0.45 * crop_h), 0, src_h - crop_h)
```

Odd crop widths (607) are fine: the crop is always scaled to the even canvas size before encode, so yuv420p never sees an odd dimension.

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -q`
Expected: PASS (10 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing tests**

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

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_motion.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write `scripts/lib/motion.py`**

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
    # ambiguous zone (large dx AND large growth, e.g. diagonal approach):
    # fall through to static on purpose — centered crop is the safe framing
    return ("static", None)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_motion.py -q`
Expected: PASS (4 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing tests**

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

def test_empty_input_returns_empty():
    assert p.smooth([], max_step=10, window=7) == []

def test_even_window_at_input_length_does_not_crash():
    raw = [float(i) for i in range(6)]
    out = p.smooth(raw, max_step=10, window=6)
    assert len(out) == 6
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_pathsmooth.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write `scripts/lib/pathsmooth.py`**

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
    if not raw:
        return []
    limited = _rate_limit(list(raw), max_step)
    if window is None or window <= 1:
        return limited
    win = window if window % 2 == 1 else window + 1
    if len(limited) < win or win <= polyorder:
        return limited
    return list(savgol_filter(np.asarray(limited), win, polyorder))
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_pathsmooth.py -q`
Expected: PASS (6 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing tests**

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

def test_gain_rejects_nonpositive_measured():
    import pytest
    with pytest.raises(ValueError, match="not positive"):
        c.gain(measured=0, target=105)
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write `scripts/lib/color.py`**

```python
"""Soft normalize-to-middle color (spec §10). lutrgb is banned; use mixer."""

TARGET = (105, 122, 137)   # R, G, B middle tone
STRENGTH = 0.55
LO, HI = 0.7, 1.5


def gain(measured, target, strength=STRENGTH, lo=LO, hi=HI):
    if measured <= 0:
        raise ValueError(
            f"channel mean {measured} is not positive — all-black frames? "
            "check the extracted segment (blackdetect) before color normalization")
    g = 1 + strength * (target / measured - 1)
    return max(lo, min(hi, g))


def gains_for_means(measured, target=TARGET):
    return tuple(gain(m, t) for m, t in zip(measured, target))


def mixer_arg(rr, gg, bb):
    return f"colorchannelmixer=rr={rr:.3f}:gg={gg:.3f}:bb={bb:.3f}"
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -q`
Expected: PASS (7 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing tests**

`tests/lib/test_checks.py`:
```python
import pytest

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

def test_continuity_flags_teleport():
    # an ID switch reads as an x-teleport in the followed route (spec §6.1a)
    route = [dict(x=100.0 + i * 10) for i in range(10)]
    route[5]["x"] = 900.0
    assert ck.continuity(route, src_w=1920)["pass"] is False

def test_continuity_pass_smooth():
    route = [dict(x=100.0 + i * 10) for i in range(30)]
    assert ck.continuity(route, src_w=1920)["pass"] is True

def test_on_line_rejects_length_mismatch():
    route = [dict(x=400)] * 10
    path = [200] * 9
    with pytest.raises(ValueError, match="length mismatch"):
        ck.on_line(route, path, crop_w=600, target_frac=1/3)

def test_jitter_rejects_invalid_direction():
    with pytest.raises(ValueError, match="direction"):
        ck.jitter([100, 110], direction=None, max_reversal=10)
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write `scripts/lib/checks.py`**

```python
"""Pure numeric checks over route + crop path (spec §9)."""


def on_line(route, path, crop_w, target_frac, tol=0.05):
    if len(route) != len(path):
        raise ValueError(
            f"route/path length mismatch: {len(route)} vs {len(path)} — "
            "route and crop path must be parallel arrays from the same reframe run")
    ok = 0
    for pt, cx in zip(route, path):
        frac = (pt["x"] - cx) / crop_w
        if abs(frac - target_frac) <= tol:
            ok += 1
    ratio = ok / max(1, len(route))
    return {"pass": ratio >= 0.9, "ratio": ratio}


def centered(route, path, crop_w, tol=0.05):
    return on_line(route, path, crop_w, target_frac=0.5, tol=tol)


def continuity(route, src_w, max_step_frac=0.04):
    """No x-teleports in the followed route (spec §6.1a): a tracker ID switch
    shows up as a per-frame |dx| far above any physical subject speed."""
    worst = 0.0
    for a, b in zip(route, route[1:]):
        worst = max(worst, abs(b["x"] - a["x"]))
    cap = max_step_frac * src_w
    return {"pass": worst <= cap, "worst_dx": worst, "cap": cap}


def jitter(path, direction, max_reversal):
    if direction not in ("left", "right"):
        raise ValueError(f"jitter: direction must be 'left' or 'right', got {direction!r}")
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

`max_reversal` is the caller's choice; `check_episode` passes `max(2.0, 0.005 * crop_w)` — the 2px floor absorbs int-rounding flicker after savgol (design §9).

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q`
Expected: PASS (8 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing integration test**

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

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_extract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.extract'`

- [x] **Step 3: Write `scripts/extract.py`**

Correct seek: `-ss` AFTER `-i` (output seek) + re-encode → frame-accurate, no black frames (the landmine was arg order, not 4K).

Pure output-seek decodes from stream start — fine for typical sources. For windows deep inside long (>60s) sources, the documented upgrade is a hybrid: coarse input-seek to `max(0, start-2)` **plus** the accurate output-seek for the remainder — frame accuracy is preserved by the re-encode. v1 ships the simple form.

```python
"""Cut an EDL window into a standalone fragment (spec §5.8, §12)."""
import argparse
from scripts.lib import proc


def extract(src, start, dur, out, crf=18):
    # output-seek (-ss after -i) + re-encode → frame-accurate, no black frames.
    # Audio is PRESERVED (spec §5.8): segments are the ambient bed for audio-mix;
    # sources without an audio stream simply produce video-only segments.
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ss", f"{start}", "-t", f"{dur}",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out,
    ]
    proc.run(cmd)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    a = ap.parse_args()
    extract(a.src, a.start, a.dur, a.out)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_extract.py -q`
Expected: PASS (1 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing test (monkeypatched detector)**

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

def test_route_seed_pin(monkeypatch, tmp_path):
    # two persistent tracks; the seed bbox must pin the RIGHT one as hero
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 120, 300], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    route = track.build_route(src="ignored.mp4", fps=30, out=str(out),
                              seed_bbox=(1500, 500, 120, 300))
    assert all(pt["x"] == 1500 for pt in route)

def test_action_intent_prefers_mover_over_bystander(monkeypatch, tmp_path):
    # bystander in ALL 20 frames (static); mover in 12 frames, crosses frame.
    # most-frames would pick the bystander — scoring must pick the mover.
    frames = []
    for i in range(20):
        dets = [_FakeBox([960, 700, 150, 340], 7)]              # bystander
        if 4 <= i < 16:
            dets.append(_FakeBox([200 + (i - 4) * 120, 500, 140, 320], 9))
        frames.append(dets)
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    route = track.build_route(src="ignored.mp4", fps=30,
                              out=str(tmp_path / "route.json"))
    xs = [pt["x"] for pt in route]
    assert xs[0] == 200 and xs[-1] == 200 + 11 * 120

def test_meta_flags_ambiguity(monkeypatch, tmp_path):
    # two indistinguishable static tracks → margin rule fires (spec §6.1a)
    frames = [[_FakeBox([500, 500, 140, 320], 1),
               _FakeBox([1400, 500, 140, 320], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    track.build_route(src="ignored.mp4", fps=30, out=str(out))
    meta = json.loads((tmp_path / "route.meta.json").read_text())
    assert meta["ambiguous"] is True

def test_unconfirmed_detections_never_become_hero(monkeypatch, tmp_path):
    # id=None detections (two DIFFERENT people) must not merge into a fake
    # track that outscores the real confirmed hero
    class _NoneBox:
        def __init__(self, xywh):
            self.xywh = [xywh]; self.id = None; self.cls = [0]
    frames = []
    for i in range(20):
        dets = [_FakeBox([600 + i * 20, 500, 140, 320], 3)]      # real hero
        dets.append(_NoneBox([200, 500, 100, 300] if i % 2 else [1700, 500, 100, 300]))
        frames.append(dets)
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    route = track.build_route(src="ignored.mp4", fps=30, out=str(out))
    meta = json.loads((tmp_path / "route.meta.json").read_text())
    assert meta["hero"] == 3
    assert "-1" not in meta["features"]
    assert [pt["x"] for pt in route] == [600 + i * 20 for i in range(20)]

def test_features_include_speed_and_border(monkeypatch, tmp_path):
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    track.build_route(src="ignored.mp4", fps=30, out=str(tmp_path / "route.json"))
    feats = json.loads((tmp_path / "route.meta.json").read_text())["features"]["1"]
    assert abs(feats["speed"] - 50.0) < 1e-6      # 50 px/frame
    assert feats["border"] is None                # dims unknown in mocked run

def test_fps_probe_when_not_given(monkeypatch, tmp_path, sample_clip):
    # fps=None → probed from the real file (sample fixture is 30fps 1920x1080)
    frames = [[_FakeBox([300, 500, 140, 320], 1)] for _ in range(5)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    route = track.build_route(src=str(sample_clip), out=str(tmp_path / "route.json"))
    assert abs(route[1]["t"] - 1 / 30) < 1e-6
    feats = json.loads((tmp_path / "route.meta.json").read_text())["features"]["1"]
    assert feats["border"] is not None            # dims known from probe
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.track'`

- [x] **Step 3: Write `scripts/track.py`**

`_iter_detections` isolates the Ultralytics call so tests can patch it; `build_route` picks the largest persistent person track and records its centre + bbox per frame.

```python
"""Track the primary subject → route.json (spec §6.1)."""
import argparse, json
from pathlib import Path

from scripts.lib import proc

# Ultralytics resolves bare model NAMES (auto-download on first use); an absolute
# path would NOT auto-download (landmine, design §12). setup.sh redirects the
# weight cache into models/.
MODEL = "yolo11n-seg.pt"


def _probe_meta(src):
    """fps + dims from the source — never trust a caller-supplied default (4K/59.94 footage is the norm)."""
    import json as _j
    r = proc.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,avg_frame_rate",
                  "-of", "json", src], text=True)
    s = _j.loads(r.stdout)["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    den = float(den) or 1.0
    fps = float(num) / den
    if fps <= 0:
        raise ValueError(f"{src}: probed fps is {fps} — corrupt/streamed source? re-encode it first")
    return fps, int(s["width"]), int(s["height"])


def _iter_detections(src, model_path=MODEL):
    """Yield (frame_index, [boxes]) using Ultralytics YOLO+ByteTrack.

    Isolated for testability; boxes expose .xywh, .id, .cls like ultralytics.
    """
    from ultralytics import YOLO
    model = YOLO(model_path)
    # imgsz=960: detect on downscaled frames (~10x faster on 4K); ultralytics
    # rescales box coords back to source resolution itself.
    for i, res in enumerate(model.track(src, stream=True, persist=True,
                                        classes=[0], tracker="bytetrack.yaml",
                                        imgsz=960, verbose=False)):
        yield i, (res.boxes if res.boxes is not None else [])


def _seed_track(per_frame, seed, first_n=5):
    """Track id with max IoU vs the seed bbox (centre-format) over first frames.

    The manifest's hero-pin (spec §5.10): resolves "which person" explicitly.
    """
    sx, sy, sw, sh = seed
    sl, st = sx - sw / 2, sy - sh / 2
    best, best_iou = None, 0.0
    for _, dets in per_frame[:first_n]:
        for tid, x, y, w, h in dets:
            l, t = x - w / 2, y - h / 2
            ix = max(0.0, min(sl + sw, l + w) - max(sl, l))
            iy = max(0.0, min(st + sh, t + h) - max(st, t))
            inter = ix * iy
            union = sw * sh + w * h - inter
            if union > 0 and inter / union > best_iou:
                best, best_iou = tid, inter / union
    return best


def _track_features(per_frame, src_w=None, src_h=None):
    """Per-track: frame count, first→last displacement, mean bbox area,
    mean speed (px/frame), border share (spec §6.1a candidate discriminators).
    """
    feats = {}
    for _, dets in per_frame:
        for tid, x, y, w, h in dets:
            f = feats.setdefault(tid, {"n": 0, "x0": x, "x1": x, "area": 0.0,
                                        "_prev_x": None, "_speed_sum": 0.0,
                                        "_speed_n": 0, "_border_n": 0})
            f["n"] += 1
            f["x1"] = x
            f["area"] += w * h
            if f["_prev_x"] is not None:
                f["_speed_sum"] += abs(x - f["_prev_x"])
                f["_speed_n"] += 1
            f["_prev_x"] = x
            if src_w is not None and src_h is not None:
                l, t = x - w / 2, y - h / 2
                r, b = x + w / 2, y + h / 2
                margin_x, margin_y = 0.02 * src_w, 0.02 * src_h
                if (l <= margin_x or r >= src_w - margin_x
                        or t <= margin_y or b >= src_h - margin_y):
                    f["_border_n"] += 1
    for f in feats.values():
        f["disp"] = abs(f["x1"] - f["x0"])
        f["area"] /= max(1, f["n"])
        f["speed"] = f["_speed_sum"] / f["_speed_n"] if f["_speed_n"] else 0.0
        f["border"] = (f["_border_n"] / f["n"]) if (src_w is not None
                                                      and src_h is not None) else None
        for k in ("_prev_x", "_speed_sum", "_speed_n", "_border_n"):
            del f[k]
    return feats


def _pick_hero(feats, intent):
    """Intent-conditioned scoring (spec §6.1a) — NOT most-frames: the subject
    of an action shot crosses the frame in seconds while a bystander stands in
    frame the whole clip, so raw frame count is biased the wrong way.

    intent: "action" (motion dominates) | "static" (size + duration dominate).
    Returns (hero_id, ambiguous) — ambiguous when top-2 scores within 20%.
    """
    if not feats:
        return None, False
    mx = {k: (max(f[k] for f in feats.values()) or 1.0)
          for k in ("disp", "n", "area")}
    wd, wn, wa = (2.0, 0.5, 0.3) if intent == "action" else (0.0, 1.0, 1.0)

    def score(f):
        return (wd * f["disp"] / mx["disp"] + wn * f["n"] / mx["n"]
                + wa * f["area"] / mx["area"])

    ranked = sorted(feats.items(), key=lambda kv: score(kv[1]), reverse=True)
    ambiguous = (len(ranked) > 1
                 and score(ranked[1][1]) >= 0.8 * score(ranked[0][1]))
    return ranked[0][0], ambiguous


def build_route(src, fps=None, out=None, model_path=MODEL, seed_bbox=None,
                intent="action"):
    # hero priority: explicit seed pin (spec §5.10) > intent-conditioned scoring
    src_w = src_h = None
    if fps is None:
        # never trust a caller-supplied default (4K/59.94 footage is the norm) —
        # a wrong fps silently desyncs route t, the crop expression's time axis
        fps, src_w, src_h = _probe_meta(src)

    per_frame = []
    for idx, boxes in _iter_detections(src, model_path=model_path):
        dets = []
        for b in boxes:
            if b.id is None:
                # unconfirmed ByteTrack detection (normal in first frames /
                # after occlusion) — do NOT fabricate a shared tid=-1 track,
                # it would merge unrelated people into one fake "hero"
                continue
            x, y, w, h = [float(v) for v in b.xywh[0]]
            tid = int(b.id[0])
            dets.append((tid, x, y, w, h))
        per_frame.append((idx, dets))

    feats = _track_features(per_frame, src_w=src_w, src_h=src_h)
    hero, ambiguous = None, False
    if seed_bbox is not None:
        hero = _seed_track(per_frame, seed_bbox)
    if hero is None:
        hero, ambiguous = _pick_hero(feats, intent)
    # sidecar meta: the orchestrator reads `ambiguous` to fire the §4.1
    # stop-and-report (margin rule) with both candidates' crops
    meta = {"hero": hero, "ambiguous": ambiguous, "intent": intent,
            "features": {str(k): {kk: f[kk] for kk in
                                   ("n", "disp", "area", "speed", "border")}
                         for k, f in feats.items()}}
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta))

    route = []
    for idx, dets in per_frame:
        # hero only — NO largest-in-frame fallback: it would splice strangers'
        # coordinates into the route (false teleports for the continuity check);
        # a frame gap is fine, smoothing bridges it
        pick = next((d for d in dets if d[0] == hero), None)
        if pick:
            _, x, y, w, h = pick
            route.append(dict(t=idx / fps, x=x, y=y, w=w, h=h))
    Path(out).write_text(json.dumps(route))
    return route


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=None,
                    help="override probed fps (default: probe the source — "
                         "never trust a caller-supplied default)")
    ap.add_argument("--model", default=MODEL,
                    help="yolo11n-seg.pt (default) / yolo11s-seg.pt / "
                         "yolo11m-seg.pt for small/far subjects")
    ap.add_argument("--seed", default=None,
                    help="hero pin: first-frame centre bbox 'x,y,w,h' in source px")
    ap.add_argument("--intent", default="action", choices=["action", "static"],
                    help="hero scoring mode (spec §6.1a)")
    a = ap.parse_args()
    seed = tuple(float(v) for v in a.seed.split(",")) if a.seed else None
    build_route(a.src, a.fps, a.out, model_path=a.model, seed_bbox=seed,
                intent=a.intent)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -q`
Expected: PASS (4 passed)

- [x] **Step 5: Commit**

```bash
git add scripts/track.py tests/integration/test_track.py
git commit -m "feat: subject tracking -> route.json (intent scoring, seed pin, ambiguity meta)"
```

---

## Task 8: `reframe.py` — route + rules → composed clip + path.json

Spec §5.10, §6. Ties geometry + motion + pathsmooth + color into an ffmpeg crop. Integration.

**Files:**
- Create: `scripts/reframe.py`
- Create: `tests/integration/test_reframe.py`

- [x] **Step 1: Write the failing test**

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

def test_xexpr_uses_route_times_across_gap():
    # 10 frames, then a 10-frame tracking gap, then 10 more frames (30fps).
    # The expression's last knot must sit at the route's REAL last t (~0.966s),
    # not at index-derived (len(path)-1)/fps (~0.633s) — the desync bug.
    times = [i / 30 for i in range(10)] + [(i + 20) / 30 for i in range(10)]
    path = list(range(0, 100, 10)) + list(range(300, 400, 10))
    knots = reframe._simplify(path, times)
    assert abs(knots[-1][0] - times[-1]) < 1e-9
    assert abs(knots[0][0] - times[0]) < 1e-9

def test_reframe_rejects_empty_route(sample_clip, tmp_path):
    rp = tmp_path / "route.json"; rp.write_text("[]")
    with pytest.raises(ValueError, match="empty"):
        reframe.reframe(src=str(sample_clip), route_path=str(rp),
                        out=str(tmp_path / "ep.mp4"), composition="lead",
                        grid="thirds", canvas=(9, 16),
                        color_means=(105, 122, 137), stabilize=False,
                        path_out=str(tmp_path / "path.json"))

@pytest.mark.integration
def test_reframe_with_route_gap_still_renders(sample_clip, tmp_path):
    # gappy route (subject lost frames 30-59) must still produce a valid clip
    route = ([dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
              for i in range(30)]
             + [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
                for i in range(60, 90)])
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep.mp4"
    reframe.reframe(src=str(sample_clip), route_path=str(rpath), out=str(out),
                    composition="lead", grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(tmp_path / "path.json"))
    assert _dims(out) == (1080, 1920)

def test_simplify_caps_knots_on_long_noisy_path():
    # ~83s at 60fps with residual tracker jitter: must stay under the knot cap
    import math
    times = [i / 60 for i in range(5000)]
    path = [int(200 + i * 0.15 + 2.5 * math.sin(i * 1.7)) for i in range(5000)]
    knots = reframe._simplify(path, times)
    assert len(knots) <= 80
    expr = reframe._xexpr(path, times)
    assert len(expr) < 8000        # comfortably inside ffmpeg's parser budget

def test_stabilize_true_fails_loud(sample_clip, tmp_path):
    rp = tmp_path / "route.json"
    rp.write_text(json.dumps([dict(t=0, x=500, y=540, w=140, h=320),
                              dict(t=0.1, x=510, y=540, w=140, h=320)]))
    with pytest.raises(NotImplementedError, match="process-episode"):
        reframe.reframe(src=str(sample_clip), route_path=str(rp),
                        out=str(tmp_path / "ep.mp4"), composition="lead",
                        grid="thirds", canvas=(9, 16),
                        color_means=(105, 122, 137), stabilize=True,
                        path_out=str(tmp_path / "path.json"))

def test_compute_path_break_center_tracks():
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="break", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25)
    assert len(path) == 20
    assert all(0 <= x <= 1920 - 607 for x in path)

def test_compute_path_unknown_composition_fails_loud():
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(5)]
    with pytest.raises(ValueError, match="unknown composition"):
        reframe.compute_path(route, composition="Lead", grid="thirds",
                             canvas=(9, 16), src=(1920, 1080),
                             motion=("lateral", "right"), max_step=25)

@pytest.mark.integration
def test_reframe_non_916_canvas_even_dims(sample_clip, tmp_path):
    # canvas 5:8 from 1080p → crop 675x1080 (odd) — output must be even and encode
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(90)]
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep58.mp4"
    reframe.reframe(src=str(sample_clip), route_path=str(rpath), out=str(out),
                    composition="lead", grid="thirds", canvas=(5, 8),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(tmp_path / "path.json"))
    w, h = _dims(out)
    assert w % 2 == 0 and h % 2 == 0
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.reframe'`

- [x] **Step 3: Write `scripts/reframe.py`**

```python
"""Compose one episode: route + rules → cropped/colored clip (spec §6)."""
import argparse, json
from pathlib import Path
from scripts.lib import geometry as g
from scripts.lib import pathsmooth, color, proc
from scripts.lib.motion import classify


def compute_path(route, composition, grid, canvas, src, motion, max_step):
    crop_w, _ = g.crop_size(canvas[0], canvas[1], src[0], src[1])
    _, direction = motion if motion[0] == "lateral" else (motion[0], "right")
    if composition in ("center", "break") or motion[0] != "lateral":
        # center / head-on / static: aim crop centre at subject, no lead.
        # break (spec §6.2): tracked but relaxed — v1 center-tracks; extreme
        # framing is editorial territory, checks are editorial-only.
        raw = [g.clamp(round(pt["x"] - crop_w / 2), 0, src[0] - crop_w)
               for pt in route]
    else:
        raw = [g.crop_x(pt["x"], composition, direction, grid, crop_w, src[0])
               for pt in route]
    smoothed = pathsmooth.smooth(raw, max_step=max_step)
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame
    return [int(g.clamp(round(x), 0, src[0] - crop_w)) for x in smoothed]


def _simplify(path, times, eps=2.0, max_knots=80):
    """Douglas-Peucker over (t, x): per-frame path → a few linear knots.

    Keeps the crop expression short (nested per-frame if() hits ffmpeg's
    expression parser limits on 60fps clips) and makes motion piecewise-linear
    — smoother than piecewise-constant per-frame steps.

    The time axis comes from the route's real timestamps (`times`), not from
    the path index — routes may have tracking gaps (hero occluded; spec
    §6.1a), so index-derived time would desync the crop expression from the
    true video timeline once a gap has occurred.

    Real footage (thousands of frames, ±px post-smoothing jitter) can still
    produce far more knots than ffmpeg's expression parser can swallow — cap
    the count adaptively by doubling eps until we're under max_knots. eps
    growth always terminates (a huge eps collapses to the 2 endpoint knots).
    """
    pts = [(float(t), float(x)) for t, x in zip(times, path)]

    def run(eps):
        def dp(lo, hi):
            if hi - lo < 2:
                return []
            (t0, x0), (t1, x1) = pts[lo], pts[hi]
            worst, wi = 0.0, None
            for i in range(lo + 1, hi):
                t, x = pts[i]
                xh = x0 + (x1 - x0) * ((t - t0) / (t1 - t0))
                if abs(x - xh) > worst:
                    worst, wi = abs(x - xh), i
            if worst <= eps:
                return []
            return dp(lo, wi) + [wi] + dp(wi, hi)

        keep = sorted(set([0] + dp(0, len(pts) - 1) + [len(pts) - 1]))
        return [pts[i] for i in keep]

    knots = run(eps)
    while len(knots) > max_knots:
        eps *= 2
        knots = run(eps)
    return knots


def _xexpr(path, times):
    # piecewise-LINEAR x(t) over simplified knots: lerp inside each segment
    knots = _simplify(path, times)
    if len(knots) == 1:
        return f"{knots[0][1]:.1f}"
    expr = f"{knots[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in zip(knots[-2::-1], knots[:0:-1]):
        slope = (x1 - x0) / max(1e-9, t1 - t0)
        seg = f"({x0:.1f}+({slope:.3f})*(t-{t0:.4f}))"
        expr = f"if(lt(t,{t1:.4f}),{seg},{expr})"
    return expr


def _probe(src):
    out = proc.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate",
         "-of", "json", src], text=True)
    s = json.loads(out.stdout)["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    fps = float(num) / (float(den) or 1.0)
    if fps <= 0:
        raise ValueError(
            f"{src}: probed fps is {fps} — corrupt/streamed source? re-encode it first")
    return int(s["width"]), int(s["height"]), fps


def reframe(src, route_path, out, composition, grid, canvas,
            color_means, stabilize, path_out, max_speed=750.0):
    """max_speed: crop-x speed cap in px/sec — frame-rate independent
    (25 px/frame at the session's 30fps ≡ 750 px/s)."""
    if stabilize:
        raise NotImplementedError(
            "stabilize=true is not wired in the core engine yet — vidstab lands in the "
            "process-episode plan (and needs a vidstab-enabled ffmpeg, see setup.sh warning)")
    src_w, src_h, fps = _probe(src)   # NEVER assume dims/fps: real footage is 4K/60
    src_dims = (src_w, src_h)
    route = json.loads(Path(route_path).read_text())
    if not route:
        raise ValueError(
            f"route {route_path} is empty — tracker found no hero frames; "
            "check route.meta.json (ambiguous? wrong seed pin?) before reframing")
    motion = classify(route, src_w, src_h)
    path = compute_path(route, composition, grid, canvas, src_dims, motion,
                        max_step=max_speed / fps)
    Path(path_out).write_text(json.dumps(path))

    crop_w, crop_h = g.crop_size(canvas[0], canvas[1], src_w, src_h)
    if canvas == (9, 16):
        out_w, out_h = 1080, 1920          # session-standard vertical delivery
    else:
        out_w, out_h = crop_w - crop_w % 2, crop_h - crop_h % 2   # yuv420p needs even dims
    rr, gg, bb = color.gains_for_means(color_means)
    times = [pt["t"] for pt in route]
    xexpr = _xexpr(path, times)
    mean_y = sum(pt["y"] for pt in route) / len(route)
    cy = g.crop_y(mean_y, crop_h, src_h)
    vf = (f"crop={crop_w}:{crop_h}:x='{xexpr}':y={cy},"
          f"scale={out_w}:{out_h},{color.mixer_arg(rr, gg, bb)},"
          f"fps={fps:.6g},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    proc.run(cmd)
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

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py -q`
Expected: PASS (5 passed)

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing tests**

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
    assert report["checks"]["continuity"]["pass"] is True
    assert "black_frames" in report["checks"]
    assert report["checks"]["horizon"] == {"status": "not-implemented"}
    assert report["attempt"] == 1 and "fail_reasons" in report
    assert report["overall"] in (True, False)

@pytest.mark.integration
def test_check_episode_rejects_unknown_composition(sample_clip, tmp_path):
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [200] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    with pytest.raises(ValueError, match="unknown composition"):
        check_episode.run(clip=str(sample_clip), route_path=str(rp),
                          path_path=str(pp), composition="Lead",
                          grid="thirds", target_dur=3.0,
                          out=str(tmp_path / "report.json"))

@pytest.mark.integration
def test_check_episode_break_is_editorial_only(sample_clip, tmp_path):
    # break: crop pinned far from any line must NOT fail numerically
    route = [dict(t=i/30, x=900, y=540, w=140, h=320) for i in range(30)]
    path = [50] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    report = check_episode.run(clip=str(sample_clip), route_path=str(rp),
                               path_path=str(pp), composition="break",
                               grid="thirds", target_dur=3.0,
                               out=str(tmp_path / "report.json"))
    assert report["checks"]["framing"] == {"status": "editorial-only"}
    assert "on_line" not in report["checks"]

def test_marks_from_route_path():
    route = [dict(t=i/30, x=400 + i, y=540, w=140, h=320) for i in range(30)]
    path = [200] * 30
    marks = storyboard.marks_from_route_path(route, path, crop_w=600,
                                             src_h=1080, n=6)
    assert len(marks) == 6
    fx0, fy0 = marks[0]
    assert abs(fx0 - (400 - 200) / 600) < 1e-9
    assert abs(fy0 - 0.5) < 1e-9

def test_marks_rejects_desync():
    route = [dict(x=400, y=540)] * 10
    with pytest.raises(ValueError, match="parallel"):
        storyboard.marks_from_route_path(route, [100] * 9, crop_w=600,
                                         src_h=1080, n=4)

@pytest.mark.integration
def test_black_frames_boundary_luma_fails_on_black_lead_in(tmp_path, sample_clip):
    # prepend 0.5s of pure black to the sample clip → boundary check must fail
    import subprocess
    bad = tmp_path / "bad.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=0.5:r=30",
         "-i", str(sample_clip), "-filter_complex",
         "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(bad)],
        check=True, capture_output=True)
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [540 - 607 // 2] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    report = check_episode.run(clip=str(bad), route_path=str(rp),
                               path_path=str(pp), composition="center",
                               grid="thirds", target_dur=3.5,
                               out=str(tmp_path / "report.json"))
    assert report["checks"]["black_frames"]["pass"] is False
    assert "black_frames" in report["fail_reasons"]
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_verify.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.storyboard'`

- [x] **Step 3: Write `scripts/storyboard.py`**

```python
"""Contact sheet with grid overlays for verification/editorial (spec §6.1)."""
import argparse, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.lib.geometry import grid_lines
from scripts.lib import proc


def _duration(src):
    import json as _j
    r = proc.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", src], text=True)
    return float(_j.loads(r.stdout)["format"]["duration"])


def _sample_frames(src, n, tmp):
    rate = max(1, n) / max(0.001, _duration(src))
    proc.run(
        ["ffmpeg", "-y", "-i", src, "-vf", f"fps={rate}",
         "-frames:v", str(n), f"{tmp}/f%02d.png"])
    return sorted(Path(tmp).glob("f*.png"))


def _overlay(img, grids, mark=None):
    d = ImageDraw.Draw(img); w, h = img.size
    palette = {"thirds": (0, 255, 255), "phi": (255, 128, 0)}
    for grid in grids:
        left, right = grid_lines(grid)
        for fx in (left, right):
            d.line([(fx * w, 0), (fx * w, h)], fill=palette.get(grid), width=2)
        for fy in (left, right):   # horizontals at the grid's OWN fractions (phi != 1/3)
            d.line([(0, fy * h), (w, fy * h)], fill=palette.get(grid), width=1)
    if mark is not None:           # hero marker (spec §6.1a): (fx, fy) fractions
        mx, my, r = mark[0] * w, mark[1] * h, max(6, w // 60)
        d.ellipse([mx - r, my - r, mx + r, my + r], outline=(0, 255, 0), width=3)
    return img


def marks_from_route_path(route, path, crop_w, src_h, n):
    """(fx, fy) subject fractions in the OUTPUT frame for n sampled frames —
    the hero marker (spec §6.1a): sample route/path uniformly, fx=(x-crop_x)/crop_w."""
    if not route or len(route) != len(path):
        raise ValueError(
            f"route/path must be non-empty parallel arrays, got {len(route)} vs {len(path)}")
    idxs = [round(i * (len(route) - 1) / max(1, n - 1)) for i in range(n)]
    marks = []
    for i in idxs:
        pt, cx = route[i], path[i]
        marks.append(((pt["x"] - cx) / crop_w, pt["y"] / src_h))
    return marks


def build(src, out, n=8, grids=("thirds",), marks=None):
    """marks: optional per-sampled-frame (fx, fy) subject fractions in the
    OUTPUT frame — the caller derives them from route+path ((x-crop_x)/crop_w).
    The editorial gate then confirms "right person" at a glance."""
    with tempfile.TemporaryDirectory() as tmp:
        frames = _sample_frames(src, n, tmp)
        imgs = [_overlay(Image.open(f).convert("RGB"), grids,
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
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--grids", default="thirds,phi")
    a = ap.parse_args()
    build(a.src, a.out, a.n, tuple(a.grids.split(",")))
```

- [x] **Step 4: Write `scripts/check_episode.py`**

```python
"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse, json
from pathlib import Path
from scripts.lib import checks, geometry, proc
from scripts.lib.motion import classify


def _duration(clip):
    out = proc.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", clip], text=True)
    return float(out.stdout.strip())


def _boundary_luma(clip, n_frames=3):
    """Mean luma of the first/last n frames (spec §9: black-frame check is
    boundary-only — the seek landmine bites at cut edges; a dark mid-shot
    is legitimate footage, not a defect)."""
    import tempfile
    from PIL import Image, ImageStat
    lumas = []
    with tempfile.TemporaryDirectory() as tmp:
        proc.run(["ffmpeg", "-y", "-i", clip, "-frames:v", str(n_frames),
                  f"{tmp}/head%02d.png"])
        proc.run(["ffmpeg", "-y", "-sseof", "-0.5", "-i", clip,
                  f"{tmp}/tail%02d.png"])
        heads = sorted(Path(tmp).glob("head*.png"))
        tails = sorted(Path(tmp).glob("tail*.png"))[-n_frames:]
        for f in heads + tails:
            lumas.append(ImageStat.Stat(Image.open(f).convert("L")).mean[0])
    return lumas


def run(clip, route_path, path_path, composition, grid, target_dur, out,
        canvas=(9, 16), src_dims=(1920, 1080), attempt=1):
    """crop_w derives from canvas+src; direction from the route itself —
    no hardcoded 607 / "right" (left-moving and non-9:16 episodes exist)."""
    route = json.loads(Path(route_path).read_text())
    path = json.loads(Path(path_path).read_text())
    crop_w, _ = geometry.crop_size(canvas[0], canvas[1], src_dims[0], src_dims[1])
    _, direction = classify(route, src_dims[0], src_dims[1])
    # static/head-on routes have no direction; "right" is an arbitrary but
    # deterministic default for the lead-line pick (spec has no answer here —
    # a lead composition over non-lateral motion is already a soft mismatch)
    direction = direction or "right"
    results = {}

    if composition == "center":
        results["centered"] = checks.centered(route, path, crop_w)
    elif composition == "lead":
        left, right = geometry.grid_lines(grid)
        tf = left if direction == "right" else right
        results["on_line"] = checks.on_line(route, path, crop_w, tf)
    elif composition == "break":
        # spec §6.2: break is tracked but relaxed — postcheck editorial only,
        # no numeric fail; no "pass" key so it can't fail `overall`
        results["framing"] = {"status": "editorial-only"}
    else:
        raise ValueError(f"unknown composition: {composition!r} — expected lead/center/break")
    results["jitter"] = checks.jitter(path, direction,
                                      max_reversal=max(2.0, crop_w * 0.005))
    results["continuity"] = checks.continuity(route, src_dims[0])
    results["length"] = checks.length(_duration(clip), target_dur)
    lumas = _boundary_luma(clip)
    results["black_frames"] = {"pass": all(l > 8 for l in lumas),
                               "boundary_lumas": [round(l, 1) for l in lumas]}
    # spec'd but not yet implementable (§9): report honestly, never silent-pass
    results["horizon"] = {"status": "not-implemented"}
    results["head_power_point"] = {"status": "not-implemented"}

    overall = all(v.get("pass", True) for v in results.values())
    fail_reasons = [k for k, v in results.items() if v.get("pass") is False]
    report = {"checks": results, "overall": overall,
              "attempt": attempt, "fail_reasons": fail_reasons}
    Path(out).write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("route"); ap.add_argument("path")
    ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--target-dur", type=float, required=True)
    ap.add_argument("--canvas", default="9:16")
    ap.add_argument("--src-dims", default="1920x1080",
                    help="source WxH the route coords live in")
    ap.add_argument("--attempt", type=int, default=1)
    a = ap.parse_args()
    cw, ch = (int(v) for v in a.canvas.split(":"))
    sw, sh = (int(v) for v in a.src_dims.split("x"))
    run(a.clip, a.route, a.path, a.composition, a.grid, a.target_dur, a.out,
        canvas=(cw, ch), src_dims=(sw, sh), attempt=a.attempt)
```

- [x] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_verify.py -q`
Expected: PASS (2 passed)

- [x] **Step 6: Commit**

```bash
git add scripts/storyboard.py scripts/check_episode.py tests/integration/test_verify.py
git commit -m "feat: storyboard overlay + episode checks (on-line/centered/jitter/length/black)"
```

---

## Task 9.5: Golden fixture — real footage in the loop

Synthetic white-box tests prove plumbing, not composition. This task commits a tiny REAL clip + a frozen route so the engine is never synthetic-only (design §15). Runs right after Task 9 because it exercises `storyboard` + `check_episode`. If `on_line` fails here, tune HERE — that is the point: numbers meet reality before process-episode is built on top.

**Files:**
- Create: `tests/fixtures/golden_ride.mp4` (~2–3s, 720p, ≤2 MB, committed to the private repo)
- Create: `tests/fixtures/golden_route.json` (frozen subject route for that clip)
- Create: `tests/integration/test_golden.py`

- [x] **Step 1: Cut the fixture from session footage**

Source: the Jul 3–5 session footage (e.g. MVI_3739 — the long ride; exact path/window from the session's REEL_SOURCES.md at execution time). Pick a 2–3s window with clear lateral motion:

```bash
ffmpeg -i /path/to/MVI_3739.MP4 -ss <t0> -t 2.5 -vf scale=-2:720 \
  -c:v libx264 -crf 23 -preset slow -an tests/fixtures/golden_ride.mp4
```

Keep the file ≤2 MB (bump crf if needed).

> **As built (2026-07-07):** fixture = MVI_3739 source window **9.083–10.668s** (~1.58s, 1280x720 @ 59.94fps, 1.48 MB), not the originally suggested lena_ride2 window. Finding: this footage is a diagonal approach (rightward + toward camera) — **no 2.5s window in the whole 22s clip** satisfies the lateral test (dx ≥ 0.15*src_w AND growth<1.6); shorter windows do. Boundary motion artifacts (takeoff pop, end cutback) were trimmed to pass jitter. Hero unambiguous, no seed pin needed. All four golden checks pass with margin (on_line ratio 1.0, worst jitter 1px, worst dx 7.5px vs cap 51.2).

- [x] **Step 2: Freeze the route**

Preferred: one real tracker run — `.venv/bin/python -m scripts.track tests/fixtures/golden_ride.mp4 tests/fixtures/golden_route.json --fps <fps>` — eyeball the storyboard, commit the JSON.
Fallback (no weights/network): hand-label the subject centre every ~0.5s from a contact sheet, interpolate linearly to per-frame, same JSON shape.

- [x] **Step 3: Write `tests/integration/test_golden.py`**

```python
import json
from pathlib import Path
import pytest
from scripts import reframe, storyboard, check_episode

FIX = Path(__file__).parent.parent / "fixtures"

@pytest.mark.integration
def test_golden_ride_pipeline(tmp_path):
    src = FIX / "golden_ride.mp4"
    route = json.loads((FIX / "golden_route.json").read_text())
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    ep = tmp_path / "ep.mp4"; pp = tmp_path / "path.json"

    reframe.reframe(str(src), str(rp), str(ep), composition="lead",
                    grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(pp))
    storyboard.build(str(ep), str(tmp_path / "sheet.jpg"), n=6,
                     grids=("thirds",))

    src_w, src_h, _ = reframe._probe(str(src))
    dur = check_episode._duration(str(ep))
    report = check_episode.run(str(ep), str(rp), str(pp),
                               composition="lead", grid="thirds",
                               target_dur=dur, out=str(tmp_path / "r.json"),
                               src_dims=(src_w, src_h))
    assert report["checks"]["black_frames"]["pass"] is True
    assert report["checks"]["on_line"]["pass"] is True    # real composition holds
    assert report["checks"]["jitter"]["pass"] is True
    assert report["checks"]["continuity"]["pass"] is True  # no ID-switch teleports
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_golden.py -q`
Expected: PASS (1 passed).

- [x] **Step 5: Commit**

```bash
git add tests/fixtures/ tests/integration/test_golden.py
git commit -m "test: golden fixture — real ride clip + frozen route through the full engine"
```

---

## Task 10: Reference docs

Spec §6.3, §6.5, §10, §12. These are consumed by process-episode and the checks; write them now so the follow-on plans reference stable files.

**Files:**
- Create: `references/editing-canon.md`
- Create: `references/ffmpeg-recipes.md`
- Create: `references/landmines.md`

- [x] **Step 1: Write `references/landmines.md`** — copy the §12 registry verbatim (lutrgb→black; seek-arg order not 4K; OpenCV HSV→YOLO; wade-in stabilization→rolling ground; ImageMagick montage tile reorder; load-all-frames OOM; vidstabdetect 255 warning cosmetic).

- [x] **Step 2: Write `references/ffmpeg-recipes.md`** — the exact command snippets used by the scripts: output-seek extract, crop+scale+colorchannelmixer, vidstab two-pass (`vidstabdetect`→`vidstabtransform`, with the "not on wade-in" note), blackdetect, concat. Each with a one-line "why".

- [x] **Step 3: Write `references/editing-canon.md`** — classic canon (thirds, headroom, lead room, 180°, cut-on-action, match/J/L cuts, continuity, contrast) + the grid library table (thirds 0.333/0.667, phi 0.382/0.618, golden-canon-grid armature) from §6.5. Mark thirds as the tracking default and golden-canon-grid as the static/editorial layer.

- [x] **Step 4: Commit**

```bash
git add references/
git commit -m "docs: editing-canon, ffmpeg-recipes, landmines references"
```

---

## Task 11: End-to-end core smoke test

Prove the whole slice runs: extract → track (mocked) → reframe → storyboard → check on the synthetic fixture.

**Files:**
- Create: `tests/integration/test_e2e_core.py`

- [x] **Step 1: Write the end-to-end test**

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

- [x] **Step 2: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_e2e_core.py -q`
Expected: PASS (1 passed)

- [x] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all unit tests pass; integration tests pass (or skip cleanly if ffmpeg absent).

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_e2e_core.py
git commit -m "test: end-to-end core pipeline smoke (extract->reframe->storyboard->check)"
```

---

## Follow-on plans (not in this plan)

Each is its own spec→plan→build cycle, and each produces working software on its own:

1. **process-episode subagent** — wraps this engine in the subagent loop. **Contract note (final review 2026-07-07):** `check_episode.run` re-derives `crop_w` from caller-supplied `canvas`/`src_dims` (defaults 9:16 / 1920x1080) while `reframe` probes the real source — the orchestrator MUST pass the probed values through (or better: extend reframe to write canvas/src_dims into a path sidecar that check_episode reads back); CLI defaults (`track --fps 30`, `check_episode --src-dims 1920x1080`) are placeholders that are silently wrong on 4K/59.94 footage (manifest in, retry until postcheck passes, self-review gate); adds vidstab stabilization + layout modes (`fit-blur`, `insert`, `split`, `pan`) + `break`/`phi`/`golden-canon` handling to `reframe.py`. Implements the §4.1 protocol: ask-before-start on ambiguous manifests, stop-and-report on mid-task contradictions (incl. the §6.1a margin rule → candidates' crops), `attempt`/`fail_reasons[]` escalation; concurrency cap 3; tracking degradation ladder (YOLO → optical-flow → manual keyframes) with `degraded:` marks; descriptor side of the §6.1a continuity guard (split/re-match on suspected ID switch).
2. **Ingestion** — footage-intake (`intake.py`), reel-brief, trend-scan. Builds `cast.json` (§6.1a): one interactive naming pass, seg-mask color descriptors; wires `SPEC.cast` → episode manifests (`hero` by name).
3. **Music** — music-and-mood (`beats.py`, `music_find.py`, `music_fetch.py`), pacing. librosa-first (design §5.5): madmom/demucs optional upgrades, essentia out; pacing↔music back-edge via `start_offset` re-pick.
4. **Assembly & delivery** — edit-plan, assemble-draft, audio-mix, reel-final-check, deliver. Draft concat normalizes segments to canvas+fps; `drawtext` with explicit fontfile; version log (`REEL_v{n}` + changelog); executable landmine lint (grep for `lutrgb`, `-ss` before `-i`).
5. **Router & checks discipline** — using-montage, montage-debugging, the Verification Iron Law tables. Resumability: stages skip when artifacts exist and input hashes match; wall-time per stage in every report.
