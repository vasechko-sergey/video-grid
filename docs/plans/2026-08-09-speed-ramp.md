# Speed Ramp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make slow-mo a first-class EDL knob whose added time propagates through every length consumer, so a ramped reel's beat grid is fitted to what the viewer actually watches.

**Architecture:** A `RampSpec` config-spec (models.py) + a pure `lib/ramp.py` (cosine speed profile, `O(t)=∫1/s` as knots, the `setpts` expression, the judder gate) + a retime **pre-stage in `extract`** that replaces `ep{i}_raw.mp4` in place, so tracking and reframe both see the retimed pixels. `EDLEpisode.play_dur()` becomes the truthful length, and the seven readers listed in design §6 switch to it.

**Tech Stack:** Python 3.13, pytest, ffmpeg (`setpts` + `fps` filters via `lib/proc.run`), no new dependencies.

**Design:** [docs/specs/2026-08-09-speed-ramp-design.md](../specs/2026-08-09-speed-ramp-design.md) — read §2 (the enclosure rule), §3 (the render), §6 (the seven sites) before starting.

## Global Constraints

- **`RAMP_EASE_KNOTS = 16`** and **`MIN_RAMP_FPS = 24.0`** — exact values, named constants in `scripts/lib/ramp.py`, never inlined.
- **Knots are anchored to the ramp region, never spread evenly across the window** (design §3.2). Evenly spaced knots make the approximated `ramp_extra` drift with `dur` (measured: 3.3 ms for the reference spec, 124 ms on a short ease), which silently breaks §2's constancy claim and with it `_bind_pacing`'s subtraction.
- **Never import `subprocess`.** Every ffmpeg call goes through `scripts.lib.proc.run`, and every binary through `scripts.lib.ffbin.ffmpeg()`. An AST scan enforces both; adding a fourth `subprocess` importer breaks the landmine lint's chokepoint (design §0).
- **A filtergraph value containing a comma MUST be single-quoted inside the `-vf` string** (design §10). In argv form nothing strips shell quotes, and ffmpeg treats a bare comma as a filter separator.
- **`setpts` must always be followed by `fps=`** (design §10) — alone it produces a VFR stream that `assembly.concat`'s uniformity check rejects.
- **Refuse, never clamp.** Every out-of-range value raises `ValueError` naming the value, the bound, and the remedy. No waiver exists for the judder gate (governance #8).
- **`bool` is checked BEFORE `int`** in every numeric validator — `isinstance(True, int)` is `True`, so `{"factor": true}` would silently mean `1.0`.
- **No `float()` coercion in validators.** `json.loads` builds arbitrary-precision ints and `float()` raises `OverflowError`, not `ValueError`, which escapes soft gates as a crash. Compare int-vs-float directly; it is exact and rejects `NaN`.
- **An episode with `ramp: null` must be byte-identical to before this slice** — same argv, same segment bytes. The golden fixtures depend on it.
- **Do NOT port** `apply_zoom` / `validate_zoom` / `ZOOM_MIN` / `ZOOM_MAX` / `highlight_red` / `EDLEpisode.smooth_window_s` / the `draft.py` `Delivery.dims` fix from `wip/montage-run-patches` (design §9).
- Scripts run as modules: `PYTHONPATH` is the repo root (`pythonpath = .` in pytest config). Python is `.venv/bin/python`.
- Tests: whole-object asserts where practical; real ffmpeg for anything claiming pixels moved.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/lib/models.py` | `RampSpec` config-spec beside `ZoomSpec`/`PanSpec` | 0 |
| `scripts/lib/ramp.py` (new) | speed profile, knots, `ramp_extra`, `setpts` expression, window + judder gates, `retime` | 1, 3 |
| `scripts/lib/edl.py` | `EDLEpisode.ramp`, the enclosure refusal, `play_dur()`, `to_dict`, `to_markdown`, `to_manifest_dict` | 2, 6 |
| `scripts/extract.py` | the retime pre-stage, in place | 3 |
| `scripts/pacing.py` | fit the grid to played lengths; the shrink floor | 4 |
| `scripts/edit_plan.py` | binding guard + assignment, back-edge target, the early judder gate | 5 |
| `scripts/edl_to_reel.py` | the reel target sum | 6 |
| `tests/lib/test_ramp.py` (new) | pure-core unit tests | 1 |
| `tests/integration/test_ramp.py` (new) | real-ffmpeg length + visibility + byte-identity proofs | 7, 8 |

---

### Task 0: `RampSpec` config-spec

**Files:**
- Modify: `scripts/lib/models.py` (add after `ZoomSpec`, which ends at the `LAYOUT_MODES = (...)` line)
- Test: `tests/lib/test_models.py`

**Interfaces:**
- Produces: `models.RampSpec(at: float, factor: float, ease: float, hold: float)`, frozen-style dataclass with `to_dict() -> dict` and `from_dict(d: dict) -> RampSpec`. Wire keys are `at`/`factor`/`ease`/`hold` — unlike `ZoomSpec`/`PanSpec` there is no keyword clash, so field names and wire names are identical.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_rampspec_round_trips_through_the_wire_form():
    d = {"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}
    assert models.RampSpec.from_dict(d).to_dict() == d


def test_rampspec_holds_its_four_numbers():
    s = models.RampSpec(at=2.0, factor=0.4, ease=0.5, hold=1.0)
    assert (s.at, s.factor, s.ease, s.hold) == (2.0, 0.4, 0.5, 1.0)


def test_rampspec_accepts_a_zero_hold_pure_vee():
    assert models.RampSpec(at=1.0, factor=0.5, ease=0.4, hold=0.0).hold == 0.0


def test_rampspec_accepts_factor_one_as_a_no_op_ramp():
    # factor 1.0 is degenerate but well-formed: extra becomes 0.0. Refusing it
    # here would make `factor` the only field whose legal range excludes its
    # own identity value, and ramp_extra already reports 0.0 truthfully.
    assert models.RampSpec(at=1.0, factor=1.0, ease=0.3, hold=0.0).factor == 1.0


@pytest.mark.parametrize("field,value", [
    ("at", -0.1), ("factor", 0.0), ("factor", 1.1), ("ease", 0.0),
    ("ease", -0.5), ("hold", -0.1),
])
def test_rampspec_refuses_out_of_range(field, value):
    kw = {"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0, field: value}
    with pytest.raises(ValueError, match=f"RampSpec.{field}"):
        models.RampSpec(**kw)


@pytest.mark.parametrize("field", ["at", "factor", "ease", "hold"])
def test_rampspec_refuses_a_bool_before_int(field):
    # isinstance(True, int) is True — without the bool check first, {"factor": true}
    # would silently mean 1.0.
    kw = {"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0, field: True}
    with pytest.raises(ValueError, match=f"RampSpec.{field}"):
        models.RampSpec(**kw)


def test_rampspec_refuses_a_non_object():
    with pytest.raises(ValueError, match="expected an object"):
        models.RampSpec.from_dict([2.0, 0.4, 0.5, 1.0])


def test_rampspec_names_every_missing_key_at_once():
    with pytest.raises(ValueError, match="missing ease, hold"):
        models.RampSpec.from_dict({"at": 2.0, "factor": 0.4})
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k rampspec -v`
Expected: FAIL, `AttributeError: module 'scripts.lib.models' has no attribute 'RampSpec'`

- [x] **Step 3: Implement**

Insert into `scripts/lib/models.py` immediately after `ZoomSpec.from_dict` and before `LAYOUT_MODES = ("fill", "fit", "insert")`:

```python
@dataclass(frozen=True)
class RampSpec:
    """A speed ramp: playback eases down to a slow plateau around one moment and
    back up (design 2026-08-09). The pro "hit the drop in slow-mo" move, rather
    than slowing a whole shot.

    All four numbers are seconds or a plain multiplier, and all times are
    relative to the EPISODE WINDOW's start, not the clip's:

      at     — the plateau's centre
      factor — minimum speed; 0.4 means 2.5x slower. A literal multiplier for the
               same reason ZoomSpec took literal from/to: the wire format states
               the quantity the filter uses, and the SKILL documents the reading.
      ease   — the cosine ramp-in and ramp-out, seconds EACH side
      hold   — the plateau's own length at `factor`

    The region [at - hold/2 - ease, at + hold/2 + ease] must lie inside the
    window, but THAT rule is not checked here — it needs the window length, which
    only EDLEpisode has. See ramp.validate_window, called from
    EDLEpisode.__post_init__. This spec validates only what is checkable from the
    four numbers alone.

    factor > 1 (speed-UP) is deliberately out of range: the whole design rests on
    s <= 1 meaning frames are only ever DUPLICATED, never dropped, so no motion is
    lost. Dropping motion needs a different argument and is deferred (design §13).
    """
    at: float
    factor: float
    ease: float
    hold: float

    def __post_init__(self) -> None:
        bounds = (("at", self.at, "seconds from the WINDOW start"),
                  ("factor", self.factor, "minimum speed in (0, 1]; "
                   "0.4 is 2.5x slower"),
                  ("ease", self.ease, "seconds of cosine ramp EACH side"),
                  ("hold", self.hold, "plateau seconds at `factor`"))
        for name, v, meaning in bounds:
            # bool BEFORE int: isinstance(True, int) is True, so {"factor": true}
            # would otherwise silently mean 1.0
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(
                    f"RampSpec.{name} must be a number — {meaning}; got {v!r}")
        # NO float(): json.loads builds ints of any size and float() raises
        # OverflowError, not ValueError, escaping the soft manifest gate as a
        # crash. Direct comparison is exact and rejects NaN too. Same landmine
        # ZoomSpec and PanSpec document.
        if not self.at >= 0.0:
            raise ValueError(
                f"RampSpec.at must be >= 0 — it is seconds from the WINDOW start, "
                f"not the clip's; got {self.at!r}")
        if not 0.0 < self.factor <= 1.0:
            raise ValueError(
                f"RampSpec.factor must be within (0.0, 1.0] — the plateau's minimum "
                f"speed, where 0.4 is 2.5x slower and 1.0 is no slowdown. Above 1.0 "
                f"would be a speed-UP, which DROPS frames rather than duplicating "
                f"them and is a different feature; got {self.factor!r}")
        if not self.ease > 0.0:
            raise ValueError(
                f"RampSpec.ease must be > 0 — an instant change of speed is a jump "
                f"cut, not a ramp. Give it at least a few frames; got {self.ease!r}")
        if not self.hold >= 0.0:
            raise ValueError(
                f"RampSpec.hold must be >= 0 — the plateau's length; 0 is a pure "
                f"V-shape that touches `factor` for one instant; got {self.hold!r}")

    def to_dict(self) -> dict:
        return {"at": self.at, "factor": self.factor,
                "ease": self.ease, "hold": self.hold}

    @classmethod
    def from_dict(cls, d: dict) -> "RampSpec":
        if not isinstance(d, dict):
            raise ValueError(
                f"RampSpec.from_dict: expected an object with at/factor/ease/hold, "
                f"got {type(d).__name__} — write ramp as "
                f'{{"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}}')
        missing = [k for k in ("at", "factor", "ease", "hold") if k not in d]
        if missing:
            raise ValueError(
                f"RampSpec.from_dict: missing {', '.join(missing)} — a ramp needs "
                f"all four of at/factor/ease/hold, got {sorted(d)}")
        return cls(at=d["at"], factor=d["factor"], ease=d["ease"], hold=d["hold"])
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k rampspec -v`
Expected: PASS — every test in the selection green

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat(models): RampSpec — the speed ramp's four numbers"
```

---

### Task 1: `lib/ramp.py` — the pure core

**Files:**
- Create: `scripts/lib/ramp.py`
- Test: `tests/lib/test_ramp.py` (new)

**Interfaces:**
- Consumes: `models.RampSpec` (Task 0).
- Produces, all pure:
  - `RAMP_EASE_KNOTS: int = 16`, `MIN_RAMP_FPS: float = 24.0`
  - `speed_at(t: float, spec: RampSpec) -> float`
  - `knots(spec: RampSpec, dur: float) -> tuple[list[float], list[float]]` — `(ts, O)`, equal length, **variable** (≈36 for a full-shape ramp; fewer when a segment is zero-width)
  - `ramp_extra(spec: RampSpec | None, dur: float) -> float`
  - `setpts_expr(spec: RampSpec, dur: float) -> str`
  - `tail_room(spec: RampSpec | None, dur: float) -> float`
  - `max_factor(fps: float) -> float`
  - `validate_window(spec: RampSpec, dur: float, where: str) -> None`
  - `require_playable(spec: RampSpec, fps: float, where: str) -> None`

- [x] **Step 1: Write the failing tests**

Create `tests/lib/test_ramp.py`:

```python
import math

import pytest

from scripts.lib import ramp
from scripts.lib.models import RampSpec

SPEC = RampSpec(at=2.0, factor=0.4, ease=0.5, hold=1.0)   # region [1.0, 3.0]
DUR = 4.0


def test_speed_is_exactly_one_outside_the_region():
    assert ramp.speed_at(0.0, SPEC) == 1.0
    assert ramp.speed_at(0.99, SPEC) == 1.0
    assert ramp.speed_at(3.01, SPEC) == 1.0
    assert ramp.speed_at(DUR, SPEC) == 1.0


def test_speed_is_exactly_factor_across_the_plateau():
    for t in (1.5, 2.0, 2.5):
        assert ramp.speed_at(t, SPEC) == pytest.approx(0.4)


def test_the_ease_is_monotonic_and_meets_both_ends():
    # cosine ease: 1.0 at the region edge, `factor` at the plateau edge, and
    # strictly decreasing between. The midpoint is the arithmetic mean.
    assert ramp.speed_at(1.0, SPEC) == pytest.approx(1.0)
    assert ramp.speed_at(1.25, SPEC) == pytest.approx(0.7)
    assert ramp.speed_at(1.5, SPEC) == pytest.approx(0.4)
    xs = [ramp.speed_at(1.0 + 0.05 * i, SPEC) for i in range(11)]
    assert all(a >= b for a, b in zip(xs, xs[1:]))


def test_knots_span_the_window_and_start_at_zero():
    ts, o = ramp.knots(SPEC, DUR)
    assert len(ts) == len(o)
    assert ts[0] == 0.0 and ts[-1] == pytest.approx(DUR)
    assert o[0] == 0.0


def test_knots_are_anchored_to_the_region_not_spread_evenly():
    # design §3.2: the flats and the plateau each get ONE interval (the trapezoid
    # is exact on a constant), and every subdivision is spent inside an ease.
    ts, _o = ramp.knots(SPEC, DUR)          # region [1.0, 3.0], plateau [1.5, 2.5]
    for boundary in (0.0, 1.0, 1.5, 2.5, 3.0, 4.0):
        assert any(abs(t - boundary) < 1e-9 for t in ts), f"{boundary} not a knot"
    # nothing between 0.0 and the region start, or across the plateau
    assert not [t for t in ts if 1e-9 < t < 1.0 - 1e-9]
    assert not [t for t in ts if 1.5 + 1e-9 < t < 2.5 - 1e-9]
    assert len(ts) == 2 * ramp.RAMP_EASE_KNOTS + 4


def test_knots_drop_zero_width_segments():
    # hold=0 collapses the plateau; a region flush with the window collapses a flat
    ts, _o = ramp.knots(RampSpec(at=2.0, factor=0.5, ease=2.0, hold=0.0), 4.0)
    assert len(ts) == len(set(ts)), "a duplicated knot means a zero-width interval"
    assert ts[0] == 0.0 and ts[-1] == pytest.approx(4.0)
    assert len(ts) == 2 * ramp.RAMP_EASE_KNOTS + 1   # both flats and the plateau gone


def test_output_time_is_strictly_increasing():
    _ts, o = ramp.knots(SPEC, DUR)
    assert all(b > a for a, b in zip(o, o[1:]))


def test_ramp_extra_matches_an_independent_simpson_integration():
    def simpson(f, a, b, n=20000):
        h = (b - a) / n
        s = f(a) + f(b)
        for i in range(1, n):
            s += (4 if i % 2 else 2) * f(a + i * h)
        return s * h / 3

    lo, hi = SPEC.at - SPEC.hold / 2, SPEC.at + SPEC.hold / 2
    ease_int = simpson(lambda t: 1.0 / ramp.speed_at(t, SPEC), lo - SPEC.ease, lo)
    exact = ((lo - SPEC.ease) + ease_int + (hi - lo) / SPEC.factor + ease_int
             + (DUR - (hi + SPEC.ease))) - DUR
    # anchored knots converge to machine precision — the cosine ease's derivative
    # vanishes at both ends, so Euler-Maclaurin's correction terms all die and the
    # trapezoid rule converges exponentially rather than as O(h^2) (design §3.2).
    assert ramp.ramp_extra(SPEC, DUR) == pytest.approx(exact, abs=1e-9)


def test_ramp_extra_is_zero_without_a_ramp():
    assert ramp.ramp_extra(None, DUR) == 0.0


def test_ramp_extra_is_bit_identical_across_window_lengths():
    # design §2: with the region enclosed, the extra is CONSTANT in dur, and §3.2's
    # anchored knots make that true of the APPROXIMATION too, not just the exact
    # integral. This is what makes _bind_pacing's `dur = slot.dur - extra` exact.
    # Evenly spaced knots fail this by 3.3ms and would corrupt every bound length.
    vals = {ramp.ramp_extra(SPEC, d) for d in (3.5, 4.0, 6.0, 9.0)}
    assert len(vals) == 1, f"extra drifts with the window length: {sorted(vals)}"


def test_a_factor_of_one_adds_no_time():
    assert ramp.ramp_extra(RampSpec(at=1.0, factor=1.0, ease=0.3, hold=0.0),
                           3.0) == pytest.approx(0.0, abs=1e-9)


def test_tail_room_is_the_gap_between_the_region_end_and_the_window_end():
    assert ramp.tail_room(SPEC, DUR) == pytest.approx(1.0)   # region ends at 3.0
    assert ramp.tail_room(None, DUR) == DUR


def test_setpts_expr_reconstructs_the_same_knots_it_was_built_from():
    # The expression is piecewise-linear THROUGH the knots, so evaluating it at a
    # knot must return that knot's own value — record and render agree by
    # construction (design §3.3).
    ts, o = ramp.knots(SPEC, DUR)
    expr = ramp.setpts_expr(SPEC, DUR)
    for t, want in zip(ts, o):
        assert _eval_expr(expr, t) == pytest.approx(want, abs=1e-5)


def test_setpts_expr_is_single_valued_and_needs_no_shell_quoting_itself():
    # It contains commas (inside if(lt(...))) — the CALLER must single-quote it
    # inside the -vf string (design §10). The expression itself carries no quotes,
    # so it can be embedded without escaping.
    expr = ramp.setpts_expr(SPEC, DUR)
    assert "," in expr
    assert "'" not in expr and '"' not in expr


def test_max_factor_is_the_floor_over_the_source_rate():
    assert ramp.max_factor(60.0) == pytest.approx(0.4)
    assert ramp.max_factor(30.0) == pytest.approx(0.8)


def test_require_playable_accepts_exactly_the_floor():
    ramp.require_playable(RampSpec(at=1.0, factor=0.4, ease=0.3, hold=0.2),
                          60.0, "ep0")   # 60 * 0.4 == 24.0 exactly


def test_require_playable_refuses_below_the_floor_and_names_the_remedy():
    spec = RampSpec(at=1.0, factor=0.5, ease=0.3, hold=0.2)
    with pytest.raises(ValueError) as ei:
        ramp.require_playable(spec, 30.0, "ep0")
    msg = str(ei.value)
    assert "ep0" in msg and "15.0 unique frames" in msg and "0.8" in msg


def test_validate_window_accepts_a_region_flush_with_both_edges():
    ramp.validate_window(RampSpec(at=2.0, factor=0.5, ease=1.0, hold=2.0),
                         4.0, "ep0")   # region exactly [0.0, 4.0]


def test_validate_window_refuses_a_region_starting_before_the_window():
    with pytest.raises(ValueError, match="starts 0.30s before"):
        ramp.validate_window(RampSpec(at=0.5, factor=0.5, ease=0.5, hold=0.6),
                             4.0, "ep0")


def test_validate_window_refuses_a_region_running_past_the_window():
    with pytest.raises(ValueError, match="ends 0.50s past"):
        ramp.validate_window(SPEC, 2.5, "ep0")   # region ends 3.0, window 2.5


def _eval_expr(expr: str, t: float) -> float:
    """Evaluate one of ffmpeg's `if(lt(T,a),b,c)` expressions in Python, for tests.

    ffmpeg's `if` and `lt` are ordinary function calls and the rest is arithmetic,
    so binding those two names plus `T` is enough — no parsing. `if` is a Python
    keyword, hence the rename; `if(` appears nowhere else in the expression."""
    env = {"_if": lambda c, a, b: a if c else b,
           "lt": lambda a, b: a < b, "T": t}
    return float(eval(expr.replace("if(", "_if("),   # noqa: S307 - test-only
                      {"__builtins__": {}}, env))
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_ramp.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scripts.lib.ramp'`

- [x] **Step 3: Implement**

Create `scripts/lib/ramp.py`:

```python
"""Speed-ramp arithmetic and the one-pass retime (design 2026-08-09).

A ramp eases playback down to a slow plateau around one moment and back up,
instead of slowing a whole shot. The speed profile s(t) over WINDOW-relative
source time is 1.0 outside the region, a cosine ease into `factor`, `factor`
across the plateau, and a cosine ease back out.

Output time is O(t) = the integral of 1/s from 0 to t — monotonic because s > 0,
and >= t because s <= 1. `out_dur = O(dur)`, so the time the ramp ADDS is
`O(dur) - dur`, which this module reports as `ramp_extra`.

Because s <= 1, the retime only ever DUPLICATES source frames and never drops
one: no motion is lost, and the price is that unique detail is not gained either
(see MIN_RAMP_FPS below).

The SAME knots serve the record and the render (design §3.3): `ramp_extra` reads
the last value of `knots()`, `setpts_expr` emits all of them. Integrating finely
here while the filter approximated coarsely would put a silent ~16ms lie in every
EDL.
"""
from __future__ import annotations

import math

from scripts.lib import ffbin, proc
from scripts.lib.models import RampSpec

RAMP_EASE_KNOTS = 16  # subdivisions per EASE. Not per window: the knots are anchored to
                    # the ramp region (design §3.2), so `ramp_extra` comes out bit-identical
                    # at every window length rather than drifting 3.3ms with it, and the
                    # flats and plateau — where 1/s is constant and the trapezoid exact —
                    # spend no knots at all. 16 reaches machine precision because the
                    # cosine ease's derivative vanishes at both ends, killing every
                    # Euler-Maclaurin correction term; measured, the value stops moving
                    # between 8 and 16 (delta 1.4e-10) and is float noise beyond.
MIN_RAMP_FPS = 24.0  # unique frames per second the plateau must keep. Slowing
                     # DUPLICATES frames, so the plateau shows `fps * factor` distinct
                     # frames per second; below the film rate that reads as stutter.
                     # A convention, not a measurement against this engine's footage
                     # (design §12) — the constant here most likely to want revisiting.

_CRF = 8            # near-lossless intermediate. NOT a default worth relaxing: a held
                    # slow-mo frame is later ENLARGED by a tight hero crop in reframe,
                    # which magnifies intermediate compression into visible whitewater
                    # macroblocks. crf 18 was measured too lossy for that
                    # second-generation crop.
_WINDOW_TOL = 1e-9  # s of float slack when comparing the region against the window
_FPS_TOL = 1e-6     # so 60.0 * 0.4 == 24.0 passes rather than losing to a float hair


def speed_at(t: float, spec: RampSpec) -> float:
    """Playback speed at WINDOW-relative source time `t`. 1.0 is normal."""
    half = spec.hold / 2.0
    lo, hi = spec.at - half, spec.at + half
    if lo <= t <= hi:
        p = 1.0
    elif lo - spec.ease <= t < lo:
        p = (t - (lo - spec.ease)) / spec.ease
    elif hi < t <= hi + spec.ease:
        p = 1.0 - (t - hi) / spec.ease
    else:
        p = 0.0
    # p is progress into the slowdown: 0 = normal, 1 = plateau. The cosine makes
    # the speed's own derivative zero at both ends, so the ramp has no visible
    # corner where it starts or stops.
    return 1.0 + (spec.factor - 1.0) * (1.0 - math.cos(math.pi * p)) / 2.0


def knots(spec: RampSpec, dur: float) -> tuple[list[float], list[float]]:
    """`(ts, O)` — the sample times and the trapezoid integral of 1/s at each.

    Knots are ANCHORED TO THE RAMP REGION, not spread evenly across the window
    (design §3.2), and both consequences matter:

    Every knot's position is fixed by the spec alone, so `ramp_extra` comes out
    bit-identical at any `dur` — which is what §2 promises and what
    _bind_pacing's subtraction spends. Evenly spaced knots slide relative to the
    eases as `dur` changes and drift by milliseconds.

    And the two flats plus the plateau hold 1/s CONSTANT, where the trapezoid rule
    is exact, so a single interval covers each and every subdivision is spent on
    the only curved parts. Zero-width segments are dropped.

    ONE source for both the recorded length and the rendered filter — see the
    module docstring."""
    lo, hi = spec.at - spec.hold / 2.0, spec.at + spec.hold / 2.0
    a, b = lo - spec.ease, hi + spec.ease          # the region's own edges
    ts = [0.0]
    if a > _WINDOW_TOL:                            # the flat before the ramp
        ts.append(a)
    ts += [a + spec.ease * k / RAMP_EASE_KNOTS     # ease-in, last point is `lo`
           for k in range(1, RAMP_EASE_KNOTS + 1)]
    if hi - lo > _WINDOW_TOL:                      # the plateau (absent when hold == 0)
        ts.append(hi)
    ts += [hi + spec.ease * k / RAMP_EASE_KNOTS    # ease-out, last point is `b`
           for k in range(1, RAMP_EASE_KNOTS + 1)]
    if dur - b > _WINDOW_TOL:                      # the flat after the ramp
        ts.append(dur)
    ts = sorted(set(ts))
    inv = [1.0 / speed_at(t, spec) for t in ts]
    out = [0.0]
    for i in range(1, len(ts)):
        out.append(out[-1] + (inv[i - 1] + inv[i]) * 0.5 * (ts[i] - ts[i - 1]))
    return ts, out


def ramp_extra(spec: RampSpec | None, dur: float) -> float:
    """Seconds the ramp ADDS to a `dur`-long window: `O(dur) - dur`. 0.0 with no ramp.

    Pure and fps-independent, so EDLEpisode.play_dur can call it without probing.

    With the region enclosed in the window (validate_window, design §2) this is
    CONSTANT in `dur` — outside the region the speed is exactly 1, so lengthening
    the window lengthens O by the same amount. That constancy is what lets
    edit_plan._bind_pacing invert the relation with one subtraction."""
    if spec is None:
        return 0.0
    return knots(spec, dur)[1][-1] - dur


def tail_room(spec: RampSpec | None, dur: float) -> float:
    """Seconds the window may shrink from its END before eating into the ramp
    region. The whole window without a ramp. Used by pacing._bounds so the beat
    fit cannot cut a shot while it is still slowed."""
    if spec is None:
        return dur
    return dur - (spec.at + spec.hold / 2.0 + spec.ease)


def max_factor(fps: float) -> float:
    """The slowest `factor` a `fps`-rate source supports under MIN_RAMP_FPS."""
    return MIN_RAMP_FPS / fps


def validate_window(spec: RampSpec, dur: float, where: str) -> None:
    """Refuse a ramp whose region pokes outside its window (design §2).

    Three things ride on the enclosure: `ramp_extra` becomes independent of `dur`
    (so the pacing inversion is a subtraction, not a solver); `tail_room` becomes
    well-defined; and editorially, a cut landing while the shot is still slowed —
    a ramp that never returns to speed — is a visible artefact, not a style."""
    head = spec.at - spec.hold / 2.0 - spec.ease
    tail = dur - (spec.at + spec.hold / 2.0 + spec.ease)
    if head < -_WINDOW_TOL:
        raise ValueError(
            f"{where}: the ramp region starts {-head:.2f}s before the window does "
            f"(at={spec.at:g}, hold={spec.hold:g}, ease={spec.ease:g} put its start at "
            f"{head:.2f}s). A ramp must begin and end inside its own window. Move `at` "
            f"later, or shorten `ease`/`hold`")
    if tail < -_WINDOW_TOL:
        raise ValueError(
            f"{where}: the ramp region ends {-tail:.2f}s past the {dur:.2f}s window "
            f"(at={spec.at:g}, hold={spec.hold:g}, ease={spec.ease:g} put its end at "
            f"{spec.at + spec.hold / 2.0 + spec.ease:.2f}s). The cut would land while the "
            f"shot is still slowed. Move `at` earlier, shorten `ease`/`hold`, or lengthen "
            f"the window")


def require_playable(spec: RampSpec, fps: float, where: str) -> None:
    """Refuse a ramp that would render as stutter (design §5). No waiver."""
    unique = fps * spec.factor
    if unique < MIN_RAMP_FPS - _FPS_TOL:
        raise ValueError(
            f"{where}: ramp factor {spec.factor:g} on a {fps:g} fps source leaves "
            f"{unique:.1f} unique frames per second on the plateau, under the "
            f"{MIN_RAMP_FPS:g} fps floor. Slowing DUPLICATES frames — it cannot create "
            f"detail that was never shot — so this renders as visible stutter. The "
            f"slowest this clip supports is factor {max_factor(fps):.3g}; a deeper ramp "
            f"needs footage shot at a higher frame rate")


def setpts_expr(spec: RampSpec, dur: float) -> str:
    """O(t) as a piecewise-linear ffmpeg expression of `T`, through `knots`.

    The same nested `if(lt(...))` shape reframe._xexpr uses for the zoom's crop
    path. O has no elementary closed form (the cosine ease makes it
    the integral of dt/(a + b*cos t)), so knots are how it reaches the filter.

    Contains commas and NO quotes: the caller must wrap it in single quotes inside
    the -vf string, or ffmpeg's parser reads the first comma as a filter separator
    (design §10)."""
    ts, o = knots(spec, dur)
    expr = f"{o[-1]:.6f}"
    for i in range(len(ts) - 2, -1, -1):
        slope = (o[i + 1] - o[i]) / (ts[i + 1] - ts[i])
        expr = (f"if(lt(T,{ts[i + 1]:.6f}),"
                f"{o[i]:.6f}+{slope:.6f}*(T-{ts[i]:.6f}),{expr})")
    return expr
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_ramp.py -v`
Expected: PASS — every test in the file green

- [x] **Step 5: Commit**

```bash
git add scripts/lib/ramp.py tests/lib/test_ramp.py
git commit -m "feat(ramp): the pure core — speed profile, knots, extra, gates"
```

---

### Task 2: `EDLEpisode.ramp`, the enclosure refusal, and `play_dur()`

**Files:**
- Modify: `scripts/lib/edl.py` (field block near `zoom`; `__post_init__`; `to_dict`; `EDL.to_markdown`)
- Test: `tests/lib/test_edl.py`

**Interfaces:**
- Consumes: `ramp.validate_window`, `ramp.ramp_extra`, `models.RampSpec`.
- Produces: `EDLEpisode.ramp: dict | None`, `EDLEpisode.play_dur() -> float`. Every later task calls `play_dur()`, never `dur`, when it means screen time.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py` (reuse the module's existing episode-building helper if one exists; otherwise this literal):

```python
def _ep(**kw):
    base = dict(source="a.mp4", start=0.0, dur=4.0, shot_type="medium",
                composition="thirds", grid="thirds")
    return edl.EDLEpisode(**{**base, **kw})


RAMP = {"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}


def test_play_dur_equals_dur_without_a_ramp():
    ep = _ep()
    assert ep.play_dur() == ep.dur == 4.0


def test_play_dur_adds_the_ramps_time():
    ep = _ep(ramp=RAMP)
    assert ep.play_dur() > ep.dur
    assert ep.play_dur() == pytest.approx(4.0 + ramp.ramp_extra(
        RampSpec.from_dict(RAMP), 4.0))


def test_a_ramp_round_trips_through_to_dict():
    assert _ep(ramp=RAMP).to_dict()["ramp"] == RAMP


def test_no_ramp_serializes_as_null():
    assert _ep().to_dict()["ramp"] is None


def test_an_episode_refuses_a_ramp_running_past_its_window():
    # region ends at 3.0s; the window is only 2.5s
    with pytest.raises(ValueError, match="ends 0.50s past"):
        _ep(dur=2.5, ramp=RAMP)


def test_an_episode_refuses_a_ramp_starting_before_its_window():
    with pytest.raises(ValueError, match="starts 0.30s before"):
        _ep(ramp={"at": 0.5, "factor": 0.5, "ease": 0.5, "hold": 0.6})


def test_an_episode_refuses_a_malformed_ramp_object():
    with pytest.raises(ValueError, match="missing ease, hold"):
        _ep(ramp={"at": 2.0, "factor": 0.4})


def test_shrinking_a_ramped_episode_into_its_region_raises_on_replace():
    # dataclasses.replace re-runs __post_init__, so the pacing binding cannot
    # quietly cut a window down into a ramp it no longer contains.
    import dataclasses
    ep = _ep(ramp=RAMP)
    with pytest.raises(ValueError, match="ends 1.00s past"):
        dataclasses.replace(ep, dur=2.0)


def test_the_markdown_total_counts_played_time_not_source_time():
    e = edl.EDL(episodes=[_ep(ramp=RAMP)])
    played = e.episodes[0].play_dur()
    assert f"{played:.1f}s" in e.to_markdown()
    assert "4.0s" not in e.to_markdown().splitlines()[0]


def test_the_markdown_row_reports_the_ramp_and_its_played_length():
    row = edl.EDL(episodes=[_ep(ramp=RAMP)]).to_markdown()
    assert "ramp x2.5" in row and "@2.0s" in row
```

Add to that file's imports: `from scripts.lib import ramp` and `from scripts.lib.models import RampSpec`.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -k "ramp or play_dur" -v`
Expected: FAIL, `TypeError: EDLEpisode.__init__() got an unexpected keyword argument 'ramp'`

- [x] **Step 3: Implement**

In `scripts/lib/edl.py`, add to the imports:

```python
from scripts.lib import ramp as ramp_mod
from scripts.lib.models import COMPOSITIONS, GRIDS, MOTIONS, RampSpec
```

(keep whatever the existing `models` import line already names; add `RampSpec` to it.)

Add the field directly after `zoom`:

```python
    ramp: dict | None = None  # {"at": s, "factor": f, "ease": s, "hold": s} — a speed
                              # ramp eased around one moment (design 2026-08-09).
                              # UNLIKE `pan`/`zoom` this IS validated here, and
                              # deliberately: the region-fits-the-window rule needs
                              # `dur`, which only this class has, and play_dur() must be
                              # safe to call from anywhere. RampSpec covers the four
                              # numbers; ramp.validate_window covers the window.
```

In `__post_init__`, immediately after the `stabilize` check:

```python
        if self.ramp is not None:
            ramp_mod.validate_window(
                RampSpec.from_dict(self.ramp), self.dur,
                f"EDLEpisode {self.source} @{self.start:.2f}s")
```

In `to_dict`, extend the `"stabilize"` line:

```python
                "stabilize": self.stabilize, "ramp": self.ramp,
```

Add the method after `to_dict`:

```python
    def play_dur(self) -> float:
        """How long this episode PLAYS, against `dur`'s how much SOURCE it consumes.

        Equal without a ramp — which is why the codebase managed with one word for
        both until now. The truthful authority for the beat-grid fit, the pacing
        binding, the per-episode length check and the reel length gate (design §1,
        §6). Anything measuring screen time calls this; anything measuring footage
        consumed keeps reading `dur`."""
        if self.ramp is None:
            return self.dur
        return self.dur + ramp_mod.ramp_extra(RampSpec.from_dict(self.ramp), self.dur)
```

In `EDL.to_markdown`, change the total and the row's notes:

```python
        total = sum(e.play_dur() for e in self.episodes)
```

and inside the row loop, just before the `lines.append(...)`:

```python
            notes = e.processing_notes
            if e.ramp is not None:
                notes = (f"⏱ ramp x{1 / e.ramp['factor']:.1f} @{e.ramp['at']:.1f}s "
                         f"(plays {e.play_dur():.2f}s) · {notes}").rstrip(" ·")
```

and use `notes` in place of `e.processing_notes` in the appended row.

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -v`
Expected: PASS, no previously-passing test broken

- [x] **Step 5: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat(edl): EDLEpisode.ramp + play_dur() + the enclosure refusal"
```

---

### Task 3: `ramp.retime` and the extract pre-stage

**Files:**
- Modify: `scripts/lib/ramp.py` (add `retime`), `scripts/extract.py` (`extract_edl`)
- Test: `tests/lib/test_ramp.py`, `tests/lib/test_extract.py` (create if absent)

**Interfaces:**
- Consumes: `setpts_expr`, `require_playable` (Task 1); `EDLEpisode.ramp` (Task 2).
- Produces: `ramp.retime(src: str, dst: str, spec: RampSpec, dur: float, fps: float, crf: int = _CRF) -> str`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_ramp.py`:

```python
def test_retime_issues_one_setpts_fps_pass_through_proc_run(monkeypatch):
    seen = []
    monkeypatch.setattr(ramp.proc, "run", lambda cmd, **kw: seen.append(cmd))
    monkeypatch.setattr(ramp.ffbin, "ffmpeg", lambda: "/bin/ffmpeg")
    ramp.retime("in.mp4", "out.mp4", SPEC, DUR, 60.0)
    assert len(seen) == 1, "a retime is ONE ffmpeg pass"
    cmd = seen[0]
    vf = cmd[cmd.index("-vf") + 1]
    # single-quoted: the expression's own commas must not split the filter chain
    assert vf.startswith("setpts='(") and "')/TB'," in vf.replace(")/TB',", "')/TB',")
    assert vf.endswith(",fps=60"), "setpts alone yields VFR — fps= is mandatory"
    assert "-an" in cmd, "slowed audio is pitch garbage; the segment goes silent"
    assert "-ss" not in cmd


def test_retime_refuses_before_spending_an_encode(monkeypatch):
    monkeypatch.setattr(ramp.proc, "run",
                        lambda *a, **k: pytest.fail("refused specs must not encode"))
    monkeypatch.setattr(ramp.ffbin, "ffmpeg", lambda: "/bin/ffmpeg")
    with pytest.raises(ValueError, match="unique frames per second"):
        ramp.retime("in.mp4", "out.mp4",
                    RampSpec(at=1.0, factor=0.5, ease=0.3, hold=0.2), 3.0, 30.0)
```

Create `tests/lib/test_extract.py`:

```python
from pathlib import Path

import pytest

from scripts import extract
from scripts.lib.edl import EDL, EDLEpisode


def _edl(**kw):
    base = dict(source="a.mp4", start=0.0, dur=4.0, shot_type="medium",
                composition="thirds", grid="thirds")
    return EDL(episodes=[EDLEpisode(**{**base, **kw})])


def test_extract_edl_retimes_a_ramped_segment_in_place(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    seg = tmp_path / "seg"
    calls = {}

    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"raw"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 4.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 60.0, "w": 1920, "h": 1080})())

    def fake_retime(src, dst, spec, dur, fps):
        calls["args"] = (src, dst, spec.factor, dur, fps)
        Path(dst).write_bytes(b"ramped")
        return dst

    monkeypatch.setattr(extract.ramp, "retime", fake_retime)
    out = extract.extract_edl(
        _edl(ramp={"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}),
        str(tmp_path), str(seg))

    assert out == [str(seg / "ep0_raw.mp4")]
    # the RETIMED bytes must sit at the raw name: draft.py and the reel manifest
    # both reference ep{i}_raw.mp4, so a ramp written beside it would be ignored
    assert (seg / "ep0_raw.mp4").read_bytes() == b"ramped"
    assert calls["args"][2:] == (0.4, 4.0, 60.0)


def test_extract_edl_leaves_an_unramped_segment_untouched(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    seg = tmp_path / "seg"
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"raw"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 4.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 60.0, "w": 1920, "h": 1080})())
    monkeypatch.setattr(extract.ramp, "retime",
                        lambda *a, **k: pytest.fail("no ramp, no retime"))
    extract.extract_edl(_edl(), str(tmp_path), str(seg))
    assert (seg / "ep0_raw.mp4").read_bytes() == b"raw"


