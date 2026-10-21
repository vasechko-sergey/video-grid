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
from collections.abc import Callable, Sequence
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


def lines_at(beats: Sequence[float], level_n: int, phase: int) -> list[float]:
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


FIT_EPS = 0.01     # s. A residual below this counts as "on the line": it is five times
                   # tighter than check_reel's 0.05s beat tolerance, so a fit this stage
                   # calls good cannot fail that gate, and it is loose enough that float
                   # accumulation over a dozen cuts never flips a verdict.


@dataclass(frozen=True)
class Fit:
    """One (level, phase) evaluated against a fixed set of episode durations.

    `shifts` is per EPISODE (seconds added to its duration; 0.0 on the tail unless it is
    held, whose length the grid authors — design 2026-10-21 §2.2); `devs` and `needs` are
    per CUT (one fewer than the episodes). `needs` is what the cut asked for before
    clamping, `devs` what is left after — the pair is what lets the report say "phrase
    needed 0.42s, the allowance is 0.29" instead of only "it did not fit". A held cut is
    chosen, not clamped, so its two are equal.

    `drift` is how far the held cuts landed from the counts they were planned or authored
    at, Σ |out − target| in seconds — best_fit's third key, after `worst` and `total`
    (design 2026-10-21 §2.2). 0.0 with no held episode, so a video-only comparison is the
    one it always was."""
    level: str
    level_n: int
    phase: int
    shifts: tuple[float, ...]
    devs: tuple[float, ...]
    needs: tuple[float, ...]
    worst: float
    total: float
    fits: bool
    drift: float = 0.0


@dataclass(frozen=True)
class Held:
    """An episode whose length the grid authors — a photo or a freeze (design
    2026-10-21 §2.2). `beats` is an authored count, or None for the planner's."""
    beats: int | None
    lo: float      # shortest legal hold, s
    hi: float      # longest, s

    def __post_init__(self) -> None:
        if self.beats is not None and (isinstance(self.beats, bool)
                                       or not isinstance(self.beats, int) or self.beats < 1):
            raise ValueError(f"gridfit.Held.beats must be a whole number of beats >= 1 or "
                             f"None (the planner's pick), got {self.beats!r}")
        for name in ("lo", "hi"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
                raise ValueError(f"gridfit.Held.{name} must be a positive number of seconds, "
                                 f"got {v!r}")
            object.__setattr__(self, name, float(v))
        if self.lo > self.hi:
            raise ValueError(f"gridfit.Held: lo {self.lo} exceeds hi {self.hi} — the hold "
                             f"range is empty")


_SLACK = 1e-9      # s: a candidate exactly at pos + lo / pos + hi is in range despite float sums


def _held_cut(i: int, h: Held, pos: float, run: tuple[int, ...], run_end: bool,
              lines: list[float], beats: list[float], period: float,
              plan: Callable[[float, tuple[int, ...]], int]) -> tuple[float, float]:
    """(out-point, target) of held episode `i` — where it ends, and where its count
    alone would have put it. The out-point is CHOSEN, not snapped (design 2026-10-21
    §2.2). The target is `k` beats from its in-point; inside a run the detected beat
    nearest it wins, so the cut is on a beat by construction. The run's last hold
    (`run_end`, the next episode is footage) chooses among the level's lines instead, so
    the cut back to footage is as musical as every other cut — but only lines within
    [k/2, 2k] beats of its plan, falling back to the beats when none is there. An
    authored count is never moved for the level, and takes the detected beat within
    half a beat of its target even a hair outside the range. A target more than half a
    beat past the last detected beat (music shorter than the reel), or nothing in range
    → the target itself, clamped into the range."""
    k = h.beats if h.beats is not None else plan(pos, run)
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"gridfit.fit_level: plan returned {k!r} for held episode {i} at "
                         f"{pos:.3f}s — it must return a whole number of beats >= 1")
    target = pos + k * period
    lo, hi = pos + h.lo, pos + h.hi
    if target - beats[-1] > period / 2 + _SLACK:
        # Past the grid (the music ends before this count does): no beat is this hold's
        # to choose — snapping to the last one would cut it short in silence. The target
        # is used, and its distance to the nearest line or beat (fit_level) is a dev the
        # fit can see, as a footage cut past the last line has
        return min(max(target, lo), hi), target
    if h.beats is not None and lo - _SLACK <= target <= hi + _SLACK:
        # An authored count inside the range (scripts/pacing.py refuses one outside it at
        # each window's tempo) takes its own beat — the detected one nearest the target —
        # even a hair outside the range: the tracker's jitter must not cost or add a beat
        # to a count the author wrote. A count outside it is clamped by the range rule
        # below, never carried further out by this one
        near = [x for x in beats if abs(x - target) <= period / 2 + _SLACK]
        if near:
            return min(near, key=lambda c: (abs(c - target), c)), target

    def inside(xs: list[float], a: float = lo, b: float = hi) -> list[float]:
        return [x for x in xs if max(lo, a) - _SLACK <= x <= min(hi, b) + _SLACK]

    cands = inside(beats)
    if run_end and h.beats is None:
        # The band keeps the hold in its length class. Across all of [lo, hi] a phrase
        # line is almost always reachable, so every coarse level would "fit" by
        # stretching the last hold and coarsest-that-fits would pick it — a planned 2
        # beats bound to 10 (design §2.2).
        cands = inside(lines, pos + k * period / 2, pos + 2 * k * period) or cands
    if not cands:
        return min(max(target, lo), hi), target
    return min(cands, key=lambda c: (abs(c - target), c)), target     # the earlier on a tie


