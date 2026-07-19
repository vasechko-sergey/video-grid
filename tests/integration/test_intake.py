"""footage-intake (5.2) real-ffmpeg golden.

Proves the intake WIRING on real bytes: real ffprobe + real PySceneDetect +
real phash cull + the contract/markdown render + the cast-candidate persistence.
YOLO is faked because YOLO returns an empty route on the synthetic `sample_clip`
(a box is not a person — design §12, same reason test_front_spine fakes
process_episode). The vidstabdetect `.trf` path has its own real-vidstab test
that skips when libvidstab is absent.
"""
import shutil
import subprocess

import pytest

from scripts import intake
from scripts.lib import footage

pytestmark = pytest.mark.integration


def _has_vidstab() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True).stdout
    return b"vidstabdetect" in out


class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [0.9]


class _FakeRes:
    def __init__(self, boxes):
        self.boxes = boxes; self.orig_img = None; self.masks = None


def _fake_frames(n):
    # one person present throughout, sliding right — YOLO would return empty on
    # the synthetic box, so we feed a real-shaped detection stream instead.
    return [_FakeRes([_FakeBox([300 + i * 12, 500, 200, 300], 1)]) for i in range(n)]


def test_intake_wiring_on_real_bytes(monkeypatch, tmp_path, sample_clip):
    # real ffprobe + real PySceneDetect + real phash on real bytes; YOLO + shake
    # faked (shake has its own real-vidstab test below).
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(_fake_frames(90))))
    monkeypatch.setattr(intake, "shake_by_window",
                        lambda clip, spans, fps, res, dur: [0.0 for _ in spans])

    out = tmp_path / "out"
    result = intake.intake(str(root), str(out))

    assert (out / "FOOTAGE.json").exists() and (out / "FOOTAGE.md").exists()
    assert (out / "cast_candidates.json").exists()          # cast-candidate wiring reached
    footage.Footage.from_json(out / "FOOTAGE.json")          # round-trips
    clip = result.clips[0]
    assert clip.source == "clip.mp4" and clip.res == (1920, 1080)
    assert len(clip.windows) >= 1
    assert clip.windows[0].shot_type in {"close", "medium", "wide"}
    assert "# Footage —" in result.to_markdown()


@pytest.mark.skipif(not _has_vidstab(), reason="needs vidstab-enabled ffmpeg (bash setup.sh --with-vidstab)")
def test_intake_real_vidstab_shake(monkeypatch, tmp_path, sample_clip):
    # the real vidstabdetect + .trf parse path on real bytes (skips without libvidstab)
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(_fake_frames(90))))

    result = intake.intake(str(root), str(tmp_path / "out"))
    clip = result.clips[0]
    assert len(clip.windows) >= 1
    assert all(w.shake >= 0.0 for w in clip.windows)         # vidstabdetect measured + parsed
