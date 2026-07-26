import dataclasses
import json
import pytest
from scripts.lib import manifest
from scripts.lib import models as m
from scripts.lib.models import LayoutSpec, PanSpec, ReelCheckSpec


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
    # pin_matched and degraded ride along explicitly: to_dict() always emits both (None here,
    # since this dict predates any pin or degradation), so the round-trip dict must include them too.
    d = {"hero": 3, "ambiguous": True, "intent": "action", "features": {"3": {"n": 5}},
         "pin_matched": None, "degraded": None}
    tm = m.TrackMeta.from_dict(d)
    assert tm.hero == 3 and tm.ambiguous is True and tm.intent == "action"
    assert tm.to_dict() == d


def test_trackmeta_hero_none():
    tm = m.TrackMeta.from_dict({"hero": None, "ambiguous": False, "intent": "static", "features": {}})
    assert tm.hero is None and tm.to_dict()["hero"] is None


def test_track_meta_pin_matched_round_trips():
    for v in (True, False, None):
        tm = m.TrackMeta(hero=1, pin_matched=v)
        assert m.TrackMeta.from_dict(tm.to_dict()).pin_matched is v


def test_track_meta_pin_matched_defaults_to_none():
    assert m.TrackMeta().pin_matched is None


def test_trackmeta_degraded_roundtrips_and_defaults_none():
    from scripts.lib.models import TrackMeta, DEGRADED_LEVELS
    assert DEGRADED_LEVELS == ("flow", "manual")
    # default: a clean YOLO route carries no degraded level
    assert TrackMeta().degraded is None
    # a flow route round-trips through the sidecar
    tm = TrackMeta(hero=None, degraded="flow")
    assert tm.to_dict()["degraded"] == "flow"
    assert TrackMeta.from_dict(tm.to_dict()) == tm
    # a sidecar written before this slice has no key → reads as clean
    old = {"hero": 3, "ambiguous": False, "intent": "action",
           "features": {}, "pin_matched": None}
    assert TrackMeta.from_dict(old).degraded is None


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
    assert s.model == "yolo11n-seg.pt" and s.intent == "action" and s.pin is None
    with pytest.raises(ValueError, match="model"):
        m.TrackSpec(src="s.mp4", model="bogus.pt")
    with pytest.raises(ValueError, match="intent"):
        m.TrackSpec(src="s.mp4", intent="cinematic")


def test_track_spec_takes_a_pin():
    p = m.HeroPin(kind="rule", rule="largest")
    assert m.TrackSpec(src="s.mp4", pin=p).pin is p
    assert m.TrackSpec(src="s.mp4").pin is None


def test_track_spec_rejects_a_raw_hero_value():
    with pytest.raises(ValueError, match="pin"):
        m.TrackSpec(src="s.mp4", pin=(900, 500, 120, 300))


def test_reframespec_validation():
    ok = dict(composition="lead", grid="thirds", canvas=(9, 16),
              color_means=(105, 122, 137), delivery=m.Delivery("native"))
    m.ReframeSpec(**ok)
    with pytest.raises(ValueError, match="composition"):
        m.ReframeSpec(**{**ok, "composition": "hero"})
    with pytest.raises(ValueError, match="color_means"):
        m.ReframeSpec(**{**ok, "color_means": (105, 0, 137)})     # #G positivity
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


def test_checkspec_hue_drift_max():
    from scripts.lib.models import CheckSpec
    assert CheckSpec(composition="center", grid="thirds", target_dur=3.0).hue_drift_max == 25.0
    with pytest.raises(ValueError, match="positive number of degrees"):
        CheckSpec(composition="center", grid="thirds", target_dur=3.0, hue_drift_max=-1)
    with pytest.raises(ValueError, match="positive number of degrees"):
        CheckSpec(composition="center", grid="thirds", target_dur=3.0, hue_drift_max=True)  # bool-reject


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
    # the fit case: 1280 wide, 16/9 tall. Evening the width first and
    # deriving the height from it would give 718, not 720 — hence floats.
    assert d.dims(1280.0, 1280.0 * 16 / 9) == (1280, 2276)


def test_layout_spec_fill_defaults():
    s = m.LayoutSpec(mode="fill")
    assert (s.mode, s.crop_aspect, s.crop_scale, s.rect) == ("fill", "canvas", 1.0, None)


def test_layout_spec_fit_and_insert_construct():
    assert m.LayoutSpec(mode="fit", crop_aspect="source").rect is None
    s = m.LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.05, 0.25, 0.90))
    assert s.rect == (0.05, 0.25, 0.90)


def test_layout_modes_are_geometry_names_only():
    # The mode names a GEOMETRY; the filler is `background`. `fit-blur` is a
    # preset spelling in prose (design §7), never a value this tuple holds —
    # pinned so a re-introduction fails here instead of quietly working.
    assert m.LAYOUT_MODES == ("fill", "fit", "insert")
    assert manifest.LAYOUTS_SUPPORTED == ("fill", "fit", "insert")


def test_layout_spec_rejects_unknown_mode():
    with pytest.raises(ValueError, match="fill/fit/insert"):
        m.LayoutSpec(mode="split")


def test_layoutspec_no_longer_claims_pan_is_a_pending_layout():
    # pan is a motion source, not a mode — its preset row is fill's row exactly
    # (design 2026-07-19 §1). A message promising a future `pan` mode would send
    # an author looking for a layout that will never exist.
    with pytest.raises(ValueError) as e:
        LayoutSpec(mode="pan")
    msg = str(e.value)
    assert "fill/fit/insert" in msg
    assert "pan" not in msg.replace("LayoutSpec.mode 'pan'", "")


def test_layout_spec_rejects_bad_scale():
    with pytest.raises(ValueError, match=r"\(0.0, 1.0\]"):
        m.LayoutSpec(mode="fit", crop_aspect="source", crop_scale=0.0)


