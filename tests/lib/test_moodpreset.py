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


def _counts(close=0, medium=0, wide=0):
    return {"close": close, "medium": medium, "wide": wide}


def test_evaluate_flags_a_size_the_preset_wants_and_the_footage_offers():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"))
    assert r.gaps == ("close",)
    assert r.ok is False
    assert r.available["close"] == 11 and r.used["close"] == 0


def test_evaluate_is_silent_when_the_footage_cannot_offer_the_size():
    # 2 close windows is below MIN_AVAIL — one stray misdetection must not block a reel
    r = moodpreset.evaluate(_counts(close=2, wide=40), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"))
    assert r.gaps == () and r.ok is True


def test_evaluate_is_silent_at_the_min_avail_boundary_and_fires_one_above():
    fun = moodpreset.resolve("fun")
    assert moodpreset.evaluate(_counts(close=2, wide=9), _counts(wide=3), 2.0, fun).gaps == ()
    assert moodpreset.evaluate(_counts(close=3, wide=9), _counts(wide=3), 2.0, fun).gaps == ("close",)


def test_evaluate_ignores_a_size_the_preset_barely_wants():
    # a shot_mix share below WANT_FLOOR is reported, never refused
    quiet = moodpreset.MoodPreset("quiet", None, {"close": 0.10, "medium": 0.45, "wide": 0.45},
                                  (2.0, 4.0))
    r = moodpreset.evaluate(_counts(close=20, wide=40), _counts(wide=8), 2.0, quiet)
    assert r.gaps == ()


def test_evaluate_fires_exactly_at_the_want_floor_boundary():
    # WANT_FLOOR (0.20) is inclusive: >= WANT_FLOOR, not > WANT_FLOOR. The nearby
    # test_evaluate_ignores_a_size_the_preset_barely_wants only pins 0.10 — well below
    # the floor — so the boundary value itself was unpinned until now.
    at_floor = moodpreset.MoodPreset("at_floor", None,
                                     {"close": 0.20, "medium": 0.40, "wide": 0.40}, (2.0, 4.0))
    r = moodpreset.evaluate(_counts(close=20, wide=40), _counts(wide=8), 2.0, at_floor)
    assert r.gaps == ("close",)


def test_evaluate_is_silent_just_below_the_want_floor_boundary():
    # the twin of the case above, one hundredth under the floor: no gap.
    below_floor = moodpreset.MoodPreset("below_floor", None,
                                        {"close": 0.19, "medium": 0.40, "wide": 0.41}, (2.0, 4.0))
    r = moodpreset.evaluate(_counts(close=20, wide=40), _counts(wide=8), 2.0, below_floor)
    assert r.gaps == ()


def test_evaluate_does_not_flag_a_size_the_cut_already_uses():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(close=1, wide=8), 2.0,
                            moodpreset.resolve("fun"))
    assert r.gaps == ()


def test_a_waiver_makes_a_gapped_report_ok_without_erasing_the_gap():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"), waiver="every close window is out of focus")
    assert r.gaps == ("close",)          # the finding survives — it is recorded, not deleted
    assert r.ok is True


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_waiver_is_refused(blank):
    with pytest.raises(ValueError, match="waiver"):
        moodpreset.evaluate(_counts(close=11), _counts(wide=8), 2.0,
                            moodpreset.resolve("fun"), waiver=blank)


def test_report_round_trips_through_json():
    r = moodpreset.evaluate(_counts(close=11, wide=40), _counts(wide=8), 2.5,
                            moodpreset.resolve("fun"), waiver="deliberate")
    assert moodpreset.VarietyReport.from_dict(r.to_dict()).to_dict() == r.to_dict()


def test_gaps_are_reported_in_shot_type_order():
    bare = moodpreset.MoodPreset("bare", None, {"close": 0.34, "medium": 0.33, "wide": 0.33},
                                 (1.0, 5.0))
    r = moodpreset.evaluate(_counts(close=5, medium=5, wide=5), _counts(wide=3), 2.0, bare)
    assert r.gaps == ("close", "medium")
