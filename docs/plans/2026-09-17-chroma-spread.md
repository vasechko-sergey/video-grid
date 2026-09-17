# Chroma spread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** put a number on how far apart a reel's episodes are in what the grade did
to their colour, from the render pair that already exists — and gate nothing.

**Architecture:** `check_episode._subject_delta_advisory` already computes the
signed CIEDE2000 chroma/hue displacement between the ungraded and graded renders of
the same frames. This slice makes that displacement available for the **crop** (the
one region every episode always has), carries it on `ReelEpisode`, and adds an
advisory `chroma_spread` check to `check_reel` that reports the reel's per-episode
values and their spread. No new decode anywhere: the pair is rendered once, by
`_grade_damage`, exactly as today.

**Tech Stack:** Python 3, numpy, ffmpeg via `scripts/lib/proc.run`, pytest.

**Design:** [docs/specs/2026-09-17-chroma-spread-design.md](../specs/2026-09-17-chroma-spread-design.md).
Read §2 (the contract) before starting. The §0 measurements are the evidence; you
do not need to reproduce them.

## Global Constraints

- **The interpreter is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .`
  in pytest config) — `from scripts.lib import x`, never a relative import.
- **Never run an installer** (`brew`, `pip install`, `uv`, `apt`, `npm`, `setup.sh`).
  Verification is read-only plus `pytest`.
- **Never run `git checkout --`, `git restore`, `git reset --hard` or `git stash`.**
  To undo a mutation of a COMMITTED file: `git show HEAD:<path> > <path>`. To undo a
  mutation of an UNCOMMITTED file you must save your own copy FIRST
  (`cp <path> <path>.bak`); run the mutation on an otherwise-clean tree and re-check
  `git diff --stat` after restoring.
- **`git add` named paths only — never `git add -A`.**
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`** — a one-byte edit can
  match the previous file's size and mtime-second and CPython then serves a stale
  `.pyc`.
- **zsh does not word-split an unquoted variable**: a pytest selection held in a
  shell variable arrives as ONE argument and the run prints `no tests ran`, which
  reads exactly like a non-discriminating mutation row. Write selections out.
- **Nothing blocks.** `chroma_spread` is advisory end to end. A reel's `overall`
  must be byte-identical to today's on every reel that passes today.
- **No knob is authored.** This slice adds no automatic chroma actuator and touches
  no field of `ReframeSpec`, `EDLEpisode` or `Manifest`.
- **`regions.py`, `color.py`, `matchgrade.py`, `color_measure.py` are untouched.**
- Threshold value: `ReelCheckSpec.chroma_spread_max = 5.0` (design §2.5).
- Commit after each task. Do not push.

## File Structure

| File | Responsibility in this slice |
|---|---|
| `scripts/check_episode.py` | emits the crop's signed displacement beside the subject's (Task 1) |
| `scripts/lib/color_fidelity.py` | `shift_from_report` — names which part of a report is the displacement (Task 2) |
| `scripts/lib/models.py` | `ReelEpisode.chroma` carrier + validation; `ReelCheckSpec.chroma_spread_max`; `_ADVISORY_CHECKS` (Tasks 3, 5) |
| `scripts/edl_to_reel.py` | phase 1 fills `chroma` from each episode's report (Task 4) |
| `scripts/build_reel.py` | builds the parallel list, refreshes it on a reprocess (Task 4) |
| `scripts/check_reel.py` | `_chroma_spread_check` + wiring (Task 5) |

---

### Task 1: the crop's own signed displacement

**Files:**
- Modify: `scripts/check_episode.py` — inside `_subject_delta_advisory`, the
  `if fallback is None:` block near the end of the function
- Test: `tests/test_check_episode.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: two new keys in the `grade_damage` report dict, present **only** when
  `region == "subject"`: `crop_delta_c: float` and `crop_delta_h: float`. They are
  `color_fidelity.evaluate`'s `delta_c` / `delta_h` over a full-frame mask.

**Context you need:** `_subject_delta_advisory(plain_frames, graded_frames, times,
route_pts, path_obj, meta) -> dict` builds a subject mask, asks
`regions.refuse("subject", ...)` whether it can supply a reading, and on a fallback
reads the whole frame instead. `_region_pairs(plain, graded, mask)` returns one
`(plain_rgb, graded_rgb)` mean pair per frame whose mask slice holds pixels.
`color_fidelity.evaluate(pairs)` returns
`{"delta_e", "delta_l", "delta_c", "delta_h", "samples"}`, or
`{"status": "not-checked", "reason": ...}` for an empty list.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_check_episode.py`. The existing test
`test_the_advisory_reads_the_subject_and_names_the_region_it_read` shows the fixture
idiom for this module — follow it for frame stacks, route points and meta.

```python
def test_a_subject_reading_also_carries_the_crops_own_displacement():
    """The reel-level check needs ONE pixel set every episode has. The subject is
    not it — it falls back by name — so a subject reading carries the crop's
    displacement alongside its own (design 2026-09-17 §2.2)."""
    out = _advisory_over_a_located_subject()          # helper below
    assert out["region"] == "subject"
    assert "crop_delta_c" in out and "crop_delta_h" in out
    assert isinstance(out["crop_delta_c"], float)
    assert isinstance(out["crop_delta_h"], float)


def test_a_crop_reading_does_not_repeat_itself_under_a_second_name():
    """When the subject fell back, delta_c/delta_h ALREADY are the crop's. A second
    key holding the same number is the contradiction surface 2026-09-16 §2.3
    refused for the background's fraction."""
    out = _advisory_over_a_refused_subject()          # helper below
    assert out["region"] == "crop"
    assert "crop_delta_c" not in out
    assert "crop_delta_h" not in out


def test_the_crops_displacement_is_the_whole_frame_not_the_background():
    """Not an approximation of the background reading: the crop is subject UNION
    background, and on a frame where the two differ the numbers must differ."""
    out = _advisory_over_a_located_subject_whose_subject_differs_from_its_background()
    assert out["region"] == "subject"
    assert out["crop_delta_c"] != out["delta_c"]
```

