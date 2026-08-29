import json

import pytest

from scripts import reframe
from scripts.lib import layout
from scripts.lib.models import Delivery, LayoutSpec, PanSpec, PathMeta, ReframeSpec, ZoomSpec


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
                        ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    centred = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    assert lead != centred
    mid = len(route) // 2
    assert abs((route[mid]["x"] - lead[mid]) / 497 - 1 / 3) < 0.02


def test_authored_lead_takes_its_direction_from_the_route():
    from scripts.reframe import compute_path
    right = _diagonal_route()
    left = _diagonal_route(x0=1434.0, x1=855.0)
    mid = len(right) // 2
    pr = compute_path(right, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_ws=[497] * len(right))
    pl = compute_path(left, "lead", "thirds", (9, 16), (1920, 1080),
                      ("static", None), max_step=12.5, crop_ws=[497] * len(left))
    assert abs((right[mid]["x"] - pr[mid]) / 497 - 1 / 3) < 0.02   # travelling right
    assert abs((left[mid]["x"] - pl[mid]) / 497 - 2 / 3) < 0.02    # travelling left


def test_break_and_center_still_ignore_the_direction_rescue():
    from scripts.reframe import compute_path
    route = _diagonal_route()
    a = compute_path(route, "break", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    b = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                     ("static", None), max_step=12.5, crop_ws=[497] * len(route))
    assert a == b


def test_smooth_window_reaches_the_smoother():
    # a wider savgol window must visibly change the path over a noisy route —
    # proves the new parameter is actually threaded into pathsmooth.smooth
    from scripts.reframe import compute_path
    route = [dict(t=i / 60, x=900 + (30 if i % 2 else -30), y=500, w=140, h=320)
             for i in range(40)]
    tight = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                         ("static", None), max_step=99, crop_ws=[497] * len(route),
                         smooth_window=5)
    wide = compute_path(route, "center", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=99, crop_ws=[497] * len(route),
                        smooth_window=21)
    assert tight != wide


def test_authored_lead_on_a_degenerate_route_falls_back_to_centre():
    # a 1-point route has no travel direction → an authored lead must take the SAFE
    # centre clamp, not crop_x with classify_direction's arbitrary "right" default.
    # Guards the `len(route) >= 2` conjunct: dropping it makes the rescue fire on a
    # directionless route.
    from scripts.reframe import compute_path
    one = [dict(t=0.0, x=900.0, y=300.0, w=140.0, h=320.0)]
    lead = compute_path(one, "lead", "thirds", (9, 16), (1920, 1080),
                        ("static", None), max_step=12.5, crop_ws=[497])
    centred = compute_path(one, "center", "thirds", (9, 16), (1920, 1080),
                           ("static", None), max_step=12.5, crop_ws=[497])
    assert lead == centred


def test_compute_path_places_each_sample_at_its_own_width():
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    wide = reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                                ("static", None), max_step=1e9, crop_ws=[800, 400])
    # a centred crop puts the subject mid-rect: 1000 - 800/2 = 600, then 1000 - 400/2 = 800
    assert wide == [600, 800]


def test_compute_path_refuses_a_width_list_that_is_not_parallel_to_the_route():
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    with pytest.raises(ValueError, match="parallel"):
        reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                             ("static", None), max_step=1e9, crop_ws=[800])


def test_compute_path_refuses_more_widths_than_route_samples():
    # the guard is a length INEQUALITY (!=), not "too few": a too-SHORT list is
    # pinned above. If the guard ever weakened to `<`, a too-LONG crop_ws would
    # slip through silently (zip just drops the extra tail) — this pins the
    # other direction so that mutant can't hide.
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    with pytest.raises(ValueError, match="parallel"):
        reframe.compute_path(route, "center", "thirds", (1080, 1920), (3840, 2160),
                             ("static", None), max_step=1e9, crop_ws=[800, 400, 200])


def test_compute_path_lead_places_each_sample_at_its_own_width():
    # the brief's own new test only exercises the center/break clamp branch
    # (g.clamp); `lead` under lateral motion runs the OTHER line (g.crop_x),
    # which zips route against crop_ws separately — nothing else pins that
    # branch varying by width too, not just a constant repeated one.
    route = [{"t": 0.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0},
             {"t": 1.0, "x": 1000.0, "y": 500.0, "w": 100.0, "h": 200.0}]
    path = reframe.compute_path(route, "lead", "thirds", (1080, 1920), (3840, 2160),
                                ("lateral", "right"), max_step=1e9, crop_ws=[900, 300])
    # lead+right targets the LEFT third line: x - crop_w/3 → 1000-300=700, 1000-100=900
    assert path == [700, 900]


