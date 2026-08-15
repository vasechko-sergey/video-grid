# Frame probe + look gate — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render three frames of one episode through the SAME chain `reframe` would
encode, so a grade converges without re-rendering a reel — and prove, after the
encode, that the look `deliver` declared actually reached the delivered pixels.

**Architecture:** `reframe()`'s middle becomes `plan_render()` returning a
`RenderPlan`; `reframe()` is that plan plus an x264 sink, the probe is that plan plus
a `select` sink into PNGs. One chain builder, two sinks — a probe that rebuilt the
chain from `path.meta.json` would drift and then lie. A new pure `lib/lookcheck.py`
measures the delivered reel against its master and `deliver` refuses on a declared
effect that changed nothing.

**Tech Stack:** Python 3.13, ffmpeg via `lib/ffbin` + `lib/proc`, numpy, Pillow,
pytest. Scripts run as modules (`pythonpath = .`); the interpreter is `.venv/bin/python`.

**Design:** [docs/specs/2026-08-15-frame-probe-look-gate-design.md](../specs/2026-08-15-frame-probe-look-gate-design.md)

## Global Constraints

1. **Fail loud.** No silent fallback, no default that papers over a missing input.
   Every refusal names the cause AND the remedy. See `docs/coding-standards.md`.
2. **Imports at the top of the file.** No function-local imports.
3. **Type every signature.** Dataclasses for contracts; `from_dict`/`to_dict` on
   anything that round-trips through JSON.
4. **ffmpeg landmines (CLAUDE.md "Known troubles"):** `-ss` **after** `-i`;
   `lutrgb` banned (use `colorchannelmixer`); `zoompan` needs explicit
   `s=`/`fps=`/`d=`; `setpts` needs a following `fps=`; a filtergraph value
   containing a comma must be single-quoted inside the `-vf` string;
   `blend=all_mode=multiply` destroys chroma. **New in this slice:** a `select`
   emitted BEFORE a chain's `fps=` silently duplicates one frame N times.
5. **Never call the ffmpeg binary by a bare literal** — always `ffbin.ffmpeg()` /
   `ffbin.ffprobe()`. An AST scan enforces it.
6. **Thresholds are module constants, never parameters** (`lib/naturalness.py` states
   the reason). A no-waiver gate whose bar is an argument has no bar.
7. **Do not mutate the developer's system.** No `brew`/`pip`/`apt`/`npm` install, no
   running `setup.sh`. Verification is read-only plus `pytest`.
8. **Never run `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.**
9. **Never `git push`.** Commit only; the repo owner pushes.
10. **Never `git commit --amend`.** A fix after review is its own follow-up commit.
11. **Commit messages:** conventional-commit subject, then a body explaining WHY.
    Use a `-F` heredoc or repeated `-m`, never a single one-line `-m` for a change
    that needs a body.
12. **These seven files are frozen this slice** — do not edit them:
    `scripts/mix.py`, `scripts/check_reel.py`, `scripts/build_reel.py`,
    `scripts/edl_to_reel.py`, `scripts/pacing.py`, `scripts/lib/pacing.py`,
    `scripts/extract.py`.
13. Run the suite with `.venv/bin/python -m pytest`. Integration tests that shell out
    to real ffmpeg live in `tests/integration/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/reframe.py` | **modified** — `RenderPlan` + `plan_render()` + `RenderPlan.with_tail()`; `reframe()` becomes plan + x264 sink + sidecars |
| `scripts/process_episode.py` | **modified** — `build_reframe_spec()` extracted, so the probe uses the one Manifest→ReframeSpec map |
| `scripts/lib/lookcheck.py` | **new, pure** — the gate's constants, `frame_delta`, `corner_centre`, `LookFinding`, `evaluate` |
| `scripts/lib/lint.py` | **modified** — a seventh `check_argv` check: `select` ahead of `fps=` in one chain |
| `scripts/probe.py` | **new** — the driver: `probe_grade` (half A) and `probe_look` (a manual re-run of half B) |
| `scripts/deliver.py` | **modified** — `_verify_look` after the encode, before the attestation |
| `scripts/lib/provenance.py` | **modified** — `Attestation.look_checks` |
| `tests/lib/test_lookcheck.py` | **new** — the pure measurements |
| `tests/lib/test_probe.py` | **new** — the probe's refusals and the colour-key merge |
| `tests/lib/test_lint.py` | **modified** — the seventh check |
| `tests/integration/test_probe.py` | **new** — real-ffmpeg fidelity, the select-position landmine, the gate firing and its control |
| `skills/edit-plan/SKILL.md`, `skills/using-montage/SKILL.md` | **modified** — the convergence loop |
| `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `docs/backlog.md` | **modified** — registry row, status, deferrals |

---

## Task 0: `RenderPlan` + `plan_render` — one chain, two sinks

**Files:**
- Modify: `scripts/reframe.py:394-538`
- Test: `tests/lib/test_reframe.py`, `tests/integration/test_golden.py` (must not move)

**Interfaces:**
- Produces: `reframe.RenderPlan` (frozen dataclass, fields below),
  `reframe.plan_render(spec: ReframeSpec, src: str, route_path: str | None) -> RenderPlan`,
  `RenderPlan.with_tail(extra: str) -> list[str]`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_reframe.py`:

```python
def test_plan_render_and_reframe_build_the_same_filter_args(tmp_path, monkeypatch):
    """reframe() must emit exactly what plan_render decided — if the two ever diverge
    the probe stops describing the render, which is the one thing it is for."""
    seen: list[list[str]] = []
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: seen.append(cmd) or _fake_ok())
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.0))
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(110.0, 120.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:540"),
                       pan=PanSpec(start=0.0, end=0.2))
    plan = reframe.plan_render(spec, "src.mp4", None)
    reframe.reframe(spec, "src.mp4", None, str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert plan.filter_args == seen[-1][4:4 + len(plan.filter_args)]


def test_with_tail_appends_after_the_chain(tmp_path, monkeypatch):
    """The sink filter lands at the END of the chain — design §3.1: ahead of the
    tail's fps= it silently emits one frame N times."""
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.0))
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(110.0, 120.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:540"),
                       pan=PanSpec(start=0.0, end=0.2))
    plan = reframe.plan_render(spec, "src.mp4", None)
    tailed = plan.with_tail("select='eq(n\\,3)'")
    assert tailed[:-1] == plan.filter_args[:-1]
    assert tailed[-1] == plan.filter_args[-1] + ",select='eq(n\\,3)'"
    assert tailed[-1].index("fps=") < tailed[-1].index("select=")
```

`_fake_ok()` is a helper returning an object with `.stdout = b""` — reuse whatever the
file already uses to fake `proc.run`; if it has none, add:

```python
class _FakeCompleted:
    stdout = b""
    stderr = b""
    returncode = 0


