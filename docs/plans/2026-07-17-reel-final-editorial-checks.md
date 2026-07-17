# Reel-final Editorial Checks (§5.13 Slice A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every shell-capable subagent brief MUST forbid installers (no brew/pip/uv/npm install, no setup.sh) — verification is read-only + `pytest`.

**Goal:** Add the three still-mechanical checks under §5.13's editorial half — `key_action` (subject not clipped by the frame edge), `pad_bars` (non-`fill` filler bars well-formed), `transitions` (adjacent-episode layout not jarring) — all **advisory**, so `overall`/`reel_orchestration`/loop-2 stay untouched.

**Architecture:** Extend the existing subject→output projection (`geometry.marks_at_times`) to bbox corners (`geometry.extent_at_times`); a new pure-decision module `lib/reel_final.py` holds the three `evaluate_*` cores; `check_reel.run` wires them inside the `geometry is not None` block it already runs for `safe_zones`, reusing the same per-episode sidecars. Three advisory thresholds join `ReelCheckSpec`; the three check names join `_ADVISORY_CHECKS`.

**Tech Stack:** Python 3.13, pytest, dataclasses (config-specs). Pure geometry — no ffmpeg, no new deps. Scripts run as modules (`pythonpath = .`).

**Spec:** `docs/specs/2026-07-17-reel-final-editorial-checks-design.md` (approved). **Branch:** `feat/reel-final-editorial` (spec already committed at `0f18c69`).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `scripts/lib/geometry.py` | pure crop/subject projection | **add** `extent_at_times` (bbox corners → output fractions) |
| `scripts/lib/reel_final.py` | the three §5.13 editorial decision cores | **create** — `evaluate_key_action` / `evaluate_pad_bars` / `evaluate_transitions` (+ `_layout_of`, `LAYOUT_MODE_PENALTY`) |
| `scripts/lib/safezones.py` | subject sampling + UI-chrome decision | **add** `subject_extents` (mirrors `subject_marks`, projects extents) |
| `scripts/lib/models.py` | wire-contracts + config-specs | **modify** `ReelCheckSpec` (+3 thresholds), `_ADVISORY_CHECKS` (+3 names) |
| `scripts/check_reel.py` | whole-reel mechanical gate driver | **modify** the `geometry` block (+3 checks), `_UNCHECKED` (+3 silent entries) |
| `tests/lib/test_geometry.py` | geometry unit tests | **add** `extent_at_times` tests |
| `tests/lib/test_reel_final.py` | the three cores' unit tests | **create** |
| `tests/lib/test_safezones.py` | sampling unit tests | **add** `subject_extents` test |
| `tests/lib/test_models.py` | config-spec + advisory tests | **add** `ReelCheckSpec` threshold tests + advisory-widen test |
| `tests/lib/test_check_reel.py` | driver integration | **add** three-check integration tests |
| docs | sync | pipeline-map, build-status, CLAUDE.md, montage design §5.13 |

---

### Task 0: `geometry.extent_at_times` — project the subject bbox corners

**Files:**
- Modify: `scripts/lib/geometry.py` (add after `marks_at_times`, ~line 140)
- Test: `tests/lib/test_geometry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_geometry.py`:

