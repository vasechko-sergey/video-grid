"""Pure numeric checks over route + crop path (spec §9)."""


def on_line(route: list[dict[str, float]], path: list[int], crop_w: int,
            target_frac: float, tol: float = 0.05) -> dict:
    if len(route) != len(path):
        raise ValueError(
            f"route/path length mismatch: {len(route)} vs {len(path)} — "
            "route and crop path must be parallel arrays from the same reframe run")
    ok = 0
    for pt, cx in zip(route, path):
        frac = (pt["x"] - cx) / crop_w
        if abs(frac - target_frac) <= tol:
            ok += 1
    ratio = ok / max(1, len(route))
    return {"pass": ratio >= 0.9, "ratio": ratio}


def centered(route: list[dict[str, float]], path: list[int], crop_w: int,
             tol: float = 0.05) -> dict:
    return on_line(route, path, crop_w, target_frac=0.5, tol=tol)


def continuity(route: list[dict[str, float]], src_w: int, max_step_frac: float = 0.04) -> dict:
    """No x-teleports in the followed route (spec §6.1a): a tracker ID switch
    shows up as a per-frame |dx| far above any physical subject speed."""
    worst = 0.0
    for a, b in zip(route, route[1:]):
        worst = max(worst, abs(b["x"] - a["x"]))
    cap = max_step_frac * src_w
    return {"pass": worst <= cap, "worst_dx": worst, "cap": cap}


def _moving_average(xs: list[float], window: int) -> list[float]:
    """Centred box filter, shrinking at the ends so length is preserved. Pure —
    checks.py stays free of scipy."""
    if window <= 1:
        return list(xs)
    half, n = window // 2, len(xs)
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        out.append(sum(xs[a:b]) / (b - a))
    return out


def jitter(path: list[int], direction: str, max_reversal: float,
           route: list[dict[str, float]] | None = None,
           route_window: int = 1) -> dict:
    """Crop-centre reversal against the direction of travel — the §9 "rounding
    flicker" guard.

    With `route`, the SUBJECT'S OWN counter-motion is subtracted first. Without it
    this is the only composition check that judges the path in a vacuum (centered/
    on_line both score path AGAINST route), and it therefore cannot tell a crop
    chattering over a smooth subject from a crop faithfully following a surfer who
    carves back up the wave: a noiseless route weaving +-150px scores worst=6 while
    on_line is still 0.919. `direction` comes from motion.classify, which reduces a
    whole episode to route[0] vs route[-1], so every honest frame of counter-motion
    is scored as jitter.

    Subtracting only the NEGATIVE part of the subject's own step keeps the check
    honest: a crop that chatters over a smoothly-moving subject still fails (the
    route contributes nothing to subtract), and a crop that reverses further or
    faster than the subject still fails, by the excess. Only the reversal the
    subject actually performed is forgiven — which is what "following" means.
    A generated pan passes `route=None`/[] and keeps the historical behaviour.

    `route_window` box-filters the route before differencing, and is the difference
    between measuring the SUBJECT and measuring the DETECTOR. A raw route carries
    per-frame bbox noise of the same amplitude as the defect, so subtracting it
    frame-to-frame cancels perfectly for a path that copies that noise and cancels
    not at all for a path that filters it — i.e. the check scores an unsmoothed,
    visibly juddering crop BEST. Measured on a 60fps drone ride: the raw path (2nd
    difference p95 = 8.9 output px, the judder you can see) scored worst_reversal
    0.94 and passed, while a smoothed path at the 1-px quantization floor scored
    4.00 and failed. Filtering the route over ~0.08s inverts both verdicts to match
    what is on screen. 1 (the default) is the historical frame-to-frame behaviour;
    check_episode derives the real window from the route's own cadence.
    """
    if direction not in ("left", "right"):
        raise ValueError(f"jitter: direction must be 'left' or 'right', got {direction!r}")
    if isinstance(route_window, bool) or not isinstance(route_window, int) or route_window < 1:
        raise ValueError(f"jitter: route_window must be an integer >= 1 frame, "
                         f"got {route_window!r}")
    sign = 1 if direction == "right" else -1
    worst = 0.0
    reversals = 0
    use_route = bool(route) and len(route) >= len(path)
    rx = _moving_average([p["x"] for p in route], route_window) if use_route else []
    for i in range(1, len(path)):
        step = (path[i] - path[i - 1]) * sign      # forward = positive
        if use_route:
            subj = (rx[i] - rx[i - 1]) * sign
            step -= min(0.0, subj)                 # forgive only the subject's own backtrack
        if step < 0:
            worst = max(worst, -step)
            if step < -1:
                reversals += 1
    return {"pass": worst <= max_reversal, "worst_reversal": worst,
            "reversals": reversals}


def length(actual: float, target: float, tol: float = 0.5) -> dict:
    return {"pass": abs(actual - target) <= tol, "delta": actual - target}
