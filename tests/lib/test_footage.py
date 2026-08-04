import json

import pytest
from scripts.lib.footage import (DESCRIPTOR_LEN, FootageWindow, FootageClip, Footage,
                                 CastMember, Cast)


def _desc(*head: float) -> list[float]:
    """A registry-valid descriptor: DESCRIPTOR_LEN floats — `head`, zero-padded.
    Reads the length from its one home rather than hardcoding 24, so a HIST_BINS
    change moves these fixtures with the contract instead of breaking them."""
    return list(head) + [0.0] * (DESCRIPTOR_LEN - len(head))


def _win(**kw):
    d = dict(start=1.0, dur=2.0, shot_type="medium", people=1, motion=0.4, shake=0.01)
    d.update(kw)
    return FootageWindow(**d)


def test_window_roundtrips():
    w = _win(description="1 person, medium, dynamic", score=0.7, best=True)
    assert FootageWindow(**w.to_dict()).to_dict() == w.to_dict()


@pytest.mark.parametrize("kw,msg", [
    (dict(start=-1), "start"), (dict(dur=0), "dur"), (dict(shot_type=""), "shot_type"),
    (dict(people=-1), "people"), (dict(people=True), "people"),
    (dict(motion=1.5), "motion"), (dict(shake=-0.1), "shake"), (dict(score=2.0), "score"),
])
def test_window_rejects_bad(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _win(**kw)


def test_clip_roundtrips_and_wraps_windows():
    c = FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=59.94,
                    shaky=False, scene_cuts=[3.0], windows=[_win()])
    back = FootageClip.from_dict(c.to_dict())
    assert back.to_dict() == c.to_dict()
    assert isinstance(back.windows[0], FootageWindow)


def test_clip_from_dict_names_bad_window():
    with pytest.raises(ValueError, match=r"windows\[0\]"):
        FootageClip.from_dict(dict(source="a.mp4", dur=1.0, res=[10, 10], fps=30,
                                   windows=[dict(start=1.0, dur=2.0, shot_type="x", people=1,
                                                 motion=0.4, shake=0.0, bogus=1)]))


def test_clip_rejects_bad_res():
    with pytest.raises(ValueError, match="res"):
        FootageClip(source="a.mp4", dur=1.0, res=(0, 10), fps=30)


def test_clip_from_dict_names_missing_window_field():
    # a window dict missing a required field is named by index, same as an unknown key
    with pytest.raises(ValueError, match=r"windows\[0\]"):
        FootageClip.from_dict(dict(source="a.mp4", dur=1.0, res=[10, 10], fps=30,
                                   windows=[dict(start=1.0, dur=2.0)]))   # missing shot_type/people/motion/shake


def test_clip_from_dict_rejects_unknown_top_key():
    with pytest.raises(ValueError, match="unknown field"):
        FootageClip.from_dict(dict(source="a.mp4", dur=1.0, res=[10, 10], fps=30, bogus=1))


@pytest.mark.parametrize("bad", [None, "abc", True, -1.0])
def test_clip_rejects_a_bad_scene_cut(bad):
    # scene_cuts were coerced with float() and never validated first: None raised a bare
    # TypeError, "abc" raised float()'s raw ValueError (naming neither class nor remedy),
    # and True/-1.0 were silently accepted (True->1.0, -1.0 a negative timestamp). Each
    # must now raise a ValueError naming the field, like every other numeric clip field.
    with pytest.raises(ValueError, match="scene_cuts"):
        FootageClip(source="a.mp4", dur=10.0, res=(10, 10), fps=30, scene_cuts=[5.0, bad])


def test_clip_bad_scene_cut_names_the_field_value_and_remedy():
    # coding-standards: wrong-value construction raises ValueError with the remedy in the
    # message. All three halves are asserted, matching the FootageWindow/from_dict style.
    with pytest.raises(ValueError) as ei:
        FootageClip(source="a.mp4", dur=10.0, res=(10, 10), fps=30, scene_cuts=[5.0, None])
    msg = str(ei.value)
    assert "scene_cuts[1]" in msg                 # the field, by index
    assert "None" in msg                          # the offending value
    assert "footage-intake" in msg                # the remedy, not just the diagnosis