```python
def test_extent_at_times_projects_bbox_corners_straddling_the_centre():
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    # fill 1000x2000; subject 100x200 centred at (500, 900) → centre mark (0.5, 0.45)
    route = [RoutePoint(0.0, 500.0, 900.0, 100.0, 200.0),
             RoutePoint(2.0, 500.0, 900.0, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000),
                    (0, 0, 1000, 2000), 0)
    ext = geometry.extent_at_times(route, path, meta, [0.0, 2.0])
    # left/top = (450/1000, 800/2000), right/bottom = (550/1000, 1000/2000)
    assert ext[0] == (0.45, 0.4, 0.55, 0.5)
    assert ext == [(0.45, 0.4, 0.55, 0.5)] * 2      # constant route → constant extents


def test_extent_at_times_pushes_a_corner_past_the_frame_when_subject_hugs_the_edge():
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    # subject centre x=980, w=100 → right edge 1030 → fx1 = 1.03 (clipped by the frame)
    route = [RoutePoint(0.0, 980.0, 900.0, 100.0, 200.0),
             RoutePoint(2.0, 980.0, 900.0, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000),
                    (0, 0, 1000, 2000), 0)
    (fx0, fy0, fx1, fy1), _ = geometry.extent_at_times(route, path, meta, [0.0, 2.0])
    assert fx1 == 1.03 and fx0 == 0.93


def test_extent_at_times_rejects_desync():
    import pytest
    from scripts.lib import geometry
    from scripts.lib.models import RoutePoint, CropPath, PathMeta
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000), (0, 0, 1000, 2000), 0)
    with pytest.raises(ValueError, match="parallel arrays"):
        geometry.extent_at_times([RoutePoint(0.0, 1.0, 1.0, 1.0, 1.0)], CropPath([0, 0]), meta, [0.0])
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -k extent -q ; echo "EXIT: $?"`
Expected: FAIL — `module 'scripts.lib.geometry' has no attribute 'extent_at_times'`.

- [ ] **Step 3: Implement `extent_at_times`**

Add to `scripts/lib/geometry.py` immediately after `marks_at_times`:

```python
def extent_at_times(route: "list[RoutePoint]", path: "CropPath", meta: "PathMeta",
                    times: list[float]) -> list[tuple[float, float, float, float]]:
    """The subject bbox corners (fx0, fy0, fx1, fy1) in OUTPUT frame fractions at
    each sample TIME — the same affine placement `marks_at_times` applies to the
    centre, applied to the source-px corners (x±w/2, y±h/2). The projection has
    positive scale, so min-source-corner maps to min-output-corner: fx0 ≤ fx1,
    fy0 ≤ fy1. Used by reel_final.evaluate_key_action to test the tracked subject
    against the frame edge (§5.13)."""
    if not route or len(route) != len(path):
        raise ValueError(f"route/path must be non-empty parallel arrays, "
                         f"got {len(route)} vs {len(path)}")
    ts = [p.t for p in route]
    xs = [p.x for p in route]
    ys = [p.y for p in route]
    ws = [p.w for p in route]
    hs = [p.h for p in route]
    cxs = path.xs
    rx, ry, rw, rh = meta.rect_px
    out_w, out_h = meta.out_dims
    extents = []
    for t in times:
        x = _interp(ts, xs, t)
        y = _interp(ts, ys, t)
        w = _interp(ts, ws, t)
        h = _interp(ts, hs, t)
        cx = _interp(ts, cxs, t)
        fx0 = (rx + rw * ((x - w / 2) - cx) / meta.crop_w) / out_w
        fx1 = (rx + rw * ((x + w / 2) - cx) / meta.crop_w) / out_w
        fy0 = (ry + rh * ((y - h / 2) - meta.crop_y) / meta.crop_h) / out_h
        fy1 = (ry + rh * ((y + h / 2) - meta.crop_y) / meta.crop_h) / out_h
        extents.append((fx0, fy0, fx1, fy1))
    return extents
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -k extent -q ; echo "EXIT: $?"`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/geometry.py tests/lib/test_geometry.py
git commit -m "feat: geometry.extent_at_times projects the subject bbox corners"
```

---

### Task 1: `ReelCheckSpec` — three advisory thresholds

**Files:**
- Modify: `scripts/lib/models.py:626-647` (`ReelCheckSpec` fields + `__post_init__`)
- Test: `tests/lib/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_reelcheckspec_editorial_thresholds_default():
    s = m.ReelCheckSpec(target_dur=6.0)
    assert s.clip_tol == 0.02 and s.bar_symmetry_tol == 0.02 and s.layout_jump_max == 0.6


@pytest.mark.parametrize("kw,msg", [
    (dict(clip_tol=0.5), "clip_tol"),            # >= 0.5
    (dict(clip_tol=-0.01), "clip_tol"),          # < 0
    (dict(bar_symmetry_tol=True), "bar_symmetry_tol"),   # bool is not a fraction
    (dict(layout_jump_max=0), "layout_jump_max"),        # must be positive
])
def test_reelcheckspec_editorial_thresholds_fail_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        m.ReelCheckSpec(target_dur=6.0, **kw)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k editorial_thresholds -q ; echo "EXIT: $?"`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'clip_tol'`.

