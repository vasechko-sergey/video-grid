import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts import contact_sheet
from scripts.lib import sheet
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
    contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert fake_frames == [(str(tmp_path / "a.mp4"), [5.0, 11.5], 30.0)]


def test_one_decode_call_per_clip(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip("a.mp4"), _clip("b.mp4")])
    contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert [c[0] for c in fake_frames] == [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")]


def test_cells_run_in_clip_then_window_order_not_score_order(tmp_path, fake_frames):
    # window 0 scores lower than window 1: a score-ordered sheet would swap them.
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, score=0.51),
                                            _win(start=8.0, score=0.99)])])
    contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert fake_frames[0][1] == [1.0, 9.0]


# ---- selection ----

def test_every_window_is_shown_by_default(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert res["cells"] == 2


def test_best_only_drops_the_rest(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=0.0, best=True),
                                            _win(start=8.0, best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"), best_only=True)
    assert res["cells"] == 1
    assert fake_frames[0][1] == [1.0]


# ---- output ----

def test_writes_sheets_and_an_index_that_links_every_one(tmp_path, fake_frames):
    fp = _footage(tmp_path, [_clip(windows=[_win(start=float(i)) for i in range(31)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert len(res["sheets"]) == 2                      # 31 cells at 30 per sheet
    md = (tmp_path / "out" / "SHEETS.md").read_text()
    for p in res["sheets"]:
        assert f"sheets/{Path(p).name}" in md
        assert Path(p).exists()
    assert "sheets/sheet_02.png" not in md              # links no sheet it did not write


def test_the_index_says_the_star_is_not_a_ranking_to_follow(tmp_path, fake_frames):
    # the scoring bias (design §1.1) is why a reader must not simply take the top of
    # the list; the index has to say so where the reader is.
    fp = _footage(tmp_path, [_clip()])
    contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    md = (tmp_path / "out" / "SHEETS.md").read_text()
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
    contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
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
    contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert seen == [True, False]


# ---- footage_root ----

def test_frames_rgb_is_called_with_footage_root_joined_against_the_bare_source(
        tmp_path, fake_frames):
    # the bug this guards: FootageClip.source is a BARE filename (intake stores only
    # Path(path).name), so calling frames_rgb with clip.source alone can never
    # resolve — the driver must join footage_root against it.
    root = tmp_path / "clips"
    fp = _footage(tmp_path, [_clip("a.mp4")])
    contact_sheet.build_sheets(fp, str(root), str(tmp_path))
    assert fake_frames[0][0] == str(root / "a.mp4")


# ---- failure modes ----

def test_a_clip_that_will_not_decode_is_skipped_and_named(tmp_path, monkeypatch):
    root = str(tmp_path)
    bad_src = str(tmp_path / "bad.mp4")

    def _frames(src, times, fps):
        if src == bad_src:
            raise RuntimeError("bad.mp4 is missing")
        return [np.zeros((180, 320, 3), np.uint8) for _ in times]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    fp = _footage(tmp_path, [_clip("bad.mp4"), _clip("good.mp4")])
    res = contact_sheet.build_sheets(fp, root, str(tmp_path / "out"))
    assert res["skipped"] == ["bad.mp4"]                 # the bare clip.source, not the joined path
    assert res["cells"] == 1                             # good.mp4 still sheeted
    md = (tmp_path / "out" / "SHEETS.md").read_text()
    assert "Not sheeted" in md and "bad.mp4" in md and "is missing" in md


def test_the_skip_reason_in_sheets_md_is_trimmed_to_its_last_line(tmp_path, monkeypatch):
    # proc.run's failure banner runs to ~30 lines; SHEETS.md must carry the one line
    # that names what went wrong, not the whole banner (99 skips would be ~3000 lines).
    banner = "command failed (exit 1): ffmpeg ...\n--- stderr tail ---\n" + \
             "\n".join(f"junk line {i}" for i in range(20)) + \
             "\nreal_clip.mp4: No such file or directory"
    fp = _footage(tmp_path, [_clip("bad.mp4"), _clip("good.mp4")])

    def _one_ok(src, times, fps):
        if src == str(tmp_path / "good.mp4"):
            return [np.zeros((180, 320, 3), np.uint8) for _ in times]
        raise RuntimeError(banner)
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _one_ok)
    res = contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    md = (tmp_path / "out" / "SHEETS.md").read_text()
    assert "junk line" not in md
    assert "real_clip.mp4: No such file or directory" in md
    assert res["skipped"] == ["bad.mp4"]


def test_no_windows_writes_an_honest_index_and_no_png(tmp_path, fake_frames):
    # an absent artifact would wedge next_action on this stage forever; an empty
    # answer is a real answer. This is the "nothing to attempt" case — no clip ever
    # had a candidate window — distinct from "attempted and every attempt failed"
    # below, which must raise instead (Critical-2 floor).
    fp = _footage(tmp_path, [_clip(windows=[_win(best=False)])])
    res = contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"), best_only=True)
    assert res["sheets"] == [] and res["cells"] == 0
    assert (tmp_path / "out" / "SHEETS.md").exists()
    assert "No sheets" in (tmp_path / "out" / "SHEETS.md").read_text()
    assert not (tmp_path / "out" / "sheets").exists()


def test_every_clip_failing_to_decode_raises_instead_of_a_silent_empty_success(
        tmp_path, monkeypatch):
    # the OTHER empty case: windows existed, a decode was attempted for every one of
    # them, and every attempt failed. That is the signature of a wrong
    # --footage-root, a moved footage folder, or a broken ffmpeg install — NOT one
    # corrupt file among many — so it must not look like a normal (if thin) success.
    def _frames(src, times, fps):
        raise RuntimeError("no such file or directory")
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    fp = _footage(tmp_path, [_clip("a.mp4"), _clip("b.mp4")])
    with pytest.raises(RuntimeError, match="every one of 2"):
        contact_sheet.build_sheets(fp, str(tmp_path), str(tmp_path / "out"))
    assert not (tmp_path / "out" / "SHEETS.md").exists()


def test_the_every_clip_failed_error_names_the_root_as_the_likely_cause(tmp_path, monkeypatch):
    def _frames(src, times, fps):
        raise RuntimeError("boom")
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _frames)
    fp = _footage(tmp_path, [_clip("a.mp4")])
    with pytest.raises(RuntimeError, match="footage-root") as exc:
        contact_sheet.build_sheets(fp, "/nonexistent/root", str(tmp_path))
    assert "/nonexistent/root" in str(exc.value)


def test_a_corrupt_footage_file_fails_loud(tmp_path):
    bad = tmp_path / "FOOTAGE.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        contact_sheet.build_sheets(str(bad), str(tmp_path), str(tmp_path / "out"))


def test_markdown_distinguishes_every_clip_failing_from_nothing_to_attempt(tmp_path):
    # _markdown's own contract: an honest answer for what it was given, distinguishing
    # "nothing to attempt" from "attempted and every attempt failed" — even though
    # build_sheets (above) now intercepts the second case with a raise before
    # _markdown is ever reached, so this exercises the helper directly.
    footage = Footage(clips=[_clip("a.mp4")])
    failed = contact_sheet._markdown(footage, 0, [], [("a.mp4", "boom")], best_only=False)
    assert "every clip with a candidate window failed to decode" in failed
    empty = contact_sheet._markdown(footage, 0, [], [], best_only=False)
    assert "No sheets: no window matched the selection." in empty


# ---- CLI ----

def test_cli_build_passes_best_only(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_sheets",
                        lambda fp, root, out, **kw: seen.update(kw) or {"status": "written"})
    monkeypatch.setattr("sys.argv", ["contact_sheet", "build", "--footage", "F.json",
                                     "--footage-root", "R", "--out-dir", str(tmp_path),
                                     "--best-only"])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen == {"best_only": True}


def test_cli_build_passes_the_footage_root_through(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_sheets",
                        lambda fp, root, out, **kw: seen.update(
                            {"fp": fp, "root": root, "out": out}) or {"status": "written"})
    monkeypatch.setattr("sys.argv", ["contact_sheet", "build", "--footage", "F.json",
                                     "--footage-root", "/clips", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen == {"fp": "F.json", "root": "/clips", "out": str(tmp_path)}


# ---- strip ----

def test_strip_samples_evenly_across_the_range(tmp_path, fake_frames):
    out = tmp_path / "s.png"
    res = contact_sheet.build_strip("a.mp4", str(out), start=10.0, dur=4.0,
                                    frames=4, fps=30.0)
    assert fake_frames == [("a.mp4", [10.5, 11.5, 12.5, 13.5], 30.0)]
    assert res["times"] == [10.5, 11.5, 12.5, 13.5]
    assert out.exists()


def test_strip_labels_each_cell_with_its_absolute_timestamp(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(c.lines for c in cells)))
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=10.0, dur=2.0,
                              frames=2, fps=30.0)
    assert seen == [("10.50s",), ("11.50s",)]


def test_strip_fits_its_layout_to_the_clips_own_aspect(tmp_path, monkeypatch):
    seen = {}
    portrait = [np.zeros((640, 360, 3), np.uint8) for _ in range(9)]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: list(portrait))
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    res = contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                    dur=4.0, frames=9, fps=30.0)
    # 9 cells of 360x640 (aspect 0.5625) fit 5 wide at 313px; the source carries
    # 360, above the fitted width, so no cap applies.
    assert (seen["cols"], seen["cell_w"], seen["cell_h"]) == (5, 313, 556)
    assert res["cols"] == 5 and res["cell_px"] == [313, 556]


def test_strip_never_upscales_past_the_sources_own_width(tmp_path, monkeypatch):
    seen = {}
    tiny = [np.zeros((160, 90, 3), np.uint8) for _ in range(9)]
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: list(tiny))
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    res = contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                    dur=4.0, frames=9, fps=30.0)
    # the fit would allow 313, the source carries 90; rendering 313 would report an
    # interpolated box as the evidence's resolution (design §7.3)
    assert seen["cell_w"] == 90 and seen["cell_h"] == 160
    assert res["cell_px"] == [90, 160]


