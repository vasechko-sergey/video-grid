# Subject-Anchored Frame Moves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `zoom` whose rect is chosen per route sample by the existing
composition rule — so every `check_episode` check applies to it — plus a `pan`
that may no longer be authored over a shot the intake measured as holding
people.

**Architecture:** The layout's crop stays the widest rect the move ever needs
(both ends of a `ZoomSpec` are `<= 1.0`), so the `crop` filter is unchanged in
size and vertical position; a `zoompan` inserted between `crop` and `scale`
cuts the shrinking sub-rect. `PathMeta` records the per-sample rect it cut, and
the two geometry chokepoints (`marks_at_times`, `extent_at_times`) plus
`checks.on_line`/`centered`/`jitter` read that record instead of three scalars.

**Tech Stack:** Python 3.13, ffmpeg (`ffmpeg-full`, resolved through
`scripts/lib/ffbin.py`), pytest.

**Design:** [docs/specs/2026-08-08-subject-anchored-moves-design.md](../specs/2026-08-08-subject-anchored-moves-design.md)

## Global Constraints

- **Fail loud.** Every refusal raises `ValueError` with a remedy naming what to
  change. No silent clamping, no defaults substituted for bad input. See
  [docs/coding-standards.md](../coding-standards.md).
- **Imports at the top of the file.** No function-local imports.
- **Scripts are modules.** Run as `python -m scripts.x`; tests rely on
  `pythonpath = .`. Python is `.venv/bin/python` (3.13).
- **`-ss` AFTER `-i`** for any re-encoded cut (design §12 seek order).
- **`lutrgb` is banned** — `colorchannelmixer` only.
- **Never invoke a bare `ffmpeg`/`ffprobe` literal.** Always
  `ffbin.ffmpeg()` / `ffbin.ffprobe()`; an AST scan enforces this.
- **`zoompan` must always carry explicit `s=`, `fps=` and `d=`** — all three
  defaults corrupt silently (design §8). Task 12 makes this machine-checked.
- **No new waiver, flag, or parameter that turns a check off.** Governance #8.
- **Zoom off must stay byte-identical.** With `spec.zoom is None` the emitted
  argv equals today's exactly — no `zoompan`, no changed `crop`, and
  `path.meta.json` gains no keys.
- **Whole-object asserts in tests** where a dataclass or dict is the subject —
  assert the whole thing, not one field. See
  [docs/testing-guide.md](../testing-guide.md).
- Commit after every task with a `feat:`/`fix:`/`test:`/`docs:` prefix and the
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` trailer.

---

## File Structure

**Created:**
- `scripts/lib/zoom.py` — pure zoom arithmetic: the per-sample rect, the `z`
  expression, the three refusals that need the episode's numbers.
- `tests/lib/test_zoom.py` — unit tests for the above.
- `tests/integration/test_zoom.py` — real-ffmpeg pixel proofs.

**Modified:**
- `scripts/lib/models.py` — `ZoomSpec`; `PathMeta.crop_ws/crop_hs/crop_ys` +
  `zoomed`; `ReframeSpec.zoom`.
- `scripts/reframe.py` — `_xexpr(var=)`, `compute_path(crop_ws=)`,
  `_filter_args(zoom_args=)`, the `reframe()` zoom branch.
- `scripts/lib/checks.py` — `on_line`/`centered` take `crop_ws`; `jitter`
  measures the rect's centre.
- `scripts/lib/geometry.py` — `_rect_at` helper; `marks_at_times` and
  `extent_at_times` use it.
- `scripts/check_episode.py` — builds `crop_ws`, narrows the `freedom == 0` arm.
- `scripts/lib/manifest.py` — `Manifest.zoom`, three refusals.
- `scripts/lib/edl.py` — `EDLEpisode.zoom`, wire + markdown + manifest bridge.
- `scripts/process_episode.py` — builds the `ZoomSpec`, preflights it.
- `scripts/edit_plan.py` — the measured pan gate; `_merge_windows` presence.
- `scripts/lib/lint.py` — the fifth landmine check.
- `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`,
  `skills/edit-plan/SKILL.md` — docs sync.

---

## Task 0: `ZoomSpec` config-spec

**Files:**
- Modify: `scripts/lib/models.py` (beside `PanSpec`)
- Test: `tests/lib/test_models.py`

**Interfaces:**
- Produces: `models.ZoomSpec(start: float, end: float)` with `to_dict()` →
  `{"from": start, "to": end}` and `ZoomSpec.from_dict(d)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_zoom_spec_round_trips_through_its_wire_names():
    z = models.ZoomSpec(start=1.0, end=0.7)
    assert z.to_dict() == {"from": 1.0, "to": 0.7}
    assert models.ZoomSpec.from_dict({"from": 1.0, "to": 0.7}) == z


def test_zoom_spec_refuses_a_fraction_above_one():
    with pytest.raises(ValueError, match=r"within \(0\.0, 1\.0\]"):
        models.ZoomSpec(start=1.2, end=0.7)


def test_zoom_spec_refuses_a_fraction_at_or_below_zero():
    with pytest.raises(ValueError, match=r"within \(0\.0, 1\.0\]"):
        models.ZoomSpec(start=1.0, end=0.0)


def test_zoom_spec_refuses_a_bool_before_it_can_read_as_one():
    with pytest.raises(ValueError, match="must be a number"):
        models.ZoomSpec(start=True, end=0.7)


def test_zoom_spec_refuses_a_zoom_that_does_not_move():
    with pytest.raises(ValueError, match="not a zoom"):
        models.ZoomSpec(start=0.8, end=0.8)


def test_zoom_spec_from_dict_refuses_a_non_object():
    with pytest.raises(ValueError, match="expected an object"):
        models.ZoomSpec.from_dict([1.0, 0.7])


def test_zoom_spec_from_dict_names_every_missing_key():
    with pytest.raises(ValueError, match="missing from, to"):
        models.ZoomSpec.from_dict({})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k zoom_spec -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.models' has no attribute 'ZoomSpec'`.

- [ ] **Step 3: Add `ZoomSpec` directly below `PanSpec`**

```python
@dataclass
class ZoomSpec:
    """A subject-anchored push-in / pull-out (design 2026-08-08).

    `start`/`end` are fractions of the layout's crop WIDTH: 1.0 is the crop the
    layout resolved, 0.7 a 1.43x push-in. DIRECTION IS THE SIGN of `end - start`
    — no direction vocabulary, for the same reason PanSpec has none (a second
    spelling of what the numbers already say).

    Both ends are in (0, 1]. Above 1.0 the rect would need pixels the layout's
    crop does not contain, so the base crop would have to grow — silently
    changing the composition the layout resolved. At or below 0.0 it is not a
    rectangle.

    Unlike a pan, a zoom is NOT a generated path: the rect's position still
    comes from the tracked route through the same composition rule, at the width
    in force at that sample. That is what keeps every check_episode check
    applicable (design §1).

    WIRE NAMES `from`/`to`, exactly as PanSpec and for the same reason: `from`
    is a Python keyword and cannot be a field name. from_dict/to_dict carry the
    mapping, and it lives in exactly one place.
    """
    start: float
    end: float

    def __post_init__(self) -> None:
        for name, v in (("start", self.start), ("end", self.end)):
            # bool BEFORE int: isinstance(True, int) is True, so {"from": true}
            # would otherwise silently mean 1.0
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(
                    f"ZoomSpec.{name} must be a number in (0.0, 1.0] — a fraction of the "
                    f"layout's crop width, where 1.0 is the whole crop and 0.7 a 1.43x "
                    f"push-in; got {v!r}")
            # NO float(): json.loads builds ints of any size and float() raises
            # OverflowError — not ValueError — on one past float range, which would
            # escape manifest.validate()'s soft gate as a crash. Same landmine PanSpec
            # documents. int-vs-float comparison is exact and rejects NaN too.
            if not 0.0 < v <= 1.0:
                raise ValueError(
                    f"ZoomSpec.{name} must be within (0.0, 1.0] — above 1.0 the rect would "
                    f"need pixels the layout's crop does not contain, and at or below 0.0 it "
                    f"is not a rectangle; got {v!r}")
        if self.start == self.end:
            raise ValueError(
                f"ZoomSpec start and end are both {self.start!r} — a zoom that does not move "
                "is not a zoom, it is a smaller crop. Set the layout's `crop_scale` for a "
                "tighter framing, or give the zoom an extent")

    def to_dict(self) -> dict:
        return {"from": self.start, "to": self.end}

    @classmethod
    def from_dict(cls, d: dict) -> "ZoomSpec":
        if not isinstance(d, dict):
            raise ValueError(
                f"ZoomSpec.from_dict: expected an object with 'from' and 'to' fractions, "
                f"got {type(d).__name__} — write zoom as {{\"from\": 1.0, \"to\": 0.7}}")
        missing = [k for k in ("from", "to") if k not in d]
        if missing:
            raise ValueError(
                f"ZoomSpec.from_dict: missing {', '.join(missing)} — a zoom needs both "
                f"'from' and 'to' fractions of the layout's crop width, got {sorted(d)}")
        return cls(start=d["from"], end=d["to"])
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k zoom_spec -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat(zoom): ZoomSpec config-spec"
```

---

## Task 1: `PathMeta` records the per-sample rect

**Files:**
- Modify: `scripts/lib/models.py` (`PathMeta`)
- Test: `tests/lib/test_models.py`

**Interfaces:**
- Consumes: nothing from Task 0.
- Produces: `PathMeta(..., crop_ws=None, crop_hs=None, crop_ys=None)` and the
  read-only property `PathMeta.zoomed -> bool`. `to_dict()` emits the three keys
  **only when zoomed**, so an unzoomed sidecar is byte-identical to today's.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`. `_meta_kwargs` is a local helper so each
test states only what it varies:

```python
def _meta_kwargs(**over):
    base = dict(mode="fill", crop_w=1080, crop_h=1920, crop_y=0,
                src_dims=(3840, 2160), canvas=(1080, 1920), out_dims=(1080, 1920),
                rect_px=(0, 0, 1080, 1920), freedom=2760)
    base.update(over)
    return base


def test_path_meta_without_a_zoom_is_not_zoomed_and_writes_no_zoom_keys():
    m = models.PathMeta(**_meta_kwargs())
    assert m.zoomed is False
    assert m.to_dict() == {
        "mode": "fill", "crop_w": 1080, "crop_h": 1920, "crop_y": 0,
        "src_dims": [3840, 2160], "canvas": [1080, 1920], "out_dims": [1080, 1920],
        "rect_px": [0, 0, 1080, 1920], "freedom": 2760, "background": "blur",
        "pan": False, "stabilized": False}


def test_path_meta_round_trips_the_zoom_arrays():
    m = models.PathMeta(**_meta_kwargs(crop_ws=[1080, 900], crop_hs=[1920, 1600],
                                       crop_ys=[0, 160]))
    assert m.zoomed is True
    d = m.to_dict()
    assert d["crop_ws"] == [1080, 900] and d["crop_hs"] == [1920, 1600]
    assert d["crop_ys"] == [0, 160]
    assert models.PathMeta.from_dict(d) == m


def test_path_meta_refuses_a_partial_set_of_zoom_arrays():
    with pytest.raises(ValueError, match="all-or-nothing"):
        models.PathMeta(**_meta_kwargs(crop_ws=[1080, 900]))


def test_path_meta_refuses_zoom_arrays_of_different_lengths():
    with pytest.raises(ValueError, match="same length"):
        models.PathMeta(**_meta_kwargs(crop_ws=[1080, 900], crop_hs=[1920],
                                       crop_ys=[0, 160]))


def test_path_meta_refuses_empty_zoom_arrays():
    with pytest.raises(ValueError, match="at least one sample"):
        models.PathMeta(**_meta_kwargs(crop_ws=[], crop_hs=[], crop_ys=[]))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k path_meta -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'crop_ws'`.

- [ ] **Step 3: Add the fields, the guard and the property**

Add to `PathMeta`, after `stabilized`:

```python
    crop_ws: list[int] | None = None    # per-route-sample effective crop width under a zoom
    crop_hs: list[int] | None = None    # ... height
    crop_ys: list[int] | None = None    # ... top edge (the rect keeps the base rect's centre)
```

Extend the class docstring with:

```
    `crop_ws`/`crop_hs`/`crop_ys` are the ZOOM record (design 2026-08-08 §4).
    They are None for a constant rect — which is every episode without a zoom,
    and which keeps this sidecar byte-identical to the one written before zoom
    existed. There is deliberately NO `zoom` bool beside them: a bit would have
    to agree with the arrays, and two representations of one fact are a
    contradiction surface. `zoomed` is a property instead, so it cannot disagree.
```

Add `__post_init__` and the property:

```python
    def __post_init__(self) -> None:
        arrays = {"crop_ws": self.crop_ws, "crop_hs": self.crop_hs, "crop_ys": self.crop_ys}
        given = sorted(n for n, v in arrays.items() if v is not None)
        if not given:
            return
        if len(given) != 3:
            raise ValueError(
                f"PathMeta: the zoom arrays are all-or-nothing — got {given} and not the "
                f"rest. A zoomed rect varies width, height and top edge together; re-run "
                f"reframe to regenerate path.meta.json")
        if len({len(v) for v in arrays.values()}) != 1:
            raise ValueError(
                f"PathMeta: the zoom arrays must be the same length — got "
                f"{ {n: len(v) for n, v in arrays.items()} }. They are parallel to the route, "
                f"so a mismatch means the sidecar was hand-edited; re-run reframe")
        if not self.crop_ws:
            raise ValueError(
                "PathMeta: the zoom arrays hold at least one sample or are all None — an "
                "empty array claims a zoom with no rect. Re-run reframe")

    @property
    def zoomed(self) -> bool:
        """True ⇒ the rect varied over the episode and the arrays record it."""
        return self.crop_ws is not None
```

In `to_dict`, after the existing `"stabilized": self.stabilized}` dict, emit the
arrays conditionally:

```python
    def to_dict(self) -> dict:
        d = {"mode": self.mode, "crop_w": self.crop_w, "crop_h": self.crop_h,
             "crop_y": self.crop_y, "src_dims": list(self.src_dims),
             "canvas": list(self.canvas), "out_dims": list(self.out_dims),
             "rect_px": list(self.rect_px), "freedom": self.freedom,
             "background": self.background, "pan": self.pan,
             "stabilized": self.stabilized}
        if self.zoomed:
            # emitted ONLY when zoomed: an unzoomed sidecar stays byte-identical to
            # every one written before this slice, which is what protects the goldens
            d.update({"crop_ws": list(self.crop_ws), "crop_hs": list(self.crop_hs),
                      "crop_ys": list(self.crop_ys)})
        return d
```

In `from_dict`, inside the existing `try:` block, add three keyword arguments to
the `cls(...)` call (they read as absent → None, the same `.get` exemption
`background` and `pan` already carry, and for the same reason: a sidecar written
before this slice has no zoom and its absence honestly means "constant rect"):

```python
                       crop_ws=_int_list(d.get("crop_ws")),
                       crop_hs=_int_list(d.get("crop_hs")),
                       crop_ys=_int_list(d.get("crop_ys")),
```

and add this module-level helper directly above `class PathMeta`:

```python
def _int_list(v: object) -> list[int] | None:
    """A sidecar's optional parallel int array, or None when the key is absent."""
    return None if v is None else [int(x) for x in v]
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k path_meta -v`
Expected: 5 passed.

- [ ] **Step 5: Run every existing PathMeta consumer**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/lib/test_geometry.py tests/lib/test_safezones.py tests/lib/test_reel_final.py -q`
Expected: all pass — the sidecar's unzoomed shape did not move.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat(zoom): PathMeta records the per-sample rect"
```

---

## Task 2: `scripts/lib/zoom.py` — the pure arithmetic

**Files:**
- Create: `scripts/lib/zoom.py`
- Test: `tests/lib/test_zoom.py`

**Interfaces:**
- Consumes: `models.ZoomSpec` (Task 0).
- Produces:
  - `zoom.ZOOM_MAX_RATE: float`
  - `zoom.validate(spec, crop_w, out_w, dur) -> None`
  - `zoom.scales(spec, times) -> list[float]`
  - `zoom.rects(spec, crop_w, crop_h, crop_y, src_h, times) -> tuple[list[int], list[int], list[int]]`
  - `zoom.z_expr(spec, t0, t1, var="it") -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_zoom.py`:

```python
import pytest

from scripts.lib import zoom
from scripts.lib.models import ZoomSpec


def test_scales_interpolate_linearly_over_the_routes_own_span():
    s = zoom.scales(ZoomSpec(start=1.0, end=0.6), [2.0, 2.5, 3.0])
    assert s == pytest.approx([1.0, 0.8, 0.6])


def test_scales_refuse_a_single_sample():
    with pytest.raises(ValueError, match="at least two samples"):
        zoom.scales(ZoomSpec(start=1.0, end=0.6), [2.0])


def test_rects_shrink_from_the_full_crop_and_keep_its_centre():
    ws, hs, ys = zoom.rects(ZoomSpec(start=1.0, end=0.5), crop_w=1000, crop_h=2000,
                            crop_y=80, src_h=2160, times=[0.0, 1.0])
    assert ws == [1000, 500]
    assert hs == [2000, 1000]
    # centre_y = 80 + 1000 = 1080; the tighter rect keeps it: 1080 - 500 = 580
    assert ys == [80, 580]


def test_rects_clamp_the_top_edge_into_the_source():
    ws, hs, ys = zoom.rects(ZoomSpec(start=1.0, end=0.5), crop_w=1000, crop_h=2000,
                            crop_y=0, src_h=2000, times=[0.0, 1.0])
    assert ys == [0, 500]
    assert all(y + h <= 2000 for y, h in zip(ys, hs))


def test_rects_are_derived_from_z_so_they_match_what_ffmpeg_cuts():
    # s = 0.7 -> z = 1/0.7 = 1.428571...; int(1000/z) is 700, and int(1000*0.7) is 699
    # on this arithmetic. The record must follow z, not s (design 3.2).
    ws, _, _ = zoom.rects(ZoomSpec(start=0.7, end=0.5), crop_w=1000, crop_h=2000,
                          crop_y=0, src_h=2160, times=[0.0, 1.0])
    assert ws[0] == int(1000 / (1 / 0.7))


def test_z_expr_evaluates_to_one_over_the_scale_at_both_ends():
    e = zoom.z_expr(ZoomSpec(start=1.0, end=0.5), t0=0.0, t1=2.0)
    assert e.count("it") == 1
    assert eval(e.replace("it", "0.0")) == pytest.approx(1.0, abs=1e-4)
    assert eval(e.replace("it", "2.0")) == pytest.approx(2.0, abs=1e-4)


def test_z_expr_takes_the_variable_name_it_is_given():
    assert "t-" in zoom.z_expr(ZoomSpec(start=1.0, end=0.5), 0.0, 2.0, var="t")


def test_validate_refuses_a_zoom_with_no_duration():
    with pytest.raises(ValueError, match="duration to travel across"):
        zoom.validate(ZoomSpec(start=1.0, end=0.7), crop_w=2000, out_w=1080, dur=0.0)


def test_validate_refuses_a_whip_zoom():
    with pytest.raises(ValueError, match="per second"):
        zoom.validate(ZoomSpec(start=1.0, end=0.2), crop_w=2000, out_w=1080, dur=0.5)


def test_validate_refuses_a_push_in_past_the_upscale_allowance():
    # tightest 600px against a 1080px delivery is 1.8x, past the 1.5x ceiling
    with pytest.raises(ValueError, match="upsampling"):
        zoom.validate(ZoomSpec(start=1.0, end=0.3), crop_w=2000, out_w=1080, dur=4.0)


def test_validate_accepts_a_push_in_inside_the_upscale_allowance():
    # tightest 800px against a 1080px delivery is 1.35x — upsampling, but inside the ceiling
    assert zoom.validate(ZoomSpec(start=1.0, end=0.4), crop_w=2000, out_w=1080,
                         dur=4.0) is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_zoom.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.zoom'`.

- [ ] **Step 3: Write `scripts/lib/zoom.py`**

