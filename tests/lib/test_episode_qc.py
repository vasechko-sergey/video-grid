"""The per-episode QC contract (design docs/specs/2026-08-08-episode-qc-design.md §4)."""
import json
import pytest

from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC


def _finding(**over) -> dict:
    d = {"axis": "composition", "severity": "important", "evidence": "ep0 @1.2s, head clipped",
         "route": "reprocess", "suggestion": "raise the crop by 6% of frame height"}
    d.update(over)
    return d


def test_a_finding_round_trips():
    f = EpisodeFinding.from_dict(_finding())
    assert f.to_dict() == {**_finding(), "confidence": "high"}


@pytest.mark.parametrize("bad, msg", [
    ({"axis": "vibes"}, "axis"),
    ({"severity": "fatal"}, "severity"),
    ({"route": "re-shoot"}, "route"),
    ({"evidence": "  "}, "evidence"),
    ({"suggestion": ""}, "suggestion"),
    ({"confidence": "certain"}, "confidence"),
])
def test_a_malformed_finding_is_refused(bad, msg):
    with pytest.raises(ValueError, match=msg):
        EpisodeFinding.from_dict(_finding(**bad))


def test_a_verdict_is_revise_iff_something_blocks():
    ok = EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab", findings=(
        EpisodeFinding.from_dict(_finding(severity="minor")),))
    bad = EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab", findings=(
        EpisodeFinding.from_dict(_finding(severity="blocking")),))
    assert ok.verdict == "approve"
    assert bad.verdict == "revise"


def test_a_stored_verdict_cannot_lie_about_itself(tmp_path):
    p = tmp_path / "EPISODE_QC.json"
    p.write_text(json.dumps({"episodes": [
        {"idx": 0, "clip": "ep0.mp4", "clip_digest": "ab", "verdict": "approve",
         "findings": [_finding(severity="blocking")]}]}))
    assert ReelQC.from_json(p).episodes[0].verdict == "revise"   # recomputed, never read


def test_reel_qc_round_trips_and_renders(tmp_path):
    qc = ReelQC(episodes=(
        EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab", summary="reads well"),
        EpisodeVerdict(idx=1, clip="ep1.mp4", clip_digest="cd", findings=(
            EpisodeFinding.from_dict(_finding(axis="hero", severity="blocking",
                                              route="edit-plan")),))))
    p = tmp_path / "EPISODE_QC.json"
    qc.write(p)
    back = ReelQC.from_json(p)
    assert back.to_dict() == qc.to_dict()
    assert back.ok is False
    md = back.to_markdown()
    assert "ep1" in md and "hero" in md and "blocking" in md


def test_duplicate_indices_are_refused():
    with pytest.raises(ValueError, match="twice"):
        ReelQC(episodes=(EpisodeVerdict(idx=0, clip="a.mp4", clip_digest="ab"),
                         EpisodeVerdict(idx=0, clip="b.mp4", clip_digest="cd")))
