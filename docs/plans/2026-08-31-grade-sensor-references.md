# Grade sensor references Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each of the two blocking colour gates a reference that admits the
declared grade exists, so a correctly graded episode stops failing and the two
no-exit loops open.

**Architecture:** One question per sensor. `check_episode.color_fidelity`
becomes `grade_damage` and asks "does the declared map destroy information?",
answered by the luma-histogram entropy of two renders that differ only in the
colour tail. `check_reel.tone_match` becomes `grade_faithful` and asks "did the
delivered pixels get the declaration?", answered against the profile the FULL
declared chain predicts instead of against a target solved with every other knob
at identity. The dE00 reading and the old target comparison survive as advisory
numbers.

**Tech Stack:** Python 3, numpy, ffmpeg via `scripts/lib/ffbin` + `scripts/lib/proc`,
pytest.

**Design:** [docs/specs/2026-08-31-grade-sensor-references-design.md](../specs/2026-08-31-grade-sensor-references-design.md)

## Global Constraints

- Scripts are modules: run everything as `python -m scripts.x`, never a path.
  `pythonpath = .` is set in pytest config. The interpreter is `.venv/bin/python`.
- **Never install anything.** No `brew`, `pip install`, `uv`, `npm`, no
  `setup.sh`. Verification is read-only plus `pytest`.
- **Never** `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.
- English in all code, comments, docstrings and commit messages.
- **A constant is measured, never chosen.** Task 3 measures the two thresholds
  this slice introduces and amends the design's §0 with the numbers. No later
  task may invent one.
- **No waiver, anywhere.** Neither gate gains a CLI flag, a manifest field or an
  environment override that lowers it. `entropy_floor` and `grade_residual_max`
  live on their specs and nowhere else.
- **Every real-ffmpeg proof carries a control that must not move.** A proof that
  only shows the new thing firing cannot tell a working sensor from one that
  fires on everything.
- Landmines that apply here (`CLAUDE.md` carries the full list):
  - A `select` filter placed BEFORE a chain's own `fps=` emits ONE frame N
    times and the frame count still comes out right. The only sanctioned way to
    append a sink is `reframe.RenderPlan.with_tail`.
  - `-ss` goes AFTER `-i`, and none of the new code uses an input seek at all.
  - A raw frame buffer is checked against `frames * w * h * channels`
    **exactly**. A `len(raw) % want == 0` check is vacuous whenever the frame
    size divides the frame count, which it does at 1920x1080.
- The mutation battery in Task 10 runs under `PYTHONDONTWRITEBYTECODE=1`. A
  one-byte edit can match the previous file's size and mtime-second and CPython
  will serve a stale `.pyc`.
- The 2026-06 run at `/Users/serg/Downloads/untitled folder/` is **read-only**.
  Never write into it.

---

## File Structure

| file | responsibility |
|---|---|
| `scripts/lib/gradedamage.py` | **new.** Pure: luma-histogram entropy and the damage verdict. numpy in, one dict out. No ffmpeg, no paths. |
| `scripts/lib/color.py` | gains `FRAMES` and `sample_times`, moved out of `color_measure` (which `check_episode` cannot import — `color_measure` imports `process_episode` imports `check_episode`). |
| `scripts/reframe.py` | gains `frames_rgb(plan, src, times)` — one plan, N decoded RGB frames. Lives beside `RenderPlan` because it is the plan's third sink, after the x264 encode and the gray ruler. |
| `scripts/process_episode.py` | gains public `plan_for` / `plan_ungraded` (the manifest→plan map, previously duplicated in `color_measure.plan_ungraded` and `probe._plan_for`); builds and passes the plan pair to `check_episode`. |
| `scripts/check_episode.py` | `color_fidelity` → `grade_damage`; dE00 demoted to an advisory field. |
| `scripts/check_reel.py` | `tone_match` → `grade_faithful`; prediction reference; advisory `target_dev`. |
| `scripts/build_reel.py` | computes the per-episode predictions once and forwards them. |
| `scripts/probe.py` | ungraded render; `grade_damage` and `predicted_profile` in `probe.json`. |
| `scripts/episode_qc.py` | `_source_reading` reads the crop-geometry ungraded render. |
| `scripts/lib/models.py` | `CheckSpec.grade_delta_max` → `entropy_floor`; `ReelCheckSpec.tone_match_max` → `grade_residual_max`. |
| `scripts/lib/orchestration.py` | `_UNFIXABLE` / `_UNFIXABLE_REASON` renamed. |

---

### Task 0: `lib/gradedamage.py` and the `sample_times` move

**Files:**
- Create: `scripts/lib/gradedamage.py`
- Create: `tests/lib/test_gradedamage.py`
- Modify: `scripts/lib/color.py` (add `FRAMES`, `sample_times`)
- Modify: `scripts/color_measure.py` (delete `FRAMES`/`sample_times`, re-point)
- Modify: `scripts/check_reel.py`, `scripts/probe.py` (call sites)
- Test: `tests/lib/test_gradedamage.py`, `tests/lib/test_color.py`

**Interfaces:**
- Produces: `gradedamage.ENTROPY_BINS: int`, `gradedamage.entropy(frame: np.ndarray) -> float`,
  `gradedamage.evaluate(plain: list, graded: list, floor: float) -> dict`.
  `evaluate` returns either `{"status","reason"}` or
  `{"ratio","plain_bits","graded_bits","floor","frames","below"}`.
- Produces: `color.FRAMES: int = 3`, `color.sample_times(dur: float, frames: int = FRAMES) -> list[float]`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_gradedamage.py`:

```python
import numpy as np
import pytest
from scripts.lib import gradedamage


def _flat(v: int, h: int = 8, w: int = 8) -> np.ndarray:
    return np.full((h, w, 3), v, dtype=np.uint8)


def _ramp(h: int = 16, w: int = 16) -> np.ndarray:
    """A frame whose luma covers many distinct codes."""
    g = np.tile(np.linspace(20, 220, w, dtype=np.uint8), (h, 1))
    return np.dstack([g, g, g])


def test_entropy_of_a_flat_frame_is_zero():
    assert gradedamage.entropy(_flat(128)) == pytest.approx(0.0)


def test_entropy_of_a_ramp_is_positive():
    assert gradedamage.entropy(_ramp()) > 3.0


def test_entropy_is_invariant_under_a_bijective_relabeling():
    """The whole reason this statistic was chosen: a monotone bijection carries the
    histogram intact, so movement alone must not read as damage."""
    a = _ramp()
    b = (a.astype(np.int16) + 20).clip(0, 255).astype(np.uint8)   # +20 codes, no collisions
    assert gradedamage.entropy(b) == pytest.approx(gradedamage.entropy(a))


def test_entropy_falls_under_a_many_to_one_map():
    a = _ramp()
    b = ((a.astype(np.int16) // 8) * 8).astype(np.uint8)          # 8:1 quantization
    assert gradedamage.entropy(b) < gradedamage.entropy(a) - 1.0


def test_evaluate_passes_a_relabeling():
    a = [_ramp(), _ramp(), _ramp()]
    b = [(f.astype(np.int16) + 20).clip(0, 255).astype(np.uint8) for f in a]
    d = gradedamage.evaluate(a, b, 0.90)
    assert d["ratio"] == pytest.approx(1.0, abs=1e-3)
    assert d["below"] is False
    assert d["frames"] == 3


def test_evaluate_fails_a_quantization():
    a = [_ramp(), _ramp(), _ramp()]
    b = [((f.astype(np.int16) // 8) * 8).astype(np.uint8) for f in a]
    d = gradedamage.evaluate(a, b, 0.90)
    assert d["below"] is True
    assert d["ratio"] < 0.90


def test_evaluate_judges_the_rounded_ratio_it_reports():
    """A report reading 'ratio: 0.9, floor: 0.9, below: true' is a contradiction no
    reader can act on — color_fidelity.evaluate documents the same rule."""
    a = [_ramp()]
    # craft graded frames whose raw ratio is just under 0.90 but rounds to 0.90
    e_a = gradedamage.entropy(a[0])
    target_bits = e_a * 0.8996
    lo, hi = 1, 255
    for _ in range(60):                       # bisect a quantization step onto target_bits
        mid = (lo + hi) / 2
        cand = ((a[0].astype(np.float64) / mid).round() * mid).clip(0, 255).astype(np.uint8)
        if gradedamage.entropy(cand) > target_bits:
            lo = mid
        else:
            hi = mid
    b = [((a[0].astype(np.float64) / lo).round() * lo).clip(0, 255).astype(np.uint8)]
    d = gradedamage.evaluate(a, b, 0.90)
    assert d["below"] is (d["ratio"] < d["floor"])


def test_evaluate_reports_not_checked_on_no_frames():
    d = gradedamage.evaluate([], [], 0.90)
    assert d["status"] == "not-checked"
    assert "below" not in d


def test_evaluate_refuses_mismatched_lists():
    with pytest.raises(ValueError, match="parallel"):
        gradedamage.evaluate([_ramp()], [_ramp(), _ramp()], 0.90)


def test_evaluate_reports_not_checked_when_the_ungraded_frame_is_flat():
    """A flat ungraded frame has zero entropy and no ratio exists. Reporting a
    division result would be inventing one."""
    d = gradedamage.evaluate([_flat(128)], [_flat(200)], 0.90)
    assert d["status"] == "not-checked"
```

Append to `tests/lib/test_color.py`:

```python
def test_sample_times_never_touches_the_ends():
    ts = color.sample_times(4.0)
    assert ts == [0.5, 2.0, 3.5]


def test_sample_times_refuses_a_non_positive_frame_count():
    with pytest.raises(ValueError, match="integer >= 1"):
        color.sample_times(4.0, 0)


def test_sample_times_refuses_a_bool_frame_count():
    with pytest.raises(ValueError, match="integer >= 1"):
        color.sample_times(4.0, True)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_gradedamage.py tests/lib/test_color.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.lib.gradedamage`, and
`AttributeError: module 'scripts.lib.color' has no attribute 'sample_times'`.

