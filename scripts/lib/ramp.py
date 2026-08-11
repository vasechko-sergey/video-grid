"""Speed-ramp arithmetic and the one-pass retime (design 2026-08-09).

A ramp eases playback down to a slow plateau around one moment and back up,
instead of slowing a whole shot. The speed profile s(t) over WINDOW-relative
source time is 1.0 outside the region, a cosine ease into `factor`, `factor`
across the plateau, and a cosine ease back out.

Output time is O(t) = the integral of 1/s from 0 to t — monotonic because s > 0,
and >= t because s <= 1. `out_dur = O(dur)`, so the time the ramp ADDS is
`O(dur) - dur`, which this module reports as `ramp_extra`.

Because s <= 1, the retime only ever DUPLICATES source frames and never drops
one: no motion is lost, and the price is that unique detail is not gained either
(see MIN_RAMP_FPS below).

The SAME knots serve the record and the render (design §3.3): `ramp_extra` reads
the last value of `knots()`, `setpts_expr` emits all of them. Integrating finely
here while the filter approximated coarsely would put a silent ~16ms lie in every
EDL.
"""
from __future__ import annotations

import math

from scripts.lib import ffbin, proc
from scripts.lib.models import RampSpec

RAMP_EASE_KNOTS = 16  # subdivisions per EASE. Not per window: the knots are anchored to
                    # the ramp region (design §3.2), so `ramp_extra` comes out bit-identical
                    # at every window length rather than drifting 3.3ms with it, and the
                    # flats and plateau — where 1/s is constant and the trapezoid exact —
                    # spend no knots at all. 16 reaches machine precision because the
                    # cosine ease's derivative vanishes at both ends, killing every
                    # Euler-Maclaurin correction term; measured, the value stops moving
                    # between 8 and 16 (delta 1.4e-10) and is float noise beyond.
MIN_RAMP_FPS = 24.0  # unique frames per second the plateau must keep. Slowing
                     # DUPLICATES frames, so the plateau shows `fps * factor` distinct
                     # frames per second; below the film rate that reads as stutter.
                     # A convention, not a measurement against this engine's footage
                     # (design §12) — the constant here most likely to want revisiting.

_CRF = 8            # near-lossless intermediate. NOT a default worth relaxing: a held
                    # slow-mo frame is later ENLARGED by a tight hero crop in reframe,
                    # which magnifies intermediate compression into visible whitewater
                    # macroblocks. crf 18 was measured too lossy for that
                    # second-generation crop.
_WINDOW_TOL = 1e-9  # s of float slack when comparing the region against the window
_FPS_TOL = 1e-6     # so 60.0 * 0.4 == 24.0 passes rather than losing to a float hair


def speed_at(t: float, spec: RampSpec) -> float:
    """Playback speed at WINDOW-relative source time `t`. 1.0 is normal."""
    half = spec.hold / 2.0
    lo, hi = spec.at - half, spec.at + half
    if lo <= t <= hi:
        p = 1.0
    elif lo - spec.ease <= t < lo:
        p = (t - (lo - spec.ease)) / spec.ease
    elif hi < t <= hi + spec.ease:
        p = 1.0 - (t - hi) / spec.ease
    else:
        p = 0.0
    # p is progress into the slowdown: 0 = normal, 1 = plateau. The cosine makes
    # the speed's own derivative zero at both ends, so the ramp has no visible
    # corner where it starts or stops.
    return 1.0 + (spec.factor - 1.0) * (1.0 - math.cos(math.pi * p)) / 2.0


def knots(spec: RampSpec, dur: float) -> tuple[list[float], list[float]]:
    """`(ts, O)` — the sample times and the trapezoid integral of 1/s at each.

    Knots are ANCHORED TO THE RAMP REGION, not spread evenly across the window
    (design §3.2), and both consequences matter:

    Every knot's position is fixed by the spec alone, so `ramp_extra` comes out
    bit-identical at any `dur` — which is what §2 promises and what
    _bind_pacing's subtraction spends. Evenly spaced knots slide relative to the
    eases as `dur` changes and drift by milliseconds.

    And the two flats plus the plateau hold 1/s CONSTANT, where the trapezoid rule
    is exact, so a single interval covers each and every subdivision is spent on
    the only curved parts. Zero-width segments are dropped.

    ONE source for both the recorded length and the rendered filter — see the
    module docstring."""
    lo, hi = spec.at - spec.hold / 2.0, spec.at + spec.hold / 2.0
    a, b = lo - spec.ease, hi + spec.ease          # the region's own edges
    ts = [0.0]
    if a > _WINDOW_TOL:                            # the flat before the ramp
        ts.append(a)
    ts += [a + spec.ease * k / RAMP_EASE_KNOTS     # ease-in, last point is `lo`
           for k in range(1, RAMP_EASE_KNOTS + 1)]
    if hi - lo > _WINDOW_TOL:                      # the plateau (absent when hold == 0)
        ts.append(hi)
    ts += [hi + spec.ease * k / RAMP_EASE_KNOTS    # ease-out, last point is `b`
           for k in range(1, RAMP_EASE_KNOTS + 1)]
    if dur - b > _WINDOW_TOL:                      # the flat after the ramp
        ts.append(dur)
    ts = sorted(set(ts))
    inv = [1.0 / speed_at(t, spec) for t in ts]
    out = [0.0]
    for i in range(1, len(ts)):
        out.append(out[-1] + (inv[i - 1] + inv[i]) * 0.5 * (ts[i] - ts[i - 1]))
    return ts, out