def _fake_ok():
    return _FakeCompleted()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -k "plan_render or with_tail" -v`
Expected: FAIL — `AttributeError: module 'scripts.reframe' has no attribute 'plan_render'`

- [ ] **Step 3: Add the dataclass and the extraction**

In `scripts/reframe.py`, above `def reframe(`, add:

```python
@dataclass(frozen=True)
class RenderPlan:
    """Everything ONE render needs, decided but not yet executed.

    Exists so this repo has exactly ONE chain builder. reframe() is this plan plus an
    x264 sink; the frame probe is this plan plus a select sink (design
    2026-08-15 §3). A probe that rebuilt the chain from path.meta.json's recorded rect
    would be a second implementation of the render, and the day the two drift is the
    day the probe lies about the one thing it exists to answer.
    """
    filter_args: list[str]        # ["-vf", chain] or ["-filter_complex", graph]
    path: list[int]               # the crop's x per route sample — CropPath's payload
    fps: float
    dur: float
    src_w: int                    # ResolvedLayout does NOT carry the source dims (checked:
    src_h: int                    # scripts/lib/layout.py:16-29), and PathMeta.src_dims needs
                                  # them — so they ride here rather than costing a second ffprobe
    rl: ResolvedLayout
    cy: int
    crop_ws: list[int] | None
    crop_hs: list[int] | None
    crop_ys: list[int] | None
    grade: str                    # the finished colour fragment, for the probe's report

    def with_tail(self, extra: str) -> list[str]:
        """These filter args with `extra` appended to the END of the chain.

        The ONLY supported way to add a sink filter, and the position is not a
        preference: measured 2026-08-15, a `select` placed BEFORE the chain's own
        `fps=` emits the SAME frame once per requested frame — the fps filter
        re-interpolates the dropped frames back up to rate by duplication, and the
        output frame count is still right, so nothing fails. Requesting frames
        15/45/75 of a 90-frame clip returned one hash three times.
        """
        if not extra:
            raise ValueError("with_tail needs a filter to append; pass the plan's "
                             "filter_args unchanged if there is no sink filter")
        args = list(self.filter_args)
        args[-1] = f"{args[-1]},{extra}"
        return args
```

Then replace the body of `reframe()` from the `zoom`/`pan` refusal through the
`xexpr = _xexpr(base_xs, times)` line with a call, moving that code into
`plan_render`. The new `plan_render` is **verbatim** the current `reframe()` lines
431-512, with these four changes:

1. It ends by returning the `RenderPlan` instead of falling through to the ffmpeg
   command.
2. `CropPath(path).to_json(path_out)` is **removed** from it (it has no `path_out`) —
   `reframe()` does that with `plan.path` after the call.
3. Its docstring is the paragraph below.
4. `_filter_args(...)` is called inside it, and its result stored in `filter_args`.

```python
def plan_render(spec: ReframeSpec, src: str, route_path: str | None) -> RenderPlan:
    """Decide one render without executing it: probe the source, resolve the layout,
    compute (or generate) the crop path, build the colour fragment, and assemble the
    filter args. Every refusal reframe() used to raise still raises HERE — a zoom
    beside a pan, a missing route, an empty route, a non-monotone tone curve — so a
    probe fails on exactly the same input the real render would.

    Pure of side effects except the ffprobe and verify_tone's 256x4 ramp: it writes no
    file. reframe() owns path.json and path.meta.json; the probe writes neither.
    """
```

The zoom/pan refusal currently at `reframe():431-435` moves to the top of
`plan_render`. `plan_render` must call `_filter_args(rl, xexpr, cy, grade, fps, dur, zoom_args=zoom_args)`
and store the result.

Then `reframe()` becomes:

```python
def reframe(spec: ReframeSpec, src: str, route_path: str | None, out: str,
            path_out: str, *, stabilized: bool = False) -> str:
    """<keep the existing docstring verbatim>"""
    plan = plan_render(spec, src, route_path)
    CropPath(plan.path).to_json(path_out)
    # `-t` pins the render to the source's length, and is the ONLY thing that does
    # (design §4). See plan_render for why the filter args are built there.
    cmd = [ffbin.ffmpeg(), "-y", "-i", src, *plan.filter_args,
           "-t", f"{plan.dur:.6f}",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    proc.run(cmd)
    PathMeta(mode=plan.rl.mode, crop_w=plan.rl.crop_w, crop_h=plan.rl.crop_h,
             crop_y=plan.cy, src_dims=(plan.src_w, plan.src_h),
             canvas=spec.canvas, out_dims=(plan.rl.out_w, plan.rl.out_h),
             rect_px=plan.rl.rect_px, freedom=plan.rl.freedom,
             background=plan.rl.background,
             pan=spec.pan is not None, stabilized=stabilized,
             crop_ws=plan.crop_ws if spec.zoom is not None else None,
             crop_hs=plan.crop_hs if spec.zoom is not None else None,
             crop_ys=plan.crop_ys if spec.zoom is not None else None,
             ).write(Path(path_out).with_suffix(".meta.json"))
    return out
```

Move the long `-t` comment block (currently `reframe.py:513-523`) with the `cmd`.

- [ ] **Step 4: Run the new tests, then the reframe + golden suites**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py tests/integration/test_reframe.py tests/integration/test_golden.py tests/integration/test_layouts.py tests/integration/test_zoom.py tests/integration/test_pan.py -v`
Expected: PASS, and **no golden fixture moves** — this task changes no argv.

- [ ] **Step 5: Commit**

```bash
git add scripts/reframe.py tests/lib/test_reframe.py
git commit -F - <<'EOF'
refactor(reframe): one chain builder, two sinks

plan_render() decides a render — layout, path, colour fragment, filter args —
and reframe() becomes that plan plus the x264 sink and the two sidecars. The
frame probe (design 2026-08-15 §3) is the same plan plus a select sink, so
there is exactly one place the chain is built.

RenderPlan.with_tail is the only way to append a sink filter, and it appends
at the END on purpose: measured, a select placed before the chain's own fps=
emits the SAME frame once per requested frame, because fps re-interpolates the
dropped frames back up by duplication. The output frame count stays right and
nothing raises.

No argv changes; the golden fixtures do not move.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 1: `build_reframe_spec` — the one Manifest→ReframeSpec map

**Files:**
- Modify: `scripts/process_episode.py:108-113, 350-368`
- Test: `tests/lib/test_process_episode.py`

**Interfaces:**
- Produces: `process_episode.build_reframe_spec(m: Manifest, delivery: Delivery, params: dict, color_correct: tuple[float, ...] | None = None) -> ReframeSpec`
- Consumes: `reframe.RenderPlan` is not used here.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_process_episode.py`:

```python
def test_build_reframe_spec_carries_every_colour_field():
    """The probe renders from this map. A field that falls out here is a field the
    probe shows unchanged while the real render changes it."""
    m = Manifest.from_dict({
        "segment": "s.mp4", "out_path": "o.mp4", "target_dur": 2.0,
        "composition": "lead", "grid": "thirds", "canvas": [9, 16],
        "color_means": [110.0, 120.0, 130.0], "delivery": "short_edge:540",
        "white_balance": 0.4, "black_point": 0.1, "highlight": 0.8,
        "highlight_red": 0.2, "saturation": 1.2, "shadow_red": 0.05,
        "mid_blue": 0.95, "dip": 0.3,
        "tone_src": [18.0, 110.0, 220.0], "tone_dst": [26.0, 118.0, 210.0]})
    spec = process_episode.build_reframe_spec(
        m, Delivery.from_spec(m.delivery), dict(orch.DEFAULT_PARAMS))
    assert (spec.white_balance, spec.black_point, spec.highlight, spec.highlight_red,
            spec.saturation, spec.shadow_red, spec.mid_blue, spec.dip) == (
        0.4, 0.1, 0.8, 0.2, 1.2, 0.05, 0.95, 0.3)
    assert spec.tone_src == (18.0, 110.0, 220.0)
    assert spec.tone_dst == (26.0, 118.0, 210.0)
    assert spec.color_correct is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py -k build_reframe_spec -v`
Expected: FAIL — `AttributeError: ... has no attribute 'build_reframe_spec'`

- [ ] **Step 3: Extract the function and call it from the loop**

Add to `scripts/process_episode.py`, above `process_episode()`:

```python
def build_reframe_spec(m: Manifest, delivery: Delivery, params: dict,
                       color_correct: tuple[float, ...] | None = None) -> ReframeSpec:
    """The ONE place a Manifest becomes a ReframeSpec.

    Extracted so the frame probe (scripts/probe.py, design 2026-08-15) renders from
    the same field map the real render uses. A probe carrying its own copy of this
    mapping would drift field by field, and a probe that renders a different grade
    than the next render is worse than no probe: it converges on pixels nobody gets.

    `params` is the retry-parameter dict (orchestration.DEFAULT_PARAMS, possibly
    adjusted). `color_correct` is the reel loop's per-channel pull, None outside it.
    """
    lspec = LayoutSpec(mode=m.layout, crop_aspect=m.crop_aspect, crop_scale=m.crop_scale,
                       rect=m.rect, background=m.background,
                       background_color=m.background_color,
                       border_px=m.border_px, border_color=m.border_color)
    return ReframeSpec(composition=m.composition, grid=m.grid, canvas=m.canvas,
                       color_means=m.color_means, delivery=delivery, layout=lspec,
                       max_speed=params["max_speed"],
                       smooth_window_s=params["smooth_window_s"],
                       color_correct=color_correct,
                       white_balance=m.white_balance, black_point=m.black_point,
                       highlight=m.highlight, highlight_red=m.highlight_red,
                       saturation=m.saturation,
                       shadow_red=m.shadow_red, mid_blue=m.mid_blue, dip=m.dip,
                       tone_src=m.tone_src, tone_dst=m.tone_dst,
                       pan=PanSpec.from_dict(m.pan) if m.pan is not None else None,
                       zoom=ZoomSpec.from_dict(m.zoom) if m.zoom is not None else None)
```

In the retry loop (currently `process_episode.py:359-368`) replace the inline
`ReframeSpec(...)` with:

```python
        rspec = build_reframe_spec(m, delivery, params, color_correct)
```

Leave `lspec`, `pan` and `zoom` where they are at lines 108-136 — the preflights
below them need `lspec`/`pan`/`zoom` before the loop, and building them twice is
cheap pure construction. Add a one-line comment at the `lspec` construction:

```python
    # Also built inside build_reframe_spec (the ONE map). Kept here because the layout
    # and pan preflights below need the resolved objects BEFORE any encode; both
    # constructions are pure and validate() already proved they succeed.
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py tests/integration/test_process_episode.py tests/integration/test_golden.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/process_episode.py tests/lib/test_process_episode.py
git commit -F - <<'EOF'
refactor(process-episode): extract the one Manifest -> ReframeSpec map

build_reframe_spec is the single field map. The frame probe renders from it
too, so a probe cannot drift field by field from the render it claims to
predict — a probe that shows a different grade than the next render converges
on pixels nobody gets.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 2: `lib/lookcheck.py` — the pure measurements

**Files:**
- Create: `scripts/lib/lookcheck.py`
- Test: `tests/lib/test_lookcheck.py`

**Interfaces:**
- Produces: `LookFinding` (frozen dataclass: `check: str`, `status: str`,
  `detail: str`, `measured: float`, `expected: float`, plus `to_dict()`),
  `frame_delta(a, b) -> float`, `corner_centre(f) -> tuple[float, float]`,
  `evaluate(mid_master, mid_delivered, first_master, first_delivered, *, vignette=0.0, fade=0.0, titles=False) -> list[LookFinding]`,
  and the constants `LOOK_NOISE_MAX`, `VIGNETTE_MIN_FRACTION`, `FADE_BLACK_MAX`,
  `FADE_SOURCE_MIN`, `VIGNETTE_FLOOR`, `BOX_DIV`.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_lookcheck.py`:

```python
import numpy as np
import pytest

from scripts.lib import lookcheck


def _flat(v: int, h: int = 200, w: int = 100) -> np.ndarray:
    return np.full((h, w, 3), v, dtype=np.uint8)


def _corners_dark(v: int, frac: float, h: int = 200, w: int = 100) -> np.ndarray:
    """A flat frame whose corner boxes are darkened by `frac` — a rendered vignette."""
    f = _flat(v, h, w)
    bh, bw = h // lookcheck.BOX_DIV, w // lookcheck.BOX_DIV
    for ys in (slice(0, bh), slice(h - bh, h)):
        for xs in (slice(0, bw), slice(w - bw, w)):
            f[ys, xs] = int(round(v * (1.0 - frac)))
    return f


def test_nothing_declared_measures_nothing():
    assert lookcheck.evaluate([_flat(100)], [_flat(100)], None, None) == []


def test_a_declared_vignette_that_changed_no_pixels_fails():
    same = [_flat(100), _flat(100), _flat(100)]
    out = lookcheck.evaluate(same, list(same), None, None, vignette=0.3)
    rendered = [f for f in out if f.check == "rendered"]
    assert len(rendered) == 1
    assert rendered[0].status == "fail"
    assert rendered[0].measured == pytest.approx(0.0)


def test_a_rendered_vignette_passes():
    master = [_flat(100), _flat(100), _flat(100)]
    delivered = [_corners_dark(100, 0.3) for _ in range(3)]
    out = lookcheck.evaluate(master, delivered, None, None, vignette=0.3)
    by = {f.check: f for f in out}
    assert by["rendered"].status == "pass"
    assert by["vignette"].status == "pass"


def test_a_vignette_too_shallow_to_be_the_declared_one_fails():
    master = [_flat(100)] * 3
    delivered = [_corners_dark(100, 0.05) for _ in range(3)]   # asked 0.30, got 0.05
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, vignette=0.30)}
    assert by["vignette"].status == "fail"


def test_a_vignette_on_black_corners_is_not_checked():
    """You cannot darken black. Reporting this as proven would be the lie the gate
    exists to stop (design §7)."""
    master = [_flat(3)] * 3
    delivered = [_flat(3)] * 3
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, vignette=0.3)}
    assert by["vignette"].status == "not-checked"


def test_a_rendered_fade_passes_and_a_missing_one_fails():
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    ok = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), fade=0.5)}
    assert ok["fade"].status == "pass"
    bad = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(80), fade=0.5)}
    assert bad["fade"].status == "fail"


def test_a_fade_on_an_already_black_opening_is_not_checked():
    by = {f.check: f for f in lookcheck.evaluate(
        [_flat(100)] * 3, [_flat(60)] * 3, _flat(2), _flat(0), fade=0.5)}
    assert by["fade"].status == "not-checked"


def test_mismatched_shapes_refuse():
    with pytest.raises(ValueError, match="same shape"):
        lookcheck.evaluate([_flat(100)], [_flat(100, h=100)], None, None, vignette=0.3)


def test_a_declared_fade_without_a_first_frame_refuses():
    with pytest.raises(ValueError, match="first frame"):
        lookcheck.evaluate([_flat(100)] * 3, [_flat(60)] * 3, None, None, fade=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_lookcheck.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.lookcheck'`

- [ ] **Step 3: Write the module**

Create `scripts/lib/lookcheck.py`:

```python
"""Did the delivered reel actually carry the look it declared? (design
docs/specs/2026-08-15-frame-probe-look-gate-design.md §7)

check_reel measures the MASTER. deliver then encodes the vignette, the bookend fade
and the titles into a file no gate reads — so a filter that silently fails to reach
the chain ships. This measures the delivered pixels against the master's at the same
timestamps and says whether the declared effect is in them.

Pure: numpy arrays in, findings out. No ffmpeg, no paths — deliver samples the frames
and deliver decides what to do with the verdict.

Every threshold below is a module constant and NOT a parameter, for the reason
naturalness.py states: a threshold a caller can pass is a threshold a subagent can
pass, and a no-waiver gate whose bar is an argument has no bar.
"""
from dataclasses import dataclass

import numpy as np

# Measured 2026-08-15 on a deliver-shaped encode of a heavy-grain master (the worst
# case for x264 at crf 18): two encodes of the SAME picture sit 0.638 / 0.727 / 0.779
# codes apart. 2.0 leaves ~2.6x headroom over the worst of those.
LOOK_NOISE_MAX = 2.0
# Measured: a declared vignette of 0.10 / 0.30 / 0.60 dropped the corner-over-centre
# ratio by 0.0844 / 0.2576 / 0.5209 — 0.84 to 0.87 of what was asked for. Requiring
# half the declared depth leaves a 1.7x margin below the worst measured case, which is
# the point: this proves the effect is THERE, it does not grade it.
VIGNETTE_MIN_FRACTION = 0.5
# Measured: a 0.5s fade took the master's 75.28-mean first frame to exactly 0.00.
FADE_BLACK_MAX = 2.0
# Below these the source cannot discriminate: a reel that opens on black is already
# black at t=0, and corners that are already dark cannot be darkened. Both report
# not-checked and pass — an honest hole, named in design §10.4.
FADE_SOURCE_MIN = 8.0
VIGNETTE_FLOOR = 8.0
# The vignette's sampling boxes, as a divisor of each dimension. look.VIGNETTE_PLATEAU
# is 0.55 of the CORNER radius, so a box 1/10 of each side sits well outside the
# plateau and the 2/10 centre box well inside it — neither straddles the falloff.
BOX_DIV = 10


@dataclass(frozen=True)
class LookFinding:
    """One check's verdict. `status` is "pass" | "fail" | "not-checked" — the third is
    a real outcome, not a synonym for pass: it says the source could not discriminate
    and nothing was proven."""
    check: str
    status: str
    detail: str
    measured: float
    expected: float

    def to_dict(self) -> dict:
        return {"check": self.check, "status": self.status, "detail": self.detail,
                "measured": round(self.measured, 4), "expected": round(self.expected, 4)}


def _rgb(f: object, what: str) -> np.ndarray:
    if not (isinstance(f, np.ndarray) and f.ndim == 3 and f.shape[2] == 3
            and f.dtype == np.uint8):
        got = f"shape={f.shape}, dtype={f.dtype}" if isinstance(f, np.ndarray) else type(f).__name__
        raise ValueError(f"lookcheck: {what} must be an HxWx3 uint8 RGB array, got {got} "
                         f"— sample frames with assembly.frames_rgb before calling")
    return f


def frame_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute per-pixel, per-channel difference between two frames.

    The catch-all sensor: two encodes of the same picture sit under LOOK_NOISE_MAX
    apart, so a declared effect that leaves this at the floor did not render at all —
    whatever the effect was, and even where its own specific measurement has a
    not-checked arm."""
    _rgb(a, "a"), _rgb(b, "b")
    if a.shape != b.shape:
        raise ValueError(f"lookcheck: frames must be the same shape to compare, got "
                         f"{a.shape} and {b.shape} — the delivery was resized relative "
                         f"to the master, which no ExportProfile should do")
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def corner_centre(f: np.ndarray) -> tuple[float, float]:
    """(mean of the four corner boxes, mean of the centre box). Their RATIO is what
    the vignette check compares between master and delivery, so picture content
    cancels and only the darkening survives."""
    _rgb(f, "frame")
    h, w = f.shape[:2]
    bh, bw = max(1, h // BOX_DIV), max(1, w // BOX_DIV)
    corners = [f[:bh, :bw], f[:bh, -bw:], f[-bh:, :bw], f[-bh:, -bw:]]
    centre = f[h // 2 - bh:h // 2 + bh, w // 2 - bw:w // 2 + bw]
    return float(np.mean([float(c.mean()) for c in corners])), float(centre.mean())


def evaluate(mid_master: list[np.ndarray], mid_delivered: list[np.ndarray],
             first_master: np.ndarray | None, first_delivered: np.ndarray | None,
             *, vignette: float = 0.0, fade: float = 0.0,
             titles: bool = False) -> list[LookFinding]:
    """Judge a delivery against its master. Empty list = nothing was declared, so
    there is nothing to prove and no ffmpeg was worth spending.

    `mid_*` are paired frames from the reel's interior; `first_*` are the frames at
    t=0, needed only when a fade was declared.
    """
    if not (vignette or fade or titles):
        return []
    if not mid_master or len(mid_master) != len(mid_delivered):
        raise ValueError(f"lookcheck.evaluate needs the same number of master and "
                         f"delivered frames, got {len(mid_master)} and "
                         f"{len(mid_delivered)}")
    out: list[LookFinding] = []

    worst = max(frame_delta(m, d) for m, d in zip(mid_master, mid_delivered))
    out.append(LookFinding(
        check="rendered",
        status="pass" if worst > LOOK_NOISE_MAX else "fail",
        detail=(f"the delivered picture differs from the master by {worst:.3f} codes "
                f"at most, at or under the {LOOK_NOISE_MAX} two encodes of the SAME "
                f"picture differ by — the declared look did not reach the filter chain"
                if worst <= LOOK_NOISE_MAX else
                f"the delivered picture differs from the master by {worst:.3f} codes"),
        measured=worst, expected=LOOK_NOISE_MAX))

    if vignette:
        mid = len(mid_master) // 2
        mc, mp = corner_centre(mid_master[mid])
        dc, dp = corner_centre(mid_delivered[mid])
        if mc < VIGNETTE_FLOOR:
            out.append(LookFinding(
                check="vignette", status="not-checked",
                detail=(f"the master's own corners average {mc:.2f}, under the "
                        f"{VIGNETTE_FLOOR} this check needs — you cannot darken black, "
                        f"so nothing here proves the vignette rendered either way"),
                measured=mc, expected=VIGNETTE_FLOOR))
        else:
            mr = mc / mp if mp else 0.0
            dr = dc / dp if dp else 0.0
            drop = 1.0 - (dr / mr) if mr else 0.0
            need = VIGNETTE_MIN_FRACTION * vignette
            out.append(LookFinding(
                check="vignette",
                status="pass" if drop >= need else "fail",
                detail=(f"a vignette of {vignette} should drop the corner-over-centre "
                        f"ratio by about {0.85 * vignette:.4f} (measured 0.84-0.87x of "
                        f"the declared depth); the delivery dropped it {drop:.4f}, under "
                        f"the {need:.4f} floor — the vignette did not render, or rendered "
                        f"far shallower than declared"
                        if drop < need else
                        f"corner-over-centre ratio {mr:.4f} -> {dr:.4f}, a drop of {drop:.4f}"),
                measured=drop, expected=need))

    if fade:
        if first_master is None or first_delivered is None:
            raise ValueError("lookcheck.evaluate needs the master's and the delivery's "
                             "first frame to judge a fade — sample t=0 from both and "
                             "pass them, or do not declare a fade")
        m0 = float(_rgb(first_master, "first_master").mean())
        d0 = float(_rgb(first_delivered, "first_delivered").mean())
        if m0 < FADE_SOURCE_MIN:
            out.append(LookFinding(
                check="fade", status="not-checked",
                detail=(f"the master's own first frame averages {m0:.2f}, under the "
                        f"{FADE_SOURCE_MIN} this check needs — the reel already opens on "
                        f"black, so a black first delivered frame proves nothing"),
                measured=m0, expected=FADE_SOURCE_MIN))
        else:
            out.append(LookFinding(
                check="fade",
                status="pass" if d0 <= FADE_BLACK_MAX else "fail",
                detail=(f"a {fade}s fade-in must start from black, but the delivery's "
                        f"first frame averages {d0:.2f} against the master's {m0:.2f} "
                        f"— the fade did not render"
                        if d0 > FADE_BLACK_MAX else
                        f"first frame {m0:.2f} -> {d0:.2f}"),
                measured=d0, expected=FADE_BLACK_MAX))
    return out
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_lookcheck.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/lookcheck.py tests/lib/test_lookcheck.py
git commit -F - <<'EOF'
feat(lookcheck): measure whether the delivered look reached the pixels

check_reel measures the master; deliver then encodes the vignette, the bookend
fade and the titles into a file no gate reads. This is the sensor for that gap
(design 2026-08-15 §7): delivered frames against the master's at the same
timestamps.

Three checks, each with a not-checked arm where the source cannot
discriminate — a reel that already opens on black, corners that are already
dark. not-checked is a real outcome, not a synonym for pass.

Constants calibrated on a real deliver-shaped encode of a heavy-grain master:
noise floor 0.638/0.727/0.779 codes -> LOOK_NOISE_MAX 2.0; a declared vignette
of 0.10/0.30/0.60 drops the corner ratio 0.0844/0.2576/0.5209, i.e. 0.84-0.87x
of what was asked, so the floor is half the declared depth; a 0.5s fade took a
75.28-mean first frame to exactly 0.00 -> FADE_BLACK_MAX 2.0.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 3: the lint's seventh check — `select` ahead of `fps=`

**Files:**
- Modify: `scripts/lib/lint.py`
- Test: `tests/lib/test_lint.py`

**Interfaces:**
- Produces: `lint._select_before_fps(cmd: list[str]) -> list[str]`, wired into
  `check_argv`'s tuple.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_lint.py`:

```python
def test_select_before_fps_is_flagged():
    bad = ["ffmpeg", "-i", "a.mp4", "-vf",
           "select='eq(n\\,3)',crop=100:200:x='5':y=0,scale=54:96,fps=30,format=yuv420p"]
    out = lint.check_argv(bad)
    assert any("select" in m and "fps=" in m for m in out)


def test_select_after_the_fps_tail_is_clean():
    good = ["ffmpeg", "-i", "a.mp4", "-vf",
            "crop=100:200:x='5':y=0,scale=54:96,fps=30,format=yuv420p,select='eq(n\\,3)'"]
    assert not [m for m in lint.check_argv(good) if "select" in m]


def test_a_select_with_no_fps_in_its_chain_is_clean():
    """assembly.frames_rgb emits exactly this and must never be flagged."""
    assert not [m for m in lint.check_argv(
        ["ffmpeg", "-i", "a.mp4", "-vf", "select='eq(n\\,3)+eq(n\\,9)'"]) if "select" in m]


def test_select_and_fps_in_DIFFERENT_chains_is_clean():
    """A filter_complex's chains are separated by ';' and run independently — a select
    in one says nothing about an fps= in another."""
    assert not [m for m in lint.check_argv(
        ["ffmpeg", "-i", "a.mp4", "-filter_complex",
         "[0:v]select='eq(n\\,3)'[a];[1:v]fps=30[b];[a][b]overlay"]) if "select" in m]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -k select -v`
Expected: FAIL on the first test — `assert any(...)` is False (no check exists yet)

- [ ] **Step 3: Add the check**

In `scripts/lib/lint.py`, beside the other module-level regexes:

```python
_SELECT_RE = re.compile(r"(?:^|[,;\]])select=")
_FPS_TAIL_RE = re.compile(r"(?:^|[,;\]])fps=")
```

Add the check function beside `_blend_multiply`:

```python
def _select_before_fps(cmd: list[str]) -> list[str]:
    """Flag a `select` that sits BEFORE an `fps=` in the SAME filter chain.

    Measured 2026-08-15 (design 2026-08-15 §3.1): asking for frames 15/45/75 of a
    90-frame clip through `select=...,crop=...,fps=30` returned the SAME frame three
    times — `fps` re-interpolates the frames select dropped back up to rate by
    duplicating the survivor, and the output frame count is still exactly what was
    asked for, so nothing fails. A probe built that way shows one frame and calls it
    three.

    Split on ';' first: a filter_complex's chains run independently, so a select in
    one says nothing about an fps= in another. Chain-local, in emission order, using
    the FIRST occurrence of each — a chain with several of either is still wrong if
    any select precedes any fps.
    """
    out: list[str] = []
    for a in cmd:
        for chain in a.split(";"):
            s, f = _SELECT_RE.search(chain), _FPS_TAIL_RE.search(chain)
            if s and f and s.start() < f.start():
                out.append(
                    f"select ahead of fps= in {chain!r} — design §12: fps re-interpolates "
                    f"the frames select dropped back up to rate by DUPLICATING the "
                    f"survivor, so the output has the right frame count and the wrong "
                    f"frames (measured: three requested frames came back as one frame "
                    f"three times). Append the select at the END of the chain, after the "
                    f"fps=/format= tail — reframe.RenderPlan.with_tail does exactly that.")
    return out
```

Wire it into `check_argv`:

```python
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font,
                  _zoompan_defaults, _blend_multiply, _select_before_fps):
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -v && .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS. The whole-suite run matters here specifically: `proc.run`'s guard is
always-on, so a false positive in this check breaks a real render somewhere.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -F - <<'EOF'
feat(lint): refuse a select emitted ahead of a chain's fps=

The seventh §12 check. Measured: `select=...,crop=...,fps=30` asking for
frames 15/45/75 of a 90-frame clip returned the SAME frame three times, with
the right file count and no error — fps re-interpolates the dropped frames
back up to rate by duplicating the survivor.

Chain-local (split on ';' first) so a filter_complex's independent chains are
not compared against each other, and so assembly.frames_rgb's bare
`-vf select='...'` — which has no fps= at all — is never flagged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 4: `scripts/probe.py` — the grade probe

**Files:**
- Create: `scripts/probe.py`
- Test: `tests/lib/test_probe.py`

**Interfaces:**
- Consumes: `reframe.plan_render`, `RenderPlan.with_tail`,
  `process_episode.build_reframe_spec`, `edl.to_manifest_dict`,
  `models.ReelManifest/CropPath/PathMeta/Delivery`, `manifest.Manifest`,
  `lib.naturalness`, `lib.sheet`, `lib.color.percentiles`,
  `orchestration.DEFAULT_PARAMS`.
- Produces: `probe.FRAMES`, `probe._COLOUR_KEYS`, `probe.source_for(md, epdir) -> str`,
  `probe.regrade(md, edl_path, index) -> dict`,
  `probe.probe_grade(episodes_path, index, *, edl_path=None, out_dir=None, frames=FRAMES) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_probe.py`:

```python
import json
from pathlib import Path

import pytest

from scripts import probe


def _md(**over) -> dict:
    md = {"segment": "seg.mp4", "out_path": "o.mp4", "target_dur": 2.0,
          "composition": "lead", "grid": "thirds", "canvas": [9, 16],
          "color_means": [110.0, 120.0, 130.0], "delivery": "short_edge:540",
          "white_balance": 0.0, "black_point": 0.0, "highlight": 1.0,
          "saturation": 1.0, "shadow_red": 0.0, "mid_blue": 1.0, "dip": 0.0,
          "highlight_red": 0.25, "tone_src": [18.0, 110.0, 220.0],
          "tone_dst": [26.0, 118.0, 210.0]}
    md.update(over)
    return md


def test_source_for_returns_the_segment_without_stabilize(tmp_path):
    assert probe.source_for(_md(), tmp_path) == "seg.mp4"


def test_source_for_returns_the_prestage_output_under_stabilize(tmp_path):
    (tmp_path / "stabilized.mp4").write_bytes(b"x")
    assert probe.source_for(_md(stabilize=True), tmp_path) == str(tmp_path / "stabilized.mp4")


def test_source_for_refuses_a_missing_prestage_output(tmp_path):
    """reframe consumed the stabilized file. Falling back to the raw segment would
    render pixels the episode never shipped, and say nothing about it."""
    with pytest.raises(FileNotFoundError, match="stabilize"):
        probe.source_for(_md(stabilize=True), tmp_path)


def test_regrade_drops_a_colour_field_the_author_deleted(tmp_path):
    """to_manifest_dict omits highlight_red at its identity, so a plain merge would
    keep the OLD value and the probe would show a grade the next render will not."""
    edl = {"episodes": [{"clip": "c.mp4", "start": 0.0, "dur": 2.0,
                         "composition": "lead", "grid": "thirds"}],
           "target_dur": 2.0}
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(edl))
    out = probe.regrade(_md(), str(p), 0)
    assert out["highlight_red"] == 0.0
    assert out["segment"] == "seg.mp4"          # non-colour keys survive


def test_regrade_refuses_an_index_past_the_edl(tmp_path):
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [{"clip": "c.mp4", "start": 0.0, "dur": 2.0,
                                           "composition": "lead", "grid": "thirds"}],
                             "target_dur": 2.0}))
    with pytest.raises(IndexError, match="out of range"):
        probe.regrade(_md(), str(p), 3)
