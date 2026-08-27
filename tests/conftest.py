from pathlib import Path

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
def multi_window_clip(tmp_path_factory):
    """12s 1920x1080 30fps, THREE segments with hard cuts at 5.0s and 9.5s — each
    its own background colour and its own box trajectory.

    Exists because `sample_clip` is 3s with no cut, and carve.units_for_span
    returns ONE whole unit for any span inside the [WIN_MIN, WIN_MAX] band — so
    that fixture is structurally unable to carve more than one window, which is
    why the 2026-08-06 pool-relative scoring shipped with no real-bytes proof
    (that design's §8). Here the first two spans (5.0s / 4.5s) exceed
    WIN_MAX = 4.0 and reach units_for_span's PEAK branch, while the third (2.5s)
    is in-band and yields one whole unit: all three branches fire.

    MEASURED, not assumed: ffprobe reports dur 12.0 / fps 30.0, and
    intake.scene_bounds returns exactly [5.0, 9.5] on these bytes.

    Distinct colours AND distinct trajectories on purpose — identical pixels
    would collide under the phash cull and mark every window but one a
    duplicate. Uses overlay, not drawbox, for the reason sample_clip records."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "multi.mp4"
    src = []
    for colour, dur in (("0x101010", 5.0), ("0x304060", 4.5), ("0x603020", 2.5)):
        src += ["-f", "lavfi", "-i", f"color=c={colour}:s=1920x1080:d={dur}:r=30",
                "-f", "lavfi", "-i", f"color=c=white:s=140x320:d={dur}:r=30"]
    graph = ("[0][1]overlay=x='200+t*300':y=300[a];"
             "[2][3]overlay=x='1500-t*250':y=500[b];"
             "[4][5]overlay=x='700+t*120':y=200[c];"
             "[a][b][c]concat=n=3:v=1:a=0[v]")
    proc.run([binary, "-y", *src, "-filter_complex", graph, "-map", "[v]",
              "-t", "12", "-pix_fmt", "yuv420p", str(out)])
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


@pytest.fixture(scope="session")
def pc_ramp_clip(tmp_path_factory):
    """2s 640x360 30fps FULL-RANGE clip: a horizontal luma ramp, tagged
    yuvj420p / color_range=pc.

    A ramp and not a flat field, because the defect it must reproduce is a tone
    transfer landing on the wrong place of a curve — a fixture with one luma
    value has no curve to be wrong about. MEASURED that it discriminates, which
    is the only reason it is worth having: cut with extract's arguments as they
    stood before 2026-08-27 and graded to a common target, the achieved profile
    misses by (-38.1, 0.0, -9.0); cut through the normalizing extract it misses
    by (-2.1, -0.5, -1.0).

    The bt709 description is NOT decoration. Measured 2026-08-27: ffmpeg writes
    the VUI's range flag only when it also writes a colour description, so a
    range-only source normalizes to `color_range=unknown` and no tag assertion
    can discriminate. Real footage always carries the description — the Canon
    this was designed against is bt709/bt709/bt709/pc — so a fixture without one
    was the unrealistic thing, not the test.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "pc_ramp.mp4"
    proc.run([binary, "-y", "-f", "lavfi", "-i", "nullsrc=s=640x360:d=2:r=30",
              "-vf", "format=gray,geq=lum='X*255/W',format=yuvj420p",
              "-c:v", "libx264", "-crf", "18", "-preset", "medium",
              "-color_range", "pc", "-color_primaries", "bt709",
              "-color_trc", "bt709", "-colorspace", "bt709",
              "-pix_fmt", "yuvj420p", str(out)])
    return out


@pytest.fixture(scope="session")
def tenbit_clip(tmp_path_factory):
    """1s 320x180 30fps TEN-BIT clip (yuv420p10le): a horizontal luma ramp.

    Carries no range tag, on purpose. The pool this slice was designed against
    holds three 10-bit HEVC clips and the real one reports
    `bits_per_raw_sample=N/A` with an unremarkable range — so depth is the only
    property that can catch it, and the fixture is shaped to make that the only
    property under test.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "tenbit.mp4"
    proc.run([binary, "-y", "-f", "lavfi", "-i", "nullsrc=s=320x180:d=1:r=30",
              "-vf", "format=gray,geq=lum='X*255/W',format=yuv420p10le",
              "-c:v", "libx264", "-crf", "18", "-preset", "medium",
              "-pix_fmt", "yuv420p10le", str(out)])
    return out


@pytest.fixture(scope="session")
def golden_ride_segment(tmp_path_factory):
    """`golden_ride.mp4` as a SEGMENT — the shape reframe actually consumes.

    The committed fixture is raw camera footage: `yuvj420p` / `color_range=pc`.
    In production nothing hands raw footage to reframe — `extract` cuts it into a
    segment first, and since 2026-08-27 that segment is limited-range by
    contract. Four integration files were feeding the raw file straight in, which
    is why `color.refuse_ungradeable_plane` refuses them: they were exercising a
    path production does not have.

    NOT built with `extract.extract`, deliberately: that seeks and trims, and
    `golden_route.json` is sampled against this clip's own timeline. This runs
    the identical range conversion over the WHOLE clip instead. Measured: dims
    1280x720, fps 60000/1001, 95 frames and duration 1.584917 are all bit-for-bit
    unchanged, so the route still applies; only the range moves, pc -> tv.

    All three arguments are load-bearing. `-pix_fmt yuv420p` alone does not
    convert (libx264 keeps full range for a full-range input); `scale=out_range=tv`
    alone does not either when the output format is `yuvj420p`, because that
    format *means* full range and wins. Measured both ways while writing this.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    src = Path(__file__).parent / "fixtures" / "golden_ride.mp4"
    out = tmp_path_factory.mktemp("media") / "golden_ride_segment.mp4"
    proc.run([binary, "-y", "-i", str(src),
              "-vf", "scale=in_range=auto:out_range=tv", "-color_range", "tv",
              "-c:v", "libx264", "-crf", "18", "-preset", "medium",
              "-pix_fmt", "yuv420p", "-an", str(out)])
    return out


@pytest.fixture
def extract_unnormalized():
    """extract.extract's command as it stood BEFORE the range normalization.

    A deliberate duplicate of production argv, and the only kind this repo
    allows, because it is the CONTROL: without it the byte-identity proofs would
    assert that two runs of the same command agree, which proves nothing, and the
    transfer-error proof would have no broken path to compare against.

    Do not "DRY" this against extract.extract. The day it tracks the production
    command is the day every proof built on it stops discriminating.
    """
    def _run(src, start, dur, out):
        proc.run([ffbin.ffmpeg(), "-y", "-i", str(src), "-ss", f"{start}", "-t", f"{dur}",
                  "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)])
        return out
    return _run


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