- [ ] **Step 3: Write `scripts/lib/gradedamage.py`**

```python
"""Grade damage (design docs/specs/2026-08-31-grade-sensor-references-design.md §3):
does the declared colour chain DESTROY information, as opposed to moving it?

Pure — numpy arrays in, one dict out. The caller renders the two frame sets and
the caller decides; this module owns the statistic and what the numbers are called.

This replaces a subject dE00 gate that could not tell a grade from damage, because
a grade IS movement and dE00 measures movement. Shannon entropy of the luma
histogram is invariant under any BIJECTIVE monotone map — a relabeling carries the
histogram intact — and falls only where the map is many-to-one. That is exactly
"blind to movement, sensitive to destruction".

Measured (design §0.3) against three classes on the reference run: legitimate
conductor pairs land 0.921-1.058 and deliberate damage at legal knob extremes lands
0.814-0.910. Two obvious alternatives were measured and rejected: a distinct-code
count is pinned at 227-254 of 256 on real footage and reads black_point=0.35 as
1.042 (the crush registers as an improvement), and mean gradient inverts the same
way at 1.327.

Read on the WHOLE frame, never the subject box. Measured (§0.3): the run's subject
boxes span 2420 to 890406 px, a 368x range, and a 256-bin entropy estimator over
2420 samples is biased far enough to erase the class boundary. The whole delivered
frame is ~2M samples on every episode, so the bias is constant across the pool and
cancels in the ratio."""
import statistics

import numpy as np

ENTROPY_BINS = 256      # one bin per 8-bit code. Coarsening to 64 was measured and
                        # makes the two classes overlap (design §0.3).


def entropy(frame: np.ndarray) -> float:
    """Shannon entropy in bits of one HxWx3 uint8 RGB frame's luma histogram."""
    y = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
    counts = np.bincount(y.round().clip(0, 255).astype(np.uint8).ravel(),
                         minlength=ENTROPY_BINS)
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log2(p)).sum())


def evaluate(plain: list, graded: list, floor: float) -> dict:
    """The episode's damage verdict: the MEDIAN per-frame entropy ratio against `floor`.

    `plain` and `graded` are parallel: the same frames of the same render, differing
    only in the colour tail. That symmetry is the point — libx264 quantization lowers
    entropy on its own, so comparing a render against a shipped clip would bias the
    ratio toward false damage.

    Median, not worst, for the reason color_fidelity.evaluate gives: one atypical
    frame must not decide an episode.

    Rounds once and judges the ROUNDED value, so `below` always agrees with the
    `ratio` the report shows — the same rule color_fidelity.evaluate documents."""
    if len(plain) != len(graded):
        raise ValueError(f"gradedamage.evaluate: plain and graded are parallel lists "
                         f"of the same frames, got {len(plain)} and {len(graded)}")
    if not plain:
        return {"status": "not-checked", "reason": "no frames to compare"}
    pe = [entropy(f) for f in plain]
    ge = [entropy(f) for f in graded]
    ratios = [g / p for p, g in zip(pe, ge) if p > 0]
    if not ratios:
        return {"status": "not-checked",
                "reason": "every ungraded frame is flat — no information to lose"}
    r = round(statistics.median(ratios), 3)
    return {"ratio": r,
            "plain_bits": round(statistics.median(pe), 3),
            "graded_bits": round(statistics.median(ge), 3),
            "floor": floor,
            "frames": len(ratios),
            "below": r < floor}
```

- [ ] **Step 4: Move `FRAMES` and `sample_times` into `scripts/lib/color.py`**

Append to `scripts/lib/color.py` (after `percentiles`):

```python
FRAMES = 3          # start / middle / end of a span, at (i+0.5)/N — never the first
                    # or last frame, which a dip or a bookend can own. Measured
                    # (design 2026-08-30 §0.4): 5 and 9 frames give the same residual
                    # median and a slightly worse maximum, because the residual is not
                    # sampling noise.
                    #
                    # Lives here rather than in color_measure because check_episode
                    # needs it and cannot import that driver: color_measure imports
                    # process_episode, which imports check_episode.


def sample_times(dur: float, frames: int = FRAMES) -> list[float]:
    """`frames` sample times spread over `dur`, at (k+0.5)/frames of it."""
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"frames must be an integer >= 1, got {frames!r}")
    return [((k + 0.5) / frames) * dur for k in range(frames)]
```

Delete both from `scripts/color_measure.py`. Then re-point every reader — find
them with:

```bash
grep -rn 'color_measure\.FRAMES\|color_measure\.sample_times\|sample_times(' scripts/ tests/
```

Inside `color_measure.py` itself the bare `sample_times(...)`/`FRAMES` references
become `color.sample_times(...)`/`color.FRAMES` (the module already imports
`color`). In `check_reel.py` and `probe.py`, `color_measure.sample_times` becomes
`color.sample_times` and `color_measure.FRAMES` becomes `color.FRAMES`; add
`color` to their existing `from scripts.lib import ...` line if absent.

- [ ] **Step 5: Run the new tests**

Run: `.venv/bin/python -m pytest tests/lib/test_gradedamage.py tests/lib/test_color.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite — the move must break nothing**

Run: `.venv/bin/python -m pytest -q`
Expected: the same pass/skip counts as before the task (3321 passed, 1 skipped at
`46d7784`; a task that changes them must say why).

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/gradedamage.py scripts/lib/color.py scripts/color_measure.py \
        scripts/check_reel.py scripts/probe.py \
        tests/lib/test_gradedamage.py tests/lib/test_color.py
git commit -m "feat: entropy as the damage statistic, and one sample_times"
```

---

### Task 1: `reframe.frames_rgb` — a plan's third sink

**Files:**
- Modify: `scripts/reframe.py` (add `frames_rgb` after `plan_render`)
- Test: `tests/integration/test_reframe_frames.py` (create)

**Interfaces:**
- Consumes: `reframe.RenderPlan`, `RenderPlan.with_tail`, `RenderPlan.rl.out_w/out_h`,
  `RenderPlan.fps`, `RenderPlan.dur`.
- Produces: `reframe.frames_rgb(plan: RenderPlan, src: str, times: list[float]) -> list[np.ndarray]`
  — each element HxWx3 uint8 in the plan's OUTPUT dimensions.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_reframe_frames.py`:

```python
"""reframe.frames_rgb over real ffmpeg — the plan's RGB sink."""
import numpy as np
import pytest

from scripts import process_episode, reframe

pytestmark = pytest.mark.integration


def _manifest(seg: str, out: str) -> dict:
    return {"segment": seg, "out_path": out, "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480"}


def test_frames_rgb_returns_one_frame_per_time_at_output_dims(golden_ride_segment, tmp_path):
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    times = [0.2, 0.6, 1.0]
    frames = reframe.frames_rgb(plan, str(golden_ride_segment), times)
    assert len(frames) == 3
    for f in frames:
        assert f.shape == (plan.rl.out_h, plan.rl.out_w, 3)
        assert f.dtype == np.uint8


def test_frames_rgb_returns_DIFFERENT_frames_not_one_repeated(golden_ride_segment, tmp_path):
    """The §12 select landmine: a select before the chain's own fps= emits ONE frame
    N times and the count still comes out right, so a length assertion cannot see it."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    frames = reframe.frames_rgb(plan, str(golden_ride_segment), [0.1, 0.7, 1.3])
    assert not np.array_equal(frames[0], frames[1])
    assert not np.array_equal(frames[1], frames[2])


def test_frames_rgb_refuses_a_short_buffer(golden_ride_segment, tmp_path):
    """A time past the stream's end yields fewer frames; the exact-byte check must
    catch it rather than reshape whatever arrived."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    with pytest.raises(RuntimeError, match="asked for"):
        reframe.frames_rgb(plan, str(golden_ride_segment), [0.1, 999.0])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe_frames.py -q`
Expected: FAIL — `AttributeError: module 'scripts.reframe' has no attribute 'frames_rgb'`
(and `plan_for`, which Task 2 adds; until then the test fails on the first missing
name, which is fine — Step 5 re-runs it after Task 2).

**Note for the implementer:** `process_episode.plan_for` is Task 2's deliverable.
Implement `frames_rgb` now against a plan built inline with
`reframe.plan_render(process_episode.build_reframe_spec(...), ...)` if you want a
green step here; the test above is written against the final API and Task 2 makes
it pass. Do not invent a different name.

- [ ] **Step 3: Implement**

Add `import numpy as np` to `scripts/reframe.py`'s imports, and after `plan_render`:

```python
def frames_rgb(plan: RenderPlan, src: str, times: list[float]) -> list:
    """The frames this plan would encode at `times`, decoded HxWx3 uint8 RGB.

    The plan's THIRD sink, beside reframe()'s x264 encode and
    color_measure.crop_percentiles' gray ruler. One chain builder, three sinks —
    a caller that rebuilt the chain would be a second implementation of the render.

    The select goes through with_tail, at the END: before the chain's own `fps=` it
    emits the SAME frame once per requested time and the output count is still right,
    so nothing fails and the caller compares a frame against itself (§12).

    No -ss anywhere. An input seek resets each frame's timestamp and the crop's x is
    a function of t, so the crop would land somewhere else, silently.
    """
    nums = [round(t * plan.fps) for t in times]
    sel = "select='" + "+".join(rf"eq(n\,{n})" for n in nums) + "'"
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src,
                    *plan.with_tail(f"{sel},format=rgb24"),
                    "-t", f"{plan.dur:.6f}", "-vsync", "0",
                    "-frames:v", str(len(nums)),
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
    w, h = plan.rl.out_w, plan.rl.out_h
    stride = w * h * 3
    want = len(nums) * stride
    # EXACT, never a modulo: len(raw) % want is true for every real frame count
    # whenever the frame size divides the request, which it does at 1920x1080 for
    # three frames (design 2026-08-30 plan, Task 0's finding).
    if len(raw) != want:
        raise RuntimeError(
            f"frames_rgb asked for {len(nums)} frames {nums} of {w}x{h} "
            f"({want} bytes) from {src} and got {len(raw)} — a frame number is past "
            f"the stream's end (times {times} against a {plan.dur:.3f}s source at "
            f"{plan.fps:.4g}fps)")
    return [np.frombuffer(raw, dtype=np.uint8, count=stride,
                          offset=i * stride).reshape(h, w, 3)
            for i in range(len(nums))]
```

