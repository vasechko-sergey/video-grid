# Unmeasured, Named — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two reports stop claiming a measurement they never made — the window
scorer publishes what each of its three terms actually separated, and the variety
census publishes how many of its windows carried no detected subject.

**Architecture:** Two additive contract fields (`Footage.scoring`,
`VarietyReport.unmeasured`), one normalisation fix (`present` becomes a
percentile rank like the other two blend terms), and the rendering that makes
both legible in `FOOTAGE.md` and `EDL.md`. No new stage, no new flag, no
`CACHE_VERSION` bump, no re-scan.

**Tech Stack:** Python 3, stdlib + numpy (already present), pytest.

**Design:** [docs/specs/2026-09-10-unmeasured-named-design.md](../specs/2026-09-10-unmeasured-named-design.md)
— read §0 before Task 1. Section references below (§0.2, §3.1, §4.1 …) point there.

---

## Global Constraints

These bind **every** task and every subagent working on this plan.

**Environment**

- Python is `.venv/bin/python`. Scripts run as modules (`pythonpath = .` in
  `pytest.ini`): `.venv/bin/python -m scripts.intake`, never
  `python scripts/intake.py`.
- **Do NOT install anything.** No `brew`, `pip install`, `apt`, `npm`, `uv`, and
  do NOT run `setup.sh`. The runtime is already provisioned. If something appears
  missing, report it — do not fix it by installing.
- **Never read from or write to `/Users/serg/Downloads/untitled folder/`.** It
  holds the only real run. It is out of scope for every task in this plan.

**Git**

- Commit at the end of each task, with the message the task gives. Do not push.
- **Do NOT use `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** They discard uncommitted work that is not yours. To restore a
  file you mutated deliberately: for content that is committed, use
  `git show HEAD:<path> > <path>`; for a file that is **not** committed, save your
  own copy first with `cp <path> <path>.bak` **before** you mutate it, and restore
  from that copy.
- Add named paths (`git add scripts/lib/footage.py tests/lib/test_footage.py`).
  Never `git add -A`.

**Testing**

- Run the tests each task names, and paste the real terminal output into your
  report. Never describe a result you did not run.
- **Mutation checks run under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit can
  match the previous file's size and mtime-second, and CPython then serves the
  stale `.pyc` — a mutation that silently does not apply reads exactly like a
  non-discriminating test.
- **zsh does not word-split an unquoted variable.** A test selection built in a
  shell variable arrives as ONE argument and pytest prints `no tests ran` — which
  also reads exactly like a non-discriminating row. Write selections out literally.

**Code**

- Follow [docs/coding-standards.md](../coding-standards.md): imports at top,
  typed signatures, fail-loud `ValueError` with a remedy in the message.
- A new contract field is validated in `__post_init__`, round-trips through
  `to_dict`/`from_dict`, and reads back as its documented default on an artifact
  written before this slice.

---

## File Structure

| File | Change |
|---|---|
| `scripts/lib/footage.py` | `SCORE_TERMS`; `Footage.scoring` field + validation + round-trip + one `to_markdown` paragraph |
| `scripts/intake.py` | `_separated()`; `score_pool` ranks `present` and returns the report; `intake()` passes it into `Footage` |
| `scripts/lib/moodpreset.py` | `VarietyReport.unmeasured` field + validation + round-trip; `evaluate(unmeasured=)` |
| `scripts/edit_plan.py` | `_available_census` returns `(counts, unmeasured)`; the `evaluate` call; the gate's log line |
| `scripts/lib/edl.py` | `EDL.md`'s Variety section renders the unmeasured sentence |
| `tests/lib/test_footage.py` | `Footage.scoring` contract tests |
| `tests/lib/test_intake.py` | `_separated` + `score_pool` report tests |
| `tests/lib/test_moodpreset.py` | `VarietyReport.unmeasured` contract tests |
| `tests/lib/test_edit_plan.py` | `_available_census` returns `(counts, unmeasured)` |
| `tests/lib/test_edl.py` | `EDL.md` names the unmeasured windows, and stays silent at zero |
| `tests/integration/test_unmeasured_named.py` | the two end-to-end proofs, each with a control |
| `CHANGELOG.md`, `.claude-plugin/plugin.json` | 0.9.0 → 0.9.1 |
| `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`, `CLAUDE.md` | queue + registry sync |

---

### Task 1: `Footage.scoring` — the contract field

**Files:**
- Modify: `scripts/lib/footage.py`
- Test: `tests/lib/test_footage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_footage.py`:

```python
def test_footage_scoring_round_trips_and_defaults_to_none():
    f = footage.Footage(clips=[], scoring={"windows": 4,
                                           "separated": {"present": 0, "motion": 3, "shake": 4}})
    back = footage.Footage.from_dict(f.to_dict())
    assert back.scoring == {"windows": 4,
                            "separated": {"present": 0, "motion": 3, "shake": 4}}
    # an artifact written before 2026-09-10 carries no key at all
    assert footage.Footage.from_dict({"clips": []}).scoring is None


def test_footage_scoring_refuses_a_term_outside_the_vocabulary():
    with pytest.raises(ValueError, match="one count per"):
        footage.Footage(clips=[], scoring={"windows": 2,
                                           "separated": {"present": 1, "motion": 1}})


