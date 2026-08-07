# Intake motion sensor + pool-relative scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make intake's motion measurement identity-consistent (so a crowd's
largest-person swap stops reading as movement) and make window scoring
pool-relative (so `score` ranks and `best` means something).

**Architecture:** Two coupled changes across the two phases that already exist.
**Phase 1** (per-clip, cached): the people timeline carries per-track boxes, and
displacement is measured per track id present in both samples, aggregated by
median — `MOTION_GAIN` is deleted. **Phase 2** (pool-wide, deterministic): a new
`score_pool` scales each factor on the scale its question deserves (absolute where
the scale is a delivery constraint, percentile where it is a property of the
footage) and rank-normalises the blend, so `FootageWindow.score` **is** a
percentile. `CACHE_VERSION` 7→8.

**Tech Stack:** Python 3.13, stdlib only for the new code (`statistics.median`),
pytest. No new dependency, no ffmpeg change, no new CLI surface.

**Design:** `docs/specs/2026-08-06-intake-motion-scoring-design.md` — read §1 (the
measurements this is built on), §3 (the sensor), §4 (the two layers), §8 (limits).

---

## Global Constraints

These bind every task. A reviewer checks against them.

1. **Fail-loud contract** (`docs/coding-standards.md`): a bad input raises
   `ValueError` with a remedy in the message. No silent clamping of a caller error.
   Clamping a *measurement* into its declared contract range is not a caller error.
2. **Imports at top of file.** No function-level imports except the documented
   heavy-optional-dependency pattern already in `intake.py` (`ultralytics`).
3. **`scripts/lib/` must not import a driver.** `carve.py` may not import
   `scripts.intake`; parameters are passed in, never imported back.
4. **Purity boundary.** Everything new in `carve.py` is pure: numbers in, numbers
   out, no IO. `score_pool` is pure apart from mutating the windows it is given
   (the same contract `cull` already has).
5. **Determinism is a hard invariant, not a nicety.**
   `docs/specs/2026-07-25-intake-parallel-checkpoint-design.md`: intake's output
   must be byte-identical at any `--jobs` and any cache mix. `score_pool` reads the
   assembled clip list, which `intake()` already re-sorts into `paths` order. Any
   construct whose result depends on iteration order of a set, or on `id()`, breaks
   this. Task 5 re-proves it.
6. **Constants carry their provenance in a comment.** Every threshold introduced or
   changed here is a first cut calibrated on ONE drone shoot (design §8.1); say so
   at the definition, in the style of the existing `SHAKY_CLIP` and `CLUSTER_COS`
   comments.
7. **No new production script, no new CLI flag.** The slice changes measurement and
   scoring in place. The §6.2 acceptance check is a documented one-off snippet
   (Task 6), deliberately not a new surface.
8. **Tests assert whole objects where practical** (`docs/testing-guide.md`), and
   every test must be one that provably reddens against the pre-change code.
9. **Do not run installers.** No `brew`/`pip`/`npm`/`uv install`, no `setup.sh`.
   Verification is read-only plus `pytest`.
10. **`.venv/bin/python` is the interpreter; scripts run as modules**
    (`pythonpath = .`). Never `python scripts/intake.py`.

---

## File Structure

| File | Change |
|---|---|
| `scripts/lib/carve.py` | **+** `track_displacements` primitive; `subject_curve` takes per-sample `{tid: box}` instead of primary centres |
| `scripts/intake.py` | `_people_timeline` row grows `boxes_by_tid`; `carve_windows` + `_build_window` read it; `_motion` becomes track-consistent; **−** `MOTION_GAIN`/`MOTION_PEAK`/`_motion_fit`/`_dur_fit`/`W_DUR`/`score_window`; **+** `_percentile_rank`/`score_pool`/`CLIP_POOL_MIN`/`DYNAMIC_RANK`; `_describe` takes a rank; `intake()` calls `score_pool` |
| `scripts/lib/intake_cache.py` | `CACHE_VERSION` 7→8 |
| `tests/lib/test_carve.py` | `subject_curve` tests rewritten for the dict input; **+** `track_displacements` tests |
| `tests/lib/test_intake.py` | timeline helpers become 5-tuples; scoring tests rewritten against `score_pool`; **−** `_motion_fit`/`_dur_fit` tests |
| `skills/edit-plan/SKILL.md`, `skills/footage-intake/SKILL.md` | the `score` column means a percentile now |
| `scripts/lib/footage.py` | `to_markdown`'s legend for the `motion`/`score` columns |
| `scripts/contact_sheet.py` | the `best` explanation in the sheet header |
| `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/cinematic-quality-playbook.md` | registry + status sync |

---

### Task 0: `carve.track_displacements` + `subject_curve` on track boxes

**Files:**
- Modify: `scripts/lib/carve.py:9-24`
- Test: `tests/lib/test_carve.py:6-14`

- [ ] **Step 1: Write the failing tests**

Replace the two existing `subject_curve` tests in `tests/lib/test_carve.py` and add
the primitive's own, keeping the file's existing `from scripts.lib import carve`
import:

```python
def test_track_displacements_ignores_a_largest_person_swap():
    # two people, BOTH stationary; the one with the larger box changes between
    # samples. Differencing the primary bbox reads this as a huge jump; measuring
    # each track's own displacement reads it as zero (design §1.2/§3.2).
    prev = {1: (100.0, 100.0, 50.0, 90.0), 2: (900.0, 100.0, 30.0, 60.0)}
    cur = {1: (100.0, 100.0, 30.0, 60.0), 2: (900.0, 100.0, 50.0, 90.0)}
    assert carve.track_displacements(prev, cur) == 0.0


def test_track_displacements_measures_real_movement():
    prev = {1: (100.0, 100.0, 50.0, 90.0)}
    cur = {1: (103.0, 104.0, 50.0, 90.0)}
    assert carve.track_displacements(prev, cur) == 5.0     # 3-4-5


def test_track_displacements_medians_across_tracks():
    # three tracks moving 1, 5 and 100 px: the median rejects the outlier
    prev = {1: (0.0, 0.0, 2.0, 2.0), 2: (0.0, 0.0, 2.0, 2.0), 3: (0.0, 0.0, 2.0, 2.0)}
    cur = {1: (1.0, 0.0, 2.0, 2.0), 2: (5.0, 0.0, 2.0, 2.0), 3: (100.0, 0.0, 2.0, 2.0)}
    assert carve.track_displacements(prev, cur) == 5.0


def test_track_displacements_without_a_shared_id_is_zero():
    assert carve.track_displacements({1: (0.0, 0.0, 2.0, 2.0)}, {2: (99.0, 99.0, 2.0, 2.0)}) == 0.0
    assert carve.track_displacements({}, {}) == 0.0


def test_subject_curve_is_identity_consistent_and_zero_at_gaps():
    boxes = [{1: (0.0, 0.0, 2.0, 2.0)},
             {1: (3.0, 4.0, 2.0, 2.0)},
             {},                                    # nobody this sample
             {1: (3.0, 4.0, 2.0, 2.0)}]
    assert carve.subject_curve(boxes) == [0.0, 5.0, 0.0, 0.0]


def test_subject_curve_edges():
    assert carve.subject_curve([]) == []
    assert carve.subject_curve([{1: (1.0, 1.0, 2.0, 2.0)}]) == [0.0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_carve.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.carve' has no attribute 'track_displacements'`, and the two `subject_curve` tests fail on the dict input.

- [ ] **Step 3: Implement**

In `scripts/lib/carve.py`, change the import line and replace `subject_curve`:

```python
from math import hypot
from statistics import median
```

```python
def track_displacements(prev: dict[int, tuple[float, float, float, float]],
                        cur: dict[int, tuple[float, float, float, float]]) -> float:
    """Median centre displacement across the track ids present in BOTH samples.

    The identity-consistent alternative to differencing the primary bbox, whose
    centre moves when the LARGEST person changes rather than when anyone moves — on
    a real 1565-window pool that artifact saturated 19.8% of windows and was 90.3%
    multi-person against 57.1% for the rest (design
    2026-08-06-intake-motion-scoring §1.2). Boxes are (cx, cy, w, h) in
    analysis-pixel space; the return is RAW pixels, like subject_curve.

    Median, not mean: a residual ID switch perturbs one track, and the median of
    the others absorbs it. No shared id returns 0.0 — an interval that cannot be
    measured is not evidence of movement, the same rule presence gaps follow."""
    shared = prev.keys() & cur.keys()
    if not shared:
        return 0.0
    return float(median(hypot(cur[t][0] - prev[t][0], cur[t][1] - prev[t][1])
                        for t in sorted(shared)))


def subject_curve(boxes: list[dict[int, tuple[float, float, float, float]]]) -> list[float]:
    """Per-sample identity-consistent 2-D displacement, aligned to samples.
    `boxes[i]` maps track id → (cx, cy, w, h) for that sample; an empty dict is a
    sample with no tracked person. Index 0 has no prior and is 0.0, as is any
    sample sharing no track id with its predecessor. Returns RAW pixel displacement
    — peak detection is scale-invariant, so no width normalisation is applied here
    (and the subject/camera curves are never compared on one axis,
    activity-units §3)."""
    if not boxes:
        return []
    return [0.0] + [track_displacements(boxes[i - 1], boxes[i]) for i in range(1, len(boxes))]
```

`sorted(shared)` is not cosmetic: it removes set-iteration order from the result,
which Global Constraint 5 requires.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_carve.py -q`
Expected: PASS (all tests in the file — the peak/unit tests are untouched).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/carve.py tests/lib/test_carve.py && git commit -m "feat(carve): identity-consistent displacement replaces primary-bbox differencing"
```

---

### Task 1: the timeline carries per-track boxes

**Files:**
- Modify: `scripts/intake.py:136-164` (`_people_timeline`), `:73-80` (`carve_windows`)
- Test: `tests/lib/test_intake.py:26-28` (`_line`), `:136-165`

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_intake.py`, beside the existing timeline tests:

```python
def test_people_timeline_row_carries_boxes_by_track_id(monkeypatch):
    class _B:
        def __init__(self, tid, xywh, conf=0.9):
            self.id = [tid] if tid is not None else None
            self.xywh = [xywh]
            self.conf = [conf]

    frames = [types.SimpleNamespace(boxes=[_B(1, (10, 20, 30, 40)),
                                           _B(2, (50, 60, 70, 80)),
                                           _B(None, (90, 90, 10, 10))])]
    monkeypatch.setattr(intake, "_iter_seg", lambda s, model_path=intake.MODEL: enumerate(frames))
    tl, _, _ = intake._people_timeline("x.mp4", fps=1.0, res=(1920, 1080), sample_fps=1.0)
    t, people, primary, tids, by_tid = tl[0]
    assert people == 3                       # the untracked detection still counts as a person
    assert tids == [1, 2]                    # ...but cannot be differenced, so it is not in by_tid
    assert by_tid == {1: (10.0, 20.0, 30.0, 40.0), 2: (50.0, 60.0, 70.0, 80.0)}
    assert primary == (50.0, 60.0, 70.0, 80.0)      # largest area, unchanged
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py::test_people_timeline_row_carries_boxes_by_track_id -q`
Expected: FAIL — `ValueError: not enough values to unpack (expected 5, got 4)`.

- [ ] **Step 3: Implement the timeline row**

In `scripts/intake.py`, replace the body of the sampling branch of `_people_timeline`
(currently lines 157-162) and update its docstring's `timeline:` line:

```python
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        by_tid = {int(b.id[0]): tuple(float(v) for v in b.xywh[0])
                  for b in boxes if getattr(b, "id", None) is not None}
        tids = sorted(by_tid)
        for tid in tids:
            seen[tid] = seen.get(tid, 0) + 1
        timeline.append((i / fps, len(bbs), primary, tids, by_tid))