def test_extract_edl_refuses_a_juddering_ramp_at_the_probed_rate(monkeypatch, tmp_path):
    # The EDL may have been hand-authored past edit_plan's early gate; this is the
    # gate against the fps that actually ships.
    (tmp_path / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"raw"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 4.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 30.0, "w": 1920, "h": 1080})())
    with pytest.raises(ValueError, match="unique frames per second"):
        extract.extract_edl(
            _edl(ramp={"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}),
            str(tmp_path), str(tmp_path / "seg"))
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_ramp.py tests/lib/test_extract.py -k retime -v`
Expected: FAIL, `AttributeError: module 'scripts.lib.ramp' has no attribute 'retime'`

- [x] **Step 3: Implement**

Append to `scripts/lib/ramp.py`:

```python
def retime(src: str, dst: str, spec: RampSpec, dur: float, fps: float,
           crf: int = _CRF) -> str:
    """Retime `src` into `dst` by `spec`, in ONE ffmpeg pass.

    `setpts` moves each frame's timestamp through O(T); `fps=` re-quantizes to the
    source's own constant rate, duplicating frames wherever the stream was
    stretched. Both are ordinary filters, so the whole retime is one argv that
    proc.run's landmine guard can read — which is the reason this is not the
    decode/encode frame pipe the parked WIP used (design §0, §3.4).

    Video only. A slowed audio track is pitch garbage, so the segment goes silent;
    mix._build_ambient already substitutes anullsrc sized to the episode's length,
    so the ambient bed stays in sync by construction (design §12).

    The judder gate runs BEFORE the encode: a refusal should cost nothing."""
    require_playable(spec, fps, f"retime {src}")
    expr = setpts_expr(spec, dur)
    # The expression contains commas. In argv form there is no shell to strip
    # quotes, and ffmpeg reads a bare comma as a filter separator — unquoted, the
    # first if(lt(T,...)) splits the chain and ffmpeg reports "No such filter"
    # (design §10). ffmpeg's own parser strips these single quotes.
    vf = f"setpts='({expr})/TB',fps={fps:.6g}"
    proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-i", src, "-vf", vf,
              "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
              "-pix_fmt", "yuv420p", "-an", dst])
    return dst
