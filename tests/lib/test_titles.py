import json

import pytest

from scripts.lib.spec import Spec
from scripts.lib.titles import POSITIONS, STYLES, Title, Titles, build_filterchain
from scripts.titles import build_titles, write_titles


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
    (dict(text="x", start=float("inf"), dur=1.0), "start"),
    (dict(text="x", start=0.0, dur=float("nan")), "dur"),
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


def _spec(**kw):
    base = dict(canvas=(1080, 1920), length_s=30.0, mood="calm", hook="Watch this")
    base.update(kw)
    return Spec(**base)


def test_build_titles_hook_opens():
    ts = build_titles(_spec(), total_s=30.0)
    assert len(ts.items) == 1              # hook only — _spec() has no text/ending
    assert ts.items[0].text == "Watch this"
    assert ts.items[0].start == 0.0 and ts.items[0].pos == "top"
    assert ts.items[0].font == "system"


def test_build_titles_ending_closes_in_last_3s():
    ts = build_titles(_spec(ending="Follow"), total_s=30.0)
    end = ts.items[-1]
    assert end.text == "Follow" and end.start == 27.0 and end.pos == "center"


def test_build_titles_text_becomes_mid_caption():
    ts = build_titles(_spec(text="mid line"), total_s=30.0)
    assert any(t.text == "mid line" for t in ts.items)


def test_build_titles_rejects_bad_total():
    with pytest.raises(ValueError, match="total_s"):
        build_titles(_spec(), total_s=0.0)


def test_build_titles_rejects_nonfinite_total():
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ValueError, match="total_s"):
            build_titles(_spec(), total_s=bad)


def test_write_titles_emits_pair(tmp_path):
    res = write_titles(build_titles(_spec(ending="Follow"), 30.0), str(tmp_path))
    assert res["status"] == "written" and res["count"] == 2
    assert (tmp_path / "TITLES.json").exists() and (tmp_path / "TITLES.md").exists()
    assert Titles.from_json(tmp_path / "TITLES.json").items[-1].text == "Follow"


def test_titles_margins_are_sourced_from_the_safe_zone_table():
    # genuine fail-first: titles._Z does not exist until the rewire, so this raises
    # AttributeError before Step 3 — value-based checks would coincide (generic == 0.08/0.12).
    from scripts.lib import titles, safezones
    assert titles._Z is safezones.default_zone()
    assert titles._Y_EXPR["top"] == f"h*{safezones.default_zone().top}"
    assert titles._Y_EXPR["bottom"] == f"h-th-h*{safezones.default_zone().bottom}"


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_titles_from_dict_rejects_a_non_object_top_level(d, name):
    # deliver.py:70 reads TITLES.json with no except around from_json.
    with pytest.raises(ValueError) as ei:
        Titles.from_dict(d)
    msg = str(ei.value)
    assert "expected a TITLES.json object" in msg
    assert f"got {name}" in msg
    assert "re-run titles" in msg
    assert "has no attribute" not in msg


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_titles_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "TITLES.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run titles"):
        Titles.from_json(p)


def test_title_animation_defaults_and_roundtrip():
    t = Title(text="Hi", start=0.0, dur=2.0)
    assert (t.fade, t.reveal, t.reveal_step) == (0.0, "none", 0.35)
    assert (t.color, t.scale, t.line_spacing) == ("white", 1.0, 1.15)
    assert Title.from_dict(t.to_dict()) == t          # 12-key round-trip


@pytest.mark.parametrize("kw, msg", [
    (dict(text="x", start=0.0, dur=1.0, fade=0.6), "never reach full opacity"),
    (dict(text="x", start=0.0, dur=1.0, fade=-0.1), "fade"),
    (dict(text="x", start=0.0, dur=1.0, fade=True), "fade"),
    (dict(text="x", start=0.0, dur=1.0, color=" "), "color"),
    (dict(text="x", start=0.0, dur=1.0, scale=0.0), "scale"),
    (dict(text="x", start=0.0, dur=1.0, scale=6.0), "scale"),
    (dict(text="x", start=0.0, dur=1.0, scale=True), "scale"),
    (dict(text="x", start=0.0, dur=1.0, line_spacing=0.4), "line_spacing"),
    (dict(text="x", start=0.0, dur=1.0, line_spacing=3.1), "line_spacing"),
    (dict(text="x", start=0.0, dur=1.0, reveal="fly"), "reveal"),
    (dict(text="x", start=0.0, dur=1.0, reveal_step=0.0), "reveal_step"),
    (dict(text="x", start=0.0, dur=1.0, reveal_step=True), "reveal_step"),
    (dict(text="x", start=0.0, dur=1.0, line_spacing=True), "line_spacing"),
    (dict(text="a b c d", start=0.0, dur=1.0, reveal="word", reveal_step=0.5),
     "would still be arriving"),
])
def test_title_animation_validation_fails_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        Title(**kw)


