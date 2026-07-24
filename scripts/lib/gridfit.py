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