Write the three helpers as module-level functions in the test file, each building
its own `(n, h, w, 3)` uint8 plain/graded stacks and route points. For the third,
make the subject box a different colour from the rest of the frame in the graded
stack only, so the subject's chroma moves and the background's does not.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_check_episode.py -k "crop_delta or crops_own or repeat_itself" -v
```

Expected: FAIL — `KeyError: 'crop_delta_c'` on the first and third.

- [ ] **Step 3: Implement**

In `_subject_delta_advisory`, the tail of the function currently reads:

```python
    if fallback is None:
        bg = ~mask
        out["background_fallback"] = regions.refuse(
            "background", located=located, fraction=1.0 - frac)
        if out["background_fallback"] is None:
            out["background_delta_e"] = color_fidelity.evaluate(
                _region_pairs(p, g, bg))["delta_e"]
    return out
```

Replace the `read = ...` line and the tail so the full-frame mask is built once and
the crop's own components ride the subject arm:

```python
    whole = np.ones((n, h, w), dtype=bool)
    read = whole if fallback else mask
```

```python
    if fallback is None:
        bg = ~mask
        out["background_fallback"] = regions.refuse(
            "background", located=located, fraction=1.0 - frac)
        if out["background_fallback"] is None:
            # A bare subscript, never .get: a background that refused nothing holds
            # pixels in at least one frame, so _region_pairs cannot come back empty
            # and evaluate cannot return its no-samples shape. If that ever stops
            # holding, a KeyError is the right answer — a None here is the defect.
            out["background_delta_e"] = color_fidelity.evaluate(
                _region_pairs(p, g, bg))["delta_e"]
        # The CROP's own signed displacement, for the reel-level chroma_spread check
        # (design 2026-09-17 §2.2). The reel needs one pixel set defined identically
        # on every episode, and the crop is the only region that is always present:
        # `subject` falls back by name and `background` is not reported at all after
        # a subject fallback. Emitted only on this arm — when the subject fell back,
        # delta_c/delta_h ALREADY are the crop's, and a second key holding the same
        # number is the contradiction surface 2026-09-16 §2.3 refused for the
        # background's fraction. The consumer reads `region` to know which pair to
        # take. Bare subscripts for the same reason as the background's above: a
        # full-frame mask holds pixels in every frame.
        crop = color_fidelity.evaluate(_region_pairs(p, g, whole))
        out["crop_delta_c"], out["crop_delta_h"] = crop["delta_c"], crop["delta_h"]
    return out
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_check_episode.py -v
```

Expected: PASS, including every pre-existing test in the file unchanged.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_episode.py tests/test_check_episode.py
git commit -m "feat(check_episode): the crop's own signed displacement, beside the subject's"
```

---

### Task 2: `color_fidelity.shift_from_report`

**Files:**
- Modify: `scripts/lib/color_fidelity.py`
- Test: `tests/lib/test_color_fidelity.py`

**Interfaces:**
- Consumes: Task 1's `crop_delta_c` / `crop_delta_h` keys and the existing
  `region` / `delta_c` / `delta_h` keys.
- Produces: `shift_from_report(report: dict) -> dict`, returning either
  `{"delta_c": float, "delta_h": float, "region": "subject" | "crop"}` or
  `{"status": "not-checked", "reason": str}`. This is exactly the shape
  `ReelEpisode.chroma` carries (Task 3).

**Context you need:** a `report.json` is `Report.to_dict()`:
`{"checks": {name: <flat detail dict>}, "overall": bool, "attempt": int,
"fail_reasons": [...]}`. The `grade_damage` entry is the merged dict
`_grade_damage` built — the entropy verdict's keys plus the advisory's. When
`grade_damage` was not checked it is `{"status": "not-checked", "reason": ...}`
with no `region` key at all.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.lib import color_fidelity as cf


def _report(grade_damage: dict) -> dict:
    return {"checks": {"grade_damage": grade_damage}, "overall": True,
            "attempt": 1, "fail_reasons": []}


def test_a_subject_reading_hands_over_the_crops_pair_not_the_subjects():
    """The reel compares ONE pixel set across episodes, and it is the crop."""
    out = cf.shift_from_report(_report(
        {"region": "subject", "delta_c": 9.0, "delta_h": 9.0,
         "crop_delta_c": -1.25, "crop_delta_h": 0.5, "pass": True}))
    assert out == {"delta_c": -1.25, "delta_h": 0.5, "region": "subject"}


def test_a_crop_reading_hands_over_its_own_pair():
    out = cf.shift_from_report(_report(
        {"region": "crop", "delta_c": -4.18, "delta_h": -1.22, "pass": True}))
    assert out == {"delta_c": -4.18, "delta_h": -1.22, "region": "crop"}


