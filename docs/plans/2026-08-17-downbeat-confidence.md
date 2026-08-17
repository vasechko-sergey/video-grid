# Downbeat Confidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `beats._LOW_HZ` onto its measured plateau (150 → 60 Hz) and add the
confidence gate the backlog has been describing as though it existed, so a track
with no detectable downbeat produces an empty bar grid instead of a phase picked
out of noise.

**Architecture:** Two constants and one comparison inside `beats._downbeat_phase`,
plus one log message. Nothing else moves: the empty-bars path already runs end to
end (`fit_outro`'s `unchanged` rung, `_apply_outro`'s early return,
`edit_plan`'s log), so the gate rides wiring that already exists.

**Tech Stack:** Python, numpy, librosa (lazy import), pytest.

**Design:** [2026-08-17-downbeat-confidence-design.md](../specs/2026-08-17-downbeat-confidence-design.md)

---

## Global Constraints

- **Fail-loud contract, imports at top, typing** — `docs/coding-standards.md`.
- **Whole-object asserts** where a test compares a returned object.
- Scripts run as modules; Python is `.venv/bin/python`; `pythonpath = .`.
- Commit messages say *why*, not only what. One commit per task.
- **Do not** run installers or mutate the environment. Verification is
  read-only plus pytest.
- **Do not** run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.
- The numbers in this plan are measured (design §2/§5). Do not round them, and do
  not re-derive them from a different window size — the threshold is calibrated
  at the window sizes `analyze` actually uses.

## File Structure

| File | Change |
|---|---|
| `scripts/beats.py` | `_LOW_HZ` 150→60, new `_PHASE_MARGIN`, the gate + docstring |
| `scripts/edit_plan.py` | the no-bars log names its third reason |
| `tests/lib/test_beats.py` | the gate's two directions |
| `docs/backlog.md` | the row closes; three deferrals open |
| `docs/build-status.md` | Done entry |
| `CLAUDE.md` | two registry rows |

---

### Task 0: The gate and the re-tune

**Files:**
- Modify: `scripts/beats.py:19-22` (constants), `scripts/beats.py:45-74` (`_downbeat_phase`)
- Test: `tests/lib/test_beats.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_beats.py`, after
`test_downbeat_phase_none_when_too_few_beats`:

```python
def test_downbeat_phase_declines_a_flat_distribution():
    """The four tracks measured on 2026-08-17 (design §3) put every phase within
    ~3% of the others; argmax still returned one, confidently, and the outro fit
    landed the reel on a beat it then called a bar line. A flat input is the
    honest None — the same answer as too-few-beats, reached for the same reason."""
    sr = 22050
    period = 0.5
    times = [i * period for i in range(16)]
    y = np.zeros(int(sr * (times[-1] + period)), dtype=np.float32)
    t = np.arange(int(sr * 0.12)) / sr
    thump = (0.9 * np.sin(2 * np.pi * 40 * t)).astype(np.float32)
    for bt in times:                       # every beat identical — no phase preference
        a = int(bt * sr)
        y[a:a + len(thump)] += thump
    assert beats._downbeat_phase(y, sr, times) is None


def test_downbeat_phase_margin_is_the_ranked_gap_not_the_spread():
    """max/min does NOT discriminate (design §4): a track with one QUIET phase
    scores a high spread while its winner barely leads. Build exactly that — one
    silent phase, three near-equal loud ones — and the detector must decline
    even though max/min is enormous."""
    sr = 22050
    period = 0.5
    times = [i * period for i in range(16)]
    y = np.zeros(int(sr * (times[-1] + period)), dtype=np.float32)
    t = np.arange(int(sr * 0.12)) / sr
    for i, bt in enumerate(times):
        if i % 4 == 1:                     # phase 1 silent -> max/min is huge
            continue
        amp = 0.90 if i % 4 == 2 else 0.88  # winner leads by 2%, far under the margin
        a = int(bt * sr)
        y[a:a + len(t)] += (amp * np.sin(2 * np.pi * 40 * t)).astype(np.float32)
    assert beats._downbeat_phase(y, sr, times) is None
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/lib/test_beats.py -k "declines_a_flat or margin_is_the_ranked" -v
```

Expected: both FAIL, returning an int (some phase) instead of `None`.

- [ ] **Step 3: Re-tune the constants**

Replace `scripts/beats.py:19-22` with:

```python
_LOW_HZ = 60.0                 # kick band edge. 2026-08-14 measured 150 on one cell of one
                               # track; 2026-08-17 swept 8 edges x 4 windows over 5 tracks and
                               # found 150 sits on a knife edge (hit-rate 32/88/59% across
                               # +/-0.05/0.10/0.15) where 60 holds a plateau (91/93/93%) at a
                               # higher margin (2.04 vs 1.67). Still tuned on ONE track — the
                               # other four have no downbeat signal to vote with (design §2).
_BAR_WIN = 0.10                # +/- seconds sampled around each beat
_PHASE_MARGIN = 1.5            # winner/runner-up below this -> no bar grid. Measured over 124
                               # sliding 30s+42s windows (design §5): of 97 windows from four
                               # tracks with NO downbeat, none reaches 1.5 — but five reach
                               # 1.31-1.35, so 1.3 would pass noise. Costs ~1 control window
                               # in 6, which is the right side of the trade.
_MIN_BEATS_FOR_BARS = 8        # below this a per-phase mean is one or two samples
_NFFT = 2048
```

- [ ] **Step 4: Gate the argmax**

In `scripts/beats.py`, replace the `_downbeat_phase` docstring's first three
paragraphs and its final two lines. The docstring becomes:

```python
    """Which of the four beat phases carries the bar's kick — the downbeat, or None.

    Peak STFT energy below _LOW_HZ in a +/-_BAR_WIN window around each beat, averaged
    per phase. The winner is returned only when it leads the runner-up by
    _PHASE_MARGIN; otherwise the four phases are too close to tell apart and None is
    the honest answer, which analyze() turns into an empty bar grid and the outro fit
    reads as its 'unchanged' rung.

    THE GATE IS THE POINT (design 2026-08-17 §5). Measured across five real tracks,
    this detector finds a downbeat on ONE: the other four score 38-50% against a 25%
    chance level at their own best sweep cell, with margins of 1.00-1.03, and no band
    edge or window in a 32-cell sweep recovers a signal. Four-on-the-floor house puts
    a kick on every beat, so the premise — the downbeat carries the kick, the other
    beats do not — is false by construction for a whole genre family. Ungated, argmax
    returned a phase for all four, confidently.

    MEASURE THE RANKED GAP, NOT THE SPREAD. max/min does not discriminate: one track
    scored 1.782 against the control's 1.887 while landing 36% hit-rate, because one
    of its phases was quiet rather than its winner loud (§4).

    ONSET STRENGTH DOES NOT WORK HERE EITHER — the control scored 4.313 / 4.285 /
    4.267 / 4.309, all four phases inside 1%. A detector built on novelty picks a
    phase out of noise and looks like it works. Do not 'simplify' this to
    librosa.onset.

    None when there are fewer than _MIN_BEATS_FOR_BARS beats. Assumes 4/4 (§11.3).
    `beat_times` are relative to the START of `y`, which is what analyze() passes."""
```

and replace the final line `return int(np.argmax(means))` with:

```python
    ranked = sorted(means, reverse=True)
    if ranked[1] <= 0.0 or ranked[0] / ranked[1] < _PHASE_MARGIN:
        return None
    return int(np.argmax(means))
```

- [ ] **Step 5: Run the new tests, then the whole beats file**

```bash
.venv/bin/python -m pytest tests/lib/test_beats.py -v
```

Expected: PASS, including the unmodified
`test_downbeat_phase_finds_the_bass_phase` — its 60 Hz thump scores margin
35.36 at the new band edge (design §7), so the re-tune does not touch it.

- [ ] **Step 6: Commit**

```bash
git add scripts/beats.py tests/lib/test_beats.py
git commit -m "$(cat <<'EOF'
fix(beats): the downbeat detector says when it is guessing

Swept 8 band edges x 4 windows over the five tracks in the 2026-08-03 run's own
music cache. Two findings, neither of them the re-tune the backlog row asked for.

The shipped 150 Hz sits on a knife edge: across +/-0.05/0.10/0.15 the control
scores 32/88/59%, where 60 Hz holds 91/93/93% at a higher margin. A plateau is
what a real signal looks like.

And on four of the five tracks there is no signal at any setting -- 38-50%
against a 25% chance level, margins of 1.00-1.03, optima scattered across the
grid. Four-on-the-floor puts a kick on every beat, so the premise fails by
construction for a whole genre family. Ungated, argmax returned a phase anyway
and the outro fit landed the reel's end on a beat it then reported as a bar line.

_PHASE_MARGIN gates it, calibrated over 124 sliding windows at the sizes analyze
actually uses: of 97 windows from the four signal-less tracks none reaches 1.5,
while five reach 1.31-1.35 -- so 1.3, the obvious round number, passes noise.
EOF
)"
```

---

### Task 1: The no-bars log names its third reason

**Files:**
- Modify: `scripts/edit_plan.py:695-698`

- [ ] **Step 1: Read the current message**

```bash
sed -n '693,700p' scripts/edit_plan.py
```

It names two reasons for an absent bar grid. There are now three.

- [ ] **Step 2: Rewrite it**

Replace the `_log(...)` call inside `if ms is not None and not ms.bars:` with:

```python
        _log(f"outro: {music} has no bar grid — beats found fewer than 8 beats, or no "
             f"phase led the others by the confidence margin (this track's kick does "
             f"not mark its bars — measured on 4 of 5 real tracks, design 2026-08-17 "
             f"§3), or the file predates the 2026-08-14 fields; the reel keeps its "
             f"footage-derived length")
```

- [ ] **Step 3: Run the edit_plan tests**

```bash
.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q
```

Expected: PASS (no test asserts on this message's text; if one does, update it
to match rather than reverting the message).

- [ ] **Step 4: Commit**

```bash
git add scripts/edit_plan.py
git commit -m "$(cat <<'EOF'
docs(edit-plan): an absent bar grid now has three causes, not two

The confidence gate is the third and by far the most common one on real music,
so a run that silently keeps its footage-derived length should say which of the
three happened rather than pointing only at the two that predate the gate.
EOF
)"
```

---

### Task 2: Mutation battery + the whole suite

**These are steps, not suggestions.** Each mutation must be watched red, then
reverted by editing the line back — never with `git checkout`.

- [ ] **Step 1: Mutation — flip the comparison**

Change `< _PHASE_MARGIN` to `> _PHASE_MARGIN` in `scripts/beats.py`.

```bash
.venv/bin/python -m pytest tests/lib/test_beats.py -q
```

Expected: FAIL. Revert by editing the operator back.

- [ ] **Step 2: Mutation — drop the gate entirely**

Delete the two gate lines (keep `return int(np.argmax(means))`).

```bash
.venv/bin/python -m pytest tests/lib/test_beats.py -q
```

Expected: FAIL on both new tests. Revert by re-adding the lines.

- [ ] **Step 3: Mutation — the spread instead of the ranked gap**

Change `ranked[0] / ranked[1]` to `ranked[0] / ranked[-1]`.

```bash
.venv/bin/python -m pytest tests/lib/test_beats.py -q
```

Expected: FAIL on `test_downbeat_phase_margin_is_the_ranked_gap_not_the_spread`
— this is the mutation that test exists for, and design §4 is the reason it is
not a hypothetical. Revert.

- [ ] **Step 4: Mutation — the threshold the measurement rejected**

Change `_PHASE_MARGIN = 1.5` to `1.3`.

```bash
.venv/bin/python -m pytest tests/lib/test_beats.py -q
```

Expected: the synthetic tests may still pass — the synthetic flat inputs sit far
below 1.3. **Record the result either way in the task report**: if they pass, the
suite does not discriminate 1.5 from 1.3, and the only evidence for 1.5 is design
§5's 124-window measurement, which no test reproduces (it needs the real tracks,
which are not in the repo). Say so plainly rather than inventing a test that
pretends otherwise. Revert to 1.5.

