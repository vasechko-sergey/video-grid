import pytest

from scripts.lib import ffbin, proc


@pytest.fixture(scope="session")
def sample_clip(tmp_path_factory):
    """3s 1920x1080 30fps clip: a bright box sliding left→right on dark bg."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    # box centre x moves from 270 to 1560 over 3s; y fixed; on a dark grey field.
    # NOTE: drawbox's x/y expressions are inert under ffmpeg 8.1.1 (the `t` var reads
    # as INT32_MAX, not the frame time) → the box never moves/appears. overlay's
    # position expressions DO evaluate per-frame, so we composite a white box source.
    bg = "color=c=0x303030:s=1920x1080:d=3:r=30"
    box = "color=c=white:s=140x320:d=3:r=30"
    proc.run(
        [binary, "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
         "-filter_complex", "[0][1]overlay=x='200+t*430':y=380",
         "-t", "3", "-pix_fmt", "yuv420p", str(out)])
    return out


@pytest.fixture(scope="session")
def ramp_clip(tmp_path_factory):
    """2s 640x360 60fps clip: a white box sliding left→right on a dark field.

    60 fps on purpose — MIN_RAMP_FPS = 24.0 admits only factor >= 0.8 on the 30fps
    sample_clip, too shallow a ramp to measure against noise.

    Uses overlay, not drawbox: drawbox's x/y expressions are inert under this
    ffmpeg (the `t` var reads as INT32_MAX), so a moving drawbox never appears at
    all — see sample_clip's note.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "ramp.mp4"
    bg = "color=c=0x202020:s=640x360:d=2:r=60"
    box = "color=c=white:s=40x80:d=2:r=60"
    proc.run(
        [binary, "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
         "-filter_complex", "[0][1]overlay=x='60+t*250':y=140",
         "-t", "2", "-pix_fmt", "yuv420p", str(out)])
    return out


@pytest.fixture
def need_filter():
    """Skip unless the RESOLVED ffmpeg carries `name`.

    Both skip reasons live here. ffbin.has_filter fails loud when nothing
    resolves at all, which is right for production and wrong for a test run on a
    box without ffmpeg — that should skip, not error.
    """
    def _need(name: str) -> None:
        try:
            present = ffbin.has_filter(name)
        except (ValueError, RuntimeError) as e:
            pytest.skip(str(e))
        if not present:
            pytest.skip(f"ffmpeg lacks the {name} filter (run: bash setup.sh)")
    return _need
