# Named absence — a measurement survives a pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three reports stop collapsing a distinguishable absence into something
that reads as a normal reading, and stop discarding numbers they already
computed.

**Architecture:** Six additive changes, no new sensor and no new blocking gate.
`check_reel.variety` reports the global nearest-pair distance on every path;
`OutroFit` gains a `cause` so the five producers of `rung: "unchanged"` stop
writing a byte-identical record; `SPEC.length_s` becomes a first-class carrier
(`EDL.brief_len` → `ReelManifest.brief_len` → `check_reel`) feeding one new
**advisory** row; `Slot.beats_in` names the slots whose energy is `fit_spine`'s
`0.5` fallback rather than a measurement; and `pacing`'s report gains a Spearman
description of how cut length tracks music energy.

**Tech Stack:** Python 3.13, stdlib only for the new arithmetic
(`statistics.correlation(..., method="ranked")`). No new dependency. pytest.

**Design:** [docs/specs/2026-09-07-named-absence-design.md](../specs/2026-09-07-named-absence-design.md).
Read it before Task 1 — §0 carries the measurements every task's wording cites.

## Global Constraints

- **Nothing new blocks.** `ReelReport.overall` must be unable to move as a result
  of this branch. The one new check is advisory (registered in
  `models._ADVISORY_CHECKS`); every other change is report detail or a new
  optional field.
- **Every new field defaults to a value that means "not recorded", and every
  `from_dict` reads it with `.get`, never as a required key.** A `PACING.json`,
  `EDL.json` or reel manifest written before this branch must load unchanged.
  This repo's precedents: `Spine.music_digest = ""`, `OutroFit.need = 0.0`.
- **Fail-loud contract:** a malformed value raises `ValueError` naming the field,
  the bad value, and the command that regenerates the artifact. See
  [docs/coding-standards.md](../coding-standards.md).
- **Whole-object asserts** where the object is small enough to write out; see
  [docs/testing-guide.md](../testing-guide.md). A test that asserts one key of a
  dict this branch is widening will not notice the other keys regressing.
- **Imports at top of file.** No function-local imports.
- **Run pytest as a module runner from the repo root**: `pythonpath = .` is set
  in `pyproject.toml`, the interpreter is `.venv/bin/python`.
- **Every mutation battery runs under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte
  edit can match the previous file's size and mtime-second, and CPython then
  serves the stale `.pyc` — a row reads GREEN for a mutation that was never
  executed.
- **Never `git checkout --`, `git restore`, `git reset --hard` or `git stash`.**
  To undo a mutation edit to committed content use
  `git show HEAD:<path> > <path>`; when the file being mutated is NOT committed,
  save your own copy first with `cp <path> <path>.bak` and restore from that.
- **Do not install anything.** No `brew`, `pip`, `uv`, `npm`, no `setup.sh`. The
  environment is already provisioned; verification is read-only plus pytest.
- **Commit per task**, with a message body that says *why*, not only what. Never
  `git commit --amend` — a post-review fix is its own follow-up commit.

---

## File Structure

| File | Responsibility in this branch |
|---|---|
| `scripts/check_reel.py` | `variety` reports the global nearest pair; `outro`'s reason comes from the cause; the new advisory `brief_length` row |
| `scripts/lib/outro.py` | `CAUSES`, `CAUSE_WHY`, `OutroFit.cause` + validation + round-trip; `fit_outro`'s two distinct `unchanged` returns |
| `scripts/lib/edl.py` | `EDL.brief_len` + validation + round-trip; `EDL.md`'s outro clause reads `CAUSE_WHY` |
| `scripts/lib/models.py` | `ReelManifest.brief_len` + round-trip; `"brief_length"` joins `_ADVISORY_CHECKS` |
| `scripts/lib/pacing.py` | `Slot.beats_in` + validation + round-trip; `fit_spine` fills it; `to_markdown` reads it; `energy_agreement` |
| `scripts/pacing.py` | the fit report's `Energy agreement` line |
| `scripts/edit_plan.py` | `_apply_outro` sets three causes; `build_edl` sets `EDL.brief_len` |
| `scripts/edl_to_reel.py` | `brief_len` onto the manifest |
| `scripts/build_reel.py` | `brief_len` into `check_reel.run` |

Tests live beside the module they exercise:
`tests/lib/test_check_reel.py`, `tests/lib/test_outro.py`,
`tests/lib/test_edl.py`, `tests/lib/test_pacing.py`,
`tests/lib/test_edit_plan.py`, `tests/lib/test_edl_to_reel.py`,
`tests/lib/test_build_reel.py`.

---

### Task 1: `variety` reports the nearest pair on every path

**Files:**
- Modify: `scripts/check_reel.py:327-342`
- Test: `tests/lib/test_check_reel.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `checks["variety"].detail` now always carries
  `{"min_distance": int, "pair": [int, int], "min": int}` when more than one
  episode was checked. No signature changes.

**Context an implementer needs.** `_hamming` already coerces `numpy.int64` to
`int` (`check_reel.py:92`), so the values are JSON-serializable as they stand —
do not add a second cast. `spec.variety_min` is the bar a distance must reach;
a pair FAILS when `dist < spec.variety_min`.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_check_reel.py`, using the `_Stub` and `_master`
helpers already defined at the top of that file:

```python
def test_a_passing_variety_reports_the_nearest_pair_it_measured(tmp_path, monkeypatch):
    """A pass used to report `{}` — every distance computed and none kept, so the
    worst junction was re-derived by hand on three separate days of the only real
    run (retro R6). The measurement now survives the pass (design 2026-09-07 §2)."""
    # ep0..ep2 at hashes 0, 1000, 1020 → pair distances 1000 and 20; both clear a
    # variety_min of 8, and the nearest pair is (1, 2) at 20.
    _Stub([3.0, 3.0, 3.0], hashes={1.5: 0, 4.5: 1000, 7.5: 1020}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4", "c.mp4"],
                         ReelCheckSpec(target_dur=9.0, variety_min=8),
                         str(tmp_path / "r.json"))
    assert rep.checks["variety"] == CheckResult(
        "variety", True, {"min_distance": 20, "pair": [1, 2], "min": 8})


def test_a_failing_variety_still_reports_the_global_minimum(tmp_path, monkeypatch):
    """The value is unchanged wherever a failure exists, and that is provable: if any
    pair is below variety_min then the global minimum IS that pair. Pinned so a later
    reader can see the fail path was not quietly re-specified (design §2.1)."""
    # pair (0,1) distance 4 fails; pair (1,2) distance 1000 passes.
    _Stub([3.0, 3.0, 3.0], hashes={1.5: 0, 4.5: 4, 7.5: 1004}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4", "c.mp4"],
                         ReelCheckSpec(target_dur=9.0, variety_min=8),
                         str(tmp_path / "r.json"))
    assert rep.checks["variety"] == CheckResult(
        "variety", False, {"min_distance": 4, "pair": [0, 1], "min": 8})
    f = [x for x in rep.fail_reasons if x.check == "variety"][0]
    assert f == ReelFailure("variety", "edit-plan", 1, {"pair": [0, 1], "distance": 4})


def test_a_passing_variety_report_survives_json(tmp_path, monkeypatch):
    """rep.write() json.dumps the detail. The failing path already had this guard;
    the passing path now carries values too and needs its own."""
    _Stub([3.0, 3.0, 3.0], hashes={1.5: 0, 4.5: 1000, 7.5: 1020}).install(monkeypatch)
    out = tmp_path / "r.json"
    check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4", "c.mp4"],
                   ReelCheckSpec(target_dur=9.0, variety_min=8), str(out))
    d = json.loads(out.read_text())
    assert d["checks"]["variety"]["detail"] == {"min_distance": 20, "pair": [1, 2], "min": 8}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_check_reel.py -k "nearest_pair or global_minimum or passing_variety_report" -v
```

Expected: `test_a_passing_variety_reports_the_nearest_pair_it_measured` FAILS
(the detail is `{}`), `test_a_passing_variety_report_survives_json` FAILS, and
`test_a_failing_variety_still_reports_the_global_minimum` FAILS on the
`"pair"`/`"min"` keys the detail does not yet carry.

- [ ] **Step 3: Replace the variety block**

`scripts/check_reel.py`, replacing the `if len(episodes) > 1:` block:

```python
    if len(episodes) > 1:
        hashes = [_phash_bits(master, m) for m in mids]
        var_ok = True
        # The nearest pair is measured on EVERY path, not only the failing one. A
        # passing variety used to report `{}`, so the worst junction of the only real
        # run was re-derived by hand on three separate days (retro R6). Where a failure
        # exists the value does not change — if any pair is below variety_min then the
        # global minimum IS that pair — so this is observable only on a pass, which is
        # therefore the only thing a test can discriminate (design 2026-09-07 §2.1).
        worst, worst_pair = None, None
        for i in range(len(hashes) - 1):
            dist = _hamming(hashes[i], hashes[i + 1])   # already coerced to int
            if worst is None or dist < worst:
                worst, worst_pair = dist, [i, i + 1]
            if dist < spec.variety_min:
                var_ok = False
                fails.append(ReelFailure("variety", "edit-plan", i + 1,
                                         {"pair": [i, i + 1], "distance": dist}))
        # len(episodes) > 1 guarantees at least one pair, so worst is never None here.
        checks["variety"] = CheckResult("variety", var_ok,
                                        {"min_distance": worst, "pair": worst_pair,
                                         "min": spec.variety_min})
    else:
        checks["variety"] = CheckResult("variety", None,
                                        {"status": "n/a", "reason": "single episode"})
```

