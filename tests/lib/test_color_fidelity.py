"""The subject grade-delta DESCRIPTION (design docs/specs/2026-08-28-grade-delta-sensors-design.md
§2.3, demoted from a verdict to a description 2026-08-31 §3 — see check_episode.grade_damage
for the entropy-ratio statistic that now votes)."""
import pytest

from scripts.lib import color_fidelity as cf
from scripts.lib import models


def test_an_identical_pair_is_zero():
    d = cf.evaluate([((150.0, 90.0, 60.0), (150.0, 90.0, 60.0))])
    assert d["delta_e"] == 0.0 and d["samples"] == 1


def test_a_hue_rotation_shows_a_large_delta_h():
    d = cf.evaluate([((150.0, 90.0, 60.0), (60.0, 150.0, 90.0))])
    assert d["delta_h"] > 30.0


def test_a_luma_lift_shows_up_as_delta_l():
    d = cf.evaluate([((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))])
    assert d["delta_l"] > 10.0


def test_a_desaturation_shows_up_as_delta_c():
    """Pulling a colour toward its own mean keeps L* nearly fixed: this checks
    delta_c specifically, not a comparison against the other two components."""
    src = (200.0, 80.0, 40.0)
    m = sum(src) / 3
    d = cf.evaluate([(src, tuple(m + (c - m) * 0.4 for c in src))])
    assert d["delta_c"] < 0


def test_a_near_grey_subject_still_gets_a_number():
    """The old grey floor discarded 9 of 24 real samples (design §0.2). A near-grey
    pair must now report a value rather than being discarded."""
    d = cf.evaluate([((128.0, 130.0, 129.0), (129.0, 130.0, 128.0))])
    assert "status" not in d
    assert d["delta_e"] < 5.0


def test_the_description_is_the_median_not_the_worst():
    """Three samples, one of them wildly off. The median ignores it; a max would not.
    This is the statistic the design measured (§0.4) — a worst-sample rule does not
    separate the shipped grade from the recorded damage."""
    same = ((150.0, 90.0, 60.0), (150.0, 90.0, 60.0))
    wild = ((150.0, 90.0, 60.0), (60.0, 150.0, 90.0))
    d = cf.evaluate([same, same, wild])
    assert d["delta_e"] == 0.0


def test_no_samples_is_not_checked():
    d = cf.evaluate([])
    assert d["status"] == "not-checked" and "no samples" in d["reason"]


def test_sample_deltas_is_one_row_per_pair():
    rows = cf.sample_deltas([((10.0, 20.0, 30.0), (11.0, 21.0, 31.0)),
                             ((10.0, 20.0, 30.0), (90.0, 20.0, 30.0))])
    assert len(rows) == 2 and all(len(r) == 4 for r in rows)
    assert rows[1][0] > rows[0][0]


def test_the_old_hue_api_is_gone():
    """The grey floor and the hue angle are deleted, not deprecated — a caller still
    reaching for them must break loudly rather than get a silently different answer."""
    assert not hasattr(cf, "hue")
    assert not hasattr(cf, "hue_drift")
    assert not hasattr(cf, "GREY_EPS")


def test_evaluate_no_longer_votes():
    """delta_max/threshold/exceeded have no consumer once the dE00 stops voting
    (design 2026-08-31 §3) — a caller still passing delta_max gets a loud TypeError,
    not a silently-ignored argument, and the returned dict carries no threshold."""
    d = cf.evaluate([((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))])
    assert "threshold" not in d and "exceeded" not in d
    with pytest.raises(TypeError):
        cf.evaluate([((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))], delta_max=5.0)


def test_evaluate_reports_the_three_components_and_no_ranking_of_them():
    """`dominant` was a ranking of three numbers that cannot be ranked: it flips
    on three of four real episodes with a sample-count change, and one real
    episode is an exact tie broken by tuple order (design 2026-09-16 §0.5).
    The components are the explanation; the reader ranks them or does not."""
    out = cf.evaluate([((10, 20, 30), (40, 50, 60))])
    assert set(out) == {"delta_e", "delta_l", "delta_c", "delta_h", "samples"}


def _report(grade_damage: dict) -> dict:
    return {"checks": {"grade_damage": grade_damage}, "overall": True,
            "attempt": 1, "fail_reasons": []}


def test_a_subject_reading_hands_over_the_crops_pair_not_the_subjects():
    """The reel compares ONE pixel set across episodes, and it is the crop.

    The output carries no `region` key (final whole-branch review, FIX 1): both
    arms hand over the crop's own numbers, so a label distinguishing them would
    either be constant or, as it shipped first, actively wrong on this very arm —
    the numbers below are the CROP's even though the source report's `region` is
    `"subject"`."""
    out = cf.shift_from_report(_report(
        {"region": "subject", "delta_c": 9.0, "delta_h": 9.0,
         "crop_delta_c": -1.25, "crop_delta_h": 0.5, "pass": True}))
    assert out == {"delta_c": -1.25, "delta_h": 0.5}


