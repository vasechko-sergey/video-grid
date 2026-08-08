import dataclasses
import json, subprocess
import pytest
from scripts import reframe
from scripts.lib import color, ffbin, models
from scripts.lib import layout as layout_lib
from scripts.lib.models import BACKGROUNDS, CropPath, Delivery, LayoutSpec, PanSpec, PathMeta

def _dims(path):
    out = subprocess.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return (s["width"], s["height"])

def _duration(path):
    out = subprocess.run(
        [ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])

def test_compute_path_lead_right():
    # pure path computation (no ffmpeg): subject slides right → crop_x rises
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="lead", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25,
                                crop_ws=[607] * len(route))
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
                                motion=("lateral", "right"), max_step=25,
                                crop_ws=[607] * len(route))
    assert len(path) == 20
    assert all(0 <= x <= 1920 - 607 for x in path)

def test_compute_path_unknown_composition_fails_loud():
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(5)]
    with pytest.raises(ValueError, match="unknown composition"):
        reframe.compute_path(route, composition="Lead", grid="thirds",
                             canvas=(9, 16), src=(1920, 1080),
                             motion=("lateral", "right"), max_step=25,
                             crop_ws=[607] * len(route))

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
    monkeypatch.setattr(reframe, "_probe", lambda src: (3840, 2160, 30.0, 2.5))
    captured = {}
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **k: captured.setdefault("cmd", cmd))
    spec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=models.Delivery("native"))
    reframe.reframe(spec, "src.mp4", str(tmp_path / "r.json"), str(tmp_path / "out.mp4"),
                    str(tmp_path / "path.json"))
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "scale=1214:2160" in vf          # 4K 9:16 crop 1215x2160 → even native, no upscale


@pytest.mark.integration
def test_probe_returns_the_source_duration(sample_clip):
    # the solid filler bounds its synthesized background with `color=:d=<dur>`, so
    # the duration is now load-bearing engine input, not diagnostics. sample_clip is
    # 1920x1080 @ 30fps, 3.0s (tests/conftest.py).
    src_w, src_h, fps, dur = reframe._probe(str(sample_clip))
    assert (src_w, src_h) == (1920, 1080)
    assert fps == pytest.approx(30.0, abs=0.01)
    assert dur == pytest.approx(3.0, abs=0.05)


def test_probe_refuses_a_durationless_source(monkeypatch):
    # An unprobeable duration must RAISE, never fall back to `overlay=:shortest=1`
    # — that fallback would reintroduce the one-frame truncation invisibly, on
    # exactly the files nobody looked at (design §4).
    class _Out:
        stdout = ('{"streams": [{"width": 1280, "height": 720, '
                  '"avg_frame_rate": "30/1"}], "format": {}}')
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **k: _Out())
    with pytest.raises(ValueError, match="no usable duration"):
        reframe._probe("weird.mkv")


def test_probe_prefers_the_stream_duration_over_the_container(monkeypatch):
    # _probe asks for BOTH stream= and format= duration in one ffprobe call,
    # since some containers carry only the latter -- but the docstring says the
    # STREAM's is preferred when both are present. Fake a probe where they
    # disagree (stream=5.0, container=9.0) and pin which one wins: with `-t
    # {duration}` now bounding every render (design §4), silently preferring the
    # wrong source would silently change output length, not just diagnostics.
    class _Out:
        stdout = ('{"streams": [{"width": 1280, "height": 720, "avg_frame_rate": "30/1", '
                  '"duration": "5.0"}], "format": {"duration": "9.0"}}')
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **k: _Out())
    _, _, _, dur = reframe._probe("whatever.mp4")
    assert dur == pytest.approx(5.0)


_NATIVE = Delivery("native", None)