def test_strip_of_landscape_content_gets_the_landscape_fit(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb", _grey_frames)  # 320x180
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.update(kw)))
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0, dur=4.0,
                              frames=9, fps=30.0)
    assert seen["cols"] == 3 and seen["cell_w"] == 320      # fit allows 522, source has 320


def test_strip_sheet_never_exceeds_the_reader_budget_across_frame_counts(tmp_path, monkeypatch):
    # sheet.fit_layout is proven never to exceed the budget (tests/lib/test_sheet.py),
    # but build_strip THEN derives cell_h by rounding the picture height back UP —
    # undoing that guarantee one function later, unless it truncates too. A 16:9
    # source at n=13-15 (cols=3, cell_w=497) is exactly where round() pushes the
    # sheet 2px past the 1568 budget (design 2026-09-08 §2, task 2); the seven-pair
    # sample in test_sheet.py never lands on this n, which is why it went unseen.
    wide = np.zeros((900, 1600, 3), np.uint8)      # 16:9, and wide enough that the
                                                    # never-upscale cap never binds —
                                                    # a fitted cell_w cannot exceed the
                                                    # 1568 budget at ANY column count.
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: [wide] * len(times))
    for n in range(9, 17):
        out = tmp_path / f"strip_{n}.png"
        res = contact_sheet.build_strip("a.mp4", str(out), start=0.0, dur=4.0,
                                        frames=n, fps=30.0)
        img = Image.open(out)
        assert max(img.size) <= sheet.READER_LONG_SIDE, (n, img.size, res["cell_px"])