- [ ] **Step 4: Run the new tests, then the whole check_reel file**

```bash
.venv/bin/python -m pytest tests/lib/test_check_reel.py -v
```

Expected: all PASS. Three pre-existing tests assert `rep.checks["variety"].passed`
only and are unaffected.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "$(cat <<'MSG'
fix: a passing variety check reports the distance it measured

check_reel assigned `worst` only inside the failure branch, so a passing variety
reported `{}` — every adjacent phash distance computed and none kept. On the only
real run the worst junction was therefore re-derived by hand on three separate
days (retro R6.1).

Two defects, not one: the failing path reported the minimum over the FAILING
pairs rather than the global minimum. Those two coincide whenever a failure
exists (a pair below variety_min is itself the global minimum), so the fail path
is byte-identical and the pass path is the only observable change — and the only
thing a test can discriminate.

The detail now carries the pair the distance came from and the bar it was judged
against, so a reader sees the margin without holding the spec.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: `OutroFit.cause` and the two causes `fit_outro` itself knows

**Files:**
- Modify: `scripts/lib/outro.py`
- Test: `tests/lib/test_outro.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `outro.CAUSES: tuple[str, ...]` =
    `("no-bars", "no-episodes", "ramped-closer", "closer-not-in-footage", "no-reachable-line")`
  - `outro.CAUSE_WHY: dict[str, str]` — one clause per cause **and** for `""`.
  - `OutroFit.cause: str = ""`, validated, in `to_dict`/`from_dict`.
  - `fit_outro` returns `cause="no-bars"` from its empty-bars early return and
    `cause="no-reachable-line"` from its final return.

**The trap this task exists to avoid.** `fit_outro` builds ONE `unchanged`
object at the top and returns it from two places that now carry different
causes. Reusing the shared object silently labels a `"no-reachable-line"` as
`"no-bars"` — the exact confusion the field exists to end.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_outro.py`:

```python
def test_no_bars_and_no_reachable_line_are_different_causes():
    """Both return rung 'unchanged'; until 2026-09-07 the two records were
    byte-identical, and check_reel asserted "the fit chose no bar line" for runs
    where no fit ever ran (design §0.1)."""
    no_bars = outro.fit_outro([], [], reel_dur=10.0, bar_s=2.0, fade=0.3,
                              music_dur=30.0, grow_max=1.0, shrink_max=1.0)
    assert (no_bars.rung, no_bars.cause) == ("unchanged", "no-bars")
    # bars exist but every one is more than a bar away from the cut's length, so the
    # ladder runs and the +/- one-bar band rejects all of them.
    unreachable = outro.fit_outro([40.0, 42.0], [], reel_dur=10.0, bar_s=2.0, fade=0.3,
                                  music_dur=60.0, grow_max=1.0, shrink_max=1.0)
    assert (unreachable.rung, unreachable.cause) == ("unchanged", "no-reachable-line")


def test_a_successful_fit_carries_no_cause():
    """A fit that chose a bar line has no absence to name."""
    fit = outro.fit_outro([9.7], [(0.0, 5.0), (9.0, 20.0)], reel_dur=10.0, bar_s=2.0,
                          fade=0.3, music_dur=30.0, grow_max=1.0, shrink_max=1.0)
    assert fit.rung == "gap" and fit.cause == ""


def test_a_cause_beside_a_chosen_rung_is_refused():
    with pytest.raises(ValueError, match="must be '' when rung is"):
        outro.OutroFit(reel_dur=10.0, line=9.7, fade=0.3, tail=1.0, rung="gap",
                       moved=0.0, cause="no-bars")


def test_an_unknown_cause_is_refused():
    with pytest.raises(ValueError, match="OutroFit.cause must be one of"):
        outro.OutroFit(reel_dur=10.0, line=None, fade=0.3, tail=0.0, rung="unchanged",
                       moved=0.0, cause="because")


def test_an_edl_written_before_this_slice_loads_with_no_cause():
    """'' is not-recorded, never 'no reason'. Pre-2026-09-07 EDL.json must load."""
    fit = outro.OutroFit.from_dict({"reel_dur": 34.93, "line": None, "fade": 0.3,
                                    "tail": 0.0, "rung": "unchanged", "moved": 0.0,
                                    "brief_len": 45.0, "need": 0.0})
    assert fit.cause == ""


def test_the_cause_round_trips():
    fit = outro.OutroFit(reel_dur=10.0, line=None, fade=0.3, tail=0.0,
                         rung="unchanged", moved=0.0, cause="ramped-closer")
    assert outro.OutroFit.from_dict(fit.to_dict()) == fit
    assert fit.to_dict()["cause"] == "ramped-closer"


def test_every_cause_has_a_clause_and_so_does_the_unrecorded_one():
    """Both readers (check_reel's outro reason, EDL.md's outro section) print from
    CAUSE_WHY. A cause with no clause would render as a KeyError or a blank."""
    assert set(outro.CAUSE_WHY) == set(outro.CAUSES) | {""}
    assert all(v.strip() for v in outro.CAUSE_WHY.values())
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_outro.py -k "cause" -v
```

Expected: FAIL — `AttributeError: module 'scripts.lib.outro' has no attribute
'CAUSE_WHY'` and `TypeError: __init__() got an unexpected keyword argument
'cause'`.

- [ ] **Step 3: Add `CAUSES`, `CAUSE_WHY`, the field and its validation**

In `scripts/lib/outro.py`, change the import line to:

```python
from dataclasses import dataclass, replace
```

Add beside `RUNGS`:

```python
CAUSES = ("no-bars", "no-episodes", "ramped-closer",
          "closer-not-in-footage", "no-reachable-line")

# One wording table for both readers — check_reel's outro reason and EDL.md's outro
# section. Two readers writing their own sentences for the same five states is the
# shape that drifts, and the sentence they used to share was FALSE for four of them:
# it said "the fit chose no bar line" where no fit had run at all.
CAUSE_WHY = {
    "no-bars": "the analysed music window carries no bar grid, so no fit ever ran",
    "no-episodes": "the cut has no episodes, so there is no closing shot to move",
    "ramped-closer": "the closing episode carries a ramp, whose played length is not "
                     "its source length, so the fit is skipped rather than guessed",
    "closer-not-in-footage": "the closing episode's source is not in FOOTAGE.json, so "
                             "the room it has left could not be measured",
    "no-reachable-line": "the fit ran and no bar line within one bar of the cut's own "
                         "length was one the closing shot could reach",
    "": "not recorded — this artifact predates 2026-09-07, when the five causes of an "
        "unchanged fit became distinguishable",
}
```

Add the field to `OutroFit`, after `need`:

```python
    cause: str = ""                  # WHY this fit is "unchanged" — one of CAUSES.
                                     # "" on every gap/no-gap fit (a fit that chose a
                                     # bar line has no absence to name) and on an
                                     # artifact written before 2026-09-07. FIVE
                                     # producers can reach "unchanged" and until this
                                     # field every one wrote a byte-identical record,
                                     # so check_reel asserted "the fit chose no bar
                                     # line" for a run whose music had no bar grid and
                                     # where no fit had run (design 2026-09-07 §3).
```

Add to `__post_init__`, after the existing `rung` check:

```python
        if self.rung == "unchanged":
            if self.cause != "" and self.cause not in CAUSES:
                raise ValueError(
                    f"OutroFit.cause must be one of {CAUSES}, or '' for an artifact "
                    f"written before 2026-09-07 which recorded none; got "
                    f"{self.cause!r}. Re-run edit_plan build --pacing --music")
        elif self.cause:
            raise ValueError(
                f"OutroFit.cause must be '' when rung is {self.rung!r} — a fit that "
                f"chose a bar line has no absence to name, so a cause beside a "
                f"'gap'/'no-gap' rung is a contradiction the record must not hold. "
                f"Got {self.cause!r}")
```

Extend `to_dict` and `from_dict`:

```python
    def to_dict(self) -> dict:
        return {"reel_dur": self.reel_dur, "line": self.line, "fade": self.fade,
                "tail": self.tail, "rung": self.rung, "moved": self.moved,
                "brief_len": self.brief_len, "need": self.need, "cause": self.cause}
```

and in `from_dict`'s `cls(...)` call add `cause=d.get("cause", "")`.

- [ ] **Step 4: Give `fit_outro`'s two `unchanged` returns their own causes**

In `fit_outro`, change the `unchanged` construction and the empty-bars return:

```python
    # The FINAL return's cause: the ladder ran and rejected every candidate.
    unchanged = OutroFit(reel_dur=reel_dur, line=None, fade=float(fade), tail=0.0,
                         rung="unchanged", moved=0.0, brief_len=brief_len,
                         cause="no-reachable-line")
    if not bars:
        # A DIFFERENT absence: with no bar grid the ladder below never runs at all.
        # It must be its own object — returning the shared `unchanged` here would
        # label it "no-reachable-line" and re-create in one line exactly the collapse
        # this field exists to end (design 2026-09-07 §3).
        return replace(unchanged, cause="no-bars")
```

The final `return unchanged` at the end of the function is left as it is.

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_outro.py -v
```

Expected: all PASS, including the 34 pre-existing tests. If a pre-existing test
constructs an `OutroFit` with `rung="unchanged"` and compares whole objects, it
now needs the `cause` it expects — update it to the real cause rather than
loosening the assert.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/outro.py tests/lib/test_outro.py
git commit -m "$(cat <<'MSG'
feat: OutroFit records WHY a fit is "unchanged"

Five producers reach rung "unchanged" and until now every one wrote a
byte-identical record, so no reader could tell "there was no bar grid, the fit
never ran" from "the fit ran and no line was legal". check_reel printed the
second wording for all of them; on the only real run all four MUSIC*.json carried
`bars: []`, so it asserted the case that had not happened (retro R7.1).

`cause` is a closed vocabulary validated like `rung`, and "" stays legal so an
EDL written before today loads and reads as not-recorded rather than as "no
reason". A cause beside a gap/no-gap rung is refused: a fit that chose a bar line
has no absence to name.

CAUSE_WHY is one wording table for both readers. Two readers inventing their own
sentences for the same five states is the shape that drifts — and the sentence
they used to share was the one that was wrong.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: the three causes `edit_plan` knows, and the two readers that print them

**Files:**
- Modify: `scripts/edit_plan.py:310-360` (`_apply_outro`)
- Modify: `scripts/lib/edl.py:467-494` (`to_markdown`'s outro section)
- Modify: `scripts/check_reel.py:368-375` (the outro check's `"n/a"` arm)
- Test: `tests/lib/test_edit_plan.py`, `tests/lib/test_edl.py`, `tests/lib/test_check_reel.py`

**Interfaces:**
- Consumes: `outro.CAUSES`, `outro.CAUSE_WHY`, `OutroFit.cause` from Task 2.
- Produces: `checks["outro"].detail` on the `"unchanged"` arm becomes
  `{"status": "n/a", "cause": <str>, "reason": <str>, "advisory": True}` — the
  `"reason"` key survives, the free-text sentence behind it changes, and
  `"cause"` is new and machine-readable.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_edit_plan.py`:

```python
def test_apply_outro_names_the_absence_when_the_music_has_no_bar_grid():
    """All four MUSIC*.json of the only real run carried `bars: []`; the whole
    outro-fit feature reported "n/a" and did nothing (retro R7.1)."""
    eps, fit = edit_plan._apply_outro(_two_episodes(), _footage(),
                                      _music(bars=()), fade=0.3, brief_len=45.0)
    assert (fit.rung, fit.cause) == ("unchanged", "no-bars")
    assert fit.brief_len == 45.0


def test_apply_outro_names_a_ramped_closing_episode():
    eps, fit = edit_plan._apply_outro(_two_episodes(ramp_last=True), _footage(),
                                      _music(), fade=0.3, brief_len=None)
    assert (fit.rung, fit.cause) == ("unchanged", "ramped-closer")


def test_apply_outro_names_a_closing_source_missing_from_footage():
    eps, fit = edit_plan._apply_outro(_two_episodes(), _footage(drop_last=True),
                                      _music(), fade=0.3, brief_len=None)
    assert (fit.rung, fit.cause) == ("unchanged", "closer-not-in-footage")


def test_apply_outro_names_an_empty_cut():
    """_apply_outro's guard is `not episodes or not music.bars` — one branch for two
    unrelated absences. Unreachable through build_edl today; lumping it under
    'no-bars' would re-create in miniature the collapse this field ends."""
    eps, fit = edit_plan._apply_outro([], _footage(), _music(), fade=0.3, brief_len=None)
    assert (fit.rung, fit.cause) == ("unchanged", "no-episodes")
```

Build `_two_episodes`, `_footage` and `_music` from the helpers this file already
uses to construct `EDLEpisode`, `Footage` and `MusicSpec`; read the file's
existing fixtures first and reuse them rather than writing a fourth shape. The
`ramp_last` variant sets the last episode's `ramp` to a valid `RampSpec` dict;
the `drop_last` variant omits the last episode's source from
`Footage.clips`. `_music(bars=())` builds a `MusicSpec` whose `bars` is empty and
whose `beats`/`tempo` are otherwise valid.

In `tests/lib/test_edl.py`:

```python
def test_edl_markdown_states_the_outro_cause_instead_of_a_disjunction():
    """EDL.md used to hedge: "none that the closing shot has room for, OR no bar grid
    at all" — a disjunction, when the producer knew which (design §0.1)."""
    edl = _edl_with_outro(OutroFit(reel_dur=34.93, line=None, fade=0.3, tail=0.0,
                                   rung="unchanged", moved=0.0, brief_len=45.0,
                                   cause="no-bars"))
    md = edl.to_markdown()
    assert outro.CAUSE_WHY["no-bars"] in md
    assert " or no bar " not in md          # the disjunction is gone
    assert "-10.07s vs the brief's 45.0s" in md   # the existing clause is untouched
```

In `tests/lib/test_check_reel.py`:

```python
def test_the_outro_check_does_not_claim_a_fit_ran_when_none_did(tmp_path, monkeypatch):
    """The one sentence check_reel printed for every unchanged fit — "the fit chose no
    bar line" — is true only for 'no-reachable-line'. On the real run the cause was
    'no-bars' and no fit had run (design §0.1)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         outro={"rung": "unchanged", "cause": "no-bars"})
    assert rep.checks["outro"] == CheckResult("outro", None, {
        "status": "n/a", "cause": "no-bars",
        "reason": outro_mod.CAUSE_WHY["no-bars"], "advisory": True})
    assert rep.overall is True


def test_an_outro_with_no_recorded_cause_reads_as_not_recorded(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         outro={"rung": "unchanged"})
    assert rep.checks["outro"].detail["cause"] == ""
    assert rep.checks["outro"].detail["reason"] == outro_mod.CAUSE_WHY[""]
```

Add `from scripts.lib import outro as outro_mod` to that test file's imports.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k outro tests/lib/test_edl.py -k outro_cause tests/lib/test_check_reel.py -k "outro_check or recorded_cause" -v
```

Expected: FAIL — the causes come back as `""` and the reader strings are the old
ones.

- [ ] **Step 3: Set the three causes in `_apply_outro`**

`scripts/edit_plan.py`, replacing the early return and the two skip arms:

```python
    if not episodes or not music.bars:
        # Two unrelated absences shared this guard. They are named apart: an empty cut
        # has no closing shot to move at all, while a bar-grid-less window means the
        # ladder never runs (design 2026-09-07 §3).
        return episodes, outro.OutroFit(
            reel_dur=sum(e.play_dur() for e in episodes),
            line=None, fade=fade, tail=0.0, rung="unchanged", moved=0.0,
            brief_len=brief_len,
            cause="no-episodes" if not episodes else "no-bars")
    last = episodes[-1]
    realized = sum(e.play_dur() for e in episodes)
    if last.ramp is not None:
        _log(f"outro: the closing episode carries a ramp — its played length is not its "
             f"source length, so the outro fit is skipped and the reel stays "
             f"{realized:.2f}s. Move the ramp off the last episode to fit the ending.")
        return episodes, outro.OutroFit(reel_dur=realized, line=None, fade=fade, tail=0.0,
                                        rung="unchanged", moved=0.0, brief_len=brief_len,
                                        cause="ramped-closer")
    clip = next((c for c in footage.clips if c.source == last.source), None)
    if clip is None:
        _log(f"outro: {last.source!r} is not in FOOTAGE — cannot measure the closing "
             f"shot's room, so the reel stays {realized:.2f}s")
        return episodes, outro.OutroFit(reel_dur=realized, line=None, fade=fade, tail=0.0,
                                        rung="unchanged", moved=0.0, brief_len=brief_len,
                                        cause="closer-not-in-footage")
```

The shared `unchanged` local that these three arms used is now gone — delete its
assignment. The `fit.rung == "unchanged"` arm further down returns `fit`, which
already carries `"no-reachable-line"` from Task 2; leave it as it is.

- [ ] **Step 4: Make `EDL.md` state the cause**

`scripts/lib/edl.py`. The module already has `from scripts.lib.outro import
OutroFit`; extend it to `from scripts.lib.outro import CAUSE_WHY, OutroFit`.
Replace the `else:` arm of the `why` ladder:

```python
            else:
                # One wording table, shared with check_reel's outro reason. This used to
                # be a disjunction — "none that the closing shot has room for, or no bar
                # grid at all" — written by a producer that knew which (design §0.1).
                why = (f"{CAUSE_WHY.get(o.cause) or f'unrecognized cause {o.cause!r}'}, "
                       f"so the reel keeps its footage-derived length and the music "
                       f"ends mid-phrase")
