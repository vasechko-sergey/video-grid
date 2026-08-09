import json

import pytest
from scripts.lib.edl import EDL, EDLEpisode, preflight, to_manifest_dict
from scripts.lib.constraints import ConstraintReport, Violation
from scripts.lib import manifest as manifest_lib
from scripts.lib import moodpreset
from scripts.lib.footage import DESCRIPTOR_LEN
from scripts.lib.manifest import DEFAULT_COLOR
from scripts.lib.project import ProjectConfig


def _ep(**kw):
    base = dict(source="a.mp4", start=1.0, dur=2.0, shot_type="wide",
                composition="lead", grid="thirds")
    base.update(kw)
    return EDLEpisode(**base)


def test_minimal_episode_defaults():
    e = _ep()
    assert e.source == "a.mp4" and e.start == 1.0 and e.dur == 2.0
    assert e.layout == "fill" and e.crop_aspect is None and e.crop_scale == 1.0
    assert e.color_means == DEFAULT_COLOR and e.beat_slot is None and e.processing_notes == ""


def test_json_arrays_coerce_to_tuples():
    e = _ep(hero=[10, 20, 30, 40], crop_aspect=[9, 16], rect=[0.1, 0.2, 0.8], color_means=[100, 110, 120])
    assert e.hero == (10, 20, 30, 40) and e.crop_aspect == (9, 16)
    assert e.rect == (0.1, 0.2, 0.8) and e.color_means == (100, 110, 120)


@pytest.mark.parametrize("kw, needle", [
    (dict(source=""), "source"),
    (dict(source=None), "source"),
    (dict(start=-0.5), "start"),
    (dict(start=True), "start"),
    (dict(dur=0), "dur"),
    (dict(dur=-1.0), "dur"),
    (dict(dur=True), "dur"),
    (dict(shot_type=""), "shot_type"),
    (dict(composition="zoom"), "composition"),
    (dict(grid="golden"), "grid"),
    (dict(layout="split"), "layout"),
    (dict(motion="orbit"), "motion"),
    (dict(beat_slot=1.5), "beat_slot"),
    (dict(beat_slot=True), "beat_slot"),
    (dict(color_means=None), "color_means"),
    (dict(color_means=[1, 2]), "color_means"),
    (dict(color_means=[1, 2, 0]), "color_means"),
])
def test_bad_field_raises_valueerror_with_remedy(kw, needle):
    with pytest.raises(ValueError, match=needle):
        _ep(**kw)


def test_episode_to_dict_is_json_friendly_and_round_trips():
    e = _ep(hero=[10, 20, 30, 40], crop_aspect=[9, 16], rect=[0.1, 0.2, 0.8],
            color_means=[100, 110, 120], motion="static", beat_slot=3, processing_notes="hold here")
    d = e.to_dict()
    assert d["hero"] == [10, 20, 30, 40] and d["crop_aspect"] == [9, 16]   # tuples → lists
    assert d["rect"] == [0.1, 0.2, 0.8] and d["color_means"] == [100, 110, 120]
    assert d["beat_slot"] == 3 and d["processing_notes"] == "hold here"
    back = EDLEpisode(**d)                       # round-trips through the constructor
    assert back.to_dict() == d


def test_episode_to_dict_keeps_none_optionals():
    d = _ep().to_dict()                          # motion/hero/crop_aspect/rect default None
    assert d["motion"] is None and d["hero"] is None and d["crop_aspect"] is None and d["rect"] is None
    assert d["beat_slot"] is None


def _solid_episode():
    # EDLEpisode's six required fields are source/start/dur/shot_type/composition/grid.
    return EDLEpisode(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                      composition="break", grid="thirds",
                      layout="fit", crop_aspect="source",
                      background="solid", background_color="#101820")


def test_edl_episode_round_trips_the_background_colour():
    # EDLEpisode has no from_dict classmethod of its own — only EDL.from_dict does,
    # and it builds episodes via EDLEpisode(**e) (see EDL.from_dict below). Round-trip
    # through the constructor instead, matching
    # test_episode_to_dict_is_json_friendly_and_round_trips above. This file also
    # imports EDLEpisode/to_manifest_dict directly, with no `edl` module alias bound
    # anywhere (see test_edl_cast_round_trips's note on the same point).
    ep = _solid_episode()
    assert EDLEpisode(**ep.to_dict()) == ep


def test_to_manifest_dict_passes_the_background_colour_through():
    md = to_manifest_dict(_solid_episode(), segment="seg.mp4", out_path="o.mp4")
    assert (md["background"], md["background_color"]) == ("solid", "#101820")


