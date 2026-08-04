"""Appearance primitives (§6.1a layer 1 / design 2026-08-04).

The 512-d OSNet embedding itself is produced by lib/reid (the only torchreid
importer). This module stays numpy+PIL-free of the model: it owns the pure cosine
DISTANCE between two embeddings and the crop helpers that feed reid.embed.
footage.DESCRIPTOR_LEN is the on-disk length; the metric here must agree with
reid.embed's output (L2-normalized), so descriptor_dist is a true cosine distance.

Shared by intake (surfaces and names the cast) and track (matches a pinned cast
member against this episode's tracks). They live here, not in intake.py, because a
driver must not import a driver — the same reason marks_at_times moved to
lib/geometry. This module (numpy, no cv2) stays importable without the torch stack
that lib/reid pulls: the manifest gate imports footage, never this, and owes the
caller an answer in milliseconds.
"""
import numpy as np

CAST_MATCH = 0.35     # max cosine distance for "this track IS that cast member" (design §5).
                      # Cosine range is [0, 2] (0 identical, 1 orthogonal, 2 opposite). A FIRST
                      # CUT calibratable on the real cache after the first re-scan — no footage
                      # exists to tune it (the repo's honest-threshold pattern). The real
                      # discriminator is min-distance + track.AMBIG_MARGIN; this only gates
                      # absence ("the pinned person is not in this episode at all").


def descriptor_dist(a: list[float], b: list[float]) -> float:
    """Cosine distance 1 - a·b between two L2-normalized embeddings. Range [0, 2]:
    0 identical direction, 1 orthogonal, 2 opposite. Operands MUST be L2-normalized
    (reid.embed's output, or a CastMember centroid) — that is this function's
    precondition and all it can check is that they agree in length: a distance
    between different-length vectors is meaningless (zip would silently truncate)."""
    if len(a) != len(b):
        raise ValueError(f"descriptor length mismatch: {len(a)} vs {len(b)} — a cosine "
                         f"distance between different-length vectors is meaningless. Both "
                         f"operands must be reid.embed outputs (512-d L2-normalized) or a "
                         f"footage.CastMember, which validates the same shape at the cast.json "
                         f"boundary.")
    return 1.0 - sum(x * y for x, y in zip(a, b))


def _bbox_ltrb(box: object) -> tuple[int, int, int, int]:
    """Clamp a box's centre-format xywh to integer (l, t, r, b), left/top >= 0."""
    x, y, w, h = (float(v) for v in box.xywh[0])
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    return max(0, l), max(0, t), r_, b_


def crop_from_result(res: object, box: object) -> np.ndarray | None:
    """The bbox crop (RGB) from an ultralytics result — the crop half of the old
    crop_and_mask, with NO mask (design §3.2/§10: OSNet is fed the raw bbox crop;
    a silhouette is out-of-distribution). ultralytics orig_img is BGR → RGB here,
    the colour-order landmine (design §10). None when the frame is unavailable
    (mocked results) or the crop is empty."""
    img = getattr(res, "orig_img", None)
    if img is None:
        return None
    arr = np.asarray(img)[..., ::-1]                       # BGR → RGB
    l, t, r_, b_ = _bbox_ltrb(box)
    crop = arr[t:b_, l:r_]
    return crop if crop.size else None


def crop_bbox(frame_rgb: np.ndarray, box_xywh: tuple[float, float, float, float],
              scale: float = 1.0) -> np.ndarray | None:
    """Crop `frame_rgb` (HxWx3 RGB) to the xywh `box` scaled by `scale`
    (proxy→original). A pure cropper: it carries no mask — the raw bbox crop is what
    reid.embed wants (design §3.2/§10). Returns None on an empty crop."""
    x, y, w, h = (v * scale for v in box_xywh)
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = frame_rgb[t:b_, l:r_]
    return crop if crop.size else None
