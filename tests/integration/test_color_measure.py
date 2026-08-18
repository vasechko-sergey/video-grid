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


def test_measure_profile_three_bands(tmp_path):
    """dark | mid | bright at 1:2:1 → p5 low, p50 in the middle band, p95 high.

    THREE bands and not two, found when the 160-wide downscale came out on
    2026-08-19: a 50/50 two-band frame has p5 == p50 by construction, because half
    its pixels sit at the dark value. The old two-band version passed only on the
    downscale's own edge blur, which invented intermediate values at the boundary
    and pulled p50 off p5 — the assertion was reading the resampler, not the
    frame. Same 1:2:1 shape test_matchgrade.py's `_three_band` already uses, and
    for the same reason it documents."""
    clip = tmp_path / "bands.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", "color=c=0x202020:s=80x240:d=2:r=25",
              "-f", "lavfi", "-i", "color=c=0x808080:s=160x240:d=2:r=25",
              "-f", "lavfi", "-i", "color=c=0xE0E0E0:s=80x240:d=2:r=25",
              "-filter_complex", "hstack=inputs=3", "-frames:v", "50",
              "-pix_fmt", "yuv420p", str(clip)])
    p5, p50, p95 = measure_profile(str(clip))
    assert p5 < 80 and p95 > 180 and p5 < p50 < p95