def test_a_crop_reading_hands_over_its_own_pair():
    out = cf.shift_from_report(_report(
        {"region": "crop", "delta_c": -4.18, "delta_h": -1.22, "pass": True}))
    assert out == {"delta_c": -4.18, "delta_h": -1.22}


def test_a_not_checked_grade_damage_keeps_its_own_reason():
    """Never a 0.0, which would read as 'the grade moved nothing' (design §4.5)."""
    out = cf.shift_from_report(_report(
        {"status": "not-checked", "reason": "no render pair: source is pc"}))
    assert out == {"status": "not-checked", "reason": "no render pair: source is pc"}


def test_a_report_with_no_grade_damage_block_is_named_not_guessed():
    out = cf.shift_from_report({"checks": {}, "overall": True})
    assert out == {"status": "not-checked",
                   "reason": "the report carries no grade_damage block"}


def test_a_non_report_is_named_rather_than_crashing():
    out = cf.shift_from_report([])
    assert out == {"status": "not-checked",
                   "reason": "the report carries no grade_damage block"}


def test_status_and_region_coexist_when_update_merges_them():
    """check_episode._grade_damage unconditionally merges gradedamage.evaluate
    (which can return status: "not-checked") with _subject_delta_advisory (which
    always sets region). A dict with both status AND region is reachable in
    production. shift_from_report keys on region, not status (design §2.3) —
    a real reading takes precedence over a status field from the evaluate side.

    The output itself carries no `region` (final whole-branch review, FIX 1) —
    only the INPUT report's region decides which pair comes back."""
    out = cf.shift_from_report(_report(
        {"status": "not-checked", "reason": "every ungraded frame is flat",
         "region": "subject", "delta_c": 9.0, "delta_h": 9.0,
         "crop_delta_c": -1.25, "crop_delta_h": 0.5, "pass": True}))
    assert out == {"delta_c": -1.25, "delta_h": 0.5}


def test_shift_from_report_emits_the_two_shapes_the_carrier_accepts():
    """The producer is the chokepoint. build_reel's reprocess arm assigns this
    function's return straight into the list check_reel reads, bypassing
    ReelEpisode.__post_init__ entirely — so a shape this function can emit but the
    carrier would refuse is a shape that reaches the consumer unchecked.

    This test holds only what the producer EMITS for good input: a reading, and a
    named absence with a reason. It cannot fail if the validation is removed — that
    is held by `test_the_carrier_and_the_producer_share_one_validator` and
    `test_shift_from_report_refuses_a_shape_the_carrier_would_refuse`, not by this
    one."""
    good = cf.shift_from_report(
        {"checks": {"grade_damage": {"region": "crop",
                                     "delta_c": 1.0, "delta_h": -2.0}}})
    assert good == {"delta_c": 1.0, "delta_h": -2.0}
    absent = cf.shift_from_report({})
    assert absent["status"] == "not-checked" and absent["reason"]


def test_validate_chroma_accepts_none_and_both_good_shapes():
    cf.validate_chroma(None)
    cf.validate_chroma({"delta_c": 0.0, "delta_h": 0.0})
    cf.validate_chroma({"status": "not-checked", "reason": "why"})


@pytest.mark.parametrize("bad,says", [
    ([], "must be a reading"),
    ({"status": "not-checked"}, "non-empty 'reason'"),
    ({"status": "not-checked", "reason": ""}, "non-empty 'reason'"),
    ({"delta_c": 1.0}, "numeric 'delta_c' and 'delta_h'"),
    ({"delta_c": True, "delta_h": 1.0}, "numeric 'delta_c' and 'delta_h'"),
])
def test_validate_chroma_refuses_each_bad_shape(bad, says):
    with pytest.raises(ValueError, match=says):
        cf.validate_chroma(bad)


def test_the_validator_files_a_dict_by_the_value_of_status_as_the_reader_does():
    """Which arm a dict lands in is decided by the VALUE `"not-checked"`, never by
    the mere presence of a `status` key — the same predicate
    `check_reel._chroma_spread_check` uses to file it as an absence (design
    2026-09-21 §0.3: the reader and its validator must key on the same thing). A
    validator keyed on presence would demand a `reason` of a reading that merely
    carries some other `status`, refusing what the reader reads as a reading.

    The last case is a behaviour `check_reel`'s comments and its own test
    (`test_a_not_checked_chroma_carrying_a_stray_component_lands_among_the_absences`)
    state as fact: the absence arm returns once it has a reason, so a stray numeric
    component beside it is admitted. That test hands the dict to the READER
    directly and never routes it through this validator, so nothing held the claim
    until now. The `status` value `"measured"` is constructed by this test, not
    observed in production: it is the right SHAPE for the property (a `status` that
    is not `not-checked`), not a claim that any producer emits one."""
    cf.validate_chroma({"status": "measured", "delta_c": 1.0, "delta_h": 2.0})
    with pytest.raises(ValueError, match="numeric 'delta_c' and 'delta_h'"):
        cf.validate_chroma({"status": "measured"})
    cf.validate_chroma({"status": "not-checked", "reason": "why", "delta_c": 1.0})