def ramp_extra(spec: RampSpec | None, dur: float) -> float:
    """Seconds the ramp ADDS to a `dur`-long window: `O(dur) - dur`. 0.0 with no ramp.

    Pure and fps-independent, so EDLEpisode.play_dur can call it without probing.

    With the region enclosed in the window (validate_window, design §2) this is
    CONSTANT in `dur` — outside the region the speed is exactly 1, so lengthening
    the window lengthens O by the same amount. That constancy is what lets
    edit_plan._bind_pacing invert the relation with one subtraction."""
    if spec is None:
        return 0.0
    return knots(spec, dur)[1][-1] - dur


def tail_room(spec: RampSpec | None, dur: float) -> float:
    """Seconds the window may shrink from its END before eating into the ramp
    region. The whole window without a ramp. Used by pacing._bounds so the beat
    fit cannot cut a shot while it is still slowed."""
    if spec is None:
        return dur
    return dur - (spec.at + spec.hold / 2.0 + spec.ease)


def max_factor(fps: float) -> float:
    """The slowest `factor` a `fps`-rate source supports under MIN_RAMP_FPS."""
    return MIN_RAMP_FPS / fps


def validate_window(spec: RampSpec, dur: float, where: str) -> None:
    """Refuse a ramp whose region pokes outside its window (design §2).

    Three things ride on the enclosure: `ramp_extra` becomes independent of `dur`
    (so the pacing inversion is a subtraction, not a solver); `tail_room` becomes
    well-defined; and editorially, a cut landing while the shot is still slowed —
    a ramp that never returns to speed — is a visible artefact, not a style."""
    head = spec.at - spec.hold / 2.0 - spec.ease
    tail = dur - (spec.at + spec.hold / 2.0 + spec.ease)
    if head < -_WINDOW_TOL:
        raise ValueError(
            f"{where}: the ramp region starts {-head:.2f}s before the window does "
            f"(at={spec.at:g}, hold={spec.hold:g}, ease={spec.ease:g} put its start at "
            f"{head:.2f}s). A ramp must begin and end inside its own window. Move `at` "
            f"later, or shorten `ease`/`hold`")
    if tail < -_WINDOW_TOL:
        raise ValueError(
            f"{where}: the ramp region ends {-tail:.2f}s past the {dur:.2f}s window "
            f"(at={spec.at:g}, hold={spec.hold:g}, ease={spec.ease:g} put its end at "
            f"{spec.at + spec.hold / 2.0 + spec.ease:.2f}s). The cut would land while the "
            f"shot is still slowed. Move `at` earlier, shorten `ease`/`hold`, or lengthen "
            f"the window")


def require_playable(spec: RampSpec, fps: float, where: str) -> None:
    """Refuse a ramp that would render as stutter (design §5). No waiver."""
    unique = fps * spec.factor
    if unique < MIN_RAMP_FPS - _FPS_TOL:
        raise ValueError(
            f"{where}: ramp factor {spec.factor:g} on a {fps:g} fps source leaves "
            f"{unique:.1f} unique frames per second on the plateau, under the "
            f"{MIN_RAMP_FPS:g} fps floor. Slowing DUPLICATES frames — it cannot create "
            f"detail that was never shot — so this renders as visible stutter. The "
            f"slowest this clip supports is factor {max_factor(fps):.3g}; a deeper ramp "
            f"needs footage shot at a higher frame rate")


def setpts_expr(spec: RampSpec, dur: float) -> str:
    """O(t) as a piecewise-linear ffmpeg expression of `T`, through `knots`.

    The same nested `if(lt(...))` shape reframe._xexpr uses for the zoom's crop
    path. O has no elementary closed form (the cosine ease makes it
    the integral of dt/(a + b*cos t)), so knots are how it reaches the filter.

    Contains commas and NO quotes: the caller must wrap it in single quotes inside
    the -vf string, or ffmpeg's parser reads the first comma as a filter separator
    (design §10)."""
    ts, o = knots(spec, dur)
    expr = f"{o[-1]:.6f}"
    for i in range(len(ts) - 2, -1, -1):
        slope = (o[i + 1] - o[i]) / (ts[i + 1] - ts[i])
        expr = (f"if(lt(T,{ts[i + 1]:.6f}),"
                f"{o[i]:.6f}+{slope:.6f}*(T-{ts[i]:.6f}),{expr})")
    return expr


def retime(src: str, dst: str, spec: RampSpec, dur: float, fps: float,
           crf: int = _CRF) -> str:
    """Retime `src` into `dst` by `spec`, in ONE ffmpeg pass.

    `setpts` moves each frame's timestamp through O(T); `fps=` re-quantizes to the
    source's own constant rate, duplicating frames wherever the stream was
    stretched. Both are ordinary filters, so the whole retime is one argv that
    proc.run's landmine guard can read — which is the reason this is not the
    decode/encode frame pipe the parked WIP used (design §0, §3.4).

    Video only. A slowed audio track is pitch garbage, so the segment goes silent;
    mix._build_ambient already substitutes anullsrc sized to the episode's length,
    so the ambient bed stays in sync by construction (design §12).

    The judder gate runs BEFORE the encode: a refusal should cost nothing."""
    require_playable(spec, fps, f"retime {src}")
    expr = setpts_expr(spec, dur)
    # The expression contains commas. In argv form there is no shell to strip
    # quotes, and ffmpeg reads a bare comma as a filter separator — unquoted, the
    # first if(lt(T,...)) splits the chain and ffmpeg reports "No such filter"
    # (design §10). ffmpeg's own parser strips these single quotes.
    vf = f"setpts='({expr})/TB',fps={fps:.6g}"
    proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-i", src, "-vf", vf,
              "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
              "-pix_fmt", "yuv420p", "-an", dst])
    return dst