- [ ] **Step 4: Verify the landmine lint still passes over the new argv**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py tests/integration/test_lint_argv.py -q`
Expected: PASS. If a lint file with a different name exists, find it with
`grep -rln 'select_before_fps' tests/` and run that.

- [ ] **Step 5: Run the test (after Task 2 lands, re-run)**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe_frames.py -q`
Expected: PASS once `plan_for` exists. Note in the report if it is still red on
`plan_for` only.

- [ ] **Step 6: Commit**

```bash
git add scripts/reframe.py tests/integration/test_reframe_frames.py
git commit -m "feat: reframe.frames_rgb — the plan's RGB sink"
```

---

### Task 2: one manifest→plan map

**Files:**
- Modify: `scripts/process_episode.py` (add `plan_for`, `plan_ungraded` after `build_reframe_spec`)
- Modify: `scripts/color_measure.py` (delete `plan_ungraded`, call through)
- Modify: `scripts/probe.py` (delete `_plan_for`, call through)
- Test: `tests/lib/test_process_episode_plans.py` (create)

**Interfaces:**
- Consumes: `process_episode.build_reframe_spec`, `manifest_lib.strip_colour`,
  `reframe.plan_render`, `orch.DEFAULT_PARAMS`.
- Produces:
  - `process_episode.plan_for(manifest_dict: dict, src: str, route: str | None) -> reframe.RenderPlan`
  - `process_episode.plan_ungraded(manifest_dict: dict, src: str, route: str | None) -> reframe.RenderPlan`

**Why:** `color_measure.plan_ungraded` and `probe._plan_for` are the same six lines
with and without the colour strip, and `plan_ungraded`'s own docstring already
names the drift risk ("the piece that must not be copied"). Task 5 needs a third
caller and `check_episode` cannot import either module without a cycle.

- [ ] **Step 1: Write the failing test**

`tests/lib/test_process_episode_plans.py`:

```python
"""process_episode.plan_for / plan_ungraded — the ONE manifest -> RenderPlan map."""
import pytest

from scripts import color_measure, process_episode
from scripts.lib import manifest as manifest_lib


def _md(seg: str) -> dict:
    return {"segment": seg, "out_path": "/tmp/ep.mp4", "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480",
            "saturation": 0.8, "black_point": 0.1}


def test_plan_for_carries_the_colour_block(golden_ride_segment):
    plan = process_episode.plan_for(_md(str(golden_ride_segment)),
                                    str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    assert "eq=saturation=0.8000" in plan.grade
    assert "colorlevels" in plan.grade


def test_plan_ungraded_strips_it(golden_ride_segment):
    plan = process_episode.plan_ungraded(_md(str(golden_ride_segment)),
                                         str(golden_ride_segment),
                                         "tests/fixtures/golden_route.json")
    assert "eq=saturation" not in plan.grade
    assert "colorlevels" not in plan.grade


def test_the_two_plans_differ_ONLY_in_the_colour_tail(golden_ride_segment):
    """The damage sensor's whole premise. If geometry moved too, the entropy ratio
    would be measuring a crop, not a grade."""
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    a = process_episode.plan_for(_md(src), src, route)
    b = process_episode.plan_ungraded(_md(src), src, route)
    assert a.path == b.path
    assert (a.rl.out_w, a.rl.out_h) == (b.rl.out_w, b.rl.out_h)
    assert a.crop_ws == b.crop_ws and a.crop_hs == b.crop_hs and a.crop_ys == b.crop_ys
    assert a.cy == b.cy and a.fps == b.fps and a.dur == b.dur
    assert a.grade != b.grade


def test_color_measure_no_longer_owns_a_second_copy():
    assert not hasattr(color_measure, "plan_ungraded")


def test_plan_ungraded_is_plan_for_of_a_stripped_manifest(golden_ride_segment):
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    a = process_episode.plan_ungraded(_md(src), src, route)
    b = process_episode.plan_for(manifest_lib.strip_colour(_md(src)), src, route)
    assert a.grade == b.grade and a.filter_args == b.filter_args
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode_plans.py -q`
Expected: FAIL — `AttributeError: module 'scripts.process_episode' has no attribute 'plan_for'`.

- [ ] **Step 3: Implement in `scripts/process_episode.py`**

Immediately after `build_reframe_spec`:

```python
def plan_for(manifest_dict: dict, src: str, route: str | None) -> reframe.RenderPlan:
    """The RenderPlan this manifest would render — the ONE manifest -> plan map.

    Lives here because build_reframe_spec does, and its docstring already names the
    risk this function exists to remove: a caller carrying its own copy of the map
    drifts field by field. Two callers used to have one each (color_measure's
    stripped variant and probe's graded one) and check_episode now needs a third.

    Params come from orch.DEFAULT_PARAMS: this builds a plan from a manifest alone,
    which is what a probe, a measurement and a check all want. The retry loop below
    does NOT come through here — it carries the attempt's own adjusted params, and
    reading defaults there would silently probe a different render than it ships."""
    m = manifest_lib.Manifest.from_dict(manifest_dict)
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        params["smooth_window_s"] = m.smooth_window_s
    spec = build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    return reframe.plan_render(spec, src, route)


def plan_ungraded(manifest_dict: dict, src: str, route: str | None) -> reframe.RenderPlan:
    """`plan_for` with every colour knob at identity — the render a measurement reads
    through, and the plain half of the damage sensor's pair."""
    return plan_for(manifest_lib.strip_colour(manifest_dict), src, route)
```

- [ ] **Step 4: Delete the two copies**

In `scripts/color_measure.py`: delete `plan_ungraded` entirely and change
`measure_crop`'s body to
`plan = process_episode.plan_ungraded(manifest_dict, src, route)`. Drop any import
that is now unused (`manifest_lib`, `orch`, `Delivery` may become dead — check with
`grep -n 'manifest_lib\.\|orch\.\|Delivery' scripts/color_measure.py`).

In `scripts/probe.py`: delete `_plan_for` and replace both call sites
(`probe_grade`, `probe_grade_geometry`) with `process_episode.plan_for(md, src, ep.route)`
and `process_episode.plan_for(md, eg.source, eg.route)`. Drop the now-unused
`Manifest` / `orch` / `Delivery` imports if nothing else uses them.

- [ ] **Step 5: Run the task's tests and the two suites that own these modules**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode_plans.py tests/integration/test_reframe_frames.py -q`
Expected: PASS — both, including Task 1's, which was waiting on `plan_for`.

Run: `.venv/bin/python -m pytest -q -k "probe or color_measure or grade_shipped"`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: unchanged pass/skip counts.

- [ ] **Step 7: Commit**

```bash
git add scripts/process_episode.py scripts/color_measure.py scripts/probe.py \
        tests/lib/test_process_episode_plans.py
git commit -m "refactor: one manifest -> RenderPlan map, three callers"
```

---

### Task 3: measure the two thresholds

**Files:**
- Create: `tests/integration/test_grade_sensor_calibration.py`
- Modify: `docs/specs/2026-08-31-grade-sensor-references-design.md` (§0.5, new)

**Interfaces:**
- Consumes: `reframe.frames_rgb`, `process_episode.plan_for`/`plan_ungraded`,
  `gradedamage.evaluate`, `color_measure.crop_percentiles`, `color.sample_times`.
- Produces: two numbers, written into the design as §0.5 and consumed as literals
  by Tasks 4 and 6: `CheckSpec.entropy_floor` and `ReelCheckSpec.grade_residual_max`.

**This task exists because a constant in this repo is measured, not chosen.** The
design proposes 0.90 and "~4.0"; only the first has a measurement behind it, and
that one is on the reference run, not on the fixture the suite can re-run.

- [ ] **Step 1: Write the measurement, as a test that asserts the bracket**

`tests/integration/test_grade_sensor_calibration.py`:

```python
"""The two thresholds this slice introduces, measured on real bytes.

Not a proof of behaviour — a proof that the CONSTANTS are where the footage puts
them. Each assertion brackets the measured value loosely enough to survive an
ffmpeg point release and tightly enough to fail if the number moves for a reason.
"""
import pytest

from scripts import color_measure, process_episode, reframe
from scripts.lib import color, gradedamage
from scripts.lib import orchestration as orch
from scripts.lib.manifest import Manifest
from scripts.lib.models import Delivery

pytestmark = pytest.mark.integration

ROUTE = "tests/fixtures/golden_route.json"


def _md(seg: str, out: str, **colour) -> dict:
    md = {"segment": seg, "out_path": out, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "layout": "fill",
          "canvas": [9, 16], "delivery": "short_edge:480"}
    md.update(colour)
    return md


def _ratio(md: dict, src: str) -> float:
    graded = process_episode.plan_for(md, src, ROUTE)
    plain = process_episode.plan_ungraded(md, src, ROUTE)
    times = color.sample_times(graded.dur)
    d = gradedamage.evaluate(reframe.frames_rgb(plain, src, times),
                             reframe.frames_rgb(graded, src, times), 0.90)
    return d["ratio"]


def test_the_entropy_floor_sits_between_a_legitimate_grade_and_a_damaging_one(
        golden_ride_segment, tmp_path):
    """§0.4's 1.2% margin, re-measured on the fixture the suite owns.

    A legitimate grade is a conductor-shaped tone pair: measure this crop's own
    profile and pull it toward a plausible common target. A damaging one is
    black_point at its documented maximum."""
    src = str(golden_ride_segment)
    prof = color_measure.measure_crop(_md(src, str(tmp_path / "a.mp4")), src, ROUTE)
    target = [round(prof[0] + 12, 1), round(prof[1] - 10, 1), round(prof[2] - 18, 1)]
    legit = _ratio(_md(src, str(tmp_path / "b.mp4"),
                       tone_src=list(prof), tone_dst=target), src)
    damaged = _ratio(_md(src, str(tmp_path / "c.mp4"), black_point=0.35), src)
    print(f"\nMEASURED entropy ratio: legitimate {legit:.3f}  damaging {damaged:.3f}")
    assert damaged < legit, "the classes must not invert on this fixture"
    assert damaged < 0.90 <= legit, (
        f"entropy_floor = 0.90 must separate them: legit {legit}, damaged {damaged}")


def test_an_ungraded_episode_reads_exactly_one(golden_ride_segment, tmp_path):
    """The control that must not move: with no colour block the two plans are the
    same render, so the ratio is 1.0 by construction. A sensor that drifts here is
    measuring the render, not the grade."""
    src = str(golden_ride_segment)
    assert _ratio(_md(src, str(tmp_path / "d.mp4")), src) == pytest.approx(1.0, abs=1e-3)


def test_the_faithfulness_residual_of_a_healthy_render_is_small(
        golden_ride_segment, tmp_path):
    """grade_residual_max's floor: render the episode for real, then compare the
    master's own profile against what the plan predicts. This is the number the
    ceiling must clear."""
    src = str(golden_ride_segment)
    out = str(tmp_path / "ep.mp4")
    md = _md(src, out, tone_src=[40.0, 120.0, 200.0], tone_dst=[52.0, 104.0, 192.0],
             black_point=0.05)
    plan = process_episode.plan_for(md, src, ROUTE)
    rspec = process_episode.build_reframe_spec(
        Manifest.from_dict(md), Delivery.from_spec(md["delivery"]),
        dict(orch.DEFAULT_PARAMS))
    reframe.reframe(rspec, src, ROUTE, out, str(tmp_path / "path.json"))
    times = color.sample_times(plan.dur)
    predicted = color_measure.crop_percentiles(plan, src, times)
    got = color_measure.clip_percentiles(out, times)
    residual = max(abs(a - b) for a, b in zip(got, predicted))
    print(f"\nMEASURED faithfulness residual (healthy, WITH a post-tone knob): {residual:.2f}")
    assert residual < 4.0, (
        f"a healthy render must sit well inside grade_residual_max; got {residual}")
```

**Implementer note on `reframe.reframe`:** confirm its signature with
`grep -n "^def reframe" -A 4 scripts/reframe.py` before writing the call — this
plan assumes `(spec, src, route_path, out_path, path_out)`.

**Implementer note on `clip_percentiles`:** check its real signature with
`grep -n 'def clip_percentiles' -A 6 scripts/color_measure.py`. If it takes
`(clip, times)` use it as written; if it takes a span list, use
`color_measure.clip_percentiles_batch(out, [times])[0]`.

- [ ] **Step 2: Run it and READ THE PRINTED NUMBERS**

Run: `.venv/bin/python -m pytest tests/integration/test_grade_sensor_calibration.py -q -s`
Expected: three PASS and three `MEASURED …` lines. If a bracket fails, the
constant is wrong, not the test — record the real numbers and continue to Step 3.

- [ ] **Step 3: Set `grade_residual_max` from the measurement**

Take the healthy residual `R` printed by the third test. The ceiling is
`ceil(R) + 2.0`, rounded to one decimal, with a floor of 4.0 — the same shape as
the predecessor's mid-gap reasoning, with the +2.0 covering the encoder noise the
single fixture cannot sample. Write the chosen value and its derivation into the
design as a new §0.5.

- [ ] **Step 4: Amend the design**

Add to `docs/specs/2026-08-31-grade-sensor-references-design.md` after §0.4:

```markdown
### §0.5 The two constants, measured on the suite's own fixture

Measured 2026-08-31 through `tests/integration/test_grade_sensor_calibration.py`
on `golden_ride_segment` — real camera footage cut to the tv-range segment
contract, with `golden_route.json` as its route.

| | value | how |
|---|---|---|
| `CheckSpec.entropy_floor` | 0.90 | a conductor-shaped tone pair reads <LEGIT>; `black_point = 0.35` reads <DAMAGED>; an ungraded episode reads 1.000 exactly |
| `ReelCheckSpec.grade_residual_max` | <CEILING> | a healthy render carrying a post-tone `black_point = 0.05` sits <R> luma units from its own prediction; the ceiling is that plus 2.0 for encoder noise a single fixture cannot sample |

The reference run put the floor's margin at 1.2 % (§0.4); this fixture is a second
shoot and a second geometry, and it agrees. Two points is not a survey and §9.1
says so.
```

Replace `<LEGIT>`, `<DAMAGED>`, `<CEILING>` and `<R>` with the printed numbers. No
placeholder may survive this step.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_grade_sensor_calibration.py \
        docs/specs/2026-08-31-grade-sensor-references-design.md
git commit -m "test: measure both thresholds on the suite's own real footage"
```

---

### Task 4: `CheckSpec.entropy_floor` and `check_episode.grade_damage`

**Files:**
- Modify: `scripts/lib/models.py` (`CheckSpec`)
- Modify: `scripts/check_episode.py`
- Modify: `scripts/lib/orchestration.py`
- Modify: `scripts/lib/color_fidelity.py` (drop the verdict, keep the description)
- Test: `tests/lib/test_models.py`, `tests/test_check_episode.py`,
  `tests/lib/test_orchestration.py`, `tests/lib/test_color_fidelity.py`

**Interfaces:**
- Consumes: `gradedamage.evaluate`, `color.sample_times`, `reframe.frames_rgb`.
- Produces: `CheckSpec.entropy_floor: float = 0.90`;
  `check_episode.run(..., plans: tuple | None = None)`;
  report key `grade_damage` replacing `color_fidelity`;
  `orchestration._UNFIXABLE` containing `"grade_damage"` and
  `_UNFIXABLE_REASON = {"grade_damage": "grade-damage"}`.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_models.py`, replace the `grade_delta_max` tests with:

```python
def test_check_spec_entropy_floor_defaults_to_the_measured_value():
    s = CheckSpec(composition="center", grid="thirds", target_dur=2.0)
    assert s.entropy_floor == 0.90


@pytest.mark.parametrize("bad", [0, -0.1, 1.5, True, "0.9", None])
def test_check_spec_refuses_an_out_of_range_entropy_floor(bad):
    with pytest.raises(ValueError, match="entropy_floor"):
        CheckSpec(composition="center", grid="thirds", target_dur=2.0, entropy_floor=bad)


def test_check_spec_no_longer_carries_grade_delta_max():
    assert not hasattr(CheckSpec(composition="center", grid="thirds", target_dur=2.0),
                       "grade_delta_max")
```

In `tests/test_check_episode.py`, add:

```python
def test_grade_damage_is_not_checked_without_plans(tmp_path, monkeypatch):
    """Same shape `source` already uses: absent input reports absent, never a
    clean pass, and never blocks."""
    rep = _run_check_episode(tmp_path, monkeypatch, plans=None)
    d = rep.checks["grade_damage"]
    assert d.passed is None
    assert d.detail["status"] == "not-checked"
    assert "color_fidelity" not in rep.checks


def test_grade_damage_blocks_when_the_ratio_is_below_the_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(check_episode.gradedamage, "evaluate",
                        lambda p, g, floor: {"ratio": 0.80, "plain_bits": 7.0,
                                             "graded_bits": 5.6, "floor": floor,
                                             "frames": 3, "below": True})
    rep = _run_check_episode(tmp_path, monkeypatch, plans=_fake_plans())
    assert rep.checks["grade_damage"].passed is False
    assert "grade_damage" in rep.fail_reasons


def test_the_subject_dE00_survives_as_an_advisory_number(tmp_path, monkeypatch):
    """It is a good DESCRIPTION of what a grade did and the QC judge reads it. It
    is not a gate: a conductor pair puts 5 of 8 real episodes over the old 5.0
    ceiling and none of them is damage (design §0.1)."""
    rep = _run_check_episode(tmp_path, monkeypatch, plans=_fake_plans())
    d = rep.checks["grade_damage"].detail
    assert "delta_e" in d and "dominant" in d
    assert d["advisory_delta_e"] is True
```

**Implementer note:** `_run_check_episode` and `_fake_plans` are helpers you write
in that file, matching its existing style — read the file first and follow how its
current `color_fidelity` tests build a clip, a route and a sidecar. `_fake_plans`
returns a `(graded, plain)` pair of `reframe.RenderPlan` objects built from a real
manifest against the test's own fixture clip; the tests above stub
`gradedamage.evaluate`, so the plans only have to be renderable.

In `tests/lib/test_orchestration.py`, rename every `color_fidelity` occurrence to
`grade_damage` and add:

```python
def test_grade_damage_is_unfixable_and_names_its_own_remedy():
    a = orchestration.next_action(["grade_damage"], attempt=1, max_attempts=3)
    assert a.kind == "stop_and_report"
    assert a.finding["reason"] == "grade-damage"


def test_color_fidelity_is_no_longer_a_known_unfixable():
    assert "color_fidelity" not in orchestration._UNFIXABLE
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/test_check_episode.py tests/lib/test_orchestration.py -q`
Expected: FAIL on `entropy_floor`, on `KeyError: 'grade_damage'`, and on
`_UNFIXABLE` still holding the old name.

- [ ] **Step 3: `CheckSpec`**

In `scripts/lib/models.py`, replace the `grade_delta_max` field and its validation:

```python
    # The smallest luma-entropy ratio (graded / ungraded, whole delivered frame) an
    # episode may carry. 0.90 is measured, not chosen: on the reference run
    # legitimate conductor pairs land 0.921-1.058 and deliberate damage at legal
    # knob extremes lands 0.814-0.910, and the suite's own fixture agrees
    # (design 2026-08-31 §0.3/§0.4/§0.5). A ratio, so it is bounded by 1.0 —
    # a "floor" above 1 would refuse every render including an ungraded one.
    entropy_floor: float = 0.90
```

The 0.90 here is a literal because Task 3 measured it and design §0.5 records it.
If Task 3's measurement moved it, use THAT number. No token, no expression — the
file must contain a decimal.