def test_footage_scoring_refuses_separating_more_windows_than_the_pool_holds():
    with pytest.raises(ValueError, match="cannot separate more windows"):
        footage.Footage(clips=[], scoring={"windows": 2,
                                           "separated": {"present": 0, "motion": 3, "shake": 1}})


def test_footage_scoring_refuses_a_non_dict():
    with pytest.raises(ValueError, match="Footage.scoring must be"):
        footage.Footage(clips=[], scoring=[1, 2, 3])


def test_footage_markdown_names_a_term_that_separated_nothing():
    f = footage.Footage(clips=[], scoring={"windows": 1508,
                                           "separated": {"present": 3, "motion": 1429,
                                                         "shake": 1458}})
    md = f.to_markdown()
    assert "**present** 3/1508" in md
    assert "separated" in md


def test_footage_markdown_says_nothing_about_scoring_on_an_older_artifact():
    assert "separated" not in footage.Footage(clips=[]).to_markdown()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_footage.py -k "scoring or separated" -q
```

Expected: FAIL — `Footage.__init__() got an unexpected keyword argument 'scoring'`.

- [ ] **Step 3: Add the vocabulary constant**

In `scripts/lib/footage.py`, beside `SHOT_TYPES` (which is at line 29):

```python
SHOT_TYPES = ("close", "medium", "wide")
CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08     # subject-area fractions bounding the three tags

# The three terms intake's window score blends, in the order they are reported.
# Lives here rather than in intake.py because it is an ON-DISK vocabulary: Footage
# validates a FOOTAGE.json against it, and lib may not import a driver (the same
# reason SHOT_TYPES lives here and moodpreset imports it).
SCORE_TERMS = ("present", "motion", "shake")
```

- [ ] **Step 4: Add the field and its validation**

In `scripts/lib/footage.py`, the `Footage` dataclass (line 245):

```python
@dataclass
class Footage:
    clips: list[FootageClip] = field(default_factory=list)
    band: tuple | None = None        # (win_min, win_max) this scan carved with
    scoring: dict | None = None      # what each score term separated (design 2026-09-10 §4)
```

At the END of `Footage.__post_init__`, after the existing `band` block:

```python
        if self.scoring is not None:
            s = self.scoring
            if not isinstance(s, dict) or set(s) != {"windows", "separated"}:
                raise ValueError(
                    f"Footage.scoring must be {{'windows': int, 'separated': {{term: int}}}}, "
                    f"or null on an artifact written before 2026-09-10. Got {s!r} — re-run "
                    f"footage-intake to regenerate FOOTAGE.json")
            n = s["windows"]
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise ValueError(f"Footage.scoring['windows'] must be an int >= 0, got {n!r}")
            sep = s["separated"]
            if not isinstance(sep, dict) or set(sep) != set(SCORE_TERMS):
                raise ValueError(
                    f"Footage.scoring['separated'] must carry one count per {SCORE_TERMS}, "
                    f"got {sep!r}")
            for k in SCORE_TERMS:
                v = sep[k]
                if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= n:
                    raise ValueError(
                        f"Footage.scoring['separated'][{k!r}] must be an int in [0, {n}] — a "
                        f"term cannot separate more windows than the pool holds; got {v!r}")
            self.scoring = {"windows": n, "separated": {k: int(sep[k]) for k in SCORE_TERMS}}
```

- [ ] **Step 5: Round-trip it**

`Footage.from_dict`'s return (currently `return cls(clips=clips, band=d.get("band"))`):

```python
        return cls(clips=clips, band=d.get("band"), scoring=d.get("scoring"))
```

`Footage.to_dict`:

```python
    def to_dict(self) -> dict:
        return {"clips": [c.to_dict() for c in self.clips],
                "band": None if self.band is None else list(self.band),
                "scoring": None if self.scoring is None else {
                    "windows": self.scoring["windows"],
                    "separated": dict(self.scoring["separated"])}}
```

- [ ] **Step 6: Render it in FOOTAGE.md**

In `Footage.to_markdown`, immediately after the existing header `lines = [...]`
block (the one ending `"never comparable to another shoot's numbers. …", ""`) and
**before** the `for c in self.clips:` loop:

```python
        if self.scoring is not None:
            n, sep = self.scoring["windows"], self.scoring["separated"]
            lines += ["Each blend term's `separated` count is how many of those windows it "
                      "told apart. A term near zero contributed nothing to THIS pool's "
                      "ordering — it is not a quality signal here, whatever its weight "
                      "(design 2026-09-10 §4): "
                      + ", ".join(f"**{t}** {sep[t]}/{n}" for t in SCORE_TERMS) + ".", ""]
```

- [ ] **Step 7: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_footage.py -q
```

Expected: PASS, and no pre-existing `test_footage.py` test fails.

- [ ] **Step 8: Prove nothing else read the old shape**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_intake_cache.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/footage.py tests/lib/test_footage.py
git commit -m "feat(footage): Footage.scoring carries what each score term separated

