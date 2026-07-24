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
from collections.abc import Sequence
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

    `shifts` is per EPISODE (seconds added to its duration, tail always 0.0); `devs` and
    `needs` are per CUT (one fewer than the episodes). `needs` is what the cut asked for
    before clamping, `devs` what is left after — the pair is what lets the report say
    "phrase needed 0.42s, the allowance is 0.29" instead of only "it did not fit"."""
    level: str
    level_n: int
    phase: int
    shifts: tuple[float, ...]
    devs: tuple[float, ...]
    needs: tuple[float, ...]
    worst: float
    total: float
    fits: bool


def fit_level(durs: Sequence[float], lines: Sequence[float],
              bounds: Sequence[tuple[float, float]], allow: float) -> Fit:
    """Greedy left-to-right snap of the CUMULATIVE cut times onto `lines`.

    Cut i sits at the sum of durations 0..i, so moving one out-point moves every later
    cut with it — the walk therefore carries a running position instead of treating cuts
    independently. Each shift is clamped twice: by `allow` (the musical budget) and by
    that episode's own `bounds` (the room its shot has left, and how far it may shrink),
    whichever binds first. What is left over is the deviation the report shows.

    The LAST episode never moves: its out-point is the reel's end, not a cut, and nothing
    follows it to be out of time with. `level`/`phase` are filled in by best_fit."""
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
    for i, (lo, hi) in enumerate(b):
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
