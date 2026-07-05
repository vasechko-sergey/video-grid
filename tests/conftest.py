import subprocess, shutil
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """3s 1920x1080 30fps clip: a bright box sliding left→right on dark bg."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    # box centre x moves from 270 to 1560 over 3s; y fixed; on a dark grey field
    src = "color=c=0x303030:s=1920x1080:d=3:r=30"
    vf = "drawbox=x='200+t*430':y=380:w=140:h=320:color=white:t=fill"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-vf", vf,
         "-t", "3", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True)
    return out