- [ ] **Step 3: Implement the fields + validation**

In `scripts/lib/models.py`, add three fields to `ReelCheckSpec` after `loudness_tol` (line 633):

```python
    loudness_tol: float = 1.0          # ± band around the target
    clip_tol: float = 0.02             # advisory: frame-edge overshoot fraction tolerated before key_action flags
    bar_symmetry_tol: float = 0.02     # advisory: max left/right (top/bottom) pad-bar mismatch (canvas fraction)
    layout_jump_max: float = 0.6       # advisory: max layout-jump score across a cut before transitions flags
```

Append to `ReelCheckSpec.__post_init__` (after the `loudness_tol` check, line 647):

```python
        for name in ("clip_tol", "bar_symmetry_tol"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v < 0.5:
                raise ValueError(f"ReelCheckSpec.{name} must be a fraction in [0.0, 0.5), got {v!r}")
        if not isinstance(self.layout_jump_max, (int, float)) or self.layout_jump_max <= 0:
            raise ValueError(f"ReelCheckSpec.layout_jump_max must be a positive number, got {self.layout_jump_max!r}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k "editorial_thresholds or reelcheckspec" -q ; echo "EXIT: $?"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelCheckSpec grows clip_tol/bar_symmetry_tol/layout_jump_max"
```

---

### Task 2: `reel_final.evaluate_key_action` + `safezones.subject_extents`

**Files:**
- Create: `scripts/lib/reel_final.py`
- Modify: `scripts/lib/safezones.py` (add `subject_extents` after `subject_marks`, ~line 68)
- Test: `tests/lib/test_reel_final.py` (create), `tests/lib/test_safezones.py` (append)

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_reel_final.py`:

```python
from scripts.lib import reel_final


def test_key_action_passes_when_every_corner_is_inside():
    # two episodes, all corners within [0,1]
    extents = [[(0.1, 0.1, 0.3, 0.4)], [(0.4, 0.2, 0.6, 0.5)]]
    passed, detail = reel_final.evaluate_key_action(extents, clip_tol=0.02)
    assert passed is True and detail["advisory"] is True and detail["episodes"] == 2


def test_key_action_flags_the_worst_overshoot_with_edge_and_episode():
    # ep1 pokes 0.05 past the right edge (fx1 = 1.05) — beyond clip_tol 0.02
    extents = [[(0.1, 0.1, 0.3, 0.4)], [(0.9, 0.2, 1.05, 0.5)]]
    passed, detail = reel_final.evaluate_key_action(extents, clip_tol=0.02)
    assert passed is False
    assert detail["worst_episode"] == 1 and detail["edge"] == "right"
    assert detail["overshoot"] == 0.05 and detail["advisory"] is True


def test_key_action_tolerates_a_corner_just_touching_the_edge():
    # fx1 = 1.015 → overshoot 0.015 < clip_tol 0.02 → still safe
    extents = [[(0.0, 0.0, 1.015, 0.5)]]
    passed, _ = reel_final.evaluate_key_action(extents, clip_tol=0.02)
    assert passed is True
```

Append to `tests/lib/test_safezones.py` (reuses the file's `_geom` helper):

```python
def test_subject_extents_samples_five_corner_boxes_across_the_episode():
    route, path, meta = _geom(500.0, 900.0)        # fill 1000x2000, subject 100x200
    ext = safezones.subject_extents(route, path, meta, dur=2.0)
    assert len(ext) == 5
    assert ext == [(0.45, 0.4, 0.55, 0.5)] * 5     # constant route → constant extents
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_final.py tests/lib/test_safezones.py -k "key_action or subject_extents" -q ; echo "EXIT: $?"`
Expected: FAIL — `No module named 'scripts.lib.reel_final'` / `safezones has no attribute 'subject_extents'`.

- [ ] **Step 3: Implement**

Create `scripts/lib/reel_final.py`:

```python
"""The three still-mechanical §5.13 editorial checks (design
2026-07-17-reel-final-editorial-checks). Each is a pure decision over data the
reel already carries (subject-extent projections + per-episode PathMeta), and
each is ADVISORY: check_reel reports it into the ReelReport but it is excluded
from `overall` and never becomes a ReelFailure — zero blast radius on loop-2.
Companion to lib.safezones (the fourth §5.13 advisory check)."""
import math

