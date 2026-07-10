import json
import pytest
from scripts.lib import models as m


def test_routepoint_roundtrip():
    d = {"t": 0.5, "x": 300.0, "y": 500.0, "w": 140.0, "h": 320.0}
    p = m.RoutePoint.from_dict(d)
    assert (p.t, p.x, p.y, p.w, p.h) == (0.5, 300.0, 500.0, 140.0, 320.0)
    assert p.to_dict() == d


def test_route_json_roundtrip(tmp_path):
    pts = [m.RoutePoint(i / 30, 300 + i, 500, 140, 320) for i in range(3)]
    fp = tmp_path / "route.json"
    m.route_to_json(pts, fp)
    back = m.route_from_json(fp)
    assert [p.to_dict() for p in back] == [p.to_dict() for p in pts]
    assert isinstance(json.loads(fp.read_text()), list)


def test_trackmeta_roundtrip():
    d = {"hero": 3, "ambiguous": True, "intent": "action", "features": {"3": {"n": 5}}}
    tm = m.TrackMeta.from_dict(d)
    assert tm.hero == 3 and tm.ambiguous is True and tm.intent == "action"
    assert tm.to_dict() == d


def test_trackmeta_hero_none():
    tm = m.TrackMeta.from_dict({"hero": None, "ambiguous": False, "intent": "static", "features": {}})
    assert tm.hero is None and tm.to_dict()["hero"] is None


def test_croppath_json_roundtrip(tmp_path):
    fp = tmp_path / "path.json"
    m.CropPath([100, 101, 102]).to_json(fp)
    assert json.loads(fp.read_text()) == [100, 101, 102]
    assert m.CropPath.from_json(fp).xs == [100, 101, 102]
    assert len(m.CropPath([1, 2, 3])) == 3


def test_checkresult_detail_pass_key_does_not_clobber():
    # detail carrying a stale "pass" must not override the real passed flag
    d = m.CheckResult("on_line", True, {"pass": "stale", "ratio": 0.9}).to_dict()
    assert d == {"ratio": 0.9, "pass": True}


def test_report_overall_and_fail_reasons():
    checks = {
        "on_line": m.CheckResult("on_line", True, {"ratio": 0.95}),
        "jitter": m.CheckResult("jitter", False, {"worst_reversal": 9.0}),
        "framing": m.CheckResult("framing", None, {"status": "editorial-only"}),
    }
    r = m.Report(checks=checks, attempt=2)
    assert r.overall is False
    assert r.fail_reasons == ["jitter"]


def test_report_to_dict_schema():
    checks = {
        "on_line": m.CheckResult("on_line", True, {"ratio": 0.95}),
        "framing": m.CheckResult("framing", None, {"status": "editorial-only"}),
    }
    d = m.Report(checks=checks, attempt=1).to_dict()
    assert d["checks"]["on_line"] == {"ratio": 0.95, "pass": True}      # pass-bearing
    assert d["checks"]["framing"] == {"status": "editorial-only"}       # status-only, no pass key
    assert d["overall"] is True and d["attempt"] == 1 and d["fail_reasons"] == []


def test_report_from_dict_roundtrip(tmp_path):
    src = {"checks": {"on_line": {"ratio": 0.9, "pass": True},
                      "black_frames": {"boundary_lumas": [120.0], "pass": False},
                      "horizon": {"status": "not-implemented"}},
           "overall": False, "attempt": 3, "fail_reasons": ["black_frames"]}
    r = m.Report.from_dict(src)
    assert r.overall is False and r.fail_reasons == ["black_frames"] and r.attempt == 3
    fp = tmp_path / "report.json"
    r.write(fp)
    assert json.loads(fp.read_text())["checks"]["on_line"]["pass"] is True