def test_edl_episode_carries_a_pan():
    e = _ep(pan={"from": 0.2, "to": 0.7})
    assert e.pan == {"from": 0.2, "to": 0.7}


def test_edl_episode_defaults_to_no_pan():
    assert _ep().pan is None


def test_edl_episode_round_trips_a_pan_through_json():
    e = _ep(pan={"from": 0.2, "to": 0.7})
    back = EDL.from_dict(EDL(episodes=(e,)).to_dict()).episodes[0]
    assert back.pan == {"from": 0.2, "to": 0.7}


def test_to_manifest_dict_carries_the_pan_across():
    # off-default fractions: (0.0, 1.0) could not tell "threaded" from "dropped
    # and re-defaulted" (test-strength rule: never fixture a field's own default)
    md = to_manifest_dict(_ep(pan={"from": 0.2, "to": 0.7}), "seg.mp4", "out.mp4")
    assert md["pan"] == {"from": 0.2, "to": 0.7}


def test_to_manifest_dict_omits_an_absent_pan():
    # the established idiom: omit rather than carry an explicit null, so
    # Manifest.from_dict falls to its own default
    assert "pan" not in to_manifest_dict(_ep(), "seg.mp4", "out.mp4")


def test_to_manifest_dict_carries_an_empty_pan_across():
    # `is not None`, not truthiness: an empty dict is FALSY, so truthiness would
    # drop the key silently, Manifest.from_dict would see pan=None, and the gate
    # would report zero problems for a malformed authoring intent. Absent and
    # empty are different statements and only one of them is a mistake — the gate
    # is where that gets said, so the bridge must carry it there intact.
    assert to_manifest_dict(_ep(pan={}), "seg.mp4", "out.mp4")["pan"] == {}


def test_edl_episode_defaults_to_no_stabilize():
    assert _ep().stabilize is False


def test_stabilize_defaults_to_false_and_rides_in_to_dict():
    assert _ep().to_dict()["stabilize"] is False
    assert _ep(stabilize=True).to_dict()["stabilize"] is True


def test_edl_episode_round_trips_stabilize_through_json():
    e = _ep(stabilize=True)
    back = EDL.from_dict(EDL(episodes=(e,)).to_dict()).episodes[0]
    assert back.stabilize is True


def test_stabilize_must_be_a_real_bool_not_a_truthy_string():
    """JSON is easy to fat-finger; "yes" or 1 must fail loud at construction,
    not silently become a stabilize pass nobody asked for."""
    with pytest.raises(ValueError, match="stabilize must be true or false"):
        _ep(stabilize="yes")


def test_stabilize_rejects_a_bare_int_despite_bool_subclassing_int():
    # isinstance(True, int) is True in Python, so the check must ask for bool
    # SPECIFICALLY — otherwise a JSON `"stabilize": 1` would sail through.
    with pytest.raises(ValueError, match="stabilize must be true or false"):
        _ep(stabilize=1)


def test_the_bridge_omits_stabilize_when_it_is_false():
    """Same shape pan/motion/hero use: an absent flag leaves the key out rather
    than carrying an explicit false, so Manifest.from_dict falls to its own
    default and the two never disagree about what "unset" means."""
    assert "stabilize" not in to_manifest_dict(_ep(), "s.mp4", "o.mp4")


def test_the_bridge_carries_stabilize_when_it_is_true():
    assert to_manifest_dict(_ep(stabilize=True), "s.mp4", "o.mp4")["stabilize"] is True


def _motion_cell(md: str, row_prefix: str) -> str:
    """The exact `motion` column of one rendered EDL.md row, located via the real
    header rather than a hardcoded column index — this pins the CELL a value
    lands in, not merely that its text appears somewhere in the document."""
    header = [c.strip() for c in next(
        ln for ln in md.splitlines() if ln.startswith("| # |")).split("|")[1:-1]]
    row = [c.strip() for c in next(
        ln for ln in md.splitlines() if ln.startswith(row_prefix)).split("|")[1:-1]]
    return row[header.index("motion")]


def test_edl_markdown_renders_a_pan_in_the_motion_column():
    md = EDL(episodes=(_ep(pan={"from": 0.2, "to": 0.7}),)).to_markdown()
    assert _motion_cell(md, "| 0 |") == "pan 0.2→0.7"


