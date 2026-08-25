import pytest

from scripts import draft as draft_cli
from scripts.lib import draft


def test_label_text_without_notes_is_header_only():
    assert draft.label_text(0, "wide", "") == "#0 wide"
    assert draft.label_text(2, "close", "   ") == "#2 close"


def test_label_text_with_notes_adds_second_line():
    assert draft.label_text(1, "medium", "track surfer") == "#1 medium\ntrack surfer"


def test_segment_filter_carries_fit_and_label_pieces():
    vf = draft.segment_filter((1080, 1920), 30.0, "/f.ttf", "/tmp/l.txt")
    for piece in ("scale=1080:1920", "force_divisible_by=2", "pad=1080:1920",
                  "fps=30.0", "format=yuv420p", "drawtext=",
                  "fontfile='/f.ttf'", "textfile='/tmp/l.txt'"):
        assert piece in vf, piece


def test_build_draft_refuses_an_out_beside_the_footage(tmp_path):
    """The exact shape that fired: <footage>/draft.mp4 is an .mp4 in the folder
    intake scans, so the next scan takes the QA preview as source material."""
    root = tmp_path / "footage"
    root.mkdir()
    with pytest.raises(ValueError, match="footage folder itself"):
        draft_cli.build_draft(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                              str(root), str(tmp_path / "work"), str(root / "draft.mp4"))


def test_build_draft_accepts_an_out_inside_the_run_dir(tmp_path):
    """Must NOT raise the run-dir refusal for <footage>/montage/draft.mp4. It still
    fails on the missing EDL — a different error, which is the point."""
    root = tmp_path / "footage"
    (root / "montage").mkdir(parents=True)
    with pytest.raises(Exception) as e:
        draft_cli.build_draft(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                              str(root), str(tmp_path / "work"),
                              str(root / "montage" / "draft.mp4"))
    assert "footage folder itself" not in str(e.value)