def test_a_not_checked_grade_damage_keeps_its_own_reason():
    """Never a 0.0, which would read as 'the grade moved nothing' (design §4.5)."""
    out = cf.shift_from_report(_report(
        {"status": "not-checked", "reason": "no render pair: source is pc"}))
    assert out == {"status": "not-checked", "reason": "no render pair: source is pc"}


def test_a_report_with_no_grade_damage_block_is_named_not_guessed():
    out = cf.shift_from_report({"checks": {}, "overall": True})
    assert out["status"] == "not-checked"
    assert "grade_damage" in out["reason"]


def test_a_non_report_is_named_rather_than_crashing():
    out = cf.shift_from_report([])
    assert out["status"] == "not-checked"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_color_fidelity.py -k shift_from_report -v
```

Expected: FAIL with `AttributeError: module 'scripts.lib.color_fidelity' has no attribute 'shift_from_report'`.

- [ ] **Step 3: Implement**

Append to `scripts/lib/color_fidelity.py`:

```python
def shift_from_report(report: dict) -> dict:
    """The episode's chroma displacement, in the shape ReelEpisode.chroma carries.

    One reader for a report's own description of what the grade did to its colour,
    so the two drivers that fill the carrier (edl_to_reel's phase 1 and build_reel's
    reprocess arm) cannot drift about which key holds it (design 2026-09-17 §2.3).

    The pair handed over is always the CROP's — the one pixel set defined identically
    on every episode — which is `crop_delta_c`/`crop_delta_h` when the subject
    supplied the primary reading and `delta_c`/`delta_h` when it fell back and the
    primary reading already IS the crop's (design §2.2).

    Keys on `region`, never on the presence of a `status` key: the grade_damage block
    is a FLAT merge of a verdict dict and an advisory dict, and a predicate over
    `"status" in d` reads a key either half could contribute.
    """
    checks = report.get("checks") if isinstance(report, dict) else None
    d = checks.get("grade_damage") if isinstance(checks, dict) else None
    if not isinstance(d, dict):
        return {"status": "not-checked",
                "reason": "the report carries no grade_damage block"}
    region = d.get("region")
    if region == "subject":
        return {"delta_c": d["crop_delta_c"], "delta_h": d["crop_delta_h"],
                "region": "subject"}
    if region == "crop":
        return {"delta_c": d["delta_c"], "delta_h": d["delta_h"], "region": "crop"}
    return {"status": "not-checked",
            "reason": d.get("reason") or d.get("status")
            or f"grade_damage names no readable region (got {region!r})"}
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_color_fidelity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/color_fidelity.py tests/lib/test_color_fidelity.py
git commit -m "feat(color_fidelity): one reader for a report's chroma displacement"
```

---

### Task 3: `ReelEpisode.chroma`

**Files:**
- Modify: `scripts/lib/models.py` — `ReelEpisode` (around line 1355) and the
  constructor call inside `ReelManifest.from_dict` (around line 1659)
- Test: `tests/lib/test_models.py`

**Interfaces:**
- Consumes: Task 2's two shapes.
- Produces: `ReelEpisode.chroma: dict | None = None`, round-tripped by
  `to_dict()` / `ReelManifest.from_dict`, refused at construction if it is
  neither shape.

**Context you need:** `ReelEpisode` is a frozen dataclass with fields
`manifest: dict, clip: str, route: str | None = None, path: str = "", meta: str = ""`
and a `to_dict()` that emits exactly those five. It has **no** `__post_init__`
today. `ReelManifest.from_dict` builds each one with explicit keyword arguments.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from scripts.lib.models import ReelEpisode, ReelManifest


def test_an_episode_carries_its_chroma_displacement_through_a_round_trip():
    e = ReelEpisode(manifest={"segment": "s.mp4"}, clip="ep0.mp4",
                    chroma={"delta_c": -4.18, "delta_h": -1.22, "region": "crop"})
    assert e.to_dict()["chroma"] == {"delta_c": -4.18, "delta_h": -1.22, "region": "crop"}


def test_an_episode_carries_a_named_absence_through_a_round_trip():
    e = ReelEpisode(manifest={}, clip="ep0.mp4",
                    chroma={"status": "not-checked", "reason": "no render pair"})
    assert e.to_dict()["chroma"]["reason"] == "no render pair"


def test_an_episode_written_before_this_field_existed_stays_loadable():
    """None is not a zero and not an error: it is a manifest from an older run."""
    assert ReelEpisode(manifest={}, clip="ep0.mp4").chroma is None
    rm = ReelManifest.from_dict({"episodes": [{"manifest": {}, "clip": "ep0.mp4"}],
                                 "target_dur": 10.0, "changelog": "c.md"})
    assert rm.episodes[0].chroma is None


def test_a_chroma_that_is_neither_shape_is_refused_by_name():
    with pytest.raises(ValueError, match="chroma"):
        ReelEpisode(manifest={}, clip="ep0.mp4", chroma={"delta_c": -1.0})


def test_a_chroma_reading_with_an_unknown_region_is_refused():
    with pytest.raises(ValueError, match="region"):
        ReelEpisode(manifest={}, clip="ep0.mp4",
                    chroma={"delta_c": 1.0, "delta_h": 1.0, "region": "background"})


def test_a_chroma_reading_with_a_non_numeric_component_is_refused():
    with pytest.raises(ValueError, match="chroma"):
        ReelEpisode(manifest={}, clip="ep0.mp4",
                    chroma={"delta_c": "-1.0", "delta_h": 1.0, "region": "crop"})
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_models.py -k chroma -v
```

