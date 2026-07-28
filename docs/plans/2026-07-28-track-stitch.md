# Track ID-switch Stitching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** splice a hero track id and its post-occlusion re-acquisition(s) into ONE route so the crop keeps following the subject instead of freezing on the truncated id, and record which ids were merged in `TrackMeta`.

**Architecture:** four pure functions in `scripts/track.py` (`_segments`, `_median`, `_joinable`, `stitch_ids`) beside the existing pure track-analysis helpers; `build_route` calls `stitch_ids` before it writes the `TrackMeta` sidecar, records the merged ids as `TrackMeta.stitched`, and the route loop picks the overlap match nearer the current route position. This is a faithful port of the parked hot-patch (`wip/montage-run-hardening` `4841dd3`) plus one addition — the `stitched` provenance — and one deviation — the call moves ahead of the meta so the sidecar can carry it.

**Tech Stack:** Python 3.13, pytest. Tests run as modules (`pythonpath = .`), Python = `.venv/bin/python`. No new dependencies. `stitch_ids` and helpers are pure (no ffmpeg / YOLO); `build_route` integration is tested with the established faked-detector harness (`_FakeBox`/`_FakeRes`/`_fake_iter` in `tests/integration/test_track.py`) — real YOLO detection is never run in the track tests.

**Spec:** [docs/specs/2026-07-28-track-stitch-design.md](../specs/2026-07-28-track-stitch-design.md)

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/lib/models.py` | `TrackMeta.stitched: list[int]` provenance field + `to_dict`/`from_dict` (Task 0) |
| `scripts/track.py` | `STITCH_*` constants, `_segments`/`_median`/`_joinable`/`stitch_ids`, `build_route` integration (Tasks 1–4) |
| `tests/lib/test_models.py` | `TrackMeta.stitched` round-trip (Task 0) |
| `tests/lib/test_track.py` | `_segments`/`_median`/`_joinable` unit tests + the 15 `stitch_ids` unit tests (Tasks 1–3) |
| `tests/integration/test_track.py` | `build_route` stitch + provenance + src_w-guard (Task 4) |
| `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, this plan | docs sync (Task 5) |

---

## Task 0: `TrackMeta.stitched` provenance field

**Files:**
- Modify: `scripts/lib/models.py` (the `TrackMeta` dataclass, ~lines 85–112)
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing round-trip test**

Add to `tests/lib/test_models.py` (import `models` the same way the file already does — it uses `from scripts.lib import models`):

```python
def test_trackmeta_stitched_defaults_empty_and_round_trips():
    # default: a clean single-id route records no stitched ids
    assert models.TrackMeta().stitched == []
    # explicit value survives to_dict → from_dict
    m = models.TrackMeta(hero=1, stitched=[66, 91])
    assert m.to_dict()["stitched"] == [66, 91]
    assert models.TrackMeta.from_dict(m.to_dict()).stitched == [66, 91]


def test_trackmeta_from_dict_without_stitched_is_backward_compatible():
    # a sidecar written before this slice has no "stitched" key → []
    legacy = {"hero": 1, "ambiguous": False, "intent": "action",
              "features": {}, "pin_matched": None, "degraded": None}
    assert models.TrackMeta.from_dict(legacy).stitched == []
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k stitched -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'stitched'` (and/or `KeyError`/attribute error).

- [x] **Step 3: Add the field + wire to_dict/from_dict**

In `scripts/lib/models.py`, add the field to `TrackMeta` right after `degraded`:

```python
    degraded: str | None = None    # None = clean (YOLO) | "flow" | "manual" (design 2026-07-21 §5) —
                                    # ROUTE-side provenance, the twin of PathMeta.pan/.stabilized
    stitched: list[int] = field(default_factory=list)   # ids merged onto the route BEYOND the hero
                                    # by an ID-switch stitch (design 2026-07-28 §6). [] = clean single id.
```

In `from_dict`, add `stitched` to the constructor call:

```python
        return cls(hero=d.get("hero"), ambiguous=bool(d.get("ambiguous", False)),
                   intent=d.get("intent", "action"), features=d.get("features", {}),
                   pin_matched=d.get("pin_matched"), degraded=d.get("degraded"),
                   stitched=list(d.get("stitched", [])))
```

In `to_dict`, add the key:

```python
    def to_dict(self) -> dict:
        return {"hero": self.hero, "ambiguous": self.ambiguous,
                "intent": self.intent, "features": self.features,
                "pin_matched": self.pin_matched, "degraded": self.degraded,
                "stitched": self.stitched}
```

(`field` is already imported in `models.py` — it is used by `TrackMeta.features`.)

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k stitched -v`
Expected: PASS (both tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: TrackMeta.stitched provenance field (track-stitch §6)"
```

---

## Task 1: `_segments` + `_median` pure helpers

**Files:**
- Modify: `scripts/track.py` (add both functions after `_seed_track`, before `_rule_track`)
- Test: `tests/lib/test_track.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_track.py` (the file already has `from scripts import track` at the top):

```python
# --- ID-switch stitching (§6.1a) ------------------------------------------------

def _frames(spans, fps=60.0):
    """spans: {tid: (first, last, x0, dx, w, h)} → the per_frame shape build_route builds."""
    n = 1 + max(s[1] for s in spans.values())
    out = []
    for idx in range(n):
        dets = []
        for tid, (a, b, x0, dx, w, h) in spans.items():
            if a <= idx <= b:
                dets.append((tid, x0 + dx * (idx - a), 500.0, w, h))
        out.append((idx, dets))
    return out


def test_segments_records_ends_count_and_per_frame_x():
    pf = _frames({1: (0, 4, 100.0, 10.0, 120, 300)})
    segs = track._segments(pf)
    assert segs[1]["first"] == 0 and segs[1]["last"] == 4 and segs[1]["n"] == 5
    assert segs[1]["head"] == (100.0, 500.0, 120, 300)
    assert segs[1]["tail"] == (140.0, 500.0, 120, 300)
    assert segs[1]["at"] == {0: 100.0, 1: 110.0, 2: 120.0, 3: 130.0, 4: 140.0}


def test_median_handles_odd_and_even_lengths():
    assert track._median([3.0, 1.0, 2.0]) == 2.0
    assert track._median([1.0, 2.0, 3.0, 4.0]) == 2.5
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -k "segments or median" -v`
Expected: FAIL — `AttributeError: module 'scripts.track' has no attribute '_segments'`.

- [x] **Step 3: Add `_segments` and `_median`**

In `scripts/track.py`, insert after `_seed_track` (ends ~line 104) and before `_rule_track`:

```python
def _segments(per_frame: list[_Frame]) -> dict[int, dict]:
    """Per track id: first/last frame index, the bbox at each end, and every frame's
    x — `at` is what lets two OVERLAPPING segments be compared where they coexist."""
    segs: dict[int, dict] = {}
    for idx, dets in per_frame:
        for tid, x, y, w, h in dets:
            s = segs.get(tid)
            if s is None:
                segs[tid] = {"first": idx, "last": idx, "n": 1,
                             "head": (x, y, w, h), "tail": (x, y, w, h), "at": {idx: x}}
            else:
                s["last"] = idx
                s["n"] += 1
                s["tail"] = (x, y, w, h)
                s["at"][idx] = x
    return segs


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -k "segments or median" -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/track.py tests/lib/test_track.py
git commit -m "feat: track _segments/_median stitch primitives + _frames test helper"
```

---

## Task 2: `STITCH_*` constants + `_joinable`

**Files:**
- Modify: `scripts/track.py` (constants near `AMBIG_MARGIN` ~line 18; `_joinable` after `_median`)
- Test: `tests/lib/test_track.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_track.py` (below the Task 1 tests):