```

The EDL literal above must match this repo's actual `EDL.from_json` shape — read
`scripts/lib/edl.py`'s `EDL.from_dict` and `EDLEpisode.from_dict` and use whatever
the minimum required keys really are. If `EDL.from_json` refuses a dict without
`provenance`, add the minimum the contract demands; do not weaken the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_probe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.probe'`

- [ ] **Step 3: Write the driver**

Create `scripts/probe.py`:

```python
"""Cheap frame probes (design docs/specs/2026-08-15-frame-probe-look-gate-design.md).

`grade` renders N frames of ONE episode through the SAME chain reframe would encode,
over the FROZEN route, and measures them — so a grade converges here instead of
costing a reel per attempt. It skips the tracking pass, the storyboard, the check and
the x264 encode; measured, a tracking pass alone costs 5.00s against the encode's
0.59-2.41s on the same 1080p/3s clip.

`look` re-runs the delivered-reel check deliver already gates on, by hand.

This driver decides nothing about colour. The sensors it prints have uncalibrated
first-cut thresholds (naturalness.py says so itself), and a solver over an
uncalibrated taste function invents a target — match_grade remains the deterministic
lane. The agent looks, edits the EDL, probes again.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import process_episode, reframe
from scripts.lib import (assembly, color, edl as edl_lib, ffbin, lookcheck,
                         naturalness, orchestration as orch, proc, sheet)
from scripts.lib.edl import EDL
from scripts.lib.manifest import Manifest
from scripts.lib.models import CropPath, Delivery, PathMeta, ReelManifest

FRAMES = 3          # start / middle / end of the window, at (i+0.5)/N — never the
                    # first or last frame, which a dip or a bookend can own

# The colour block, as it crosses edl.to_manifest_dict. A CLOSED set, because regrade
# below must DROP these before re-applying: to_manifest_dict omits highlight_red,
# tone_src and tone_dst at their identity, so a plain merge would keep a value the
# author has just deleted from the EDL.
_COLOUR_KEYS = ("color_means", "white_balance", "black_point", "highlight",
                "highlight_red", "saturation", "shadow_red", "mid_blue", "dip",
                "tone_src", "tone_dst")


def source_for(md: dict, epdir: Path | str) -> str:
    """The file reframe ACTUALLY consumed for this episode.

    Under `stabilize` that is the pre-stage's output, not md["segment"] — process_episode
    runs vidstab.stabilize and hands ITS output to both the tracker and reframe (design
    2026-07-20 §1). A probe that reaches for the raw segment there renders different
    pixels than shipped and reports them as the episode's, which is precisely the
    silent-wrong-answer this whole slice exists to prevent.
    """
    if not md.get("stabilize"):
        return md["segment"]
    st = Path(epdir) / "stabilized.mp4"
    if not st.exists():
        raise FileNotFoundError(
            f"this episode declares stabilize but {st} is gone — reframe consumed the "
            f"stabilized pre-stage output, so probing {md['segment']} would render pixels "
            f"the episode never shipped. Re-run the episode (process_episode leaves the "
            f"file beside path.json), or drop stabilize from the EDL")
    return str(st)


def regrade(md: dict, edl_path: str, index: int) -> dict:
    """`md` with its colour block replaced by EDL episode `index`'s.

    Dropped and re-applied, never merged — see _COLOUR_KEYS. Everything else (the
    segment, the resolved canvas/delivery the project filled in, the layout, the
    hero) stays exactly as the run resolved it: this probes a NEW GRADE on the SAME
    episode, and re-deriving the rest would silently probe a different cut.
    """
    e = EDL.from_json(edl_path)
    if not 0 <= index < len(e.episodes):
        raise IndexError(f"--edl has {len(e.episodes)} episodes; index {index} is out of "
                         f"range. The index is the episode's position in BOTH EDL.json and "
                         f"EPISODES.json — they must describe the same cut")
    fresh = edl_lib.to_manifest_dict(e.episodes[index], md["segment"], md["out_path"])
    out = {k: v for k, v in md.items() if k not in _COLOUR_KEYS}
    out.update({k: v for k, v in fresh.items() if k in _COLOUR_KEYS})
    return out


def _refuse_on_drift(plan: reframe.RenderPlan, path_json: str, meta_json: str) -> None:
    """Refuse unless the recomputed geometry is what actually shipped.

    The probe's whole claim is that its pixels are the pixels the next render ships.
    That holds because a grade cannot move the crop (design §2). So if the recomputed
    geometry does NOT match the frozen sidecars, the claim is already false.

    The PATH comparison is the load-bearing half: a retry-adjusted max_speed or
    smooth_window_s moves every x while leaving the recorded rect identical, so the
    meta check alone would wave it straight through.
    """
    frozen = CropPath.from_json(path_json).xs
    if list(plan.path) != list(frozen):
        where = next((i for i, (a, b) in enumerate(zip(plan.path, frozen)) if a != b),
                     min(len(plan.path), len(frozen)))
        raise RuntimeError(
            f"the recomputed crop path does not match the frozen {path_json} "
            f"({len(plan.path)} points vs {len(frozen)}, first difference at index "
            f"{where}) — a grade cannot move the crop, so something else changed: a "
            f"re-track, a retry-adjusted max_speed/smooth_window_s, or a different "
            f"source file. Re-render this episode, then probe the render you got")
    meta = PathMeta.from_json(meta_json)
    got = (plan.rl.mode, plan.rl.crop_w, plan.rl.crop_h,
           (plan.rl.out_w, plan.rl.out_h))
    want = (meta.mode, meta.crop_w, meta.crop_h, tuple(meta.out_dims))
    if got != want:
        raise RuntimeError(
            f"the recomputed geometry does not match the frozen {meta_json}: "
            f"mode/crop/out {got} vs {want}. The layout or the delivery changed since "
            f"this episode was rendered, so the probe would show a frame this episode "
            f"never produced. Re-render it first")


def _tone(f: np.ndarray) -> tuple[float, float, float]:
    """(p5, p50, p95) luma — the same three anchors ReframeSpec.tone_src/tone_dst speak
    in, so a probe reading drops straight into an EDL pair.

    Computed in numpy from RGB with the BT.601 weights, where color_measure gets its
    histogram from ffmpeg's `format=gray`. The two can differ by a code or so on the
    same frame; both feed the same three anchors, and a tone pair is authored in whole
    codes.
    """
    luma = 0.299 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.114 * f[:, :, 2]
    hist = np.bincount(luma.astype(np.uint8).ravel(), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def _render(plan: reframe.RenderPlan, src: str, times: list[float],
            out_dir: Path) -> list[np.ndarray]:
    """The probe's sink: the plan's own chain plus a select, straight to PNG.

    No -ss anywhere. An input seek would reset each frame's timestamp, and the crop's
    x is a function of t — the crop would land somewhere else, silently (§12's seek
    landmine in its worst form). select never moves a timestamp.
    """
    nums = [round(t * plan.fps) for t in times]
    sel = "select='" + "+".join(rf"eq(n\,{n})" for n in nums) + "'"
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("f*.png"):
        p.unlink()
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, *plan.with_tail(sel),
              "-t", f"{plan.dur:.6f}", "-vsync", "0",
              "-frames:v", str(len(nums)), str(out_dir / "f%03d.png")])
    pngs = sorted(out_dir.glob("f*.png"))
    if len(pngs) != len(nums):
        raise RuntimeError(
            f"probe asked for {len(nums)} frames {nums} and ffmpeg emitted {len(pngs)} "
            f"— a frame number is past the stream's end (times {times} against a "
            f"{plan.dur:.3f}s source at {plan.fps:.4g}fps)")
    return [np.asarray(Image.open(p).convert("RGB")) for p in pngs]


def probe_grade(episodes_path: str, index: int, *, edl_path: str | None = None,
                out_dir: str | None = None, frames: int = FRAMES) -> dict:
    """Render and measure `frames` frames of episode `index`. Returns the report dict
    it also writes to probe.json, beside a probe.jpg of the frames themselves.

    With `edl_path`, the colour block comes from that (edited) EDL through the same
    bridge the real run uses, so what converges is exactly what ships. Without it, the
    grade that WAS rendered — the baseline to compare against.
    """
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"probe: frames must be an integer >= 1, got {frames!r}")
    rm = ReelManifest.from_json(episodes_path)
    if not 0 <= index < len(rm.episodes):
        raise IndexError(f"{episodes_path} has {len(rm.episodes)} episodes; index "
                         f"{index} is out of range")
    ep = rm.episodes[index]
    epdir = Path(ep.path).parent
    md = dict(ep.manifest)
    if edl_path is not None:
        md = regrade(md, edl_path, index)
    m = Manifest.from_dict(md)
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        params["smooth_window_s"] = m.smooth_window_s
    spec = process_episode.build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    plan = reframe.plan_render(spec, source_for(md, epdir), ep.route)
    _refuse_on_drift(plan, ep.path, ep.meta)

    d = Path(out_dir) if out_dir is not None else epdir / "probe"
    times = [((i + 0.5) / frames) * plan.dur for i in range(frames)]
    imgs = _render(plan, source_for(md, epdir), times, d)
    stats = naturalness.measure(imgs)
    report = {
        "episode": index, "episodes": episodes_path, "edl": edl_path,
        "source": source_for(md, epdir), "frames": len(imgs),
        "times": [round(t, 3) for t in times],
        "grade": plan.grade,
        "colour": {k: md[k] for k in _COLOUR_KEYS if k in md},
        "tone": [[round(v, 1) for v in _tone(f)] for f in imgs],
        "naturalness": {"stats": stats, "flags": naturalness.evaluate(stats)},
    }
    (d / "probe.json").write_text(json.dumps(report, indent=2))
    cells = [sheet.Cell(image=f,
                        lines=(f"t={t:.2f}s",
                               "p5/p50/p95 " + "/".join(f"{v:.0f}" for v in tone)))
             for f, t, tone in zip(imgs, times, report["tone"])]
    sheet.tile(cells).save(str(d / "probe.jpg"), quality=90)
    return report


def probe_look(master: str, delivered: str, *, vignette: float = 0.0,
               fade: float = 0.0, titles: bool = False) -> list[dict]:
    """The delivered-look check deliver gates on, run by hand against two files."""
    dur = assembly.probe_duration(delivered)
    ts = [dur * 0.25, dur * 0.5, dur * 0.75]
    mm = assembly.frames_rgb(master, ts, assembly.probe_stream(master).fps)
    dd = assembly.frames_rgb(delivered, ts, assembly.probe_stream(delivered).fps)
    f_m = f_d = None
    if fade:
        f_m = assembly.frames_rgb(master, [0.0], assembly.probe_stream(master).fps)[0]
        f_d = assembly.frames_rgb(delivered, [0.0], assembly.probe_stream(delivered).fps)[0]
    return [f.to_dict() for f in lookcheck.evaluate(
        mm, dd, f_m, f_d, vignette=vignette, fade=fade, titles=titles)]


def main() -> None:
    ap = argparse.ArgumentParser(description="cheap frame probes: converge a grade, "
                                             "or re-check a delivered look")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grade", help="render+measure N frames of one episode over its "
                                     "frozen route")
    g.add_argument("--episodes", required=True, help="EPISODES.json from "
                                                     "edl_to_reel --stop-after-episodes")
    g.add_argument("--index", type=int, required=True)
    g.add_argument("--edl", default=None, help="take the colour block from this "
                                               "(edited) EDL.json instead of the "
                                               "grade that was rendered")
    g.add_argument("--out-dir", default=None, help="default: <epdir>/probe")
    g.add_argument("--frames", type=int, default=FRAMES)

    lk = sub.add_parser("look", help="re-check a delivered reel against its master")
    lk.add_argument("master")
    lk.add_argument("delivered")
    lk.add_argument("--vignette", type=float, default=0.0)
    lk.add_argument("--fade", type=float, default=0.0)
    lk.add_argument("--titles", action="store_true")

    a = ap.parse_args()
    if a.cmd == "grade":
        r = probe_grade(a.episodes, a.index, edl_path=a.edl, out_dir=a.out_dir,
                        frames=a.frames)
        print(json.dumps(r, indent=2))
    else:
        print(json.dumps(probe_look(a.master, a.delivered, vignette=a.vignette,
                                    fade=a.fade, titles=a.titles), indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_probe.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/probe.py tests/lib/test_probe.py
git commit -F - <<'EOF'
feat(probe): converge a grade on three frames, not a reel

probe grade renders N frames of ONE episode through the SAME chain reframe
would encode, over the frozen route, and measures them (design 2026-08-15 §4).
It skips the tracking pass, the storyboard, the check and the encode; measured,
tracking alone costs 5.00s against the encode's 0.59-2.41s on the same 1080p/3s
clip, and via edl_to_reel today all of that is paid for EVERY episode to look
at one.

Two refusals carry the honesty:

- source_for returns the stabilize pre-stage's output, and refuses when it is
  gone. reframe consumed that file; probing the raw segment would render pixels
  the episode never shipped and report them as its own.
- _refuse_on_drift compares the recomputed crop path element by element against
  the frozen path.json before comparing geometry against path.meta.json. The
  path half is load-bearing: a retry-adjusted max_speed moves every x while
  leaving the recorded rect identical.

regrade drops the colour keys before re-applying them rather than merging:
to_manifest_dict omits highlight_red/tone_src/tone_dst at their identity, so a
merge would keep a value the author just deleted from the EDL.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 5: `deliver`'s post-encode look gate

**Files:**
- Modify: `scripts/deliver.py:66-173`, `scripts/lib/provenance.py`
- Test: `tests/test_deliver.py` — it already carries the `_bound(tmp_path)` helper
  (a master on disk plus a report bound to it) and the `_capture(monkeypatch)` ffmpeg
  stub that produces its output file. Use both; do **not** write new equivalents.
  (`tests/lib/test_deliver.py` also exists and covers `_next_version`/`_video_only_args`
  — leave it alone.)

**Interfaces:**
- Consumes: `lookcheck.evaluate`, `assembly.frames_rgb`, `assembly.probe_stream`,
  `assembly.probe_duration`.
- Produces: `deliver._verify_look(master, out, look, titles) -> list[LookFinding]`,
  `provenance.Attestation.look_checks: list[dict]`.

- [ ] **Step 1: Write the failing test**

Append to the deliver test file:

```python
def _finding(check="rendered", status="fail"):
    return lookcheck.LookFinding(check=check, status=status, detail="d",
                                 measured=0.4, expected=2.0)


