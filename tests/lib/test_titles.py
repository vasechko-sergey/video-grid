import json

import pytest

from scripts.lib import safezones, titles as titles_mod
from scripts.lib.spec import Spec
from scripts.lib.titles import POSITIONS, STYLES, Title, Titles, build_filterchain
from scripts.titles import build_titles, check_titles, write_titles


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
    assert STYLES == ("bold-box", "outline", "outline-bold", "plain")


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
    assert "x=(w-tw)/2" in vf and "fontsize=h*0.055556" in vf   # h/18, respelled


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


def test_y_exprs_generic_matches_the_default_zone():
    from scripts.lib import titles, safezones
    z = safezones.SAFE_ZONES["generic"]
    assert titles.y_exprs("") == {"top": f"h*{z.top}", "center": "(h-th)/2",
                                  "bottom": f"h-th-h*{z.bottom}"}
    assert not hasattr(titles, "_Y_EXPR")      # the frozen constant is gone


def test_y_exprs_platform_zone_pushes_the_bottom_title_up():
    from scripts.lib import titles
    # reels reserves 0.16 of the bottom vs the generic 0.12 → the bottom y moves up
    assert titles.y_exprs("reel")["bottom"] == "h-th-h*0.16"
    assert titles.y_exprs("reel")["bottom"] != titles.y_exprs("")["bottom"]
    assert titles.y_exprs("reel")["top"] == titles.y_exprs("")["top"]   # top zone equal


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


def test_layers_none_carries_a_nonzero_start():
    # reveal="none" must carry t.start, not a hardcoded 0.0
    from scripts.lib.titles import _layers
    t = Title("whole", 5.0, 2.0)
    assert _layers(t, "/f.ttf", _stub_measure) == [("whole", 5.0, "(w-tw)/2", "")]


def test_layers_stair_adds_the_per_line_drop_to_the_baseline_correction():
    # stair drop = baseline-correction + per-line drop; a stub with a non-flat top on
    # one step proves the per-line term ADDS to (does not overwrite) the correction.
    from scripts.lib.titles import _layers

    def _tops(font, text):
        return (float(len(text)) * 10.0, 5.0 if text == "bb" else 0.0)
    t = Title("AA\nbb", 0.0, 3.0, reveal="stair", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _tops)
    assert layers[0][3] == "+0.000000*h"
    # baseline (5-0)*k where k=1/(18*100)=0.005556e-1 → 0.002778, PLUS per-line
    # 1*1.15*1.0/18 = 0.063889 → 0.066667
    assert layers[1][3] == "+0.066667*h"


def test_layers_word_emits_a_negative_drop_when_a_word_rises_above_the_line():
    # a word whose ink-top sits ABOVE the joined line's top → negative drop → "-...*h"
    from scripts.lib.titles import _layers

    def _tops(font, text):
        return (float(len(text)) * 10.0, 0.0 if text == "bb" else 8.0)
    t = Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _tops)
    # top_full("a bb")=8; word "bb" top=0 → drop=(0-8)*k=-0.004444 → negative branch
    assert layers[0][3] == "+0.000000*h"
    assert layers[1][3] == "-0.004444*h"