```python
def test_joinable_overlap_uses_shared_frames_and_skips_the_area_gate():
    # two segments that share frames 2..4, ~3px apart, one box COLLAPSING (area would
    # reject on endpoints) — the overlap regime joins them anyway.
    a = {"at": {0: 100.0, 1: 101.0, 2: 102.0, 3: 103.0, 4: 104.0},
         "tail": (104.0, 500.0, 40, 80), "head": (100.0, 500.0, 104, 207)}
    b = {"at": {2: 105.0, 3: 106.0, 4: 107.0, 5: 108.0},
         "head": (105.0, 500.0, 70, 116), "tail": (108.0, 500.0, 70, 116)}
    assert track._joinable(a, b, gap=-2, speed=3.0, src_w=1920) is True


def test_joinable_gap_joins_within_reach_and_same_size_class():
    a = {"at": {0: 100.0}, "tail": (100.0, 500.0, 120, 300), "head": (100.0, 500.0, 120, 300)}
    b = {"at": {10: 130.0}, "head": (130.0, 500.0, 120, 300), "tail": (130.0, 500.0, 120, 300)}
    # 30px jump, reach floor = 0.02*1920 = 38.4 → within reach; same size → joins
    assert track._joinable(a, b, gap=9, speed=3.0, src_w=1920) is True


def test_joinable_gap_refuses_a_jump_beyond_reach():
    a = {"at": {0: 100.0}, "tail": (100.0, 500.0, 120, 300), "head": (100.0, 500.0, 120, 300)}
    b = {"at": {10: 900.0}, "head": (900.0, 500.0, 120, 300), "tail": (900.0, 500.0, 120, 300)}
    assert track._joinable(a, b, gap=9, speed=3.0, src_w=1920) is False


def test_joinable_gap_refuses_a_very_different_size():
    a = {"at": {0: 100.0}, "tail": (100.0, 500.0, 120, 300), "head": (100.0, 500.0, 120, 300)}
    b = {"at": {10: 110.0}, "head": (110.0, 500.0, 20, 40), "tail": (110.0, 500.0, 20, 40)}
    assert track._joinable(a, b, gap=9, speed=3.0, src_w=1920) is False
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -k joinable -v`
Expected: FAIL — `AttributeError: module 'scripts.track' has no attribute '_joinable'`.

- [x] **Step 3: Add the constants + `_joinable`**

In `scripts/track.py`, after the `AMBIG_MARGIN` block (~line 18–19), add the constant block:

```python
# --- ID-switch stitching (§6.1a) -------------------------------------------------
# ByteTrack drops a subject through an occlusion — spray, a passing lip, a frame the
# detector misses — and re-acquires it under a NEW id. The route is built from ONE id,
# so a switch truncates it, and reframe then holds the last crop position for the whole
# remainder: measured on a 9.14s drone ride, the hero track ended at 3.04s and the crop
# sat frozen for the other 6.10s while the rider carried on to the frame edge. That is
# not the frame gap the smoother bridges — it is 67% of the shot left uncomposed.
#
# The thresholds below are deliberately tight, because stitching too eagerly fails far
# worse than not stitching: splicing a STRANGER onto the hero's route teleports the crop
# mid-shot and reads as a cut. A candidate must resume within a blink, from about where
# the hero left off, at about the size the hero had.
STITCH_MAX_GAP_S = 0.40      # a re-acquisition later than this is not a blink
STITCH_MAX_OVERLAP_S = 0.50  # ...and a handover may also OVERLAP: ByteTrack routinely
                             # confirms the new id BEFORE it drops the old one, so the
                             # same rider reads as tid 1 over frames 0..182 and tid 66
                             # over 180..547 — a gap of -2. Measured overlaps run from 2
                             # to 29 frames on the same shot, so this is generous rather
                             # than tight: an overlapping pair is judged on where the two
                             # tracks sit ON THE FRAMES THEY SHARE (see _joinable), which
                             # is far stronger evidence than the length of the overlap.
STITCH_MIN_FRAMES = 5        # below this a "track" is detector noise, not a subject
STITCH_SPEED_SLACK = 3.0     # travel allowed = the hero's own mean speed x gap x this
STITCH_MIN_JUMP_FRAC = 0.02  # ...but never less than 2% of frame width (a slow hero)
STITCH_AREA_RATIO = 2.5      # apparent size may not change by more than this factor
```

Then, after `_median` (from Task 1), add `_joinable`:

```python
def _joinable(a: dict, b: dict, gap: int, speed: float, src_w: int) -> bool:
    """Is segment `b` the same subject as `a`, resuming `gap` frames later (or, for a
    negative gap, `-gap` frames before `a` ends)?

    Two regimes, because they have different evidence available:

    OVERLAP — the tracks coexist on real frames, so ask the question directly: how far
    apart are they WHERE THEY BOTH EXIST? The same rider handed between two ids sits a
    few px apart on every shared frame; two different surfers stay apart on all of them.
    That is strictly better evidence than any endpoint comparison, so it is used alone —
    in particular the box-area gate is skipped, because a dying track's last boxes are
    degrading (that degradation is usually WHY it died) and comparing them against a
    fresh track's first boxes reads a healthy handover as a size change. Measured: a
    detector box collapsing 104x207 -> 70x116 through spray, 3px away, is one rider.

    GAP — nothing coexists, so fall back to the endpoints: the jump must fit the hero's
    own speed, and the box must be in the same size class (the distant-bystander guard).
    """
    shared = sorted(set(a["at"]) & set(b["at"]))
    reach = max(STITCH_MIN_JUMP_FRAC * src_w, speed * max(1, abs(gap)) * STITCH_SPEED_SLACK)
    if shared:
        return _median([abs(a["at"][i] - b["at"][i]) for i in shared]) <= reach
    ax, _ay, aw, ah = a["tail"]
    bx, _by, bw, bh = b["head"]
    if abs(bx - ax) > reach:
        return False
    area_a, area_b = aw * ah, bw * bh
    if area_a <= 0 or area_b <= 0:
        return False
    ratio = area_b / area_a
    return 1 / STITCH_AREA_RATIO <= ratio <= STITCH_AREA_RATIO
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -k joinable -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/track.py tests/lib/test_track.py
git commit -m "feat: track STITCH_* thresholds + _joinable (overlap/gap regimes)"
```

---

## Task 3: `stitch_ids` chaining

**Files:**
- Modify: `scripts/track.py` (add `stitch_ids` after `_joinable`)
- Test: `tests/lib/test_track.py`

- [x] **Step 1: Write the failing tests**

Append the parked `stitch_ids` battery to `tests/lib/test_track.py` (the `_frames` helper from Task 1 is already present; add `_SPEED` once):

```python
_SPEED = {1: {"speed": 3.0}}


def test_stitch_joins_a_track_that_resumes_where_the_hero_stopped():
    # the measured case: hero ends at frame 182, a new id picks the SAME subject up at 183
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  142: (183, 550, 1450.0, 3.0, 130, 310)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 142}


def test_stitch_refuses_a_stranger_across_the_frame():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  9: (183, 550, 200.0, 3.0, 120, 300)})     # 1250px away in one frame
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_a_resumption_after_a_long_gap():
    # 0.4s at 60fps = 24 frames; 40 is past it — not a blink, a different moment
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  7: (223, 550, 1450.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_a_track_of_a_very_different_size():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  8: (183, 550, 1450.0, 3.0, 20, 40)})      # a distant bystander
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_ignores_noise_fragments():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  5: (183, 185, 1450.0, 3.0, 120, 300)})    # 3 frames < STITCH_MIN_FRAMES
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_chains_through_two_switches():
    pf = _frames({1: (0, 100, 900.0, 3.0, 120, 300),
                  2: (101, 200, 1210.0, 3.0, 120, 300),
                  3: (201, 300, 1520.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 2, 3}


def test_stitch_reaches_backwards_for_the_head_of_a_shot():
    # `largest` picks the LONGER late fragment; the take-off is the earlier one
    pf = _frames({4: (0, 100, 600.0, 3.0, 120, 300),
                  1: (101, 500, 910.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 4}


def test_stitch_with_no_hero_stitches_nothing():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, None, 60.0, 1920, _SPEED) == set()


def test_stitch_without_a_frame_width_declines_to_guess():
    # build_route skips the probe when the caller supplies fps — no scale, no stitch
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  142: (183, 550, 1450.0, 3.0, 130, 310)})
    assert track.stitch_ids(pf, 1, 60.0, None, _SPEED) == {1}


def test_stitch_joins_an_overlapping_handover():
    # the measured shape: ByteTrack confirms the new id 2 frames BEFORE it drops the old.
    # Positions and boxes are the real ones — tid 1 ends at (845, 151x360) and tid 66
    # opens at (868, 142x352): 23px apart, the same rider.
    pf = _frames({1: (0, 182, 1027.0, -1.0, 151, 360),      # tail x = 1027 - 182 = 845
                  66: (180, 547, 868.0, 1.0, 142, 352)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 66}


def test_stitch_refuses_a_bystander_who_brackets_the_hero():
    # a track that spans the whole shot offers a small negative gap at BOTH ends, so the
    # overlap tolerance alone would absorb it — the extension test is what refuses it
    pf = _frames({1: (100, 300, 900.0, 3.0, 120, 300),
                  5: (0, 500, 880.0, 0.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_an_overlap_longer_than_a_handover():
    # 0.5s at 60fps = 30 frames; a 61-frame overlap is two people, not one handover
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  6: (122, 547, 1450.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_uses_where_two_overlapping_tracks_actually_sit():
    # the same rider handed over across a 29-frame overlap, with the outgoing track's
    # box COLLAPSING through spray (104x207 -> 70x116). The area gate would reject that
    # pair on endpoints alone; on the frames they share they are 3px apart.
    pf = _frames({1: (0, 157, 1079.0, -1.13, 104, 207),
                  7: (129, 177, 1079.0 - 1.13 * 129 + 3, -1.13, 70, 116)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 7}


def test_stitch_refuses_two_people_who_merely_coexist():
    # same overlap, same sizes — but 400px apart on every frame they share
    pf = _frames({1: (0, 157, 1079.0, -1.13, 104, 207),
                  7: (129, 177, 1079.0 - 1.13 * 129 + 400, -1.13, 104, 207)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_chains_a_shot_fragmented_into_four():
    # the measured day-1 ride: overlap, overlap, then a 2-frame gap
    pf = _frames({1:  (0,   157, 1079.0, -1.13, 104, 207),
                  7:  (129, 177,  934.0, -0.4,   76, 112),
                  10: (168, 221,  905.0,  1.0,   70, 116),
                  14: (223, 547,  958.0,  0.23,  81, 175)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 7, 10, 14}
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -k stitch -v`
Expected: FAIL — `AttributeError: module 'scripts.track' has no attribute 'stitch_ids'`.

