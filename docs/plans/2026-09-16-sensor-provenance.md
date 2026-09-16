# Sensor Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every reading this slice touches name the pixels, the sample count and the baseline it came from — one region resolver shared between the tone stage and the grade description, the dE00 riding the render pair that already exists, an undecidable field deleted, and three report surfaces that state more than they hold.

**Architecture:** `lib/regions.py` gains two pure functions extracted from code it already runs inline (`subject_mask`, `refuse`); `check_episode._subject_delta_advisory` stops decoding files and reads those masks over the `(graded, plain)` RGB stacks `_grade_damage` has already rendered; `color_fidelity.evaluate` loses `dominant`; `check_reel._grade_faithful_check` records its sample count; `match_grade._report_md` loses an unreachable gate once every `measure_crop` stub models the real return shape.

**Tech Stack:** Python 3.12, numpy, pytest, ffmpeg via `scripts/lib/ffbin.py`. Scripts run as modules (`pythonpath = .`); the interpreter is `.venv/bin/python`.

**Design:** `docs/specs/2026-09-16-sensor-provenance-design.md` — read §0 before judging any threshold or shape in this plan; every number below comes from there.

## Global Constraints

- **Never run an installer.** No `brew`, `pip install`, `uv`, `npm`, `apt`, no `setup.sh`. Verification is read-only plus `pytest`. If something is missing, report it — do not install it.
- **Never run `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.** To restore committed content: `git show HEAD:<path> > <path>`. To restore an UNCOMMITTED file you are about to mutate: copy it first (`cp <path> <path>.bak`) and restore from that copy. Run any mutation on an otherwise-clean tree and re-check `git diff --stat` after restoring.
- **`git add` named paths only**, never `git add -A`.
- **Never `git commit --amend`**; a follow-up fix is its own commit.
- **Never push.**
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`** — a one-byte edit can match the previous file's size and mtime-second and CPython then serves a stale `.pyc`.
- **zsh does not word-split an unquoted variable.** A pytest selection held in a shell variable arrives as ONE argument and the run prints `no tests ran`, which reads exactly like a non-discriminating mutation row. Pass selections literally.
- **Enumerate call sites by `grep`, not by memory**, and put the full enumeration in your report.
- **The run at `/Users/serg/Downloads/untitled folder/` is read-only.** Do not write into it.
- Code, comments, commit messages and docs are **English**.
- Exact values that must not drift: `regions.MIN_REGION_FRAC = 0.01`; `regions.FALLBACKS = ("no-route", "too-small", "unorderable")`; `regions.ANCHORS = ("toe", "mid", "shoulder")`; `regions.KINDS = ("subject", "background", "crop")`; `color.FRAMES = 3`; `CheckSpec.entropy_floor = 0.90`; `ReelCheckSpec.grade_residual_max = 4.0`. **No threshold moves in this slice.**
- The full suite before this slice: `3888 passed, 1 skipped`. Any task that ends with fewer passing than it started (minus tests it deliberately deleted) is not done.

---

### Task 1: `regions.subject_mask` and `regions.refuse` — the shared resolver

**Corrected (final review, 2026-09-16): `regions.refuse` shipped with two
keyword parameters, not three.** Every `empty: bool` below — this task's own
`Produces` signature, its test calls, the function body, and Task 3's
`Consumes` line — is the plan **as it was written and executed**, not the
shape that shipped; task bodies are a record of what was asked for and are
left as they read. The final fix wave deleted `empty`: no production caller
could decide it independently of `fraction` (a `None` profile in `measure`
already means a fraction of exactly 0.0; `check_episode` reduces emptiness and
the fraction from the SAME mask; the crop — the one kind the size gate skips —
can never reach `refuse` empty at all, since `assemble` raises on a
profile-less crop before its loop starts). Measured over the whole suite
before the deletion: 288 production calls, 16 of them with `empty=True`, every
one at `fraction == 0.0`, and the two predicates — with the parameter and
without it — agreed on all 288. See the design's own §2.1 for the full
accounting. The shipped signature is `regions.refuse(kind: str, *, located:
bool, fraction: float) -> str | None`.

**Files:**
- Modify: `scripts/lib/regions.py`
- Test: `tests/lib/test_regions.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `regions.subject_mask(extents, n: int, h: int, w: int) -> tuple[np.ndarray, float]` — an `(n, h, w)` bool mask and its fraction.
  - `regions.refuse(kind: str, *, located: bool, fraction: float, empty: bool) -> str | None` — one of `regions.FALLBACKS` or `None`.

The whole point of this task is that it changes **no behaviour**. `regions.measure` and `regions.assemble` keep their exact outputs; the proof is that every pre-existing test in `tests/lib/test_regions.py` and `tests/integration/test_named_regions.py` passes with only the one error-prefix change named in Step 3.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_regions.py`:

```python
def test_subject_mask_marks_the_projected_box_and_reports_its_fraction():
    # One 10x10 frame, a box covering the middle 5x4 = 20 of 100 cells.
    mask, frac = regions.subject_mask([(0.2, 0.3, 0.7, 0.7)], 1, 10, 10)
    assert mask.shape == (1, 10, 10)
    assert mask[0, 3:7, 2:7].all()
    assert mask.sum() == 20
    assert frac == 0.2


def test_subject_mask_keeps_the_part_of_a_straddling_box_that_is_still_in_frame():
    """A subject walking off the left edge is ordinary; what ships is what is
    left inside. The mask must not fabricate pixels at the edge to replace it."""
    mask, frac = regions.subject_mask([(-0.5, 0.0, 0.2, 1.0)], 1, 10, 10)
    assert mask[0, :, :2].all()
    assert not mask[0, :, 2:].any()
    assert frac == 0.2


def test_subject_mask_of_a_box_wholly_outside_the_frame_is_empty_not_clamped():
    mask, frac = regions.subject_mask([(1.4, 1.4, 1.9, 1.9)], 1, 10, 10)
    assert not mask.any()
    assert frac == 0.0


def test_subject_mask_refuses_extents_that_are_not_parallel_to_the_frames():
    with pytest.raises(ValueError, match="2 frames but 1 extents"):
        regions.subject_mask([(0.0, 0.0, 1.0, 1.0)], 2, 4, 4)


def test_refuse_names_no_route_for_a_region_that_was_never_located():
    assert regions.refuse("subject", located=False, fraction=0.0, empty=True) == "no-route"


def test_refuse_names_too_small_for_a_located_region_under_the_floor():
    assert regions.refuse("subject", located=True, fraction=0.009, empty=False) == "too-small"
    assert regions.refuse("subject", located=True, fraction=0.011, empty=False) is None


def test_refuse_names_too_small_for_a_located_region_that_holds_no_pixels():
    """Located and empty has a route and a real measured fraction of 0.0, so it
    is too-small and never no-route — an episode that HAS a route must not be
    told it has none."""
    assert regions.refuse("subject", located=True, fraction=0.0, empty=True) == "too-small"


def test_refuse_never_gates_the_crop_on_size():
    """Every fallback lands on the crop, so a crop under the floor would have
    nowhere to fall back to."""
    assert regions.refuse("crop", located=True, fraction=0.001, empty=False) is None


def test_refuse_rejects_a_kind_outside_the_vocabulary():
    with pytest.raises(ValueError, match="unknown kind"):
        regions.refuse("skin", located=True, fraction=0.5, empty=False)


def test_refuse_returns_only_names_from_the_closed_set():
    for located, empty in ((False, True), (True, True), (True, False)):
        got = regions.refuse("subject", located=located, fraction=0.0, empty=empty)
        assert got is None or got in regions.FALLBACKS
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_regions.py -k "subject_mask or refuse" -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.regions' has no attribute 'subject_mask'`.