Expected: FAIL with `TypeError: ReelEpisode.__init__() got an unexpected keyword argument 'chroma'`.

- [ ] **Step 3: Implement**

Add the field and its validation to `ReelEpisode`, and extend `to_dict`:

```python
    manifest: dict
    clip: str
    route: str | None = None
    path: str = ""
    meta: str = ""
    #: What the grade did to this episode's COLOUR, measured once in phase 1 from
    #: the render pair check_episode already decodes (design 2026-09-17 §2.3), and
    #: read at reel level by check_reel's advisory chroma_spread. Two shapes, both
    #: named: a reading {"delta_c", "delta_h", "region"} or an absence
    #: {"status": "not-checked", "reason"}. None means a manifest written before
    #: this field existed — check_reel reports that as its own named not-checked
    #: reason, never as a 0.0 that would read as "the grade moved nothing".
    chroma: dict | None = None

    def __post_init__(self) -> None:
        if self.chroma is None:
            return
        c = self.chroma
        if not isinstance(c, dict):
            raise ValueError(
                f"ReelEpisode.chroma must be a reading "
                f"{{delta_c, delta_h, region}} or an absence {{status, reason}}, "
                f"got {type(c).__name__} — build it with "
                f"color_fidelity.shift_from_report(report)")
        if c.get("status") == "not-checked":
            if not (isinstance(c.get("reason"), str) and c["reason"]):
                raise ValueError(
                    f"ReelEpisode.chroma: a not-checked chroma must carry a "
                    f"non-empty 'reason' naming the absence, got {c!r}")
            return
        if not all(isinstance(c.get(k), (int, float)) and not isinstance(c.get(k), bool)
                   for k in ("delta_c", "delta_h")):
            raise ValueError(
                f"ReelEpisode.chroma must carry numeric 'delta_c' and 'delta_h' "
                f"(signed CIEDE2000 components), got {c!r} — build it with "
                f"color_fidelity.shift_from_report(report)")
        if c.get("region") not in ("subject", "crop"):
            raise ValueError(
                f"ReelEpisode.chroma 'region' must be 'subject' or 'crop' — the two "
                f"regions check_episode can read a displacement over — got "
                f"{c.get('region')!r}")
```

```python
    def to_dict(self) -> dict:
        """The shape from_dict reads back. `manifest` is emitted INLINE even when it
        was loaded from a path (_load_manifest accepts both): a reel manifest that
        names a file is only as reproducible as that file, and phase 2 may run after
        the scratch dir is gone."""
        return {"manifest": dict(self.manifest), "clip": self.clip,
                "route": self.route, "path": self.path, "meta": self.meta,
                "chroma": self.chroma}
```

And in `ReelManifest.from_dict`:

```python
        eps = [ReelEpisode(manifest=_load_manifest(e.get("manifest")),
                           clip=e.get("clip", ""), route=e.get("route", ""),
                           path=e.get("path", ""), meta=e.get("meta", ""),
                           chroma=e.get("chroma"))
               for e in eps_in]
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_models.py -v
```

Expected: PASS, every pre-existing test included.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat(models): ReelEpisode carries its chroma displacement or a named absence"
```

---

### Task 4: fill the carrier, and keep it no older than the clip beside it

**Files:**
- Modify: `scripts/edl_to_reel.py` — `_build_manifest` (the `ReelEpisode(...)`
  construction around line 259)
- Modify: `scripts/build_reel.py` — the parallel-list block around line 101 and the
  reprocess arm around line 218
- Test: `tests/lib/test_edl_to_reel.py`, `tests/test_build_reel.py`

**Interfaces:**
- Consumes: `color_fidelity.shift_from_report(report: dict) -> dict` (Task 2),
  `ReelEpisode.chroma` (Task 3).
- Produces: `chroma: list[dict | None]`, one entry per `rm.episodes`, passed to
  `check_reel.run(..., chroma=chroma)` in Task 5.

**Context you need:** `_build_manifest(mds, results, routes, epdirs, ...)` builds the
`ReelEpisode` list from each episode's `results[i]`, a `process_episode` result dict
whose `mechanical_pass` shape carries `"report": report.to_dict()`. In
`build_reel`, `tone_dsts = [e.manifest.get("tone_dst") for e in rm.episodes]` is the
existing parallel-list idiom; the reprocess arm assigns `clips[item.idx] = res["clip"]`
after a successful `process_episode` call.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_edl_to_reel.py`:

```python
def test_phase_one_records_each_episodes_chroma_displacement():
    """The pair is rendered once, in phase 1. The reel reads the number phase 1
    already produced rather than paying for a second pair (design §2.3)."""
    rm = _build_manifest_with(results=[
        {"status": "mechanical_pass", "clip": "ep0.mp4",
         "report": {"checks": {"grade_damage": {
             "region": "crop", "delta_c": -4.18, "delta_h": -1.22, "pass": True}}}}])
    assert rm.episodes[0].chroma == {"delta_c": -4.18, "delta_h": -1.22,
                                     "region": "crop"}


def test_phase_one_records_a_named_absence_when_the_pair_was_refused():
    rm = _build_manifest_with(results=[
        {"status": "mechanical_pass", "clip": "ep0.mp4",
         "report": {"checks": {"grade_damage": {
             "status": "not-checked", "reason": "no render pair"}}}}])
    assert rm.episodes[0].chroma["reason"] == "no render pair"
```