def fit_level(durs: Sequence[float], lines: Sequence[float],
              bounds: Sequence[tuple[float, float]], allow: float, *,
              beats: Sequence[float] = (), held: Sequence[Held | None] | None = None,
              plan: Callable[[float, tuple[int, ...]], int] | None = None) -> Fit:
    """Greedy left-to-right snap of the CUMULATIVE cut times onto `lines`.

    Cut i sits at the sum of durations 0..i, so moving one out-point moves every later
    cut with it — the walk therefore carries a running position instead of treating cuts
    independently. Each shift is clamped twice: by `allow` (the musical budget) and by
    that episode's own `bounds` (the room its shot has left, and how far it may shrink),
    whichever binds first. What is left over is the deviation the report shows.

    The LAST episode never moves: its out-point is the reel's end, not a cut, and nothing
    follows it to be out of time with. `level`/`phase` are filled in by best_fit.

    `held` (design 2026-10-21 §2.2) marks the episodes whose length nothing in the
    footage fixes — one entry per episode, a `Held` or None for footage — and `plan`
    answers how many beats a held episode at `pos` should take, given the counts `run`
    already used by the held episodes just before it. A held cut is chosen (see
    _held_cut) from the detected `beats`; its deviation is to the nearest detected beat,
    or to the nearest LINE at the run's end, where the cut returns to footage. A held
    tail is placed the same way and records no deviation. `held=None` is the walk
    exactly as it was."""
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
    if isinstance(allow, bool) or not isinstance(allow, (int, float)) or allow <= 0:
        raise ValueError(f"gridfit.fit_level: allow must be a positive number of seconds "
                         f"(see gridfit.allowance), got {allow!r}")
    hd: list[Held | None] = [None] * len(d)
    bt = [float(x) for x in beats]
    if held is None:
        if plan is not None:
            raise ValueError("gridfit.fit_level: a `plan` without `held` has nothing to "
                             "plan — pass the per-episode Held records with it")
    else:
        hd = list(held)
        if len(hd) != len(d):
            raise ValueError(f"gridfit.fit_level: held must carry one entry per episode (a "
                             f"Held, or None for footage) — {len(hd)} against {len(d)} durs")
        bad = [i for i, h in enumerate(hd) if h is not None and not isinstance(h, Held)]
        if bad:
            raise ValueError(f"gridfit.fit_level: held[{bad[0]}] must be a gridfit.Held or "
                             f"None, got {hd[bad[0]]!r}")
        if not callable(plan):
            raise ValueError(f"gridfit.fit_level: held episodes need a `plan(pos, run)` that "
                             f"returns their beat count, got {plan!r}")
        if not bt:
            raise ValueError("gridfit.fit_level: held episodes need the detected `beats` — "
                             "a held cut is chosen among them")
    for i, (lo, hi) in enumerate(b):
        if hd[i] is not None:
            continue      # a held episode's length is chosen, not clamped: never read
        if lo > hi:
            raise ValueError(f"gridfit.fit_level: bounds[{i}] is empty ({lo} > {hi})")
        # Both checks below are non-tail only: the walk forces the tail's shift to 0.0 and
        # never reads its bound (see the loop), so a tail bound that looks too generous for
        # the allowance, or that looks like it shrinks the episode away, is not a real
        # problem — refusing it would be a false refusal on a value that cannot be used.
        if i < len(d) - 1 and (lo > allow or hi < -allow):
            raise ValueError(
                f"gridfit.fit_level: bounds[{i}] ({lo}, {hi}) does not overlap the "
                f"±{allow} allowance — the clamp would have to violate one of the two "
                f"to produce a shift. Bounds are a shot's room around its CURRENT "
                f"length, so they straddle 0; a pair that does not is a caller bug")
        if i < len(d) - 1 and d[i] + lo <= 0:
            raise ValueError(f"gridfit.fit_level: bounds[{i}] lets episode {i} shrink to "
                             f"{d[i] + lo:.3f}s — an episode must stay positive")
    if not ln:
        raise ValueError("gridfit.fit_level got no lines — see lines_at")
    period = 2.0 * float(allow)      # the allowance is half a beat by definition (allowance)
    pos, shifts, devs, needs, drift = 0.0, [], [], [], 0.0
    run: tuple[int, ...] = ()
    for i, dur in enumerate(d):
        tail = i == len(d) - 1
        h = hd[i]
        if h is not None:
            run_end = not tail and hd[i + 1] is None
            out, target = _held_cut(i, h, pos, run, run_end, ln, bt, period, plan)
            shifts.append(out - pos - dur)
            run += (round((out - pos) / period),)
            pos = out
            if not tail:
                ref = ln if run_end else bt
                dev = abs(out - min(ref, key=lambda L: abs(L - out)))
                devs.append(dev)
                needs.append(dev)
                drift += abs(out - target)
            continue
        run = ()          # a run of holds ends at footage
        if tail:
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
               needs=tuple(needs), worst=worst, total=sum(devs), fits=worst <= FIT_EPS,
               drift=drift)