from scripts.lib.models import PathMeta

LAYOUT_MODE_PENALTY = 0.5      # a mode change (fill↔insert) adds this to the layout-jump score


def evaluate_key_action(extents_per_ep: list[list[tuple[float, float, float, float]]],
                        clip_tol: float) -> tuple[bool, dict]:
    """Flag if any episode's tracked-subject bbox corner leaves the output frame
    [0,1] by more than `clip_tol` (a close-up legitimately touches the edge). The
    report names the deepest overshoot, its edge, and episode. Advisory."""
    worst = None                                   # (overshoot, ep_idx, edge)
    for i, extents in enumerate(extents_per_ep):
        for fx0, fy0, fx1, fy1 in extents:
            for over, edge in ((-fx0, "left"), (fx1 - 1.0, "right"),
                               (-fy0, "top"), (fy1 - 1.0, "bottom")):
                if over > clip_tol and (worst is None or over > worst[0]):
                    worst = (over, i, edge)
    if worst is None:
        return True, {"episodes": len(extents_per_ep), "advisory": True}
    over, idx, edge = worst
    return False, {"worst_episode": idx, "overshoot": round(over, 4), "edge": edge,
                   "advisory": True}
```

Add to `scripts/lib/safezones.py` after `subject_marks` (the projection sibling):

```python
def subject_extents(route: list[RoutePoint], path: CropPath, meta: PathMeta,
                    dur: float) -> list[tuple[float, float, float, float]]:
    """The subject's bbox corners (fx0, fy0, fx1, fy1) at _SAFE_SAMPLES points —
    the extent counterpart of subject_marks, feeding reel_final.evaluate_key_action
    (§5.13). Same sampling, geometry.extent_at_times instead of marks_at_times."""
    return extent_at_times(route, path, meta, _sample_times(dur))
```

Update the `safezones.py` import line (line 8) to also import `extent_at_times`:

```python
from scripts.lib.geometry import marks_at_times, extent_at_times
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_final.py tests/lib/test_safezones.py -k "key_action or subject_extents" -q ; echo "EXIT: $?"`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/reel_final.py scripts/lib/safezones.py tests/lib/test_reel_final.py tests/lib/test_safezones.py
git commit -m "feat: reel_final.evaluate_key_action + safezones.subject_extents (§5.13)"
```

---

### Task 3: `reel_final.evaluate_pad_bars`

**Files:**
- Modify: `scripts/lib/reel_final.py`
- Test: `tests/lib/test_reel_final.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_reel_final.py`:

```python
from scripts.lib.models import PathMeta


def _meta(mode="fill", rect_px=(0, 0, 1000, 2000), out=(1000, 2000)):
    return PathMeta(mode, 1000, 2000, 0, (1000, 2000), out, out, rect_px, 0)


def test_pad_bars_na_when_every_episode_is_fill():
    passed, detail = reel_final.evaluate_pad_bars([_meta("fill"), _meta("fill")], bar_symmetry_tol=0.02)
    assert passed is None and detail["status"] == "n/a" and detail["advisory"] is True


def test_pad_bars_passes_a_symmetric_letterbox():
    # fit-blur: 1000-wide content in a 1000x2000 frame, centred vertically (500px bars top+bottom)
    passed, detail = reel_final.evaluate_pad_bars([_meta("fit-blur", (0, 500, 1000, 1000))],
                                                  bar_symmetry_tol=0.02)
    assert passed is True and detail["bars"] == 1 and detail["advisory"] is True


def test_pad_bars_flags_a_rect_that_pokes_outside_the_frame():
    passed, detail = reel_final.evaluate_pad_bars([_meta("fit-blur", (0, 500, 1000, 1600))],
                                                  bar_symmetry_tol=0.02)
    assert passed is False and detail["issue"] == "rect_overflow" and detail["worst_episode"] == 0


def test_pad_bars_flags_asymmetric_bars():
    # top bar 300, bottom bar 700 → |300-700|/2000 = 0.2 > tol
    passed, detail = reel_final.evaluate_pad_bars([_meta("fit-blur", (0, 300, 1000, 1000))],
                                                  bar_symmetry_tol=0.02)
    assert passed is False and detail["issue"] == "asymmetric" and detail["worst_episode"] == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_final.py -k pad_bars -q ; echo "EXIT: $?"`
