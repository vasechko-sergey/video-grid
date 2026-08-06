import pytest

from scripts.lib import mood, moodpreset
from scripts.lib.footage import SHOT_TYPES


def test_every_shipped_preset_is_a_valid_distribution():
    for p in (*moodpreset.PRESETS, moodpreset.BALANCED):
        assert set(p.shot_mix) == set(SHOT_TYPES)
        assert abs(sum(p.shot_mix.values()) - 1.0) < 1e-6
        assert 0.0 < p.asl[0] < p.asl[1]


def test_preset_refuses_a_mix_that_is_not_a_distribution():
    with pytest.raises(ValueError, match="sum to 1.0"):
        moodpreset.MoodPreset("x", None, {"close": 0.5, "medium": 0.4, "wide": 0.4}, (1.0, 2.0))


def test_preset_refuses_unknown_or_missing_mix_keys():
    with pytest.raises(ValueError, match="shot_mix keys"):
        moodpreset.MoodPreset("x", None, {"close": 0.5, "wide": 0.5}, (1.0, 2.0))


def test_preset_refuses_an_inverted_asl_band():
    with pytest.raises(ValueError, match="asl"):
        moodpreset.MoodPreset("x", None, {"close": 0.3, "medium": 0.3, "wide": 0.4}, (4.0, 2.0))


@pytest.mark.parametrize("text,expected", [
    ("fun and playful", "fun"),
    ("epic adventure", "epic"),
    ("dark and brooding", "moody"),
    ("nostalgic", "nostalgic"),
])
def test_resolve_picks_the_nearest_named_preset(text, expected):
    assert moodpreset.resolve(text).name == expected


@pytest.mark.parametrize("text", [None, "", "   ", "xyzzy plugh"])
def test_resolve_falls_back_to_balanced_when_nothing_matches(text):
    assert moodpreset.resolve(text).name == "balanced"


def test_balanced_is_never_a_match_target():
    # it is the fallback only — a mid-range anchor in the search would swallow
    # every mood sitting between the four named ones
    assert moodpreset.BALANCED not in moodpreset.PRESETS
    assert moodpreset.BALANCED.anchor is None
    assert all(p.anchor is not None for p in moodpreset.PRESETS)


def test_balanced_still_asks_for_close_ups():
    # the autonomous path (no SPEC.json) must not get a dead gate
    assert moodpreset.BALANCED.shot_mix["close"] >= 0.20