- [x] **Step 3: Add `stitch_ids`**

In `scripts/track.py`, after `_joinable`, add:

```python
def stitch_ids(per_frame: list[_Frame], hero_id: int | None, fps: float,
               src_w: int | None, feats: dict[int, dict] | None = None) -> set[int]:
    """The hero id plus every id that is the SAME SUBJECT re-acquired after an
    ID switch — see the STITCH_* block for why this exists and why it is strict.

    Chains forward and backward from the hero, one hop at a time, so a subject
    dropped twice is followed twice; each candidate is judged against the segment
    it would attach to, never against the original hero, because a real subject
    drifts across a shot. A None hero (nobody picked) stitches nothing: there is
    no anchor, and guessing one here would resurrect exactly the largest-in-frame
    fallback build_route refuses below.
    """
    if hero_id is None:
        return set()
    if src_w is None:
        # build_route skips the probe when the caller supplies fps, and the reach
        # test is stated as a fraction of frame width. Without the width there is no
        # scale to judge a jump against, so DON'T stitch — an unstitched route is a
        # frozen crop the report shows, a mis-stitched one is a stranger nobody sees.
        return {hero_id}
    segs = _segments(per_frame)
    if hero_id not in segs:
        return {hero_id}
    speed = (feats or {}).get(hero_id, {}).get("speed") or 0.0
    max_gap = max(1, round(STITCH_MAX_GAP_S * fps))
    max_overlap = max(1, round(STITCH_MAX_OVERLAP_S * fps))
    chosen = {hero_id}
    for forward in (True, False):
        cur = segs[hero_id]
        while True:
            cands = []
            for tid, s in segs.items():
                if tid in chosen or s["n"] < STITCH_MIN_FRAMES:
                    continue
                gap = (s["first"] - cur["last"]) if forward else (cur["first"] - s["last"])
                if not -max_overlap <= gap <= max_gap:
                    continue
                # A candidate must EXTEND the coverage, not sit inside it. Without this
                # the overlap tolerance would happily absorb a bystander who stands in
                # frame for the whole shot — their track brackets the hero's on both
                # sides, so every gap it offers is a small negative one.
                if (s["last"] <= cur["last"]) if forward else (s["first"] >= cur["first"]):
                    continue
                a, b = (cur, s) if forward else (s, cur)
                # `a` always precedes `b` in TIME, so the reach test reads the same
                # way in both directions: tail-of-earlier vs head-of-later.
                if _joinable(a, b, gap, speed, src_w):
                    cands.append((abs(gap), tid, s))
            if not cands:
                break
            _d, tid, seg = min(cands)        # nearest in time; ties on the lower id
            chosen.add(tid)
            cur = seg
    return chosen
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py -k stitch -v`
Expected: PASS (15 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/track.py tests/lib/test_track.py
git commit -m "feat: track.stitch_ids — forward/backward ID-switch chaining (§6.1a)"
```

---

## Task 4: `build_route` integration — stitch before the meta, provenance, route-nearer pick

**Files:**
- Modify: `scripts/track.py` (`build_route`, the meta-write + route loop, ~lines 335–355)
- Test: `tests/integration/test_track.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/integration/test_track.py` (it already defines `_FakeBox`, `_FakeRes`, `_fake_iter` at the top and imports `track`, `models`):

```python
def _switch_frames():
    """tid 1 slides right for frames 0..20, then the SAME subject is re-acquired as
    tid 66 with a 3-frame overlap (18..20), 8px off tid 1's path — one rider, two ids.
    41 frames total."""
    frames = []
    for i in range(41):
        dets = []
        if i <= 20:
            dets.append(_FakeBox([900.0 + i * 5, 500.0, 120.0, 300.0], 1))
        if i >= 18:
            dets.append(_FakeBox([900.0 + i * 5 + 8, 500.0, 122.0, 302.0], 66))
        frames.append(dets)
    return frames


def test_build_route_stitches_an_id_switch_and_records_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(_switch_frames()))
    monkeypatch.setattr(track, "_probe_meta", lambda src: (60.0, 1920, 1080))  # fps=None → probe
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4",
                            pin=models.HeroPin(kind="track", track_id=1))
    route = track.build_route(spec, out=str(out))
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.stitched == [66]                 # provenance names the merged id
    assert len(route) == 41                       # every frame contributed — no freeze at tid 1's end
    assert route[-1].t > 20 / 60.0                # the route continues PAST where tid 1 stopped