def test_layout_spec_rejects_bad_aspect():
    with pytest.raises(ValueError, match="canvas.*source.*pair"):
        m.LayoutSpec(mode="fit", crop_aspect="wide")


def test_layout_spec_fill_must_be_canvas_aspect_and_full_rect():
    with pytest.raises(ValueError, match="an insert, and must say so"):
        m.LayoutSpec(mode="fill", rect=(0.1, 0.1, 0.5))
    with pytest.raises(ValueError, match="crop_aspect 'canvas'"):
        m.LayoutSpec(mode="fill", crop_aspect="source")


def test_layout_spec_fit_takes_no_rect():
    with pytest.raises(ValueError, match="fit spans the full canvas width"):
        m.LayoutSpec(mode="fit", crop_aspect="source", rect=(0.0, 0.1, 0.8))


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


def test_layout_spec_accepts_a_solid_filler():
    spec = m.LayoutSpec(mode="fit", crop_aspect="source", background="solid")
    assert (spec.mode, spec.crop_aspect, spec.crop_scale, spec.rect, spec.background,
            spec.background_color, spec.border_px, spec.border_color) == (
        "fit", "source", 1.0, None, "solid", "black", 0, "white")


def test_layout_spec_takes_an_explicit_background_colour():
    spec = m.LayoutSpec(mode="fit", crop_aspect="source",
                        background="solid", background_color="#101820")
    assert spec.background_color == "#101820"


def test_fill_refuses_a_filler_it_cannot_show():
    # fill covers the canvas edge to edge — a filler would be an inert setting
    # that reads as if it did something. Mirrors fill's existing border refusal.
    with pytest.raises(ValueError, match="no background to fill"):
        m.LayoutSpec(mode="fill", background="solid")


def test_layout_spec_refuses_an_unknown_background():
    # Pin the ENUMERATION, not just the word "unknown": this message is the only
    # thing that tells an author what IS supported, and a bare-word matcher
    # survives near-total erasure of it. `solid` was this test's unknown value
    # until it landed (design 2026-07-18-fit-solid §3), so it names one that stays
    # unknown rather than reusing a now-valid one.
    with pytest.raises(ValueError, match=r"background 'gradient' unknown") as excinfo:
        m.LayoutSpec(mode="fit", crop_aspect="source", background="gradient")
    assert "'blur', 'solid'" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["", None, 7])
def test_background_colour_must_be_a_non_empty_string(bad):
    with pytest.raises(ValueError, match="non-empty ffmpeg colour"):
        m.LayoutSpec(mode="fit", crop_aspect="source", background_color=bad)


@pytest.mark.parametrize("ch", [",", ":", ";", "'", "[", "]", "\\"])
def test_background_colour_refuses_filtergraph_breaking_characters(ch):
    # Same guard border_color gets: this string reaches an ffmpeg filter argument.
    with pytest.raises(ValueError, match="break the ffmpeg filtergraph"):
        m.LayoutSpec(mode="fit", crop_aspect="source",
                     background_color=f"bla{ch}ck")


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


def test_path_meta_round_trips_the_filler():
    pm = m.PathMeta(mode="fit", crop_w=1280, crop_h=720, crop_y=0,
                    src_dims=(1280, 720), canvas=(9, 16), out_dims=(1280, 2276),
                    rect_px=(0, 778, 1280, 720), freedom=0, background="solid")
    assert m.PathMeta.from_dict(pm.to_dict()) == pm


def test_path_meta_reads_a_pre_filler_sidecar_as_blur():
    # Before this slice `blur` was the ONLY value the field could hold, so the
    # substitution is provably the truth for every sidecar written until now —
    # a fact, not a guessed default.
    d = m.PathMeta(mode="fit", crop_w=1280, crop_h=720, crop_y=0,
                   src_dims=(1280, 720), canvas=(9, 16), out_dims=(1280, 2276),
                   rect_px=(0, 778, 1280, 720), freedom=0, background="solid").to_dict()
    del d["background"]
    assert m.PathMeta.from_dict(d).background == "blur"


def test_path_meta_still_raises_on_any_other_missing_field():
    # The exemption is ONE key, not a loosening of the integrity check.
    d = m.PathMeta(mode="fit", crop_w=1280, crop_h=720, crop_y=0,
                   src_dims=(1280, 720), canvas=(9, 16), out_dims=(1280, 2276),
                   rect_px=(0, 778, 1280, 720), freedom=0, background="blur").to_dict()
    del d["freedom"]
    # pin WHICH field the message names: a bare "no field" survives the message
    # being erased down to those two words, and would pass just as well if the
    # integrity check blamed the wrong key.
    with pytest.raises(RuntimeError, match=r"no field 'freedom'"):
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


def test_export_profile_color_range():
    from scripts.lib.models import ExportProfile
    args = ExportProfile().args()
    assert "-color_range" in args and "tv" in args
    assert "pc" in ExportProfile(color_range="pc").args()
    with pytest.raises(ValueError, match="tv"):
        ExportProfile(color_range="full")


def test_reel_check_spec_defaults():
    s = m.ReelCheckSpec(target_dur=6.0)
    assert s.variety_min == 8 and s.color_delta_max == 12.0


@pytest.mark.parametrize("kw, msg", [
    (dict(target_dur=0), "target_dur"),
    (dict(target_dur=6.0, variety_min=-1), "variety_min"),
    (dict(target_dur=6.0, variety_min=True), "variety_min"),
    (dict(target_dur=6.0, color_delta_max=0), "color_delta_max"),
])
def test_reel_check_spec_rejects_bad(kw, msg):
    with pytest.raises(ValueError, match=msg):
        m.ReelCheckSpec(**kw)