def test_delivery_short_edge_across_aspects():
    # crop aspect drives the derived edge; short edge pinned to 1080; even dims
    assert m.Delivery("short_edge", 1080).dims(1215, 2160) == (1080, 1920)   # 9:16
    assert m.Delivery("short_edge", 1080).dims(1920, 1080) == (1920, 1080)   # 16:9
    assert m.Delivery("short_edge", 1080).dims(1000, 1000) == (1080, 1080)   # 1:1
    assert m.Delivery("short_edge", 1080).dims(864, 1080) == (1080, 1350)    # 4:5


def test_delivery_long_edge():
    assert m.Delivery("long_edge", 2160).dims(1215, 2160) == (1214, 2160)    # long=height
    assert m.Delivery("long_edge", 1920).dims(1920, 1080) == (1920, 1080)


def test_delivery_native_even_no_upscale():
    assert m.Delivery("native").dims(1215, 2160) == (1214, 2160)   # even-adjusted, no scale
    assert m.Delivery("native").dims(607, 1080) == (606, 1080)


def test_delivery_exact():
    assert m.Delivery("exact", (1080, 1920)).dims(999, 999) == (1080, 1920)


def test_delivery_from_spec():
    assert m.Delivery.from_spec(None).mode == "native"
    assert m.Delivery.from_spec("native").mode == "native"
    assert m.Delivery.from_spec("short_edge:1080") == m.Delivery("short_edge", 1080)
    assert m.Delivery.from_spec("exact:1080x1920") == m.Delivery("exact", (1080, 1920))


def test_delivery_rejects_bad():
    with pytest.raises(ValueError, match="mode"):
        m.Delivery("weird")
    with pytest.raises(ValueError, match="short_edge"):
        m.Delivery("short_edge", -5)
    # pin the positive-ints message — "exact" alone also matches the parity
    # message below, and an over-loose match has bitten this codebase before
    with pytest.raises(ValueError, match="exact needs .w, h. positive ints"):
        m.Delivery("exact", (1080,))


def test_delivery_exact_rejects_odd_dims():
    # exact must refuse odd sides at construction — h.264/yuv420p needs both
    # divisible by 2. match "even dimensions" so this cannot pass on the
    # positive-ints message, which also contains "exact".
    with pytest.raises(ValueError, match="exact needs even dimensions"):
        m.Delivery("exact", (405, 721))
    with pytest.raises(ValueError, match="exact needs even dimensions"):
        m.Delivery("exact", (405, 720))   # one odd side is enough
    with pytest.raises(ValueError, match="exact needs even dimensions"):
        m.Delivery("exact", (404, 721))
    # from_spec constructs the same object and must refuse identically —
    # not swallowed into the generic "unparseable" message
    with pytest.raises(ValueError, match="exact needs even dimensions"):
        m.Delivery.from_spec("exact:405x721")


def test_delivery_long_edge_real_scaling():
    assert m.Delivery("long_edge", 2160).dims(608, 1080) == (1216, 2160)   # 2x upscale
    assert m.Delivery("long_edge", 540).dims(540, 1080) == (270, 540)      # downscale
    assert m.Delivery.from_spec("long_edge:2160") == m.Delivery("long_edge", 2160)


def test_delivery_dims_rejects_nonpositive_crop():
    with pytest.raises(ValueError, match="positive crop"):
        m.Delivery("short_edge", 1080).dims(1080, 0)
    with pytest.raises(ValueError, match="positive crop"):
        m.Delivery("native").dims(-10, 100)


def test_delivery_from_spec_malformed_raises_clean():
    for bad in ("short_edge:", "exact:1080", "exact:axb"):
        with pytest.raises(ValueError, match="unparseable"):
            m.Delivery.from_spec(bad)
    with pytest.raises(ValueError, match="string"):
        m.Delivery.from_spec(123)
    # a bad MODE still gets its own specific message, not "unparseable"
    with pytest.raises(ValueError, match="mode"):
        m.Delivery.from_spec("bogus:5")