```python
        if (isinstance(self.entropy_floor, bool)
                or not isinstance(self.entropy_floor, (int, float))
                or not 0 < self.entropy_floor <= 1.0):
            raise ValueError(f"CheckSpec.entropy_floor must be a ratio in (0, 1], "
                             f"got {self.entropy_floor!r}")
```

- [ ] **Step 4: `check_episode`**

Add `gradedamage` and `color` to the `from scripts.lib import ...` line, add
`from scripts import reframe`, and replace `_colour_fidelity` with:

```python
def _grade_damage(clip: str, source: str | None, plans, route_pts, path_obj,
                  meta, spec: CheckSpec) -> CheckResult:
    """Does the DECLARED grade destroy information (design 2026-08-31 §3)?

    Renders the same episode twice — once with its colour block, once with every
    knob at identity — and compares the luma-histogram entropy of the two. Both
    sides come from a render, never from the shipped clip: libx264 quantization
    lowers entropy on its own and would bias the ratio toward false damage. The
    consequence is explicit and paired: THIS sensor judges the declared map, and
    check_reel's grade_faithful judges the delivered pixels.

    `plans` is (graded, plain) and comes from process_episode, which owns the
    attempt's own params — building the pair here from orch defaults would compare
    two renders the episode never made. `None` reports not-checked and does not
    block, exactly the shape `source` uses.

    The subject dE00 rides along as an ADVISORY description, not a verdict. It was
    the verdict until 2026-08-31, and it could not tell a grade from damage: on the
    reference run a real conductor pair puts five of eight episodes over the old
    5.0 ceiling, two at over twice it, and none of them is damage (design §0.1).
    """
    if plans is None or source is None:
        return CheckResult("grade_damage", None,
                           {"status": "not-checked",
                            "reason": "no render plans" if source else "no source clip"})
    graded_plan, plain_plan = plans
    times = color.sample_times(graded_plan.dur)
    g_frames = reframe.frames_rgb(graded_plan, source, times)
    p_frames = reframe.frames_rgb(plain_plan, source, times)
    d = gradedamage.evaluate(p_frames, g_frames, spec.entropy_floor)
    d.update(_subject_delta_advisory(clip, source, route_pts, path_obj, meta))
    if "status" in d:
        return CheckResult("grade_damage", None, d)
    return CheckResult("grade_damage", not d["below"], d)
```

Keep the old sampling body as `_subject_delta_advisory`, returning the advisory
fields instead of a `CheckResult`:

```python
def _subject_delta_advisory(clip: str, source: str | None, route_pts, path_obj,
                            meta) -> dict:
    """The tracked subject's source-vs-graded dE00, as a DESCRIPTION. Same sampling
    as the old color_fidelity gate; the only change is that nothing votes on it."""
    if source is None or not route_pts:
        return {"advisory_delta_e": True, "delta_e": None,
                "delta_reason": "no source clip or no tracked subject"}
    # ... the existing _colour_fidelity body, unchanged, up to the evaluate call ...
    d = color_fidelity.evaluate(pairs)
    return {"advisory_delta_e": True, **d}
```

**Implementer note:** `color_fidelity.evaluate`'s `delta_max` parameter and its
`threshold`/`exceeded` keys now have no consumer. Delete the parameter and both
keys from `scripts/lib/color_fidelity.py`, update its docstring to say it
describes rather than judges, and update `tests/lib/test_color_fidelity.py`
accordingly — do not leave a dead threshold in a module whose whole failure mode
was a bar measuring the wrong thing.

Then in `run`: add `plans=None` to the signature, and swap the wiring line:

```python
    checks["grade_damage"] = _grade_damage(clip, source, plans, route_pts,
                                           path_obj, meta, spec)
```

- [ ] **Step 5: `orchestration`**

```python
_UNFIXABLE = ("length", "continuity", "black_frames", "grade_damage")
_UNFIXABLE_REASON = {"grade_damage": "grade-damage"}
```

Update the comment above them: the remedy is still the episode's colour block, and
now that is the right answer rather than a loop, because the sensor fires only on
a grade that destroys information.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/test_check_episode.py tests/lib/test_orchestration.py tests/lib/test_color_fidelity.py -q`
Expected: PASS.

- [ ] **Step 7: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Integration files naming `color_fidelity`
(`tests/integration/test_check_episode.py`, `test_color_fidelity.py`,
`test_colour_stage.py`, `test_process_episode.py`, `test_grade_shipped_pixels.py`)
need their key renamed; find them with
`grep -rn 'color_fidelity' tests/ | grep -v test_color_fidelity.py`.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/models.py scripts/check_episode.py scripts/lib/orchestration.py \
        scripts/lib/color_fidelity.py tests/
git commit -m "feat: color_fidelity becomes grade_damage, and dE00 becomes a description"
```

---

### Task 5: `process_episode` passes the plan pair

**Files:**
- Modify: `scripts/process_episode.py` (the retry loop, around line 428)
- Test: `tests/integration/test_process_episode.py`

**Interfaces:**
- Consumes: `process_episode.plan_for` semantics but NOT the function — the loop
  carries the attempt's own `params`, so it builds both plans from `rspec` and a
  colour-stripped twin with the SAME `params`.
- Produces: `check_episode.run(..., plans=(graded, plain))`.

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_process_episode.py`:

```python
def test_process_episode_hands_check_episode_a_plan_pair_that_differs_only_in_colour(
        monkeypatch, tmp_path, sample_clip):
    """Nothing else pins this wiring, and deleting the argument leaves the whole
    suite green while the gate silently reports not-checked forever — the exact
    failure the 2026-08-30 slice found on `src = prepared_source`."""
    seen = {}
    real = check_episode.run

    def spy(*a, **kw):
        seen["plans"] = kw.get("plans")
        return real(*a, **kw)

    monkeypatch.setattr(check_episode, "run", spy)
    _run_one_episode(tmp_path, sample_clip, saturation=0.8)   # existing helper
    graded, plain = seen["plans"]
    assert graded.grade != plain.grade
    assert graded.path == plain.path
    assert (graded.rl.out_w, graded.rl.out_h) == (plain.rl.out_w, plain.rl.out_h)


def test_the_plain_plan_uses_the_ATTEMPT_S_params_not_the_defaults(
        monkeypatch, tmp_path, sample_clip):
    """A retry adjusts smooth_window_s. If the plain plan read orch defaults the two
    renders would differ in GEOMETRY as well as colour and the entropy ratio would
    be measuring a crop."""
    seen = {}
    monkeypatch.setattr(check_episode, "run",
                        lambda *a, **kw: seen.setdefault("plans", kw["plans"]) or
                                         _passing_report(tmp_path))
    _run_one_episode(tmp_path, sample_clip, smooth_window_s=0.9, saturation=0.8)
    graded, plain = seen["plans"]
    assert graded.path == plain.path
```

**Implementer note:** `_run_one_episode` and `_passing_report` follow that file's
existing helpers — read it first. If the file has no such helper, build the
manifest inline the way its neighbouring tests do.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -q -k plan_pair`
Expected: FAIL — `seen["plans"]` is `None`.

- [ ] **Step 3: Implement**

In the retry loop, after `rspec = build_reframe_spec(m, delivery, params)`:

```python
        # The damage sensor's pair: the SAME render twice, differing only in the
        # colour tail. Built from this attempt's own `params`, not through
        # plan_for/plan_ungraded, which read orch defaults — a retry that adjusted
        # smooth_window_s would otherwise compare two different geometries and the
        # entropy ratio would be measuring a crop instead of a grade.
        plain_m = manifest_lib.Manifest.from_dict(manifest_lib.strip_colour(manifest_dict))
        plain_spec = build_reframe_spec(plain_m, delivery, params)
        plans = (reframe.plan_render(rspec, src, rp),
                 reframe.plan_render(plain_spec, src, rp))
```

and pass `plans=plans` to `check_episode.run`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/process_episode.py tests/integration/test_process_episode.py
git commit -m "feat: the damage sensor gets its pair, at the attempt's own params"
```

---

### Task 6: `check_reel.grade_faithful`

**Files:**
- Modify: `scripts/lib/models.py` (`ReelCheckSpec`)
- Modify: `scripts/check_reel.py`
- Test: `tests/lib/test_check_reel.py`, `tests/lib/test_models.py`

**Interfaces:**
- Consumes: `color.sample_times`, `color_measure.clip_percentiles_batch`.
- Produces:
  - `ReelCheckSpec.grade_residual_max: float` — design §0.5's measured decimal (`tone_match_max` deleted)
  - `check_reel.run(..., predicted: list | None = None, tone_target=None, tone_dsts=None)`
  - report key `grade_faithful` replacing `tone_match`
  - `ReelFailure("grade_faithful", "process-episode", i, {...})`

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_check_reel.py`, replace the `tone_match` block with:

```python
def test_grade_faithful_passes_when_the_master_matches_every_prediction(monkeypatch, tmp_path):
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)
    c = rep.checks["grade_faithful"]
    assert c.passed is True
    assert c.detail["worst"] == 0.0
    assert "tone_match" not in rep.checks


def test_grade_faithful_judges_EVERY_episode_not_only_the_bound_ones(monkeypatch, tmp_path):
    """Faithfulness is a property of any declaration, including an empty one. The
    old not-bound skip is gone (design §2.1)."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    tone_target=(52.0, 104.0, 192.0), tone_dsts=[None, None])
    assert rep.checks["grade_faithful"].detail["residuals"] == {"0": 0.0, "1": 0.0}
    assert rep.checks["grade_faithful"].detail["not_checked"] == {}


def test_grade_faithful_fails_and_routes_to_process_episode(monkeypatch, tmp_path):
    """A dropped colour block is a render that did not get its declaration; the
    remedy is a re-render, not a re-authoring."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0), (20.0, 104.0, 192.0)])
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)
    assert rep.checks["grade_faithful"].passed is False
    f = [x for x in rep.failures if x.check == "grade_faithful"][0]
    assert f.stage == "process-episode"
    assert f.index == 1


def test_grade_faithful_is_not_checked_without_predictions(tmp_path):
    rep = _run_reel(tmp_path, predicted=None)
    c = rep.checks["grade_faithful"]
    assert c.passed is None
    assert c.detail["reason"] == "no-predictions"


def test_a_missing_prediction_is_NAMED_never_silently_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0), None])
    d = rep.checks["grade_faithful"].detail
    assert d["not_checked"] == {"1": "no-prediction"}
    assert "1" not in d["residuals"]


def test_target_dev_is_advisory_and_only_for_bound_episodes(monkeypatch, tmp_path):
    """The agreement signal survives as a number, not a gate (design §2.1). A gate
    would re-open the deadlock from the other side: ep0's declared chain lands
    12.50 from the target and only an iterative conductor can fix that."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0), (70.0, 104.0, 192.0)],
                    tone_target=(52.0, 104.0, 192.0),
                    tone_dsts=[[52.0, 104.0, 192.0], None])
    d = rep.checks["grade_faithful"].detail
    assert d["target_dev"] == {"0": 0.0}
    assert rep.checks["grade_faithful"].passed is True     # advisory never blocks


def test_predicted_must_be_parallel_to_the_episodes(tmp_path):
    with pytest.raises(ValueError, match="parallel"):
        _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)])   # 1 for 2 episodes
```

In `tests/lib/test_models.py`:

```python
def test_reel_check_spec_no_longer_carries_tone_match_max():
    assert not hasattr(ReelCheckSpec(target_dur=10.0), "tone_match_max")


def test_reel_check_spec_grade_residual_max_defaults_to_the_measured_value():
    assert ReelCheckSpec(target_dur=10.0).grade_residual_max == 4.0   # <- design §0.5
```

**Implementer note:** `4.0` is this plan's expectation, not a measurement — put
design §0.5's actual number in BOTH places (here and the dataclass default) and
make them agree. `_run_reel` is a helper you write in that file following its
existing style.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_models.py -q`
Expected: FAIL — `KeyError: 'grade_faithful'` and `tone_match_max` still present.

- [ ] **Step 3: `ReelCheckSpec`**

Replace `tone_match_max` with:

Substitute the decimal design §0.5 records. The line below must contain a
number when you write it — a surviving token is a plan failure, and
`tests/lib/test_models.py` pins the value, so a token cannot ship silently.

```python
    grade_residual_max: float = 4.0    # <- REPLACE with design §0.5's measured value
                                       # max per-anchor luma distance between an
                                       # episode's delivered profile and what its own
                                       # DECLARED chain predicts. Measured (design
                                       # 2026-08-31 §0.5). Replaces tone_match_max,
                                       # whose reference — the reel's common target,
                                       # solved with every other knob at identity —
                                       # was displaced by any post-tone luma knob and
                                       # so failed correctly graded episodes (§0.2).
```

and rename its `__post_init__` validation to match, keeping the same shape.

- [ ] **Step 4: Rewrite `_tone_match_check` as `_grade_faithful_check`**

```python
def _grade_faithful_check(master: str, durations: list[float], cuts: list[float],
                          spec: ReelCheckSpec, predicted: list | None,
                          tone_target, tone_dsts) -> tuple[CheckResult, ReelFailure | None]:
    """GRADE_FAITHFUL — did the delivered pixels get the declaration (design
    2026-08-31 §2)?

    BLOCKING, and now unconditionally justified. The old reference was the reel's
    common tone target, and the justification was that percentiles commute with a
    monotone map — true, and irrelevant: it holds only while the tone curve is the
    LAST luma operation, and six luma-moving filters follow it in
    color.grade_chain. Measured (§0.2) on the reference run, all eight episodes
    carry a post-tone knob, the knobs displace the reading by up to 4.0 units and
    one of eight crossed the old 12.0 ceiling while being correctly graded.

    `predicted[i]` is the (p5, p50, p95) that episode i's OWN full declared chain
    produces, rendered fresh by the caller. Fresh, never recorded at render time:
    build_reel's retry loop re-renders an episode after any record was written, and
    a stale binding is this repo's most repeated wound.

    Every episode is judged, not only the ones bound to a common target —
    faithfulness is a property of any declaration, including an empty one. An
    episode whose prediction could not be built is NAMED in `not_checked`, never
    silently passed.

    `target_dev` is ADVISORY: max|prediction - target| for bound episodes, i.e. does
    the declared grade actually land this episode on the reel's common tone. It
    carries two jobs the blocking reading gives up — a reference independent of
    process_episode.build_reframe_spec, which the prediction now shares with the
    render, and the only remaining measure of cross-episode agreement. It is not a
    gate because making it one re-opens the deadlock from the other side (§2.1).

    Read off the MASTER, not the delivered reel: the look's vignette and the bookend
    fade ride deliver's one encode and both move percentiles. Every span is measured
    in ONE clip_percentiles_batch call.

    Escalates to process-episode — the pixels did not get the declaration, so the
    remedy is a re-render, not a re-authoring — and escalates for free:
    reel_orchestration._REPROCESS_CLASS is ("black",).
    """
    if predicted is None:
        return CheckResult("grade_faithful", None, {
            "status": "not-checked", "reason": "no-predictions",
            "remedy": "check_reel was called without per-episode predictions; "
                      "build_reel supplies them, and the CLI cannot (it has no "
                      "manifests to plan from)"}), None
    if len(predicted) != len(durations):
        raise ValueError(
            f"check_reel: predicted carries {len(predicted)} profiles for "
            f"{len(durations)} episodes — they are parallel lists; build_reel "
            f"builds one per episode, None where a plan could not be made")
    starts = [0.0] + cuts
    not_checked: dict[str, str] = {}
    idx: list[int] = []
    spans: list[list[float]] = []
    for i, (st, dur, p) in enumerate(zip(starts, durations, predicted)):
        if p is None:
            not_checked[str(i)] = "no-prediction"
            continue
        idx.append(i)
        spans.append([st + t for t in color.sample_times(dur)])
    residuals: dict[str, float] = {}
    worst, worst_i = 0.0, None
    if spans:
        got_profiles = color_measure.clip_percentiles_batch(master, spans)
        for i, got in zip(idx, got_profiles):
            d = max(abs(a - b) for a, b in zip(got, predicted[i]))
            residuals[str(i)] = round(d, 2)
            if d > worst:
                worst, worst_i = d, i
    target_dev: dict[str, float] = {}
    if tone_target is not None:
        for i, p in enumerate(predicted):
            if p is not None and _same_target((tone_dsts or [None] * len(predicted))[i],
                                              tone_target):
                target_dev[str(i)] = round(max(abs(a - b) for a, b in zip(p, tone_target)), 2)
    detail = {"residuals": residuals, "not_checked": not_checked,
              "max": spec.grade_residual_max,
              "target_dev": target_dev, "target_dev_advisory": True}
    if not residuals:
        return CheckResult("grade_faithful", None, {
            **detail, "status": "not-checked", "reason": "no-episode-predicted",
            "remedy": "no episode could be planned — read the per-episode reasons "
                      "in not_checked"}), None
    ok = worst <= spec.grade_residual_max
    detail["worst"] = round(worst, 2)
    fail = None if ok else ReelFailure("grade_faithful", "process-episode", worst_i,
                                       {"residual": round(worst, 2),
                                        "max": spec.grade_residual_max})
    return CheckResult("grade_faithful", ok, detail), fail
```

Update `run`'s signature to `predicted: list | None = None` beside the existing
`tone_target`/`tone_dsts`, and the wiring:

```python
    cr, fail = _grade_faithful_check(master, durations, cuts, spec, predicted,
                                     tone_target, tone_dsts)
    checks["grade_faithful"] = cr
```

Keep `_same_target` and `_TONE_BIND_EPS` — `target_dev` still uses them. Delete
`_tone_match_check`.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_models.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/models.py scripts/check_reel.py tests/lib/test_check_reel.py tests/lib/test_models.py
git commit -m "feat: tone_match becomes grade_faithful, against the declared chain"
```

---

### Task 7: `build_reel` builds the predictions

**Files:**
- Modify: `scripts/build_reel.py`
- Test: `tests/lib/test_build_reel.py`

**Interfaces:**
- Consumes: `process_episode.plan_for`, `probe.source_for`,
  `color_measure.crop_percentiles`, `color.sample_times`,
  `check_reel.run(..., predicted=...)`.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing test**

In `tests/lib/test_build_reel.py`:

```python
def test_build_reel_forwards_one_prediction_per_episode(monkeypatch, tmp_path):
    """Nothing else pins this. A dropped argument leaves the gate reporting
    not-checked forever and the suite green."""
    seen = {}
    monkeypatch.setattr(build_reel.check_reel, "run",
                        lambda *a, **kw: seen.update(kw) or _green_report(a[3]))
    monkeypatch.setattr(build_reel, "_predict",
                        lambda rm: [(52.0, 104.0, 192.0)] * len(rm.episodes))
    build_reel.build_reel(_manifest_path(tmp_path))
    assert seen["predicted"] == [(52.0, 104.0, 192.0)] * 2


def test_a_plan_that_cannot_be_built_becomes_None_not_a_crash(monkeypatch, tmp_path):
    """One unplannable episode must not cost the reel its whole gate — check_reel
    names it in not_checked."""
    def boom(md, src, route):
        raise FileNotFoundError("gone")
    monkeypatch.setattr(build_reel.process_episode, "plan_for", boom)
    rm = _reel_manifest(tmp_path)
    assert build_reel._predict(rm) == [None] * len(rm.episodes)


def test_predictions_are_built_ONCE_not_per_retry_round(monkeypatch, tmp_path):
    """A reprocess re-renders with the same manifest, so the declaration cannot move
    between rounds — the same argument tone_dsts already makes."""
    calls = []
    monkeypatch.setattr(build_reel, "_predict", lambda rm: calls.append(1) or [None, None])
    monkeypatch.setattr(build_reel.check_reel, "run",
                        lambda *a, **kw: _report_failing_black(a[3]))
    build_reel.build_reel(_manifest_path(tmp_path))
    assert len(calls) == 1
```