def test_reelcheckspec_audio_thresholds_default_and_validate():
    s = m.ReelCheckSpec(target_dur=30.0)
    assert (s.beat_tol, s.loudness_target, s.loudness_tol) == (0.05, -14.0, 1.0)
    with pytest.raises(ValueError, match="beat_tol"):
        m.ReelCheckSpec(target_dur=30.0, beat_tol=0)
    with pytest.raises(ValueError, match="loudness_tol"):
        m.ReelCheckSpec(target_dur=30.0, loudness_tol=-1)
    with pytest.raises(ValueError, match="loudness_target"):
        m.ReelCheckSpec(target_dur=30.0, loudness_target="bad")


def _rr():
    return m.ReelReport(
        checks={"black": m.CheckResult("black", True, {"black_start": []}),
                "length": m.CheckResult("length", False, {"dur": 7.0, "target": 6.0}),
                "beat": m.CheckResult("beat", None, {"status": "not-implemented"})},
        fail_reasons=[m.ReelFailure("length", "pacing", None, {"dur": 7.0})],
        episode_count=2, wall_s=1.5)


def test_reel_report_overall_false_on_a_failed_check():
    assert _rr().overall is False


def test_reel_report_none_check_never_fails():
    rr = m.ReelReport(checks={"beat": m.CheckResult("beat", None, {"status": "x"})})
    assert rr.overall is True


def test_reel_report_round_trips():
    rr = _rr()
    back = m.ReelReport.from_dict(rr.to_dict())
    assert back.to_dict() == rr.to_dict()
    assert back.episode_count == 2 and back.wall_s == 1.5
    assert back.fail_reasons[0].check == "length" and back.fail_reasons[0].escalate_to == "pacing"


def test_reel_report_writes_json(tmp_path):
    p = tmp_path / "reel.json"
    _rr().write(p)
    assert m.ReelReport.from_dict(json.loads(p.read_text())).overall is False


def test_reelreport_overall_excludes_advisory_beat():
    checks = {"black": m.CheckResult("black", True, {}),
              "beat": m.CheckResult("beat", False, {"worst_dev": 0.3})}
    assert m.ReelReport(checks=checks).overall is True          # advisory beat=False does NOT block delivery


def test_reelreport_overall_blocks_on_loudness_false():
    assert m.ReelReport(checks={"loudness": m.CheckResult("loudness", False, {"measured": -9.0})}).overall is False


def test_reframe_spec_accepts_color_correct():
    s = m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      color_correct=(1.1, 1.0, 0.9))
    assert s.color_correct == (1.1, 1.0, 0.9)


def test_reframe_spec_color_correct_defaults_none():
    s = m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"))
    assert s.color_correct is None


def test_reframe_spec_rejects_nonpositive_color_correct():
    with pytest.raises(ValueError, match="color_correct"):
        m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      color_correct=(0.0, 1.0, 1.0))


def test_reframe_spec_rejects_wrong_length_color_correct():
    with pytest.raises(ValueError, match="color_correct"):
        m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      color_correct=(1.1, 1.0))


def _reel_dict(**over):
    d = dict(episodes=[{"manifest": {"segment": "s0.mp4"}, "clip": "c0.mp4", "route": "r0.json"},
                       {"manifest": {"segment": "s1.mp4"}, "clip": "c1.mp4", "route": "r1.json"}],
             target_dur=6.0, variety_min=4, color_delta_max=10.0, cap=3, changelog="cut")
    d.update(over)
    return d


def test_reel_manifest_from_dict_round_trip():
    rm = m.ReelManifest.from_dict(_reel_dict())
    assert len(rm.episodes) == 2
    assert rm.episodes[0].clip == "c0.mp4" and rm.episodes[0].route == "r0.json"
    assert rm.episodes[1].manifest == {"segment": "s1.mp4"}
    cs = rm.check_spec
    assert isinstance(cs, m.ReelCheckSpec)
    assert cs.target_dur == 6.0 and cs.variety_min == 4 and cs.color_delta_max == 10.0


def test_reel_manifest_defaults():
    rm = m.ReelManifest.from_dict(dict(
        episodes=[{"manifest": {}, "clip": "c.mp4", "route": "r.json"}], target_dur=3.0))
    assert rm.cap == 3 and rm.changelog == ""
    assert rm.check_spec.variety_min == 8 and rm.check_spec.color_delta_max == 12.0


def test_reel_manifest_rejects_empty_episodes():
    with pytest.raises(ValueError, match="episodes is empty"):
        m.ReelManifest.from_dict(_reel_dict(episodes=[]))


