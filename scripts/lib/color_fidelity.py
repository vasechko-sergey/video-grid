"""Advisory colour-fidelity metric (design 2026-07-26 §7): subject hue drift,
source vs graded. Pure — the ffmpeg/PIL sampling lives in check_episode."""
import colorsys

GREY_EPS = 10.0     # min chroma (max-min of mean RGB, 0-255) for a defined hue


def hue(rgb: tuple[float, float, float]) -> float | None:
    """HSV hue angle in degrees, or None when the colour is too near grey to have one.
    Hue is invariant to exposure (scaling all channels) and to saturation (scaling
    chroma about grey), so a drift in it means a real hue shift, not the grade's
    intended exposure/saturation move."""
    if max(rgb) - min(rgb) < GREY_EPS:
        return None
    h, _, _ = colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return h * 360.0


def hue_drift(src_rgb: tuple[float, float, float],
              graded_rgb: tuple[float, float, float]) -> float | None:
    """Circular hue distance in degrees, or None when either side is near-grey."""
    hs, hg = hue(src_rgb), hue(graded_rgb)
    if hs is None or hg is None:
        return None
    d = abs(hs - hg)
    return min(d, 360.0 - d)


def evaluate(pairs: list[tuple], threshold: float) -> dict:
    """Aggregate per-sample (src_rgb, graded_rgb) pairs into an advisory result.
    All-grey samples → not-checked (a grey subject cannot 'drift')."""
    drifts = [d for src, graded in pairs if (d := hue_drift(src, graded)) is not None]
    if not drifts:
        return {"status": "not-checked", "reason": "subject near-grey in every sample"}
    worst = max(drifts)
    return {"worst_drift_deg": round(worst, 1), "threshold": threshold,
            "exceeded": worst > threshold, "samples": len(drifts)}
