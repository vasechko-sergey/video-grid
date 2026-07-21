"""Optical-flow centroid tracker — rung 2 of the degradation ladder (design 2026-07-21 §3).

Identity-blind: it follows the dominant motion blob and makes no person/identity claim,
so process_episode runs it ONLY for an unpinned episode whose YOLO route came back empty
(orchestration.flow_eligible). The first runtime use of OpenCV as a *tracker* — intake
only ever probed with it. cv2 is undeclared in requirements.txt (transitive under
ultralytics), so available() is a real gate, not decoration.
"""


def available() -> bool:
    """True iff cv2 imports. Rung-2 gate: if ultralytics was the absent dep, cv2 (its
    transitive) may be gone too — this makes that a clean fall to rung 3, not a second
    traceback. Mirrors track.available()."""
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def _centroid_bbox(mask) -> tuple[float, float, float, float] | None:
    """Largest connected component of a boolean motion mask → (cx, cy, w, h) in mask
    pixels, or None when nothing is set. cv2 label 0 is background."""
    import cv2
    import numpy as np
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8),
                                                                     connectivity=8)
    if n <= 1:                                     # only background → no motion blob
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    _x, _y, w, h, _area = stats[idx]
    cx, cy = centroids[idx]
    return float(cx), float(cy), float(w), float(h)
