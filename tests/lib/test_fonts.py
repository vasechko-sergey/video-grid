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
    (lib / "Montserrat-Regular.ttf").write_text("x")
    assert fonts.resolve_font("Montserrat") == str(lib / "Montserrat-Regular.ttf")


def test_known_name_not_installed_points_at_with_fonts(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts.Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(ValueError, match="--with-fonts"):
        fonts.resolve_font("Oswald")


def test_unknown_name_fails_loud():
    with pytest.raises(ValueError, match="known name"):
        fonts.resolve_font("Comic Papyrus")