Expected: FAIL — `module 'scripts.lib.reel_final' has no attribute 'evaluate_pad_bars'`.

- [ ] **Step 3: Implement**

Add to `scripts/lib/reel_final.py`:

```python
def evaluate_pad_bars(metas: list[PathMeta], bar_symmetry_tol: float) -> tuple[bool | None, dict]:
    """Structural filler-bar check from the sidecar only (no pixels). For each
    non-`fill` episode: the content rect must lie inside the output frame, and the
    bars must be symmetric within `bar_symmetry_tol` (a canvas fraction). `fill`
    episodes have no bars (skipped); an all-`fill` reel is n/a. Advisory."""
    worst = None                                   # (severity, ep_idx, issue, rect, out)
    n_bars = 0
    for i, meta in enumerate(metas):
        if meta.mode == "fill":
            continue
        n_bars += 1
        rx, ry, rw, rh = meta.rect_px
        ow, oh = meta.out_dims
        overflow = max(-rx, -ry, (rx + rw) - ow, (ry + rh) - oh)
        if overflow > 0:
            sev = overflow / max(ow, oh)
            if worst is None or sev > worst[0]:
                worst = (sev, i, "rect_overflow", [rx, ry, rw, rh], [ow, oh])
            continue
        asym = max(abs(rx - (ow - (rx + rw))) / ow, abs(ry - (oh - (ry + rh))) / oh)
        if asym > bar_symmetry_tol and (worst is None or asym > worst[0]):
            worst = (asym, i, "asymmetric", [rx, ry, rw, rh], [ow, oh])
    if n_bars == 0:
        return None, {"status": "n/a", "reason": "no non-fill layout", "advisory": True}
    if worst is None:
        return True, {"bars": n_bars, "advisory": True}
    _, idx, issue, rect, out = worst
    return False, {"worst_episode": idx, "issue": issue, "rect_px": rect,
                   "out_dims": out, "advisory": True}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_final.py -k pad_bars -q ; echo "EXIT: $?"`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/reel_final.py tests/lib/test_reel_final.py
git commit -m "feat: reel_final.evaluate_pad_bars (structural sidecar check, §5.13)"
```

---

### Task 4: `reel_final.evaluate_transitions`

**Files:**
- Modify: `scripts/lib/reel_final.py`
- Test: `tests/lib/test_reel_final.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_reel_final.py`:

```python
def test_transitions_na_for_a_single_episode():
    passed, detail = reel_final.evaluate_transitions([_meta("fill")], layout_jump_max=0.6)
    assert passed is None and detail["status"] == "n/a" and detail["advisory"] is True


def test_transitions_passes_two_identical_layouts():
    passed, detail = reel_final.evaluate_transitions([_meta("fill"), _meta("fill")], layout_jump_max=0.6)
    assert passed is True and detail["cuts"] == 1 and detail["advisory"] is True