- [ ] **Step 3: Extract both functions**

In `scripts/lib/regions.py`, insert both functions immediately above `def measure(`:

```python
def subject_mask(extents, n: int, h: int, w: int) -> tuple[np.ndarray, float]:
    """The tracked subject's (n, h, w) boolean mask, and its fraction of that volume.

    `extents` is one (fx0, fy0, fx1, fy1) tuple of OUTPUT-frame fractions per
    frame — geometry.extent_at_times' own return shape.

    Shared by this region's two readers (design 2026-09-16 §2.1): the tone stage,
    through measure() below, and check_episode's grade description, which means
    over the same mask in RGB instead of luma. ONE rule, so the fraction a
    fallback is decided on is the same number on both sides.
    """
    if len(extents) != n:
        raise ValueError(f"regions.subject_mask: {n} frames but {len(extents)} extents "
                         "— they must be parallel, one extent per sampled frame")
    mask = np.zeros((n, h, w), dtype=bool)
    for i, (fx0, fy0, fx1, fy1) in enumerate(extents):
        # Clamped, not refused: extent_at_times projects the tracked bbox, and a
        # subject that walks partly out of the delivered frame is ordinary. What
        # is left inside is what ships, so it is what gets measured. A box with no
        # overlap at all contributes NO pixels — never a fabricated edge sample,
        # which is what the check_episode box reader it replaces used to do
        # (design §0.6).
        x0, y0 = max(0, int(fx0 * w)), max(0, int(fy0 * h))
        x1, y1 = min(w, int(fx1 * w)), min(h, int(fy1 * h))
        if x1 > x0 and y1 > y0:
            mask[i, y0:y1, x0:x1] = True
    return mask, float(mask.mean())


def refuse(kind: str, *, located: bool, fraction: float, empty: bool) -> str | None:
    """Why `kind` cannot supply a reading — one of FALLBACKS, or None when it can.

    The decision assemble() used to make inline, lifted so check_episode's grade
    description makes the SAME one (design 2026-09-16 §2.1). `unorderable` is
    deliberately not here: it is a property of a three-anchor profile, and a
    single reading has none.

    `empty` is "located, and holds no pixels" — a subject entirely outside the
    delivered frame. It has a route and a real, measured fraction of 0.0, so it
    reports `too-small`; `no-route` would say something false about the episode.

    The crop is never gated on size: every fallback lands there, so a refused
    crop would have nowhere to fall back to.
    """
    if kind not in KINDS:
        raise ValueError(f"regions.refuse: unknown kind {kind!r} — one of {KINDS}")
    if not located:
        return "no-route"
    if empty or (kind != "crop" and fraction < MIN_REGION_FRAC):
        return "too-small"
    return None
```

- [ ] **Step 4: Route `measure` through `subject_mask`**

In `regions.measure`, delete the parallel-length guard and the mask-building block:

```python
    if len(extents) != n:
        raise ValueError(f"regions.measure: {n} frames but {len(extents)} extents — "
                         "they must be parallel, one extent per sampled frame")
    mask = np.zeros((n, h, w), dtype=bool)
    for i, (fx0, fy0, fx1, fy1) in enumerate(extents):
        # Clamped, not refused: extent_at_times projects the tracked bbox, and a
        # subject that walks partly out of the delivered frame is ordinary. What
        # is left inside is what ships, so it is what gets measured.
        x0, y0 = max(0, int(fx0 * w)), max(0, int(fy0 * h))
        x1, y1 = min(w, int(fx1 * w)), min(h, int(fy1 * h))
        if x1 > x0 and y1 > y0:
            mask[i, y0:y1, x0:x1] = True
    frac = float(mask.mean())
```

and replace all of it with:

```python
    mask, frac = subject_mask(extents, n, h, w)
```

The guard's message prefix changes from `regions.measure:` to `regions.subject_mask:`. Find the test that pins it (`grep -rn "frames but" tests/`) and update its `match=` to the substring `"2 frames but 1 extents"`, which is prefix-free and survives either spelling.

- [ ] **Step 5: Route `assemble` through `refuse`**

In `regions.assemble`, replace the three-branch body of the `for anchor in ANCHORS:` loop:

```python
        if not r.located:
            rows.append(AnchorReading(anchor, want.name, want.of, "crop", r.fraction,
                                      crop.profile[idx], "no-route"))
        elif r.profile is None or (want.of != "crop" and r.fraction < MIN_REGION_FRAC):
            # Located and empty is the `r.profile is None` half: a real fraction
            # (0.0) under any gate, so it lands here rather than on `no-route`.
            rows.append(AnchorReading(anchor, want.name, want.of, "crop", r.fraction,
                                      crop.profile[idx], "too-small"))
        else:
            rows.append(AnchorReading(anchor, want.name, want.of, want.of, r.fraction,
                                      r.profile[idx], None))
```

