"""The subject grade-delta DESCRIPTION (design docs/specs/2026-08-28-grade-delta-sensors-design.md
§2.3, demoted from a verdict to a description 2026-08-31 §3 — see check_episode.grade_damage
for the entropy-ratio statistic that now votes)."""
import pytest

from scripts.lib import color_fidelity as cf


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
