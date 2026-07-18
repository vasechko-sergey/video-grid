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
                                motion=("lateral", "right"), max_step=25, crop_w=607)
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
                                motion=("lateral", "right"), max_step=25, crop_w=607)
    assert len(path) == 20
    assert all(0 <= x <= 1920 - 607 for x in path)

def test_compute_path_unknown_composition_fails_loud():
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(5)]
    with pytest.raises(ValueError, match="unknown composition"):
        reframe.compute_path(route, composition="Lead", grid="thirds",
                             canvas=(9, 16), src=(1920, 1080),
                             motion=("lateral", "right"), max_step=25, crop_w=607)

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


def test_filter_args_fit_composites_over_a_blurred_cover():
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
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


def test_filter_args_solid_synthesizes_its_background():
    # blur reads the source TWICE (cover + content) and therefore splits; solid
    # synthesizes its background and reads the source once, so there is no split.
    # `shortest=1` is load-bearing: `color` is an INFINITE source, and without it
    # the overlay never sees EOF on either input and the encode does not finish.
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source",
                                       background="solid"),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=59.94)
    assert args == [
        "-filter_complex",
        "color=c=black:s=1280x2276:r=59.94[bg];"
        "[0:v]crop=1280:720:x='0.0':y=0,scale=1280:720[fg];"
        "[bg][fg]overlay=0:778:shortest=1,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=59.94,format=yuv420p",
    ]


def test_filter_args_solid_uses_the_requested_colour():
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source",
                                       background="solid", background_color="#101820"),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=59.94)
    assert args[1].startswith("color=c=#101820:s=1280x2276:r=59.94[bg];")


def test_filter_args_solid_insert_keeps_its_border():
    # the filler is orthogonal to the rect: a bordered card over a solid pad is
    # two colours in one graph, not a third code path.
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1),
                                       rect=(0.05, 0.25, 0.90), background="solid",
                                       border_px=8, border_color="white"),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert args == [
        "-filter_complex",
        "color=c=black:s=800x1422:r=30[bg];"
        "[0:v]crop=720:720:x='0.0':y=0,scale=704:704,pad=720:720:8:8:white[fg];"
        "[bg][fg]overlay=40:356:shortest=1,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=30,format=yuv420p",
    ]


def test_filter_args_insert_is_pinned_to_the_rect():
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90)),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert args == [
        "-filter_complex",
        "[0:v]split=2[a][b];"
        "[a]scale=800:1422:force_original_aspect_ratio=increase,"
        "crop=800:1422,boxblur=13:2[bg];"
        "[b]crop=720:720:x='0.0':y=0,scale=720:720[fg];"
        "[bg][fg]overlay=40:356,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=30,format=yuv420p",
    ]


def test_filter_args_borderless_insert_is_byte_identical():
    # b == 0 must emit exactly the pre-border string: pad vanishes, overlay is rx:ry
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90)),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert "pad=" not in args[1]
    assert "overlay=40:356" in args[1]


def test_filter_args_bordered_insert_pads_the_card():
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90),
                                       border_px=8, border_color="white"),
                            (9, 16), (1280, 720), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert args == [
        "-filter_complex",
        "[0:v]split=2[a][b];"
        "[a]scale=800:1422:force_original_aspect_ratio=increase,"
        "crop=800:1422,boxblur=13:2[bg];"
        "[b]crop=720:720:x='0.0':y=0,scale=704:704,pad=720:720:8:8:white[fg];"
        "[bg][fg]overlay=40:356,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=30,format=yuv420p",
    ]


def test_filter_args_never_emit_the_banned_lutrgb():
    # spec §12: lutrgb produced black frames; colorchannelmixer only
    for spec in (LayoutSpec(mode="fill"),
                 LayoutSpec(mode="fit", crop_aspect="source"),
                 LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90))):
        rl = layout_lib.resolve(spec, (9, 16), (1280, 720), _NATIVE)
        args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
        assert "lutrgb" not in args[1]
        assert "colorchannelmixer" in args[1]


def test_blur_radius_scales_with_canvas_width():
    # a constant radius is nearly sharp on 4K; tie it to the canvas
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                            (9, 16), (3840, 2160), _NATIVE)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert "boxblur=64:2" in args[1]        # 3840 // 60


def test_blur_radius_is_capped_by_the_short_side():
    # boxblur needs radius < min(out_w, out_h) / 4 (strict on ffmpeg 8.1.2); a 3840x200
    # cover's unclamped 3840//60=64 is refused, so the ceiling caps it at (200-1)//4=49
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.4, 0.02, 0.03)),
                            (21, 9), (3840, 2160), Delivery("exact", (3840, 200)))
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert "boxblur=49:2" in args[1]


