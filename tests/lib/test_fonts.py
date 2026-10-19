import pytest

from scripts.lib import fonts


def test_none_returns_first_existing_candidate(tmp_path, monkeypatch):
    f = tmp_path / "F.ttf"
    f.write_text("x")
    monkeypatch.setattr(fonts, "FONT_CANDIDATES", (str(tmp_path / "missing.ttf"), str(f)))
    assert fonts.resolve_font() == str(f)
    assert fonts.resolve_font("system") == str(f)
    assert fonts.resolve_font("") == str(f)


def test_none_found_fails_loud(monkeypatch):
    monkeypatch.setattr(fonts, "FONT_CANDIDATES", ())
    with pytest.raises(ValueError, match="fontfile"):
        fonts.resolve_font()


def test_existing_path_wins(tmp_path):
    f = tmp_path / "over.ttf"
    f.write_text("x")
    assert fonts.resolve_font(str(f)) == str(f)


def test_missing_path_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        fonts.resolve_font(str(tmp_path / "nope.ttf"))


def test_known_name_maps_to_installed_cask_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts.Path, "home", staticmethod(lambda: tmp_path))
    lib = tmp_path / "Library" / "Fonts"
    lib.mkdir(parents=True)
    (lib / "Montserrat-Regular.ttf").write_text("x")       # the older static install
    assert fonts.resolve_font("Montserrat") == str(lib / "Montserrat-Regular.ttf")