```python
"""Subject-anchored zoom geometry (design 2026-08-08 §3).

A zoom is a RECT PATH, not a generated one: the layout's crop is the widest rect
the move ever needs (both ends of a ZoomSpec are <= 1.0), every sample cuts a
smaller rect inside it, and that rect's POSITION still comes from the tracked
route through the same composition rule. This module owns the arithmetic only —
reframe owns the ffmpeg strings, the sidecar and the route.
"""
from scripts.lib import geometry as g
from scripts.lib.models import ZoomSpec

ZOOM_MAX_RATE = 0.5      # crop-width fractions per second. FIRST CUT, uncalibrated against any
                         # real shoot (design §10). It exists to catch the absurd — a typo that
                         # turns 0.7 into 0.07 — not to police taste, exactly as PanSpec's speed
                         # cap does for a whip pan.
ZOOM_MAX_UPSCALE = 1.5   # how far past 1:1 a push-in may resample. NOT zero, and the reason is
                         # measured: a 9:16 crop of a 16:9 4K source is 1215px wide against a
                         # 1080px delivery, so refusing every upsample would cap the reel format
                         # this engine exists for at 1.125x — below visibility (design §6). Also
                         # a FIRST CUT: nobody has judged a 1.5x push-in on real graded footage.


def validate(spec: ZoomSpec, crop_w: int, out_w: int, dur: float) -> None:
    """Refuse a zoom this episode cannot carry (design §6, refusals 4-6).

    The three refusals that need the EPISODE's numbers and so cannot live on
    ZoomSpec itself: it validates its own two fractions, this validates them
    against a duration, a crop and a delivery width.
    """
    if dur <= 0:
        raise ValueError(
            f"a zoom needs a duration to travel across and this episode has {dur}s — "
            "the scale would have to change instantaneously. Check the segment probes "
            "to a real duration, or drop the `zoom` field")
    rate = abs(spec.end - spec.start) / dur
    if rate > ZOOM_MAX_RATE:
        raise ValueError(
            f"zoom {spec.start}->{spec.end} over {dur:.3f}s is {rate:.3g} of the crop "
            f"width per second, past the {ZOOM_MAX_RATE} ceiling — that is a lurch, not a "
            "move. Narrow the from->to span, give the episode a longer duration, or check "
            "for a mistyped fraction")
    tightest = int(crop_w / (1.0 / min(spec.start, spec.end)))
    floor = out_w / ZOOM_MAX_UPSCALE
    if tightest < floor:
        raise ValueError(
            f"zoom {spec.start}->{spec.end} tightens the {crop_w}px crop to {tightest}px "
            f"against a {out_w}px delivery — {out_w / tightest:.2f}x upsampling, past the "
            f"{ZOOM_MAX_UPSCALE}x this engine will ship. Past it the reel carries magnified "
            "pixels that were never resolved. Zoom less far, or deliver narrower")


def scales(spec: ZoomSpec, times: list[float]) -> list[float]:
    """s(t), the crop-width fraction in force at each sample — linear in time over
    the route's OWN span, so a zoom always completes exactly at the episode's end."""
    if len(times) < 2:
        raise ValueError(
            f"a zoom needs at least two samples to interpolate across, got {len(times)} — "
            "the route is too short to carry a move")
    t0, t1 = times[0], times[-1]
    if t1 <= t0:
        raise ValueError(
            f"a zoom needs an increasing time span, got {t0} to {t1} — the route's "
            "timestamps are not ordered; re-run tracking")
    k = (spec.end - spec.start) / (t1 - t0)
    return [spec.start + k * (t - t0) for t in times]


def rects(spec: ZoomSpec, crop_w: int, crop_h: int, crop_y: int, src_h: int,
          times: list[float]) -> tuple[list[int], list[int], list[int]]:
    """(widths, heights, top edges) per sample — WHAT FFMPEG WILL CUT, recorded so
    no consumer re-derives it (design §4).

    Each is `int(base / z)`, NOT `round(base * s)`: zoompan is handed `z` and cuts
    `iw/z`, so defining the record from z removes the systematic half of any
    disagreement with the render. The rounding residual remains and is measured,
    not asserted away (design §10).

    The top edge keeps the BASE rect's vertical centre, so a push-in tightens
    around the same point the layout chose rather than drifting up the frame.
    """
    centre_y = crop_y + crop_h / 2
    ws: list[int] = []
    hs: list[int] = []
    ys: list[int] = []
    for s in scales(spec, times):
        z = 1.0 / s
        w = int(crop_w / z)
        h = int(crop_h / z)
        ws.append(w)
        hs.append(h)
        ys.append(int(g.clamp(round(centre_y - h / 2), 0, src_h - h)))
    return ws, hs, ys


def z_expr(spec: ZoomSpec, t0: float, t1: float, var: str = "it") -> str:
    """z(t) = 1/s(t) as a CLOSED-FORM ffmpeg expression.

    Not routed through reframe's piecewise-linear knot builder, for two
    disqualifying reasons (design §3.3): that builder formats knots at `.1f`,
    which would quantize a 1.4286 zoom to 1.4 and put the recorded widths ~30px
    from the rendered rect; and z = 1/s is hyperbolic, so a two-knot linear
    approximation is 6.6% wrong at the midpoint of a 1.0->0.6 push-in.

    Cannot divide by zero: s is linear between two ends both in (0, 1], so it is
    bounded below by min(start, end) > 0.
    """
    if t1 <= t0:
        raise ValueError(f"z_expr needs t1 > t0, got {t0} to {t1}")
    k = (spec.end - spec.start) / (t1 - t0)
    return f"1/({spec.start:.6f}+({k:.6f})*({var}-{t0:.4f}))"
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_zoom.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/zoom.py tests/lib/test_zoom.py
git commit -m "feat(zoom): pure rect + expression arithmetic"
```

---

## Task 3: `compute_path` composes at the width in force

**Files:**
- Modify: `scripts/reframe.py:13-51` (`compute_path`) and its one call site
- Test: `tests/lib/test_reframe.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `compute_path(route, composition, grid, canvas, src, motion, max_step, crop_ws, smooth_window=...)` — `crop_w: int` is **replaced** by `crop_ws: list[int]`, one shape, no union. Every caller passes a list; a constant rect passes `[crop_w] * len(route)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_reframe.py`:

```python
def test_compute_path_places_each_sample_at_its_own_width():
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    wide = reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                                ("static", None), max_step=1e9, crop_ws=[800, 400])
    # a centred crop puts the subject mid-rect: 1000 - 800/2 = 600, then 1000 - 400/2 = 800
    assert wide == [600, 800]


def test_compute_path_refuses_a_width_list_that_is_not_parallel_to_the_route():
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    with pytest.raises(ValueError, match="parallel"):
        reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                             ("static", None), max_step=1e9, crop_ws=[800])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -k compute_path_places -v`
Expected: FAIL — `TypeError: compute_path() got an unexpected keyword argument 'crop_ws'`.

- [ ] **Step 3: Change the signature and the three widths it uses**

In `scripts/reframe.py`, replace the signature line and add the guard:

```python
def compute_path(route: list[dict[str, float]], composition: str, grid: str,
                 canvas: tuple[int, int], src: tuple[int, int],
                 motion: tuple[str, str | None], max_step: float,
                 crop_ws: list[int], smooth_window: int = pathsmooth.DEFAULT_WINDOW) -> list[int]:
    # crop_ws comes from the resolved layout — the caller already cut it; deriving it
    # from `canvas` here would be right only while every layout is `fill`. It is a LIST
    # (one width per route sample), not a scalar, because a zoom varies the rect while
    # the composition rule that places it does not change (design 2026-08-08 §3.2). A
    # constant rect passes [crop_w] * len(route) and behaves exactly as before.
    if len(crop_ws) != len(route):
        raise ValueError(
            f"compute_path: crop_ws must be parallel to the route — got {len(crop_ws)} "
            f"widths for {len(route)} samples")
```

Then the three bodies that used `crop_w`:

```python
        raw = [g.clamp(round(pt["x"] - cw / 2), 0, src[0] - cw)
               for pt, cw in zip(route, crop_ws)]
```

```python
        raw = [g.crop_x(pt["x"], composition, direction, grid, cw, src[0])
               for pt, cw in zip(route, crop_ws)]
```

```python
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame.
    # At zero freedom (crop_w == src_w) this clamps to a constant 0 — a
    # whole-frame layout has nowhere to travel, and needs no special case.
    return [int(g.clamp(round(x), 0, src[0] - cw)) for x, cw in zip(smoothed, crop_ws)]
```

- [ ] **Step 4: Update the one production call site**

In `reframe()`, change `crop_w=rl.crop_w,` to `crop_ws=[rl.crop_w] * len(route_dicts),`.

- [ ] **Step 5: Run reframe's tests and fix every other caller the failures name**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py tests/integration/test_reframe.py -q`
Expected: PASS. Any test still passing `crop_w=` is updated to `crop_ws=[...] * n`
— the point of the atomic rename is that no caller can keep the old spelling.

- [ ] **Step 6: Commit**

```bash
git add scripts/reframe.py tests/lib/test_reframe.py
git commit -m "refactor(zoom): compute_path composes at the width in force"
```

---

## Task 4: `_xexpr` takes a variable name; `_filter_args` takes a zoompan

**Files:**
- Modify: `scripts/reframe.py:179-189` (`_xexpr`), `:339-372` (`_filter_args`)
- Test: `tests/lib/test_reframe.py`

**Interfaces:**
- Produces: `_xexpr(path, times, var="t") -> str`;
  `_filter_args(rl, xexpr, cy, grade, fps, dur, zoom_args="") -> list[str]`.
  `zoom_args` is a complete `zoompan=...` filter string or `""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_reframe.py`:

```python
def test_xexpr_emits_the_variable_it_is_given():
    e = reframe._xexpr([0, 100], [0.0, 1.0], var="it")
    assert "it" in e and "(t-" not in e


def test_filter_args_inserts_the_zoompan_between_crop_and_scale():
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("long_edge", 1920))
    args = reframe._filter_args(rl, "0", 0, "", 30.0, 3.0,
                                zoom_args="zoompan=z='1':x='0':y='0':d=1:s=8x8:fps=30")
    chain = args[1]
    assert chain.index("crop=") < chain.index("zoompan=") < chain.index("scale=")


def test_filter_args_without_a_zoom_is_unchanged():
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("long_edge", 1920))
    assert (reframe._filter_args(rl, "0", 0, "", 30.0, 3.0)
            == reframe._filter_args(rl, "0", 0, "", 30.0, 3.0, zoom_args=""))
    assert "zoompan" not in reframe._filter_args(rl, "0", 0, "", 30.0, 3.0)[1]
```

