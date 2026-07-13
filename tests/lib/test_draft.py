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