def test_build_filterchain_fade_zero_emits_no_alpha(tmp_path):
    ts = Titles(items=(Title("Hook", 0.0, 2.0),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "alpha=" not in vf                        # the historical fast path


def test_build_filterchain_fade_emits_a_trapezoid_alpha(tmp_path):
    ts = Titles(items=(Title("Hook", 0.0, 2.0, fade=0.5),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "alpha='max(0,min(1,min((t-0.0)/0.5,(2.0-t)/0.5)))'" in vf


def test_build_filterchain_platform_shifts_the_bottom_title(tmp_path):
    ts = Titles(items=(Title("hi", 0.0, 2.0, pos="bottom"),))
    generic = build_filterchain(ts, str(tmp_path / "g"), resolve=_fake_resolve)
    reel = build_filterchain(ts, str(tmp_path / "r"), resolve=_fake_resolve, platform="reel")
    assert "y=h-th-h*0.12" in generic
    assert "y=h-th-h*0.16" in reel


def test_build_filterchain_word_reveal_lays_each_word_at_final_x(tmp_path):
    ts = Titles(items=(Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve, measure=_stub_measure)
    assert vf.count("drawtext=") == 2
    assert "enable='between(t,0.0,2.0)'" in vf and "enable='between(t,0.5,2.0)'" in vf
    assert "x=(w-tw)/2" not in vf                    # never naively centred per word
    assert "+0.000000*h" in vf and "+0.011111*h" in vf   # word0 / word1 baked prefixes
    assert (tmp_path / "title_0_0.txt").read_text() == "a"
    assert (tmp_path / "title_0_1.txt").read_text() == "bb"


def test_build_filterchain_scale_and_colour(tmp_path):
    ts = Titles(items=(Title("hi", 0.0, 2.0, scale=2.0, color="0xffcc00"),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "fontsize=h*0.111111" in vf and "fontcolor=0xffcc00" in vf


def test_build_filterchain_fade_on_a_word_reveal_uses_each_layers_own_appears(tmp_path):
    # a late-revealed word fades in on ITS OWN entrance (appears); all layers fade OUT
    # together at the shared end. Pins the per-layer appears → alpha in-ramp wiring.
    ts = Titles(items=(Title("a bb", 0.0, 3.0, fade=0.5, reveal="word", reveal_step=0.5),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve, measure=_stub_measure)
    assert vf.count("drawtext=") == 2
    assert "min((t-0.0)/0.5,(3.0-t)/0.5)" in vf      # word0 in-ramp from its appears=0.0
    assert "min((t-0.5)/0.5,(3.0-t)/0.5)" in vf      # word1 in-ramp from its appears=0.5


def test_build_filterchain_plain_style_emits_no_empty_fragment(tmp_path):
    # style="plain" contributes no fragment, so the chain must not contain a doubled colon
    ts = Titles(items=(Title("hi", 0.0, 2.0, style="plain"),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "::" not in vf


def test_ink_extent_bottom_sits_on_the_zone_edge():
    # a single-line bottom title's ink box ends EXACTLY at the safe zone's inner
    # edge — that is what y_exprs' `h-th-h*z.bottom` means, and the extent must
    # agree or the overflow check refuses every ordinary title.
    t = Title("salt sun and you", 0.0, 3.0, pos="bottom")
    top, bottom = titles_mod.ink_extent(t, "reels")
    assert bottom == pytest.approx(1.0 - 0.16)
    assert top == pytest.approx(1.0 - 0.16 - 1.0 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_top_and_center():
    top_t = Title("hi", 0.0, 1.0, pos="top")
    assert titles_mod.ink_extent(top_t, "reels")[0] == pytest.approx(0.08)
    mid = Title("hi", 0.0, 1.0, pos="center")
    lo, hi = titles_mod.ink_extent(mid, "reels")
    assert (lo + hi) / 2 == pytest.approx(0.5)
    assert hi - lo == pytest.approx(1.0 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_scales_with_the_titles_own_scale():
    small = Title("hi", 0.0, 1.0, pos="center", scale=0.5)
    lo, hi = titles_mod.ink_extent(small, "reels")
    assert hi - lo == pytest.approx(0.5 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_adds_the_staircases_drop():
    # measured 2026-08-19: four steps at the default line_spacing drop the last
    # one 3*1.15/18 of the frame below the base box (design §5).
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, reveal="stair", reveal_step=0.4)
    base_bottom = 1.0 - 0.16
    assert titles_mod.ink_extent(t, "reels")[1] == pytest.approx(
        base_bottom + 3 * 1.15 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_word_reveal_stays_on_one_line():
    # a word reveal lays every step at the SAME y — only a stair drops lines, so
    # a word reveal's extent must equal the plain title's.
    plain = Title("salt sun and you", 0.0, 3.0, pos="bottom")
    word = Title("salt sun and you", 0.0, 3.0, pos="bottom", reveal="word",
                 reveal_step=0.3)
    assert titles_mod.ink_extent(word, "reels") == titles_mod.ink_extent(plain, "reels")


def test_ink_extent_unknown_platform_takes_the_generic_zone():
    t = Title("hi", 0.0, 1.0, pos="bottom")
    assert titles_mod.ink_extent(t, "nope") == titles_mod.ink_extent(t, "")


def test_zone_overflow_passes_an_ordinary_title_at_every_position():
    # the ordinary bottom case sits EXACTLY on the zone edge — an off-by-an-epsilon
    # comparison here would refuse every title this repo authors.
    for pos in POSITIONS:
        assert titles_mod.zone_overflow(Title("hi", 0.0, 1.0, pos=pos), "reels") == ""


def test_zone_overflow_names_a_staircase_that_leaves_the_zone():
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="bottom", reveal="stair",
              reveal_step=0.4)
    why = titles_mod.zone_overflow(t, "reels")
    assert "below" in why and "reels" in why
    assert "0.16" in why                      # the margin it broke, quoted


def test_zone_overflow_a_top_staircase_fits():
    # the same four steps at the TOP have the whole frame to fall into.
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="top", reveal="stair",
              reveal_step=0.4)
    assert titles_mod.zone_overflow(t, "reels") == ""


def test_zone_overflow_a_tall_centred_staircase_leaves_the_bottom():
    assert titles_mod.zone_overflow(Title("hi", 0.0, 1.0, pos="center", scale=5.0),
                                    "") == ""          # 5/18 of h still fits centred
    tall = Title("a\nb\nc\nd\ne", 0.0, 5.0, pos="center", reveal="stair",
                 reveal_step=0.5, scale=3.0)
    assert "below" in titles_mod.zone_overflow(tall, "")


def test_no_title_can_rise_above_a_zones_top_margin():
    """Why zone_overflow guards only the BOTTOM. Scanned over every position x
    platform x legal scale, the closest the ink's top ever comes to the top margin
    is exactly 0 — `pos="top"` sits ON it by construction, `center` is pushed down
    by half a font size, `bottom` by a whole one, and a stair only ever moves the
    BOTTOM. A top guard would be a branch nothing can reach, which is the same dead
    code this slice deletes elsewhere. If a future position or a wider scale range
    makes it reachable, this reddens first."""
    worst = 1.0
    for pos in POSITIONS:
        for key, z in safezones.SAFE_ZONES.items():
            for scale in (0.001, 0.5, 1.0, 3.0, 5.0):
                t = Title("hi", 0.0, 1.0, pos=pos, scale=scale)
                worst = min(worst, titles_mod.ink_extent(t, key)[0] - z.top)
    assert worst == pytest.approx(0.0) and worst >= -titles_mod.ZONE_EPS


def test_build_filterchain_refuses_a_title_that_leaves_the_zone(tmp_path):
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="bottom", reveal="stair",
              reveal_step=0.4)
    with pytest.raises(ValueError, match="leaves the reels safe zone"):
        build_filterchain(Titles(items=(t,)), str(tmp_path), resolve=_fake_resolve,
                          platform="reels")


def test_build_filterchain_still_builds_the_ordinary_titles(tmp_path):
    # the anti-regression pin for the refusal: everything that used to build must
    # still build, at every position.
    ts = Titles(items=tuple(Title("hi", 0.0, 1.0, pos=p) for p in POSITIONS))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve, platform="reels")
    assert vf.count("drawtext=") == len(POSITIONS)


def test_check_titles_passes_a_clean_file(tmp_path):
    ts = Titles(items=(Title("hi", 0.0, 1.0, pos="bottom"),))
    out = check_titles(ts, "reels")
    assert out == {"status": "ok", "count": 1, "platform": "reels"}


def test_check_titles_refuses_a_zone_overflow(tmp_path):
    # the case the chokepoint would catch at DELIVER, after every episode is
    # rendered and the master assembled. Here it costs nothing.
    ts = Titles(items=(Title("hi", 0.0, 1.0),
                       Title("salt\nsun\nand\nyou", 2.0, 4.0, pos="bottom",
                             reveal="stair", reveal_step=0.4)))
    with pytest.raises(ValueError, match="item 1"):
        check_titles(ts, "reels")


def test_check_titles_is_the_same_verdict_build_filterchain_would_give(tmp_path):
    # one predicate, two callers — a drift between them would make the preflight
    # useless (passes here, refuses at deliver) or worse than useless (the reverse).
    stair = Titles(items=(Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="bottom",
                                reveal="stair", reveal_step=0.4),))
    for platform in ("", "reels", "tiktok"):
        refused_here = refused_there = False
        try:
            check_titles(stair, platform)
        except ValueError:
            refused_here = True
        try:
            build_filterchain(stair, str(tmp_path / platform), resolve=_fake_resolve,
                              platform=platform)
        except ValueError:
            refused_there = True
        assert refused_here == refused_there
