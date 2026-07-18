import sys
import types

from scripts import track


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