def test_known_name_not_installed_points_at_the_installer(tmp_path, monkeypatch):
    """The remedy must name a command that still EXISTS. It used to say
    `setup.sh --with-fonts`; that flag was deleted when the curated set became
    baseline (ffmpeg-baseline design 2026-07-20 §8).

    The absence assertion is the load-bearing one. Matching only `bash setup.sh`
    cannot fail — the stale `bash setup.sh --with-fonts` contains it as a
    substring — so that half alone would pin nothing, which is how this test was
    first written and what a mutation check caught.
    """
    monkeypatch.setattr(fonts.Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(ValueError) as e:
        fonts.resolve_font("Oswald")
    assert "bash setup.sh" in str(e.value)
    assert "--with-fonts" not in str(e.value)


def test_unknown_name_fails_loud():
    """Same deleted-flag guard on the OTHER raise — it carried the stale remedy too."""
    with pytest.raises(ValueError) as e:
        fonts.resolve_font("Comic Papyrus")
    assert "known name" in str(e.value)
    assert "--with-fonts" not in str(e.value)


# --- retro 2026-10-16 S13: a title's icons are drawn, never left as empty boxes -------

PIN, CAL = 0x1F4CD, 0x1F5D3


def test_missing_glyphs_names_what_the_font_cannot_draw(tmp_path, make_ttf):
    from scripts.lib import fonts
    _ttf = make_ttf
    base = _ttf(tmp_path / "base.ttf", [ord("A"), ord("B")])
    assert fonts.missing_glyphs(base, "AB A") == []                    # whitespace is free
    assert fonts.missing_glyphs(base, f"{chr(PIN)} AB {chr(PIN)}") == [chr(PIN)]


def test_an_icon_the_icon_font_has_is_merged_into_a_new_font(tmp_path, make_ttf):
    from fontTools.ttLib import TTFont
    from scripts.lib import fonts
    _ttf = make_ttf
    base = _ttf(tmp_path / "base.ttf", [ord("A")])
    icons = _ttf(tmp_path / "icons.ttf", [PIN, CAL])
    out = fonts.cover_glyphs(base, f"{chr(PIN)} A\n{chr(CAL)} A", str(tmp_path / "w"),
                             icon_font=icons)
    assert out != base
    cmap = TTFont(out).getBestCmap()
    assert {PIN, CAL, ord("A")} <= set(cmap)
    assert fonts.missing_glyphs(out, f"{chr(PIN)} A") == []
    # the same request reuses the same file
    assert fonts.cover_glyphs(base, f"{chr(PIN)} A\n{chr(CAL)} A", str(tmp_path / "w"),
                              icon_font=icons) == out


def test_text_the_font_already_draws_keeps_its_font(tmp_path, make_ttf):
    from scripts.lib import fonts
    _ttf = make_ttf
    base = _ttf(tmp_path / "base.ttf", [ord("A")])
    assert fonts.cover_glyphs(base, "A A", str(tmp_path / "w"),
                              icon_font=_ttf(tmp_path / "i.ttf", [PIN])) == base


def test_a_character_no_font_draws_is_refused_by_name(tmp_path, make_ttf):
    from scripts.lib import fonts
    _ttf = make_ttf
    base = _ttf(tmp_path / "base.ttf", [ord("A")])
    icons = _ttf(tmp_path / "icons.ttf", [PIN])
    with pytest.raises(ValueError, match=chr(CAL)):
        fonts.cover_glyphs(base, f"A {chr(CAL)}", str(tmp_path / "w"), icon_font=icons)


def test_the_icon_font_is_a_named_font_the_setup_installs():
    from scripts.lib import fonts
    assert fonts.FONT_NAMES[fonts.ICON_FONT] == ("NotoEmoji[wght].ttf",)


def test_invisible_joiners_and_selectors_are_never_required(tmp_path, make_ttf):
    """🗓 is text-style by default, so emoji pickers insert U+1F5D3 U+FE0F — the second
    run's own calendar. drawtext (HarfBuzz) already draws nothing for a missing
    selector or joiner; demanding a glyph for one refused a title that renders fine."""
    from scripts.lib import fonts
    base = make_ttf(tmp_path / "base.ttf", [ord("A")])
    text = f"A{chr(0xFE0F)}A{chr(0x200D)}{chr(0xFE0E)}"
    assert fonts.missing_glyphs(base, text) == []
    assert fonts.cover_glyphs(base, text, str(tmp_path / "w"),
                              icon_font=make_ttf(tmp_path / "i.ttf", [PIN])) == base


def test_the_merged_icon_sits_at_the_cap_height_on_the_baseline(tmp_path, make_ttf):
    from fontTools.ttLib import TTFont
    from scripts.lib import fonts
    base = make_ttf(tmp_path / "base.ttf", [ord("A")])         # cap height 700
    icons = make_ttf(tmp_path / "icons.ttf", [PIN])            # a 500x700 square
    merged = TTFont(fonts.cover_glyphs(base, chr(PIN), str(tmp_path / "w"), icon_font=icons))
    g = merged["glyf"][merged.getBestCmap()[PIN]]
    assert (g.yMax - g.yMin) == pytest.approx(1.15 * 700, abs=2)
    assert g.yMin == pytest.approx(-0.06 * 700, abs=2)


def test_two_icon_sets_never_share_one_merged_font(tmp_path, make_ttf):
    from scripts.lib import fonts
    base = make_ttf(tmp_path / "base.ttf", [ord("A")])
    icons = make_ttf(tmp_path / "icons.ttf", [PIN, CAL])
    a = fonts.cover_glyphs(base, chr(PIN), str(tmp_path / "w"), icon_font=icons)
    b = fonts.cover_glyphs(base, chr(CAL), str(tmp_path / "w"), icon_font=icons)
    assert a != b and fonts.missing_glyphs(b, chr(CAL)) == []


def test_a_variable_title_font_is_pinned_at_its_default_instance(tmp_path, make_ttf):
    from fontTools.ttLib import TTFont
    from scripts.lib import fonts
    base = make_ttf(tmp_path / "var.ttf", [ord("A")], variable=True)
    assert "fvar" in TTFont(base)
    merged = TTFont(fonts.cover_glyphs(base, f"A{chr(PIN)}", str(tmp_path / "w"),
                                       icon_font=make_ttf(tmp_path / "i.ttf", [PIN])))
    assert "fvar" not in merged and "gvar" not in merged


def test_a_cff_title_font_is_refused_with_the_remedy(tmp_path, make_ttf):
    from scripts.lib import fonts
    base = make_ttf(tmp_path / "cff.otf", [ord("A")], cff=True)
    with pytest.raises(ValueError, match=r"\.ttf"):
        fonts.cover_glyphs(base, f"A{chr(PIN)}", str(tmp_path / "w"),
                           icon_font=make_ttf(tmp_path / "i.ttf", [PIN]))


def test_a_composite_icon_glyph_is_drawn_decomposed(tmp_path, make_ttf):
    from fontTools.ttLib import TTFont
    from scripts.lib import fonts
    base = make_ttf(tmp_path / "base.ttf", [ord("A")])
    icons = make_ttf(tmp_path / "icons.ttf", [PIN], composite=True)
    merged = TTFont(fonts.cover_glyphs(base, chr(PIN), str(tmp_path / "w"), icon_font=icons))
    g = merged["glyf"][merged.getBestCmap()[PIN]]
    assert not g.isComposite() and g.numberOfContours > 0


# --- S19 (found by the S13 review): the named fonts resolve to what the casks install --

def test_a_name_resolves_to_the_variable_font_the_cask_installs(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts.Path, "home", staticmethod(lambda: tmp_path))
    lib = tmp_path / "Library" / "Fonts"
    lib.mkdir(parents=True)
    (lib / "Montserrat[wght].ttf").write_text("x")
    assert fonts.resolve_font("Montserrat") == str(lib / "Montserrat[wght].ttf")
    (lib / "Oswald-Regular.ttf").write_text("x")                 # an older static install
    assert fonts.resolve_font("Oswald") == str(lib / "Oswald-Regular.ttf")
    (lib / "Oswald[wght].ttf").write_text("x")                   # both: the cask's wins
    assert fonts.resolve_font("Oswald") == str(lib / "Oswald[wght].ttf")


def test_a_variable_font_is_drawn_at_regular_weight_not_its_default(tmp_path, make_ttf):
    """drawtext renders a variable font at its DEFAULT instance — weight 100 (Thin) for
    Montserrat[wght]. A title is pinned at TITLE_WEIGHT instead."""
    from fontTools.ttLib import TTFont
    var = make_ttf(tmp_path / "var.ttf", [ord("A")], variable=True, default_wght=100)
    pinned = fonts.static_instance(var, str(tmp_path / "w"))
    f = TTFont(pinned)
    assert "fvar" not in f and f["OS/2"].usWeightClass == fonts.TITLE_WEIGHT == 400
    static = make_ttf(tmp_path / "s.ttf", [ord("A")])
    assert fonts.static_instance(static, str(tmp_path / "w")) == static


def test_a_pinned_copy_is_rebuilt_when_the_font_changes_in_place(tmp_path, make_ttf):
    import os
    var = make_ttf(tmp_path / "var.ttf", [ord("A")], variable=True, default_wght=100)
    a = fonts.static_instance(var, str(tmp_path / "w"))
    make_ttf(tmp_path / "var.ttf", [ord("A"), ord("B")], variable=True, default_wght=100)
    os.utime(var, ns=(1, 1))                       # a different mtime, whatever the clock says
    b = fonts.static_instance(var, str(tmp_path / "w"))
    assert a != b and fonts.missing_glyphs(b, "B") == []