```

In `scripts/extract.py`, add `ramp` to the lib import and `RampSpec` to a new one:

```python
from scripts.lib import assembly, ffbin, proc, ramp
from scripts.lib.models import RampSpec
```

In `extract_edl`, replace the `segments.append(out)` line with:

```python
        if ep.ramp is not None:
            # A PRE-STAGE writing a file, exactly like vidstab.stabilize and for
            # the same reason (design §4): the route must be measured on the
            # pixels that ship. A route tracked on un-retimed time and applied to
            # retimed pixels would place the crop at the wrong moment, and
            # check_episode would confirm the framing — path and route would
            # agree with each other while only the pixels disagreed.
            #
            # It replaces ep{i}_raw.mp4 IN PLACE because draft.py and the reel
            # manifest built by preflight both reference that exact name; a ramp
            # written beside it would simply be ignored, leaving reframe the
            # un-ramped cut.
            ramped = str(Path(seg_dir) / f"ep{i}_ramped.mp4")
            ramp.retime(out, ramped, RampSpec.from_dict(ep.ramp), ep.dur, fps)
            Path(ramped).replace(out)
        segments.append(out)
```

(`fps` is already in scope from the `probed, fps = ...` line above.)

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_ramp.py tests/lib/test_extract.py -v`
Expected: PASS