```

- [ ] **Step 5: Make `check_reel`'s outro reason cause-specific**

`scripts/check_reel.py`. Add `outro` to the `scripts.lib` import line, which
becomes:

```python
from scripts.lib import color, ffbin, outro as outro_mod, proc, provenance, reel_final, safezones
```

(`outro.py` imports only `collections.abc` and `dataclasses`, so it is a leaf and
introduces no cycle. The alias avoids shadowing `run`'s own `outro` parameter.)

Replace the `"n/a"` arm:

```python
        if outro.get("rung", "unchanged") == "unchanged":
            # WHICH absence, not merely that there was one. Until 2026-09-07 this
            # printed "the fit chose no bar line" for all five causes — true for
            # exactly one of them, and not the one that fired on the only real run.
            cause = outro.get("cause", "")
            checks["outro"] = CheckResult("outro", None, {
                "status": "n/a", "cause": cause,
                "reason": (outro_mod.CAUSE_WHY.get(cause)
                           or f"unrecognized cause {cause!r}"),
                "advisory": True})
```

- [ ] **Step 6: Run the three test files**

```bash
.venv/bin/python -m pytest tests/lib/test_edit_plan.py tests/lib/test_edl.py tests/lib/test_check_reel.py -v
```

Expected: all PASS. A pre-existing test asserting the old
`"the fit chose no bar line (rung 'unchanged')"` string must be updated to the
cause-specific wording, not deleted.

- [ ] **Step 7: Commit**

```bash
git add scripts/edit_plan.py scripts/lib/edl.py scripts/check_reel.py tests/lib/test_edit_plan.py tests/lib/test_edl.py tests/lib/test_check_reel.py
git commit -m "$(cat <<'MSG'
fix: the outro's readers say which absence it was, not a disjunction

_apply_outro reaches "unchanged" from three arms and each now names its own
cause; its `not episodes or not music.bars` guard covered two unrelated absences
under one branch and they are split ("no-episodes" is unreachable through
build_edl today, and lumping it in would re-create in miniature the collapse this
field ends).

Both readers stop guessing. check_reel's outro reason came from one hardcoded
sentence — "the fit chose no bar line" — which is true for "no-reachable-line"
and false for the other four, including the one that actually fired on the real
run. EDL.md hedged instead: "none that the closing shot has room for, or no bar
grid at all", a disjunction written by a producer that knew which. Both now print
from outro.CAUSE_WHY, and check_reel's detail carries the raw cause beside the
sentence so a machine reader does not have to parse prose.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 4: `SPEC.length_s` becomes a first-class carrier

