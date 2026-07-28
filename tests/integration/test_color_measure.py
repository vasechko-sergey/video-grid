import pytest
from scripts.color_measure import measure_profile
from scripts.lib import ffbin, proc

pytestmark = pytest.mark.integration


def _flat_gray(path, level):
    # a 2s flat-gray clip at a known luma level (0-255)
    hexv = f"0x{level:02x}{level:02x}{level:02x}"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c={hexv}:s=320x240:d=2:r=25",
              "-frames:v", "50", "-pix_fmt", "yuv420p", str(path)])


def test_measure_profile_flat_gray(tmp_path):
    clip = tmp_path / "gray.mp4"
    _flat_gray(clip, 120)
    p5, p50, p95 = measure_profile(str(clip))
    # a flat field → all three percentiles near the known level (allow codec/round slop)
    assert abs(p50 - 120) <= 8 and abs(p5 - 120) <= 12 and abs(p95 - 120) <= 12


def test_measure_profile_two_bands(tmp_path):
    # left dark, right bright → p5 low, p95 high, p50 between
    clip = tmp_path / "bands.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", "color=c=0x202020:s=160x240:d=2:r=25",
              "-f", "lavfi", "-i", "color=c=0xE0E0E0:s=160x240:d=2:r=25",
              "-filter_complex", "[0][1]hstack", "-frames:v", "50", "-pix_fmt", "yuv420p", str(clip)])
    p5, p50, p95 = measure_profile(str(clip))
    assert p5 < 80 and p95 > 180 and p5 < p50 < p95