- [x] **Step 5: Prove the argv survives the landmine lint**

Add to `tests/lib/test_ramp.py`:

```python
def test_the_retime_argv_passes_the_landmine_lint():
    # lint._element must not be fooled by the commas inside the quoted setpts
    # expression — the same quote-blindness that once refused every real zoom
    # render (design 2026-08-08 as-built).
    from scripts.lib import lint
    expr = ramp.setpts_expr(SPEC, DUR)
    cmd = ["/bin/ffmpeg", "-y", "-v", "error", "-i", "in.mp4",
           "-vf", f"setpts='({expr})/TB',fps=60", "-c:v", "libx264",
           "-crf", "8", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", "out.mp4"]
    assert lint.check_argv(cmd) == []
```

Run: `.venv/bin/python -m pytest tests/lib/test_ramp.py -k landmine -v`
Expected: PASS. **If it fails, do not weaken the test** — read `scripts/lib/lint.py`'s `check_argv`/`_element` and report the finding: a lint that cannot read this argv would refuse every real ramp render at runtime, exactly as it once did for the zoom.

- [x] **Step 6: Commit**

```bash
git add scripts/lib/ramp.py scripts/extract.py tests/lib/test_ramp.py tests/lib/test_extract.py
git commit -m "feat(ramp): one-pass retime + the extract pre-stage"
```