def test_xexpr_emits_the_variable_it_is_given():
    e = reframe._xexpr([0, 100], [0.0, 1.0], var="it")
    assert "it" in e and "(t-" not in e


def test_filter_args_inserts_the_zoompan_between_crop_and_scale():
    # Delivery.mode has no "1080" — native/short_edge/long_edge/exact only (models.py
    # __post_init__). The assertions below only check filter-string ORDER, not the
    # resolved layout's numbers, so "native" (the placeholder used the same way
    # throughout test_layout.py/test_models.py) resolves a valid fast-path layout.
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("native"))
    args = reframe._filter_args(rl, "0", 0, "", 30.0, 3.0,
                                zoom_args="zoompan=z='1':x='0':y='0':d=1:s=8x8:fps=30")
    chain = args[1]
    assert chain.index("crop=") < chain.index("zoompan=") < chain.index("scale=")


def test_filter_args_inserts_the_zoompan_between_crop_and_scale_in_the_composite_branch():
    # The fast-path test above only pins the order inside `fill`'s single -vf chain.
    # A non-fill layout takes the OTHER branch (-filter_complex: a background chain,
    # an overlay, and the crop/zoompan/scale composed around them) — nothing else
    # in the suite would catch zoom_args landing in the wrong spot there, or being
    # dropped from that arm entirely while the fast path kept working.
    #
    # background="solid" on purpose: the default "blur" filler ALSO emits its own
    # "crop=" and "scale=" (scale the cover, then crop and boxblur it — see
    # _background_args), and `str.index` finds the FIRST match. On this exact
    # layout the blur background's crop/scale even land on the SAME pixel numbers
    # as the foreground's, so a naive index-order assertion would pass or fail by
    # accident rather than by checking the chain this test is actually about.
    # solid's bg_chain is a bare `color=...`, with neither substring, so the one
    # "crop=" and one "scale=" left in the chain can only be the foreground's.
    rl = layout.resolve(LayoutSpec(mode="fit", background="solid"), (1080, 1920),
                        (3840, 2160), Delivery("long_edge", 1920))
    assert not rl.fast_path                       # confirms this exercises the OTHER branch
    args = reframe._filter_args(rl, "0", 0, "", 30.0, 3.0,
                                zoom_args="zoompan=z='1':x='0':y='0':d=1:s=8x8:fps=30")
    assert args[0] == "-filter_complex"
    chain = args[1]
    assert chain.count("crop=") == 1 and chain.count("scale=") == 1
    assert chain.index("crop=") < chain.index("zoompan=") < chain.index("scale=")


def test_filter_args_without_a_zoom_is_unchanged():
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("native"))
    assert (reframe._filter_args(rl, "0", 0, "", 30.0, 3.0)
            == reframe._filter_args(rl, "0", 0, "", 30.0, 3.0, zoom_args=""))
    assert "zoompan" not in reframe._filter_args(rl, "0", 0, "", 30.0, 3.0)[1]


def test_reframe_refuses_a_zoom_together_with_a_pan():
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"), pan=PanSpec(start=0.0, end=1.0),
                       zoom=ZoomSpec(start=1.0, end=0.7))
    with pytest.raises(ValueError, match="zoom and pan"):
        reframe.reframe(spec, "src.mp4", None, "out.mp4", "path.json")


def test_reframe_emits_a_zoompan_with_every_default_overridden(tmp_path, monkeypatch):
    cmds = []
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: cmds.append(cmd))
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.0, "yuv420p", "tv"))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([
        {"t": 0.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0},
        {"t": 2.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0}]))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"), zoom=ZoomSpec(start=1.0, end=0.7))
    reframe.reframe(spec, "src.mp4", str(route), str(tmp_path / "out.mp4"),
                    str(tmp_path / "path.json"))
    chain = [a for a in cmds[0] if "zoompan=" in a][0]
    rl = layout.resolve(LayoutSpec(mode="fill"), (1080, 1920), (3840, 2160),
                        Delivery("long_edge", 1920))
    # every default overridden, and `s` is the CROP it consumes — not the delivery,
    # which would drive z below 1 and render nothing (design §3.3)
    assert ":d=1:" in chain and ":fps=30" in chain
    assert f":s={rl.crop_w}x{rl.crop_h}" in chain


