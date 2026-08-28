"""sRGB -> CIE Lab and CIEDE2000 (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.1).

Colour-difference arithmetic and nothing else: no sampling, no thresholds, no
ffmpeg. `math` only — the caller already has numpy for pixels, but a difference
between two colours is scalar work and adding an array dependency here would
buy nothing.

Why CIEDE2000 and not the hue angle it replaces: a grade moves exposure and
saturation, and hue is invariant to both by construction, so the metric that was
here reported ~0 for every real grade and threw the sample away entirely when
the subject came near grey (design §0.2). dE00 keeps all three components and
weighs a near-grey hue term down through its own S_H rather than by discarding
the sample."""
import math

# sRGB D65 white point, the reference white the Lab transfer is defined against.
_XN, _YN, _ZN = 0.95047, 1.0, 1.08883
_DELTA = 6.0 / 29.0        # the Lab transfer's linear/cubic knee


def _linearize(c: float) -> float:
    """One sRGB channel (0-255) to linear light (0-1)."""
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1.0 / 3.0) if t > _DELTA ** 3 else t / (3 * _DELTA ** 2) + 4.0 / 29.0


def rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """(R, G, B) in 0-255 to (L*, a*, b*). sRGB primaries, D65."""
    r, g, b = (_linearize(v) for v in rgb)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    fx, fy, fz = _f(x / _XN), _f(y / _YN), _f(z / _ZN)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def ciede2000(lab1: tuple[float, float, float],
              lab2: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """(dE00, dL', dC', dH') between two Lab colours, k_L = k_C = k_H = 1.

    The three components are returned alongside the total because they are the
    report's explanation — which of luma, chroma and hue the grade moved — and
    recomputing them in the caller would duplicate every intermediate below.
    They are SIGNED (lab1 -> lab2); the total is symmetric, the components are not.
    """
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2.0
    # G expands a* near the neutral axis so a small chroma difference there is not
    # swamped; at cbar = 0 the radical is 0 and G is exactly 0.5.
    g = 0.5 * (1.0 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25.0 ** 7))) if cbar > 0 else 0.5
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0 if (a2p or b2) else 0.0

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2.0)

    lbar, cbarp = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hbar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hbar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hbar = (h1p + h2p + 360.0) / 2.0
    else:
        hbar = (h1p + h2p - 360.0) / 2.0

    t = (1.0
         - 0.17 * math.cos(math.radians(hbar - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * hbar))
         + 0.32 * math.cos(math.radians(3.0 * hbar + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * hbar - 63.0)))
    dtheta = 30.0 * math.exp(-(((hbar - 275.0) / 25.0) ** 2))
    rc = 2.0 * math.sqrt(cbarp ** 7 / (cbarp ** 7 + 25.0 ** 7)) if cbarp > 0 else 0.0
    sl = 1.0 + (0.015 * (lbar - 50.0) ** 2) / math.sqrt(20.0 + (lbar - 50.0) ** 2)
    sc = 1.0 + 0.045 * cbarp
    sh = 1.0 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2.0 * dtheta)) * rc

    de = math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2
                   + rt * (dcp / sc) * (dHp / sh))
    return (de, dlp, dcp, dHp)