---

### Task 4: pacing fits the grid to played lengths

**Files:**
- Modify: `scripts/pacing.py` (`_bounds`, `build_pacing`)
- Test: `tests/lib/test_pacing_driver.py` (or the existing test module covering `scripts/pacing.py` — find it with `grep -rl "build_pacing\|_bounds" tests/`)

**Interfaces:**
- Consumes: `EDLEpisode.play_dur()` (Task 2), `ramp.tail_room` (Task 1).
- Produces: no new API — `build_pacing` now fits `Spine` slots to played lengths, so every downstream consumer of `PACING.json` is already in played time.

- [x] **Step 1: Write the failing tests**

```python
def test_the_fitter_receives_played_lengths_not_source_windows(monkeypatch, tmp_path):
    seen = {}

    def spy(durs, beats, energy, hz, tempo, bounds):
        seen["durs"] = list(durs)
        raise _Stop()

    monkeypatch.setattr(pacing_driver.pacing, "fit_spine", spy)
    ep = _ramped_episode(dur=4.0, factor=0.4)      # helper below
    with pytest.raises(_Stop):
        pacing_driver.build_pacing(_write_edl(tmp_path, [ep]), _footage(tmp_path),
                                   [_music(tmp_path)], str(tmp_path))
    assert seen["durs"] == [pytest.approx(ep.play_dur())]
    assert seen["durs"] != [4.0], "fitting the source window puts every later cut off-beat"


def test_the_shrink_bound_stops_at_the_ramp_region(tmp_path):
    # window 4.0s, region [1.0, 3.0] -> only 1.0s of tail may be trimmed, even
    # though half the window (2.0s) and the allowance might both be larger.
    ep = _ramped_episode(dur=4.0, factor=0.4)
    lo, _hi = pacing_driver._bounds(_edl([ep]), _footage_obj(room=10.0), allow=2.0)[0]
    assert lo == pytest.approx(-1.0)


def test_the_shrink_bound_is_unchanged_without_a_ramp(tmp_path):
    ep = _plain_episode(dur=4.0)
    lo, _hi = pacing_driver._bounds(_edl([ep]), _footage_obj(room=10.0), allow=2.0)[0]
    assert lo == pytest.approx(-2.0)     # min(allow, dur/2) as before


def test_the_extend_bound_is_unchanged_by_a_ramp(tmp_path):
    # Outside the region the speed is exactly 1, so extending the played length by
    # d costs d of source — `room - dur` is already right in source seconds.
    ramped = _ramped_episode(dur=4.0, factor=0.4)
    plain = _plain_episode(dur=4.0)
    _lo_r, hi_r = pacing_driver._bounds(_edl([ramped]), _footage_obj(room=4.5), allow=2.0)[0]
    _lo_p, hi_p = pacing_driver._bounds(_edl([plain]), _footage_obj(room=4.5), allow=2.0)[0]
    assert hi_r == pytest.approx(hi_p) == pytest.approx(0.5)
```

Write `_ramped_episode`, `_plain_episode`, `_edl`, `_footage_obj`, `_write_edl`, `_footage`, `_music` and `class _Stop(Exception)` as local helpers in that test module, following whatever fixture style the module already uses for EDL/Footage/MusicSpec construction. `_ramped_episode(dur, factor)` builds an `EDLEpisode` with `ramp={"at": dur/2, "factor": factor, "ease": 0.5, "hold": 1.0}` — for `dur=4.0` that is the region `[1.0, 3.0]`.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_driver.py -k "played or shrink or extend" -v`
Expected: FAIL — `seen["durs"] == [4.0]` and `lo == -2.0`

- [x] **Step 3: Implement**

In `scripts/pacing.py`, add the import:

```python
from scripts.lib import gridfit, ramp as ramp_mod
from scripts.lib.models import RampSpec
```

(merge into the existing `scripts.lib` import line rather than adding a duplicate.)

Replace `_bounds`'s loop body:

```python
    for i, ep in enumerate(edl.episodes):
        clip = by_source.get(ep.source)
        if clip is None:
            raise ValueError(f"pacing: EDL episode {i} references {ep.source!r}, which is "
                             f"not in FOOTAGE.json — have {sorted(by_source)}")
        room = clip.room_after(ep.start)
        # Outward: the speed is exactly 1 outside the ramp region, so extending the
        # PLAYED length by d costs d of source — `room - ep.dur` is already the
        # right bound in source seconds and needs no conversion.
        #
        # Inward is the asymmetric direction. The window may not shrink into the
        # ramp region: a cut landing while the shot is still slowed is the artefact
        # ramp.validate_window exists to refuse (design §2, §6).
        spec = None if ep.ramp is None else RampSpec.from_dict(ep.ramp)
        shrink = min(allow, ep.dur / 2.0, ramp_mod.tail_room(spec, ep.dur))
        out.append((-shrink, min(allow, max(0.0, room - ep.dur))))