@pytest.mark.parametrize("layout", [
    models.LayoutSpec(mode="fit", crop_aspect="source", background="solid"),
    models.LayoutSpec(mode="fit", crop_aspect="source", background="blur"),
    models.LayoutSpec(mode="fill"),                       # the -vf fast path
    models.LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90),
                      background="solid"),
])
def test_reframe_bounds_every_layout_to_the_source_length(tmp_path, monkeypatch, layout):
    """`-t` is what actually pins a render's length — `color=:d=` alone leaves the
    overlay's timebase mismatched with the tail's `fps` filter, and an exact-rate
    match blows up (measured 46080 frames / 1536s from a 90-frame 3s clip).

    Parametrized over EVERY layout on purpose: `-t` is deliberately unconditional
    so no future filler can forget it, and that decision needs a guard. Making it
    `if background == "solid"` left the entire suite green.

    Pinned as an OUTPUT option — after the filter args, before the output path —
    because `-t` placed before `-i` would seek the source instead of bounding the
    render.
    """
    route = [dict(t=i / 30, x=900.0, y=540.0, w=140.0, h=320.0) for i in range(10)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    cmd = {}
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 3.0))
    monkeypatch.setattr(reframe.proc, "run", lambda c, **k: cmd.setdefault("v", c))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105.0, 122.0, 137.0), delivery=models.Delivery("native"),
                              layout=layout)
    reframe.reframe(spec, "src.mp4", str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    v = cmd["v"]
    assert "-t" in v, f"{layout.mode}/{layout.background}: no -t — the render is unbounded"
    assert v[v.index("-t") + 1] == "3.000000"          # the probed source duration
    assert v.index("-t") > v.index("-i") + 1           # an output option, not an input seek
    assert v.index("-t") < len(v) - 1                  # ...and before the output path


@pytest.mark.integration
def test_solid_and_blur_are_duration_symmetric_with_the_source(sample_clip, tmp_path):
    """The measured regression this whole amendment exists for.

    `overlay=:shortest=1` terminates but lands EXACTLY one frame short of the
    source at any frame rate (golden fixture: source 95 frames, blur 95, solid
    94). One frame is not cosmetic: check_reel measures the assembled reel
    against _LENGTH_TOL (0.5s), so ~15 solid episodes at 30fps eat the whole band
    from this artifact alone. A filler must not change how long the reel is.

    Asserted to within HALF a frame — deliberately tighter than the one-frame
    truncation it guards against, so a one-frame regression cannot hide inside
    the tolerance. Task 7 proves the pad's colour and uniformity; this proves the
    property that is symmetric across fillers.

    sample_clip is 30fps, and that is the POINT, not an accident of which fixture
    was nearest: the timebase blow-up fires on an exact rate match, so it hits
    integer rates and misses the NTSC ones. Run against golden_ride's 59.94 this
    test would pass even with `-t` deleted (design §8) — an integer-rate source is
    the only kind that can see this class of failure at all.
    """
    src_w, src_h, fps, src_probe_dur = reframe._probe(str(sample_clip))
    route_p = tmp_path / "route.json"
    models.route_to_json([models.RoutePoint(t=i / fps, x=900.0, y=540.0, w=80.0, h=200.0)
                          for i in range(int(src_probe_dur * fps))], route_p)

    def _render(name, background):
        out = tmp_path / f"{name}.mp4"
        spec = models.ReframeSpec(composition="break", grid="thirds", canvas=(9, 16),
                                  color_means=(105, 122, 137), delivery=_NATIVE,
                                  layout=models.LayoutSpec(mode="fit", crop_aspect="source",
                                                           background=background))
        reframe.reframe(spec, str(sample_clip), str(route_p), str(out),
                        str(tmp_path / f"{name}_path.json"))
        return out

    assert fps == pytest.approx(round(fps), abs=1e-9), (
        f"sample_clip is {fps}fps — this test is only meaningful on an INTEGER "
        "rate; a fractional one cannot trigger the exact-rate-match blow-up")
    src_dur = _duration(sample_clip)
    half_frame = 0.5 / fps          # derived, not hardcoded: the fixture's rate may change
    assert _duration(_render("solid", "solid")) == pytest.approx(src_dur, abs=half_frame)
    assert _duration(_render("blurred", "blur")) == pytest.approx(src_dur, abs=half_frame)


def test_filter_args_fill_is_pinned_to_todays_chain():
    rl = layout_lib.resolve(LayoutSpec(mode="fill"), (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.1, 1.2), dur=1.584917)
    args = reframe._filter_args(rl, xexpr="577.0", cy=0, grade=grade,
                                fps=59.94, dur=1.584917)
    assert args == [
        "-vf",
        "crop=405:720:x='577.0':y=0,scale=404:720,"
        "colorchannelmixer=rr=1.000:gg=1.100:bb=1.200,fps=59.94,format=yuv420p",
    ]


def test_filter_args_fit_composites_over_a_blurred_cover():
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                            (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=1.584917)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=59.94, dur=1.584917)
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
    # `color` is an INFINITE source, so something must end it — but NOT the
    # overlay: `overlay=:shortest=1` truncates exactly one frame off every render
    # (design §4). The bound goes on the SOURCE, as `d=`, leaving both inputs
    # finite and equal and the overlay options empty for both fillers.
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source",
                                       background="solid"),
                            (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=1.584917)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=59.94, dur=1.584917)
    assert args == [
        "-filter_complex",
        "color=c=black:s=1280x2276:r=59.94:d=1.584917[bg];"
        "[0:v]crop=1280:720:x='0.0':y=0,scale=1280:720[fg];"
        "[bg][fg]overlay=0:778,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=59.94,format=yuv420p",
    ]


