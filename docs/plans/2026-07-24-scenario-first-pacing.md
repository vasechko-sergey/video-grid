# Scenario-First Pacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the footage own the cut — `edit-plan` runs before the music, an episode's
duration comes from its own shot, and `pacing` becomes a fitter that picks the coarsest
musical grid level those cuts can reach inside a ±half-beat allowance.

**Architecture:** Two new pure stdlib modules (`lib/gridfit.py` decides the grid,
`lib/anchors.py` finds action anchors), `lib/pacing.py`'s generator half replaced by a
fitter, `edit_plan._bind_pacing` demoted from re-timer to applier-with-a-guard, and the
`scripts/pacing.py` driver re-pointed at `EDL.json` + `FOOTAGE.json` + one-or-more
`MUSIC*.json`. The conveyor's stage table swaps music/pacing behind edit-plan.

**Tech Stack:** Python 3.13, stdlib only in the pure cores (no numpy/librosa — the goldens
pin exact numbers), ffmpeg via `scripts/lib/ffbin` + `scripts/lib/proc` for the one
measurement pass, pytest.

**Design:** [docs/specs/2026-07-24-scenario-first-pacing-design.md](../specs/2026-07-24-scenario-first-pacing-design.md)
(committed as `c149f06`). **Branch:** `feat/scenario-first-pacing`.

**Parked prior work:** branch `wip/montage-run-hardening` (`4841dd3`) holds the hot-patches
written during the first real montage run. Two of its hunks are *adopted* by this plan
(Task 7); the rest belong to other slices and must NOT be pulled in here.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/gridfit.py` (new) | Pure. Grid levels, the cumulative snap, the coarsest-that-fits search. Imports nothing from the repo. |
| `scripts/lib/anchors.py` (new) | Action anchors: a pure local-maxima picker + the one ffmpeg frame-difference probe that feeds it. |
| `scripts/lib/pacing.py` | `Slot` gains `line`/`dev`; `build_spine` (energy → slots) is replaced by `fit_spine` (cuts + beats → slots). The 2/4/8 ladder is deleted. |
| `scripts/lib/footage.py` | `FootageClip.room_after(t)` — seconds left in the same uninterrupted shot. One owner for a fact two callers need. |
| `scripts/lib/offset.py` | `best_offsets(..., k)` returns the top-K window candidates; `best_offset` delegates. |
| `scripts/edit_plan.py` | `window_to_episode(start_offset=)`, `_bind_pacing` applies a fitted spine and refuses a foreign one. |
| `scripts/pacing.py` | Driver: EDL + FOOTAGE + MUSIC(s) → `PACING.{json,md}` fit report. |
| `scripts/montage.py` | `V1_STAGES` order. |
| `skills/{using-montage,pacing,edit-plan}/SKILL.md` | The two-pass flow and the gate. |

---

## Task 0: gridfit levels and lines

**Files:**
- Create: `scripts/lib/gridfit.py`
- Test: `tests/lib/test_gridfit.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_gridfit.py
"""gridfit — the grid levels and the lines they name (design 2026-07-24 §3)."""
import pytest

from scripts.lib import gridfit


def test_levels_are_coarsest_last_and_are_beat_multiples():
    names = [n for n, _ in gridfit.GRID_LEVELS]
    mults = [m for _, m in gridfit.GRID_LEVELS]
    assert names == ["beat", "half-bar", "bar", "2-bar", "phrase"]
    assert mults == [1, 2, 4, 8, 16]
    assert mults == sorted(mults)


def test_lines_at_takes_every_nth_beat_from_the_phase():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    assert gridfit.lines_at(beats, 4, 0) == [0.0, 2.0]
    assert gridfit.lines_at(beats, 4, 1) == [0.5, 2.5]
    assert gridfit.lines_at(beats, 1, 0) == beats


def test_lines_at_refuses_a_phase_outside_its_level():
    with pytest.raises(ValueError, match="phase"):
        gridfit.lines_at([0.0, 0.5], 2, 2)


def test_lines_at_refuses_a_level_below_one():
    with pytest.raises(ValueError, match="level_n"):
        gridfit.lines_at([0.0, 0.5], 0, 0)


def test_lines_at_refuses_an_empty_beat_grid():
    with pytest.raises(ValueError, match="no beats"):
        gridfit.lines_at([], 1, 0)


def test_allowance_is_half_a_beat():
    assert gridfit.allowance(120.0) == pytest.approx(0.25)
    assert gridfit.allowance(104.16666666666667) == pytest.approx(0.288, abs=1e-3)