```

In `build_pacing`, replace the `durs` line:

```python
    # PLAYED lengths, not source windows: the grid is fitted to what the viewer
    # watches. Reading `dur` here is what let a ramped episode drift every later
    # cut off its musical line (design §6).
    durs = [ep.play_dur() for ep in edl.episodes]
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_driver.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add scripts/pacing.py tests/lib/test_pacing_driver.py
git commit -m "fix(pacing): fit the beat grid to played lengths, floor the shrink at the ramp"
```

---

### Task 5: edit_plan binds, targets and gates in played time

**Files:**
- Modify: `scripts/edit_plan.py` (`window_to_episode`, `_bind_pacing`, `_back_edge_target`)
- Test: `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: `EDLEpisode.play_dur()`, `ramp.ramp_extra`, `ramp.require_playable`, `FootageClip.fps`.
- Produces: no new API.

- [x] **Step 1: Write the failing tests**

```python
def test_the_binding_guard_compares_the_played_length():
    # A 4.0s window with a ramp plays ~6.08s. Against a 6.08s slot it must BIND;
    # comparing the source window would see a 2.08s gap and refuse a correct fit.
    ep = _ramped_episode(dur=4.0, factor=0.4)
    slot_dur = ep.play_dur()
    bound = edit_plan._bind_pacing([ep], _spine([slot_dur], tempo=120.0))
    assert bound[0].beat_slot == 0


def test_binding_sets_the_source_window_the_slot_implies():
    # The episode must PLAY for slot.dur, so its SOURCE window is slot.dur minus
    # the ramp's added time — one subtraction, exact because the enclosed region
    # makes ramp_extra constant in dur (design §2).
    ep = _ramped_episode(dur=4.0, factor=0.4)
    extra = ep.play_dur() - ep.dur
    slot_dur = ep.play_dur() + 0.10
    bound = edit_plan._bind_pacing([ep], _spine([slot_dur], tempo=120.0))
    assert bound[0].dur == pytest.approx(slot_dur - extra)
    assert bound[0].play_dur() == pytest.approx(slot_dur)


def test_binding_an_unramped_episode_is_unchanged():
    ep = _plain_episode(dur=4.0)
    bound = edit_plan._bind_pacing([ep], _spine([4.1], tempo=120.0))
    assert bound[0].dur == pytest.approx(4.1)


def test_the_guard_still_refuses_a_spine_fitted_to_a_different_edit():
    ep = _ramped_episode(dur=4.0, factor=0.4)
    with pytest.raises(ValueError, match="fitted to a different edit"):
        edit_plan._bind_pacing([ep], _spine([2.0], tempo=120.0))


def test_the_back_edge_target_sums_played_time():
    eps = [_ramped_episode(dur=4.0, factor=0.4), _plain_episode(dur=3.0)]
    want = eps[0].play_dur() + 3.0
    got = edit_plan._back_edge_target(eps, _spine([99.0], tempo=120.0, target=99.0))
    assert got == pytest.approx(want)


def test_window_to_episode_refuses_a_juddering_ramp_early():
    # FOOTAGE knows the clip's fps, so the refusal costs no encode at all.
    clip = _clip(fps=30.0)
    with pytest.raises(ValueError, match="unique frames per second"):
        edit_plan.window_to_episode(
            clip, clip.windows[0],
            {"ramp": {"at": 1.0, "factor": 0.4, "ease": 0.3, "hold": 0.2}})


def test_window_to_episode_accepts_a_ramp_the_clip_can_carry():
    clip = _clip(fps=60.0)
    ep = edit_plan.window_to_episode(
        clip, clip.windows[0],
        {"ramp": {"at": 1.0, "factor": 0.4, "ease": 0.3, "hold": 0.2}})
    assert ep.ramp == {"at": 1.0, "factor": 0.4, "ease": 0.3, "hold": 0.2}
```

