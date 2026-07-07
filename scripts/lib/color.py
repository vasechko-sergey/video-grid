"""Soft normalize-to-middle color (spec §10). lutrgb is banned; use mixer."""

TARGET = (105, 122, 137)   # R, G, B middle tone
STRENGTH = 0.55
LO, HI = 0.7, 1.5


def gain(measured, target, strength=STRENGTH, lo=LO, hi=HI):
    g = 1 + strength * (target / measured - 1)
    return max(lo, min(hi, g))


def gains_for_means(measured, target=TARGET):
    return tuple(gain(m, t) for m, t in zip(measured, target))


def mixer_arg(rr, gg, bb):
    return f"colorchannelmixer=rr={rr:.3f}:gg={gg:.3f}:bb={bb:.3f}"