def test_filter_args_solid_uses_the_requested_colour():
    # whole-list equality, like every other pin in this file: this is the SOLE
    # guard that background_color reaches the graph, and a prefix assertion would
    # let anything after the colour drift unnoticed.
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source",
                                       background="solid", background_color="#101820"),
                            (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=1.584917)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=59.94, dur=1.584917)
    assert args == [
        "-filter_complex",
        "color=c=#101820:s=1280x2276:r=59.94:d=1.584917[bg];"
        "[0:v]crop=1280:720:x='0.0':y=0,scale=1280:720[fg];"
        "[bg][fg]overlay=0:778,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=59.94,format=yuv420p",
    ]


def test_filter_args_solid_insert_keeps_its_border():
    # the filler is orthogonal to the rect: a bordered card over a solid pad is
    # two colours in one graph, not a third code path.
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1),
                                       rect=(0.05, 0.25, 0.90), background="solid",
                                       border_px=8, border_color="white"),
                            (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
    assert args == [
        "-filter_complex",
        "color=c=black:s=800x1422:r=30:d=2.500000[bg];"
        "[0:v]crop=720:720:x='0.0':y=0,scale=704:704,pad=720:720:8:8:white[fg];"
        "[bg][fg]overlay=40:356,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
        "fps=30,format=yuv420p",
    ]


def test_background_args_refuses_a_filler_it_does_not_know():
    """The exhaustiveness guard. `_background_args` returns early for solid and
    would otherwise fall through to blur, so a future BACKGROUNDS entry with no arm
    of its own would render as a blurred cover — wrong pixels, no error.

    Constructed by replacing `background` on an already-resolved layout, which
    deliberately BYPASSES LayoutSpec's vocabulary gate: that gate is exactly what
    a new entry would pass, so a test routed through it could not reach this line.
    Turning the guard into `if False:` left the whole suite green.
    """
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                            (9, 16), (1280, 720), _NATIVE)
    bogus = dataclasses.replace(rl, background="gradient")
    with pytest.raises(ValueError, match=r"unknown background: 'gradient'") as excinfo:
        reframe._background_args(bogus, fps=30.0, dur=2.5)
    # the enumeration is the only thing that tells an author what IS supported —
    # pin it, not just the word "unknown" (this slice has been bitten three times)
    assert str(BACKGROUNDS) in str(excinfo.value)


_EXPECTED_FG_SRC = {"solid": "[0:v]", "blur": "[b]"}  # solid reads the source once (no split); blur splits it


def test_every_known_background_has_an_arm():
    # The guard above proves an UNKNOWN filler raises. This proves the vocabulary
    # and the implementation have not drifted apart in the other direction: every
    # value LayoutSpec accepts must actually produce a graph -- and the RIGHT
    # one. Asserting fg_src is merely "one of" the two labels stayed green even
    # if the blur arm returned "[0:v]" (the unsplit source) instead of "[b]" --
    # a real defect, since fg would then read footage nothing had scaled/cropped
    # for the background yet.
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                            (9, 16), (1280, 720), _NATIVE)
    for bg in BACKGROUNDS:
        chain, fg_src, _ = reframe._background_args(
            dataclasses.replace(rl, background=bg), fps=30.0, dur=2.5)
        assert chain.endswith("[bg];"), bg
        assert fg_src == _EXPECTED_FG_SRC[bg], bg