def test_edl_markdown_shows_both_a_motion_and_its_pan():
    # motion describes the subject, pan the camera — the canonical pan has both
    md = EDL(episodes=(_ep(motion="static", pan={"from": 0.0, "to": 1.0}),)).to_markdown()
    assert _motion_cell(md, "| 0 |") == "static · pan 0.0→1.0"


def _edl(**kw):
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds")
    base = dict(episodes=[ep, {**ep, "start": 2.0}])
    base.update(kw)
    return EDL.from_dict(base)


def test_edl_from_dict_defaults():
    e = _edl()
    assert len(e.episodes) == 2 and all(isinstance(x, EDLEpisode) for x in e.episodes)
    assert e.cap == 3 and e.music is None and e.target_dur is None


def test_edl_reel_level_fields():
    e = _edl(music="MUSIC.json", cap=2, target_dur=8.0)
    assert e.music == "MUSIC.json" and e.cap == 2 and e.target_dur == 8.0


def test_edl_to_dict_round_trips():
    e = _edl(music="MUSIC.json", cap=2, target_dur=8.0)
    assert EDL.from_dict(e.to_dict()).to_dict() == e.to_dict()
    assert e.to_dict()["cap"] == 2 and e.to_dict()["music"] == "MUSIC.json"


def test_edl_null_cap_defaults_to_three():
    e = _edl(cap=None)
    assert e.cap == 3


@pytest.mark.parametrize("kw, needle", [
    (dict(episodes=[]), "at least one"),
    (dict(cap=0), "cap"),
    (dict(cap=True), "cap"),
    (dict(target_dur=-1.0), "target_dur"),
    (dict(music=""), "music"),
])
def test_edl_bad_reel_field_raises(kw, needle):
    with pytest.raises(ValueError, match=needle):
        _edl(**kw)


def test_edl_episodes_must_be_a_list():
    with pytest.raises(ValueError, match="episodes"):
        EDL.from_dict({"episodes": "nope"})


def test_edl_episode_unknown_field_names_the_key():
    bad = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="w",
               composition="lead", grid="thirds", typo=1)
    with pytest.raises(ValueError, match="episodes\\[0\\]"):
        EDL.from_dict({"episodes": [bad]})


def test_edl_from_json_roundtrip(tmp_path):
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0,
                 shot_type="wide", composition="lead", grid="thirds")], "cap": 2}))
    e = EDL.from_json(str(p))
    assert e.cap == 2 and e.episodes[0].source == "a.mp4"


def test_edl_from_json_corrupt_names_a_remedy(tmp_path):
    p = tmp_path / "EDL.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        EDL.from_json(str(p))


def test_to_markdown_renders_header_and_rows():
    e = _edl(target_dur=8.0)          # two episodes, start 0.0 and 2.0, dur 2.0 each
    md = e.to_markdown()
    assert md.startswith("# Edit plan — 2 episodes, 4.0s · target 8.0s")
    assert "| # | source | window | shot | layout | comp | grid | motion | beat | notes |" in md
    assert "| 0 | a.mp4 | 0.00–2.00 (2.00s) | wide | fill | lead | thirds | – | – |" in md


def test_to_markdown_header_omits_target_when_unset():
    md = _edl().to_markdown()         # target_dur None
    assert md.startswith("# Edit plan — 2 episodes, 4.0s\n")
    assert "target" not in md.splitlines()[0]


def test_to_markdown_shows_motion_and_beat_when_set():
    ep = dict(source="b.mp4", start=1.0, dur=3.0, shot_type="close",
              composition="center", grid="phi", motion="lateral:right", beat_slot=2,
              processing_notes="nose")
    md = EDL.from_dict({"episodes": [ep]}).to_markdown()
    assert "| 0 | b.mp4 | 1.00–4.00 (3.00s) | close | fill | center | phi | lateral:right | 2 | nose |" in md


def test_bridge_produces_a_valid_manifest():
    ep = _ep(composition="lead", grid="thirds", layout="fill", crop_scale=0.8)
    md = to_manifest_dict(ep, segment="segments/ep0_raw.mp4", out_path="out/ep0.mp4")
    md["canvas"] = [1080, 1920]                   # the driver injects this via resolve_manifest
    m = manifest_lib.Manifest.from_dict(md)       # would raise on an unknown key or a bad field
    assert manifest_lib.validate(m) == []
    assert m.segment == "segments/ep0_raw.mp4" and m.out_path == "out/ep0.mp4"
    assert m.target_dur == ep.dur and m.crop_scale == 0.8