(If `tests/lib/test_reframe.py` does not already import `layout`, `LayoutSpec`
and `Delivery`, add them to its imports:
`from scripts.lib import layout` and
`from scripts.lib.models import Delivery, LayoutSpec`.)

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -k "xexpr_emits or filter_args_inserts" -v`
Expected: FAIL — `_xexpr() got an unexpected keyword argument 'var'`.

- [ ] **Step 3: Parameterize `_xexpr`**

```python
def _xexpr(path: list[int], times: list[float], var: str = "t") -> str:
    # `var` is the ffmpeg time variable to emit against: `t` for the crop filter,
    # `it` for zoompan, which has no `t`. Same clock either way — crop does not
    # touch timestamps — which is what keeps the base rect and the zoom window
    # from drifting apart (design 2026-08-08 §3.4).
    # piecewise-LINEAR x(t) over simplified knots: lerp inside each segment
    knots = _simplify(path, times)
    if len(knots) == 1:
        return f"{knots[0][1]:.1f}"
    expr = f"{knots[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in zip(knots[-2::-1], knots[:0:-1]):
        slope = (x1 - x0) / max(1e-9, t1 - t0)
        seg = f"({x0:.1f}+({slope:.3f})*({var}-{t0:.4f}))"
        expr = f"if(lt({var},{t1:.4f}),{seg},{expr})"
    return expr
```

- [ ] **Step 4: Thread `zoom_args` through `_filter_args`**

```python
def _filter_args(rl: ResolvedLayout, xexpr: str, cy: int, grade: str,
                 fps: float, dur: float, zoom_args: str = "") -> list[str]:
```

Extend its docstring with:

```
    `zoom_args` is a complete `zoompan=...` filter or "". It sits between the
    crop and the scale in BOTH branches: the crop cuts the widest rect the move
    needs and zoompan cuts the shrinking rect inside it. Its `s` equals the crop
    it consumes, which is forced rather than chosen — zoompan clamps z below 1 to
    1 silently, so an output smaller than its input would render no zoom at all
    (design 2026-08-08 §3.3).
```

and insert it in both returns:

```python
    tail = f"{grade},fps={fps:.6g},format=yuv420p"
    zp = f"{zoom_args}," if zoom_args else ""     # "" keeps the fast path byte-identical
    if rl.fast_path:
        return ["-vf", (f"crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},{zp}"
                        f"scale={rl.out_w}:{rl.out_h},{tail}")]
    rx, ry, rw, rh = rl.rect_px          # the CONTENT rect; the border sits outside it
    b = rl.border_px
    ox, oy, ow, oh = rx - b, ry - b, rw + 2 * b, rh + 2 * b
    bg_chain, fg_src, ov_opts = _background_args(rl, fps, dur)
    pad = f",pad={ow}:{oh}:{b}:{b}:{rl.border_color}" if b else ""
    return ["-filter_complex",
            (f"{bg_chain}"
             f"{fg_src}crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},{zp}"
             f"scale={rw}:{rh}{pad}[fg];"
             f"[bg][fg]overlay={ox}:{oy}{ov_opts},{tail}")]
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -q`
Expected: PASS, including the existing argv-shape tests — the `zp` is empty
without a zoom, so the strings are unchanged.

- [ ] **Step 6: Commit**

```bash
git add scripts/reframe.py tests/lib/test_reframe.py
git commit -m "feat(zoom): _xexpr takes a variable, _filter_args takes a zoompan"
```

---

## Task 5: `reframe()` renders the zoom

**Files:**
- Modify: `scripts/reframe.py` (`reframe()`, the tracked branch and the sidecar)
- Test: `tests/lib/test_reframe.py`

**Interfaces:**
- Consumes: `zoom.validate/rects/z_expr` (Task 2), `_xexpr(var=)` and
  `_filter_args(zoom_args=)` (Task 4), `compute_path(crop_ws=)` (Task 3),
  `PathMeta.crop_ws/hs/ys` (Task 1), `ReframeSpec.zoom` (added here).
- Produces: a `reframe()` that, given `spec.zoom`, emits a zoompan and writes
  the three sidecar arrays.

- [ ] **Step 1: Add `ReframeSpec.zoom`**

In `scripts/lib/models.py`, beside `ReframeSpec.pan`:

```python
    zoom: "ZoomSpec | None" = None   # a subject-anchored push-in/pull-out (design
                                     # 2026-08-08). Requires a route: unlike `pan` it does
                                     # not replace the observation, it rescales the rect the
                                     # observation places.
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/lib/test_reframe.py`. These drive `reframe()` through a stubbed
`proc.run`/`_probe`, asserting on the argv and the sidecar rather than pixels
(the pixels are Task 13):

```python
def test_reframe_refuses_a_zoom_together_with_a_pan():
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"), pan=PanSpec(start=0.0, end=1.0),
                       zoom=ZoomSpec(start=1.0, end=0.7))
    with pytest.raises(ValueError, match="zoom and pan"):
        reframe.reframe(spec, "src.mp4", None, "out.mp4", "path.json")


def test_reframe_emits_a_zoompan_with_every_default_overridden(tmp_path, monkeypatch):
    cmds = []
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: cmds.append(cmd))
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.0))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([
        {"t": 0.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0},
        {"t": 2.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0}]))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"), zoom=ZoomSpec(start=1.0, end=0.7))
    reframe.reframe(spec, "src.mp4", str(route), str(tmp_path / "out.mp4"),
                    str(tmp_path / "path.json"))
    chain = [a for a in cmds[0] if "zoompan=" in a][0]
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("long_edge", 1920))
    # every default overridden, and `s` is the CROP it consumes — not the delivery,
    # which would drive z below 1 and render nothing (design §3.3)
    assert ":d=1:" in chain and ":fps=30" in chain
    assert f":s={rl.crop_w}x{rl.crop_h}" in chain


def test_reframe_writes_the_rect_arrays_into_the_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.0))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([
        {"t": 0.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0},
        {"t": 2.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0}]))
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"), zoom=ZoomSpec(start=1.0, end=0.7))
    reframe.reframe(spec, "src.mp4", str(route), str(tmp_path / "out.mp4"), str(path_out))
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert meta.zoomed is True
    assert meta.crop_ws[0] == meta.crop_w          # starts at the full crop
    assert meta.crop_ws[-1] < meta.crop_w          # and ends tighter
    assert len(meta.crop_ws) == 2


def test_reframe_without_a_zoom_writes_no_arrays(tmp_path, monkeypatch):
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.0))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([
        {"t": 0.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0},
        {"t": 2.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0}]))
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"))
    reframe.reframe(spec, "src.mp4", str(route), str(tmp_path / "out.mp4"), str(path_out))
    assert "crop_ws" not in json.loads(path_out.with_suffix(".meta.json").read_text())
```

These tests need `json`, `layout`, `Delivery`, `LayoutSpec`, `PanSpec`,
`PathMeta` and `ZoomSpec` in the file's imports — add whichever are missing.

- [ ] **Step 3: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -k "zoompan or rect_arrays or zoom_together" -v`
Expected: FAIL — `ReframeSpec` has no `zoom`, then no zoompan in the argv.

- [ ] **Step 4: Implement the branch**

Add `from scripts.lib import zoom as zoom_lib` to `reframe.py`'s imports and
`ZoomSpec` to the `models` import list. In `reframe()`, immediately after
`rl = layout_lib.resolve(...)`:

```python
    if spec.pan is not None and spec.zoom is not None:
        raise ValueError(
            "zoom and pan on one episode: a zoom anchors the rect to a tracked subject "
            "and a pan declares there is none. Keep the zoom (and let the route place "
            "the crop), or keep the pan and drop the zoom")
```

Replace the tracked branch's tail (from `mean_y = ...` onward) with:

```python
        mean_y = sum(p.y for p in route) / len(route)
        cy = g.crop_y(mean_y, rl.crop_h, src_h)
        if spec.zoom is None:
            crop_ws = [rl.crop_w] * len(route)
        else:
            zoom_lib.validate(spec.zoom, rl.crop_w, rl.out_w, dur)
            crop_ws, crop_hs, crop_ys = zoom_lib.rects(
                spec.zoom, rl.crop_w, rl.crop_h, cy, src_h, times)
        path = compute_path(route_dicts, spec.composition, spec.grid, spec.canvas,
                            (src_w, src_h), motion, max_step=spec.max_speed / fps,
                            crop_ws=crop_ws,
                            smooth_window=pathsmooth.window_frames(
                                spec.smooth_window_s, fps))
```

(`times` is already bound above as `[p.t for p in route]`; move that line up so
it precedes the zoom block.)

Then, after `CropPath(path).to_json(path_out)`, build the zoompan:

```python
    zoom_args = ""
    base_xs = path                     # the crop filter's x — the desired rect without a zoom
    if spec.zoom is not None:
        # The base crop is the WIDEST rect (both ends <= 1.0), centred on the rect the
        # composition chose, so the shrinking rect always sits inside it. Proof: if the
        # left clamp bites then x + w/2 - W0/2 < 0, hence x + w < W0/2 + w/2 <= W0; the
        # right edge is symmetric (design 2026-08-08 §3.3).
        base_xs = [int(g.clamp(round(x + w / 2 - rl.crop_w / 2), 0, src_w - rl.crop_w))
                   for x, w in zip(path, crop_ws)]
        xx = [x - a for x, a in zip(path, base_xs)]
        yy = [y - cy for y in crop_ys]
        # EVERY zoompan default is overridden, and all three are silent-corruption
        # landmines: s defaults to hd720 (resizes the episode), fps to 25 (resamples a
        # 60fps clip) and d to 90 (holds each frame 90 output frames). See design §8 —
        # lint.check_argv machine-checks this line.
        zoom_args = (f"zoompan=z='{zoom_lib.z_expr(spec.zoom, times[0], times[-1])}'"
                     f":x='{_xexpr(xx, times, var='it')}'"
                     f":y='{_xexpr(yy, times, var='it')}'"
                     f":d=1:s={rl.crop_w}x{rl.crop_h}:fps={fps:.6g}")
    xexpr = _xexpr(base_xs, times)
```

Delete the old `xexpr = _xexpr(path, times)` line, pass `zoom_args` into
`_filter_args(...)`, and extend the `PathMeta(...)` call:

```python
             pan=spec.pan is not None, stabilized=stabilized,
             crop_ws=crop_ws if spec.zoom is not None else None,
             crop_hs=crop_hs if spec.zoom is not None else None,
             crop_ys=crop_ys if spec.zoom is not None else None,
             ).write(Path(path_out).with_suffix(".meta.json"))
```