with:

```python
        # ONE rule, shared with check_episode's grade description (design §2.1).
        # `empty` is the located-and-holds-no-pixels case, which refuse() names
        # `too-small` at its real measured fraction of 0.0 — see its docstring.
        fb = refuse(want.of, located=r.located, fraction=r.fraction,
                    empty=r.profile is None)
        rows.append(AnchorReading(anchor, want.name, want.of,
                                  "crop" if fb else want.of, r.fraction,
                                  crop.profile[idx] if fb else r.profile[idx], fb))
```

- [ ] **Step 6: Run the new tests and the whole regions suite**

Run: `.venv/bin/python -m pytest tests/lib/test_regions.py tests/integration/test_named_regions.py -v`
Expected: PASS, every pre-existing test included and unmodified except the one `match=` string from Step 4.

- [ ] **Step 7: Run everything the refactor could reach**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/integration/test_color_measure.py tests/integration/test_bound_reports.py tests/integration/test_mood_contract.py -q`
Expected: PASS, unchanged counts.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/regions.py tests/lib/test_regions.py
git commit -m "refactor(regions): one resolver for the mask and the fallback, so a second reader cannot invent its own"
```

---

### Task 2: `color_fidelity` loses `dominant`

**Files:**
- Modify: `scripts/lib/color_fidelity.py`
- Test: whichever tests pin the field — find them with `grep -rn "dominant" tests/ scripts/ skills/ references/ docs/`

**Interfaces:**
- Consumes: nothing.
- Produces: `color_fidelity.evaluate(pairs) -> dict` with keys `delta_e`, `delta_l`, `delta_c`, `delta_h`, `samples` (and the unchanged `{"status": "not-checked", "reason": ...}` shape for empty input). **`dominant` is gone.**

Design §0.5 is the whole case: over the four real episodes whose render plans build, `dominant` flips on **three of them** between 3 and 5 samples, every flip has its top two components within 0.5, and ep7 at n=3 is an exact tie (|ΔC\*| = |ΔH\*| = 1.22) broken by the order of `_COMPONENTS`. Task 3 moves this sensor from 5 samples to 3, so leaving the field in place means shipping those flips.

- [ ] **Step 1: Write the failing test**

Append to the file that already tests `evaluate` (find it: `grep -rln "color_fidelity.evaluate" tests/`):

```python
def test_evaluate_reports_the_three_components_and_no_ranking_of_them():
    """`dominant` was a ranking of three numbers that cannot be ranked: it flips
    on three of four real episodes with a sample-count change, and one real
    episode is an exact tie broken by tuple order (design 2026-09-16 §0.5).
    The components are the explanation; the reader ranks them or does not."""
    out = color_fidelity.evaluate([((10, 20, 30), (40, 50, 60))])
    assert set(out) == {"delta_e", "delta_l", "delta_c", "delta_h", "samples"}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest <that file> -k "no_ranking" -v`
Expected: FAIL — the key set still contains `dominant`.

- [ ] **Step 3: Delete the field and the tuple it ranked**

In `scripts/lib/color_fidelity.py`, delete the module constant

```python
# Report names for the three signed components, in ciede2000's own order.
_COMPONENTS = ("luma", "chroma", "hue")
```

delete this line from `evaluate`

```python
    dominant = _COMPONENTS[max(range(3), key=lambda i: abs(comps[i]))]
```

and drop `"dominant": dominant,` from the returned dict.

Replace the docstring's last paragraph

```python
    The three components are reported but do not vote. They are the explanation:
    `dominant` names whichever moved most, so a report reads as "the grade lifted
    exposure" rather than "the colour changed by 6"."""
```

with

```python
    The three signed components are reported but do not vote. They are the
    explanation — "the grade lifted exposure" rather than "the colour changed by
    6" — and they are reported as three numbers, not as a winner among them: the
    `dominant` field this returned until 2026-09-16 flipped on three of the four
    real episodes when the sample count moved from 5 to 3, with the top two
    components within 0.5 in every flip and one exact tie at 1.22 broken by the
    order of a tuple (design 2026-09-16 §0.5)."""
```

- [ ] **Step 4: Run the test and every consumer's tests**

Run: `.venv/bin/python -m pytest tests/ -q -k "fidelity or check_episode or grade"`
Expected: PASS, except any test that asserts on `dominant` — update each to assert the components instead, and record every file you changed in your report.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/color_fidelity.py <the test files you changed>
git commit -m "fix(color_fidelity): delete a ranking of three numbers that ties, flips with the sample count, and is resolved by tuple order"
```

---

### Task 3: The dE00 advisory rides `grade_damage`'s render pair

**Files:**
- Modify: `scripts/check_episode.py`
- Modify: `scripts/episode_qc.py` (the stale `SAMPLE_FRACS` coincidence comment)
- Test: `tests/test_check_episode.py`, `tests/integration/test_color_fidelity.py`

**Interfaces:**
- Consumes: `regions.subject_mask(extents, n, h, w)`, `regions.refuse(kind, *, located, fraction, empty)` (Task 1); `color_fidelity.evaluate` without `dominant` (Task 2).
- Produces: `_subject_delta_advisory(plain_frames, graded_frames, times, route_pts, path_obj, meta) -> dict` carrying `advisory_delta_e`, `region`, `region_fraction`, `region_fallback`, `delta_e`, `delta_l`, `delta_c`, `delta_h`, `samples`, and `background_delta_e` **only when no fallback fired**. `_grade_damage` loses its `clip` parameter.

Deleted in this task: `SAMPLE_FRACS`, `_box_mean_rgb`, `_last_sampleable_t`, the unreachable `source is None` branch inside the advisory, and the `"no source clip or no tracked subject"` disjunction (design §0.6: the advisory is only ever reached after `_grade_damage` has already returned on `source is None`).

- [ ] **Step 1: Write the failing tests**

Replace the whole body of `tests/test_check_episode.py` (it exists only to test `_box_mean_rgb`) with:

```python
"""Unit proofs for check_episode's grade description. Two numpy frame stacks are
all the advisory needs, so this needs no ffmpeg and does not carry the
integration marker. The real-bytes proof is tests/integration/test_color_fidelity.py."""
import numpy as np
import pytest
from scripts import check_episode
from scripts.lib.models import CropPath, PathMeta, RoutePoint

