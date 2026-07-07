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
