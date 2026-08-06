import json

import numpy as np
from PIL import Image

from scripts.lib import intake_cache
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
    stored = intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY)
    assert loaded is not None
    assert loaded.clip.to_dict() == _clip().to_dict()
    assert loaded.phashes == ["8f3c2a1b0d4e5f60"]
    assert loaded.cast[0].source == "a.mp4" and loaded.cast[0].tid == 1
    assert loaded.cast[0].descriptor == _desc(0.5, 0.5)
    assert stored.cast[0].crop == loaded.cast[0].crop and loaded.cast[0].crop_rgb is None
    assert Image.open(loaded.cast[0].crop).size == (8, 8)


def test_load_is_none_when_absent(tmp_path):
    assert intake_cache.load(str(tmp_path / "out"), str(_src(tmp_path)), 3.0, _M, _PROXY) is None


def test_load_is_none_on_changed_mtime(tmp_path):
    import os
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    os.utime(src, ns=(0, 0))
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_load_is_none_on_changed_sample_fps(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    assert intake_cache.load(str(out), str(src), 4.0, _M, _PROXY) is None


def test_load_is_none_on_changed_model(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), "m1", _PROXY)
    assert intake_cache.load(str(out), str(src), 3.0, "m2", _PROXY) is None


def test_load_is_none_on_bumped_version(tmp_path, monkeypatch):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    monkeypatch.setattr(intake_cache, "CACHE_VERSION", intake_cache.CACHE_VERSION + 1)
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_crops_without_clip_json_is_a_miss(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    (out / ".intake_cache" / "a.mp4" / "clip.json").unlink()
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_corrupt_clip_json_is_a_miss_not_a_crash(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    (out / ".intake_cache" / "a.mp4" / "clip.json").write_text("{ not json")
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_nondict_clip_json_is_a_miss_not_a_crash(tmp_path):
    # valid JSON, wrong shape: payload.get would AttributeError without the guard
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    (out / ".intake_cache" / "a.mp4" / "clip.json").write_text("null")
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_load_is_none_when_source_file_removed(tmp_path):
    # a raw clip moved/deleted between runs → clip_key's os.stat must not crash the
    # scan; a miss routes it back through the worker, where quarantine covers it
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    src.unlink()
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_crop_png_round_trips_red(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), _M, _PROXY)
    loaded = intake_cache.load(str(out), str(src), 3.0, _M, _PROXY)
    px = np.asarray(Image.open(loaded.cast[0].crop))
    assert px[0, 0, 0] == 255 and px[0, 0, 1] == 0


def test_a_version_1_entry_is_a_miss(tmp_path):
    # a cache written under an old CACHE_VERSION must not be trusted by current code
    from scripts.lib import intake_cache
    src = tmp_path / "a.mp4"; src.write_bytes(b"x")
    out = tmp_path / "out"; out.mkdir()
    d = out / ".intake_cache" / "a.mp4"; d.mkdir(parents=True)
    key = intake_cache.clip_key(str(src), 3.0, _M, _PROXY)
    stale = {**key, "version": 1}
    (d / "clip.json").write_text(json.dumps(
        {"key": stale, "clip": {"source": "a.mp4", "dur": 1.0, "res": [2, 2], "fps": 1.0,
                                "shaky": False, "scene_cuts": [], "windows": []},
         "phashes": [], "cast": []}))
    assert intake_cache.load(str(out), str(src), 3.0, _M, _PROXY) is None


def test_clip_key_includes_proxy_long_side_and_v7(tmp_path):
    from scripts.lib import intake_cache
    f = tmp_path / "c.mp4"; f.write_bytes(b"x")
    k = intake_cache.clip_key(str(f), sample_fps=3.0, model="m", proxy_long_side=960)
    assert k["version"] == 7
    assert k["proxy_long_side"] == 960
    k2 = intake_cache.clip_key(str(f), sample_fps=3.0, model="m", proxy_long_side=1280)
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
                      model="m", proxy_long_side=960, reid_model="osnet_x1_0")
    assert stored.cast[0].presence == 2.5
    loaded = ic.load(str(out), str(src), 3.0, model="m",
                     proxy_long_side=960, reid_model="osnet_x1_0")
    assert loaded.cast[0].presence == 2.5


def test_reid_model_is_part_of_the_key(tmp_path):
    from scripts.lib import intake_cache as ic
    clip = _clip()
    out, src = tmp_path / "out", _src(tmp_path)        # a real backing file: clip_key stats it
    ic.store(str(out), str(src), 3.0, ic.ClipResult(clip=clip, phashes=[], cast=[]),
             model="m", proxy_long_side=960, reid_model="")           # cached reid-absent
    # a later run WITH reid must MISS, not serve the stale empty-cast entry
    assert ic.load(str(out), str(src), 3.0, model="m",
                   proxy_long_side=960, reid_model="osnet_x1_0") is None


def test_cache_version_is_seven_for_the_shot_size_fields():
    # shot-size fields (design 2026-08-06): FootageWindow stores subject_w/subject_h/
    # present, measured in Phase 1 — a cached ClipResult (built under v6) cannot
    # supply them → v6 must miss
    from scripts.lib import intake_cache as ic
    assert ic.CACHE_VERSION == 7
