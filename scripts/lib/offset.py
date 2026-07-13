"""Pure decision core for start-offset intelligence (design
docs/specs/2026-07-13-start-offset-intelligence-design.md). Operates on numeric
envelopes only — no audio IO, no librosa, no demucs — so every branch of the
in-point decision is unit-tested deterministically. `downsample` (relocated from
beats.py) is the shared envelope-builder beats.py and vocals.py reuse without a
circular import."""
import numpy as np

HOP = 512                                             # librosa beat/rms default hop_length


def downsample(rms: np.ndarray, sr: int, hop: int, target_hz: float) -> tuple[list[float], float]:
    """Average per-frame RMS into ~target_hz bins → a short coarse energy curve.
    Returns (energy, energy_hz)."""
    frame_hz = sr / hop
    step = max(1, int(round(frame_hz / target_hz)))
    energy = [float(np.mean(rms[i:i + step])) for i in range(0, len(rms), step)]
    return energy, frame_hz / step