def test_build_route_clean_single_id_records_no_stitch(monkeypatch, tmp_path):
    frames = [[_FakeBox([900.0 + i * 5, 500.0, 120.0, 300.0], 1)] for i in range(20)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    monkeypatch.setattr(track, "_probe_meta", lambda src: (60.0, 1920, 1080))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", pin=models.HeroPin(kind="track", track_id=1))
    track.build_route(spec, out=str(out))
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.stitched == []


def test_build_route_with_fps_supplied_does_not_stitch(monkeypatch, tmp_path):
    # fps in the spec → build_route skips the probe → src_w is None → stitch_ids returns
    # {hero} and the route-loop change is byte-identical to the old hero-only pick.
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(_switch_frames()))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=60,
                            pin=models.HeroPin(kind="track", track_id=1))
    route = track.build_route(spec, out=str(out))
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.stitched == []                    # no width → no stitch
    assert len(route) == 21                        # only tid 1's frames (0..20), not tid 66's
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -k "stitch or single_id or fps_supplied" -v`
Expected: FAIL — `AssertionError` on `meta.stitched == [66]` (the field is `[]` because `build_route` does not call `stitch_ids` yet), and/or `len(route) == 41` fails (route stops at 21).

- [x] **Step 3: Wire `stitch_ids` into `build_route`**

In `scripts/track.py`, replace the meta-write + route-loop block (currently the `meta = TrackMeta(...)` construction through `return route`, ~lines 338–355) with:

```python
    # the hero's id, plus any id that is the hero re-acquired after an ID switch.
    # Called BEFORE the meta so the sidecar can carry the stitch provenance.
    hero_ids = stitch_ids(per_frame, hero_id, fps, src_w, feats)
    stitched = sorted(hero_ids - {hero_id})
    meta = TrackMeta(hero=hero_id, ambiguous=ambiguous, intent=spec.intent,
                     features={str(k): {kk: f[kk] for kk in
                                        ("n", "disp", "area", "speed", "border")}
                               for k, f in feats.items()},
                     pin_matched=pin_matched, stitched=stitched)
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta.to_dict()))

    route = []
    for idx, dets in per_frame:
        # hero only — NO largest-in-frame fallback: it would splice strangers'
        # coordinates into the route (false teleports for the continuity check);
        # a frame gap is fine, smoothing bridges it. `hero_ids` is not that
        # fallback: every extra id in it passed stitch_ids' continuity test against
        # the hero's own trajectory, the opposite of picking whoever is biggest.
        #
        # A handover OVERLAPS (see STITCH_MAX_OVERLAP_S), so for a few frames BOTH the
        # outgoing and incoming id report the same person from slightly different boxes.
        # Taking whichever comes first in detection order would flip between them and
        # write a small teleport into the route at the exact moment the crop is meant to
        # be continuous — so follow the nearer one to where the route already is.
        matches = [d for d in dets if d[0] in hero_ids]
        if len(matches) > 1 and route:
            matches.sort(key=lambda d: abs(d[1] - route[-1].x))
        pick = matches[0] if matches else None
        if pick:
            _, x, y, w, h = pick
            route.append(RoutePoint(t=idx / fps, x=x, y=y, w=w, h=h))
    route_to_json(route, out)
    return route
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -k "stitch or single_id or fps_supplied" -v`
Expected: PASS (3 tests).

- [x] **Step 5: Run the whole track suite to prove no regression**

Run: `.venv/bin/python -m pytest tests/lib/test_track.py tests/integration/test_track.py -v`
Expected: PASS — all existing route tests still green (they supply `fps`, so `src_w` is None and the route loop reduces to the old hero-only pick).

- [x] **Step 6: Commit**

```bash
git add scripts/track.py tests/integration/test_track.py
git commit -m "feat: build_route stitches ID switches + records TrackMeta.stitched"
```

---

## Task 5: docs sync + full suite

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/plans/2026-07-28-track-stitch.md` (this file — tick the boxes), `docs/specs/2026-07-28-track-stitch-design.md` (status line)

