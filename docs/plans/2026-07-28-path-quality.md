# Reframe path-quality cluster — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** land the parked "pathsmooth smooth_window_s" bucket (design
[2026-07-28-path-quality-design.md](../specs/2026-07-28-path-quality-design.md)) —
three coupled fixes: **A** the savgol window in seconds not frames, **B** the
jitter check judged against the subject's own route, **C** an authored `lead`
honoured in `classify`'s ambiguous zone.

**Architecture:** a faithful port of the parked hunks from
`wip/montage-run-hardening` (`4841dd3`), colour half excluded (landed slice F),
grafted onto post-slice-F `main`. `smooth_window_s` is a retry knob (starts at
`DEFAULT_PARAMS`, the ladder tunes it), not an authored field. No `PathMeta`
provenance. No threshold re-derivation — every constant is field-measured.

**Tech Stack:** Python 3.13, pytest, scipy (savgol, already a dep), real-ffmpeg
golden fixtures. `pythonpath = .`; scripts run as modules; `.venv/bin/python`.

**Ground rules:**
- TDD every task: failing test → run-red → minimal impl → run-green → commit.
- Run tests with `.venv/bin/python -m pytest`.
- Every guard gets a **mutation check**: neutralize the guarded line, confirm a
  named test flips red, restore. The park's tests are the starting point, not the
  finish line — the sibling track-stitch port hid two coverage holes that only
  mutation surfaced.
- No golden fixture may move (design §7). Task 9 proves it.

---

## Task 0: pathsmooth — window in seconds

**Files:**
- Modify: `scripts/lib/pathsmooth.py`
- Test: `tests/lib/test_pathsmooth.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_pathsmooth.py` (top-of-file `import pytest` if absent):

```python
import pytest


def test_window_frames_preserves_the_historical_30fps_default():
    # DEFAULT_WINDOW = 7 was tuned at 30fps; the seconds-based default must land on it
    from scripts.lib import pathsmooth as ps
    assert ps.window_frames(ps.DEFAULT_WINDOW_S, 30.0) == ps.DEFAULT_WINDOW


def test_window_frames_doubles_on_60fps_footage():
    # 7 frames is 0.23s at 30fps but 0.12s at 60fps, so the same literal filters
    # half as much motion on the footage this repo actually gets
    from scripts.lib import pathsmooth as ps
    assert ps.window_frames(ps.DEFAULT_WINDOW_S, 59.94) == 15


def test_window_frames_is_always_odd_and_at_least_five():
    from scripts.lib import pathsmooth as ps
    for fps in (24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0, 120.0, 240.0):
        n = ps.window_frames(ps.DEFAULT_WINDOW_S, fps)
        assert n % 2 == 1 and n >= 5, (fps, n)


@pytest.mark.parametrize("seconds, fps", [(0.25, 0.0), (0.25, -1.0), (0.0, 30.0), (-0.1, 30.0)])
def test_window_frames_rejects_degenerate_input(seconds, fps):
    from scripts.lib import pathsmooth as ps
    with pytest.raises(ValueError):
        ps.window_frames(seconds, fps)
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_pathsmooth.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.pathsmooth' has no attribute 'window_frames'`.

- [ ] **Step 3: Implement**

In `scripts/lib/pathsmooth.py`, after the module docstring / imports and before
`_rate_limit`, add the constants and `window_frames`:

```python
DEFAULT_WINDOW = 7        # savgol frames — the pure function's own fallback
DEFAULT_WINDOW_S = 0.25   # ...and the width callers should actually ask for, IN SECONDS


def window_frames(seconds: float, fps: float) -> int:
    """An odd savgol window spanning `seconds` at `fps`.

    The window has to be specified in TIME, not frames, because it is a low-pass
    filter and its cutoff is a frequency. DEFAULT_WINDOW = 7 was tuned on 30fps
    footage, where it spans 0.23s; handed unchanged to a 60fps source it spans
    0.12s and filters half as much motion, which is exactly the regime this repo's
    drone and telephoto footage lives in. Measured across four 60fps rides, 7
    frames left the crop's 2nd difference at 2-4x the integer-crop floor and one
    episode failed the jitter check outright; the same 0.25s expressed as 15
    frames put all four ON the floor, for 1-3% of crop width in added lag.

    DEFAULT_WINDOW_S is chosen so a 30fps clip still resolves to 7 — the historical
    value is preserved exactly where it came from, and only the frame rates it was
    never tuned for change."""
    if fps <= 0:
        raise ValueError(f"window_frames needs a positive fps, got {fps!r} — "
                         "a window in seconds cannot be converted without one")
    if seconds <= 0:
        raise ValueError(f"window_frames needs a positive span, got {seconds!r}s — "
                         "pass window=1 to smooth() to skip savgol entirely")
    n = round(seconds * fps)
    if n % 2 == 0:                 # round DOWN to odd: 0.25s at 30fps is 7.5 -> 7,
        n -= 1                     # the historical default, not 9
    return max(5, n)               # savgol needs window > polyorder (2)
```

Then change the `smooth` signature default from the literal `7` to the constant:

```python
def smooth(raw: list[float], max_step: float, window: int | None = DEFAULT_WINDOW,
           polyorder: int = 2) -> list[float]:
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_pathsmooth.py -q`
Expected: PASS (existing smooth tests still pass — the default is unchanged in value).

- [ ] **Step 5: Mutation check**

