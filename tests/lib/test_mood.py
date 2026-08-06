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


def test_moodvector_from_dict_missing_key_raises():
    with pytest.raises(ValueError, match="missing key"):
        MoodVector.from_dict({"energy": 0.5, "brightness": 0.5})   # no "pace"


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


from scripts.lib.mood import mood_target


def test_mood_target_single_anchor():
    assert mood_target("energetic") == MOOD_ANCHORS["energetic"]


def test_mood_target_averages_multiple():
    t = mood_target("energetic dark")
    e, d = MOOD_ANCHORS["energetic"], MOOD_ANCHORS["dark"]
    assert t == MoodVector((e.energy + d.energy) / 2,
                           (e.brightness + d.brightness) / 2,
                           (e.pace + d.pace) / 2)


def test_mood_target_case_insensitive():
    assert mood_target("ENERGETIC") == MOOD_ANCHORS["energetic"]


def test_mood_target_ignores_punctuation_and_filler():
    assert mood_target("energetic, and driving!") == mood_target("energetic driving")


def test_mood_target_synonym_resolves():
    assert mood_target("mellow") == MOOD_ANCHORS["mellow"]


def test_mood_target_zero_match_returns_none():
    assert mood_target("purple wombat") is None


def test_mood_target_empty_returns_none():
    assert mood_target("") is None


from scripts.lib.mood import distance, rank, rank_by_drive


def test_distance_identical_is_zero():
    v = MoodVector(0.5, 0.5, 0.5)
    assert distance(v, v) == 0.0


def test_distance_known_pair():
    assert distance(MoodVector(0.0, 0.0, 0.0), MoodVector(1.0, 0.0, 0.0)) == 1.0


def test_distance_weights_scale_one_axis():
    a, b = MoodVector(0.0, 0.0, 0.0), MoodVector(1.0, 0.0, 0.0)
    assert distance(a, b, weights=(4.0, 1.0, 1.0)) == 2.0     # sqrt(4 * 1) = 2


def test_rank_orders_ascending_by_distance():
    target = MoodVector(1.0, 1.0, 1.0)
    cands = [("far", MoodVector(0.0, 0.0, 0.0)), ("near", MoodVector(0.9, 0.9, 0.9))]
    assert [n for n, _d, _v in rank(cands, target)] == ["near", "far"]


def test_rank_stable_on_ties():
    target = MoodVector(0.0, 0.0, 0.0)
    a, b = MoodVector(0.5, 0.0, 0.0), MoodVector(0.5, 0.0, 0.0)   # equidistant
    assert [n for n, _d, _v in rank([("a", a), ("b", b)], target)] == ["a", "b"]


def test_rank_empty():
    assert rank([], MoodVector(0.5, 0.5, 0.5)) == []


def test_rank_by_drive_orders_by_energy_plus_pace_desc():
    lo = MoodVector(0.1, 0.9, 0.1)     # drive 0.2
    hi = MoodVector(0.8, 0.0, 0.7)     # drive 1.5
    ranked = rank_by_drive([("lo", lo), ("hi", hi)])
    assert [n for n, _s, _v in ranked] == ["hi", "lo"]
    assert ranked[0][1] == pytest.approx(1.5)      # positive drive in the score slot


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_moodvector_from_dict_rejects_a_non_object_top_level(d, name):
    # `k not in d` raised a bare TypeError on a scalar top level and mis-reported a list/str
    # one as "missing key(s)". No production reader (MoodVector is built by beats.mood_features
    # and serialized into MUSIC_SHORTLIST via to_dict), but from_dict is public contract
    # surface and owes ValueError-with-remedy per coding-standards.
    with pytest.raises(ValueError) as ei:
        MoodVector.from_dict(d)
    msg = str(ei.value)
    assert "expected a mood-vector object" in msg
    assert f"got {name}" in msg
    assert "re-run music-match" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


from scripts.lib import mood


def test_the_real_brief_vocabulary_now_matches_an_anchor():
    # 'fun and playful' matched NO anchor before 2026-08-06 and fell into the
    # drive-ranking fallback — the music ranking was running blind on the real run
    assert mood.mood_target("fun and playful") is not None
    for token in ("fun", "playful", "nostalgic", "adventure"):
        assert token in mood.MOOD_ANCHORS
