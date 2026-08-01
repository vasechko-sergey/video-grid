"""Appearance descriptors — the identity primitives (§6.1a layer 1).

Shared by intake (surfaces and names the cast) and track (matches a pinned cast
member against this episode's tracks). They live here, not in intake.py, because
a driver must not import a driver — the same reason marks_at_times moved to
lib/geometry. That rule is about DRIVERS: lib/footage is a contract module, so
importing HIST_BINS from it is allowed and deliberate. The direction matters —
this module (numpy + Pillow, no cv2) depends on the contract, never the reverse:
footage must stay importable without the CV stack, because the manifest gate
imports it and owes the caller an answer in milliseconds.

HIST_BINS is not declared here because a descriptor's shape is cast.json's
contract, and cast.json is footage's file. Reading it from there is what stops
the producer (build_descriptor) and the registry that validates its output from
drifting to two different numbers.
"""
import numpy as np
from PIL import Image

from scripts.lib.footage import HIST_BINS

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
    distance — a silently wrong hero, not a crash.

    That the operands agree with each other is this function's OWN precondition,
    and it is all this checks. A descriptor's shape (footage.DESCRIPTOR_LEN) is
    deliberately not re-checked here: footage.CastMember owns that fact and gates
    the one path a foreign descriptor takes into the engine (cast.json), so by the
    time anything reaches this function both operands come from build_descriptor
    or a validated CastMember. Re-asserting it would be a second spelling of the
    same fact and a branch no wired path can reach. The message used to promise
    that check without making it — it now says exactly what it does."""
    if len(a) != len(b):
        raise ValueError(f"descriptor length mismatch: {len(a)} vs {len(b)} — a distance between "
                         f"different-length vectors is meaningless. Both operands must be "
                         f"descriptors from appearance.build_descriptor (or a footage.CastMember, "
                         f"which validates the same shape at the cast.json boundary).")
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


def crop_bbox(frame_rgb: np.ndarray, box_xywh: tuple[float, float, float, float],
              scale: float = 1.0) -> np.ndarray | None:
    """Crop `frame_rgb` (HxWx3 RGB) to the xywh `box` scaled by `scale`
    (proxy→original). No mask: the maskless descriptor path is accurate enough for
    a full-body crop (design §5). Returns None on an empty crop."""
    x, y, w, h = (v * scale for v in box_xywh)
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = frame_rgb[t:b_, l:r_]
    return crop if crop.size else None