def test_bridge_omits_canvas_delivery_and_edl_only_fields():
    ep = _ep(shot_type="wide", processing_notes="stabilize here", beat_slot=3)
    md = to_manifest_dict(ep, "s.mp4", "o.mp4")
    for k in ("canvas", "delivery", "model", "stabilize",
              "source", "start", "dur", "shot_type", "processing_notes", "beat_slot"):
        assert k not in md, f"{k} must not cross the EDL↔manifest boundary"


def test_bridge_forwards_layout_and_hero_when_set():
    # NOTE: task fixture used motion="lateral", but MOTIONS (scripts/lib/models.py) is
    # ("lateral:right", "lateral:left", "head-on", "static") — "lateral" is not a member
    # and would raise inside EDLEpisode. Swapped to the real member "lateral:right" here
    # and in the assertion below, per the task's own sanity-check instruction.
    ep = _ep(layout="insert", crop_aspect=[9, 16], rect=[0.1, 0.1, 0.8],
             motion="lateral:right", hero=[10, 20, 30, 40])
    md = to_manifest_dict(ep, "s.mp4", "o.mp4")
    assert md["layout"] == "insert" and md["crop_aspect"] == [9, 16]
    assert md["rect"] == [0.1, 0.1, 0.8] and md["motion"] == "lateral:right" and md["hero"] == [10, 20, 30, 40]


def test_bridge_omits_crop_aspect_when_none_so_manifest_auto_picks():
    md = to_manifest_dict(_ep(layout="insert"), "s.mp4", "o.mp4")   # crop_aspect defaults None
    assert "crop_aspect" not in md


def _cfg():
    return ProjectConfig(purpose="reel", canvas=[1080, 1920], delivery="native")


def test_preflight_resolves_all_episodes_clean():
    # crop_scale 0.8 gives 'lead' horizontal freedom, so validate() passes
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8)]})
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop is None
    assert len(mds) == 1 and mds[0]["canvas"] == [1080, 1920] and mds[0]["delivery"] == "native"
    assert mds[0]["segment"] == "seg/ep0_raw.mp4" and mds[0]["out_path"] == "out/ep0.mp4"


def test_preflight_stops_on_a_bad_layout_episode_naming_the_index():
    e = EDL.from_dict({"episodes": [
        dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide", composition="lead",
             grid="thirds", crop_scale=0.8),                          # ep0 fine
        dict(source="a.mp4", start=2.0, dur=2.0, shot_type="wide", composition="lead",
             grid="thirds", layout="fill", border_px=5)]})            # ep1 fill+border → LayoutSpec rejects
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "edl-invalid" and stop["finding"]["episode_idx"] == 1
    assert stop["finding"]["problems"]                                # non-empty problem list


def test_edl_cast_round_trips():
    # NOTE: task snippet used `edl.EDL(...)`/`edl.EDL.from_dict(...)`, but this file
    # imports names directly (`from scripts.lib.edl import EDL, ...`) with no `edl`
    # module alias bound anywhere — `edl.EDL(...)` raises NameError: name 'edl' is
    # not defined (confirmed by running the snippet verbatim before this fix).
    # Swapped to the unqualified names this file already uses everywhere else.
    e = EDL(episodes=(_ep(),), cast="proj/cast.json")
    assert EDL.from_dict(e.to_dict()).cast == "proj/cast.json"


def test_edl_cast_defaults_to_none():
    assert EDL(episodes=(_ep(),)).cast is None


def test_edl_cast_rejects_an_empty_string():
    with pytest.raises(ValueError, match="cast"):
        EDL(episodes=(_ep(),), cast="")


def test_episode_hero_accepts_a_track_id():
    assert _ep(hero=3).hero == 3


def test_bridge_forwards_the_cast_path():
    md = to_manifest_dict(_ep(hero="Lena"), "s.mp4", "o.mp4", cast="proj/cast.json")
    assert md["hero"] == "Lena" and md["cast"] == "proj/cast.json"


def test_bridge_omits_the_cast_when_absent():
    assert "cast" not in to_manifest_dict(_ep(), "s.mp4", "o.mp4")


def _cast_json(tmp_path, *members: dict):
    """A cast.json on disk. Descriptors are DESCRIPTOR_LEN floats — the real shape;
    a short one now stops preflight, so a fixture carrying one would make the tests
    below pass for the wrong reason."""
    p = tmp_path / "cast.json"
    p.write_text(json.dumps({"members": [
        {**m, "descriptor": list(m["descriptor"])
                            + [0.0] * (DESCRIPTOR_LEN - len(m["descriptor"]))}
        for m in members]}))
    return p