An additive report field, null on any FOOTAGE.json written before this slice.
SCORE_TERMS lives in footage.py because it is an on-disk vocabulary that Footage
validates against, and lib may not import a driver."
```

---

### Task 2: `score_pool` ranks presence and reports separation

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

**Interface from Task 1:** `footage.SCORE_TERMS == ("present", "motion", "shake")`,
and `Footage.scoring` validates `{"windows": int, "separated": {term: int}}` with
each count in `[0, windows]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_intake.py`. `_w` and `_clip` already exist in that file
(`_w` at line ~75 builds a `FootageWindow`); use them.

```python
def test_separated_is_the_pool_minus_its_largest_tie_group():
    assert intake._separated([]) == 0
    assert intake._separated([0.5, 0.5, 0.5, 0.5]) == 0        # one tie group: nothing told apart
    assert intake._separated([0.0, 1.0]) == 1                   # two groups of one
    assert intake._separated([0.5, 0.5, 0.5, 0.9]) == 1         # the outlier alone


def test_score_pool_reports_a_presence_term_that_separated_nothing():
    # every window holds people for its whole span — the 2026-06 run's shape (99.8%)
    ws = [_w(dur=2.0, people=1, motion=m, shake=0.0, present=1.0)
          for m in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)]
    rep = intake.score_pool([_clip("a.mp4", ws)])
    assert rep["windows"] == 6
    assert rep["separated"]["present"] == 0
    assert rep["separated"]["motion"] == 5      # six distinct motions, largest tie 1


def test_score_pool_reports_a_presence_term_that_did_separate():
    ws = [_w(dur=2.0, people=1, motion=0.5, shake=0.0, present=p)
          for p in (0.0, 0.25, 0.5, 0.75, 1.0, 1.0)]
    rep = intake.score_pool([_clip("a.mp4", ws)])
    assert rep["separated"]["present"] == 4     # six windows, largest tie group is the two 1.0s


def test_score_pool_on_an_empty_pool_reports_zero_windows_not_none():
    # an empty pool is a MEASUREMENT (zero windows), not an absent one. Footage.scoring
    # is None only on an artifact written before this slice.
    assert intake.score_pool([]) == {"windows": 0,
                                     "separated": {"present": 0, "motion": 0, "shake": 0}}


def test_presence_is_ranked_across_the_pool_not_summed_absolutely():
    # A pool where NOBODY is present must not have 0.44 of its blend zeroed away: the
    # ranked term ties at a constant, which _percentile_rank's tie rule then makes
    # invisible to the ordering. So the ordering must be the SAME as an identical pool
    # where everybody is present (design 2026-09-10 §3.1).
    def scores(present):
        ws = [_w(dur=2.0, people=0, motion=m, shake=s, present=present)
              for m, s in ((0.1, 0.9), (0.5, 0.2), (0.9, 0.5))]
        intake.score_pool([_clip("a.mp4", ws)])
        return [w.score for w in ws]
    assert scores(0.0) == scores(1.0)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py -k "separated or presence_is_ranked or reports_a_presence or empty_pool_reports" -q
```

Expected: FAIL — `module 'scripts.intake' has no attribute '_separated'`, and the
`score_pool` calls return `None`.

- [ ] **Step 3: Import `Counter`**

`scripts/intake.py` line 12 currently reads `from collections.abc import Iterator`.
Add above it:

```python
from collections import Counter
from collections.abc import Iterator
```

- [ ] **Step 4: Add `_separated`**

In `scripts/intake.py`, immediately after `_percentile_rank`:

```python
def _separated(vec: list[float]) -> int:
    """How many windows a blend term told apart: the pool size minus its largest tie
    group. A term whose every window shares one value separated NOTHING — it shifts
    the blend by a constant, which the final `_percentile_rank` then makes invisible
    to the ordering (design 2026-09-10 §4).

    Measured on the RANKED vector the blend consumes, not the raw input: that is
    what the ordering was actually built from. `motion` ranks per-clip above
    CLIP_POOL_MIN, so two clips can land a window on the same rank by coincidence
    (every clip's top window ranks 1.0) — its count is exact for the blend and a
    LOWER BOUND on what the raw measurement distinguished (§4.1). That asymmetry is
    safe in the direction that matters: a coincidence can only merge two values,
    never split one, so an inert term cannot be inflated into looking useful.
    """
    if not vec:
        return 0
    return len(vec) - max(Counter(vec).values())
```

- [ ] **Step 5: Rank `present` and return the report**

Replace `score_pool`'s signature, the `present` sentence in its docstring, its
empty-pool early return, its blend, and its tail.

Signature:

```python
def score_pool(clips: list[footage.FootageClip]) -> dict:
```

In the docstring, the sentence currently reading

> `shake` by rank across the pool (steadiness is a camera property, so a
> within-clip comparison asks nothing); `present` absolutely, its fraction already
> meaning what it says.

becomes

> `shake` by rank across the pool (steadiness is a camera property, so a
> within-clip comparison asks nothing); `present` by rank across the pool too —
> "does this window hold the subject" is a whole-shoot comparison, and a pool where
> nobody is present then ties at a constant instead of contributing a uniform zero
> that still outweighs two ranks (design 2026-09-10 §3). It was absolute until
> 2026-09-10, which summed a raw fraction against two percentiles: on the only real
> pool that was harmless because the term was near-constant, and it separated 3
> windows of 1508 (§0.1).

Add to the end of the docstring:

> Returns the separation report `Footage.scoring` carries: how many windows each
> term told apart, so a weight that bought nothing on this pool is visible instead
> of implied by its size.

Body — the early return, the blend, and the tail:

```python
    windows = [w for c in clips for w in c.windows]
    if not windows:
        return {"windows": 0, "separated": {t: 0 for t in footage.SCORE_TERMS}}
    motion_fit = _percentile_rank([w.motion for w in windows])
    at = 0
    for c in clips:                      # a big enough clip ranks its own windows in place
        n = len(c.windows)
        if n >= CLIP_POOL_MIN:
            motion_fit[at:at + n] = _percentile_rank([w.motion for w in c.windows])
        at += n
    stability = _percentile_rank([-w.shake for w in windows])
    presence = _percentile_rank([w.present for w in windows])
    blend = [W_PRESENT * p + W_MOTION * m + W_STABLE * s
             for p, m, s in zip(presence, motion_fit, stability)]
    for w, sc, m in zip(windows, _percentile_rank(blend), motion_fit):
        w.score = round(sc, 3)
        w.description = _describe(w.people, w.shot_type, m)
    return {"windows": len(windows),
            "separated": {"present": _separated(presence),
                          "motion": _separated(motion_fit),
                          "shake": _separated(stability)}}