**Implementer note:** `_green_report`, `_report_failing_black`, `_manifest_path`
and `_reel_manifest` follow that file's existing helpers — read it first. The
file's `check_reel.run` stub must accept the new `predicted` keyword; widen it,
the way the 2026-08-30 slice had to.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -q -k predict`
Expected: FAIL — `AttributeError: module 'scripts.build_reel' has no attribute '_predict'`.

- [ ] **Step 3: Implement**

Add `from scripts import color_measure, probe, process_episode` (whichever are not
already imported) and, above `build_reel`:

```python
def _predict(rm: ReelManifest) -> list:
    """One (p5, p50, p95) per episode: what its OWN full declared chain produces.

    The reference check_reel.grade_faithful compares the master against. Built here
    rather than inside check_reel because this is where the manifests are, and built
    ONCE rather than per retry round because a reprocess re-renders with the same
    manifest — the declaration cannot move between rounds, the same argument
    tone_dsts already makes just below.

    probe.source_for, not md["segment"]: under `stabilize` reframe consumed the
    pre-stage's output, and planning against the raw segment would predict pixels
    the episode never shipped.

    An episode whose plan cannot be built contributes None. check_reel NAMES it in
    not_checked; losing one episode's reading must not cost the reel its gate.
    """
    out = []
    for e in rm.episodes:
        try:
            md = dict(e.manifest)
            src = probe.source_for(md, Path(e.path).parent)
            plan = process_episode.plan_for(md, src, e.route)
            out.append(color_measure.crop_percentiles(
                plan, src, color.sample_times(plan.dur)))
        except Exception as ex:                     # noqa: BLE001 — reported, not swallowed
            _log(f"build_reel: no grade prediction for {e.clip}: {ex}")
            out.append(None)
    return out
```

Then, beside the existing `tone_dsts = [...]` line:

```python
    predicted = _predict(rm)
```

and add `predicted=predicted` to the `check_reel.run(...)` call.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. `edl_to_reel` and the attestation may name `tone_match`; find with
`grep -rn 'tone_match' scripts/ tests/ skills/ docs/`.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py
git commit -m "feat: build_reel predicts each episode's own declared profile"
```

---

### Task 8: the two consumers — `probe` and `episode_qc`

**Files:**
- Modify: `scripts/probe.py` (`probe_grade`, `probe_grade_geometry`)
- Modify: `scripts/episode_qc.py` (`_source_reading`)
- Test: `tests/integration/test_probe.py`, `tests/lib/test_episode_qc.py`

**Interfaces:**
- Consumes: `process_episode.plan_ungraded`, `reframe.frames_rgb`,
  `gradedamage.evaluate`, `models.CheckSpec` (for the floor).
- Produces: `probe.json` gains `"grade_damage"` and `"predicted_profile"`.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_probe.py`:

```python
def test_probe_json_predicts_BOTH_gates(tmp_path, golden_ride_segment):
    """The P2 row this closes: an operator converging on stills could not see the
    stop coming, and probe was the only cheap way to converge at all."""
    rep = _probe_one(tmp_path, golden_ride_segment, saturation=0.8, black_point=0.1)
    assert rep["grade_damage"]["ratio"] > 0.0
    assert "below" in rep["grade_damage"]
    assert rep["predicted_profile"] == rep["tone_profile"]


def test_probe_grade_damage_agrees_with_check_episode_on_the_same_episode(
        tmp_path, golden_ride_segment):
    """A predictor that disagrees with the gate it predicts is worse than none."""
    rep = _probe_one(tmp_path, golden_ride_segment, black_point=0.35)
    from_check = _check_episode_grade_damage(tmp_path, golden_ride_segment,
                                             black_point=0.35)
    assert rep["grade_damage"]["ratio"] == pytest.approx(from_check["ratio"], abs=0.02)
    assert rep["grade_damage"]["below"] is from_check["below"]
```

In `tests/lib/test_episode_qc.py`:

```python
def test_source_reading_measures_the_source_IN_THE_EPISODE_S_CROP(monkeypatch, tmp_path):
    """It used to measure the whole segment frame against a reframed crop of it —
    the branch's own test recorded source contrast 0.0 against graded 123.6 with no
    grade at all, which is a crop, not a grade."""
    seen = {}
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded",
                        lambda md, src, route: seen.setdefault("planned", (src, route))
                        or _fake_plan())
    monkeypatch.setattr(episode_qc.reframe, "frames_rgb",
                        lambda plan, src, times: [_flat_frame()] * len(times))
    d = episode_qc._source_reading(_episode(tmp_path), {"contrast": 100.0})
    assert seen["planned"][0].endswith("segment.mp4")
    assert d["source"] is not None


def test_source_reading_still_reports_absent_as_absent(tmp_path):
    ep = _episode(tmp_path, segment="/nowhere/gone.mp4")
    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}
```

**Implementer note:** the helpers (`_probe_one`, `_check_episode_grade_damage`,
`_fake_plan`, `_flat_frame`, `_episode`) follow each file's existing style.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_probe.py tests/lib/test_episode_qc.py -q -k "predict or grade_damage or crop"`
Expected: FAIL — `KeyError: 'grade_damage'`.

- [ ] **Step 3: `probe`**

In both `probe_grade` and `probe_grade_geometry`, after the existing
`tone = color_measure.crop_percentiles(plan, src, times)`:

```python
    plain = process_episode.plan_ungraded(md, src, <route>)
    damage = gradedamage.evaluate(reframe.frames_rgb(plain, src, times),
                                  [np.asarray(i) for i in imgs],
                                  CheckSpec.__dataclass_fields__["entropy_floor"].default)
```

and add to the report dict:

```python
        "predicted_profile": [round(v, 1) for v in tone],
        "grade_damage": damage,
```

`<route>` is `ep.route` in `probe_grade` and `eg.route` in `probe_grade_geometry`.
`imgs` are already RGB arrays from `_render`; if `_render` returns PIL-converted
arrays already, drop the `np.asarray`.

Keep `"tone_profile"` as well — it is the same number under its established name,
and `predicted_profile` says what it is FOR. Add a one-line comment saying they
are the same value.

**Implementer note on the floor:** reading it out of the dataclass field default
keeps ONE definition. If that reads badly in this codebase's style, use
`CheckSpec(composition="center", grid="thirds", target_dur=1.0).entropy_floor`
instead — but do not hardcode 0.90 in probe.

- [ ] **Step 4: `episode_qc._source_reading`**

Replace the segment-frame read with the crop-geometry ungraded render:

```python
def _source_reading(ep, graded: dict) -> dict:
    """The episode's own source IN ITS OWN CROP, and the delta against the delivered
    clip (design 2026-08-31 §5).

    It used to measure a whole segment frame against a reframed crop of that frame —
    often 9:16 out of 16:9 — so the "delta" carried the crop as well as the grade.
    The ungraded render this slice added is exactly the source in the delivered
    geometry, which makes the two readings comparable for the first time.

    probe.source_for, not ep.manifest["segment"]: on a stabilized episode the two
    colour sensors used to describe changes from two different starting points.

    A manifest whose source is gone reports both as None — absent is reported as
    absent, never as a clean reading."""
    md = dict(ep.manifest)
    try:
        src = probe.source_for(md, Path(ep.path).parent)
        plan = process_episode.plan_ungraded(md, src, ep.route)
    except (FileNotFoundError, KeyError, ValueError):
        return {"source": None, "delta": None}
    frames = reframe.frames_rgb(plan, src, color.sample_times(plan.dur, SENSOR_FRAMES))
    src_stats = naturalness.measure(frames)
    return {"source": src_stats, "delta": naturalness.evaluate_delta(src_stats, graded)}
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_probe.py tests/lib/test_episode_qc.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/probe.py scripts/episode_qc.py tests/integration/test_probe.py tests/lib/test_episode_qc.py
git commit -m "feat: probe predicts both gates; QC reads the source in the episode's crop"
```

---

### Task 9: the six real-ffmpeg proofs

**Files:**
- Create: `tests/integration/test_grade_sensor_references.py`

**Interfaces:** consumes everything above; produces nothing.

Every proof carries a control that must not move.

- [ ] **Step 1: Write the proofs**

```python
"""Design 2026-08-31 §7 — the six proofs, each with a control.

Real ffmpeg throughout. These are the claims the slice stands on; a green unit
suite over stubbed renders proves none of them.
"""
import numpy as np
import pytest

from scripts import build_reel, check_episode, check_reel, color_measure, \
    process_episode, reframe
from scripts.lib import color, gradedamage
from scripts.lib.models import CheckSpec, ReelCheckSpec

pytestmark = pytest.mark.integration

ROUTE = "tests/fixtures/golden_route.json"
```

- **Proof 1 — the deadlock, demonstrated and removed.** Author a conductor-shaped
  tone pair on `golden_ride_segment`, run the full `process_episode`, and assert
  `report.checks["grade_damage"].passed is True` while the OLD statistic — the
  advisory `delta_e` now in the same detail dict — exceeds 5.0. **Control:** the
  same episode ungraded passes both and its `delta_e` is under 5.0, so the proof
  is showing a grade crossing the old bar rather than a broken fixture.

- **Proof 2 — damage still fails.** `black_point = 0.35` through the same path:
  `grade_damage.passed is False`, `fail_reasons` contains `grade_damage`, and
  `orchestration.next_action` returns `stop_and_report` with reason
  `grade-damage`. **Control:** `black_point = 0.02` passes, so the proof is not
  simply "any black_point fails".

