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


# --- ID-switch stitching (§6.1a) ------------------------------------------------

def _frames(spans, fps=60.0):
    """spans: {tid: (first, last, x0, dx, w, h)} → the per_frame shape build_route builds."""
    n = 1 + max(s[1] for s in spans.values())
    out = []
    for idx in range(n):
        dets = []
        for tid, (a, b, x0, dx, w, h) in spans.items():
            if a <= idx <= b:
                dets.append((tid, x0 + dx * (idx - a), 500.0, w, h))
        out.append((idx, dets))
    return out


def test_segments_records_ends_count_and_per_frame_x():
    pf = _frames({1: (0, 4, 100.0, 10.0, 120, 300)})
    segs = track._segments(pf)
    assert segs[1]["first"] == 0 and segs[1]["last"] == 4 and segs[1]["n"] == 5
    assert segs[1]["head"] == (100.0, 500.0, 120, 300)
    assert segs[1]["tail"] == (140.0, 500.0, 120, 300)
    assert segs[1]["at"] == {0: 100.0, 1: 110.0, 2: 120.0, 3: 130.0, 4: 140.0}


def test_median_handles_odd_and_even_lengths():
    assert track._median([3.0, 1.0, 2.0]) == 2.0
    assert track._median([1.0, 2.0, 3.0, 4.0]) == 2.5
