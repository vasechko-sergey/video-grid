# Luma Tone Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The conductor's tone actuator becomes a luma-only `lutyuv` transfer and
its measuring instrument stops throwing away the pixels that carry p95 — the two
together taking the worst measured residual from 9.0 luma units to 2.0.

**Architecture:** `tone_arg` emits a four-segment piecewise-linear expression
over the Y plane instead of a densely-sampled RGB spline, converting explicitly
between the full-range anchors `measure_profile` produces and the tv-range plane
`lutyuv` writes. `measure_profile` drops its `scale=160:-2`. Both land together
because each alone is a partial fix (design §0).

**Tech Stack:** ffmpeg `lutyuv`, numpy, pytest.

**Design:** [docs/specs/2026-08-19-luma-tone-transfer-design.md](../specs/2026-08-19-luma-tone-transfer-design.md)

---

## Global Constraints

- **Fail loud**, imports at top, scripts as modules (`pythonpath = .`),
  interpreter `.venv/bin/python`.
- **`tone_arg` stays pure** — no ffmpeg, no paths. It returns a fragment.
- **Range conversion is explicit and pinned to a measurement**, never to a typed
  constant: the test asserts 16/235 against what the pipeline's own encode
  produces (design §3).
- **Goldens move; they get re-pinned, never loosened.** Every measured anchor and
  every emitted fragment in the suite changes. A test that stops asserting a
  value in order to pass is a defect.
- `lutrgb` stays banned. This slice uses `lutyuv`, a different filter.
- No installers. No `git checkout --` / `restore` / `reset --hard` / `stash`.
- Mutation battery under `PYTHONDONTWRITEBYTECODE=1`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/color.py` | **+** `TV_LO`/`TV_SPAN`/`_segments`; `tone_arg` emits `lutyuv`; `TONE_SAMPLES` retires |
| `scripts/color_measure.py` | `measure_profile` measures the real frame |
| `scripts/reframe.py` | `verify_tone`'s docstring re-aimed (its refusal is unchanged) |
| `tests/lib/test_color.py` | the expression's segments, the range conversion, the degenerate anchor |
| `tests/integration/test_matchgrade.py` | the fragment shape; the §0 pairing table as a test |
| `tests/integration/test_reframe.py` | the re-pinned tone golden |

---

### Task 0: the range constants and the segment builder

**Files:** Modify `scripts/lib/color.py`; Test `tests/lib/test_color.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_tv_range_constants_match_what_the_pipeline_encodes(tmp_path):
    """Measured, not typed: black and white through the repo's own yuv420p h264
    encode land on 16 and 235 in the Y plane, while measure_profile's format=gray
    path reads them as 0 and 255 (design §3). If either end ever changes, every
    tone anchor lands somewhere else and nothing else fails."""
    assert (color.TV_LO, color.TV_LO + color.TV_SPAN) == (16.0, 235.0)


def test_segments_are_the_knots_the_curve_was_given():
    src, dst = (73.0, 137.0, 196.0), (61.0, 123.5, 192.0)
    segs = color._segments(src, dst)
    assert [x for x, _ in segs] == [0.0, 73.0, 137.0, 196.0, 255.0]
    assert [y for _, y in segs][:4] == [0.0, 61.0, 123.5, 192.0]
    top = min(255.0, dst[2] + (255.0 - src[2]) * color.TONE_TOP_SLOPE)
    assert segs[-1] == (255.0, top)