**Files:**
- Modify: `scripts/lib/edl.py` (`EDL` field, `__post_init__`, `to_dict`, `from_dict`)
- Modify: `scripts/lib/models.py` (`ReelManifest` field, `to_dict`, `from_dict`)
- Modify: `scripts/edit_plan.py:600-602` (`build_edl`'s `EDL(...)` call)
- Modify: `scripts/edl_to_reel.py:275-285` (`ReelManifest(...)` call)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_edl_to_reel.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–3.
- Produces: `EDL.brief_len: float | None` and `ReelManifest.brief_len: float | None`,
  both round-tripping through `to_dict`/`from_dict`. Task 5 reads
  `rm.brief_len`.

**Why a new field rather than reusing `OutroFit.brief_len`.** That one is a pure
function's record of the tie-breaker it was handed, and it exists only when
`--music` was supplied. The brief is a property of the reel, not of the outro
fit. `EDL.platform` is the precedent this follows exactly: copied from `Spec` by
`edit_plan`, spent by `edl_to_reel` on the manifest, read by `check_reel`.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_edl.py`:

```python
def test_edl_carries_the_brief_length_and_round_trips_it():
    edl = _minimal_edl(brief_len=45.0)
    assert edl.brief_len == 45.0
    assert EDL.from_dict(edl.to_dict()).brief_len == 45.0


def test_an_edl_written_before_this_slice_has_no_brief_length():
    d = _minimal_edl().to_dict()
    d.pop("brief_len")
    assert EDL.from_dict(d).brief_len is None


@pytest.mark.parametrize("bad", [0.0, -1.0, "45", True])
def test_a_non_positive_brief_length_is_refused(bad):
    """gap_frac divides by this two stages later; it fails where it is accepted."""
    with pytest.raises(ValueError, match="EDL.brief_len must be a positive number"):
        _minimal_edl(brief_len=bad)
```

In `tests/lib/test_edl_to_reel.py`, extend whichever test already asserts that
`_build_manifest` copies `platform`/`look`/`outro` off the EDL, adding
`brief_len` to the same whole-object or field-by-field assertion. If no such test
exists, add:

```python
def test_the_manifest_carries_the_brief_length_off_the_edl(tmp_path, monkeypatch):
    """check_reel's `length` gate measures against EDL.target_dur, which came from the
    footage — a tautology with respect to the brief. brief_len is the one length that
    is not derived from the cut, so it must reach the manifest (design §4)."""
    rm = _build_manifest_for(tmp_path, monkeypatch, brief_len=45.0)
    assert rm.brief_len == 45.0
    assert ReelManifest.from_dict(rm.to_dict()).brief_len == 45.0
```

using this file's existing manifest-building helper.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_edl.py -k brief tests/lib/test_edl_to_reel.py -k brief -v
```

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument
'brief_len'`.

- [ ] **Step 3: Add `EDL.brief_len`**

`scripts/lib/edl.py`, in the `EDL` dataclass after `outro`:

```python
    brief_len: float | None = None   # SPEC.length_s — the ONE length in a reel that is
                                     # NOT derived from the cut. target_dur comes from
                                     # edit_plan._back_edge_target, i.e. from the
                                     # footage, so check_reel's length gate is a
                                     # tautology with respect to the brief and could
                                     # not notice the real run shipping 34.93s against
                                     # a 45.0s brief. check_reel's advisory
                                     # brief_length row measures against this (design
                                     # 2026-09-07 §4). None = no brief was supplied.
```

In `__post_init__`:

```python
        if self.brief_len is not None and (
                isinstance(self.brief_len, bool)
                or not isinstance(self.brief_len, (int, float))
                or self.brief_len <= 0):
            raise ValueError(
                f"EDL.brief_len must be a positive number of seconds (SPEC.length_s) "
                f"or None, got {self.brief_len!r} — this is what check_reel's "
                f"brief_length row divides by; re-run edit_plan build --spec")
```

In `to_dict`, add `"brief_len": self.brief_len` to the dict literal. In
`from_dict`'s `cls(...)` call, add `brief_len=d.get("brief_len")`.

- [ ] **Step 4: Add `ReelManifest.brief_len`**

`scripts/lib/models.py`, in `ReelManifest` after `tone_target`:

```python
    brief_len: float | None = None     # SPEC.length_s, carried off EDL.brief_len so
                                       # check_reel can measure the delivered reel
                                       # against the length that was ASKED FOR rather
                                       # than only against target_dur, which came from
                                       # the cut (design 2026-09-07 §4). None = no
                                       # brief; the brief_length row then reads
                                       # not-checked, never "on target".
```

In `to_dict`, add `"brief_len": self.brief_len`. In `from_dict`'s `cls(...)`
call, add `brief_len=d.get("brief_len")`.

- [ ] **Step 5: Fill it at both producers**

`scripts/edit_plan.py`, `build_edl`'s return:

```python
    return EDL(episodes=tuple(episodes), music=selection.get("music"), cast=cast,
               cap=cap if cap is not None else 3, platform=platform, look=resolved_look,
               target_dur=target, variety=variety, constraints=cons, outro=fit,
               brief_len=brief_len)
```

`scripts/edl_to_reel.py`, the `ReelManifest(...)` call — add, beside
`tone_target`:

```python
                      # SPEC.length_s. The only length in the manifest that did not
                      # come from the cut, so it is the only one check_reel's length
                      # arithmetic cannot be circular about (design 2026-09-07 §4)
                      brief_len=edl.brief_len,
```

- [ ] **Step 6: Run both test files**

```bash
.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_edl_to_reel.py tests/lib/test_edit_plan.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/edl.py scripts/lib/models.py scripts/edit_plan.py scripts/edl_to_reel.py tests/lib/test_edl.py tests/lib/test_edl_to_reel.py
git commit -m "$(cat <<'MSG'
feat: SPEC.length_s reaches the reel manifest as EDL.brief_len

check_reel's `length` check measures the master against spec.target_dur, which
edl_to_reel took from EDL.target_dur, which edit_plan._back_edge_target computed
as min(realized, spine.target_dur) — a number derived from the cut itself. The
gate is therefore a tautology with respect to the brief, and the real run's
34.93s against a 45.0s brief (-22.4%) passed everything because there was nothing
for it to fail.

brief_len follows EDL.platform's precedent exactly: copied from Spec by
edit_plan, spent by edl_to_reel onto the manifest, read by check_reel. It is
validated positive-or-None where it is accepted, because the check that consumes
it divides by it two stages later.

OutroFit.brief_len stays and is not a duplicate in kind: fit_outro is a pure
function and that field is its record of the tie-breaker it was handed. One
writer sets both, so on the edit_plan path they cannot drift.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 5: the advisory `brief_length` check

**Files:**
- Modify: `scripts/check_reel.py` (`_UNCHECKED`, a new `_brief_length_check`, `run`'s signature and call site)
- Modify: `scripts/lib/models.py:1288` (`_ADVISORY_CHECKS`)
- Modify: `scripts/build_reel.py:120-124` (the `check_reel.run` call)
- Test: `tests/lib/test_check_reel.py`, `tests/lib/test_build_reel.py`

**Interfaces:**
- Consumes: `ReelManifest.brief_len` from Task 4.
- Produces: `check_reel.run(..., brief_len: float | None = None)` and a
  `checks["brief_length"]` row.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_check_reel.py`:

```python
def test_brief_length_measures_the_reel_against_the_length_that_was_asked_for(tmp_path, monkeypatch):
    """The real run: a 45.0s brief delivered as 34.93s, past every gate, because the
    only length anything compared against came from the cut (design §0.2)."""
    _Stub([17.465, 17.465], hashes={8.7325: 0, 26.1975: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=34.93), str(tmp_path / "r.json"),
                         brief_len=45.0)
    assert rep.checks["brief_length"] == CheckResult("brief_length", False, {
        "brief": 45.0, "delivered": 34.93, "gap": -10.07, "gap_frac": -0.2238,
        "budget": 1.5, "advisory": True})
    # length itself still passes — it is measured against the cut's own target
    assert rep.checks["length"].passed is True


def test_brief_length_is_advisory_and_cannot_block(tmp_path, monkeypatch):
    _Stub([17.465, 17.465], hashes={8.7325: 0, 26.1975: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=34.93), str(tmp_path / "r.json"),
                         brief_len=45.0)
    assert rep.checks["brief_length"].passed is False
    assert rep.overall is True
    assert not [f for f in rep.fail_reasons if f.check == "brief_length"]


def test_brief_length_passes_inside_the_budget_the_pipeline_already_absorbs(tmp_path, monkeypatch):
    """_LENGTH_TOL (0.5) + length_retime_max (1.0) is what the conveyor already says
    it absorbs without comment. Not a measured answer to how far a reel may drift
    from its brief — the least-invented number available (design §4.3)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         brief_len=7.5)
    assert rep.checks["brief_length"].passed is True     # gap -1.5, exactly the budget


def test_brief_length_treats_over_and_under_alike(tmp_path, monkeypatch):
    """The borrowed budget is one-sided — reel_orchestration absorbs a shortfall only,
    because mix.mix refuses dur > music.duration. That reason is a mixer constraint
    and says nothing about a brief, so it is deliberately not carried over (§4.3)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         brief_len=4.4)
    assert rep.checks["brief_length"].passed is False    # gap +1.6, past the budget
    assert rep.checks["brief_length"].detail["gap"] == 1.6


def test_no_brief_reads_as_not_checked_never_as_on_target(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"))
    assert rep.checks["brief_length"].passed is None
    assert rep.checks["brief_length"].detail["status"] == "not-checked"
```

In `tests/lib/test_build_reel.py`, extend the existing test that asserts what
`build_reel` forwards to `check_reel.run` (it already pins `platform`, `outro`,
`predicted`, `tone_target`, `tone_dsts`) with `brief_len`. If the file captures
the call through a spy, add the key to the captured-kwargs assertion; if it has
no such test, add one that installs a spy over `check_reel.run`, drives
`build_reel` with a manifest carrying `brief_len=45.0`, and asserts the spy saw
`brief_len == 45.0`.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_check_reel.py -k brief -v
```

Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'brief_len'`.

- [ ] **Step 3: Register the advisory check**

`scripts/lib/models.py:1288`:

```python
_ADVISORY_CHECKS = ("beat", "safe_zones", "key_action", "pad_bars", "transitions",
                    "outro", "brief_length")   # measured + reported but non-blocking (design §5)
```

- [ ] **Step 4: Add the check**

`scripts/check_reel.py`, extend `_UNCHECKED`:

```python
              "brief_length": "not checked — the reel manifest carries no brief_len "
                              "(SPEC.length_s); a reel authored without --spec has no "
                              "asked-for length to be measured against",
```

Add the function beside `_loudness_check`:

```python
def _brief_length_check(total: float, brief_len: float, spec: ReelCheckSpec) -> CheckResult:
    """BRIEF_LENGTH — advisory. The delivered master against SPEC.length_s, the one
    length in a reel that is NOT derived from the cut (design 2026-09-07 §4).

    `length` above measures the master against spec.target_dur, which edl_to_reel took
    from EDL.target_dur, which edit_plan._back_edge_target computed from the footage —
    so it is circular with respect to the brief and could not notice the only real run
    shipping 34.93s against a 45.0s brief. Nothing else in the tree compares them.

    `passed` keys on _LENGTH_TOL + spec.length_retime_max: the length gate's own band
    plus the further shortfall build_reel will silently re-time the target by. That sum
    is exactly what the conveyor already declares it absorbs without comment, so no new
    constant is invented here — and it is NOT a measured answer to how far a reel may
    drift from its brief (§7).

    Applied symmetrically, though the borrowed budget is one-sided: reel_orchestration
    absorbs a shortfall only, and its reason is local and mechanical (the stem is cut
    from a fixed fragment and mix.mix refuses dur > music.duration). A reel LONGER than
    its brief is not blocked by anything — it is merely not the reel that was asked
    for — so that asymmetry stays where its cause is."""
    budget = _LENGTH_TOL + spec.length_retime_max
    gap = total - brief_len
    return CheckResult("brief_length", abs(gap) <= budget,
                       {"brief": round(brief_len, 3), "delivered": round(total, 3),
                        "gap": round(gap, 3), "gap_frac": round(gap / brief_len, 4),
                        "budget": round(budget, 3), "advisory": True})
```

Add `brief_len: float | None = None` to `run`'s keyword parameters, and call it
immediately after the `length` check is appended:

```python
    if brief_len is not None:
        checks["brief_length"] = _brief_length_check(total, brief_len, spec)
```

- [ ] **Step 5: Feed it from `build_reel`**

`scripts/build_reel.py`, the `check_reel.run` call:

```python
        report = check_reel.run(master, clips, spec, report_path,
                                music=music, audio=audio, geometry=geometry,
                                platform=rm.platform, outro=rm.outro,
                                predicted=predicted,
                                tone_target=rm.tone_target, tone_dsts=tone_dsts,
                                brief_len=rm.brief_len)
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_build_reel.py -v
```

Expected: all PASS. Every pre-existing test that iterates `_UNCHECKED` or asserts
the full set of check names now sees `brief_length` — update those to include it
rather than narrowing what they iterate.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_reel.py scripts/lib/models.py scripts/build_reel.py tests/lib/test_check_reel.py tests/lib/test_build_reel.py
git commit -m "$(cat <<'MSG'
feat: an advisory brief_length row measures the reel against SPEC.length_s

Every length the reel was checked against came from the cut, so no gate could
notice the only real run delivering 34.93s against a 45.0s brief — 22.4% short,
past everything, because nothing compared them. EDL.md printed the distance and
nothing read it.

brief_length is advisory and registered in _ADVISORY_CHECKS, so overall cannot
move. `passed` keys on _LENGTH_TOL + length_retime_max (1.5s on the defaults) —
exactly the budget the conveyor already declares it absorbs silently, so this
introduces no new constant. The design records that this is an analogy and not a
measured answer, and that the row is expected to be red often: no stage aims at
SPEC.length_s, and a frequently-false row here is reporting that gap rather than
misfiring.

Applied symmetrically although the borrowed budget is one-sided, because the
reason over-length escalates there is a mixer constraint (mix.mix refuses
dur > music.duration) that says nothing about a brief.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 6: `Slot.beats_in` — when the energy is a fallback, not a measurement

**Files:**
- Modify: `scripts/lib/pacing.py` (`Slot` field + validation + round-trip, `fit_spine`, `Spine.to_markdown`)
- Test: `tests/lib/test_pacing.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–5.
- Produces: `Slot.beats_in: int = -1`. Task 7's `energy_agreement` reads it.

**The measurement behind this task.** `fit_spine` computes a slot's energy as
`fmean(span or [0.5])`. When no beat of the analysed window falls inside the
slot, `span` is empty and the energy becomes the literal constant 0.5 — and
`_kind` then labels the slot from that constant. On the real run,
`pacing_B/PACING.json` slots 0–3 read `energy: 0.500` with kinds
`hook`/`build`/`build`/`build`, because `MUSIC_B.json`'s first beat is at 9.7387s
and those four slots end at 7.99s. `_beat_energy` min-max normalizes into
[0, 1], so a genuine 0.500 is possible and today indistinguishable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_pacing.py`:

```python
def test_a_slot_no_beat_reaches_records_that_its_energy_is_a_fallback():
    """fit_spine's `or [0.5]` is not a measurement, and _kind labels the slot from it.
    On the real run four slots of pacing_B read energy 0.500 / kind 'build' because
    that window's first beat is at 9.74s (design 2026-09-07 §0.4)."""
    beats = [4.0 + i * 0.5 for i in range(40)]      # nothing before t=4.0
    energy = [0.5] * 60
    spine, _, _ = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    assert spine.slots[0].beats_in == 0             # [0.0, 2.0) holds no beat
    assert spine.slots[0].energy == pytest.approx(0.5)   # the value is unchanged
    assert spine.slots[2].beats_in > 0


def test_a_measured_slot_counts_the_beats_it_contains():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, _, _ = pacing.fit_spine([2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 2)
    # slot 0 spans [0.0, 2.0): beats at 0.0, 0.5, 1.0, 1.5
    assert spine.slots[0].beats_in == 4


def test_beats_in_round_trips_and_defaults_to_not_recorded():
    s = pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0, beats_in=4)
    assert pacing.Slot.from_dict(s.to_dict()) == s
    old = {"index": 0, "start": 0.0, "dur": 2.0, "energy": 0.5, "kind": "hook",
           "line": 2.0, "dev": 0.0}          # a PACING.json written before this slice
    assert pacing.Slot.from_dict(old).beats_in == -1


@pytest.mark.parametrize("bad", [-2, 1.5, True, "4"])
def test_a_malformed_beats_in_is_refused(bad):
    with pytest.raises(ValueError, match="Slot.beats_in must be"):
        pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0, beats_in=bad)


def test_the_markdown_shows_a_dash_where_nothing_was_measured():
    beats = [4.0 + i * 0.5 for i in range(40)]
    energy = [0.5] * 60
    spine, _, _ = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    md = spine.to_markdown()
    assert "| 0 | 0.00–2.00 | 2.00 | – | – |" in md
    assert "contain no beat of the analysed window" in md


def test_the_markdown_of_a_fully_measured_spine_carries_no_footnote():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, _, _ = pacing.fit_spine([2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 2)
    assert "contain no beat" not in spine.to_markdown()
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_pacing.py -k "beats_in or fallback or markdown" -v
```

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument
'beats_in'`.

- [ ] **Step 3: Add the field**

`scripts/lib/pacing.py`, in `Slot` after `dev`:

```python
    beats_in: int = -1   # beats of the analysed window that fall inside this slot's
                         # span. 0 => `energy` is fit_spine's `or [0.5]` FALLBACK and
                         # `kind` is a label computed from that constant, not a
                         # measurement. -1 => not recorded (a PACING.json written
                         # before 2026-09-07). _beat_energy min-max normalizes into
                         # [0, 1], so a genuine 0.5 exists and was indistinguishable
                         # from the fallback until this field (design 2026-09-07 §5).
```

In `__post_init__`, after the `dev` check:

```python
        if (isinstance(self.beats_in, bool) or not isinstance(self.beats_in, int)
                or self.beats_in < -1):
            raise ValueError(
                f"Slot.beats_in must be a non-negative count of beats, or -1 for a "
                f"PACING.json written before 2026-09-07 which recorded none; got "
                f"{self.beats_in!r} — re-run pacing to regenerate PACING.json")
```

In `to_dict`, add `"beats_in": self.beats_in`. In `from_dict`, add
`beats_in=d.get("beats_in", -1)` to the `cls(...)` call — and **do not** add
`"beats_in"` to the `missing` list, or every pre-slice `PACING.json` stops
loading.

- [ ] **Step 4: Fill it in `fit_spine`**

Replace the slot loop's first two lines:

```python
    for i, dur in enumerate(fitted):
        inside = [n[k] for k, b in enumerate(beats) if pos <= b < pos + dur]
        # `or [0.5]` is a FALLBACK for a slot no beat reaches, not a measurement, and
        # _kind below labels the slot from it. beats_in records the count so a reader
        # can tell the two apart (design 2026-09-07 §0.4).
        e = fmean(inside or [0.5])
```

and the `Slot(...)` construction at the end of the loop:

```python
        slots.append(Slot(i, pos, dur, e, "hook" if i == 0 else _kind(e),
                          line=line, dev=dev, beats_in=len(inside)))
```

- [ ] **Step 5: Make `to_markdown` read it**

Replace `Spine.to_markdown`'s body:

```python
    def to_markdown(self) -> str:
        lines = [f"# Pacing — fitted spine ({len(self.slots)} slots, "
                 f"{self.target_dur:.1f}s @ {self.tempo:.0f} BPM)", "",
                 "| # | start–end | dur | energy | kind | line | dev |",
                 "|--:|-----------|----:|-------:|------|-----:|----:|"]
        unmeasured = 0
        for s in self.slots:
            line = f"{s.line:.2f}" if s.line is not None else "–"
            dev = f"{s.dev:.3f}" if s.line is not None else "–"
            # beats_in == -1 is a pre-2026-09-07 spine that did not record the count:
            # print what it has rather than claim it was unmeasured.
            if s.beats_in == 0:
                unmeasured += 1
                energy, kind = "–", "–"
            else:
                energy, kind = f"{s.energy:.2f}", s.kind
            lines.append(f"| {s.index} | {s.start:.2f}–{s.start + s.dur:.2f} | "
                         f"{s.dur:.2f} | {energy} | {kind} | {line} | {dev} |")
        if unmeasured:
            lines += ["", f"*{unmeasured} of {len(self.slots)} slots contain no beat of "
                          f"the analysed window, so their energy and kind are not "
                          f"measurements — `fit_spine` falls back to 0.5 and labels "
                          f"from it. A window whose beats start well into the reel is "
                          f"the usual cause.*"]
        return "\n".join(lines) + "\n"
```

- [ ] **Step 6: Run the tests, then every file that reads a spine**

```bash
.venv/bin/python -m pytest tests/lib/test_pacing.py tests/lib/test_pacing_fixed_point.py tests/lib/test_edit_plan.py -v
```

Expected: all PASS. A golden that pins a serialized spine now gains a
`"beats_in"` key — re-pin it, and check the re-pinned values are the beat counts
the fixture's grid actually produces rather than a blanket `-1`.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/pacing.py tests/lib/test_pacing.py
git commit -m "$(cat <<'MSG'
feat: a Slot records whether its energy was measured at all

fit_spine computes a slot's energy as fmean(span or [0.5]). When no beat of the
analysed window falls inside the slot, that 0.5 is a literal constant and _kind
then labels the slot from it. _beat_energy min-max normalizes into [0, 1], so a
genuine 0.5 exists and the two were indistinguishable.

On the only real run this is on disk: pacing_B/PACING.json slots 0-3 read
energy 0.500 with kinds hook/build/build/build, because MUSIC_B.json's first beat
is at 9.7387s and those four slots end at 7.99s. Slot 0 also carries dev 7.14 —
seven seconds off the grid — and still reads as a measured hook.

energy and kind are unchanged: kind cannot carry this state (slot 0 is
simultaneously unmeasured and positionally "hook", which Spine's own invariant
requires) and energy: None would break its contract and every consumer. The fact
rides in its own field and the readers change.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 7: the energy-agreement description

**Files:**
- Modify: `scripts/lib/pacing.py` (`energy_agreement`, `AGREEMENT_MIN_SLOTS`, the `statistics` import)
- Modify: `scripts/pacing.py:56-88` (`_report`'s header)
- Test: `tests/lib/test_pacing.py`

**Interfaces:**
- Consumes: `Slot.beats_in` from Task 6.
- Produces:
  `pacing.energy_agreement(slots) -> tuple[float | None, int, int, str]`
  returning `(rho, used, total, reason)`. `rho is None` ⟺ `reason` is non-empty.

**Why Spearman and not Pearson.** Eight to eighteen points, and the question is
ordinal — *do the shorter shots sit where the music is louder* — not linear.
`statistics.correlation(x, y, method="ranked")` is stdlib, which keeps
`lib/pacing.py`'s "stdlib only, no numpy, bit-exact" promise. Measured on the
run's three spines: −0.571 (shipped), +0.509 (the 18-episode cut), +0.484
(that cut against a second window).

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_pacing.py`:

```python
def _slot(i, start, dur, energy, beats_in=4):
    return pacing.Slot(i, start, dur, energy, "hook" if i == 0 else "build",
                       line=None, dev=0.0, beats_in=beats_in)


def test_energy_agreement_is_negative_when_short_shots_sit_where_it_is_loud():
    slots = (_slot(0, 0.0, 4.0, 0.2), _slot(1, 4.0, 3.0, 0.5),
             _slot(2, 7.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho == pytest.approx(-1.0)
    assert (used, total, why) == (3, 3, "")


def test_energy_agreement_is_positive_when_the_cut_inverts_the_curve():
    slots = (_slot(0, 0.0, 2.0, 0.2), _slot(1, 2.0, 3.0, 0.5),
             _slot(2, 5.0, 4.0, 0.9))
    rho, _, _, _ = pacing.energy_agreement(slots)
    assert rho == pytest.approx(1.0)


def test_energy_agreement_excludes_slots_whose_energy_was_never_measured():
    """Including them moves the number: measured on the real run's pacing_B, the
    Pearson correlation is +0.276 over all 18 slots and +0.160 over the 14 measured
    ones (design §0.4). The hole in the report biases the statistic that describes
    the report."""
    slots = (_slot(0, 0.0, 4.0, 0.5, beats_in=0), _slot(1, 4.0, 4.0, 0.2),
             _slot(2, 8.0, 3.0, 0.5), _slot(3, 11.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert (used, total, why) == (3, 4, "")
    assert rho == pytest.approx(-1.0)     # the three measured slots agree perfectly


def test_a_pre_slice_spine_is_included_rather_than_reported_unmeasurable():
    """beats_in == -1 means the count was not recorded, not that it was zero.
    Excluding every slot of an old spine would report "not measurable" for a spine
    that is merely unlabelled."""
    slots = (_slot(0, 0.0, 4.0, 0.2, beats_in=-1), _slot(1, 4.0, 3.0, 0.5, beats_in=-1),
             _slot(2, 7.0, 2.0, 0.9, beats_in=-1))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert (used, total, why) == (3, 3, "")
    assert rho == pytest.approx(-1.0)


def test_too_few_measured_slots_names_the_reason_instead_of_returning_zero():
    slots = (_slot(0, 0.0, 4.0, 0.5, beats_in=0), _slot(1, 4.0, 3.0, 0.5, beats_in=0),
             _slot(2, 7.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho is None and (used, total) == (1, 3)
    assert "1 of 3" in why and "needed to rank" in why


def test_a_constant_series_names_the_reason_instead_of_raising():
    """statistics.correlation raises StatisticsError on a constant input; the function
    owns that refusal rather than letting it escape into the report builder."""
    slots = (_slot(0, 0.0, 3.0, 0.5), _slot(1, 3.0, 3.0, 0.5), _slot(2, 6.0, 3.0, 0.5))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho is None and (used, total) == (3, 3)
    assert "no ordering to correlate" in why
```

And, for the driver's report, in `tests/lib/test_pacing.py` (or the file that
already exercises `scripts.pacing._report` — reuse it if one exists):

```python
def test_the_fit_report_states_the_energy_agreement_beside_the_verdict(tmp_path):
    beats = [i * 0.5 for i in range(40)]
    energy = [0.1] * 20 + [0.9] * 20
    spine, fit, rejected = pacing.fit_spine([4.0, 2.0], beats, energy, 1.0, 120.0,
                                            [(-0.25, 0.25)] * 2)
    md = scripts_pacing._report(spine, fit, rejected, "MUSIC.json", {})
    assert "- **Energy agreement:**" in md
    assert "A DESCRIPTION, not a verdict" in md
```

with `from scripts import pacing as scripts_pacing` at the top of the file — or
put this one test in a new `tests/lib/test_pacing_report.py` if importing the
driver into the library's test module creates an import clash with the
`from scripts.lib import pacing` already there.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_pacing.py -k "energy_agreement or fit_report" -v
```

Expected: FAIL — `AttributeError: module 'scripts.lib.pacing' has no attribute
'energy_agreement'`.

- [ ] **Step 3: Add `energy_agreement`**

`scripts/lib/pacing.py` — change the statistics import to:

```python
from statistics import correlation, fmean
```

Add after `_beat_energy`:

```python
AGREEMENT_MIN_SLOTS = 3   # Spearman over fewer than three ranked points describes
                          # nothing: with two, rho is +1 or -1 by construction.


def energy_agreement(slots: Sequence[Slot]) -> tuple[float | None, int, int, str]:
    """Spearman rho between a slot's DURATION and its music energy, over the slots
    whose energy was actually measured (design 2026-09-07 §6).

    Negative = shorter shots where the music is louder. Returns
    (rho, used, total, reason); `rho` is None exactly when `reason` is non-empty —
    never a silent 0.0, which would read as "no relationship" for a spine that was
    never measurable at all.

    A DESCRIPTION, not a verdict. No threshold has been measured: the only two real
    cuts on record are -0.571 (the reel that shipped) and +0.509 (the 18-episode cut
    it was cut down from), one shoot and one song, and nothing says where a line
    would go. Reporting only `dev` and `fits` made those two indistinguishable, which
    is the whole of retro R7.2.

    Ranked, not linear: the question is ordinal, and eight points do not support a
    fitted slope. statistics.correlation keeps this module's stdlib-only promise.

    beats_in == 0 slots are excluded — their energy is fit_spine's 0.5 fallback, and
    including them moves the number (on the real run's pacing_B, +0.276 over all 18
    slots against +0.160 over the 14 measured ones). beats_in == -1 is INCLUDED: it
    means the count was not recorded, not that it was zero, and excluding every slot
    of a pre-2026-09-07 spine would report "not measurable" for one that is merely
    unlabelled."""
    total = len(slots)
    usable = [s for s in slots if s.beats_in != 0]
    if len(usable) < AGREEMENT_MIN_SLOTS:
        return None, len(usable), total, (
            f"only {len(usable)} of {total} slots carry a measured energy, and "
            f"{AGREEMENT_MIN_SLOTS} are needed to rank")
    durs = [s.dur for s in usable]
    ens = [s.energy for s in usable]
    # correlation() raises StatisticsError when either input is constant, and under
    # method="ranked" that is exactly `len(set(...)) == 1`: ranking maps distinct
    # values to distinct ranks and ties to a shared one, so constant ranks means every
    # value was tied. Own the refusal here rather than let it escape into _report.
    if len(set(durs)) == 1 or len(set(ens)) == 1:
        return None, len(usable), total, (
            "every measured slot has the same duration or the same energy, so there "
            "is no ordering to correlate")
    return correlation(durs, ens, method="ranked"), len(usable), total, ""
```

`Sequence` is already imported at the top of the module
(`from collections.abc import Sequence`).

- [ ] **Step 4: Print it in the fit report**

`scripts/pacing.py`, at the top of `_report`:

```python
def _report(spine, fit, rejected, music_path: str, anchor_map: dict) -> str:
    rho, used, total, why = pacing.energy_agreement(spine.slots)
    agreement = (f"{rho:+.2f} (Spearman rho, {used} of {total} slots measured)"
                 if rho is not None else f"not computed — {why}")
    lines = ["# Pacing — fit report", "",
             f"- **Music:** `{Path(music_path).name}`",
             f"- **Level:** {fit.level} (every {fit.level_n} beat(s), phase {fit.phase})",
             f"- **Verdict:** {'fits' if fit.fits else 'OFF-GRID — see below'}",
             # `dev` and `fits` were the whole summary, and they cannot tell a
             # wrong-but-aligned cut from a right one: the run's shipped spine and the
             # 18-episode cut it came from both fit, and differ by 1.08 in this number
             # (design 2026-09-07 §0.3).
             f"- **Energy agreement:** {agreement}",
             "  Negative = shorter shots where the music is louder. A DESCRIPTION, not "
             "a verdict — no threshold has been measured (design 2026-09-07 §7).",
             "",
             "| level | step | worst | needed | verdict |",
             "|-------|-----:|------:|-------:|---------|"]
```

The rest of `_report` is unchanged.

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_pacing.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/pacing.py scripts/pacing.py tests/lib/test_pacing.py
git commit -m "$(cat <<'MSG'
feat: the pacing report says whether the cut agrees with the music's energy

`dev` and `fits` were the stage's entire summary, and they cannot tell a
wrong-but-aligned cut from a right one. The only real run has both on disk: the
shipped 8-slot spine reports dev 0.0 on every slot at Spearman -0.571 (shorter
shots where the music is louder), and the 18-episode cut it was trimmed from also
fits, at +0.509 — inverted. Nothing anywhere printed either number.

Spearman rather than Pearson: eight to eighteen points, and the question is
ordinal. statistics.correlation(method="ranked") keeps lib/pacing.py's
stdlib-only promise.

Computed over measured slots only. Including the beats_in == 0 fallbacks moves
it — on pacing_B, +0.276 over all 18 slots against +0.160 over the 14 measured —
so the hole Slot.beats_in names is the same hole that biases this statistic.

Reported, never gated: the two cuts above are one shoot and one song, and nothing
on record says where a line would go.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 8: mutation battery, full suite, version bump, docs

**Files:**
- Modify: `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`,
  `CLAUDE.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`
- No production code changes unless the battery finds a hole.

**Interfaces:** none — this task consumes every earlier one.

- [ ] **Step 1: Run the full suite on the branch tip**

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -20
```

Expected: green. Record the exact `N passed, M skipped` line — the build-status
entry quotes it. The pre-branch baseline is `3455 passed, 1 skipped`.

- [ ] **Step 2: Run the 12-row mutation battery**

Every row: apply the edit, run **only** the named test selection, record RED or
GREEN, then restore with `git show HEAD:<path> > <path>` and confirm
`git diff --stat` is empty before the next row. Every command runs under
`PYTHONDONTWRITEBYTECODE=1`.

| # | file | mutation | must fail |
|--:|---|---|---|
| 1 | `scripts/check_reel.py` | move `worst`/`worst_pair` assignment back inside `if dist < spec.variety_min:` | `tests/lib/test_check_reel.py -k nearest_pair` |
| 2 | `scripts/check_reel.py` | drop `"min": spec.variety_min` from the variety detail | `tests/lib/test_check_reel.py -k "nearest_pair or global_minimum"` |
| 3 | `scripts/lib/outro.py` | return the shared `unchanged` from the `if not bars` branch instead of `replace(..., cause="no-bars")` | `tests/lib/test_outro.py -k different_causes` |
| 4 | `scripts/lib/outro.py` | delete the `elif self.cause:` arm of the validation | `tests/lib/test_outro.py -k cause_beside_a_chosen_rung` |
| 5 | `scripts/lib/outro.py` | make `from_dict` read `cause=d["cause"]` instead of `.get("cause", "")` | `tests/lib/test_outro.py -k before_this_slice` |
| 6 | `scripts/edit_plan.py` | make the empty-cut arm return `cause="no-bars"` | `tests/lib/test_edit_plan.py -k empty_cut` |
| 7 | `scripts/check_reel.py` | hardcode the outro reason back to the old sentence | `tests/lib/test_check_reel.py -k outro_check` |
| 8 | `scripts/lib/edl.py` | drop the `brief_len <= 0` clause from the validation | `tests/lib/test_edl.py -k non_positive_brief` |
| 9 | `scripts/check_reel.py` | change `budget` to `_LENGTH_TOL` alone | `tests/lib/test_check_reel.py -k inside_the_budget` |
| 10 | `scripts/check_reel.py` | make `passed` key on `gap >= -budget` (short-only, mirroring the borrowed asymmetry) | `tests/lib/test_check_reel.py -k over_and_under` |
| 11 | `scripts/lib/pacing.py` | make `fit_spine` pass `beats_in=len(inside) or 1` | `tests/lib/test_pacing.py -k fallback` |
| 12 | `scripts/lib/pacing.py` | make `energy_agreement` filter on `s.beats_in > 0` instead of `!= 0` | `tests/lib/test_pacing.py -k pre_slice_spine` |

A GREEN row is a coverage hole: write the test that discriminates it, then re-run
the row. Record the outcome of every row — including the ones that needed a new
test — in the task's report.

- [ ] **Step 3: Bump the version**

The judgement, per
[docs/development-workflow.md §Versioning](../development-workflow.md#versioning):
**PATCH → 0.8.1**. This branch adds no stage, no flag, no renamed signature, and
no changed default that alters output; `check_reel.run` gains one keyword with a
default, and `ReelReport.overall` cannot move. Run-dir separation (0.2.1) is the
worked precedent — it moved where every artifact lands and was still a PATCH.

Edit `.claude-plugin/plugin.json` to `"version": "0.8.1"` and add the matching
top entry to `CHANGELOG.md` in the file's existing format.
`tests/test_plugin_manifests.py` asserts the two agree.

- [ ] **Step 4: Close the three backlog rows**

Move R7.1 and R7.2 out of `docs/backlog.md`'s P1 table and R6.1 out of P2, into
`docs/backlog-closed.md` under their existing `## Closed from P1` / `## Closed
from P2` sections, each with a closure note that records **what the row's own
premise got wrong** — that is the archive's whole purpose:

- **R7.1** — the "22% short" half of the row was already reported: `EDL.md` has
  printed the distance from the brief since 2026-08-18. What was missing was that
  no gate compared them at all, because `check_reel.length` measures against
  `target_dur`, which came from the cut.
- **R7.2** — the row's two claims belong to two different files. `dev: 0.0` on
  all 8 slots is the shipped spine, whose ρ is −0.571, the *correct* direction;
  the inversion (+0.509) is `pacing_A`, the 18-episode cut it was trimmed from.
  Both real. And the row never named the defect that most resembles its own
  title: `energy: 0.5` as an unflagged sentinel.
- **R6.1** — confirmed as filed, plus a second defect it did not name: the
  failing path reported the minimum over failing pairs, not the global minimum.

- [ ] **Step 5: File the two rows this branch deliberately did not close**

Add to `docs/backlog.md` P3, under **Music**:

```
rank candidate music windows on energy agreement, not only grid quality —
`build_pacing` picks the winner with `(fit.level_n if fit.fits else 0, -fit.worst)`
and nothing in that tuple sees whether the window's energy arc matches the cut's
rhythm, which is the stage's one real choice. Deferred on evidence, not doubt: the
only A/B pair on disk agrees on both criteria (window A wins the grid AND the
agreement), so any weighting between them would be typed rather than measured
(named-absence §1, §7) ·
a window whose beats start well into the reel is accepted — `pacing_B`'s first beat
is at 9.74s, its slot 0 carries `dev: 7.14`, and `build_pacing` neither refuses it
nor ranks it down; `Slot.beats_in` now makes the resulting hole visible in the
report, which is the whole of what this slice did about it (named-absence §7)
```

- [ ] **Step 6: Add the build-status entry and the registry rows**

Append a `## Done` entry at the top of `docs/build-status.md` titled
**"A measurement survives a pass — three reports stop collapsing an absence
(2026-09-07)"**, recording: the four `bars: []` windows; `EDL.outro`'s
`brief_len: 45.0` beside `reel_dur: 34.93`; the five producers of one
byte-identical `unchanged`; the three spines' Spearman values
(−0.571 / +0.509 / +0.484); `pacing_B`'s four `energy: 0.500` slots against a
first beat at 9.7387s; the +0.276 → +0.160 bias the sentinel puts on the
statistic; §2.1's proof that the variety fail path cannot move; and the battery's
result. Set `_Last updated: 2026-09-07._`.

Add two rows to `CLAUDE.md`'s Quick Reference table, in the same format as its
neighbours — one for
`docs/specs/2026-09-07-named-absence-design.md` and one for
`docs/plans/2026-09-07-named-absence.md`.

- [ ] **Step 7: Re-run the full suite and commit**

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -5
```

```bash
git add -A
git commit -m "$(cat <<'MSG'
docs: 0.8.1 — a measurement survives a pass, and an absence is named

Closes R7.1, R7.2 and R6.1, and records what two of the three rows got wrong.

R7.1's "22% short" half was already reported — EDL.md has printed the distance
from the brief since 2026-08-18. The real hole was that nothing compared them at
any gate, because check_reel's length check measures against target_dur, which
came from the cut.

R7.2's two claims belong to two different files, and both are real: dev 0.0 on
all 8 slots is the shipped spine, whose Spearman is -0.571 — the correct
direction — while the inversion (+0.509) is the 18-episode cut it was trimmed
from. The row never named the defect closest to its own title: energy 0.5 as an
unflagged sentinel for "no beat fell in this slot".

R6.1 was confirmed as filed, and carried a second defect it did not name: the
failing path reported the minimum over failing pairs, not the global minimum.

Two rows filed rather than closed: ranking candidate music windows on energy
agreement (deferred on evidence — the only A/B pair on disk agrees on both
criteria, so a weighting would be typed), and accepting a window whose beats
start 9.74s into the reel.

PATCH, not MINOR: no stage, no flag, no renamed signature, no changed default.
check_reel.run gains one defaulted keyword and ReelReport.overall cannot move.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Self-Review

**Spec coverage.** §2 → Task 1. §3 + §3.1 → Tasks 2 and 3. §4.1 → Task 4;
§4.2/§4.3 → Task 5. §5 → Task 6. §6 → Task 7. §7's filed rows → Task 8 Step 5.
§8's "what this does not touch" is enforced by the Global Constraints' first
bullet and by Task 5's `test_brief_length_is_advisory_and_cannot_block`.

**Placeholder scan.** Tasks 3, 4 and 5 tell the implementer to reuse the
fixtures each test file already has rather than reproducing them; every assertion
and every value is given in full, and the fixtures exist in the tree today. No
step says "add validation", "handle edge cases" or "similar to Task N". The one
place a step describes rather than shows is Task 8 Step 6's build-status entry,
which lists the exact measurements the prose must contain.

**Type consistency.** `energy_agreement` returns `(float | None, int, int, str)`
in Task 7's interface block, its docstring, its implementation and all six of its
tests. `Slot.beats_in` is `int` with sentinel `-1` in Tasks 6 and 7.
`OutroFit.cause` is `str` with sentinel `""` in Tasks 2 and 3.
`EDL.brief_len` / `ReelManifest.brief_len` are `float | None` in Tasks 4 and 5.
`CAUSE_WHY` is keyed by cause and read by both `edl.py` and `check_reel.py`.