def best_fit(durs: Sequence[float], beats: Sequence[float],
             bounds: Sequence[tuple[float, float]], allow: float,
             levels: Sequence[tuple[str, int]] = GRID_LEVELS, *,
             held: Sequence[Held | None] | None = None,
             plan: Callable[[float, tuple[int, ...]], int] | None = None,
             ) -> tuple[Fit, tuple[Fit, ...]]:
    """The coarsest level whose lines the cuts can reach → (chosen Fit, rejected Fits).

    Walks `levels` coarse → fine and returns the FIRST that fits, so the choice is a rule
    rather than three hardcoded beat counts. Every coarser level it passed over comes back
    in `rejected`, best-phase first, so the report can print the number that rejected it —
    silence here is what let the last run miss a phrase grid by 0.076s per cut without
    anyone knowing.

    Nothing fits → the least-bad Fit is returned with `fits` False and every level in
    `rejected`; the caller decides whether to accept an off-grid reel.

    `held`/`plan` ride through to every fit_level, with `beats` as the detected grid a
    held cut is chosen from (design 2026-10-21 §2.2)."""
    lvl = list(levels)
    if not lvl:
        raise ValueError("gridfit.best_fit: levels must be a non-empty table of "
                         "(name, beats-per-line) — see GRID_LEVELS")
    prev = None
    for i, entry in enumerate(lvl):
        try:
            name, n = entry
        except (TypeError, ValueError):
            raise ValueError(f"gridfit.best_fit: levels[{i}] must be a (name, beats-per-line) "
                             f"pair, got {entry!r}") from None
        if not isinstance(name, str) or not name:
            raise ValueError(f"gridfit.best_fit: levels[{i}] name must be a non-empty str, "
                             f"got {name!r}")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError(f"gridfit.best_fit: levels[{i}] ({name!r}) beats-per-line must "
                             f"be an int >= 1, got {n!r}")
        # `reversed()` below is the whole "coarsest first" rule, and it only means that if
        # the table ascends. A well-typed but unordered table would silently pick a FINER
        # level and still call it the coarsest that fits — the exact silence this stage
        # exists to end.
        if prev is not None and n <= prev[1]:
            raise ValueError(f"gridfit.best_fit: levels must ascend strictly by "
                             f"beats-per-line — levels[{i}] {(name, n)} does not follow "
                             f"{prev}")
        prev = (name, n)
    per_level = []
    for name, n in reversed(lvl):
        best = None
        for phase in range(n):
            lines = lines_at(beats, n, phase)
            if not lines:
                continue      # this phase's grid lands past all beats (a short track):
                              # nothing to fit against here; phase 0 always has a line.
            f = fit_level(durs, lines, bounds, allow, beats=beats, held=held, plan=plan)
            f = Fit(level=name, level_n=n, phase=phase, shifts=f.shifts, devs=f.devs,
                    needs=f.needs, worst=f.worst, total=f.total, fits=f.fits,
                    drift=f.drift)
            if best is None or _rank(f) < _rank(best):
                best = f
        per_level.append(best)
    for i, f in enumerate(per_level):
        if f.fits:
            return f, tuple(per_level[:i])
    least = min(per_level, key=_rank)
    return least, tuple(per_level)


def _rank(f: Fit) -> tuple[float, float, float]:
    """Lower is better: the worst cut, then the sum, then how far the held cuts drifted
    from their counts. The third key is what decides when a run of holds opens the reel:
    the run re-syncs every later cut to whichever line it ends on, so every phase that
    fits ties at (0, 0) and the first phase tried — the hold's SHORTEST legal length —
    would win by the order of a range() (design 2026-10-21 §2.2). drift is 0.0 without
    a held episode, so a video-only choice is unchanged."""
    return f.worst, f.total, f.drift
