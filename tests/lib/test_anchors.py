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


@pytest.mark.parametrize("bad", [-1.0, True, "0", None])
def test_measure_curve_refuses_a_bad_start(bad):
    with pytest.raises(ValueError, match="start"):
        anchors.measure_curve("x.mp4", bad, 4.0)


@pytest.mark.parametrize("bad", [0, -1.0, True, "4", None])
def test_measure_curve_refuses_a_bad_dur(bad):
    with pytest.raises(ValueError, match="dur"):
        anchors.measure_curve("x.mp4", 0.0, bad)


@pytest.mark.parametrize("bad", [0, -1.0, True, "3", None])
def test_measure_curve_refuses_a_bad_hz(bad):
    with pytest.raises(ValueError, match="hz"):
        anchors.measure_curve("x.mp4", 0.0, 4.0, hz=bad)


def test_curve_contrast_is_the_fraction_clearing_the_floor():
    """Near 1.0 the relative floor is admitting the whole curve rather than selecting
    from it (design 2026-08-18 §4). A single spike over a low plateau: only the spike
    clears 0.6 x peak."""
    curve = [0.1] * 20 + [1.0]
    assert anchors.curve_contrast(curve, rel=0.6) == pytest.approx(1 / 21)
    assert anchors.curve_contrast([0.9, 0.95, 1.0], rel=0.6) == 1.0
    assert anchors.curve_contrast([]) == 0.0
    assert anchors.curve_contrast([0.0, 0.0]) == 0.0     # no peak, no fraction
    # A sample landing EXACTLY on the floor is the only thing that tells `>=` from `>`,
    # and none of the cases above does: 0.6 * 1.0 is exactly 0.6 in binary, so this one
    # counts under `>=` and not under `>`. Found by the mutation battery, which the
    # three assertions above survived (design 2026-08-18 §4).
    assert anchors.curve_contrast([0.6, 0.1, 1.0], rel=0.6) == pytest.approx(2 / 3)


def test_a_plateau_yields_no_anchors_even_though_it_has_local_maxima():
    """The real-footage case, reproduced synthetically. Every sample sits between 0.76
    and 1.00 of the peak — the exact band measured on MVI_3998, the one episode of the
    2026-08-03 run that carries a ramp — so `rel=0.6` admits all 21 samples and the
    local maxima that survive are noise on a plateau. Before the flat guard this
    returned FIVE 'anchors' at 1.0/2.0/3.0/4.0/5.33s: one per min_gap across the whole
    window, a grid rather than a set of events."""
    curve = [1.00, 0.96, 0.87, 0.94, 0.89, 0.91, 0.97, 0.83, 0.84, 0.95, 0.87,
             0.77, 0.83, 0.76, 0.79, 0.87, 0.90, 0.86, 0.89, 0.76, 0.86]
    assert anchors.curve_contrast(curve) == 1.0
    assert anchors.anchors_from_curve(curve, hz=3.0) == []
    # ...and the raw maxima are still reachable, so the guard hides nothing
    raw = anchors.anchors_from_curve(curve, hz=3.0, flat_frac=1.0)
    assert raw == pytest.approx([1.0, 2.0, 3.0, 4.0, 16 / 3.0], abs=1e-9)


def test_the_flat_guard_does_not_swallow_a_real_spike():
    """The control that must not move: a curve with one genuine event has low contrast,
    so the guard never fires on it."""
    curve = [0.1] * 10 + [0.9] + [0.1] * 10
    assert anchors.curve_contrast(curve) < anchors.ANCHOR_FLAT_FRAC
    assert anchors.anchors_from_curve(curve, hz=3.0) == pytest.approx([10 / 3.0], abs=1e-9)


@pytest.mark.parametrize("bad", [0, -0.1, 1.5, "half", True, None])
def test_anchors_refuse_a_flat_frac_outside_zero_one(bad):
    with pytest.raises(ValueError, match="flat_frac"):
        anchors.anchors_from_curve([0.1, 0.9, 0.1], flat_frac=bad)
