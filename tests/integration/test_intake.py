"""footage-intake (5.2) real-ffmpeg golden.

Proves the intake WIRING on real bytes: real ffprobe + real PySceneDetect +
real phash cull + the contract/markdown render + the cast-candidate persistence.
YOLO is faked because YOLO returns an empty route on the synthetic `sample_clip`
(a box is not a person — design §12, same reason test_front_spine fakes
process_episode). The vidstabdetect `.trf` path has its own real-vidstab test
that skips when libvidstab is absent.
"""
import shutil

import pytest

from scripts import intake
from scripts.lib import ffbin, footage

pytestmark = pytest.mark.integration


def _has_vidstab() -> bool:
    """Collection-time, so this cannot be the shared `need_filter` fixture — the
    skipif below is evaluated at import. It delegates to the same one
    implementation, which is the part that matters: probe the RESOLVED binary,
    never PATH. A box with no ffmpeg at all resolves to nothing and skips."""
    try:
        return ffbin.has_filter("vidstabdetect")
    except (ValueError, RuntimeError):
        return False


class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [0.9]


class _FakeRes:
    def __init__(self, boxes):
        self.boxes = boxes; self.orig_img = None; self.masks = None


def _fake_frames(n):
    # one person present throughout, sliding right — YOLO would return empty on
    # the synthetic box, so we feed a real-shaped detection stream instead.
    # Boxes are authored in PROXY (960-long-side) coordinates, because the analysis
    # runs on the 960 proxy make_proxy writes from the 1920 sample_clip (design
    # 2026-08-01): _motion/shot_type normalize by pres=(960,540), and
    # _cast_from_original scales the box up by res/pres=2 to crop the 1920 original.
    # In 1920 coords they would normalize/scale 2x wrong (a clipped crop, saturated
    # motion, an inflated shot_type).
    return [_FakeRes([_FakeBox([150 + i * 6, 250, 100, 150], 1)]) for i in range(n)]


def test_intake_wiring_on_real_bytes(monkeypatch, tmp_path, sample_clip):
    # real ffprobe + real PySceneDetect + real phash on real bytes; YOLO + shake
    # faked (shake has its own real-vidstab test below).
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(_fake_frames(90))))
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.reid, "embed",           # torchreid absent on CI: fake 512-d rows
                        lambda crops: [[1.0] + [0.0] * 511 for _ in crops])
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    monkeypatch.setattr(intake.vidstab, "detect", lambda src, trf, dur: [])

    out = tmp_path / "out"
    result = intake.intake(str(root), str(out))

    assert (out / "FOOTAGE.json").exists() and (out / "FOOTAGE.md").exists()
    assert (out / "cast_candidates.json").exists()          # cast-candidate wiring reached
    footage.Footage.from_json(out / "FOOTAGE.json")          # round-trips
    # Whole-object golden. res is the ORIGINAL 1920x1080 (make_proxy analyses a 960
    # proxy but FootageClip stores the source geometry); shot_type/motion are
    # measured in proxy space. Values re-pinned for the 960 analysis proxy (design
    # 2026-08-01) — shake=0.0 here because vidstab.detect is faked (its real value
    # is pinned in test_intake_real_vidstab_shake).
    #
    # motion/score/description re-pinned by 2026-08-06-intake-motion-scoring. Neither
    # number is magic — both fall out of the fixture:
    #   motion 0.0625: _fake_frames slides track 1 by 6 px/frame in PROXY space; at
    #     SAMPLE_FPS=3.0 on a 30 fps clip that is 10 frames = 60 px between samples,
    #     60/960 = 0.0625, stored exactly at the 4dp precision `_build_window` now
    #     rounds to. It read 0.625 before because MOTION_GAIN multiplied the fraction
    #     by 10; the gain is deleted, so the reported number IS the measurement now
    #     (§3.3).
    #   score 0.5: score is a percentile over the whole pool (§3.4), and this pool holds
    #     exactly ONE window — _percentile_rank returns 0.5 for n==1, "neither above nor
    #     below anything". So the 0.861 this used to pin was an absolute blend that no
    #     longer exists; a single-clip fixture cannot pin an ordering, and the real
    #     ordering proof lives in tests/lib/test_intake.py's score_pool tests.
    #   "dynamic" survives, but on a new footing: motion RANK 0.5 >= DYNAMIC_RANK 0.5,
    #     not a high absolute fraction.
    #   best=True is forced the same way, and is worth naming explicitly: BEST_FLOOR is
    #     exactly 0.50 and cull's rule is `(not dup) and score >= BEST_FLOOR` — the pool's
    #     one window is never a dup (kept starts empty) and scores exactly 0.5, so best
    #     is True here regardless of what the window actually shows. A singleton pool
    #     cannot exercise cull's dedup/floor logic any more than it can exercise ordering.
    assert result.clips[0] == footage.FootageClip(
        source="clip.mp4", dur=3.0, res=(1920, 1080), fps=30.0, shaky=False,
        scene_cuts=[],
        windows=[footage.FootageWindow(
            start=0.0, dur=3.0, shot_type="wide", people=1, motion=0.0625,
            shake=0.0, description="1 person, wide, dynamic", score=0.5,
            best=True, track_ids=[1], subject_w=0.1042, subject_h=0.2778,
            present=1.0)])
    assert "# Footage —" in result.to_markdown()


