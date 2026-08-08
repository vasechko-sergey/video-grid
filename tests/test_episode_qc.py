"""episode_qc driver — validation and stamping (design §6/§7)."""
import json
import pytest

from scripts import episode_qc
from scripts.lib import provenance
from scripts.lib.models import ReelEpisode, ReelManifest


def _rm(tmp_path, n=2):
    eps = []
    for i in range(n):
        clip = tmp_path / f"ep{i}.mp4"
        clip.write_bytes(f"clip-{i}".encode())
        eps.append(ReelEpisode(manifest={"segment": f"s{i}.mp4", "target_dur": 2.0},
                               clip=str(clip), route=None,
                               path=str(tmp_path / f"ep{i}" / "path.json"),
                               meta=str(tmp_path / f"ep{i}" / "path.meta.json")))
    return ReelManifest(episodes=eps, target_dur=4.0)


def _findings(packets, i, severity="minor"):
    d = packets / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps({
        "summary": f"ep{i} reads well", "reviewer": "test-judge",
        "findings": [{"axis": "colour", "severity": severity, "evidence": "warm cast",
                      "route": "match-grade", "suggestion": "cool it by 4 units"}]}))


def test_build_stamps_the_digest_itself_and_ignores_what_the_judge_claimed(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _findings(packets, 1)
    (packets / "ep0" / "findings.json").write_text(json.dumps({
        "clip_digest": "deadbeef", "findings": []}))          # the judge tries to set it
    res = episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    qc = json.loads((tmp_path / "EPISODE_QC.json").read_text())
    assert res["status"] == "written" and res["verdict"] == "approve"
    assert qc["episodes"][0]["clip_digest"] == provenance.digest_file(rm.episodes[0].clip)
    assert (tmp_path / "EPISODE_QC.md").exists()


def test_build_refuses_an_unjudged_episode(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    with pytest.raises(ValueError, match="episode 1 has no findings.json"):
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))


def test_build_reports_revise_when_a_finding_blocks(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _findings(packets, 1, severity="blocking")
    res = episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    assert res["verdict"] == "revise" and res["blocking"] == 1


def test_pack_refuses_an_episode_with_no_sidecar_path(tmp_path):
    rm = ReelManifest(episodes=[ReelEpisode(manifest={"segment": "s.mp4"},
                                            clip=str(tmp_path / "ep0.mp4"))],
                      target_dur=2.0)
    (tmp_path / "ep0.mp4").write_bytes(b"x")
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    with pytest.raises(ValueError, match="no path sidecar"):
        episode_qc.pack(str(ep_path), str(tmp_path / "qc"))


def _episode_with_scratch(tmp_path):
    d = tmp_path / "ep0"
    d.mkdir()
    ep = ReelEpisode(manifest={"segment": "s.mp4"}, clip=str(tmp_path / "ep0.mp4"),
                     path=str(d / "path.json"), meta=str(d / "path.meta.json"))
    return ep, d


def test_evidence_reports_a_missing_storyboard_as_none(tmp_path):
    # The storyboard is the evidence the `hero` axis stands on (design §6) — a judge
    # must be able to tell "there was no storyboard" from "there was one", the same
    # distinction _evidence already draws for report.json/route.meta.json/path.meta.json.
    ep, _ = _episode_with_scratch(tmp_path)
    ev = episode_qc._evidence(ep, 0, {"stats": {}, "flags": {}})
    assert ev["storyboard"] is None
    assert ev["checks"] is None and ev["track"] is None and ev["geometry"] is None


def test_evidence_reports_an_existing_storyboard_path(tmp_path):
    ep, d = _episode_with_scratch(tmp_path)
    (d / "storyboard.jpg").write_bytes(b"x")
    ev = episode_qc._evidence(ep, 0, {"stats": {}, "flags": {}})
    assert ev["storyboard"] == str(d / "storyboard.jpg")