Temporarily change `n -= 1` to `n += 1`; run
`test_window_frames_preserves_the_historical_30fps_default` — it must FAIL (9 ≠ 7).
Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/pathsmooth.py tests/lib/test_pathsmooth.py
git commit -m "feat: pathsmooth.window_frames — savgol window in seconds, 30fps→7"
```

---

## Task 1: ReframeSpec.smooth_window_s

**Files:**
- Modify: `scripts/lib/models.py` (`ReframeSpec`, ~line 616 and `__post_init__`)
- Test: `tests/lib/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_models.py`:

```python
def test_reframespec_smooth_window_s_defaults_to_quarter_second():
    from scripts.lib.models import ReframeSpec, Delivery
    s = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), delivery=Delivery())
    assert s.smooth_window_s == 0.25


@pytest.mark.parametrize("bad", [0, -0.1, 2.5, True])
def test_reframespec_rejects_bad_smooth_window_s(bad):
    from scripts.lib.models import ReframeSpec, Delivery
    with pytest.raises(ValueError, match="smooth_window_s"):
        ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), delivery=Delivery(),
                    smooth_window_s=bad)
```

(If `pytest` / `ReframeSpec` / `Delivery` are already imported at the top of the
file, drop the local imports and reuse them.)

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q -k smooth_window_s`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'smooth_window_s'`.

- [ ] **Step 3: Implement**

In `scripts/lib/models.py`, `class ReframeSpec`, add the field immediately after
`max_speed: float = 750.0`:

```python
    smooth_window_s: float = 0.25  # savgol span over the tracked path, IN SECONDS. max_speed
                              # caps how FAR the crop may move per frame; this sets over how
                              # long a wobble is averaged away. They are not interchangeable: a
                              # low-amplitude, high-frequency hitch (the jitter check's whole
                              # subject) already sits under any max_speed the ladder reaches,
                              # so damping speed cannot touch it. Seconds and not frames
                              # because it is a filter cutoff — see pathsmooth.window_frames,
                              # resolved against the clip's own fps at render time.
```

In `__post_init__`, after the `max_speed` validation block, add:

```python
        if (isinstance(self.smooth_window_s, bool)
                or not isinstance(self.smooth_window_s, (int, float))
                or not 0 < self.smooth_window_s <= 2.0):
            raise ValueError(
                f"ReframeSpec.smooth_window_s must be a span in seconds in (0, 2.0], got "
                f"{self.smooth_window_s!r} — it is a filter cutoff, and a window longer than "
                "a couple of seconds stops following the subject rather than smoothing it")
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReframeSpec.smooth_window_s — savgol span in seconds, (0, 2.0]"
```

---

## Task 2: orchestration — DEFAULT_PARAMS, SMOOTH_WINDOW_S_MAX, ladder

**Files:**
- Modify: `scripts/lib/orchestration.py` (`DEFAULT_PARAMS` ~124, `adjust_reframe_params` ~136)
- Test: `tests/lib/test_orchestration.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_orchestration.py` (module imports `orchestration as orch`):

```python
def test_jitter_fail_also_widens_the_smoothing_window():
    # the knob that actually reaches this failure: the jitter check fires on
    # low-amplitude reversals that sit under any max_speed the ladder reaches
    p = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["jitter"])
    assert p["smooth_window_s"] > orch.DEFAULT_PARAMS["smooth_window_s"]


def test_smoothing_window_ladder_is_bounded():
    p = dict(orch.DEFAULT_PARAMS)
    for _ in range(20):
        p = orch.adjust_reframe_params(p, ["jitter"])
    assert p["smooth_window_s"] == orch.SMOOTH_WINDOW_S_MAX


def test_line_lag_narrows_the_window_but_never_below_the_default():
    wide = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["jitter"])
    back = orch.adjust_reframe_params(wide, ["on_line"])
    assert back["smooth_window_s"] < wide["smooth_window_s"]
    assert back["smooth_window_s"] >= orch.DEFAULT_PARAMS["smooth_window_s"]


def test_adjust_fills_a_partial_params_dict():
    # a caller that only knows about max_speed still gets both knobs back
    p = orch.adjust_reframe_params({"max_speed": 750.0}, ["jitter"])
    assert set(p) == set(orch.DEFAULT_PARAMS)
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q -k "smoothing_window or widens or narrows or partial"`
Expected: FAIL — `KeyError: 'smooth_window_s'` / `AttributeError: ... SMOOTH_WINDOW_S_MAX`.

- [ ] **Step 3: Implement**

In `scripts/lib/orchestration.py`, replace the `DEFAULT_PARAMS` line:

```python
DEFAULT_PARAMS = {"max_speed": 750.0,             # px/s (§6.1: 25 px/frame @30fps)
                  "smooth_window_s": 0.25}        # savgol span, seconds (pathsmooth.DEFAULT_WINDOW_S)

SMOOTH_WINDOW_S_MAX = 0.7   # past this the crop stops following the subject at all and
                            # lags visibly through a real direction change
