import json, subprocess
import pytest
from scripts import reframe
from scripts.lib import models
from scripts.lib import layout as layout_lib
from scripts.lib.models import Delivery, LayoutSpec

def _dims(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return (s["width"], s["height"])

def test_compute_path_lead_right():
    # pure path computation (no ffmpeg): subject slides right → crop_x rises
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="lead", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25)
    assert len(path) == 20
    assert path[-1] >= path[0]                  # crop follows subject right
    assert all(0 <= x <= 1920 - 607 for x in path)

@pytest.mark.integration
def test_reframe_output_dims(sample_clip, tmp_path):
    # build a route matching the fixture's sliding box (x = 200 + t*430 + w/2)
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(90)]
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep.mp4"
    # explicit exact:1080x1920 delivery — the engine has no aspect/res hardcode
    # anymore (#F), so the session-standard vertical size is now spec'd, not implied
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137),
                              delivery=models.Delivery.from_spec("exact:1080x1920"))
    reframe.reframe(spec, str(sample_clip), str(rpath), str(out),
                    str(tmp_path / "path.json"))
    assert _dims(out) == (1080, 1920)
    assert (tmp_path / "path.json").exists()

def test_xexpr_uses_route_times_across_gap():
    # 10 frames, then a 10-frame tracking gap, then 10 more frames (30fps).
    # The expression's last knot must sit at the route's REAL last t (~0.966s),
    # not at index-derived (len(path)-1)/fps (~0.633s) — the desync bug.
    times = [i / 30 for i in range(10)] + [(i + 20) / 30 for i in range(10)]
    path = list(range(0, 100, 10)) + list(range(300, 400, 10))
    knots = reframe._simplify(path, times)
    assert abs(knots[-1][0] - times[-1]) < 1e-9
    assert abs(knots[0][0] - times[0]) < 1e-9

def test_simplify_caps_knots_on_long_noisy_path():
    # ~83s at 60fps with residual tracker jitter: must stay under the knot cap
    import math
    times = [i / 60 for i in range(5000)]
    path = [int(200 + i * 0.15 + 2.5 * math.sin(i * 1.7)) for i in range(5000)]
    knots = reframe._simplify(path, times)
    assert len(knots) <= 80
    expr = reframe._xexpr(path, times)
    assert len(expr) < 8000        # comfortably inside ffmpeg's parser budget

def test_simplify_iterative_no_recursion_on_long_path():
    # a saw-tooth 5000-frame path would blow Python's recursion limit if DP recursed
    times = [i / 30 for i in range(5000)]
    path = [i % 7 for i in range(5000)]
    knots = reframe._simplify(path, times)          # must not raise RecursionError
    assert knots[0][0] == times[0] and knots[-1][0] == times[-1]

def test_reframe_rejects_empty_route(sample_clip, tmp_path):
    rp = tmp_path / "route.json"; rp.write_text("[]")
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=models.Delivery())
    with pytest.raises(ValueError, match="empty"):
        reframe.reframe(spec, str(sample_clip), str(rp), str(tmp_path / "ep.mp4"),
                        str(tmp_path / "path.json"))

@pytest.mark.integration
def test_reframe_with_route_gap_still_renders(sample_clip, tmp_path):
    # gappy route (subject lost frames 30-59) must still produce a valid clip
    route = ([dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
              for i in range(30)]
             + [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
                for i in range(60, 90)])
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep.mp4"
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137),
                              delivery=models.Delivery.from_spec("exact:1080x1920"))
    reframe.reframe(spec, str(sample_clip), str(rpath), str(out),
                    str(tmp_path / "path.json"))
    assert _dims(out) == (1080, 1920)

def test_compute_path_break_center_tracks():
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="break", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25)
    assert len(path) == 20
    assert all(0 <= x <= 1920 - 607 for x in path)

def test_compute_path_unknown_composition_fails_loud():
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(5)]
    with pytest.raises(ValueError, match="unknown composition"):
        reframe.compute_path(route, composition="Lead", grid="thirds",
                             canvas=(9, 16), src=(1920, 1080),
                             motion=("lateral", "right"), max_step=25)

@pytest.mark.integration
def test_reframe_non_916_canvas_even_dims(sample_clip, tmp_path):
    # canvas 5:8 from 1080p → crop 675x1080 (odd) — output must be even and encode.
    # native delivery (default): Delivery.dims owns the even-ification now (#F).
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(90)]
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep58.mp4"
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(5, 8),
                              color_means=(105, 122, 137), delivery=models.Delivery())
    reframe.reframe(spec, str(sample_clip), str(rpath), str(out),
                    str(tmp_path / "path.json"))
    w, h = _dims(out)
    assert w % 2 == 0 and h % 2 == 0

def test_reframe_delivery_dims_native(monkeypatch, tmp_path):
    # native delivery on a 4K source → crop-native even dims, NOT 1080x1920
    route = [models.RoutePoint(i / 30, 1900 + i * 5, 1080, 200, 480) for i in range(10)]
    models.route_to_json(route, tmp_path / "r.json")
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0))
    captured = {}
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **k: captured.setdefault("cmd", cmd))
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=models.Delivery("native"))
    reframe.reframe(spec, "src.mp4", str(tmp_path / "r.json"), str(tmp_path / "out.mp4"),
                    str(tmp_path / "path.json"))
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "scale=1214:2160" in vf          # 4K 9:16 crop 1215x2160 → even native, no upscale


_NATIVE = Delivery("native", None)


def test_filter_args_fill_is_pinned_to_todays_chain():
    rl = layout_lib.resolve(LayoutSpec(mode="fill"), (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="577.0", cy=0, gains=(1.0, 1.1, 1.2), fps=59.94)
    assert args == [
        "-vf",
        "crop=405:720:x='577.0':y=0,scale=404:720,"
        "colorchannelmixer=rr=1.000:gg=1.100:bb=1.200,fps=59.94,format=yuv420p",
    ]


def test_filter_args_fit_blur_composites_over_a_blurred_cover():
    rl = layout_lib.resolve(LayoutSpec(mode="fit-blur", crop_aspect="source"),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=59.94)
    assert args == [
        "-filter_complex",
        "[0:v]split=2[a][b];"
        "[a]scale=1280:2276:force_original_aspect_ratio=increase,"
        "crop=1280:2276,boxblur=21:2[bg];"
        "[b]crop=1280:720:x='0.0':y=0,scale=1280:720[fg];"
        "[bg][fg]overlay=0:778,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=59.94,format=yuv420p",
    ]


def test_filter_args_never_emit_the_banned_lutrgb():
    # spec §12: lutrgb produced black frames; colorchannelmixer only
    for spec in (LayoutSpec(mode="fill"),
                 LayoutSpec(mode="fit-blur", crop_aspect="source"),
                 LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90))):
        rl = layout_lib.resolve(spec, (9, 16), (1280, 720), _NATIVE)
        args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
        assert "lutrgb" not in args[1]
        assert "colorchannelmixer" in args[1]


def test_blur_radius_scales_with_canvas_width():
    # a constant radius is nearly sharp on 4K; tie it to the canvas
    rl = layout_lib.resolve(LayoutSpec(mode="fit-blur", crop_aspect="source"),
                            (9, 16), (3840, 2160), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert "boxblur=64:2" in args[1]        # 3840 // 60