def test_deliver_refuses_a_declared_look_that_changed_nothing(tmp_path, monkeypatch):
    """The cinematic-look review found a filter-list drop that would have silently
    killed the bookend and every title for three of four mood presets. This is the
    gate for that class."""
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [_finding()])
    with pytest.raises(RuntimeError, match="does not carry the look it declared"):
        deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "v", rep,
                            look=LookSpec(vignette=0.3))


def test_deliver_writes_no_attestation_when_the_look_gate_fails(tmp_path, monkeypatch):
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look",
                        lambda *a, **kw: [_finding(check="fade")])
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError):
        deliver_mod.deliver(master, REEL_H264, str(out_dir), "v", rep,
                            look=LookSpec(fade=0.5))
    assert list(out_dir.glob("REEL_v*.mp4"))                  # the file is left to look at
    assert not list(out_dir.glob("*.attest.json"))            # but nothing attests it


def test_deliver_records_the_look_checks_in_the_attestation(tmp_path, monkeypatch):
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [
        lookcheck.LookFinding(check="vignette", status="not-checked",
                              detail="corners already black", measured=3.0,
                              expected=8.0)])
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "v", rep,
                              look=LookSpec(vignette=0.3))
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    assert att["look_checks"] == [{"check": "vignette", "status": "not-checked",
                                   "detail": "corners already black",
                                   "measured": 3.0, "expected": 8.0}]


