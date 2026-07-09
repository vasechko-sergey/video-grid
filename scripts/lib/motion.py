"""Classify a subject route into motion type (spec §6.2)."""

LATERAL_FRAC = 0.15   # net |dx| > 15% of width → lateral
GROWTH_RATIO = 1.6    # bbox area grows ≥1.6x → head-on


def classify(route: list[dict[str, float]], src_w: int, src_h: int,
             lateral_frac: float = LATERAL_FRAC,
             growth_ratio: float = GROWTH_RATIO) -> tuple[str, str | None]:
    if len(route) < 2:
        return ("static", None)
    first, last = route[0], route[-1]
    dx = last["x"] - first["x"]
    area0 = max(1, first["w"] * first["h"])
    area1 = last["w"] * last["h"]
    growth = area1 / area0

    if abs(dx) >= lateral_frac * src_w and growth < growth_ratio:
        return ("lateral", "right" if dx > 0 else "left")
    if growth >= growth_ratio and abs(dx) < lateral_frac * src_w:
        return ("head-on", None)
    # ambiguous zone (large dx AND large growth, e.g. diagonal approach):
    # fall through to static on purpose — centered crop is the safe framing
    return ("static", None)