def test_clip_rejects_a_non_list_scene_cuts():
    # a non-iterable container used to raise a bare TypeError out of the comprehension
    with pytest.raises(ValueError, match="scene_cuts"):
        FootageClip(source="a.mp4", dur=10.0, res=(10, 10), fps=30, scene_cuts=5.0)


def test_clip_rejects_a_non_list_windows():
    # windows validates each entry (isinstance) but the container itself was unchecked,
    # so a non-iterable raised a bare TypeError out of enumerate — the same shape of fail
    # as an unvalidated scene_cut. Guarded alongside scene_cuts for symmetry.
    with pytest.raises(ValueError, match="windows"):
        FootageClip(source="a.mp4", dur=10.0, res=(10, 10), fps=30, windows=42)


def test_clip_from_dict_surfaces_a_bad_scene_cut_not_as_a_missing_field():
    # float()'s TypeError used to be caught by from_dict's `except TypeError` and
    # re-labelled "missing or unknown field" — a wrong diagnosis. __post_init__ now
    # raises ValueError (uncaught there), so the real cause and its remedy survive.
    with pytest.raises(ValueError, match="scene_cuts") as ei:
        FootageClip.from_dict(dict(source="a.mp4", dur=1.0, res=[10, 10], fps=30,
                                   scene_cuts=[5.0, None]))
    assert "missing or unknown field" not in str(ei.value)


def test_room_after_runs_to_the_next_scene_cut():
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[12.0, 25.0], windows=[])
    assert clip.room_after(4.0) == pytest.approx(8.0)


def test_room_after_runs_to_the_clip_end_when_no_cut_follows():
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[12.0], windows=[])
    assert clip.room_after(20.0) == pytest.approx(10.0)


def test_room_after_ignores_a_cut_at_the_start_itself():
    # The in-point IS the cut: the shot that starts there runs to the NEXT one.
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[12.0, 25.0], windows=[])
    assert clip.room_after(12.0) == pytest.approx(13.0)


def test_room_after_refuses_a_start_past_the_clip():
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[], windows=[])
    with pytest.raises(ValueError, match="past the end"):
        clip.room_after(30.0)


@pytest.mark.parametrize("bad", [-1.0, True, "4.0", None])
def test_room_after_refuses_a_bad_start(bad):
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       shaky=False, scene_cuts=[], windows=[])
    with pytest.raises(ValueError, match="start"):
        clip.room_after(bad)


def _footage():
    return Footage(clips=[FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=30,
                                      scene_cuts=[3.0],
                                      windows=[_win(score=0.8, best=True),
                                               _win(start=5.0, score=0.3)])])


def test_footage_roundtrips():
    f = _footage()
    assert Footage.from_dict(f.to_dict()).to_dict() == f.to_dict()


def test_footage_from_json_roundtrip(tmp_path):
    f = _footage()
    p = tmp_path / "FOOTAGE.json"; p.write_text(json.dumps(f.to_dict()))
    assert Footage.from_json(p).to_dict() == f.to_dict()


def test_footage_from_json_bad_syntax(tmp_path):
    p = tmp_path / "FOOTAGE.json"; p.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        Footage.from_json(p)


def test_ranked_windows_is_score_descending():
    f = _footage()
    ranked = f.ranked_windows()
    assert [w.score for _, w in ranked] == [0.8, 0.3]


def test_to_markdown_renders_header_and_star():
    md = _footage().to_markdown()
    assert "# Footage — 1 clips, 2 windows (1 best)" in md
    assert "## a.mp4" in md and "★" in md
    assert "| # | start | dur | shot | people | motion | shake | score | best | description |" in md


def test_to_markdown_numbers_windows_zero_based_per_clip():
    # the `#` column matches clip.windows[i] ordering — what build_edl indexes into
    md = _footage().to_markdown()
    assert "\n| 0 | 1.00 | 2.00 | medium |" in md
    assert "\n| 1 | 5.00 | 2.00 | medium |" in md