```

Replace `adjust_reframe_params`:

```python
def adjust_reframe_params(params: dict[str, float], fail_reasons: list[str]) -> dict[str, float]:
    """One documented nudge per mechanical fail (§4.1 retry-in-place).

    A partial `params` is filled from DEFAULT_PARAMS first, so a caller that knows
    about one knob still gets a complete, nudgeable set back rather than a KeyError
    on the knob it had never heard of."""
    p = {**DEFAULT_PARAMS, **params}
    if _lags_line(fail_reasons):
        p["max_speed"] = p["max_speed"] * 1.5      # crop lags the line → catch up
        # a wide window is exactly what makes the crop lag, so give it back the
        # responsiveness the same way it was taken — never below the default
        p["smooth_window_s"] = max(DEFAULT_PARAMS["smooth_window_s"],
                                   p["smooth_window_s"] / 2)
    if "jitter" in fail_reasons:
        p["max_speed"] = p["max_speed"] * 0.6      # crop too twitchy → damp harder
        # …and widen the averaging window, which is the knob that actually reaches
        # this failure. max_speed caps the SIZE of a step; the jitter check fires on
        # low-amplitude reversals that are already far under any speed cap the ladder
        # reaches, so speed alone never converges — measured on a 60fps drone ride:
        # 3 attempts of 750→450→270 px/s left worst_reversal unchanged at 4.0px.
        p["smooth_window_s"] = min(SMOOTH_WINDOW_S_MAX, p["smooth_window_s"] * 2)
    return p
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q`
Expected: PASS (existing `max_speed` ladder tests still pass — those factors are unchanged).

- [ ] **Step 5: Mutation check**

Change `min(SMOOTH_WINDOW_S_MAX, ...)` to `max(...)`; run
`test_smoothing_window_ladder_is_bounded` — it must FAIL (unbounded growth).
Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/orchestration.py tests/lib/test_orchestration.py
git commit -m "feat: retry ladder tunes smooth_window_s (jitter widens, line-lag narrows)"
```

---

## Task 3: checks — route-aware jitter

**Files:**
- Modify: `scripts/lib/checks.py` (`jitter` ~line 34)
- Test: `tests/lib/test_checks.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_checks.py` (module imports `checks as ck`, `import pytest`):

```python
def _route(xs):
    return [{"x": float(x), "y": 0.0} for x in xs]


def test_jitter_forgives_the_subject_s_own_backtrack():
    # a surfer carving back up the wave: the crop reverses because the SUBJECT did.
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 90, 130])       # subject moved exactly the same way
    assert ck.jitter(path, "right", max_reversal=10)["pass"] is False        # no route: fails
    assert ck.jitter(path, "right", max_reversal=10, route=route)["pass"] is True


def test_jitter_still_fails_chatter_over_a_smooth_subject():
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 130, 140])      # subject never went backwards
    assert ck.jitter(path, "right", max_reversal=10, route=route)["pass"] is False


def test_jitter_fails_the_excess_beyond_the_subject_s_backtrack():
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 115, 130])      # subject reversed 5, crop reversed 30
    res = ck.jitter(path, "right", max_reversal=10, route=route)
    assert res["pass"] is False
    assert res["worst_reversal"] == 25


def test_jitter_route_window_filters_detector_noise_not_subject_motion():
    subj = [100 + 2 * i for i in range(40)]
    noise = [(6 if i % 2 else -6) for i in range(40)]
    route = _route([s + n for s, n in zip(subj, noise)])
    path = [s + n for s, n in zip(subj, noise)]          # crop copies the noise verbatim
    assert ck.jitter(path, "right", 3.0, route=route)["pass"] is True     # blind
    assert ck.jitter(path, "right", 3.0, route=route, route_window=5)["pass"] is False


def test_jitter_route_window_lets_a_smooth_crop_pass_over_a_noisy_route():
    subj = [100 + 2 * i for i in range(40)]
    route = _route([s + (6 if i % 2 else -6) for i, s in enumerate(subj)])
    assert ck.jitter(subj, "right", 3.0, route=route, route_window=5)["pass"] is True


def test_jitter_route_window_of_one_is_the_historical_behaviour():
    path = [100, 110, 120, 90, 130]
    route = _route([100, 110, 120, 90, 130])
    assert (ck.jitter(path, "right", 10, route=route)
            == ck.jitter(path, "right", 10, route=route, route_window=1))


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, None])
def test_jitter_rejects_a_bad_route_window(bad):
    with pytest.raises(ValueError, match="route_window"):
        ck.jitter([100, 110], "right", 10, route=_route([100, 110]), route_window=bad)


def test_jitter_reports_reversal_count():
    path = [100, 110, 105, 115, 110]               # two reversals
    res = ck.jitter(path, "right", max_reversal=10)
    assert res["reversals"] == 2
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q -k jitter`
Expected: FAIL — `TypeError: jitter() got an unexpected keyword argument 'route'`.

- [ ] **Step 3: Implement**

In `scripts/lib/checks.py`, add `_moving_average` before `jitter`, then replace
`jitter` entirely:

```python
def _moving_average(xs: list[float], window: int) -> list[float]:
    """Centred box filter, shrinking at the ends so length is preserved. Pure —
    checks.py stays free of scipy."""
    if window <= 1:
        return list(xs)
    half, n = window // 2, len(xs)
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        out.append(sum(xs[a:b]) / (b - a))
    return out


def jitter(path: list[int], direction: str, max_reversal: float,
           route: list[dict[str, float]] | None = None,
           route_window: int = 1) -> dict:
    """Crop-centre reversal against the direction of travel — the §9 "rounding
    flicker" guard.

    With `route`, the SUBJECT'S OWN counter-motion is subtracted first. Without it
    this is the only composition check that judges the path in a vacuum (centered/
    on_line both score path AGAINST route), and it therefore cannot tell a crop
    chattering over a smooth subject from a crop faithfully following a surfer who
    carves back up the wave: a noiseless route weaving +-150px scores worst=6 while
    on_line is still 0.919. `direction` comes from motion.classify, which reduces a
    whole episode to route[0] vs route[-1], so every honest frame of counter-motion
    is scored as jitter.

    Subtracting only the NEGATIVE part of the subject's own step keeps the check
    honest: a crop that chatters over a smoothly-moving subject still fails (the
    route contributes nothing to subtract), and a crop that reverses further or
    faster than the subject still fails, by the excess. Only the reversal the
    subject actually performed is forgiven — which is what "following" means.
    A generated pan passes `route=None`/[] and keeps the historical behaviour.

    `route_window` box-filters the route before differencing, and is the difference
    between measuring the SUBJECT and measuring the DETECTOR. A raw route carries
    per-frame bbox noise of the same amplitude as the defect, so subtracting it
    frame-to-frame cancels perfectly for a path that copies that noise and cancels
    not at all for a path that filters it — i.e. the check scores an unsmoothed,
    visibly juddering crop BEST. Measured on a 60fps drone ride: the raw path (2nd
    difference p95 = 8.9 output px, the judder you can see) scored worst_reversal
    0.94 and passed, while a smoothed path at the 1-px quantization floor scored
    4.00 and failed. Filtering the route over ~0.08s inverts both verdicts to match
    what is on screen. 1 (the default) is the historical frame-to-frame behaviour;
    check_episode derives the real window from the route's own cadence.
    """
    if direction not in ("left", "right"):
        raise ValueError(f"jitter: direction must be 'left' or 'right', got {direction!r}")
    if isinstance(route_window, bool) or not isinstance(route_window, int) or route_window < 1:
        raise ValueError(f"jitter: route_window must be an integer >= 1 frame, "
                         f"got {route_window!r}")
    sign = 1 if direction == "right" else -1
    worst = 0.0
    reversals = 0
    use_route = bool(route) and len(route) >= len(path)
    rx = _moving_average([p["x"] for p in route], route_window) if use_route else []
    for i in range(1, len(path)):
        step = (path[i] - path[i - 1]) * sign      # forward = positive
        if use_route:
            subj = (rx[i] - rx[i - 1]) * sign
            step -= min(0.0, subj)                 # forgive only the subject's own backtrack
        if step < 0:
            worst = max(worst, -step)
            if step < -1:
                reversals += 1
    return {"pass": worst <= max_reversal, "worst_reversal": worst,
            "reversals": reversals}
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q`
Expected: PASS (existing vacuum-jitter tests still pass — `route=None` is unchanged).

- [ ] **Step 5: Mutation check**

