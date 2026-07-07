"""Damped velocity-following smoothing of a raw crop-x path (spec §6.1)."""
import numpy as np
from scipy.signal import savgol_filter


def _rate_limit(raw, max_step):
    out = [float(raw[0])]
    for target in raw[1:]:
        prev = out[-1]
        delta = target - prev
        if delta > max_step:
            delta = max_step
        elif delta < -max_step:
            delta = -max_step
        out.append(prev + delta)
    return out


def smooth(raw, max_step, window=7, polyorder=2):
    """Rate-limit then (optionally) Savitzky-Golay smooth the path.

    max_step: max crop-x change per frame (px) — the damping.
    window:   savgol window (odd, >polyorder). window<=1 skips savgol.
    """
    limited = _rate_limit(list(raw), max_step)
    if window is None or window <= 1 or len(limited) < window:
        return limited
    win = window if window % 2 == 1 else window + 1
    if win <= polyorder:
        return limited
    return list(savgol_filter(np.asarray(limited), win, polyorder))
