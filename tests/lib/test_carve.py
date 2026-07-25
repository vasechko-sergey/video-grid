import pytest

from scripts.lib import carve


def test_subject_curve_is_2d_and_zero_at_gaps():
    centers = [(0.0, 0.0), (3.0, 4.0), None, (0.0, 0.0)]
    # sample 1: hypot(3,4)=5; sample 2: gap → 0; sample 3: prev is a gap → 0
    assert carve.subject_curve(centers) == [0.0, 5.0, 0.0, 0.0]


def test_subject_curve_edges():
    assert carve.subject_curve([]) == []
    assert carve.subject_curve([(1.0, 1.0)]) == [0.0]


def test_camera_curve_samples_frame_magnitudes_at_times():
    mags = [0.0, 9.0, 0.0, 0.0]           # per-frame at fps=1 → frame i at second i
    assert carve.camera_curve(mags, fps=1.0, times=[0.0, 1.0, 3.5]) == [0.0, 9.0, 0.0]
    assert carve.camera_curve([], fps=1.0, times=[0.0, 1.0]) == [0.0, 0.0]


def test_camera_curve_clamps_past_the_last_frame():
    # a sample time beyond the last vidstab frame reads the last magnitude, never IndexErrors
    assert carve.camera_curve([0.0, 9.0], fps=1.0, times=[0.0, 1.0, 5.0]) == [0.0, 9.0, 9.0]


def test_camera_curve_rejects_nonpositive_fps():
    # fps <= 0 would map every sample onto frame 0 — a silent flat curve; refuse it
    with pytest.raises(ValueError):
        carve.camera_curve([1.0, 2.0], fps=0.0, times=[0.0])


def test_local_extrema_are_interior_only():
    curve = [0.0, 2.0, 0.0, 5.0, 1.0]
    assert carve._local_maxima(curve) == [1, 3]
    assert carve._local_minima(curve) == [2]
    assert carve._local_maxima([0.0, 5.0, 5.0, 0.0]) == []   # a flat plateau is not a peak


def test_find_peaks_returns_raw_local_maxima_far_apart():
    # two clear maxima 2.0s apart (> win_min) → both kept, in time order
    curve = [0.0, 3.0, 9.0, 0.0, 4.0, 0.0]        # maxima at idx 2 (9) and idx 4 (4)
    times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    peaks = carve.find_peaks(curve, times, win_min=1.2)
    assert [times[i] for i in peaks] == [2.0, 4.0]


def test_find_peaks_rejects_a_weaker_maximum_within_win_min():
    # finer sampling (0.4s) so two maxima can sit < win_min apart; the greedy
    # strongest-first keeps the stronger and drops the neighbour, far one survives
    curve = [0.0, 9.0, 0.0, 6.0, 0.0, 0.0, 7.0, 0.0]   # maxima idx1(9), idx3(6), idx6(7)
    times = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8]
    peaks = carve.find_peaks(curve, times, win_min=1.2)
    # idx1(t=0.4,9) kept; idx3(t=1.2,6) is 0.8s away (< 1.2) → dropped; idx6(t=2.4,7) far → kept
    assert [times[i] for i in peaks] == [0.4, 2.4]


def test_find_peaks_keeps_the_stronger_of_two_close_peaks():
    # the stronger peak is the LATER one → a plain index-order greedy would keep the
    # earlier weaker one; strongest-first keeps t=1.2, and the final sort orders it
    curve = [0.0, 4.0, 0.0, 9.0, 0.0]
    times = [0.0, 0.4, 0.8, 1.2, 1.6]
    assert [times[i] for i in carve.find_peaks(curve, times, win_min=1.2)] == [1.2]


def _steps(times):
    return [float(t) for t in times]


def test_span_within_band_is_one_whole_unit():
    # 3.0s span (<= WIN_MAX 4.0) → the whole span, no peak logic
    assert carve.units_for_span(0.0, 3.0, [0.0, 1.0, 2.0], [0.0, 5.0, 0.0], 1.2, 4.0) == [(0.0, 3.0)]


def test_span_below_band_is_dropped():
    assert carve.units_for_span(0.0, 0.9, [0.0], [0.0], 1.2, 4.0) == []


