"""Stabilization apply (design 2026-07-20) — the proofs that need real pixels.

Everything in tests/lib/test_vidstab.py runs against a stubbed proc.run, so it
pins the ARGV. Whether that argv actually reduces shake, and whether crop=keep
actually leaves no black edge, only real libvidstab can say.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from scripts import process_episode, track
from scripts.lib import ffbin, proc, vidstab
from scripts.lib.models import PathMeta, RoutePoint

pytestmark = pytest.mark.integration


@pytest.fixture
def shaky_clip(tmp_path, need_filter):
    """A synthetic clip that genuinely shakes: a static test pattern pushed around
    by a per-frame crop offset. sample_clip is too still to measure against.

    The offset's oscillation frequency (n*1.7 / n*2.3) is fine as a shake signal —
    measured — but a first attempt at 18px amplitude on a 640x480 canvas is NOT: the
    SECOND vidstabdetect pass (measuring the stabilized output) has its own noise
    floor from vidstabtransform's crop=keep border-fill seams (see vidstab.stabilize's
    docstring, §7), and 18px of source shake lands right at that floor — `after` came
    out at or above `before`, not because stabilization does not work but because
    the signal was too small to clear the measurement's own noise. 150px on a
    1120x800 canvas keeps the identical frequency and crops down to the same
    560x400 output, but pushes `before` (~0.043) well clear of that floor, giving a
    reproducible ~2.5x reduction instead of a coin flip.
    """
    need_filter("vidstabdetect")
    need_filter("vidstabtransform")
    out = str(tmp_path / "shaky.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", "testsrc2=size=1120x800:rate=30:duration=2",
              "-vf", ("crop=560:400:280+150*sin(n*1.7):200+150*cos(n*2.3),"
                      "scale=560:400,format=yuv420p"),
              "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-an", out])
    return out


def test_stabilization_actually_reduces_the_shake(shaky_clip, tmp_path):
    """The slice's charter, and the one assertion no stub can fake."""
    out = str(tmp_path / "stabilized.mp4")
    before, after = vidstab.stabilize(shaky_clip, out, (560, 400), 30.0, 2.0)
    assert before > 0, "the fixture is not shaky — the comparison below is vacuous"
    assert after < before


def test_crop_keep_leaves_no_black_edge(shaky_clip, tmp_path):
    """The positive control for design §4.1. crop=black would put a band at the
    frame edge that check_episode's median-based black gate cannot see, so this
    decision is otherwise pinned by prose alone. Reads the outermost rows/columns
    of every frame — a frame median would miss exactly the defect this looks for."""
    out = str(tmp_path / "stabilized.mp4")
    vidstab.stabilize(shaky_clip, out, (560, 400), 30.0, 2.0)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", out,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 400, 560)
    assert len(frames) > 30, "too few frames decoded to be a real check"
    for i, f in enumerate(frames):
        for name, band in (("top", f[0]), ("bottom", f[-1]),
                           ("left", f[:, 0]), ("right", f[:, -1])):
            assert band.max() > 16, f"frame {i} has a black {name} edge — crop=keep regressed"


def test_a_stabilized_episode_reaches_mechanical_pass(shaky_clip, tmp_path, monkeypatch):
    """End to end through process_episode with a real vidstab pass: the pre-stage
    runs, the tracker and reframe both read its output, the sidecar records it.
    YOLO is faked — a test pattern is not a person, the same reason
    tests/integration/test_intake.py fakes it.

    The route stub must write BOTH route.json and its route.meta.json sidecar —
    process_episode's _load_route reads a route AND a .meta.json sidecar (a
    TrackMeta), and a stub writing only the former fails on the missing sidecar,
    not on the thing under test. Mirrors test_process_episode.py's fake_build_route.

    manifest.validate() calls vidstab.require() for a stabilize=true manifest,
    which is a real `ffmpeg -filters` spawn on this machine — slow but honest for
    an integration test to let run; it is deliberately NOT stubbed here.
    """
    # a static subject, dead-center in the 560x400 stabilized frame (comfortably
    # inside on every side) — composition "center" below expects exactly this.
    route = [{"t": i / 30, "x": 280.0, "y": 200.0, "w": 100.0, "h": 200.0}
             for i in range(60)]

    def fake_build_route(spec, out):
        Path(out).write_text(json.dumps(route))
        Path(out).with_suffix(".meta.json").write_text(json.dumps({"ambiguous": False}))
        return [RoutePoint.from_dict(d) for d in route]
    monkeypatch.setattr(track, "build_route", fake_build_route)

    proj = tmp_path / "proj"
    proj.mkdir()
    md = {"segment": shaky_clip, "out_path": str(tmp_path / "ep.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [1080, 1920],
          "target_dur": 2.0, "stabilize": True}
    result = process_episode.process_episode(md, str(proj))
    assert result["status"] == "mechanical_pass", result
    assert result["stabilize"]["after"] < result["stabilize"]["before"]
    meta = PathMeta.from_json(proj / "path.meta.json")
    assert meta.stabilized is True