def test_transitions_flags_a_fill_to_insert_jump():
    # fill (area 1.0, centre 0.5,0.5) → insert card (area 0.09, centre 0.15,0.15)
    metas = [_meta("fill"), _meta("insert", (0, 0, 300, 600))]
    passed, detail = reel_final.evaluate_transitions(metas, layout_jump_max=0.6)
    assert passed is False and detail["worst_cut"] == 0 and detail["modes"] == ["fill", "insert"]
    assert detail["advisory"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_final.py -k transitions -q ; echo "EXIT: $?"`
Expected: FAIL — `module 'scripts.lib.reel_final' has no attribute 'evaluate_transitions'`.

- [ ] **Step 3: Implement**

Add to `scripts/lib/reel_final.py`:

```python
def _layout_of(meta: PathMeta) -> tuple[float, float, float, str]:
    """(coverage-fraction, centre-fx, centre-fy, mode) of one episode's content rect."""
    rx, ry, rw, rh = meta.rect_px
    ow, oh = meta.out_dims
    return (rw * rh) / (ow * oh), (rx + rw / 2) / ow, (ry + rh / 2) / oh, meta.mode


def evaluate_transitions(metas: list[PathMeta], layout_jump_max: float) -> tuple[bool | None, dict]:
    """Flag a cut whose layout jumps beyond `layout_jump_max`: |Δcoverage| +
    centre shift + a LAYOUT_MODE_PENALTY when the mode changes. Reads PathMeta
    only (reel episodes share the canvas, so fractions are comparable). n/a for a
    single episode. Advisory — 'jarring' is a taste proxy, never a gate."""
    if len(metas) < 2:
        return None, {"status": "n/a", "reason": "single episode", "advisory": True}
    worst = None                                   # (jump, cut_idx, [mode_i, mode_j])
    for i in range(len(metas) - 1):
        a0, cx0, cy0, m0 = _layout_of(metas[i])
        a1, cx1, cy1, m1 = _layout_of(metas[i + 1])
        jump = abs(a0 - a1) + math.hypot(cx0 - cx1, cy0 - cy1) + (LAYOUT_MODE_PENALTY if m0 != m1 else 0.0)
        if jump > layout_jump_max and (worst is None or jump > worst[0]):
            worst = (jump, i, [m0, m1])
    if worst is None:
        return True, {"cuts": len(metas) - 1, "advisory": True}
    jump, idx, modes = worst
    return False, {"worst_cut": idx, "jump": round(jump, 4), "modes": modes, "advisory": True}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_final.py -q ; echo "EXIT: $?"`
Expected: PASS (all reel_final tests green).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/reel_final.py tests/lib/test_reel_final.py
git commit -m "feat: reel_final.evaluate_transitions (layout-jump proxy, §5.13)"
```

---

### Task 5: widen `_ADVISORY_CHECKS` — the three never block `overall`

**Files:**
- Modify: `scripts/lib/models.py:755` (`_ADVISORY_CHECKS`)
- Test: `tests/lib/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_models.py`:

```python
def test_reelreport_overall_excludes_the_three_editorial_advisories():
    checks = {"black": m.CheckResult("black", True, {}),
              "key_action": m.CheckResult("key_action", False, {"advisory": True}),
              "pad_bars": m.CheckResult("pad_bars", False, {"advisory": True}),
              "transitions": m.CheckResult("transitions", False, {"advisory": True})}
    assert m.ReelReport(checks=checks).overall is True     # advisory Falses never block
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k three_editorial_advisories -q ; echo "EXIT: $?"`
Expected: FAIL — `overall` is `False` (the three are not yet advisory).

- [ ] **Step 3: Implement**

In `scripts/lib/models.py` replace line 755:

```python
_ADVISORY_CHECKS = ("beat", "safe_zones", "key_action", "pad_bars", "transitions")   # measured + reported, non-blocking (design §5)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k "advisory" -q ; echo "EXIT: $?"`
Expected: PASS (the new test + the existing `safe_zones` advisory test).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: key_action/pad_bars/transitions join _ADVISORY_CHECKS"
```

---

### Task 6: wire the three checks into `check_reel.run`

**Files:**
- Modify: `scripts/check_reel.py:16` (import), `:23-25` (`_UNCHECKED`), `:204-210` (the `geometry` block)
- Test: `tests/lib/test_check_reel.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_check_reel.py` (reuses the file's `_Stub` and `_write_geom`; adds a layout-writer):

```python
def _write_geom_layout(d, mode, rect_px):
    # a non-fill episode: subject centred, but the content rect is a card/letterbox
    d.mkdir(parents=True, exist_ok=True)
    (d / "route.json").write_text(json.dumps(
        [{"t": 0.0, "x": 500.0, "y": 900.0, "w": 100.0, "h": 200.0},
         {"t": 3.0, "x": 500.0, "y": 900.0, "w": 100.0, "h": 200.0}]))
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": mode, "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": list(rect_px), "freedom": 0}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


def test_editorial_checks_report_and_stay_advisory(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    # ep0 fills; ep1's subject (x=980, w=100 via _write_geom) pokes past the right edge → key_action False
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),
            _write_geom(tmp_path / "ep1", 980.0, 900.0)]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["key_action"].passed is False           # clipped subject flagged
    assert rep.checks["key_action"].detail["advisory"] is True
    assert rep.checks["pad_bars"].passed is None              # both fill → n/a
    assert rep.checks["transitions"].passed is True           # fill→fill, no layout jump
    assert rep.overall is True                                # all three advisory — none block
    assert not rep.fail_reasons                               # no ReelFailure emitted