N, H, W = 3, 40, 60


def _stacks(sub_plain=(10, 10, 10), sub_graded=(200, 10, 10),
            bg_plain=(60, 60, 60), bg_graded=(60, 60, 60)):
    """A plain/graded pair whose SUBJECT box moves and whose background does not."""
    plain = np.zeros((N, H, W, 3), np.uint8)
    graded = np.zeros((N, H, W, 3), np.uint8)
    plain[:] = bg_plain
    graded[:] = bg_graded
    plain[:, 10:30, 20:40] = sub_plain      # 20x20 of 40x60 = 16.7% of the frame
    graded[:, 10:30, 20:40] = sub_graded
    return list(plain), list(graded)


def _sidecar(box=(30.0, 20.0, 20.0, 20.0), src_w=60, src_h=40):
    """A route/path/meta trio that projects `box` onto the SAME rect the stacks
    paint, so the mask and the painted pixels agree by construction."""
    x, y, w, h = box
    route = [RoutePoint(t=t, x=x, y=y, w=w, h=h) for t in (0.0, 0.5, 1.0)]
    path = CropPath(xs=[0.0, 0.0, 0.0])
    meta = PathMeta(crop_w=src_w, crop_h=src_h, crop_y=0, out_dims=(W, H),
                    rect_px=(0, 0, W, H), freedom=0)
    return route, path, meta


def test_the_advisory_reads_the_subject_and_names_the_region_it_read():
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "subject"
    assert d["region_fallback"] is None
    assert d["region_fraction"] == pytest.approx(0.1667, abs=5e-4)
    assert d["delta_e"] > 10          # (10,10,10) -> (200,10,10) is a large move
    assert d["samples"] == 3
    assert d["advisory_delta_e"] is True


def test_the_advisory_reports_the_background_beside_the_subject():
    """The contamination check the folded backlog row is about: on a global grade
    the two agree, on a targeted one they do not (design §2.3)."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    # the background is painted identically on both sides — it did not move
    assert d["background_delta_e"] == 0.0
    assert d["delta_e"] > d["background_delta_e"]


def test_a_subject_under_the_floor_falls_back_to_the_crop_and_says_so():
    plain, graded = _stacks()
    # 4x4 of 40x60 = 0.17% of the frame, under regions.MIN_REGION_FRAC
    route, path, meta = _sidecar(box=(30.0, 20.0, 4.0, 4.0))
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "crop"
    assert d["region_fallback"] == "too-small"
    assert d["region_fraction"] == pytest.approx(0.0067, abs=5e-4)
    # the fraction reported is the SUBJECT's, the evidence for the fallback —
    # never the crop's 1.0 it fell back to
    assert d["region_fraction"] < 0.01
    assert "background_delta_e" not in d


def test_a_routeless_episode_reads_the_crop_and_names_no_route():
    """A pan has no subject. Today this reports delta_e: null; after this slice
    it reports a real crop reading with the absence named."""
    plain, graded = _stacks()
    _, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              None, path, meta)
    assert d["region"] == "crop"
    assert d["region_fallback"] == "no-route"
    assert d["region_fraction"] == 0.0
    assert d["delta_e"] is not None
    assert "background_delta_e" not in d


def test_the_advisory_refuses_two_stacks_of_different_shapes():
    """The two stacks are two renders of ONE plan pair — a disagreement is a
    caller error, not an input to broadcast over."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    with pytest.raises(ValueError, match="same shape"):
        check_episode._subject_delta_advisory(plain[:2], graded, [0.0, 0.5, 1.0],
                                              route, path, meta)


def test_every_fallback_the_advisory_can_report_is_a_regions_name():
    from scripts.lib import regions
    plain, graded = _stacks()
    _, path, meta = _sidecar()
    for route in (None, _sidecar(box=(30.0, 20.0, 4.0, 4.0))[0], _sidecar()[0]):
        d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                                  route, path, meta)
        assert d["region_fallback"] is None or d["region_fallback"] in regions.FALLBACKS
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/test_check_episode.py -v`
Expected: FAIL — `TypeError` on the old signature, or `KeyError: 'region'`.

- [ ] **Step 3: Rewrite the advisory**

In `scripts/check_episode.py`, delete these three top-level definitions entirely:

- the `SAMPLE_FRACS` constant and its comment,
- `def _box_mean_rgb(...)` and its docstring,
- `def _last_sampleable_t(...)` and its docstring.

Add `regions` to the `scripts.lib` import list, and drop `assembly` from it if nothing else in the file uses it (`grep -n "assembly\." scripts/check_episode.py` before deciding — do not guess).

Replace the whole of `_subject_delta_advisory` with:

```python
def _region_pairs(plain, graded, mask) -> list[tuple]:
    """One (plain_rgb, graded_rgb) mean pair per frame, over that frame's own mask.

    A frame whose mask slice holds no pixels contributes NO pair rather than a
    fabricated one: an empty slice would mean() to NaN in silence. The count that
    survives is what color_fidelity.evaluate reports as `samples`."""
    pairs = []
    for i in range(len(graded)):
        m = mask[i]
        if not m.any():
            continue
        pairs.append((tuple(float(plain[i][m][:, c].mean()) for c in range(3)),
                      tuple(float(graded[i][m][:, c].mean()) for c in range(3))))
    return pairs


