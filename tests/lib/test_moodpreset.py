import pytest

from scripts.lib import carve, mood, moodpreset
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


# --- MoodPreset.look: the reel's default finish (design 2026-08-13 §6) --------------

from scripts.lib.look import LookSpec
from scripts.lib.moodpreset import BALANCED, PRESETS, MoodPreset, resolve


def test_every_preset_carries_a_look():
    for p in (*PRESETS, BALANCED):
        assert isinstance(p.look, LookSpec)


def test_the_fallback_applies_no_vignette():
    # This field is defence in depth, not the mechanism (corrected post-review,
    # final-findings.md I-2): write_edit_plan — not MoodPreset — is what keeps a
    # brief-less run's output unchanged, by passing look=None to build_edl whenever
    # resolve() falls back to BALANCED (see tests/lib/test_edit_plan.py's
    # test_write_edit_plan_leaves_the_look_unauthored_when_no_mood_matches). Filling
    # THIS field with anything but identity would still be a change for a caller who
    # reads MoodPreset.look directly, bypassing that check: a real fade imposes a
    # TASTE nobody chose, and even fade=0.0 would reach build_reel as an AUTHORED
    # zero and switch off mix's own audio bookend. (BALANCED must not disable a
    # quality GATE either — that is why its shot_mix keeps a real close share. The
    # two rows read opposite because a gate and a look are different kinds of thing.)
    assert BALANCED.look == LookSpec()


def test_moody_is_the_heaviest_look():
    assert resolve("dark and moody").look == LookSpec(vignette=0.40, fade=1.0)


def test_look_must_be_a_lookspec():
    with pytest.raises(ValueError, match="MoodPreset.look must be a LookSpec"):
        MoodPreset("x", None, {"close": 0.3, "medium": 0.4, "wide": 0.3}, (1.0, 2.0),
                   look={"vignette": 0.3})


def test_every_preset_carries_a_tone_bias_and_balanced_carries_none():
    """The bias is a taste, so the no-match fallback must not have one — the same
    rule BALANCED.look already states: a skipped brief must not silently impose a
    look (design 2026-08-17 §1)."""
    assert moodpreset.BALANCED.tone_bias == (0.0, 0.0, 0.0)
    assert {p.name: p.tone_bias for p in moodpreset.PRESETS} == {
        "fun": (10.0, 18.0, 8.0),
        "epic": (-16.0, 0.0, 16.0),
        "moody": (-18.0, -16.0, -8.0),
        "nostalgic": (20.0, 0.0, -18.0),
    }


def test_tone_bias_must_be_three_numbers():
    with pytest.raises(ValueError, match="tone_bias"):
        moodpreset.MoodPreset("x", None, {"close": 0.3, "medium": 0.4, "wide": 0.3},
                              (1.0, 2.0), tone_bias=(1.0, 2.0))


_FLOOR_PRESET = moodpreset.MoodPreset(
    "deep", None, {"close": 0.3, "medium": 0.4, "wide": 0.3}, (2.5, 5.0))


def test_reconcile_refuses_a_preset_floor_below_the_carved_floor():
    # The preset wants shots down to 2.5s; nothing in FOOTAGE.json is shorter
    # than 3.0s, and no stage splits a window.
    msg = moodpreset.reconcile_band(_FLOOR_PRESET, (3.0, 4.0))
    assert msg is not None
    assert "2.5" in msg and "3.0" in msg and "--win-min" in msg


def test_reconcile_allows_a_preset_ceiling_above_the_carved_ceiling():
    # edit_plan JOINS adjacent windows (span merge), so a taller ceiling is
    # always reachable — the run's own 5.80s episode against a 4.0s carve
    # proves it (design 2026-09-03 §0.3). Refusing here would be wrong.
    assert moodpreset.reconcile_band(_FLOOR_PRESET, (1.2, 4.0)) is None


def test_reconcile_allows_an_exactly_equal_floor():
    assert moodpreset.reconcile_band(_FLOOR_PRESET, (2.5, 4.0)) is None


def test_reconcile_is_silent_without_a_carved_band():
    # A legacy FOOTAGE.json: uncheckable, and the caller says so out loud.
    assert moodpreset.reconcile_band(_FLOOR_PRESET, None) is None


