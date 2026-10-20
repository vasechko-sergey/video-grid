import json

import pytest
from scripts.lib import footage
from scripts.lib.footage import (DESCRIPTOR_LEN, FootageWindow, FootageClip, Footage,
                                 CastMember, Cast)


def _desc(*head: float) -> list[float]:
    """A registry-valid descriptor: DESCRIPTOR_LEN floats — `head`, zero-padded.
    Reads the length from its one home rather than hardcoding 512, so a
    DESCRIPTOR_LEN change moves these fixtures with the contract instead of
    breaking them."""
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
    # A descriptor is a DESCRIPTOR_LEN-float 512-d OSNet person-re-ID embedding.
    # Nothing used to check that until appearance.descriptor_dist ran deep inside
    # tracking, so a stale cast.json (built under a different DESCRIPTOR_LEN — e.g.
    # a pre-2026-08-04 24-d colour histogram — or hand-edited) passed Cast.from_json,
    # hero.resolve, manifest.validate AND edl.preflight, then detonated in
    # track.build_route — after every window had been cut. A typo'd cast NAME fails
    # in milliseconds; a stale descriptor must too. This is the one boundary a
    # foreign descriptor crosses, so this is where the shape is checked.
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
    # Not exotic: intake clusters surfaced crops at a cosine cut (CLUSTER_COS=0.30,
    # design 2026-08-04), so one person shot in two lightings can still surface
    # twice, and naming both "Lena" is the obvious human move. Uniqueness is the
    # registry's invariant, so it is checked
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


def test_shot_type_buckets_on_area_with_exact_boundaries():
    # MEDIUM_AREA 0.08 is inclusive, CLOSE_AREA 0.30 is exclusive (> not >=)
    assert footage.shot_type(0.0, 0.0) == "wide"          # no subject → scenery
    assert footage.shot_type(0.2, 0.399) == "wide"         # area 0.0798 < 0.08
    assert footage.shot_type(0.2, 0.4) == "medium"         # area 0.08 exactly
    assert footage.shot_type(0.5, 0.6) == "medium"         # area 0.30 exactly, NOT close
    assert footage.shot_type(0.5, 0.61) == "close"         # area 0.305 > 0.30


def test_delivered_shot_grows_the_area_by_the_width_crop():
    # 3840x2160 → 9:16 fill: crop is 1215x2160, so width scales by 3840/1215 = 3.16
    # and height does not scale at all. A subject at 3% of the source frame is `wide`
    # in source geometry and `medium` once the delivery crop is taken into account.
    src, aspect = (3840, 2160), (9, 16)
    assert footage.shot_type(0.1, 0.3) == "wide"                       # area 0.030
    assert footage.delivered_shot(0.1, 0.3, src, aspect) == "medium"   # area 0.0948


def test_delivered_shot_clamps_a_subject_wider_than_the_crop():
    # a subject filling the source width is fully framed after the crop, not 3.16x wide
    assert footage.delivered_shot(1.0, 1.0, (3840, 2160), (9, 16)) == "close"


def test_delivered_shot_without_people_is_wide_in_any_geometry():
    assert footage.delivered_shot(0.0, 0.0, (3840, 2160), (9, 16)) == "wide"


def test_window_carries_the_three_measurements_and_round_trips():
    w = footage.FootageWindow(start=0.0, dur=2.0, shot_type="medium", people=1,
                              motion=0.3, shake=0.01, subject_w=0.25, subject_h=0.4,
                              present=0.75)
    assert (w.subject_w, w.subject_h, w.present) == (0.25, 0.4, 0.75)
    assert footage.FootageWindow(**w.to_dict()).to_dict() == w.to_dict()


@pytest.mark.parametrize("bad", [
    dict(subject_w=-0.1), dict(subject_w=1.1), dict(subject_h=-0.1),
    dict(subject_h=1.1), dict(present=-0.1), dict(present=1.1),
    dict(present="1.0"), dict(present=True),
])
def test_window_refuses_a_measurement_outside_the_unit_interval(bad):
    base = dict(start=0.0, dur=2.0, shot_type="wide", people=0, motion=0.0, shake=0.0)
    with pytest.raises(ValueError, match="subject_w|subject_h|present"):
        footage.FootageWindow(**{**base, **bad})


