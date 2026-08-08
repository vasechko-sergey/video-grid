"""The QC gate against real pixels (design docs/specs/2026-08-08-episode-qc-design.md §11).

Fixtures prove the contract; this proves the GATE: a reel that is not fully judged, is
judged stale, or carries a blocking verdict does not get assembled — and a clean one
delivers with the QC state on its attestation."""
import json
from pathlib import Path

import pytest

from scripts import edl_to_reel, episode_qc, reframe
from scripts.lib import provenance
from scripts.lib.models import Delivery, LayoutSpec, ReframeSpec, ReelEpisode, ReelManifest


def _episode(sample_clip, tmp, x_const, name):
    """A real reframed episode with its sidecars named the way process_episode names
    them, so ReelEpisode.path/meta are coherent and pack can derive the scratch dir."""
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    (d / "route.json").write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    clip = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(sample_clip), str(d / "route.json"), clip, str(d / "path.json"))
    return ReelEpisode(manifest={"segment": str(sample_clip), "target_dur": 3.0,
                                 "composition": "center", "grid": "thirds"},
                       clip=clip, route=str(d / "route.json"),
                       path=str(d / "path.json"), meta=str(d / "path.meta.json"))


def _episodes_json(tmp_path, sample_clip):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    eps = [_episode(sample_clip, tmp_path, 645, "ep0"),
           _episode(sample_clip, tmp_path, 1045, "ep1")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, changelog="qc proof")
    p = out / "EPISODES.json"
    rm.write(p)
    return p, rm


def _judge(packets, i, severity=None):
    d = Path(packets) / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    fs = [] if severity is None else [
        {"axis": "hero", "severity": severity, "evidence": f"ep{i} follows a bystander",
         "route": "edit-plan", "suggestion": "pin the hero by cast name"}]
    (d / "findings.json").write_text(json.dumps(
        {"summary": f"ep{i}", "reviewer": "integration", "findings": fs}))


@pytest.mark.integration
def test_pack_gives_the_judge_pixels_and_numbers(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    res = episode_qc.pack(str(p), str(tmp_path / "qc"))
    assert res["episodes"] == 2
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert (tmp_path / "qc" / "ep0" / "strip.jpg").exists()
    assert ev["intent"]["composition"] == "center"
    assert ev["naturalness"]["stats"]["frames"] == episode_qc.SENSOR_FRAMES
    assert set(ev["naturalness"]["flags"]) == {"blown_highlights", "crushed_blacks",
                                               "colour_cast", "oversaturated", "flat"}
    assert ev["geometry"] is not None          # the path.meta sidecar reframe wrote


@pytest.mark.integration
def test_a_clean_run_delivers_and_the_attestation_names_the_judged_bytes(tmp_path, sample_clip):
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1, "minor")
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    att = json.loads(Path(str(provenance.attest_path(res["output"]))).read_text())
    assert att["episode_qc"]["state"] == "judged"
    assert att["episode_qc"]["judged"] == {
        "0": provenance.digest_file(rm.episodes[0].clip),
        "1": provenance.digest_file(rm.episodes[1].clip)}
    assert att["episode_qc"]["reprocessed_after"] == []


@pytest.mark.integration
def test_a_blocking_verdict_stops_the_reel_and_writes_nothing(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1, "blocking")
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-blocking"
    assert list(p.parent.glob("REEL_v*")) == []


@pytest.mark.integration
def test_a_re_rendered_episode_invalidates_its_verdict(tmp_path, sample_clip):
    """The digest binding is load-bearing, not decorative: judge, then rebuild ep0's
    bytes, and the verdict no longer describes the clip that would be assembled."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    Path(rm.episodes[0].clip).write_bytes(
        Path(rm.episodes[0].clip).read_bytes() + b"\x00")      # a different render
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-stale"
    assert "episode 0" in res["finding"]["problems"][0]


@pytest.mark.integration
def test_an_unjudged_reel_never_reaches_assembly(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-missing"
