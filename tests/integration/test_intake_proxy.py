"""Proxy-wiring proof on real bytes (design 2026-08-01-intake-analysis-proxy).

The sample_clip is 1920x1080, so make_proxy writes a 960-long-side proxy and the
whole analysis (scene-detect, YOLO, vidstabdetect, phash) runs on THAT — while
FootageClip.res must still record the ORIGINAL geometry, because delivery-space
crops stay full-res. This spies on vidstab.detect to prove its input really is the
downscaled proxy, and asserts the stored res is the original. YOLO is faked (a box
is not a person on the synthetic clip, design §12); vidstab is real, gated by
need_filter (require() needs both detect + transform, so both are gated).
"""
import pytest

from scripts import intake
from scripts.lib import assembly

pytestmark = pytest.mark.integration


class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [0.9]


class _FakeRes:
    def __init__(self, boxes):
        self.boxes = boxes; self.orig_img = None; self.masks = None


def _fake_frames(n):
    # PROXY (960-long-side) coords, matching test_intake.py: analysis runs on the proxy.
    return [_FakeRes([_FakeBox([150 + i * 6, 250, 100, 150], 1)]) for i in range(n)]


def test_proxy_intake_analyses_proxy_but_stores_original_res(need_filter, sample_clip, monkeypatch):
    need_filter("vidstabdetect")            # real vidstab on the proxy; skip if absent
    need_filter("vidstabtransform")         # vidstab.require() needs both
    monkeypatch.setattr(intake, "_iter_seg",
                        lambda src, **k: iter(enumerate(_fake_frames(90))))
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)

    # Spy on the real detect: capture the width of the pixels it actually analyses
    # (probed inside the spy, before _process_clip's TemporaryDirectory is torn down).
    seen: dict[str, object] = {}
    real_detect = intake.vidstab.detect

    def spy_detect(src, trf, dur):
        seen["src"] = src
        seen["w"] = assembly.probe_stream(src).w
        return real_detect(src, trf, dur)

    monkeypatch.setattr(intake.vidstab, "detect", spy_detect)

    res = intake._process_clip(str(sample_clip))

    # analysis ran on the 960 proxy, NOT the 1920 source bytes
    assert seen["src"] != str(sample_clip)
    assert seen["w"] == 960
    # ...yet the ORIGINAL geometry is what FootageClip records
    assert res.clip.res == (1920, 1080)
    # real carving + a real vidstab measurement survived the proxy round-trip
    assert res.clip.windows
    assert all(0.0 <= w.shake < 1.0 for w in res.clip.windows)