Change `step -= min(0.0, subj)` to `step -= subj`; run
`test_jitter_fails_the_excess_beyond_the_subject_s_backtrack` — it must FAIL
(forgiving the subject's *forward* motion would wrongly pass). Restore.

**Correction (2026-07-29, Task 9 final sweep):** this pairing is INEFFECTIVE —
the named fixture's reversing frame coincides with the subject's own
backtrack, so `min(0.0, subj)` and the mutated `subj` agree there and
`worst_reversal` stays 25 either way; the test does not flip red. The
guard's effective test is
`test_jitter_does_not_invent_a_reversal_when_the_crop_lags_a_forward_subject`
(added in a follow-up commit), which uses a monotonically-forward crop
lagging a faster forward subject — the case only the `min(0.0, ...)` clamp
protects.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/checks.py tests/lib/test_checks.py
git commit -m "feat: jitter subtracts the subject's own backtrack, box-filtered (route-aware)"
```

---

## Task 4: motion.travel_direction

**Files:**
- Modify: `scripts/lib/motion.py`
- Test: `tests/lib/test_motion.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_motion.py` (module imports `motion as m`):

```python
def test_travel_direction_reads_net_dx():
    from scripts.lib.motion import travel_direction
    right = [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]
    left = [dict(t=i / 30, x=1500 - i * 90, y=500, w=140, h=320) for i in range(10)]
    assert travel_direction(right) == "right"
    assert travel_direction(left) == "left"


def test_travel_direction_defaults_to_right_without_travel():
    from scripts.lib.motion import travel_direction
    assert travel_direction([]) == "right"
    assert travel_direction([dict(t=0.0, x=5.0, y=0.0, w=1.0, h=1.0)]) == "right"
    flat = [dict(t=i / 30, x=500.0, y=0.0, w=1.0, h=1.0) for i in range(5)]
    assert travel_direction(flat) == "right"
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_motion.py -q -k travel_direction`
Expected: FAIL — `ImportError: cannot import name 'travel_direction'`.

- [ ] **Step 3: Implement**

Append to `scripts/lib/motion.py`:

```python
def travel_direction(route: list[dict[str, float]]) -> str:
    """Which way the subject NET travels, whatever `classify` called the shot.

    `classify` answers "what kind of shot is this", and returns no direction for
    head-on/static — including the ambiguous zone above, which a subject can enter
    only when |dx| is LARGE. So the shot type can be undecided while the direction
    is not, and a composition the author explicitly asked for still needs one.

    One spelling, two readers: reframe.compute_path lays the crop out against it and
    check_episode scores the result against it. If they derived it separately they
    could disagree on a left-moving subject — the crop leading one way and the check
    grading the other line — and the report would be wrong about a correct render.
    An empty/1-point route has no travel; "right" matches classify's own default.
    """
    if len(route) < 2:
        return "right"
    return "right" if route[-1]["x"] - route[0]["x"] >= 0 else "left"
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_motion.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/motion.py tests/lib/test_motion.py
git commit -m "feat: motion.travel_direction — net-dx sign, one spelling for two readers"
```

---

## Task 5: orchestration — lead honoured when the subject travels

**Files:**
- Modify: `scripts/lib/orchestration.py` (import block; `detect_contradictions` lead gate ~99)
- Test: `tests/lib/test_orchestration.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_orchestration.py`. If a `_route_right()` helper is not
already present in the file, add the small helper too:

```python
def _diagonal():
    """Crosses the frame AND grows toward the camera — classify's ambiguous zone,
    which answers "static" even though |dx| is 30% of frame width."""
    return [dict(t=i / 60, x=855 + 579 * i / 59, y=300,
                 w=116 + 21 * i / 59, h=149 + 240 * i / 59) for i in range(60)]


def test_lead_is_allowed_when_the_subject_travels_even_if_classify_says_static():
    from scripts.lib.motion import classify
    route = _diagonal()
    assert classify(route, 1920, 1080)[0] == "static"          # the premise
    findings = orch.detect_contradictions(motion=None, route=route,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert not any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_is_still_refused_when_the_subject_does_not_travel():
    parked = [dict(t=i / 60, x=900 + i * 0.2, y=300, w=120, h=300) for i in range(60)]
    findings = orch.detect_contradictions(motion=None, route=parked,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert any(f["reason"] == "composition-motion-mismatch" for f in findings)


def test_lead_over_a_plain_lateral_shot_is_unchanged():
    right = [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]
    findings = orch.detect_contradictions(motion=None, route=right,
                                          track_meta={"ambiguous": False},
                                          src_w=1920, src_h=1080, composition="lead")
    assert not any(f["reason"] == "composition-motion-mismatch" for f in findings)
```

(If the file already defines `_route_right()`, use it in the third test instead of
the inline `right`.)

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q -k "lead_is_allowed or lead_is_still"`
Expected: FAIL — the diagonal shot currently produces a `composition-motion-mismatch`
finding (`classify` says static → the old gate refuses).

- [ ] **Step 3: Implement**

In `scripts/lib/orchestration.py`, add the import above `from scripts.lib.motion import classify`:

```python
from scripts.lib import motion as motion_mod
```

Replace the `if composition == "lead":` gate:

```python
    if composition == "lead":
        obs_type, _ = classify(route, src_w, src_h)
        # `lead` needs somewhere to lead TO, which is net travel — not the shot label.
        # classify answers "what kind of shot", and its ambiguous zone (a subject that
        # crosses the frame AND grows toward the camera — a surfer on a beach-side
        # telephoto) reports "static" while |dx| is LARGE. reframe.compute_path honours
        # an authored lead there, taking the direction from that same travel, so
        # refusing here would block a composition the renderer can now actually deliver.
        # A subject that genuinely does not travel still has no direction to lead into,
        # and is still refused — measured by the one threshold classify itself uses.
        travels = (len(route) >= 2
                   and abs(route[-1]["x"] - route[0]["x"]) >= motion_mod.LATERAL_FRAC * src_w)
        if obs_type != "lateral" and not travels:
            findings.append({"reason": "composition-motion-mismatch",
                             "detail": f"composition 'lead' needs somewhere to lead to, but the "
                                       f"subject's net travel is under "
                                       f"{motion_mod.LATERAL_FRAC:.0%} of frame width and the "
                                       f"tracker sees {obs_type} — set composition to 'center' "
                                       f"or 'break', or fix the window/segment"})
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q`
Expected: PASS (existing lead-mismatch tests over genuinely non-travelling routes
still fail-and-report, unchanged).

- [ ] **Step 5: Mutation check**

Change `and not travels` to `and False` (i.e. never refuse); run
`test_lead_is_still_refused_when_the_subject_does_not_travel` — it must FAIL.
Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/orchestration.py tests/lib/test_orchestration.py
git commit -m "feat: lead gate allows an authored lead when the subject net-travels"
```

---

## Task 6: reframe.compute_path — smooth_window param + lead-from-travel

**Files:**
- Modify: `scripts/reframe.py` (import ~line 8; `compute_path` 13–33)
- Test: `tests/lib/test_reframe.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_reframe.py`:

```python
def _diagonal_route(n=60, x0=855.0, x1=1434.0):
    """The measured shape of a surfer riding ACROSS and TOWARD a beach-side telephoto:
    dx is 30% of frame width (lateral needs 15%) AND the box grows 3.1x (head-on needs
    1.6x), so motion.classify lands in its ambiguous zone and answers "static"."""
    return [dict(t=i / 60, x=x0 + (x1 - x0) * i / (n - 1), y=300.0,
                 w=116 + 21 * i / (n - 1), h=149 + 240 * i / (n - 1)) for i in range(n)]


def test_classify_calls_the_diagonal_shot_static():
    from scripts.lib.motion import classify
    assert classify(_diagonal_route(), 1920, 1080) == ("static", None)


def test_authored_lead_is_honoured_when_the_shot_classifies_static():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    lead = compute_path(route, "lead", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=12.5, crop_w=497)
    centred = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_w=497)
    assert lead != centred
    mid = len(route) // 2
    assert abs((route[mid]["x"] - lead[mid]) / 497 - 1 / 3) < 0.02


def test_authored_lead_takes_its_direction_from_the_route():
    from scripts.reframe import compute_path
    right = _diagonal_route()
    left = _diagonal_route(x0=1434.0, x1=855.0)
    mid = len(right) // 2
    pr = compute_path(right, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_w=497)
    pl = compute_path(left, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_w=497)
    assert abs((right[mid]["x"] - pr[mid]) / 497 - 1 / 3) < 0.02   # travelling right
    assert abs((left[mid]["x"] - pl[mid]) / 497 - 2 / 3) < 0.02    # travelling left


def test_break_and_center_still_ignore_the_direction_rescue():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    a = compute_path(route, "break", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_w=497)
    b = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_w=497)
    assert a == b


def test_smooth_window_reaches_the_smoother():
    # a wider savgol window must visibly change the path over a noisy route —
    # proves the new parameter is actually threaded into pathsmooth.smooth
    from scripts.reframe import compute_path
    route = [dict(t=i / 60, x=900 + (30 if i % 2 else -30), y=500, w=140, h=320)
             for i in range(40)]
    tight = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                         ("static", None), max_step=99, crop_w=497, smooth_window=5)
    wide = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=99, crop_w=497, smooth_window=21)
    assert tight != wide
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -q`
Expected: FAIL — `test_authored_lead_is_honoured...` (currently renders centred) and
`test_smooth_window_reaches_the_smoother` (`compute_path` has no `smooth_window`
kwarg → `TypeError`).

- [ ] **Step 3: Implement**

In `scripts/reframe.py`, change the motion import (line ~8):

```python
from scripts.lib.motion import classify, travel_direction as classify_direction
```

Replace `compute_path` (13–33) with:

```python
def compute_path(route: list[dict[str, float]], composition: str, grid: str,
                 canvas: tuple[int, int], src: tuple[int, int],
                 motion: tuple[str, str | None], max_step: float,
                 crop_w: int, smooth_window: int = pathsmooth.DEFAULT_WINDOW) -> list[int]:
    # crop_w comes from the resolved layout — the caller already cut it; deriving
    # it from `canvas` here would be right only while every layout is `fill`.
    kind, direction = motion if motion[0] == "lateral" else (motion[0], "right")
    if composition == "lead" and kind != "lateral" and len(route) >= 2:
        # motion.classify refuses to call a shot lateral when the subject ALSO grows
        # toward the camera — its "ambiguous zone", which falls through to static
        # deliberately because a centred crop is the SAFE framing when nobody said
        # otherwise. A surfer riding across the frame and toward a beach-side telephoto
        # is exactly that shape: measured on one, dx was 30% of frame width (lateral
        # needs 15%) and the box grew 3.1x (head-on needs 1.6x), so the shot was called
        # static and the authored `lead` silently rendered as `center`.
        #
        # Picking a safe default for an unstated intent is not the same as VETOING a
        # stated one, and quietly substituting a different composition is the class of
        # silent swap this repo refuses everywhere else. So honour the request and take
        # the direction from the route's own net travel — the one thing the ambiguous
        # zone never made ambiguous (it enters that zone only when |dx| is LARGE).
        kind, direction = "lateral", classify_direction(route)
    if composition in ("center", "break") or kind != "lateral":
        # center / head-on / static: aim crop centre at subject, no lead.
        # break (spec §6.2): tracked but relaxed — v1 center-tracks; extreme
        # framing is editorial territory, checks are editorial-only.
        raw = [g.clamp(round(pt["x"] - crop_w / 2), 0, src[0] - crop_w)
               for pt in route]
    else:
        raw = [g.crop_x(pt["x"], composition, direction, grid, crop_w, src[0])
               for pt in route]
    smoothed = pathsmooth.smooth(raw, max_step=max_step, window=smooth_window)
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame.
    # At zero freedom (crop_w == src_w) this clamps to a constant 0 — a
    # whole-frame layout has nowhere to travel, and needs no special case.
    return [int(g.clamp(round(x), 0, src[0] - crop_w)) for x in smoothed]
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py tests/integration/test_reframe.py -q`
Expected: PASS (the integration `compute_path` tests still pass — `break`/`center`
and plain `lateral` are unchanged; the default `smooth_window` equals the old
literal).

- [ ] **Step 5: Mutation check**

Change `kind, direction = "lateral", classify_direction(route)` to `pass`; run
`test_authored_lead_is_honoured_when_the_shot_classifies_static` — it must FAIL
(`lead == centred`). Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/reframe.py tests/lib/test_reframe.py
git commit -m "feat: compute_path honours an authored lead in the ambiguous zone; smooth_window param"
```

