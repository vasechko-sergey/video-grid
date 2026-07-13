"""Pure decision core for start-offset intelligence (design
docs/specs/2026-07-13-start-offset-intelligence-design.md). Operates on numeric
envelopes only — no audio IO, no librosa, no demucs — so every branch of the
in-point decision is unit-tested deterministically. `downsample` (relocated from
beats.py) is the shared envelope-builder beats.py and vocals.py reuse without a
circular import."""
from collections.abc import Sequence

import numpy as np

HOP = 512                                             # librosa beat/rms default hop_length


def downsample(rms: np.ndarray, sr: int, hop: int, target_hz: float) -> tuple[list[float], float]:
    """Average per-frame RMS into ~target_hz bins → a short coarse energy curve.
    Returns (energy, energy_hz)."""
    frame_hz = sr / hop
    step = max(1, int(round(frame_hz / target_hz)))
    energy = [float(np.mean(rms[i:i + step])) for i in range(0, len(rms), step)]
    return energy, frame_hz / step


def vocal_gaps(env: Sequence[float], hz: float, *,
               thresh_frac: float = 0.15, min_gap: float = 0.35) -> tuple[tuple[float, float], ...]:
    """Spans (start_s, end_s) where the activity envelope stays below
    thresh_frac * max(env) for at least min_gap seconds. Relative bar (design §12
    relative-gate lesson): a quiet mix must not read as all-silent. A below-thresh
    run shorter than min_gap is a between-words dip, dropped. env all-zero → one
    gap over the whole envelope (no vocals to avoid). Times are seconds (i / hz)."""
    n = len(env)
    if n == 0:
        return ()
    thresh = thresh_frac * max(env)
    gaps: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, v in enumerate(env):
        below = v <= thresh
        if below and run_start is None:
            run_start = i
        elif not below and run_start is not None:
            if (i - run_start) / hz >= min_gap:
                gaps.append((run_start / hz, i / hz))
            run_start = None
    if run_start is not None and (n - run_start) / hz >= min_gap:
        gaps.append((run_start / hz, n / hz))
    return tuple(gaps)