def test_title_reveal_that_fits_is_accepted():
    # 3 words, step 0.4 → need (3-1)*0.4 = 0.8s <= dur 2.0s
    Title(text="a b c", start=0.0, dur=2.0, reveal="word", reveal_step=0.4)


def test_steps_word_splits_on_whitespace():
    from scripts.lib.titles import _steps
    assert _steps(Title("salt sun you", 0.0, 2.0, reveal="word")) == ["salt", "sun", "you"]


def test_steps_stair_splits_on_newlines_and_strips():
    from scripts.lib.titles import _steps
    t = Title("salt,\nsun\n& you", 0.0, 3.0, reveal="stair", reveal_step=0.5)
    assert _steps(t) == ["salt,", "sun", "& you"]


def test_title_animation_roundtrip_carries_non_default_values():
    # every new key must survive to_dict/from_dict at a NON-default value — a
    # hardcoded default in to_dict (e.g. "fade": 0.0) would slip past a defaults-only test.
    t = Title(text="a b c", start=0.0, dur=4.0, fade=0.5, reveal="word",
              reveal_step=0.6, color="0xff0000", scale=2.0, line_spacing=1.5)
    d = t.to_dict()
    assert d["fade"] == 0.5 and d["reveal"] == "word" and d["reveal_step"] == 0.6
    assert d["color"] == "0xff0000" and d["scale"] == 2.0 and d["line_spacing"] == 1.5
    assert Title.from_dict(d) == t


@pytest.mark.parametrize("kw", [
    dict(text="hi", start=0.0, dur=1.0, fade=0.5),                          # 2*fade == dur (inclusive)
    dict(text="a b c", start=0.0, dur=1.0, reveal="word", reveal_step=0.5), # need == dur (inclusive)
    dict(text="hi", start=0.0, dur=1.0, scale=5.0),                         # scale upper bound (inclusive)
    dict(text="hi", start=0.0, dur=1.0, line_spacing=0.5),                  # line_spacing lower bound
    dict(text="hi", start=0.0, dur=1.0, line_spacing=3.0),                  # line_spacing upper bound
])
def test_title_boundary_values_are_accepted(kw):
    Title(**kw)      # inclusive bounds — must NOT raise


def _stub_measure(font, text):
    # width proportional to length; a flat ink-box top (baseline shift = 0)
    return (float(len(text)) * 10.0, 0.0)


def test_layers_none_is_one_centered_layer():
    from scripts.lib.titles import _layers
    t = Title("whole line", 0.0, 2.0)
    assert _layers(t, "/f.ttf", _stub_measure) == [("whole line", 0.0, "(w-tw)/2", "")]


def test_layers_word_places_each_word_at_its_final_x():
    from scripts.lib.titles import _layers
    t = Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _stub_measure)
    assert [ly[0] for ly in layers] == ["a", "bb"]          # one layer per word
    assert [ly[1] for ly in layers] == [0.0, 0.5]           # appears at start + j*step
    # x is the FULL line centred + this word's measured prefix — never (w-tw)/2.
    # total="a bb"→40px, k=1/(18*100); prefix word0=0, word1="a "→20px.
    assert layers[0][2] == "(w-0.022222*h)/2+0.000000*h"
    assert layers[1][2] == "(w-0.022222*h)/2+0.011111*h"
    assert all("*h" in ly[2] for ly in layers)              # resolution-independent (inv 5)


def test_layers_stair_drops_a_line_per_step():
    from scripts.lib.titles import _layers
    t = Title("salt,\nsun\n& you", 0.0, 3.0, reveal="stair", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _stub_measure)
    assert [ly[0] for ly in layers] == ["salt,", "sun", "& you"]   # newline split
    # per-step drop = j * line_spacing(1.15) * scale(1.0) / 18 = 0.063889 * j
    assert [ly[3] for ly in layers] == ["+0.000000*h", "+0.063889*h", "+0.127778*h"]


def test_layers_baseline_shift_uses_ink_box_top():
    from scripts.lib.titles import _layers

    def _measure_with_tops(font, text):
        tops = {"a bb": 0.0, "a": 5.0, "bb": 0.0, "a ": 20.0}
        return (float(len(text)) * 10.0, tops.get(text, 0.0))
    t = Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _measure_with_tops)
    # word "a" sits 5px above the line's top → shifted DOWN by (5-0)*k = +0.002778*h
    assert layers[0][3] == "+0.002778*h"
    assert layers[1][3] == "+0.000000*h"
