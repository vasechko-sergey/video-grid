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


def test_reel_count_above_one_is_refused_with_the_remedy():
    with pytest.raises(ValueError, match="one reel at a time"):
        Spec(**{**GOOD, "reel_count": 3})


def test_reel_count_one_is_the_supported_value():
    assert Spec(**{**GOOD, "reel_count": 1}).reel_count == 1


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
    # reel_count > 1 is refused at construction (see test_reel_count_above_one_is_refused_...);
    # this test's job is the heading + populated optional fields, not reel_count itself.
    s = Spec(**{**GOOD, "platform": "tiktok", "cast": ["Anna"]})
    md = s.to_markdown()
    assert md.startswith("# Reel brief — 1 reel, 30s, 9:16")
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


def test_to_markdown_full_render_whole_string():
    # reel_count is pinned to the only supported value (1) — reel_count > 1 is refused at
    # construction (see test_reel_count_above_one_is_refused_...); to_markdown's plural
    # branch is now unreachable through any valid Spec, by design.
    s = Spec(canvas=(9, 16), length_s=30.0, mood="energetic", hook="jump-cut open",
             reel_count=1, music="ODESZA", music_mode="local", style_lean="trend",
             platform="tiktok", text="captions", ending="freeze frame",
             cast=["Anna", "Ben"], notes="keep it tight")
    assert s.to_markdown() == (
        "# Reel brief — 1 reel, 30s, 9:16\n"
        "\n"
        "- **Mood:** energetic\n"
        "- **Hook:** jump-cut open\n"
        "- **Music:** ODESZA (mode: local)\n"
        "- **Style-lean:** trend\n"
        "- **Platform:** tiktok\n"
        "- **Cast:** Anna, Ben\n"
        "- **Text:** captions\n"
        "- **Ending:** freeze frame\n"
        "- **Notes:** keep it tight"
    )


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_spec_from_dict_rejects_a_non_object_top_level(d, name):
    # Four production readers (music_find.py:101, titles.py:51, mood.py:78, pacing.py:29) call
    # Spec.from_json with no except; before the guard a wrong-shaped SPEC.json reached
    # d.get("canvas") and raised a bare AttributeError out of each of them.
    with pytest.raises(ValueError) as ei:
        Spec.from_dict(d)
    msg = str(ei.value)
    assert "expected a SPEC.json object" in msg
    assert f"got {name}" in msg
    assert "re-run reel-brief" in msg
    assert "has no attribute" not in msg


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_spec_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "SPEC.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run reel-brief"):
        Spec.from_json(p)


def test_spec_tone_bias_defaults_to_none_not_zero():
    # None and (0,0,0) mean different things: None = "take the preset's taste",
    # (0,0,0) = "this mood, leave my colour alone". A zero default would make
    # the second inexpressible (design 2026-09-03 §2).
    assert Spec(**GOOD).tone_bias is None


def test_spec_accepts_an_authored_tone_bias():
    s = Spec(**{**GOOD, "tone_bias": [10, 0, -18]})
    assert s.tone_bias == (10.0, 0.0, -18.0)


def test_spec_accepts_an_explicit_zero_bias():
    s = Spec(**{**GOOD, "tone_bias": (0, 0, 0)})
    assert s.tone_bias == (0.0, 0.0, 0.0)


def test_spec_rejects_a_two_element_tone_bias():
    with pytest.raises(ValueError, match="tone_bias"):
        Spec(**{**GOOD, "tone_bias": (10, 0)})


def test_spec_rejects_a_bool_in_tone_bias():
    with pytest.raises(ValueError, match="tone_bias"):
        Spec(**{**GOOD, "tone_bias": (10, True, 0)})


def test_spec_round_trips_tone_bias_through_json_shape():
    s = Spec(**{**GOOD, "tone_bias": (10, 0, -18)})
    assert Spec.from_dict(s.to_dict()) == s


def test_spec_round_trips_an_absent_tone_bias():
    s = Spec(**GOOD)
    assert Spec.from_dict(s.to_dict()) == s