- [ ] **Step 5: Full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: the pre-slice baseline (2959 passed, 2 skipped) plus the two new tests
= **2961 passed, 2 skipped**, no golden moved. If a golden did move, stop and
report which — `MUSIC.json` fixtures are the plausible ones and the design did
not predict any.

- [ ] **Step 6: Commit if any test file changed**

```bash
git add -A tests/
git commit -m "test(beats): the mutation battery for the confidence gate"
```

(If nothing changed, skip the commit — say so in the report.)

---

### Task 3: Docs, backlog, registry

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`

- [ ] **Step 1: Close the backlog row**

In `docs/backlog.md`'s P2 table, flip the downbeat row to `✅` and rewrite it to
carry the measurement — the row's own premise ("a second genre is the cheapest
next evidence") was right, and the answer it produced was not a re-tune. State:
five tracks measured; the band edge moved 150 → 60 onto a plateau; four of five
tracks carry no signal at any of 32 sweep cells; the "phase-confidence margin"
the row named did not exist in the code and now does at 1.5, calibrated over 124
sliding windows; and the honest limit that the positive class is still one song.

- [ ] **Step 2: Open the three deferrals (design §9)**

Add to P3:
- a real downbeat detector (madmom or a trained model) — **M**, the honest fix
- calibrate the positive class on more than one song — **S**

Add to P4:
- carry the measured margin on `MusicSpec` so a skill can report how close a
  track came — no consumer asked

Also correct the **Music** P3 line "meter beyond 4/4": it is now one of two known
premise failures, not the only one — the kick-marks-the-bar assumption is the
other, and it fails on more music than 3/4 does.

- [ ] **Step 3: build-status Done entry**

Add an entry naming: the reproduction of the design's §3 numbers (49.61/55.39/
41.46/88.89 against 48.01/54.65/42.03/79.31, 15/18 bars against 14/18); the
sweep; the 124-window threshold calibration and why 1.3 fails; that the shipped
track is Walking On Sunshine and not a Manson track (the earlier prose reads
otherwise at a glance); and that the real 2026-08-03 run's artifacts are on disk
at `~/Downloads/untitled folder/` — which is what made this measurable at all,
and is worth recording for the calibration rows still open.

- [ ] **Step 4: CLAUDE.md registry rows**

Add the design and plan rows to the Quick Reference table, in the established
style (one row each, the design row carrying the load-bearing finding).

- [ ] **Step 5: Verify the docs claims against the code**

```bash
grep -n "_LOW_HZ\|_PHASE_MARGIN" scripts/beats.py
```

Every number quoted in the docs must match what this prints.

- [ ] **Step 6: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(downbeat): close the calibration row with what it actually found

The row asked for a second genre. Four were already on disk, and the answer they
gave was not a re-tuned constant: the detector works on one track of five, which
makes the outro fit a feature that fires on some music and now says so on the
rest. Records where the real run's artifacts live, since three calibration rows
still open are blocked on exactly that material.
EOF
)"
```

---

## Self-Review

**Spec coverage.** Design §2 → Task 0 Step 3. §4 → Task 0 Step 1's second test
and Task 2 Step 3. §5 → Task 0 Steps 3-4. §6 → Tasks 0 and 1. §7 → Task 0 Step 5
(the untouched synthetic test) and Task 2 Step 5. §9 → Task 3 Step 2. §10 → Task
3 Step 1.

**The plan's own weak point, stated rather than hidden.** Task 2 Step 4 is a
mutation check that is expected to *not* discriminate. The threshold 1.5 rests on
a 124-window measurement over five real tracks, and those tracks are not in the
repo and will not be — so no test in this suite can distinguish 1.5 from 1.3. The
step exists to make that fact surface in a task report instead of being
discovered later by someone who assumes the number is test-defended. Writing a
synthetic test that appears to pin 1.5 would be worse than having none: it would
defend a number it does not actually measure.

**Type consistency.** `_downbeat_phase` keeps its `int | None` return; the gate
adds a second `None` route to the one that already exists, and `analyze`'s
`if phase is not None` handles both without change.
