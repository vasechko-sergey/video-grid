from scripts.lib import motion as m

# a route point: dict(t, x, y, w, h) — subject bbox centre x/y and bbox w/h
def _route(points):
    return [dict(t=t, x=x, y=y, w=w, h=h) for (t, x, y, w, h) in points]

def test_lateral_right():
    r = _route([(0, 300, 500, 140, 320), (1, 800, 500, 145, 322),
                (2, 1300, 500, 148, 320)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("lateral", "right")

def test_lateral_left():
    r = _route([(0, 1300, 500, 140, 320), (1, 800, 500, 140, 320),
                (2, 300, 500, 140, 320)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("lateral", "left")

def test_head_on_growth():
    # x roughly stable, bbox area grows a lot → approaching camera
    r = _route([(0, 950, 500, 100, 200), (1, 955, 480, 180, 380),
                (2, 960, 460, 300, 640)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("head-on", None)

def test_static():
    r = _route([(0, 950, 500, 140, 320), (1, 952, 501, 141, 319),
                (2, 949, 500, 140, 320)])
    assert m.classify(r, src_w=1920, src_h=1080) == ("static", None)

def test_travel_direction_reads_net_dx():
    from scripts.lib.motion import travel_direction
    right = [dict(t=i / 30, x=300 + i * 90, y=500, w=140, h=320) for i in range(10)]
    left = [dict(t=i / 30, x=1500 - i * 90, y=500, w=140, h=320) for i in range(10)]
    assert travel_direction(right) == "right"
    assert travel_direction(left) == "left"


def test_travel_direction_defaults_to_right_without_travel():
    from scripts.lib.motion import travel_direction
    assert travel_direction([]) == "right"
    assert travel_direction([dict(t=0.0, x=5.0, y=0.0, w=1.0, h=1.0)]) == "right"
    flat = [dict(t=i / 30, x=500.0, y=0.0, w=1.0, h=1.0) for i in range(5)]
    assert travel_direction(flat) == "right"
