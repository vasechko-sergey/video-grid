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


def test_local_extrema_are_interior_only():
    curve = [0.0, 2.0, 0.0, 5.0, 1.0]
    assert carve._local_maxima(curve) == [1, 3]
    assert carve._local_minima(curve) == [2]


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
