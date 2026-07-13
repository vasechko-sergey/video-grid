import json

import pytest

from scripts.lib.titles import POSITIONS, STYLES, Title, Titles


def test_title_defaults_and_roundtrip():
    t = Title(text="Hi", start=0.0, dur=2.0)
    assert (t.font, t.pos, t.style) == ("system", "bottom", "bold-box")
    assert Title.from_dict(t.to_dict()) == t


@pytest.mark.parametrize("kw, msg", [
    (dict(text=" ", start=0.0, dur=1.0), "text"),
    (dict(text="x", start=-1.0, dur=1.0), "start"),
    (dict(text="x", start=0.0, dur=0.0), "dur"),
    (dict(text="x", start=0.0, dur=1.0, font=" "), "font"),
    (dict(text="x", start=0.0, dur=1.0, pos="side"), "pos"),
    (dict(text="x", start=0.0, dur=1.0, style="neon"), "style"),
    (dict(text="x", start=True, dur=1.0), "start"),
    (dict(text="x", start=0.0, dur=True), "dur"),
])
def test_title_validation_fails_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        Title(**kw)


def test_title_from_dict_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown field"):
        Title.from_dict({"text": "Hi", "start": 0.0, "dur": 1.0, "postion": "top"})


def test_titles_roundtrip_and_markdown():
    ts = Titles(items=(Title("Hook", 0.0, 2.0, pos="top"),
                       Title("End", 26.0, 3.0, pos="center", style="plain")))
    assert Titles.from_dict(ts.to_dict()) == ts
    md = ts.to_markdown()
    assert "| 0 | Hook | 0.0→2.0 | top | bold-box | system |" in md
    assert "End" in md


def test_titles_empty_is_legal_and_markdown_shows_none():
    assert Titles().items == ()
    assert "(none)" in Titles().to_markdown()


def test_titles_rejects_non_title_items():
    with pytest.raises(ValueError, match="Title"):
        Titles(items=({"text": "x"},))


def test_titles_from_dict_rejects_non_dict_item():
    with pytest.raises(ValueError, match=r"items\[1\]"):
        Titles.from_dict({"items": [{"text": "x", "start": 0.0, "dur": 1.0}, "oops"]})


def test_titles_items_list_coerced_to_tuple():
    ts = Titles(items=[Title("a", 0.0, 1.0)])
    assert ts.items == (Title("a", 0.0, 1.0),)


def test_titles_from_json_roundtrip(tmp_path):
    ts = Titles(items=(Title("Hook", 0.0, 2.0),))
    p = tmp_path / "TITLES.json"
    ts.write(p)
    assert Titles.from_json(p) == ts


def test_positions_and_styles_frozen():
    assert POSITIONS == ("top", "center", "bottom")
    assert STYLES == ("bold-box", "outline", "plain")


from scripts.lib.titles import build_filterchain


def _fake_resolve(name):
    return "/f.ttf"


def test_build_filterchain_empty_is_blank(tmp_path):
    assert build_filterchain(Titles(), str(tmp_path)) == ""


def test_build_filterchain_one_drawtext_per_title_with_windows(tmp_path):
    ts = Titles(items=(Title("Hook", 0.0, 2.0, pos="top", style="bold-box"),
                       Title("End", 26.0, 3.0, pos="center", style="plain")))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert vf.count("drawtext=") == 2
    assert "enable='between(t,0.0,2.0)'" in vf
    assert "enable='between(t,26.0,29.0)'" in vf
    assert "fontfile='/f.ttf'" in vf
    # per-title textfiles written, referenced
    assert (tmp_path / "title_0.txt").read_text() == "Hook"
    assert (tmp_path / "title_1.txt").read_text() == "End"
    assert "textfile='" in vf


def test_build_filterchain_positions_and_styles(tmp_path):
    ts = Titles(items=(Title("a", 0.0, 1.0, pos="top", style="bold-box"),
                       Title("b", 1.0, 1.0, pos="center", style="outline"),
                       Title("c", 2.0, 1.0, pos="bottom", style="plain")))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "y=h*0.08" in vf                     # top
    assert "y=(h-th)/2" in vf                   # center
    assert "y=h-th-h*0.12" in vf                # bottom
    assert "box=1:boxcolor=black@0.5:boxborderw=16" in vf   # bold-box
    assert "borderw=4:bordercolor=black" in vf              # outline
    assert "x=(w-tw)/2" in vf and "fontsize=h/18" in vf