```

- [ ] **Step 6: Run the new tests**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py -k "separated or presence_is_ranked or reports_a_presence or empty_pool_reports" -q
```

Expected: PASS.

- [ ] **Step 7: Run the whole scorer suite and report every mover**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py -q
```

Some pre-existing tests pin `score` values built on the absolute `present` term.
For each failure: if the test's INTENT still holds under a ranked presence,
re-pin its expected numbers and say so in your report. If a test's intent
contradicts §3 (e.g. it asserts that presence contributes an absolute amount),
**stop and report it** — that is a plan/spec conflict, not a re-pin.

- [ ] **Step 8: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "fix(intake): presence joins the other two blend terms as a rank

It was an absolute fraction summed against two percentile ranks. Measured on the
only real pool the change is a no-op (Spearman 0.999, identical best set,
identical top-100) -- which is the argument for making it now: a people-free
window otherwise needs a mean rank of 0.786 across motion and shake merely to tie
the WORST window containing a person.

score_pool now returns what each term separated, so an inert weight is visible."
```

---

### Task 3: `intake()` carries the report into `Footage`

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

**Interface from Task 2:** `score_pool(clips) -> dict`, mutating `clips` in place
as before.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_intake.py`:

```python
def test_intake_builds_footage_with_the_scoring_report_through_validation():
    # The report must pass Footage.__post_init__, not be assigned onto a built object:
    # a field that skips its own validation is a field nothing checks.
    ws = [_w(dur=2.0, people=1, motion=m, shake=0.0, present=1.0) for m in (0.1, 0.9)]
    clips = [_clip("a.mp4", ws)]
    scoring = intake.score_pool(clips)
    f = footage.Footage(clips=clips, band=(1.2, 4.0), scoring=scoring)
    assert f.scoring["windows"] == 2
    assert set(f.scoring["separated"]) == set(footage.SCORE_TERMS)
```

- [ ] **Step 2: Run it**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py -k "through_validation" -q
```

Expected: PASS already (Tasks 1 and 2 supply both halves). This test pins the
CONTRACT the wiring must honour; Step 3 makes `intake()` honour it.

- [ ] **Step 3: Rewire `intake()`**

`scripts/intake.py` around line 599 currently reads:

```python
    result = footage.Footage(clips=[r.clip for r in ok], band=band)
    score_pool(result.clips)          # Phase 2: pool-relative score + description (design §4.5)
```

Replace with:

```python
    clips = [r.clip for r in ok]
    # Score BEFORE constructing Footage so `scoring` passes __post_init__ rather than
    # being assigned onto a built object (design 2026-09-10 §4.2).
    scoring = score_pool(clips)       # Phase 2: pool-relative score + description (design §4.5)
    result = footage.Footage(clips=clips, band=band, scoring=scoring)
```

- [ ] **Step 4: Prove the wiring on the real driver path**

```bash
.venv/bin/python -m pytest tests/integration/test_intake.py -q
```

Expected: PASS. If a golden `FOOTAGE.json` in that file is compared whole, it now
carries a `scoring` key — re-pin it and paste the diff into your report.

- [ ] **Step 5: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "feat(intake): the scoring report reaches FOOTAGE.json through validation

Footage is constructed AFTER score_pool so the new field passes __post_init__
instead of being assigned onto a built object."
```

---

### Task 4: `VarietyReport.unmeasured` — the contract field

**Files:**
- Modify: `scripts/lib/moodpreset.py`
- Test: `tests/lib/test_moodpreset.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_moodpreset.py`:

`_counts(close=0, medium=0, wide=0)` already exists in that file (line 57) — use
it rather than writing census dicts out by hand.

```python
def _variety(unmeasured=0):
    return moodpreset.VarietyReport(preset="fun", available=_counts(close=1, medium=1, wide=8),
                                    used=_counts(close=1, wide=1), asl=2.0, asl_band=(1.0, 3.0),
                                    unmeasured=unmeasured)


def test_variety_unmeasured_round_trips_and_defaults_to_zero():
    r = _variety(unmeasured=6)
    assert moodpreset.VarietyReport.from_dict(r.to_dict()).unmeasured == 6
    # an EDL.json written before 2026-09-10 carries no key
    d = r.to_dict()
    del d["unmeasured"]
    assert moodpreset.VarietyReport.from_dict(d).unmeasured == 0


def test_variety_unmeasured_refuses_to_exceed_the_census_it_is_a_subset_of():
    with pytest.raises(ValueError, match="exceeds the 10 windows"):
        _variety(unmeasured=11)