def test_editorial_checks_flag_padbars_and_transitions(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    # ep0 fill; ep1 an asymmetric letterbox AND a fill→insert-ish layout jump
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),
            _write_geom_layout(tmp_path / "ep1", "insert", (0, 300, 400, 800))]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["pad_bars"].passed is False and rep.checks["pad_bars"].detail["worst_episode"] == 1
    assert rep.checks["transitions"].passed is False and rep.checks["transitions"].detail["worst_cut"] == 0
    assert rep.overall is True and not rep.fail_reasons


def test_editorial_checks_not_checked_when_silent(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))            # no geometry
    for name in ("key_action", "pad_bars", "transitions"):
        assert rep.checks[name].passed is None
        assert rep.checks[name].detail["status"] == "not-checked"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -k editorial -q ; echo "EXIT: $?"`
Expected: FAIL — `KeyError: 'key_action'` (the checks aren't wired yet).

- [ ] **Step 3: Implement**

In `scripts/check_reel.py` update the import (line 16):

```python
from scripts.lib import proc, reel_final, safezones
```

Extend `_UNCHECKED` (lines 23-25) with three entries:

```python
_UNCHECKED = {"beat": "not checked — no MUSIC.json supplied (silent reel)",
              "loudness": "not checked — no audio stem supplied (silent reel)",
              "safe_zones": "not checked — no per-episode geometry supplied",
              "key_action": "not checked — no per-episode geometry supplied",
              "pad_bars": "not checked — no per-episode geometry supplied",
              "transitions": "not checked — no per-episode geometry supplied"}
```

Replace the `geometry` block (lines 204-210) — load the sidecars once, feed all four checks:

```python
    if geometry is not None:
        routes = [route_from_json(r) for (r, _, _) in geometry]
        paths = [CropPath.from_json(p) for (_, p, _) in geometry]
        metas = [PathMeta.from_json(m) for (_, _, m) in geometry]
        zone = safezones.safe_zone_for(platform)
        marks_per_ep = [safezones.subject_marks(rt, pa, me, dur)
                        for rt, pa, me, dur in zip(routes, paths, metas, durations)]
        sz_pass, sz_detail = safezones.evaluate(marks_per_ep, zone)
        checks["safe_zones"] = CheckResult("safe_zones", sz_pass, sz_detail)
        extents_per_ep = [safezones.subject_extents(rt, pa, me, dur)
                          for rt, pa, me, dur in zip(routes, paths, metas, durations)]
        ka_pass, ka_detail = reel_final.evaluate_key_action(extents_per_ep, spec.clip_tol)
        checks["key_action"] = CheckResult("key_action", ka_pass, ka_detail)
        pb_pass, pb_detail = reel_final.evaluate_pad_bars(metas, spec.bar_symmetry_tol)
        checks["pad_bars"] = CheckResult("pad_bars", pb_pass, pb_detail)
        tr_pass, tr_detail = reel_final.evaluate_transitions(metas, spec.layout_jump_max)
        checks["transitions"] = CheckResult("transitions", tr_pass, tr_detail)
