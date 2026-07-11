"""Soft normalize-to-middle color (spec §10). lutrgb is banned; use mixer."""

TARGET = (105, 122, 137)   # R, G, B middle tone
STRENGTH = 0.55
LO, HI = 0.7, 1.5


def gain(measured: float, target: float, strength: float = STRENGTH,
         lo: float = LO, hi: float = HI) -> float:
    if measured <= 0:
        raise ValueError(
            f"channel mean {measured} is not positive — all-black frames? "
            "check the extracted segment (blackdetect) before color normalization")
    g = 1 + strength * (target / measured - 1)
    return max(lo, min(hi, g))


def gains_for_means(measured: tuple[float, ...],
                    target: tuple[float, ...] = TARGET) -> tuple[float, ...]:
    return tuple(gain(m, t) for m, t in zip(measured, target))


def mixer_arg(rr: float, gg: float, bb: float) -> str:
    return f"colorchannelmixer=rr={rr:.3f}:gg={gg:.3f}:bb={bb:.3f}"


def corrected(gains: tuple[float, ...], correction: tuple[float, ...],
              lo: float = LO, hi: float = HI) -> tuple[float, ...]:
    """Compose an external per-channel correction onto base grade gains and
    re-clamp to [lo, hi] (design 2026-07-11 §4). The reel retry loop passes an absolute
    factor here to pull one episode's delivered mean toward the reel median;
    the clamp keeps the total correction inside the same soft band as the grade."""
    return tuple(max(lo, min(hi, g * corr)) for g, corr in zip(gains, correction))