def test_preflight_resolves_a_cast_name_hero_via_the_registry(tmp_path):
    p = _cast_json(tmp_path, {"name": "Lena", "descriptor": [1.0, 1.1, 1.2]})
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8, hero="Lena")],
                       "cast": str(p)})
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop is None
    assert mds[0]["hero"] == "Lena" and mds[0]["cast"] == str(p)


def test_preflight_stops_on_a_stale_cast_descriptor(tmp_path):
    # preflight's docstring sells "fail in ms, before any ffmpeg". It did not: a
    # descriptor of the wrong length (a cast.json built under a different
    # DESCRIPTOR_LEN — e.g. a pre-2026-08-04 24-d colour histogram) passed
    # Cast.from_json, hero.resolve and validate() — stop was None — and blew
    # up later in track.build_route, after every window had been cut. The registry
    # load is the boundary, so the stop must come from there: episode_idx is None
    # (the cast is reel-level, not one episode's fault) and the remedy names intake.
    p = tmp_path / "cast.json"
    p.write_text(json.dumps({"members": [{"name": "Lena", "descriptor": [100.0, 110.0, 120.0]}]}))
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8, hero="Lena")],
                       "cast": str(p)})
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["episode_idx"] is None
    assert any("footage-intake" in msg for msg in stop["finding"]["problems"]), stop


def test_preflight_stops_when_the_cast_name_is_not_registered(tmp_path):
    # NOTE: asserting only "Ghost" in the problem text is a false-positive trap — hero.resolve's
    # OTHER raise site ("hero 'Ghost' is a cast name but no cast.json was supplied") also embeds
    # the queried name, so it would pass even if preflight never loaded the registry at all
    # (confirmed: this happened before the cast=cast wiring below was added). Asserting "Lena"
    # (the real registered member) appears too proves the registry was actually loaded and
    # consulted, not just that a hero-name error of some kind was raised.
    p = _cast_json(tmp_path, {"name": "Lena", "descriptor": [1.0, 2.0, 3.0]})
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8, hero="Ghost")],
                       "cast": str(p)})
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["episode_idx"] == 0
    assert any("Ghost" in msg and "Lena" in msg and "known names" in msg
              for msg in stop["finding"]["problems"])


def test_preflight_cast_json_missing_file_stops_gracefully_naming_no_episode(tmp_path):
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8)],
                       "cast": str(tmp_path / "does_not_exist.json")})
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "edl-invalid" and stop["finding"]["episode_idx"] is None
    assert mds == []


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_preflight_cast_json_malformed_shape_stops_gracefully_not_crashes(tmp_path, body):
    # A syntactically-valid cast.json whose TOP LEVEL is not an object (a bare array/
    # string/number/bool/null) once reached Cast.from_dict's `d.get("members", [])` and
    # raised a bare AttributeError — an exception preflight's (OSError, ValueError) does
    # not catch, crashing the one gate that promises never to. Fixed at the source:
    # Cast.from_dict now guards its own top level and raises ValueError-with-remedy, so
    # preflight catches it like any other bad input. Asserting the remedy text (not just
    # "some stop happened") is what pins that: a laundered AttributeError string would
    # carry no 'members'/re-run remedy, so this fails if the from_dict guard is removed.
    p = tmp_path / "cast.json"
    p.write_text(body)
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8)],
                       "cast": str(p)})
    mds, stop = preflight(e, _cfg(), "seg", "out")     # must not raise
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "edl-invalid" and stop["finding"]["episode_idx"] is None
    assert mds == []
    problem = stop["finding"]["problems"][0]
    assert "is unreadable" in problem                      # preflight's own framing
    assert "expected a cast.json object with a 'members' list" in problem   # from_dict's remedy
    assert "re-run footage-intake" in problem
    assert "AttributeError" not in problem and "has no attribute" not in problem


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_edl_from_dict_rejects_a_non_object_top_level(d, name):
    # EDL.from_dict validated its NESTED input (episodes is a list, each an object) but not its
    # own `d` — a valid-JSON-but-wrong-shape top level reached d.get("episodes") and raised a
    # bare AttributeError. Both production readers (edl_to_reel.py:25, draft.py:38) call
    # EDL.from_json with no except, so it crashed the driver. coding-standards: wrong-type
    # construction raises ValueError with the remedy in the message.
    with pytest.raises(ValueError) as ei:
        EDL.from_dict(d)
    msg = str(ei.value)
    assert "expected an EDL.json object" in msg          # what was expected
    assert f"got {name}" in msg                          # what actually arrived
    assert "re-run edit-plan" in msg                     # the remedy
    assert "has no attribute" not in msg                 # not a laundered AttributeError


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_edl_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "EDL.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run edit-plan"):
        EDL.from_json(p)