Under a pan, `crop_ws`/`crop_hs`/`crop_ys` are never bound; guard by initialising
`crop_ws = crop_hs = crop_ys = None` immediately before the `if spec.pan is not
None:` branch, and have the tracked branch overwrite them.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py tests/integration/test_reframe.py tests/integration/test_pan.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/models.py scripts/reframe.py tests/lib/test_reframe.py
git commit -m "feat(zoom): reframe renders the zoom and records its rects"
```

---

## Task 6: the composition checks take a width per sample

**Files:**
- Modify: `scripts/lib/checks.py` (`on_line`, `centered`, `jitter`)
- Test: `tests/lib/test_checks.py`

**Interfaces:**
- Produces: `on_line(route, path, crop_ws, target_frac, tol=0.05)`,
  `centered(route, path, crop_ws, tol=0.05)`,
  `jitter(path, direction, max_reversal, route=None, route_window=1, crop_ws=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_checks.py`:

```python
def test_on_line_scores_each_sample_against_its_own_width():
    route = [{"x": 500.0}, {"x": 500.0}]
    # rect 1: left 200, width 900 -> frac 0.333; rect 2: left 350, width 450 -> frac 0.333
    assert checks.on_line(route, [200, 350], [900, 450], target_frac=1 / 3)["pass"] is True
    # against a single constant width the second sample would score 0.167 and fail
    assert checks.on_line(route, [200, 350], [900, 900], target_frac=1 / 3)["pass"] is False


def test_on_line_refuses_a_width_list_that_is_not_parallel():
    with pytest.raises(ValueError, match="parallel arrays"):
        checks.on_line([{"x": 1.0}, {"x": 2.0}], [0, 0], [10], target_frac=0.5)


def test_jitter_on_a_constant_width_is_identical_with_and_without_widths():
    path = [0, 10, 8, 20]
    a = checks.jitter(path, "right", max_reversal=5.0)
    b = checks.jitter(path, "right", max_reversal=5.0, crop_ws=[100] * 4)
    assert a == b


def test_jitter_ignores_the_inward_drift_a_push_in_creates():
    # a static subject under a push-in: the LEFT EDGE marches right while the rect's
    # CENTRE stays put, so measuring the edge would report travel that is not there
    ws = [1000, 900, 800, 700]
    path = [0, 50, 100, 150]                      # centre is 500 at every sample
    d = checks.jitter(path, "right", max_reversal=1.0, crop_ws=ws)
    assert d == {"pass": True, "worst_reversal": 0.0, "reversals": 0}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -k "own_width or parallel or push_in or constant_width" -v`
Expected: FAIL — `on_line() got an unexpected keyword` / positional mismatch.

- [ ] **Step 3: Rewrite the three functions**

```python
def on_line(route: list[dict[str, float]], path: list[int], crop_ws: list[int],
            target_frac: float, tol: float = 0.05) -> dict:
    """How often the subject sat on its composition line.

    `crop_ws` is a WIDTH PER SAMPLE, not a scalar: under a zoom the rect the
    subject is judged inside changes while the rule placing it does not (design
    2026-08-08 §5). A constant rect passes [crop_w] * len(path) and scores
    exactly as it did before.
    """
    if len(route) != len(path) or len(crop_ws) != len(path):
        raise ValueError(
            f"route/path/crop_ws must be parallel arrays from the same reframe run: "
            f"{len(route)} vs {len(path)} vs {len(crop_ws)}")
    ok = 0
    for pt, cx, cw in zip(route, path, crop_ws):
        frac = (pt["x"] - cx) / cw
        if abs(frac - target_frac) <= tol:
            ok += 1
    ratio = ok / max(1, len(route))
    return {"pass": ratio >= 0.9, "ratio": ratio}


def centered(route: list[dict[str, float]], path: list[int], crop_ws: list[int],
             tol: float = 0.05) -> dict:
    return on_line(route, path, crop_ws, target_frac=0.5, tol=tol)
```

In `jitter`, add the parameter and derive the series it measures:

```python
def jitter(path: list[int], direction: str, max_reversal: float,
           route: list[dict[str, float]] | None = None,
           route_window: int = 1, crop_ws: list[int] | None = None) -> dict:
```

Extend its docstring with:

```
    With `crop_ws` the reversals are measured on the rect's CENTRE (x + w/2)
    rather than its left edge. For a constant width that is the same series
    shifted by a constant, so every existing verdict is unchanged to the bit;
    under a zoom it is the honest one, because a push-in marches the left edge
    inward even over a motionless subject (design 2026-08-08 §5).
```

and replace the loop's series:

```python
    if crop_ws is not None and len(crop_ws) != len(path):
        raise ValueError(
            f"jitter: crop_ws must be parallel to the path — got {len(crop_ws)} widths "
            f"for {len(path)} samples")
    centres = ([x + w / 2 for x, w in zip(path, crop_ws)] if crop_ws is not None
               else [float(x) for x in path])
    sign = 1 if direction == "right" else -1
    worst = 0.0
    reversals = 0
    use_route = bool(route) and len(route) >= len(path)
    rx = _moving_average([p["x"] for p in route], route_window) if use_route else []
    for i in range(1, len(centres)):
        step = (centres[i] - centres[i - 1]) * sign      # forward = positive
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

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_checks.py -q`
Expected: PASS. Existing `on_line`/`centered` tests that pass a scalar are
updated to a list of that scalar — the atomic change again.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/checks.py tests/lib/test_checks.py
git commit -m "feat(zoom): composition checks judge each sample at its own width"
```

---

## Task 7: the two geometry chokepoints read the recorded rect

**Files:**
- Modify: `scripts/lib/geometry.py` (`marks_at_times`, `extent_at_times`, new `_rect_at`)
- Test: `tests/lib/test_geometry.py`

**Interfaces:**
- Produces: `geometry._rect_at(meta, ts, t) -> tuple[float, float, float]` —
  the `(crop_w, crop_h, crop_y)` in force at time `t`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_geometry.py`:

```python
def _zoom_meta(**over):
    base = dict(mode="fill", crop_w=1000, crop_h=2000, crop_y=0,
                src_dims=(4000, 2000), canvas=(1000, 2000), out_dims=(1000, 2000),
                rect_px=(0, 0, 1000, 2000), freedom=3000,
                crop_ws=[1000, 500], crop_hs=[2000, 1000], crop_ys=[0, 500])
    base.update(over)
    return PathMeta(**base)


def test_marks_use_the_recorded_width_at_that_time():
    route = [RoutePoint(t=0.0, x=500.0, y=1000.0, w=100.0, h=200.0),
             RoutePoint(t=1.0, x=500.0, y=1000.0, w=100.0, h=200.0)]
    path = CropPath([0, 250])
    fx, _ = geometry.marks_at_times(route, path, _zoom_meta(), [1.0])[0]
    # tight rect: (500 - 250) / 500 = 0.5 of the output, not (500 - 250) / 1000 = 0.25
    assert fx == pytest.approx(0.5)


def test_extents_use_the_recorded_rect_at_that_time():
    route = [RoutePoint(t=0.0, x=500.0, y=1000.0, w=100.0, h=200.0),
             RoutePoint(t=1.0, x=500.0, y=1000.0, w=100.0, h=200.0)]
    path = CropPath([0, 250])
    fx0, fy0, fx1, fy1 = geometry.extent_at_times(route, path, _zoom_meta(), [1.0])[0]
    assert fx1 - fx0 == pytest.approx(100 / 500)      # bbox width over the TIGHT rect
    assert fy1 - fy0 == pytest.approx(200 / 1000)


def test_an_unzoomed_meta_still_uses_its_scalars():
    route = [RoutePoint(t=0.0, x=500.0, y=1000.0, w=100.0, h=200.0),
             RoutePoint(t=1.0, x=500.0, y=1000.0, w=100.0, h=200.0)]
    path = CropPath([0, 250])
    meta = _zoom_meta(crop_ws=None, crop_hs=None, crop_ys=None)
    fx, _ = geometry.marks_at_times(route, path, meta, [1.0])[0]
    assert fx == pytest.approx(0.25)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py -k "recorded or unzoomed" -v`
Expected: FAIL — the marks come back at 0.25, the constant-width answer.

- [ ] **Step 3: Add `_rect_at` and route both helpers through it**

Above `marks_at_times`:

```python
def _rect_at(meta: "PathMeta", ts: list[float], t: float) -> tuple[float, float, float]:
    """The (crop_w, crop_h, crop_y) in force at time `t`.

    The scalars for a constant rect; the sidecar's parallel arrays, interpolated
    on the route's own timestamps, under a zoom. Every consumer that divides by a
    crop dimension goes through here, which is why fixing these two helpers also
    fixes safezones, key_action, the storyboard's marks and check_reel's geometry
    section without any of them learning that zoom exists (design 2026-08-08 §5).
    """
    if meta.crop_ws is None:
        return float(meta.crop_w), float(meta.crop_h), float(meta.crop_y)
    return (_interp(ts, [float(v) for v in meta.crop_ws], t),
            _interp(ts, [float(v) for v in meta.crop_hs], t),
            _interp(ts, [float(v) for v in meta.crop_ys], t))
```

In `marks_at_times`, inside the loop:

```python
    for t in times:
        x = _interp(ts, xs, t)
        y = _interp(ts, ys, t)
        cx = _interp(ts, cxs, t)
        cw, ch, cyy = _rect_at(meta, ts, t)
        fx = (rx + rw * (x - cx) / cw) / out_w
        fy = (ry + rh * (y - cyy) / ch) / out_h
        marks.append((fx, fy))
```

In `extent_at_times`, inside the loop:

```python
        cx = _interp(ts, cxs, t)
        cw, ch, cyy = _rect_at(meta, ts, t)
        fx0 = (rx + rw * ((x - w / 2) - cx) / cw) / out_w
        fx1 = (rx + rw * ((x + w / 2) - cx) / cw) / out_w
        fy0 = (ry + rh * ((y - h / 2) - cyy) / ch) / out_h
        fy1 = (ry + rh * ((y + h / 2) - cyy) / ch) / out_h
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_geometry.py tests/lib/test_safezones.py tests/lib/test_reel_final.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/geometry.py tests/lib/test_geometry.py
git commit -m "feat(zoom): marks and extents read the recorded rect"
```

---

## Task 8: `check_episode` judges a zoom like any tracked episode

**Files:**
- Modify: `scripts/check_episode.py` (`run`)
- Test: `tests/integration/test_check_episode.py`

**Interfaces:**
- Consumes: `PathMeta.crop_ws`/`zoomed` (Task 1), the new
  `on_line`/`centered`/`jitter` signatures (Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_check_episode.py`. These construct the
sidecar and path directly, so no encode is needed beyond the fixture clip the
file already builds:

```python
def test_a_zoomed_episode_is_judged_on_composition_not_excused(tmp_path, sample_clip):
    # a zero-freedom layout that WOULD have reported editorial-only: under a zoom the
    # push-in creates the freedom the layout lacked, so the check applies
    route = [{"t": 0.0, "x": 320.0, "y": 240.0, "w": 60.0, "h": 120.0},
             {"t": 1.0, "x": 320.0, "y": 240.0, "w": 60.0, "h": 120.0}]
    rp = tmp_path / "route.json"
    rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"
    pp.write_text(json.dumps([0, 80]))
    PathMeta(mode="fill", crop_w=640, crop_h=480, crop_y=0, src_dims=(640, 480),
             canvas=(640, 480), out_dims=(640, 480), rect_px=(0, 0, 640, 480),
             freedom=0, crop_ws=[640, 480], crop_hs=[480, 360], crop_ys=[0, 60]
             ).write(pp.with_suffix(".meta.json"))
    rep = check_episode.run(str(sample_clip), str(rp), str(pp),
                            CheckSpec(composition="center", grid="thirds", target_dur=1.0),
                            str(tmp_path / "report.json"))
    assert "centered" in rep.checks
    assert rep.checks["centered"].passed is not None


def test_an_unzoomed_zero_freedom_episode_is_still_editorial_only(tmp_path, sample_clip):
    route = [{"t": 0.0, "x": 320.0, "y": 240.0, "w": 60.0, "h": 120.0},
             {"t": 1.0, "x": 320.0, "y": 240.0, "w": 60.0, "h": 120.0}]
    rp = tmp_path / "route.json"
    rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"
    pp.write_text(json.dumps([0, 0]))
    PathMeta(mode="fill", crop_w=640, crop_h=480, crop_y=0, src_dims=(640, 480),
             canvas=(640, 480), out_dims=(640, 480), rect_px=(0, 0, 640, 480),
             freedom=0).write(pp.with_suffix(".meta.json"))
    rep = check_episode.run(str(sample_clip), str(rp), str(pp),
                            CheckSpec(composition="center", grid="thirds", target_dur=1.0),
                            str(tmp_path / "report.json"))
    assert rep.checks["framing"].detail["reason"] == "no horizontal freedom"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/integration/test_check_episode.py -k "zoomed or zero_freedom" -v`
Expected: FAIL — `centered` is absent because the `freedom == 0` arm fired.

- [ ] **Step 3: Wire the widths and narrow the arm**

In `run()`, directly after `crop_w = meta.crop_w`:

```python
    # One width per sample: the scalars for a constant rect, the sidecar's record under a
    # zoom. Built once here so every check below is handed the same series (design §5).
    crop_ws = meta.crop_ws or [meta.crop_w] * len(path)
```

Replace the `freedom == 0` arm's condition and comment:

```python
    elif meta.freedom == 0 and not meta.zoomed:
        # the crop is as wide as the source: nobody controls composition, so it
        # can neither be failed nor silently passed (design 2026-07-10 §6). A ZOOM
        # is the exception: a push-in creates the freedom the layout did not have,
        # so the composition it produces is real and gets judged (design 2026-08-08 §5).
```

Pass the widths at the three call sites:

```python
        d = checks_mod.centered(route, path, crop_ws)
```
```python
        d = checks_mod.on_line(route, path, crop_ws, tf)
```
```python
    dj = checks_mod.jitter(path, direction, max_reversal=max(2.0, crop_w * 0.005),
                           route=route or None, route_window=_route_window(route),
                           crop_ws=crop_ws)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_check_episode.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_episode.py tests/integration/test_check_episode.py
git commit -m "feat(zoom): check_episode judges a zoomed episode in full"
```

---

## Task 9: the authoring path carries `zoom`, and the manifest gate refuses the contradictions

**Files:**
- Modify: `scripts/lib/manifest.py` (`OPTIONAL`, `Manifest`, `from_dict`, `validate`)
- Modify: `scripts/lib/edl.py` (`EDLEpisode`, `to_dict`, `from_dict`, `to_markdown`, `to_manifest_dict`)
- Test: `tests/lib/test_manifest.py`, `tests/lib/test_edl.py`

**Interfaces:**
- Produces: `Manifest.zoom: dict | None`, `EDLEpisode.zoom: dict | None`, both
  raw wire dicts built into a `ZoomSpec` by `process_episode` (Task 10).

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_manifest.py`:

```python
def test_manifest_refuses_a_zoom_beside_a_pan():
    m = _valid_manifest(pan={"from": 0.0, "to": 1.0}, zoom={"from": 1.0, "to": 0.7})
    assert any("zoom and pan" in p for p in manifest.validate(m))


def test_manifest_refuses_a_pan_beside_a_hero_pin():
    m = _valid_manifest(pan={"from": 0.0, "to": 1.0}, hero=(0.5, 0.5))
    assert any("declares the shot has no subject" in p for p in manifest.validate(m))


def test_manifest_refuses_a_pan_beside_a_cast_name():
    m = _valid_manifest(pan={"from": 0.0, "to": 1.0}, hero="Sergei", cast="cast.json")
    assert any("declares the shot has no subject" in p for p in manifest.validate(m))


def test_manifest_uses_zoomspec_as_its_oracle():
    m = _valid_manifest(zoom={"from": 1.2, "to": 0.7})
    assert any("within (0.0, 1.0]" in p for p in manifest.validate(m))


def test_manifest_round_trips_the_zoom_dict():
    m = manifest.Manifest.from_dict(_valid_dict(zoom={"from": 1.0, "to": 0.7}))
    assert m.zoom == {"from": 1.0, "to": 0.7}
```

(`_valid_manifest` / `_valid_dict` are this file's existing helpers; if they are
named differently, use the file's own convention and keep the assertions.)

Append to `tests/lib/test_edl.py`:

```python
def test_edl_episode_round_trips_a_zoom():
    e = _episode(zoom={"from": 1.0, "to": 0.7})
    assert e.to_dict()["zoom"] == {"from": 1.0, "to": 0.7}
    assert edl.EDLEpisode.from_dict(e.to_dict()) == e


def test_edl_markdown_names_the_zoom_beside_the_motion():
    doc = edl.EDL(episodes=[_episode(zoom={"from": 1.0, "to": 0.7})],
                  canvas=(1080, 1920), delivery="1080").to_markdown()
    assert "zoom 1.0→0.7" in doc


def test_manifest_dict_carries_the_zoom_through():
    md = edl.to_manifest_dict(_episode(zoom={"from": 1.0, "to": 0.7}),
                              canvas=(1080, 1920), delivery="1080",
                              segment="seg.mp4", out_path="out.mp4", target_dur=3.0)
    assert md["zoom"] == {"from": 1.0, "to": 0.7}
```

(Match `_episode` and `to_manifest_dict`'s real signature in the file — the
assertions are what matter.)

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py tests/lib/test_edl.py -k zoom -v`
Expected: FAIL — unexpected keyword argument `zoom`.

- [ ] **Step 3: `manifest.py`**

Add `"zoom"` to `OPTIONAL` (after `"pan"`), import `ZoomSpec` beside `PanSpec`,
add the field below `pan`:

```python
    zoom: dict | None = None         # {"from": f, "to": f} — a SUBJECT-ANCHORED push-in
                                     # (design 2026-08-08). Raw wire dict here, built into a
                                     # ZoomSpec by process_episode, exactly as `pan` is.
```

Add `zoom=d.get("zoom"),` to `from_dict` beside `pan=d.get("pan"),`.

In `validate`, directly after the existing `if m.pan is not None:` block:

```python
    if m.pan is not None and (m.hero is not None or m.cast):
        problems.append(
            "pan with a hero pin: a pan declares the shot has no subject to follow — it "
            "turns off framing, continuity and colour-fidelity — and a pin names one. Drop "
            "the pan and let the tracked route place the crop, or drop the pin "
            "(design 2026-08-08 §2.2)")
    if m.zoom is not None:
        if m.pan is not None:
            problems.append(
                "zoom and pan on one episode: a zoom anchors the rect to a tracked subject "
                "and a pan declares there is none. Keep one")
        # ZoomSpec is the HARD backstop; here it is the soft gate's oracle — the same
        # PanSpec/LayoutSpec pattern used above. One constructor for validation and for
        # the shell's real build, so the two cannot drift apart.
        try:
            ZoomSpec.from_dict(m.zoom)
        except ValueError as e:
            problems.append(str(e))
```

- [ ] **Step 4: `edl.py`**

Add the field beside `pan`:

```python
    zoom: dict | None = None  # {"from": f, "to": f} — a SUBJECT-ANCHORED push-in/pull-out
                              # (design 2026-08-08). NOT validated here: like `pan`, its one
                              # home is the manifest gate reached via preflight, which uses
                              # ZoomSpec as its oracle.
```

In `to_dict`, add `"zoom": self.zoom,` beside `"pan": self.pan,`. In `from_dict`
(wherever `pan` is read) add the matching `zoom=d.get("zoom")`.

In `to_markdown`, extend the block that composes the motion cell:

```python
            if e.zoom is not None:
                zm = f"zoom {e.zoom.get('from')}→{e.zoom.get('to')}"
                motion = zm if motion == "–" else f"{motion} · {zm}"
```

In `to_manifest_dict`, beside the `pan` line:

```python
    if ep.zoom is not None:
        md["zoom"] = ep.zoom
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py tests/lib/test_edl.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/manifest.py scripts/lib/edl.py tests/lib/test_manifest.py tests/lib/test_edl.py
git commit -m "feat(zoom): EDL and manifest carry zoom; the gate refuses pan+hero"
```

---

## Task 10: `process_episode` builds and preflights the `ZoomSpec`

**Files:**
- Modify: `scripts/process_episode.py`
- Test: `tests/integration/test_process_episode.py`

**Interfaces:**
- Consumes: `Manifest.zoom` (Task 9), `zoom.validate` (Task 2),
  `ReframeSpec.zoom` (Task 5).

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_process_episode.py`:

```python
def test_process_episode_preflights_an_impossible_zoom(tmp_path, sample_clip):
    m = _manifest(tmp_path, sample_clip, zoom={"from": 1.0, "to": 0.05})
    res = process_episode.process_episode(m, str(tmp_path / "ep"))
    assert res["status"] == "stop_and_report"
    assert "upsample" in json.dumps(res)
```

(Use the file's own manifest-building helper and its own stop-and-report shape;
what must hold is that the refusal arrives BEFORE any encode, as the pan
preflight already does.)

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -k impossible_zoom -v`
Expected: FAIL — the zoom is ignored and the episode renders.

- [ ] **Step 3: Build it beside the pan**

Add `ZoomSpec` to the `models` import and `from scripts.lib import zoom as zoom_lib`.
Beside `pan = PanSpec.from_dict(m.pan) if m.pan is not None else None`:

```python
    # the zoom is editorial intent, not a retry parameter — build it once, beside the pan,
    # so the ladder below can never mutate it
    zoom = ZoomSpec.from_dict(m.zoom) if m.zoom is not None else None
```

In the preflight block that already calls `reframe.generate_pan_path` for a pan,
add the zoom's own (it needs the same resolved layout and probed duration):

```python
    if zoom is not None:
        # Same shape as the pan preflight above: the HARD engine gate needs numbers only
        # reframe has, so run it here, before any encode, rather than let a doomed zoom
        # cost a render first.
        zoom_lib.validate(zoom, rl.crop_w, rl.out_w, _dur)
```

Thread it into the `ReframeSpec(...)` build: `pan=pan, zoom=zoom)`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/process_episode.py tests/integration/test_process_episode.py
git commit -m "feat(zoom): process_episode builds and preflights the zoom"
```

---

## Task 11: the measured pan gate

**Files:**
- Modify: `scripts/edit_plan.py` (`window_to_episode`, `_merge_windows`)
- Test: `tests/lib/test_edit_plan.py`

**Interfaces:**
- Produces: `edit_plan.PAN_PRESENCE_MAX: float`; a `ValueError` from
  `window_to_episode` when a `pan` is authored over a people-bearing window.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`:

```python
def test_window_to_episode_refuses_a_pan_over_a_window_holding_people():
    clip = _clip(windows=[_window(present=0.8)])
    with pytest.raises(ValueError, match="holds people in 80%"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                    grid="thirds", pan={"from": 0.0, "to": 1.0})


def test_window_to_episode_allows_a_pan_over_an_empty_window():
    clip = _clip(windows=[_window(present=0.0)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                     grid="thirds", pan={"from": 0.0, "to": 1.0})
    assert ep.pan == {"from": 0.0, "to": 1.0}


def test_window_to_episode_leaves_a_people_bearing_window_alone_without_a_pan():
    clip = _clip(windows=[_window(present=0.8)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                     grid="thirds")
    assert ep.pan is None


def test_merged_window_reports_the_busiest_presence_in_the_span():
    clip = _clip(windows=[_window(present=0.0, start=0.0, dur=2.0),
                          _window(present=0.9, start=2.0, dur=2.0)])
    merged = edit_plan._merge_windows(clip, 0, 1)
    assert merged.present == 0.9
```

(`_clip` / `_window` are this file's existing builders; give `_window` a
`present=` passthrough if it does not have one.)

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "pan or busiest" -v`
Expected: FAIL — the pan is accepted; the merged window reports 0.0.

- [ ] **Step 3: Add the constant and the gate**

Near the top of `scripts/edit_plan.py`:

```python
PAN_PRESENCE_MAX = 0.10   # fraction of a window's samples holding >= 1 person. Above this a
                          # `pan` is refused: a pan DECLARES the shot has no subject, and that
                          # declaration turns off three of check_episode's checks (design
                          # 2026-08-08 §2). FIRST CUT, uncalibrated — it encodes a judgement
                          # about what "incidental" means, not a measurement.
```

In `window_to_episode`, directly before the `defaults = {...}` line:

```python
    if editorial.get("pan") is not None and window.present > PAN_PRESENCE_MAX:
        raise ValueError(
            f"window_to_episode: this window holds people in {window.present:.0%} of its "
            f"samples, above the {PAN_PRESENCE_MAX:.0%} a `pan` may be authored over — a pan "
            "declares the shot has no subject to follow, and on that declaration "
            "check_episode reports framing editorial-only, continuity not-checked and "
            "colour-fidelity not-checked. Drop the `pan` and let the tracked route place the "
            "crop, or reference a window intake measured as empty")
```

Extend the function's docstring with:

```
    A `pan` is refused over a window intake measured as holding people
    (PAN_PRESENCE_MAX) — this is the one site that sees both the requested
    editorial fields and the measured window, which is why the gate lives here
    and not in EDLEpisode or the manifest (design 2026-08-08 §2.1).
```

In `_merge_windows`, take the busiest presence across the span:

```python
    tids = sorted({t for w in wins for t in w.track_ids})
    # the busiest sample in the span, not window i's: a span that starts empty and fills
    # with people would otherwise report the empty window's presence and slip the pan gate
    # past a shot full of subjects (design 2026-08-08 §2.3)
    present = max(w.present for w in wins)
```

and add `present=present` to the `dataclasses.replace(...)` call.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py tests/integration/test_edit_plan.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat(pan): refuse a pan over a window intake measured as peopled"
```

---

## Task 12: the fifth landmine check

**Files:**
- Modify: `scripts/lib/lint.py`
- Test: `tests/lib/test_lint.py`

**Interfaces:**
- Produces: `lint._zoompan_defaults(cmd) -> list[str]`, added to `check_argv`'s
  tuple.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_lint.py`:

```python
def test_zoompan_without_an_explicit_size_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1.2':x='0':y='0':d=1:fps=30", "o.mp4"])
    assert any("s=" in m for m in out)


def test_zoompan_without_an_explicit_fps_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1.2':x='0':y='0':d=1:s=100x200", "o.mp4"])
    assert any("fps=" in m for m in out)


def test_zoompan_without_an_explicit_d_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1.2':x='0':y='0':s=100x200:fps=30", "o.mp4"])
    assert any("d=" in m for m in out)


def test_a_fully_specified_zoompan_is_clean():
    assert lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                            "crop=100:200:x='0':y=0,"
                            "zoompan=z='1.2':x='0':y='0':d=1:s=100x200:fps=30,"
                            "scale=50:100", "o.mp4"]) == []


