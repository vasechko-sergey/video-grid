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


def _banded_episode(tmp_path, top=240, bottom=100):
    """(src, manifest_dict, route_json): a 640x1280 source stacking a bright
    band over a darker one, plus a minimal `fill` episode at a 1:1 canvas whose
    route sits in the bottom (darker) band.

    layout `fill` + crop_aspect "canvas" (fill's own default) + canvas [1, 1] crops
    the largest SQUARE that fits the 640x1280 source — 640x640 — and geometry.crop_y
    places it against the route's mean y. A route pinned at y=960 (the bottom
    band's own centre) lands the crop at y=640..1280 exactly: the top band is
    excluded, not merely down-weighted, which is what makes the two readings
    (whole frame vs. crop) disagree.

    Defaults (240/100) are the design's own dramatic case — the top band blown
    out, the bottom mid-grey. A caller can pass a smaller, realistic gap (e.g.
    top=120, bottom=100 — near the 14-unit median and 36-unit maximum the design
    measured against real footage) to prove the discrimination survives at
    production scale, not only at a 35x margin."""
    src = tmp_path / "banded.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c=0x{top:02x}{top:02x}{top:02x}:s=640x640:d=2:r=30",
              "-f", "lavfi", "-i", f"color=c=0x{bottom:02x}{bottom:02x}{bottom:02x}:s=640x640:d=2:r=30",
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
    through the render plan.

    Asserts the crop's exact value too (whole-object assert, docs/testing-guide.md):
    a bare `> MATCH_EPS` diff alone cannot tell "excludes the top band" from "reads
    the wrong band" — a sign flip in geometry.crop_y that read the TOP band instead
    would show the same ~140-unit difference and pass a diff-only assertion."""
    src, md, route = _banded_episode(tmp_path)                # helper below
    whole = color_measure.measure_profile(str(src), at=0.5)
    crop = color_measure.measure_crop(md, str(src), str(route))
    assert crop == pytest.approx((100.0, 100.0, 100.0))
    assert max(abs(a - b) for a, b in zip(whole, crop)) > matchgrade.MATCH_EPS


def test_crop_percentiles_discriminates_at_a_realistic_gap(tmp_path):
    """The design measured a 14-unit median and 36-unit maximum gap between the
    whole-frame and crop readings on real footage — a test that only passes at the
    240/100 fixture's 35x margin does not exercise the threshold that actually
    matters in production. 20 units, near that median, is not a margin any
    resampling or codec noise could manufacture by accident."""
    src, md, route = _banded_episode(tmp_path, top=120, bottom=100)
    whole = color_measure.measure_profile(str(src), at=0.5)
    crop = color_measure.measure_crop(md, str(src), str(route))
    assert crop == pytest.approx((100.0, 100.0, 100.0))
    assert max(abs(a - b) for a, b in zip(whole, crop)) > matchgrade.MATCH_EPS


def _pan_episode(tmp_path, left=40, right=220):
    """(src, manifest_dict): a 640x360 (16:9) source split left/right, cropped by a
    9:16 `fill` layout — crop_w = 360*9/16 = 202 against a 640-wide source, so
    freedom (640-202=438px) exists for generate_pan_path to travel across (design
    2026-07-19 §4). `pan` replaces the route: reframe.plan_render's pan branch
    GENERATES the path and never reads route_path (design §2.1)."""
    src = tmp_path / "pan_src.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c=0x{left:02x}{left:02x}{left:02x}:s=320x360:d=2:r=30",
              "-f", "lavfi", "-i", f"color=c=0x{right:02x}{right:02x}{right:02x}:s=320x360:d=2:r=30",
              "-filter_complex", "hstack=inputs=2", "-frames:v", "60",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(src)])
    md = {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
          "grid": "thirds", "canvas": [9, 16], "target_dur": 2.0,
          "pan": {"from": 0.0, "to": 1.0}}
    return str(src), md


def test_measure_crop_works_on_a_pan_episode(tmp_path):
    """A pan episode's route is legitimately None (design 2026-07-19): reframe.
    plan_render GENERATES the crop path instead of reading one. match_grade's
    conductor measures every EDL episode's crop, so a pan riding the reel must
    not crash the whole stage — nothing exercised measure_crop(route=None) before
    this (design 2026-08-30 task 4).

    The two bands are far enough apart (40 vs 220) that a crop sweeping across
    the boundary over the clip's 2s reads BOTH — proof this went through the
    generated pan path and actually sampled moving content, not a frozen crop
    that happened not to crash."""
    src, md = _pan_episode(tmp_path)
    p5, p50, p95 = color_measure.measure_crop(md, src, None)
    assert p5 < 100 and p95 > 160, f"expected the pan to cross both bands, got {(p5, p50, p95)}"


def test_percentiles_from_gray_refuses_a_short_buffer_the_old_check_missed():
    """60x60 makes w*h (3600) divisible by 3, so the OLD `len(raw) % want` guard
    would have silently accepted two frames' worth of bytes while three were
    asked for — exactly the failure mode production frame sizes (1920x1080,
    1080x1920: frame_bytes % 3 == 0 for both) hit for want=3. The new guard checks
    the byte count against want*w*h exactly, so a short buffer is caught here
    regardless of whether it happens to be divisible by the frame count."""
    raw = bytes(60 * 60 * 2)          # two frames' worth, not the three asked for
    with pytest.raises(RuntimeError, match="asked for 3"):
        color_measure._percentiles_from_gray(raw, 3, 60, 60, "test")


def test_sample_times_never_touches_the_ends():
    assert color_measure.sample_times(3.0, 3) == [0.5, 1.5, 2.5]
    assert color_measure.sample_times(1.0, 1) == [0.5]