def test_a_look_less_delivery_runs_no_look_check_at_all(tmp_path, monkeypatch):
    """Zero cost and zero blast radius when nothing was declared."""
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    calls: list = []
    monkeypatch.setattr(deliver_mod.assembly, "frames_rgb",
                        lambda *a, **kw: calls.append(a) or [])
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "v", rep)
    assert calls == []
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    assert att["look_checks"] == []
```

`tests/test_deliver.py` needs `json` and `lookcheck` added to its imports; `pytest`,
`Path`, `provenance`, `LookSpec` and `REEL_H264` are already there.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_deliver.py -k look -v`
Expected: FAIL — `AttributeError: module 'scripts.deliver' has no attribute '_verify_look'`

- [ ] **Step 3: Implement**

In `scripts/lib/provenance.py`, add to `Attestation` (as the LAST field, defaulted, so
every existing construction still works):

```python
    look_checks: list[dict] = field(default_factory=list)   # deliver's post-encode
    # proof that the declared vignette/fade/titles reached the delivered pixels
    # (design 2026-08-15 §7). A "not-checked" row is a real outcome: the source could
    # not discriminate. An empty list means nothing was declared.
```

Add it to `Attestation.to_dict()` (and `from_dict`, if the class has one).

In `scripts/deliver.py`, add the import `lookcheck` to the `scripts.lib` import line
and add above `deliver()`:

```python
def _verify_look(master: str, out: str, look: LookSpec | None,
                 titles: str | None) -> list[lookcheck.LookFinding]:
    """Prove the declared look reached the DELIVERED pixels (design 2026-08-15 §7).

    check_reel measured the master; everything below rides this encode and nothing
    else ever reads the result. Samples three interior frames from both files at the
    same timestamps — and t=0 from both as well when a fade was declared.

    Each file's own fps is probed separately rather than shared: a profile that
    changed the rate would otherwise shift every frame number on one side only, and
    compare two different moments as if they were one.

    With nothing declared this makes no ffmpeg call at all, so a look-less delivery
    costs exactly what it cost before this gate existed.
    """
    vig = look.vignette if look is not None else 0.0
    fade = look.fade if look is not None else 0.0
    if not (vig or fade or titles is not None):
        return []
    ts = [d * f for d in (assembly.probe_duration(out),) for f in (0.25, 0.5, 0.75)]
    m_fps, d_fps = assembly.probe_stream(master).fps, assembly.probe_stream(out).fps
    first_m = first_d = None
    if fade:
        first_m = assembly.frames_rgb(master, [0.0], m_fps)[0]
        first_d = assembly.frames_rgb(out, [0.0], d_fps)[0]
    return lookcheck.evaluate(assembly.frames_rgb(master, ts, m_fps),
                              assembly.frames_rgb(out, ts, d_fps),
                              first_m, first_d,
                              vignette=vig, fade=fade, titles=titles is not None)
```

