"""Real-ffmpeg proof for the reel retry loop (design §6): build_reel wires probe →
assemble → check_reel → deliver end-to-end on real files. Clips are built with the
real reframe encoder, matching test_reel_backhalf.py's precedent.

The colour half of this file is retired with the corrector it proved (design
2026-08-29). A reprocess-then-pass proof cannot honestly be rebuilt on the black arm:
a black hit that is IN the source survives a clean re-encode, so the loop would
exhaust rather than converge. The reprocess path keeps its unit coverage in
tests/lib/test_build_reel.py."""
import json

import pytest

from scripts import build_reel, check_reel, reframe
from scripts.lib import assembly
from scripts.lib.models import (Delivery, LayoutSpec, ReframeSpec, ReelEpisode, ReelManifest)


def _reframe(src, tmp, x_const, name):
    """Build a clip via the real reframe encoder with a constant-x crop route. A
    different x_const frames sample_clip's moving box at a different in-frame
    position → distinct phash, so two clips at 645 vs 1045 pass the variety check."""
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"; rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(src), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_build_reel_delivers_a_passing_reel(tmp_path, sample_clip):
    # two uniform clips off the same source → pass on the first assemble → deliver,
    # no reprocess (proves the driver's real probe/assemble/check/deliver wiring)
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    ep1 = _reframe(sample_clip, tmp_path, 1045, "ep1")
    target = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep0,
                              route=str(tmp_path / "ep0.route.json")),
                  ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep1,
                              route=str(tmp_path / "ep1.route.json"))],
        target_dur=target, variety_min=4, changelog="retry golden")
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["output"].endswith("REEL_v1.mp4")
    v1 = res["output"]
    assert (assembly.probe_stream(v1).w % 2 == 0) and (assembly.probe_stream(v1).h % 2 == 0)
    assert "- v1 |" in (tmp_path / "out" / "VERSIONS.md").read_text()


@pytest.mark.integration
def test_build_reel_absorbs_a_within_band_shortfall(tmp_path, sample_clip):
    # the reel is real; the TARGET is 0.7s optimistic — inside the 1.0s band, so the driver
    # re-times to the reel's real length and delivers instead of waking a human (design §3)
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    ep1 = _reframe(sample_clip, tmp_path, 1045, "ep1")
    real = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep0,
                              route=str(tmp_path / "ep0.route.json")),
                  ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep1,
                              route=str(tmp_path / "ep1.route.json"))],
        target_dur=real + 0.7, variety_min=4, changelog="retime golden")
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))

    assert res["status"] == "delivered"
    length = res["report"]["checks"]["length"]
    # CheckResult.to_dict() serializes passed under "pass" and flattens detail to the top
    # level (no nested "detail" key) — see scripts/lib/models.py CheckResult.to_dict(),
    # matching test_music_spine.py:74's identical ["checks"]["loudness"]["pass"] pattern.
    assert length["pass"] is True
    # the delivered report states the reel's REAL length as its target — re-checked, not patched
    assert abs(length["target"] - real) < 0.05


@pytest.mark.integration
def test_build_reel_escalates_a_shortfall_past_the_band(tmp_path, sample_clip):
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    real = check_reel._probe_dur(ep0)
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep0,
                              route=str(tmp_path / "ep0.route.json"))],
        target_dur=real + 3.0, variety_min=4, changelog="retime golden")
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))

    assert res["status"] == "stop_and_report"
    assert res["finding"]["check"] == "length" and res["finding"]["escalate_to"] == "pacing"
