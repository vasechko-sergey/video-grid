import subprocess, shutil
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """3s 1920x1080 30fps clip: a bright box sliding left→right on dark bg."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    # box centre x moves from 270 to 1560 over 3s; y fixed; on a dark grey field.
    # NOTE: drawbox's x/y expressions are inert under ffmpeg 8.1.1 (the `t` var reads
    # as INT32_MAX, not the frame time) → the box never moves/appears. overlay's
    # position expressions DO evaluate per-frame, so we composite a white box source.
    bg = "color=c=0x303030:s=1920x1080:d=3:r=30"
    box = "color=c=white:s=140x320:d=3:r=30"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
         "-filter_complex", "[0][1]overlay=x='200+t*430':y=380",
         "-t", "3", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True)
    return out