# --- colour-as-a-stage Task 9: EDLEpisode carries the nine colour fields ---

def test_edlepisode_colour_round_trips():
    e = _ep(white_balance=0.5, black_point=0.1, saturation=1.2,
            tone_src=(30, 100, 148), tone_dst=(35, 110, 150))
    d = e.to_dict()
    assert d["white_balance"] == 0.5 and d["tone_src"] == [30, 100, 148]
    md = to_manifest_dict(e, "seg.mp4", "out.mp4")
    assert md["white_balance"] == 0.5 and md["saturation"] == 1.2 and md["tone_dst"] == [35, 110, 150]


def test_edlepisode_colour_defaults_omit_tone():
    d = _ep().to_dict()
    assert d["white_balance"] == 0.0 and d["saturation"] == 1.0 and "tone_src" not in d


def test_tone_pair_coerces_to_tuples_from_json_arrays():
    # an EDL loaded from JSON carries tone_src/tone_dst as LISTS; __post_init__ must
    # coerce them to tuples so an EDLEpisode round-trips (like hero/crop_aspect/rect
    # at test_json_arrays_coerce_to_tuples above).
    ep = _ep(tone_src=[30, 100, 148], tone_dst=[35, 110, 150])
    assert ep.tone_src == (30, 100, 148) and isinstance(ep.tone_src, tuple)
    assert ep.tone_dst == (35, 110, 150) and isinstance(ep.tone_dst, tuple)
    assert EDLEpisode(**ep.to_dict()) == ep   # full round-trip equality


# --- attested-run Task 1: EDL.provenance (design docs/specs/2026-08-04-attested-run-design.md §4) ---
# NOTE: the task brief's snippet used `_ep()` inside an `EDL.from_dict({"episodes": [_ep()], ...})`
# call, but this file's `_ep()` returns a constructed EDLEpisode object, not a dict — EDL.from_dict
# requires each `episodes[i]` to be a dict (it raises "must be an object" otherwise; confirmed by
# running the snippet verbatim before this fix). `_edl(**kw)` (above) is this file's existing
# helper for exactly this shape: a minimal 2-episode EDL.from_dict payload with reel-level fields
# overridden via **kw — the same helper test_edl_reel_level_fields/test_edl_bad_reel_field_raises
# already use. Swapped to it here.

def test_edl_round_trips_a_provenance_block():
    e = _edl(provenance={"v": 1, "self": "abc"})
    assert e.provenance == {"v": 1, "self": "abc"}
    assert e.to_dict()["provenance"] == {"v": 1, "self": "abc"}


def test_edl_without_provenance_emits_no_key():
    assert "provenance" not in _edl().to_dict()


def test_edl_refuses_a_non_dict_provenance():
    with pytest.raises(ValueError, match="EDL.provenance"):
        _edl(provenance="nope")


# --- attested-run Task 2: write_edl (the one EDL.json writer chokepoint) + from_json's
# tampered-EDL refusal (design docs/specs/2026-08-04-attested-run-design.md §4/§5)
# NOTE: the task brief's snippets write `EDL.from_dict({"episodes": [_ep()]})`, but (as
# Task 1's tests above already found) `_ep()` returns a constructed EDLEpisode OBJECT,
# not a dict — EDL.from_dict requires each `episodes[i]` to be a dict. `_edl(**kw)` is
# this file's existing helper for exactly this shape (a valid multi-episode EDL via
# EDL.from_dict); swapped to it below wherever the brief built an EDL through
# from_dict. `test_from_json_still_loads_a_hand_authored_unstamped_edl` writes RAW json
# directly (never goes through EDL.from_dict/EDL()) to simulate hand authorship, so it
# needs a JSON-serializable episode dict instead — `_ep().to_dict()` is that same
# episode's dict form.

def test_write_edl_stamps_and_from_json_reads_it_back_intact(tmp_path):
    from scripts.lib import edl as edl_mod, provenance
    e = _edl()
    p = tmp_path / "EDL.json"
    edl_mod.write_edl(e, p)
    assert provenance.check(json.loads(p.read_text()))[0] == "intact"
    assert edl_mod.EDL.from_json(p).provenance["self"]


