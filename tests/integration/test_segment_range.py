"""End-to-end proofs for the segment format contract (design 2026-08-27).

Each carries its own control. The central claim — that normalizing the range at
extract fixes the grade — is only a claim if the un-normalized path is shown to
break on the same bytes, so every proof here builds both paths.
"""
import numpy as np
import pytest

from scripts import extract, reframe
from scripts.lib import assembly, color, ffbin, proc
from scripts.lib.models import Delivery, PanSpec, ReframeSpec

pytestmark = pytest.mark.integration

W, H = 640, 360                 # pc_ramp_clip's dimensions
DST = (40.0, 120.0, 200.0)      # a plausible common target for that ramp


def _profile(clip, vf=None):
    """(p5, p50, p95) exactly the way measure_profile reads them: `format=gray`,
    which honours the source's range tag and converts."""
    chain = f"{vf},format=gray" if vf else "format=gray"
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(clip), "-ss", "0.500",
                    "-frames:v", "1", "-vf", chain,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    a = np.frombuffer(raw[:W * H], dtype=np.uint8)
    return tuple(round(float(np.percentile(a, q)), 1) for q in (5, 50, 95))


def _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path):
    old = extract_unnormalized(pc_ramp_clip, 0.2, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(pc_ramp_clip), start=0.2, dur=1.0, out=str(new))
    return old, new


def test_normalizing_the_range_lands_the_grade_on_its_target(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """The slice's central claim, with its own control.

    Measured 2026-08-27 on this fixture: the un-normalized path misses by
    (-38.1, 0.0, -9.0) and the normalized one by (-2.1, -0.5, -1.0). The bars
    below sit far from both, so an encoder nudge cannot flip the verdict.
    """
    old, new = _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path)
    errs = {}
    for name, seg in (("old", old), ("new", new)):
        src = _profile(seg)
        got = _profile(seg, color.tone_arg(src, DST).rstrip(","))
        errs[name] = [g - d for g, d in zip(got, DST)]

    assert max(abs(e) for e in errs["old"]) > 20.0, errs      # the defect reproduces
    assert max(abs(e) for e in errs["new"]) <= 5.0, errs      # and the fix closes it
    assert max(abs(e) for e in errs["new"]) < max(abs(e) for e in errs["old"]) / 4


def test_normalizing_does_not_move_the_profile_the_grade_is_measured_from(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """match_grade measures the RAW source and reframe grades the SEGMENT. That
    only works because `format=gray` reports the same profile either side of the
    normalization — measured (51, 113, 194) both ways on the real Canon frame.
    Load-bearing, so pinned rather than left to luck."""
    old, new = _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path)
    for a, b in zip(_profile(old), _profile(new)):
        assert abs(a - b) <= 1.0, (_profile(old), _profile(new))


def test_a_normalized_segment_no_longer_reads_as_a_concat_outlier(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """The quiet win: a full-range file reads as a concat outlier and gets
    re-encoded whole, and a normalized one does not — a full extra generation
    saved for two thirds of the pool.

    Honest about what it measures (final review, 2026-08-27): these are SEGMENTS,
    and `assemble` receives EPISODES. The consequence for episodes is real — a
    reframe-shaped chain over pc footage emits `yuvj420p`/pc, and over a
    normalized segment emits `yuv420p`/tv — but this test does not establish that
    step; it establishes that `matches` separates the two range tags."""
    old, new = _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path)
    assert not assembly.matches(assembly.probe_stream(str(old)), (W, H), 30.0)
    assert assembly.matches(assembly.probe_stream(str(new)), (W, H), 30.0)


def test_the_guard_stops_raw_footage_and_passes_an_extracted_segment(
        pc_ramp_clip, tenbit_clip, tmp_path):
    """plan_render over REAL files — no stubbed probe anywhere, which is the only
    way to prove _probe actually reports the two fields the guard reads."""
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(110.0, 120.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:180"),
                       pan=PanSpec(start=0.0, end=0.2))
    with pytest.raises(ValueError, match="pc"):
        reframe.plan_render(spec, str(pc_ramp_clip), None)
    with pytest.raises(ValueError, match="10 bits"):
        reframe.plan_render(spec, str(tenbit_clip), None)

    seg = tmp_path / "seg.mp4"
    extract.extract(src=str(pc_ramp_clip), start=0.2, dur=1.0, out=str(seg))
    assert reframe.plan_render(spec, str(seg), None).fps == pytest.approx(30.0)