def test_long_take_is_not_equal_tiling():
    # 8s take, one clear peak at t=4 with lulls either side → NOT 2x4s or 3x2.67s tiles
    times = _steps(range(9))                       # 0..8 at 1s
    curve = [0, 0, 1, 3, 9, 3, 1, 0, 0]
    units = carve.units_for_span(0.0, 8.0, times, curve, 1.2, 4.0)
    assert units                                   # at least one unit
    assert all(1.2 - 1e-6 <= d <= 4.0 + 1e-6 for _, d in units)
    starts = sorted(s for s, _ in units)
    # equal-interval tiling would start every 2.0s or 2.67s from 0; activity units do not
    assert starts != [0.0, 4.0]
    assert starts != [0.0, 2.0, 4.0, 6.0]


def test_peak_gets_a_lead_in_and_a_tight_candidate():
    # peak at t=4; lull at t=1 (val 0 between rises), settle at t=6
    times = _steps(range(9))
    curve = [3, 0, 2, 5, 9, 5, 0, 2, 3]
    units = carve.units_for_span(0.0, 8.0, times, curve, 1.2, 4.0)
    # a tight ~WIN_MIN window contains the peak; a wider lead-in window also contains it
    assert any(abs(d - 1.2) < 1e-6 and s <= 4.0 <= s + d for s, d in units)   # tight
    assert any(d > 1.2 and s <= 4.0 <= s + d for s, d in units)               # lead-in


def test_flat_span_is_one_max_mean_window_not_a_tiling():
    # monotone-ish, no interior local max → one WIN_MAX window at the busiest position
    times = _steps(range(11))                      # 0..10 at 1s
    curve = [0, 0, 0, 0, 0, 5, 5, 5, 5, 0, 0]      # busiest around t=5..8
    units = carve.units_for_span(0.0, 10.0, times, curve, 1.2, 4.0)
    assert len(units) == 1
    s, d = units[0]
    assert abs(d - 4.0) < 1e-6                      # exactly WIN_MAX
    assert 4.0 <= s <= 6.0                          # centred on the busy stretch


def test_lead_in_longer_than_the_band_is_clamped_with_the_peak_inside():
    # lull far before the peak (t=1) and peak at t=7 → raw lead-in 6s > WIN_MAX
    times = _steps(range(9))
    curve = [3, 0, 1, 2, 3, 4, 5, 9, 3]            # rises to a peak at t=7, lull at t=1
    units = carve.units_for_span(0.0, 8.0, times, curve, 1.2, 4.0)
    lead = max(units, key=lambda u: u[1])          # the widest unit
    s, d = lead
    assert d <= 4.0 + 1e-6 and s <= 7.0 <= s + d   # band-clamped, peak still inside


def test_units_for_span_refuses_misaligned_or_bad_band():
    import pytest
    with pytest.raises(ValueError):                 # times/curve length mismatch
        carve.units_for_span(0.0, 8.0, [0.0, 1.0], [0.0], 1.2, 4.0)
    with pytest.raises(ValueError):                 # win_min > win_max
        carve.units_for_span(0.0, 8.0, [0.0], [0.0], 5.0, 4.0)


def test_units_for_span_dedups_and_sorts_deterministically():
    # two peaks (t=1.2, t=2.4); the first peak's tight == its lead-in (minima flank it
    # at ±win_min/2), so the exact-dup drop must collapse them; output is (start,dur)-sorted.
    # Drop the dedup → a duplicate (0.6,1.2) survives; drop the sort → order changes.
    times = [0.0, 0.6, 1.2, 1.8, 2.4, 3.0, 3.6, 4.2, 4.8]
    curve = [5.0, 0.0, 9.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0]
    assert carve.units_for_span(0.0, 4.8, times, curve, 1.2, 4.0) == [(0.6, 1.2), (1.8, 1.2), (1.8, 3.0)]


def test_flat_span_tie_breaks_to_the_earliest_window():
    # two equal-mean WIN_MAX windows in a flat span → the earliest wins (strict >);
    # a >= tie-break would pick the later one
    times = _steps(range(11))
    curve = [9.0, 9.0, 9.0, 9.0, 0.0, 0.0, 9.0, 9.0, 9.0, 9.0, 0.0]
    assert carve.units_for_span(0.0, 10.0, times, curve, 1.2, 4.0) == [(0.0, 4.0)]