def test_trackspec_defaults_and_validation():
    s = m.TrackSpec(src="seg.mp4")
    assert s.model == "yolo11n-seg.pt" and s.intent == "action" and s.seed_bbox is None
    with pytest.raises(ValueError, match="model"):
        m.TrackSpec(src="s.mp4", model="bogus.pt")
    with pytest.raises(ValueError, match="intent"):
        m.TrackSpec(src="s.mp4", intent="cinematic")
    with pytest.raises(ValueError, match="seed_bbox"):
        m.TrackSpec(src="s.mp4", seed_bbox=(1, 2, 3))
    m.TrackSpec(src="s.mp4", seed_bbox=(1, 2, 3, 4))   # 4-tuple ok


def test_reframespec_validation():
    ok = dict(composition="lead", grid="thirds", canvas=(9, 16),
              color_means=(105, 122, 137), delivery=m.Delivery("native"))
    m.ReframeSpec(**ok)
    with pytest.raises(ValueError, match="composition"):
        m.ReframeSpec(**{**ok, "composition": "hero"})
    with pytest.raises(ValueError, match="color_means"):
        m.ReframeSpec(**{**ok, "color_means": (105, 0, 137)})     # #G positivity
    with pytest.raises(ValueError, match="stabilize"):
        m.ReframeSpec(**{**ok, "stabilize": True})
    with pytest.raises(ValueError, match="canvas"):
        m.ReframeSpec(**{**ok, "canvas": (9, 0)})


def test_checkspec_defaults():
    s = m.CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    assert s.attempt == 1 and s.black_floor == 6.0 and s.black_rel == 0.35
    with pytest.raises(ValueError, match="target_dur"):
        m.CheckSpec(composition="lead", grid="thirds", target_dur=0)


def test_check_spec_no_longer_carries_canvas_or_src_dims():
    spec = m.CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    assert not hasattr(spec, "canvas")
    assert not hasattr(spec, "src_dims")


def test_storyboardspec_validation():
    assert m.StoryboardSpec().n == 6
    with pytest.raises(ValueError, match="n"):
        m.StoryboardSpec(n=0)
    with pytest.raises(ValueError, match="grid"):
        m.StoryboardSpec(grids=("golden",))


def test_spec_type_errors_are_value_errors():
    # wrong TYPE (not just wrong value) must raise ValueError-with-remedy, not TypeError
    with pytest.raises(ValueError, match="color_means"):
        m.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                      color_means=None, delivery=m.Delivery("native"))
    with pytest.raises(ValueError, match="max_speed"):
        m.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                      color_means=(105, 122, 137), delivery=m.Delivery("native"), max_speed=None)
    with pytest.raises(ValueError, match="target_dur"):
        m.CheckSpec(composition="lead", grid="thirds", target_dur=None)
    with pytest.raises(ValueError, match="grids"):
        m.StoryboardSpec(grids="thirds")     # bare string, not a list


def test_storyboardspec_grids_nonlist_is_value_error():
    for bad in (None, 5, 3.14):
        with pytest.raises(ValueError, match="grids"):
            m.StoryboardSpec(grids=bad)
    with pytest.raises(ValueError, match="grids"):
        m.StoryboardSpec(grids="thirds")     # bare string still rejected


def test_trackspec_empty_src_and_reframespec_delivery_type():
    with pytest.raises(ValueError, match="src"):
        m.TrackSpec(src="")
    with pytest.raises(ValueError, match="delivery"):
        m.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                      color_means=(105, 122, 137), delivery="native")   # str, not Delivery


def test_delivery_dims_takes_floats_and_evens_each_side():
    d = m.Delivery("native", None)
    # the fill case: canvas floats equal the crop, and the answer is today's output
    assert d.dims(405.0, 720.0) == (404, 720)
    # the fit-blur case: 1280 wide, 16/9 tall. Evening the width first and
    # deriving the height from it would give 718, not 720 — hence floats.
    assert d.dims(1280.0, 1280.0 * 16 / 9) == (1280, 2276)


