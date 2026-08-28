"""The subject grade-delta verdict (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.3)."""
import pytest

from scripts.lib import color_fidelity as cf


def test_an_identical_pair_is_zero_and_passes():
    d = cf.evaluate([((150.0, 90.0, 60.0), (150.0, 90.0, 60.0))], delta_max=5.0)
    assert d["delta_e"] == 0.0 and d["exceeded"] is False and d["samples"] == 1


def test_a_hue_rotation_exceeds():
    d = cf.evaluate([((150.0, 90.0, 60.0), (60.0, 150.0, 90.0))], delta_max=5.0)
    assert d["exceeded"] is True and d["dominant"] == "hue"


def test_a_luma_lift_exceeds_and_names_luma():
    d = cf.evaluate([((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))], delta_max=5.0)
    assert d["exceeded"] is True and d["dominant"] == "luma" and d["delta_l"] > 10.0


def test_a_desaturation_names_chroma():
    """The component that must NOT be the largest here is luma: pulling a colour
    toward its own mean keeps L* nearly fixed."""
    src = (200.0, 80.0, 40.0)
    m = sum(src) / 3
    d = cf.evaluate([(src, tuple(m + (c - m) * 0.4 for c in src))], delta_max=5.0)
    assert d["dominant"] == "chroma" and d["delta_c"] < 0


def test_a_near_grey_subject_still_gets_a_number():
    """The old grey floor discarded 9 of 24 real samples (design §0.2). A near-grey
    pair must now report a value, and a near-grey pair that barely moved must PASS
    rather than reporting a wild hue swing."""
    d = cf.evaluate([((128.0, 130.0, 129.0), (129.0, 130.0, 128.0))], delta_max=5.0)
    assert "status" not in d
    assert d["delta_e"] < 5.0 and d["exceeded"] is False


def test_the_verdict_is_the_median_not_the_worst():
    """Three samples, one of them wildly off. The median ignores it; a max would not.
    This is the statistic the design measured (§0.4) — a worst-sample rule does not
    separate the shipped grade from the recorded damage."""
    same = ((150.0, 90.0, 60.0), (150.0, 90.0, 60.0))
    wild = ((150.0, 90.0, 60.0), (60.0, 150.0, 90.0))
    d = cf.evaluate([same, same, wild], delta_max=5.0)
    assert d["delta_e"] == 0.0 and d["exceeded"] is False


def test_threshold_is_strict_greater_than():
    """A delta exactly at the bar passes: the bar is the largest acceptable value."""
    pairs = [((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))]
    at = cf.evaluate(pairs, delta_max=1000.0)
    assert at["exceeded"] is False
    exact = cf.evaluate(pairs, delta_max=at["delta_e"])
    assert exact["exceeded"] is False


def test_no_samples_is_not_checked():
    d = cf.evaluate([], delta_max=5.0)
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