In `deliver()`, immediately after the `if audio is None: ... else: ...` encode block
and **before** `_log_version`:

```python
    # The look gate (design 2026-08-15 §7). AFTER the encode, because the honest
    # subject is the file that shipped, not a prediction of it. On a failure the file
    # stays on disk — deleting output nobody asked to delete is worse than leaving the
    # evidence — but no attestation is written, which montage status already reports as
    # an unattested delivery. No waiver (governance #8).
    look_checks = _verify_look(master, out, look, titles)
    bad = [f for f in look_checks if f.status == "fail"]
    if bad:
        raise RuntimeError(
            f"{Path(out).name} does not carry the look it declared: "
            + "; ".join(f"{f.check} — {f.detail}" for f in bad)
            + f". The file is on disk to look at, but no attestation was written, so "
              f"`montage status` reports it as unattested. Fix the look chain (EDL.look, "
              f"or the titles file) and deliver again — this gate has no waiver")
```

Pass the results into the attestation:

```python
        episode_qc=rp.get("episode_qc") or {},
        look_checks=[f.to_dict() for f in look_checks],
        delivered_at=datetime.now().isoformat(timespec="seconds"),
```

Extend `deliver()`'s docstring with one paragraph naming the new refusal, beside the
two existing binding refusals it already documents.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_deliver.py tests/integration/test_look.py tests/integration/test_reel_backhalf.py tests/integration/test_attested_run.py tests/integration/test_titles.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/deliver.py scripts/lib/provenance.py tests/test_deliver.py
git commit -F - <<'EOF'
feat(deliver): refuse a reel that does not carry the look it declared

check_reel measures the master. deliver then encodes the vignette, the bookend
fade and the titles into a file no gate has ever read — the cinematic-look
review found a filter-list drop that would have silently killed the bookend and
every title for three of four mood presets, and nothing downstream would have
noticed.

The gate runs AFTER the encode, because the honest subject is the file that
shipped rather than a prediction of it. On a failure the file stays on disk to
look at and no attestation is written, which montage status already reports as
an unattested delivery — consistent with deliver's existing master_digest
refusals, and with no waiver.

Passing and not-checked results are recorded on the attestation, so a delivery
carries the evidence rather than the claim.

With no look and no titles declared the gate makes no ffmpeg call at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 6: real-ffmpeg proofs

**Files:**
- Create: `tests/integration/test_probe.py`

**Interfaces:** consumes everything built above. Mark with whatever real-ffmpeg marker
this repo's `tests/integration/` files already use (check a neighbour, e.g.
`tests/integration/test_look.py`).

- [ ] **Step 1: Write the tests**

Create `tests/integration/test_probe.py`:

```python
"""Real ffmpeg. The probe's central claim is that its frames are the frames the full
render ships; the look gate's is that a declared effect reached the delivered pixels.
Both are pixel claims and are proved on pixels."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scripts import deliver as deliver_mod, probe, reframe
from scripts.lib import assembly, color, ffbin, layout as layout_lib, proc, provenance
from scripts.lib.look import LookSpec
from scripts.lib.models import Delivery, ExportProfile, PanSpec, ReelReport, ReframeSpec


def _grainy(tmp_path: Path, w: int = 640, h: int = 360, dur: float = 3.0) -> str:
    """Grain is the WORST case for x264 at crf 18, so the probe-vs-shipped gap this
    measures is an upper bound on real footage."""
    dst = str(tmp_path / "src.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"testsrc2=s={w}x{h}:r=30:d={dur:g}",
              "-vf", "noise=alls=40:allf=t+u",
              "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
              "-pix_fmt", "yuv420p", dst])
    return dst


def _spec() -> ReframeSpec:
    return ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(112.0, 118.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:360"),
                       pan=PanSpec(start=0.0, end=0.3),
                       tone_src=[18.0, 110.0, 220.0], tone_dst=[26.0, 118.0, 210.0],
                       black_point=0.08, saturation=1.1)


def test_the_probes_frames_are_the_frames_the_render_ships(tmp_path):
    """crf 18 is lossy so these cannot be byte-identical. What must hold is that the
    STATISTIC the grade decision reads — mean luma — agrees. Measured 2026-08-15 on a
    1080p and a 4K grain source: within 0.14 codes."""
    src = _grainy(tmp_path)
    sp = _spec()
    out = str(tmp_path / "shipped.mp4")
    reframe.reframe(sp, src, None, out, str(tmp_path / "path.json"))
    plan = reframe.plan_render(sp, src, None)
    n = 3
    times = [((i + 0.5) / n) * plan.dur for i in range(n)]
    probed = probe._render(plan, src, times, tmp_path / "probe")
    shipped = assembly.frames_rgb(out, [round(t * plan.fps) / plan.fps for t in times],
                                  plan.fps)
    assert len(probed) == len(shipped) == n
    for a, b in zip(probed, shipped):
        assert a.shape == b.shape
        assert abs(float(a.mean()) - float(b.mean())) < 0.5


def test_a_select_ahead_of_the_tail_collapses_to_one_frame(tmp_path):
    """The §3.1 landmine, kept as an executable measurement: this is WHY with_tail
    appends at the end. If ffmpeg ever stops duplicating here, this test says so."""
    src = _grainy(tmp_path)
    plan = reframe.plan_render(_spec(), src, None)
    nums = [round(((i + 0.5) / 3) * plan.dur * plan.fps) for i in range(3)]
    sel = "select='" + "+".join(rf"eq(n\,{k})" for k in nums) + "'"

    def hashes(args, sub):
        d = tmp_path / sub
        d.mkdir()
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, *args, "-t", f"{plan.dur:.6f}",
                  "-vsync", "0", "-frames:v", "3", str(d / "f%03d.png")])
        return [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.glob("*.png"))]

    first = list(plan.filter_args)
    first[-1] = f"{sel},{first[-1]}"
    assert len(set(hashes(first, "first"))) == 1        # one frame, three times
    assert len(set(hashes(plan.with_tail(sel), "last"))) == 3


def test_the_probe_refuses_a_path_that_no_longer_matches_the_render(tmp_path):
    src = _grainy(tmp_path)
    sp = _spec()
    pj = tmp_path / "path.json"
    reframe.reframe(sp, src, None, str(tmp_path / "o.mp4"), str(pj))
    plan = reframe.plan_render(sp, src, None)
    pj.write_text(json.dumps([x + 7 for x in plan.path]))
    with pytest.raises(RuntimeError, match="recomputed crop path"):
        probe._refuse_on_drift(plan, str(pj), str(pj.with_suffix(".meta.json")))


def test_a_delivered_vignette_and_fade_pass_the_gate(tmp_path):
    """The positive control. Without it, a gate that always failed would look correct
    to the negative test below."""
    src = _grainy(tmp_path)
    master = str(tmp_path / "master.mp4")
    reframe.reframe(_spec(), src, None, master, str(tmp_path / "p.json"))
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))
    out = deliver_mod.deliver(master, ExportProfile(), str(tmp_path / "out"), "look",
                              rep, look=LookSpec(vignette=0.3, fade=0.5))
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    by = {c["check"]: c for c in att["look_checks"]}
    assert by["rendered"]["status"] == "pass"
    assert by["vignette"]["status"] == "pass"
    assert by["fade"]["status"] == "pass"


def test_a_vignette_that_renders_nothing_is_refused(tmp_path, monkeypatch):
    """Simulates the real failure: the mask input is there and carries no darkening,
    exactly as a dropped filter would look downstream."""
    src = _grainy(tmp_path)
    master = str(tmp_path / "master.mp4")
    reframe.reframe(_spec(), src, None, master, str(tmp_path / "p.json"))
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))

    def _clear_mask(m: str, out_dir: str, vignette: float) -> str:
        si = assembly.probe_stream(m)
        mask = str(Path(out_dir) / "look_mask.png")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
                  "-i", f"nullsrc=s={si.w}x{si.h}:d=1:r=1",
                  "-vf", "format=rgba,geq=r=0:g=0:b=0:a=0",
                  "-frames:v", "1", mask])
        return mask

    monkeypatch.setattr(deliver_mod, "_render_mask", _clear_mask)
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="does not carry the look it declared"):
        deliver_mod.deliver(master, ExportProfile(), str(out_dir), "look", rep,
                            look=LookSpec(vignette=0.5))
    assert list(out_dir.glob("REEL_v*.mp4"))
    assert not list(out_dir.glob("*.attest.json"))
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_probe.py -v`
Expected: PASS (5 tests). If `test_a_delivered_vignette_and_fade_pass_the_gate` fails
on `vignette`, print the measured drop and compare it against §7's table before
touching `VIGNETTE_MIN_FRACTION` — a small synthetic canvas has proportionally larger
corner boxes, and the honest fix may be the test's canvas, not the constant. **Record
whichever it was in the design's §7.**

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_probe.py
git commit -F - <<'EOF'
test(probe): pixel proofs for the probe's claim and the look gate's