def test_layout_spec_fill_defaults():
    s = m.LayoutSpec(mode="fill")
    assert (s.mode, s.crop_aspect, s.crop_scale, s.rect) == ("fill", "canvas", 1.0, None)


def test_layout_spec_fit_blur_and_insert_construct():
    assert m.LayoutSpec(mode="fit-blur", crop_aspect="source").rect is None
    s = m.LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90))
    assert s.rect == (0.05, 0.25, 0.90)


def test_layout_spec_rejects_unknown_mode():
    with pytest.raises(ValueError, match="fill/fit-blur/insert"):
        m.LayoutSpec(mode="split")


def test_layout_spec_rejects_unknown_background():
    with pytest.raises(ValueError, match="solid lands with fit-solid"):
        m.LayoutSpec(mode="fit-blur", crop_aspect="source", background="solid")


def test_layout_spec_rejects_bad_scale():
    with pytest.raises(ValueError, match=r"\(0.0, 1.0\]"):
        m.LayoutSpec(mode="fit-blur", crop_aspect="source", crop_scale=0.0)


def test_layout_spec_rejects_bad_aspect():
    with pytest.raises(ValueError, match="canvas.*source.*pair"):
        m.LayoutSpec(mode="fit-blur", crop_aspect="wide")


def test_layout_spec_fill_must_be_canvas_aspect_and_full_rect():
    with pytest.raises(ValueError, match="an insert, and must say so"):
        m.LayoutSpec(mode="fill", rect=(0.1, 0.1, 0.5))
    with pytest.raises(ValueError, match="crop_aspect 'canvas'"):
        m.LayoutSpec(mode="fill", crop_aspect="source")


def test_layout_spec_fit_blur_takes_no_rect():
    with pytest.raises(ValueError, match="fit-blur spans the full canvas width"):
        m.LayoutSpec(mode="fit-blur", crop_aspect="source", rect=(0.0, 0.1, 0.8))


def test_layout_spec_insert_needs_a_rect():
    with pytest.raises(ValueError, match="insert needs a rect"):
        m.LayoutSpec(mode="insert", crop_aspect=(1, 1))


def test_layout_spec_rejects_a_rect_off_the_canvas():
    with pytest.raises(ValueError, match=r"x \+ w"):
        m.LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.5, 0.1, 0.8))
    # "fractions" appears in three of LayoutSpec's messages; pin the bounds one
    with pytest.raises(ValueError, match="w must be in"):
        m.LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.0, 0.1, 0.0))


def test_layout_spec_border_defaults_to_off():
    s = m.LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90))
    assert (s.border_px, s.border_color) == (0, "white")


def test_layout_spec_rejects_a_bad_border():
    ok = dict(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90))
    with pytest.raises(ValueError, match="non-negative int"):
        m.LayoutSpec(**ok, border_px=-2)
    with pytest.raises(ValueError, match="non-empty ffmpeg colour"):
        m.LayoutSpec(**ok, border_color="")
    with pytest.raises(ValueError, match="break the ffmpeg filtergraph"):
        m.LayoutSpec(**ok, border_color="white,drawbox=t=fill")


def test_layout_spec_fill_refuses_a_border():
    with pytest.raises(ValueError, match="a bordered frame is an insert"):
        m.LayoutSpec(mode="fill", border_px=8)


def test_path_meta_round_trips_through_json(tmp_path):
    # every field distinct: a from_dict that read crop_w out of src_dims would
    # survive a fixture where crop_w happened to equal the source width
    pm = m.PathMeta(mode="insert", crop_w=720, crop_h=648, crop_y=36,
                    src_dims=(1280, 720), canvas=(9, 16), out_dims=(800, 1422),
                    rect_px=(40, 356, 720, 648), freedom=560)
    p = tmp_path / "path.meta.json"
    pm.write(p)
    assert m.PathMeta.from_json(p) == pm