def test_filter_args_insert_is_pinned_to_the_rect():
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90)),
                            (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
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
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
    assert "pad=" not in args[1]
    assert "overlay=40:356" in args[1]


def test_filter_args_bordered_insert_pads_the_card():
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90),
                                       border_px=8, border_color="white"),
                            (9, 16), (1280, 720), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
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
    # spec §12: lutrgb produced black frames; colorchannelmixer only.
    # The list is hand-enumerated, so it silently under-covers as the vocabulary
    # grows — every filler needs its own entry, not just every mode.
    for spec in (LayoutSpec(mode="fill"),
                 LayoutSpec(mode="fit", crop_aspect="source"),
                 LayoutSpec(mode="fit", crop_aspect="source", background="solid"),
                 LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90)),
                 LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90),
                            background="solid")):
        rl = layout_lib.resolve(spec, (9, 16), (1280, 720), _NATIVE)
        grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
        args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                    fps=30.0, dur=2.5)
        assert "lutrgb" not in args[1]
        assert "colorchannelmixer" in args[1]


def test_blur_radius_scales_with_canvas_width():
    # a constant radius is nearly sharp on 4K; tie it to the canvas
    rl = layout_lib.resolve(LayoutSpec(mode="fit", crop_aspect="source"),
                            (9, 16), (3840, 2160), _NATIVE)
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
    assert "boxblur=64:2" in args[1]        # 3840 // 60


def test_blur_radius_is_capped_by_the_short_side():
    # boxblur needs radius < min(out_w, out_h) / 4 (strict on ffmpeg 8.1.2); a 3840x200
    # cover's unclamped 3840//60=64 is refused, so the ceiling caps it at (200-1)//4=49
    rl = layout_lib.resolve(LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.4, 0.02, 0.03)),
                            (21, 9), (3840, 2160), Delivery("exact", (3840, 200)))
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
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
    grade = color.grade_chain((1.0, 1.0, 1.0), dur=2.5)
    args = reframe._filter_args(rl, xexpr="0.0", cy=0, grade=grade,
                                fps=30.0, dur=2.5)
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
                                motion=("lateral", "right"), max_step=25,
                                crop_ws=[960] * len(route))
    assert path == [640] * 20
    assert all(0 <= x <= 1920 - 960 for x in path)