def test_variety_unmeasured_refuses_a_non_int():
    with pytest.raises(ValueError, match="unmeasured must be an int"):
        _variety(unmeasured=2.5)


def test_evaluate_carries_unmeasured_through_without_touching_the_gaps():
    # the gate still judges only what it COULD measure: a size below MIN_AVAIL is not a
    # gap, whether or not the census had blind windows (design 2026-09-10 §2.2).
    preset = moodpreset.resolve("fun")
    r = moodpreset.evaluate(_counts(wide=40), _counts(wide=8), 2.0, preset,
                            unmeasured=40)
    assert r.unmeasured == 40
    assert r.gaps == ()
    assert r.ok
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_moodpreset.py -k "unmeasured" -q
```

Expected: FAIL — unexpected keyword argument `unmeasured`.

- [ ] **Step 3: Add the field LAST**

In `scripts/lib/moodpreset.py`, the `VarietyReport` dataclass. The field goes
**after `waiver`**, at the end — a new field inserted among the existing
defaulted ones would silently re-bind any positional caller:

```python
    gaps: tuple[str, ...] = ()
    waiver: str | None = None
    # How many of the windows counted in `available` carried no detected subject at
    # all. They ARE in the census, tagged `wide`, and correctly so: shot size is the
    # subject's area fraction and nothing fills the frame (design 2026-09-10 §0.5).
    # The count exists because `available` is otherwise read as a description of the
    # footage — and on a shoot with no people in it, every window lands in `wide` and
    # the census states that the footage offers no close-ups about footage that may be
    # entirely close-ups (§0.2). A subset of the census, never a fourth bucket.
    unmeasured: int = 0
```

Extend the class docstring's second paragraph with one sentence:

> `unmeasured` is the census's own blind spot, not a fourth size: it counts how many
> of the SAME windows were measured against a detector that found nothing.

- [ ] **Step 4: Validate it**

At the END of `VarietyReport.__post_init__`, after the `waiver` check:

```python
        if isinstance(self.unmeasured, bool) or not isinstance(self.unmeasured, int) \
                or self.unmeasured < 0:
            raise ValueError(
                f"VarietyReport.unmeasured must be an int >= 0 (windows in `available` whose "
                f"subject was never detected), got {self.unmeasured!r} — re-run `edit_plan "
                f"build` to regenerate EDL.json")
        total = sum(self.available.values())
        if self.unmeasured > total:
            raise ValueError(
                f"VarietyReport.unmeasured {self.unmeasured} exceeds the {total} windows in "
                f"`available` — the unmeasured windows are a SUBSET of the census (counted in "
                f"it as `wide`), not a fourth bucket beside it. Re-run `edit_plan build` to "
                f"regenerate EDL.json")
```

- [ ] **Step 5: Round-trip it**

`to_dict` gains `"unmeasured": self.unmeasured`. `from_dict` gains
`unmeasured=d.get("unmeasured") or 0` — `or 0` and not `d.get("unmeasured", 0)`,
so an explicit `null` from an older writer reads as 0 rather than reaching the
type check.

- [ ] **Step 6: Thread it through `evaluate`**

```python
def evaluate(available: dict[str, int], used: dict[str, int], asl: float,
             preset: MoodPreset, waiver: str | None = None,
             unmeasured: int = 0) -> VarietyReport:
```

and the constructed report gains `unmeasured=unmeasured`. The `gaps`
comprehension is **unchanged** — the gate keeps judging only what it could
measure.

- [ ] **Step 7: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_moodpreset.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/moodpreset.py tests/lib/test_moodpreset.py
git commit -m "feat(moodpreset): VarietyReport.unmeasured names the census's blind spot

Shot size is measured from a person detector, so a window it found nobody in is
counted as `wide` -- correctly, since nothing fills the frame. The count says how
many of the census came from that silence, so `available` stops reading as a
complete description of the footage. Placed last: inserting among the defaulted
fields would re-bind a positional caller."
```

---

### Task 5: the census counts it, the log and `EDL.md` name it

**Files:**
- Modify: `scripts/edit_plan.py`, `scripts/lib/edl.py`
- Test: `tests/lib/test_edit_plan.py`

**Interface from Task 4:** `evaluate(available, used, asl, preset, waiver=None, unmeasured=0)`;
`VarietyReport.unmeasured` defaults to 0 and is a subset of `sum(available.values())`.

- [ ] **Step 1: Write the failing tests, in the two files that own them**

The census belongs to `edit_plan`; the rendering belongs to `EDL`. Both files
already carry the helpers to use — do not write new ones.

Append to `tests/lib/test_edit_plan.py` (which imports `Footage`, `FootageClip`
and `FootageWindow` at line 9 and defines `_clip(**kw)` at line 14 and
`_window(**kw)` at line 22):

```python
def test_available_census_counts_windows_with_no_detected_subject():
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.0, subject_h=0.0),
                                            _window(subject_w=0.0, subject_h=0.4),
                                            _window(subject_w=0.5, subject_h=0.6)])
    counts, unmeasured = edit_plan._available_census(Footage(clips=[clip]), (9, 16))
    assert unmeasured == 2          # (0, 0) and (0, 0.4) both have zero subject AREA
    assert sum(counts.values()) == 3


def test_available_census_reports_no_blind_windows_when_every_subject_was_found():
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.3, subject_h=0.4)])
    counts, unmeasured = edit_plan._available_census(Footage(clips=[clip]), (9, 16))
    assert unmeasured == 0
    assert sum(counts.values()) == 1
```

