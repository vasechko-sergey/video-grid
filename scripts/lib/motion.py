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


def travel_direction(route: list[dict[str, float]]) -> str:
    """Which way the subject NET travels, whatever `classify` called the shot.

    `classify` answers "what kind of shot is this", and returns no direction for
    head-on/static — including the ambiguous zone above, which a subject can enter
    only when |dx| is LARGE. So the shot type can be undecided while the direction
    is not, and a composition the author explicitly asked for still needs one.

    One spelling, two readers: reframe.compute_path lays the crop out against it and
    check_episode scores the result against it. If they derived it separately they
    could disagree on a left-moving subject — the crop leading one way and the check
    grading the other line — and the report would be wrong about a correct render.
    An empty/1-point route has no travel; "right" matches classify's own default.
    """
    if len(route) < 2:
        return "right"
    return "right" if route[-1]["x"] - route[0]["x"] >= 0 else "left"