def test_write_edl_records_the_selection_digest(tmp_path):
    from scripts.lib import edl as edl_mod, provenance
    sel = tmp_path / "selection.json"
    sel.write_text('{"episodes": []}')
    p = tmp_path / "EDL.json"
    edl_mod.write_edl(_edl(), p, selection=sel)
    block = json.loads(p.read_text())["provenance"]
    assert block["inputs"]["selection"] == provenance.digest_file(sel)


def test_from_json_refuses_an_edl_edited_after_the_tool_wrote_it(tmp_path):
    from scripts.lib import edl as edl_mod
    p = tmp_path / "EDL.json"
    edl_mod.write_edl(_edl(), p)
    d = json.loads(p.read_text())
    d["cap"] = 9                                   # raw-JSON surgery
    p.write_text(json.dumps(d, indent=2))
    with pytest.raises(ValueError, match="selection.json"):
        edl_mod.EDL.from_json(p)


def test_from_json_still_loads_a_hand_authored_unstamped_edl(tmp_path):
    # edl_to_reel's documented SP1 front door: absence is legal, tampering is not
    from scripts.lib import edl as edl_mod
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [_ep().to_dict()]}, indent=2))
    assert edl_mod.EDL.from_json(p).provenance == {}


def test_a_rewritten_edl_restamps_rather_than_going_stale(tmp_path):
    from scripts.lib import edl as edl_mod, provenance
    p = tmp_path / "EDL.json"
    e = _edl()
    edl_mod.write_edl(e, p)
    e2 = edl_mod.EDL.from_json(p)
    e2.cap = 5                                     # a TOOL changing the EDL
    edl_mod.write_edl(e2, p)
    assert provenance.check(json.loads(p.read_text()))[0] == "intact"


# --- mood-preset-variety Task 4: EDL.variety (design docs/specs/2026-08-06-mood-preset-variety-design.md §9)

def test_edl_carries_a_variety_report_and_round_trips():
    r = moodpreset.evaluate({"close": 11, "medium": 0, "wide": 40},
                            {"close": 0, "medium": 0, "wide": 8}, 2.0,
                            moodpreset.resolve("fun"), waiver="close windows are soft")
    e = EDL(episodes=(_ep(),), variety=r)
    back = EDL.from_dict(e.to_dict())
    assert back.variety.to_dict() == r.to_dict()


def test_edl_without_a_variety_report_round_trips_as_none():
    # a hand-authored EDL through edl_to_reel's SP1 front door was never evaluated
    e = EDL(episodes=(_ep(),))
    assert e.to_dict()["variety"] is None
    assert EDL.from_dict(e.to_dict()).variety is None


def test_edl_refuses_a_variety_field_that_is_not_a_report():
    with pytest.raises(ValueError, match="variety"):
        EDL(episodes=(_ep(),), variety={"preset": "fun"})


def test_markdown_prints_available_against_used_and_the_waiver():
    r = moodpreset.evaluate({"close": 11, "medium": 0, "wide": 40},
                            {"close": 0, "medium": 0, "wide": 8}, 2.0,
                            moodpreset.resolve("fun"), waiver="close windows are soft")
    md = EDL(episodes=(_ep(),), variety=r).to_markdown()
    assert "## Variety" in md
    assert "fun" in md and "close" in md and "11" in md
    assert "close windows are soft" in md


# --- editorial-constraints Task 3: EDL.constraints (design docs/specs/2026-08-07-editorial-constraints-design.md §8)

def _report(ok=True):
    rules = ({"kind": "no_repeat", "stated": "эпизоды не должны повторяться"},)
    vio = () if ok else (Violation(rule_index=0, kind="no_repeat",
                                   stated="эпизоды не должны повторяться",
                                   message="episodes 0, 1 are all from A.mp4 [0.00s–10.00s]"),)
    return ConstraintReport(rules=rules, violations=vio)


def test_edl_carries_the_constraint_report_through_a_round_trip():
    edl = EDL(episodes=(_ep(),), constraints=_report())
    back = EDL.from_dict(edl.to_dict())
    assert back.constraints == _report() and back.constraints.ok


def test_edl_without_constraints_round_trips_as_none():
    # None means NOT EVALUATED (no CONSTRAINTS.json), never "passed" — the SP1
    # hand-authored front door lands here.
    edl = EDL(episodes=(_ep(),))
    assert edl.to_dict()["constraints"] is None
    assert EDL.from_dict(edl.to_dict()).constraints is None