def test_allowance_refuses_a_nonpositive_tempo():
    with pytest.raises(ValueError, match="tempo"):
        gridfit.allowance(0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_gridfit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.gridfit'`

- [ ] **Step 3: Write the module**

```python
# scripts/lib/gridfit.py
"""Grid fitting (design docs/specs/2026-07-24-scenario-first-pacing-design.md §3).

The pure core of scenario-first pacing: given cut durations the SCENARIO already fixed,
choose the coarsest musical level whose lines those cuts can reach inside a fixed
allowance. stdlib only — NO numpy, NO librosa — so the fit is bit-exact and its goldens
pin exact numbers. Owns the fit value-space exactly as pacing.py owns the spine space;
imports nothing from the repo.

A LEVEL is not a shot length. It answers a different question: which points in the music
count as legal cut points. Beats are not equal — every 4th beat opens a bar, every 4th bar
a phrase — and a cut on a downbeat reads as intended where a cut on the third beat of a bar
reads as accidental. The ladder this replaces fused the two questions into one constant
(a slot IS 2/4/8 beats), which is why a 6-9s surf ride could not be expressed at all."""
from dataclasses import dataclass

# (name, beats per line). Coarser = lines further apart = harder to hit, more musical
# when hit. Ordered fine → coarse; best_fit walks it backwards.
GRID_LEVELS = (("beat", 1), ("half-bar", 2), ("bar", 4), ("2-bar", 8), ("phrase", 16))


def allowance(tempo: float) -> float:
    """Half a beat, in seconds — the fixed budget an out-point may move to reach a line.

    Half a BEAT and never half a LINE: half a phrase is 4.6s at 104 BPM, and an episode
    moved that far is a different episode. The level chooses which lines exist; this
    chooses how far we may reach for one, and it does not grow with the level."""
    if isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or tempo <= 0:
        raise ValueError(f"gridfit.allowance: tempo must be a positive BPM, got {tempo!r}")
    return 30.0 / float(tempo)


def lines_at(beats, level_n: int, phase: int) -> list[float]:
    """Every `level_n`-th DETECTED beat starting at index `phase`.

    Detected beats, not a synthesized metronome: librosa's grid is what check_reel's beat
    gate measures against downstream, and a metronome laid over a real track drifts away
    from it within a few bars — the reel would pass its own fitter and fail the gate."""
    if isinstance(level_n, bool) or not isinstance(level_n, int) or level_n < 1:
        raise ValueError(f"gridfit.lines_at: level_n must be an int >= 1, got {level_n!r}")
    if isinstance(phase, bool) or not isinstance(phase, int) or not 0 <= phase < level_n:
        raise ValueError(f"gridfit.lines_at: phase must be an int in [0, {level_n}), "
                         f"got {phase!r}")
    seq = list(beats)
    if not seq:
        raise ValueError("gridfit.lines_at got no beats — MUSIC.json analyze() found none; "
                         "check the track/window (a grid needs a beat list)")
    return seq[phase::level_n]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_gridfit.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/gridfit.py tests/lib/test_gridfit.py
git commit -m "feat: gridfit levels, lines and the half-beat allowance"
```

---

## Task 1: the cumulative snap

**Files:**
- Modify: `scripts/lib/gridfit.py`
- Test: `tests/lib/test_gridfit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_gridfit.py`:

```python
def test_fit_snaps_the_cumulative_cut_not_each_duration():
    # Three 1.9s episodes against 2.0s lines. Cut 0 wants +0.1; if each duration were
    # snapped independently cut 1 would want +0.1 too — but after cut 0 moved, cut 1
    # already sits at 3.8+0.1=3.9 and needs only +0.1 to reach 4.0. The third episode
    # is the tail: nothing follows it, so it never moves.
    f = gridfit.fit_level([1.9, 1.9, 1.9], [0.0, 2.0, 4.0, 6.0],
                          [(-0.5, 0.5)] * 3, 0.5)
    assert f.shifts == pytest.approx((0.1, 0.1, 0.0), abs=1e-9)
    assert f.worst == pytest.approx(0.0, abs=1e-9)
    assert f.fits is True


def test_fit_leaves_the_tail_episode_alone():
    f = gridfit.fit_level([2.4], [0.0, 2.0, 4.0], [(-0.5, 0.5)], 0.5)
    assert f.shifts == (0.0,)
    assert f.devs == ()
    assert f.fits is True


def test_fit_clamps_to_the_allowance_and_reports_the_residual():
    # Cut wants +0.8 but the allowance is 0.3 → it moves 0.3 and stays 0.5 short.
    f = gridfit.fit_level([1.2, 1.0], [0.0, 2.0], [(-1.0, 1.0)] * 2, 0.3)
    assert f.shifts == pytest.approx((0.3, 0.0), abs=1e-9)
    assert f.devs == pytest.approx((0.5,), abs=1e-9)
    assert f.needs == pytest.approx((0.8,), abs=1e-9)
    assert f.fits is False


def test_fit_clamps_to_the_shot_s_room_before_the_allowance():
    # The allowance would permit +0.8, the shot only has +0.2 left.
    f = gridfit.fit_level([1.2, 1.0], [0.0, 2.0], [(-1.0, 0.2), (-1.0, 1.0)], 1.0)
    assert f.shifts == pytest.approx((0.2, 0.0), abs=1e-9)
    assert f.devs == pytest.approx((0.6,), abs=1e-9)


def test_fit_may_shorten_as_well_as_lengthen():
    f = gridfit.fit_level([2.3, 1.0], [0.0, 2.0], [(-0.5, 0.5)] * 2, 0.5)
    assert f.shifts == pytest.approx((-0.3, 0.0), abs=1e-9)
    assert f.fits is True


def test_fit_refuses_bounds_that_do_not_match_the_episodes():
    with pytest.raises(ValueError, match="bounds"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(-0.5, 0.5)], 0.5)


def test_fit_refuses_a_nonpositive_episode():
    with pytest.raises(ValueError, match="durs"):
        gridfit.fit_level([0.0, 1.0], [0.0, 2.0], [(-0.5, 0.5)] * 2, 0.5)


def test_fit_refuses_an_episode_shortened_out_of_existence():
    with pytest.raises(ValueError, match="bounds"):
        gridfit.fit_level([1.0, 1.0], [0.0, 2.0], [(-2.0, 0.5), (-0.5, 0.5)], 0.5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_gridfit.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.gridfit' has no attribute 'fit_level'`

- [ ] **Step 3: Implement**

Append to `scripts/lib/gridfit.py`:

```python
FIT_EPS = 0.01     # s. A residual below this counts as "on the line": it is five times
                   # tighter than check_reel's 0.05s beat tolerance, so a fit this stage
                   # calls good cannot fail that gate, and it is loose enough that float
                   # accumulation over a dozen cuts never flips a verdict.


@dataclass(frozen=True)
class Fit:
    """One (level, phase) evaluated against a fixed set of episode durations.

    `shifts` is per EPISODE (seconds added to its duration, tail always 0.0); `devs` and
    `needs` are per CUT (one fewer than the episodes). `needs` is what the cut asked for
    before clamping, `devs` what is left after — the pair is what lets the report say
    "phrase needed 0.42s, the allowance is 0.29" instead of only "it did not fit"."""
    level: str
    level_n: int
    phase: int
    shifts: tuple
    devs: tuple
    needs: tuple
    worst: float
    total: float
    fits: bool


def fit_level(durs, lines, bounds, allow: float) -> Fit:
    """Greedy left-to-right snap of the CUMULATIVE cut times onto `lines`.

    Cut i sits at the sum of durations 0..i, so moving one out-point moves every later
    cut with it — the walk therefore carries a running position instead of treating cuts
    independently. Each shift is clamped twice: by `allow` (the musical budget) and by
    that episode's own `bounds` (the room its shot has left, and how far it may shrink),
    whichever binds first. What is left over is the deviation the report shows.

    The LAST episode never moves: its out-point is the reel's end, not a cut, and nothing
    follows it to be out of time with. `level`/`phase` are filled by the caller."""
    d = [float(x) for x in durs]
    b = [(float(lo), float(hi)) for lo, hi in bounds]
    ln = [float(x) for x in lines]
    if not d:
        raise ValueError("gridfit.fit_level got no durs — a fit needs at least one episode")
    if any(x <= 0 for x in d):
        raise ValueError(f"gridfit.fit_level: durs must all be > 0 seconds, got {durs!r}")
    if len(b) != len(d):
        raise ValueError(f"gridfit.fit_level: bounds must carry one (lo, hi) per episode — "
                         f"{len(b)} bounds against {len(d)} durs")
    for i, (lo, hi) in enumerate(b):
        if lo > hi:
            raise ValueError(f"gridfit.fit_level: bounds[{i}] is empty ({lo} > {hi})")
        if d[i] + lo <= 0:
            raise ValueError(f"gridfit.fit_level: bounds[{i}] lets episode {i} shrink to "
                             f"{d[i] + lo:.3f}s — an episode must stay positive")
    if not ln:
        raise ValueError("gridfit.fit_level got no lines — see lines_at")
    pos, shifts, devs, needs = 0.0, [], [], []
    for i, dur in enumerate(d):
        if i == len(d) - 1:
            shifts.append(0.0)
            break
        want = pos + dur
        line = min(ln, key=lambda L: abs(L - want))
        need = line - want
        lo, hi = b[i]
        shift = max(max(lo, -allow), min(min(hi, allow), need))
        shifts.append(shift)
        pos = want + shift
        devs.append(abs(pos - line))
        needs.append(abs(need))
    worst = max(devs) if devs else 0.0
    return Fit(level="", level_n=0, phase=0, shifts=tuple(shifts), devs=tuple(devs),
               needs=tuple(needs), worst=worst, total=sum(devs), fits=worst <= FIT_EPS)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_gridfit.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/gridfit.py tests/lib/test_gridfit.py
git commit -m "feat: gridfit.fit_level — the cumulative snap with two clamps"
```

---

## Task 2: coarsest-that-fits search

**Files:**
- Modify: `scripts/lib/gridfit.py`
- Test: `tests/lib/test_gridfit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_gridfit.py`:

```python
def _metronome(n, step=0.5):
    return [i * step for i in range(n)]


def test_best_fit_prefers_the_coarsest_level_that_fits():
    # 2.0s episodes on a 0.5s beat: every level up to "bar" (4 beats = 2.0s) lands
    # exactly, so the coarsest fitting one wins over the finest.
    beats = _metronome(40)
    chosen, rejected = gridfit.best_fit([2.0] * 4, beats, [(-0.2, 0.2)] * 4, 0.25)
    assert chosen.level == "bar"
    assert chosen.fits is True
    assert [f.level for f in rejected] == ["phrase", "2-bar"]


def test_best_fit_falls_to_a_finer_level_and_names_what_it_rejected():
    beats = _metronome(40)
    chosen, rejected = gridfit.best_fit([1.0] * 4, beats, [(-0.1, 0.1)] * 4, 0.1)
    assert chosen.level == "half-bar"
    assert [f.level for f in rejected] == ["phrase", "2-bar", "bar"]
    assert all(f.fits is False for f in rejected)


def test_best_fit_returns_the_least_bad_when_nothing_fits():
    beats = _metronome(40)
    chosen, rejected = gridfit.best_fit([0.7, 0.7, 0.7], beats, [(0.0, 0.0)] * 3, 0.0)
    assert chosen.fits is False
    assert chosen.worst == min(f.worst for f in rejected + (chosen,))


def test_best_fit_searches_every_phase_of_a_level():
    # Lines every 4th beat; the cut lands on beat index 1, so only phase 1 fits.
    beats = _metronome(40)
    chosen, _ = gridfit.best_fit([0.5, 0.5], beats, [(0.0, 0.0)] * 2, 0.0,
                                 levels=(("bar", 4),))
    assert chosen.phase == 1
    assert chosen.fits is True


def test_best_fit_the_runs_own_reel_reaches_beat_but_not_phrase():
    """The 2026-07-24 run's real cut lengths (design §3): beat fits, coarser does not,
    and the reason is a 0.076s-per-cut drift against the 9.216s phrase."""
    tempo = 104.16666666666667
    beat = 60.0 / tempo
    beats = [i * beat for i in range(120)]
    durs = [4.98, 9.14, 9.14, 9.16, 8.85, 8.73]
    allow = gridfit.allowance(tempo)
    chosen, rejected = gridfit.best_fit(durs, beats, [(-allow, allow)] * 6, allow)
    assert chosen.level == "beat"
    assert chosen.fits is True
    phrase = next(f for f in rejected if f.level == "phrase")
    assert phrase.fits is False
    assert max(phrase.needs) > allow


def test_best_fit_refuses_an_empty_level_table():
    with pytest.raises(ValueError, match="levels"):
        gridfit.best_fit([1.0, 1.0], _metronome(10), [(0.0, 0.0)] * 2, 0.1, levels=())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_gridfit.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.gridfit' has no attribute 'best_fit'`

- [ ] **Step 3: Implement**

Append to `scripts/lib/gridfit.py`:

```python
def best_fit(durs, beats, bounds, allow: float, levels=GRID_LEVELS):
    """The coarsest level whose lines the cuts can reach → (chosen Fit, rejected Fits).

    Walks `levels` coarse → fine and returns the FIRST that fits, so the choice is a rule
    rather than three hardcoded beat counts. Every coarser level it passed over comes back
    in `rejected`, best-phase first, so the report can print the number that rejected it —
    silence here is what let the last run miss by 0.076s per cut without anyone knowing.

    Nothing fits → the least-bad Fit is returned with `fits` False and every level in
    `rejected`; the caller decides whether to accept an off-grid reel."""
    if not levels:
        raise ValueError("gridfit.best_fit: levels must be a non-empty table of "
                         "(name, beats-per-line) — see GRID_LEVELS")
    per_level = []
    for name, n in reversed(list(levels)):
        best = None
        for phase in range(n):
            lines = lines_at(beats, n, phase)
            f = fit_level(durs, lines, bounds, allow)
            f = Fit(level=name, level_n=n, phase=phase, shifts=f.shifts, devs=f.devs,
                    needs=f.needs, worst=f.worst, total=f.total, fits=f.fits)
            if best is None or (f.worst, f.total) < (best.worst, best.total):
                best = f
        per_level.append(best)
    for i, f in enumerate(per_level):
        if f.fits:
            return f, tuple(per_level[:i])
    least = min(per_level, key=lambda f: (f.worst, f.total))
    return least, tuple(per_level)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_gridfit.py -q`
Expected: PASS (21 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/gridfit.py tests/lib/test_gridfit.py
git commit -m "feat: gridfit.best_fit — coarsest level that fits, rejections named"
```

---

## Task 3: FootageClip.room_after

**Files:**
- Modify: `scripts/lib/footage.py`
- Test: `tests/lib/test_footage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_footage.py`:

```python
def test_room_after_runs_to_the_next_scene_cut():
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[12.0, 25.0], windows=[])
    assert clip.room_after(4.0) == pytest.approx(8.0)


def test_room_after_runs_to_the_clip_end_when_no_cut_follows():
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[12.0], windows=[])
    assert clip.room_after(20.0) == pytest.approx(10.0)