def _subject_delta_advisory(plain_frames, graded_frames, times: list[float],
                            route_pts: list[RoutePoint] | None,
                            path_obj: CropPath, meta: PathMeta) -> dict:
    """The grade's dE00 over a NAMED region, as a DESCRIPTION (design 2026-09-16).

    Both stacks come from the (graded, plain) render pair _grade_damage has
    already decoded: same geometry, same times, same baseline as the entropy
    ratio that carries the verdict. Until 2026-09-16 this decoded the raw source
    and the shipped clip instead — two more decodes and four more ffprobes, in a
    different geometry at a different time set, two lines after the pair it could
    have used. Zero coverage was lost by the swap: the advisory is only ever
    reached after _grade_damage has returned on a missing pair (design §0.3).

    The region is resolved by regions.subject_mask/refuse — the SAME rule the
    tone stage authors a grade with — so a subject under regions.MIN_REGION_FRAC
    reads the crop and SAYS which, instead of reporting the grade's effect on
    whatever a 0.23%-of-frame box happened to contain (design §0.2: that box is
    exactly where the region choice is worth the most and trustworthy the least).

    `background_delta_e` rides along only when the subject supplied the reading:
    after a fallback the reading IS the crop, and a crop and its background agree
    to 0.03 on seven of the eight real episodes (design §0.1) — two names for one
    number.
    """
    g, p = np.asarray(graded_frames), np.asarray(plain_frames)
    if g.shape != p.shape:
        raise ValueError(f"check_episode: the graded and plain frames must have the "
                         f"same shape — got {g.shape} and {p.shape}. They are two "
                         f"renders of ONE plan pair; a disagreement is a caller "
                         f"error, not an input to broadcast over")
    n, h, w = g.shape[:3]
    if route_pts:
        extents = geometry.extent_at_times(route_pts, path_obj, meta, times)
        mask, frac = regions.subject_mask(extents, n, h, w)
        located, empty = True, not mask.any()
    else:
        mask, frac, located, empty = None, 0.0, False, True
    fallback = regions.refuse("subject", located=located, fraction=frac, empty=empty)
    read = np.ones((n, h, w), dtype=bool) if fallback else mask
    out = {"advisory_delta_e": True,
           "region": "crop" if fallback else "subject",
           # the fraction of the region ASKED for — on a too-small row it is the
           # small number that is the evidence, never the crop's 1.0 it fell back
           # to. regions.AnchorReading.fraction's own convention (design §2.3).
           "region_fraction": round(frac, 4),
           "region_fallback": fallback,
           **color_fidelity.evaluate(_region_pairs(p, g, read))}
    if fallback is None:
        out["background_delta_e"] = color_fidelity.evaluate(
            _region_pairs(p, g, ~mask)).get("delta_e")
    return out
```

- [ ] **Step 4: Wire `_grade_damage` to pass its own frames**

In `_grade_damage`, drop the `clip` parameter from the signature and change the advisory call:

```python
    d.update(_subject_delta_advisory(clip, source, route_pts, path_obj, meta))
```

becomes

```python
    d.update(_subject_delta_advisory(p_frames, g_frames, times, route_pts, path_obj, meta))
```

Update its docstring's last paragraph to say the description now rides the same pair as the verdict, citing design 2026-09-16 §0.3.

Then fix the one call site — find it with `grep -n "_grade_damage(" scripts/check_episode.py` — by removing the `clip` argument.

- [ ] **Step 5: Retire the stale coincidence comment**

In `scripts/episode_qc.py`, the comment above `SENSOR_FRAMES` warns that `(k+0.5)/5` coincides with `check_episode.SAMPLE_FRACS`. That constant no longer exists. Replace the comment block

```python
# (k+0.5)/5 happens to produce check_episode.SAMPLE_FRACS' five fractions, but of a
# different quantity — clip duration here, route span there — and NOTHING ties the two.
# Either can move without the other noticing; no code depends on the agreement
# (design 2026-08-28 §9.9).
```

with

```python
# Independent of every other sample count in the tree. The coincidence design
# 2026-08-28 §9.9 recorded — these five fractions equalling check_episode's
# SAMPLE_FRACS — retired with that constant on 2026-09-16, when the grade
# description moved onto the render pair's own color.sample_times.
```

- [ ] **Step 6: Run the unit tests**

Run: `.venv/bin/python -m pytest tests/test_check_episode.py -v`
Expected: PASS, all seven.

- [ ] **Step 7: Rewrite the real-bytes proof**

`tests/integration/test_color_fidelity.py` drives the old path: it builds `source.mp4` (640x360) and cropped "graded" clips (480x360) and calls the advisory with file paths. The advisory now takes two frame stacks of ONE shape.

Keep the fixture recipes. Change how the frames arrive: render or decode BOTH sides at the same dimensions and pass the arrays. The file's own second fixture pair — "a real authored `ReframeSpec` colour block rendered by `reframe.reframe` itself" — is already the right shape; extend that approach to the first three.

Requirements for the rewritten file, each of which must be a separate test:

1. A real-ffmpeg faithful pair (no colour change) reports a small `delta_e` over `region: "subject"`.
2. A real-ffmpeg broken pair (`hue=h=120`) reports a large `delta_e` over `region: "subject"` — the control for (1), and it must not merely differ, it must exceed (1) by more than a factor of three.
3. A real-ffmpeg episode whose route box is under `regions.MIN_REGION_FRAC` reports `region: "crop"`, `region_fallback: "too-small"`, and NO `background_delta_e`.
4. `check_episode.run(..., source=, plans=)` end to end: the `grade_damage` detail carries `region`, `region_fraction`, `region_fallback`, and the verdict (`passed`) is decided by the entropy ratio alone — assert the same `passed` for an episode whose `delta_e` is large, proving the description does not vote.
5. The advisory issues no subprocess of its own: monkeypatch `scripts.lib.proc.run` to raise, call the advisory with two frame stacks, and assert it returns a reading. (This is the "rides the pair" proof — the old path would have called ffprobe and ffmpeg.)
6. The advisory reads the objects `_grade_damage` decoded, not a second decode of its own: monkeypatch `check_episode._subject_delta_advisory` with a recorder, run `check_episode.run(..., source=, plans=)`, and assert the two stacks it received are the SAME objects `reframe.plan_frames_rgb` returned (record those too, by wrapping `check_episode.reframe.plan_frames_rgb`) — identity, `is`, not equality.
7. ONE resolver, two readers (design §4 proof 2): the same episode whose subject is under `regions.MIN_REGION_FRAC` reports `too-small` from `regions.assemble` (through `color_measure.measure_crop`) and from the advisory, at the SAME `fraction`. Assert the two fractions are equal, not merely both small — that equality is the whole claim of the shared resolver.

Delete the tests that only existed for `_last_sampleable_t`'s clamp and `_box_mean_rgb`'s asymmetry: both functions are gone, and `regions.subject_mask`'s own tests (Task 1) now pin the straddling-box behaviour that replaced them. Say in your report exactly which tests you deleted and which behaviour now covers each.

- [ ] **Step 8: Run the integration proof and everything downstream**

Run: `.venv/bin/python -m pytest tests/integration/test_color_fidelity.py tests/integration/test_check_episode.py tests/integration/test_grade_sensor_references.py tests/integration/test_process_episode.py tests/integration/test_probe.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/check_episode.py scripts/episode_qc.py tests/test_check_episode.py tests/integration/test_color_fidelity.py
git commit -m "feat(check_episode): the grade description names its region and rides the pair the verdict already rendered"
```

---

### Task 4: `grade_faithful` records the sample count it read over

**Files:**
- Modify: `scripts/check_reel.py` (inside `_grade_faithful_check`)
- Test: `tests/lib/test_check_reel.py` or `tests/integration/test_grade_sensor_references.py` — find where `grade_faithful`'s detail is asserted (`grep -rn "grade_faithful" tests/`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `grade_faithful`'s detail dict gains `"frames": int` — the per-episode count actually read from the master, `0` when no episode could be predicted.

The backlog row: `grade_damage`'s report carries a `frames` key precisely so a silently reduced or enlarged sample count is visible; `grade_faithful` has no analogous field, and its `color.sample_times(dur)` call picks the count with no parameter and no record.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_check_reel.py` (its imports already carry
`check_reel` and `ReelCheckSpec`):

