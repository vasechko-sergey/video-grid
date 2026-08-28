"""Colour-naturalness measurement (design docs/specs/2026-08-08-episode-qc-design.md §5).

check_episode's color_fidelity answers "how far did the grade move the SUBJECT's
colour" and says nothing about the frame around it. This measures the frame: two
absolute flags for information the grade destroyed (blown highlights, crushed
blacks) and three source-relative ones for what it changed (cast, saturation,
contrast), so the QC judge argues from numbers instead of impressions.

Pure: numpy arrays in, one dict out. No ffmpeg, no file paths — the caller decodes
(assembly.frames_rgb) and the caller decides. Nothing here fails an episode: the flags
are advisory in both directions (design §5)."""
import numpy as np

# Absolute bars, for destroyed information only. A blown sky is blown whatever the
# source held, so these two do not need a source to compare against. Still first
# cuts: BLOWN_FRAC fired once on the reference run and plausibly; CRUSHED_FRAC never
# fired on footage that never crushed.
CLIP_HIGH = 250       # a channel value at/above this counts as "at white"
CLIP_LOW = 5          # ...and at/below this as "at black"
BLOWN_FRAC = 0.02     # >2% of pixels at white in ANY channel → blown_highlights
CRUSHED_FRAC = 0.05   # >5% at black → crushed_blacks (shadows legitimately cover more area)

# Source-relative bars (design docs/specs/2026-08-28-grade-delta-sensors-design.md §4).
# The absolute versions of these three were DELETED, not retuned: CAST_MAX read the
# ocean (6 of 8 SOURCES exceeded it before any grade), and SAT_MAX/FLAT_SPREAD sat at
# 0.60 and 40.0 against footage measuring 0.11-0.50 and 86-189 — unreachable. Each bar
# below is set where the reference run's OWN source-to-graded range stops, so nothing
# the shipped grade did would fire it.
CAST_DELTA_MAX = 0.08        # |Δ grey-world deviation|; run's max was 0.0766
SAT_DELTA_MAX = 0.12         # |Δ mean relative saturation|; run's range −0.1026…+0.0316
CONTRAST_DROP_MAX = 20.0     # LOSS of p95−p5 luma only; run's worst loss was 16.61


def _frame_stats(f: np.ndarray) -> dict:
    """One frame's numbers. Reductions only — no float copy of the whole frame is
    materialized, so a 4K frame costs its own bytes and not eight times them."""
    ok = isinstance(f, np.ndarray) and f.ndim == 3 and f.shape[2] == 3 and f.dtype == np.uint8
    if not ok:
        got = f"shape={f.shape}, dtype={f.dtype}" if isinstance(f, np.ndarray) else type(f).__name__
        raise ValueError(f"naturalness: each frame must be an HxWx3 uint8 RGB array, got "
                         f"{got} — sample frames with assembly.frames_rgb (HxWx3 uint8 RGB) "
                         f"before calling")
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
    """The absolute flags: information the grade destroyed. Never a pass/fail — the
    judge weighs them against the episode's intent (a deliberately crushed night shot
    is not a defect)."""
    return {"blown_highlights": max(stats["clip_high"]) > BLOWN_FRAC,
            "crushed_blacks": max(stats["clip_low"]) > CRUSHED_FRAC}


def evaluate_delta(src: dict, grd: dict) -> dict:
    """What the grade DID: `src` and `grd` are two `measure` readings, pre- and
    post-grade. Advisory in both directions.

    `contrast_drop` is signed and the other two are not: a gain in luma spread is not
    a defect (the reference run's ep6 gained 24.5 legitimately), while a cast or a
    saturation move is worth reporting whichever way it went."""
    return {"cast_shift": abs(grd["cast"] - src["cast"]) > CAST_DELTA_MAX,
            "saturation_shift": abs(grd["saturation"] - src["saturation"]) > SAT_DELTA_MAX,
            "contrast_drop": (src["contrast"] - grd["contrast"]) > CONTRAST_DROP_MAX}