def test_compute_path_at_zero_freedom_is_constant_zero():
    # fit at scale 1.0: crop is the whole frame, so the crop cannot move
    route = [dict(t=i / 30, x=300 + i * 40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="break", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25,
                                crop_ws=[1920] * len(route))
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
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.5))
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
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.5))
    monkeypatch.setattr(reframe.proc, "run", lambda c, **k: cmd.setdefault("v", c))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105.0, 122.0, 137.0), delivery=models.Delivery("native"),
                              layout=models.LayoutSpec(mode="fill"))
    reframe.reframe(spec, "src.mp4", str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert "colorchannelmixer=rr=1.000:gg=1.000:bb=1.000" in " ".join(cmd["v"])


# --- colour-as-a-stage Task 6 (Approach A): _filter_args takes a FINISHED grade
# string from color.grade_chain; reframe() builds wb/tone/grade and verifies the
# tone curve before it ever reaches ffmpeg for real ---

def test_filter_args_fast_path_byte_identical_at_defaults():
    # a fill layout + default grade must emit exactly the pre-slice tail (mixer,fps,format)
    rl = layout_lib.resolve(LayoutSpec(mode="fill"), (1080, 1920), (1920, 1080), _NATIVE)
    gains = (1.1, 1.0, 0.9)
    grade = color.grade_chain(gains, dur=3.0)                 # all knobs default
    got = reframe._filter_args(rl, "0", 0, grade, 30.0, 3.0)
    assert got[0] == "-vf"
    assert got[1].endswith(f"{color.mixer_arg(*gains)},fps=30,format=yuv420p")


@pytest.mark.integration
def test_verify_tone_rejects_a_banding_curve():
    # (35,84,118)->(30,100,148) is tone_arg's own docstring example, but it no
    # longer dips — TONE_SAMPLES=13 dense sampling is the fix that case motivated.
    # (50,60,245)->(10,200,245) still does: a ~3.3x expansion crammed into the
    # 50-60 input band forces the fitted spline into 24 real monotonicity
    # violations (measured — see the exploration this test's triple came from).
    with pytest.raises(RuntimeError):
        reframe.verify_tone(color.tone_arg((50, 60, 245), (10, 200, 245)))


@pytest.mark.integration
def test_verify_tone_accepts_a_gentle_monotone_curve():
    reframe.verify_tone(color.tone_arg((30, 100, 148), (35, 110, 150)))   # no raise


# --- reframe.generate_pan_path (design 2026-07-19 §4): the pure generator ---

def test_generate_pan_path_travels_the_declared_extent():
    # freedom 760, 2s at 10fps → 20 samples, 19 intervals, 40px each. The extent
    # is chosen to divide EXACTLY by n-1 so that "constant velocity" can be
    # asserted as written; the non-divisible case is its own test below.
    path, times = reframe.generate_pan_path(
        PanSpec(start=0.0, end=1.0), freedom=760, fps=10.0, dur=2.0, max_speed=750.0)
    assert len(path) == len(times) == 20
    assert path[0] == 0 and path[-1] == 760
    assert times[0] == 0.0 and times[-1] == pytest.approx(1.9)
    # constant velocity: pin the actual step size, not merely that one exists
    steps = {path[i] - path[i - 1] for i in range(1, len(path))}
    assert steps == {40}


def test_generate_pan_path_spreads_rounding_evenly_when_the_extent_does_not_divide():
    # The REAL case — a freedom of 875 rarely divides by n-1. Integer rounding of
    # an exact line can deviate by at most one pixel per step; anything wider
    # means the ramp is not linear (an ease, a rate limit, a savgol bend). This
    # is the assertion the divisible fixture above cannot make.
    path, _ = reframe.generate_pan_path(
        PanSpec(start=0.0, end=1.0), freedom=875, fps=10.0, dur=2.0, max_speed=750.0)
    assert path[0] == 0 and path[-1] == 875
    steps = {path[i] - path[i - 1] for i in range(1, len(path))}
    assert max(steps) - min(steps) <= 1


def test_generate_pan_path_rounds_to_nearest_rather_than_truncating():
    # int() truncation yields the SAME step multiset as round() — merely phase-
    # shifted — so neither a spread bound nor a multiset can tell them apart.
    # Compare against the exact line: every sample must sit within half a pixel
    # of it, which truncation violates as soon as a fraction exceeds .5.
    freedom, fps, dur = 875, 10.0, 2.0
    path, _ = reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=freedom,
                                        fps=fps, dur=dur, max_speed=750.0)
    n = len(path)
    exact = [freedom * i / (n - 1) for i in range(n)]
    assert all(abs(p - e) <= 0.5 for p, e in zip(path, exact))


def test_generate_pan_path_runs_right_to_left_when_end_is_below_start():
    path, _ = reframe.generate_pan_path(
        PanSpec(start=1.0, end=0.0), freedom=800, fps=10.0, dur=2.0, max_speed=750.0)
    assert path[0] == 800 and path[-1] == 0
    assert all(path[i] < path[i - 1] for i in range(1, len(path)))


def test_generate_pan_path_lands_exactly_on_a_partial_extent():
    # Exact equality, not a tolerance: a tolerance would let a re-introduced
    # smoothing pass regress the travel invisibly. (This pins that the declared
    # fractions land exactly; the no-smoothing refusal itself is proved by
    # test_generate_pan_path_never_calls_the_smoother, because a slow pan
    # survives the smoother with these very endpoints intact.)
    path, _ = reframe.generate_pan_path(
        PanSpec(start=0.2, end=0.7), freedom=1000, fps=30.0, dur=3.0, max_speed=750.0)
    assert path[0] == 200
    assert path[-1] == 700


def test_generate_pan_path_never_calls_the_smoother(monkeypatch):
    # THE ACTUAL no-smoothing proof, and it has to be this shape. The endpoint
    # assertions CANNOT make it: pathsmooth's rate limiter only bites near
    # max_speed, so a realistic slow reveal (192 px/s here) survives a full
    # smooth() pass with byte-identical endpoints — measured, not assumed.
    # Assert the BRANCH, not an outcome the other branch also produces.
    monkeypatch.setattr(reframe.pathsmooth, "smooth", lambda *a, **k: pytest.fail(
        "generate_pan_path must not smooth — a generated line has no observation noise"))
    reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=1920,
                              fps=30.0, dur=10.0, max_speed=750.0)


