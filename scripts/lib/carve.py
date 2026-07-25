"""Activity-anchored window carving (design 2026-07-25-intake-activity-units §4).

Pure: floats in, (start, dur) spans out. No ffmpeg and no `scripts.intake` import —
a lib module must not depend on a driver, so the band (WIN_MIN/WIN_MAX) is passed
in, never imported. Mirrors lib/gridfit.py. Peaks are LOCAL maxima found relative
to the clip, so no absolute activity threshold is invented (§2) — there is no real
footage to tune one on.
"""
from math import hypot

# A light denoise of the ~3fps activity curve before peak-finding — NOT a tuned
# threshold (§9): it is a fixed 3-sample centred average, the smallest kernel that
# removes single-sample detection jitter.
SMOOTH_KERNEL = 3


def subject_curve(centers: list[tuple[float, float] | None]) -> list[float]:
    """Per-sample 2-D displacement of the primary bbox centre, aligned to samples.
    `centers[i]` is (cx, cy) or None (no person that sample). Index 0 has no prior,
    and any sample bordering a gap, are 0.0."""
    if not centers:
        return []
    out = [0.0]
    for i in range(1, len(centers)):
        c0, c1 = centers[i - 1], centers[i]
        out.append(hypot(c1[0] - c0[0], c1[1] - c0[1]) if c0 is not None and c1 is not None else 0.0)
    return out


def camera_curve(mags: list[float], fps: float, times: list[float]) -> list[float]:
    """Resample per-frame vidstab magnitudes to the sample `times` (a people-less
    span's only within-shot signal, §3). Empty mags → a flat zero curve."""
    if not mags:
        return [0.0 for _ in times]
    n = len(mags)
    return [mags[min(int(t * fps), n - 1)] for t in times]


def smooth(curve: list[float], kernel: int = SMOOTH_KERNEL) -> list[float]:
    """Centred moving average, edge-clamped. A curve of <= 2 samples is returned
    unchanged (nothing to denoise)."""
    if kernel <= 1 or len(curve) <= 2:
        return list(curve)
    half = kernel // 2
    return [sum(curve[max(0, i - half):min(len(curve), i + half + 1)])
            / len(curve[max(0, i - half):min(len(curve), i + half + 1)])
            for i in range(len(curve))]


def _local_maxima(curve: list[float]) -> list[int]:
    return [i for i in range(1, len(curve) - 1)
            if curve[i] > curve[i - 1] and curve[i] > curve[i + 1]]


def _local_minima(curve: list[float]) -> list[int]:
    return [i for i in range(1, len(curve) - 1)
            if curve[i] < curve[i - 1] and curve[i] < curve[i + 1]]


def find_peaks(curve: list[float], times: list[float], win_min: float) -> list[int]:
    """Indices of activity peaks: local maxima of the curve, kept strongest first
    with a time spacing of at least `win_min` (the band's floor doubles as the
    peak spacing — there is no separate density knob, §4). Returned in time order."""
    maxima = sorted(_local_maxima(curve), key=lambda i: curve[i], reverse=True)
    kept: list[int] = []
    for i in maxima:
        if all(abs(times[i] - times[j]) >= win_min for j in kept):
            kept.append(i)
    return sorted(kept)