---

## Task 7: check_episode — route-aware jitter + direction from travel

**Files:**
- Modify: `scripts/check_episode.py` (import ~8; add `_route_window` ~66; direction ~149; jitter call ~189)
- Test: `tests/integration/test_check_episode.py` (unit part of `_route_window` is pure; add there or a `tests/lib/test_check_episode.py` if the repo has one)

- [ ] **Step 1: Write the failing tests**

Find where `check_episode` is tested (`git ls-files | grep check_episode` — likely
`tests/integration/test_check_episode.py`). Add a pure unit test for the new
helper (no ffmpeg needed):

```python
def test_route_window_derives_from_the_route_s_own_cadence():
    import scripts.check_episode as ce
    # 60fps route → ROUTE_SMOOTH_S (0.08s) spans ~5 frames
    route = [{"t": i / 60, "x": 100.0, "y": 0.0} for i in range(30)]
    assert ce._route_window(route) == round(29 / (29 / 60) * 0.08)   # == 5
    # 30fps → ~2 frames
    slow = [{"t": i / 30, "x": 100.0, "y": 0.0} for i in range(30)]
    assert ce._route_window(slow) == max(1, round(29 / (29 / 30) * 0.08))


def test_route_window_is_one_for_degenerate_routes():
    import scripts.check_episode as ce
    assert ce._route_window([]) == 1
    assert ce._route_window([{"t": 0.0, "x": 1.0, "y": 0.0}]) == 1
    # zero elapsed time → 1
    assert ce._route_window([{"t": 0.0, "x": 1.0, "y": 0.0},
                             {"t": 0.0, "x": 2.0, "y": 0.0}]) == 1
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest <that file> -q -k route_window`
Expected: FAIL — `AttributeError: module 'scripts.check_episode' has no attribute '_route_window'`.

