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
    gap over the whole envelope (no vocals to avoid). An all-zero envelope shorter
    than min_gap yields () — pathological; real envelopes span seconds. Times are
    seconds (i / hz)."""
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


def best_offsets(mix_energy: Sequence[float], mix_hz: float,
                 gaps: Sequence[tuple[float, float]],
                 duration: float, track_dur: float, k: int = 1) -> list[float]:
    """The top-`k` start_offsets (track seconds), best (highest mean energy) first.

    One pick is not enough once pacing fits a grid to cuts that already exist: shifting
    the music window moves every grid line with it, so the window is one of the two
    search axes (design 2026-07-24 §3) and the fitter needs alternatives to compare.
    Ranking is unchanged from the original best_offset (design §2): candidate starts =
    gap starts with start <= track_dur - duration (the window must fit the track); a
    gap starting later is dropped. No usable gap → argmax over a coarse per-sample
    slide (honest degrade — may begin mid-phrase; the driver logs it). Ties resolve to
    the earliest start."""
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
        # floor: i / mix_hz <= latest for every i (round() could overshoot)
        n = int(latest * mix_hz)
        candidates = [i / mix_hz for i in range(n + 1)]
        if candidates[-1] < latest:
            candidates.append(latest)                 # also weigh the exact-fit endpoint window
    ranked = sorted(candidates, key=lambda s: (-win_mean(s), s))
    # clamp: a 1e-9-slack gap start must not exceed latest
    return [float(min(s, latest)) for s in ranked[:k]]


def best_offset(mix_energy: Sequence[float], mix_hz: float,
                gaps: Sequence[tuple[float, float]],
                duration: float, track_dur: float) -> float:
    """The single best start_offset — `best_offsets(..., k=1)[0]`. Kept because
    beats.choose_offset and its goldens name it."""
    return best_offsets(mix_energy, mix_hz, gaps, duration, track_dur, k=1)[0]
