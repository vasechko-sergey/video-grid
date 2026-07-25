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


def test_smooth_is_a_centred_moving_average():
    assert carve.smooth([0.0, 9.0, 0.0], kernel=3) == [4.5, 3.0, 4.5]
    assert carve.smooth([1.0, 2.0], kernel=3) == [1.0, 2.0]   # too short → unchanged


def test_local_extrema_are_interior_only():
    curve = [0.0, 2.0, 0.0, 5.0, 1.0]
    assert carve._local_maxima(curve) == [1, 3]
    assert carve._local_minima(curve) == [2]


def test_find_peaks_keeps_strongest_first_with_min_spacing():
    # times 0..5s at 1s; two maxima at t=1 (val 3) and t=2 (val 9), win_min 1.2 apart-fail
    curve = [0.0, 3.0, 9.0, 0.0, 4.0, 0.0]
    times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    peaks = carve.find_peaks(curve, times, win_min=1.2)
    # t=1 and t=2 are 1.0s apart (< 1.2) → only the stronger (t=2) survives; t=4 is far → kept
    assert [times[i] for i in peaks] == [2.0, 4.0]