- [ ] **Step 3: Implement**

In `scripts/check_episode.py`, extend the motion import:

```python
from scripts.lib.motion import classify, travel_direction
```

Add the constant + helper before `def run(` (after `_black_frames_check`):

```python
ROUTE_SMOOTH_S = 0.08     # the span over which a crop reversal becomes visible (~5 frames @60fps)


def _route_window(route: list[dict]) -> int:
    """Frames spanning ROUTE_SMOOTH_S at the route's OWN cadence — see checks.jitter
    on why the route is filtered before it is differenced. Derived from the route's
    timestamps rather than an ffprobe fps: the route is what is being filtered, and a
    gappy or resampled one has a cadence of its own that the container never states.
    Degenerate input (too few points, or no elapsed time) → 1, the historical
    frame-to-frame behaviour, which is exactly right when there is nothing to filter."""
    if len(route) < 2:
        return 1
    span = route[-1]["t"] - route[0]["t"]
    if span <= 0:
        return 1
    return max(1, round((len(route) - 1) / span * ROUTE_SMOOTH_S))
```

Change the tracked-branch direction default (currently `direction = direction or "right"`):

```python
        _, direction = classify(route, src_w, src_h)
        # static/head-on routes carry no direction of their own. reframe does NOT
        # centre in that case when the author asked for `lead` — it lays the crop out
        # against the route's net travel (see compute_path) — so scoring against a
        # fixed "right" would grade the wrong line for a left-moving subject and
        # report a correct render as broken. Same helper, same answer, both sides.
        direction = direction or travel_direction(route)
```

Change the jitter call (currently one line):

```python
    # route is [] under a pan (there is no observation), so a generated path keeps
    # the historical vacuum-judged behaviour; a tracked one gets the subject's own
    # counter-motion discounted (see checks.jitter).
    dj = checks_mod.jitter(path, direction, max_reversal=max(2.0, crop_w * 0.005),
                           route=route or None, route_window=_route_window(route))
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/integration/test_check_episode.py -q`
Expected: PASS (the `meta.pan` branch still passes `route=[]` → historical jitter).

- [ ] **Step 5: Mutation check**

