import pytest
from scripts.lib import manifest as mf
from scripts.lib.footage import Cast, CastMember


def _ok_dict(**over):
    d = dict(segment="seg.mp4", out_path="out.mp4", composition="lead",
             grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_from_dict_defaults():
    m = mf.Manifest.from_dict(_ok_dict())
    assert m.layout == "fill"
    assert m.stabilize is False
    assert m.color_means == (105, 122, 137)
    assert m.canvas == (9, 16)           # list coerced to tuple
    assert m.model == "yolo11n-seg.pt"


def test_from_dict_missing_required_raises():
    d = _ok_dict(); del d["composition"]
    with pytest.raises(KeyError, match="composition"):
        mf.Manifest.from_dict(d)


def test_validate_ok():
    assert mf.validate(mf.Manifest.from_dict(_ok_dict())) == []


def test_validate_unknown_composition():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(composition="Lead")))
    assert any("composition" in p for p in problems)


def test_validate_unknown_grid():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(grid="golden-canon")))
    assert any("grid" in p for p in problems)


def test_validate_unsupported_layout_refused():
    # fit-blur/insert are first-class layouts now; a genuinely unknown one still
    # fails the soft gate, with a message that names what IS supported.
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(layout="pan")))
    assert any("pan" in p and "fit-blur" in p for p in problems)


def test_validate_stabilize_refused():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(stabilize=True)))
    assert any("stabilize" in p for p in problems)


def test_validate_nonpositive_duration():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(target_dur=0)))
    assert any("target_dur" in p for p in problems)


def test_validate_bad_canvas():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(canvas=[9, 16, 1])))
    assert any("canvas" in p for p in problems)


def test_validate_bad_motion_string():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(motion="sideways")))
    assert any("motion" in p for p in problems)


def test_validate_accepts_known_motion():
    for good in ("lateral:right", "lateral:left", "head-on", "static"):
        assert mf.validate(mf.Manifest.from_dict(_ok_dict(motion=good))) == []


def test_explicit_null_required_raises():
    d = _ok_dict(canvas=None)
    with pytest.raises(KeyError, match="canvas"):
        mf.Manifest.from_dict(d)


def test_explicit_null_optional_uses_default_not_crash():
    m = mf.Manifest.from_dict(_ok_dict(color_means=None, model=None, layout=None))
    assert m.color_means == (105, 122, 137)
    assert m.model == "yolo11n-seg.pt"
    assert m.layout == "fill"          # explicit null → default, not a needs_input


def test_unknown_key_raises():
    with pytest.raises(KeyError, match="stablize"):
        mf.Manifest.from_dict(_ok_dict(stablize=True))   # typo of stabilize


def test_hero_list_coerced_to_tuple():
    m = mf.Manifest.from_dict(_ok_dict(hero=[900, 500, 120, 300]))
    assert m.hero == (900, 500, 120, 300)
    assert isinstance(m.hero, tuple)


def test_hero_string_rule_kept():
    m = mf.Manifest.from_dict(_ok_dict(hero="largest"))
    assert m.hero == "largest"


def test_validate_bad_model():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(model="yolo11n-set.pt")))
    assert any("model" in p for p in problems)


def test_validate_color_means_wrong_length():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(color_means=[255, 10])))
    assert any("color_means" in p for p in problems)


def test_validate_canvas_nonpositive():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(canvas=[0, 16])))
    assert any("canvas" in p for p in problems)


def test_validate_empty_segment():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(segment="")))
    assert any("segment" in p for p in problems)


def test_delivery_defaults_native():
    m = mf.Manifest.from_dict(_ok_dict())
    assert m.delivery == "native"


def test_delivery_passthrough():
    m = mf.Manifest.from_dict(_ok_dict(delivery="short_edge:1080"))
    assert m.delivery == "short_edge:1080"
    assert mf.validate(m) == []


def test_validate_bad_delivery():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(delivery="huge:9999x")))
    assert any("delivery" in p for p in problems)


def test_validate_color_means_nonpositive():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(color_means=[0, 122, 137])))
    assert any("color_means" in p for p in problems)


# --- Task 9: fit-blur / insert layouts, JSON array coercion, zero-freedom gate ---

