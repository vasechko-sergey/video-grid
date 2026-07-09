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