```python
def test_grade_faithful_records_the_sample_count_it_read(monkeypatch):
    """Not color.FRAMES echoed back — the count that actually ran. Changing the
    call must move the field, which is the whole point of recording it: seven
    here, against a color.FRAMES of three."""
    seen = {}

    def fake_batch(master, spans):
        seen["n"] = len(spans[0])
        return [(10.0, 100.0, 200.0) for _ in spans]

    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch", fake_batch)
    monkeypatch.setattr(check_reel.color, "sample_times",
                        lambda dur, frames=7: [dur * (k + 0.5) / 7 for k in range(7)])
    cr, fail = check_reel._grade_faithful_check(
        "master.mp4", [4.0], [], ReelCheckSpec(target_dur=4.0),
        [(10.0, 100.0, 200.0)], None, None)
    assert seen["n"] == 7
    assert cr.detail["frames"] == 7
    assert fail is None


def test_grade_faithful_records_zero_frames_when_nothing_could_be_predicted(monkeypatch):
    """`0` is a true statement that nothing was read — the check examined no
    pixels, and the report says so beside its own not-checked status."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda master, spans: (_ for _ in ()).throw(
                            AssertionError("nothing to read")))
    cr, fail = check_reel._grade_faithful_check(
        "master.mp4", [4.0], [], ReelCheckSpec(target_dur=4.0), [None], None, None)
    assert cr.passed is None
    assert cr.detail["frames"] == 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest <that file> -k "records_the_sample_count" -v`
Expected: FAIL — `KeyError: 'frames'`.

- [ ] **Step 3: Record the count**

In `_grade_faithful_check`, the `detail` dict:

```python
    detail = {"residuals": residuals, "not_checked": not_checked,
              "max": spec.grade_residual_max,
              "target_dev": target_dev, "target_dev_advisory": True,
              "target_dev_reason": target_dev_reason}
```

becomes

```python
    detail = {"residuals": residuals, "not_checked": not_checked,
              "max": spec.grade_residual_max,
              # The count actually read from the master per episode, not
              # color.FRAMES — a constant echoing itself would record nothing and
              # would not move if the call above changed. grade_damage's report
              # carries `frames` for exactly this reason; this one had no
              # analogue, so a silently changed N was invisible downstream
              # (design 2026-09-16 §2.5). 0 when nothing was predicted, which is
              # a true statement that nothing was read.
              "frames": len(spans[0]) if spans else 0,
              "target_dev": target_dev, "target_dev_advisory": True,
              "target_dev_reason": target_dev_reason}
```

- [ ] **Step 4: Run the test and the reel checks**

Run: `.venv/bin/python -m pytest tests/ -q -k "check_reel or grade_faithful or sensor_references"`
Expected: PASS. Any test asserting `grade_faithful`'s detail as a whole object gains the new key — update each and list them in your report.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_reel.py <the test files you changed>
git commit -m "fix(check_reel): grade_faithful states a residual, so it states what it read it over"
```

---

### Task 5: The two report surfaces from the previous slice

**Files:**
- Modify: `tests/conftest.py` (the shared stub-shape helper)
- Modify: `scripts/match_grade.py` (delete the unreachable gate)
- Modify: `tests/lib/test_match_grade.py`, `tests/integration/test_bound_reports.py`, `tests/integration/test_mood_contract.py`, `tests/integration/test_matchgrade.py` (every `measure_crop` stub)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tests/conftest.py::crop_anchor_rows(profile) -> tuple[regions.AnchorReading, ...]` — the three crop rows the real `measure_crop` always returns.

Two backlog rows, both filed by the named-regions Task 7 review:

- `_report_md`'s `if any(d.regions for d in decisions)` is unreachable for every real input, because `regions.assemble` always returns three rows — every undeclared anchor still reports, over the crop. Same shape as `gradedamage.ENTROPY_BINS`, which this repo settled by deletion.
- `test_write_match_rewrites_the_edl_and_writes_md` pins `MATCH.md` byte-exactly but gives its second episode an empty tuple, so the one place the region table's exact bytes are held holds one of its two episodes.

- [ ] **Step 1: Add the shared helper**

In `tests/conftest.py`, add (importing `regions` at the top if it is not already imported):

```python
def crop_anchor_rows(profile) -> tuple:
    """The three crop AnchorReadings the REAL measure_crop always returns.

    regions.assemble falls every undeclared anchor back to the crop, so a run
    with no REGIONS.json still reports three rows — never an empty tuple. A stub
    returning () models a shape production cannot produce, and it was what kept
    an unreachable `if any(d.regions ...)` gate in match_grade._report_md looking
    reachable (design 2026-09-16 §2.6)."""
    return tuple(regions.AnchorReading(a, "crop", "crop", "crop", 1.0, v, None)
                 for a, v in zip(regions.ANCHORS, profile))
```

- [ ] **Step 2: Enumerate every stub by grep, then fix them all**

Run: `grep -rn 'setattr(match_grade, "measure_crop"' tests/`

There are **23** at the time of writing; re-run the grep rather than trusting that number. Every one whose lambda returns `(profile, ())` becomes `(profile, crop_anchor_rows(profile))`. Where the profile is a literal triple, pass that literal. Where it is `profs[src]` or `_MOOD_PROFS[src]`, bind it first, e.g.