- [x] **Step 1: Run the full suite (baseline for the docs claim)**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (record the exact `N passed / M skipped` count for the build-status entry). No golden fixtures move — this slice adds no new render path.

- [x] **Step 2: build-status.md**

Add a DONE entry under the current front matter, dated 2026-07-28, describing the track-stitch slice: "`track.stitch_ids` bridges a hero ID switch (§6.1a) — `TrackMeta.stitched` provenance, route-nearer overlap pick; port of the parked `4841dd3` hunk. Full suite `<N> passed / <M> skipped`." Follow the format of the existing most-recent entry (the colour-stage entry).

- [x] **Step 3: pipeline-map.md**

In the §6.1 / tracking row (the same row that mentions `TrackMeta.degraded` and the tracking ladder), add a note that `build_route` now stitches post-occlusion ID switches into one route, recording the merged ids in `TrackMeta.stitched`.

- [x] **Step 4: CLAUDE.md registry**

Add two rows to the Quick Reference table (matching the existing row style), pointing at the design and plan:

```markdown
| Track-stitch design | [2026-07-28-track-stitch-design.md](docs/specs/2026-07-28-track-stitch-design.md) | §6.1a: `stitch_ids` splices a hero ID switch back into one route (occlusion re-acquisition) — measured tight thresholds, overlap-vs-gap evidence, `TrackMeta.stitched` provenance; port of the parked `4841dd3` hunk. |
| Track-stitch plan | [2026-07-28-track-stitch.md](docs/plans/2026-07-28-track-stitch.md) | Tasks 0–5: `TrackMeta.stitched`, `_segments`/`_median`/`_joinable`/`stitch_ids`, `build_route` stitch-before-meta + route-nearer pick, faked-detector integration proof, docs. |
```

- [x] **Step 5: Tick this plan's checkboxes + the spec status**

Mark every `- [ ]` in this plan `- [x]`. In the design spec, update the **Status** line to note the slice landed (2026-07-28).

- [x] **Step 6: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/registry for track-stitch"
```

---

## Self-review notes (for the final whole-slice reviewer)

- **Anti-regression pin (Task 4, Step 5):** the route-loop change must be byte-identical when `stitch_ids` returns `{hero_id}` — every existing `test_track.py` route test supplies `fps`, so `src_w` is `None`, `stitch_ids` returns `{hero_id}`, and `matches = [d for d in dets if d[0] in {hero_id}]` yields the same single hero pick as the old `next(...)`. If any existing route test changes its expected output, the loop rewrite is wrong.
- **The one deviation from the park:** `stitch_ids` is called *before* the `TrackMeta` construction (the park called it at the route loop). Verified free — all inputs are computed by that point.
- **Provenance has no consumer gate** by design (§8) — `TrackMeta.stitched` is observability only. Do not add a check that reads it in this slice.
- **No real-YOLO test** — consistent with every other `build_route` test in the repo (the detector is always faked). Staging a real ByteTrack ID switch deterministically is out of scope (spec §7).
