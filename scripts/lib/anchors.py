# scripts/lib/anchors.py
"""Action anchors (design docs/specs/2026-07-24-scenario-first-pacing-design.md §4).

An episode's in-point is its meaning — the take-off, the step into the water — so the
fitter never slides it. It may JUMP: to the next point in the shot where something
happens, when that lands a better ending. This module finds those points.

The measure is a PROXY, and the design says so: it is global frame-to-frame difference,
so it fires on any large motion change including a camera whip, not only on a manoeuvre.
Anchors are therefore advisory — the pacing report names each one with its timestamp so
a wrong one is visible rather than silently moving a cut."""
ANCHOR_HZ = 3.0        # samples/s — intake's SAMPLE_FPS, so the two agree about "a moment"
ANCHOR_MIN_GAP = 1.0   # s between anchors: closer than this and they describe one event
ANCHOR_REL = 0.6       # fraction of the curve's own peak a local max must reach. Relative,
                       # not absolute: a telephoto shot and an aerial differ by an order of
                       # magnitude in frame-to-frame difference, and an absolute floor would
                       # find every moment in one and none in the other.


def anchors_from_curve(curve, hz: float = ANCHOR_HZ, min_gap: float = ANCHOR_MIN_GAP,
                       rel: float = ANCHOR_REL) -> list[float]:
    """Local maxima of `curve` above `rel` x its peak, thinned to one per `min_gap`.

    Returns seconds from the curve's start, ascending. Thinning keeps the STRONGER of two
    neighbours rather than the earlier one: a manoeuvre ramps up over several samples, and
    keeping the first would anchor the cut before the action rather than on it."""
    c = [float(x) for x in curve]
    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or hz <= 0:
        raise ValueError(f"anchors_from_curve: hz must be a positive sample rate, got {hz!r}")
    if isinstance(rel, bool) or not isinstance(rel, (int, float)) or not 0 < rel <= 1:
        raise ValueError(f"anchors_from_curve: rel must be a fraction in (0, 1], got {rel!r}")
    if isinstance(min_gap, bool) or not isinstance(min_gap, (int, float)) or min_gap <= 0:
        raise ValueError(f"anchors_from_curve: min_gap must be > 0 seconds, got {min_gap!r}")
    if len(c) < 3:
        return []
    peak = max(c)
    floor = peak * rel
    if peak <= 0 or max(c) - min(c) <= 0:
        return []
    peaks = [i for i in range(1, len(c) - 1)
             if c[i] >= floor and c[i] >= c[i - 1] and c[i] > c[i + 1]]
    kept: list[int] = []
    for i in sorted(peaks, key=lambda i: (-c[i], i)):
        if all(abs(i - j) / hz >= min_gap for j in kept):
            kept.append(i)
    return [i / hz for i in sorted(kept)]