Append to `tests/lib/test_edl.py`, beside the existing `EDL.variety` block at
line 639. It already imports `moodpreset` and defines `_ep(**kw)` at line 20;
`EDL(episodes=(_ep(),), variety=r)` is the shape its own variety tests use:

```python
def _variety_edl(unmeasured):
    r = moodpreset.evaluate({"close": 0, "medium": 0, "wide": 9},
                            {"close": 0, "medium": 0, "wide": 3}, 2.0,
                            moodpreset.resolve("fun"), unmeasured=unmeasured)
    return EDL(episodes=(_ep(),), variety=r)


def test_edl_markdown_names_the_unmeasured_windows():
    md = _variety_edl(9).to_markdown()
    assert "9 of the 9 available windows carried no detected subject" in md


def test_edl_markdown_stays_silent_at_zero_unmeasured():
    assert "no detected subject" not in _variety_edl(0).to_markdown()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_edit_plan.py tests/lib/test_edl.py -k "unmeasured or no_detected_subject or blind_windows" -q
```

Expected: FAIL — `_available_census` returns a dict, not a pair, and `evaluate`
rejects the `unmeasured` keyword until Task 4 has landed.

- [ ] **Step 3: `_available_census` returns the pair**

In `scripts/edit_plan.py` (line 371):

```python
def _available_census(footage: Footage, aspect: tuple[int, int]) -> tuple[dict[str, int], int]:
```

Append to its docstring:

```
    Returns (counts, unmeasured). `unmeasured` is how many of those SAME windows
    carried no detected subject: intake measures subject_w/subject_h with a person
    detector, and a window it found nobody in reads (0.0, 0.0), whose delivered shot
    size is `wide` — correctly, since nothing fills the frame (design 2026-09-10
    §0.5). The count exists so `available` stops reading as a complete description
    of the footage: on a shoot with no people in it every window lands in `wide`,
    and the census would otherwise state that the footage offers no close-ups about
    footage that may be entirely close-ups (§0.2).
```

Body:

```python
    counts = {s: 0 for s in SHOT_TYPES}
    unmeasured = 0
    for clip in footage.clips:
        for w in clip.windows:
            counts[delivered_shot(w.subject_w, w.subject_h, clip.res, aspect)] += 1
            if w.subject_w * w.subject_h == 0.0:
                unmeasured += 1
    return counts, unmeasured
```

- [ ] **Step 4: Update the call site**

`scripts/edit_plan.py` around line 601:

```python
        asl = (sum(e.play_dur() for e in episodes) / len(episodes)) if episodes else 0.0
        avail, unmeasured = _available_census(footage, aspect)
        variety = moodpreset.evaluate(avail, used, asl, preset,
                                      waiver=selection.get("variety_waiver"),
                                      unmeasured=unmeasured)
```

- [ ] **Step 5: Name it in the gate's log line**

`scripts/edit_plan.py` line 761:

```python
    _log("variety: preset {} — footage offers {}{}".format(
        v.preset, ", ".join(f"{s} {v.available[s]}" for s in SHOT_TYPES),
        f" ({v.unmeasured} with no detected subject)" if v.unmeasured else ""))
```

- [ ] **Step 6: Name it in `EDL.md`**

`scripts/lib/edl.py`, the Variety block (line 462). After the
`lines += [f"| {s} | ..." for s in v.available]` row and **before** the ASL
sentence:

```python
            if v.unmeasured:
                lines += ["", f"**{v.unmeasured} of the {sum(v.available.values())} available "
                              f"windows carried no detected subject** and are counted above as "
                              f"`wide`. Shot size is the subject's share of the frame, measured "
                              f"with a person detector — so on footage without people this "
                              f"census describes what it could not see (design 2026-09-10 §2)."]
```

Rendered only when non-zero, for the reason the editorial-rules block a few lines
below already gives: a line that says nothing is worth nothing to a reader.

- [ ] **Step 7: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_edit_plan.py tests/lib/test_edl.py -q
```

Expected: PASS.

- [ ] **Step 8: Prove no other caller broke**

```bash
grep -rn "_available_census" scripts/ tests/
```

Expected: the definition, the one call site, and the new test. Any other caller
still expecting a bare dict is a bug — fix it and say so in your report.

- [ ] **Step 9: Commit**

```bash
git add scripts/edit_plan.py scripts/lib/edl.py tests/lib/test_edit_plan.py tests/lib/test_edl.py
git commit -m "feat(edit-plan): the variety census publishes its own blind spot

_available_census returns (counts, unmeasured); the gate's log line and EDL.md's
Variety section name it, and only when it is non-zero. The gaps logic is
untouched -- the gate still judges only what it could measure."
```

---

### Task 6: end-to-end proofs, each with a control

**Files:**
- Create: `tests/integration/test_unmeasured_named.py`

Neither proof decodes a frame; both drive the real functions.

- [ ] **Step 1: Write the proofs**

```python
"""The two reports say what they could not measure (design 2026-09-10).

No ffmpeg: both proofs drive the real scorer and the real edit_plan census over
constructed footage. Each carries a CONTROL that must NOT move — a report that
fires on everything is not a report."""
import json

