"""Damped velocity-following smoothing of a raw crop-x path (spec §6.1)."""
import numpy as np
from scipy.signal import savgol_filter

DEFAULT_WINDOW = 7        # savgol frames — the pure function's own fallback
DEFAULT_WINDOW_S = 0.25   # ...and the width callers should actually ask for, IN SECONDS


def window_frames(seconds: float, fps: float) -> int:
    """An odd savgol window spanning `seconds` at `fps`.

    The window has to be specified in TIME, not frames, because it is a low-pass
    filter and its cutoff is a frequency. DEFAULT_WINDOW = 7 was tuned on 30fps
    footage, where it spans 0.23s; handed unchanged to a 60fps source it spans
    0.12s and filters half as much motion, which is exactly the regime this repo's
    drone and telephoto footage lives in. Measured across four 60fps rides, 7
    frames left the crop's 2nd difference at 2-4x the integer-crop floor and one
    episode failed the jitter check outright; the same 0.25s expressed as 15
    frames put all four ON the floor, for 1-3% of crop width in added lag.

    DEFAULT_WINDOW_S is chosen so a 30fps clip still resolves to 7 — the historical
    value is preserved exactly where it came from, and only the frame rates it was
    never tuned for change."""
    if fps <= 0:
        raise ValueError(f"window_frames needs a positive fps, got {fps!r} — "
                         "a window in seconds cannot be converted without one")
    if seconds <= 0:
        raise ValueError(f"window_frames needs a positive span, got {seconds!r}s — "
                         "pass window=1 to smooth() to skip savgol entirely")
    n = round(seconds * fps)
    if n % 2 == 0:                 # round(0.25*30fps)==8 (ties-to-even); the -1 lands
        n -= 1                     # the even result on 7 — the historical default, not 9
    return max(5, n)               # savgol needs window > polyorder (2)


def _rate_limit(raw: list[float], max_step: float) -> list[float]:
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


def smooth(raw: list[float], max_step: float, window: int | None = DEFAULT_WINDOW,
           polyorder: int = 2) -> list[float]:
    """Rate-limit then (optionally) Savitzky-Golay smooth the path.

    max_step: max crop-x change per frame (px) — the damping.
    window:   savgol window (odd, >polyorder). window<=1 skips savgol.
    """
    if not raw:
        return []
    limited = _rate_limit(list(raw), max_step)
    if window is None or window <= 1:
        return limited
    win = window if window % 2 == 1 else window + 1
    if len(limited) < win or win <= polyorder:
        return limited
    return list(savgol_filter(np.asarray(limited), win, polyorder))