@pytest.mark.skipif(not _has_vidstab(), reason="needs vidstab-enabled ffmpeg (bash setup.sh)")
def test_intake_real_vidstab_shake(monkeypatch, tmp_path, sample_clip):
    # the real vidstabdetect + .trf parse path on real bytes (skips without libvidstab)
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(_fake_frames(90))))
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.reid, "embed",           # torchreid absent on CI: fake 512-d rows
                        lambda crops: [[1.0] + [0.0] * 511 for _ in crops])

    result = intake.intake(str(root), str(tmp_path / "out"))
    # Whole-object golden: real vidstabdetect ran on the 960 proxy + parsed its
    # ascii .trf → shake 0.0077 (a small fraction of frame width, below SHAKY_CLIP
    # 0.02 → shaky=False). Values re-pinned for the 960 analysis proxy (design
    # 2026-08-01); shake shifts vs the raw 1920 pass because detect ran on the proxy.
    # motion 0.0625 / score 0.5 re-pinned by 2026-08-06-intake-motion-scoring — same two
    # causes as the fixture above (MOTION_GAIN deleted; score is a one-window pool's
    # percentile). shake is what this test is FOR and it did not move: the same 0.0077
    # scores 0.5 here as 0.0 does above, because a percentile over a single window
    # cannot see shake at all — the shake-vs-score coupling is proved by the pool tests,
    # this one proves the .trf parse. best=True is forced too, same as the fixture
    # above: BEST_FLOOR == 0.50 == this pool's only score, so cull marks it best on
    # this shake value exactly as it would on any other — this test cannot exercise
    # BEST_FLOOR as a real cut either.
    assert result.clips[0] == footage.FootageClip(
        source="clip.mp4", dur=3.0, res=(1920, 1080), fps=30.0, shaky=False,
        scene_cuts=[],
        windows=[footage.FootageWindow(
            start=0.0, dur=3.0, shot_type="wide", people=1, motion=0.0625,
            shake=0.0077, description="1 person, wide, dynamic", score=0.5,
            best=True, track_ids=[1], subject_w=0.1042, subject_h=0.2778,
            present=1.0)])


def test_intake_resumes_from_cache_byte_identical(monkeypatch, tmp_path, sample_clip):
    # real ffprobe + PySceneDetect + phash on run 1; run 2 must touch NO clip CV
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(_fake_frames(90))))
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    monkeypatch.setattr(intake.vidstab, "detect", lambda src, trf, dur: [])
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.reid, "embed",           # torchreid absent on CI: fake 512-d rows
                        lambda crops: [[1.0] + [0.0] * 511 for _ in crops])
    out = tmp_path / "out"
    intake.intake(str(root), str(out))
    first = (out / "FOOTAGE.json").read_text()
    assert (out / ".intake_cache" / "clip.mp4" / "clip.json").exists()

    monkeypatch.setattr(intake, "_process_clip",
                        lambda *a, **k: pytest.fail("resume recomputed a cached clip"))
    intake.intake(str(root), str(out))                 # must be all cache hits → no CV
    assert (out / "FOOTAGE.json").read_text() == first