```python
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (profs[src], crop_anchor_rows(profs[src])))
```

Leave `_never` (the stub that raises) alone. Put the complete enumeration — every file and line you changed, and every one you deliberately did not — in your report.

- [ ] **Step 3: Run and watch the byte-exact pins fail**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/integration/test_bound_reports.py tests/integration/test_mood_contract.py tests/integration/test_matchgrade.py -q`
Expected: FAIL on every test that pins `MATCH.md`'s bytes — each now carries region rows it did not before. That failure is the point: those reports were short because their stubs modelled a shape production cannot emit.

- [ ] **Step 4: Extend the byte-exact pin**

In `test_write_match_rewrites_the_edl_and_writes_md`, replace the local `d_rows` construction and the stub with:

```python
    d_prof, b_prof = (10.0, 90.0, 150.0), (40.0, 130.0, 240.0)
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k:
                        (d_prof, crop_anchor_rows(d_prof)) if "d.mp4" in src
                        else (b_prof, crop_anchor_rows(b_prof)))
```

and extend the pinned markdown's region table with episode 1's three rows:

```
"| 1 | toe | crop | crop | 100.00% | 40 | — |\n"
"| 1 | mid | crop | crop | 100.00% | 130 | — |\n"
"| 1 | shoulder | crop | crop | 100.00% | 240 | — |\n"
```

Update the comment above the stub: it currently explains why only `d.mp4` carries rows, and that reason is gone.

Then fix every other pin the grep in Step 3 turned red, the same way.

- [ ] **Step 5: Delete the unreachable gate**

In `scripts/match_grade._report_md`, delete the six-line comment block starting `# Reachable only via a measure_crop STUB` and the `if any(d.regions for d in decisions):` line, and dedent its body by four spaces. The result:

```python
    # regions.assemble fills all three anchors for every real episode — an
    # undeclared one falls back to the crop and still reports — so this table is
    # unconditional. It was guarded until 2026-09-16 by a condition only a test
    # double could make false; the doubles now model the real shape
    # (design 2026-09-16 §2.6).
    lines += ["", "| # | anchor | region | kind | % of frame | value | fallback |",
              "|---|--------|--------|------|-----------:|------:|----------|"]
    for d in decisions:
        for r in d.regions:
            fb = r["fallback"] or "—"
            # TWO decimals, not one: MIN_REGION_FRAC is 1% of the frame, and
            # ".1f" rounds a 0.0099 region — which the gate REFUSED — to "1.0%",
            # printed beside a `too-small` fallback the docs describe as "under
            # 1% of the frame". A printed number must not round across the gate
            # it is being shown next to (whole-branch review, finding 9). The
            # stored value already carries four places (_row_dict).
            lines.append(f"| {d.index} | {r['anchor']} | {r['name']} | {r['of']} "
                         f"| {r['fraction'] * 100:.2f}% | {r['value']:.0f} | {fb} |")
```

- [ ] **Step 6: Run the match-grade suites**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/integration/test_bound_reports.py tests/integration/test_mood_contract.py tests/integration/test_matchgrade.py tests/integration/test_named_regions.py tests/integration/test_grade_shipped_pixels.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py scripts/match_grade.py tests/lib/test_match_grade.py tests/integration/test_bound_reports.py tests/integration/test_mood_contract.py tests/integration/test_matchgrade.py
git commit -m "fix(match-grade): delete a gate only a test double can trip, and pin both episodes of the report it guarded"
```

---

### Task 6: The judge's instructions, the docs, the queue, the version

**Files:**
- Modify: `skills/episode-qc/episode-reviewer.md`, `skills/episode-qc/SKILL.md`
- Modify: `CLAUDE.md` (two registry rows), `docs/build-status.md`, `docs/backlog.md`, `docs/backlog-closed.md`, `docs/pipeline-map.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: the report shape from Task 3 (`region`, `region_fraction`, `region_fallback`, `background_delta_e`, no `dominant`) and Task 4 (`frames`).
- Produces: nothing code-facing.

- [ ] **Step 1: Rewrite the judge's colour paragraph**

`skills/episode-qc/episode-reviewer.md` and `skills/episode-qc/SKILL.md` both name `dominant` and both tell the judge that a pan reports `delta_e: null` with `delta_reason`. All three facts changed. The rewritten guidance must say:

- the advisory reports `delta_e` plus three signed components (`delta_l`/`delta_c`/`delta_h`); there is no ranking of them, because a ranking of three numbers that tie cannot be made;
- **read `region` before `delta_e`** — a reading whose `region` is `crop` is not a statement about the subject, and `region_fallback` says why (`too-small`: the tracked box was under 1% of the frame; `no-route`: a scenery pan has no subject at all);
- `background_delta_e`, present only when the subject supplied the reading, is the contamination check: close to `delta_e` means the grade moved everything, far from it means the grade moved the subject and its surroundings differently;
- a large `delta_e` is still not itself a finding — the entropy ratio carries the verdict, and a real regrade is supposed to move colour;
- the `{"status": "not-checked", "passed": null}` arm on the whole `grade_damage` block is unchanged and still means the render plans were unavailable.

Delete every mention of `delta_reason` and `dominant` from both files. Verify with `grep -rn "dominant\|delta_reason" skills/ references/ docs/` that nothing else still names them, and fix whatever does.

- [ ] **Step 2: Run the skills-contract tests**

Run: `.venv/bin/python -m pytest tests/test_skills_contract.py tests/test_skill_convention.py tests/test_cli_help.py -q`
Expected: PASS.

- [ ] **Step 3: Sync the registry and the docs**

- `CLAUDE.md`: add the design and plan rows at the **chronological end** of the Quick Reference table, matching the density and voice of the named-regions rows directly above them. The design row must carry §0's overturns: the crop equals the background to 0.03 on seven of eight; the region choice is worth 0.06–0.46 where the box is trustworthy and 0.99 where it is not; the advisory already ran only when the pair existed and re-decoded anyway; `dominant` flips on three of four episodes and ties on one.
- `docs/pipeline-map.md`: stage 5.11's row names `delta_e`/`dominant` — update it.
- `docs/build-status.md`: a Done entry for this slice.
- `CHANGELOG.md`: a `0.11.0` entry, newest first, and `.claude-plugin/plugin.json` bumped to `0.11.0` in the same commit (`tests/test_plugin_manifests.py` enforces the match).