def test_reconcile_never_fires_at_the_shipped_defaults():
    # Honest scope (design §4): at carve.DEFAULT_BAND every shipped preset passes,
    # so this check goes live only when an operator raises --win-min.
    for p in moodpreset.PRESETS + (moodpreset.BALANCED,):
        assert moodpreset.reconcile_band(p, carve.DEFAULT_BAND) is None


# --- VarietyReport.unmeasured: the census's blind spot (design 2026-09-10) ----------


def _variety(unmeasured=0):
    return moodpreset.VarietyReport(preset="fun", available=_counts(close=1, medium=1, wide=8),
                                    used=_counts(close=1, wide=1), asl=2.0, asl_band=(1.0, 3.0),
                                    unmeasured=unmeasured)


def test_variety_unmeasured_round_trips_and_defaults_to_zero():
    r = _variety(unmeasured=6)
    assert moodpreset.VarietyReport.from_dict(r.to_dict()).unmeasured == 6
    # an EDL.json written before 2026-09-10 carries no key at all
    d = r.to_dict()
    del d["unmeasured"]
    assert moodpreset.VarietyReport.from_dict(d).unmeasured == 0
    # an EDL.json written by a version that DOES emit the key, but as an explicit
    # JSON null (e.g. a writer that always serializes every field). `from_dict` uses
    # `d.get("unmeasured") or 0` rather than `d.get("unmeasured", 0)` for exactly this
    # case -- `or 0` treats a present-but-None value the same as an absent one, so
    # neither reaches `__post_init__`'s type check as `None`.
    d_null = r.to_dict()
    d_null["unmeasured"] = None
    assert moodpreset.VarietyReport.from_dict(d_null).unmeasured == 0


def test_variety_unmeasured_refuses_to_exceed_the_census_it_is_a_subset_of():
    with pytest.raises(ValueError, match="exceeds the 10 windows"):
        _variety(unmeasured=11)


def test_variety_unmeasured_allows_the_exact_census_total():
    # the refusal is a strict `>`, so `unmeasured == total` must PASS: every window in
    # `available` (10, from _counts(close=1, medium=1, wide=8)) coming back unmeasured
    # is a legitimate (if extreme) reading, not an overflow.
    r = _variety(unmeasured=10)
    assert r.unmeasured == 10


def test_variety_unmeasured_refuses_a_non_int():
    with pytest.raises(ValueError, match="unmeasured must be an int"):
        _variety(unmeasured=2.5)


def test_variety_unmeasured_refuses_a_bool():
    # isinstance(True, int) is True in Python, which is why the guard checks bool
    # explicitly ahead of the int check -- this must be pinned separately from the
    # plain non-int case above, or a guard that dropped the isinstance(..., bool)
    # clause would still pass every other test.
    with pytest.raises(ValueError, match="unmeasured must be an int"):
        _variety(unmeasured=True)


def test_variety_unmeasured_refuses_a_negative_int():
    with pytest.raises(ValueError, match="unmeasured must be an int"):
        _variety(unmeasured=-1)


def test_evaluate_carries_unmeasured_through_without_touching_the_gaps():
    # the gate still judges only what it COULD measure (design 2026-09-10 §2.2). The
    # census below deliberately makes `close` a REAL gap -- available["close"] clears
    # MIN_AVAIL, and the resolved preset wants >= WANT_FLOOR of it -- so this test can
    # actually discriminate a version that let `unmeasured` change `gaps`. (A fixture
    # where every non-`wide` size sits below MIN_AVAIL regardless would report
    # `gaps == ()` no matter what `unmeasured` touched, proving nothing.)
    preset = moodpreset.resolve("fun")
    assert preset.shot_mix["close"] >= moodpreset.WANT_FLOOR
    available = _counts(close=5, wide=40)
    assert available["close"] >= moodpreset.MIN_AVAIL
    used = _counts(wide=8)

    baseline = moodpreset.evaluate(available, used, 2.0, preset, unmeasured=0)
    assert baseline.gaps == ("close",)            # the gap genuinely fires

    r = moodpreset.evaluate(available, used, 2.0, preset, unmeasured=40)
    assert r.unmeasured == 40
    assert r.gaps == baseline.gaps                # identical regardless of `unmeasured`
    assert r.ok is False                          # a real, unwaived gap is never `ok`