```

- [ ] **Step 4: Run to verify they pass + no regression**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/integration/test_safezones.py -q ; echo "EXIT: $?"`
Expected: PASS — new editorial tests green, **existing `safe_zones` tests still green** (the refactor is behaviour-preserving).

- [ ] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "feat: check_reel wires key_action/pad_bars/transitions (advisory, §5.13)"
```

---

### Task 7: docs sync + full suite + final whole-slice review

**Files:**
- Modify: `docs/pipeline-map.md`, `docs/build-status.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md`

- [ ] **Step 1: Full suite green**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS — the prior count (**1160 passed / 8 skipped**) + the ~14 new tests, exit 0. Record the new number.

- [ ] **Step 2: Sync the docs**

- `docs/pipeline-map.md` — the 5.13 row and the "Editorial reel-final" roadmap bullet: mark `key action not clipped` / `pad bars clean` / `layout transitions not jarring` as **built (advisory)**; the stage **stays ◐** (agent review = Slice B, still open). Tally unchanged (**14 ✅ · 1 ◐ · 1 ❌**). Bump `_Last updated_`.
- `docs/build-status.md` — add a bullet under the reel-final work naming the three advisory checks + `lib/reel_final.py` + `geometry.extent_at_times`; note Slice B (agent review) remains. Bump `_Last updated_` and correct the headline test count.
- `CLAUDE.md` Quick Reference — two rows: this design + this plan (mirroring the safe-zones rows' phrasing).
- `docs/specs/2026-07-05-montage-skillset-design.md` — line ~562 enumeration and §5.13 (line ~402-403): mark the three as built (advisory); the agent review is the only §5.13 item still open.

- [ ] **Step 3: Commit the docs**

```bash
git add docs/pipeline-map.md docs/build-status.md CLAUDE.md docs/specs/2026-07-05-montage-skillset-design.md
git commit -m "docs: §5.13 mechanical editorial trio landed (advisory); agent review still open"
```

- [ ] **Step 4: Final whole-slice review**

Dispatch a fresh subagent (read-only + pytest; **no installers**) to review the whole branch diff `main..feat/reel-final-editorial` against the spec: spec-compliance (all three checks advisory, no `overall`/loop-2 change, no new inputs) then code-quality (the projection math, the DRY `subject_extents`/`subject_marks` pairing, the threshold validation). Address any blocking findings as follow-up commits (not `--amend`). Then STOP and report — do **not** merge (the user merges to local `main` and pushes himself).

---

## Self-Review

**1. Spec coverage:**
- §2.1 `key_action` → Tasks 0 (projection) + 2 (decision) + 6 (wiring). ✓
- §2.2 `pad_bars` → Task 3 + 6. ✓
- §2.3 `transitions` → Task 4 + 6. ✓
- §3 `ReelCheckSpec` thresholds → Task 1; `_ADVISORY_CHECKS` widen → Task 5; `_UNCHECKED` + wiring → Task 6. ✓
- §4 testing → pure-core unit tests (Tasks 0-4), advisory proof (Task 5), integration incl. silent path (Task 6). ✓
- §5 boundaries (no `overall`/orchestration/deliver change) → held: only `_ADVISORY_CHECKS`, `_UNCHECKED`, the `geometry` block change; no driver/CLI edit. ✓
- §6 docs → Task 7. ✓
- No Slice B leakage. ✓

**2. Placeholder scan:** none — every code step carries full code; every run step has an exact command + expected result.

**3. Type consistency:** `extent_at_times → list[tuple4]` feeds `subject_extents → list[tuple4]` feeds `evaluate_key_action(extents_per_ep, clip_tol)`. `evaluate_pad_bars(metas, bar_symmetry_tol)` / `evaluate_transitions(metas, layout_jump_max)` both take `list[PathMeta]` and return `(bool | None, dict)`. `check_reel` reads `spec.clip_tol` / `spec.bar_symmetry_tol` / `spec.layout_jump_max` — the exact `ReelCheckSpec` fields from Task 1. Check names `key_action` / `pad_bars` / `transitions` are identical across Tasks 5, 6, and `_ADVISORY_CHECKS`. ✓
