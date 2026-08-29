# Retiring the reel's colour-convergence loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `check_reel`'s `color_across_cuts` check and the reel retry loop's colour corrector, delete the `color_correct` cascade they were the only consumers of, and give `reel-review` a `colour` axis routed to `match-grade`.

**Architecture:** This is a removal slice. Almost every step deletes code; the only additions are two strings in two closed tuples in `scripts/lib/review.py`, and one new test per deletion that pins the deletion so it cannot silently return. Tasks are ordered so the full suite is green at every commit: `check_reel` stops *emitting* the failure first (the orchestrator's handling becomes dead but harmless), then the orchestrator and driver stop *handling* it, then the contracts that carried its threshold go, then the CLI, then the `color_correct` cascade, then the reviewer axis.

**Tech Stack:** Python 3, pytest, ffmpeg via `scripts/lib/ffbin`, numpy/Pillow (both partly retired here).

**Design:** [docs/specs/2026-08-29-colour-convergence-retire-design.md](../specs/2026-08-29-colour-convergence-retire-design.md)

## Global Constraints

- Scripts run as modules: `pythonpath = .` in `pytest.ini`; the interpreter is `.venv/bin/python`. Run tests as `.venv/bin/python -m pytest`.
- Fail-loud contract, imports at top of file, typing on every signature — see `docs/coding-standards.md`.
- Whole-object asserts where practical — see `docs/testing-guide.md`.
- **Never** run an installer (`brew`, `pip install`, `npm`, `apt`, `setup.sh`). Verification is read-only plus pytest.
- **Never** run `git checkout --`, `git restore`, `git reset --hard`, or `git stash`. If a file needs reverting, ask.
- Do not `git push`. Commit locally only.
- A mutation battery is run with `PYTHONDONTWRITEBYTECODE=1` — a one-byte edit can match the previous file's size and mtime-second, and CPython then serves a stale `.pyc`.
- **Deletions must not leave unused imports.** Two are known and named in Task 0; check for others with a lint/grep pass in each task.
- The preserved run at `/Users/serg/Downloads/untitled folder/` is read-only. Do not write to it.

---

### Task 0: `check_reel` stops emitting `color_across_cuts`

**Files:**
- Modify: `scripts/check_reel.py` (delete `_frame_mean` 69-73, `_rgb_dist` 76-77, `_channel_median` 89-90, the colour block 159-184, and the now-dead `import statistics` / `import numpy as np`)
- Test: `tests/lib/test_check_reel.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `check_reel.run()` returns a `ReelReport` whose `checks` dict has **no** `color_across_cuts` key. Later tasks rely on that absence.

**What must NOT change:** `cuts = _boundaries(durations)` stays — line 210 passes `cuts` to `_beat_check`. `mids = _midpoints(durations)` stays — the phash variety check consumes it. `_sample_frame`, `_phash_bits`, `import tempfile` and `from PIL import Image` stay (`_phash_bits` uses all three).

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_check_reel.py`, replacing the six tests named in Step 3:

```python
def test_no_across_cut_colour_check_is_reported(tmp_path, monkeypatch):
    """The across-cut colour check is retired (design 2026-08-29 §2). It compared two
    frames straddling a cut — two different SHOTS — so six of the only real reel's
    seven cuts exceeded the 12.0 default and the operator raised the ceiling to 56.0
    to switch it off. Its absence is pinned here: re-adding the key would make this
    fail, and would also silently re-arm a corrector that can only damage the grade."""
    _Stub([3.0, 3.0]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"))
    assert "color_across_cuts" not in rep.checks
    assert not [f for f in rep.fail_reasons if f.check == "color_across_cuts"]
    assert rep.overall is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py::test_no_across_cut_colour_check_is_reported -v`

Expected: FAIL — `assert 'color_across_cuts' not in rep.checks` (the key is still produced).

- [ ] **Step 3: Delete the six colour tests and the stub's `means` support**

Delete from `tests/lib/test_check_reel.py`:

- `test_color_across_cuts_passes_when_neighbours_match`
- `test_color_across_cuts_blames_the_episode_farther_from_the_reel_median`
- `test_color_across_cuts_is_not_applicable_for_a_single_episode`
- `test_color_across_cuts_two_episode_tie_blames_the_later_episode`
- `test_color_across_cuts_uses_median_not_mean_so_a_far_outlier_does_not_mislead`
- `test_color_fail_detail_carries_target_and_culprit_mean`

Then in `_Stub`, drop the `means` parameter, the `self.means` attribute, the `means: {t: (r,g,b)}.` sentence in the docstring, and the `_frame_mean` monkeypatch. The class becomes:

```python
class _Stub:
    """Stub the ffmpeg-touching helpers so check_reel logic is unit-testable.
    durations: per-episode seconds. blacks: black_start times on the master.
    hashes: {t: int} used as a fake ImageHash distance base."""
    def __init__(self, durations, blacks=(), hashes=None):
        self.durations = durations
        self.blacks = list(blacks)
        self.hashes = hashes or {}

    def install(self, monkeypatch):
        eps_dur = iter(self.durations + [sum(self.durations)])  # episodes..., then master
        monkeypatch.setattr(check_reel, "_probe_dur", lambda v: next(eps_dur))
        monkeypatch.setattr(check_reel, "_black_hits", lambda m: self.blacks)
        monkeypatch.setattr(check_reel, "_phash_bits",
                            lambda v, t: self.hashes.get(round(t, 3), 0), raising=False)
        monkeypatch.setattr(check_reel, "_hamming", lambda a, b: abs(a - b), raising=False)
```

- [ ] **Step 4: Delete the check and its three helpers**

In `scripts/check_reel.py`, delete `_frame_mean`, `_rgb_dist` and `_channel_median` entirely, and replace the whole colour block

```python
    cuts = _boundaries(durations)
    mids = _midpoints(durations)
    if cuts:
        span_means = [_frame_mean(master, m) for m in mids]
        ...
    else:
        checks["color_across_cuts"] = CheckResult("color_across_cuts", None,
                                                  {"status": "n/a", "reason": "single episode, no cut"})
```

with just the two lines that survive it:

```python
    cuts = _boundaries(durations)      # _beat_check reads these below
    mids = _midpoints(durations)       # the phash variety check reads these below
```

- [ ] **Step 5: Remove the two imports that just went dead**

In `scripts/check_reel.py`, delete `import statistics` (its only use was `_channel_median`) and `import numpy as np` (its only use was `_frame_mean`).

Verify nothing else needs them:

```bash
grep -n "statistics\.\|np\." scripts/check_reel.py
```

Expected: no output.

- [ ] **Step 6: Run the file's tests**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -v`

Expected: PASS, with six fewer tests than before and the new one green.

- [ ] **Step 7: Fix the two integration assertions that read the deleted key**

`tests/integration/test_reel_backhalf.py:53` asserts `rep.checks["color_across_cuts"].passed is True`. Delete that line — the surrounding test's other assertions still carry it.

`tests/integration/test_look.py:53` and `tests/integration/test_attested_run.py:20` and `tests/integration/test_front_spine.py:163` mention the check in prose only. Update each sentence to name the checks that remain (`black` / `length` / `variety`), so no docstring promises a check that no longer exists.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. If anything else indexes `checks["color_across_cuts"]`, fix it the same way.

- [ ] **Step 9: Commit**

```bash
git add scripts/check_reel.py tests/
git commit -m "refactor: check_reel stops comparing two different shots

color_across_cuts measured the mean absolute per-channel difference between two
frames straddling a cut — that is, how different two consecutive SHOTS look.
Six of the only real reel's seven cuts exceeded the 12.0 default (11.0 to 51.5)
and its EPISODES.json records 56.0: the operator switched the check off the only
way the knob allowed. No threshold separates a grade mismatch from a content
change in a whole-frame mean, so the sensor is wrong in kind, not calibration.

_frame_mean, _rgb_dist and _channel_median had no other caller and go with it,
along with the statistics and numpy imports they were the only users of. cuts and
mids stay — _beat_check and the phash variety check read them."
```

---

### Task 1: the reel loop stops correcting colour

**Files:**
- Modify: `scripts/lib/reel_orchestration.py` (`_REPROCESS_CLASS` line 10, `ReprocessItem` 13-19, `_correction` 33-40, the `corr` lines 104-106)
- Modify: `scripts/build_reel.py` (the `corrected` import line 21, `_compound` 29-34, `cc` line 57, the reprocess-arm lines 150-166 and the comment block 176-184)
- Test: `tests/lib/test_reel_orchestration.py`, `tests/lib/test_build_reel.py`

**Interfaces:**
- Consumes: Task 0's guarantee that `check_reel` never emits a `color_across_cuts` failure.
- Produces: `ReprocessItem(idx)` — a frozen dataclass with a single `idx: int` field. `reel_orchestration._REPROCESS_CLASS == ("black",)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_reel_orchestration.py`:

```python
def test_a_colour_failure_is_no_longer_reprocessable():
    """The colour corrector is retired (design 2026-08-29 §2). Anything that is not a
    black hit escalates instead of being handed a per-channel pull: the pull moved each
    episode's whole-frame mean toward the reel median, which on real footage demanded
    1.41x on one episode's red and 1.75x on all three of another's — against 0.71 dE00
    of headroom, where 1.10x on one channel already costs 3.92."""
    f = ReelFailure("color_across_cuts", "reprocess", 0,
                    {"target": [130.0, 120.0, 130.0], "culprit_mean": [160.0, 120.0, 130.0]})
    a = reel_orchestration.next_action([f], {}, 3, 1.0, False)
    assert a.kind == "escalate"
    assert a.reprocess == ()


def test_a_black_failure_still_reprocesses_and_carries_only_an_index():
    b = ReelFailure("black", "reprocess", 1, {"t": 2.0})
    a = reel_orchestration.next_action([b], {}, 3, 1.0, False)
    assert a.kind == "reprocess"
    assert a.reprocess == (reel_orchestration.ReprocessItem(1),)
```

- [ ] **Step 2: Run them and watch the first fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_orchestration.py::test_a_colour_failure_is_no_longer_reprocessable -v`

Expected: FAIL — `assert 'reprocess' == 'escalate'` (colour is still in `_REPROCESS_CLASS`).

- [ ] **Step 3: Shrink the reprocess class and delete the corrector**

In `scripts/lib/reel_orchestration.py`:

```python
_REPROCESS_CLASS = ("black",)      # the only reel failure a re-render can fix. The
                                   # colour arm is retired (design 2026-08-29): its
                                   # lever pulled an episode's whole-frame mean toward
                                   # the reel median, which is an exposure change on a
                                   # reel with legitimately dark and bright shots.
```

Replace `ReprocessItem` with:

```python
@dataclass(frozen=True)
class ReprocessItem:
    """Reprocess one episode: a clean re-encode for a black hit. Nothing is tuned —
    the route is frozen and the grade is the EDL's, so the only thing a reprocess can
    change is a transient encode artifact."""
    idx: int
```

Delete `_correction` entirely, and replace the two lines that used it:

```python
        corr = _correction(f) if f.check == "color_across_cuts" else None
        if f.episode_idx not in items or corr is not None:
            items[f.episode_idx] = ReprocessItem(f.episode_idx, corr)
```

with:

```python
        items[f.episode_idx] = ReprocessItem(f.episode_idx)
```

- [ ] **Step 4: Delete the driver's compounded factor**

In `scripts/build_reel.py`:

- delete `from scripts.lib.color import corrected` (line 21)
- delete `_compound` (lines 29-34)
- delete `cc: dict[int, tuple[float, float, float]] = {}` (line 57)
- in the reprocess arm, delete the two `item.color_correct` lines and drop the keyword from the call:

```python
        for item in action.reprocess:                # sequential: a reprocess batch is typically one
                                                     # or two culprits, so the fan-out's measured 1.70x
                                                     # (docs/specs/2026-07-18-cap3-fanout-design.md §2)
                                                     # has little to bite on here.
            epdir = str(Path(work_dir) / f"ep{item.idx}")
            manifest = rm.episodes[item.idx].manifest
```

and

```python
            res = process_episode.process_episode(manifest, epdir, route_path=route)
```

- replace the comment block at 176-184 (the one beginning `# A REJECTED re-render is already on disk.`) with the shorter statement that survives the deletion:

```python
            # A REJECTED re-render is already on disk. reframe writes m.out_path before
            # check_episode.run reads it (process_episode.py), so this early return
            # leaves ep{i}.mp4 overwritten by the render that just failed, and skips the
            # reprocessed.add() below — the run stops with a clip nobody recorded as
            # touched. Not a silent bypass: episode_qc.gate's stale-digest arm refuses on
            # the next --from-episodes, because the clip no longer hashes to what was
            # judged. But nothing in this finding says a clip was rewritten (backlog row).
```

- [ ] **Step 5: Re-point the driver's colour tests at black**

In `tests/lib/test_build_reel.py`, the fixtures at lines 22-23, 130-136, 235-237, 300-302 and 423-424 build `CheckResult("color_across_cuts", False, {})` plus a matching `ReelFailure(... "reprocess" ...)` to drive a reprocess round. Every one of them becomes a black hit — the failure class that still reprocesses:

```python
        checks={"black": CheckResult("black", False, {"black_start": [1.0]})},
        fail_reasons=[ReelFailure("black", "reprocess", idx, {"t": 1.0})],
```

Delete any assertion that reads `item.color_correct` or a compounded factor; those describe the deleted lever.

- [ ] **Step 6: Run both test files**

Run: `.venv/bin/python -m pytest tests/lib/test_reel_orchestration.py tests/lib/test_build_reel.py -v`

Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. `tests/integration/test_episode_qc.py:177-178` also builds a `color_across_cuts` reprocess failure — re-point it to black the same way.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/reel_orchestration.py scripts/build_reel.py tests/
git commit -m "refactor: the reel loop keeps its black arm and loses its colour one

_REPROCESS_CLASS becomes ('black',). ReprocessItem loses color_correct and carries
only an index; _correction, build_reel's cc dict and _compound go with it.

The corrector optimised a different quantity than the gate measured: the gate read
the delta between two frames adjacent across one cut, the lever pulled the culprit
episode's whole-frame MIDPOINT mean toward the median of every episode's midpoint
mean. On the only real reel that arithmetic asks for 1.75x on all three channels of
a legitimately dark shot — an exposure change, not a colour match — against a 1.5
clamp costing ~16 dE00 and 0.71 dE00 of headroom."
```

---

### Task 2: the threshold leaves both contracts

**Files:**
- Modify: `scripts/lib/models.py` (`ReelCheckSpec` field 1075 + validation 1090-1091; `ReelManifest` field 1383, `check_spec` 1454, `from_dict` 1481, `to_dict` 1496, and the `self.check_spec` comment 1450)
- Test: `tests/lib/test_models.py`, `tests/lib/test_provenance.py`, `tests/lib/test_deliver.py`, `tests/lib/test_edl_to_reel.py`, `tests/integration/test_music_spine.py`, `tests/integration/test_safezones.py`

**Interfaces:**
- Consumes: nothing — Tasks 0 and 1 already stopped reading the field.
- Produces: `ReelCheckSpec(target_dur, variety_min, beat_tol, ...)` — `variety_min` is now the **second and last** positional before `beat_tol`. `ReelManifest.check_spec` returns `ReelCheckSpec(self.target_dur, self.variety_min)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_models.py`:

```python
def test_reel_check_spec_no_longer_accepts_color_delta_max():
    """The across-cut ceiling is retired with the check it bounded (design
    2026-08-29 §6). Pinned as a TypeError so a re-added field is caught by the
    contract, not by a check that silently starts running again."""
    with pytest.raises(TypeError):
        m.ReelCheckSpec(target_dur=6.0, color_delta_max=12.0)


def test_reel_manifest_ignores_a_legacy_color_delta_max_key():
    """A pre-0.5.0 EPISODES.json carries the key. from_dict reads named keys, so an
    unknown one is dropped — deliberate (design §6): it recorded a ceiling for a check
    that no longer exists, so ignoring it cannot mislead about anything that runs."""
    rm = m.ReelManifest.from_dict(_reel_dict(color_delta_max=56.0))
    assert not hasattr(rm, "color_delta_max")
    assert rm.check_spec.variety_min == 8
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k "color_delta_max" -v`

Expected: the first FAILs (`DID NOT RAISE TypeError`); the second FAILs on `assert not hasattr(...)`.

- [ ] **Step 3: Delete the field from both dataclasses**

In `scripts/lib/models.py`:

- `ReelCheckSpec`: delete `color_delta_max: float = 12.0      # §9 across-cut mean-RGB delta ceiling` and its two validation lines.
- `ReelManifest`: delete `color_delta_max: float = 12.0`.
- `check_spec` becomes:

```python
    @property
    def check_spec(self) -> ReelCheckSpec:
        return ReelCheckSpec(self.target_dur, self.variety_min)
```

- the comment on line 1450 becomes `self.check_spec  # forces ReelCheckSpec validation of target_dur/variety_min`
- `from_dict`: delete the `color_delta_max=d.get("color_delta_max", 12.0),` line.
- `to_dict`: delete `"color_delta_max": self.color_delta_max,` from the returned dict.

- [ ] **Step 4: Delete the old contract tests and re-point the overrides example**

Delete `test_reel_manifest_rejects_bad_color_delta_max` (`tests/lib/test_models.py:781-783`) and the `(dict(target_dur=6.0, color_delta_max=0), "color_delta_max"),` row from the validation table at line 589. Update the two assertions at 582 and 691/698 to drop `color_delta_max`.

**Remove `color_delta_max=10.0` from `_reel_dict`'s base dict (line 679).** This is not tidying: the new legacy-key test overrides the key on purpose, and if the base already carried it then every other `_reel_dict()` call would carry it too — the test would assert the same thing every existing call already proves, and would stop discriminating the mutation it exists to catch. After the edit, confirm the base has no such key:

```bash
sed -n '676,682p' tests/lib/test_models.py
```

Expected: `target_dur=6.0, variety_min=4, cap=3, changelog="cut"` with no `color_delta_max`.

`provenance.spec_overrides` is generic over the dataclass's own fields and is **not** changed — only the field four tests used as their example. In each of these, swap `color_delta_max`/`20.0`/`12.0` for `variety_min`/`4`/`8`:

- `tests/lib/test_provenance.py:77` — `ReelCheckSpec(target_dur=10.0, variety_min=4)`
- `tests/lib/test_provenance.py:79` and `:108` — the expected override dict
- `tests/lib/test_deliver.py:220` and `:233` — the attestation's `overrides` fixture and assertion
- `tests/lib/test_edl_to_reel.py:948-951` — the run-provenance override assertion

- [ ] **Step 5: Drop the keyword from the two integration specs**

`tests/integration/test_music_spine.py:68` and `tests/integration/test_safezones.py:51` construct a `ReelCheckSpec` with `color_delta_max=`. Delete that keyword from both; the other arguments are unchanged.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. Anything still passing the keyword raises `TypeError` and names itself in the traceback.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py tests/
git commit -m "refactor: the across-cut ceiling leaves ReelCheckSpec and ReelManifest

The field bounded a check that no longer exists. A pre-0.5.0 EPISODES.json carrying
the key is silently ignored — from_dict reads named keys — and that is deliberate: it
recorded a ceiling for a retired check, so ignoring it cannot mislead about anything
that still runs.

provenance.spec_overrides is untouched; it is generic over a spec's own fields. Only
the four tests that used color_delta_max as their example field move to variety_min."
```

---

### Task 3: `--color-delta-max` leaves the CLI

**Files:**
- Modify: `scripts/edl_to_reel.py` (`_build_manifest` signature 79 + docstring 87-91, `extra` line 199, `edl_to_reel` 229/236, `process_episodes` 247/253, the flag 338-342, the `--from-episodes` refusal 357+363, the call 390)
- Test: `tests/lib/test_edl_to_reel.py`

**Interfaces:**
- Consumes: Task 2's contract — `ReelManifest` no longer has the field, so `extra` can never carry it.
- Produces: `_build_manifest(edl_path, project_path, footage_root, work_dir, out_dir, *, music=None, jobs=DEFAULT_JOBS, changelog="")` and the same keyword set on `edl_to_reel` / `process_episodes`.

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_edl_to_reel.py`:

```python
def test_cli_refuses_a_color_delta_max_flag(monkeypatch, tmp_path):
    """The flag is retired with the check it tuned (design 2026-08-29 §2). argparse
    fails loud on an unrecognised argument, so a stale script or skill line stops the
    run rather than silently setting a ceiling nothing reads."""
    monkeypatch.setattr(sys, "argv",
                        ["edl_to_reel", "--edl", str(tmp_path / "e.json"),
                         "--project", str(tmp_path / "p.json"),
                         "--footage-root", str(tmp_path),
                         "--work-dir", str(tmp_path / "w"),
                         "--out-dir", str(tmp_path / "o"),
                         "--color-delta-max", "20.0"])
    with pytest.raises(SystemExit):
        edl_to_reel.main()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py::test_cli_refuses_a_color_delta_max_flag -v`

Expected: FAIL — the flag parses, so `main()` proceeds instead of exiting.

- [ ] **Step 3: Delete the flag and its four signatures**

In `scripts/edl_to_reel.py`:

- `_build_manifest`: drop `color_delta_max: float | None = None,` from the signature and delete the paragraph of the docstring beginning `` `color_delta_max` overrides the across-cut mean-RGB ceiling `` through `never to silence a grade that is genuinely wrong."""` — keep the closing `"""` on the preceding sentence.
- Replace `extra = {} if color_delta_max is None else {"color_delta_max": color_delta_max}` with `extra: dict = {}` and leave its consumer untouched. If `extra` now has no other contributor, keep it: it is the seam a future override uses, and removing it would be an unrelated change.
- `edl_to_reel` and `process_episodes`: drop `color_delta_max: float | None = None,` from both signatures and `color_delta_max=color_delta_max,` from both `_build_manifest` calls.
- Delete the whole `ap.add_argument("--color-delta-max", ...)` block.
- In the `--from-episodes` refusal, delete `or a.color_delta_max is not None` from the condition and `--color-delta-max / ` from the message text.
- Delete `color_delta_max=a.color_delta_max,` from the `fn(...)` call at 390.

- [ ] **Step 4: Delete the six tests that exercised the flag**

From `tests/lib/test_edl_to_reel.py`, delete:

- `test_color_delta_max_override_reaches_the_reel_manifest` (189)
- `test_color_delta_max_omitted_keeps_the_reel_check_spec_default` (198)
- `test_cli_threads_color_delta_max` (500)
- `test_cli_color_delta_max_defaults_to_none` (520)
- `test_cli_from_episodes_refuses_a_color_delta_max_flag` (670) — superseded by the new test, which refuses the flag everywhere rather than only on the phase-2 path
- the `color_delta_max=None` keyword in the two fake signatures at 801 and 831, and the comment at 639 naming the flag

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/edl_to_reel.py tests/
git commit -m "refactor: --color-delta-max leaves the CLI

The flag tuned a retired check. argparse now fails loud on it, so a stale skill line
or script stops the run instead of setting a ceiling nothing reads. The
--from-episodes refusal drops it from its list for the same reason.

Its own help text carried the diagnosis all along: 'raise ONLY for a reel that
deliberately cuts between scenes of different exposure' describes an ordinary edit."
```

---

### Task 4: the `color_correct` cascade

**Files:**
- Modify: `scripts/lib/models.py` (`ReframeSpec.color_correct` 840 + validation 938-940)
- Modify: `scripts/process_episode.py` (`build_reframe_spec` 32-33 + docstring 41 + the `color_correct=color_correct,` argument 52; `process_episode` parameter 77)
- Modify: `scripts/reframe.py` (the branch 509-510, the docstring sentences 553-556)
- Modify: `scripts/lib/color.py` (delete `corrected`, 404-411)
- Modify: `scripts/probe.py` (delete the docstring caveat 230-245)
- Test: `tests/integration/test_reel_retry.py`, plus any unit test constructing `ReframeSpec(color_correct=...)`

**Interfaces:**
- Consumes: Task 1's driver, which no longer passes the keyword.
- Produces: `build_reframe_spec(m, delivery, params)` — three arguments. `process_episode(manifest_dict, project_dir, route_path=None, max_attempts=3, project=None, keyframes_path=None)`.

**Why this is safe:** `grep -rn "color_correct" scripts/` before this task returns only these sites. `probe.py` **mentions** `color_correct` in its docstring and never passes it, so nothing executable changes there.

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_models.py`:

```python
def test_reframe_spec_no_longer_accepts_color_correct():
    """color_correct existed only for the reel loop's colour pull (design §3). With
    the pull retired it is dead everywhere, and pinned dead here: re-adding the field
    would let a caller compose a per-channel factor onto the grade with nothing
    measuring the damage."""
    with pytest.raises(TypeError):
        m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      layout=m.LayoutSpec(mode="fill"), color_correct=(0.9, 1.0, 1.0))
```

Add to `tests/lib/test_color.py`:

```python
def test_corrected_is_gone():
    """color.corrected composed the reel loop's external pull onto the grade gains and
    re-clamped. The loop is retired and reframe's branch with it, so the primitive has
    no caller (design §3). LO/HI stay — color.gain reads them."""
    assert not hasattr(color, "corrected")
    assert (color.LO, color.HI) == (0.7, 1.5)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py::test_reframe_spec_no_longer_accepts_color_correct tests/lib/test_color.py::test_corrected_is_gone -v`

Expected: both FAIL — the first `DID NOT RAISE TypeError`, the second on `assert not hasattr(color, 'corrected')`.

- [ ] **Step 3: Delete the field, the parameters and the branch**

- `scripts/lib/models.py`: delete `color_correct: tuple | None = None` from `ReframeSpec` and its three-line validation block.
- `scripts/process_episode.py`: drop the fourth parameter from `build_reframe_spec`, delete the sentence `` `color_correct` is the reel loop's per-channel pull, None outside it. `` from its docstring, delete `color_correct=color_correct,` from the `ReframeSpec(...)` it builds, and drop `color_correct: tuple | None = None,` from `process_episode`'s signature.
- `scripts/reframe.py`: replace

```python
    gains = color.gains_for_means(spec.color_means)
    if spec.color_correct is not None:  # reel retry loop; see docstring
        gains = color.corrected(gains, spec.color_correct)
```

with

```python
    gains = color.gains_for_means(spec.color_means)
```

and in the module docstring, change `delivery/layout/max_speed/color_correct/pan/zoom` to `delivery/layout/max_speed/pan/zoom`, then delete the three sentences beginning `spec.color_correct: an optional per-channel factor` through `(None = base grade only).`

- `scripts/lib/color.py`: delete `corrected` entirely.
- `scripts/probe.py`: delete the docstring paragraph from `**The baseline claim is false, silently, ...` through `... or refuse instead of silently showing the wrong grade.` — the caveat describes a pull that can no longer exist.

- [ ] **Step 4: Retire proof (A) and keep proof (B) in the retry integration test**

In `tests/integration/test_reel_retry.py`:

- delete `test_color_correct_pulls_delivered_mean_toward_target` and the `_tinted` helper it is the only user of
- drop the `color_correct=None` parameter from `_reframe` and the `color_correct=color_correct` keyword from the `ReframeSpec` it builds
- delete the `check_reel` import if `_frame_mean` was its only use
- update the module docstring: proof (A) is gone, so it now reads

```python
"""Real-ffmpeg proof for the reel retry loop (design §6): build_reel wires probe →
assemble → check_reel → deliver end-to-end on real files. Clips are built with the
real reframe encoder, matching test_reel_backhalf.py's precedent.

The colour half of this file is retired with the corrector it proved (design
2026-08-29). A reprocess-then-pass proof cannot honestly be rebuilt on the black arm:
a black hit that is IN the source survives a clean re-encode, so the loop would
exhaust rather than converge. The reprocess path keeps its unit coverage in
tests/lib/test_build_reel.py."""
```

- keep the end-to-end test itself, driven by a reel that passes

- [ ] **Step 5: Run the integration file, then the whole suite**

Run: `.venv/bin/python -m pytest tests/integration/test_reel_retry.py -v -m integration`

Expected: PASS (one test).

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Confirm the cascade is complete**

```bash
grep -rn "color_correct\|color_across_cuts\|color_delta_max" --include='*.py' scripts/ tests/
```

Expected: no output. Any hit is a site this slice missed.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py scripts/process_episode.py scripts/reframe.py scripts/lib/color.py scripts/probe.py tests/
git commit -m "refactor: color_correct existed only for the retired loop, so it goes too

ReframeSpec.color_correct, build_reframe_spec's fourth argument, process_episode's
parameter, reframe's compose branch and color.corrected had exactly one producer
between them — build_reel's colour pull. color.LO/HI stay; color.gain reads them.

This deletes probe.py's long caveat rather than satisfying it: probe grade could not
see a pull the loop applied and therefore rendered a baseline the real encode would
not match. With no pull, probe grade is faithful by construction. It also dissolves
the backlog row asking to record the applied factor on PathMeta.

test_reel_retry keeps its end-to-end proof and loses the colour one. A
reprocess-then-pass proof cannot be rebuilt honestly on the black arm — a black hit
in the source survives a clean re-encode."
```

---

### Task 5: the `colour` axis on `reel-review`

**Files:**
- Modify: `scripts/lib/review.py:12-16` (`REVIEW_AXES`, `REVIEW_ROUTES`)
- Modify: `skills/reel-review/reel-reviewer.md` (the axis list ~line 31-38, the `route ∈` rule line)
- Modify: `skills/reel-review/SKILL.md` (the `description` front-matter line, the routing map table ~line 85-90)
- Test: `tests/lib/test_review.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `review.REVIEW_AXES` contains `"colour"`; `review.REVIEW_ROUTES` contains `"match-grade"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_review.py`:

```python
def test_a_colour_finding_routed_to_match_grade_round_trips():
    """Reel-level colour agreement is no longer measured by a machine (design §4-§5):
    a whole-frame mean cannot separate 'different shot' from 'different grade', but a
    reader looking at the per-episode stills the packet already carries can. The axis
    is spelled as episode_qc.QC_AXES spells it."""
    f = review.Finding(axis="colour", severity="important",
                       evidence="ep3's mid still reads markedly bluer than ep2's and ep4's",
                       route="match-grade",
                       suggestion="re-run match-grade so every episode takes one common target",
                       confidence="medium")
    assert review.Finding.from_dict(f.to_dict()) == f


def test_the_american_spelling_is_not_an_axis():
    """One spelling only — 'colour', matching episode_qc.QC_AXES. Two spellings would
    split findings across two axes nobody could aggregate."""
    with pytest.raises(ValueError, match="not in"):
        review.Finding(axis="color", severity="minor", evidence="e",
                       route="match-grade", suggestion="s")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -k "colour or american" -v`

Expected: the first FAILs with `Finding.axis 'colour' not in (...)`; the second FAILs because `route='match-grade'` raises before the axis is reached.

- [ ] **Step 3: Add the two entries**

In `scripts/lib/review.py`:

```python
REVIEW_AXES = ("idea", "mood", "hook", "ending", "spine",       # the §5.13 editorial questions
               "edl_completeness", "trend_flavor",
               "colour")                                        # design 2026-08-29 §4: no machine
                                                                # measures reel-level colour agreement,
                                                                # so the reader who can does
REVIEW_SEVERITY = ("blocking", "important", "minor")             # blocking ⇒ verdict "revise"
REVIEW_ROUTES = ("edit-plan", "pacing", "music",                # the fixer stage the human re-runs
                 "reprocess", "titles", "match-grade", "none")
```

- [ ] **Step 4: Run the file's tests**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -v`

Expected: PASS.

- [ ] **Step 5: Give the reviewer the question**

In `skills/reel-review/reel-reviewer.md`, add one line to the axis list, aligned with the seven above it:

```
- colour           — do the episodes read as ONE grade?          (the per-episode mid stills side by side + EDL.md's shot descriptions)
```

and extend the rule line:

```
- route ∈ (edit-plan, pacing, music, reprocess, titles, match-grade, none) — the fixer stage to re-run.
```

Then add one rule beneath the `trend_flavor` rule:

```
- colour: judge the episodes side by side, and read EDL.md first — a shot of open
  water SHOULD look different from a shot of bright sand. Flag only a difference the
  content does not explain. You have ONE frame per episode: a wave, a cloud or a
  specular flash can read as a grade shift, so say `confidence: "low"` when the
  evidence is a single frame you cannot corroborate.
```

- [ ] **Step 6: Give the routing map its row**

In `skills/reel-review/SKILL.md`, add to the routing-map table:

```
| `match-grade` | match-grade SKILL then `edl_to_reel` | one episode reads as a different grade from the rest |
```

and add `colour` to the axis list in the front-matter `description` after `spine`.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. `tests/test_plugin_manifests.py` and any skill-reference test must stay green.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/review.py skills/reel-review/ tests/
git commit -m "feat: reel-review judges colour, routed to match-grade

After the corrector's deletion nothing automated measures whether the rendered
episodes agree with each other. A whole-frame mean cannot separate 'different shot'
from 'different grade' — that is why the deleted check fired on six of seven real
cuts — but a reader looking at the stills, with EDL.md saying what each shot is, can.

No new evidence is gathered: the packet already grabs one mid-frame per episode, the
same frames the reviewer judges composition from. The template says so, and tells the
reviewer to drop to confidence 'low' when a single frame is all it has.

Spelled 'colour', matching episode_qc.QC_AXES."
```

---

### Task 6: the battery, the version, and the docs

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`, `docs/backlog.md`, `docs/build-status.md`, `docs/pipeline-map.md`
- Modify: `skills/edit-plan/SKILL.md`, `skills/using-montage/SKILL.md` (any `--color-delta-max` mention)

**Interfaces:**
- Consumes: every earlier task.
- Produces: version `0.5.0` in both `CHANGELOG.md`'s top entry and `.claude-plugin/plugin.json` (`tests/test_plugin_manifests.py` enforces that they match).

- [ ] **Step 1: Find every stale mention in prose**

```bash
grep -rn "color_across_cuts\|color-delta-max\|color_delta_max\|color_correct" --include='*.md' . | grep -v "^./docs/specs/\|^./docs/plans/\|^./docs/retro/"
```

Every hit outside `docs/specs/`, `docs/plans/` and `docs/retro/` (which are dated records and stay as written) is a live document promising a knob or a check that no longer exists. Fix each.

- [ ] **Step 2: Run the six-row mutation battery**

Each row reverts one deletion and names the test that must go RED. Run every row with:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <the named test> -q
```

| # | mutation | test that must fail |
|---|---|---|
| 1 | re-add the `color_across_cuts` `CheckResult` line to `check_reel.run` | `tests/lib/test_check_reel.py::test_no_across_cut_colour_check_is_reported` |
| 2 | `_REPROCESS_CLASS = ("black", "color_across_cuts")` | `tests/lib/test_reel_orchestration.py::test_a_colour_failure_is_no_longer_reprocessable` |
| 3 | re-add `color_delta_max: float = 12.0` to `ReelCheckSpec` | `tests/lib/test_models.py::test_reel_check_spec_no_longer_accepts_color_delta_max` |
| 4 | re-add `color_correct: tuple \| None = None` to `ReframeSpec` | `tests/lib/test_models.py::test_reframe_spec_no_longer_accepts_color_correct` |
| 5 | re-add `corrected` to `scripts/lib/color.py` | `tests/lib/test_color.py::test_corrected_is_gone` |
| 6 | drop `"colour"` from `REVIEW_AXES` | `tests/lib/test_review.py::test_a_colour_finding_routed_to_match_grade_round_trips` |

A row that stays GREEN is a coverage hole, not a row to soften — write the missing test.

After each row, restore the file and confirm with `git diff --stat` that the tree is clean before the next.

- [ ] **Step 3: Write the changelog entry**

Add to `CHANGELOG.md` above the `0.4.0` entry:

```markdown
## 0.5.0 — 2026-08-29

**Retired the reel's colour-convergence loop.** `check_reel`'s `color_across_cuts`
compared two frames straddling a cut — two different shots — so six of the only real
reel's seven cuts exceeded its 12.0 default and the operator raised the ceiling to
56.0 to switch it off. Its corrector then optimised a different quantity than the gate
read, demanding pulls of 1.41x and 1.75x against 0.71 dE00 of fidelity headroom. Both
are deleted, along with the `color_correct` cascade they were the only consumers of:
`ReframeSpec.color_correct`, `process_episode`'s parameter, `reframe`'s compose branch
and `color.corrected`.

**Breaking:** `ReelCheckSpec.color_delta_max`, `ReelManifest.color_delta_max`,
`ReframeSpec.color_correct` and `edl_to_reel --color-delta-max` are removed. A
pre-0.5.0 `EPISODES.json` carrying `color_delta_max` is silently ignored; the CLI flag
fails loud.

**Added:** a `colour` axis on `reel-review`, routed to `match-grade`. Reel-level colour
agreement is now judged by a reader over the per-episode stills the packet already
carries, because no whole-frame statistic separates a grade mismatch from a content
change. Nothing automated measures it — see the design's §5.
```

Set `.claude-plugin/plugin.json`'s `version` to `"0.5.0"`.

- [ ] **Step 4: Update the backlog**

In `docs/backlog.md`:

- mark **R2.6** `✅`, with a sentence naming what was measured and that the answer was deletion, linking the design.
- mark the P2 row *"A rejected colour-convergence re-render blames the EDL"* and the P3 row *"record the applied `color_correct` on `PathMeta`"* as `✅ dissolved` — the code they describe no longer exists.
- leave the P2 row *"`probe grade` is the one tool in the convergence loop that cannot predict the gate"* **open**, and add a sentence saying it is more load-bearing after this slice, not less.
- add the three new rows from design §10: crop-accurate grading (P1/L, absorbs R2.1 and R3.1), more frames per episode for the reviewer (P3/S), a grade-movement table in the reviewer's packet (P3/S).

- [ ] **Step 5: Update the registry, status and map**

- `CLAUDE.md`: add a Quick Reference row for this design and plan, and correct the retro row's sentence that still describes `color_across_cuts` as a live check.
- `docs/build-status.md`: a Done entry naming the measurement that decided it and the suite figure.
- `docs/pipeline-map.md`: the reel-check stage no longer lists a colour check; `reel-review` lists a `colour` axis.

- [ ] **Step 6: Run the whole suite one final time**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS. Record the exact `N passed, M skipped` figure in `docs/build-status.md`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: 0.5.0 — what the corrector's deletion changed, and what it did not

The changelog records the breaking contract removals and the one silent case: a
pre-0.5.0 EPISODES.json carrying color_delta_max is ignored, deliberately, because the
key bounded a check that no longer exists.

Backlog: R2.6 closed by deletion; two rows dissolved with the code they describe; the
probe-grade row left open and marked as MORE load-bearing after this slice, since
probe grade is now the only cheap way to converge a grade. Three new rows filed, the
first of them the real fix — measure the grade on the pixels that ship."
```

---

## Self-Review

**Spec coverage.** §2 (the deletions) → Tasks 0-3. §3 (the cascade) → Task 4. §4 (the axis) → Task 5. §6 (contract changes) → Tasks 2-4, with the silent `EPISODES.json` case pinned by a test in Task 2. §7 (`spec_overrides`, `test_reel_retry`) → Tasks 2 and 4. §8's six proofs → Tasks 0-5, one test each, re-run as Task 6's battery. §9 (honest limits) → the changelog and the reviewer-template rule in Task 5 Step 5. §10 (deferred) → Task 6 Step 4.

**Placeholder scan.** Every step names a file, a line region and the literal text to write. No "add validation" or "handle edge cases".

**Type consistency.** `ReprocessItem(idx)` is defined in Task 1 and used in Task 1's own test only. `build_reframe_spec(m, delivery, params)` is defined in Task 4 and has no other caller in this plan. `REVIEW_AXES`/`REVIEW_ROUTES` are read by Task 5's tests alone. `ReelCheckSpec(self.target_dur, self.variety_min)` in Task 2 matches the field order left after the deletion.

**One risk worth naming to the implementer.** Task 1 Step 5 re-points five fixtures in `tests/lib/test_build_reel.py` from a colour failure to a black one. A black failure reprocesses with `color_correct=None` today, so those tests already exercise the black path's *shape* — the risk is that a fixture silently stops driving a reprocess round at all (for example if the failure's `episode_idx` no longer matches). After the re-point, confirm each such test still reaches the reprocess arm by checking that its assertion on `attempts` or `reprocessed` is non-trivially satisfied, not merely that the test passes.
