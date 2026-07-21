import sys
import types

from scripts import track
from scripts.lib.manifest import DEFAULT_MODEL


def _fake_ultralytics(calls):
    """A stand-in ultralytics module whose YOLO records the path it was built with.
    Faked at the sys.modules level because ensure_model imports ultralytics lazily,
    INSIDE the function — so the fake must be in place at call time, not import time.
    Keeps the fast tier free of real weights and of any network access."""
    mod = types.ModuleType("ultralytics")

    class _YOLO:
        def __init__(self, path):
            calls.append(path)

    mod.YOLO = _YOLO
    return mod


def test_ensure_model_constructs_the_named_model(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "ultralytics", _fake_ultralytics(calls))
    track.ensure_model("yolo11s-seg.pt")
    assert calls == ["yolo11s-seg.pt"]


def test_ensure_model_defaults_to_the_module_model(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "ultralytics", _fake_ultralytics(calls))
    track.ensure_model()
    assert calls == [track.MODEL]


def test_the_module_model_matches_the_manifest_default():
    # The fan-out warms track.MODEL (scripts/edl_to_reel.py) while every worker ends up
    # constructing manifest.DEFAULT_MODEL (Manifest -> TrackSpec -> _iter_detections).
    # They are independent literals. If they ever drift, the driver warms model A while N
    # workers race a cold download of model B into one path — precisely the silent
    # corruption the warm-up exists to prevent, and nothing else asserts they agree.
    assert track.MODEL == DEFAULT_MODEL


def test_available_true_when_ultralytics_imports():
    # this repo's env ships ultralytics (requirements.txt), so the gate is open
    assert track.available() is True


def test_available_false_when_ultralytics_absent(monkeypatch):
    # setting the module to None makes `import ultralytics` raise ImportError —
    # the "ultralytics unavailable" rung-1 trigger, simulated without uninstalling
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    assert track.available() is False
