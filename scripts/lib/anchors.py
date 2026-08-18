# scripts/lib/anchors.py
"""Action anchors (design docs/specs/2026-07-24-scenario-first-pacing-design.md §4).

An episode's in-point is its meaning — the take-off, the step into the water — so the
fitter never slides it. It may JUMP: to the next point in the shot where something
happens, when that lands a better ending. This module finds those points.

The measure is a PROXY, and the design says so: it is global frame-to-frame difference,
so it fires on any large motion change including a camera whip, not only on a manoeuvre.
Anchors are therefore advisory — the pacing report names each one with its timestamp so
a wrong one is visible rather than silently moving a cut."""
from collections.abc import Sequence

from scripts.lib import ffbin, proc

ANCHOR_HZ = 3.0        # samples/s — intake's SAMPLE_FPS, so the two agree about "a moment"
ANCHOR_MIN_GAP = 1.0   # s between anchors: closer than this and they describe one event
ANCHOR_REL = 0.6       # fraction of the curve's own peak a local max must reach. Relative,
                       # not absolute: a telephoto shot and an aerial differ by an order of
                       # magnitude in frame-to-frame difference, and an absolute floor would
                       # find every moment in one and none in the other.
ANCHOR_FLAT_FRAC = 0.5 # fraction of the curve that may sit at or above `rel * peak`
                       # before the relative floor stops SELECTING and starts admitting
                       # everything. Past it there is no distinguished moment and
                       # anchors_from_curve returns nothing rather than the min_gap
                       # thinning grid dressed as events.
                       #
                       # Measured 2026-08-18 over the real run's eight episodes: SEVEN
                       # have 100% of their samples above 0.6*peak (peak/min ratios
                       # 1.23-1.64 — the whole curve is a plateau), and the one shot
                       # with real texture sits at 33% (ratio 2.78). The gap is so wide
                       # that anything in [0.34, 0.99] separates them; 0.5 is the
                       # midpoint. One shoot, and §7 of the design says so.
                       #
                       # What this is NOT: a claim that the flat shots contain no
                       # action. It is a claim that global frame-difference on a moving
                       # camera cannot find it — the camera's own motion is the signal,
                       # and it is roughly constant. The docstring above always called
                       # this a proxy; this constant is the proxy admitting when it has
                       # nothing to say.
ANCHOR_W, ANCHOR_H = 160, 90   # the analysis frame. Fixed, not aspect-preserving: this is
                               # a motion PROXY and a squeezed frame differences the same;
                               # a fixed size keeps the raw-frame arithmetic below exact.
_FRAME_BYTES = ANCHOR_W * ANCHOR_H


def curve_contrast(curve: Sequence[float], rel: float = ANCHOR_REL) -> float:
    """Fraction of `curve`'s samples at or above `rel * peak` — 0.0 for an empty curve.

    The number that says whether the relative floor is doing any work. Near 1.0 the
    floor admits the whole curve, so whatever `anchors_from_curve` returns is the
    min_gap thinning grid rather than a set of events; near 0 a few samples stand out.
    Reported beside the anchors so a reader can see which case they are looking at
    (design 2026-08-18 §4)."""
    c = [float(x) for x in curve]
    if not c:
        return 0.0
    peak = max(c)
    if peak <= 0:
        return 0.0
    return sum(1 for v in c if v >= peak * float(rel)) / len(c)


def anchors_from_curve(curve: Sequence[float], hz: float = ANCHOR_HZ,
                       min_gap: float = ANCHOR_MIN_GAP,
                       rel: float = ANCHOR_REL,
                       flat_frac: float = ANCHOR_FLAT_FRAC) -> list[float]:
    """Local maxima of `curve` above `rel` x its peak, thinned to one per `min_gap`.

    Returns seconds from the curve's start, ascending. Thinning keeps the STRONGER of two
    neighbours rather than the earlier one: a manoeuvre ramps up over several samples, and
    keeping the first would anchor the cut before the action rather than on it.

    A curve whose `curve_contrast` exceeds `flat_frac` yields **nothing**. Measured
    2026-08-18 (design §4): on seven of the real run's eight episodes the relative floor
    admits 100% of the samples, and what came back was one "anchor" per `min_gap` across
    the whole window — a grid, not a set of moments. Returning it invites a reader to
    treat noise as an event, which is exactly what the one consumer (`PACING.md`'s
    advisory table) was doing. Pass `flat_frac=1.0` to see the raw maxima anyway."""
    c = [float(x) for x in curve]
    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or hz <= 0:
        raise ValueError(f"anchors_from_curve: hz must be a positive sample rate, got {hz!r}")
    if isinstance(rel, bool) or not isinstance(rel, (int, float)) or not 0 < rel <= 1:
        raise ValueError(f"anchors_from_curve: rel must be a fraction in (0, 1], got {rel!r}")
    if isinstance(min_gap, bool) or not isinstance(min_gap, (int, float)) or min_gap <= 0:
        raise ValueError(f"anchors_from_curve: min_gap must be > 0 seconds, got {min_gap!r}")
    if isinstance(flat_frac, bool) or not isinstance(flat_frac, (int, float)) \
            or not 0 < flat_frac <= 1:
        raise ValueError(f"anchors_from_curve: flat_frac must be a fraction in (0, 1], "
                         f"got {flat_frac!r}")
    if len(c) < 3:
        return []
    peak = max(c)
    floor = peak * rel
    if peak <= 0 or max(c) - min(c) <= 0:
        return []
    if curve_contrast(c, rel) > flat_frac:      # the floor is selecting nothing
        return []
    peaks = [i for i in range(1, len(c) - 1)
             if c[i] >= floor and c[i] >= c[i - 1] and c[i] > c[i + 1]]
    kept: list[int] = []
    for i in sorted(peaks, key=lambda i: (-c[i], i)):
        if all(abs(i - j) / hz >= min_gap for j in kept):
            kept.append(i)
    return [i / hz for i in sorted(kept)]


def measure_curve(src: str, start: float, dur: float, hz: float = ANCHOR_HZ) -> list[float]:
    """Mean frame-to-frame difference of `src[start : start+dur]`, sampled at `hz`.

    `-ss` goes AFTER `-i` — design §12's first landmine: before the input it is a fast
    keyframe seek and the frames returned are not the frames asked for, which would move
    every anchor by up to a GOP.

    `tblend=all_mode=difference` emits |frame[i] - frame[i-1]| from the second frame on,
    so curve[i] describes the interval between samples i and i+1; the caller's anchor time
    lands at the START of that interval, which is where the action begins."""
    if isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0:
        raise ValueError(f"anchors.measure_curve: start must be >= 0 seconds, got {start!r}")
    if isinstance(dur, bool) or not isinstance(dur, (int, float)) or dur <= 0:
        raise ValueError(f"anchors.measure_curve: dur must be > 0 seconds, got {dur!r}")
    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or hz <= 0:
        raise ValueError(f"anchors.measure_curve: hz must be a positive sample rate, got {hz!r}")
    r = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src, "-ss", f"{start}",
                  "-t", f"{dur}", "-vf",
                  f"fps={hz},scale={ANCHOR_W}:{ANCHOR_H},format=gray,"
                  f"tblend=all_mode=difference",
                  "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    raw = r.stdout or b""
    n = len(raw) // _FRAME_BYTES
    return [sum(raw[i * _FRAME_BYTES:(i + 1) * _FRAME_BYTES]) / _FRAME_BYTES
            for i in range(n)]
