# tests/integration/test_anchors.py
"""Real-ffmpeg proof that measure_curve reads motion off actual pixels."""
import pytest

from scripts.lib import anchors, ffbin, proc

pytestmark = pytest.mark.integration


def _clip(path, expr):
    """A 4s 30fps clip whose content follows `expr` (a testsrc-free synthetic)."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c=black:s=320x180:d=4:r=30", "-vf", expr,
              "-pix_fmt", "yuv420p", str(path)])


def test_measure_curve_is_flat_on_a_still_clip(tmp_path):
    src = tmp_path / "still.mp4"
    _clip(src, "drawbox=x=10:y=10:w=40:h=40:color=white:t=fill")
    curve = anchors.measure_curve(str(src), 0.0, 4.0)
    assert len(curve) >= 10
    assert max(curve) - min(curve) < 1.0        # nothing moves, so nothing differs


def test_measure_curve_spikes_where_the_picture_jumps(tmp_path):
    # A box that teleports at t=2s: one large frame-to-frame difference, there and
    # nowhere else. The jump is expressed by enable-gating two drawboxes on the
    # timestamp, NOT by an `x` expression in `t` — in drawbox the variable `t` is
    # the box THICKNESS, not time (only the `enable` timeline sees the timestamp),
    # so an `if(lt(t,2),...)` in `x` never moves.
    src = tmp_path / "jump.mp4"
    _clip(src, "drawbox=x=10:y=10:w=40:h=40:color=white:t=fill:enable='lt(t,2)',"
               "drawbox=x=260:y=10:w=40:h=40:color=white:t=fill:enable='gte(t,2)'")
    curve = anchors.measure_curve(str(src), 0.0, 4.0)
    got = anchors.anchors_from_curve(curve)
    assert got, "the teleport must produce an anchor"
    assert min(abs(t - 2.0) for t in got) < 0.5