Write `_build_manifest_with` as a module-level helper that calls the real
`_build_manifest` with the minimum arguments the existing tests in that file already
assemble (copy their fixture idiom; do not invent a new one).

In `tests/test_build_reel.py`:

```python
def test_a_reprocessed_episode_hands_check_reel_its_NEW_chroma(...):
    """A reprocess re-renders the episode, so check_episode ran again and produced a
    fresh displacement. The stale phase-1 value must not outlive the clip it
    described (design §2.3)."""
```

Build it on the file's existing reprocess fixture: make round 1 fail with `black`,
have the faked `process_episode` return a `mechanical_pass` whose report carries
`delta_c = 2.0`, start from a manifest whose `chroma` says `delta_c = -9.0`, and
assert the `chroma` list `check_reel.run` was called with on the FINAL round carries
`2.0` at that index. Capture the call with the same monkeypatch idiom the file
already uses for `check_reel.run`.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -k chroma tests/test_build_reel.py -k chroma -v
```

Expected: FAIL — `rm.episodes[0].chroma` is `None`.

- [ ] **Step 3: Implement**

In `scripts/edl_to_reel.py`, add the import (`from scripts.lib import color_fidelity`
beside the existing `scripts.lib` imports) and fill the field:

```python
    episodes = [ReelEpisode(manifest=md, clip=res["clip"], route=routes[i],
                            path=str(Path(epdirs[i]) / "path.json"),
                            meta=str(Path(epdirs[i]) / "path.meta.json"),
                            # What the grade did to this episode's colour, from the
                            # render pair check_episode already decoded. Phase 2 runs
                            # from EPISODES.json alone and never sees a phase-1
                            # report, so the number has to ride the contract
                            # (design 2026-09-17 §2.3).
                            chroma=color_fidelity.shift_from_report(res.get("report") or {}))
                for i, (md, res) in enumerate(zip(mds, results, strict=True))]
```

In `scripts/build_reel.py`, beside `tone_dsts`:

```python
    # Per-episode chroma displacement, for check_reel's advisory chroma_spread. A
    # parallel list like `geometry` and `tone_dsts` above, for the same reason —
    # check_reel.run stays callable from its own CLI, which has none of them. NOT
    # constant across rounds, unlike those two: a reprocess re-renders the episode
    # and check_episode measures it again, so the reprocess arm below replaces the
    # entry rather than letting a stale number outlive the clip it described.
    chroma = [e.chroma for e in rm.episodes]
```

and in the reprocess arm, immediately after `clips[item.idx] = res["clip"]`:

```python
            clips[item.idx] = res["clip"]
            chroma[item.idx] = color_fidelity.shift_from_report(res.get("report") or {})
```

with `color_fidelity` added to `build_reel`'s existing `from scripts.lib import ...`
line.

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/test_build_reel.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/edl_to_reel.py scripts/build_reel.py tests/lib/test_edl_to_reel.py tests/test_build_reel.py
git commit -m "feat: carry each episode's chroma displacement from phase 1 to the reel"
```

---

### Task 5: `check_reel.chroma_spread`

**Files:**
- Modify: `scripts/lib/models.py` — `ReelCheckSpec` (the field block ending at
  `grade_residual_max`, around line 1081) and `_ADVISORY_CHECKS` (around line 1288)
- Modify: `scripts/check_reel.py` — a new `_chroma_spread_check`, and the
  `run(...)` signature and body
- Modify: `scripts/build_reel.py` — pass `chroma=chroma` to `check_reel.run`
- Test: `tests/lib/test_check_reel.py`, `tests/lib/test_models.py`

**Interfaces:**
- Consumes: `chroma: list[dict | None]` (Task 4).
- Produces: `check_reel.run(..., chroma: list | None = None)`; a `CheckResult`
  named `"chroma_spread"` in `ReelReport.checks`.

**Context you need:** `run(master, episodes, spec, out_report, music=None,
audio=None, geometry=None, platform="", outro=None, predicted=None,
tone_target=None, tone_dsts=None, brief_len=None) -> ReelReport` assembles
`checks: dict[str, CheckResult]` and `fails: list[ReelFailure]`. `predicted` is the
precedent for an optional parallel list whose `None` becomes a named not-checked.
`_ADVISORY_CHECKS` is the tuple `ReelReport.overall` excludes.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_models.py`:

```python
def test_chroma_spread_is_advisory():
    from scripts.lib.models import _ADVISORY_CHECKS
    assert "chroma_spread" in _ADVISORY_CHECKS


def test_the_chroma_bar_has_its_measured_default():
    from scripts.lib.models import ReelCheckSpec
    assert ReelCheckSpec(target_dur=10.0).chroma_spread_max == 5.0
```

In `tests/lib/test_check_reel.py`:

```python
from scripts.check_reel import _chroma_spread_check


def _reading(c, h, region="crop"):
    return {"delta_c": c, "delta_h": h, "region": region}


def test_the_spread_is_the_widest_gap_across_the_reel():
    cr = _chroma_spread_check([_reading(-4.18, -1.22), _reading(-2.72, -0.51),
                               _reading(-0.66, -0.53)], 5.0)
    assert cr.detail["spread_c"] == pytest.approx(3.52)
    assert cr.detail["spread_h"] == pytest.approx(0.71)
    assert cr.detail["worst"] == pytest.approx(3.52)
    assert cr.passed is True


