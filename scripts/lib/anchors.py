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
ANCHOR_W, ANCHOR_H = 160, 90   # the analysis frame. Fixed, not aspect-preserving: this is
                               # a motion PROXY and a squeezed frame differences the same;
                               # a fixed size keeps the raw-frame arithmetic below exact.
_FRAME_BYTES = ANCHOR_W * ANCHOR_H


def anchors_from_curve(curve: Sequence[float], hz: float = ANCHOR_HZ,
                       min_gap: float = ANCHOR_MIN_GAP,
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


def measure_curve(src: str, start: float, dur: float, hz: float = ANCHOR_HZ) -> list[float]:
    """Mean frame-to-frame difference of `src[start : start+dur]`, sampled at `hz`.

    `-ss` goes AFTER `-i` — design §12's first landmine: before the input it is a fast
    keyframe seek and the frames returned are not the frames asked for, which would move
    every anchor by up to a GOP.

    `tblend=all_mode=difference` emits |frame[i] - frame[i-1]| from the second frame on,
    so curve[i] describes the interval between samples i and i+1; the caller's anchor time
    lands at the START of that interval, which is where the action begins."""
    if dur <= 0:
        raise ValueError(f"anchors.measure_curve: dur must be > 0 seconds, got {dur!r}")
    r = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src, "-ss", f"{start}",
                  "-t", f"{dur}", "-vf",
                  f"fps={hz},scale={ANCHOR_W}:{ANCHOR_H},format=gray,"
                  f"tblend=all_mode=difference",
                  "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    raw = r.stdout or b""
    n = len(raw) // _FRAME_BYTES
    return [sum(raw[i * _FRAME_BYTES:(i + 1) * _FRAME_BYTES]) / _FRAME_BYTES
            for i in range(n)]
