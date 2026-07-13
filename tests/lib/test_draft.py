import pytest

from scripts.lib import draft


def test_resolve_font_returns_first_existing_candidate(tmp_path, monkeypatch):
    f = tmp_path / "F.ttf"
    f.write_text("x")
    monkeypatch.setattr(draft, "FONT_CANDIDATES",
                        (str(tmp_path / "missing.ttf"), str(f)))
    assert draft.resolve_font() == str(f)


def test_resolve_font_override_wins(tmp_path):
    f = tmp_path / "over.ttf"
    f.write_text("x")
    assert draft.resolve_font(str(f)) == str(f)


def test_resolve_font_missing_override_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="--font"):
        draft.resolve_font(str(tmp_path / "nope.ttf"))


def test_resolve_font_none_found_fails_loud(monkeypatch):
    monkeypatch.setattr(draft, "FONT_CANDIDATES", ())
    with pytest.raises(ValueError, match="fontfile"):
        draft.resolve_font()


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