- [ ] **Step 4: Move the four closed rows**

In `docs/backlog.md`:

- R2.1 stays `◐`. Append to its note: the dE00 sampling-box half is closed 2026-09-16, with what the measurement found (the premise held, the consequence was small except on the box the gate refuses), and state that R2.1 now waits on exactly one thing — a chroma target.
- Delete the P3 `color_fidelity` sampling-box line (in the P3 "Front-half sensors"-adjacent colour group) and move it to `docs/backlog-closed.md` with its closure note.
- Move the two P2 rows (`_report_md`'s inert gate; the half-covered `MATCH.md` pin) and the P2 `grade_faithful` sample-count row to `docs/backlog-closed.md`, each with its closure note.
- Add the three new rows from design §6: a masked `subject` already exists as a row — leave it and point it at this design's §5; chroma agreement already exists as a P3 line — leave it and note the instrument is now in hand; add ONE new row for the encode's own colour cost, P4, size S, sourced to this design §5.

Count the rows before and after (`grep -c '^| [○◐⊘]'` per section) and put both counts in your report.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Report the exact counts against the 3888/1 baseline and account for every difference.

- [ ] **Step 6: Commit**

```bash
git add skills/episode-qc CLAUDE.md docs/pipeline-map.md docs/build-status.md docs/backlog.md docs/backlog-closed.md CHANGELOG.md .claude-plugin/plugin.json
git commit -m "docs: the judge reads a region before a number, and four rows leave the queue"
```

---

### Task 7: The mutation battery

**Files:**
- Modify: none permanently. Every mutation is reverted.
- Test: the whole suite.

**Interfaces:**
- Consumes: everything above.
- Produces: a written record of which mutation each row caught, and which test caught it.

Run each row under `PYTHONDONTWRITEBYTECODE=1`, on an otherwise-clean tree, restoring with `git show HEAD:<path> > <path>` and re-checking `git diff --stat` after every restore. A row that comes back GREEN is a coverage hole: close it with a NEW test, then re-run the row to prove the new test discriminates. Do not close a hole by reasoning that the mutation is harmless — measure it.

- [ ] **Step 1: Run all fourteen rows**

| # | File | Mutation | Expected to be caught by |
|---|------|----------|--------------------------|
| 1 | `scripts/lib/regions.py` | in `subject_mask`, `max(0, int(fx0 * w))` → `int(fx0 * w)` | `test_subject_mask_keeps_the_part_of_a_straddling_box_...` |
| 2 | `scripts/lib/regions.py` | in `subject_mask`, swap `h` and `w` in the `np.zeros` shape | the axis-mapping tests in `tests/lib/test_regions.py` |
| 3 | `scripts/lib/regions.py` | in `subject_mask`, delete the `if x1 > x0 and y1 > y0` guard | `test_subject_mask_of_a_box_wholly_outside_...` |
| 4 | `scripts/lib/regions.py` | in `refuse`, `if not located` → `if False` | `test_refuse_names_no_route_...` AND `tests/integration/test_named_regions.py`'s pan case |
| 5 | `scripts/lib/regions.py` | in `refuse`, `fraction < MIN_REGION_FRAC` → `fraction <= MIN_REGION_FRAC` | a boundary test — if none exists, this row is a hole |
| 6 | `scripts/lib/regions.py` | in `refuse`, drop the `kind != "crop"` guard | `test_refuse_never_gates_the_crop_on_size` |
| 7 | `scripts/lib/color_fidelity.py` | re-add `"dominant": "luma"` to the returned dict | `test_evaluate_reports_the_three_components_and_no_ranking_of_them` |
| 8 | `scripts/check_episode.py` | in `_subject_delta_advisory`, `regions.refuse("subject", ...)` → `regions.refuse("crop", ...)` | `test_a_subject_under_the_floor_falls_back_...` |
| 9 | `scripts/check_episode.py` | `"region_fraction": round(frac, 4)` → `round(1.0, 4)` | `test_a_subject_under_the_floor_...` and `test_a_routeless_episode_...` |
| 10 | `scripts/check_episode.py` | report `background_delta_e` unconditionally (move it out of the `if fallback is None`) | `test_a_subject_under_the_floor_...` and `test_a_routeless_episode_...` |
| 11 | `scripts/check_episode.py` | delete the `g.shape != p.shape` refusal | `test_the_advisory_refuses_two_stacks_of_different_shapes` |
| 12 | `scripts/check_episode.py` | in `_region_pairs`, drop the `if not m.any(): continue` | a NaN in `delta_e` — if nothing catches it, this row is a hole |
| 13 | `scripts/check_episode.py` | swap the argument order: `_subject_delta_advisory(g_frames, p_frames, ...)` | the sign of `delta_l` in the integration proof — if nothing catches it, this row is a hole, and it is the same inversion `gradedamage`'s keyword-only signature exists to prevent |
| 14 | `scripts/check_reel.py` | `"frames": len(spans[0]) if spans else 0` → `"frames": color.FRAMES` | `test_grade_faithful_records_the_sample_count_it_read` |

For each row record: the mutation, the command, RED or GREEN, and the first failing test's name.

- [ ] **Step 2: Close every hole**

For each GREEN row, write the test that discriminates it, re-run the row to prove RED, and record both.

Row 13 deserves particular attention: `_subject_delta_advisory(plain, graded, ...)` is positional, and swapping the two stacks inverts every signed component while leaving `delta_e` itself identical (CIEDE2000 is symmetric in magnitude). If nothing catches it, the right fix is a test on the SIGN of `delta_l` for a pair whose grade is a known direction — and consider making the two parameters keyword-only, which is what `gradedamage.evaluate` did for exactly this reason.

- [ ] **Step 3: Verify the tree is clean and the suite is green**

Run: `git diff --stat` (expected: only tests you added in Step 2) and `.venv/bin/python -m pytest -q`.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: close the coverage holes the mutation battery found"
```

- [ ] **Step 5: Write the battery record**

Write the full fourteen-row table with its outcomes into your report file. It is the evidence that the tests above discriminate, and it lives nowhere else.