def test_reel_manifest_rejects_missing_clip():
    with pytest.raises(ValueError, match=r"episodes\[0\].clip"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": {}, "clip": "", "route": "r.json"}]))


def test_reel_manifest_rejects_missing_route():
    with pytest.raises(ValueError, match=r"episodes\[0\].route"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": {}, "clip": "c.mp4", "route": ""}]))


def test_reel_manifest_accepts_a_none_route_for_a_generated_pan_path():
    # a pan writes NO route.json — process_episode skips tracking, and an empty
    # route.json would already mean "the tracker ran and found nobody". The
    # contract has to be able to say the observation never existed.
    rm = m.ReelManifest(
        episodes=[m.ReelEpisode(manifest={}, clip="c.mp4", route=None,
                                path="p.json", meta="pm.json")],
        target_dur=6.0)
    assert rm.episodes[0].route is None
    # the sidecars are REAL under a pan — only the route is absent
    assert rm.episodes[0].path == "p.json" and rm.episodes[0].meta == "pm.json"


def test_reel_manifest_still_accepts_a_string_route():
    rm = m.ReelManifest(
        episodes=[m.ReelEpisode(manifest={}, clip="c.mp4", route="r.json")],
        target_dur=6.0)
    assert rm.episodes[0].route == "r.json"


def test_reel_manifest_rejects_an_empty_string_route_even_though_none_is_legal():
    # "" is NOT the pan spelling: it is a caller who meant to pass a path and lost
    # it. None states the absence deliberately; "" states nothing.
    with pytest.raises(ValueError, match="a generated pan path, which has no route"):
        m.ReelManifest(episodes=[m.ReelEpisode(manifest={}, clip="c.mp4", route="")],
                       target_dur=6.0)


def test_reel_manifest_rejects_a_non_string_route():
    with pytest.raises(ValueError, match="must be a route.json path or None"):
        m.ReelManifest(episodes=[m.ReelEpisode(manifest={}, clip="c.mp4", route=123)],
                       target_dur=6.0)


def test_reel_manifest_from_dict_carries_an_explicit_null_route_through():
    # the wire spelling of "there was never a route here" is an explicit null. It
    # has to survive from_dict, or a pan reel cannot be hand-authored at all.
    rm = m.ReelManifest.from_dict(_reel_dict(
        episodes=[{"manifest": {}, "clip": "c.mp4", "route": None,
                   "path": "p.json", "meta": "pm.json"}]))
    assert rm.episodes[0].route is None


def test_reel_manifest_from_dict_still_rejects_an_omitted_route_key():
    # an OMITTED key is not the pan spelling either — from_dict maps it to "", the
    # same "lost it" value a caller passes directly. A pan must say `null` out loud,
    # for the same reason the all-pan reel check says "not-checked" instead of
    # silently passing: the absence is stated, never inferred from a gap.
    with pytest.raises(ValueError, match="a generated pan path, which has no route"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": {}, "clip": "c.mp4"}]))


def test_reel_manifest_rejects_bad_cap():
    with pytest.raises(ValueError, match="cap"):
        m.ReelManifest.from_dict(_reel_dict(cap=0))


def test_reel_manifest_rejects_bad_variety_min():
    with pytest.raises(ValueError, match="variety_min"):
        m.ReelManifest.from_dict(_reel_dict(variety_min=-1))


def test_reel_manifest_rejects_bad_color_delta_max():
    with pytest.raises(ValueError, match="color_delta_max"):
        m.ReelManifest.from_dict(_reel_dict(color_delta_max=-5.0))


def test_reel_manifest_rejects_null_manifest():
    with pytest.raises(ValueError, match="manifest"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": None, "clip": "c.mp4", "route": "r.json"}]))


def test_reel_manifest_rejects_non_dict_manifest_direct():
    with pytest.raises(ValueError, match=r"episodes\[0\].manifest"):
        m.ReelManifest(episodes=[m.ReelEpisode(manifest=None, clip="c.mp4", route="r.json")],
                       target_dur=6.0)


def test_reel_manifest_rejects_missing_clip_key():
    with pytest.raises(ValueError, match=r"episodes\[0\].clip"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": {}, "route": "r.json"}]))


def test_reel_manifest_from_dict_rejects_missing_episodes_key():
    with pytest.raises(ValueError, match="episodes"):
        m.ReelManifest.from_dict({"target_dur": 3.0})


def test_reel_manifest_from_dict_rejects_non_dict_episode_entry():
    with pytest.raises(ValueError, match=r"episodes\[0\]"):
        m.ReelManifest.from_dict({"episodes": ["ep0.json"], "target_dur": 3.0})


def _music(**kw):
    d = dict(track="t.m4a", start_offset=0.0, duration=10.0, tempo=120.0,
             beats=(0.0, 0.5, 1.0), energy=(0.1, 0.2), energy_hz=2.0)
    d.update(kw)
    return d


def test_musicspec_roundtrips():
    spec = m.MusicSpec.from_dict(_music())
    assert m.MusicSpec.from_dict(spec.to_dict()) == spec
    assert spec.beats == (0.0, 0.5, 1.0) and spec.duration == 10.0


@pytest.mark.parametrize("kw, msg", [
    (dict(track=""), "non-empty path"),
    (dict(start_offset=-1), ">= 0"),
    (dict(duration=0), "positive number"),
    (dict(tempo=0), "positive BPM"),
    (dict(beats=()), "beats is empty"),
    (dict(beats=(1.0, 0.5)), "ascending"),
    (dict(beats=(0.0, 99.0)), r"outside \[0, 10.0\]"),
    (dict(beats=None), "beats must be a list"),
    (dict(beats=(0.0, "x")), "numeric beat times"),
    (dict(energy=()), "energy is empty"),
    (dict(energy=None), "energy must be a list"),
    (dict(energy_hz=0), "positive sample rate"),
])
def test_musicspec_rejects_with_remedy(kw, msg):
    with pytest.raises(ValueError, match=msg):
        m.MusicSpec.from_dict(_music(**kw))


def test_reelmanifest_accepts_music_path_and_defaults_none():
    ep = dict(manifest={"a": 1}, clip="c.mp4", route="r.json")
    assert m.ReelManifest.from_dict(dict(episodes=[ep], target_dur=10.0)).music is None
    rm = m.ReelManifest.from_dict(dict(episodes=[ep], target_dur=10.0, music="MUSIC.json"))
    assert rm.music == "MUSIC.json"
    with pytest.raises(ValueError, match="music must be"):
        m.ReelManifest.from_dict(dict(episodes=[ep], target_dur=10.0, music=""))


def test_reel_manifest_ambient_defaults_true():
    assert m.ReelManifest.from_dict(_reel_dict()).ambient is True


def test_reel_manifest_ambient_false_from_dict():
    assert m.ReelManifest.from_dict(_reel_dict(ambient=False)).ambient is False


def test_reel_manifest_rejects_non_bool_ambient():
    with pytest.raises(ValueError, match="ambient"):
        m.ReelManifest.from_dict(_reel_dict(ambient="yes"))


def test_reel_manifest_sfx_defaults_false():
    assert m.ReelManifest.from_dict(_reel_dict()).sfx is False


def test_reel_manifest_sfx_true_from_dict():
    assert m.ReelManifest.from_dict(_reel_dict(sfx=True)).sfx is True


def test_reel_manifest_rejects_non_bool_sfx():
    with pytest.raises(ValueError, match="sfx"):
        m.ReelManifest.from_dict(_reel_dict(sfx="yes"))


def test_reel_episode_path_meta_round_trip():
    rm = m.ReelManifest.from_dict(_reel_dict(episodes=[
        {"manifest": {}, "clip": "c.mp4", "route": "r.json", "path": "p.json", "meta": "pm.json"}]))
    assert rm.episodes[0].path == "p.json" and rm.episodes[0].meta == "pm.json"


def test_reel_episode_path_meta_default_empty():
    rm = m.ReelManifest.from_dict(_reel_dict())
    assert rm.episodes[0].path == "" and rm.episodes[0].meta == ""    # backward compatible


def test_reel_manifest_rejects_a_lone_sidecar():
    with pytest.raises(ValueError, match="path and meta must both"):
        m.ReelManifest.from_dict(_reel_dict(episodes=[
            {"manifest": {}, "clip": "c.mp4", "route": "r.json", "path": "p.json"}]))   # meta missing


def test_reel_manifest_platform_default_and_set():
    assert m.ReelManifest.from_dict(_reel_dict()).platform == ""
    assert m.ReelManifest.from_dict(_reel_dict(platform="tiktok")).platform == "tiktok"


def test_reelreport_overall_excludes_advisory_safe_zones():
    rr = m.ReelReport(checks={"safe_zones": m.CheckResult("safe_zones", False, {"advisory": True})})
    assert rr.overall is True          # advisory False never blocks the reel


def test_hero_pin_bbox():
    p = m.HeroPin(kind="bbox", bbox=(900.0, 500.0, 120.0, 300.0))
    assert p.kind == "bbox" and p.bbox == (900.0, 500.0, 120.0, 300.0)


def test_hero_pin_rule_rejects_unknown_rule():
    assert m.HeroPin(kind="rule", rule="largest").rule == "largest"
    with pytest.raises(ValueError, match="HERO_RULES|largest"):
        m.HeroPin(kind="rule", rule="tallest")


def test_hero_pin_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        m.HeroPin(kind="vibes")


def test_hero_pin_bbox_must_be_a_4_tuple():
    for bad in (None, (1, 2, 3), [1, 2, 3, 4], (1, 2, 3, 4, 5)):
        with pytest.raises(ValueError, match="bbox"):
            m.HeroPin(kind="bbox", bbox=bad)


def test_hero_pin_track_id_rejects_bool_and_none():
    assert m.HeroPin(kind="track", track_id=0).track_id == 0   # 0 is a real track id
    for bad in (None, True, 1.5, "3"):
        with pytest.raises(ValueError, match="track_id"):
            m.HeroPin(kind="track", track_id=bad)


def test_hero_pin_cast_needs_a_name_and_a_descriptor():
    p = m.HeroPin(kind="cast", name="Lena", descriptor=(0.5, 0.5))
    assert p.name == "Lena" and p.descriptor == (0.5, 0.5)
    with pytest.raises(ValueError, match="name"):
        m.HeroPin(kind="cast", name="", descriptor=(0.5, 0.5))
    with pytest.raises(ValueError, match="descriptor"):
        m.HeroPin(kind="cast", name="Lena", descriptor=())


def test_hero_pin_cast_descriptor_must_be_numeric():
    # the message promises "a non-empty tuple OF NUMBERS" — enforce what it says.
    # A str element otherwise reaches appearance.descriptor_dist and dies there on
    # a bare `TypeError: unsupported operand type(s) for -: 'str' and 'float'` —
    # no remedy, deep in the tracking pipeline. bool is the standing landmine:
    # isinstance(True, int) is True, so it needs its own exclusion, as bbox's does.
    for bad in (("a", "b", "c"), (0.5, "x"), (True, False), (0.5, True), (None,), [0.5, 0.5]):
        with pytest.raises(ValueError, match="descriptor"):
            m.HeroPin(kind="cast", name="Lena", descriptor=bad)


def test_hero_pin_is_frozen():
    p = m.HeroPin(kind="rule", rule="leftmost")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.rule = "largest"


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_musicspec_from_dict_rejects_a_non_object_top_level(d, name):
    # A MUSIC.json whose top level is not an object reached d.get("track") and raised a bare
    # AttributeError. All four readers (build_reel.py:34, mix.py:226, draft.py:69,
    # pacing.py:26) call MusicSpec.from_json with no except.
    with pytest.raises(ValueError) as ei:
        m.MusicSpec.from_dict(d)
    msg = str(ei.value)
    assert "expected a MUSIC.json object" in msg
    assert f"got {name}" in msg
    assert "re-run beats" in msg
    assert "has no attribute" not in msg


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_musicspec_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "MUSIC.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run beats"):
        m.MusicSpec.from_json(p)


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_reelmanifest_from_dict_rejects_a_non_object_top_level(d, name):
    # build_reel.py:91 reads the reel manifest with no except around from_json.
    with pytest.raises(ValueError) as ei:
        m.ReelManifest.from_dict(d)
    msg = str(ei.value)
    assert "expected a reel-manifest object" in msg
    assert f"got {name}" in msg
    assert "process_episode" in msg
    assert "has no attribute" not in msg


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_reelmanifest_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "REEL_MANIFEST.json"; p.write_text(body)
    with pytest.raises(ValueError, match="process_episode"):
        m.ReelManifest.from_json(p)


@pytest.mark.parametrize("d,name", [([], "list"), ("str", "str"), (42, "int"), (None, "NoneType")])
def test_trackmeta_from_dict_rejects_a_non_object_top_level(d, name):
    # TrackMeta has no from_json and no production reader today (track.py:165 constructs it
    # directly), but from_dict is public contract surface and owes the same one type — a guard
    # that only holds while nobody calls it is not a guard.
    with pytest.raises(ValueError) as ei:
        m.TrackMeta.from_dict(d)
    msg = str(ei.value)
    assert "expected a track-meta object" in msg
    assert f"got {name}" in msg
    assert "re-run track" in msg
    assert "has no attribute" not in msg


# --- the TypeError/RuntimeError leakers (subscript / try-wrap, not `.get`): the a75fe8e
# sweep killed the AttributeError variant (`.get` on a non-dict); these classes reach their
# own top level via d["key"] or a try that wraps the resulting TypeError, so a non-dict raised
# a bare TypeError (or, for PathMeta, a RuntimeError laundering one) instead of the same
# ValueError-with-remedy. Same first-statement isinstance guard, same three-part message.

@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_routepoint_from_dict_rejects_a_non_object_top_level(d, name):
    # d["t"] raised a bare TypeError ('int' object is not subscriptable) on a non-dict.
    # route_from_json feeds each element here — a route.json of bare scalars is valid JSON, and
    # route.json is also the §5.10 answer channel a human can supply — so it reached the four
    # bare readers (check_episode/check_reel/process_episode/reframe) as a driver crash.
    with pytest.raises(ValueError) as ei:
        m.RoutePoint.from_dict(d)
    msg = str(ei.value)
    assert "expected a route-point object" in msg
    assert f"got {name}" in msg
    assert "re-run track" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


def test_route_from_json_rejects_bare_scalar_elements_with_a_remedy(tmp_path):
    # the real reader: route.json = [1, 2] is valid JSON; before the guard RoutePoint.from_dict(1)
    # raised a bare TypeError out of route_from_json's list comprehension.
    p = tmp_path / "route.json"; p.write_text("[1, 2]")
    with pytest.raises(ValueError, match="re-run track"):
        m.route_from_json(p)


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_report_from_dict_rejects_a_non_object_top_level(d, name):
    # d["checks"] raised a bare TypeError on a non-dict. No production reader (check_episode
    # writes report.json via to_dict; nobody reads it back through from_dict), but from_dict is
    # public contract surface and owes ValueError-with-remedy.
    with pytest.raises(ValueError) as ei:
        m.Report.from_dict(d)
    msg = str(ei.value)
    assert "expected a report object" in msg
    assert f"got {name}" in msg
    assert "re-run check_episode" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_reelfailure_from_dict_rejects_a_non_object_top_level(d, name):
    # d["check"] raised a bare TypeError on a non-dict. Read via ReelReport.from_dict (which now
    # guards its own top level); from_dict is public contract surface.
    with pytest.raises(ValueError) as ei:
        m.ReelFailure.from_dict(d)
    msg = str(ei.value)
    assert "expected a reel-failure object" in msg
    assert f"got {name}" in msg
    assert "re-run check_reel" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_reelreport_from_dict_rejects_a_non_object_top_level(d, name):
    # d["checks"] raised a bare TypeError on a non-dict. deliver.py:94 reads
    # ReelReport.from_dict(json.loads(...)) with no except, so it crashed deliver on a
    # wrong-shaped --report file.
    with pytest.raises(ValueError) as ei:
        m.ReelReport.from_dict(d)
    msg = str(ei.value)
    assert "expected a reel-report object" in msg
    assert f"got {name}" in msg
    assert "re-run check_reel" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_pathmeta_from_dict_rejects_a_non_object_top_level(d, name):
    # A non-dict `d` is wrong-TYPE construction → ValueError-with-remedy (coding-standards §37):
    # the from_dict CONTRACT boundary. This is DISTINCT from a dict with a missing/bad field,
    # which stays RuntimeError below (a machine-sidecar INTEGRITY failure — see the two tests
    # above that pass dicts). Before the guard the non-dict fell into the integrity arm and
    # laundered a bare "list indices must be integers" into the message.
    with pytest.raises(ValueError) as ei:
        m.PathMeta.from_dict(d)
    msg = str(ei.value)
    assert "expected a path.meta.json object" in msg
    assert f"got {name}" in msg
    assert "re-run reframe" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable",
                "indices must be", "unusable field"):
        assert bad not in msg


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_pathmeta_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    # from_json parses then delegates: a valid-JSON non-object top level now surfaces the
    # from_dict guard's ValueError, not the integrity arm's RuntimeError. The integrity/
    # corrupt-JSON RuntimeError tests above still hold (they feed a dict / unparseable bytes).
    p = tmp_path / "path.meta.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run reframe"):
        m.PathMeta.from_json(p)


def test_reelcheckspec_editorial_thresholds_default():
    s = m.ReelCheckSpec(target_dur=6.0)
    assert s.clip_tol == 0.02 and s.bar_symmetry_tol == 0.02 and s.layout_jump_max == 0.6


@pytest.mark.parametrize("kw,msg", [
    (dict(clip_tol=0.5), "clip_tol"),            # >= 0.5
    (dict(clip_tol=-0.01), "clip_tol"),          # < 0
    (dict(bar_symmetry_tol=True), "bar_symmetry_tol"),   # bool is not a fraction
    (dict(layout_jump_max=0), "layout_jump_max"),        # must be positive
])
def test_reelcheckspec_editorial_thresholds_fail_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        m.ReelCheckSpec(target_dur=6.0, **kw)


def test_reelreport_overall_excludes_the_three_editorial_advisories():
    checks = {"black": m.CheckResult("black", True, {}),
              "key_action": m.CheckResult("key_action", False, {"advisory": True}),
              "pad_bars": m.CheckResult("pad_bars", False, {"advisory": True}),
              "transitions": m.CheckResult("transitions", False, {"advisory": True})}
    assert m.ReelReport(checks=checks).overall is True     # advisory Falses never block


def test_reel_check_spec_length_retime_max_defaults_to_one_second():
    # the band build_reel may absorb as a SHORTFALL, on top of the gate's own 0.5s (design §3.1)
    assert ReelCheckSpec(target_dur=12.0).length_retime_max == 1.0


def test_reel_check_spec_length_retime_max_rejects_non_positive():
    for bad in (0, -1.0):
        with pytest.raises(ValueError, match="length_retime_max"):
            ReelCheckSpec(target_dur=12.0, length_retime_max=bad)


def test_reel_check_spec_length_retime_max_rejects_non_number():
    with pytest.raises(ValueError, match="length_retime_max"):
        ReelCheckSpec(target_dur=12.0, length_retime_max="1.0")


# --- PanSpec (design 2026-07-19): two fractions of horizontal freedom, not a layout ---

def test_panspec_holds_two_fractions_of_freedom():
    p = PanSpec(start=0.2, end=0.7)
    assert (p.start, p.end) == (0.2, 0.7)


def test_panspec_direction_is_the_sign_of_the_travel():
    # right-to-left is spelled by the numbers, not by a direction vocabulary
    assert PanSpec(start=1.0, end=0.0).end < PanSpec(start=1.0, end=0.0).start


@pytest.mark.parametrize("start,end", [(-0.1, 1.0), (0.0, 1.5), (1.2, 0.3)])
def test_panspec_refuses_a_fraction_outside_the_unit_interval(start, end):
    with pytest.raises(ValueError) as e:
        PanSpec(start=start, end=end)
    msg = str(e.value)
    # pin the offending value AND the interval — not one word of the message
    assert "PanSpec" in msg and "[0.0, 1.0]" in msg
    assert repr(start) in msg or repr(end) in msg


@pytest.mark.parametrize("bad", [10**400, -(10**400)])
def test_panspec_refuses_an_int_too_large_for_a_float(bad):
    # json.loads builds ints of any size, and float() raises OverflowError — NOT
    # ValueError — on one past float range. The manifest gate catches only
    # ValueError, so an OverflowError here would escape it as a crash. The range
    # comparison is therefore done without float().
    with pytest.raises(ValueError) as e:
        PanSpec(start=bad, end=0.5)
    assert "[0.0, 1.0]" in str(e.value)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_panspec_refuses_a_non_finite_fraction(bad):
    # json.loads accepts bare NaN/Infinity. NaN fails every comparison, so the
    # `not 0.0 <= v <= 1.0` form rejects it for free — pin that it does.
    with pytest.raises(ValueError) as e:
        PanSpec(start=bad, end=0.5)
    assert "[0.0, 1.0]" in str(e.value)


def test_panspec_refuses_a_pan_that_does_not_move():
    with pytest.raises(ValueError) as e:
        PanSpec(start=0.4, end=0.4)
    msg = str(e.value)
    assert "0.4" in msg
    # the remedy must say to DROP the field, not to write a different degenerate one
    assert "drop" in msg.lower() or "omit" in msg.lower()


@pytest.mark.parametrize("bad", [True, False])
def test_panspec_refuses_a_bool_masquerading_as_a_fraction(bad):
    # isinstance(True, int) is True in Python — {"from": true} must not mean 1.0
    with pytest.raises(ValueError) as e:
        PanSpec(start=bad, end=0.5)
    msg = str(e.value)
    assert "PanSpec.start" in msg and "[0.0, 1.0]" in msg and repr(bad) in msg


@pytest.mark.parametrize("bad", ["0.5", None, [0.5]])
def test_panspec_refuses_a_non_number(bad):
    with pytest.raises(ValueError) as e:
        PanSpec(start=bad, end=0.5)
    msg = str(e.value)
    assert "PanSpec.start" in msg and "[0.0, 1.0]" in msg and repr(bad) in msg


def test_panspec_round_trips_through_from_and_to_keys():
    # the WIRE keys are from/to; the FIELD names are start/end (`from` is a Python
    # keyword). This is the only place in the repo where the two differ.
    d = {"from": 0.2, "to": 0.7}
    p = PanSpec.from_dict(d)
    assert (p.start, p.end) == (0.2, 0.7)
    assert p.to_dict() == d


def test_panspec_from_dict_refuses_a_non_object():
    with pytest.raises(ValueError) as e:
        PanSpec.from_dict([0.0, 1.0])
    msg = str(e.value)
    assert "from" in msg and "to" in msg
    # pin the TYPE-guard branch specifically: for a list, "from" not in d and
    # "to" not in d are BOTH true too, so the missing-key branch would raise a
    # message that also contains "from"/"to" — asserting only that would still
    # pass with the type guard deleted entirely.
    assert "expected an object" in msg and "list" in msg


def test_panspec_from_dict_names_a_missing_key():
    with pytest.raises(ValueError) as e:
        PanSpec.from_dict({"from": 0.0})
    assert "to" in str(e.value)


# --- ReframeSpec.pan (design 2026-07-19 §5.1): the crop's second x(t) source ---

def test_reframespec_defaults_to_no_pan():
    spec = m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                         color_means=(105, 122, 137), delivery=m.Delivery("native"))
    assert spec.pan is None


def test_reframespec_carries_a_panspec():
    p = PanSpec(start=0.2, end=0.7)          # off-default values on purpose
    spec = m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                         color_means=(105, 122, 137), delivery=m.Delivery("native"), pan=p)
    assert spec.pan == p