def test_the_radius_floor_never_beats_the_chroma_ceiling():
    """Written as max(2, min(w // 60, ceiling)), the floor wins whenever the
    ceiling is 0 or 1 — and asks ffmpeg for exactly the radius the ceiling exists
    to forbid. A 256:1 canvas resolves to 1280x4, where min/4 = 1 and ffmpeg 8.1.2
    requires radius strictly < 1: the ceiling ((4 - 1) // 4 = 0) yields a radius-0
    no-op, not the floor's 2. (An unclamped 2 drew "Invalid chroma_param radius
    value 2, must be >= 0 and < 1" from real ffmpeg.) Below 8px blur is meaningless."""
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect=(256, 1)),
                            (256, 1), (1280, 720), _NATIVE)
    assert (rl.out_w, rl.out_h) == (1280, 4)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, gains=(1.0, 1.0, 1.0), fps=30.0)
    assert "boxblur=0:2" in args[1]


def test_reframe_spec_defaults_to_a_fill_layout():
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=_NATIVE)
    assert spec.layout == models.LayoutSpec(mode="fill")


def test_compute_path_takes_crop_w_from_the_caller():
    # A stationary subject makes the path constant, and its one value names the
    # crop_w that produced it: the subject sits on the left third of the window,
    # so x - crop_w/3. crop_w=960 gives 640; the canvas-derived 607 gives 758.
    # A bounds-only assertion would pass under either, and this test exists
    # precisely to catch a compute_path that went back to deriving crop_w itself.
    route = [dict(t=i / 30, x=960.0, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="lead", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25, crop_w=960)
    assert path == [640] * 20
    assert all(0 <= x <= 1920 - 960 for x in path)


def test_compute_path_at_zero_freedom_is_constant_zero():
    # fit at scale 1.0: crop is the whole frame, so the crop cannot move
    route = [dict(t=i / 30, x=300 + i * 40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="break", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25, crop_w=1920)
    assert path == [0] * 20


@pytest.mark.integration
def test_reframe_writes_a_truthful_sidecar(sample_clip, tmp_path):
    # sample_clip is 1920x1080 @ 30fps, 3.0s (tests/conftest.py)
    route_p = tmp_path / "route.json"
    models.route_to_json([models.RoutePoint(t=i / 30, x=600.0 + i * 4, y=540.0, w=80.0, h=200.0)
                          for i in range(90)], route_p)
    out, path_out = tmp_path / "ep.mp4", tmp_path / "path.json"
    spec = models.ReframeSpec(composition="break", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=_NATIVE,
                              layout=models.LayoutSpec(mode="fit", crop_aspect="source"))
    reframe.reframe(spec, str(sample_clip), str(route_p), str(out), str(path_out))
    meta = models.PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert meta.mode == "fit"
    assert (meta.crop_w, meta.crop_h) == (1920, 1080)
    assert meta.freedom == 0
    assert meta.src_dims == (1920, 1080)
    assert meta.canvas == (9, 16)
    # the sidecar's out_dims must equal what ffmpeg actually produced
    assert meta.out_dims == _dims(out)


def test_reframe_applies_color_correct_onto_the_grade(tmp_path, monkeypatch):
    # color_means == TARGET → base gains are all 1.0, so the emitted mixer shows
    # the color_correct factors verbatim. Proves the override reaches the filter.
    route = [dict(t=i / 30, x=900.0, y=540.0, w=140.0, h=320.0) for i in range(10)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    cmd = {}
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0))
    monkeypatch.setattr(reframe.proc, "run", lambda c, **k: cmd.setdefault("v", c))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105.0, 122.0, 137.0), delivery=models.Delivery("native"),
                              layout=models.LayoutSpec(mode="fill"), color_correct=(1.2, 1.0, 0.9))
    reframe.reframe(spec, "src.mp4", str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    joined = " ".join(cmd["v"])
    assert "colorchannelmixer=rr=1.200:gg=1.000:bb=0.900" in joined


def test_reframe_without_color_correct_is_unit_grade(tmp_path, monkeypatch):
    route = [dict(t=i / 30, x=900.0, y=540.0, w=140.0, h=320.0) for i in range(10)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    cmd = {}
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0))
    monkeypatch.setattr(reframe.proc, "run", lambda c, **k: cmd.setdefault("v", c))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105.0, 122.0, 137.0), delivery=models.Delivery("native"),
                              layout=models.LayoutSpec(mode="fill"))
    reframe.reframe(spec, "src.mp4", str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert "colorchannelmixer=rr=1.000:gg=1.000:bb=1.000" in " ".join(cmd["v"])
