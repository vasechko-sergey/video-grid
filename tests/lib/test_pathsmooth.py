import pytest

from scripts.lib import pathsmooth as p

def test_constant_stays_constant():
    raw = [700.0] * 30
    out = p.smooth(raw, max_step=10, window=5)
    assert all(abs(v - 700.0) < 1e-6 for v in out)

def test_step_is_rate_limited():
    # a hard jump must not move faster than max_step per frame
    raw = [0.0] * 5 + [100.0] * 25
    out = p.smooth(raw, max_step=10, window=1)  # window=1 → no savgol, pure limiter
    steps = [abs(out[i] - out[i - 1]) for i in range(1, len(out))]
    assert max(steps) <= 10 + 1e-6

def test_reaches_target_eventually():
    raw = [0.0] * 2 + [100.0] * 40
    out = p.smooth(raw, max_step=10, window=1)
    assert abs(out[-1] - 100.0) < 1.0

def test_length_preserved():
    raw = [float(i) for i in range(50)]
    assert len(p.smooth(raw, max_step=10, window=7)) == 50

def test_empty_input_returns_empty():
    assert p.smooth([], max_step=10, window=7) == []

def test_even_window_at_input_length_does_not_crash():
    raw = [float(i) for i in range(6)]
    out = p.smooth(raw, max_step=10, window=6)
    assert len(out) == 6

def test_window_frames_preserves_the_historical_30fps_default():
    # DEFAULT_WINDOW = 7 was tuned at 30fps; the seconds-based default must land on it
    from scripts.lib import pathsmooth as ps
    assert ps.window_frames(ps.DEFAULT_WINDOW_S, 30.0) == ps.DEFAULT_WINDOW


def test_window_frames_doubles_on_60fps_footage():
    # 7 frames is 0.23s at 30fps but 0.12s at 60fps, so the same literal filters
    # half as much motion on the footage this repo actually gets
    from scripts.lib import pathsmooth as ps
    assert ps.window_frames(ps.DEFAULT_WINDOW_S, 59.94) == 15


def test_window_frames_is_always_odd_and_at_least_five():
    from scripts.lib import pathsmooth as ps
    for fps in (24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0, 120.0, 240.0):
        n = ps.window_frames(ps.DEFAULT_WINDOW_S, fps)
        assert n % 2 == 1 and n >= 5, (fps, n)


@pytest.mark.parametrize("seconds, fps", [(0.25, 0.0), (0.25, -1.0), (0.0, 30.0), (-0.1, 30.0)])
def test_window_frames_rejects_degenerate_input(seconds, fps):
    from scripts.lib import pathsmooth as ps
    with pytest.raises(ValueError):
        ps.window_frames(seconds, fps)