@pytest.mark.parametrize("bad", [{"from": 0.0, "to": 1.0}, (0.0, 1.0), "0->1", 0.5])
def test_reframespec_refuses_a_pan_that_is_not_a_panspec(bad):
    # the dict form is the WIRE shape; the spec takes the constructed type, so a
    # caller that forgot PanSpec.from_dict fails here rather than at render time
    with pytest.raises(ValueError) as e:
        m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                     color_means=(105, 122, 137), delivery=m.Delivery("native"), pan=bad)
    msg = str(e.value)
    assert "ReframeSpec.pan" in msg and "PanSpec" in msg


# --- PathMeta.pan (design 2026-07-19 §2.1): the provenance bit ---

_META_KW = dict(mode="fill", crop_w=405, crop_h=720, crop_y=0, src_dims=(1280, 720),
                canvas=(9, 16), out_dims=(404, 720), rect_px=(0, 0, 404, 720), freedom=875)


def test_pathmeta_defaults_to_a_tracked_path():
    assert m.PathMeta(**_META_KW).pan is False


def test_pathmeta_records_that_the_path_was_generated():
    pm = m.PathMeta(**_META_KW, pan=True)
    assert pm.to_dict()["pan"] is True
    assert m.PathMeta.from_dict(pm.to_dict()).pan is True