def test_reframe_writes_the_rect_arrays_into_the_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.0, "yuv420p", "tv"))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([
        {"t": 0.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0},
        {"t": 2.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0}]))
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"), zoom=ZoomSpec(start=1.0, end=0.7))
    reframe.reframe(spec, "src.mp4", str(route), str(tmp_path / "out.mp4"), str(path_out))
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert meta.zoomed is True
    assert meta.crop_ws[0] == meta.crop_w          # starts at the full crop
    assert meta.crop_ws[-1] < meta.crop_w          # and ends tighter
    assert len(meta.crop_ws) == 2


def test_reframe_without_a_zoom_writes_no_arrays(tmp_path, monkeypatch):
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.0, "yuv420p", "tv"))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([
        {"t": 0.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0},
        {"t": 2.0, "x": 1900.0, "y": 1080.0, "w": 200.0, "h": 400.0}]))
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery("long_edge", 1920),
                       layout=LayoutSpec(mode="fill"))
    reframe.reframe(spec, "src.mp4", str(route), str(tmp_path / "out.mp4"), str(path_out))
    assert "crop_ws" not in json.loads(path_out.with_suffix(".meta.json").read_text())


class _FakeCompleted:
    stdout = b""
    stderr = b""
    returncode = 0


def _fake_ok():
    return _FakeCompleted()


def test_plan_render_and_reframe_build_the_same_filter_args(tmp_path, monkeypatch):
    """reframe() must emit exactly what plan_render decided — if the two ever diverge
    the probe stops describing the render, which is the one thing it is for."""
    seen: list[list[str]] = []
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **kw: seen.append(cmd) or _fake_ok())
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.0, "yuv420p", "tv"))
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(110.0, 120.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:540"),
                       pan=PanSpec(start=0.0, end=0.2))
    plan = reframe.plan_render(spec, "src.mp4", None)
    reframe.reframe(spec, "src.mp4", None, str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert plan.filter_args == seen[-1][4:4 + len(plan.filter_args)]


def test_with_tail_appends_after_the_chain(tmp_path, monkeypatch):
    """The sink filter lands at the END of the chain — design §3.1: ahead of the
    tail's fps= it silently emits one frame N times."""
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.0, "yuv420p", "tv"))
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(110.0, 120.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:540"),
                       pan=PanSpec(start=0.0, end=0.2))
    plan = reframe.plan_render(spec, "src.mp4", None)
    tailed = plan.with_tail("select='eq(n\\,3)'")
    assert tailed[:-1] == plan.filter_args[:-1]
    assert tailed[-1] == plan.filter_args[-1] + ",select='eq(n\\,3)'"
    assert tailed[-1].index("fps=") < tailed[-1].index("select=")


def _guard_spec(**kw):
    base = dict(composition="lead", grid="thirds", canvas=(9, 16),
                color_means=(110.0, 120.0, 130.0),
                delivery=Delivery.from_spec("short_edge:540"),
                pan=PanSpec(start=0.0, end=0.2))
    return ReframeSpec(**{**base, **kw})


def test_plan_render_refuses_a_full_range_source(monkeypatch):
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuvj420p", "pc"))
    with pytest.raises(ValueError, match="pc"):
        reframe.plan_render(_guard_spec(), "src.mp4", None)


def test_plan_render_refuses_a_ten_bit_source(monkeypatch):
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuv420p10le", "tv"))
    with pytest.raises(ValueError, match="10 bits"):
        reframe.plan_render(_guard_spec(), "src.mp4", None)


def test_plan_render_accepts_an_untagged_eight_bit_source(monkeypatch):
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuv420p", "unknown"))
    assert reframe.plan_render(_guard_spec(), "src.mp4", None).fps == 30.0


def test_the_guard_runs_even_with_no_colour_knob_set(monkeypatch):
    """The contract is about the segment, not about whether this episode happens
    to grade: every knob in grade_chain reads the same plane, and check_episode
    compares episodes to each other, so a pc episode is the wrong pixels even
    ungraded."""
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuvj420p", "pc"))
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(105, 122, 137),   # required by the dataclass (no
                                                       # default) — left at the file's own
                                                       # generic value; no OTHER grading
                                                       # knob (tone_src/tone_dst/
                                                       # white_balance/...) is set
                       delivery=Delivery.from_spec("short_edge:540"),
                       pan=PanSpec(start=0.0, end=0.2))
    with pytest.raises(ValueError, match="pc"):
        reframe.plan_render(spec, "src.mp4", None)
