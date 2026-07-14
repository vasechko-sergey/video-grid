import pytest

from scripts.lib.mood import (MoodVector, MOOD_ANCHORS, norm01,
                              PACE_BPM, BRIGHT_HZ, ENERGY_RMS)


def test_moodvector_roundtrip():
    v = MoodVector(0.9, 0.7, 0.85)
    assert v.as_tuple() == (0.9, 0.7, 0.85)
    assert MoodVector.from_dict(v.to_dict()) == v


def test_moodvector_rejects_out_of_range():
    with pytest.raises(ValueError, match=r"energy.*\[0, 1\]"):
        MoodVector(1.5, 0.5, 0.5)


def test_moodvector_rejects_bool():
    with pytest.raises(ValueError):
        MoodVector(True, 0.5, 0.5)


def test_moodvector_rejects_non_number():
    with pytest.raises(ValueError):
        MoodVector("hi", 0.5, 0.5)


def test_norm01_endpoints_midpoint_and_clamp():
    assert norm01(60, 60, 180) == 0.0
    assert norm01(180, 60, 180) == 1.0
    assert norm01(120, 60, 180) == 0.5
    assert norm01(30, 60, 180) == 0.0        # below lo clamps
    assert norm01(240, 60, 180) == 1.0       # above hi clamps


def test_norm01_requires_hi_gt_lo():
    with pytest.raises(ValueError):
        norm01(1, 5, 5)


def test_refs_are_ordered_pairs():
    for lo, hi in (PACE_BPM, BRIGHT_HZ, ENERGY_RMS):
        assert hi > lo


def test_anchors_all_valid_and_lowercase():
    assert MOOD_ANCHORS
    for name, v in MOOD_ANCHORS.items():
        assert name == name.lower() and name.isalpha()
        assert isinstance(v, MoodVector)     # __post_init__ already validated its ranges


def test_anchor_families_present():
    for w in ("energetic", "chill", "epic", "dark", "happy",
              "melancholic", "dreamy", "tense"):
        assert w in MOOD_ANCHORS