def test_each_zoompan_in_a_chain_is_judged_on_its_own_segment():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1':x='0':y='0':d=1:s=10x20:fps=30,"
                           "zoompan=z='1':x='0':y='0':d=1:fps=30", "o.mp4"])
    assert len(out) == 1 and "#2 of 2" in out[0]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -k zoompan -v`
Expected: FAIL — `check_argv` returns `[]` for all of them.

- [ ] **Step 3: Add the check**

```python
_ZOOMPAN_REQUIRED = ("s=", "fps=", "d=")


def _zoompan_defaults(cmd: list[str]) -> list[str]:
    """§12: zoompan's three defaults each corrupt SILENTLY (design 2026-08-08 §8).

    `s` defaults to hd720 — the episode is resized to 1280x720. `fps` defaults to
    25 — a 60fps clip is resampled. `d` defaults to 90 — every input frame is held
    for 90 output frames. None of the three errors; all three ship wrong pixels.

    Split on the filter name so EACH zoompan is judged on its own segment, and
    bound that segment at the next graph separator so a neighbour's `fps=` cannot
    exempt it — the same two rules _drawtext_font and _unbounded_source follow.

    What this CANNOT check is the fourth trap: zoompan clamps a `z` below 1 to 1
    byte-identically, and z is a runtime expression, not a literal. Its detector
    is the pixel proof in tests/integration/test_zoom.py.
    """
    out: list[str] = []
    for a in cmd:
        segs = a.split("zoompan=")[1:]
        for n, seg in enumerate(segs, 1):
            body = _element(seg, 0)
            missing = [k for k in _ZOOMPAN_REQUIRED if k not in body]
            if missing:
                out.append(
                    f"zoompan #{n} of {len(segs)} omits {', '.join(missing)} (segment: "
                    f"{('zoompan=' + seg)[:48]!r}) in {a!r} — design §12: zoompan's "
                    "defaults are s=hd720, fps=25 and d=90, each of which silently "
                    "resizes, resamples or stalls the episode. Pass all three explicitly.")
    return out
