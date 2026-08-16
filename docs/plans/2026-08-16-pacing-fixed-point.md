# Pacing Fixed Point Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pacing`'s fit-then-apply round trip a fixed point by recording the
scenario's own episode lengths, bind a spine to the music window it was fitted to, and
stop `build_reel`'s length absorb from silently overwriting a length the outro fit chose.

**Architecture:** `EDLEpisode` gains `base_dur` — the footage-projected source length,
written once by `window_to_episode` and never rewritten. Everything that asks "what did
the scenario say" (`pacing.build_pacing`, `pacing._bounds`,
`edit_plan._bind_pacing`'s half-beat guard) reads it instead of the already-bound `dur`,
which makes the spine a function of `(base, music)` alone. `Spine` gains `music_digest`,
an identity for the analysed *window* rather than the tempo proxy. `ReelManifest` carries
`EDL.outro` so `reel_orchestration.next_action` can refuse a within-band absorb when the
target was chosen as `line + fade`, and `check_reel` reports the residual as an advisory.

**Tech Stack:** Python 3.11 stdlib + dataclasses; pytest; ffmpeg via `scripts/lib/ffbin`
(not needed by this slice's own proofs). No new dependencies.

**Design:** [docs/specs/2026-08-16-pacing-fixed-point-design.md](../specs/2026-08-16-pacing-fixed-point-design.md)

## Global Constraints

- **Python is `.venv/bin/python`**; scripts run as modules (`pythonpath = .` in
  `pyproject.toml`). Run tests as `.venv/bin/python -m pytest …` from the repo root.
- **Fail-loud contract** ([docs/coding-standards.md](../coding-standards.md)): every
  refusal is a `ValueError` (or the module's documented type) whose message names the
  bad value **and the remedy**. No silent fallbacks, no bare `except`.
- **Imports at the top of the file.** No function-local imports.
- **Config-specs validate in `__post_init__`.** A new field on a dataclass that is a
  config-spec (`Spine`, `ReelManifest`, `EDLEpisode`) gets a validation branch and a
  round-trip through `to_dict`/`from_dict`.
- **A new optional field must default to today's behaviour.** `base_dur=None`,
  `music_digest=""`, `outro=None` and `outro_fixed=False` each reproduce the pre-slice
  path exactly, because the hand-authored `edl_to_reel` front door and every artifact
  written before this slice must keep working.
- **`not-checked` is a real outcome.** Where a check cannot discriminate — no digest, no
  readable track, no bar line chosen — say so by name. Never report "same" or "passed"
  for a measurement that did not run.
- **Whole-object asserts** ([docs/testing-guide.md](../testing-guide.md)): compare the
  whole dict / dataclass, not a field at a time, wherever the object is small enough.
- **Never `git checkout --` / `git restore` / `git reset --hard` / `git stash`.** Fix
  forward.
- **Do not install anything.** No `brew`, `pip install`, `npm`, no running `setup.sh`.
  Verification is read-only plus pytest.
- **Commit after each task** with a message that says *why*, not only *what*. Do not
  amend; a follow-up fix is a follow-up commit.

---

## File Structure

| File | Responsibility in this slice |
|---|---|
| `scripts/lib/edl.py` | `EDLEpisode.base_dur` + `base_play_dur()` — the scenario's length as a recorded fact |
| `scripts/edit_plan.py` | writes `base_dur`; the half-beat guard reads it; the digest ladder |
| `scripts/pacing.py` | fits `base_play_dur()`; bounds from `base_dur`; records `music_digest` |
| `scripts/lib/pacing.py` | `Spine.music_digest` + `music_identity()`, the one place a window's identity is computed |
| `scripts/lib/models.py` | `ReelManifest.outro`; `_ADVISORY_CHECKS` gains `"outro"` |
| `scripts/lib/reel_orchestration.py` | `next_action(..., outro_fixed=)` — the absorb's refusal |
| `scripts/build_reel.py` | derives `outro_fixed`, threads `outro` to `check_reel` |
| `scripts/edl_to_reel.py` | carries `EDL.outro` onto the `ReelManifest` |
| `scripts/check_reel.py` | the advisory `outro` residual |
| `tests/lib/test_pacing_fixed_point.py` | **new** — the fixed-point proof, real drivers, no ffmpeg |

---

## Task 0: `EDLEpisode.base_dur` and `base_play_dur()`

**Files:**
- Modify: `scripts/lib/edl.py` (the `EDLEpisode` dataclass, its `__post_init__`,
  `to_dict`, and a new method beside `play_dur`)
- Test: `tests/lib/test_edl.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `EDLEpisode.base_dur: float | None` (default `None`), serialized under the
  key `"base_dur"`; `EDLEpisode.base_play_dur() -> float`. Tasks 1, 2 and 6 read both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py`. The file already defines `_ep`, `_ramp_ep` and `RAMP`
near the top and at line ~808 respectively — reuse them, do not redefine them.

```python
def test_base_dur_defaults_to_none_and_round_trips():
    assert _ep().base_dur is None
    assert _ep().to_dict()["base_dur"] is None
    d = _ep(base_dur=2.0).to_dict()
    assert d["base_dur"] == 2.0
    assert EDLEpisode(**d).base_dur == 2.0


def test_base_play_dur_falls_back_to_play_dur_without_a_base():
    # A hand-authored SP1 EDL has no scenario behind it: `dur` IS the intent.
    ep = _ramp_ep()
    assert ep.base_dur is None
    assert ep.base_play_dur() == ep.play_dur() == 4.0


def test_base_play_dur_is_the_base_when_there_is_no_ramp():
    ep = _ramp_ep(dur=4.25, base_dur=4.0)
    assert ep.play_dur() == 4.25
    assert ep.base_play_dur() == 4.0


def test_base_play_dur_adds_the_same_ramp_extra_a_base_length_episode_would_have():
    # The whole point of the subtraction: ramp_extra is constant in dur while the
    # region stays enclosed, so base_play_dur() on a BOUND episode equals play_dur()
    # on a fresh episode cut to the base length.
    bound = _ramp_ep(dur=4.25, base_dur=4.0, ramp=RAMP)
    fresh = _ramp_ep(dur=4.0, ramp=RAMP)
    assert bound.base_play_dur() == pytest.approx(fresh.play_dur())
    assert bound.base_play_dur() != pytest.approx(bound.play_dur())


def test_base_dur_survives_the_replace_the_pacing_binding_uses():
    ep = _ep(dur=2.0, base_dur=2.0)
    assert dataclasses.replace(ep, dur=2.2, beat_slot=1).base_dur == 2.0


@pytest.mark.parametrize("bad", [0, -1.0, True, "4.0"])
def test_base_dur_refuses_a_non_positive_or_non_number(bad):
    with pytest.raises(ValueError, match="base_dur must be a positive number"):
        _ep(base_dur=bad)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -k base -v`
Expected: FAIL — `TypeError: EDLEpisode.__init__() got an unexpected keyword argument
'base_dur'` on every case.

- [ ] **Step 3: Add the field**

In `scripts/lib/edl.py`, immediately after the `beat_slot` field of `EDLEpisode`:

```python
    base_dur: float | None = None    # the footage-projected SOURCE length, before any
                                     # pacing snap or outro move (design 2026-08-16 §2).
                                     # Written once by edit_plan.window_to_episode and
                                     # never rewritten: _bind_pacing and _apply_outro both
                                     # go through dataclasses.replace(ep, dur=...), which
                                     # carries this across untouched. Authoring metadata,
                                     # exactly like beat_slot and processing_notes —
                                     # extract, to_manifest_dict and check_reel never read
                                     # it, so it can never move a pixel. None = never
                                     # projected (a hand-authored SP1 EDL, or one written
                                     # before this slice); base_play_dur() then returns
                                     # play_dur(), the pre-slice behaviour exactly.
```

- [ ] **Step 4: Validate it**

In `EDLEpisode.__post_init__`, immediately after the existing `beat_slot` branch:

```python
        if self.base_dur is not None and (isinstance(self.base_dur, bool)
                                          or not isinstance(self.base_dur, (int, float))
                                          or self.base_dur <= 0):
            raise ValueError(
                f"EDLEpisode.base_dur must be a positive number of seconds or null — it is "
                f"the footage-projected length this episode had before any pacing snap; got "
                f"{self.base_dur!r}. Re-run edit_plan build to regenerate EDL.json")
```

- [ ] **Step 5: Serialize it**

In `EDLEpisode.to_dict`, extend the final line:

```python
                "color_means": list(self.color_means), "processing_notes": self.processing_notes,
                "beat_slot": self.beat_slot, "base_dur": self.base_dur}
```

`EDL.from_dict` constructs episodes with `EDLEpisode(**e)`, so no reader change is
needed: an old `EDL.json` simply has no `"base_dur"` key and falls to the default.

- [ ] **Step 6: Add `base_play_dur`**

In `scripts/lib/edl.py`, directly below `play_dur`:

```python
    def base_play_dur(self) -> float:
        """The PLAYED length the SCENARIO projected — what pacing fits its grid to, and
        what _bind_pacing's half-beat guard compares a slot against (design 2026-08-16
        §2.1).

        `base_dur` plus this episode's own ramp extra. The extra is `play_dur() - dur`
        and is CONSTANT in `dur` while the ramp region stays enclosed in the window
        (speed-ramp design §2) — the identity _bind_pacing already relies on when it
        writes `dur = slot.dur - extra` — so this is exact, not an approximation. The
        enclosure holds for `base_dur` too: __post_init__ validates the region against
        `dur`, and at construction `dur` IS `base_dur`; later binds move only `dur`.

        No base_dur -> play_dur(), i.e. the pre-slice behaviour exactly. A hand-authored
        SP1 EDL has no scenario behind it, so its `dur` IS the author's intent."""
        if self.base_dur is None:
            return self.play_dur()
        return self.base_dur + (self.play_dur() - self.dur)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -v`
Expected: PASS, whole file green (the existing `to_dict` whole-object asserts may need
`"base_dur": None` added — if one fails, add the key to the expected dict; do **not**
weaken the assert to a subset check).

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat(edl): record the scenario's own episode length as base_dur

pacing fits the durations it reads out of EDL.json, which are outputs of the
pacing binding and the outro fit rather than the scenario's own lengths — so
the stage fits its own previous output. Recording the projected length once,
where it is still the scenario's, is what lets every later reader ask the
question it actually means.

Authoring metadata only: extract, to_manifest_dict and check_reel never read
it. Absent (a hand-authored SP1 EDL, or one written before this slice)
base_play_dur() returns play_dur(), which is the pre-slice behaviour exactly."
```

---

## Task 1: `window_to_episode` writes it; the half-beat guard reads it

**Files:**
- Modify: `scripts/edit_plan.py` (`window_to_episode`'s `EDLEpisode(...)` construction,
  and `_bind_pacing`)
- Test: `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: `EDLEpisode.base_dur`, `EDLEpisode.base_play_dur()` (Task 0).
- Produces: every episode `edit_plan` projects carries `base_dur == window.dur`;
  `_bind_pacing` compares `slot.dur` against `ep.base_play_dur()`. Task 6's proof rests
  on both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`. Reuse whatever `FootageClip`/`FootageWindow`
helpers that file already defines; the snippets below construct them inline so the task
is self-contained — if the file has an equivalent factory, prefer it.

```python
def test_window_to_episode_records_the_projected_length():
    clip = FootageClip(source="a.mp4", dur=20.0, res=(640, 360), fps=30.0, windows=[
        FootageWindow(start=1.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds")
    assert ep.dur == 4.0
    assert ep.base_dur == 4.0


def test_base_dur_cannot_be_authored_from_selection():
    # `dur` is passed positionally and editorial is forwarded as **kwargs, so an
    # author trying to set either gets the same named refusal.
    clip = FootageClip(source="a.mp4", dur=20.0, res=(640, 360), fps=30.0, windows=[
        FootageWindow(start=1.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])
    with pytest.raises(ValueError, match="unknown or missing editorial field"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="lead",
                                    grid="thirds", base_dur=9.0)


def test_bind_pacing_accepts_a_slot_that_matches_the_SCENARIO_not_the_bound_length():
    # The deadlock, in one assert: an episode already grown 0.70s by an outro fit
    # binds against a spine fitted to its 4.00s scenario length. Half a beat at
    # 120 BPM is 0.25s, so the OLD guard (comparing 4.70 against 4.00) refused.
    ep = _ep(dur=4.70, base_dur=4.00)
    spine = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook", line=4.0, dev=0.0),),
                  target_dur=4.0, tempo=120.0)
    bound = edit_plan._bind_pacing([ep], spine)
    assert bound[0].dur == 4.0
    assert bound[0].base_dur == 4.0
    assert bound[0].beat_slot == 0


def test_bind_pacing_still_refuses_a_spine_fitted_to_a_different_edit():
    ep = _ep(dur=4.0, base_dur=4.0)
    spine = Spine(slots=(Slot(0, 0.0, 7.3, 0.5, "hook", line=7.3, dev=0.0),),
                  target_dur=7.3, tempo=120.0)
    with pytest.raises(ValueError, match="fitted to a different edit"):
        edit_plan._bind_pacing([ep], spine)


def test_bind_pacing_names_the_arm_when_an_episode_has_no_base_dur():
    ep = _ep(dur=4.70)                       # no base_dur: pre-slice or hand-authored
    spine = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook", line=4.0, dev=0.0),),
                  target_dur=4.0, tempo=120.0)
    with pytest.raises(ValueError, match="carries no `base_dur`"):
        edit_plan._bind_pacing([ep], spine)
```

`_ep` here must build a valid `EDLEpisode`; if `tests/lib/test_edit_plan.py` has no such
helper, add:

```python
def _ep(**kw):
    base = dict(source="a.mp4", start=0.0, dur=4.0, shot_type="wide",
                composition="lead", grid="thirds")
    return EDLEpisode(**{**base, **kw})
```

and make sure `EDLEpisode`, `Slot` and `Spine` are imported at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "base_dur or bind_pacing" -v`
Expected: FAIL — `assert ep.base_dur == 4.0` gets `None`; the deadlock test raises
`pacing: slot 0 is 4.00s against a 4.70s episode`; the arm-naming test raises the message
without the new sentence.

- [ ] **Step 3: Write the projection**

In `scripts/edit_plan.py`, `window_to_episode`'s return:

```python
    defaults = {"shot_type": window.shot_type, "processing_notes": window.description}
    try:
        # base_dur is the projection's own answer, recorded where it is still the
        # SCENARIO's length — before any pacing snap or outro move touches `dur`
        # (design 2026-08-16 §2). Passed positionally alongside `dur` rather than
        # through `defaults`, so an author who tries to set it in selection.json
        # collides and gets the "unknown or missing editorial field" refusal.
        return EDLEpisode(source=clip.source, start=start, dur=window.dur,
                          base_dur=window.dur,
                          **{**defaults, **editorial})
    except TypeError as ex:
        raise ValueError(f"window_to_episode: unknown or missing editorial field — {ex}") from ex
```

- [ ] **Step 4: Move the guard onto the scenario's length**

Replace the body of the `for i in range(n)` loop in `_bind_pacing`:

```python
    for i in range(n):
        slot, ep = spine.slots[i], episodes[i]
        # PLAYED time on both sides, and the SCENARIO's played time on the episode
        # side: the spine was fitted to base_play_dur (scripts/pacing.py), so
        # comparing the already-bound length would refuse a correct re-apply by
        # exactly whatever the previous bind and the outro fit had added — the
        # deadlock recorded as design 2026-08-14 §11.8.
        played = ep.play_dur()
        want = ep.base_play_dur()
        if abs(slot.dur - want) > allow:
            arm = "" if ep.base_dur is not None else (
                " NOTE: this episode carries no `base_dur`, so the guard is comparing the "
                "BOUND length rather than the scenario's — the EDL was hand-authored through "
                "the SP1 front door, or written before the 2026-08-16 fixed-point slice. If "
                "it also carries an outro fit (a non-null `outro`), re-running pacing against "
                "it LOOPS: rebuild the EDL WITHOUT --pacing first, re-run pacing against THAT "
                "EDL.json, then re-apply with --pacing --music")
            raise ValueError(
                f"pacing: slot {i} is {slot.dur:.2f}s against a {want:.2f}s episode — "
                f"further apart than the {allow:.2f}s snap allows, so this PACING.json "
                f"was fitted to a different edit. Re-run pacing against the current "
                f"EDL.json before binding.{arm}")
        # Assign the SOURCE window that plays for slot.dur. ramp_extra is constant
        # in dur while the region stays enclosed (design §2), so this is exact
        # rather than a solve — and dataclasses.replace re-runs __post_init__, so a
        # shrink that ate into the region raises instead of passing quietly.
        extra = played - ep.dur
        bound.append(dataclasses.replace(ep, beat_slot=i, dur=slot.dur - extra))
```

Also update `_bind_pacing`'s docstring: the second paragraph currently says "episode i's
`play_dur()` … takes slot i's duration". Replace that paragraph with:

```
    """Apply a FITTED spine: episode i's PLAYED length takes slot i's duration, and the
    episode gets `beat_slot=i`.

    The guard compares the slot against `base_play_dur()` — the length the SCENARIO
    projected — not against the length a previous bind or outro fit left behind. That is
    what makes fit-then-apply a fixed point (design 2026-08-16 §3.1): the spine is a
    function of (base, music), the bound `dur` is a function of (spine, ramp extra), and
    neither reads the previous run's output.

    A slot may differ from its episode's scenario length only by the snap the fit was
    allowed — half a beat. A larger difference means this spine was fitted to a DIFFERENT
    edit, and copying its length across would truncate a shot exactly the way the
    generator used to: a 7.3s ride into a 4.6s slot, in silence. Refuse instead.

    Zip-to-min; an over/underflow is logged, never a silent drop (§4.1)."""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py tests/lib/test_edl.py -v`
Expected: PASS. Some existing `edit_plan` tests assert a whole projected episode dict —
add `"base_dur": <the window's dur>` to those expectations rather than loosening them.

- [ ] **Step 6: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "fix(edit-plan): the half-beat guard judges the scenario's length, not the bound one

The guard exists to catch a spine fitted to a DIFFERENT edit. Comparing it
against the already-bound dur made it fire on a correctly re-applied spine
too: after an outro fit the closing episode is a length footage re-projection
cannot reproduce, so re-applying deadlocked (music-outro-fit §11.8). Comparing
against base_play_dur() keeps the guard pointed at what it was built for.

An episode with no base_dur keeps today's behaviour and the refusal now names
that arm, so a reader can tell 'the fix does not apply here' from 'the fix
failed'."
```

---

## Task 2: `pacing` fits the scenario's own lengths

**Files:**
- Modify: `scripts/pacing.py` (`_bounds`, `build_pacing`)
- Test: `tests/lib/test_pacing_driver.py`

**Interfaces:**
- Consumes: `EDLEpisode.base_dur`, `EDLEpisode.base_play_dur()` (Task 0).
- Produces: `build_pacing` fits `[ep.base_play_dur() …]`; `_bounds` derives room and
  shrink from `base_dur`. No signature changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_pacing_driver.py`. The first test is the drift regression pin —
it uses `pacing_lib.fit_spine` directly, mirroring the measurement in design §1.2, and
does **not** need the driver.

```python
def _grid(bpm, n=400):
    return [i * 60.0 / bpm for i in range(n)]


def _fit(durs, bpm):
    spine, _f, _r = pacing_lib.fit_spine(durs, _grid(bpm), [0.5] * 800, 2.0, bpm,
                                         [(-2.0, 2.0)] * len(durs))
    return [round(s.dur, 4) for s in spine.slots], [s.line for s in spine.slots]


def test_refitting_an_already_fitted_edit_lands_on_different_beats():
    # design §1.2, the measurement this slice exists to remove. Kept as a pin on
    # fit_spine itself: the function is NOT idempotent across windows, and it does
    # not have to be — the fix is that nobody feeds it its own output any more.
    scenario = [5.77, 3.41, 6.02, 4.88]
    fitted_to_128, _ = _fit(scenario, 128.0)
    assert fitted_to_128 == [5.625, 3.2812, 6.0938, 4.88]
    from_fitted, lines_a = _fit(fitted_to_128, 110.0)
    from_scenario, lines_b = _fit(scenario, 110.0)
    beat = 60.0 / 110.0
    assert [round(x / beat) for x in lines_a[:-1]] == [10, 16, 27]
    assert [round(x / beat) for x in lines_b[:-1]] == [11, 17, 28]
    assert round(sum(from_fitted) - sum(from_scenario), 4) == -0.5455
```

The remaining tests exercise the driver. `build_pacing` needs an `EDL.json`, a
`FOOTAGE.json` and a `MUSIC.json` on disk; write them with the contracts directly.

> **The fixture needs TWO episodes, and this is not cosmetic.** `fit_spine` gives the
> LAST slot `line=None` and `dev=0.0` — the tail's out-point is the reel's end, not a
> cut, so it is never snapped. A one-episode spine therefore reproduces its input
> duration exactly, whatever it was fed, and a one-episode version of these tests would
> pass with the fix reverted. Measured while writing this plan: `fit_spine([4.25], …)`
> returns `[4.25]`, not `[4.5]`.
>
> The numbers below are measured, not guessed: at 120 BPM (beat 0.5s, allowance 0.25s)
> `fit_spine([4.0, 3.0])` → `[4.0, 3.0]`, target 7.0; `fit_spine([4.4, 3.0])` →
> `[4.5, 3.0]`, target 7.5. `4.4` is used rather than `4.25` deliberately: 4.25 is
> exactly equidistant from the 4.0 and 4.5 lines, and a test that turns on a tie is a
> test that will flip on an unrelated float change.

```python
def _edl_json(tmp_path, *, dur, base_dur, source="a.mp4"):
    """Two episodes: the first out-point is a real CUT the grid can snap, the second
    is the tail, which fit_spine never snaps (line=None). A single-episode EDL would
    make every assertion below vacuous."""
    def ep(d, b):
        return EDLEpisode(source=source, start=0.0, dur=d, base_dur=b,
                          shot_type="wide", composition="lead", grid="thirds")
    p = tmp_path / "EDL.json"
    write_edl(EDL(episodes=(ep(dur, base_dur), ep(3.0, 3.0 if base_dur else None))), p)
    return str(p)


def _footage_json(tmp_path, *, source="a.mp4", clip_dur=20.0, window_dur=4.0):
    f = Footage(clips=[FootageClip(source=source, dur=clip_dur, res=(640, 360), fps=30.0,
                                   windows=[FootageWindow(start=0.0, dur=window_dur,
                                                          shot_type="wide", people=1,
                                                          motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _music_json(tmp_path, tempo=120.0, duration=20.0, track=None):
    # The beat count is DERIVED from the window, never hardcoded: MusicSpec refuses a
    # beat outside [0, duration], and at 110 BPM a hardcoded 40 beats overruns a 20s
    # window ("has 20.18… outside [0, 20.0]").
    if track is None:
        track = tmp_path / "t.wav"
        track.write_bytes(b"not really audio, only hashed")
    step = 60.0 / tempo
    ms = MusicSpec(track=str(track), start_offset=0.0, duration=duration, tempo=tempo,
                   beats=tuple(i * step for i in range(int(duration / step))),
                   energy=(0.3,) * 10, energy_hz=2.0)
    p = tmp_path / "MUSIC.json"
    p.write_text(json.dumps(ms.to_dict()))
    return str(p)


def test_build_pacing_fits_the_scenario_length_not_the_bound_one(tmp_path):
    # The opening episode was bound to 4.4 and the scenario said 4.0. At 120 BPM the
    # grid has a line at exactly 4.0, so a spine fitted to the scenario needs no shift
    # at all — while one fitted to 4.4 snaps up to 4.5.
    edl = _edl_json(tmp_path, dur=4.4, base_dur=4.0)
    res = pacing_driver.build_pacing(edl, _footage_json(tmp_path),
                                     [_music_json(tmp_path)], str(tmp_path / "out"))
    assert [s.dur for s in res["spine"].slots] == [4.0, 3.0]
    assert res["spine"].target_dur == 7.0


def test_build_pacing_falls_back_to_the_bound_length_without_a_base(tmp_path):
    edl = _edl_json(tmp_path, dur=4.4, base_dur=None)
    res = pacing_driver.build_pacing(edl, _footage_json(tmp_path),
                                     [_music_json(tmp_path)], str(tmp_path / "out"))
    assert [s.dur for s in res["spine"].slots] == [4.5, 3.0]
    assert res["spine"].target_dur == 7.5


def test_the_grow_bound_is_measured_from_the_scenario_length(tmp_path):
    # room_after(0.0) is 4.1s, and the scenario window is 4.0 -> 0.1s of grow room.
    # Reading the BOUND 4.4 instead would compute a NEGATIVE room and clamp to 0,
    # forbidding a growth the shot actually has.
    edl = _edl_json(tmp_path, dur=4.4, base_dur=4.0)
    footage = _footage_json(tmp_path, clip_dur=4.1)
    lo, hi = pacing_driver._bounds(EDL.from_json(edl), Footage.from_json(footage), 0.25)[0]
    assert (round(lo, 4), round(hi, 4)) == (-0.25, 0.1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_driver.py -k "scenario or fitted or grow_bound" -v`
Expected: FAIL — `test_build_pacing_fits_the_scenario_length_not_the_bound_one` returns
`[4.5, 3.0]` because the fit reads `play_dur()`, and `_bounds` returns `hi == 0.0`.
`test_build_pacing_falls_back_to_the_bound_length_without_a_base` PASSES already, and
must: it pins the arm this slice does **not** change. The
`refitting_an_already_fitted_edit` pin also passes already — it pins `fit_spine`'s own
behaviour, which this slice does not touch either.

- [ ] **Step 3: Fit the scenario's lengths**

In `scripts/pacing.py`, `build_pacing`:

```python
    # The SCENARIO's played lengths, not what a previous bind or outro fit left in
    # EDL.json. Reading play_dur() here made the stage fit its own previous output:
    # a re-fit against a different window landed every cut a beat early, and after an
    # outro fit the re-apply deadlocked outright (design 2026-08-16 §1). base_play_dur()
    # falls back to play_dur() for a hand-authored SP1 EDL, which has no scenario.
    durs = [ep.base_play_dur() for ep in edl.episodes]
```

- [ ] **Step 4: Measure the bounds from the same length**

In `scripts/pacing.py`, `_bounds`, replace the loop body's tail:

```python
        room = clip.room_after(ep.start)
        # The SCENARIO's source length, for the same reason build_pacing fits the
        # scenario's played length: the room a cut may grow into is a property of the
        # shot and the scenario's out-point, not of whatever a previous bind left behind.
        base = ep.base_dur if ep.base_dur is not None else ep.dur
        spec = None if ep.ramp is None else RampSpec.from_dict(ep.ramp)
        shrink = max(0.0, min(allow, base / 2.0, ramp_mod.tail_room(spec, base)))
        out.append((-shrink, min(allow, max(0.0, room - base))))
```

Update `_bounds`'s docstring first line to say "the room the episode's own shot still has
after the SCENARIO's out-point".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_driver.py tests/lib/test_pacing.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pacing.py tests/lib/test_pacing_driver.py
git commit -m "fix(pacing): fit the scenario's own lengths, not the stage's previous output

Measured on the real fit_spine: re-fitting an already-fitted edit against a
DIFFERENT music window lands every cut one beat early — beats 10/16/27 against
the scenario's 11/17/28, the whole reel 0.5455s short at 110 BPM. Not rounding:
from the scenario's 5.77s the 6.0s line is 0.23s away and inside the 0.2727s
allowance, but from the already-snapped 5.625s it is 0.375s away and out of
reach.

Changing the window is this stage's OWN recommended remedy when no level fits,
so the drift fired on the workflow the fit report asks for."
```

---

## Task 3: `Spine.music_digest` and the identity ladder

**Files:**
- Modify: `scripts/lib/pacing.py` (`Spine` field + validation + round trip, new
  `music_identity`), `scripts/pacing.py` (`build_pacing` records it),
  `scripts/edit_plan.py` (`build_edl`'s ladder)
- Test: `tests/lib/test_pacing.py`, `tests/lib/test_pacing_driver.py`,
  `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: nothing from Tasks 0–2.
- Produces: `Spine.music_digest: str` (default `""`), serialized under `"music_digest"`;
  `scripts.lib.pacing.music_identity(track: str, start_offset: float, duration: float)
  -> str` returning `""` when the track file cannot be read. `build_edl` refuses a
  mismatch and falls back to `_TEMPO_TOL` otherwise.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_pacing.py`:

```python
def test_spine_music_digest_defaults_to_empty_and_round_trips():
    s = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook"),), target_dur=4.0, tempo=120.0)
    assert s.music_digest == ""
    assert s.to_dict()["music_digest"] == ""
    s2 = dataclasses.replace(s, music_digest="abc")
    assert Spine.from_dict(s2.to_dict()) == s2


def test_spine_from_dict_accepts_a_pacing_json_written_before_the_digest():
    d = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook"),), target_dur=4.0, tempo=120.0).to_dict()
    d.pop("music_digest")
    assert Spine.from_dict(d).music_digest == ""


def test_spine_refuses_a_non_string_digest():
    with pytest.raises(ValueError, match="music_digest must be a string"):
        Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook"),), target_dur=4.0, tempo=120.0,
              music_digest=7)


def test_music_identity_separates_two_windows_of_the_same_track(tmp_path):
    t = tmp_path / "t.wav"
    t.write_bytes(b"same bytes both times")
    a = music_identity(str(t), 46.0, 42.0)
    b = music_identity(str(t), 147.772, 42.0)
    assert a and b and a != b
    assert music_identity(str(t), 46.0, 42.0) == a          # deterministic


def test_music_identity_is_empty_when_the_track_cannot_be_read(tmp_path):
    assert music_identity(str(tmp_path / "missing.wav"), 0.0, 42.0) == ""
```

In `tests/lib/test_pacing_driver.py` (reusing the `_edl_json` / `_footage_json` /
`_music_json` helpers added in Task 2):

```python
def test_build_pacing_records_the_music_window_identity(tmp_path):
    mj = _music_json(tmp_path)
    res = pacing_driver.build_pacing(_edl_json(tmp_path, dur=4.0, base_dur=4.0),
                                     _footage_json(tmp_path), [mj], str(tmp_path / "out"))
    m = MusicSpec.from_json(mj)
    assert res["spine"].music_digest == music_identity(m.track, m.start_offset, m.duration)


def test_build_pacing_says_so_when_the_track_cannot_be_hashed(tmp_path, capsys):
    mj = _music_json(tmp_path, track=tmp_path / "gone.wav")
    res = pacing_driver.build_pacing(_edl_json(tmp_path, dur=4.0, base_dur=4.0),
                                     _footage_json(tmp_path), [mj], str(tmp_path / "out"))
    assert res["spine"].music_digest == ""
    assert "records no music_digest" in capsys.readouterr().err
```

In `tests/lib/test_edit_plan.py`:

```python
def _spine(tempo=120.0, digest=""):
    return Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook", line=4.0, dev=0.0),),
                 target_dur=4.0, tempo=tempo, music_digest=digest)


def _music(tmp_path, tempo=120.0, offset=0.0, track=None):
    # Beat count DERIVED from the window: MusicSpec refuses a beat outside
    # [0, duration], and at 110 BPM a hardcoded 40 beats overruns a 20s window.
    if track is None:
        track = tmp_path / "t.wav"
        track.write_bytes(b"bytes")
    step = 60.0 / tempo
    return MusicSpec(track=str(track), start_offset=offset, duration=20.0, tempo=tempo,
                     beats=tuple(i * step for i in range(int(20.0 / step))),
                     energy=(0.3,) * 10, energy_hz=2.0)


def test_build_edl_refuses_a_spine_fitted_to_a_different_music_window(tmp_path):
    # SAME track, SAME tempo, different in-point: the tempo check cannot see this.
    m = _music(tmp_path, offset=147.772)
    stale = music_identity(m.track, 46.0, m.duration)
    with pytest.raises(ValueError, match="fitted to a different music window"):
        edit_plan.build_edl(_footage(tmp_path), _selection(), pacing=_spine(digest=stale),
                            music=m)


def test_build_edl_binds_when_the_window_identity_matches(tmp_path):
    m = _music(tmp_path)
    good = music_identity(m.track, m.start_offset, m.duration)
    edl = edit_plan.build_edl(_footage(tmp_path), _selection(), pacing=_spine(digest=good),
                              music=m)
    assert edl.episodes[0].beat_slot == 0


def test_build_edl_names_the_not_checked_arm_and_falls_back_to_tempo(tmp_path, capsys):
    m = _music(tmp_path, tempo=110.0)
    with pytest.raises(ValueError, match="belongs to a DIFFERENT track"):
        edit_plan.build_edl(_footage(tmp_path), _selection(), pacing=_spine(tempo=140.625),
                            music=m)
    err = capsys.readouterr().err
    assert "music identity not-checked" in err
    assert "records no music_digest" in err
```

`_footage(tmp_path)` and `_selection()` must produce a one-episode scenario whose window
is 4.0s long so the spine binds; build them from whatever factories
`tests/lib/test_edit_plan.py` already has, or add:

```python
def _footage(tmp_path, window_dur=4.0):
    return Footage(clips=[FootageClip(source="a.mp4", dur=20.0, res=(640, 360), fps=30.0,
                                      windows=[FootageWindow(start=0.0, dur=window_dur,
                                                             shot_type="wide", people=1,
                                                             motion=0.3, shake=0.0)])])


def _selection():
    return {"episodes": [{"source": "a.mp4", "window": 0,
                          "composition": "lead", "grid": "thirds"}]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing.py tests/lib/test_pacing_driver.py tests/lib/test_edit_plan.py -k "digest or identity or window" -v`
Expected: FAIL — `TypeError: Spine.__init__() got an unexpected keyword argument
'music_digest'`, and `ImportError: cannot import name 'music_identity'`.

- [ ] **Step 3: Add the field to `Spine`**

In `scripts/lib/pacing.py`, add to the `Spine` dataclass after `tempo`:

```python
    music_digest: str = ""   # identity of the analysed music WINDOW this spine was fitted
                             # to (design 2026-08-16 §4): music_identity() of the track
                             # file's own digest plus start_offset and duration. "" = not
                             # recorded — a PACING.json written before this slice, or one
                             # whose track file could not be read — and edit_plan then says
                             # so by name and falls back to comparing tempo, which cannot
                             # see a start_offset change at all.
```

In `__post_init__`, after the `tempo` branch:

```python
        if not isinstance(self.music_digest, str):
            raise ValueError(f"Spine.music_digest must be a string (the analysed music "
                             f"window's identity, or '' when it was not recorded), got "
                             f"{self.music_digest!r} — re-run pacing to regenerate PACING.json")
```

In `to_dict`:

```python
    def to_dict(self) -> dict:
        return {"target_dur": self.target_dur, "tempo": self.tempo,
                "music_digest": self.music_digest,
                "slots": [s.to_dict() for s in self.slots]}
```

In `from_dict`'s return — note it is **not** added to the required-key loop, so an old
`PACING.json` still loads:

```python
        return cls(slots=tuple(Slot.from_dict(s) for s in d["slots"]),
                   target_dur=d["target_dur"], tempo=d["tempo"],
                   music_digest=d.get("music_digest", ""))
```

- [ ] **Step 4: Add `music_identity`**

At the top of `scripts/lib/pacing.py`, add `from scripts.lib import gridfit, provenance`
(replacing the existing `from scripts.lib import gridfit`). Then, directly below the
`Spine` class:

```python
def music_identity(track: str, start_offset: float, duration: float) -> str:
    """Identity of an analysed music WINDOW — the digest a Spine records and edit_plan
    checks (design 2026-08-16 §4).

    The track file's CONTENT digest (so moving a run directory does not invalidate it)
    plus the window's own in-point and length. Both halves are load-bearing: `tempo`
    alone cannot tell two tracks at the same BPM apart, and neither tempo NOR a
    track-only digest can see the same track analysed at a different `start_offset`,
    which moves every reel-relative grid line while the BPM stays bit-identical.

    Returns "" when the track file cannot be read — a NAMED not-checked, never a
    coincidental match. The caller must say so and fall back rather than treat "" as
    agreement."""
    try:
        track_digest = provenance.digest_file(track)
    except OSError:
        return ""
    return provenance.digest_obj({"track": track_digest,
                                  "start_offset": float(start_offset),
                                  "duration": float(duration)})
```

- [ ] **Step 5: Record it in `build_pacing`**

In `scripts/pacing.py`, add `import dataclasses` at the top and
`from scripts.lib.pacing import music_identity` alongside the existing
`from scripts.lib import anchors, gridfit, pacing, ramp as ramp_mod`.

Carry the winning `MusicSpec` through the selection loop, then stamp the spine:

```python
    best = None
    for path in music_jsons:
        m = MusicSpec.from_json(path)
        bounds = _bounds(edl, footage, gridfit.allowance(m.tempo))
        spine, fit, rejected = pacing.fit_spine(durs, m.beats, m.energy, m.energy_hz,
                                                m.tempo, bounds)
        # Coarsest FITTING level wins; a window whose best level misses ranks below every
        # window that fits, and ties break on the smaller worst deviation.
        rank = (fit.level_n if fit.fits else 0, -fit.worst)
        if best is None or rank > best[0]:
            best = (rank, spine, fit, rejected, path, m)
    _rank, spine, fit, rejected, music_path, music = best
    # Bind the spine to the WINDOW it was fitted to, not merely to a BPM (design §4).
    digest = music_identity(music.track, music.start_offset, music.duration)
    if not digest:
        _log(f"pacing: {music.track!r} could not be read, so PACING.json records no "
             f"music_digest — edit_plan will fall back to comparing tempo, which cannot "
             f"see a start_offset change. That is a not-checked, not a 'same track'")
    spine = dataclasses.replace(spine, music_digest=digest)
```

- [ ] **Step 6: Run the ladder in `build_edl`**

In `scripts/edit_plan.py`, change the import at line 27 to
`from scripts.lib.pacing import Spine, music_identity`, then replace the unconditional
tempo check with the ladder:

```python
    if music is not None and pacing is not None:
        # Identity first, tempo only as a fallback rung (design 2026-08-16 §4.2). The
        # tempo proxy shipped a 140.625 BPM spine against a 110.294 BPM reel in the
        # 2026-08-03 run and no stage objected — but it also cannot see the SAME track
        # at a different start_offset, which moves every grid line.
        want = music_identity(music.track, music.start_offset, music.duration)
        if pacing.music_digest and want and pacing.music_digest != want:
            raise ValueError(
                f"pacing: this PACING.json was fitted to a different music window — it "
                f"records {pacing.music_digest[:12]}… and this MUSIC.json hashes to "
                f"{want[:12]}…. Equal tempo does not prove the same track, and the SAME "
                f"track at a different start_offset moves every grid line while the BPM "
                f"stays identical. Re-run pacing against this MUSIC.json before binding")
        if not (pacing.music_digest and want):
            why = ("this PACING.json records no music_digest (written before the "
                   "2026-08-16 fixed-point slice)" if not pacing.music_digest
                   else f"{music.track!r} could not be read")
            _log(f"pacing: music identity not-checked — {why}; falling back to the "
                 f"{_TEMPO_TOL} BPM tempo comparison, which cannot see a start_offset "
                 f"change")
            if abs(pacing.tempo - music.tempo) > _TEMPO_TOL:
                raise ValueError(
                    f"pacing: the spine was fitted at {pacing.tempo:.3f} BPM but this "
                    f"MUSIC.json is {music.tempo:.3f} BPM — further apart than the "
                    f"{_TEMPO_TOL} BPM two reads of one track can differ by, so this "
                    f"PACING.json belongs to a DIFFERENT track. Re-run pacing against "
                    f"this MUSIC.json before binding")
```

Delete the old `if music is not None and pacing is not None and abs(...) > _TEMPO_TOL:`
block it replaces. Update `build_edl`'s docstring paragraph about `_TEMPO_TOL` to describe
the ladder: identity when both sides have it, a named not-checked plus the tempo
comparison otherwise.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing.py tests/lib/test_pacing_driver.py tests/lib/test_edit_plan.py -v`
Expected: PASS. Existing tests that construct a `Spine` and compare `to_dict()` whole need
`"music_digest": ""` added.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/pacing.py scripts/pacing.py scripts/edit_plan.py \
        tests/lib/test_pacing.py tests/lib/test_pacing_driver.py tests/lib/test_edit_plan.py
git commit -m "feat(pacing): bind a spine to the music WINDOW it was fitted to

The 0.5 BPM tempo check was a proxy, and shadow-red-length-reconcile §6 said
so: equal tempo does not prove the same track. It also cannot see the second
hole — the SAME track analysed at a different start_offset. The beat grid is
reel-relative, so moving the in-point moves every line while the BPM stays
bit-identical, and beats --auto-start returning a different offset on a re-run
is routine.

music_identity() hashes the track's CONTENT plus the window's in-point and
length, so a moved run directory does not invalidate it. When either side is
missing the ladder says 'not-checked' by name and falls back to tempo rather
than reporting agreement it never measured."
```

---

## Task 4: the absorb refuses a chosen length

**Files:**
- Modify: `scripts/lib/models.py` (`ReelManifest.outro` + validation + round trip),
  `scripts/lib/reel_orchestration.py` (`next_action`), `scripts/build_reel.py`,
  `scripts/edl_to_reel.py`
- Test: `tests/lib/test_models.py`, `tests/lib/test_reel_orchestration.py`,
  `tests/lib/test_build_reel.py`, `tests/lib/test_edl_to_reel.py`

**Interfaces:**
- Consumes: nothing from Tasks 0–3.
- Produces: `ReelManifest.outro: dict | None`;
  `reel_orchestration.next_action(fail_reasons, attempts, cap, length_retime_max=0.0,
  outro_fixed=False)`; the escalate finding's `reason` is `"outro-length-chosen"` when the
  refusal fires. Task 5 reads `ReelManifest.outro` too.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_reel_orchestration.py`:

```python
def _length_fail(dur, target):
    return ReelFailure("length", "pacing", None, {"dur": dur, "target": target})


def test_a_within_band_shortfall_is_absorbed_without_an_outro():
    a = next_action([_length_fail(9.4, 10.0)], {}, 3, 1.0, False)
    assert (a.kind, a.retime) == ("retime", 9.4)


def test_a_within_band_shortfall_escalates_when_the_outro_chose_the_length():
    a = next_action([_length_fail(9.4, 10.0)], {}, 3, 1.0, True)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "outro-length-chosen"
    assert a.finding["escalate_to"] == "pacing"
    assert a.finding["detail"]["dur"] == 9.4
    assert "line + fade" in a.finding["detail"]["why"]


def test_a_past_the_band_shortfall_still_reads_not_auto_fixable_with_an_outro():
    # outro_fixed must not relabel a failure it did not cause.
    a = next_action([_length_fail(8.0, 10.0)], {}, 3, 1.0, True)
    assert a.finding["reason"] == "not-auto-fixable"


def test_an_over_length_reel_is_unchanged_by_outro_fixed():
    for fixed in (False, True):
        a = next_action([_length_fail(11.0, 10.0)], {}, 3, 1.0, fixed)
        assert a.finding["reason"] == "not-auto-fixable"
```

In `tests/lib/test_models.py`:

```python
def test_reel_manifest_outro_defaults_to_none_and_round_trips(reel_manifest_kwargs):
    rm = ReelManifest(**reel_manifest_kwargs)
    assert rm.outro is None
    assert rm.to_dict()["outro"] is None
    fit = OutroFit(reel_dur=10.7, line=10.2, fade=0.5, tail=1.8, rung="gap", moved=0.7)
    rm2 = ReelManifest(**{**reel_manifest_kwargs, "outro": fit.to_dict()})
    assert ReelManifest.from_dict(rm2.to_dict()).outro == fit.to_dict()


def test_reel_manifest_refuses_a_malformed_outro(reel_manifest_kwargs):
    # A bad rung must fail loud rather than read as "unchanged" and silently
    # restore the length absorb it exists to block.
    with pytest.raises(ValueError, match="rung must be one of"):
        ReelManifest(**{**reel_manifest_kwargs, "outro": {"reel_dur": 10.7, "rung": "nope"}})
    with pytest.raises(ValueError, match="ReelManifest.outro must be an object"):
        ReelManifest(**{**reel_manifest_kwargs, "outro": "gap"})
```

`reel_manifest_kwargs` must be whatever minimal valid kwargs the file already uses to
build a `ReelManifest`; if there is no such fixture, inline the same construction the
file's other `ReelManifest` tests use.

In `tests/lib/test_edl_to_reel.py`, extend or add a test asserting the manifest carries
the fit:

```python
def test_edl_to_reel_carries_the_outro_onto_the_reel_manifest(...):
    # Build the EDL with a "gap" outro, run edl_to_reel's manifest assembly, and
    # assert rm.outro == edl.outro.to_dict(). Follow whatever seam this file already
    # uses to reach the ReelManifest without rendering (the module's existing
    # manifest-assembly test is the template).
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_orchestration.py tests/lib/test_models.py -k "outro or absorb or band" -v`
Expected: FAIL — `next_action() takes from 3 to 4 positional arguments but 5 were given`,
and `ReelManifest.__init__() got an unexpected keyword argument 'outro'`.

- [ ] **Step 3: Add `ReelManifest.outro`**

In `scripts/lib/models.py`, add `from scripts.lib.outro import OutroFit` to the imports
(`lib/outro.py` imports only `collections.abc` and `dataclasses`, so there is no cycle),
then add the field after `look`:

```python
    outro: dict | None = None          # EDL.outro.to_dict() — the fit that CHOSE this
                                       # reel's length as line + fade (design 2026-08-16
                                       # §5). None = no fit ran, and build_reel's
                                       # within-band length absorb behaves exactly as
                                       # before.
```

In `__post_init__`, after the `look` branch:

```python
        if self.outro is not None:
            if not isinstance(self.outro, dict):
                raise ValueError(f"ReelManifest.outro must be an object (EDL.outro.to_dict()) "
                                 f"or None, got {type(self.outro).__name__} — edl_to_reel "
                                 f"builds it from EDL.outro")
            OutroFit.from_dict(self.outro)   # the shape/rung oracle. A malformed outro must
                                             # fail loud here, not read as "unchanged" and
                                             # silently restore the absorb it exists to block
```

In `from_dict`: `outro=d.get("outro"),`. In `to_dict`: `"outro": self.outro,`.

- [ ] **Step 4: Teach `next_action` the refusal**

In `scripts/lib/reel_orchestration.py`:

```python
def next_action(fail_reasons: list[ReelFailure], attempts: dict[int, int], cap: int,
                length_retime_max: float = 0.0, outro_fixed: bool = False) -> ReelAction:
```

and replace the `length` branch:

```python
        if f.check == "length":
            gap = _shortfall(f)
            absorbable = gap is not None and gap <= length_retime_max
            if absorbable and not outro_fixed:
                retime = f.detail["dur"]   # the reel IS this long — make it the target
                continue
            finding = {"reason": "not-auto-fixable", "check": f.check,
                       "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                       "detail": f.detail}
            if absorbable and outro_fixed:
                # The absorb's premise is "the reel IS that long, so the target was
                # wrong". False when the target was CHOSEN: with an outro fit,
                # target_dur is line + fade, a decision about where the music resolves.
                # mix fades over [master_dur - fade, master_dur], so absorbing keeps the
                # fade at the reel's end and moves the BAR LINE out from under it — and
                # length_retime_max (1.0s) is as wide as the 0.96s miss the outro slice
                # exists to fix (design 2026-08-16 §5).
                finding["reason"] = "outro-length-chosen"
                finding["detail"] = {**f.detail, "why": (
                    "the reel's length was CHOSEN by the outro fit as line + fade, so "
                    "absorbing this shortfall would move the fade off the bar line. Grow "
                    "or re-cut the closing episode — edit-plan and pacing own the "
                    "picture's length; the reel loop cannot invent picture")}
            return ReelAction("escalate", finding=finding)
```

Extend `next_action`'s docstring: `length` is auto-fixable in exactly one shape *and only
when the length was not chosen* — an outro-fitted reel escalates instead.

- [ ] **Step 5: Wire the drivers**

In `scripts/build_reel.py`, above the loop:

```python
    # A fit whose rung is "unchanged" chose nothing — the reel kept its footage-derived
    # length — so it must not block the absorb. .get with a default rather than [] : the
    # manifest's own validation already guarantees the key, and if that ever regresses,
    # degrading to today's behaviour beats stopping a deliverable reel.
    outro_fixed = (rm.outro is not None
                   and rm.outro.get("rung", "unchanged") != "unchanged")
```

and pass it:

```python
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap,
                                                spec.length_retime_max, outro_fixed)
```

In `scripts/edl_to_reel.py`, extend the `ReelManifest(...)` construction:

```python
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=note, music=music or edl.music, platform=edl.platform,
                      look=edl.look,
                      # the fit that chose this reel's length, so the reel loop can tell a
                      # CHOSEN length from a derived one (design 2026-08-16 §5)
                      outro=edl.outro.to_dict() if edl.outro is not None else None,
                      **extra)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_orchestration.py tests/lib/test_models.py tests/lib/test_build_reel.py tests/lib/test_edl_to_reel.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py scripts/lib/reel_orchestration.py scripts/build_reel.py \
        scripts/edl_to_reel.py tests/lib/test_models.py tests/lib/test_reel_orchestration.py \
        tests/lib/test_build_reel.py tests/lib/test_edl_to_reel.py
git commit -m "fix(reel): the length absorb must not overwrite a length the outro fit chose

The within-band absorb justifies itself as 'the reel IS that long, so the
target was wrong'. That premise is false when the target was CHOSEN: with an
outro fit, target_dur is line + fade, a decision about where the music
resolves. mix fades over [master_dur - fade, master_dur], so absorbing keeps
the fade at the reel's end and moves the bar line out from under it — and
length_retime_max is 1.0s, as wide as the 0.96s miss the whole outro slice
exists to fix.

Escalating is actionable rather than a dead end: edit-plan already computes how
far the closing shot can grow, and an over-length reel escalates the same way
for the same reason — the reel loop cannot invent picture."
```

---

## Task 5: the advisory `outro` residual

**Files:**
- Modify: `scripts/lib/models.py` (`_ADVISORY_CHECKS`), `scripts/check_reel.py`
  (`run`'s signature + the check), `scripts/build_reel.py` (thread it)
- Test: `tests/lib/test_check_reel.py`, `tests/lib/test_models.py`

**Interfaces:**
- Consumes: `ReelManifest.outro` (Task 4).
- Produces: `check_reel.run(..., outro: dict | None = None)`; `report.checks["outro"]`
  with detail keys `line`, `fade`, `rung`, `asked`, `delivered`, `residual`, `tol`,
  `advisory`, or the `n/a` form.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_models.py`:

```python
def test_a_failing_outro_residual_does_not_block_overall():
    r = ReelReport(checks={"length": CheckResult("length", True, {}),
                           "outro": CheckResult("outro", False, {"residual": -0.8})})
    assert r.overall is True
```

In `tests/lib/test_check_reel.py`, alongside the file's existing `run` tests (follow its
established way of stubbing the probes — do not add real ffmpeg here):

```python
GAP = {"reel_dur": 10.7, "line": 10.2, "fade": 0.5, "tail": 1.8,
       "rung": "gap", "moved": 0.7, "brief_len": None}


def test_no_outro_key_at_all_when_no_fit_ran(<the file's run harness>):
    report = <run with outro=None, master 10.7s>
    assert "outro" not in report.checks


def test_an_unchanged_rung_reports_n_a_not_a_measurement(<harness>):
    report = <run with outro={**GAP, "rung": "unchanged", "line": None}, master 10.7s>
    assert report.checks["outro"].passed is None
    assert report.checks["outro"].detail["status"] == "n/a"


def test_the_residual_is_the_master_against_the_length_the_fit_asked_for(<harness>):
    report = <run with outro=GAP, master 10.68s>
    assert report.checks["outro"].detail["asked"] == 10.7
    assert report.checks["outro"].detail["delivered"] == 10.68
    assert report.checks["outro"].detail["residual"] == -0.02
    assert report.checks["outro"].passed is True


def test_a_residual_past_the_reporting_tolerance_is_flagged_but_advisory(<harness>):
    report = <run with outro=GAP, master 9.9s>
    assert report.checks["outro"].passed is False
    assert report.overall is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_models.py -k outro -v`
Expected: FAIL — `run() got an unexpected keyword argument 'outro'`, and the
`ReelReport.overall` test fails because `"outro"` is not advisory yet.

- [ ] **Step 3: Widen the advisory list**

In `scripts/lib/models.py`:

```python
_ADVISORY_CHECKS = ("beat", "safe_zones", "key_action", "pad_bars", "transitions", "outro")   # measured + reported but non-blocking (design §5)
```

- [ ] **Step 4: Add the check**

In `scripts/check_reel.py`, extend `run`'s signature:

```python
def run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str,
        music: MusicSpec | None = None, audio: str | None = None,
        geometry: list[tuple[str, str, str]] | None = None, platform: str = "",
        outro: dict | None = None) -> ReelReport:
```

and add the check immediately after the `beat` check (`total` is already in hand, so this
costs no extra I/O):

```python
    if outro is not None:
        # OUTRO — advisory. Three states, each named. No key at all means no fit ever
        # ran; "n/a" means a fit ran and chose nothing; a measurement means a bar line
        # was chosen and this is how far the delivered master sits from line + fade
        # (design 2026-08-16 §6). mix fades over [master_dur - fade, master_dur], so
        # this residual IS the distance between the fade's start and the bar line.
        # `passed` keys on the length gate's own _LENGTH_TOL — a REPORTING boundary
        # borrowed from a neighbouring check, not a claim about when an ending stops
        # resolving. Nobody has measured that, and inventing it here would be
        # inventing TAIL_MIN a second time.
        if outro.get("rung", "unchanged") == "unchanged":
            checks["outro"] = CheckResult("outro", None, {
                "status": "n/a", "reason": "the fit chose no bar line (rung 'unchanged')",
                "advisory": True})
        else:
            asked = float(outro["reel_dur"])
            residual = total - asked
            checks["outro"] = CheckResult("outro", abs(residual) <= _LENGTH_TOL, {
                "line": outro.get("line"), "fade": outro.get("fade"),
                "rung": outro.get("rung"), "asked": round(asked, 3),
                "delivered": round(total, 3), "residual": round(residual, 3),
                "tol": _LENGTH_TOL, "advisory": True})
```

- [ ] **Step 5: Thread it from `build_reel`**

In `scripts/build_reel.py`:

```python
        report = check_reel.run(master, clips, spec, report_path,
                                music=music, audio=audio, geometry=geometry,
                                platform=rm.platform, outro=rm.outro)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_models.py tests/lib/test_build_reel.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py scripts/check_reel.py scripts/build_reel.py \
        tests/lib/test_check_reel.py tests/lib/test_models.py
git commit -m "feat(check-reel): measure how far the delivered reel sits from the bar line

music-outro-fit §11.9 deferred this because 'the fade starts a fraction of a
frame off the line and nothing measures the residual'. The fraction-of-a-frame
framing was optimistic: _LENGTH_TOL is 0.5s, so the length gate passes a master
half a second off the chosen length without a word.

Advisory, and deliberately so. The residual that matters perceptually is
unknown — nobody has measured how far a fade may start from a bar line before
the ending stops resolving — so `passed` keys on the length gate's own
reporting boundary, and the teeth live in the absorb's refusal instead.

Three named states: no key when no fit ran, n/a when a fit chose nothing, a
measurement when a line was chosen. check_reel already probes the master's
duration, so this costs no extra I/O."
```

---

## Task 6: the fixed-point proof

**Files:**
- Create: `tests/lib/test_pacing_fixed_point.py`

**Interfaces:**
- Consumes: everything from Tasks 0–3.
- Produces: nothing other tasks read.

This proof needs **no ffmpeg and no model weights** — `write_edit_plan` reads
`FOOTAGE.json` and writes `EDL.json`, and `build_pacing` without `--anchors` reads JSON
only. So it belongs in `tests/lib/`, not `tests/integration/`, whose marker means
"requires ffmpeg and/or model weights (slow)".

- [ ] **Step 1: Write the failing proof**

```python
"""fit -> apply -> fit -> apply is a fixed point (design
docs/specs/2026-08-16-pacing-fixed-point-design.md §3.1, §7).

Real drivers end to end — edit_plan.write_edit_plan and pacing.build_pacing — and no
ffmpeg at all: neither driver decodes a frame. The 'track' is a few bytes on disk
because music_identity only ever HASHES it; nothing here plays it.

Fixture shape copied from tests/integration/test_outro.py (two windows far apart in
one clip, a no-slack spine, one bar line the realized length is 0.2s short of) minus
everything that needed real pixels. The outro fit must actually fire: it is the case
that deadlocked, so a proof where it does not fire proves nothing."""
import json

import pytest

from scripts import edit_plan, pacing as pacing_driver
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.models import MusicSpec

W, H, FPS = 640, 360, 30.0
CLIP_DUR = 20.0
TEMPO = 120.0            # -> outro.bar_seconds == 2.0s, allowance == 0.25s
FADE = 0.5               # mix's own default: no look is authored in selection.json
LINE = 10.2              # the sole bar line; realized is 6.0 + 4.0 = 10.0s
MUSIC_DUR = 20.0


@pytest.fixture
def run_dir(tmp_path):
    f = Footage(clips=[FootageClip(source="a.mp4", dur=CLIP_DUR, res=(W, H), fps=FPS, windows=[
        FootageWindow(start=0.5, dur=6.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=10.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(f.to_dict()))
    (tmp_path / "selection.json").write_text(json.dumps({"episodes": [
        {"source": "a.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "a.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}))
    (tmp_path / "project.json").write_text(json.dumps(
        {"purpose": "reel", "canvas": [1080, 1920], "delivery": "long_edge:240"}))
    track = tmp_path / "t.wav"
    track.write_bytes(b"only ever hashed, never decoded")
    ms = MusicSpec(track=str(track), start_offset=0.0, duration=MUSIC_DUR, tempo=TEMPO,
                   beats=tuple(i * 0.5 for i in range(int(MUSIC_DUR / 0.5))),
                   energy=(0.3,) * 10, energy_hz=2.0, bars=(LINE,),
                   vocal_spans=((LINE, LINE + 1.8),))
    (tmp_path / "MUSIC.json").write_text(json.dumps(ms.to_dict()))
    return tmp_path


def _plan(run_dir, out_name, *, pacing_path=None, music=None):
    out = run_dir / out_name
    res = edit_plan.write_edit_plan(str(run_dir / "FOOTAGE.json"),
                                    str(run_dir / "selection.json"),
                                    str(run_dir / "project.json"), str(out),
                                    pacing_path=pacing_path, music=music)
    assert res["status"] == "written", res
    return out / "EDL.json"


def _fit(run_dir, edl_path, out_name):
    res = pacing_driver.build_pacing(str(edl_path), str(run_dir / "FOOTAGE.json"),
                                     [str(run_dir / "MUSIC.json")], str(run_dir / out_name))
    return res["json"]


def test_fit_then_apply_is_a_fixed_point(run_dir):
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")                                  # 1. the scenario
    spine1 = _fit(run_dir, edl0, "f1")                           # 2. fit it
    edl_a = _plan(run_dir, "pa", pacing_path=spine1, music=music) # 3. apply -> A
    spine2 = _fit(run_dir, edl_a, "f2")                          # 4. re-fit A
    edl_b = _plan(run_dir, "pb", pacing_path=spine2, music=music) # 5. re-apply -> B

    assert edl_a.read_bytes() == edl_b.read_bytes()


def test_the_proof_would_be_vacuous_without_the_outro_fit_firing(run_dir):
    # Guards the fixture, not the code: if the fit stopped firing, the fixed-point
    # test above would still pass and would no longer be testing the deadlock.
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")
    edl_a = EDL.from_json(_plan(run_dir, "pa", music=music,
                                pacing_path=_fit(run_dir, edl0, "f1")))
    assert edl_a.outro is not None and edl_a.outro.rung == "gap"
    assert edl_a.outro.reel_dur == pytest.approx(LINE + FADE)
    assert edl_a.episodes[-1].dur > edl_a.episodes[-1].base_dur


def test_the_refit_spine_is_the_same_spine(run_dir):
    # The mechanism, so a failure of the byte-comparison above is diagnosable:
    # both fits read base_play_dur, so they produce identical slots.
    music = str(run_dir / "MUSIC.json")
    edl0 = _plan(run_dir, "p0")
    s1 = _fit(run_dir, edl0, "f1")
    edl_a = _plan(run_dir, "pa", pacing_path=s1, music=music)
    s2 = _fit(run_dir, edl_a, "f2")
    assert json.loads(open(s1).read()) == json.loads(open(s2).read())
```

- [ ] **Step 2: Run it to verify it fails on the pre-slice code**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_fixed_point.py -v`

Expected on the code as it stands **before Tasks 0–3** (recorded here for the reviewer;
by the time this task runs it should pass): step 4 or 5 raises `pacing: slot 1 is 4.70s
against a 4.00s episode`. If the whole file passes on the first run, stop and check that
`base_dur` is actually being written — a green proof here can only mean the fixture is
not exercising the deadlock.

- [ ] **Step 3: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_fixed_point.py -v`
Expected: PASS, all four tests.

- [ ] **Step 4: Commit**

```bash
git add tests/lib/test_pacing_fixed_point.py
git commit -m "test(pacing): prove fit-then-apply is a fixed point, end to end

Five real driver calls: build -> pacing -> build --pacing --music (A) -> pacing
-> build --pacing --music (B), asserting A and B are byte-identical. The
provenance block digests the rest of the file, so it is identical exactly when
they are; provenance.stamp deliberately carries no timestamp, which is what
makes the comparison possible.

Needs no ffmpeg — neither driver decodes a frame, and the track is a few bytes
because music_identity only hashes it — so this lives in tests/lib rather than
under the integration marker.

A companion test asserts the outro fit actually fires (rung 'gap', reel_dur ==
line + fade). Without it the fixed-point proof would still pass while no longer
testing the case that deadlocked."
```

---

## Task 7: mutation battery, skills, docs

**Files:**
- Modify: `skills/pacing/SKILL.md`, `skills/edit-plan/SKILL.md`,
  `skills/reel-review/SKILL.md`, `CLAUDE.md`, `docs/build-status.md`, `docs/backlog.md`,
  `docs/pipeline-map.md`

**Interfaces:**
- Consumes: everything.
- Produces: nothing.

- [ ] **Step 1: Run the mutation battery**

For each row: apply the mutation to the production code, run the named test, **watch it
go red**, then revert the mutation. A row that stays green is a coverage hole — close it
by adding a test that discriminates, and record that you did.

| # | Mutation | Must turn red |
|---|---|---|
| 1 | `window_to_episode` drops `base_dur=window.dur` | `test_window_to_episode_records_the_projected_length`, `test_fit_then_apply_is_a_fixed_point` |
| 2 | `base_play_dur` returns `self.play_dur()` unconditionally | `test_base_play_dur_is_the_base_when_there_is_no_ramp` |
| 3 | `base_play_dur` returns `self.base_dur` (drops the ramp extra) | `test_base_play_dur_adds_the_same_ramp_extra_a_base_length_episode_would_have` |
| 4 | `_bind_pacing` guards `ep.play_dur()` again | `test_bind_pacing_accepts_a_slot_that_matches_the_SCENARIO_not_the_bound_length` |
| 5 | `_bind_pacing` drops the no-`base_dur` arm sentence | `test_bind_pacing_names_the_arm_when_an_episode_has_no_base_dur` |
| 6 | `build_pacing` fits `ep.play_dur()` | `test_build_pacing_fits_the_scenario_length_not_the_bound_one`, `test_fit_then_apply_is_a_fixed_point` |
| 7 | `_bounds` measures room from `ep.dur` | `test_the_grow_bound_is_measured_from_the_scenario_length` |
| 8 | `music_identity` drops `start_offset` from the hashed dict | `test_music_identity_separates_two_windows_of_the_same_track`, `test_build_edl_refuses_a_spine_fitted_to_a_different_music_window` |
| 9 | `music_identity` returns a constant instead of `""` on `OSError` | `test_music_identity_is_empty_when_the_track_cannot_be_read` |
| 10 | `build_edl` skips the digest comparison | `test_build_edl_refuses_a_spine_fitted_to_a_different_music_window` |
| 11 | `build_edl`'s fallback drops the tempo check | `test_build_edl_names_the_not_checked_arm_and_falls_back_to_tempo` |
| 12 | `build_edl`'s fallback drops the `not-checked` log line | same test's `capsys` assert |
| 13 | `next_action` ignores `outro_fixed` | `test_a_within_band_shortfall_escalates_when_the_outro_chose_the_length` |
| 14 | `next_action` relabels **every** length escalate `"outro-length-chosen"` when `outro_fixed` | `test_a_past_the_band_shortfall_still_reads_not_auto_fixable_with_an_outro` |
| 15 | `build_reel` derives `outro_fixed = rm.outro is not None` (drops the rung test) | needs a test: a manifest with an `"unchanged"` outro must still absorb — add it to `tests/lib/test_build_reel.py` if row 15 stays green |
| 16 | `ReelManifest` drops the `OutroFit.from_dict` oracle | `test_reel_manifest_refuses_a_malformed_outro` |
| 17 | `edl_to_reel` drops `outro=` from the `ReelManifest` | `test_edl_to_reel_carries_the_outro_onto_the_reel_manifest` |
| 18 | `_ADVISORY_CHECKS` loses `"outro"` | `test_a_failing_outro_residual_does_not_block_overall`, `test_a_residual_past_the_reporting_tolerance_is_flagged_but_advisory` |
| 19 | `check_reel` emits a measurement for `rung == "unchanged"` | `test_an_unchanged_rung_reports_n_a_not_a_measurement` |
| 20 | `check_reel` emits the `outro` check even when `outro is None` | `test_no_outro_key_at_all_when_no_fit_ran` |

- [ ] **Step 2: Run the whole suite**

Run: `find . -name __pycache__ -type d -prune -exec rm -rf {} + && .venv/bin/python -m pytest -q`
Expected: green, with the same skip count as before this branch. Record the exact
pass/skip numbers in the commit message.

- [ ] **Step 3: Delete the detour from the skills**

The rebuild-without-`--pacing` workaround exists only because the round trip was not a
fixed point. Now that it is, the instruction is wrong, not merely redundant.

- `skills/pacing/SKILL.md` step 1: delete the whole **"Re-fitting? Check for an outro fit
  first."** paragraph (currently lines ~51–61). Replace it with:

  ```
     **Re-fitting is safe to repeat.** The fit reads each episode's `base_dur` — the
     length the scenario projected — not the length a previous bind or outro fit left
     behind, so fitting an already-fitted `EDL.json` produces the same spine and
     re-applying reproduces the same EDL (design 2026-08-16 §3.1). An `EDL.json`
     written before 2026-08-16 has no `base_dur`: the old deadlock still applies there,
     and `edit_plan build --pacing` says so by name in its refusal.
  ```

- `skills/edit-plan/SKILL.md`: the paragraph around line 371 that teaches the same
  detour — replace with a one-line pointer to the pacing skill's new wording.
- `skills/reel-review/SKILL.md` line 84: the `pacing` routing row's caveat ("but if
  `EDL.json` carries an outro fit, rebuild WITHOUT `--pacing`/`--music` first, else the
  re-fit deadlocks") — delete the caveat, keep the row.

Also add to `skills/reel-review/SKILL.md`'s routing table a row for the new stop:
`outro-length-chosen` → the closing episode must grow or be re-cut; the reel loop will
not absorb the shortfall because the length was chosen musically.

- [ ] **Step 4: Sync the docs**

- `CLAUDE.md`: add two Quick Reference rows — the design and this plan — in the same
  shape as the neighbouring music-outro-fit rows.
- `docs/build-status.md`: a Done entry naming what landed, including the measured
  one-beat drift and the fact that it fires on the stage's own recommended remedy.
- `docs/backlog.md`:
  - Mark the P2 row **"Make pacing's round trip a fixed point again"** ✅ with what was
    built and what the measurement found beyond the queued row.
  - Mark the P2 row **"Reconcile `build_reel`'s length re-time with the outro fit"** ✅.
  - Mark the P3 Music row **"measure the delivered fade's real distance from
    `EDL.outro.line`"** ✅ — closed for free by the advisory check, and note the
    correction: `_LENGTH_TOL` is 0.5s, so the band was never "a fraction of a frame".
  - Add the three new rows from design §10: the `base_dur` migration (P3, S), the
    digest's audio-unreadable rung (P3, S), and calibrating the outro residual (P3, S).
  - Update `_Last updated:_`.
- `docs/pipeline-map.md`: only if a stage's status line mentions the detour — check with
  `grep -n "pacing" docs/pipeline-map.md` and fix what is stale.

- [ ] **Step 5: Commit**

```bash
git add skills/ CLAUDE.md docs/
git commit -m "docs(pacing): retire the rebuild-without---pacing detour

It existed only because the round trip was not a fixed point. Now that it is,
the instruction is wrong rather than redundant — three skills taught it, and a
reader following it would rebuild an EDL for no reason.

Backlog: both P2 rows close, and so does the P3 'measure the fade's distance
from the line' row the advisory check picked up for free. Its reasoning needed
a correction on the way out: it assumed the residual was a fraction of a frame,
but _LENGTH_TOL is 0.5s, so the length gate was passing a master half a second
off the chosen length without a word.

Three new deferrals filed: a migration for EDLs with no base_dur, the digest's
audio-unreadable rung falling back to a check that cannot see a window change,
and calibrating the residual's reporting boundary against perception."
```

---

## Self-Review

**Spec coverage.** Design §2 → Task 0. §2.1 → Task 0 Step 6. §2.2 → Task 0 (the absent
arm) + Task 1 Step 4 (the named arm in the refusal). §3's table → Tasks 1 and 2. §3.1 →
Task 6. §4 → Task 3. §4.1 → Task 3 Step 4's docstring + the two-window test. §4.2's three
rungs → Task 3 Step 6. §5 → Task 4. §5.1 → Task 4 Steps 3–5. §5.2 → the finding's `why`
text. §5.3 → the design records it; no code. §6 → Task 5. §7's eight test groups → Tasks
0–6 plus Task 7's battery. §9's honest limits → Task 7's docs sync. §10's three deferrals
→ Task 7 Step 4.

**Placeholders.** Task 4 Step 1's `test_edl_to_reel_carries_the_outro_onto_the_reel_manifest`
and Task 5 Step 1's four `<harness>` markers are the only two places this plan does not
write literal test bodies. Both are deliberate: those files reach `ReelManifest` /
`check_reel.run` through fixtures whose exact shape lives in the test files themselves,
and inventing a second harness beside them would be worse than pointing at the existing
one. Every assertion those tests must make is spelled out.

**Fixture values were executed, not guessed.** Three numbers in Task 2 and Task 3 were
checked against the real code while writing this plan, and two of them were wrong on the
first pass. `fit_spine([4.25], …)` returns `[4.25]`, not `[4.5]` — the tail slot is never
snapped, so a one-episode fixture would have made the whole task's tests vacuous. And a
`MusicSpec` at 110 BPM refuses a hardcoded 40-beat grid over a 20s window. Both are now
fixed in the task text with the reason written beside them.

**Type consistency.** `base_dur: float | None` and `base_play_dur() -> float` are used
under those exact names in Tasks 1, 2 and 6. `music_identity(track, start_offset,
duration) -> str` is called with the same three arguments in `scripts/pacing.py` and
`scripts/edit_plan.py`. `Spine.music_digest: str` is read as `pacing.music_digest` in
`build_edl`. `ReelManifest.outro: dict | None` is read as `rm.outro` in `build_reel` (both
for `outro_fixed` and for `check_reel.run(outro=)`) and written as
`edl.outro.to_dict()` in `edl_to_reel`. `next_action`'s fifth parameter is `outro_fixed`
in the definition, the call, and every test.
