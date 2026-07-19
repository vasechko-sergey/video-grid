"""Real-ffmpeg proof that a pan moves the crop across the source (design §10)."""
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import reframe
from scripts.lib import proc
from scripts.lib.models import Delivery, LayoutSpec, PanSpec, ReframeSpec

pytestmark = pytest.mark.integration

SRC_W, SRC_H, DUR, FPS = 1280, 720, 2.0, 30


@pytest.fixture
def edge_marked_clip(tmp_path):
    """Grey clip with a RED block at the left edge and a BLUE one at the right.

    A 9:16 crop of a 720-tall source is 405px wide, so no single frame can hold
    both blocks (they sit 1000px apart). Static drawbox positions only — the
    repo's landmine is `t`-DEPENDENT drawbox expressions, which read t as
    INT32_MAX under this ffmpeg; constants are fine.
    """
    out = tmp_path / "edges.mp4"
    proc.run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"color=c=gray:s={SRC_W}x{SRC_H}:d={DUR}:r={FPS}",
              "-vf", ("drawbox=x=40:y=310:w=120:h=120:color=red@1.0:t=fill,"
                      "drawbox=x=1120:y=310:w=120:h=120:color=blue@1.0:t=fill"),
              "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)])
    return str(out)


def _frame(clip: str, where: str, tmp_path: Path) -> Image.Image:
    png = tmp_path / f"{where}.png"
    if where == "first":
        proc.run(["ffmpeg", "-y", "-i", clip, "-frames:v", "1", "-update", "1", str(png)])
    else:
        # -sseof BEFORE -i is the established form in this repo (check_episode
        # uses it); the banned pattern is `-ss` AFTER `-i` for frame-accurate cuts
        proc.run(["ffmpeg", "-y", "-sseof", "-0.1", "-i", clip, "-update", "1", str(png)])
    return Image.open(png).convert("RGB")


def _has(img: Image.Image, colour: str) -> bool:
    """Loose thresholds — h264 + yuv420p shifts saturated colours a little."""
    px = list(img.getdata())
    if colour == "red":
        return any(r > 130 and g < 95 and b < 95 for r, g, b in px)
    return any(b > 130 and r < 95 and g < 95 for r, g, b in px)


def _centre_route(tmp_path) -> Path:
    """A tracked route pinned at the source's centre — the CONTROL."""
    p = tmp_path / "route.json"
    p.write_text(json.dumps([
        {"t": i / FPS, "x": SRC_W / 2, "y": SRC_H / 2, "w": 100, "h": 200}
        for i in range(int(DUR * FPS))]))
    return p


def _render(tmp_path, src, pan):
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105, 122, 137), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"), pan=pan)
    out = tmp_path / f"out_{'pan' if pan else 'static'}.mp4"
    reframe.reframe(spec, src, None if pan else str(_centre_route(tmp_path)),
                    str(out), str(tmp_path / f"path_{'pan' if pan else 'static'}.json"))
    return str(out)


def test_a_left_to_right_pan_moves_the_crop_across_the_source(edge_marked_clip, tmp_path):
    out = _render(tmp_path, edge_marked_clip, PanSpec(start=0.0, end=1.0))
    first, last = _frame(out, "first", tmp_path), _frame(out, "last", tmp_path)
    assert _has(first, "red") and not _has(first, "blue"), "the pan must START at the left edge"
    assert _has(last, "blue") and not _has(last, "red"), "the pan must END at the right edge"


def test_a_right_to_left_pan_moves_the_other_way(edge_marked_clip, tmp_path):
    out = _render(tmp_path, edge_marked_clip, PanSpec(start=1.0, end=0.0))
    first, last = _frame(out, "first", tmp_path), _frame(out, "last", tmp_path)
    assert _has(first, "blue"), "a 1→0 pan must start at the RIGHT edge"
    assert _has(last, "red"), "a 1→0 pan must end at the LEFT edge"


def test_the_control_sees_neither_edge(edge_marked_clip, tmp_path):
    # WITHOUT THIS the proof above would also pass if both markers were simply
    # visible in every frame — the assertion would be measuring nothing.
    out = _render(tmp_path, edge_marked_clip, None)
    for where in ("first", "last"):
        img = _frame(out, where, tmp_path)
        assert not _has(img, "red") and not _has(img, "blue"), \
            f"a centre-pinned crop must see neither edge marker ({where} frame)"