from scripts import edit_plan, intake
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _win(present, motion=0.3, sw=0.2, sh=0.2):
    return FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=1 if present else 0,
                         motion=motion, shake=0.0, present=present,
                         subject_w=sw, subject_h=sh)


def _clip(src, wins):
    return FootageClip(source=src, dur=60.0, res=(3840, 2160), fps=30.0, windows=wins)


def test_a_pool_where_everyone_is_present_reports_presence_separated_nothing(tmp_path):
    wins = [_win(1.0, motion=m) for m in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)]
    clips = [_clip("a.mp4", wins)]
    f = Footage(clips=clips, band=(1.2, 4.0), scoring=intake.score_pool(clips))
    assert f.scoring["separated"]["present"] == 0
    assert f.scoring["separated"]["motion"] > 0
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict(), indent=2))
    # it survives the round trip a downstream stage actually performs
    assert Footage.from_json(p).scoring["separated"]["present"] == 0
    assert "**present** 0/6" in f.to_markdown()


def test_control_a_pool_where_presence_varies_reports_presence_as_working():
    wins = [_win(p, motion=0.3) for p in (0.0, 0.25, 0.5, 0.75, 1.0, 1.0)]
    clips = [_clip("a.mp4", wins)]
    scoring = intake.score_pool(clips)
    assert scoring["separated"]["present"] == 4      # largest tie is the two 1.0s
    assert "**present** 0/6" not in Footage(clips=clips, scoring=scoring).to_markdown()


def test_a_people_free_census_says_it_could_not_see():
    wins = [FootageWindow(start=float(i), dur=2.0, shot_type="wide", people=0,
                          motion=0.3, shake=0.0, present=0.0,
                          subject_w=0.0, subject_h=0.0) for i in range(9)]
    counts, unmeasured = edit_plan._available_census(Footage(clips=[_clip("a.mp4", wins)]),
                                                     (9, 16))
    assert counts == {"close": 0, "medium": 0, "wide": 9}
    assert unmeasured == 9        # every one of them: the census measured nothing


def test_control_a_people_bearing_census_reports_no_blind_windows():
    wins = [FootageWindow(start=float(i), dur=2.0, shot_type="wide", people=1,
                          motion=0.3, shake=0.0, present=1.0,
                          subject_w=0.30, subject_h=0.40) for i in range(9)]
    counts, unmeasured = edit_plan._available_census(Footage(clips=[_clip("a.mp4", wins)]),
                                                     (9, 16))
    assert unmeasured == 0
    assert counts["wide"] < 9     # the 9:16 crop widens the subject out of `wide`
```

- [ ] **Step 2: Run them**

```bash
.venv/bin/python -m pytest tests/integration/test_unmeasured_named.py -q
```

Expected: 4 passed. If the last control's `counts["wide"] < 9` does not hold,
compute the real delivered tag for `(0.30, 0.40)` at 3840x2160 → 9:16 and re-pin
the assertion to whatever discriminates a measured subject from a blind one —
then say in your report what the real tag was.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_unmeasured_named.py
git commit -m "test: both reports name their blind spot, each against a control

The controls are the load-bearing half: a pool whose presence varies must report
the term as working, and a people-bearing census must report zero blind windows.
A report that fires on everything is not a report."
```

---

### Task 7: mutation battery, version bump, docs sync

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `docs/backlog.md`,
  `docs/backlog-closed.md`, `docs/build-status.md`, `CLAUDE.md`

- [ ] **Step 1: Run the mutation battery**

Each row: apply the mutation, run the selector, confirm **RED**, then restore.

Restore route — the files are committed by now, so:
`git show HEAD:<path> > <path>`. Do NOT use `git checkout --`, `git restore`,
`git reset --hard`, or `git stash`.

Every run is prefixed `PYTHONDONTWRITEBYTECODE=1`.

