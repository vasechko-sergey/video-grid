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

    Both the AMPLITUDE and the FREQUENCY were tuned by measurement, and each guards
    a different test:

    * Amplitude 150px on a 1120x800 canvas (cropped down to the 560x400 output) is
      what test 1 needs. An earlier 18px-on-640x480 attempt measured real source
      shake but landed at the noise floor the SECOND vidstabdetect pass picks up
      from vidstabtransform's crop=keep border-fill seams (see vidstab.stabilize's
      docstring, §7) — so `after` came out at or above `before`, a coin flip. 150px
      pushes `before` (~0.066) well clear of that floor.

    * Frequency 0.3 (slow), not the ~1.7 a first version used, is what test 2 needs.
      vidstabdetect tracks a SLOW oscillation accurately and vidstabtransform then
      applies a LARGE correction, uncovering a wide border the filler must fill. A
      fast oscillation is under-tracked: the correction is only a few px, zoom=2
      covers it, and crop=black vs crop=keep become indistinguishable at the edge —
      the exact reason the first version of test 2 could not catch a crop=black
      regression (measured: identical outputs). At freq 0.3 the two modes separate
      cleanly (border dark-fraction ~0.32 vs ~0.005); test 2 depends on that.

    Measured with this recipe: before~0.066, after~0.040 (a ~40% reduction).
    """
    need_filter("vidstabdetect")
    need_filter("vidstabtransform")
    out = str(tmp_path / "shaky.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", "testsrc2=size=1120x800:rate=30:duration=2",
              "-vf", ("crop=560:400:280+150*sin(n*0.3):200+150*cos(n*0.405),"
                      "scale=560:400,format=yuv420p"),
              "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-an", out])
    return out


def test_stabilization_actually_reduces_the_shake(shaky_clip, tmp_path):
    """The slice's charter, and the one assertion no stub can fake."""
    out = str(tmp_path / "stabilized.mp4")
    before, after = vidstab.stabilize(shaky_clip, out, (560, 400), 30.0, 2.0)
    assert before > 0, "the fixture is not shaky — the comparison below is vacuous"
    assert after < before


# Border-defect detection (test 2). Calibrated against the shaky_clip fixture by
# rendering it under BOTH crop=keep (the shipped recipe) and crop=black (the
# rejected one, design §4.1) and measuring where they separate — the mutation
# `crop=keep`->`crop=black` in scripts/lib/vidstab.py MUST fail this test, or it
# controls nothing.
#
# Two facts drove every choice here, both measured, both counter-intuitive:
#
#  1. crop=black's border is NOT at the outermost row/column. zoom=2 pulls the
#     outermost ~8px from real content, so the uncovered black band sits INSET from
#     the true edge. Reading only f[0]/f[-1]/f[:,0]/f[:,-1] (the first version of
#     this test) misses it entirely. So we read a border RING of thickness _RING_PX.
#
#  2. band.max() > 16 is the wrong aggregation: it passes as long as ONE bright
#     pixel exists anywhere along the edge, and crop=black's band is a wedge/strip
#     that leaves plenty. We measure the FRACTION of the ring that is black instead.
#
# Calibrated distributions (3 rebuilds each; worst frame per clip):
#   crop=keep  ring dark-fraction: 0.0006 .. 0.0069   (testsrc2's own dark content)
#   crop=black ring dark-fraction: 0.3235             (the border-fill band)
# _MAX_DARK_FRAC = 0.05 sits ~7x above keep's worst and ~6.5x below black's — a 47x
# separation. A frame median (check_episode's own black gate) cannot see either;
# that blind spot is precisely why crop=black was rejected in prose and needs a
# pixel-level control here.
_RING_PX = 20
_MAX_DARK_FRAC = 0.05


def test_crop_keep_leaves_no_black_edge(shaky_clip, tmp_path):
    """The positive control for design §4.1: crop=keep must leave no border-fill
    band. Renders the shipped recipe and asserts no frame has a black border ring —
    the mutation to crop=black fails exactly here (see the calibration note above)."""
    out = str(tmp_path / "stabilized.mp4")
    vidstab.stabilize(shaky_clip, out, (560, 400), 30.0, 2.0)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", out,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 400, 560)
    assert len(frames) > 30, "too few frames decoded to be a real check"
    ring = np.zeros((400, 560), dtype=bool)
    ring[:_RING_PX, :] = True
    ring[-_RING_PX:, :] = True
    ring[:, :_RING_PX] = True
    ring[:, -_RING_PX:] = True
    for i, f in enumerate(frames):
        dark_frac = float((f[ring] < 16).mean())
        assert dark_frac < _MAX_DARK_FRAC, (
            f"frame {i}: {dark_frac:.1%} of the {_RING_PX}px border ring is black — "
            "crop=keep regressed to crop=black (design §4.1)")


def test_a_stabilized_episode_reaches_mechanical_pass(shaky_clip, tmp_path, monkeypatch):
    """End to end through process_episode with a real vidstab pass: the pre-stage
    runs, the tracker and reframe both read its output, the sidecar records it.
    YOLO is faked — a test pattern is not a person, the same reason
    tests/integration/test_intake.py fakes it.

    The route stub writes BOTH route.json and its route.meta.json sidecar, mirroring
    the real tracker's contract (and test_process_episode.py's fake_build_route). A
    missing sidecar would not actually crash — _load_route (process_episode.py:31-32)
    treats it as absent-means-unambiguous and defaults to {"ambiguous": False}, the
    exact value written here — but writing it keeps the stub faithful to what
    track.build_route really produces rather than leaning on that default.

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
