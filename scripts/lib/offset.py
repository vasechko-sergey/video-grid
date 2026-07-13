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


def best_offset(mix_energy: Sequence[float], mix_hz: float,
                gaps: Sequence[tuple[float, float]],
                duration: float, track_dur: float) -> float:
    """start_offset (track seconds) of the max-mean-energy duration-window whose
    start lies in a vocal gap (design §2). track_dur <= duration → 0.0. Candidate
    starts = gap starts with start <= track_dur - duration (the window must fit the
    track); a gap starting later is dropped. No usable gap → argmax over a coarse
    per-sample slide (honest degrade — may begin mid-phrase; the driver logs it).
    Ties resolve to the earliest start (max() keeps the first maximum)."""
    if track_dur <= duration:
        return 0.0
    latest = track_dur - duration

    def win_mean(start: float) -> float:
        a = int(round(start * mix_hz))
        b = int(round((start + duration) * mix_hz))
        seg = mix_energy[a:b]
        return float(np.mean(seg)) if len(seg) else 0.0

    candidates = [g0 for (g0, _g1) in gaps if g0 <= latest + 1e-9]
    if candidates:
        return float(max(candidates, key=win_mean))
    starts = [i / mix_hz for i in range(int(round(latest * mix_hz)) + 1)]
    return float(max(starts, key=win_mean)) if starts else 0.0
