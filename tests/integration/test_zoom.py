"""Real-ffmpeg proofs for the subject-anchored zoom (design 2026-08-08 §9).

No stubs: every assertion here is about pixels ffmpeg actually produced, because
the one trap the lint cannot reach — zoompan clamping z below 1 to 1, byte
identically — is invisible to any argv-level check.
"""
import json

import pytest
from PIL import Image

from scripts import reframe
from scripts.lib import assembly, ffbin, proc
from scripts.lib.models import (CropPath, Delivery, LayoutSpec, PathMeta, ReframeSpec,
                                ZoomSpec)

pytestmark = pytest.mark.integration


@pytest.fixture
def marked_clip(tmp_path):
    """2s, 30fps, 640x480: a 64px white square centred on black."""
    out = tmp_path / "marked.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", "color=c=black:s=640x480:r=30:d=2",
              "-f", "lavfi", "-i", "color=c=white:s=64x64:r=30:d=2",
              "-filter_complex", "[0][1]overlay=288:208",
              "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)])
    return out


def _route(tmp_path):
    p = tmp_path / "route.json"
    p.write_text(json.dumps([
        {"t": 0.0, "x": 320.0, "y": 240.0, "w": 64.0, "h": 64.0},
        {"t": 1.0, "x": 320.0, "y": 240.0, "w": 64.0, "h": 64.0},
        {"t": 2.0, "x": 320.0, "y": 240.0, "w": 64.0, "h": 64.0}]))
    return p


def _spec(**over):
    # long_edge=240 (not native) on purpose: `zoom.validate` refuses a push-in that
    # upsamples past ZOOM_MAX_UPSCALE, and a native delivery makes the crop and the
    # output the same width, leaving no room at all (design 2026-08-08 §6).
    base = dict(composition="center", grid="thirds", canvas=(640, 480),
                color_means=(105, 122, 137), delivery=Delivery("long_edge", 240),
                layout=LayoutSpec(mode="fill"))
    base.update(over)
    return ReframeSpec(**base)


def _white_width(clip, t):
    """Width in output px of the white square at time t."""
    png = f"{clip}.{t}.png"
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(clip), "-ss", f"{t:.3f}",   # -ss AFTER -i (§12)
              "-frames:v", "1", png])
    im = Image.open(png).convert("L")
    cols = [x for x in range(im.width)
            if max(im.crop((x, 0, x + 1, im.height)).getdata()) > 200]
    return (max(cols) - min(cols) + 1) if cols else 0


def test_a_push_in_really_magnifies_the_subject(tmp_path, marked_clip):
    out = tmp_path / "zoomed.mp4"
    reframe.reframe(_spec(zoom=ZoomSpec(start=1.0, end=0.6)), str(marked_clip),
                    str(_route(tmp_path)), str(out), str(tmp_path / "path.json"))
    first, last = _white_width(out, 0.05), _white_width(out, 1.95)
    assert first > 0
    # 1/0.6 = 1.67x, allowing for the encode's edge softening and int rounding
    assert last / first == pytest.approx(1 / 0.6, rel=0.12)


def test_the_recorded_widths_match_the_rendered_rect(tmp_path, marked_clip):
    path_out = tmp_path / "path.json"
    out = tmp_path / "zoomed.mp4"
    reframe.reframe(_spec(zoom=ZoomSpec(start=1.0, end=0.6)), str(marked_clip),
                    str(_route(tmp_path)), str(out), str(path_out))
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    # the subject is 64 source px wide; on screen it occupies 64/rect_w of the output
    for t, i in ((0.05, 0), (1.95, -1)):
        expected = 64 * meta.out_dims[0] / meta.crop_ws[i]
        assert _white_width(out, t) == pytest.approx(expected, abs=4)


def test_a_zoom_changes_neither_the_dimensions_nor_the_frame_count(tmp_path, marked_clip):
    plain, zoomed = tmp_path / "plain.mp4", tmp_path / "zoomed.mp4"
    reframe.reframe(_spec(), str(marked_clip), str(_route(tmp_path)), str(plain),
                    str(tmp_path / "p1.json"))
    reframe.reframe(_spec(zoom=ZoomSpec(start=1.0, end=0.6)), str(marked_clip),
                    str(_route(tmp_path)), str(zoomed), str(tmp_path / "p2.json"))
    a, b = assembly.probe_stream(str(plain)), assembly.probe_stream(str(zoomed))
    assert (a.w, a.h, a.fps) == (b.w, b.h, b.fps)
    assert abs(assembly.probe_duration(str(plain))
               - assembly.probe_duration(str(zoomed))) < 0.05


def test_a_pull_out_moves_the_pixels_too(tmp_path, marked_clip):
    """The z-clamp trap's other face: a pull-out is authored 0.6 -> 1.0, and it must
    render, not collapse to a still frame."""
    out = tmp_path / "pulled.mp4"
    reframe.reframe(_spec(zoom=ZoomSpec(start=0.6, end=1.0)), str(marked_clip),
                    str(_route(tmp_path)), str(out), str(tmp_path / "path.json"))
    assert _white_width(out, 1.95) < _white_width(out, 0.05)