def test_generate_pan_path_refuses_a_crop_with_nowhere_to_go():
    with pytest.raises(ValueError) as e:
        reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=0,
                                  fps=30.0, dur=3.0, max_speed=750.0)
    msg = str(e.value)
    # "has 0px", not a bare "0": the remedy's own "crop_scale below 1.0" contains
    # a "0", so the loose form survives {freedom} failing to interpolate entirely.
    # "px" appears nowhere else in the message, so this can only come from the f-string.
    assert "freedom" in msg and "has 0px" in msg
    assert "crop_scale" in msg          # the remedy names the actual lever


def test_generate_pan_path_refuses_an_extent_that_rounds_away():
    # PanSpec validates FRACTIONS and cannot see the freedom they multiply. A span
    # under half a pixel collapses to a constant — the freedom guard's own failure
    # mode by another road, and just as silent.
    with pytest.raises(ValueError) as e:
        reframe.generate_pan_path(PanSpec(start=0.5, end=0.5004), freedom=875,
                                  fps=30.0, dur=3.0, max_speed=750.0)
    msg = str(e.value)
    assert "STATIC" in msg
    # 0.5*875 = 437.5 and 0.5004*875 = 437.85, and BOTH round to 438 — 437.5 goes
    # up under banker's rounding because 438 is the even neighbour. "438px" rather
    # than a bare "438": the px suffix can only come from the f-string, and pins
    # that the message names the collapsed coordinate rather than some other number.
    assert "438px" in msg
    assert "`pan`" in msg          # the remedy names the actual field to drop


@pytest.mark.parametrize("bad", [0.0, 0, -1.0])
def test_generate_pan_path_refuses_a_clip_with_no_duration(bad):
    # 0 would be ZeroDivisionError — no offending value, no remedy. A NEGATIVE dur
    # is worse: the speed comes out negative, slides under the max_speed ceiling
    # untouched, and n collapses to 2, silently returning a two-frame pan.
    with pytest.raises(ValueError) as e:
        reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=800,
                                  fps=30.0, dur=bad, max_speed=750.0)
    msg = str(e.value)
    assert "duration" in msg and f"{bad}s" in msg


def test_generate_pan_path_refuses_a_pan_faster_than_max_speed():
    # 1000px in 1.0s = 1000 px/s, past the 750 px/s ceiling
    with pytest.raises(ValueError) as e:
        reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=1000,
                                  fps=30.0, dur=1.0, max_speed=750.0)
    msg = str(e.value)
    assert "1000" in msg and "750" in msg          # measured value AND the ceiling
    # all three remedies, because only one of them may be available to the author
    assert "extent" in msg and "longer" in msg and "max_speed" in msg


def test_generate_pan_path_allows_a_pan_exactly_at_max_speed():
    # the gate is `>`, not `>=` — a pan at the ceiling is legal
    path, _ = reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=750,
                                        fps=30.0, dur=1.0, max_speed=750.0)
    assert path[-1] == 750


def test_generate_pan_path_survives_a_clip_shorter_than_two_frames():
    # n is floored at 2 so i/(n-1) can never divide by zero
    path, times = reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=100,
                                            fps=1.0, dur=0.2, max_speed=750.0)
    assert len(path) == len(times) == 2
    assert path == [0, 100]


def test_generate_pan_path_rounds_the_frame_count_rather_than_truncating():
    # 29.97 × 1.0 = 29.97 → round gives 30 samples, int() would give 29. Every
    # other fixture here has an integer dur*fps, so nothing else can see this.
    path, times = reframe.generate_pan_path(PanSpec(start=0.0, end=1.0), freedom=700,
                                            fps=29.97, dur=1.0, max_speed=750.0)
    assert len(path) == len(times) == 30


