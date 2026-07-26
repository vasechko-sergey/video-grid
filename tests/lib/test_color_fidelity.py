import pytest
from scripts.lib import color_fidelity as cf


def test_exposure_and_saturation_do_not_count_as_drift():
    base = (150.0, 90.0, 60.0)
    assert cf.hue_drift(base, (75.0, 45.0, 30.0)) == pytest.approx(0.0, abs=1.0)   # 0.5x exposure
    m = sum(base) / 3
    sat = tuple(m + (c - m) * 1.4 for c in base)                                    # more saturated
    assert cf.hue_drift(base, sat) == pytest.approx(0.0, abs=2.0)


def test_a_real_hue_rotation_is_drift():
    assert cf.hue_drift((150.0, 90.0, 60.0), (60.0, 150.0, 90.0)) > 60.0            # orange → green


def test_near_grey_has_no_hue():
    assert cf.hue((128.0, 130.0, 129.0)) is None
    assert cf.hue_drift((128.0, 130.0, 129.0), (60.0, 150.0, 90.0)) is None


def test_evaluate_worst_and_threshold():
    pairs = [((150, 90, 60), (150, 90, 60)), ((150, 90, 60), (60, 150, 90))]
    d = cf.evaluate(pairs, threshold=25.0)
    assert d["exceeded"] is True and d["worst_drift_deg"] > 60 and d["samples"] == 2
    grey = cf.evaluate([((128, 130, 129), (100, 101, 102))], threshold=25.0)
    assert grey["status"] == "not-checked"
