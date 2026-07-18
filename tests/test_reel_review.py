import pytest

from scripts.lib.review import Review
from scripts.reel_review import build_review, write_review

RAW = [
    {"axis": "hook", "severity": "important", "evidence": "ep0 is a slow pan",
     "route": "edit-plan", "suggestion": "open on the jump-cut in ep2"},
    {"axis": "mood", "severity": "minor", "evidence": "track brighter than SPEC.mood",
     "route": "music", "suggestion": "pick a warmer cue", "confidence": "medium"},
]


def test_build_review_validates_and_sets_verdict():
    r = build_review(RAW, "out/REEL_v1.mp4", summary="delivers the calm idea")
    assert isinstance(r, Review) and r.verdict == "approve"   # no blocking finding
    assert len(r.findings) == 2 and r.findings[0].axis == "hook"
    assert r.summary == "delivers the calm idea"


def test_build_review_blocking_gives_revise():
    raw = [{"axis": "idea", "severity": "blocking", "evidence": "reel is a different story",
            "route": "edit-plan", "suggestion": "reselect windows to the SPEC idea"}]
    assert build_review(raw, "out/REEL_v1.mp4").verdict == "revise"


def test_build_review_rejects_bad_finding_writes_nothing():
    bad = [{"axis": "bogus", "severity": "minor", "evidence": "x", "route": "none", "suggestion": "y"}]
    with pytest.raises(ValueError, match="axis"):
        build_review(bad, "out/REEL_v1.mp4")


def test_build_review_rejects_non_list_findings():
    with pytest.raises(ValueError, match="list"):
        build_review({"axis": "hook"}, "out/REEL_v1.mp4")


def test_build_review_empty_findings_approves():
    r = build_review([], "out/REEL_v1.mp4")
    assert r.verdict == "approve" and r.findings == ()


def test_write_review_emits_both_files(tmp_path):
    r = build_review(RAW, "out/REEL_v1.mp4", platform="tiktok")
    res = write_review(r, str(tmp_path))
    assert res["status"] == "written" and res["verdict"] == "approve" and res["findings"] == 2
    assert (tmp_path / "REVIEW.json").exists() and (tmp_path / "REVIEW.md").exists()
    assert Review.from_json(tmp_path / "REVIEW.json").to_dict() == r.to_dict()
    assert (tmp_path / "REVIEW.md").read_text().startswith("# Reel review —")


import json
import sys


def _write_findings(tmp_path, obj):
    p = tmp_path / "review_findings.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_cli_build_writes_and_exits_0(tmp_path, monkeypatch, capsys):
    from scripts import reel_review
    findings = _write_findings(tmp_path, {"summary": "good", "findings": RAW})
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", findings,
                         "--reel", "out/REEL_v1.mp4", "--platform", "tiktok",
                         "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written" and payload["findings"] == 2
    r = Review.from_json(tmp_path / "REVIEW.json")
    assert r.verdict == "approve" and r.summary == "good" and r.platform == "tiktok"


def test_cli_accepts_bare_list_findings(tmp_path, monkeypatch, capsys):
    from scripts import reel_review
    findings = _write_findings(tmp_path, RAW)   # bare list, no summary object
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", findings,
                         "--reel", "out/REEL_v1.mp4", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    assert Review.from_json(tmp_path / "REVIEW.json").summary == ""


def test_cli_bad_findings_json_fails_loud(tmp_path, monkeypatch):
    from scripts import reel_review
    p = tmp_path / "review_findings.json"
    p.write_text("{not json")
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", str(p),
                         "--reel", "out/REEL_v1.mp4", "--out-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="valid JSON"):
        reel_review.main()