def test_strip_refuses_a_decode_that_returned_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda src, times, fps: [])
    with pytest.raises(ValueError, match="decoded no frames"):
        contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                  dur=4.0, frames=9, fps=30.0)


def test_strip_probes_fps_when_not_given(tmp_path, fake_frames, monkeypatch):
    monkeypatch.setattr(contact_sheet.assembly, "probe_stream",
                        lambda p: type("I", (), {"fps": 60.0})())
    contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0, dur=1.0,
                              frames=1)
    assert fake_frames[0][2] == 60.0


def test_strip_refuses_a_non_positive_frame_count(tmp_path):
    with pytest.raises(ValueError, match="frames must be >= 1"):
        contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                  dur=1.0, frames=0, fps=30.0)


def test_strip_refuses_a_non_positive_duration(tmp_path):
    with pytest.raises(ValueError, match="dur must be > 0"):
        contact_sheet.build_strip("a.mp4", str(tmp_path / "s.png"), start=0.0,
                                  dur=0.0, frames=4, fps=30.0)


# ---- --window sugar ----

def test_resolve_window_returns_the_windows_own_range_and_the_clips_fps(tmp_path):
    (tmp_path / "MVI_3739.mp4").touch()
    fp = _footage(tmp_path, [_clip("MVI_3739.mp4",
                                   windows=[_win(start=1.0, dur=2.0),
                                            _win(start=9.0, dur=3.0)])])
    assert contact_sheet.resolve_window(fp, str(tmp_path), "MVI_3739.mp4", 1) == \
        (str(tmp_path / "MVI_3739.mp4"), 9.0, 3.0, 30.0)


def test_resolve_window_fails_loud_on_an_unknown_source(tmp_path):
    fp = _footage(tmp_path, [_clip("a.mp4")])
    with pytest.raises(ValueError, match="not in"):
        contact_sheet.resolve_window(fp, str(tmp_path), "typo.mp4", 0)


def test_resolve_window_fails_loud_on_an_out_of_range_index(tmp_path):
    fp = _footage(tmp_path, [_clip("a.mp4")])
    with pytest.raises(ValueError, match="out of range"):
        contact_sheet.resolve_window(fp, str(tmp_path), "a.mp4", 7)


