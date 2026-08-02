import numpy as np
import pytest
from PIL import Image

from scripts.lib import assembly, ffbin, proc

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


def _gray_ramp_clip(tmp_path, n=10, fps=10):
    """A clip whose frame i is solid gray v=i*25 — distinct, 420-subsampling-robust."""
    src = tmp_path / "ramp"; src.mkdir()
    for i in range(n):
        v = i * 25
        Image.new("RGB", (64, 64), (v, v, v)).save(src / f"{i:03d}.png")
    clip = tmp_path / "ramp.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-framerate", str(fps), "-i", str(src / "%03d.png"),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])
    return str(clip)


@pytest.mark.integration
def test_frames_rgb_selects_exact_frames_in_input_order(tmp_path):
    clip = _gray_ramp_clip(tmp_path)
    # unsorted → frames 8, 2, 5 (gray ≈ 200, 50, 125); result stays in INPUT order
    frames = assembly.frames_rgb(clip, [0.8, 0.2, 0.5], 10.0)
    vals = [int(f.mean()) for f in frames]
    assert vals[0] > vals[2] > vals[1]                       # order preserved, not sorted
    assert abs(vals[0] - 200) < 15 and abs(vals[1] - 50) < 15 and abs(vals[2] - 125) < 15
    assert frames[0].ndim == 3 and frames[0].shape[2] == 3


@pytest.mark.integration
def test_frames_rgb_dedupes_and_empty(tmp_path):
    clip = _gray_ramp_clip(tmp_path, n=5)
    dup = assembly.frames_rgb(clip, [0.3, 0.3], 10.0)        # same frame twice
    assert len(dup) == 2 and np.array_equal(dup[0], dup[1])
    assert assembly.frames_rgb(clip, [], 10.0) == []         # no times → no decode


def test_frames_rgb_handles_more_than_one_select_chunk(tmp_path):
    # >_SELECT_CHUNK distinct frames must all come back, in input order, across
    # chunk boundaries — the case a single giant select expression ENOMEMs on 4K.
    n = assembly._SELECT_CHUNK * 2 + 5           # forces >=3 chunks
    src = tmp_path / "ramp"; src.mkdir()
    for i in range(n):
        Image.new("RGB", (16, 16), (i % 256, i % 256, i % 256)).save(src / f"{i:04d}.png")
    clip = tmp_path / "ramp.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-framerate", "30", "-i", str(src / "%04d.png"),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])
    order = list(range(n - 1, -1, -1))           # reversed → also checks ordering
    frames = assembly.frames_rgb(clip.as_posix(), [i / 30.0 for i in order], 30.0)
    assert len(frames) == n
    vals = [int(f.mean()) for f in frames]
    assert all(abs(v - (i % 256)) < 8 for v, i in zip(vals, order))   # each slot = its frame
