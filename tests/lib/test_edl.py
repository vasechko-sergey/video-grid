import json

import pytest
from scripts.lib.edl import EDL, EDLEpisode, to_manifest_dict
from scripts.lib import manifest as manifest_lib
from scripts.lib.manifest import DEFAULT_COLOR


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