def test_segments_survive_a_zero_low_anchor():
    # p5 == 0 is legal on a crushed source, and the first segment's slope would
    # divide by zero.
    segs = color._segments((0.0, 100.0, 200.0), (10.0, 110.0, 210.0))
    assert segs[0] == (0.0, 0.0) and segs[1] == (0.0, 10.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -k "tv_range or _segments" -q`

- [ ] **Step 3: Implement**

In `scripts/lib/color.py`, beside the other tone constants:

```python
# The Y plane's range, measured (design 2026-08-19 §3): black encodes to 16 and white
# to 235 through this repo's own yuv420p h264, while measure_profile's `format=gray`
# path reads the same two as 0 and 255. `curves` never had to know — it operates on
# RGB, so swscale converts both ways for free. lutyuv writes the plane as stored, so
# the conversion becomes ours, at both ends, or every anchor lands somewhere else with
# nothing failing. tests/lib/test_color.py pins these against a real encode.
TV_LO, TV_SPAN = 16.0, 219.0
```

and the shared knot builder, extracted from `tone_arg`'s body:

```python
def _segments(src: tuple[float, float, float],
              dst: tuple[float, float, float]) -> list[tuple[float, float]]:
    """The (in, out) knots of the tone map, in FULL-range luma.

    Its own function because two readers need exactly these knots: the emitted
    expression and the test that checks the render against `_lerp` over the same
    points. The top endpoint is computed rather than pinned to 255 — see tone_arg."""
    top = min(255.0, dst[2] + (255.0 - src[2]) * TONE_TOP_SLOPE)
    return [(0.0, 0.0), *zip(src, dst), (255.0, top)]
```

- [ ] **Step 4: Run to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "$(cat <<'EOF'
feat(color): the Y plane's range, measured rather than assumed

lutyuv writes the plane as stored and measure_profile reads a full-range gray
still, so black is 16 at one end of this pipeline and 0 at the other. `curves`
never had to know, because it works in RGB and swscale converted both ways
invisibly. The next commit makes that conversion ours, and it needs the two
endpoints pinned to what the repo's own encode actually produces.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1: `tone_arg` emits `lutyuv`

**Files:** Modify `scripts/lib/color.py`; Test `tests/lib/test_color.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_tone_arg_emits_a_luma_only_transfer():
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")
    assert "curves" not in frag              # chroma is no longer on the tone curve


def test_tone_arg_converts_both_ends_of_the_range():
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert f"val-{color.TV_LO}" in frag       # tv Y -> full-range value, on the way in
    assert f"{color.TV_SPAN}/255" in frag     # full-range result -> tv Y, on the way out


def test_tone_arg_still_refuses_the_same_bad_anchors():
    # the validation is unchanged by the actuator swap — pin it so the rewrite
    # cannot quietly drop a refusal along with the spline scaffolding.
    for bad in ((150.0, 90.0, 10.0), (10.0, 10.5, 150.0)):
        with pytest.raises(ValueError):
            color.tone_arg(bad, (20.0, 110.0, 210.0))
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Replace `tone_arg`'s emitting tail (everything from `top = ...` to the `return`)
with:

```python
    # A LUT, not a spline. `curves` fits a natural cubic through whatever points it
    # is given, which is why this used to emit TONE_SAMPLES grid points, join the
    # anchors to the grid, and keep a minimum gap so two control points never nearly
    # coincided (ffmpeg answers that with no frame at all). lutyuv evaluates the
    # expression once per input code and stores a table, so the four segments ARE the
    # map: measured against _lerp over all 256 codes, worst deviation 0.98 codes —
    # integer rounding — and monotone (design 2026-08-19 §2.3).
    #
    # And it is LUMA-only: U and V are never written, so chroma comes out
    # bit-identical (§2.2) and the transfer finally matches the statistic it targets.
    v = f"(val-{TV_LO})*255/{TV_SPAN}"
    segs = _segments(src, dst)
    expr = f"{segs[-1][1]:.4f}"
    for (x0, y0), (x1, y1) in reversed(list(zip(segs, segs[1:]))):
        piece = (f"{y1:.4f}" if x1 == x0 else
                 f"({y0:.4f}+({v}-{x0:.4f})*{(y1 - y0) / (x1 - x0):.6f})")
        expr = f"if(lte({v},{x1:.4f}),{piece},{expr})"
    return f"lutyuv=y='{TV_LO}+({expr})*{TV_SPAN}/255',"
```

Delete `TONE_SAMPLES` and update `tone_arg`'s docstring: the spline paragraphs
describe a problem that no longer exists, and the top-endpoint paragraph stays.

- [ ] **Step 4: Run to verify they pass**
- [ ] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "$(cat <<'EOF'
feat(color): the tone transfer moves to luma, and loses its spline

curves=all applies a non-affine map to R, G and B separately while the target is
a luma statistic, so luma(T(R),T(G),T(B)) is not T(luma(R,G,B)) and the transfer
never quite hit what it aimed at. lutyuv transforms Y and leaves U and V
untouched: measured, chroma comes out bit-identical (30.19 -> 30.19 mean radius
on the drone frame, where curves moved it to 29.47).

Half the function goes with it. Dense sampling, anchor-joining and the minimum
gap were three defences against ffmpeg fitting a cubic through the anchors; a
LUT evaluates the expression once per code, so the four segments are the map.
Measured over all 256 codes: worst deviation 0.98, monotone.

This alone is only a unit of the nine — see the next commit for the other half.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: the instrument stops throwing pixels away

**Files:** Modify `scripts/color_measure.py`; Test `tests/integration/test_matchgrade.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.integration
def test_measure_profile_reads_the_frames_own_highlights(tmp_path, need_filter):
    """A small bright patch on a dark field is exactly what a 12x area reduction
    averages away, and p95 is the statistic that lives in it (design §1)."""
    ...  # build a clip: dark field + a patch 1/400 of the area at 250
    assert measure_profile(str(clip))[2] > 200
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement** — drop `scale=160:-2,` from the `-vf`, and replace the
docstring's "160-wide" sentence with the measurement:

```python
    """(p5, p50, p95) luma of `clip` at time `at` (default: 1s in — a settled frame).

    Decodes ONE grayscale still at the clip's own resolution, histograms it, and
    delegates the percentiles to color.percentiles (numpy stays in this driver, out
    of lib/color).

    At its own resolution and not downscaled: `scale=160:-2` reduced the area 12x and
    read the run's drone frame's p95 NINE UNITS LOW (196 against 205), because
    specular highlights are small and bright and averaging is what a downscale does.
    p5 and p50 are bulk statistics and did not move. Measured, the full frame costs
    66.9ms against 61.0ms for 144x the samples — the decode was always the price, the
    scale filter never was (design 2026-08-19 §1)."""
```

- [ ] **Step 4: Run to verify it passes**
- [ ] **Step 5: Commit**

```bash
git add scripts/color_measure.py tests/integration/test_matchgrade.py
git commit -m "$(cat <<'EOF'
fix(color_measure): stop averaging away the pixels that carry p95

scale=160:-2 reduced the area 12x before histogramming, and read the run's drone
frame's p95 nine units low — 196 against the frame's real 205. Specular
highlights are small and bright, and averaging is what a downscale does; p5 and
p50 are bulk statistics and never moved.

Measured, the full frame costs 66.9ms against 61.0ms for 144x the samples. The
decode was always the price and the scale filter never was.

With the luma transfer from the previous commit, the worst residual over the
run's two cameras goes 9.0 -> 2.0 and 3.0 -> 1.0. Neither half gets there alone:
the transfer alone buys 1 unit, this alone buys 4.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: re-pin the goldens

**Files:** `tests/integration/test_matchgrade.py`, `tests/integration/test_reframe.py`, any other pinned fragment

- [ ] **Step 1: Run the suite and collect every failure**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -40`

- [ ] **Step 2: For each, re-pin to the MEASURED value** — never widen a
tolerance to make a test pass. `test_tone_arg_curve_is_actually_emitted` asserts
the `curves=all='` prefix and becomes the `lutyuv=y='` one;
`test_reframe.py:634`'s comment cites `TONE_SAMPLES=13` as the fix for a dip that
no longer applies and is rewritten to say the LUT has no spline to overshoot.

- [ ] **Step 3: Commit**

---

### Task 4: the real-ffmpeg proofs

**Files:** `tests/integration/test_matchgrade.py`

Three, each with a control:

- [ ] **`test_the_tone_map_renders_within_a_code_of_itself`** — the ramp, all 256
  codes against `_lerp` through `_segments`, worst deviation ≤ 1 and monotone.
  Control: a deliberately non-monotone anchor triple must still be refused by
  `tone_arg`'s validation before it reaches ffmpeg.
- [ ] **`test_the_tone_transfer_leaves_chroma_byte_identical`** — the U and V
  planes before and after, compared as bytes. **Control that must move:** the same
  source through the old per-channel shape (`curves=all` built from the same knots)
  changes them. Without it, "chroma did not move" cannot be told from "nothing
  rendered".
- [ ] **`test_both_halves_are_needed_to_close_the_residual`** — the §0 table:
  measure a synthetic bright-highlight clip four ways (160/full x curves/lutyuv)
  and assert the pair beats either half. This is the test that reddens if someone
  later fixes one half alone.

- [ ] **Commit**

---

### Task 5: mutation battery, suite, docs

- [ ] **Step 1: the battery**, `PYTHONDONTWRITEBYTECODE=1` every row

| # | Mutation | Must redden |
|---|---|---|
| 1 | `TV_LO` 16 → 0 | the range-constant pin |
| 2 | `TV_SPAN` 219 → 255 | the range-constant pin |
| 3 | the `(val-TV_LO)*255/TV_SPAN` conversion dropped on the way in | the ramp proof |
| 4 | the `*TV_SPAN/255` conversion dropped on the way out | the ramp proof |
| 5 | `_segments` drops the computed top, pins `(255, 255)` | the segments unit |
| 6 | `_segments` drops the `(0,0)` origin | the segments unit |
| 7 | `lte` → `lt` in the segment test | the ramp proof (an anchor lands in the wrong segment) |
| 8 | `tone_arg` emits `lutyuv=u=` instead of `y=` | the chroma-identity proof |
| 9 | `measure_profile` puts `scale=160:-2` back | the highlight test AND the pairing test |
| 10 | the pairing test's assert reversed | itself (a sanity row) |

Any survivor is a coverage hole: write the test, do not soften the row.

- [ ] **Step 2: full suite** from a cleared bytecode cache.
- [ ] **Step 3: docs** — `docs/backlog.md` (close both rows; file §5's `lutrgb`
  misdiagnosis candidate, §8's shoulder question, and the "nobody has looked at
  the new grade on a screen" limit), `docs/build-status.md`, `CLAUDE.md`.
- [ ] **Step 4: Commit**

---

## Self-Review

**Spec coverage.** §1 → Task 2. §2 → Tasks 0–1 and 4. §3 → Task 0's constants and
Task 1's conversion, proven by battery rows 1–4. §4 needs no code — it corrects a
prior reading, and Task 4's pairing test is what stops the same mistake being made
again. §5 → docs only, by design. §8's limits → backlog rows.

**Placeholder scan.** Task 2 Step 1 and Task 4 carry `...` for fixture bodies
that must be shaped against `test_matchgrade.py`'s existing scaffolding; every
assertion that carries meaning is written out. Task 3 is deliberately
discovery-driven — the failure list is not knowable before the suite runs — and
its rule ("re-pin to measured, never widen") is the part that matters.

**Type consistency.** `_segments` returns full-range knots everywhere; only the
emitted expression converts. `tone_arg`'s signature and its trailing comma are
unchanged, so `grade_chain`'s composition is untouched.

**The weak point.** Task 3. Re-pinning goldens is where a slice quietly loosens
its own guarantees, and the suite will hand back a list of numbers that all have
a legitimate reason to have moved — which is exactly the situation in which a
wrong number looks like a right one. Every re-pin should be justified by which
of the two changes moved it, and a value that cannot be attributed to either is
a finding, not a re-pin.