```

and add it to the tuple:

```python
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font,
                  _zoompan_defaults):
```

- [ ] **Step 4: Run the tests, then the whole suite's argv guard**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py tests/lib/test_landmine_scan.py -q`
Expected: PASS — including the scan that runs the predicate over every argv the
suite issues, which is what proves Task 5's zoompan satisfies it.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -m "feat(lint): zoompan must carry s, fps and d"
```

---

## Task 13: the real-ffmpeg proofs

**Files:**
- Create: `tests/integration/test_zoom.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the proofs**

Create `tests/integration/test_zoom.py`. The fixture is a synthetic clip with a
bright square on a dark field, so the subject's on-screen width is measurable
from the delivered pixels:

```python
"""Real-ffmpeg proofs for the subject-anchored zoom (design 2026-08-08 §9).

No stubs: every assertion here is about pixels ffmpeg actually produced, because
the one trap the lint cannot reach — zoompan clamping z below 1 to 1, byte
identically — is invisible to any argv-level check.
"""
import json

import pytest
from PIL import Image

from scripts import reframe
from scripts.lib import assembly, ffbin, proc
from scripts.lib.models import (CropPath, Delivery, LayoutSpec, PathMeta, ReframeSpec,
                                ZoomSpec)

pytestmark = pytest.mark.integration


@pytest.fixture
def marked_clip(tmp_path):
    """2s, 30fps, 640x480: a 64px white square centred on black."""
    out = tmp_path / "marked.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", "color=c=black:s=640x480:r=30:d=2",
              "-f", "lavfi", "-i", "color=c=white:s=64x64:r=30:d=2",
              "-filter_complex", "[0][1]overlay=288:208",
              "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)])
    return out


def _route(tmp_path):
    p = tmp_path / "route.json"
    p.write_text(json.dumps([
        {"t": 0.0, "x": 320.0, "y": 240.0, "w": 64.0, "h": 64.0},
        {"t": 1.0, "x": 320.0, "y": 240.0, "w": 64.0, "h": 64.0},
        {"t": 2.0, "x": 320.0, "y": 240.0, "w": 64.0, "h": 64.0}]))
    return p


def _spec(**over):
    # long_edge=240 (not native) on purpose: `zoom.validate` refuses a push-in that
    # upsamples past ZOOM_MAX_UPSCALE, and a native delivery makes the crop and the
    # output the same width, leaving no room at all (design 2026-08-08 §6).
    base = dict(composition="center", grid="thirds", canvas=(640, 480),
                color_means=(105, 122, 137), delivery=Delivery("long_edge", 240),
                layout=LayoutSpec(mode="fill"))
    base.update(over)
    return ReframeSpec(**base)


def _white_width(clip, t):
    """Width in output px of the white square at time t."""
    png = f"{clip}.{t}.png"
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(clip), "-ss", f"{t:.3f}",   # -ss AFTER -i (§12)
              "-frames:v", "1", png])
    im = Image.open(png).convert("L")
    cols = [x for x in range(im.width)
            if max(im.crop((x, 0, x + 1, im.height)).getdata()) > 200]
    return (max(cols) - min(cols) + 1) if cols else 0


def test_a_push_in_really_magnifies_the_subject(tmp_path, marked_clip):
    out = tmp_path / "zoomed.mp4"
    reframe.reframe(_spec(zoom=ZoomSpec(start=1.0, end=0.6)), str(marked_clip),
                    str(_route(tmp_path)), str(out), str(tmp_path / "path.json"))
    first, last = _white_width(out, 0.05), _white_width(out, 1.95)
    assert first > 0
    # 1/0.6 = 1.67x, allowing for the encode's edge softening and int rounding
    assert last / first == pytest.approx(1 / 0.6, rel=0.12)


def test_the_recorded_widths_match_the_rendered_rect(tmp_path, marked_clip):
    path_out = tmp_path / "path.json"
    out = tmp_path / "zoomed.mp4"
    reframe.reframe(_spec(zoom=ZoomSpec(start=1.0, end=0.6)), str(marked_clip),
                    str(_route(tmp_path)), str(out), str(path_out))
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    # the subject is 64 source px wide; on screen it occupies 64/rect_w of the output
    for t, i in ((0.05, 0), (1.95, -1)):
        expected = 64 * meta.out_dims[0] / meta.crop_ws[i]
        assert _white_width(out, t) == pytest.approx(expected, abs=4)


def test_a_zoom_changes_neither_the_dimensions_nor_the_frame_count(tmp_path, marked_clip):
    plain, zoomed = tmp_path / "plain.mp4", tmp_path / "zoomed.mp4"
    reframe.reframe(_spec(), str(marked_clip), str(_route(tmp_path)), str(plain),
                    str(tmp_path / "p1.json"))
    reframe.reframe(_spec(zoom=ZoomSpec(start=1.0, end=0.6)), str(marked_clip),
                    str(_route(tmp_path)), str(zoomed), str(tmp_path / "p2.json"))
    a, b = assembly.probe_stream(str(plain)), assembly.probe_stream(str(zoomed))
    assert (a.w, a.h, a.fps) == (b.w, b.h, b.fps)
    assert abs(assembly.probe_duration(str(plain))
               - assembly.probe_duration(str(zoomed))) < 0.05


def test_a_pull_out_moves_the_pixels_too(tmp_path, marked_clip):
    """The z-clamp trap's other face: a pull-out is authored 0.6 -> 1.0, and it must
    render, not collapse to a still frame."""
    out = tmp_path / "pulled.mp4"
    reframe.reframe(_spec(zoom=ZoomSpec(start=0.6, end=1.0)), str(marked_clip),
                    str(_route(tmp_path)), str(out), str(tmp_path / "path.json"))
    assert _white_width(out, 1.95) < _white_width(out, 0.05)
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_zoom.py -v`
Expected: 4 passed. If `test_a_push_in_really_magnifies_the_subject` reports a
ratio of exactly 1.0, the `z` expression collapsed — check that `z_expr` emits
`it` and that `s=` equals the crop, not the delivery.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_zoom.py
git commit -m "test(zoom): real-ffmpeg proof the rect shrank and the record matches"
```

---

## Task 14: mutation battery, full suite, docs sync

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`,
  `docs/fixes-backlog.md`, `skills/edit-plan/SKILL.md`