def _base(**over):
    d = dict(segment="a.mp4", out_path="o.mp4", composition="lead", grid="thirds",
             canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_fit_blur_and_insert_are_now_supported():
    m = mf.Manifest.from_dict(_base(layout="fit-blur", crop_aspect="source",
                                    composition="break"))
    assert mf.validate(m) == []
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1],
                                    rect=[0.05, 0.25, 0.9]))
    assert mf.validate(m) == []


def test_json_arrays_become_tuples():
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1],
                                    rect=[0.05, 0.25, 0.9]))
    assert m.crop_aspect == (1, 1)
    assert m.rect == (0.05, 0.25, 0.9)


def test_lead_at_zero_freedom_is_refused_with_a_remedy():
    m = mf.Manifest.from_dict(_base(layout="fit-blur", crop_aspect="source",
                                    composition="lead"))
    problems = mf.validate(m)
    assert len(problems) == 1
    assert "crop_scale" in problems[0] and "break" in problems[0]


def test_lead_with_a_scaled_crop_is_allowed():
    m = mf.Manifest.from_dict(_base(layout="fit-blur", crop_aspect="source",
                                    composition="lead", crop_scale=0.9))
    assert mf.validate(m) == []


def test_a_bad_layout_field_becomes_a_problem_not_a_crash():
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1]))
    problems = mf.validate(m)
    assert any("insert needs a rect" in p for p in problems)


def test_split_is_still_refused():
    m = mf.Manifest.from_dict(_base(layout="split"))
    assert any("split" in p for p in mf.validate(m))


def test_insert_border_fields_round_trip_and_validate_clean():
    # border_px/border_color ride the manifest onto the Manifest and pass the gate.
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1],
                                    rect=[0.05, 0.25, 0.9], border_px=8,
                                    border_color="black"))
    assert m.border_px == 8
    assert m.border_color == "black"
    assert mf.validate(m) == []


def test_fill_with_a_border_is_a_problem_not_a_crash():
    # LayoutSpec raises for a bordered fill; the soft gate must catch it, not die.
    m = mf.Manifest.from_dict(_base(layout="fill", border_px=8))
    problems = mf.validate(m)
    assert any("border" in p for p in problems)


# --- Task 5: cast field + hero.resolve as validate()'s oracle ---

def _cast():
    return Cast(members=[CastMember(name="Lena", descriptor=[0.5, 0.5])])


def test_cast_path_round_trips():
    m = mf.Manifest.from_dict(_ok_dict(cast="proj/cast.json"))
    assert m.cast == "proj/cast.json"


def test_cast_defaults_to_empty():
    assert mf.Manifest.from_dict(_ok_dict()).cast == ""


def test_hero_track_id_survives_from_dict():
    assert mf.Manifest.from_dict(_ok_dict(hero=3)).hero == 3


def test_validate_accepts_a_rule_hero_without_a_cast():
    assert mf.validate(mf.Manifest.from_dict(_ok_dict(hero="largest"))) == []


def test_validate_accepts_a_known_cast_name():
    m = mf.Manifest.from_dict(_ok_dict(hero="Lena", cast="proj/cast.json"))
    assert mf.validate(m, cast=_cast()) == []


def test_validate_flags_a_cast_name_with_no_registry():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(hero="Lena")))
    assert any("cast.json" in p for p in problems)


def test_validate_flags_an_unknown_cast_name():
    m = mf.Manifest.from_dict(_ok_dict(hero="Lna", cast="proj/cast.json"))
    assert any("Lena" in p for p in mf.validate(m, cast=_cast()))


def test_validate_flags_a_malformed_hero():
    # Strengthened beyond a bare truthiness check: each of these must name the hero
    # field specifically, not merely produce SOME problem. All three otherwise-valid
    # dicts pass validate() clean (see test_validate_ok), so a bare `assert problems`
    # would still pass today even if the message were about something else entirely —
    # this pins the message content, not just the list's non-emptiness.
    for bad in ([1, 2, 3], True, 4.2):
        problems = mf.validate(mf.Manifest.from_dict(_ok_dict(hero=bad)))
        assert any("hero" in p for p in problems), (bad, problems)