Change `direction or travel_direction(route)` to `direction or "right"`; add/confirm
a test that a **left-moving** diagonal route (classify → static) is graded on the
`right` grid-line and thus reports the correct render as broken — it must flip. If
no such integration test exists yet, add a minimal one over the real `sample_clip`;
otherwise rely on Task 9's end-to-end left-lead proof. Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_episode.py tests/integration/test_check_episode.py
git commit -m "feat: check_episode route-aware jitter + lead direction from net travel"
```

---

## Task 8: thread the resolved window through the shell

**Files:**
- Modify: `scripts/reframe.py` (`reframe()` compute_path call ~410)
- Modify: `scripts/process_episode.py` (ReframeSpec build ~308; pan comment ~346)
- Test: `tests/integration/test_reframe.py`

- [ ] **Step 1: Write the failing test**

The wiring cannot be caught on a 30fps clip (`window_frames(0.25, 30) == 7 ==` the
old default) or a frozen route (a constant smooths to itself). Prove it directly:
spy on `compute_path` and assert `reframe()` hands it
`window_frames(spec.smooth_window_s, fps)` — 15 at 60fps. Add to
`tests/integration/test_reframe.py`:

```python
@pytest.mark.integration
def test_reframe_passes_the_fps_resolved_window_to_compute_path(tmp_path, monkeypatch):
    import json, subprocess
    from scripts.lib import models, ffbin, pathsmooth
    from scripts import reframe as rf
    captured = {}
    real = rf.compute_path
    def spy(*a, **k):
        captured["smooth_window"] = k.get("smooth_window")
        return real(*a, **k)
    monkeypatch.setattr(rf, "compute_path", spy)
    src = tmp_path / "s60.mp4"
    subprocess.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
                    "-i", "color=c=gray:s=1920x1080:d=1:r=60", "-pix_fmt", "yuv420p",
                    str(src)], check=True)
    route = [dict(t=i / 60, x=960.0, y=540.0, w=140.0, h=320.0) for i in range(60)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137),
                              delivery=models.Delivery.from_spec("exact:1080x1920"),
                              smooth_window_s=0.25)
    rf.reframe(spec, str(src), str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert captured["smooth_window"] == pathsmooth.window_frames(0.25, 60.0) == 15
```

- [ ] **Step 2: Run — verify red**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py -q -k passes_the_fps_resolved`
Expected: FAIL — `reframe()` still calls `compute_path` without a `smooth_window`
kwarg, so `captured["smooth_window"]` is `None`, not 15.

- [ ] **Step 3: Implement**

In `scripts/reframe.py`, `reframe()`, update the `compute_path` call:

```python
        path = compute_path(route_dicts, spec.composition, spec.grid, spec.canvas,
                            (src_w, src_h), motion, max_step=spec.max_speed / fps,
                            crop_w=rl.crop_w,
                            smooth_window=pathsmooth.window_frames(
                                spec.smooth_window_s, fps))
```

In `scripts/process_episode.py`, add `smooth_window_s` to the `ReframeSpec` built in
the retry loop (after `max_speed=params["max_speed"],`):

```python
                            max_speed=params["max_speed"],
                            smooth_window_s=float(params["smooth_window_s"]),
```

Update the `pan-not-retryable` comment block to name both knobs:

```python
            # The retry ladder tunes max_speed and smooth_window_s, via
            # adjust_reframe_params. For a tracked path those are the damper and
            # the averaging span. For a generated one smooth_window_s is not read
            # at all (generate_pan_path never smooths) and max_speed is only the
            # speed CEILING, so a retry re-renders byte-identical pixels — three
            # identical ffmpeg passes ending in "max-retries", a reason that
            # describes nothing.
```

- [ ] **Step 4: Run — verify green**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py tests/integration/test_process_episode.py -q`
Expected: PASS — including the frozen-route resolves-window test.

- [ ] **Step 5: Commit**

```bash
git add scripts/reframe.py scripts/process_episode.py tests/integration/test_reframe.py
git commit -m "feat: reframe resolves smooth_window from seconds; process_episode threads the ladder knob"
```

---

## Task 9: full suite + golden immunity + mutation battery + docs sync

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-28-path-quality-design.md` (Status line).

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Record the counts (before this slice the suite was ~1897 passed / 2
skipped; expect the new unit + integration tests on top).

- [ ] **Step 2: Golden-immunity confirmation**

No golden may move (design §7). Check: `git status --porcelain tests/` shows no
modified fixture / `*.json`. If any golden changed, STOP — investigate the fps of
that fixture; the byte-identical claim is violated and must be understood before
landing.

- [ ] **Step 3: Mutation battery (teeth confirmation)**

For each, apply the mutation, run the named test, confirm RED, then restore:
1. `pathsmooth.window_frames`: `n -= 1` → `n += 1` ⇒ `test_window_frames_preserves_the_historical_30fps_default`.
2. `orchestration`: `min(SMOOTH_WINDOW_S_MAX, ...)` → `max(...)` ⇒ `test_smoothing_window_ladder_is_bounded`.
3. `checks.jitter`: `step -= min(0.0, subj)` → `step -= subj` ⇒ `test_jitter_fails_the_excess_beyond_the_subject_s_backtrack`.
4. `checks._moving_average`: return `list(xs)` unconditionally (drop the filter) ⇒ `test_jitter_route_window_filters_detector_noise_not_subject_motion`.
5. `reframe.compute_path`: the lead-rescue assignment → `pass` ⇒ `test_authored_lead_is_honoured_when_the_shot_classifies_static`.
6. `orchestration` lead gate: `and not travels` → `and False` ⇒ `test_lead_is_still_refused_when_the_subject_does_not_travel`.
7. `check_episode`: `direction or travel_direction(route)` → `direction or "right"` ⇒ the left-lead grading test (Task 7 Step 5); if it was deferred there, add it now over `sample_clip` with a left-moving diagonal route.
8. `reframe` (Task 8): remove the `smooth_window=window_frames(...)` kwarg ⇒ `test_reframe_passes_the_fps_resolved_window_to_compute_path`.

- [ ] **Step 4: Docs sync**

- `docs/build-status.md` — DONE entry for the path-quality cluster (smooth_window_s +
  route-aware jitter + lead-from-travel), final suite count, "no golden moved",
  campaign progress (2nd parked bucket landed).
- `docs/pipeline-map.md` — note the smoothing window is fps-resolved, the jitter check
  route-aware, the lead composition honoured in the ambiguous zone.
- `CLAUDE.md` — two Quick Reference rows for the design + plan, house-style hooks.
- design Status line → "landed 2026-07-28 (feat/path-quality)".

- [ ] **Step 5: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/registry for the path-quality cluster"
```

---

## Self-review notes

- **Spec coverage:** A (Tasks 0,1,2,6,8), B (Tasks 3,7), C (Tasks 4,5,6,7). Every
  §3 file appears; every §4 invariant has a test (0/1/2/3/6 fast paths; 6+7 two-
  readers; 3+9 A↔B coupling; 2 ladder bounds).
- **No placeholders:** every code step carries the actual code.
- **Type consistency:** `smooth_window_s` (float, seconds) vs `smooth_window`
  (int, frames) — the seconds→frames boundary is `pathsmooth.window_frames`, used
  only in `reframe()` (Task 8). `travel_direction` is imported as `classify_direction`
  in `reframe.py` and plainly in `check_episode.py`/`motion.py` — same function.
- **Ordering:** foundational pure functions first (0,3,4), specs/ladder (1,2,5),
  then the two shells that consume them (6,7,8), then the full-suite + golden-immunity
  + mutation battery + docs gate (9). Ten tasks, 0–9.