def test_one_episode_graded_the_other_way_fails_the_bar():
    """ep0 of the only real reel: the sole episode whose grade RAISED chroma, 8.35
    dH* from its three siblings, on the opening shot (design §0.6).

    Corrected, final whole-branch review, FIX 7: this snippet originally asserted
    pytest.approx(9.07), design §2.5's full-precision figure. The SHIPPED test
    pins 9.06 — what these exact literals compute — deliberately: see design
    §2.5's own closing note and docs/build-status.md's Done entry, which
    reconcile the two numbers rather than "fixing" either to match the other.
    Do not move this back to 9.07."""
    cr = _chroma_spread_check([_reading(2.72, 7.84), _reading(-4.18, -1.22),
                               _reading(-2.72, -0.51), _reading(-0.66, -0.53)], 5.0)
    assert cr.detail["worst"] == pytest.approx(9.06)
    assert cr.passed is False


def test_the_detail_names_every_episode_and_every_absence():
    cr = _chroma_spread_check(
        [_reading(-1.0, -1.0), {"status": "not-checked", "reason": "no render pair"},
         None], 5.0)
    assert cr.detail["per_episode"] == {"0": [-1.0, -1.0]}
    assert cr.detail["not_checked"]["1"] == "no render pair"
    assert "older" in cr.detail["not_checked"]["2"]


def test_one_reading_is_not_a_spread():
    cr = _chroma_spread_check([_reading(-1.0, -1.0), None], 5.0)
    assert cr.passed is None
    assert cr.detail["status"] == "not-checked"


def test_no_chroma_at_all_is_named_not_zero():
    cr = _chroma_spread_check(None, 5.0)
    assert cr.passed is None
    assert cr.detail["reason"]


def test_a_failing_chroma_spread_does_not_fail_the_reel():
    """Advisory end to end: overall is what it would have been (design §3)."""
    from scripts.lib.models import CheckResult, ReelReport
    rep = ReelReport(checks={
        "black": CheckResult("black", True, {}),
        "chroma_spread": CheckResult("chroma_spread", False, {"worst": 9.07})},
        fails=[], duration_s=0.0)
    assert rep.overall is True
```

Match `ReelReport`'s real constructor signature — read it in
`scripts/lib/models.py` rather than copying the line above verbatim if it differs.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_check_reel.py -k chroma tests/lib/test_models.py -k chroma -v
```

Expected: FAIL with `ImportError: cannot import name '_chroma_spread_check'`.

- [ ] **Step 3: Implement**

Add the threshold to `ReelCheckSpec`, directly under `grade_residual_max`:

```python
    chroma_spread_max: float = 5.0     # advisory: the widest gap, across the reel's
                                       # episodes, in what the grade did to their
                                       # COLOUR — the signed CIEDE2000 dC*/dH*
                                       # between each episode's ungraded and graded
                                       # render of the same frames. Content cancels
                                       # by construction, which is what an absolute
                                       # cross-episode chroma statistic cannot do
                                       # (design 2026-09-17 §0.4). Measured: the
                                       # only real reel's three consistently graded
                                       # episodes span 3.52, and its opening shot
                                       # takes that to 9.07 (§2.5).
```

Add `"chroma_spread"` to `_ADVISORY_CHECKS`.

Add to `scripts/check_reel.py`:

```python
def _chroma_spread_check(chroma: list | None, bar: float) -> CheckResult:
    """How far apart the reel's episodes are in what the grade did to their COLOUR.

    ADVISORY, and the name is the whole claim: this measures whether the grade
    treated the episodes alike, NOT whether they end up agreeing. Two episodes with
    the same displacement can still look nothing like each other, and two with
    different displacements can be exactly right if they started apart. The quantity
    a reader wants — do the delivered episodes agree in colour — is not measurable
    from these artifacts: within ONE camera, ungraded, the only real run's episodes
    differ by 4.87 b* with no grade applied at all, so no threshold on an absolute
    chroma statistic separates a mismatch from a different amount of ocean (design
    2026-09-17 §0.4). That is the shape of color_across_cuts, whose ceiling went
    12 -> 44 -> 56 before it was deleted; naming this check after the goal instead
    of after the measurement would be the first step back down that road.

    Each entry is one episode's ReelEpisode.chroma: a reading, a named absence, or
    None for a manifest written before the field existed. A spread over fewer than
    two readings is not a number and says so."""
    if chroma is None:
        return CheckResult("chroma_spread", None,
                           {"status": "not-checked", "advisory": True,
                            "reason": "no per-episode chroma supplied — check_reel's "
                                      "own CLI does not carry it"})
    per: dict[str, list] = {}
    missing: dict[str, str] = {}
    for i, c in enumerate(chroma):
        if isinstance(c, dict) and "delta_c" in c:
            per[str(i)] = [c["delta_c"], c["delta_h"]]
        elif isinstance(c, dict):
            missing[str(i)] = c.get("reason") or "not checked"
        else:
            missing[str(i)] = ("the reel manifest is older than this field — "
                               "re-run phase 1 to record it")
    detail = {"per_episode": per, "not_checked": missing,
              "max": bar, "advisory": True}
    if len(per) < 2:
        return CheckResult("chroma_spread", None,
                           {**detail, "status": "not-checked",
                            "reason": f"{len(per)} episode(s) measured — a spread "
                                      f"needs at least two"})
    cs = [v[0] for v in per.values()]
    hs = [v[1] for v in per.values()]
    spread_c, spread_h = max(cs) - min(cs), max(hs) - min(hs)
    worst = max(spread_c, spread_h)
    return CheckResult("chroma_spread", worst <= bar,
                       {**detail, "spread_c": round(spread_c, 2),
                        "spread_h": round(spread_h, 2), "worst": round(worst, 2)})
```