def test_path_meta_from_json_reports_a_missing_file_with_a_remedy(tmp_path):
    with pytest.raises(RuntimeError, match="re-run reframe"):
        m.PathMeta.from_json(tmp_path / "absent.meta.json")


def test_path_meta_from_dict_reports_a_truncated_sidecar_with_a_remedy():
    # a run that died mid-write leaves a parseable file with fields missing;
    # a bare KeyError('crop_w') is not something a stranger can act on
    with pytest.raises(RuntimeError, match="has no field"):
        m.PathMeta.from_dict({"mode": "fill", "crop_h": 720})


def test_path_meta_from_json_reports_an_unparseable_sidecar_with_a_remedy(tmp_path):
    """The case the message above only *names*: a run that died mid-write leaves
    a file that does not parse at all, so from_dict is never reached. Before this
    was handled, json.loads raised a bare JSONDecodeError pointing at a column
    number — no file, no remedy, and nothing to tell the reader that `reframe`
    is what regenerates it."""
    p = tmp_path / "path.meta.json"
    p.write_text('{"mode": "fill", "crop_w": 405')       # truncated mid-write
    with pytest.raises(RuntimeError, match="is corrupt"):
        m.PathMeta.from_json(p)
    with pytest.raises(RuntimeError, match="re-run reframe"):
        m.PathMeta.from_json(p)


def test_path_meta_from_dict_reports_an_unusable_field_with_a_remedy():
    # present but the wrong type: int("abc") raises a bare ValueError that names
    # neither the sidecar nor the fix
    d = dict(mode="fill", crop_w="abc", crop_h=720, crop_y=0, src_dims=[1280, 720],
             canvas=[9, 16], out_dims=[404, 720], rect_px=[0, 0, 404, 720], freedom=875)
    with pytest.raises(RuntimeError, match="unusable field"):
        m.PathMeta.from_dict(d)


def test_export_profile_defaults_are_the_silent_reel():
    p = m.REEL_H264
    assert (p.vcodec, p.crf, p.pix_fmt, p.container) == ("libx264", 18, "yuv420p", "mp4")
    assert p.faststart is True and p.acodec is None


def test_export_profile_silent_args_use_an_and_faststart():
    a = m.REEL_H264.args()
    assert "-an" in a
    assert a[a.index("-movflags") + 1] == "+faststart"
    assert "-c:v" in a and a[a.index("-c:v") + 1] == "libx264"
    assert "scale=" not in " ".join(a)          # deliver never re-scales


def test_export_profile_maxrate_adds_bufsize():
    a = m.ExportProfile(maxrate_kbps=9000).args()
    assert a[a.index("-maxrate") + 1] == "9000k"
    assert a[a.index("-bufsize") + 1] == "18000k"


def test_export_profile_audio_args_when_voiced():
    a = m.ExportProfile(acodec="aac", abitrate_kbps=192).args()
    assert "-an" not in a
    assert a[a.index("-c:a") + 1] == "aac" and a[a.index("-b:a") + 1] == "192k"


@pytest.mark.parametrize("kw, msg", [
    (dict(crf=60), "0..51"),
    (dict(crf=-1), "0..51"),
    (dict(crf=True), "0..51"),
    (dict(pix_fmt=""), "pixel format"),
    (dict(vcodec=""), "codec name"),
    (dict(container=""), "container"),
    (dict(fps=0), "positive number or None"),
    (dict(fps=True), "positive number or None"),
    (dict(maxrate_kbps=0), "positive int or None"),
    (dict(maxrate_kbps=True), "positive int or None"),
    (dict(abitrate_kbps=192), "acodec is None"),
    (dict(acodec="aac", abitrate_kbps=True), "positive int or None"),
])
def test_export_profile_rejects_bad_construction(kw, msg):
    with pytest.raises(ValueError, match=msg):
        m.ExportProfile(**kw)