def test_room_after_ignores_a_cut_at_the_start_itself():
    # The in-point IS the cut: the shot that starts there runs to the NEXT one.
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[12.0, 25.0], windows=[])
    assert clip.room_after(12.0) == pytest.approx(13.0)


def test_room_after_refuses_a_start_past_the_clip():
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[], windows=[])
    with pytest.raises(ValueError, match="past the end"):
        clip.room_after(30.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -q`
Expected: FAIL — `AttributeError: 'FootageClip' object has no attribute 'room_after'`

- [ ] **Step 3: Implement**

Add to `FootageClip` in `scripts/lib/footage.py`, after `to_dict`:

```python
    def room_after(self, start: float) -> float:
        """Seconds available after `start` inside the SAME uninterrupted shot.

        Running an episode into this room is not stretching footage — no frame is slowed
        or repeated, the shot simply runs longer. intake carves a continuous take into
        WIN_TARGET-sized windows by LENGTH, not by content (its own docstring: "MVI_3739
        = 1 ride -> 3 windows"), so a window boundary inside a shot marks nothing. A
        scene cut does mark something, and running across one would splice two different
        shots into one episode — so the room stops there."""
        if isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0:
            raise ValueError(f"FootageClip.room_after: start must be >= 0 seconds, "
                             f"got {start!r}")
        if start >= self.dur:
            raise ValueError(f"FootageClip.room_after: start {start} is past the end of "
                             f"{self.source} ({self.dur}s)")
        after = [c for c in self.scene_cuts if c > start]
        return float((min(after) if after else self.dur) - start)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/footage.py tests/lib/test_footage.py
git commit -m "feat: FootageClip.room_after — the shot's remaining room, one owner"
```

---

## Task 4: offset.best_offsets (top-K windows)

**Files:**
- Modify: `scripts/lib/offset.py`
- Test: `tests/lib/test_offset.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_offset.py`:

```python
def test_best_offsets_returns_k_candidates_best_first():
    energy = [0.1] * 10 + [0.9] * 10 + [0.5] * 10
    gaps = [(0.0, 0.5), (10.0, 10.5), (20.0, 20.5)]
    got = offset.best_offsets(energy, 1.0, gaps, duration=10.0, track_dur=30.0, k=3)
    assert got == [10.0, 20.0, 0.0]


def test_best_offsets_k_of_one_is_the_old_single_pick():
    energy = [0.1] * 10 + [0.9] * 10 + [0.5] * 10
    gaps = [(0.0, 0.5), (10.0, 10.5), (20.0, 20.5)]
    single = offset.best_offset(energy, 1.0, gaps, duration=10.0, track_dur=30.0)
    assert offset.best_offsets(energy, 1.0, gaps, 10.0, 30.0, k=1) == [single]


def test_best_offsets_never_returns_more_than_it_has():
    energy = [0.5] * 30
    got = offset.best_offsets(energy, 1.0, [(0.0, 0.5)], duration=10.0,
                              track_dur=30.0, k=5)
    assert len(got) == 1


def test_best_offsets_on_a_track_shorter_than_the_window_gives_one_zero():
    assert offset.best_offsets([0.5] * 5, 1.0, [], duration=10.0, track_dur=5.0, k=3) == [0.0]


def test_best_offsets_refuses_a_nonpositive_k():
    with pytest.raises(ValueError, match="k must"):
        offset.best_offsets([0.5] * 30, 1.0, [(0.0, 0.5)], 10.0, 30.0, k=0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.offset' has no attribute 'best_offsets'`

- [ ] **Step 3: Implement**

In `scripts/lib/offset.py`, replace the body of `best_offset` with a delegation and add
`best_offsets` above it:

```python
def best_offsets(mix_energy: Sequence[float], mix_hz: float,
                 gaps: Sequence[tuple[float, float]],
                 duration: float, track_dur: float, k: int = 1) -> list[float]:
    """The top-`k` start_offsets, best (highest mean energy) first.

    One pick is not enough once pacing fits a grid to cuts that already exist: shifting
    the window moves every line with it, so the window is one of the two search axes
    (design 2026-07-24 §3) and the fitter needs alternatives to compare. Ranking is
    unchanged — mean energy over the window, candidates from vocal-gap starts, the
    coarse per-sample slide when no gap is usable. Ties keep the earlier start."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"offset.best_offsets: k must be an int >= 1, got {k!r}")
    if track_dur <= duration:
        return [0.0]
    latest = track_dur - duration

    def win_mean(start: float) -> float:
        a = int(round(start * mix_hz))
        b = int(round((start + duration) * mix_hz))
        seg = mix_energy[a:b]
        return float(np.mean(seg)) if len(seg) else 0.0

    candidates = [g0 for (g0, _g1) in gaps if g0 <= latest + 1e-9]
    if not candidates:
        n = int(latest * mix_hz)
        candidates = [i / mix_hz for i in range(n + 1)]
        if candidates[-1] < latest:
            candidates.append(latest)
    ranked = sorted(candidates, key=lambda s: (-win_mean(s), s))
    return [float(min(s, latest)) for s in ranked[:k]]


def best_offset(mix_energy: Sequence[float], mix_hz: float,
                gaps: Sequence[tuple[float, float]],
                duration: float, track_dur: float) -> float:
    """The single best start_offset — `best_offsets(..., k=1)[0]`. Kept because
    beats.choose_offset and its goldens name it."""
    return best_offsets(mix_energy, mix_hz, gaps, duration, track_dur, k=1)[0]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py tests/lib/test_beats.py -q`
Expected: PASS — the existing `best_offset` tests still pass unchanged

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/offset.py tests/lib/test_offset.py
git commit -m "feat: offset.best_offsets — top-K window candidates for the fitter"
```

---

## Task 5: Slot carries its line and deviation

**Files:**
- Modify: `scripts/lib/pacing.py`
- Test: `tests/lib/test_pacing.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_pacing.py`:

```python
def test_slot_carries_the_line_it_was_matched_to_and_its_deviation():
    s = pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0)
    assert (s.line, s.dev) == (2.0, 0.0)
    assert s.to_dict()["line"] == 2.0
    assert s.to_dict()["dev"] == 0.0


def test_slot_roundtrips_line_and_dev():
    s = pacing.Slot(1, 2.0, 3.0, 0.4, "peak", line=5.0, dev=0.02)
    assert pacing.Slot.from_dict(s.to_dict()) == s


def test_slot_tail_has_no_line():
    s = pacing.Slot(2, 5.0, 4.0, 0.2, "release", line=None, dev=0.0)
    assert s.line is None
    assert pacing.Slot.from_dict(s.to_dict()) == s


def test_slot_refuses_a_negative_deviation():
    with pytest.raises(ValueError, match="dev"):
        pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=-0.1)


def test_slot_refuses_a_nonnumeric_line():
    with pytest.raises(ValueError, match="line"):
        pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line="2.0", dev=0.0)


def test_slot_from_dict_names_the_missing_fit_fields():
    d = {"index": 0, "start": 0.0, "dur": 2.0, "energy": 0.5, "kind": "hook"}
    with pytest.raises(ValueError, match="line"):
        pacing.Slot.from_dict(d)


def test_markdown_shows_the_line_and_deviation():
    spine = pacing.Spine((pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.004),
                          pacing.Slot(1, 2.0, 2.0, 0.4, "peak", line=None, dev=0.0)),
                         4.0, 120.0)
    md = spine.to_markdown()
    assert "| line | dev |" in md
    assert "2.00 | 0.004" in md
    assert "| – | – |" in md
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing.py -q`
Expected: FAIL — `TypeError: Slot.__init__() got an unexpected keyword argument 'line'`

- [ ] **Step 3: Implement**

In `scripts/lib/pacing.py`:

Replace the `Slot` dataclass fields and validation (lines 20–68) with:

```python
@dataclass(frozen=True)
class Slot:
    """One fitted span of the spine. `dur` is the episode's own duration plus whatever
    the snap was allowed to add; `line` is the beat time its out-point was matched to
    (None on the tail — the reel's end is not a cut) and `dev` how far it still is from
    that line. `kind` is an energy-band LABEL, not a temporal role and no longer a
    length: a quiet intro and a quiet outro both read 'release'; 'hook' is positional."""
    index: int
    start: float
    dur: float
    energy: float
    kind: str
    line: float | None = None
    dev: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError(f"Slot.index must be a non-negative int, got {self.index!r}")
        for name in ("start", "dur", "energy", "dev"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"Slot.{name} must be a number, got {v!r}")
            object.__setattr__(self, name, float(v))
        if self.start < 0:
            raise ValueError(f"Slot.start must be >= 0, got {self.start}")
        if self.dur <= 0:
            raise ValueError(f"Slot.dur must be > 0 (a zero-width slot means two beats "
                             f"coincide — the beat grid is malformed), got {self.dur}")
        if not 0.0 <= self.energy <= 1.0:
            raise ValueError(f"Slot.energy must be in [0, 1], got {self.energy}")
        if self.kind not in KINDS:
            raise ValueError(f"Slot.kind {self.kind!r} not in {KINDS}")
        if self.line is not None:
            if isinstance(self.line, bool) or not isinstance(self.line, (int, float)):
                raise ValueError(f"Slot.line must be a beat time in seconds or None "
                                 f"(the tail slot ends the reel, not a cut), got {self.line!r}")
            object.__setattr__(self, "line", float(self.line))
        if self.dev < 0:
            raise ValueError(f"Slot.dev must be >= 0 (it is a distance), got {self.dev}")

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "dur": self.dur,
                "energy": self.energy, "kind": self.kind, "line": self.line,
                "dev": self.dev}

    @classmethod
    def from_dict(cls, d: dict) -> "Slot":
        # Top level checked FIRST, before `k not in d` — a scalar top level raised a bare
        # TypeError, a list/str one mis-read as "missing key(s)".
        if not isinstance(d, dict):
            raise ValueError(f"Slot.from_dict: expected a slot object with index/start/dur/"
                             f"energy/kind/line/dev fields, got {type(d).__name__} — re-run "
                             f"pacing to regenerate PACING.json")
        missing = [k for k in ("index", "start", "dur", "energy", "kind", "line", "dev")
                   if k not in d]
        if missing:
            raise ValueError(f"Slot.from_dict missing key(s) {missing} — a fitted slot needs "
                             f"index, start, dur, energy, kind, line, dev. A PACING.json "
                             f"written before 2026-07-24 has no fit; re-run pacing")
        return cls(index=d["index"], start=d["start"], dur=d["dur"], energy=d["energy"],
                   kind=d["kind"], line=d["line"], dev=d["dev"])