Build `_spine(durs, tempo, target=None)` as a local helper returning a `Spine` whose `slots` carry those durations (mirror the module's existing spine helper if it has one), and `_clip(fps)` as a `FootageClip` with at least one window long enough to hold the ramp.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "played or binding or judder or back_edge" -v`
Expected: FAIL — the guard raises "fitted to a different edit" on a correct fit

- [x] **Step 3: Implement**

In `scripts/edit_plan.py`, extend the lib import with `ramp as ramp_mod` and `RampSpec`.

In `window_to_episode`, insert immediately before `defaults = {...}`:

```python
    if editorial.get("ramp") is not None:
        # The early half of the judder gate (design §5): FOOTAGE already knows this
        # clip's frame rate, so a ramp that would stutter is refused before the
        # pipeline spends anything. The extract pre-stage repeats the check against
        # the PROBED rate, which is what a hand-authored EDL meets instead.
        ramp_mod.require_playable(RampSpec.from_dict(editorial["ramp"]), clip.fps,
                                  f"{clip.source} window at {start:.2f}s")
```

In `_bind_pacing`, replace the loop body:

```python
    for i in range(n):
        slot, ep = spine.slots[i], episodes[i]
        # PLAYED time on both sides: the spine was fitted to play_dur (pacing.py),
        # so comparing the source window would refuse a correct fit on any ramped
        # episode by exactly the ramp's added time.
        played = ep.play_dur()
        if abs(slot.dur - played) > allow:
            raise ValueError(
                f"pacing: slot {i} is {slot.dur:.2f}s against a {played:.2f}s episode — "
                f"further apart than the {allow:.2f}s snap allows, so this PACING.json "
                f"was fitted to a different edit. Re-run pacing against the current "
                f"EDL.json before binding")
        # Assign the SOURCE window that plays for slot.dur. ramp_extra is constant
        # in dur while the region stays enclosed (design §2), so this is exact
        # rather than a solve — and dataclasses.replace re-runs __post_init__, so a
        # shrink that ate into the region raises instead of passing quietly.
        extra = played - ep.dur
        bound.append(dataclasses.replace(ep, beat_slot=i, dur=slot.dur - extra))
```

In `_back_edge_target`:

```python
    realized = sum(e.play_dur() for e in episodes)
```

and update that function's docstring sentence "`realized` sums EVERY bound episode" to "`realized` sums EVERY bound episode's PLAYED length".

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "fix(edit_plan): bind, target and gate a ramp in played time"
```

---

### Task 6: the manifest and reel targets

**Files:**
- Modify: `scripts/lib/edl.py` (`to_manifest_dict`), `scripts/edl_to_reel.py` (the target sum)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_edl_to_reel.py`

**Interfaces:**
- Consumes: `EDLEpisode.play_dur()`.
- Produces: no new API. After this task all seven design §6 sites read played time.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py`:

```python
def test_the_episode_manifest_target_is_the_played_length():
    # process_episode's per-episode length check measures the RETIMED segment,
    # which is play_dur long. Handing it `dur` would fail every ramped episode.
    ep = _ep(ramp=RAMP)
    md = edl.to_manifest_dict(ep, "seg.mp4", "out.mp4")
    assert md["target_dur"] == pytest.approx(ep.play_dur())
    assert md["target_dur"] != ep.dur
```

Append to `tests/lib/test_edl_to_reel.py`:

```python
def test_the_reel_target_sums_played_lengths(monkeypatch, tmp_path):
    eps = [_ramped_episode(dur=4.0, factor=0.4), _plain_episode(dur=3.0)]
    want = eps[0].play_dur() + 3.0
    rm = _manifest_for(monkeypatch, tmp_path, eps)
    assert rm.target_dur == pytest.approx(want)


def test_an_explicit_edl_target_still_wins(monkeypatch, tmp_path):
    eps = [_ramped_episode(dur=4.0, factor=0.4)]
    rm = _manifest_for(monkeypatch, tmp_path, eps, target_dur=12.0)
    assert rm.target_dur == 12.0
```

`_manifest_for` writes the EDL/project/footage the module's existing driver tests
already build, then calls **`edl_to_reel._build_manifest(edl_path, project_path,
footage_root, work_dir, out_dir)`** — which returns `(rm, None)` on success — and
returns that `rm`. It stubs the extract and per-episode fan-out the same way the
module's current `_build_manifest` tests do; the target arithmetic under test runs
after both. Do NOT reach for `edl_to_reel.edl_to_reel`, which would go on to
render.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_edl_to_reel.py -k "played or target" -v`
Expected: FAIL — both report the source-window sum

- [x] **Step 3: Implement**

In `scripts/lib/edl.py`'s `to_manifest_dict`:

```python
        "segment": segment, "out_path": out_path, "target_dur": ep.play_dur(),
```

In `scripts/edl_to_reel.py`:

```python
    # PLAYED lengths: check_reel measures the master's real duration against this
    # number, and a ramped episode contributes more screen time than its source
    # window (design §6).
    target = (edl.target_dur if edl.target_dur is not None
              else sum(ep.play_dur() for ep in edl.episodes))
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_edl_to_reel.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add scripts/lib/edl.py scripts/edl_to_reel.py tests/lib/test_edl.py tests/lib/test_edl_to_reel.py
git commit -m "fix(edl,edl_to_reel): episode and reel targets read played time"
```

---

### Task 7: real-ffmpeg proofs — length, visibility, byte-identity

**Files:**
- Create: `tests/integration/test_ramp.py`
- Modify: `tests/conftest.py` (add the 60 fps fixture)

**Interfaces:**
- Consumes: everything from Tasks 0–3.
- Produces: `ramp_clip` fixture — 2.0s, 640×360, **60 fps**, a white box moved by `overlay`.

**Why a new fixture:** the shared `sample_clip` is 30 fps, and `MIN_RAMP_FPS = 24.0` therefore admits only `factor ≥ 0.8` on it — a 1.25× slowdown too shallow to separate from measurement noise (design §11). At 60 fps `factor = 0.4` is legal.

- [x] **Step 1: Add the fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def ramp_clip(tmp_path_factory):
    """2s 640x360 60fps clip: a white box sliding left→right on a dark field.

    60 fps on purpose — MIN_RAMP_FPS = 24.0 admits only factor >= 0.8 on the 30fps
    sample_clip, too shallow a ramp to measure against noise.

    Uses overlay, not drawbox: drawbox's x/y expressions are inert under this
    ffmpeg (the `t` var reads as INT32_MAX), so a moving drawbox never appears at
    all — see sample_clip's note.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "ramp.mp4"
    bg = "color=c=0x202020:s=640x360:d=2:r=60"
    box = "color=c=white:s=40x80:d=2:r=60"
    proc.run(
        [binary, "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
         "-filter_complex", "[0][1]overlay=x='60+t*250':y=140",
         "-t", "2", "-pix_fmt", "yuv420p", str(out)])
    return out
```

- [x] **Step 2: Write the proofs**

Create `tests/integration/test_ramp.py`:

```python
"""Real-ffmpeg proofs for the speed ramp (design §11).

These render actual pixels. A correct-looking argv is not evidence that a frame
moved — backlog #18's whole finding is that a live-added vignette came out
invisible and no test caught it.
"""
import subprocess

import pytest

from scripts.lib import assembly, ffbin, proc, ramp
from scripts.lib.models import RampSpec

pytestmark = pytest.mark.integration

SPEC = RampSpec(at=1.0, factor=0.4, ease=0.25, hold=0.5)   # region [0.25, 1.75]
DUR, FPS, W, H = 2.0, 60.0, 640, 360


def _diff_curve(path, w, h):
    """mean |frame - prev| per frame, gray, one decode — the way lib/anchors
    measures motion. Slowing must drop this on the plateau."""
    p = subprocess.Popen(                                  # noqa: S603 - test-only probe
        [ffbin.ffmpeg(), "-v", "error", "-i", str(path),
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE)
    n, prev, out = w * h, None, []
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            if prev is not None:
                out.append(sum(abs(a - b) for a, b in zip(buf, prev)) / n)
            prev = buf
    finally:
        p.stdout.close()
        p.wait()
    return out


def _band(curve, t0, t1, fps=FPS):
    seg = curve[max(0, int(t0 * fps)):min(len(curve), int(t1 * fps))]
    assert seg, f"empty band [{t0}, {t1}]"
    return sum(seg) / len(seg)


def test_the_rendered_length_matches_the_recorded_one(ramp_clip, tmp_path):
    """play_dur() must not be a number the file disagrees with."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    want = DUR + ramp.ramp_extra(SPEC, DUR)
    got = assembly.probe_duration(dst)
    assert got == pytest.approx(want, abs=2.0 / FPS), (
        f"recorded {want:.4f}s against a rendered {got:.4f}s — record and render "
        f"read the same knots, so they may differ only by fps= quantization")


def test_the_ramp_actually_slows_the_picture(ramp_clip, tmp_path):
    """Backlog #18's demand: measure the effect in pixels, not in the argv."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)

    ts, o = ramp.knots(SPEC, DUR)

    def o_at(t):
        """Where source time t lands in the output. Knots are NOT evenly spaced
        (design §3.2), so find the interval rather than dividing by a step."""
        i = max(0, min(len(ts) - 2, next(k for k in range(len(ts) - 1)
                                         if ts[k + 1] >= t)))
        return o[i] + (o[i + 1] - o[i]) * (t - ts[i]) / (ts[i + 1] - ts[i])

    curve = _diff_curve(dst, W, H)
    normal = _band(curve, 0.05, o_at(0.25) - 0.05)          # before the region
    plateau = _band(curve, o_at(0.75) + 0.05, o_at(1.25) - 0.05)
    ratio = plateau / normal
    assert ratio == pytest.approx(SPEC.factor, abs=0.12), (
        f"plateau/normal frame difference is {ratio:.3f} against a factor of "
        f"{SPEC.factor} — the picture is not actually slowing")


def test_the_retimed_stream_is_constant_frame_rate(ramp_clip, tmp_path):
    """setpts without fps= yields VFR, which assembly.concat will not accept."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    assert assembly.probe_stream(dst).fps == pytest.approx(FPS, abs=0.01)


def test_the_retimed_segment_carries_no_audio(ramp_clip, tmp_path):
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    streams = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", dst]).stdout
    assert streams.strip() == ""


def test_a_deeper_ramp_slows_more_than_a_shallow_one(ramp_clip, tmp_path):
    """The gate's own arithmetic, proved in pixels: factor is a real dial, not a
    flag that merely switches slowdown on."""
    shallow = RampSpec(at=1.0, factor=0.8, ease=0.25, hold=0.5)
    a, b = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")
    ramp.retime(str(ramp_clip), a, shallow, DUR, FPS)
    ramp.retime(str(ramp_clip), b, SPEC, DUR, FPS)
    assert assembly.probe_duration(b) > assembly.probe_duration(a) + 0.2
```

- [x] **Step 3: Run the proofs**

Run: `.venv/bin/python -m pytest tests/integration/test_ramp.py -v`
Expected: PASS — every test in the file green. If the visibility ratio misses its band, **report the number** — do not widen `abs=0.12` to make it pass. A ratio far from `factor` means the retime is not doing what the design claims.

- [x] **Step 4: Prove the unramped path is byte-identical**

Add to `tests/integration/test_ramp.py`:

```python
def test_an_unramped_extract_is_unchanged_by_this_slice(sample_clip, tmp_path):
    """No ramp, no retime, no new bytes — the golden fixtures depend on it."""
    from scripts import extract
    from scripts.lib.edl import EDL, EDLEpisode
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.mp4").write_bytes(sample_clip.read_bytes())
    e = EDL(episodes=[EDLEpisode(source="a.mp4", start=0.0, dur=1.0,
                                 shot_type="medium", composition="thirds",
                                 grid="thirds")])
    one = extract.extract_edl(e, str(src_dir), str(tmp_path / "s1"))
    two = extract.extract_edl(e, str(src_dir), str(tmp_path / "s2"))
    from pathlib import Path
    assert Path(one[0]).read_bytes() == Path(two[0]).read_bytes()
    assert not list((tmp_path / "s1").glob("*_ramped.mp4"))
```

Run: `.venv/bin/python -m pytest tests/integration/test_ramp.py -v`
Expected: PASS — including the new byte-identity test

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_ramp.py tests/conftest.py
git commit -m "test(ramp): real-ffmpeg length, visibility and byte-identity proofs"
```

---

### Task 8: end-to-end — a ramped episode through SP3 → SP1

**Files:**
- Modify: `tests/integration/test_ramp.py`

**Interfaces:**
- Consumes: Tasks 0–7 complete.

- [x] **Step 1: Write the end-to-end proof**

Find the existing SP3→SP1 integration test (`grep -rln "write_edit_plan" tests/integration/`) and mirror its scaffolding — FOOTAGE.json, project.json, selection.json, then `edit_plan build`, then `edl_to_reel`. Append to `tests/integration/test_ramp.py`:

```python
def test_a_ramped_episode_reaches_the_reel_at_its_played_length(ramp_clip, tmp_path):
    """The whole point of backlog #7, end to end: the reel is as long as the
    episodes PLAY, not as long as their source windows."""
    from scripts import edit_plan, edl_to_reel
    from scripts.lib.edl import EDL

    proj = _write_project(tmp_path)              # 9:16, long_edge 240 — small and fast
    foot = _write_footage(tmp_path, ramp_clip, fps=60.0)
    sel = _write_selection(tmp_path, [
        {"source": "ramp.mp4", "window": 0,
         "ramp": {"at": 1.0, "factor": 0.4, "ease": 0.25, "hold": 0.5}},
    ])
    edit_plan.write_edit_plan(str(sel), str(foot), str(proj), str(tmp_path))

    e = EDL.from_json(str(tmp_path / "EDL.json"))
    ep = e.episodes[0]
    assert ep.play_dur() > ep.dur

    res = edl_to_reel.edl_to_reel(
        str(tmp_path / "EDL.json"), str(proj), str(tmp_path),
        str(tmp_path / "work"), str(tmp_path / "out"))
    assert res["status"] == "delivered", res
    from scripts.lib import assembly
    assert assembly.probe_duration(res["output"]) == pytest.approx(
        ep.play_dur(), abs=0.2)


def test_the_edl_markdown_reports_the_ramp(ramp_clip, tmp_path):
    from scripts import edit_plan
    proj = _write_project(tmp_path)
    foot = _write_footage(tmp_path, ramp_clip, fps=60.0)
    sel = _write_selection(tmp_path, [
        {"source": "ramp.mp4", "window": 0,
         "ramp": {"at": 1.0, "factor": 0.4, "ease": 0.25, "hold": 0.5}},
    ])
    edit_plan.write_edit_plan(str(sel), str(foot), str(proj), str(tmp_path))
    md = (tmp_path / "EDL.md").read_text()
    assert "ramp x2.5" in md and "plays" in md
```

Write `_write_project`, `_write_footage` and `_write_selection` by copying the existing SP3 integration test's helpers verbatim into this module and adjusting `_write_footage` to take an `fps` argument and emit one window covering `[0.0, 2.0]` of `ramp.mp4` (copy `ramp_clip` into `tmp_path/ramp.mp4` first, since `footage_root` is `tmp_path`).

The signature above is the real one: `edl_to_reel.edl_to_reel(edl_path, project_path, footage_root, work_dir, out_dir, *, music=None, titles=None, jobs=DEFAULT_JOBS, color_delta_max=None, changelog="")`, returning `{"status": "delivered", "output": ..., "report": ..., "reprocessed": [...]}` on success and `{"status": "stop_and_report", "finding": {...}, ...}` otherwise. Assert on `status` first so a stop reports its finding instead of a bare `KeyError`.

- [x] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/integration/test_ramp.py -v`
Expected: PASS — including both end-to-end tests

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_ramp.py
git commit -m "test(ramp): end-to-end — a ramped episode reaches the reel at play_dur"
```

---

### Task 9: mutation battery + full suite

**Files:**
- Modify: none expected. Any change here is a coverage hole this task found.

The battery is a sequence of **steps, not suggestions**. For each row: apply the mutation to production code, run the named test selection, confirm it FAILS, then `git checkout --` **only the mutated file** and re-confirm green. If a mutation SURVIVES, write the missing test, commit it, and record the hole in the task report.

- [x] **Step 1: Run the battery**

| # | Mutation | Must be caught by |
|---|---|---|
| 1 | `ramp.RAMP_EASE_KNOTS` 16 → 3 | `test_ramp_extra_matches_an_independent_simpson_integration` (3 subdivisions per ease is well short of convergence) and `test_knots_are_anchored_to_the_region_not_spread_evenly` (the count assert). NOT `test_setpts_expr_reconstructs_the_same_knots_it_was_built_from`, which is self-consistent at any count — note that in the report. |
| 1b | `knots` spreads evenly across `[0, dur]` again (the naive scheme this design rejects) | `test_ramp_extra_is_bit_identical_across_window_lengths` and `test_knots_are_anchored_to_the_region_not_spread_evenly`. This is the single most important row in the battery: an even spread still *looks* right at one window length and silently corrupts every bound length at another. |
| 2 | `ramp.MIN_RAMP_FPS` 24.0 → 1.0 | `test_require_playable_refuses_below_the_floor_and_names_the_remedy`, `test_extract_edl_refuses_a_juddering_ramp_at_the_probed_rate`, `test_window_to_episode_refuses_a_juddering_ramp_early` |
| 3 | `retime`'s `vf` drops the `,fps={fps:.6g}` suffix | `test_the_retimed_stream_is_constant_frame_rate` |
| 4 | `retime`'s `vf` drops the single quotes around the setpts expression | `test_retime_issues_one_setpts_fps_pass_through_proc_run`, and `tests/integration/test_ramp.py` should ERROR at the ffmpeg call |
| 5 | `retime` drops `-an` | `test_the_retimed_segment_carries_no_audio` |
| 6 | `retime` calls `require_playable` AFTER `proc.run` | `test_retime_refuses_before_spending_an_encode` |
| 7 | `extract_edl` writes the ramped file beside `ep{i}_raw.mp4` instead of replacing it | `test_extract_edl_retimes_a_ramped_segment_in_place` |
| 8 | `EDLEpisode.play_dur` returns `self.dur` always | `test_play_dur_adds_the_ramps_time`, `test_the_binding_guard_compares_the_played_length`, the two `edl_to_reel` target tests, the end-to-end |
| 9 | `validate_window`'s tail check `< -_WINDOW_TOL` → `< -1e3` | `test_an_episode_refuses_a_ramp_running_past_its_window` |
| 10 | `validate_window`'s head check deleted entirely | `test_an_episode_refuses_a_ramp_starting_before_its_window` |
| 11 | `pacing.build_pacing`'s `durs` back to `ep.dur` | `test_the_fitter_receives_played_lengths_not_source_windows` |
| 12 | `pacing._bounds`'s `shrink` drops the `tail_room` term | `test_the_shrink_bound_stops_at_the_ramp_region` |
| 13 | `_bind_pacing` assigns `dur=slot.dur` (no `- extra`) | `test_binding_sets_the_source_window_the_slot_implies` |
| 14 | `_bind_pacing`'s guard compares `ep.dur` again | `test_the_binding_guard_compares_the_played_length` |
| 15 | `_back_edge_target` sums `e.dur` | `test_the_back_edge_target_sums_played_time` |
| 16 | `to_manifest_dict`'s `target_dur` back to `ep.dur` | `test_the_episode_manifest_target_is_the_played_length` |
| 17 | `edl_to_reel`'s target sums `ep.dur` | `test_the_reel_target_sums_played_lengths` |
| 18 | `speed_at`'s cosine → linear (`p` instead of `(1-cos(pi*p))/2`) | `test_the_ease_is_monotonic_and_meets_both_ends` (the 0.7 midpoint) |
| 19 | `RampSpec.__post_init__`'s bool-before-int check removed | the six `test_rampspec_refuses_a_bool_before_int` cases |
| 20 | `RampSpec` accepts `factor > 1.0` | `test_rampspec_refuses_out_of_range[factor-1.1]` |

- [x] **Step 2: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: every test passes; the only new skips are ones that already existed (demucs, torchreid, no-network iTunes). **No golden fixture may move** — an unramped run is byte-identical by construction. If a golden moved, stop and report it rather than re-pinning.

- [x] **Step 3: Commit any tests the battery added**

```bash
git add tests/
git commit -m "test(ramp): close the mutation-battery holes"
```

---

### Task 10: skills and docs sync

**Files:**
- Modify: `skills/edit-plan/SKILL.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/fixes-backlog.md`, `docs/cinematic-quality-playbook.md`, `docs/plans/2026-08-09-speed-ramp.md`

- [x] **Step 1: `skills/edit-plan/SKILL.md`**

Add a `ramp` subsection beside the existing `zoom`/`pan` guidance:

- The wire form, with `0.4 = 2.5x slower` spelled out.
- All four times are relative to the **window's** start.
- The region `[at − hold/2 − ease, at + hold/2 + ease]` must sit inside the window.
- `MIN_RAMP_FPS = 24.0`: the slowest legal `factor` is `24 / clip fps` — 0.4 on 60 fps footage, 0.8 on 30 fps. FOOTAGE.md prints each clip's rate.
- **Author the ramp before running pacing.** A ramp added afterwards makes the binding guard refuse, naming the re-run.
- A ramped episode plays longer than its window; `EDL.md` shows both.
- The segment goes silent — say so in `processing_notes` if the shot had nat sound worth keeping, and consider not ramping it.

- [x] **Step 2: `docs/build-status.md`**

Add a Done entry dated 2026-08-09 carrying the measured numbers (6.067s rendered against 6.081s analytic; the 32-knot table; the 0.453 visibility ratio against a 0.40 factor; 1.32× and 1.90 GB for the rejected pipe), the seven fixed length sites, every §12 honest limit, and the §13 deferrals. Update **Next action** to name what remains in P4: **#9** effects library + mood palettes, **#10** the 3-frame probe, the rest of **#18** (look filters, `highlight_red`'s missing visibility proof, `outline-bold`), and **#5** documenting the knob surface — plus the two out-of-scope gaps this slice found and did not fix: `EDLEpisode.smooth_window_s` cannot be authored though `ReframeSpec` has the field, and `draft.py` uses the canvas aspect where it needs delivery pixels.

- [x] **Step 3: `docs/pipeline-map.md`**

Note the retime pre-stage in the extract row, beside stabilize.

- [x] **Step 4: `CLAUDE.md`**

Add two Quick Reference rows (design + plan) in the established one-paragraph style, placed after the subject-anchored-moves rows. Add one always-loaded Known-troubles bullet:

> - `setpts` remaps timestamps but does **not** resample — without a following
>   `fps=` the output is VFR and concat's uniformity check rejects it. And a
>   filtergraph value containing a comma must be single-quoted *inside* the `-vf`
>   string: in argv form nothing strips shell quotes, so the first bare comma
>   splits the filter chain.

- [x] **Step 5: `docs/fixes-backlog.md` and the playbook**

Mark **#7 ✅ LANDED 2026-08-09** with the design/plan links, what it does, and what it does not (the §12 limits — especially that `MIN_RAMP_FPS` is a convention and that a hand-authored EDL meets only one of the two judder gates). Update **#18** to record the speed half as landed with its visibility proof, leaving the look filters, `highlight_red` and `outline-bold` open. Update the playbook's priority 4 the same way.

- [x] **Step 6: Tick this plan's checkboxes and commit**

```bash
git add docs/ CLAUDE.md skills/
git commit -m "docs(ramp): status, registry, backlog and skill guidance"
```

---

## Self-Review

**1. Spec coverage.**

| Design § | Task |
|---|---|
| §1 two lengths | 2 (`play_dur`) |
| §2 enclosure refusal | 1 (`validate_window`), 2 (wired into `__post_init__`) |
| §3 one ffmpeg pass, knots, record==render | 1, 3, 7 |
| §4 pre-stage at extract | 3 |
| §5 judder gate, both sites | 1 (`require_playable`), 3 (extract), 5 (edit_plan) |
| §6 all seven length sites | 2 (markdown), 4 (pacing ×2), 5 (bind ×2, back-edge), 6 (manifest, reel) |
| §7 stage order enforces itself | 5 (the guard), 10 (SKILL) |
| §8 contract + authoring | 0, 2, 10 |
| §9 what is not ported | Global Constraints |
| §10 landmines | 3 (the quoting, in code + test), 10 (CLAUDE.md) |
| §11 proofs | 7, 8 |
| §12 honest limits | 10 (build-status, backlog) |
| §13 deferred | 10 (build-status) |

No gaps.

**2. Placeholder scan.** No TBD/TODO. Three tasks (4, 5, 8) say "mirror the module's existing helper style" for test scaffolding rather than reproducing fixture builders whose current shape must be read from the file — the *assertions* are given in full, which is the part that carries the requirement.

**3. Type consistency.** `RampSpec(at, factor, ease, hold)` is constructed identically in Tasks 0–8. `ramp_extra(spec | None, dur)`, `tail_room(spec | None, dur)`, `validate_window(spec, dur, where)`, `require_playable(spec, fps, where)`, `setpts_expr(spec, dur)`, `retime(src, dst, spec, dur, fps, crf=)` — each appears with the same signature everywhere it is named. `play_dur()` takes no arguments throughout.

**One risk worth naming before execution.** Task 3's Step 5 asserts `lint.check_argv` accepts the retime argv. If `_element` mishandles the quoted comma the way it once did for the zoom, that test fails *at implementation time* rather than at the first real render — which is the point of putting it there. The instruction is explicit: report it, do not weaken it.
