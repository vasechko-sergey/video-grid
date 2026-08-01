import numpy as np
import pytest
from scripts.lib import assembly, ffbin

pytestmark = pytest.mark.integration


def _make_src(path, w=1920, h=1080, secs=1):
    import subprocess
    subprocess.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
                    f"testsrc=size={w}x{h}:rate=30:duration={secs}",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


def test_make_proxy_downscales_long_side_to_960(tmp_path):
    src = tmp_path / "src.mp4"; _make_src(src)
    dst = tmp_path / "proxy.mp4"
    assembly.make_proxy(str(src), str(dst), long_side=960)
    info = assembly.probe_stream(str(dst))
    assert max(info.w, info.h) == 960          # long side hit
    assert (info.w, info.h) == (960, 540)      # 16:9 preserved, even dims


def test_make_proxy_does_not_upscale_a_small_clip(tmp_path):
    src = tmp_path / "s.mp4"; _make_src(src, w=640, h=360)
    dst = tmp_path / "p.mp4"
    made = assembly.make_proxy(str(src), str(dst), long_side=960)
    assert made is False                       # already <=960 long side → no proxy written
    assert not dst.exists()


def test_frame_rgb_returns_original_resolution_array(tmp_path):
    src = tmp_path / "s.mp4"; _make_src(src, w=1920, h=1080)
    arr = assembly.frame_rgb(str(src), 0.5)
    assert isinstance(arr, np.ndarray) and arr.shape == (1080, 1920, 3)
