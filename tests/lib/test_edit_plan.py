import pytest
from scripts import edit_plan
from scripts.lib.footage import FootageClip, FootageWindow


def _clip(**kw):
    d = dict(source="MVI_3739.mp4", dur=22.0, res=(1920, 1080), fps=30.0,
             windows=[FootageWindow(start=2.1, dur=4.0, shot_type="close", people=1,
                                    motion=0.4, shake=0.01, description="lena nose")])
    d.update(kw)
    return FootageClip(**d)


def test_window_to_episode_copies_mechanical_fields_by_reference():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds")
    assert ep.source == "MVI_3739.mp4"                      # from the parent clip
    assert ep.start == 2.1 and ep.dur == 4.0                # from the window, not retyped
    assert ep.shot_type == "close"                          # window.shot_type default
    assert ep.processing_notes == "lena nose"                # window.description seed
    assert ep.composition == "lead" and ep.grid == "thirds"


def test_window_to_episode_forwards_editorial_and_overrides_defaults():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center", grid="phi",
                                     layout="insert", motion="lateral:right", hero=[10, 20, 30, 40],
                                     shot_type="wide", processing_notes="custom")
    assert ep.layout == "insert" and ep.motion == "lateral:right" and ep.hero == (10, 20, 30, 40)
    assert ep.shot_type == "wide"                           # editorial override wins over window default
    assert ep.processing_notes == "custom"


def test_window_to_episode_unknown_editorial_key_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="bogus"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds", bogus=1)


def test_window_to_episode_missing_required_composition_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="composition"):
        edit_plan.window_to_episode(clip, clip.windows[0], grid="thirds")
