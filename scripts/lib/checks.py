"""Pure numeric checks over route + crop path (spec §9)."""


def on_line(route, path, crop_w, target_frac, tol=0.05):
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


def centered(route, path, crop_w, tol=0.05):
    return on_line(route, path, crop_w, target_frac=0.5, tol=tol)


def continuity(route, src_w, max_step_frac=0.04):
    """No x-teleports in the followed route (spec §6.1a): a tracker ID switch
    shows up as a per-frame |dx| far above any physical subject speed."""
    worst = 0.0
    for a, b in zip(route, route[1:]):
        worst = max(worst, abs(b["x"] - a["x"]))
    cap = max_step_frac * src_w
    return {"pass": worst <= cap, "worst_dx": worst, "cap": cap}


def jitter(path, direction, max_reversal):
    if direction not in ("left", "right"):
        raise ValueError(f"jitter: direction must be 'left' or 'right', got {direction!r}")
    sign = 1 if direction == "right" else -1
    worst = 0.0
    for i in range(1, len(path)):
        step = (path[i] - path[i - 1]) * sign      # forward = positive
        if step < 0:
            worst = max(worst, -step)
    return {"pass": worst <= max_reversal, "worst_reversal": worst}


def length(actual, target, tol=0.5):
    return {"pass": abs(actual - target) <= tol, "delta": actual - target}
