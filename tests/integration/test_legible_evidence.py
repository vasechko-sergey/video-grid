"""Real-ffmpeg proof that a strip cell shaped like its content carries picture edge
to edge, and that the footage contact sheet did not move (design §2, §8).

Each claim has a control that must NOT move.
"""
import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib import ffbin, proc, sheet

pytestmark = pytest.mark.integration


def _solid_clip(path, w, h, seconds=3, colour="red"):
    """A solid-colour clip at an exact size. `d=` bounds the lavfi source itself, so
    there is no infinite input to cut short (fit-solid §4), and the pix_fmt + range
    pair is the one the §12 registry requires."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c={colour}:s={w}x{h}:d={seconds}:r=30",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(path)])
    return str(path)


def _is_red(px):
    r, g, b = px
    return r > 150 and g < 90 and b < 90


def test_a_portrait_strips_cell_carries_picture_edge_to_edge(tmp_path):
    src = _solid_clip(tmp_path / "portrait.mp4", 360, 640)
    out = tmp_path / "strip.png"
    res = contact_sheet.build_strip(src, str(out), start=0.0, dur=2.0, frames=9)
    cw, ch = res["cell_px"]
    img = Image.open(out).convert("RGB")

    assert max(img.size) <= sheet.READER_LONG_SIDE          # inside the budget
    assert img.size == (res["cols"] * cw,
                        2 * (ch + sheet.LABEL_H))           # 9 cells at 5 wide -> 2 rows

    # THE claim: the first cell's picture reaches both of its own side edges. Under a
    # 16:9 box a 9:16 frame uses 95 of 300 columns and these two pixels are black.
    assert _is_red(img.getpixel((1, ch // 2)))
    assert _is_red(img.getpixel((cw - 2, ch // 2)))
    # and its label strip below is still background, so the cell height is right
    assert img.getpixel((cw // 2, ch + sheet.LABEL_H - 2)) == (0, 0, 0)


def test_control_a_landscape_strip_is_still_letterbox_free(tmp_path):
    # The control: 16:9 content was ALREADY edge to edge in the 16:9 box. If this
    # moves, the change broke the case it was not supposed to touch.
    src = _solid_clip(tmp_path / "wide.mp4", 640, 360)
    out = tmp_path / "wide_strip.png"
    res = contact_sheet.build_strip(src, str(out), start=0.0, dur=2.0, frames=9)
    cw, ch = res["cell_px"]
    img = Image.open(out).convert("RGB")
    assert _is_red(img.getpixel((1, ch // 2)))
    assert _is_red(img.getpixel((cw - 2, ch // 2)))


def test_control_the_default_cell_box_still_letterboxes_a_portrait_frame(tmp_path):
    # The control on the CONTACT SHEET's side: sheet.tile's defaults are unchanged,
    # so a portrait thumbnail in the mixed-aspect overview still lands in a 16:9 box
    # with black at its left edge. Byte-identical behaviour, deliberately kept
    # (design §8) -- that sheet mixes aspects and a ragged grid would be worse.
    import numpy as np
    frame = np.full((320, 180, 3), 200, np.uint8)
    img = sheet.tile([sheet.Cell(image=frame, lines=("t",))])
    assert img.size == (sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)
    assert img.getpixel((1, sheet.CELL_H // 2)) == (0, 0, 0)


def test_a_strip_never_renders_more_pixels_than_the_source_carries(tmp_path):
    src = _solid_clip(tmp_path / "small.mp4", 96, 160)
    out = tmp_path / "small_strip.png"
    res = contact_sheet.build_strip(src, str(out), start=0.0, dur=2.0, frames=9)
    assert res["cell_px"] == [96, 160]           # the fit would allow far more
    img = Image.open(out).convert("RGB")
    assert img.size == (res["cols"] * 96, 2 * (160 + sheet.LABEL_H))
