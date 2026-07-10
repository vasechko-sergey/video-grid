"""Real-ffmpeg whole-slice proof: 2 distinct episodes (via the real reframe
encoder, the stage inside process-episode that writes the locked clip) →
assemble → check_reel → deliver. Design §7."""
import json
import pytest
from scripts import check_reel, deliver, reframe
from scripts.lib import assembly
from scripts.lib.models import (Delivery, LayoutSpec, ReframeSpec, ReelCheckSpec, REEL_H264)


def _episode(sample_clip, tmp, x_const, name):
    # center composition (no lateral requirement); a constant route x fixes a
    # static crop window. The moving box (white, src-x≈845 at clip t=1.5) lands at
    # a DIFFERENT in-frame position in ep0 vs ep1 → distinct phash (variety passes),
    # while both cut-boundary frames are pure grey → equal mean (color passes).
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"
    rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(sample_clip), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_backhalf_assembles_checks_and_delivers(tmp_path, sample_clip):
    # two crops that frame the moving box at different in-frame positions
    ep0 = _episode(sample_clip, tmp_path, 645, "ep0")    # box on the right of frame
    ep1 = _episode(sample_clip, tmp_path, 1045, "ep1")   # box on the left of frame
    dims = (assembly.probe_stream(ep0).w, assembly.probe_stream(ep0).h)
    fps = assembly.probe_stream(ep0).fps

    master = str(tmp_path / "work" / "master.mp4")
    assembly.assemble([ep0, ep1], dims, fps, master)
    minfo = assembly.probe_stream(master)
    assert (minfo.w, minfo.h) == dims
    assert minfo.w % 2 == 0 and minfo.h % 2 == 0

    # target_dur from the EPISODES' own probed durations, NOT the master's own probe
    # (which would make length vacuously true). This makes `length` actually verify
    # assemble produced a master of the full summed duration — catching a dropped episode.
    target = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    spec = ReelCheckSpec(target_dur=target, variety_min=4)
    rep = check_reel.run(master, [ep0, ep1], spec, str(tmp_path / "reel.json"))
    assert rep.overall is True
    assert rep.checks["black"].passed is True
    assert rep.checks["length"].passed is True
    assert rep.checks["color_across_cuts"].passed is True
    assert rep.checks["variety"].passed is True
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None

    out_dir = str(tmp_path / "out")
    v1 = deliver.deliver(master, REEL_H264, out_dir, "golden first cut", rep)
    assert v1.endswith("REEL_v1.mp4")
    assert (assembly.probe_stream(v1).w, assembly.probe_stream(v1).h) == dims
    assert "- v1 |" in (tmp_path / "out" / "VERSIONS.md").read_text()

    v2 = deliver.deliver(master, REEL_H264, out_dir, "golden second cut", rep)
    assert v2.endswith("REEL_v2.mp4")
