"""Manual keyframes → a dense route (rung 3 of the degradation ladder, design 2026-07-21 §4).

The human's answer channel when both automatic trackers gave nothing: a few sparse
RoutePoint marks, densified by linear interpolation into the same route.json every
downstream reader expects. The session's proven method — sparse keyframes plus
interpolation — one level up from hand-authoring a full frame-by-frame route.
"""
import json
from pathlib import Path

import numpy as np

from scripts.lib.models import RoutePoint, TrackMeta, route_to_json


def interpolate(sparse: list[RoutePoint], fps: float, dur: float) -> list[RoutePoint]:
    """Sparse marks → one RoutePoint per frame over [0, dur]. Each field (x, y, w, h)
    is linearly interpolated across the marks' t values; before the first mark it holds
    the first, after the last it holds the last (numpy.interp's edge behavior, named on
    purpose). One mark is a legal static hold; zero marks, an out-of-range t, or
    non-increasing ts fail loud — a hand-authored answer channel is exactly where a
    silent clamp would hide a typo."""
    if not sparse:
        raise ValueError("keyframes: need at least one mark [{t,x,y,w,h}] to interpolate a "
                         "route — supply a keyframes.json with one or more sparse RoutePoints")
    marks = sorted(sparse, key=lambda p: p.t)
    ts = [p.t for p in marks]
    if any(t < 0 or t > dur for t in ts):
        raise ValueError(f"keyframes: a mark t is outside [0, {dur}] — every keyframe must land "
                         f"within the clip; got {ts}")
    if any(ts[i] >= ts[i + 1] for i in range(len(ts) - 1)):
        raise ValueError(f"keyframes: mark ts must strictly increase (a route is single-valued "
                         f"in time); got {ts}")
    n = round(dur * fps)
    grid = [i / fps for i in range(n + 1)]

    def col(attr: str) -> np.ndarray:
        return np.interp(grid, ts, [getattr(p, attr) for p in marks])

    xs, ys, ws, hs = col("x"), col("y"), col("w"), col("h")
    return [RoutePoint(t=grid[i], x=float(xs[i]), y=float(ys[i]),
                       w=float(ws[i]), h=float(hs[i])) for i in range(len(grid))]


def write_route(keyframes_path: str, out: str, fps: float, dur: float) -> list[RoutePoint]:
    """Read a sparse keyframes.json, interpolate, and write the SAME pair track.py
    writes: route.json + a route.meta.json stamped degraded="manual". RoutePoint.from_dict
    guards a bare-scalar file — the hand-authoring human is exactly who benefits."""
    raw = json.loads(Path(keyframes_path).read_text())
    sparse = [RoutePoint.from_dict(d) for d in raw]
    route = interpolate(sparse, fps, dur)
    route_to_json(route, out)
    Path(out).with_suffix(".meta.json").write_text(json.dumps(TrackMeta(degraded="manual").to_dict()))
    return route