def test_pathmeta_reads_an_older_sidecar_as_not_a_pan():
    # the one-key exemption: a sidecar written before this slice has no `pan`
    # key, and its absence honestly means "this path came from a route".
    # Every OTHER key stays a hard integrity check.
    d = m.PathMeta(**_META_KW).to_dict()
    del d["pan"]
    assert m.PathMeta.from_dict(d).pan is False


def test_pathmeta_still_hard_fails_on_a_missing_non_exempt_key():
    d = m.PathMeta(**_META_KW).to_dict()
    del d["crop_w"]
    # pin WHICH field the message names: a bare pytest.raises(RuntimeError) would
    # be satisfied by a regression that raised for the wrong reason or blamed the
    # wrong key — the same bar its sibling above already holds "freedom" to.
    with pytest.raises(RuntimeError, match=r"no field 'crop_w'"):
        m.PathMeta.from_dict(d)


# --- PathMeta.stabilized (design 2026-07-20 §6.2): the other provenance bit ---

def test_path_meta_carries_the_stabilized_provenance_bit():
    pm = m.PathMeta(mode="fill", crop_w=608, crop_h=1080, crop_y=0,
                    src_dims=(1920, 1080), canvas=(1080, 1920), out_dims=(1080, 1920),
                    rect_px=(0, 0, 1080, 1920), freedom=1312, stabilized=True)
    assert pm.to_dict() == {
        "mode": "fill", "crop_w": 608, "crop_h": 1080, "crop_y": 0,
        "src_dims": [1920, 1080], "canvas": [1080, 1920], "out_dims": [1080, 1920],
        "rect_px": [0, 0, 1080, 1920], "freedom": 1312,
        "background": "blur", "pan": False, "stabilized": True}


