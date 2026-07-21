"""Optical-flow rung — the proof that needs real pixels and real cv2.

sample_clip is a bright box sliding left→right on a dark field (tests/conftest.py):
YOLO detects no person in it (that's the rung-1→2 trigger), and its motion is exactly
what optical-flow reads. So the flow route's x must climb left→right.
"""
import json
from pathlib import Path

import pytest

from scripts.lib import flow
from scripts.lib.models import route_from_json, TrackMeta

pytestmark = pytest.mark.integration


def test_flow_route_tracks_the_moving_box(sample_clip, tmp_path):
    out = str(tmp_path / "route.json")
    route = flow.build_route(str(sample_clip), out, fps=30.0, dims=(1920, 1080))
    assert len(route) > 10, "optical-flow found no motion in a clip that plainly moves"
    xs = [p.x for p in route]
    assert xs[-1] > xs[0] + 200, "the box slides left→right; the flow centroid must follow"
    assert route_from_json(out) == route
    meta = TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.degraded == "flow"
