"""Optical-flow centroid tracker — rung 2 of the degradation ladder (design 2026-07-21 §3).

Identity-blind: it follows the dominant motion blob and makes no person/identity claim,
so process_episode runs it ONLY for an unpinned episode whose YOLO route came back empty
(orchestration.flow_eligible). The first runtime use of OpenCV as a *tracker* — intake
only ever probed with it. cv2 is undeclared in requirements.txt (transitive under
ultralytics), so available() is a real gate, not decoration.
"""
import json
from pathlib import Path

import numpy as np

from scripts.lib.models import RoutePoint, TrackMeta, route_to_json


LONG_SIDE = 480      # downscale target; centroid precision is coarse by nature and the route
                     # is smoothed downstream, so a small frame buys ~15x fewer flow pixels
MAG_FRAC = 0.5       # motion mask threshold = MAG_FRAC * this frame's own max flow magnitude


def available() -> bool:
    """True iff cv2 imports. Rung-2 gate: if ultralytics was the absent dep, cv2 (its
    transitive) may be gone too — this makes that a clean fall to rung 3, not a second
    traceback. Mirrors track.available()."""
    try:
        import cv2  # lazy import: heavy optional dep (cv2, undeclared/transitive under ultralytics)
        return True
    except ImportError:
        return False


def _centroid_bbox(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """Largest connected component of a boolean motion mask → (cx, cy, w, h) in mask
    pixels, or None when nothing is set. cv2 label 0 is background."""
    import cv2  # lazy import: heavy optional dep (cv2, undeclared/transitive under ultralytics)
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8),
                                                                     connectivity=8)
    if n <= 1:                                     # only background → no motion blob
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    _x, _y, w, h, _area = stats[idx]
    cx, cy = centroids[idx]
    return float(cx), float(cy), float(w), float(h)


def build_route(src: str, out: str, fps: float, dims: tuple[int, int]) -> list[RoutePoint]:
    """Decode src with cv2 (its own decoder — NOT an ffmpeg argv, so no §12 landmine),
    downscale to LONG_SIDE, run dense Farneback flow between consecutive gray frames, and
    take the largest motion blob's centroid + box as the per-frame RoutePoint. Writes the
    standard route.json + route.meta.json(degraded="flow") pair. fps/dims are passed in
    (the caller already probed them); an empty route (no motion above threshold) is honest
    — flow needs motion, and rung 3 takes over."""
    import cv2  # lazy import: heavy optional dep (cv2, undeclared/transitive under ultralytics)
    src_w, src_h = dims
    scale = LONG_SIDE / max(src_w, src_h)
    inv = 1.0 / scale
    cap = cv2.VideoCapture(str(src))
    prev, hits = None, []                          # hits[i]: blob for the flow between frames i,i+1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            f = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag = np.hypot(f[..., 0], f[..., 1])
            mx = float(mag.max())
            hits.append(_centroid_bbox(mag > MAG_FRAC * mx) if mx > 0 else None)
        prev = gray
    cap.release()
    # a flow field sits between source frames i and i+1; index it to frame i+1 and seed
    # frame 0 from the first field so the route starts at t=0 (design §3).
    per_frame = ([hits[0]] + hits) if hits else []
    route = []
    for i, hit in enumerate(per_frame):
        if hit is None:
            continue                                # a gap — smoothing bridges it, no fake point
        cx, cy, w, h = hit
        route.append(RoutePoint(t=i / fps, x=cx * inv, y=cy * inv, w=w * inv, h=h * inv))
    route_to_json(route, out)
    Path(out).with_suffix(".meta.json").write_text(json.dumps(TrackMeta(degraded="flow").to_dict()))
    return route