def test_a_sidecar_written_before_this_slice_reads_as_not_stabilized():
    """Same one-key exemption background and pan already have: a sidecar with no
    `stabilized` key was written when stabilization could not happen at all, so
    False is provably the truth for those files rather than a guessed default."""
    d = {"mode": "fill", "crop_w": 608, "crop_h": 1080, "crop_y": 0,
         "src_dims": [1920, 1080], "canvas": [1080, 1920], "out_dims": [1080, 1920],
         "rect_px": [0, 0, 1080, 1920], "freedom": 1312}
    assert m.PathMeta.from_dict(d).stabilized is False


def test_reframe_spec_has_no_stabilize_field_at_all():
    """Not "refuses True" — GONE. The field existed only to be refused, back when
    stabilization was unimplemented. Keeping a refused field once the feature
    exists invites someone to flip it to True and expect the pre-stage to run
    inside reframe, which is exactly the arrangement design 2026-07-20 §1 rules
    out. A TypeError says so at construction."""
    with pytest.raises(TypeError, match="stabilize"):
        m.ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                      color_means=(105, 122, 137), delivery=m.Delivery(),
                      stabilize=True)


# --- ReframeSpec colour fields (colour-as-a-stage): nine identity-default grade knobs ---

def test_reframespec_colour_defaults_are_identity():
    from scripts.lib.models import ReframeSpec, Delivery
    s = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                    color_means=(100, 100, 100), delivery=Delivery("native"))
    assert (s.white_balance, s.black_point, s.highlight, s.saturation, s.shadow_red,
            s.mid_blue, s.dip) == (0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0)
    assert s.tone_src is None and s.tone_dst is None