```

Replace `Spine.to_markdown` (lines 133–141) with:

```python
    def to_markdown(self) -> str:
        lines = [f"# Pacing — fitted spine ({len(self.slots)} slots, "
                 f"{self.target_dur:.1f}s @ {self.tempo:.0f} BPM)", "",
                 "| # | start–end | dur | energy | kind | line | dev |",
                 "|--:|-----------|----:|-------:|------|-----:|----:|"]
        for s in self.slots:
            line = f"{s.line:.2f}" if s.line is not None else "–"
            dev = f"{s.dev:.3f}" if s.line is not None else "–"
            lines.append(f"| {s.index} | {s.start:.2f}–{s.start + s.dur:.2f} | "
                         f"{s.dur:.2f} | {s.energy:.2f} | {s.kind} | {line} | {dev} |")
        return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing.py -q`
Expected: FAIL on the *old* `build_spine` goldens (they construct `Slot`s without
`line`/`dev` — those keep working — but assert the old markdown header). Fix each failing
golden by updating its expected markdown header to the new column list. No behaviour is
being changed here; only the report's columns.

Run again: `.venv/bin/python -m pytest tests/lib/test_pacing.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/pacing.py tests/lib/test_pacing.py
git commit -m "feat: Slot carries the line it was fitted to and its deviation"
```

---

## Task 6: fit_spine replaces the ladder

**Files:**
- Modify: `scripts/lib/pacing.py`
- Test: `tests/lib/test_pacing.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_pacing.py`:

```python
def test_fit_spine_keeps_every_episode_s_own_length_when_it_already_lands():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, fit, rejected = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                            [(-0.25, 0.25)] * 3)
    assert [s.dur for s in spine.slots] == pytest.approx([2.0, 2.0, 2.0])
    assert fit.level == "bar"
    assert spine.target_dur == pytest.approx(6.0)


def test_fit_spine_moves_an_out_point_within_the_allowance():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, fit, _ = pacing.fit_spine([1.9, 2.1], beats, energy, 1.0, 120.0,
                                     [(-0.25, 0.25)] * 2)
    assert spine.slots[0].dur == pytest.approx(2.0)
    assert spine.slots[1].dur == pytest.approx(2.1)   # the tail never moves
    assert spine.slots[0].dev == pytest.approx(0.0, abs=1e-9)


def test_fit_spine_slot_zero_is_the_hook_and_the_rest_are_energy_labels():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.1] * 20 + [0.9] * 20
    spine, _, _ = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    assert spine.slots[0].kind == "hook"
    assert {s.kind for s in spine.slots[1:]} <= {"build", "peak", "release"}