def test_cast_roundtrips():
    c = Cast(members=[CastMember(name="Lena", descriptor=_desc(0.5, 0.5), notes="red jacket",
                                 ref_crops=["crops/lena_0.png"])])
    assert Cast.from_dict(c.to_dict()).to_dict() == c.to_dict()


@pytest.mark.parametrize("kw,msg", [
    (dict(name=""), "name"), (dict(descriptor=[]), "descriptor"),
    (dict(descriptor=["x"]), "descriptor"),
])
def test_castmember_rejects_bad(kw, msg):
    d = dict(name="Lena", descriptor=_desc(0.5, 0.5)); d.update(kw)
    with pytest.raises(ValueError, match=msg):
        CastMember(**d)


def test_castmember_rejects_a_wrong_length_descriptor():
    # A descriptor is 3 channels × HIST_BINS = DESCRIPTOR_LEN floats. Nothing used
    # to check that until appearance.descriptor_dist ran deep inside tracking, so a
    # stale cast.json (built under a different HIST_BINS, or hand-edited) passed
    # Cast.from_json, hero.resolve, manifest.validate AND edl.preflight, then
    # detonated in track.build_route — after every window had been cut. A typo'd
    # cast NAME fails in milliseconds; a stale descriptor must too. This is the one
    # boundary a foreign descriptor crosses, so this is where the shape is checked.
    for bad in ([0.5, 0.5], [0.0] * (DESCRIPTOR_LEN - 1), [0.0] * (DESCRIPTOR_LEN + 1)):
        with pytest.raises(ValueError, match="descriptor") as ex:
            CastMember(name="Lena", descriptor=bad)
        assert str(DESCRIPTOR_LEN) in str(ex.value), ex.value
        assert "footage-intake" in str(ex.value), ex.value    # the remedy, not just the diagnosis


def test_castmember_descriptor_must_be_512():
    from scripts.lib.footage import DESCRIPTOR_LEN, CastMember
    assert DESCRIPTOR_LEN == 512
    for bad in ([0.5, 0.5], [0.0] * 511, [0.0] * 513):
        with pytest.raises(ValueError) as ex:
            CastMember(name="Lena", descriptor=bad)
        assert "512" in str(ex.value)
    CastMember(name="Lena", descriptor=[0.0] * 512)     # exact length accepted


def test_cast_from_json_roundtrip(tmp_path):
    c = Cast(members=[CastMember(name="Lena", descriptor=_desc(0.5, 0.5))])
    p = tmp_path / "cast.json"; p.write_text(json.dumps(c.to_dict()))
    assert Cast.from_json(p).to_dict() == c.to_dict()


def _twins():
    """Two members named "Lena" carrying OPPOSITE descriptors — the pin that
    resolves to one follows a completely different person than the other."""
    return [CastMember(name="Lena", descriptor=_desc(1.0)),
            CastMember(name="Lena", descriptor=[0.0] * (DESCRIPTOR_LEN - 1) + [1.0])]


def test_cast_rejects_duplicate_names():
    # A registry maps a NAME to an identity; two entries under one name map it to
    # neither. hero.resolve returned whichever was listed first, so the route
    # followed a coin flip decided by list order — silently, with no way to tell.
    # Not exotic: intake dedups surfaced crops at CAST_DEDUP=0.30, so one person
    # shot in two lightings gets surfaced twice, and naming both "Lena" is the
    # obvious human move. Uniqueness is the registry's invariant, so it is checked
    # on construction — which also makes resolve's first-match loop correct rather
    # than merely lucky.
    with pytest.raises(ValueError, match="Lena") as ex:
        Cast(members=_twins())
    assert "duplicate" in str(ex.value)
    assert "distinct names" in str(ex.value)      # the remedy, not just the diagnosis


def test_cast_from_json_rejects_duplicate_names(tmp_path):
    # the disk path must refuse it too — from_json is how every real cast.json enters
    p = tmp_path / "cast.json"
    p.write_text(json.dumps({"members": [m.to_dict() for m in _twins()]}))
    with pytest.raises(ValueError, match="duplicate"):
        Cast.from_json(p)


