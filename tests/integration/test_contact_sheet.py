"""Real-ffmpeg proof for the footage contact sheet (design
docs/specs/2026-08-05-footage-contact-sheet-design.md). The unit tests fake the decode;
these run it, so the frames on the sheet are the frames in the clip.

The FOOTAGE these tests write carries a BARE filename for `source` plus a SEPARATE
`footage_root` — exactly the shape scripts/intake.py actually produces
(`FootageClip(source=Path(path).name, ...)`, intake.py:352). Earlier revisions of this
file passed `str(sample_clip)` — an absolute path — straight through as `source`, which
happened to decode regardless of whether `build_sheets` joined a root at all, so it
could not have caught the bug where `build_sheets` called `assembly.frames_rgb` on the
bare `clip.source` alone (a name with no directory can never resolve). Keeping the
fixture in intake's real shape is what makes this suite a real regression guard.
"""
import json

import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib import sheet
from scripts.lib.footage import Footage, FootageClip, FootageWindow

pytestmark = pytest.mark.integration


def _footage(tmp_path, source: str, windows) -> str:
    f = Footage(clips=[FootageClip(source=source, dur=3.0, res=(1920, 1080), fps=30.0,
                                   windows=windows)])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _win(start, dur, best=True, shot="wide"):
    return FootageWindow(start=start, dur=dur, shot_type=shot, people=1, motion=0.3,
                         shake=0.001, description="1 person, wide, calm", score=0.7,
                         best=best)


def test_build_writes_a_real_sheet_of_the_real_frames(sample_clip, tmp_path):
    fp = _footage(tmp_path, sample_clip.name,
                  [_win(0.0, 1.0), _win(1.0, 1.0), _win(2.0, 1.0)])
    res = contact_sheet.build_sheets(fp, str(sample_clip.parent), str(tmp_path))
    assert res["cells"] == 3 and res["skipped"] == []
    assert len(res["sheets"]) == 1
    img = Image.open(res["sheets"][0])
    assert img.size == (3 * sheet.CELL_W, sheet.CELL_H + sheet.LABEL_H)
    assert max(img.size) <= 1568
    md = (tmp_path / "SHEETS.md").read_text()
    assert "sheets/sheet_00.png" in md and "3 windows" in md


def test_the_sheet_carries_the_moving_box_at_three_different_places(sample_clip, tmp_path):
    # the fixture's white box slides left->right, so the three midpoint frames differ.
    # A sheet that grabbed the SAME frame three times (the failure mode a keyframe-near
    # seek would produce) puts the box at the same x in every cell.
    fp = _footage(tmp_path, sample_clip.name,
                  [_win(0.0, 1.0), _win(1.0, 1.0), _win(2.0, 1.0)])
    res = contact_sheet.build_sheets(fp, str(sample_clip.parent), str(tmp_path))
    px = Image.open(res["sheets"][0]).convert("RGB").load()
    y = sheet.CELL_H // 2
    centres = []
    for c in range(3):
        xs = [x for x in range(c * sheet.CELL_W, (c + 1) * sheet.CELL_W)
              if px[x, y][0] > 200]
        assert xs, f"cell {c} shows no white box"
        centres.append(sum(xs) / len(xs) - c * sheet.CELL_W)
    assert centres[0] < centres[1] < centres[2]


def test_best_only_narrows_the_real_build(sample_clip, tmp_path):
    fp = _footage(tmp_path, sample_clip.name,
                  [_win(0.0, 1.0, best=True), _win(1.5, 1.0, best=False)])
    res = contact_sheet.build_sheets(fp, str(sample_clip.parent), str(tmp_path),
                                     best_only=True)
    assert res["cells"] == 1
    assert Image.open(res["sheets"][0]).size == (sheet.CELL_W,
                                                 sheet.CELL_H + sheet.LABEL_H)


def test_a_missing_clip_is_quarantined_and_the_good_one_still_sheets(sample_clip, tmp_path):
    f = Footage(clips=[
        FootageClip(source="gone.mp4", dur=3.0, res=(1920, 1080),
                    fps=30.0, windows=[_win(0.0, 1.0)]),
        FootageClip(source=sample_clip.name, dur=3.0, res=(1920, 1080),
                    fps=30.0, windows=[_win(0.0, 1.0)])])
    fp = tmp_path / "FOOTAGE.json"
    fp.write_text(json.dumps(f.to_dict()))
    res = contact_sheet.build_sheets(str(fp), str(sample_clip.parent), str(tmp_path))
    assert res["skipped"] == ["gone.mp4"]
    assert res["cells"] == 1 and len(res["sheets"]) == 1
    assert "Not sheeted" in (tmp_path / "SHEETS.md").read_text()


def test_every_clip_missing_raises_instead_of_a_silent_empty_sheet(sample_clip, tmp_path):
    # the Critical-2 floor, proved against a real (missing) path rather than a fake:
    # a footage_root that resolves NOTHING must not produce a thin, silent "success".
    fp = _footage(tmp_path, sample_clip.name, [_win(0.0, 1.0)])
    wrong_root = tmp_path / "not_where_the_clips_are"
    wrong_root.mkdir()
    with pytest.raises(RuntimeError, match="footage-root"):
        contact_sheet.build_sheets(fp, str(wrong_root), str(tmp_path))
    assert not (tmp_path / "SHEETS.md").exists()


def test_strip_renders_the_requested_frames_in_time_order(sample_clip, tmp_path):
    out = tmp_path / "strip.png"
    res = contact_sheet.build_strip(str(sample_clip), str(out), start=0.0, dur=3.0,
                                    frames=6)
    assert res["times"] == sorted(res["times"]) and len(res["times"]) == 6
    # The layout is fitted to the clip's aspect, so cols and cell dimensions come from
    # fit_layout, not hardcoded values. Verify they are in the response and the image
    # was rendered with those dimensions.
    assert "cols" in res and "cell_px" in res and "frames" in res
    cell_w, cell_h = res["cell_px"]
    rows = (res["frames"] + res["cols"] - 1) // res["cols"]  # ceiling division
    expected_size = (res["cols"] * cell_w, rows * (cell_h + sheet.LABEL_H))
    img = Image.open(out)
    assert img.size == expected_size


def test_strip_window_sugar_matches_the_explicit_range(sample_clip, tmp_path):
    fp = _footage(tmp_path, sample_clip.name, [_win(0.0, 1.0), _win(1.0, 1.5)])
    src, start, dur, fps = contact_sheet.resolve_window(fp, str(sample_clip.parent),
                                                         sample_clip.name, 1)
    assert src == str(sample_clip)
    a = contact_sheet.build_strip(src, str(tmp_path / "a.png"), start=start, dur=dur,
                                  frames=4, fps=fps)
    b = contact_sheet.build_strip(str(sample_clip), str(tmp_path / "b.png"), start=1.0,
                                  dur=1.5, frames=4)
    assert a["times"] == b["times"]
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