def test_fit_spine_covers_the_fitted_length_exactly():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, _, _ = pacing.fit_spine([1.9, 2.1, 1.8], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    assert sum(s.dur for s in spine.slots) == pytest.approx(spine.target_dur)
    assert spine.slots[0].start == 0.0


def test_fit_spine_refuses_an_empty_beat_grid():
    with pytest.raises(ValueError, match="no beats"):
        pacing.fit_spine([2.0], [], [0.5], 1.0, 120.0, [(0.0, 0.0)])


def test_the_ladder_is_gone():
    for dead in ("build_spine", "_beats_per_slot", "HOOK_BEATS", "SLOW_BEATS",
                 "MID_BEATS", "FAST_BEATS"):
        assert not hasattr(pacing, dead), (
            f"{dead} survived: the 2/4/8 ladder generated cut LENGTHS, which the "
            "material now owns (design 2026-07-24 §5)")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.pacing' has no attribute 'fit_spine'`

- [ ] **Step 3: Implement**

In `scripts/lib/pacing.py`:

1. Change the module docstring's second paragraph to:

```python
"""Pacing / fitted spine (design docs/specs/2026-07-24-scenario-first-pacing-design.md §3).

The pure core: given the cut durations the SCENARIO fixed and MUSIC.json's beat grid +
RMS energy curve, snap each out-point onto the coarsest musical grid level it can reach
and emit the fitted spine. Consumed by edit_plan (beat_slot + the snapped dur) and
rendered as PACING.{json,md} by scripts/pacing.py. stdlib only (statistics.fmean) — NO
numpy, NO librosa — so fit_spine is bit-exact and its goldens pin exact slots.

Until 2026-07-24 this module GENERATED lengths from energy (2/4/8 beats per slot), which
capped a slot at 4.6s at 104 BPM and silently truncated any shot that WAS the content —
a surf ride, a trick. Length ownership moved to the footage; what is left here is the
fit."""
```

2. Add the import `from scripts.lib import gridfit` under the stdlib imports. (`gridfit`
   imports nothing from the repo, so this stays acyclic.)

3. Delete `SLOW_BEATS, MID_BEATS, FAST_BEATS`, `HOOK_BEATS`, `_beats_per_slot` and
   `build_spine` entirely. Keep `LOW_BAND, HIGH_BAND`, `_FLAT_EPS`, `_kind`, `_beat_energy`.

4. Add at the end of the file:

```python
def fit_spine(durs, beats, energy, energy_hz: float, tempo: float, bounds,
              levels=gridfit.GRID_LEVELS):
    """Fit the cuts the scenario already fixed onto the coarsest reachable grid level.

    Returns (Spine, chosen Fit, rejected Fits). `durs` are the episodes' own durations,
    `bounds` the per-episode (lo, hi) the snap may move each out-point by — the caller
    derives hi from the shot's remaining room (FootageClip.room_after). The allowance is
    half a beat, from `tempo`, and is NOT a function of the level (design §4).

    Slot 0 is the hook positionally; every other kind is an energy label. The spine
    covers [0, sum(fitted durations)] exactly, so Spine's own contiguity and total
    invariants hold by construction."""
    if not list(beats):
        raise ValueError("fit_spine got no beats — MUSIC.json analyze() found none; "
                         "check the track/window (a fit needs a beat grid)")
    allow = gridfit.allowance(tempo)
    fit, rejected = gridfit.best_fit(durs, beats, bounds, allow, levels=levels)
    fitted = [float(d) + s for d, s in zip(durs, fit.shifts)]
    total = sum(fitted)
    n = _beat_energy(beats, energy, energy_hz, total)
    slots, pos = [], 0.0
    for i, dur in enumerate(fitted):
        span = [n[k] for k, b in enumerate(beats) if pos <= b < pos + dur] or [0.5]
        e = fmean(span)
        tail = i == len(fitted) - 1
        dev = 0.0 if tail else fit.devs[i]
        # The tail's out-point is the reel's end, not a cut: it has no line to be near.
        line = None
        if not tail:
            want = pos + dur
            line = min(gridfit.lines_at(beats, fit.level_n, fit.phase),
                       key=lambda L: abs(L - want))
        slots.append(Slot(i, pos, dur, e, "hook" if i == 0 else _kind(e),
                          line=line, dev=dev))
        pos += dur
    return Spine(tuple(slots), total, float(tempo)), fit, rejected
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing.py -q`
Expected: FAIL on the old `build_spine` tests, which no longer have a function to call.
**Delete** those tests (they pin a generator that no longer exists) — search
`tests/lib/test_pacing.py` for `build_spine` and remove each test that calls it. Keep every
`Slot`/`Spine` contract test.

Run again: `.venv/bin/python -m pytest tests/lib/test_pacing.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/pacing.py tests/lib/test_pacing.py
git commit -m "feat: fit_spine replaces the 2/4/8 ladder — the material owns the length"
```

---

## Task 7: edit_plan adopts start_offset and stops re-timing

**Files:**
- Modify: `scripts/edit_plan.py`
- Test: `tests/lib/test_edit_plan.py`

The `window_to_episode(start_offset=)` hunk and the `build_edl` pop are adopted verbatim
from the parked branch. Read them with:

```bash
git show wip/montage-run-hardening:scripts/edit_plan.py > /tmp/parked_edit_plan.py
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`:

```python
def test_start_offset_moves_the_in_point_but_not_the_duration(footage_clip):
    w = footage_clip.windows[0]
    ep = edit_plan.window_to_episode(footage_clip, w, start_offset=1.5,
                                     composition="center", grid="thirds")
    assert ep.start == pytest.approx(w.start + 1.5)
    assert ep.dur == pytest.approx(w.dur)


def test_start_offset_defaults_to_the_window_start(footage_clip):
    w = footage_clip.windows[0]
    ep = edit_plan.window_to_episode(footage_clip, w, composition="center", grid="thirds")
    assert ep.start == pytest.approx(w.start)


def test_start_offset_refuses_to_cross_a_scene_cut(footage_clip):
    with pytest.raises(ValueError, match="scene cut"):
        edit_plan.window_to_episode(footage_clip, footage_clip.windows[0],
                                    start_offset=footage_clip.scene_cuts[0] + 0.1,
                                    composition="center", grid="thirds")


def test_start_offset_past_the_clip_is_refused(footage_clip):
    with pytest.raises(ValueError, match="past the end"):
        edit_plan.window_to_episode(footage_clip, footage_clip.windows[0],
                                    start_offset=999.0,
                                    composition="center", grid="thirds")


def test_start_offset_must_be_a_nonnegative_number(footage_clip):
    with pytest.raises(ValueError, match="start_offset"):
        edit_plan.window_to_episode(footage_clip, footage_clip.windows[0],
                                    start_offset=-1.0,
                                    composition="center", grid="thirds")


def test_bind_applies_a_fitted_slot_verbatim():
    """A fitted spine's slot IS the episode's duration plus its snap — binding copies it
    across and sets beat_slot; it never invents a length."""
    eps = [_ep(dur=2.0), _ep(dur=3.0)]
    spine = pacing.Spine((pacing.Slot(0, 0.0, 2.1, 0.5, "hook", line=2.1, dev=0.0),
                          pacing.Slot(1, 2.1, 3.0, 0.5, "peak", line=None, dev=0.0)),
                         5.1, 120.0)
    bound = edit_plan._bind_pacing(eps, spine)
    assert [e.dur for e in bound] == pytest.approx([2.1, 3.0])
    assert [e.beat_slot for e in bound] == [0, 1]


def test_bind_refuses_a_spine_fitted_to_a_different_edit():
    """The pre-2026-07-24 behaviour truncated a 7.3s ride into a 4.6s slot in silence.
    A slot further from its episode than the allowance means the spine was fitted to
    OTHER cuts — that is a wiring bug, not a re-time."""
    eps = [_ep(dur=7.3), _ep(dur=3.0)]
    spine = pacing.Spine((pacing.Slot(0, 0.0, 4.6, 0.5, "hook", line=4.6, dev=0.0),
                          pacing.Slot(1, 4.6, 3.0, 0.5, "peak", line=None, dev=0.0)),
                         7.6, 120.0)
    with pytest.raises(ValueError, match="fitted to a different"):
        edit_plan._bind_pacing(eps, spine)
```

Add this fixture near the top of `tests/lib/test_edit_plan.py` if one does not already
exist, and a `_ep` helper. The file needs these imports if it lacks them:
`from scripts.lib import pacing`, `from scripts.lib.edl import EDLEpisode`,
`from scripts.lib.footage import FootageClip, FootageWindow`.

```python
@pytest.fixture
def footage_clip():
    return FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0, shaky=False,
                       scene_cuts=[12.0],
                       windows=[FootageWindow(start=2.0, dur=4.0, shot_type="wide",
                                              people=1, motion=0.4, shake=0.001,
                                              description="a ride", score=0.8, best=True)])


def _ep(dur):
    return EDLEpisode(source="a.mp4", start=0.0, dur=dur, shot_type="wide",
                      composition="center", grid="thirds")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q`
Expected: FAIL — `TypeError: window_to_episode() got an unexpected keyword argument
'start_offset'`

- [ ] **Step 3: Implement**

1. Replace `window_to_episode` with the parked version (from `/tmp/parked_edit_plan.py`),
   which adds the `start_offset` parameter, its four refusals, and the docstring paragraph.

2. Replace `_bind_pacing` (and delete `_room_in_shot` if the parked copy brought it — the
   room now lives on `FootageClip`) with:

```python
_SNAP_TOL = 1e-3      # s of float slack when comparing a slot against its episode


def _bind_pacing(episodes: list, spine: Spine) -> list:
    """Apply a FITTED spine: episode i takes slot i's duration and `beat_slot=i`.

    The spine was fitted TO these episodes (scripts/pacing.py reads the same EDL), so a
    slot may differ from its episode only by the snap the fit was allowed — half a beat.
    A larger difference means this spine was fitted to a DIFFERENT edit, and copying its
    length across would truncate a shot exactly the way the generator used to: a 7.3s
    ride into a 4.6s slot, in silence. Refuse instead.

    Zip-to-min; an over/underflow is logged, never a silent drop (§4.1)."""
    allow = gridfit.allowance(spine.tempo) + _SNAP_TOL
    n = min(len(episodes), len(spine.slots))
    bound = []
    for i in range(n):
        slot, ep = spine.slots[i], episodes[i]
        if abs(slot.dur - ep.dur) > allow:
            raise ValueError(
                f"pacing: slot {i} is {slot.dur:.2f}s against a {ep.dur:.2f}s episode — "
                f"further apart than the {allow:.2f}s snap allows, so this PACING.json "
                f"was fitted to a different edit. Re-run pacing against the current "
                f"EDL.json before binding")
        bound.append(dataclasses.replace(ep, beat_slot=i, dur=slot.dur))
    if len(episodes) > len(spine.slots):
        _log(f"pacing: {len(episodes)} episodes exceed the {len(spine.slots)}-slot spine "
             f"— the {len(episodes) - len(spine.slots)} tail episode(s) keep beat_slot=None; "
             f"re-run pacing against the current EDL.json")
        bound.extend(episodes[n:])
    elif len(spine.slots) > len(episodes):
        _log(f"pacing: {len(spine.slots)} slots exceed the {len(episodes)} episodes — the "
             f"{len(spine.slots) - len(episodes)} tail slot(s) are unfilled")
    return bound
```

3. Add `from scripts.lib import gridfit` to the imports.

4. In `build_edl`, add the `start_offset` pop and forward it (parked hunk):

```python
        # popped like source/window, not forwarded as editorial: it is a MECHANICAL
        # field (it moves the cut), and EDLEpisode would reject it as unknown.
        start_offset = ed.pop("start_offset", 0.0)
```
```python
        episodes.append(window_to_episode(clip, clip.windows[window],
                                          start_offset=start_offset, **ed))
```

5. `_back_edge_target` keeps its body but its docstring's first line becomes:

```python
    """The reel's target length: the realized footage, clamped to the fitted spine. This
    is now the ORDINARY way a target is computed (design 2026-07-24 §1) rather than a
    rescue for an under-fill — the music is cut to the reel, not the reel to the music."""
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q`
Expected: FAIL on existing tests that assert the old re-timing (an episode truncated to a
shorter slot). Update each: a fitted spine no longer shortens an episode, so those tests
either assert the new refusal or use a slot within the allowance. Then PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat: edit_plan adopts start_offset; binding applies a fit, never re-times"
```

---

## Task 8: anchors — the pure picker

**Files:**
- Create: `scripts/lib/anchors.py`
- Test: `tests/lib/test_anchors.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_anchors.py
"""anchors — action anchors from a motion curve (design 2026-07-24 §4)."""
import pytest

from scripts.lib import anchors


def test_one_spike_yields_one_anchor_at_its_time():
    curve = [0.1] * 10 + [0.9] + [0.1] * 10
    got = anchors.anchors_from_curve(curve, hz=3.0)
    assert got == pytest.approx([10 / 3.0], abs=1e-9)


def test_a_flat_curve_yields_no_anchors():
    assert anchors.anchors_from_curve([0.4] * 30, hz=3.0) == []


def test_two_spikes_closer_than_the_min_gap_collapse_to_the_stronger():
    curve = [0.1] * 5 + [0.7] + [0.1] + [0.9] + [0.1] * 5
    got = anchors.anchors_from_curve(curve, hz=3.0, min_gap=2.0)
    assert got == pytest.approx([7 / 3.0], abs=1e-9)


def test_two_spikes_further_apart_than_the_min_gap_both_survive():
    curve = [0.1] * 5 + [0.9] + [0.1] * 10 + [0.85] + [0.1] * 5
    got = anchors.anchors_from_curve(curve, hz=3.0, min_gap=1.0)
    assert got == pytest.approx([5 / 3.0, 16 / 3.0], abs=1e-9)


def test_a_spike_below_the_relative_threshold_is_not_an_anchor():
    curve = [0.1] * 5 + [0.3] + [0.1] * 5 + [1.0] + [0.1] * 5
    got = anchors.anchors_from_curve(curve, hz=3.0, rel=0.6)
    assert got == pytest.approx([11 / 3.0], abs=1e-9)


def test_anchors_refuse_a_nonpositive_hz():
    with pytest.raises(ValueError, match="hz"):
        anchors.anchors_from_curve([0.1, 0.9], hz=0)


def test_anchors_refuse_a_threshold_outside_zero_one():
    with pytest.raises(ValueError, match="rel"):
        anchors.anchors_from_curve([0.1, 0.9], hz=3.0, rel=1.5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_anchors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.anchors'`

- [ ] **Step 3: Implement**

```python
# scripts/lib/anchors.py
"""Action anchors (design docs/specs/2026-07-24-scenario-first-pacing-design.md §4).

An episode's in-point is its meaning — the take-off, the step into the water — so the
fitter never slides it. It may JUMP: to the next point in the shot where something
happens, when that lands a better ending. This module finds those points.

The measure is a PROXY, and the design says so: it is global frame-to-frame difference,
so it fires on any large motion change including a camera whip, not only on a manoeuvre.
Anchors are therefore advisory — the pacing report names each one with its timestamp so
a wrong one is visible rather than silently moving a cut."""
ANCHOR_HZ = 3.0        # samples/s — intake's SAMPLE_FPS, so the two agree about "a moment"
ANCHOR_MIN_GAP = 1.0   # s between anchors: closer than this and they describe one event
ANCHOR_REL = 0.6       # fraction of the curve's own peak a local max must reach. Relative,
                       # not absolute: a telephoto shot and an aerial differ by an order of
                       # magnitude in frame-to-frame difference, and an absolute floor would
                       # find every moment in one and none in the other.


def anchors_from_curve(curve, hz: float = ANCHOR_HZ, min_gap: float = ANCHOR_MIN_GAP,
                       rel: float = ANCHOR_REL) -> list[float]:
    """Local maxima of `curve` above `rel` x its peak, thinned to one per `min_gap`.

    Returns seconds from the curve's start, ascending. Thinning keeps the STRONGER of two
    neighbours rather than the earlier one: a manoeuvre ramps up over several samples, and
    keeping the first would anchor the cut before the action rather than on it."""
    c = [float(x) for x in curve]
    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or hz <= 0:
        raise ValueError(f"anchors_from_curve: hz must be a positive sample rate, got {hz!r}")
    if isinstance(rel, bool) or not isinstance(rel, (int, float)) or not 0 < rel <= 1:
        raise ValueError(f"anchors_from_curve: rel must be a fraction in (0, 1], got {rel!r}")
    if isinstance(min_gap, bool) or not isinstance(min_gap, (int, float)) or min_gap <= 0:
        raise ValueError(f"anchors_from_curve: min_gap must be > 0 seconds, got {min_gap!r}")
    if len(c) < 3:
        return []
    peak = max(c)
    floor = peak * rel
    if peak <= 0 or max(c) - min(c) <= 0:
        return []
    peaks = [i for i in range(1, len(c) - 1)
             if c[i] >= floor and c[i] >= c[i - 1] and c[i] > c[i + 1]]
    kept: list[int] = []
    for i in sorted(peaks, key=lambda i: (-c[i], i)):
        if all(abs(i - j) / hz >= min_gap for j in kept):
            kept.append(i)
    return [i / hz for i in sorted(kept)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_anchors.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/anchors.py tests/lib/test_anchors.py
git commit -m "feat: anchors_from_curve — advisory action anchors, thinned by strength"
```

---

## Task 9: anchors — the ffmpeg measurement

**Files:**
- Modify: `scripts/lib/anchors.py`
- Test: `tests/integration/test_anchors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_anchors.py
"""Real-ffmpeg proof that measure_curve reads motion off actual pixels."""
import pytest

from scripts.lib import anchors, ffbin, proc

pytestmark = pytest.mark.integration


def _clip(path, expr):
    """A 4s 30fps clip whose content follows `expr` (a testsrc-free synthetic)."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c=black:s=320x180:d=4:r=30", "-vf", expr,
              "-pix_fmt", "yuv420p", str(path)])


def test_measure_curve_is_flat_on_a_still_clip(tmp_path):
    src = tmp_path / "still.mp4"
    _clip(src, "drawbox=x=10:y=10:w=40:h=40:color=white:t=fill")
    curve = anchors.measure_curve(str(src), 0.0, 4.0)
    assert len(curve) >= 10
    assert max(curve) - min(curve) < 1.0        # nothing moves, so nothing differs


def test_measure_curve_spikes_where_the_picture_jumps(tmp_path):
    # A box that teleports at t=2s: one large frame-to-frame difference, there and
    # nowhere else.
    src = tmp_path / "jump.mp4"
    _clip(src, "drawbox=x='if(lt(t,2),10,260)':y=10:w=40:h=40:color=white:t=fill")
    curve = anchors.measure_curve(str(src), 0.0, 4.0)
    got = anchors.anchors_from_curve(curve)
    assert got, "the teleport must produce an anchor"
    assert min(abs(t - 2.0) for t in got) < 0.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_anchors.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.anchors' has no attribute
'measure_curve'`

- [ ] **Step 3: Implement**

Add to `scripts/lib/anchors.py` (imports at top of the file):

```python
from scripts.lib import ffbin, proc

ANCHOR_W, ANCHOR_H = 160, 90   # the analysis frame. Fixed, not aspect-preserving: this is
                               # a motion PROXY and a squeezed frame differences the same;
                               # a fixed size keeps the raw-frame arithmetic below exact.
_FRAME_BYTES = ANCHOR_W * ANCHOR_H


def measure_curve(src: str, start: float, dur: float, hz: float = ANCHOR_HZ) -> list[float]:
    """Mean frame-to-frame difference of `src[start : start+dur]`, sampled at `hz`.

    `-ss` goes AFTER `-i` — design §12's first landmine: before the input it is a fast
    keyframe seek and the frames returned are not the frames asked for, which would move
    every anchor by up to a GOP.

    `tblend=all_mode=difference` emits |frame[i] - frame[i-1]| from the second frame on,
    so curve[i] describes the interval between samples i and i+1; the caller's anchor time
    lands at the START of that interval, which is where the action begins."""
    if dur <= 0:
        raise ValueError(f"anchors.measure_curve: dur must be > 0 seconds, got {dur!r}")
    r = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src, "-ss", f"{start}",
                  "-t", f"{dur}", "-vf",
                  f"fps={hz},scale={ANCHOR_W}:{ANCHOR_H},format=gray,"
                  f"tblend=all_mode=difference",
                  "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    raw = r.stdout or b""
    n = len(raw) // _FRAME_BYTES
    return [sum(raw[i * _FRAME_BYTES:(i + 1) * _FRAME_BYTES]) / _FRAME_BYTES
            for i in range(n)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_anchors.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/anchors.py tests/integration/test_anchors.py
git commit -m "feat: anchors.measure_curve — one frame-difference pass, -ss after -i"
```

---

## Task 10: the pacing driver becomes a fitter

**Files:**
- Modify: `scripts/pacing.py`
- Test: `tests/lib/test_pacing_driver.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_pacing_driver.py
"""The pacing driver: EDL + FOOTAGE + MUSIC(s) -> the fit report."""
import json

import pytest

from scripts import pacing as driver


def _write(path, obj):
    path.write_text(json.dumps(obj))
    return str(path)


@pytest.fixture
def run_dir(tmp_path):
    beats = [i * 0.5 for i in range(40)]
    _write(tmp_path / "MUSIC.json",
           {"track": "t.mp3", "start_offset": 0.0, "duration": 20.0, "tempo": 120.0,
            "beats": beats, "energy": [0.5] * 20, "energy_hz": 1.0})
    _write(tmp_path / "FOOTAGE.json",
           {"clips": [{"source": "a.mp4", "dur": 30.0, "res": [1920, 1080], "fps": 30.0,
                       "shaky": False, "scene_cuts": [],
                       "windows": [{"start": 0.0, "dur": 2.0, "shot_type": "wide",
                                    "people": 1, "motion": 0.4, "shake": 0.001,
                                    "description": "d", "score": 0.8, "best": True}]}]})
    _write(tmp_path / "EDL.json",
           {"episodes": [{"source": "a.mp4", "start": 0.0, "dur": 1.9, "shot_type": "wide",
                          "composition": "center", "grid": "thirds"},
                         {"source": "a.mp4", "start": 4.0, "dur": 2.1, "shot_type": "wide",
                          "composition": "center", "grid": "thirds"}],
            "cap": 3})
    return tmp_path


def test_fit_writes_both_artifacts_and_returns_the_spine(run_dir):
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [str(run_dir / "MUSIC.json")], str(run_dir))
    assert (run_dir / "PACING.json").exists()
    assert (run_dir / "PACING.md").exists()
    assert len(res["spine"].slots) == 2


def test_the_report_names_every_rejected_level_with_its_number(run_dir):
    driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                        [str(run_dir / "MUSIC.json")], str(run_dir))
    md = (run_dir / "PACING.md").read_text()
    assert "| level | step | worst | needed | verdict |" in md
    assert "phrase" in md and "beat" in md


def test_the_snapped_durations_stay_inside_the_shot_s_room(run_dir):
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [str(run_dir / "MUSIC.json")], str(run_dir))
    # window at 4.0 in a 30s cut-free clip has 26s of room; the snap is capped by the
    # allowance (0.25s at 120 BPM), not the room.
    assert res["spine"].slots[0].dur == pytest.approx(2.0)


def test_several_music_candidates_are_compared_and_the_best_wins(run_dir):
    shifted = [i * 0.5 + 0.13 for i in range(40)]
    _write(run_dir / "MUSIC_b.json",
           {"track": "t.mp3", "start_offset": 5.0, "duration": 20.0, "tempo": 120.0,
            "beats": shifted, "energy": [0.5] * 20, "energy_hz": 1.0})
    res = driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                              [str(run_dir / "MUSIC.json"), str(run_dir / "MUSIC_b.json")],
                              str(run_dir))
    assert res["music"] == str(run_dir / "MUSIC.json")   # the un-shifted grid lands exactly


def test_an_edl_source_missing_from_footage_fails_loud(run_dir):
    _write(run_dir / "EDL.json",
           {"episodes": [{"source": "ghost.mp4", "start": 0.0, "dur": 1.9,
                          "shot_type": "wide", "composition": "center", "grid": "thirds"}],
            "cap": 3})
    with pytest.raises(ValueError, match="ghost.mp4"):
        driver.build_pacing(str(run_dir / "EDL.json"), str(run_dir / "FOOTAGE.json"),
                            [str(run_dir / "MUSIC.json")], str(run_dir))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_driver.py -q`
Expected: FAIL — `TypeError: build_pacing() takes ... positional arguments`

- [ ] **Step 3: Implement**

Replace `scripts/pacing.py` entirely with:

```python
# scripts/pacing.py
"""Pacing driver (design docs/specs/2026-07-24-scenario-first-pacing-design.md §6):
read the EDL the scenario produced, the footage it came from and one or more analyzed
music windows, fit the cuts onto the coarsest reachable grid, write PACING.{json,md}.

The stage runs AFTER edit-plan, not before it: the cuts are the input, the grid is the
output. edit_plan then re-runs with --pacing to apply the fit."""
import argparse
import json
import sys
from pathlib import Path

from scripts.lib import anchors, gridfit, pacing
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage
from scripts.lib.models import MusicSpec


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _bounds(edl: EDL, footage: Footage, allow: float) -> list[tuple[float, float]]:
    """Per-episode (lo, hi) the snap may move an out-point by. `hi` is whichever is
    smaller: the allowance, or the room the episode's own shot still has after it ends.
    `lo` is the allowance, floored so the episode cannot vanish."""
    by_source = {c.source: c for c in footage.clips}
    out = []
    for i, ep in enumerate(edl.episodes):
        clip = by_source.get(ep.source)
        if clip is None:
            raise ValueError(f"pacing: EDL episode {i} references {ep.source!r}, which is "
                             f"not in FOOTAGE.json — have {sorted(by_source)}")
        room = clip.room_after(ep.start)
        out.append((-min(allow, ep.dur / 2.0), min(allow, max(0.0, room - ep.dur))))
    return out


def _report(spine, fit, rejected, music_path: str, anchor_map: dict) -> str:
    lines = ["# Pacing — fit report", "",
             f"- **Music:** `{Path(music_path).name}`",
             f"- **Level:** {fit.level} (every {fit.level_n} beat(s), phase {fit.phase})",
             f"- **Verdict:** {'fits' if fit.fits else 'OFF-GRID — see below'}", "",
             "| level | step | worst | needed | verdict |",
             "|-------|-----:|------:|-------:|---------|"]
    for f in list(rejected) + [fit]:
        need = max(f.needs) if f.needs else 0.0
        lines.append(f"| {f.level} | {f.level_n} beats | {f.worst:.3f} | {need:.3f} | "
                     f"{'fits' if f.fits else 'misses'} |")
    lines += ["", spine.to_markdown()]
    if anchor_map:
        lines += ["## Action anchors (advisory)", "",
                  "A proxy — global frame difference, so a camera whip reads as an event "
                  "too. Move an in-point onto one by setting `start_offset` in "
                  "selection.json and re-running edit-plan.", "",
                  "| episode | anchors (s from the in-point) |",
                  "|--------:|-------------------------------|"]
        for i, ts in sorted(anchor_map.items()):
            lines.append(f"| {i} | {', '.join(f'{t:.2f}' for t in ts) or '–'} |")
    return "\n".join(lines) + "\n"


def build_pacing(edl_json: str, footage_json: str, music_jsons: list[str], out_dir: str,
                 footage_root: str | None = None, with_anchors: bool = False) -> dict:
    """Fit the EDL's cuts onto the best of the supplied music windows.

    Every candidate window is fitted; the one whose best level is coarsest (ties broken by
    the smaller worst deviation) wins. Returns {"json", "md", "spine", "fit", "music"}."""
    if not music_jsons:
        raise ValueError("pacing: at least one --music MUSIC.json is required — the fit "
                         "needs a beat grid (a silent reel skips this stage entirely)")
    edl = EDL.from_json(edl_json)
    footage = Footage.from_json(footage_json)
    durs = [ep.dur for ep in edl.episodes]
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
            best = (rank, spine, fit, rejected, path)
    _rank, spine, fit, rejected, music_path = best
    if not fit.fits:
        _log(f"pacing: no level fits — best is {fit.level} with a worst cut of "
             f"{fit.worst:.3f}s. Try another window (beats --auto-start), another "
             f"scenario length, or accept an off-grid reel (check_reel's beat gate is "
             f"advisory)")
    anchor_map: dict[int, list[float]] = {}
    if with_anchors:
        root = Path(footage_root or ".")
        for i, ep in enumerate(edl.episodes):
            curve = anchors.measure_curve(str(root / ep.source), ep.start, ep.dur)
            anchor_map[i] = anchors.anchors_from_curve(curve)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "PACING.json", out / "PACING.md"
    json_path.write_text(json.dumps(spine.to_dict(), indent=2))
    md_path.write_text(_report(spine, fit, rejected, music_path, anchor_map))
    return {"json": str(json_path), "md": str(md_path), "spine": spine, "fit": fit,
            "music": music_path}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="fit the EDL's cuts onto a musical grid -> PACING.{json,md}")
    ap.add_argument("--edl", required=True, help="EDL.json from edit-plan (the cuts)")
    ap.add_argument("--footage", required=True, help="FOOTAGE.json (for each shot's room)")
    ap.add_argument("--music", required=True, action="append",
                    help="MUSIC.json — repeat to compare several analyzed windows")
    ap.add_argument("--out-dir", required=True, help="where to write PACING.{json,md}")
    ap.add_argument("--footage-root", help="root the EDL's sources resolve against "
                                           "(required with --anchors)")
    ap.add_argument("--anchors", action="store_true",
                    help="measure action anchors for each episode (one ffmpeg pass each)")
    a = ap.parse_args()
    if a.anchors and not a.footage_root:
        ap.error("--anchors needs --footage-root to find the clips")
    res = build_pacing(a.edl, a.footage, a.music, a.out_dir, a.footage_root, a.anchors)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_pacing_driver.py -q`
Expected: PASS (5 tests)

Then delete the obsolete driver tests: search `tests/` for `build_pacing(` calls with the
old `(music_json, out_dir, spec_json)` signature and remove those tests — the stage no
longer reads SPEC (the scenario owns the length now).

- [ ] **Step 5: Commit**

```bash
git add scripts/pacing.py tests/lib/test_pacing_driver.py
git commit -m "feat: pacing driver fits the EDL's cuts, compares windows, reports why"
```

---

## Task 11: the conveyor's stage order

**Files:**
- Modify: `scripts/montage.py:37-57`
- Test: `tests/lib/test_montage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_montage.py`:

```python
def test_edit_plan_comes_before_music_and_pacing():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("edit-plan") < keys.index("music-and-mood")
    assert keys.index("edit-plan") < keys.index("pacing")


def test_pacing_still_follows_the_music_it_fits_against():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("music-and-mood") < keys.index("pacing")


def test_a_run_with_footage_but_no_edl_asks_for_edit_plan_not_music(tmp_path):
    (tmp_path / "project.json").write_text("{}")
    (tmp_path / "FOOTAGE.json").write_text("{}")
    assert montage.next_action(str(tmp_path))["next"] == "edit-plan"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: FAIL — `assert 5 < 4`

- [ ] **Step 3: Implement**

In `scripts/montage.py`, move the `edit-plan` Stage entry so it sits directly after
`trend-scan`, leaving `music-and-mood` and `pacing` after it, and update `pacing`'s runner
string:

```python
    Stage("trend-scan", "TRENDS.md", "deferred", "5.4 - not built", None),
    Stage("edit-plan", "EDL.json", "required",
          "edit-plan SKILL -> edit_plan build CLI", "edl"),
    Stage("music-and-mood", "MUSIC.json", "optional",
          "beats CLI (absent -> silent reel)", None),
    Stage("pacing", "PACING.md", "optional",
          "pacing SKILL -> pacing CLI (fits the EDL's cuts; edit-plan re-runs with "
          "--pacing to apply)", None),
    Stage("assemble-draft", "draft.mp4", "optional",
          "draft CLI (optional QA preview)", "edl"),
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: the conveyor runs edit-plan before music and pacing"
```

---

## Task 12: skills wiring

**Files:**
- Modify: `skills/using-montage/SKILL.md`, `skills/pacing/SKILL.md`,
  `skills/edit-plan/SKILL.md`
- Test: `tests/test_skill_convention.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_convention.py`:

```python
def test_the_pacing_skill_documents_the_two_pass_flow():
    text = (SKILLS / "pacing" / "SKILL.md").read_text()
    assert "--edl" in text and "--footage" in text
    assert "edit_plan build --pacing" in text, (
        "the fit is APPLIED by re-running edit-plan; a skill that stops at PACING.json "
        "leaves the EDL un-snapped")


def test_using_montage_orders_edit_plan_before_music():
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    assert text.index("edit_plan build") < text.index("scripts.beats")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: FAIL — `--edl` not in the pacing skill

- [ ] **Step 3: Implement**

In `skills/pacing/SKILL.md`, replace the procedure section with:

```markdown
## The Process

Announce on entry: **"Using pacing to fit the cuts onto the music's grid."**

1. **Recon.** The EDL must already exist — pacing runs AFTER edit-plan (design
   2026-07-24 §1). No `EDL.json` -> run edit-plan first; this stage has nothing to fit.
2. **Analyze the candidate windows.** `beats --auto-start` picks one; for a real choice
   ask it for more and analyze each into its own `MUSIC_<k>.json`. Shifting the window
   moves every grid line with it, so it is one of the two search axes.
3. **Fit.**
   `"$VG" scripts.pacing --edl <run>/EDL.json --footage <run>/FOOTAGE.json --music <run>/MUSIC.json [--music <run>/MUSIC_2.json ...] --out-dir <run>`
   Add `--anchors --footage-root <root>` to also measure action anchors (one ffmpeg pass
   per episode).
4. **Read the report.** `PACING.md` names the level chosen and every coarser level it
   rejected WITH the number that rejected it. A miss is actionable, not fatal: try
   another window, change a scenario length, or accept an off-grid reel (check_reel's
   beat gate is advisory).
5. **Apply.** `"$VG" scripts.edit_plan build ... --pacing <run>/PACING.json` — this is
   what writes the snapped durations and `beat_slot` into `EDL.json`. Stopping at step 4
   leaves the EDL un-snapped.
```

In `skills/using-montage/SKILL.md`, move the music/pacing bullets after the edit-plan
bullet and add:

```markdown
The scenario comes first and the music is fitted to it (design 2026-07-24). Run
`edit_plan build` with NO `--pacing` to get the cuts at their material lengths, then
`pacing`, then `edit_plan build --pacing` to apply the fit. Never re-time a shot to make
a slot: a shot that IS the content — a ride, a trick — is not a slot's length.
```

In `skills/edit-plan/SKILL.md`, add under its inputs:

```markdown
`start_offset` (optional, per selection episode) moves the in-point later inside the SAME
shot — the window grid is a scoring artifact, not an editorial one. It never crosses a
scene cut and never changes `dur`. Use it to start on the first manoeuvre when the pacing
report says that lands a better ending.
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ tests/test_skill_convention.py
git commit -m "docs: skills carry the scenario-first order and the two-pass fit"
```

---

## Task 13: real-ffmpeg end-to-end proof

**Files:**
- Create: `tests/integration/test_scenario_first.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_scenario_first.py
"""The slice's proof over real pixels: a reel whose episodes keep their measured
durations end to end, and a spine that never invents one."""
import json

import pytest

from scripts import edit_plan, pacing as pacing_driver
from scripts.lib import ffbin, proc

pytestmark = pytest.mark.integration

_LONG = 7.3      # a "ride": longer than any slot the deleted 2/4/8 ladder could make


def _clip(path, dur):
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"testsrc=size=320x180:rate=30:duration={dur}", "-pix_fmt", "yuv420p",
              str(path)])


def test_a_ride_keeps_its_length_through_fit_and_bind(tmp_path):
    src = tmp_path / "ride.mp4"
    _clip(src, 20.0)
    beats = [i * 0.5 for i in range(80)]
    (tmp_path / "MUSIC.json").write_text(json.dumps(
        {"track": "t.mp3", "start_offset": 0.0, "duration": 40.0, "tempo": 120.0,
         "beats": beats, "energy": [0.5] * 40, "energy_hz": 1.0}))
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(
        {"clips": [{"source": "ride.mp4", "dur": 20.0, "res": [320, 180], "fps": 30.0,
                    "shaky": False, "scene_cuts": [],
                    "windows": [{"start": 0.0, "dur": _LONG, "shot_type": "wide",
                                 "people": 1, "motion": 0.4, "shake": 0.0,
                                 "description": "ride", "score": 0.9, "best": True}]}]}))
    (tmp_path / "EDL.json").write_text(json.dumps(
        {"episodes": [{"source": "ride.mp4", "start": 0.0, "dur": _LONG,
                       "shot_type": "wide", "composition": "center", "grid": "thirds"},
                      {"source": "ride.mp4", "start": 10.0, "dur": 5.0,
                       "shot_type": "wide", "composition": "center", "grid": "thirds"}],
         "cap": 3}))

    res = pacing_driver.build_pacing(str(tmp_path / "EDL.json"),
                                     str(tmp_path / "FOOTAGE.json"),
                                     [str(tmp_path / "MUSIC.json")], str(tmp_path))
    spine = res["spine"]
    # The ride reaches a line by moving at most half a beat, and NOTHING truncates it to
    # the 4 x 0.5s = 2.0s a "peak" slot used to be.
    assert spine.slots[0].dur == pytest.approx(_LONG, abs=0.25)
    assert spine.slots[0].dur > 4.6

    selection = {"episodes": [{"source": "ride.mp4", "window": 0,
                               "composition": "center", "grid": "thirds"}]}
    from scripts.lib.footage import Footage
    edl = edit_plan.build_edl(Footage.from_json(str(tmp_path / "FOOTAGE.json")),
                              selection, pacing=spine)
    assert edl.episodes[0].dur == pytest.approx(spine.slots[0].dur)
    assert edl.episodes[0].beat_slot == 0


def test_a_spine_from_another_edit_is_refused_not_applied(tmp_path):
    from scripts.lib import pacing as core
    from scripts.lib.footage import Footage
    _clip(tmp_path / "ride.mp4", 20.0)
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(
        {"clips": [{"source": "ride.mp4", "dur": 20.0, "res": [320, 180], "fps": 30.0,
                    "shaky": False, "scene_cuts": [],
                    "windows": [{"start": 0.0, "dur": _LONG, "shot_type": "wide",
                                 "people": 1, "motion": 0.4, "shake": 0.0,
                                 "description": "ride", "score": 0.9, "best": True}]}]}))
    foreign = core.Spine((core.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0),), 2.0,
                         120.0)
    selection = {"episodes": [{"source": "ride.mp4", "window": 0,
                               "composition": "center", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="fitted to a different"):
        edit_plan.build_edl(Footage.from_json(str(tmp_path / "FOOTAGE.json")),
                            selection, pacing=foreign)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_scenario_first.py -q`
Expected: FAIL until Tasks 6, 7 and 10 are all in (run it last).

- [ ] **Step 3: Implement**

No production code — this task is the proof. If it fails, the fault is in Tasks 6/7/10;
fix there, not here.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_scenario_first.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_scenario_first.py
git commit -m "test: real-ffmpeg proof a ride survives the fit at its own length"
```

---

## Task 14: mutation battery, docs sync, whole suite

**Files:**
- Modify: `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`,
  `docs/specs/2026-07-14-pacing-design.md`

- [ ] **Step 1: Run the mutation battery**

These are steps, not suggestions. For each, make the mutation, run the named test, confirm
it FAILS, then revert.

| # | Mutation | Must fail |
|---|----------|-----------|
| 1 | `gridfit.allowance` returns `30.0 / tempo * level_n` (half a LINE) | `test_allowance_is_half_a_beat` |
| 2 | `best_fit` iterates `levels` fine → coarse (drops `reversed`) | `test_best_fit_prefers_the_coarsest_level_that_fits` |
| 3 | `best_fit` returns the first fitting level with `rejected=()` | `test_best_fit_falls_to_a_finer_level_and_names_what_it_rejected` |
| 4 | `fit_level` snaps each `dur` independently (`pos = 0` each iteration) | `test_fit_snaps_the_cumulative_cut_not_each_duration` |
| 5 | `fit_level` clamps by `allow` only (drops the `bounds` clamp) | `test_fit_clamps_to_the_shot_s_room_before_the_allowance` |
| 6 | `_bind_pacing` drops the allowance guard and copies `slot.dur` | `test_bind_refuses_a_spine_fitted_to_a_different_edit` |
| 7 | `measure_curve` puts `-ss` before `-i` | `proc.run`'s landmine guard raises (`tests/lib/test_landmine_scan.py` + the integration test) |
| 8 | `anchors_from_curve` keeps the earlier of two close peaks | `test_two_spikes_closer_than_the_min_gap_collapse_to_the_stronger` |

- [ ] **Step 2: Sync the docs**

`CLAUDE.md` — add two registry rows after the pacing rows:

```markdown
| Scenario-first pacing design | [2026-07-24-scenario-first-pacing-design.md](docs/specs/2026-07-24-scenario-first-pacing-design.md) | §5.6 re-cut: edit-plan runs BEFORE the music, an episode's length comes from its own shot, and pacing becomes a fitter — the coarsest grid **level** (beat/half-bar/bar/2-bar/phrase) whose lines the existing cuts reach inside a fixed **±half-beat** allowance (never ½ a line). Kills the 2/4/8 ladder that capped a slot at 4.6s. |
| Scenario-first pacing plan | [2026-07-24-scenario-first-pacing.md](docs/plans/2026-07-24-scenario-first-pacing.md) | Tasks 0–14: `gridfit` (levels/cumulative snap/coarsest-that-fits), `FootageClip.room_after`, `offset.best_offsets`, `Slot.line/dev`, `fit_spine`, edit_plan's `start_offset` + the binding guard, the driver's fit report, `anchors`, stage order, skills, real-ffmpeg proof, 8-check mutation battery. |
```

`docs/specs/2026-07-14-pacing-design.md` — add at the top, under the status line:

```markdown
> **Superseded in part (2026-07-24).** The generator half of this design — a slot's
> length derived from local energy via a 2/4/8 beat ladder — is replaced by
> [scenario-first pacing](2026-07-24-scenario-first-pacing-design.md): the footage owns
> the cut and this stage fits a grid to it. The energy curve, the `Slot`/`Spine`
> contracts and the beat-alignment goal all survive.
```

`docs/build-status.md` — add an entry naming the slice, the deleted ladder, the new stage
order, and the parked `wip/montage-run-hardening` branch as the source of the two adopted
hunks.

`docs/pipeline-map.md` — swap §5.5/§5.6 behind §5.7 in the stage list and note the
two-pass edit-plan.

- [ ] **Step 3: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green. Record the exact counts in `docs/build-status.md`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "docs: sync registry, build-status, pipeline-map for scenario-first pacing"
```

---

## Self-Review Notes

**Spec coverage.** §1 order → Task 11 + 12. §2 duration ownership → Tasks 3, 6, 7. §3
levels/two axes → Tasks 0, 1, 2, 4, 10. §4 allowance + anchors → Tasks 0 (allowance), 8, 9,
10 (report). §5 deletions → Task 6 (`test_the_ladder_is_gone`) — note the parked
`slot_scale`/`bands` never enter the tree, so nothing to delete there. §6 report + gate →
Task 10. §7 contracts → every task's file list. §8 testing → Tasks 13, 14.

**Known follow-ups, deliberately out of this plan:** ranking several *tracks* by fit
(design §9), intake's per-clip checkpointing and window band (slice B), the draft gate
(slice D), provenance (slice E), colour (slice F).
