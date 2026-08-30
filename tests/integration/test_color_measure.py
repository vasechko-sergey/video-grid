import json

import pytest
from scripts import color_measure
from scripts.color_measure import measure_profile
from scripts.lib import ffbin, matchgrade, proc

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


def _two_band_clip(tmp_path, dark=40, bright=200):
    """640x640, 1s, 30fps: a dark band over a bright one, tv range — the shape
    clip_percentiles reads off a FINISHED file (no crop, no manifest)."""
    clip = tmp_path / "two_band.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c=0x{dark:02x}{dark:02x}{dark:02x}:s=640x320:d=1:r=30",
              "-f", "lavfi", "-i", f"color=c=0x{bright:02x}{bright:02x}{bright:02x}:s=640x320:d=1:r=30",
              "-filter_complex", "vstack=inputs=2", "-frames:v", "30",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(clip)])
    return clip


def _banded_episode(tmp_path):
    """(src, manifest_dict, route_json): a 640x1280 source stacking a blown-out
    band over a mid-grey one, plus a minimal `fill` episode at a 1:1 canvas whose
    route sits in the bottom (mid-grey) band.

    layout `fill` + crop_aspect "canvas" (fill's own default) + canvas [1, 1] crops
    the largest SQUARE that fits the 640x1280 source — 640x640 — and geometry.crop_y
    places it against the route's mean y. A route pinned at y=960 (the bottom
    band's own centre) lands the crop at y=640..1280 exactly: the top band is
    excluded, not merely down-weighted, which is what makes the two readings
    (whole frame vs. crop) disagree by more than a resampling nudge."""
    src = tmp_path / "banded.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", "color=c=0xF0F0F0:s=640x640:d=2:r=30",   # top: blown out
              "-f", "lavfi", "-i", "color=c=0x646464:s=640x640:d=2:r=30",   # bottom: mid-grey
              "-filter_complex", "vstack=inputs=2", "-frames:v", "60",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(src)])
    md = {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
          "grid": "thirds", "canvas": [1, 1], "target_dur": 2.0}
    route = [dict(t=0.0, x=320.0, y=960.0, w=100.0, h=100.0),
             dict(t=2.0, x=320.0, y=960.0, w=100.0, h=100.0)]
    route_path = tmp_path / "route.json"
    route_path.write_text(json.dumps(route))
    return str(src), md, str(route_path)


def test_clip_percentiles_reads_a_finished_file(tmp_path):
    """Two bands, 50/50: p5 lands in the dark one, p95 in the bright one."""
    clip = _two_band_clip(tmp_path, dark=40, bright=200)      # helper below
    p5, p50, p95 = color_measure.clip_percentiles(str(clip), [0.5])
    assert p5 < 60 and p95 > 180


def test_crop_percentiles_reads_the_crop_not_the_frame(tmp_path):
    """The design's §0.1 finding, as a test: a frame whose TOP half is blown out
    and whose bottom half is mid-grey reads very differently once the crop
    excludes the top. If these ever agree, the measuring path has stopped going
    through the render plan."""
    src, md, route = _banded_episode(tmp_path)                # helper below
    whole = color_measure.measure_profile(str(src), at=0.5)
    crop = color_measure.measure_crop(md, str(src), str(route))
    assert max(abs(a - b) for a, b in zip(whole, crop)) > matchgrade.MATCH_EPS


def test_sample_times_never_touches_the_ends():
    assert color_measure.sample_times(3.0, 3) == [0.5, 1.5, 2.5]
    assert color_measure.sample_times(1.0, 1) == [0.5]