Wire it into `run`: add `chroma: list | None = None` to the signature after
`brief_len`, and beside the `grade_faithful` assignment add

```python
    checks["chroma_spread"] = _chroma_spread_check(chroma, spec.chroma_spread_max)
```

It appends **no** `ReelFailure` — that is what advisory means here.

In `scripts/build_reel.py`, add `chroma=chroma,` to the `check_reel.run(...)` call.

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_models.py tests/test_build_reel.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py scripts/check_reel.py scripts/build_reel.py tests/lib/test_check_reel.py tests/lib/test_models.py
git commit -m "feat(check_reel): advisory chroma_spread — how far apart the grade left the episodes"
```

---

### Task 6: real-pixel proofs, and the bar re-derived on the suite's own fixture

**Files:**
- Create: `tests/integration/test_chroma_spread.py`
- Test: the same file

**Interfaces:**
- Consumes: everything above.
- Produces: nothing later tasks depend on.

**Context you need:** `golden_ride_segment` is a session fixture
(`tests/conftest.py:150`) producing a real, range-normalized `tv` segment.
`process_episode.plan_for(manifest_dict, src, route)` and
`process_episode.plan_ungraded(...)` build the graded and identity-colour
`RenderPlan`s; `reframe.plan_frames_rgb(plan, src, times)` decodes the frames a plan
would encode; `color.sample_times(dur)` gives the three sample times. Mark the module
with whatever real-ffmpeg marker the neighbouring integration tests use.

- [ ] **Step 1: Write the proofs**

```python
def test_two_identical_chains_displace_nothing(golden_ride_segment):
    """The control that must not move: content cancels by construction, so a
    displacement measured between two renders of ONE chain is exactly 0.0 on both
    components (design §4.4). If this ever drifts, the statistic is measuring the
    encoder, not the grade."""


def test_a_saturation_pull_moves_dC_and_leaves_the_sign_readable(golden_ride_segment):
    """saturation_arg is the one clean, hue-preserving chroma scaler: a pull below
    1.0 must come back as a NEGATIVE delta_c (design §5.2)."""


def test_swapping_the_two_stacks_inverts_the_crops_components(golden_ride_segment):
    """Same inversion the 2026-09-16 row-13 assertion pins for the subject's pair:
    delta_e is identical and every signed component flips."""


def test_the_bar_separates_a_consistent_reel_from_one_odd_episode(golden_ride_segment):
    """The bar re-derived on the suite's own fixture rather than only on the run it
    came from: three episodes graded alike against one graded the other way."""
```

Render the fixture through three manifests differing only in `saturation` /
`mid_blue`, feed the resulting displacements to `_chroma_spread_check`, and assert
the consistent trio passes `ReelCheckSpec(target_dur=…).chroma_spread_max` while the
trio-plus-outlier fails it. Record the four measured displacements in the test's
docstring — they are the fixture-side evidence for 5.0.

- [ ] **Step 2: Run them**

```bash
.venv/bin/python -m pytest tests/integration/test_chroma_spread.py -v
```

Expected: PASS. If the fixture's own numbers do **not** straddle 5.0, do NOT move
the assertions to fit — report the measurement, and the controller rules on whether
the design's threshold changes. A bar that only separates on the run it was derived
from is a finding, not a test failure to paper over.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_chroma_spread.py
git commit -m "test(chroma_spread): real-pixel proofs and the bar on the suite's own fixture"
```

---

### Task 7: mutation battery, docs, version

**Files:**
- Modify: `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`,
  `docs/pipeline-map.md`, `CHANGELOG.md`, `CLAUDE.md`,
  `.claude-plugin/plugin.json`, `references/edit-plan/episode-fields.md`
- Modify: the `episode-qc` skill files if they describe the `grade_damage` report's
  keys (check `skills/episode-qc/SKILL.md` and `skills/episode-qc/episode-reviewer.md`
  — 2026-09-16 shipped a defect where both described a report shape the code did not
  emit)

- [ ] **Step 1: Run the mutation battery**

Each row: apply the mutation, run the named selection, expect RED, restore with
`git show HEAD:<path> > <path>`, re-check `git diff --stat` is empty. Run everything
under `PYTHONDONTWRITEBYTECODE=1`. A row that comes back GREEN is a coverage hole —
close it with a NEW test and say so in the report.