def test_a_generated_pan_simplifies_to_exactly_two_knots():
    # a straight line is two knots; integer rounding deviates by <= 0.5px, far
    # under _simplify's eps=2.0. Pins that the dense path costs nothing in the
    # emitted expression.
    path, times = reframe.generate_pan_path(
        PanSpec(start=0.0, end=1.0), freedom=800, fps=30.0, dur=3.0, max_speed=750.0)
    assert len(reframe._simplify(path, times)) == 2


# --- reframe() wiring the pan generator in (design 2026-07-19 §6): route_path
# becomes optional, and a pan must never read (or write) a route ---

def test_reframe_without_a_pan_still_reads_the_route(sample_clip, tmp_path, monkeypatch):
    # THE REGRESSION PIN, and it is deliberately not the filtergraph: a pan
    # changes xexpr, which _filter_args merely interpolates, and
    # test_filter_args_fill_is_pinned_to_todays_chain already pins that whole
    # string. What this slice owes is one level up — proof that an ordinary
    # episode did NOT get quietly routed through the generator.
    seen = []
    real = reframe.route_from_json
    monkeypatch.setattr(reframe, "route_from_json", lambda p: seen.append(p) or real(p))
    route = tmp_path / "route.json"
    route.write_text(json.dumps([{"t": 0.0, "x": 640, "y": 360, "w": 100, "h": 200},
                                 {"t": 1.0, "x": 700, "y": 360, "w": 100, "h": 200}]))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"))
    reframe.reframe(spec, str(sample_clip), str(route), str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    assert seen == [str(route)]


def test_reframe_with_a_pan_never_reads_a_route(sample_clip, tmp_path, monkeypatch):
    # Not merely "it works with route_path=None" — that would also pass if the
    # code read a route it happened to find. This asserts the BRANCH.
    monkeypatch.setattr(reframe, "route_from_json",
                        lambda p: pytest.fail("a pan must not read a route"))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"),
                              layout=LayoutSpec(mode="fill", crop_scale=0.5),
                              pan=PanSpec(start=0.2, end=0.7))
    reframe.reframe(spec, str(sample_clip), None, str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    assert (tmp_path / "o.mp4").exists()


def test_reframe_writes_the_pan_bit_into_the_sidecar(sample_clip, tmp_path):
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"),
                              layout=LayoutSpec(mode="fill", crop_scale=0.5),
                              pan=PanSpec(start=0.2, end=0.7))
    reframe.reframe(spec, str(sample_clip), None, str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    meta = PathMeta.from_json(tmp_path / "path.meta.json")
    assert meta.pan is True


def test_reframe_without_a_pan_writes_a_sidecar_that_says_so(sample_clip, tmp_path):
    route = tmp_path / "route.json"
    route.write_text(json.dumps([{"t": 0.0, "x": 640, "y": 360, "w": 100, "h": 200},
                                 {"t": 1.0, "x": 700, "y": 360, "w": 100, "h": 200}]))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"))
    reframe.reframe(spec, str(sample_clip), str(route), str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    assert PathMeta.from_json(tmp_path / "path.meta.json").pan is False


def test_reframe_pan_path_lands_on_the_declared_fractions(sample_clip, tmp_path):
    # end-to-end through the real render: what reframe WROTE to path.json must
    # still be the exact extent, i.e. nothing between the generator and disk
    # re-smoothed or re-clamped it
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"),
                              layout=LayoutSpec(mode="fill", crop_scale=0.5),
                              pan=PanSpec(start=0.0, end=1.0))
    reframe.reframe(spec, str(sample_clip), None, str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    meta = PathMeta.from_json(tmp_path / "path.meta.json")
    xs = CropPath.from_json(str(tmp_path / "path.json")).xs
    assert xs[0] == 0
    assert xs[-1] == meta.freedom


def test_reframe_writes_no_route_json_for_a_pan(sample_clip, tmp_path):
    # an empty route.json would MEAN "the tracker found nobody" — a fabricated
    # observation. Nothing route-shaped may appear beside the outputs.
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"),
                              layout=LayoutSpec(mode="fill", crop_scale=0.5),
                              pan=PanSpec(start=0.0, end=1.0))
    reframe.reframe(spec, str(sample_clip), None, str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    assert not (tmp_path / "route.json").exists()


def test_reframe_refuses_a_missing_route_when_there_is_no_pan(sample_clip, tmp_path):
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137), delivery=Delivery("native"))
    with pytest.raises(ValueError) as e:
        reframe.reframe(spec, str(sample_clip), None, str(tmp_path / "o.mp4"),
                        str(tmp_path / "path.json"))
    msg = str(e.value)
    assert "route" in msg and "pan" in msg


