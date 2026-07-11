"""Real-ffmpeg proof for the reel retry loop (design §6). (A) color_correct moves
real pixels toward the target; (B) build_reel wires probe → assemble → check_reel
→ deliver end-to-end on real files. Clips are built with the real reframe encoder,
matching test_reel_backhalf.py's precedent."""
import json
import pytest
from scripts import build_reel, check_reel, reframe
from scripts.lib import assembly, proc
from scripts.lib.models import (Delivery, LayoutSpec, ReframeSpec, ReelEpisode, ReelManifest)


def _tinted(sample_clip, tmp):
    """A warm copy of the grey sample clip — its red channel is boosted so its
    delivered mean sits off any neutral reference."""
    out = str(tmp / "warm.mp4")
    proc.run(["ffmpeg", "-y", "-i", str(sample_clip),
              "-vf", "colorchannelmixer=rr=1.4", "-pix_fmt", "yuv420p",
              "-c:v", "libx264", "-crf", "18", "-an", out])
    return out


def _reframe(src, tmp, x_const, name, color_correct=None):
    """Build a clip via the real reframe encoder with a constant-x crop route. A
    different x_const frames sample_clip's moving box at a different in-frame
    position → distinct phash, so two clips at 645 vs 1045 pass the variety check."""
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"; rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"), color_correct=color_correct)
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(src), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_color_correct_pulls_delivered_mean_toward_target(tmp_path, sample_clip):
    warm = _tinted(sample_clip, tmp_path)
    uncorrected = _reframe(warm, tmp_path, 900, "u")
    corrected = _reframe(warm, tmp_path, 900, "c", color_correct=(0.75, 1.0, 1.0))
    r_u = check_reel._frame_mean(uncorrected, 1.0)[0]
    r_c = check_reel._frame_mean(corrected, 1.0)[0]
    # rr=1.4 warms the grey source's red; the warm clip's delivered mean red measures
    # ~76 uncorrected and the 0.75 correction pulls it to ~57 — a ~19pt fall on real
    # pixels, so the 5-unit margin is generous, not tuned.
    assert r_c < r_u - 5          # the correction visibly lowered the red channel on real pixels


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