```

Docstring line becomes:

```
    timeline: [(t, people, primary_bbox, track_ids, boxes_by_tid)] sampled at ~SAMPLE_FPS.
    primary = largest bbox (what shot size is measured from); boxes_by_tid = {tid: (cx,cy,w,h)}
    for that sample, the only shape motion can be differenced on (design
    2026-08-06-intake-motion-scoring §3.1). An untracked detection counts toward
    `people` but cannot appear in boxes_by_tid — it has no identity to follow.
```

- [ ] **Step 4: Point `carve_windows` at the new element**

In `scripts/intake.py:75-79`, replace the primary-centre construction:

```python
        if any(row[1] > 0 for row in samples):
            curve = carve.subject_curve([row[4] for row in samples])
        else:
            curve = carve.camera_curve(mags, fps, times)
```

Add to `carve_windows`'s docstring, after the existing sentence about 2-D bbox
displacement:

```
    The subject curve is identity-consistent (design 2026-08-06-intake-motion-scoring
    §3.3): it was built from the primary bbox's centre, so in a crowd it tracked
    which person was largest and moved WINDOW BOUNDARIES on that artifact.
```

- [ ] **Step 5: Update the test helper and the monkeypatched timelines**

In `tests/lib/test_intake.py`, `_line` (line 26) becomes:

```python
def _line(n_from_to):   # helper: timeline [(t, people, bbox, track_ids, boxes_by_tid)] at 1s steps
    return [(float(t), n, (500, 500, 200, 300) if n else None, [1] if n else [],
             {1: (500.0, 500.0, 200.0, 300.0)} if n else {})
            for t, n in n_from_to]
