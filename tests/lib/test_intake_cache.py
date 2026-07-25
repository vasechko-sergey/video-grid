import json
import numpy as np
from PIL import Image

import pytest

from scripts.lib import intake_cache
from scripts.lib.intake_cache import CastEntry, ClipResult
from scripts.lib.footage import DESCRIPTOR_LEN, FootageClip, FootageWindow


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
    stored = intake_cache.store(str(out), str(src), 3.0, _result())
    loaded = intake_cache.load(str(out), str(src), 3.0)
    assert loaded is not None
    assert loaded.clip.to_dict() == _clip().to_dict()
    assert loaded.phashes == ["8f3c2a1b0d4e5f60"]
    assert loaded.cast[0].source == "a.mp4" and loaded.cast[0].tid == 1
    assert loaded.cast[0].descriptor == _desc(0.5, 0.5)
    # cached-form carries the crop as a PNG path, not an array
    assert stored.cast[0].crop == loaded.cast[0].crop and loaded.cast[0].crop_rgb is None
    assert Image.open(loaded.cast[0].crop).size == (8, 8)


def test_load_is_none_when_absent(tmp_path):
    assert intake_cache.load(str(tmp_path / "out"), str(_src(tmp_path)), 3.0) is None


def test_load_is_none_on_changed_mtime(tmp_path):
    import os, time
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    os.utime(src, ns=(0, 0))                       # different mtime_ns
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_load_is_none_on_changed_sample_fps(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    assert intake_cache.load(str(out), str(src), 4.0) is None


def test_load_is_none_on_changed_model(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), model="m1")
    assert intake_cache.load(str(out), str(src), 3.0, model="m2") is None


def test_load_is_none_on_bumped_version(tmp_path, monkeypatch):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    monkeypatch.setattr(intake_cache, "CACHE_VERSION", intake_cache.CACHE_VERSION + 1)
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_crops_without_clip_json_is_a_miss(tmp_path):
    # the commit marker is clip.json; a crash mid-write leaves crops but no json
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    (out / ".intake_cache" / "a.mp4" / "clip.json").unlink()
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_corrupt_clip_json_is_a_miss_not_a_crash(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    (out / ".intake_cache" / "a.mp4" / "clip.json").write_text("{ not json")
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_crop_png_round_trips_red(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    loaded = intake_cache.load(str(out), str(src), 3.0)
    px = np.asarray(Image.open(loaded.cast[0].crop))
    assert px[0, 0, 0] == 255 and px[0, 0, 1] == 0     # still red
