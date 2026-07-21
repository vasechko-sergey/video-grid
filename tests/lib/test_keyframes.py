import pytest
from scripts.lib import keyframes
from scripts.lib.models import RoutePoint

def test_two_marks_interpolate_linearly():
    marks = [RoutePoint(t=0.0, x=100, y=10, w=40, h=80),
             RoutePoint(t=1.0, x=200, y=10, w=40, h=80)]
    route = keyframes.interpolate(marks, fps=10.0, dur=1.0)
    assert route == [RoutePoint(t=i / 10.0, x=100.0 + 10.0 * i, y=10.0, w=40.0, h=80.0)
                     for i in range(11)]

def test_one_mark_is_a_constant_hold():
    route = keyframes.interpolate([RoutePoint(t=0.5, x=300, y=5, w=20, h=20)],
                                  fps=4.0, dur=1.0)
    assert route == [RoutePoint(t=i / 4.0, x=300.0, y=5.0, w=20.0, h=20.0)
                     for i in range(5)]

def test_zero_marks_raises():
    with pytest.raises(ValueError, match="at least one mark"):
        keyframes.interpolate([], fps=10.0, dur=1.0)

def test_mark_outside_clip_raises():
    with pytest.raises(ValueError, match=r"outside \[0"):
        keyframes.interpolate([RoutePoint(t=2.0, x=1, y=1, w=1, h=1)], fps=10.0, dur=1.0)

def test_non_increasing_ts_raise():
    marks = [RoutePoint(t=0.5, x=1, y=1, w=1, h=1),
             RoutePoint(t=0.5, x=2, y=2, w=2, h=2)]
    with pytest.raises(ValueError, match="strictly increase"):
        keyframes.interpolate(marks, fps=10.0, dur=1.0)
