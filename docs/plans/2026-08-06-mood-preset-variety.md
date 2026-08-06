# Mood presets + shot-size variety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the cut a mood and an objective it can be held to — `edit_plan build`
refuses a cut that takes *zero* of a shot size the mood's preset wants and the
footage actually offers, unless the selection carries a written waiver.

**Architecture:** A new pure `scripts/lib/moodpreset.py` holds the preset table, its
resolution from `SPEC.mood` (reusing `lib/mood.py`'s existing anchor vocabulary), and
the `available`-vs-`used` evaluation. `scripts/lib/footage.py` gains the shot-size
classifier (moved out of `intake`) plus a delivered-geometry variant, and
`FootageWindow` starts *storing* the three measurements intake already computes and
throws away (`CACHE_VERSION` 6→7). `scripts/edit_plan.py` counts both sides during
projection, attaches a typed `VarietyReport` to the EDL, and returns a
`stop_and_report` when a gap survives without a waiver.

**Tech Stack:** Python 3.13, stdlib-only in the pure modules, pytest. No new
dependency. No ffmpeg change.

**Design spec:** [docs/specs/2026-08-06-mood-preset-variety-design.md](../specs/2026-08-06-mood-preset-variety-design.md) — read §1.1, §5, §6, §7 before Task 0.

## Global Constraints

- **Python is `.venv/bin/python` (3.13).** Scripts run as modules: `python -m scripts.edit_plan`. `pytest.ini` sets `pythonpath = .`.
- **Fail-loud contract.** A contract boundary raises `ValueError` with a *remedy* in the message. No silent defaults for missing data, no `except: pass`.
- **Config-spec pattern.** Dataclass + validate-and-raise in `__post_init__` + JSON round-trip (`to_dict`/`from_dict`), like `models.TrackSpec`, `footage.FootageWindow`, `edl.EDL`.
- **Imports at top of file**, never inside functions, except a documented lazy import of a heavy optional dependency.
- **Whole-object asserts** in tests where the repo already uses them (the intake goldens compare a whole `FootageClip`).
- **Tests live in `tests/lib/` (unit) and `tests/integration/` (real ffmpeg/librosa, marked `pytest.mark.integration`).**
- **Exact constants, copied verbatim:** `MIN_AVAIL = 3`, `WANT_FLOOR = 0.20`, `CLOSE_AREA = 0.30`, `MEDIUM_AREA = 0.08`, `SHOT_TYPES = ("close", "medium", "wide")`, `CACHE_VERSION = 7`.
- **The gate's reason string is `variety-gap`** — its own value, never `edl-invalid`.
- **The stop shape is the one `edl.preflight` already returns:** `{"status": "stop_and_report", "finding": {"reason": ..., "episode_idx": ..., "problems": [str, ...]}}`.
- **Do not re-tune `_motion_fit`** (design §1.1). This slice stores its inputs; the curve is out of scope.
- **Do not add a `V1_STAGES` row.** The gate lives inside a stage that already exists.
- **Never `git commit --amend`.** Post-review fixes are separate follow-up commits.
- **Never run installers** (`brew`, `pip install`, `setup.sh`). Verification is read-only plus `pytest`.
- **Branch:** work happens on `feat/mood-preset-variety`, already created, design spec already committed as `abfacca`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `scripts/lib/footage.py` | `SHOT_TYPES`, `shot_type(w,h)`, `delivered_shot(...)`; `FootageWindow` + 3 measured fields; the legacy-artifact refusal | 0, 1 |
| `scripts/intake.py` | stops owning the classifier; `_build_window` stores the measurements; `CACHE_VERSION` 7 | 0, 1 |
| `scripts/lib/mood.py` | +4 anchors (`fun`, `playful`, `nostalgic`, `adventure`) | 2 |
| `scripts/lib/moodpreset.py` | **new** — `MoodPreset`, `PRESETS`, `BALANCED`, `resolve`, `VarietyReport`, `evaluate` | 2, 3 |
| `scripts/lib/edl.py` | `EDL.variety` carrier + the `## Variety` markdown section | 4 |
| `scripts/edit_plan.py` | both censuses during projection, the gate, the waiver, `--spec` | 5 |
| `skills/edit-plan/SKILL.md` | the variety objective, the waiver, `--spec` | 7 |
| `skills/using-montage/SKILL.md` | pass `--spec` when a brief exists | 7 |
| `tests/lib/test_footage.py` | classifier boundaries, delivered multiplier, field validation, legacy refusal | 0, 1 |
| `tests/lib/test_intake.py` | the moved classifier call site | 0 |
| `tests/lib/test_moodpreset.py` | **new** — table, resolution, evaluation | 2, 3 |
| `tests/lib/test_mood.py` | the four new anchors resolve | 2 |
| `tests/lib/test_edl.py` | `variety` round-trip + markdown section | 4 |
| `tests/lib/test_edit_plan.py` | census, gate, waiver, `--spec` | 5 |
| `tests/integration/test_intake.py` | golden re-pin with the three new fields | 1 |
| `tests/integration/test_edit_plan.py` | end-to-end refusal + waiver + the block in `EDL.json` | 6 |

---

## Task 0: The shot-size classifier moves to `footage`, and learns delivered geometry

The classifier currently lives in `scripts/intake.py` and buckets on *source*
geometry only. Move it — atomically, no duplicate left behind — and add the
delivered-geometry variant that `edit_plan` will call. Design §6.

**Files:**
- Modify: `scripts/lib/footage.py` (add near the top, after the `_num` helper)
- Modify: `scripts/intake.py:40` (delete `CLOSE_AREA, MEDIUM_AREA`), `scripts/intake.py:51-62` (delete `shot_type`), `scripts/intake.py:298` (call site)
- Test: `tests/lib/test_footage.py`, `tests/lib/test_intake.py`

**Interfaces:**
- Consumes: `scripts.lib.geometry.crop_for(aspect, scale, src_w, src_h) -> (crop_w, crop_h)` — already exists.
- Produces: `footage.SHOT_TYPES: tuple[str, str, str]`, `footage.CLOSE_AREA`, `footage.MEDIUM_AREA`, `footage.shot_type(subject_w: float, subject_h: float) -> str`, `footage.delivered_shot(subject_w: float, subject_h: float, res: tuple[int, int], aspect: tuple[int, int], crop_scale: float = 1.0) -> str`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_footage.py`:

```python
def test_shot_type_buckets_on_area_with_exact_boundaries():
    # MEDIUM_AREA 0.08 is inclusive, CLOSE_AREA 0.30 is exclusive (> not >=)
    assert footage.shot_type(0.0, 0.0) == "wide"          # no subject → scenery
    assert footage.shot_type(0.2, 0.399) == "wide"         # area 0.0798 < 0.08
    assert footage.shot_type(0.2, 0.4) == "medium"         # area 0.08 exactly
    assert footage.shot_type(0.5, 0.6) == "medium"         # area 0.30 exactly, NOT close
    assert footage.shot_type(0.5, 0.61) == "close"         # area 0.305 > 0.30


def test_delivered_shot_grows_the_area_by_the_width_crop():
    # 3840x2160 → 9:16 fill: crop is 1215x2160, so width scales by 3840/1215 = 3.16
    # and height does not scale at all. A subject at 3% of the source frame is `wide`
    # in source geometry and `medium` once the delivery crop is taken into account.
    src, aspect = (3840, 2160), (9, 16)
    assert footage.shot_type(0.1, 0.3) == "wide"                       # area 0.030
    assert footage.delivered_shot(0.1, 0.3, src, aspect) == "medium"   # area 0.0948


def test_delivered_shot_clamps_a_subject_wider_than_the_crop():
    # a subject filling the source width is fully framed after the crop, not 3.16x wide
    assert footage.delivered_shot(1.0, 1.0, (3840, 2160), (9, 16)) == "close"


def test_delivered_shot_without_people_is_wide_in_any_geometry():
    assert footage.delivered_shot(0.0, 0.0, (3840, 2160), (9, 16)) == "wide"
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -k "shot_type or delivered" -v`
Expected: FAIL with `AttributeError: module 'scripts.lib.footage' has no attribute 'shot_type'`

- [x] **Step 3: Add the classifier to `scripts/lib/footage.py`**

Add `from scripts.lib import geometry` to the imports (`geometry.py` imports `models`
only under `TYPE_CHECKING`, so there is no cycle), and insert after the `_num` helper:

```python
SHOT_TYPES = ("close", "medium", "wide")
CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08     # subject-area fractions bounding the three tags


def shot_type(subject_w: float, subject_h: float) -> str:
    """close/medium/wide from the subject's area as a fraction of the FRAME it is
    measured against. Geometry-agnostic on purpose (design 2026-08-06 §6): intake
    passes source fractions, edit_plan passes delivered ones via delivered_shot,
    and one classifier keeps the two from drifting apart. No subject — (0.0, 0.0) —
    is 'wide', the same answer scenery gets."""
    area = subject_w * subject_h
    if area > CLOSE_AREA:
        return "close"
    if area >= MEDIUM_AREA:
        return "medium"
    return "wide"


def delivered_shot(subject_w: float, subject_h: float, res: tuple[int, int],
                   aspect: tuple[int, int], crop_scale: float = 1.0) -> str:
    """The window's shot size as it will READ in the delivered frame rather than in
    the source one. A 9:16 fill crop of a 16:9 source keeps the height and cuts the
    width, so the subject's area fraction grows by src_w/crop_w — 3.16x for
    3840x2160 — which is why the source-geometry tag cannot discriminate on footage
    shot from a distance (design §1c, §6). The fractions are scale-normalized, so it
    does not matter that intake measured them on the 960 analysis proxy while `res`
    is the original: only the divisor changes, and it changes on both sides."""
    crop_w, crop_h = geometry.crop_for(aspect, crop_scale, *res)
    return shot_type(min(1.0, subject_w * res[0] / crop_w),
                     min(1.0, subject_h * res[1] / crop_h))
```

- [x] **Step 4: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -k "shot_type or delivered" -v`
Expected: PASS (4 tests)

- [x] **Step 5: Delete intake's copy and rewire its call site**

In `scripts/intake.py`, delete the whole `def shot_type(bbox, res)` function (lines
51–62) and the `CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08` constant line (line 40).
In `_build_window`, replace

```python
    shot = shot_type(primary, res)
```

with

```python
    w, h = res
    sw = (primary[2] / w) if primary is not None and w else 0.0
    sh = (primary[3] / h) if primary is not None and h else 0.0
    shot = footage.shot_type(sw, sh)
```

`footage` is already imported in `intake.py`. `res` here is the **proxy** resolution
(`pres`), so `sw`/`sh` are proxy-normalized fractions — which is exactly what the
contract stores (design §5).

- [x] **Step 6: Update the moved-function test in `tests/lib/test_intake.py`**

Search that file for `intake.shot_type` and rewrite each call onto the new signature —
`intake.shot_type(bbox, res)` becomes `footage.shot_type(bw / w, bh / h)`. If a test
exercised the `None` bbox case, express it as `footage.shot_type(0.0, 0.0)`.

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_footage.py -q`
Expected: PASS

- [x] **Step 7: Prove no copy of the classifier is left behind**

Run: `grep -rn "def shot_type" scripts/`
Expected: exactly one hit, `scripts/lib/footage.py`.

Run: `grep -rn "CLOSE_AREA\|MEDIUM_AREA" scripts/`
Expected: hits only in `scripts/lib/footage.py`.

- [x] **Step 8: Run the whole unit suite**

Run: `.venv/bin/python -m pytest tests/lib -q`
Expected: PASS

- [x] **Step 9: Commit**

```bash
git add scripts/lib/footage.py scripts/intake.py tests/lib/test_footage.py tests/lib/test_intake.py
git commit -m "refactor(footage): shot_type moves out of intake and learns delivered geometry"
```

---

## Task 1: `FootageWindow` stores the measurement, not only the verdict

Intake computes the primary bbox and the presence fraction, derives two verdicts from
them, and discards the inputs. Store them, bump the cache, and refuse an artifact
written before this change rather than reading it as "no people anywhere". Design §5.

**Files:**
- Modify: `scripts/lib/footage.py` (`FootageWindow` fields + validation + `to_dict`; `FootageClip.from_dict` guard)
- Modify: `scripts/intake.py` (`_build_window` returns the three; nothing else)
- Modify: `scripts/lib/intake_cache.py:39` (`CACHE_VERSION = 6` → `7`)
- Modify: `tests/integration/test_scenario_first.py`, `tests/lib/test_pacing_driver.py` (hand-written window dicts)
- Test: `tests/lib/test_footage.py`, `tests/integration/test_intake.py`

**Interfaces:**
- Consumes: `footage.shot_type` from Task 0.
- Produces: `FootageWindow.subject_w: float`, `.subject_h: float`, `.present: float` — all defaulting to `0.0`, all validated into `[0, 1]`, all in `to_dict()`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_footage.py`:

```python
def test_window_carries_the_three_measurements_and_round_trips():
    w = footage.FootageWindow(start=0.0, dur=2.0, shot_type="medium", people=1,
                              motion=0.3, shake=0.01, subject_w=0.25, subject_h=0.4,
                              present=0.75)
    assert (w.subject_w, w.subject_h, w.present) == (0.25, 0.4, 0.75)
    assert footage.FootageWindow(**w.to_dict()).to_dict() == w.to_dict()


@pytest.mark.parametrize("bad", [
    dict(subject_w=-0.1), dict(subject_w=1.1), dict(subject_h=-0.1),
    dict(subject_h=1.1), dict(present=-0.1), dict(present=1.1),
    dict(present="1.0"), dict(present=True),
])
def test_window_refuses_a_measurement_outside_the_unit_interval(bad):
    base = dict(start=0.0, dur=2.0, shot_type="wide", people=0, motion=0.0, shake=0.0)
    with pytest.raises(ValueError, match="subject_w|subject_h|present"):
        footage.FootageWindow(**{**base, **bad})


def test_clip_from_dict_refuses_a_footage_json_written_before_the_shot_size_fields():
    legacy = {"source": "a.mp4", "dur": 10.0, "res": [1920, 1080], "fps": 30.0,
              "windows": [{"start": 0.0, "dur": 2.0, "shot_type": "wide",
                           "people": 0, "motion": 0.0, "shake": 0.0}]}
    with pytest.raises(ValueError, match="predates.*re-run footage-intake"):
        footage.FootageClip.from_dict(legacy)
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -k "measurement or predates or three" -v`
Expected: FAIL — `TypeError: FootageWindow.__init__() got an unexpected keyword argument 'subject_w'` and, for the legacy test, no exception raised.

- [x] **Step 3: Add the fields, the validation, and the `to_dict` keys**

In `scripts/lib/footage.py`, `FootageWindow` gains three fields after `track_ids`:

```python
    subject_w: float = 0.0   # primary subject's bbox width as a fraction of the frame width
    subject_h: float = 0.0   # ...and height. 0.0 / 0.0 = no person detected in this window
    present: float = 0.0     # fraction of this window's samples holding >= 1 person
```

In `__post_init__`, after the `track_ids` check:

```python
        for name in ("subject_w", "subject_h", "present"):
            v = getattr(self, name)
            if not (_num(v) and 0.0 <= v <= 1.0):
                raise ValueError(
                    f"FootageWindow.{name} must be a number in [0, 1] — subject_w/subject_h "
                    f"are fractions of the frame, present is a fraction of the window's "
                    f"samples; got {v!r}")
```

In `to_dict`, add to the returned dict:

```python
                "subject_w": self.subject_w, "subject_h": self.subject_h,
                "present": self.present,
```

- [x] **Step 4: Add the legacy-artifact refusal to `FootageClip.from_dict`**

In the `for k, w in enumerate(wins_in):` loop, immediately after the
`if not isinstance(w, dict):` check and before `FootageWindow(**w)`:

```python
            if "present" not in w:
                raise ValueError(
                    f"FootageClip.from_dict: windows[{k}] predates the 2026-08-06 shot-size "
                    f"fields (missing 'present') — re-run footage-intake to rescan. The "
                    f"fields carry 0.0 defaults so the object would build, but it would then "
                    f"claim 'no people anywhere' and the variety gate would read that as a "
                    f"monotone footage set")
```

Checking key *presence*, not value, is the point: `0.0` is a legitimate measurement.

- [x] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -k "measurement or predates or three" -v`
Expected: PASS

- [x] **Step 6: Make intake store what it already computes**

In `scripts/intake.py`, `_build_window` — reuse the `sw`/`sh` locals Task 0 introduced
and the existing `present` local, and pass all three to the constructor:

```python
    return footage.FootageWindow(start=round(a, 3), dur=round(d, 3), shot_type=shot,
                                 people=people, motion=round(motion, 3), shake=round(shake, 4),
                                 description=_describe(people, shot, motion), score=round(score, 3),
                                 track_ids=track_ids, subject_w=round(sw, 4),
                                 subject_h=round(sh, 4), present=round(present, 3))
```

- [x] **Step 7: Bump the cache version**

In `scripts/lib/intake_cache.py`, change `CACHE_VERSION = 6` to `CACHE_VERSION = 7` and
extend its comment with one line naming why:

```python
CACHE_VERSION = 7   # 6→7 (2026-08-06): FootageWindow stores subject_w/subject_h/present,
                    # measured in Phase 1 — a cached ClipResult cannot supply them.
```

- [x] **Step 8: Repair the hand-written window dicts in existing fixtures**

Six sites build a `"windows": [{...}]` dict literal and will now hit the Step-4
refusal. Add `"present": 1.0, "subject_w": 0.0, "subject_h": 0.0` to each window dict
in:

- `tests/integration/test_scenario_first.py` (three sites, near lines 32, 67, 96)
- `tests/lib/test_pacing_driver.py` (three sites, near lines 24, 74, 95)

`subject_w`/`subject_h` of `0.0` classify as `wide`, matching the `"shot_type": "wide"`
those fixtures already declare — so the fixture stays internally consistent.

Find them all with: `grep -rn '"shot_type"' tests/ | grep '"windows"\|"start"'`

- [x] **Step 9: Re-pin the intake goldens**

Run: `.venv/bin/python -m pytest tests/integration/test_intake.py -v`
Expected: FAIL — the whole-object `FootageClip` comparisons now differ, because the
expected `FootageWindow(...)` still carries the `0.0` defaults while the actual object
carries measured values.

Read the actual values out of the assertion diff and pin them into both goldens
(`test_intake_writes_footage_and_cast` and `test_intake_real_vidstab_shake`), adding
`subject_w=..., subject_h=..., present=...` to each expected `FootageWindow`.

Sanity-check before accepting the numbers: `subject_w * subject_h` must be below
`MEDIUM_AREA` (0.08), because the existing golden pins `shot_type="wide"` and Task 0
did not change how the tag is derived. If it is not, the move in Task 0 has a bug —
stop and report rather than re-pinning around it.

Re-run: `.venv/bin/python -m pytest tests/integration/test_intake.py -v`
Expected: PASS

- [x] **Step 10: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Any other failure is a fixture that hand-writes a window dict — fix it
the same way as Step 8.

- [x] **Step 11: Commit**

```bash
git add scripts/lib/footage.py scripts/intake.py scripts/lib/intake_cache.py tests/
git commit -m "feat(footage): store subject_w/subject_h/present; CACHE_VERSION 6→7"
```

---

## Task 2: `lib/moodpreset.py` — the preset table and its resolution

Design §4. Four named presets plus a fallback, resolved through the *existing* mood
vocabulary so there is no second lexicon to keep in sync.

**Files:**
- Create: `scripts/lib/moodpreset.py`
- Modify: `scripts/lib/mood.py` (`MOOD_ANCHORS` + 4 entries)
- Test: `tests/lib/test_moodpreset.py` (new), `tests/lib/test_mood.py`

**Interfaces:**
- Consumes: `mood.MoodVector`, `mood.mood_target(text) -> MoodVector | None`, `mood.distance(a, b) -> float`, `footage.SHOT_TYPES`.
- Produces: `moodpreset.MoodPreset` (fields `name`, `anchor`, `shot_mix`, `asl`), `moodpreset.PRESETS: tuple[MoodPreset, ...]`, `moodpreset.BALANCED: MoodPreset`, `moodpreset.resolve(mood_text: str | None) -> MoodPreset`.

- [x] **Step 1: Write the failing tests**

Create `tests/lib/test_moodpreset.py`:

```python
import pytest

from scripts.lib import mood, moodpreset
from scripts.lib.footage import SHOT_TYPES


def test_every_shipped_preset_is_a_valid_distribution():
    for p in (*moodpreset.PRESETS, moodpreset.BALANCED):
        assert set(p.shot_mix) == set(SHOT_TYPES)
        assert abs(sum(p.shot_mix.values()) - 1.0) < 1e-6
        assert 0.0 < p.asl[0] < p.asl[1]


def test_preset_refuses_a_mix_that_is_not_a_distribution():
    with pytest.raises(ValueError, match="sum to 1.0"):
        moodpreset.MoodPreset("x", None, {"close": 0.5, "medium": 0.4, "wide": 0.4}, (1.0, 2.0))


def test_preset_refuses_unknown_or_missing_mix_keys():
    with pytest.raises(ValueError, match="shot_mix keys"):
        moodpreset.MoodPreset("x", None, {"close": 0.5, "wide": 0.5}, (1.0, 2.0))


def test_preset_refuses_an_inverted_asl_band():
    with pytest.raises(ValueError, match="asl"):
        moodpreset.MoodPreset("x", None, {"close": 0.3, "medium": 0.3, "wide": 0.4}, (4.0, 2.0))


@pytest.mark.parametrize("text,expected", [
    ("fun and playful", "fun"),
    ("epic adventure", "epic"),
    ("dark and brooding", "moody"),
    ("nostalgic", "nostalgic"),
])
def test_resolve_picks_the_nearest_named_preset(text, expected):
    assert moodpreset.resolve(text).name == expected


@pytest.mark.parametrize("text", [None, "", "   ", "xyzzy plugh"])
def test_resolve_falls_back_to_balanced_when_nothing_matches(text):
    assert moodpreset.resolve(text).name == "balanced"


def test_balanced_is_never_a_match_target():
    # it is the fallback only — a mid-range anchor in the search would swallow
    # every mood sitting between the four named ones
    assert moodpreset.BALANCED not in moodpreset.PRESETS
    assert moodpreset.BALANCED.anchor is None
    assert all(p.anchor is not None for p in moodpreset.PRESETS)


def test_balanced_still_asks_for_close_ups():
    # the autonomous path (no SPEC.json) must not get a dead gate
    assert moodpreset.BALANCED.shot_mix["close"] >= 0.20
```

Append to `tests/lib/test_mood.py`:

```python
def test_the_real_brief_vocabulary_now_matches_an_anchor():
    # 'fun and playful' matched NO anchor before 2026-08-06 and fell into the
    # drive-ranking fallback — the music ranking was running blind on the real run
    assert mood.mood_target("fun and playful") is not None
    for token in ("fun", "playful", "nostalgic", "adventure"):
        assert token in mood.MOOD_ANCHORS
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_moodpreset.py tests/lib/test_mood.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.moodpreset'`, and the mood test fails on the missing anchors.

- [x] **Step 3: Add the four anchors to `scripts/lib/mood.py`**

Inside `MOOD_ANCHORS`, after the `"happy"/"joyful"/"upbeat"/"bright"` group:

```python
    "fun": MoodVector(0.75, 0.85, 0.72),       "playful": MoodVector(0.72, 0.82, 0.70),
    "adventure": MoodVector(0.80, 0.60, 0.65), "nostalgic": MoodVector(0.35, 0.45, 0.35),
```

- [x] **Step 4: Create `scripts/lib/moodpreset.py` with the type, the table, and `resolve`**

```python
"""Mood presets (design docs/specs/2026-08-06-mood-preset-variety-design.md §4) —
the playbook §3 spine, carrying exactly the two fields its one consumer reads.

A mood is not one knob: it is a recipe across shot selection, pace, colour, music
and effects. v1 wires the SELECTION half only — `edit_plan` reads `shot_mix` to
decide which shot-size under-use is refusable, and `asl` to report the realized
average shot length against a band. Colour, effects and QC are named follow-ups in
the design's §14, not fields nothing reads.

Pure: stdlib + lib.mood + lib.footage's SHOT_TYPES vocabulary. No IO."""
from dataclasses import dataclass

from scripts.lib import mood
from scripts.lib.footage import SHOT_TYPES


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class MoodPreset:
    """name + the anchor it is matched by + what it asks of the cut.

    `anchor` is None for BALANCED alone: the fallback must stay OUT of the
    nearest-neighbour search, or a mid-range vector would swallow every mood that
    sits between the four named presets."""
    name: str
    anchor: mood.MoodVector | None
    shot_mix: dict[str, float]        # a distribution over SHOT_TYPES, summing to 1.0
    asl: tuple[float, float]          # (lo, hi) seconds — reported, never enforced

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError("MoodPreset.name must be a non-empty string")
        if self.anchor is not None and not isinstance(self.anchor, mood.MoodVector):
            raise ValueError(f"MoodPreset.anchor must be a MoodVector or None (None = the "
                             f"fallback preset, excluded from matching), got {self.anchor!r}")
        if not isinstance(self.shot_mix, dict) or set(self.shot_mix) != set(SHOT_TYPES):
            raise ValueError(f"MoodPreset.shot_mix keys must be exactly {SHOT_TYPES}, got "
                             f"{sorted(self.shot_mix) if isinstance(self.shot_mix, dict) else self.shot_mix!r}")
        for k, v in self.shot_mix.items():
            if not (_num(v) and 0.0 <= v <= 1.0):
                raise ValueError(f"MoodPreset.shot_mix[{k!r}] must be a number in [0, 1], got {v!r}")
        total = sum(self.shot_mix.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"MoodPreset.shot_mix must sum to 1.0 (it is a distribution over "
                             f"{SHOT_TYPES}), got {total}")
        if not (isinstance(self.asl, (tuple, list)) and len(self.asl) == 2
                and all(_num(v) for v in self.asl)):
            raise ValueError(f"MoodPreset.asl must be a (lo, hi) pair of seconds, got {self.asl!r}")
        self.asl = (float(self.asl[0]), float(self.asl[1]))
        if not 0.0 < self.asl[0] < self.asl[1]:
            raise ValueError(f"MoodPreset.asl needs 0 < lo < hi seconds, got {self.asl!r}")


# Hand-tuned FIRST CUT. No footage has been cut against these numbers, so they live
# in this one place and are declared as guesses — the same honesty intake's
# CLUSTER_COS and MAX_CAST carry. Calibrate on the first real run that uses them.
PRESETS: tuple[MoodPreset, ...] = (
    MoodPreset("fun", mood.MoodVector(0.74, 0.84, 0.72),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (1.2, 2.5)),
    MoodPreset("epic", mood.MoodVector(0.80, 0.55, 0.55),
               {"close": 0.25, "medium": 0.35, "wide": 0.40}, (1.5, 3.5)),
    MoodPreset("moody", mood.MoodVector(0.48, 0.22, 0.42),
               {"close": 0.30, "medium": 0.35, "wide": 0.35}, (2.5, 5.0)),
    MoodPreset("nostalgic", mood.MoodVector(0.32, 0.45, 0.34),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (2.0, 4.0)),
)

# The no-match fallback. Its close share is deliberately above WANT_FLOOR: the
# autonomous path skips the optional reel-brief, and skipping a brief must not
# disable a quality gate (design §4.2). "A montage that stays one size reads
# amateur" is a grammar rule, not a mood-specific one.
BALANCED = MoodPreset("balanced", None,
                      {"close": 0.25, "medium": 0.40, "wide": 0.35}, (1.5, 4.0))


def resolve(mood_text: str | None) -> MoodPreset:
    """SPEC.mood -> the nearest named preset; empty or unrecognised -> BALANCED.

    Reuses mood.mood_target's anchor vocabulary rather than introducing a second
    lexicon, so 'fun and playful' resolves the same way here and in the music
    ranking. Because BALANCED is never a match target, `resolve(t).name ==
    "balanced"` is an exact test for 'nothing matched' — which is how the caller
    knows to log the fallback instead of applying it silently."""
    if not (isinstance(mood_text, str) and mood_text.strip()):
        return BALANCED
    target = mood.mood_target(mood_text)
    if target is None:
        return BALANCED
    return min(PRESETS, key=lambda p: mood.distance(p.anchor, target))
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_moodpreset.py tests/lib/test_mood.py -q`
Expected: PASS

- [x] **Step 6: Check the new anchors did not disturb the music ranking tests**

Run: `.venv/bin/python -m pytest tests/lib/test_mood_driver.py tests/lib/test_music_find_driver.py tests/integration/test_mood.py -q`
Expected: PASS. If a test asserted that some string falls into the drive fallback and
that string contains one of the four new tokens, the assertion is now wrong on
purpose — update it and note the reason in the test's comment.

- [x] **Step 7: Commit**

```bash
git add scripts/lib/moodpreset.py scripts/lib/mood.py tests/lib/test_moodpreset.py tests/lib/test_mood.py
git commit -m "feat(moodpreset): MoodPreset table + resolution through the existing mood anchors"
```

---

## Task 3: `VarietyReport` + `evaluate` — available vs used

Design §7 and §9. Pure counting-dicts in, typed report out — no `Footage`/`EDL`
import, so every branch is unit-testable on literals.

**Files:**
- Modify: `scripts/lib/moodpreset.py`
- Test: `tests/lib/test_moodpreset.py`

**Interfaces:**
- Consumes: `MoodPreset` from Task 2.
- Produces: `moodpreset.MIN_AVAIL = 3`, `moodpreset.WANT_FLOOR = 0.20`, `moodpreset.VarietyReport` (fields `preset: str`, `available: dict[str, int]`, `used: dict[str, int]`, `asl: float`, `asl_band: tuple[float, float]`, `gaps: tuple[str, ...]`, `waiver: str | None`; property `ok: bool`; `to_dict()`/`from_dict()`), `moodpreset.evaluate(available, used, asl, preset, waiver=None) -> VarietyReport`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_moodpreset.py`:

```python
def _counts(close=0, medium=0, wide=0):
    return {"close": close, "medium": medium, "wide": wide}


def test_evaluate_flags_a_size_the_preset_wants_and_the_footage_offers():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"))
    assert r.gaps == ("close",)
    assert r.ok is False
    assert r.available["close"] == 11 and r.used["close"] == 0


def test_evaluate_is_silent_when_the_footage_cannot_offer_the_size():
    # 2 close windows is below MIN_AVAIL — one stray misdetection must not block a reel
    r = moodpreset.evaluate(_counts(close=2, wide=40), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"))
    assert r.gaps == () and r.ok is True


def test_evaluate_is_silent_at_the_min_avail_boundary_and_fires_one_above():
    fun = moodpreset.resolve("fun")
    assert moodpreset.evaluate(_counts(close=2, wide=9), _counts(wide=3), 2.0, fun).gaps == ()
    assert moodpreset.evaluate(_counts(close=3, wide=9), _counts(wide=3), 2.0, fun).gaps == ("close",)


def test_evaluate_ignores_a_size_the_preset_barely_wants():
    # a shot_mix share below WANT_FLOOR is reported, never refused
    quiet = moodpreset.MoodPreset("quiet", None, {"close": 0.10, "medium": 0.45, "wide": 0.45},
                                  (2.0, 4.0))
    r = moodpreset.evaluate(_counts(close=20, wide=40), _counts(wide=8), 2.0, quiet)
    assert r.gaps == ()


def test_evaluate_does_not_flag_a_size_the_cut_already_uses():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(close=1, wide=8), 2.0,
                            moodpreset.resolve("fun"))
    assert r.gaps == ()


def test_a_waiver_makes_a_gapped_report_ok_without_erasing_the_gap():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"), waiver="every close window is out of focus")
    assert r.gaps == ("close",)          # the finding survives — it is recorded, not deleted
    assert r.ok is True


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_waiver_is_refused(blank):
    with pytest.raises(ValueError, match="waiver"):
        moodpreset.evaluate(_counts(close=11), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"), waiver=blank)


def test_report_round_trips_through_json():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(wide=8), 2.5,
                            moodpreset.resolve("fun"), waiver="deliberate")
    assert moodpreset.VarietyReport.from_dict(r.to_dict()).to_dict() == r.to_dict()


def test_gaps_are_reported_in_shot_type_order():
    bare = moodpreset.MoodPreset("bare", None, {"close": 0.34, "medium": 0.33, "wide": 0.33},
                                 (1.0, 5.0))
    r = moodpreset.evaluate(_counts(close=5, medium=5, wide=5), _counts(wide=3), 2.0, bare)
    assert r.gaps == ("close", "medium")
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_moodpreset.py -k "evaluate or waiver or report or gaps" -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.moodpreset' has no attribute 'evaluate'`

- [x] **Step 3: Add the constants, the report, and the evaluation**

Append to `scripts/lib/moodpreset.py`:

```python
MIN_AVAIL = 3        # windows of a size below which a zero-use is NOT refusable — one
                     # stray misdetection must not block a reel (design §7)
WANT_FLOOR = 0.20    # shot_mix share at or above which the preset genuinely asks for a size


@dataclass
class VarietyReport:
    """What the cut did with the shot sizes the footage offered.

    Both censuses are measured in the SAME geometry (the project's default framing —
    design §6); comparing a delivered `used` against a source `available` would put
    the two sides of the comparison in different units. `gaps` survives a waiver on
    purpose: the waiver records a decision, it does not delete the finding."""
    preset: str
    available: dict[str, int]
    used: dict[str, int]
    asl: float
    asl_band: tuple[float, float]
    gaps: tuple[str, ...] = ()
    waiver: str | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.preset, str) and self.preset):
            raise ValueError("VarietyReport.preset must be the preset's name")
        for name in ("available", "used"):
            c = getattr(self, name)
            if not isinstance(c, dict) or set(c) != set(SHOT_TYPES):
                raise ValueError(f"VarietyReport.{name} must be a count per {SHOT_TYPES}, got {c!r}")
            for k, v in c.items():
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise ValueError(f"VarietyReport.{name}[{k!r}] must be an int >= 0, got {v!r}")
        if not (_num(self.asl) and self.asl >= 0):
            raise ValueError(f"VarietyReport.asl must be a number >= 0 seconds, got {self.asl!r}")
        if not (isinstance(self.asl_band, (tuple, list)) and len(self.asl_band) == 2
                and all(_num(v) for v in self.asl_band)):
            raise ValueError(f"VarietyReport.asl_band must be a (lo, hi) pair, got {self.asl_band!r}")
        self.asl_band = (float(self.asl_band[0]), float(self.asl_band[1]))
        self.gaps = tuple(self.gaps)
        bad = [g for g in self.gaps if g not in SHOT_TYPES]
        if bad:
            raise ValueError(f"VarietyReport.gaps must name shot types from {SHOT_TYPES}, got {bad}")
        if self.waiver is not None and not (isinstance(self.waiver, str) and self.waiver.strip()):
            raise ValueError(
                "VarietyReport.waiver must be a non-empty reason or null — a blank waiver is a "
                'bypass wearing the costume of a decision. State why the cut stays one size in '
                'selection.json\'s "variety_waiver"')

    @property
    def ok(self) -> bool:
        """A gap with a recorded reason passes; a gap without one does not."""
        return not self.gaps or bool(self.waiver)

    def to_dict(self) -> dict:
        return {"preset": self.preset, "available": dict(self.available),
                "used": dict(self.used), "asl": self.asl, "asl_band": list(self.asl_band),
                "gaps": list(self.gaps), "waiver": self.waiver}

    @classmethod
    def from_dict(cls, d: dict) -> "VarietyReport":
        if not isinstance(d, dict):
            raise ValueError(f"VarietyReport.from_dict: expected an object with preset/available/"
                             f"used fields, got {type(d).__name__} — re-run edit_plan build")
        return cls(preset=d.get("preset"), available=d.get("available"), used=d.get("used"),
                   asl=d.get("asl"), asl_band=d.get("asl_band"),
                   gaps=tuple(d.get("gaps") or ()), waiver=d.get("waiver"))


def evaluate(available: dict[str, int], used: dict[str, int], asl: float,
             preset: MoodPreset, waiver: str | None = None) -> VarietyReport:
    """Refuse only on a size the cut uses ZERO of, that the footage genuinely offers,
    and that the preset genuinely wants (design §7, decision 6). Deviation from the
    target fractions when the size IS used, and the realized ASL, are carried in the
    report for the human and never refused: the machine can prove 'the footage offered
    close-ups and you took none', not that some ideal mix was reachable."""
    gaps = tuple(s for s in SHOT_TYPES
                 if used.get(s, 0) == 0
                 and available.get(s, 0) >= MIN_AVAIL
                 and preset.shot_mix[s] >= WANT_FLOOR)
    return VarietyReport(preset=preset.name,
                         available={s: int(available.get(s, 0)) for s in SHOT_TYPES},
                         used={s: int(used.get(s, 0)) for s in SHOT_TYPES},
                         asl=float(asl), asl_band=preset.asl, gaps=gaps, waiver=waiver)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_moodpreset.py -q`
Expected: PASS (all tests in the file)

- [x] **Step 5: Commit**

```bash
git add scripts/lib/moodpreset.py tests/lib/test_moodpreset.py
git commit -m "feat(moodpreset): VarietyReport + available-vs-used evaluation"
```

---

## Task 4: `EDL.variety` — the carrier and its markdown section

Design §9. The report has to live on the object, because `EDL.to_markdown` renders
from the object and a report that stayed in the driver could not be printed.

**Files:**
- Modify: `scripts/lib/edl.py` (`EDL` field + validation + `to_dict` + `from_dict` + `to_markdown`)
- Test: `tests/lib/test_edl.py`

**Interfaces:**
- Consumes: `moodpreset.VarietyReport` from Task 3.
- Produces: `EDL.variety: VarietyReport | None = None`, serialized under the `"variety"` key; `EDL.to_markdown()` gains a `## Variety` section when `variety` is set.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py` (reuse whatever episode factory that file already
defines; the snippet below assumes a local `_ep()` helper returning one valid
`EDLEpisode` — if the file names it differently, use that name):

```python
def test_edl_carries_a_variety_report_and_round_trips():
    r = moodpreset.evaluate({"close": 11, "medium": 0, "wide": 40},
                            {"close": 0, "medium": 0, "wide": 8}, 2.0,
                            moodpreset.resolve("fun"), waiver="close windows are soft")
    e = EDL(episodes=(_ep(),), variety=r)
    back = EDL.from_dict(e.to_dict())
    assert back.variety.to_dict() == r.to_dict()


def test_edl_without_a_variety_report_round_trips_as_none():
    # a hand-authored EDL through edl_to_reel's SP1 front door was never evaluated
    e = EDL(episodes=(_ep(),))
    assert e.to_dict()["variety"] is None
    assert EDL.from_dict(e.to_dict()).variety is None


def test_edl_refuses_a_variety_field_that_is_not_a_report():
    with pytest.raises(ValueError, match="variety"):
        EDL(episodes=(_ep(),), variety={"preset": "fun"})


def test_markdown_prints_available_against_used_and_the_waiver():
    r = moodpreset.evaluate({"close": 11, "medium": 0, "wide": 40},
                            {"close": 0, "medium": 0, "wide": 8}, 2.0,
                            moodpreset.resolve("fun"), waiver="close windows are soft")
    md = EDL(episodes=(_ep(),), variety=r).to_markdown()
    assert "## Variety" in md
    assert "fun" in md and "close" in md and "11" in md
    assert "close windows are soft" in md
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -k variety -v`
Expected: FAIL — `TypeError: EDL.__init__() got an unexpected keyword argument 'variety'`

- [x] **Step 3: Add the field and its validation**

In `scripts/lib/edl.py`, import the type at the top —
`from scripts.lib.moodpreset import VarietyReport` (`moodpreset` imports `mood` and
`footage`, neither of which imports `edl`, so no cycle) — and add to `EDL` after
`target_dur`:

```python
    variety: VarietyReport | None = None   # design 2026-08-06 §9. None = never evaluated
                                           # (a hand-authored EDL through the SP1 front door)
```

In `__post_init__`, after the `target_dur` check:

```python
        if self.variety is not None and not isinstance(self.variety, VarietyReport):
            raise ValueError(f"EDL.variety must be a VarietyReport or None, got "
                             f"{type(self.variety).__name__} — re-run edit_plan build")
```

- [x] **Step 4: Serialize it**

In `to_dict`, add to the base dict:

```python
             "variety": self.variety.to_dict() if self.variety is not None else None,
```

In `from_dict`, add to the `cls(...)` call:

```python
                   variety=VarietyReport.from_dict(d["variety"]) if d.get("variety") else None,
```

An `EDL.json` stamped before this slice has no `"variety"` key, so `d.get` returns
`None` and its provenance digest — computed over the raw dict as written — still
matches. No existing artifact is invalidated.

- [x] **Step 5: Render the section**

At the end of `to_markdown`, before `return "\n".join(lines)`:

```python
        if self.variety is not None:
            v = self.variety
            lines += ["", f"## Variety — preset `{v.preset}`", "",
                      "| shot | available | used |", "|------|----------:|-----:|"]
            lines += [f"| {s} | {v.available[s]} | {v.used[s]} |" for s in v.available]
            lines += ["", f"ASL {v.asl:.2f}s against the preset's "
                          f"{v.asl_band[0]:.1f}–{v.asl_band[1]:.1f}s band "
                          f"(reported, not enforced)."]
            if v.gaps:
                lines.append(f"**Unused sizes the footage offered:** {', '.join(v.gaps)}.")
            if v.waiver:
                lines.append(f"**Waiver:** {v.waiver}")
```

Iterating `v.available` rather than `SHOT_TYPES` keeps the render honest to whatever
the report actually holds; `VarietyReport.__post_init__` already guarantees the keys.

- [x] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: PASS

- [x] **Step 7: Run every EDL consumer**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_match_grade.py tests/lib/test_matchgrade.py tests/lib/test_preflight.py tests/lib/test_draft.py -q`
Expected: PASS. `to_dict` gained a key, so any test asserting a whole EDL dict needs
the `"variety": None` entry added.

- [x] **Step 8: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py tests/
git commit -m "feat(edl): EDL.variety carrier + the Variety markdown section"
```

---

## Task 5: `edit_plan` counts both sides, gates, and takes `--spec`

Design §7, §8, §10. `build_edl` measures (never refuses); `write_edit_plan` applies the
policy and returns the same stop shape `preflight` already returns.

**Files:**
- Modify: `scripts/edit_plan.py`
- Test: `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: `footage.delivered_shot`, `footage.SHOT_TYPES`, `moodpreset.resolve`, `moodpreset.evaluate`, `spec.Spec.from_json`, `ProjectConfig.canvas`.
- Produces: `build_edl(footage, selection, pacing=None, cast=None, *, aspect=None, preset=None) -> EDL` (attaches `EDL.variety` when **both** `aspect` and `preset` are given); `write_edit_plan(footage_path, selection_path, project_path, out_dir, pacing_path=None, cast=None, spec=None) -> dict`; CLI flag `--spec`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`. The helpers below build a footage set that
offers close windows the selection ignores; adapt the construction to whatever
factory the file already uses for `Footage`/`FootageClip`.

```python
def _varied_footage():
    """One clip: 3 close windows (a subject filling the frame) + 6 wide ones."""
    close = [footage.FootageWindow(start=float(i), dur=1.0, shot_type="close", people=1,
                                   motion=0.2, shake=0.0, subject_w=0.8, subject_h=0.8,
                                   present=1.0) for i in range(3)]
    wide = [footage.FootageWindow(start=float(3 + i), dur=1.0, shot_type="wide", people=1,
                                  motion=0.3, shake=0.0, subject_w=0.02, subject_h=0.05,
                                  present=1.0) for i in range(6)]
    clip = footage.FootageClip(source="a.mp4", dur=20.0, res=(3840, 2160), fps=30.0,
                               windows=close + wide)
    return footage.Footage(clips=[clip])


def _wide_only_selection():
    return {"episodes": [{"source": "a.mp4", "window": 3 + i, "composition": "center",
                          "grid": "thirds"} for i in range(3)]}


def test_build_edl_counts_both_censuses_in_delivered_geometry():
    edl = edit_plan.build_edl(_varied_footage(), _wide_only_selection(),
                              aspect=(9, 16), preset=moodpreset.resolve("fun"))
    assert edl.variety.available["close"] == 3
    assert edl.variety.used == {"close": 0, "medium": 0, "wide": 3}
    assert edl.variety.gaps == ("close",)


def test_build_edl_skips_the_evaluation_without_an_aspect_or_preset():
    # the SP1 boundary: no project geometry, no report — not a silent pass
    edl = edit_plan.build_edl(_varied_footage(), _wide_only_selection())
    assert edl.variety is None


def test_build_edl_reads_the_waiver_from_the_selection():
    sel = {**_wide_only_selection(), "variety_waiver": "the close windows are all soft"}
    edl = edit_plan.build_edl(_varied_footage(), sel, aspect=(9, 16),
                              preset=moodpreset.resolve("fun"))
    assert edl.variety.waiver == "the close windows are all soft"
    assert edl.variety.ok is True


def test_build_edl_refuses_a_blank_waiver():
    sel = {**_wide_only_selection(), "variety_waiver": "   "}
    with pytest.raises(ValueError, match="waiver"):
        edit_plan.build_edl(_varied_footage(), sel, aspect=(9, 16),
                            preset=moodpreset.resolve("fun"))


def test_write_edit_plan_stops_on_a_variety_gap_and_names_candidates(tmp_path, ...):
    # build FOOTAGE.json from _varied_footage(), selection.json from
    # _wide_only_selection(), and a 9:16 project.json using this file's existing
    # project fixture helper
    result = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert result["finding"]["reason"] == "variety-gap"
    problems = " ".join(result["finding"]["problems"])
    assert "close" in problems and "a.mp4 #0" in problems and "variety_waiver" in problems
    assert not (tmp_path / "EDL.json").exists()      # nothing lands on a stop


def test_write_edit_plan_passes_with_a_waiver(tmp_path, ...):
    # same fixtures, selection.json carrying "variety_waiver": "close windows are soft"
    result = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert result["status"] == "written"
    written = json.loads((tmp_path / "EDL.json").read_text())
    assert written["variety"]["waiver"] == "close windows are soft"
    assert written["variety"]["gaps"] == ["close"]


def test_write_edit_plan_without_a_spec_uses_balanced(tmp_path, ...):
    # no --spec: the gate stays live, so the same wide-only selection still stops
    result = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert result["finding"]["reason"] == "variety-gap"
    assert "balanced" in " ".join(result["finding"]["problems"])
```

Replace each `...` and `fp`/`sp`/`pp` with the concrete `tmp_path` writes the file
already uses for its other `write_edit_plan` tests — do not invent a new fixture style.

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "variety or census or waiver or spec" -v`
Expected: FAIL — `TypeError: build_edl() got an unexpected keyword argument 'aspect'`

- [x] **Step 3: Add the census helpers to `scripts/edit_plan.py`**

Extend the imports:

```python
from scripts.lib import gridfit, moodpreset
from scripts.lib.footage import Footage, FootageClip, FootageWindow, SHOT_TYPES, delivered_shot
from scripts.lib.moodpreset import MoodPreset
from scripts.lib.spec import Spec
```

and add, above `build_edl`:

```python
def _available_census(footage: Footage, aspect: tuple[int, int]) -> dict[str, int]:
    """Every window the footage offers, bucketed in DELIVERED geometry (design §6).

    Every window, never only the `best` ones: `best` is a threshold on a score whose
    ordering leans toward motion (design §1.1), and a denominator drawn from it would
    inherit the very lean this gate exists to correct. Windows the phash cull removed
    are already absent from FOOTAGE.json, so they are correctly outside the pool."""
    counts = {s: 0 for s in SHOT_TYPES}
    for clip in footage.clips:
        for w in clip.windows:
            counts[delivered_shot(w.subject_w, w.subject_h, clip.res, aspect)] += 1
    return counts


def _candidates(footage: Footage, aspect: tuple[int, int], want: str,
                limit: int = 3) -> list[tuple[str, int, float]]:
    """The strongest unused-size windows, as (source, window index, score), so a
    refusal names a mechanical fix instead of an abstract complaint."""
    rows = [(clip.source, i, w.score)
            for clip in footage.clips
            for i, w in enumerate(clip.windows)
            if delivered_shot(w.subject_w, w.subject_h, clip.res, aspect) == want]
    return sorted(rows, key=lambda r: r[2], reverse=True)[:limit]
```

- [x] **Step 4: Measure inside `build_edl`**

Change the signature and add the `used` tally inside the projection loop — the count
has to happen there, because after projection an episode carries no window index and
its `shot_type` may have been editorially overridden:

```python
def build_edl(footage: Footage, selection: dict, pacing: Spine | None = None,
              cast: str | None = None, *, aspect: tuple[int, int] | None = None,
              preset: MoodPreset | None = None) -> EDL:
```

Inside the loop, right after `fw = _resolve_window(clip, window, source, k)`:

```python
        if aspect is not None:
            used[delivered_shot(fw.subject_w, fw.subject_h, clip.res, aspect)] += 1
```

with `used = {s: 0 for s in SHOT_TYPES}` initialised beside `episodes`. Then, just
before the `return EDL(...)`:

```python
    variety = None
    if aspect is not None and preset is not None:
        asl = (sum(e.dur for e in episodes) / len(episodes)) if episodes else 0.0
        variety = moodpreset.evaluate(_available_census(footage, aspect), used, asl,
                                      preset, waiver=selection.get("variety_waiver"))
```

and pass `variety=variety` to the `EDL(...)` constructor. `build_edl` MEASURES; it
never refuses on a gap — the policy lives one level up, so the report reaches the
caller either way.

Extend the docstring with one paragraph naming the new keywords and stating that a
missing `aspect`/`preset` means "not evaluated", not "passed".

- [x] **Step 5: Apply the policy in `write_edit_plan`**

New signature: `def write_edit_plan(footage_path, selection_path, project_path, out_dir, pacing_path=None, cast=None, spec=None) -> dict:`

After `cfg = ProjectConfig.from_json(project_path)`:

```python
    preset = moodpreset.resolve(Spec.from_json(spec).mood if spec else None)
    if preset.name == "balanced":
        _log(f"variety: no SPEC mood matched a preset — using the 'balanced' shot mix "
             f"{preset.shot_mix} (a skipped brief must not disable the gate)")
```

Pass the geometry into the build:

```python
    edl = build_edl(footage, selection, pacing=pacing, cast=cast,
                    aspect=tuple(cfg.canvas), preset=preset)
```

and, after the build and before `preflight`:

```python
    v = edl.variety
    _log("variety: preset {} — footage offers {}".format(
        v.preset, ", ".join(f"{s} {v.available[s]}" for s in SHOT_TYPES)))
    if not v.ok:
        problems = []
        for s in v.gaps:
            cands = ", ".join(f"{src} #{i} (score {sc:.2f})"
                              for src, i, sc in _candidates(footage, tuple(cfg.canvas), s))
            problems.append(
                f"preset {v.preset!r} wants {s} (target {preset.shot_mix[s]:.0%}) and the "
                f"footage offers {v.available[s]} {s} windows in the delivered frame, but "
                f"the cut uses 0. Candidates: {cands}. Add one, or state why the cut stays "
                f'as it is in selection.json: "variety_waiver": "<reason>"')
        return {"status": "stop_and_report",
                "finding": {"reason": "variety-gap", "episode_idx": None,
                            "problems": problems}}
```

The stop shape is `preflight`'s exactly, so `main()`'s `SystemExit(0 if status ==
"written" else 1)` already gives the right exit code, and nothing is written on a stop —
the same "a bad EDL never lands as a half-valid artifact" rule the preflight follows.

- [x] **Step 6: Add the CLI flag**

In `main()`, beside `--cast`:

```python
    b.add_argument("--spec", help="SPEC.json — its mood picks the shot-mix preset "
                                  "(optional; without it the 'balanced' preset applies)")
```

and thread it: `result = write_edit_plan(a.footage, a.selection, a.project, a.out_dir, a.pacing, cast=a.cast, spec=a.spec)`.

- [x] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q`
Expected: PASS

- [x] **Step 8: Run the whole unit suite**

Run: `.venv/bin/python -m pytest tests/lib -q`
Expected: PASS. Existing fixtures build all-`wide` windows (`subject_w`/`subject_h`
default to `0.0`), so `available["close"]` is `0`, no gap can fire, and no existing
test changes behaviour — confirm that is why they pass rather than assuming it.

- [x] **Step 9: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat(edit-plan): variety census + the variety-gap gate + --spec"
```

---

## Task 6: The end-to-end proof

Design §12. The unit tests prove the decision core; this proves the artifact — that a
real `edit_plan build` invocation stops, that a waiver gets it moving, and that the
block survives the round trip into `EDL.json` and `EDL.md`.

**Files:**
- Modify: `tests/integration/test_edit_plan.py`

**Interfaces:**
- Consumes: everything from Tasks 0–5.
- Produces: no production code.

- [x] **Step 1: Write the failing tests**

Append to `tests/integration/test_edit_plan.py`, following that file's existing
fixture style (it already writes a `FOOTAGE.json`, a `selection.json` and a
`project.json` into `tmp_path` and calls `edit_plan.write_edit_plan`):

```python
def test_sp3_stops_on_a_variety_gap_then_passes_with_a_waiver(tmp_path):
    """A cut that ignores every close window the footage offers is refused; the same
    cut with a stated reason is written, and the reason lands INSIDE the stamped
    EDL.json where it cannot be quietly revised (design §8)."""
    # FOOTAGE.json: 3 close windows (subject_w/h 0.8) + 6 wide (0.02/0.05), res 3840x2160
    # selection.json: the 3 wide windows only; project.json: 9:16
    stop = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "variety-gap"
    assert not (tmp_path / "EDL.json").exists()

    sp.write_text(json.dumps({**selection, "variety_waiver": "close windows are out of focus"}))
    ok = edit_plan.write_edit_plan(str(fp), str(sp), str(pp), str(tmp_path))
    assert ok["status"] == "written"

    edl = EDL.from_json(tmp_path / "EDL.json")        # provenance check passes
    assert edl.variety.gaps == ("close",)
    assert edl.variety.waiver == "close windows are out of focus"
    assert "## Variety" in (tmp_path / "EDL.md").read_text()


def test_sp3_delivered_geometry_is_what_decides(tmp_path):
    """The SAME footage passes 16:9 and stops 9:16 — proof the gate reads the crop,
    not the source frame. A subject at 3% of the source frame is `wide` in source
    geometry and `medium` once a 9:16 crop is taken (design §6)."""
    # windows with subject_w=0.1, subject_h=0.3 (area 0.030) + a selection using
    # only the clip's other, genuinely wide windows
    wide_canvas = edit_plan.write_edit_plan(str(fp), str(sp), str(pp_16x9), str(tmp_path))
    assert wide_canvas["status"] == "written"          # nothing but wide exists at 16:9
    tall = edit_plan.write_edit_plan(str(fp), str(sp), str(pp_9x16), str(tmp_path / "b"))
    assert tall["finding"]["reason"] == "variety-gap"  # the same windows read `medium`
```

Fill in `fp`/`sp`/`pp` with concrete `tmp_path` writes. The second test needs the
preset to want `medium` at or above `WANT_FLOOR` — `balanced` wants `0.40`, so no
`--spec` is needed.

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_edit_plan.py -k variety -v`
Expected: FAIL (the tests do not exist / the fixtures are unfinished)

- [x] **Step 3: Complete the fixtures until both tests pass**

No production code should be needed. If either test needs a production change to pass,
stop: that is a design gap, and it belongs in a report rather than in an ad-hoc patch.

Run: `.venv/bin/python -m pytest tests/integration/test_edit_plan.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_edit_plan.py
git commit -m "test(edit-plan): end-to-end variety-gap refusal, waiver, and delivered-geometry proof"
```

---

## Task 7: Mutation battery, skills, docs

Design §12 (the five mutation checks are steps, not suggestions) and §10.

**Files:**
- Modify: `skills/edit-plan/SKILL.md`, `skills/using-montage/SKILL.md`
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/fixes-backlog.md`, `docs/cinematic-quality-playbook.md`
- Test: no new file — this task proves the existing ones bite

- [x] **Step 1: Run the five mutation checks**

Each mutation must turn at least one test **red**. Apply it, run the suite, record
which test caught it, then revert. If a mutation stays green, the battery has found a
missing test — write it before moving on.

1. In `_available_census`, filter to `if w.best` — expected red: the census tests in `tests/lib/test_edit_plan.py`.
2. In `_available_census`/`_candidates`/`build_edl`, replace `delivered_shot(...)` with `w.shot_type` — expected red: `test_sp3_delivered_geometry_is_what_decides`.
3. In `VarietyReport.__post_init__`, drop the blank-waiver refusal — expected red: `test_a_blank_waiver_is_refused`.
4. In `_available_census`, count `w.dur` instead of `1` — expected red: the census assertion pinning `available["close"] == 3`.
5. Add `BALANCED` to `PRESETS` — expected red: `test_balanced_is_never_a_match_target`, and at least one `resolve` case.

- [x] **Step 2: Record the battery in the plan**

Append the five results to this file under a `## Mutation battery results` heading —
mutation, the test that caught it, and (if any) the test written to close a gap.

- [x] **Step 3: Update `skills/edit-plan/SKILL.md`**

Three edits:

- **Inputs:** add `SPEC.md` / `SPEC.json` to the list of soft inputs with a note that its mood picks the shot-mix preset, and that without one the `balanced` preset applies.
- **Procedure step 2:** after the paragraph beginning "The ranking is not the answer", add:

  > **Variety is an objective, not a preference.** The build refuses a cut that uses
  > *zero* of a shot size the mood's preset wants when the footage offers three or
  > more windows of it — the reason is `variety-gap` and it names candidate windows
  > by clip and index. Shot size is judged in the **delivered** frame, so a window
  > tagged `wide` in `FOOTAGE.md` may well be `medium` once the 9:16 crop is taken;
  > trust the refusal's numbers over the tag. If the cut is genuinely right as it
  > stands — every close window is soft, or the reel is deliberately one texture —
  > state why in `selection.json`:
  >
  >     {"episodes": [...], "variety_waiver": "every close window is out of focus"}
  >
  > The reason is printed in `EDL.md` and stamped into `EDL.json`. A blank waiver is
  > refused.

- **Procedure step 3:** add `[--spec SPEC.json]` to the build command and one line saying it selects the preset.

- [x] **Step 4: Update `skills/using-montage/SKILL.md`**

Where the router invokes the edit-plan build, add `--spec SPEC.json` when a brief
exists, and one sentence: a `variety-gap` stop routes back to edit-plan like any other
`stop_and_report`, never to a loosened gate.

- [x] **Step 5: Update the docs**

- `docs/build-status.md`: a **Done** entry for this slice (what shipped, the `CACHE_VERSION` 6→7 cost and why it was paid now, the §13 honest limits in one sentence, the mutation battery result), and rewrite the **Next action** head so it names what is left of P3 — S3 (`_motion_fit` re-tune, now free), the hero-conditioned re-scan, #14 rule memory, #3 per-episode QC.
- `docs/pipeline-map.md`: note the gate on the edit-plan (5.7) row.
- `CLAUDE.md`: two Quick Reference rows — the design and this plan — in the established one-line style.
- `docs/fixes-backlog.md`: mark **#19** landed with the design/plan paths, and state plainly what it does not cover (limits §13.1, §13.2, §13.5, §13.6).
- `docs/cinematic-quality-playbook.md` §4: mark the mood-preset spine + #19 as landed under priority 3, leaving #3 and #14 open.

- [x] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS with no skips beyond the ones the tree already had (record the exact
counts in the commit message).

- [x] **Step 7: Commit**

```bash
git add skills/ docs/ CLAUDE.md
git commit -m "docs(mood-preset-variety): skills, registry, backlog #19, build status"
```

---

## Self-review notes

- **Spec coverage:** §4 → Task 2; §5 → Task 1; §6 → Task 0; §7 → Tasks 3 and 5; §8 → Tasks 3 and 5; §9 → Task 4; §10 → Tasks 5 and 7; §11 failure modes → Task 1 (legacy artifact), Task 2 (no-match log, broken table), Task 3 (`MIN_AVAIL`, blank waiver), Task 5 (no `SPEC.json`), Task 4 (`variety=None` for the SP1 door); §12 → Tasks 0–7; §13 honest limits → recorded in Task 7's docs; §14 deferrals → no task, by design.
- **`Footage` with no windows at all** (§11): `_available_census` returns zeros, `evaluate` finds no gap, the report is still written. Covered by the existing all-`wide` fixtures continuing to pass in Task 5 Step 8 rather than by a dedicated test — if the reviewer wants it pinned explicitly, add `test_evaluate_on_empty_footage` beside the Task 3 cases.
- **Type consistency:** `subject_w`/`subject_h`/`present` are used with those exact names in Tasks 0, 1, 5 and 6; `delivered_shot(subject_w, subject_h, res, aspect, crop_scale=1.0)` has one signature throughout; `VarietyReport` field names match between Tasks 3, 4 and 5; the reason string is `variety-gap` in Tasks 5, 6 and 7.

---

## Mutation battery results

Run 2026-08-06, Task 7 Step 1. Protocol: apply the edit directly in the working tree,
run the targeted tests, record what failed, `git checkout -- <file>` before the next
mutation. Every mutation was reverted; none was committed. Six mutations run, not
five — Task 7's brief adds a sixth (the `WANT_FLOOR` boundary) on the strength of a
Task-3 reviewer finding that no shipped test pinned it exactly.

| # | Mutation | Predicted catch | Actual result |
|---|----------|------------------|----------------|
| 1 | `_available_census`: filter to `if w.best` | "the census tests in `tests/lib/test_edit_plan.py`" | **RED**, as predicted, and wider: 6 tests failed — `test_build_edl_counts_both_censuses_in_delivered_geometry` plus `test_write_edit_plan_stops_on_a_variety_gap_and_names_candidates`, `test_write_edit_plan_passes_with_a_waiver`, `test_write_edit_plan_without_a_spec_uses_balanced` (all `tests/lib/test_edit_plan.py`), and both variety tests in `tests/integration/test_edit_plan.py`. None of the fixtures mark any window `best=True`, so the filter zeroes `available` entirely. |
| 2 | `_available_census`/`_candidates`/`build_edl`: `delivered_shot(...)` → `w.shot_type` | `test_sp3_delivered_geometry_is_what_decides` | **RED**, exactly and only that test (73 others stayed green). Every other fixture's hand-set `shot_type` tag already agrees with what `delivered_shot` computes for its subject fractions — only this test's fixture is deliberately built so source and delivered geometry disagree, which is the one case the mutation can be caught by. |
| 3 | `VarietyReport.__post_init__`: drop the blank-waiver refusal | `test_a_blank_waiver_is_refused` | **RED** — all 3 parametrized cases (`""`, `"   "`, `"\n"`), plus `test_build_edl_refuses_a_blank_waiver` in `tests/lib/test_edit_plan.py` as a bonus catch. |
| 4 | `_available_census`: count `w.dur` instead of `1` | "the census assertion pinning `available["close"] == 3`" (`test_build_edl_counts_both_censuses_in_delivered_geometry`) | **The predicted test stayed GREEN.** `_varied_footage()`'s three close windows all carry `dur=1.0`, so `sum(dur) == count(windows) == 3.0`, and `evaluate` casts through `int()` before the assertion ever sees a fraction — counting seconds and counting windows are numerically indistinguishable on that fixture. The mutation was *not* silent overall — it turned two **integration** tests red as a side effect (`test_sp3_stops_on_a_variety_gap_then_passes_with_a_waiver`, `test_sp3_delivered_geometry_is_what_decides`: their `dur=0.5` fixtures truncate `int(1.5) = 1 < MIN_AVAIL`, so the gate stops firing) — but the one test whose whole job is to pin this census had a blind spot. **Closed:** added `test_available_census_counts_windows_not_seconds` to `tests/lib/test_edit_plan.py`, with three close windows at non-uniform durations 2.0/3.25/4.5s (`sum = 9.75`, `int() = 9`, window-count `= 3`) so the two strategies diverge; confirmed RED under the mutation, green without it. |
| 5 | `PRESETS = PRESETS + (BALANCED,)` (BALANCED enters the nearest-neighbour search) | `test_balanced_is_never_a_match_target`, "and at least one `resolve` case" | **RED**, broadly — `test_balanced_is_never_a_match_target` (first assert: `BALANCED not in PRESETS`) plus all 4 `test_resolve_picks_the_nearest_named_preset` cases and 9 more cascading failures (14 total), because `mood.distance(None, target)` raises `AttributeError` the moment `min(PRESETS, ...)` evaluates `BALANCED.anchor` against any real target. |
| 6 (added per Task 7 brief, not in the design's original five) | `evaluate`: `preset.shot_mix[s] >= WANT_FLOOR` → `> WANT_FLOOR` | Predicted to stay green (Task-3 reviewer finding) | **Confirmed GREEN** — all 100 tests in the three variety-relevant files passed with the mutation live; the nearest existing case (`test_evaluate_ignores_a_size_the_preset_barely_wants`) pins `0.10`, well below the floor, never the boundary itself. **Closed:** added `test_evaluate_fires_exactly_at_the_want_floor_boundary` (`shot_mix["close"] = 0.20` → gap fires) and its twin `test_evaluate_is_silent_just_below_the_want_floor_boundary` (`0.19` → no gap) to `tests/lib/test_moodpreset.py`; confirmed the first goes RED under the mutation, both green without it. |

**Net finding:** the battery caught two real coverage gaps beyond the one it was sent
to find (#6) — #4's dedicated census test was coincidentally correct only because
every fixture window happens to carry `dur=1.0`. Both gaps are closed with new tests;
no production code changed (every mutation was reverted, `git diff --stat scripts/`
is empty at the end of this task).