def test_edl_rejects_a_non_report_constraints_value():
    with pytest.raises(ValueError, match="ConstraintReport"):
        EDL(episodes=(_ep(),), constraints={"rules": []})


def test_markdown_lists_the_rules_and_says_they_held():
    md = EDL(episodes=(_ep(),), constraints=_report()).to_markdown()
    assert "## Editorial rules" in md
    assert "эпизоды не должны повторяться" in md and "no_repeat" in md
    assert "1 checked, none broken" in md


def test_markdown_shows_a_broken_rule():
    md = EDL(episodes=(_ep(),), constraints=_report(ok=False)).to_markdown()
    assert "**Broken:**" in md and "episodes 0, 1" in md


def test_markdown_omits_the_section_when_there_are_no_rules():
    md = EDL(episodes=(_ep(),), constraints=ConstraintReport()).to_markdown()
    assert "## Editorial rules" not in md


# --- subject-anchored-moves Task 9: EDLEpisode.zoom + the manifest-dict bridge
# (design docs/specs/2026-08-08-subject-anchored-moves-design.md §7) ---

def test_edl_episode_carries_a_zoom():
    e = _ep(zoom={"from": 1.0, "to": 0.7})
    assert e.zoom == {"from": 1.0, "to": 0.7}


def test_edl_episode_defaults_to_no_zoom():
    # zoom must round-trip and render exactly as before when absent (task brief)
    assert _ep().zoom is None


def test_edl_episode_round_trips_a_zoom():
    # EDLEpisode has no from_dict of its own (see test_edl_episode_round_trips_the_background_colour
    # above) — round-trip through the constructor, same as every other field here.
    e = _ep(zoom={"from": 1.0, "to": 0.7})
    assert e.to_dict()["zoom"] == {"from": 1.0, "to": 0.7}
    assert EDLEpisode(**e.to_dict()) == e


def test_edl_markdown_names_the_zoom_beside_the_motion():
    # NOTE: the task brief's snippet passed EDL(..., canvas=..., delivery=...), but
    # EDL has neither field (only episodes/music/cast/cap/target_dur/variety/
    # constraints/provenance — see the dataclass above); those two arguments would
    # raise TypeError. Dropped them, matching test_edl_markdown_renders_a_pan_in_the_motion_column's
    # shape exactly (motion column keyed off the real header, not a hardcoded index).
    md = EDL(episodes=(_ep(zoom={"from": 1.0, "to": 0.7}),)).to_markdown()
    assert _motion_cell(md, "| 0 |") == "zoom 1.0→0.7"


def test_edl_markdown_shows_both_a_motion_and_its_zoom():
    # catches the `motion == "–" else f"{motion} · {zm}"` else-branch going untested —
    # without this, only the "zoom alone" arm would ever be exercised.
    md = EDL(episodes=(_ep(motion="static", zoom={"from": 1.0, "to": 0.7}),)).to_markdown()
    assert _motion_cell(md, "| 0 |") == "static · zoom 1.0→0.7"


def test_manifest_dict_carries_the_zoom_through():
    # NOTE: the task brief's snippet called to_manifest_dict(ep, canvas=..., delivery=...,
    # segment=..., out_path=..., target_dur=...) — none of canvas/delivery/target_dur are
    # parameters of the real function (`to_manifest_dict(ep, segment, out_path, cast=None)`,
    # see the import at the top of this file and test_to_manifest_dict_carries_the_pan_across
    # above for the established call shape). Matched the real signature; kept the assertion.
    md = to_manifest_dict(_ep(zoom={"from": 1.0, "to": 0.7}), "seg.mp4", "out.mp4")
    assert md["zoom"] == {"from": 1.0, "to": 0.7}


def test_to_manifest_dict_omits_an_absent_zoom():
    # the established idiom (see test_to_manifest_dict_omits_an_absent_pan): omit rather
    # than carry an explicit null, so Manifest.from_dict falls to its own None default.
    assert "zoom" not in to_manifest_dict(_ep(), "seg.mp4", "out.mp4")


def test_to_manifest_dict_carries_an_empty_zoom_across():
    # `is not None`, not truthiness (see test_to_manifest_dict_carries_an_empty_pan_across):
    # an empty dict is FALSY, so `if ep.zoom:` would silently drop a malformed zoom and the
    # manifest gate would never see it to report the problem.
    assert to_manifest_dict(_ep(zoom={}), "seg.mp4", "out.mp4")["zoom"] == {}
