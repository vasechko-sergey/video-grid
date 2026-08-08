"""The per-episode QC contract (design docs/specs/2026-08-08-episode-qc-design.md §4)."""
import json
import pytest

from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC, gate


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


def _verdict(idx, digest, severity=None):
    fs = () if severity is None else (EpisodeFinding.from_dict(_finding(severity=severity)),)
    return EpisodeVerdict(idx=idx, clip=f"ep{idx}.mp4", clip_digest=digest, findings=fs)


def test_a_fully_judged_reel_passes_the_gate():
    qc = ReelQC(episodes=(_verdict(0, "aa"), _verdict(1, "bb", "minor")))
    assert gate(qc, {0: "aa", 1: "bb"}) == (None, [])


def test_an_unjudged_episode_stops_the_reel():
    reason, problems = gate(ReelQC(episodes=(_verdict(0, "aa"),)), {0: "aa", 1: "bb"})
    assert reason == "episode-qc-incomplete"
    assert problems == ["episode 1 has no verdict"]


def test_a_verdict_for_an_episode_the_reel_does_not_have_stops_it():
    reason, problems = gate(ReelQC(episodes=(_verdict(0, "aa"), _verdict(4, "zz"))), {0: "aa"})
    assert reason == "episode-qc-incomplete"
    assert problems == ["verdict for episode 4, which this reel does not have"]


def test_a_moved_digest_stops_the_reel_before_any_blocking_finding():
    qc = ReelQC(episodes=(_verdict(0, "aa", "blocking"), _verdict(1, "OLD")))
    reason, problems = gate(qc, {0: "aa", 1: "NEW"})
    assert reason == "episode-qc-stale"          # staleness outranks the blocking finding
    assert problems == ["episode 1 was judged as OLD… but ep1.mp4 now hashes to NEW…"]


def test_a_blocking_finding_stops_the_reel():
    qc = ReelQC(episodes=(_verdict(0, "aa"), _verdict(1, "bb", "blocking")))
    reason, problems = gate(qc, {0: "aa", 1: "bb"})
    assert reason == "episode-qc-blocking"
    assert problems == ["episode 1: [blocking] composition — ep0 @1.2s, head clipped"]


def test_a_verdict_rejects_empty_clip_digest():
    with pytest.raises(ValueError, match="clip_digest"):
        EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="")


def test_a_verdict_rejects_none_clip_digest():
    with pytest.raises(ValueError, match="clip_digest"):
        EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest=None)


def test_a_verdict_from_dict_missing_clip_digest_is_refused():
    with pytest.raises(ValueError, match="clip_digest"):
        EpisodeVerdict.from_dict({"idx": 0, "clip": "ep0.mp4"})


def test_a_verdict_rejects_negative_idx():
    with pytest.raises(ValueError, match="idx"):
        EpisodeVerdict(idx=-1, clip="ep0.mp4", clip_digest="ab")


def test_a_verdict_rejects_bool_idx():
    # isinstance(True, int) is True in Python — without an explicit bool guard this
    # would silently pass as episode index 1.
    with pytest.raises(ValueError, match="idx"):
        EpisodeVerdict(idx=True, clip="ep0.mp4", clip_digest="ab")


def test_a_verdict_rejects_raw_dict_findings():
    with pytest.raises(ValueError, match="findings"):
        EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab",
                        findings=[{"axis": "composition"}])


def test_a_finding_from_dict_non_dict_raises_clean():
    with pytest.raises(ValueError, match="EpisodeFinding.from_dict"):
        EpisodeFinding.from_dict(["not", "a", "dict"])


def test_a_verdict_from_dict_non_dict_raises_clean():
    with pytest.raises(ValueError, match="EpisodeVerdict.from_dict"):
        EpisodeVerdict.from_dict(["not", "a", "dict"])


def test_reel_qc_from_dict_non_dict_raises_clean():
    with pytest.raises(ValueError, match="ReelQC.from_dict"):
        ReelQC.from_dict(["not", "a", "dict"])


def test_reel_qc_from_json_corrupt_raises(tmp_path):
    p = tmp_path / "EPISODE_QC.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="re-run episode_qc build"):
        ReelQC.from_json(p)