| # | File | Mutation | Must go RED |
|---|---|---|---|
| 1 | `check_episode.py` | emit `crop_delta_*` on BOTH arms (drop the `if fallback is None` guard) | the no-repeat test |
| 2 | `check_episode.py` | `crop = ...evaluate(_region_pairs(p, g, mask))` (subject mask, not `whole`) | the crop-≠-subject test |
| 3 | `check_episode.py` | swap: `out["crop_delta_c"], out["crop_delta_h"] = crop["delta_h"], crop["delta_c"]` | `test_the_crops_displacement_is_the_whole_frame_not_the_background` (corrected — see the note below the table) |
| 4 | `color_fidelity.py` | `shift_from_report` hands over `d["delta_c"]` on the subject arm | Task 2's first test |
| 5 | `color_fidelity.py` | key on `"status" in d` instead of on `region` | add a report whose advisory half carries a `status` key |
| 6 | `models.py` | drop `ReelEpisode.__post_init__` entirely | the three refusal tests |
| 7 | `models.py` | accept `region="background"` | the unknown-region test |
| 8 | `models.py` | `chroma_spread_max = 50.0` | the one-odd-episode test |
| 9 | `models.py` | remove `"chroma_spread"` from `_ADVISORY_CHECKS` | the advisory test |
| 10 | `edl_to_reel.py` | pass `chroma=None` | phase-1 recording test |
| 11 | `build_reel.py` | drop the reprocess-arm refresh | the reprocess freshness test |
| 12 | `build_reel.py` | build `chroma` inside the round loop from `rm.episodes` (so the refresh is overwritten every round) | the reprocess freshness test |
| 13 | `check_reel.py` | `worst = min(spread_c, spread_h)` | `test_one_episode_graded_the_other_way_fails_the_bar` (corrected — see the note below the table) |
| 14 | `check_reel.py` | `worst < bar` instead of `worst <= bar` | needs a test pinned exactly at the bar — write one |
| 15 | `check_reel.py` | `len(per) < 1` instead of `< 2` | the one-reading test |
| 16 | `check_reel.py` | treat a `None` entry as `{"delta_c": 0.0, "delta_h": 0.0}` | the names-every-absence test |
| 17 | `check_reel.py` | append a `ReelFailure` for a failing spread | the advisory test |
| 18 | `check_reel.py` | `spread_c = max(cs)` (drop `- min(cs)`) | the widest-gap test |

**Corrections found by running the battery, not by inspection.** Row 3's
original pointer, "an integration sign proof," named a test that never calls
`check_episode` at all — the mutation is actually caught by
`test_the_crops_displacement_is_the_whole_frame_not_the_background` (Task 1's
own crop-≠-subject test). Row 13's original pointer reused row 8's
"one-odd-episode test," which asserts `worst == pytest.approx(9.06)` and
cannot tell a `min` from a `max` on that fixture — the mutation is actually
caught by `test_one_episode_graded_the_other_way_fails_the_bar`. Both cells
above are corrected to the test that actually discriminates. **Row 14 came
back GREEN** on the first pass — no existing test was pinned exactly at
`worst == bar` — a genuine coverage hole, closed with a new test,
`test_the_bar_is_inclusive_at_the_boundary`.

**Corrected, final whole-branch review, FIX 7:** this note said 9.07 here,
design §2.5's full-precision figure, where the SHIPPED test's own literal is
9.06. See design §2.5's closing note and docs/build-status.md's Done entry,
which reconcile the two numbers deliberately — 9.07 is the real reel's
full-precision measurement, 9.06 is what the test's 2-decimal literals compute
— rather than treating either as a typo to fix toward the other.

- [ ] **Step 2: Full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: everything green, and the count no lower than the pre-slice baseline
(record both numbers in the report).

- [ ] **Step 3: Docs**

- `docs/backlog.md`: move R2.1 to the archive as `✅`, with the closure note saying
  what the row's premise got right (§0.1/§0.2) and what its remedy got wrong (§0.4,
  §0.5). Move the P3 chroma-convergence line out of the Colour list. File §6's four
  deferrals as new rows.
- `docs/backlog-closed.md`: R2.1's closure note, and re-count the archive's
  parenthetical (the CLAUDE.md registry row states the count and the rule that it is
  re-counted when a row closes).
- `docs/build-status.md`: the Done entry, with the seven tasks and the battery
  roll-call.
- `docs/pipeline-map.md`: `check_reel` gains an advisory check.
- `CHANGELOG.md` + `.claude-plugin/plugin.json`: **0.12.0** (a new contract field
  and a new check — MINOR). `tests/test_plugin_manifests.py` enforces that the top
  changelog entry matches the manifest version.
- `CLAUDE.md`: a registry row for the design and the plan, in the table's existing
  two-row idiom.
- `references/edit-plan/episode-fields.md`: only if it documents report keys.

- [ ] **Step 4: Commit**

```bash
git add docs CHANGELOG.md CLAUDE.md .claude-plugin/plugin.json references skills
git commit -m "docs: close R2.1 — the chroma half closes by measurement, not by a target"
```

---

## Self-Review

**Spec coverage.** §2.1 → Tasks 1–2. §2.2 → Task 1. §2.3 → Tasks 3–4. §2.4 → Task 5.
§2.5 → Task 5 (value) and Task 6 (re-derivation). §3 → Task 5's advisory wiring plus
battery rows 9 and 17. §4's seven proofs → Task 1's three tests (proof 1), Task 6
(proofs 2, 3, 4), Task 5's tests (proofs 5, 6, 7). §5 → Task 7's docs. §6 → Task 7's
backlog rows.

**Known weak point.** Task 6 is the one task whose numbers are not yet known: the
fixture's own displacements have not been measured, so the claim that they straddle
5.0 is a prediction, not a measurement. Step 2 says explicitly what to do if they do
not — report, do not fit. Treat a GREEN there as a finding about the threshold, not
as a broken test.

**Type consistency.** `shift_from_report` returns the exact two shapes
`ReelEpisode.__post_init__` accepts and `_chroma_spread_check` reads;
`per_episode` keys are `str(i)` in both the check and its tests, matching
`grade_faithful`'s own `{idx: …}` string-keyed detail maps.