```

Every other literal timeline row in the file gains its fifth element. There are
four monkeypatched `_people_timeline` sites (lines ~106, ~329, ~355, ~389) plus the
people-less row list in `test_carve_peopleless_span_uses_camera_motion` (line ~63)
and the `_motion` samples (line ~165). A people-less row's fifth element is `{}`;
a one-person row's is `{1: <that row's bbox as floats>}`.

Run `grep -n "None, \[\])\|\[1\])" tests/lib/test_intake.py` to find them all, and
after the edit `grep -c "), 4)" ` must find no unpack of a 4-tuple timeline row.

- [ ] **Step 6: Run the intake and carve suites**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_carve.py -q`
Expected: the new test passes; `test_motion_*`/`test_score_*`/`test_dur_fit_*` may
still fail — they are Task 2 and Task 3. Nothing else may fail.

- [ ] **Step 7: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py && git commit -m "feat(intake): people timeline carries per-track boxes; carving reads them"
```

---

### Task 2: `_motion` becomes track-consistent; `MOTION_GAIN` is deleted

**Files:**
- Modify: `scripts/intake.py:296-303` (`_motion`), `:31` (`MOTION_GAIN`)
- Test: `tests/lib/test_intake.py:~160-168`

- [ ] **Step 1: Write the failing test**

Replace the existing `_motion` test in `tests/lib/test_intake.py` with:

```python
def test_motion_measures_a_tracks_own_displacement():
    res = (1000, 1000)
    samples = [(0.0, 1, (100, 100, 50, 90), [1], {1: (100.0, 100.0, 50.0, 90.0)}),
               (1.0, 1, (110, 100, 50, 90), [1], {1: (110.0, 100.0, 50.0, 90.0)})]
    assert intake._motion(samples, res) == pytest.approx(0.01)   # 10px / 1000px, no gain


def test_motion_is_zero_when_only_the_largest_person_changes():
    # both people stationary; the larger box swaps. The old primary-bbox difference
    # reported a full-frame jump here (design §1.2) — the whole bug in one assert.
    res = (1000, 1000)
    a = {1: (100.0, 100.0, 50.0, 90.0), 2: (900.0, 100.0, 30.0, 60.0)}
    b = {1: (100.0, 100.0, 30.0, 60.0), 2: (900.0, 100.0, 50.0, 90.0)}
    samples = [(0.0, 2, (100, 100, 50, 90), [1, 2], a),
               (1.0, 2, (900, 100, 50, 90), [1, 2], b)]
    assert intake._motion(samples, res) == 0.0


def test_motion_needs_two_samples():
    assert intake._motion([(0.0, 1, (1, 1, 1, 1), [1], {1: (1.0, 1.0, 1.0, 1.0)})], (100, 100)) == 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k motion -q`
Expected: FAIL — the swap test reports ≈0.8 (the primary centre jumped 800 px),
and the first test reports 0.1 (the deleted `MOTION_GAIN` multiplies by 10).

- [ ] **Step 3: Implement**

Delete the `MOTION_GAIN` line (`scripts/intake.py:31`) and replace `_motion`:

```python
def _motion(samples: list, res: tuple[int, int]) -> float:
    """Mean per-sample identity-consistent displacement, as a fraction of the
    ANALYSIS width (design 2026-08-06-intake-motion-scoring §3.3). Fewer than two
    samples → 0.0.

    No gain: the reported number is the measurement. The deleted MOTION_GAIN
    existed only to stretch this fraction onto [0, 1] so a fixed triangular
    preference could be applied to it, and scoring is a rank now (§3.4) — a rank
    has no scale to choose and no ceiling to saturate against. Expect values ~10x
    smaller than before the change."""
    if len(samples) < 2:
        return 0.0
    w = res[0] or 1
    disps = [carve.track_displacements(samples[i - 1][4], samples[i][4])
             for i in range(1, len(samples))]
    return float(min(1.0, (sum(disps) / len(disps)) / w))
```

The `min(1.0, ...)` stays: `FootageWindow.motion`'s contract is [0, 1] and a
measurement is clamped into its declared range (Global Constraint 1) — this is not
a swallowed caller error.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k motion -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py && git commit -m "fix(intake): motion measures a track's own displacement, not which person is largest"
```

---

### Task 3: `score_pool` — the two scoring layers

**Files:**
- Modify: `scripts/intake.py:30-34` (constants), `:87-114` (the factor functions),
  `:274-293` (`_build_window`)
- Test: `tests/lib/test_intake.py:70-95`

- [ ] **Step 1: Write the failing tests**

Replace `test_score_rises_with_presence`, `test_score_penalises_shake`,
`test_motion_fit_peaks_in_the_middle`, `test_dur_fit_peaks_at_target` and
`test_describe` in `tests/lib/test_intake.py` with:

```python
def _w(motion, shake, present=1.0, dur=2.0, people=1):
    return footage.FootageWindow(start=0.0, dur=dur, shot_type="wide", people=people,
                                 motion=motion, shake=shake, present=present)


def _clip(source, windows):
    return footage.FootageClip(source=source, dur=60.0, res=(1920, 1080), fps=30.0,
                               windows=windows)


def test_percentile_rank_is_uniform_tie_aware_and_bounded():
    assert intake._percentile_rank([]) == []
    assert intake._percentile_rank([7.0]) == [0.5]
    assert intake._percentile_rank([10.0, 0.0, 5.0]) == [1.0, 0.0, 0.5]
    assert intake._percentile_rank([3.0, 3.0]) == [0.5, 0.5]      # a tie shares its mid-rank


def test_score_is_a_percentile_not_an_absolute_blend():
    # five windows differing only in motion: their scores must span [0, 1] evenly.
    # The old absolute blend put all five inside a 0.09-wide band above 0.61 (§1.1).
    ws = [_w(motion=m, shake=0.001) for m in (0.01, 0.02, 0.03, 0.04, 0.05)]
    intake.score_pool([_clip("a.mp4", ws)])
    assert [w.score for w in ws] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_score_ignores_a_factor_that_is_constant_across_the_pool():
    # present is constant BY CONSTRUCTION (carve splits on presence transitions,
    # §1.1). Halving it for every window must not reorder anything.
    a = [_w(motion=m, shake=0.001, present=1.0) for m in (0.01, 0.05, 0.03)]
    b = [_w(motion=m, shake=0.001, present=0.5) for m in (0.01, 0.05, 0.03)]
    intake.score_pool([_clip("a.mp4", a)])
    intake.score_pool([_clip("b.mp4", b)])
    assert [w.score for w in a] == [w.score for w in b]


def test_motion_ranks_within_its_own_clip_when_the_clip_is_big_enough():
    # calm clip and busy clip, CLIP_POOL_MIN windows each. The calm clip's best
    # moment must outscore the busy clip's worst, which pool-wide ranking forbids.
    calm = [_w(motion=m, shake=0.001) for m in (0.001, 0.002, 0.003, 0.004, 0.010)]
    busy = [_w(motion=m, shake=0.001) for m in (0.020, 0.030, 0.040, 0.050, 0.060)]
    intake.score_pool([_clip("calm.mp4", calm), _clip("busy.mp4", busy)])
    assert calm[-1].score > busy[0].score


def test_a_clip_below_clip_pool_min_falls_back_to_the_pool():
    # 2 windows is no distribution; ranking them within the clip would hand the
    # stronger one a flat 1.0 — tying the shoot's genuinely busiest window — no
    # matter how weak it is against the rest of the shoot.
    small = [_w(motion=0.001, shake=0.001), _w(motion=0.002, shake=0.001)]
    big = [_w(motion=m, shake=0.001) for m in (0.10, 0.20, 0.30, 0.40, 0.50)]
    intake.score_pool([_clip("small.mp4", small), _clip("big.mp4", big)])
    assert small[1].score < big[-1].score         # pool-ranked, so it cannot tie the top
    assert small[0].score != small[1].score       # ...but the two are still ordered


def test_score_penalises_shake_across_the_pool():
    ws = [_w(motion=0.02, shake=s) for s in (0.001, 0.009)]
    intake.score_pool([_clip("a.mp4", ws)])
    assert ws[0].score > ws[1].score


def test_score_pool_fills_description_from_the_motion_rank():
    ws = [_w(motion=m, shake=0.001, people=p)
          for m, p in ((0.001, 0), (0.002, 1), (0.003, 2), (0.004, 2), (0.900, 2))]
    intake.score_pool([_clip("a.mp4", ws)])
    assert ws[0].description == "no people, wide, calm"
    assert ws[1].description == "1 person, wide, calm"
    assert ws[-1].description == "2 people, wide, dynamic"


def test_score_pool_on_an_empty_pool_is_a_no_op():
    intake.score_pool([])
    intake.score_pool([_clip("a.mp4", [])])


def test_describe_reads_a_rank_not_a_raw_motion():
    assert intake._describe(1, "medium", 0.9) == "1 person, medium, dynamic"
    assert intake._describe(0, "wide", 0.1) == "no people, wide, calm"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k "score or percentile or describe" -q`
Expected: FAIL — `AttributeError: module 'scripts.intake' has no attribute '_percentile_rank'` / `'score_pool'`.

- [ ] **Step 3: Replace the constants**

In `scripts/intake.py`, replace lines 30-34 (`W_PRESENT…BEST_FLOOR`) with:

```python
W_PRESENT, W_MOTION, W_STABLE = 0.44, 0.28, 0.28   # sum to 1. First cuts calibrated on ONE drone
                                                   # shoot (design 2026-08-06-intake-motion-scoring
                                                   # §8.1) — the SHAKY_CLIP precedent below.
CLIP_POOL_MIN = 5        # a clip with fewer windows has no distribution to rank inside, so its
                         # motion falls back to the pool. 10 of 99 clips in the tuning pool were
                         # in that state; first cut (design §4.1).
DYNAMIC_RANK = 0.5       # motion rank at or above which a window is DESCRIBED "dynamic". A rank,
                         # not an absolute value, because every comparison here is pool-relative.
DEDUP_DIST = 8                             # phash Hamming below which two windows are duplicates
BEST_FLOOR = 0.50        # `score` is a PERCENTILE now (design §4.2), so this is the top-half cut,
                         # not an absolute quality bar. The VALUE is deliberately unchanged: the
                         # meaning change is the fix, and inventing a new number on one shoot is
                         # what §8.1 warns against. As an absolute bar it passed 99.6% of a real
                         # 1565-window pool — i.e. it was inert.
```

`W_DUR` is gone. `MOTION_PEAK` is gone. `WIN_MIN`/`WIN_TARGET`/`WIN_MAX` stay —
they are `carve`'s band, still used by `carve_windows`.

- [ ] **Step 4: Replace the factor functions**

Delete `_motion_fit` (lines 87-91), `_dur_fit` (94-100) and `score_window`
(103-108). In their place:

```python
def _percentile_rank(values: list[float]) -> list[float]:
    """Each value's position in its own pool, on [0, 1], aligned to the input order.
    Ties share the mid-rank of their group, so equal inputs always get equal outputs
    — the property that lets a structurally constant factor shift every window
    equally instead of ordering them arbitrarily (design §4.2). A single value ranks
    0.5: it is neither above nor below anything."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    return out


def score_pool(clips: list) -> None:
    """Fill every window's `score` and `description` from the WHOLE pool — Phase 2
    (design 2026-08-06-intake-motion-scoring §4). Mutates in place, like cull.

    Not computable in Phase 1, and that is the point: a per-clip worker cannot see
    a pool, and the absolute blend it used to compute could not rank. Three of its
    four terms were near-constant on real footage (`present` constant BY
    CONSTRUCTION, `_dur_fit` an exact zero for the 76% of windows carve emits at
    WIN_MIN, `stability` compressed 2-14x below its own divisor), leaving `score`
    ~ 0.61 + 0.25*motion — and the motion term saturated (§1.1/§1.2).

    Each factor is scaled on the scale its question deserves: `motion` by rank
    WITHIN ITS OWN CLIP ("the active moment of this shot"), falling back to the pool
    below CLIP_POOL_MIN windows; `shake` by rank across the pool (steadiness is a
    camera property, so a within-clip comparison asks nothing); `present` absolutely,
    its fraction already meaning what it says. The blend is then ranked across the
    pool, so `score` IS a percentile — which makes a constant factor unable to
    distort the ordering, restores BEST_FLOOR's meaning, and makes saturation
    unrepresentable.

    Deterministic in the order of `clips`, which intake() has already re-sorted into
    `paths` order — so output stays byte-identical at any --jobs and cache mix
    (intake-parallel §2)."""
    windows = [w for c in clips for w in c.windows]
    if not windows:
        return
    motion_fit = _percentile_rank([w.motion for w in windows])
    at = 0
    for c in clips:                      # a big enough clip ranks its own windows in place
        n = len(c.windows)
        if n >= CLIP_POOL_MIN:
            motion_fit[at:at + n] = _percentile_rank([w.motion for w in c.windows])
        at += n
    stability = _percentile_rank([-w.shake for w in windows])
    blend = [W_PRESENT * w.present + W_MOTION * m + W_STABLE * s
             for w, m, s in zip(windows, motion_fit, stability)]
    for w, sc, m in zip(windows, _percentile_rank(blend), motion_fit):
        w.score = round(sc, 3)
        w.description = _describe(w.people, w.shot_type, m)
```

- [ ] **Step 5: `_describe` reads a rank**

Replace `_describe` (line 111-114):

```python
def _describe(people: int, shot: str, motion_rank: float) -> str:
    """The human line in FOOTAGE.md. `motion_rank` is the window's motion PERCENTILE
    in its comparison pool, not a raw fraction — the dynamic/calm call is a
    comparison, and every comparison in this design is pool-relative, so it cannot
    be made by a per-clip worker (design §4.5)."""
    who = "no people" if people == 0 else ("1 person" if people == 1 else f"{people} people")
    dyn = "dynamic" if motion_rank >= DYNAMIC_RANK else "calm"
    return f"{who}, {shot}, {dyn}"
```

- [ ] **Step 6: `_build_window` stops scoring**

In `scripts/intake.py:287-293`, delete the `score = score_window(...)` line and drop
both derived arguments from the constructor, so Phase 1 emits the measurements only:

```python
    track_ids = sorted({tid for row in samples for tid in row[3]})
    return footage.FootageWindow(start=round(a, 3), dur=round(d, 3), shot_type=shot,
                                 people=people, motion=round(motion, 3), shake=round(shake, 4),
                                 track_ids=track_ids, subject_w=round(sw, 4),
                                 subject_h=round(sh, 4), present=round(present, 3))
```

`score` and `description` keep their dataclass defaults (`0.0`, `""`) until
`score_pool` fills them. Add one line to `_build_window`'s docstring, or create it
if absent:

```
    Measurements only: `score` and `description` are pool-relative and belong to
    Phase 2 (design 2026-08-06-intake-motion-scoring §4.5), so they keep their
    defaults here.
```

- [ ] **Step 7: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_carve.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py && git commit -m "feat(intake): score_pool replaces the absolute blend — score is a pool percentile"
```

---

### Task 4: wire Phase 2 and bump the cache

**Files:**
- Modify: `scripts/intake.py:445-448` (`intake()`), `scripts/lib/intake_cache.py:39`
- Test: `tests/lib/test_intake.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_intake.py`:

```python
def test_cache_version_is_8_for_the_phase1_sensor_change():
    from scripts.lib import intake_cache
    assert intake_cache.CACHE_VERSION == 8
```

And, in the existing driver test `test_intake_builds_footage_and_writes`
(`tests/lib/test_intake.py:319`), assert that the driver ran Phase 2 — Phase 1
leaves both fields at their dataclass defaults, so a missing `score_pool` call
shows up as empty descriptions:

```python
    # Phase 2 ran: description is pool-derived, never a Phase-1 default
    assert all(w.description for c in result.clips for w in c.windows)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k "cache_version or intake_driver" -q`
Expected: FAIL — `assert 7 == 8`, and empty descriptions.

- [ ] **Step 3: Call `score_pool` in the driver**

In `scripts/intake.py`, between the `Footage` assembly and `cull`:

```python
    ok = [results[p] for p in paths if p in results]
    result = footage.Footage(clips=[r.clip for r in ok])
    score_pool(result.clips)          # Phase 2: pool-relative score + description (design §4.5)
    phash_by = {(r.clip.source, w.start, w.dur): imagehash.hex_to_hash(h)
                for r in ok for w, h in zip(r.clip.windows, r.phashes)}
    cull(result.clips, phash_of=lambda c, w: phash_by[(c.source, w.start, w.dur)])
```

`score_pool` must run **before** `cull`: `cull` ranks by `score`, and in Phase 1
every score is `0.0`.

- [ ] **Step 4: Bump the cache version**

In `scripts/lib/intake_cache.py:39`:

```python
CACHE_VERSION = 8   # 7→8 (2026-08-06): the Phase-1 people timeline carries per-track boxes and
                    # _motion measures a track's own displacement instead of the largest bbox's
                    # centre — a cached v7 ClipResult cannot supply the new measurement, and its
                    # window BOUNDARIES were carved on the contaminated curve too (design
                    # 2026-08-06-intake-motion-scoring §1.2/§1.3).
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/intake.py scripts/lib/intake_cache.py tests/lib/test_intake.py && git commit -m "feat(intake): run score_pool in Phase 2; CACHE_VERSION 7->8"
```

---

### Task 5: the goldens, the suite, and the determinism re-proof

**Files:**
- Modify: `tests/integration/test_intake.py`, `tests/integration/test_intake_proxy.py`,
  `tests/integration/test_contact_sheet.py` and any other golden the change moves

- [ ] **Step 1: Run the whole suite and collect what moved**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -40`

Expect failures in the intake integration goldens. Window boundaries move because
the activity curve changed (design §3.3) and every `score`/`description` changes
because both are now pool-derived. **This is expected and is not licence to
re-record blindly.**

- [ ] **Step 2: Read each moved golden before re-pinning**

For every failing assertion, state in the commit message which of the three causes
it is:
1. boundaries moved (the curve is identity-consistent now),
2. `score` is a percentile,
3. `motion` lost its 10x display gain.

A failure that fits none of the three is a bug in this slice, not a golden to
re-pin — stop and investigate.

- [ ] **Step 3: Re-pin**

Update the pinned values. Where a golden pins a `motion` value, keep the assertion
meaningful rather than transcribing a new magic number — prefer a relational
assertion (`busy > calm`) over an exact float where the test's intent allows it.

- [ ] **Step 4: Close the gap the pool-relative score opens in the determinism proof**

Three byte-identity proofs already exist —
`test_output_is_byte_identical_across_jobs` (`tests/lib/test_intake.py:470`),
`test_output_is_byte_identical_scanned_vs_cached` (`:514`), and
`test_intake_resumes_from_cache_byte_identical`
(`tests/integration/test_intake.py:112`). All of them compare an **all-cold** run
against an **all-cached** run.

None covers a *mix*, and the mix is exactly where a pool-relative score can break:
an implementation that ranked only the freshly-scanned clips would pass all three
and still write different percentiles on a resume. Add the missing arm, modelled on
`test_only_cache_misses_reach_the_pool` (`:480`), which already builds the mix:

The existing `_fake_result` (`:421`) returns a clip with **no windows**, so reusing
it would make this test pass trivially — there would be nothing to rank. The test
needs its own scored-pool fixture:

```python
def _scored_result(name):
    """A fake ClipResult with windows whose motion differs BETWEEN clips — the pool
    must have something to order for a percentile to be observable at all."""
    from scripts.lib.footage import FootageClip, FootageWindow
    base = 0.01 if name == "a.mp4" else 0.05
    ws = [FootageWindow(start=float(i), dur=2.0, shot_type="wide", people=1,
                        motion=base + i / 1000, shake=0.001, present=1.0)
          for i in range(3)]
    return intake.ClipResult(clip=FootageClip(source=name, dur=10.0, res=(100, 100),
                                              fps=30.0, windows=ws),
                             phashes=["0" * 16] * 3, cast=[])


def test_output_is_byte_identical_across_a_cache_mix(monkeypatch, tmp_path):
    """score is a percentile over the WHOLE pool, so every window's number depends
    on every other window's. A resume that ranked only the clips it re-scanned
    would differ here — and would pass the all-cold and all-cached proofs above,
    which is why this arm exists (design 2026-08-06-intake-motion-scoring §4.5)."""
    import shutil
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True:
                        _scored_result(intake.Path(path).name))
    intake.intake(str(root), str(out))
    cold = (out / "FOOTAGE.json").read_text()
    assert len({json.loads(cold)["clips"][0]["windows"][i]["score"] for i in range(3)}) > 1
    shutil.rmtree(out / ".intake_cache" / "b.mp4")     # a stays cached, b re-scans
    intake.intake(str(root), str(out))
    assert (out / "FOOTAGE.json").read_text() == cold
```

The middle assertion is load-bearing: without it, a `score_pool` that wrote the
same number everywhere would satisfy the byte-identity check and prove nothing.

- [ ] **Step 5: Run the whole suite green**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: 0 failures. Record the exact pass/skip counts for the commit message.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "test(intake): re-pin goldens moved by the sensor and scoring change"
```

---

### Task 6: docs, skills and the acceptance snippet

**Files:**
- Modify: `skills/edit-plan/SKILL.md:78`, `skills/footage-intake/SKILL.md:43`,
  `scripts/lib/footage.py:269-274`, `scripts/contact_sheet.py:50-57`,
  `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`,
  `docs/cinematic-quality-playbook.md`

- [ ] **Step 1: Fix the agent-facing sentences about `score`**

`skills/edit-plan/SKILL.md:78` currently says the score "peaks at motion 0.35",
which describes the deleted triangular preference. Replace that passage with:

```
   The ranking is not the answer. `score` is a **percentile within this shoot**
   (design 2026-08-06-intake-motion-scoring §4.2) — 0.9 means "ranks above 90% of
   the windows scanned here", never "is 90% good". It cannot be compared against
   another shoot's numbers, and it says nothing about whether the moment serves
   YOUR cut. `best` marks the top half that also survived phash dedup. Look at the
   contact sheets.
```

`skills/footage-intake/SKILL.md:43` describes `FOOTAGE.md`'s columns — say that
`score` is a percentile and `motion` is a raw fraction of frame width per sample.

- [ ] **Step 2: Fix the table legend and the sheet header**

`scripts/lib/footage.py`'s `to_markdown` emits the `| # | start | dur | shot |
people | motion | shake | score | best | description |` header. Add a legend line
under the table stating that `score` is a percentile within this footage set and
`motion` is mean per-sample subject displacement as a fraction of frame width.

`scripts/contact_sheet.py:57` currently reads "a dedup survivor scoring >= 0.50";
replace with "a dedup survivor in the top half of this shoot's ranking".

- [ ] **Step 3: The acceptance snippet (design §6.2)**

Add a short section to `docs/build-status.md`'s entry for this slice with the
copy-pasteable checker, so §6.2's four criteria are executable rather than prose.
Keep it a documented one-off — Global Constraint 7 forbids a new production script:

````markdown
Validation after the next real intake run (design §6.2):

```bash
.venv/bin/python - <<'PY'
import json, statistics as st
d = json.load(open("FOOTAGE.json"))
ws = [w for c in d["clips"] for w in c["windows"]]
sat = sum(1 for w in ws if w["motion"] >= 0.999)
top = sorted(ws, key=lambda w: w["motion"], reverse=True)[:max(1, len(ws)//10)]
print("1. ceiling pile-up:", sat, "windows at motion=1.0 (was 321/1565)")
print("2. crowd share in the top motion decile: %.1f%% vs pool %.1f%% (was 90.3 vs 57.1)"
      % (100*sum(1 for w in top if w["people"] >= 2)/len(top),
         100*sum(1 for w in ws if w["people"] >= 2)/len(ws)))
print("3. score quartiles (want ~0.25/0.50/0.75):",
      [round(st.quantiles([w["score"] for w in ws], n=4)[i], 3) for i in range(3)])
print("4. best share: %.1f%% of all windows (was 77.6%%)"
      % (100*sum(1 for w in ws if w["best"])/len(ws)))
PY
```
````

- [ ] **Step 4: Registry and status sync**

- `CLAUDE.md` Quick Reference — add the design and plan rows, in the established
  one-line-with-the-load-bearing-fact style.
- `docs/build-status.md` — a Done entry naming what shipped, the `CACHE_VERSION`
  7→8 consequence (the next `footage-intake` re-scans everything), and a Next-action
  update: S3 is done, so what remains of P3 is the hero-conditioned re-scan, #14 and
  #3.
- `docs/pipeline-map.md` — §5.2's row mentions scoring; keep it true.
- `docs/cinematic-quality-playbook.md` §4 priority 3 — mark S3 landed, and correct
  the "S3 is a re-tune" framing: it was a sensor fix, and the reason is §1.2.

- [ ] **Step 5: Verify no stale reference survives**

Run: `grep -rn "MOTION_PEAK\|MOTION_GAIN\|score_window\|_dur_fit\|W_DUR\|motion 0.35" --include='*.py' --include='*.md' scripts/ tests/ skills/ docs/ | grep -v "docs/specs/2026-08-06-intake-motion-scoring-design.md\|docs/plans/2026-08-06-intake-motion-scoring.md"`
Expected: no output. (The design and this plan legitimately name the deleted
constants; nothing else may.)

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: 0 failures.

```bash
git add -A && git commit -m "docs(intake-motion-scoring): score is a percentile — skills, legend, registry, status"
```

---

## Mutation battery

These are **steps, not suggestions**. Each names a mutation, the test that must
redden, and what a green result means. Run each by editing the source, running the
named test, and reverting.

Items 2-6 were **pre-verified against a throwaway prototype of this plan's exact
code and tests** (13/13 green; each mutation reddened exactly the named tests), so
a green result on one of them means the implementation drifted from the plan, not
that the mutation was a bad idea. Items 1, 7, 8 need the real `intake.py` and were
not pre-verified; item 9 is an EQUIVALENT mutation, not a blind spot —
`statistics.median` sorts its input internally, so no test could ever redden
against it, and none should be expected to.

- [ ] **1. Revert the sensor.** Make `_motion` difference `samples[i][2]` (the
  primary bbox) again. `test_motion_is_zero_when_only_the_largest_person_changes`
  must fail. Green means the slice's central fix is untested.

- [ ] **2. Drop the median.** Make `track_displacements` return the *mean* across
  shared ids. `test_track_displacements_medians_across_tracks` must fail. Green
  means the outlier rejection is decorative.

- [ ] **3. Break tie handling.** Make `_percentile_rank` assign ranks by position
  instead of sharing the mid-rank (`out[order[k]] = k / (n - 1)`).
  `test_percentile_rank_is_uniform_tie_aware_and_bounded` and
  `test_score_ignores_a_factor_that_is_constant_across_the_pool` must fail. Green
  means a constant factor can still reorder the pool — the defect §4.2 exists to
  prevent.

- [ ] **4. Rank motion pool-wide always.** Delete the `if n >= CLIP_POOL_MIN` branch.
  `test_motion_ranks_within_its_own_clip_when_the_clip_is_big_enough` must fail.

- [ ] **5. Rank motion per-clip always.** Change `CLIP_POOL_MIN` to `1`.
  `test_a_clip_below_clip_pool_min_falls_back_to_the_pool` must fail.

- [ ] **6. Skip the composite rank.** Make `score_pool` assign the raw `blend`
  instead of its percentile. **Two** tests must fail:
  `test_score_is_a_percentile_not_an_absolute_blend` and
  `test_score_ignores_a_factor_that_is_constant_across_the_pool`. The second is the
  sharper one — without the composite rank a constant factor moves every score, which
  is precisely the defect §4.2 removes. Green means `score` could return to a narrow
  band above a constant baseline unnoticed.

- [ ] **7. Score after culling.** Move the `score_pool` call in `intake()` to after
  `cull`. A test must fail — `cull` would rank an all-zero pool. If none does, add
  one: this ordering is silent corruption, not a crash.

- [ ] **8. Forget the cache bump.** Set `CACHE_VERSION` back to 7.
  `test_cache_version_is_8_for_the_phase1_sensor_change` must fail. Green means a
  stale v7 cache would be silently reused against a changed Phase 1 — exactly the
  class of silent corruption the version exists to prevent.

- [ ] **9. Make the rank order-dependent.** Replace `sorted(shared)` in
  `track_displacements` with `shared`. No test will redden — and none should:
  `statistics.median` sorts its input internally (`data = sorted(data)` is its own
  first line), so this is an **EQUIVALENT MUTATION**, not a blind spot in the
  tests — there is no observable difference for any test to catch. The `sorted()`
  at the call site is defensive, not load-bearing (see its own comment in
  `scripts/lib/carve.py`), and stays for Global Constraint 5: it guards against a
  later swap of the aggregator to something order-sensitive, so this call site
  doesn't quietly reopen the set-order landmine if `median()` is ever replaced.

---

## Self-review notes (for the executing agent)

- The plan deletes four constants and one public function (`score_window`). Task 6
  step 5 is the machine check that nothing still references them.
- `WIN_MIN`/`WIN_MAX` are **not** deleted — they stay as carve's band parameters;
  `carve_windows` passes exactly those two to `carve.units_for_span`. `WIN_TARGET`
  loses its only consumer when `_dur_fit` is deleted (Task 3) and, unlike this note
  originally predicted, was itself deleted as a review finding before Task 4 began
  — it has no other reader. Correction landed in Task 6 alongside the design's
  matching §4.3 fix.
- `SHAKY_CLIP` is **not** deleted. `_dur_fit`'s removal does not touch it; it still
  decides `FootageClip.shaky`, which is a different question from ranking.
- Task 5 is the one with real judgement in it. If a golden fails for a fourth
  reason, that is a finding, not a re-pin.
