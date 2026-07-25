# tests/lib/test_anchors.py
"""anchors — action anchors from a motion curve (design 2026-07-24 §4)."""
import pytest

from scripts.lib import anchors


def test_one_spike_yields_one_anchor_at_its_time():
    curve = [0.1] * 10 + [0.9] + [0.1] * 10
    got = anchors.anchors_from_curve(curve, hz=3.0)
    assert got == pytest.approx([10 / 3.0], abs=1e-9)


def test_a_flat_curve_yields_no_anchors():
    assert anchors.anchors_from_curve([0.4] * 30, hz=3.0) == []


def test_two_spikes_closer_than_the_min_gap_collapse_to_the_stronger():
    curve = [0.1] * 5 + [0.7] + [0.1] + [0.9] + [0.1] * 5
    got = anchors.anchors_from_curve(curve, hz=3.0, min_gap=2.0)
    assert got == pytest.approx([7 / 3.0], abs=1e-9)


def test_two_spikes_further_apart_than_the_min_gap_both_survive():
    curve = [0.1] * 5 + [0.9] + [0.1] * 10 + [0.85] + [0.1] * 5
    got = anchors.anchors_from_curve(curve, hz=3.0, min_gap=1.0)
    assert got == pytest.approx([5 / 3.0, 16 / 3.0], abs=1e-9)


def test_a_spike_below_the_relative_threshold_is_not_an_anchor():
    curve = [0.1] * 5 + [0.3] + [0.1] * 5 + [1.0] + [0.1] * 5
    got = anchors.anchors_from_curve(curve, hz=3.0, rel=0.6)
    assert got == pytest.approx([11 / 3.0], abs=1e-9)


def test_anchors_refuse_a_nonpositive_hz():
    with pytest.raises(ValueError, match="hz"):
        anchors.anchors_from_curve([0.1, 0.9], hz=0)


def test_anchors_refuse_a_threshold_outside_zero_one():
    with pytest.raises(ValueError, match="rel"):
        anchors.anchors_from_curve([0.1, 0.9], hz=3.0, rel=1.5)
