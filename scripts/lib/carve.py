"""Activity-anchored window carving (design 2026-07-25-intake-activity-units §4).

Pure: floats in, (start, dur) spans out. No ffmpeg and no `scripts.intake` import —
a lib module must not depend on a driver, so the band (WIN_MIN/WIN_MAX) is passed
in, never imported. Mirrors lib/gridfit.py. Peaks are LOCAL maxima found relative
to the clip, so no absolute activity threshold is invented (§2) — there is no real
footage to tune one on.
"""
from math import hypot


def subject_curve(centers: list[tuple[float, float] | None]) -> list[float]:
    """Per-sample 2-D displacement of the primary bbox centre, aligned to samples.
    `centers[i]` is (cx, cy) or None (no person that sample). Index 0 has no prior,
    and any sample bordering a gap, are 0.0. Returns RAW pixel displacement — peak
    detection is scale-invariant, so no width normalisation is applied here (and the
    subject/camera curves are never compared on one axis, §3)."""
    if not centers:
        return []
    out = [0.0]
    for i in range(1, len(centers)):
        c0, c1 = centers[i - 1], centers[i]
        out.append(hypot(c1[0] - c0[0], c1[1] - c0[1]) if c0 is not None and c1 is not None else 0.0)
    return out


def camera_curve(mags: list[float], fps: float, times: list[float]) -> list[float]:
    """Resample per-frame vidstab magnitudes to the sample `times` (a people-less
    span's only within-shot signal, §3). Empty mags → a flat zero curve. A
    non-positive fps is refused, not defended around: it maps a time to a frame
    index, so fps <= 0 would collapse every sample onto frame 0 — a silent flat
    curve that then yields wrong peaks (a §12-class silent corruption)."""
    if fps <= 0:
        raise ValueError(f"carve.camera_curve: fps must be positive, got {fps!r} — "
                         "a non-positive fps collapses every sample onto frame 0")
    if not mags:
        return [0.0 for _ in times]
    n = len(mags)
    return [mags[min(int(t * fps), n - 1)] for t in times]


def _local_maxima(curve: list[float]) -> list[int]:
    return [i for i in range(1, len(curve) - 1)
            if curve[i] > curve[i - 1] and curve[i] > curve[i + 1]]


def _local_minima(curve: list[float]) -> list[int]:
    return [i for i in range(1, len(curve) - 1)
            if curve[i] < curve[i - 1] and curve[i] < curve[i + 1]]


def find_peaks(curve: list[float], times: list[float], win_min: float) -> list[int]:
    """Indices of activity peaks: local maxima of the curve, kept strongest first
    with a time spacing of at least `win_min` (the band's floor doubles as the peak
    spacing — the ONLY peak regulator, §4). Returned in time order. The curve is not
    smoothed: on a ~3fps curve a fixed denoise kernel is unvalidatable and redundant
    with this spacing (design §4.1)."""
    maxima = sorted(_local_maxima(curve), key=lambda i: curve[i], reverse=True)
    kept: list[int] = []
    for i in maxima:
        if all(abs(times[i] - times[j]) >= win_min for j in kept):
            kept.append(i)
    return sorted(kept)


def _clamp_to_band(s: float, e: float, a: float, b: float, p: float,
                   win_min: float, win_max: float) -> tuple[float, float]:
    """Force [s, e] into [win_min, win_max] and inside [a, b], keeping the peak `p`
    in it. Holds the start (the lead-in) and trims/extends the tail first."""
    s = max(a, min(s, p))                 # start no later than the peak, no earlier than a
    e = min(b, max(e, p))                 # end no earlier than the peak, no later than b
    if e - s > win_max:                   # too long: keep the lead-in, trim the tail
        e = s + win_max
        if e < p:                         # the lead-in alone exceeds the band → anchor on the peak
            e = min(b, p)
            s = e - win_max
    if e - s < win_min:                   # too short: extend, preferring to keep the peak inside
        s = max(a, min(s, e - win_min))
        e = min(b, s + win_min)
        if e - s < win_min:               # both span edges crowd it
            s = max(a, e - win_min)
    return (round(s, 3), round(e - s, 3))


def _tight_unit(pk: int, a: float, b: float, times: list[float], win_min: float) -> tuple[float, float]:
    p = times[pk]
    return _clamp_to_band(p - win_min / 2, p + win_min / 2, a, b, p, win_min, win_min)


def _lead_in_unit(pk: int, minima: list[int], a: float, b: float, times: list[float],
                  win_min: float, win_max: float) -> tuple[float, float]:
    p = times[pk]
    befores = [times[m] for m in minima if times[m] < p]
    afters = [times[m] for m in minima if times[m] > p]
    lull = befores[-1] if befores else a           # the approach starts at the last lull before the peak
    settle = afters[0] if afters else b            # ends at the first lull after it (§4)
    return _clamp_to_band(lull, settle, a, b, p, win_min, win_max)


def _flat_unit(a: float, b: float, times: list[float], curve: list[float],
               win_max: float) -> tuple[float, float]:
    """A flat span (no interior peak) yields ONE window of WIN_MAX at the position of
    maximum mean activity — never a tiling (§4.3)."""
    best_s, best_mean = a, -1.0
    for t in times:
        if t + win_max > b + 1e-9:
            break
        vals = [curve[j] for j, tt in enumerate(times) if t <= tt < t + win_max]
        m = sum(vals) / len(vals) if vals else 0.0
        if m > best_mean:
            best_mean, best_s = m, t
    return (round(best_s, 3), round(win_max, 3))


def units_for_span(a: float, b: float, times: list[float], curve: list[float],
                   win_min: float, win_max: float) -> list[tuple[float, float]]:
    """Carve one span [a, b] into activity units (§4). A short span (< win_min) is
    dropped; a span within the band is one whole unit; a longer span is carved on
    its activity peaks (two candidates each) or, if flat, one max-mean window.

    This is the module's public entry (intake.carve_windows calls it), so it
    validates here and the helpers below trust it — the same fail-loud boundary
    gridfit.py draws."""
    if len(times) != len(curve):
        raise ValueError(f"carve.units_for_span: times and curve must align, got "
                         f"{len(times)} times vs {len(curve)} curve samples")
    if not (0 < win_min <= win_max):
        raise ValueError(f"carve.units_for_span: need 0 < win_min <= win_max, got "
                         f"win_min={win_min!r}, win_max={win_max!r}")
    L = b - a
    if L < win_min:
        return []
    if L <= win_max:
        return [(round(a, 3), round(L, 3))]
    peaks = find_peaks(curve, times, win_min)
    if not peaks:
        return [_flat_unit(a, b, times, curve, win_max)]
    minima = _local_minima(curve)
    seen: set = set()
    out: list[tuple[float, float]] = []
    for pk in peaks:
        for unit in (_lead_in_unit(pk, minima, a, b, times, win_min, win_max),
                     _tight_unit(pk, a, b, times, win_min)):
            if unit not in seen:                   # exact-dup drop (§4.5): a sharp peak makes them equal
                seen.add(unit)
                out.append(unit)
    out.sort(key=lambda u: (u[0], u[1]))
    return out