Five real-ffmpeg proofs:

- the probe's frames against the same frames decoded out of reframe's real
  x264 output, on a grain source (the worst case at crf 18): mean luma within
  half a code.
- the §3.1 landmine as an executable measurement — select ahead of the chain
  yields ONE distinct hash for three requested frames, select at the tail
  yields three. If ffmpeg ever stops duplicating here, this test says so.
- the drift refusal, on a mutated path.json.
- a delivered vignette + fade passing the gate. The positive control: without
  it a gate that always failed would look correct.
- a vignette whose mask carries no darkening being refused, with the file left
  on disk and no attestation beside it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 7: mutation battery, skills, docs, backlog

**Files:**
- Modify: `skills/edit-plan/SKILL.md`, `skills/using-montage/SKILL.md`,
  `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `docs/backlog.md`

- [ ] **Step 1: Run the mutation battery**

For each row: make the mutation, run the named test, confirm it goes **RED**, then
revert the mutation. A row whose test stays green is a **coverage hole** — write the
test that catches it before moving on, and say so in the commit body.

| # | Mutation | Must turn red |
|---|---|---|
| 1 | `source_for`: return `md["segment"]` unconditionally | `test_source_for_returns_the_prestage_output_under_stabilize` |
| 2 | `source_for`: return the raw segment instead of raising when `stabilized.mp4` is gone | `test_source_for_refuses_a_missing_prestage_output` |
| 3 | `_refuse_on_drift`: delete the path comparison, keep the meta one | `test_the_probe_refuses_a_path_that_no_longer_matches_the_render` |
| 4 | `regrade`: `out = dict(md)` then `out.update(fresh)` (a plain merge) | `test_regrade_drops_a_colour_field_the_author_deleted` |
| 5 | `with_tail`: prepend instead of append (`f"{extra},{args[-1]}"`) | `test_with_tail_appends_after_the_chain` **and** `test_a_select_ahead_of_the_tail_collapses_to_one_frame` |
| 6 | `LOOK_NOISE_MAX = 1000.0` | `test_a_declared_vignette_that_changed_no_pixels_fails` |
| 7 | `VIGNETTE_MIN_FRACTION = 0.0` | `test_a_vignette_too_shallow_to_be_the_declared_one_fails` |
| 8 | `evaluate`: make the `mc < VIGNETTE_FLOOR` arm return `status="pass"` | `test_a_vignette_on_black_corners_is_not_checked` |
| 9 | `evaluate`: make the `m0 < FADE_SOURCE_MIN` arm return `status="fail"` | `test_a_fade_on_an_already_black_opening_is_not_checked` |
| 10 | `deliver`: log the failures instead of raising | `test_deliver_refuses_a_declared_look_that_changed_nothing`, `test_a_vignette_that_renders_nothing_is_refused` |
| 11 | `deliver`: write the attestation before the gate | `test_deliver_writes_no_attestation_when_the_look_gate_fails` |
| 12 | `deliver`: drop the `if not (vig or fade or titles)` shortcut | `test_a_look_less_delivery_runs_no_look_check_at_all` |
| 13 | `lint`: remove `_select_before_fps` from `check_argv`'s tuple | `test_select_before_fps_is_flagged` |
| 14 | `lint`: drop the `a.split(";")` (scan whole arguments) | `test_select_and_fps_in_DIFFERENT_chains_is_clean` |
| 15 | `probe_grade`: use `md["segment"]` for the render but `source_for` for the report | `test_the_probes_frames_are_the_frames_the_render_ships` under a stabilized fixture — **if no such fixture exists, this row has no test; write one or record the hole explicitly** |

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all green. Record the exact pass/skip counts — they go in the commit body
and in `docs/build-status.md`.

- [ ] **Step 3: Skills**

In `skills/edit-plan/SKILL.md`, in the colour-grade section, add:

> **Converging a grade — do not re-render a reel to look at one episode.** After
> `edl_to_reel --stop-after-episodes` has written `EPISODES.json`, edit the episode's
> colour fields in `EDL.json`, then:
>
> ```bash
> "$VG" probe grade --episodes <work>/EPISODES.json --index <N> --edl EDL.json
> ```
>
> It writes `<work>/ep<N>/probe/probe.jpg` (the frames) and `probe.json` (naturalness
> flags plus p5/p50/p95 per frame, which read straight into a `tone_src`/`tone_dst`
> pair). Look at the pixels, edit, probe again. Only when it converges is the full
> render worth paying for — and to re-render **that one episode** rather than the
> reel, pass its frozen route so the tracker never runs again:
>
> ```bash
> "$VG" process_episode --manifest <work>/ep<N>/manifest.json --route <work>/ep<N>/route.json
> ```
>
> The probe **refuses** if the recomputed crop path differs from the frozen one: that
> means something other than colour changed, and its frames would not be the frames
> the next render ships.

In `skills/using-montage/SKILL.md`, at the episode-QC checkpoint, add one line: when
a QC verdict flags colour, run the probe loop above before re-rendering, and note
that `deliver` now hard-refuses a reel whose declared vignette/fade/titles did not
reach the pixels — that failure is a broken look chain, never something to retry.

Verify the launcher variable (`$VG` above) matches what the other skills in this repo
actually use; copy the exact preamble from `skills/edit-plan/SKILL.md`.

- [ ] **Step 4: Docs**

1. `CLAUDE.md` — a Quick Reference row for the design and the plan, in the table's
   established two-row style (design row, then plan row), placed after the
   shadow-red/length-reconcile rows.
2. `CLAUDE.md` "Known troubles" — add the new landmine:

   > - `select` placed **before** a chain's `fps=` emits the SAME frame once per
   >   requested frame: `fps` re-interpolates the dropped frames back up to rate by
   >   duplicating the survivor, and the output frame count is still right, so nothing
   >   fails. Measured 2026-08-15: three requested frames came back as one frame three
   >   times. Append a sink filter at the END —
   >   `reframe.RenderPlan.with_tail` does. **Machine-checked**: the landmine lint's
   >   seventh `check_argv` check.
3. `docs/build-status.md` — a Done entry with the measured numbers (the cost table,
   the fidelity table, the gate's calibration) and the suite counts from Step 2.
4. `docs/pipeline-map.md` — the probe is not a conveyor stage; add it to whatever the
   file's "tools beside the conveyor" section is, or create one row noting it runs
   between `episodes` and `episode-qc` on demand.
5. `docs/backlog.md`:
   - Flip the P2 `#10` row to ✅ with the measured numbers, in the style of the other
     closed rows (state what was measured, not just what was built).
   - Add the four §11 deferrals as new rows: titles in the look gate (P3, S), a
     one-step re-render of a converged episode (P4, S), calibrating §7's constants on
     real footage (P3, S), generalizing the probe to composition/path axes (P3, M).
     Each cites `frame-probe-look-gate §11`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/ skills/
git commit -F - <<'EOF'
docs: frame probe + look gate — registry, landmine, skills, backlog

Registry rows for the design and plan; the new §12 landmine in the always-loaded
Known troubles (a select ahead of a chain's fps= duplicates one frame, silently,
with the right frame count); the convergence loop in the edit-plan and
using-montage skills, including how to re-render ONE episode with its frozen
route instead of the reel.

Backlog #10 closes. Four deferrals filed as their own rows, per the rule that a
slice is not finished until its design's deferrals have a queue: titles in the
look gate, a one-step re-render of a converged episode, calibrating the gate's
constants on real footage, and generalizing the probe to the other QC axes.

Mutation battery: 15 rows, each mutation confirmed red before revert.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Self-review notes

**Spec coverage.** §1 (frozen artifacts, the stabilize trap) → Task 4 `source_for`.
§2 (the invariant and its oracle) → Task 4 `_refuse_on_drift` + Task 6's drift proof.
§3 (one chain, two sinks) → Task 0. §3.1 (the select landmine) → Task 0's `with_tail`,
Task 3's lint check, Task 6's executable measurement, Task 7's Known-troubles entry.
§4 (what the probe does and writes) → Task 4. §5/§6 (the measured cost and fidelity)
→ Task 6's fidelity proof and Task 7's build-status entry. §7 (the gate) → Tasks 2
and 5. §8 (thresholds are constants) → Task 2, enforced by Global Constraint 6.
§9 (files) → the File Structure table. §10 (honest limits) → Task 7's docs.
§11 (deferrals) → Task 7 Step 4.5.

**One place the implementer must check reality before writing code**, flagged inline:
the minimum `EDL.json` literal `EDL.from_json` accepts (Task 4 Step 1). Not a
placeholder — it names exactly what to read and what to do with either answer.
(`ResolvedLayout`'s fields were checked while writing this plan: `layout.py:16-29`
carries no source dims, so `RenderPlan` carries `src_w`/`src_h` itself.)
