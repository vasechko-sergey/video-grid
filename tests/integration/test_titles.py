"""Real-ffmpeg proof for the titles stage (design docs/specs/2026-07-13-titles-design.md,
§5.16): a TITLES.json burned by deliver changes pixels in the title's time window, and
(with audio) rides the mux branch's single encode. Uses the shared sample_clip fixture;
skips where this machine's ffmpeg lacks drawtext (same guard as the draft golden)."""
import shutil
from pathlib import Path

import pytest

from scripts import deliver as deliver_mod
from scripts.lib import proc
from scripts.lib.models import REEL_H264, CheckResult, ReelReport
from scripts.lib.titles import Title, Titles


@pytest.fixture(autouse=True)
def _need_drawtext():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    filters = proc.run(["ffmpeg", "-hide_banner", "-filters"]).stdout.decode(errors="replace")
    if "drawtext" not in filters:
        pytest.skip("ffmpeg built without the drawtext filter (run: bash setup.sh)")


def _passing_report():
    return ReelReport(checks={"length": CheckResult("length", True, {})})


def _frame_bytes(src, tmp_path, name):
    """One PNG frame at t=1.0 (inside the [0,3] title window). Input-seek is fine here —
    the title shows for the whole window, so any in-window frame carries it."""
    png = tmp_path / name
    proc.run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(src), "-frames:v", "1", str(png)])
    return png.read_bytes()


@pytest.mark.integration
def test_title_burns_into_the_silent_encode(sample_clip, tmp_path):
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("HELLO", 0.0, 3.0, pos="center", style="bold-box"),)).write(tj)
    titled = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "t"),
                                 "titled", _passing_report(), titles=str(tj))
    plain = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "p"),
                                "plain", _passing_report())
    assert Path(titled).exists() and Path(plain).exists()
    codec = proc.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                      "stream=codec_type", "-of", "csv=p=0", titled]).stdout.decode()
    assert "video" in codec
    # the centered box changed the frame inside the title window
    assert _frame_bytes(titled, tmp_path, "a.png") != _frame_bytes(plain, tmp_path, "b.png")


@pytest.mark.integration
def test_title_burns_into_the_mux_encode_with_audio(sample_clip, tmp_path):
    # the production path: music + titles -> deliver's mux branch (-vf + -map + -c:a copy)
    aac = tmp_path / "stem.aac"
    proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
              "-c:a", "aac", str(aac)])
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("HELLO", 0.0, 3.0, pos="center", style="bold-box"),)).write(tj)
    titled = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "t"),
                                 "titled+audio", _passing_report(), audio=str(aac), titles=str(tj))
    plain = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "p"),
                                "plain", _passing_report())
    # the muxed output carries BOTH a video and an audio stream...
    types = proc.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                      "-of", "csv=p=0", titled]).stdout.decode()
    assert "video" in types and "audio" in types
    # ...and the title still burned into the picture (frame differs from the titleless encode)
    assert _frame_bytes(titled, tmp_path, "a.png") != _frame_bytes(plain, tmp_path, "b.png")