@pytest.mark.parametrize("field,bad,msg", [
    ("white_balance", 1.5, r"\[0, 1\]"), ("white_balance", True, r"\[0, 1\]"),
    ("black_point", 0.5, "0.35"), ("black_point", False, "0.35"),
    ("highlight", 0.4, "0.6"), ("highlight", True, "0.6"),
    ("saturation", 2.0, "1.5"), ("saturation", True, "1.5"),
    ("shadow_red", 0.5, "0.20"), ("shadow_red", False, "0.20"),
    ("mid_blue", 1.5, "1.20"), ("mid_blue", True, "1.20"),
    ("dip", 0.9, "0.5"), ("dip", False, "0.5")])
def test_reframespec_colour_ranges(field, bad, msg):
    from scripts.lib.models import ReframeSpec, Delivery
    with pytest.raises(ValueError, match=msg):
        ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                    color_means=(100, 100, 100), delivery=Delivery("native"), **{field: bad})


def test_reframespec_tone_is_an_xor_pair_validated_by_color():
    from scripts.lib.models import ReframeSpec, Delivery
    base = dict(composition="center", grid="thirds", canvas=(1080, 1920),
                color_means=(100, 100, 100), delivery=Delivery("native"))
    with pytest.raises(ValueError, match="come as a pair"):
        ReframeSpec(**base, tone_src=(30, 100, 148))          # dst missing
    with pytest.raises(ValueError, match="increase by at least"):
        ReframeSpec(**base, tone_src=(30, 33, 148), tone_dst=(35, 110, 150))  # gap < 6 → color.tone_arg
    ReframeSpec(**base, tone_src=(30, 100, 148), tone_dst=(35, 110, 150))     # valid, no raise
