import json

import numpy as np
import pytest
from PIL import Image

from scripts.lib import carve, intake_cache
from scripts.lib.intake_cache import CastEntry, ClipResult
from scripts.lib.footage import DESCRIPTOR_LEN, FootageClip, FootageWindow

_M = "yolo11n-seg.pt"          # a stand-in for track.MODEL; the driver supplies the real one
_PROXY = 960                   # the analysis-proxy long side the driver supplies (intake.PROXY_LONG_SIDE)


def _desc(*head):
    return list(head) + [0.0] * (DESCRIPTOR_LEN - len(head))


def _clip(name="a.mp4"):
    w = FootageWindow(start=0.0, dur=2.0, shot_type="medium", people=1,
                      motion=0.4, shake=0.0, score=0.9)
    return FootageClip(source=name, dur=8.0, res=(1920, 1080), fps=30.0,
                       scene_cuts=[4.0], windows=[w])


def _result(name="a.mp4"):
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    entry = CastEntry(source=name, tid=1, conf=0.9, descriptor=_desc(0.5, 0.5), crop_rgb=red)
    return ClipResult(clip=_clip(name), phashes=["8f3c2a1b0d4e5f60"], cast=[entry])


def _src(tmp_path, name="a.mp4", data=b"x"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_store_then_load_round_trips(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    stored = intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    assert loaded is not None
    assert loaded.clip.to_dict() == _clip().to_dict()
    assert loaded.phashes == ["8f3c2a1b0d4e5f60"]
    assert loaded.cast[0].source == "a.mp4" and loaded.cast[0].tid == 1
    assert loaded.cast[0].descriptor == _desc(0.5, 0.5)
    assert stored.cast[0].crop == loaded.cast[0].crop and loaded.cast[0].crop_rgb is None
    assert Image.open(loaded.cast[0].crop).size == (8, 8)


def test_load_is_none_when_absent(tmp_path):
    assert intake_cache.load(str(tmp_path / "out"), str(_src(tmp_path)), 3.0, _M, _PROXY,
                             band=carve.DEFAULT_BAND) is None


def test_load_is_none_on_changed_mtime(tmp_path):
    import os
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    os.utime(src, ns=(0, 0))
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_load_is_none_on_changed_sample_fps(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    assert intake_cache.load(str(out), str(src), 4.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_load_is_none_on_changed_model(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), "m1", _PROXY, band=carve.DEFAULT_BAND)
    assert intake_cache.load(str(out), str(src), 3.0, "m2", _PROXY,
                             band=carve.DEFAULT_BAND) is None


def test_load_is_none_on_bumped_version(tmp_path, monkeypatch):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    monkeypatch.setattr(intake_cache, "CACHE_VERSION", intake_cache.CACHE_VERSION + 1)
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_crops_without_clip_json_is_a_miss(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    (out / ".intake_cache" / "a.mp4" / "clip.json").unlink()
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_corrupt_clip_json_is_a_miss_not_a_crash(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    (out / ".intake_cache" / "a.mp4" / "clip.json").write_text("{ not json")
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_nondict_clip_json_is_a_miss_not_a_crash(tmp_path):
    # valid JSON, wrong shape: payload.get would AttributeError without the guard
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    (out / ".intake_cache" / "a.mp4" / "clip.json").write_text("null")
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_load_is_none_when_source_file_removed(tmp_path):
    # a raw clip moved/deleted between runs → clip_key's os.stat must not crash the
    # scan; a miss routes it back through the worker, where quarantine covers it
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    src.unlink()
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_crop_png_round_trips_red(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    px = np.asarray(Image.open(loaded.cast[0].crop))
    assert px[0, 0, 0] == 255 and px[0, 0, 1] == 0


def test_a_version_1_entry_is_a_miss(tmp_path):
    # a cache written under an old CACHE_VERSION must not be trusted by current code
    from scripts.lib import intake_cache
    src = tmp_path / "a.mp4"; src.write_bytes(b"x")
    out = tmp_path / "out"; out.mkdir()
    d = out / ".intake_cache" / "a.mp4"; d.mkdir(parents=True)
    key = intake_cache.clip_key(str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    stale = {**key, "version": 1}
    (d / "clip.json").write_text(json.dumps(
        {"key": stale, "clip": {"source": "a.mp4", "dur": 1.0, "res": [2, 2], "fps": 1.0,
                                "shaky": False, "scene_cuts": [], "windows": []},
         "phashes": [], "cast": []}))
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND) is None


def test_clip_key_includes_proxy_long_side_and_v9(tmp_path):
    from scripts.lib import intake_cache
    f = tmp_path / "c.mp4"; f.write_bytes(b"x")
    k = intake_cache.clip_key(str(f), sample_fps=3.0, model="m", proxy_long_side=960,
                              band=carve.DEFAULT_BAND)
    assert k["version"] == 9
    assert k["proxy_long_side"] == 960
    k2 = intake_cache.clip_key(str(f), sample_fps=3.0, model="m", proxy_long_side=1280,
                               band=carve.DEFAULT_BAND)
    assert k != k2                              # a scale change invalidates


def test_cast_entry_presence_round_trips(tmp_path):
    from scripts.lib import intake_cache as ic
    clip = _clip()                                    # existing helper in this file
    entry = ic.CastEntry(source="a.mp4", tid=1, conf=0.9,
                         descriptor=_desc((1.0,)), presence=2.5,
                         crop_rgb=np.zeros((4, 4, 3), "uint8"))
    out, src = tmp_path / "out", _src(tmp_path)        # a real backing file: clip_key stats it
    stored = ic.store(str(out), str(src), 3.0,
                      ic.ClipResult(clip=clip, phashes=[], cast=[entry]),
                      model="m", proxy_long_side=960, reid_model="osnet_x1_0",
                      band=carve.DEFAULT_BAND)
    assert stored.cast[0].presence == 2.5
    loaded = ic.load(str(out), str(src), 3.0, model="m",
                     proxy_long_side=960, reid_model="osnet_x1_0",
                     band=carve.DEFAULT_BAND)
    assert loaded.cast[0].presence == 2.5


def test_reid_model_is_part_of_the_key(tmp_path):
    from scripts.lib import intake_cache as ic
    clip = _clip()
    out, src = tmp_path / "out", _src(tmp_path)        # a real backing file: clip_key stats it
    ic.store(str(out), str(src), 3.0, ic.ClipResult(clip=clip, phashes=[], cast=[]),
             model="m", proxy_long_side=960, reid_model="",           # cached reid-absent
             band=carve.DEFAULT_BAND)
    # a later run WITH reid must MISS, not serve the stale empty-cast entry
    assert ic.load(str(out), str(src), 3.0, model="m",
                   proxy_long_side=960, reid_model="osnet_x1_0",
                   band=carve.DEFAULT_BAND) is None


def test_load_is_none_on_changed_band(tmp_path):
    # test_a_different_band_is_a_different_key proves clip_key() differs IN MEMORY only;
    # this exercises load()'s actual `payload.get("key") != clip_key(...)` comparison
    # against a JSON-round-tripped disk entry — the layer that must reject a stale band.
    from scripts.lib import intake_cache as ic
    clip = _clip()
    out, src = tmp_path / "out", _src(tmp_path)        # a real backing file: clip_key stats it
    ic.store(str(out), str(src), 3.0, ic.ClipResult(clip=clip, phashes=[], cast=[]),
             model="m", proxy_long_side=960, reid_model="", band=(1.2, 4.0))
    # control: the SAME band a load must return the stored entry — otherwise this test
    # would pass against a load() that always returns None regardless of band
    assert ic.load(str(out), str(src), 3.0, model="m", proxy_long_side=960,
                   reid_model="", band=(1.2, 4.0)) is not None
    # a later run under a DIFFERENT band must MISS, not silently serve stale boundaries
    assert ic.load(str(out), str(src), 3.0, model="m", proxy_long_side=960,
                   reid_model="", band=(1.2, 6.0)) is None


def test_cache_version_is_nine_for_the_carve_band_key():
    # the carve band joins clip_key (design 2026-09-03 §0.5/§3): carve_windows runs
    # inside the cached Phase 1, so a cached v8 ClipResult was carved under whatever
    # band scanned it, with no key term recording which — a changed WIN_MIN/WIN_MAX
    # must miss instead of silently returning boundaries carved under the old band
    from scripts.lib import intake_cache as ic
    assert ic.CACHE_VERSION == 9


def test_clip_key_carries_the_band(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    k = intake_cache.clip_key(str(p), 2.0, "m.pt", 960, band=(1.2, 4.0))
    assert k["band"] == [1.2, 4.0]


def test_a_different_band_is_a_different_key(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    a = intake_cache.clip_key(str(p), 2.0, "m.pt", 960, band=(1.2, 4.0))
    b = intake_cache.clip_key(str(p), 2.0, "m.pt", 960, band=(1.2, 6.0))
    assert a != b


def test_band_is_a_required_keyword(tmp_path):
    # A silent default here would serve boundaries carved under another band —
    # the same failure proxy_long_side is a required argument to prevent.
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    with pytest.raises(TypeError):
        intake_cache.clip_key(str(p), 2.0, "m.pt", 960)


def _photo_result(name="IMG_1.jpg", taken=1_760_000_000.25, sharpness=812.375):
    w = FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=0, motion=0.0, shake=0.0)
    clip = FootageClip(source=name, dur=8.0, res=(400, 300), fps=0.0, windows=[w],
                       kind="photo")
    return ClipResult(clip=clip, phashes=["8f3c2a1b0d4e5f60"], taken=taken,
                      sharpness=sharpness)


def test_a_photos_capture_time_and_sharpness_round_trip(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path, "IMG_1.jpg")
    stored = intake_cache.store(str(out), str(src), 3.0, _photo_result(), _M, _PROXY,
                                band=carve.DEFAULT_BAND)
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    assert (stored.taken, stored.sharpness) == (1_760_000_000.25, 812.375)
    assert (loaded.taken, loaded.sharpness) == (1_760_000_000.25, 812.375)
    assert loaded.clip.to_dict() == _photo_result().clip.to_dict()


def test_a_video_result_writes_no_photo_fields_and_reads_back_none(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY, band=carve.DEFAULT_BAND)
    payload = json.loads((out / ".intake_cache" / "a.mp4" / "clip.json").read_text())
    assert "taken" not in payload and "sharpness" not in payload
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    assert (loaded.taken, loaded.sharpness) == (None, None)


def test_a_photo_without_a_capture_time_round_trips_none(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path, "IMG_2.png")
    intake_cache.store(str(out), str(src), 3.0, _photo_result("IMG_2.png", taken=None),
                       _M, _PROXY, band=carve.DEFAULT_BAND)
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    assert (loaded.taken, loaded.sharpness) == (None, 812.375)


# --- the photo-only key term (design 2026-10-21 §5; the 2026-10-21 review's M9) -------

def _v9_key(src):
    """The key exactly as the pre-photo-rhythm code wrote it: no photo term."""
    st = src.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sample_fps": 3.0, "model": _M,
            "proxy_long_side": _PROXY, "reid_model": "",
            "band": [float(v) for v in carve.DEFAULT_BAND], "version": 9}


def _write_entry(out, src, key, result):
    d = out / ".intake_cache" / src.name
    d.mkdir(parents=True)
    (d / "clip.json").write_text(json.dumps(
        {"key": key, "clip": result.clip.to_dict(), "phashes": result.phashes, "cast": []}))


def test_a_video_entry_written_before_the_photo_fields_still_loads(tmp_path):
    # a photo-only payload change must not re-scan every video of an existing run
    out, src = tmp_path / "out", _src(tmp_path)
    _write_entry(out, src, _v9_key(src), _result())
    hit = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    assert hit is not None and hit.clip.to_dict() == _clip().to_dict()


def test_a_photo_entry_written_before_the_photo_fields_misses(tmp_path):
    # it carries no capture time and no sharpness: Phase 2 would group it with no time
    # and rank it the least sharp, so it re-scans instead
    out, src = tmp_path / "out", _src(tmp_path, "IMG_1.jpg")
    _write_entry(out, src, _v9_key(src), _photo_result(taken=None, sharpness=None))
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY,
                             band=carve.DEFAULT_BAND) is None


def test_only_a_photos_key_carries_the_photo_term(tmp_path):
    video, photo = _src(tmp_path), _src(tmp_path, "IMG_1.HEIC")
    vk = intake_cache.clip_key(str(video), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    pk = intake_cache.clip_key(str(photo), 3.0, _M, _PROXY, band=carve.DEFAULT_BAND)
    assert vk == _v9_key(video)
    assert pk == {**_v9_key(photo), "photo_version": intake_cache.PHOTO_CACHE_VERSION}
    assert intake_cache.PHOTO_CACHE_VERSION == 1
