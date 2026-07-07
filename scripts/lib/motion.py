"""Classify a subject route into motion type (spec §6.2)."""

LATERAL_FRAC = 0.15   # net |dx| > 15% of width → lateral
GROWTH_RATIO = 1.6    # bbox area grows ≥1.6x → head-on


def classify(route, src_w, src_h, lateral_frac=LATERAL_FRAC,
             growth_ratio=GROWTH_RATIO):
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
    return ("static", None)
