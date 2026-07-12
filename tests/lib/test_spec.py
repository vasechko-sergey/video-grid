import pytest

from scripts.lib.spec import MUSIC_MODES, STYLE_LEANS, Spec

GOOD = dict(canvas=(9, 16), length_s=30.0, mood="energetic", hook="jump-cut open")


def test_spec_accepts_good():
    s = Spec(**GOOD)
    assert s.canvas == (9, 16) and s.reel_count == 1 and s.music_mode == "free"
    assert s.style_lean == "balanced" and s.music == "auto" and s.cast == ()


def test_spec_rejects_bad_canvas():
    with pytest.raises(ValueError, match="canvas"):
        Spec(**{**GOOD, "canvas": (9,)})


def test_spec_rejects_nonpositive_length():
    with pytest.raises(ValueError, match="length_s"):
        Spec(**{**GOOD, "length_s": 0})


def test_spec_rejects_bool_length():
    with pytest.raises(ValueError, match="length_s"):
        Spec(**{**GOOD, "length_s": True})


def test_spec_rejects_empty_mood():
    with pytest.raises(ValueError, match="mood"):
        Spec(**{**GOOD, "mood": "  "})


def test_spec_rejects_empty_hook():
    with pytest.raises(ValueError, match="hook"):
        Spec(**{**GOOD, "hook": ""})


def test_spec_rejects_reel_count_below_one():
    with pytest.raises(ValueError, match="reel_count"):
        Spec(**{**GOOD, "reel_count": 0})


def test_spec_rejects_empty_music():
    with pytest.raises(ValueError, match="music"):
        Spec(**{**GOOD, "music": ""})


def test_spec_rejects_bad_music_mode():
    with pytest.raises(ValueError, match="music_mode"):
        Spec(**{**GOOD, "music_mode": "pirate"})


def test_spec_rejects_bad_style_lean():
    with pytest.raises(ValueError, match="style_lean"):
        Spec(**{**GOOD, "style_lean": "edgy"})


def test_spec_rejects_nonstr_cast_entry():
    with pytest.raises(ValueError, match="cast"):
        Spec(**{**GOOD, "cast": ["Anna", 7]})


def test_spec_normalises_canvas_and_cast_to_tuple():
    s = Spec(**{**GOOD, "canvas": [9, 16], "cast": ["Anna", "Ben"]})
    assert s.canvas == (9, 16) and s.cast == ("Anna", "Ben")


def test_spec_roundtrip_to_from_dict():
    s = Spec(**{**GOOD, "cast": ["Anna"], "platform": "tiktok", "notes": "n"})
    assert Spec.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_spec_from_dict_missing_required_raises_clean():
    with pytest.raises(ValueError, match="mood"):
        Spec.from_dict({"canvas": [9, 16], "length_s": 30, "hook": "x"})


def test_spec_from_json_corrupt_raises(tmp_path):
    p = tmp_path / "SPEC.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="corrupt"):
        Spec.from_json(p)


def test_spec_write_then_from_json(tmp_path):
    s = Spec(**GOOD)
    p = tmp_path / "SPEC.json"
    s.write(p)
    assert Spec.from_json(p).to_dict() == s.to_dict()


def test_vocab_constants_are_the_allowed_sets():
    assert MUSIC_MODES == ("local", "free", "any")
    assert STYLE_LEANS == ("classic", "balanced", "trend")


def test_spec_from_dict_rejects_noniterable_cast():
    with pytest.raises(ValueError, match="cast"):
        Spec.from_dict({**GOOD, "cast": 42})


def test_spec_from_dict_rejects_string_cast():
    # a bare string is iterable — tuple("Anna") would splat to ('A','n','n','a');
    # from_dict must reject it cleanly, not silently splat
    with pytest.raises(ValueError, match="cast"):
        Spec.from_dict({**GOOD, "cast": "Anna"})


def test_to_markdown_heading_and_gate_fields():
    s = Spec(**{**GOOD, "reel_count": 2, "platform": "tiktok", "cast": ["Anna"]})
    md = s.to_markdown()
    assert md.startswith("# Reel brief — 2 reels, 30s, 9:16")
    assert "**Mood:** energetic" in md
    assert "**Hook:** jump-cut open" in md
    assert "**Music:** auto (mode: free)" in md
    assert "**Cast:** Anna" in md


def test_to_markdown_singular_reel_and_empty_frees_dash():
    md = Spec(**GOOD).to_markdown()
    assert md.startswith("# Reel brief — 1 reel, 30s, 9:16")
    assert "**Platform:** –" in md
    assert "**Cast:** –" in md
    assert "**Text:** –" in md
    assert "**Ending:** –" in md