def test_an_integer_component_is_numeric():
    """The numeric clause admits an int as well as a float — the `bool` exclusion
    beside it exists because a bool IS an int, which needs saying only if ints are
    otherwise legal. Nothing else in the suite hands either validator an int, so a
    clause narrowed to `float` passed every test while refusing
    `{"delta_c": 2, "delta_h": 0}`, which the pre-extraction
    `ReelEpisode.__post_init__` accepted."""
    cf.validate_chroma({"delta_c": 2, "delta_h": 0})


def test_the_carrier_and_the_producer_share_one_validator(monkeypatch):
    """Not 'both validate' — both call the SAME function. Two validators that
    agree today are two that can disagree tomorrow, which is the shape this slice
    exists to remove: a rule kept by whoever remembers to keep it."""
    seen = []
    monkeypatch.setattr(cf, "validate_chroma",
                        lambda c: seen.append(c))
    models.ReelEpisode(manifest={}, clip="c.mp4",
                       chroma={"delta_c": 1.0, "delta_h": 2.0})
    cf.shift_from_report(
        {"checks": {"grade_damage": {"region": "crop",
                                     "delta_c": 3.0, "delta_h": 4.0}}})
    assert seen == [{"delta_c": 1.0, "delta_h": 2.0},
                    {"delta_c": 3.0, "delta_h": 4.0}]


def test_shift_from_report_refuses_a_shape_the_carrier_would_refuse():
    """The behavioural half of the chokepoint claim, beside the spy test above.

    That test proves both callers reach the SAME validator; it cannot see whether
    the producer lets the refusal OUT, because its stand-in never raises — so a
    producer that caught and discarded the ValueError would leave it green while
    the very shape this slice exists to stop reached check_reel. This drives the
    real validator with a shape `_shift` genuinely emits: a `crop` block is copied
    through untouched, so a null delta comes out the other side as a reading with
    no number in it, and must stop here. The `None` is constructed by this test,
    not observed in production, where real readings are floats: it is the right
    SHAPE to test (a value `_shift` passes through untouched), not a claim that any
    producer emits it."""
    report = {"checks": {"grade_damage": {"region": "crop",
                                          "delta_c": None, "delta_h": 1.0}}}
    with pytest.raises(ValueError, match="numeric 'delta_c' and 'delta_h'"):
        cf.shift_from_report(report)


_CHROMA_REFUSALS = (
    "ReelEpisode.chroma must be a reading "
    "{delta_c, delta_h} or an absence {status, reason}, "
    "got list — build it with "
    "color_fidelity.shift_from_report(report)",
    "ReelEpisode.chroma: a not-checked chroma must carry a "
    "non-empty 'reason' naming the absence, got {'status': 'not-checked'}",
    "ReelEpisode.chroma must carry numeric 'delta_c' and 'delta_h' "
    "(signed CIEDE2000 components), got {'delta_c': 1.0} — build it with "
    "color_fidelity.shift_from_report(report)",
)


@pytest.mark.parametrize("bad,want", list(zip(
    ([], {"status": "not-checked"}, {"delta_c": 1.0}), _CHROMA_REFUSALS,
    strict=True)))
def test_each_refusal_message_is_pinned_whole_not_by_fragment(bad, want):
    """`validate_chroma`'s docstring used to say these messages were asserted
    verbatim. That was false: every other assertion matches a fragment, so the
    `— build it with …` tail could be rewritten to name a module that does not
    exist and the whole non-integration suite stayed green (measured 2026-09-29).
    That is this slice's own subject appearing in its own diff — a rule stated in
    a comment with nothing holding it — so the claim is made true rather than
    withdrawn.

    The expected strings are what the refusals printed when this was written
    (identical to the pre-move `ReelEpisode.__post_init__`'s output), copied from
    that output rather than typed from the source."""
    with pytest.raises(ValueError) as e:
        cf.validate_chroma(bad)
    assert str(e.value) == want


def test_the_validators_docstring_names_the_test_that_pins_its_messages():
    """`validate_chroma`'s docstring points at the test that pins its messages, and
    a pointer is a claim too: rename that test and the docstring names nothing.
    Reading the name off the function object makes that rename fail here instead of
    rotting quietly."""
    pin = test_each_refusal_message_is_pinned_whole_not_by_fragment
    assert pin.__name__ in cf.validate_chroma.__doc__