- [ ] **Step 1: Run the mutation battery**

Each row breaks one production line, runs the named test, confirms it FAILS,
then reverts with `git checkout -- <file>`. A row that passes with the mutation
in place is a hole: fix the test before continuing.

| # | Mutation | Must fail |
|---|---|---|
| 1 | `zoom.rects`: `w = int(crop_w * s)` instead of `int(crop_w / z)` | `tests/lib/test_zoom.py::test_rects_are_derived_from_z_so_they_match_what_ffmpeg_cuts` |
| 2 | `zoom.z_expr`: drop the `1/`, return `s(t)` | `tests/integration/test_zoom.py::test_a_push_in_really_magnifies_the_subject` |
| 3 | `reframe`: `s={rl.out_w}x{rl.out_h}` instead of the crop | `tests/integration/test_zoom.py::test_a_push_in_really_magnifies_the_subject` |
| 4 | `reframe`: drop `:d=1` from the zoompan | `tests/lib/test_lint.py::test_zoompan_without_an_explicit_d_is_flagged` **and** `tests/lib/test_landmine_scan.py` |
| 5 | `reframe`: `_xexpr(xx, times)` without `var='it'` | `tests/integration/test_zoom.py::test_a_push_in_really_magnifies_the_subject` |
| 6 | `reframe`: `base_xs = path` under a zoom (skip the containment centring) | `tests/integration/test_zoom.py::test_the_recorded_widths_match_the_rendered_rect` |
| 7 | `checks.on_line`: use `crop_ws[0]` for every sample | `tests/lib/test_checks.py::test_on_line_scores_each_sample_against_its_own_width` |
| 8 | `checks.jitter`: measure `path` instead of `centres` | `tests/lib/test_checks.py::test_jitter_ignores_the_inward_drift_a_push_in_creates` |
| 9 | `geometry._rect_at`: always return the scalars | `tests/lib/test_geometry.py::test_marks_use_the_recorded_width_at_that_time` |
| 10 | `check_episode`: drop `and not meta.zoomed` | `tests/integration/test_check_episode.py::test_a_zoomed_episode_is_judged_on_composition_not_excused` |
| 11 | `edit_plan`: `window.present >= 1.0` in the gate | `tests/lib/test_edit_plan.py::test_window_to_episode_refuses_a_pan_over_a_window_holding_people` |
| 12 | `edit_plan._merge_windows`: drop `present=present` | `tests/lib/test_edit_plan.py::test_merged_window_reports_the_busiest_presence_in_the_span` |
| 13 | `manifest.validate`: drop the pan+hero arm | `tests/lib/test_manifest.py::test_manifest_refuses_a_pan_beside_a_hero_pin` |
| 14 | `PathMeta.to_dict`: emit the arrays unconditionally | `tests/lib/test_models.py::test_path_meta_without_a_zoom_is_not_zoomed_and_writes_no_zoom_keys` |

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: every test passes; the baseline before this slice is **2423 passed,
3 skipped**. Report the new counts. No golden may move — a moved golden means
the unzoomed path changed, which the Global Constraints forbid.

- [ ] **Step 3: `docs/build-status.md`**

Add a Done entry at the top of `## Done`, dated 2026-08-08, naming: the dead
premise the run exposed (three checks off on the author's word); the two halves;
the four measured zoompan landmines; and the honest limits from design §10 —
the footage-less door's remaining hole, the two uncalibrated constants, the
≤1px record-vs-render residual, the second resample, presence as a people-only
proxy, and that the gate proves the premise, never the taste.

Update `## Next action`: #17 moves to done; name what remains of playbook
priority 4 (#7 speed ramp, #9 effects library + mood palettes, #10 cheap
3-frame preview, and the rest of #18).

- [ ] **Step 4: `docs/pipeline-map.md`**

Update the reframe/check_episode rows to say that a frame move is either
subject-anchored (fully checked) or scenery (measured subject-less).

- [ ] **Step 5: `CLAUDE.md`**

Add two Quick Reference rows — the design and this plan — in the established
one-line-summary style, and add the zoompan trap to the always-loaded **Known
troubles** list, since it corrupts silently:

```markdown
- `zoompan` needs explicit `s=`/`fps=`/`d=` — the defaults (hd720 / 25fps /
  90-frame hold) silently resize, resample and stall. And it clamps `z` below 1
  to 1 **byte-identically**, so a pull-out expressed as a shrink renders nothing.
```

- [ ] **Step 6: `docs/fixes-backlog.md`**

Mark #17 ✅ LANDED with the design/plan paths, and note under #18 that the
frame-moving half is closed while the speed ramp and the look filters are not.

- [ ] **Step 7: `skills/edit-plan/SKILL.md`**

Add the authoring guidance: `zoom` is `{"from": 1.0, "to": 0.7}` fractions of
the crop width, needs a tracked subject, and stays inside every check; `pan` may
be authored only over a window `FOOTAGE.md` shows as empty of people, and
`edit_plan build` will refuse it otherwise.

- [ ] **Step 8: Commit**

```bash
git add docs CLAUDE.md skills/edit-plan/SKILL.md
git commit -m "docs(moves): status, registry, backlog, skill guidance"
```

---

## Self-Review

**Spec coverage.** §1 the rule → Tasks 8/11 (the two halves' enforcement).
§2.1 measured gate → Task 11. §2.2 declared gate → Task 9. §2.3 span-merge
presence → Task 11. §2.4 arm comments → Task 8. §3.1 `ZoomSpec` → Task 0.
§3.2 rect geometry → Tasks 2/3/5. §3.3 render chain → Tasks 4/5. §3.4 the clock
→ Task 4 (`var`) + Task 13 (its detector). §4 path contract → Task 1.
§5 the checks → Tasks 6/7/8. §6 refusals 1-3 → Tasks 0/5/9; 4-6 → Task 2; 7 →
Tasks 9/11. §8 landmine registry → Tasks 12 and 14 step 5. §9 proofs 1-4 →
Task 13; proof 5 → Tasks 9/11; proof 6 → Task 13's push-in test. §10 honest
limits → Task 14 step 3. §11 deferred → nothing built, correctly.

**Placeholder scan.** Clean — every step carries the code it asks for. Task 5's
`s=` assertion derives the expected crop from `layout.resolve` rather than
hardcoding a width, because `geometry.even` rounds a 9:16 crop of 4K and the
literal would be a guess.

**Type consistency.** `crop_ws` is `list[int]` in `compute_path` (Task 3),
`checks.on_line`/`centered` (Task 6) and `PathMeta` (Task 1); `jitter` takes it
as `list[int] | None` because absent legitimately means "left edge, as before".
`zoom.rects` returns `(list[int], list[int], list[int])` in the order
widths/heights/top-edges, and Task 5 unpacks it as `crop_ws, crop_hs, crop_ys`.
`z_expr(spec, t0, t1, var="it")` is called with positional times in Task 5 and
with `var="t"` only in its own test. `ZoomSpec` is spelled with `start`/`end`
fields and `from`/`to` wire keys everywhere.