def test_clip_from_dict_refuses_a_footage_json_written_before_the_shot_size_fields():
    legacy = {"source": "a.mp4", "dur": 10.0, "res": [1920, 1080], "fps": 30.0,
              "windows": [{"start": 0.0, "dur": 2.0, "shot_type": "wide",
                           "people": 0, "motion": 0.0, "shake": 0.0}]}
    with pytest.raises(ValueError, match="predates.*re-run footage-intake"):
        footage.FootageClip.from_dict(legacy)


def test_shot_at_no_cuts_is_the_whole_clip():
    clip = FootageClip(source="A.mp4", dur=20.0, res=(1920, 1080), fps=30.0, scene_cuts=[])
    assert clip.shot_at(0.0) == (0.0, 20.0)
    assert clip.shot_at(19.9) == (0.0, 20.0)


def test_shot_at_returns_the_segment_between_the_surrounding_cuts():
    clip = FootageClip(source="A.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       scene_cuts=[10.0, 22.0])
    assert clip.shot_at(3.0) == (0.0, 10.0)
    assert clip.shot_at(15.0) == (10.0, 22.0)
    assert clip.shot_at(25.0) == (22.0, 30.0)


def test_shot_at_on_a_cut_belongs_to_the_later_shot_like_room_after():
    # room_after keeps `c > start`, so a start exactly ON a cut gets the room of the
    # shot that BEGINS there. shot_at must agree, or the two authorities would place
    # the same episode in different shots.
    clip = FootageClip(source="A.mp4", dur=30.0, res=(1920, 1080), fps=30.0,
                       scene_cuts=[10.0, 22.0])
    assert clip.shot_at(10.0) == (10.0, 22.0)
    assert clip.shot_at(10.0)[1] - 10.0 == clip.room_after(10.0)


def test_shot_at_is_bit_identical_for_two_times_in_the_same_shot():
    # Regression (whole-branch review, 2026-08-07): shot_at used to return
    # (max(before), t + room_after(t)) — an end derived from the CALLER's own t,
    # not from the shot's own boundary. In IEEE-754, t + (cut - t) is not
    # bit-identical to cut in general, so two episodes inside the SAME shot at
    # different (non-round) in-points could key differently and the no_repeat/
    # exclude checks (which key on this pair) silently missed the repeat. These
    # exact non-round numbers are the review's reproduction — ~6% of realistic
    # (start, start, cut) triples reproduce it, including at 30/29.97/59.94fps.
    # Every pre-existing shot_at fixture used round seconds (1.0/6.0/10.0/22.0),
    # where the arithmetic happens to be exact, which is why it went unseen.
    cut = 15.515515515515515
    clip = FootageClip(source="A.mp4", dur=30.0, res=(1920, 1080), fps=29.97,
                       scene_cuts=[cut])
    t1, t2 = 6.606606606606607, 14.848181514848182
    s1, s2 = clip.shot_at(t1), clip.shot_at(t2)
    assert s1 == s2
    assert s1[1] == cut


def test_shot_at_refuses_a_time_outside_the_clip():
    clip = FootageClip(source="A.mp4", dur=20.0, res=(1920, 1080), fps=30.0)
    with pytest.raises(ValueError, match="past the end"):
        clip.shot_at(20.0)
    with pytest.raises(ValueError, match=">= 0"):
        clip.shot_at(-1.0)


def test_footage_band_defaults_to_none_for_a_legacy_artifact():
    # A FOOTAGE.json written before 2026-09-03 carries no band. None is "unknown",
    # and edit_plan's reconciliation reports not-checked rather than passing green.
    assert footage.Footage.from_dict({"clips": []}) == footage.Footage(clips=[], band=None)


def test_footage_round_trips_its_band():
    f = footage.Footage(clips=[], band=(1.2, 4.0))
    assert footage.Footage.from_dict(f.to_dict()) == f


def test_footage_band_is_coerced_to_a_tuple_of_floats():
    assert footage.Footage(clips=[], band=[1, 4]) == footage.Footage(clips=[], band=(1.0, 4.0))


def test_footage_rejects_a_one_element_band():
    with pytest.raises(ValueError, match="band"):
        footage.Footage(clips=[], band=(1.2,))


def test_footage_rejects_an_inverted_band():
    with pytest.raises(ValueError, match="band"):
        footage.Footage(clips=[], band=(4.0, 1.2))


def test_footage_scoring_round_trips_and_defaults_to_none():
    f = footage.Footage(clips=[], scoring={"windows": 4,
                                           "separated": {"present": 0, "motion": 3, "shake": 4}})
    back = footage.Footage.from_dict(f.to_dict())
    assert back.scoring == {"windows": 4,
                            "separated": {"present": 0, "motion": 3, "shake": 4}}
    # an artifact written before 2026-09-10 carries no key at all
    assert footage.Footage.from_dict({"clips": []}).scoring is None


def test_footage_scoring_refuses_a_missing_score_term():
    with pytest.raises(ValueError, match="one count per"):
        footage.Footage(clips=[], scoring={"windows": 2,
                                           "separated": {"present": 1, "motion": 1}})


def test_footage_scoring_refuses_an_extra_unknown_score_term():
    with pytest.raises(ValueError, match="one count per"):
        footage.Footage(clips=[], scoring={"windows": 2,
                                           "separated": {"present": 1, "motion": 1, "shake": 1, "blur": 1}})


def test_footage_scoring_refuses_a_bad_windows_value():
    # negative int
    with pytest.raises(ValueError, match="windows.*must be an int >= 0"):
        footage.Footage(clips=[], scoring={"windows": -1,
                                           "separated": {"present": 0, "motion": 0, "shake": 0}})
    # bool (a subclass of int in Python)
    with pytest.raises(ValueError, match="windows.*must be an int >= 0"):
        footage.Footage(clips=[], scoring={"windows": True,
                                           "separated": {"present": 0, "motion": 0, "shake": 0}})
    # non-int string
    with pytest.raises(ValueError, match="windows.*must be an int >= 0"):
        footage.Footage(clips=[], scoring={"windows": "4",
                                           "separated": {"present": 0, "motion": 0, "shake": 0}})
    # float
    with pytest.raises(ValueError, match="windows.*must be an int >= 0"):
        footage.Footage(clips=[], scoring={"windows": 4.0,
                                           "separated": {"present": 0, "motion": 0, "shake": 0}})


def test_footage_scoring_refuses_separating_more_windows_than_the_pool_holds():
    with pytest.raises(ValueError, match="cannot separate more windows"):
        footage.Footage(clips=[], scoring={"windows": 2,
                                           "separated": {"present": 0, "motion": 3, "shake": 1}})


def test_footage_scoring_refuses_a_non_dict():
    with pytest.raises(ValueError, match="Footage.scoring must be"):
        footage.Footage(clips=[], scoring=[1, 2, 3])


def test_footage_markdown_names_a_term_that_separated_nothing():
    f = footage.Footage(clips=[], scoring={"windows": 1508,
                                           "separated": {"present": 3, "motion": 1429,
                                                         "shake": 1458}})
    md = f.to_markdown()
    assert "**present** 3/1508" in md
    assert "separated" in md


def test_footage_markdown_says_nothing_about_scoring_on_an_older_artifact():
    assert "separated" not in footage.Footage(clips=[]).to_markdown()


# --- photos (design 2026-10-20 §1) --------------------------------------------------

def _photo(**kw):
    d = dict(source="IMG_0001.HEIC", dur=8.0, res=(3024, 4032), fps=0.0, kind="photo",
             windows=[_win(start=0.0, motion=0.0, shake=0.0)])
    d.update(kw)
    return FootageClip(**d)


def test_a_photo_clip_roundtrips_with_its_kind():
    c = _photo()
    d = c.to_dict()
    assert d["kind"] == "photo" and d["fps"] == 0.0
    assert FootageClip.from_dict(json.loads(json.dumps(d))).to_dict() == d


def test_a_video_clip_omits_kind_so_old_artifacts_are_byte_identical():
    c = FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=59.94, windows=[_win()])
    assert "kind" not in c.to_dict()
    assert FootageClip.from_dict(c.to_dict()).kind == "video"


@pytest.mark.parametrize("kw, msg", [
    (dict(fps=30.0), "0.0 for a photo"),
    (dict(scene_cuts=[1.0]), "no scene cuts"),
    (dict(shaky=True), "cannot be shaky"),
    (dict(kind="clip"), "kind must be one of"),
])
def test_a_photo_clip_refuses_what_a_still_cannot_have(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _photo(**kw)


def test_a_video_clip_still_refuses_a_zero_rate():
    with pytest.raises(ValueError, match="fps must be a positive number"):
        FootageClip(source="a.mp4", dur=2.0, res=(10, 10), fps=0.0)


def test_footage_markdown_names_a_photo_as_one():
    md = Footage(clips=[_photo()]).to_markdown()
    assert "## IMG_0001.HEIC  (photo · 3024×4032 · may hold up to 8.0s)" in md