def test_cast_allows_distinct_names_with_identical_descriptors():
    # the invariant is about NAMES, not descriptors: two people who happen to be
    # dressed alike are a tracking problem (track.py's margin rule), not a registry
    # problem, and the registry must not pre-empt that judgement
    d = _desc(0.5, 0.5)
    assert len(Cast(members=[CastMember(name="Lena", descriptor=d),
                             CastMember(name="Bo", descriptor=d)]).members) == 2


def test_cast_from_json_bad_syntax(tmp_path):
    p = tmp_path / "cast.json"; p.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        Cast.from_json(p)


@pytest.mark.parametrize("d", [[], [1, 2], "str", 42, 4.5, True, None])
def test_cast_from_dict_rejects_a_non_object_top_level(d):
    # This boundary reads user-supplied JSON, so it owes callers ONE documented type.
    # Before the top-level guard these raised a bare AttributeError out of d.get(),
    # which callers' `except (OSError, ValueError)` did not catch.
    with pytest.raises(ValueError, match="expected a cast.json object"):
        Cast.from_dict(d)


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_cast_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "cast.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run footage-intake"):
        Cast.from_json(p)


@pytest.mark.parametrize("d", [[], [1, 2], "str", 42, 4.5, True, None])
def test_footage_from_dict_rejects_a_non_object_top_level(d):
    # This boundary reads user-supplied JSON, so it owes callers ONE documented type.
    # Before the top-level guard these raised a bare AttributeError out of d.get("clips"),
    # and write_edit_plan (scripts/edit_plan.py) has NO except around Footage.from_json —
    # so a valid-JSON-but-wrong-shape FOOTAGE.json crashed the driver outright.
    with pytest.raises(ValueError, match="expected a FOOTAGE.json object"):
        Footage.from_dict(d)


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_footage_from_dict_names_what_was_expected_what_arrived_and_the_remedy(d, name):
    # coding-standards: wrong-type construction raises ValueError with the remedy in the
    # message. All three halves are asserted — a message missing any of them leaves the
    # reader knowing something broke but not what to do about it.
    with pytest.raises(ValueError) as ei:
        Footage.from_dict(d)
    msg = str(ei.value)
    assert "'clips' list" in msg                    # what was expected
    assert f"got {name}" in msg                     # what actually arrived
    assert "re-run footage-intake" in msg           # the remedy


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_footage_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "FOOTAGE.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run footage-intake"):
        Footage.from_json(p)


@pytest.mark.parametrize("d", [[], [1, 2], "str", 42, 4.5, True, None])
def test_clip_from_dict_rejects_a_non_object_top_level(d):
    # Footage.from_dict checks each clip is a dict before delegating, so this guard is for
    # the DIRECT caller: FootageClip.from_dict is public contract surface (tests and any
    # future per-clip reader call it) and owes the same one type. Same bug shape —
    # d.get("windows") on an unchecked d.
    with pytest.raises(ValueError, match="expected a FOOTAGE.json clip object"):
        FootageClip.from_dict(d)


@pytest.mark.parametrize("d,name", [([], "list"), ("str", "str"), (42, "int"), (None, "NoneType")])
def test_clip_from_dict_names_what_was_expected_what_arrived_and_the_remedy(d, name):
    with pytest.raises(ValueError) as ei:
        FootageClip.from_dict(d)
    msg = str(ei.value)
    assert "'windows' list" in msg
    assert f"got {name}" in msg
    assert "re-run footage-intake" in msg


def test_footage_window_track_ids_default_and_roundtrip():
    from scripts.lib.footage import FootageWindow
    w = FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=2,
                      motion=0.3, shake=0.0, track_ids=[3, 7])
    assert w.track_ids == [3, 7]
    assert w.to_dict()["track_ids"] == [3, 7]
    assert FootageWindow(**w.to_dict()).track_ids == [3, 7]
    # default is an empty list (a window with nobody in it)
    assert FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=0,
                         motion=0.0, shake=0.0).track_ids == []


def test_footage_window_track_ids_rejects_bad_values():
    import pytest
    from scripts.lib.footage import FootageWindow
    for bad in [[-1], [True], ["1"], 5]:
        with pytest.raises(ValueError):
            FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=1,
                          motion=0.0, shake=0.0, track_ids=bad)
