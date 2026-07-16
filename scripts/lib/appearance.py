"""Appearance descriptors — the identity primitives (§6.1a layer 1).

Shared by intake (surfaces and names the cast) and track (matches a pinned cast
member against this episode's tracks). They live here, not in intake.py, because
a driver must not import a driver — the same reason marks_at_times moved to
lib/geometry. numpy + Pillow, no cv2.
"""
import numpy as np
from PIL import Image

HIST_BINS = 8
CAST_MATCH = 0.6      # max L1 descriptor distance for "this track IS that cast member".
                      # descriptor_dist ranges [0.0, 2.0], so this is 30% of the max:
                      # necessarily looser than intake's CAST_DEDUP (0.30, "are these two
                      # crops the same person") because a cast descriptor is snapped from a
                      # different clip's lighting and pose — yet tight enough that "the
                      # pinned person is not in this episode at all" still fails. A FIRST
                      # CUT, not a derived number: the real discriminator is min-distance
                      # among the tracks present plus track.py's margin rule; this only
                      # guards absence. Deriving it from cast_candidates.json's distance
                      # distribution is a deferred slice (design §11).


def build_descriptor(crop_rgb: np.ndarray, mask: np.ndarray | None) -> list[float]:
    """L1-normalized color histogram over the segmentation-mask pixels only
    (clothing/gear — background removed; §6.1a). numpy + Pillow, no cv2."""
    px = crop_rgb[mask > 0] if mask is not None else crop_rgb.reshape(-1, 3)
    if px.size == 0:
        px = crop_rgb.reshape(-1, 3)
    hist: list[float] = []
    for c in range(3):
        h, _ = np.histogram(px[:, c], bins=HIST_BINS, range=(0, 255))
        hist.extend(h.tolist())
    total = float(sum(hist)) or 1.0
    return [v / total for v in hist]


def descriptor_dist(a: list[float], b: list[float]) -> float:
    """L1 distance between two descriptors. Range [0.0, 2.0]: each descriptor is
    normalized over its GRAND total, so both sum to 1.0 and the maximum is
    attained exactly when their supports are disjoint. Equal lengths are enforced:
    zip() would truncate to the shorter operand and return a plausible-but-wrong
    distance — a silently wrong hero — and cast.json's own validation cannot catch
    it (CastMember.descriptor is checked as "a non-empty list of numbers" only)."""
    if len(a) != len(b):
        raise ValueError(f"descriptor length mismatch: {len(a)} vs {len(b)} (both must be "
                         f"3 * HIST_BINS = {3 * HIST_BINS}) — a descriptor built under a different "
                         f"HIST_BINS, i.e. a stale cast.json; re-run footage-intake to regenerate it "
                         f"(`.venv/bin/python -m scripts.intake <footage_root> <out_dir>`)")
    return sum(abs(x - y) for x, y in zip(a, b))


def crop_and_mask(res: object, idx: int, box: object) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Extract the box's crop (RGB) + seg mask from an ultralytics result. Returns
    (None, None) when the frame image or masks are unavailable (mocked tests)."""
    img = getattr(res, "orig_img", None)
    if img is None:
        return None, None
    arr = np.asarray(img)[..., ::-1]                       # ultralytics orig_img is BGR → RGB
    x, y, w, h = (float(v) for v in box.xywh[0])
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = arr[t:b_, l:r_]
    mask = None
    masks = getattr(res, "masks", None)
    if masks is not None and getattr(masks, "data", None) is not None:
        m = np.asarray(masks.data[idx])                    # (H, W) in model space
        m = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((arr.shape[1], arr.shape[0])))
        mask = m[t:b_, l:r_]
    return (crop if crop.size else None), mask