- **Proof 3 — faithfulness passes a post-tone knob and fails a dropped block.**
  Render two episodes with a tone pair plus `black_point = 0.05`, assemble the
  master, run `build_reel`'s prediction path, and assert `grade_faithful.passed is
  True` with `worst` under `grade_residual_max`. Then re-run `check_reel.run` with
  `predicted` computed from a manifest whose colour block was stripped — the
  "declared but never rendered" case — and assert it fails and routes to
  `process-episode`. **Control:** with the correct predictions the same master
  passes, so the failure is the reference and not the master.

- **Proof 4 — the advisory does not block.** A reel whose `target_dev` is large
  (an episode whose declared chain lands far from the common target) still passes
  `grade_faithful` when its own prediction matches. **Control:** the same reel
  with a genuinely unfaithful episode fails, so the advisory is not simply being
  ignored everywhere.

- **Proof 5 — the x264 entropy bias, measured.** Compute the entropy ratio twice
  for one graded episode: once from two renders (the shipped path) and once with
  the graded side read from the encoded clip via `assembly.frames_rgb`. Print both
  and assert the render-pair ratio is the higher of the two — that is the direction
  the design claims, and it is why both sides are renders. Record the magnitude in
  a `print` and in the test's docstring. **Control:** on an ungraded episode both
  readings are within 0.01 of each other and of 1.0.

- **Proof 6 — byte-identity.** An episode with no colour block renders to the same
  bytes as it did before this slice. Build it, hash it, and compare against a
  hash pinned in the test from a run on this commit's parent. **Control:** an
  episode WITH a colour block hashes differently, so the test can tell identity
  from a broken comparison.

**Implementer note:** write each of these as a real test function with real
assertions — the bullets above are the specification, not the code. Follow
`tests/integration/test_grade_shipped_pixels.py` for the house style of a proof
with a control; read it first. Proof 6 cannot compare against a pre-slice binary without checking out the parent
commit, which the Global Constraints forbid. Assert the honest weaker form
instead: the render of a manifest with NO colour block is byte-identical to the
render of `process_episode.plan_ungraded` of the SAME manifest WITH a colour block
— same pixels, two routes to them — and say in your report that the stronger
across-commits claim is untested.

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_grade_sensor_references.py -q -s`
Expected: PASS, with the measured numbers printed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_grade_sensor_references.py
git commit -m "test: six real-ffmpeg proofs, each with a control"
```

---

### Task 10: mutation battery, docs, version

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`,
  `docs/build-status.md`, `docs/pipeline-map.md`, `docs/backlog.md`
- Modify: `skills/process-episode/SKILL.md`, `skills/episode-qc/SKILL.md`,
  `skills/edit-plan/SKILL.md`, `skills/match-grade/SKILL.md`,
  `skills/using-montage/SKILL.md`

- [ ] **Step 1: Run the mutation battery**

Every row is a real edit, run under `PYTHONDONTWRITEBYTECODE=1`, restored
afterwards with `git diff` confirming a clean tree. A row that stays GREEN is a
coverage hole to close, not a row to delete.

| # | mutation | must go RED in |
|---|---|---|
| 1 | `gradedamage.ENTROPY_BINS` 256 → 64 | `test_gradedamage.py` (the quantization test) |
| 2 | `entropy` drops the `.clip(0, 255)` | `test_gradedamage.py` |
| 3 | `evaluate` returns the mean instead of the median | `test_gradedamage.py` |
| 4 | `evaluate` judges the raw ratio, not the rounded one | `test_evaluate_judges_the_rounded_ratio_it_reports` |
| 5 | `evaluate` returns `ratio >= floor` for `below` | `test_gradedamage.py` |
| 6 | `color.sample_times` uses `k/frames` instead of `(k+0.5)/frames` | `test_color.py` |
| 7 | `frames_rgb` puts the select BEFORE the chain (`plan.filter_args` edited directly instead of `with_tail`) | `test_frames_rgb_returns_DIFFERENT_frames_not_one_repeated` |
| 8 | `frames_rgb`'s size check becomes `len(raw) % want == 0` | `test_frames_rgb_refuses_a_short_buffer` |
| 9 | `plan_ungraded` forgets `strip_colour` | `test_process_episode_plans.py` |
| 10 | `plan_for` hardcodes `orch.DEFAULT_PARAMS["smooth_window_s"]` | `test_process_episode_plans.py` — **if GREEN, add a test** |
| 11 | `CheckSpec.entropy_floor` default 0.90 → 0.50 | `test_models.py` |
| 12 | `CheckSpec` accepts an `entropy_floor` above 1.0 | `test_models.py` |
| 13 | `_grade_damage` returns `passed=True` on `below` | `test_check_episode.py` |
| 14 | `_grade_damage` ignores `plans` and always reports not-checked | `test_check_episode.py` + Proof 1 |
| 15 | `process_episode` passes `plans=(rspec_plan, rspec_plan)` (same plan twice) | `test_process_episode.py` — **if GREEN, add a test**; the ratio would be exactly 1.0 always |
| 16 | `process_episode` builds the plain plan from `orch.DEFAULT_PARAMS` | `test_the_plain_plan_uses_the_ATTEMPT_S_params_not_the_defaults` |
| 17 | `_UNFIXABLE` drops `grade_damage` | `test_orchestration.py` |
| 18 | `ReelCheckSpec.grade_residual_max` default doubled | `test_models.py` |
| 19 | `_grade_faithful_check` skips episodes whose `tone_dst` is None (the old not-bound skip) | `test_grade_faithful_judges_EVERY_episode_not_only_the_bound_ones` |
| 20 | `_grade_faithful_check` compares against `tone_target` instead of `predicted` | `test_check_reel.py` + Proof 3 |
| 21 | `_grade_faithful_check` lets `target_dev` vote (`ok = ok and max(target_dev) <= max`) | `test_target_dev_is_advisory_and_only_for_bound_episodes` |
| 22 | `_grade_faithful_check` returns `passed=True` when `residuals` is empty | `test_check_reel.py` |
| 23 | `ReelFailure`'s stage becomes `"match-grade"` | `test_grade_faithful_fails_and_routes_to_process_episode` |
| 24 | `build_reel._predict` returns `[None] * n` unconditionally | `test_build_reel.py` + Proof 3 |
| 25 | `build_reel` drops `predicted=` from the `check_reel.run` call | `test_build_reel_forwards_one_prediction_per_episode` |
| 26 | `build_reel._predict` uses `md["segment"]` instead of `probe.source_for` | **expected GREEN** on a non-stabilized fixture — say so, and add a stabilized-episode test if one is cheap |
| 27 | `probe` reports `grade_damage` from the graded frames twice | `test_probe_grade_damage_agrees_with_check_episode_on_the_same_episode` |
| 28 | `episode_qc._source_reading` reverts to the whole segment frame | `test_source_reading_measures_the_source_IN_THE_EPISODE_S_CROP` |

- [ ] **Step 2: Record the battery's outcome**

Write the result — every row, RED or GREEN, and what was added to close each
GREEN — into the plan file under this task. A row expected GREEN must say so in
advance, as rows 26 does.

- [ ] **Step 3: Version bump**

`.claude-plugin/plugin.json` → `0.7.0`, and a matching `CHANGELOG.md` entry at the
top. `tests/test_plugin_manifests.py` enforces that they agree; the install path
is version-keyed, so an unbumped version lets a reinstall keep the old snapshot.

- [ ] **Step 4: Docs**

- `CHANGELOG.md` — a 0.7.0 entry naming both renames, both new references, the
  two measured constants, and the §2.1 demotion.
- `CLAUDE.md` — two new Quick Reference rows (design + plan), in the established
  voice: what changed, the load-bearing measurement, and the honest half.
- `docs/build-status.md` — a Done entry.
- `docs/pipeline-map.md` — the two renamed checks.
- `docs/backlog.md` — mark P1 rows 1 and 2 `✅`, mark the two P2 rows (`probe
  grade`, `naturalness.evaluate_delta`) `✅`, and add the design's four §10
  deferrals as new rows. **The slice is not finished until every §10 row has a
  backlog row** — that rule is why the backlog exists.
- Skills: `process-episode` and `episode-qc` name `color_fidelity`; `match-grade`,
  `edit-plan` and `using-montage` name `tone_match` or describe the convergence
  loop. Find every one with
  `grep -rn 'color_fidelity\|tone_match\|grade_delta_max' skills/ docs/`.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Report the final counts against the 3321/1 baseline and account
for the difference.

- [ ] **Step 6: Commit**

```bash
git add -- CHANGELOG.md .claude-plugin/plugin.json CLAUDE.md docs/ skills/ \
           docs/plans/2026-08-31-grade-sensor-references.md
git commit -m "docs: 0.7.0 — each colour gate gets a reference that admits the grade"
```

---

## Self-Review

**Spec coverage.** §1 → Tasks 4/6. §2 → Task 6. §2.1 → Task 6 (the rename, the
every-episode widen, the advisory `target_dev`). §3 → Tasks 0/4/5. §3.1 → Tasks
0/2/4/5. §4 → Proofs 1 and 3. §5 → Task 8. §6 → the File Structure table. §7 →
Task 9. §8 → nothing to build. §9 → Task 10's doc sync carries the limits
forward. §10 → Task 10, Step 4's backlog rows.

**Two thresholds, one source.** `entropy_floor` and `grade_residual_max` are both
produced by Task 3 and consumed as literals by Tasks 4 and 6. No later task may
invent one; Task 3's Step 4 forbids a surviving placeholder.

**Type consistency.** `plan_for`/`plan_ungraded` keep their names from Task 2
through Tasks 5, 7 and 8. `frames_rgb(plan, src, times)` keeps its argument order
everywhere. `gradedamage.evaluate(plain, graded, floor)` is called with the plain
frames FIRST in Tasks 4 and 8 — the ratio is graded ÷ plain, so a swapped call
inverts the sensor silently, and mutation row 27 is the closest thing to a guard.
The check keys are `grade_damage` (episode) and `grade_faithful` (reel), never
mixed.

**The weakest point is Task 9's Proof 6.** Byte-identity against a pre-slice
render cannot be asserted from inside the slice without checking out the parent
commit, which the Global Constraints forbid. The proof is stated in its honest
weaker form — two routes to the same ungraded pixels — and the implementer should
say plainly in their report that the stronger claim is not tested.

**One known-GREEN mutation row** (26) is declared in advance rather than
discovered, because the suite has no stabilized-episode fixture and building one
is a slice of its own.