def test_reframe_pan_centres_the_crop_vertically(sample_clip, tmp_path):
    # no route means no mean_y, and a headroom rule with nothing to give headroom
    # TO is arbitrary — centre is the neutral choice.
    #
    # canvas=(1,1) + crop_scale=0.5 against sample_clip (1920x1080) resolves to
    # crop_w=crop_h=540 — STRICTLY less than src_h=1080 (measured), so this does
    # NOT degenerate into the crop_h>=src_h→0 special case that g.crop_y and the
    # centre formula would otherwise share trivially. The expected value here is
    # 270, which g.crop_y(subject_y, 540, 1080) only reproduces at subject_y=513
    # — not any "natural" value (0, crop_h/2, src_h/2, crop_h, src_h) a stray
    # reuse of the route branch could plausibly produce — so the two formulas
    # are genuinely distinguished by this fixture.
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(1, 1),
                              color_means=(105, 122, 137), delivery=Delivery("native"),
                              layout=LayoutSpec(mode="fill", crop_scale=0.5),
                              pan=PanSpec(start=0.0, end=1.0))
    reframe.reframe(spec, str(sample_clip), None, str(tmp_path / "o.mp4"),
                    str(tmp_path / "path.json"))
    meta = PathMeta.from_json(tmp_path / "path.meta.json")
    src_h = meta.src_dims[1]
    assert meta.crop_h < src_h          # guard: the fixture must not have degenerated
    assert meta.crop_y == max(0, (src_h - meta.crop_h) // 2)


# --- reframe(stabilized=): a FACT ABOUT `src`, recorded and nowhere else
# consumed (design 2026-07-20 §6.2) ---

def test_reframe_records_that_its_source_was_stabilized(monkeypatch, tmp_path):
    """reframe does not stabilize — the flag is a FACT ABOUT ITS `src`, handed in
    by the caller that did. It flows to the sidecar and nowhere else; a
    ReframeSpec.stabilize would have been an instruction reframe cannot carry out
    (design 2026-07-20 §6.2)."""
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.0))
    monkeypatch.setattr(reframe.proc, "run", lambda cmd, **k: None)
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                              color_means=(105, 122, 137), delivery=Delivery())
    route = tmp_path / "route.json"
    route.write_text(json.dumps([{"t": 0.0, "x": 960.0, "y": 540.0, "w": 100.0, "h": 200.0},
                                 {"t": 1.0, "x": 960.0, "y": 540.0, "w": 100.0, "h": 200.0}]))
    path_out = tmp_path / "path.json"
    reframe.reframe(spec, "seg.mp4", str(route), str(tmp_path / "o.mp4"), str(path_out),
                    stabilized=True)
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert meta.stabilized is True


@pytest.mark.integration
def test_reframe_passes_the_fps_resolved_window_to_compute_path(tmp_path, monkeypatch):
    # A 30fps fixture can't prove this: window_frames(0.25, 30) == 7, the SAME
    # value compute_path's own default falls back to, so a still-hardcoded
    # default would pass unnoticed. 60fps resolves to 15 — the only fps that
    # tells "resolved from spec.smooth_window_s" apart from "old default".
    captured = {}
    real = reframe.compute_path
    def spy(*a, **k):
        captured["smooth_window"] = k.get("smooth_window")
        return real(*a, **k)
    monkeypatch.setattr(reframe, "compute_path", spy)
    src = tmp_path / "s60.mp4"
    subprocess.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
                    "-i", "color=c=gray:s=1920x1080:d=1:r=60", "-pix_fmt", "yuv420p",
                    str(src)], check=True)
    route = [dict(t=i / 60, x=960.0, y=540.0, w=140.0, h=320.0) for i in range(60)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    spec = models.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                              color_means=(105, 122, 137),
                              delivery=Delivery.from_spec("exact:1080x1920"),
                              smooth_window_s=0.25)
    reframe.reframe(spec, str(src), str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert captured["smooth_window"] == reframe.pathsmooth.window_frames(0.25, 60.0) == 15
