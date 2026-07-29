def _diagonal_route(n=60, x0=855.0, x1=1434.0):
    """The measured shape of a surfer riding ACROSS and TOWARD a beach-side telephoto:
    dx is 30% of frame width (lateral needs 15%) AND the box grows 3.1x (head-on needs
    1.6x), so motion.classify lands in its ambiguous zone and answers "static"."""
    return [dict(t=i / 60, x=x0 + (x1 - x0) * i / (n - 1), y=300.0,
                 w=116 + 21 * i / (n - 1), h=149 + 240 * i / (n - 1)) for i in range(n)]


def test_classify_calls_the_diagonal_shot_static():
    from scripts.lib.motion import classify
    assert classify(_diagonal_route(), 1920, 1080) == ("static", None)


def test_authored_lead_is_honoured_when_the_shot_classifies_static():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    lead = compute_path(route, "lead", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=12.5, crop_w=497)
    centred = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_w=497)
    assert lead != centred
    mid = len(route) // 2
    assert abs((route[mid]["x"] - lead[mid]) / 497 - 1 / 3) < 0.02


def test_authored_lead_takes_its_direction_from_the_route():
    from scripts.reframe import compute_path
    right = _diagonal_route()
    left = _diagonal_route(x0=1434.0, x1=855.0)
    mid = len(right) // 2
    pr = compute_path(right, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_w=497)
    pl = compute_path(left, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_w=497)
    assert abs((right[mid]["x"] - pr[mid]) / 497 - 1 / 3) < 0.02   # travelling right
    assert abs((left[mid]["x"] - pl[mid]) / 497 - 2 / 3) < 0.02    # travelling left


def test_break_and_center_still_ignore_the_direction_rescue():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    a = compute_path(route, "break", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_w=497)
    b = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_w=497)
    assert a == b


def test_smooth_window_reaches_the_smoother():
    # a wider savgol window must visibly change the path over a noisy route —
    # proves the new parameter is actually threaded into pathsmooth.smooth
    from scripts.reframe import compute_path
    route = [dict(t=i / 60, x=900 + (30 if i % 2 else -30), y=500, w=140, h=320)
             for i in range(40)]
    tight = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                         ("static", None), max_step=99, crop_w=497, smooth_window=5)
    wide = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=99, crop_w=497, smooth_window=21)
    assert tight != wide


def test_authored_lead_on_a_degenerate_route_falls_back_to_centre():
    # a 1-point route has no travel direction → an authored lead must take the SAFE
    # centre clamp, not crop_x with classify_direction's arbitrary "right" default.
    # Guards the `len(route) >= 2` conjunct: dropping it makes the rescue fire on a
    # directionless route.
    from scripts.reframe import compute_path
    one = [dict(t=0.0, x=900.0, y=300.0, w=140.0, h=320.0)]
    lead = compute_path(one, "lead", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=12.5, crop_w=497)
    centred = compute_path(one, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_w=497)
    assert lead == centred