| # | File | Mutation | Selector | Expect |
|---|---|---|---|---|
| 1 | `scripts/intake.py` | `_separated` returns `len(vec)` unconditionally | `tests/lib/test_intake.py -k separated_is_the_pool` | RED |
| 2 | `scripts/intake.py` | `_separated` returns `len(Counter(vec))` (distinct count, not pool-minus-tie) | `tests/lib/test_intake.py -k separated_is_the_pool` | RED |
| 3 | `scripts/intake.py` | blend uses `w.present` again instead of the ranked `p` | `tests/lib/test_intake.py -k presence_is_ranked` | RED |
| 4 | `scripts/intake.py` | `presence = _percentile_rank(...)` computed per-clip like motion | `tests/integration/test_unmeasured_named.py -k presence_separated_nothing` | RED |
| 5 | `scripts/intake.py` | `score_pool`'s empty-pool arm returns `None` | `tests/lib/test_intake.py -k empty_pool_reports` | RED |
| 6 | `scripts/intake.py` | the report's `separated` reads the RAW `[w.present ...]` instead of `presence` | `tests/lib/test_intake.py -k reports_a_presence_term_that_did_separate` | see note |
| 7 | `scripts/lib/footage.py` | `Footage.__post_init__` drops the `0 <= v <= n` bound | `tests/lib/test_footage.py -k more_windows_than_the_pool` | RED |
| 8 | `scripts/lib/footage.py` | `to_dict` omits the `scoring` key | `tests/lib/test_footage.py -k round_trips_and_defaults` | RED |
| 9 | `scripts/lib/footage.py` | `from_dict` hardcodes `scoring=None` | `tests/lib/test_footage.py -k round_trips_and_defaults` | RED |
| 10 | `scripts/lib/footage.py` | `to_markdown` renders the scoring block unconditionally (drops `is not None`) | `tests/lib/test_footage.py -k says_nothing_about_scoring` | RED |
| 11 | `scripts/lib/moodpreset.py` | drop the `unmeasured > total` refusal | `tests/lib/test_moodpreset.py -k exceed_the_census` | RED |
| 12 | `scripts/lib/moodpreset.py` | `from_dict` uses `d.get("unmeasured", 0)` and a writer emits `null` | `tests/lib/test_moodpreset.py -k round_trips_and_defaults` | see note |
| 13 | `scripts/lib/moodpreset.py` | `evaluate` drops `unmeasured=unmeasured` from the constructed report | `tests/lib/test_moodpreset.py -k carries_unmeasured_through` | RED |
| 14 | `scripts/lib/moodpreset.py` | `evaluate`'s `gaps` comprehension also skips a size when `unmeasured` is non-zero | `tests/lib/test_moodpreset.py -k carries_unmeasured_through` | see note |
| 15 | `scripts/edit_plan.py` | `_available_census` counts `subject_w == 0.0` only (drops the `* subject_h` product) | `tests/lib/test_edit_plan.py -k no_detected_subject` | RED |
| 16 | `scripts/edit_plan.py` | the call site passes `unmeasured=0` | `tests/integration/test_unmeasured_named.py` | see note |
| 17 | `scripts/lib/edl.py` | the `EDL.md` block renders unconditionally (drops `if v.unmeasured:`) | `tests/lib/test_edl.py -k stays_silent_at_zero` | RED |
| 18 | `scripts/lib/edl.py` | the block prints `v.unmeasured` where it prints the total | `tests/lib/test_edl.py -k names_the_unmeasured` | RED |

**Rows 6, 12, 14 and 16 are flagged as uncertain, not assumed RED.** Run each and
report what actually happened:

- **Row 6** may come back GREEN: ranking is a monotone map, so raw and ranked
  presence have the SAME tie structure and therefore the same `_separated` count.
  If it is green, that is a real finding — the docstring's "measured on the ranked
  vector" claim is then unobservable for `present` and observable only for
  `motion`. Add a test that discriminates it on `motion` (a two-clip pool, each
  clip at or above `CLIP_POOL_MIN`, whose raw motions are all distinct but whose
  per-clip ranks collide), or report why none can.
- **Row 12** needs the `null`-emitting writer to be part of the mutation; if the
  test does not already round-trip an explicit `null`, add one.
- **Row 14** must be RED: it is the §2.2 guarantee that the gate keeps judging
  what it could measure. If the existing test does not discriminate it, write one
  that does — a census with a real close-up gap AND non-zero `unmeasured`.
- **Row 16** has no dedicated selector yet; if the integration file does not
  exercise the driver end of the call site, say so and add the coverage rather
  than recording a pass.

Any row that will not go red is a **coverage hole**: close it with a new test in
the same task and name it in your report.

- [ ] **Step 2: Full suite**

```bash
.venv/bin/python -m pytest -q
```

Paste the real summary line. The pre-slice baseline on `main` is
`3618 passed, 1 skipped`; report the new numbers and account for the delta.

- [ ] **Step 3: Version bump — 0.9.0 → 0.9.1 (PATCH)**

The judgement, per [the versioning rule](../development-workflow.md#versioning),
which says the judgement is the point of writing down: this slice adds **no flag,
no stage, no required artifact**, and renames nothing. It adds two report fields
nothing is required to read, and corrects a blend term that was summing an
absolute fraction against two ranks — measured as a no-op on the only real pool
(design §0.3). `score` values move in their third decimal, but `score` is
documented in `FOOTAGE.md` itself as a percentile within one footage set and
"never an absolute quality bar". The driving is unchanged. **PATCH.**

Edit `.claude-plugin/plugin.json` (`"version": "0.9.1"`) and add the matching top
entry to `CHANGELOG.md` in the same commit — `tests/test_plugin_manifests.py`
asserts they agree.

- [ ] **Step 4: Backlog and registry sync**

- `docs/backlog.md`: file the **four** §7 Deferred rows (re-derive the three
  blend weights; a non-person subject sensor; make `Footage.scoring` reachable at
  the moment of need — pointing at the R4.1/R4.2 discoverability slice, not
  scattered ahead of it; the L3 colour-knob constants). Add the L1/L2 audit's
  own remaining half if it is not already there.
- `docs/backlog-closed.md`: nothing closes here — this slice opened its rows from
  an audit, it did not close a queued one. Say so rather than inventing a closure.
- `docs/build-status.md`: a Done entry naming what was measured, including the
  two overturned premises (§0.4) and the `shot_type` non-defect (§0.5).
- `CLAUDE.md`: two Quick Reference rows (design + plan), in the registry's
  existing style — one row each, describing what the slice measured, not what it
  built.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md .claude-plugin/plugin.json docs/backlog.md docs/build-status.md CLAUDE.md
git commit -m "docs: 0.9.1 — two reports name what they could not measure

PATCH: no flag, no stage, no required artifact. Two report fields nothing is
required to read, and a blend term corrected from an absolute fraction to a rank
-- measured as a no-op on the only real pool."
```