def test_resolve_window_fails_loud_on_a_missing_file_naming_both_halves(tmp_path):
    # a.mp4 is never created on disk here — the source key resolves in FOOTAGE.json,
    # but the joined path does not exist, so the message must name footage_root and
    # source SEPARATELY (extract.extract_edl's precedent) so a user sees which is wrong.
    fp = _footage(tmp_path, [_clip("a.mp4")])
    with pytest.raises(ValueError, match="source not found") as exc:
        contact_sheet.resolve_window(fp, str(tmp_path), "a.mp4", 0)
    assert f"footage_root={str(tmp_path)!r}" in str(exc.value)
    assert "source='a.mp4'" in str(exc.value)


def test_cli_strip_with_window_resolves_the_same_range_as_explicit_args(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_strip",
                        lambda src, out, **kw: seen.update({"src": src, **kw})
                        or {"status": "written"})
    (tmp_path / "a.mp4").touch()
    fp = _footage(tmp_path, [_clip("a.mp4", windows=[_win(start=1.0, dur=2.0),
                                                     _win(start=9.0, dur=3.0)])])
    monkeypatch.setattr("sys.argv", ["contact_sheet", "strip", "--footage", fp,
                                     "--footage-root", str(tmp_path),
                                     "--source", "a.mp4", "--window", "1",
                                     "--frames", "8", "--out", str(tmp_path / "s.png")])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen["src"] == str(tmp_path / "a.mp4")
    assert seen["start"] == 9.0 and seen["dur"] == 3.0
    assert seen["frames"] == 8 and seen["fps"] == 30.0


def test_cli_strip_requires_a_range_or_a_window(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["contact_sheet", "strip", "--source", "a.mp4",
                                     "--out", str(tmp_path / "s.png")])
    with pytest.raises(SystemExit):
        contact_sheet.main()
    assert "--start/--dur" in capsys.readouterr().err


def test_cli_strip_footage_window_without_footage_root_fails_loud(tmp_path, monkeypatch, capsys):
    fp = _footage(tmp_path, [_clip("a.mp4", windows=[_win(start=1.0, dur=2.0)])])
    monkeypatch.setattr("sys.argv", ["contact_sheet", "strip", "--footage", fp,
                                     "--source", "a.mp4", "--window", "0",
                                     "--out", str(tmp_path / "s.png")])
    with pytest.raises(SystemExit):
        contact_sheet.main()
    assert "--footage-root" in capsys.readouterr().err


def test_cli_strip_explicit_source_and_range_needs_no_footage_root(tmp_path, monkeypatch):
    # the explicit --source/--start/--dur path must keep working unchanged, with no
    # root at all — it never touches FOOTAGE.json or footage_root.
    seen = {}
    monkeypatch.setattr(contact_sheet, "build_strip",
                        lambda src, out, **kw: seen.update({"src": src, **kw})
                        or {"status": "written"})
    monkeypatch.setattr("sys.argv", ["contact_sheet", "strip", "--source", "a.mp4",
                                     "--start", "1.0", "--dur", "2.0",
                                     "--out", str(tmp_path / "s.png")])
    with pytest.raises(SystemExit) as e:
        contact_sheet.main()
    assert e.value.code == 0
    assert seen["src"] == "a.mp4" and seen["start"] == 1.0 and seen["dur"] == 2.0


# ---- photos (design 2026-10-20 §1) ----

def test_a_photo_cell_is_the_decoded_photo_not_a_video_decode(tmp_path, monkeypatch):
    root = tmp_path / "foot"; root.mkdir()
    Image.new("RGB", (60, 40), (200, 10, 10)).save(root / "IMG_1.png")
    photo = FootageClip(source="IMG_1.png", dur=8.0, res=(60, 40), fps=0.0, kind="photo",
                        windows=[_win()])
    seen = []
    monkeypatch.setattr(contact_sheet.assembly, "frames_rgb",
                        lambda *a: (_ for _ in ()).throw(AssertionError("video decode")))
    monkeypatch.setattr(contact_sheet.sheet, "tile",
                        _stub_tile(lambda cells, kw: seen.extend(cells)))
    contact_sheet.build_sheets(_footage(tmp_path, [photo]), str(root), str(tmp_path / "out"))
    (cell,) = seen
    assert cell.image.shape == (40, 60, 3) and tuple(cell.image[5, 5]) == (200, 10, 10)


def test_sheets_are_never_written_into_the_footage_folder(tmp_path):
    with pytest.raises(ValueError, match="contact_sheet's out_dir"):
        contact_sheet.build_sheets(_footage(tmp_path, [_clip()]), str(tmp_path),
                                   str(tmp_path))


def test_a_strip_of_a_photo_is_refused_with_the_reason(tmp_path):
    photo = FootageClip(source="IMG_1.jpg", dur=8.0, res=(60, 40), fps=0.0, kind="photo",
                        windows=[_win()])
    with pytest.raises(ValueError, match="is a photo"):
        contact_sheet.resolve_window(_footage(tmp_path, [photo]), str(tmp_path),
                                     "IMG_1.jpg", 0)
