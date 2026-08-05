import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _stub_tile(sink):
    """A sheet.tile stand-in that records what it was handed and returns a throwaway
    image, so a test can assert on CELLS (labels, marks, cols) without decoding a
    real sheet."""
    def _tile(cells, **kw):
        sink(cells, kw)
        return Image.new("RGB", (10, 10))
    return _tile


def _grey_frames(src, times, fps):
    return [np.zeros((180, 320, 3), np.uint8) for _ in times]


def _win(start=0.0, dur=2.0, shot="wide", score=0.6, best=True):
    return FootageWindow(start=start, dur=dur, shot_type=shot, people=1,
                         motion=0.3, shake=0.001, description="1 person, wide, calm",
                         score=score, best=best)


def _footage(tmp_path, clips) -> str:
    f = Footage(clips=clips)
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _clip(source="a.mp4", windows=None):
    return FootageClip(source=source, dur=30.0, res=(1920, 1080), fps=30.0,
                       windows=windows if windows is not None else [_win()])


@pytest.fixture
def fake_frames(monkeypatch):
    """Replace the decode with a recorder returning a distinct grey per call, so the
    driver's sampling is observable without ffmpeg."""
    calls = []

    def _frames(src, times, fps):
        calls.append((src, list(times), fps))
        return [np.full((180, 320, 3), 10 + i, dtype=np.uint8) for i in range(len(times))]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    return calls


# ---- sampling ----

def test_one_frame_per_window_at_the_window_midpoint(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=4.0, dur=2.0),
                                            _win(start=10.0, dur=3.0)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert fake_frames == [("a.mp4", [5.0, 11.5], 30.0)]


def test_one_decode_call_per_clip(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip("a.mp4"), _clip("b.mp4")])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert [c[0] for c in fake_frames] == ["a.mp4", "b.mp4"]


def test_cells_run_in_clip_then_window_order_not_score_order(tmp_path, fake_frames):
    # window 0 scores lower than window 1: a score-ordered sheet would swap them.
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, score=0.51),
                                            _win(start=8.0, score=0.99)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert fake_frames[0][1] == [1.0, 9.0]


# ---- selection ----

def test_every_window_is_shown_by_default(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert res["cells"] == 2


def test_best_only_drops_the_rest(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), best_only=True)
    assert res["cells"] == 1
    assert fake_frames[0][1] == [1.0]


# ---- output ----

def test_writes_sheets_and_an_index_that_links_every_one(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=float(i)) for i in range(31)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert len(res["sheets"]) == 2                      # 31 cells at 30 per sheet
    md = (tmp_path / "SHEETS.md").read_text()
    for p in res["sheets"]:
        assert f"sheets/{Path(p).name}" in md
        assert Path(p).exists()
    assert "sheets/sheet_02.png" not in md              # links no sheet it did not write


def test_the_index_says_the_star_is_not_a_ranking_to_follow(tmp_path, fake_frames):
    # the scoring bias (design §1.1) is why a reader must not simply take the top of
    # the list; the index has to say so where the reader is.
    fp = _footage(tmp_path, [_clip()])
    contact_sheet.build_sheets(fp, str(tmp_path))
    md = (tmp_path / "SHEETS.md").read_text()
    assert "not a ranking to follow" in md


def test_labels_carry_the_window_index_and_the_measurements(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(c.lines for c in cells)))
    fp = _footage(tmp_path, [_clip("clips/MVI_3739.mp4",
                                   windows=[_win(start=0.0, dur=3.4, shot="medium",
                                                 score=0.71, best=True),
                                            _win(start=8.0, best=False)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert seen[0] == ("MVI_3739.mp4 #0", "medium · 3.4s · 0.71 ★")
    assert seen[1][0] == "MVI_3739.mp4 #1"
    assert "★" not in seen[1][1]


def test_best_windows_are_marked(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(c.marked for c in cells)))
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    contact_sheet.build_sheets(fp, str(tmp_path))
    assert seen == [True, False]


# ---- failure modes ----

def test_a_clip_that_will_not_decode_is_skipped_and_named(tmp_path, monkeypatch):
    def _frames(src, times, fps):
        if src == "bad.mp4":
            raise RuntimeError("bad.mp4 is missing")
        return [np.zeros((180, 320, 3), np.uint8) for _ in times]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    fp = _footage(tmp_path, [_clip("bad.mp4"), _clip("good.mp4")])
    res = contact_sheet.build_sheets(fp, str(tmp_path))
    assert res["skipped"] == ["bad.mp4"]
    assert res["cells"] == 1                             # good.mp4 still sheeted
    md = (tmp_path / "SHEETS.md").read_text()
    assert "Not sheeted" in md and "bad.mp4" in md and "is missing" in md


def test_no_windows_writes_an_honest_index_and_no_png(tmp_path, fake_frames):
    # an absent artifact would wedge next_action on this stage forever; an empty
    # answer is a real answer.
    fp = _footage(tmp_path, [_clip(windows=[_win(best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), best_only=True)
    assert res["sheets"] == [] and res["cells"] == 0
    assert (tmp_path / "SHEETS.md").exists()
    assert "No sheets" in (tmp_path / "SHEETS.md").read_text()
    assert not (tmp_path / "sheets").exists()


def test_a_corrupt_footage_file_fails_loud(tmp_path):
    bad = tmp_path / "FOOTAGE.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError):
        contact_sheet.build_sheets(str(bad), str(tmp_path))


# ---- CLI ----

def test_cli_build_passes_best_only(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_sheets",
                        lambda fp, out, **kw: seen.update(kw) or {"status": "written"})
    monkeypatch.setattr("sys.argv", ["contact_sheet", "build", "--footage", "F.json",
                                     "--out-dir", str(tmp_path), "--best-only"])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen == {"best_only": True}
