"""Colour-naturalness measurement (design docs/specs/2026-08-08-episode-qc-design.md §5).

check_episode's color_fidelity answers "did the grade move the SUBJECT's hue away from
the source" and is blind to the four things that actually make a graded frame read
unnatural: blown highlights, crushed blacks, a global colour cast, and oversaturation.
This measures those, so the QC judge argues from numbers instead of impressions.

Pure: numpy arrays in, one dict out. No ffmpeg, no file paths — the caller decodes
(assembly.frames_rgb) and the caller decides. Nothing here fails an episode: the flags
are advisory in both directions (design §5)."""
import numpy as np

# First cuts, declared as first cuts — no footage has been graded against them. They
# live here and ONLY here: a threshold a caller can pass is a threshold a subagent can
# pass, and the gate's no-waiver rule (§7) would be worth nothing if the sensor's bar
# were an argument. Calibrate on the first real run that uses them.
CLIP_HIGH = 250       # a channel value at/above this counts as "at white"
CLIP_LOW = 5          # ...and at/below this as "at black"
BLOWN_FRAC = 0.02     # >2% of pixels at white in ANY channel → blown_highlights
CRUSHED_FRAC = 0.05   # >5% at black → crushed_blacks (shadows legitimately cover more area)
CAST_MAX = 0.08       # grey-world channel deviation above this reads as a colour cast
SAT_MAX = 0.60        # mean relative saturation above this reads oversaturated
FLAT_SPREAD = 40.0    # p95-p5 luma below this reads flat


def _frame_stats(f: np.ndarray) -> dict:
    """One frame's numbers. Reductions only — no float copy of the whole frame is
    materialized, so a 4K frame costs its own bytes and not eight times them."""
    if not (isinstance(f, np.ndarray) and f.ndim == 3 and f.shape[2] == 3):
        raise ValueError(f"naturalness: each frame must be an HxWx3 RGB array, got "
                         f"{getattr(f, 'shape', type(f).__name__)}")
    px = f.reshape(-1, 3)
    means = [float(px[:, c].mean()) for c in range(3)]
    hi = [float((px[:, c] >= CLIP_HIGH).mean()) for c in range(3)]
    lo = [float((px[:, c] <= CLIP_LOW).mean()) for c in range(3)]
    mx = px.max(axis=1).astype(np.float32)
    mn = px.min(axis=1).astype(np.float32)
    sat = float(((mx - mn) / np.maximum(mx, 1.0)).mean())
    luma = (0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]).astype(np.float32)
    p5, p95 = (float(v) for v in np.percentile(luma, [5, 95]))
    return {"means": means, "clip_high": hi, "clip_low": lo, "saturation": sat,
            "contrast": p95 - p5}


def measure(frames: list) -> dict:
    """Aggregate `frames` (HxWx3 uint8 RGB) into one clip-level reading.

    Averaged per frame, never pooled pixel-wise: a single blown frame in a 90-frame
    episode must read as 1/90 blown, and pooling would also cost a float copy of every
    pixel in the episode at once."""
    if not frames:
        raise ValueError("naturalness.measure needs at least one frame — sample the clip "
                         "with assembly.frames_rgb before calling")
    per = [_frame_stats(f) for f in frames]
    n = len(per)
    means = [sum(s["means"][c] for s in per) / n for c in range(3)]
    neutral = sum(means) / 3
    # A frame whose channels are all zero has no neutral to deviate from; report no
    # cast rather than divide by it. (A black episode is the black_frames gate's job.)
    cast = max(abs(m / neutral - 1.0) for m in means) if neutral > 0 else 0.0
    return {"frames": n,
            "means": [round(m, 2) for m in means],
            "clip_high": [round(sum(s["clip_high"][c] for s in per) / n, 4) for c in range(3)],
            "clip_low": [round(sum(s["clip_low"][c] for s in per) / n, 4) for c in range(3)],
            "cast": round(cast, 4),
            "saturation": round(sum(s["saturation"] for s in per) / n, 4),
            "contrast": round(sum(s["contrast"] for s in per) / n, 2)}


def evaluate(stats: dict) -> dict:
    """Named advisory flags. Never a pass/fail — the judge weighs them against the
    episode's intent (a deliberately crushed night shot is not a defect)."""
    return {"blown_highlights": max(stats["clip_high"]) > BLOWN_FRAC,
            "crushed_blacks": max(stats["clip_low"]) > CRUSHED_FRAC,
            "colour_cast": stats["cast"] > CAST_MAX,
            "oversaturated": stats["saturation"] > SAT_MAX,
            "flat": stats["contrast"] < FLAT_SPREAD}
