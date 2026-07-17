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


def test_descriptor_len_is_three_channels_of_hist_bins():
    # the derived fact gets ONE spelling, here — appearance.build_descriptor imports
    # HIST_BINS from this module rather than declaring its own, so the producer and
    # the on-disk contract cannot drift
    from scripts.lib.footage import HIST_BINS
    assert DESCRIPTOR_LEN == 3 * HIST_BINS


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
