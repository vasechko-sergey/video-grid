import pytest

from scripts.lib import review
from scripts.lib.episode_qc import QC_AXES
from scripts.lib.review import (REVIEW_AXES, REVIEW_CONFIDENCE, REVIEW_ROUTES,
                                REVIEW_SEVERITY, Finding)

GOOD = dict(axis="hook", severity="important", evidence="ep0 opens on a slow pan",
            route="edit-plan", suggestion="open on the jump-cut instead")


def test_finding_accepts_good():
    f = Finding(**GOOD)
    assert f.axis == "hook" and f.severity == "important" and f.confidence == "high"


def test_finding_rejects_bad_axis():
    with pytest.raises(ValueError, match="axis"):
        Finding(**{**GOOD, "axis": "vibe"})


def test_finding_rejects_bad_severity():
    with pytest.raises(ValueError, match="severity"):
        Finding(**{**GOOD, "severity": "critical"})


def test_finding_rejects_empty_evidence():
    with pytest.raises(ValueError, match="evidence"):
        Finding(**{**GOOD, "evidence": "  "})


def test_finding_rejects_bad_route():
    with pytest.raises(ValueError, match="route"):
        Finding(**{**GOOD, "route": "rerender"})


def test_finding_rejects_empty_suggestion():
    with pytest.raises(ValueError, match="suggestion"):
        Finding(**{**GOOD, "suggestion": ""})


def test_finding_rejects_bad_confidence():
    with pytest.raises(ValueError, match="confidence"):
        Finding(**{**GOOD, "confidence": "sure"})


def test_finding_from_dict_non_dict_raises_clean():
    with pytest.raises(ValueError, match="Finding.from_dict"):
        Finding.from_dict(["not", "a", "dict"])


def test_finding_from_dict_missing_required_raises():
    with pytest.raises(ValueError, match="axis"):
        Finding.from_dict({"severity": "minor", "evidence": "x", "route": "none", "suggestion": "y"})


def test_finding_roundtrip_to_from_dict():
    f = Finding(**{**GOOD, "confidence": "low"})
    assert Finding.from_dict(f.to_dict()).to_dict() == f.to_dict()


def test_a_colour_finding_routed_to_match_grade_round_trips():
    """Reel-level colour agreement is no longer measured by a machine (design §4-§5):
    a whole-frame mean cannot separate 'different shot' from 'different grade', but a
    reader looking at the per-episode stills the packet already carries can. The axis
    is spelled as episode_qc.QC_AXES spells it."""
    f = review.Finding(axis="colour", severity="important",
                       evidence="ep3's mid still reads markedly bluer than ep2's and ep4's",
                       route="match-grade",
                       suggestion="re-run match-grade so every episode takes one common target",
                       confidence="medium")
    assert review.Finding.from_dict(f.to_dict()) == f


def test_the_american_spelling_is_not_an_axis():
    """Guards against the American spelling ever being ACCEPTED as a second axis
    value alongside 'colour'. This does NOT by itself confirm REVIEW_AXES spells
    the axis the same way episode_qc.QC_AXES does — it would pass identically even
    if 'colour' were never added to REVIEW_AXES at all, because Finding.__post_init__
    validates axis before route and 'color' was never a valid axis either way. That
    cross-check is test_colour_axis_spelling_matches_episode_qc below."""
    with pytest.raises(ValueError, match="not in"):
        review.Finding(axis="color", severity="minor", evidence="e",
                       route="match-grade", suggestion="s")


def test_colour_axis_spelling_matches_episode_qc():
    """The cross-check the test above does not perform: REVIEW_AXES and
    episode_qc.QC_AXES must agree on ONE spelling of the colour axis, or a finding
    routed between reel-review and episode-qc silently splits into two axes
    nobody aggregates."""
    assert "colour" in REVIEW_AXES and "colour" in QC_AXES
    assert "color" not in REVIEW_AXES and "color" not in QC_AXES


def test_vocab_constants_are_the_allowed_sets():
    assert REVIEW_AXES == ("idea", "mood", "hook", "ending", "spine",
                           "edl_completeness", "trend_flavor", "colour")
    assert REVIEW_SEVERITY == ("blocking", "important", "minor")
    assert REVIEW_ROUTES == ("edit-plan", "pacing", "music", "reprocess", "titles",
                             "match-grade", "none")
    assert REVIEW_CONFIDENCE == ("high", "medium", "low")


from scripts.lib.review import Review

F_IMPORTANT = Finding(**GOOD)
F_BLOCKING = Finding(axis="idea", severity="blocking", evidence="reel tells a different story",
                     route="edit-plan", suggestion="reselect windows to the SPEC idea")


def test_review_accepts_good_and_defaults():
    r = Review(reel="out/REEL_v1.mp4", findings=[F_IMPORTANT])
    assert r.reel == "out/REEL_v1.mp4" and r.findings == (F_IMPORTANT,)
    assert r.summary == "" and r.platform == "" and r.spec_ref == "" and r.reviewer == ""


def test_review_rejects_empty_reel():
    with pytest.raises(ValueError, match="reel"):
        Review(reel="  ", findings=[F_IMPORTANT])


def test_review_rejects_raw_dict_finding():
    with pytest.raises(ValueError, match="findings"):
        Review(reel="out/REEL_v1.mp4", findings=[{"axis": "hook"}])


def test_verdict_approve_without_blocking():
    assert Review(reel="r.mp4", findings=[F_IMPORTANT]).verdict == "approve"


def test_verdict_revise_with_blocking():
    assert Review(reel="r.mp4", findings=[F_IMPORTANT, F_BLOCKING]).verdict == "revise"


def test_verdict_approve_when_empty():
    assert Review(reel="r.mp4").verdict == "approve"


def test_review_roundtrip_recomputes_verdict():
    r = Review(reel="out/REEL_v1.mp4", findings=[F_BLOCKING], summary="s", platform="tiktok")
    d = r.to_dict()
    assert d["verdict"] == "revise"
    d["verdict"] = "approve"                      # a lying stored verdict is ignored on load
    assert Review.from_dict(d).verdict == "revise"
    assert Review.from_dict(r.to_dict()).to_dict() == r.to_dict()


def test_review_from_json_corrupt_raises(tmp_path):
    p = tmp_path / "REVIEW.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="corrupt"):
        Review.from_json(p)


def test_review_write_then_from_json(tmp_path):
    r = Review(reel="out/REEL_v1.mp4", findings=[F_IMPORTANT], summary="ok")
    p = tmp_path / "REVIEW.json"
    r.write(p)
    assert Review.from_json(p).to_dict() == r.to_dict()


def test_to_markdown_approve_header_and_summary():
    r = Review(reel="out/REEL_v1.mp4", findings=[F_IMPORTANT], summary="delivers the calm idea",
               platform="tiktok")
    md = r.to_markdown()
    assert md.startswith("# Reel review — ✅ approve · tiktok")
    assert "delivers the calm idea" in md
    assert "**[important] hook** → `edit-plan`" in md
    assert "open on the jump-cut instead" in md


def test_to_markdown_revise_orders_blocking_first():
    r = Review(reel="r.mp4", findings=[F_IMPORTANT, F_BLOCKING])
    md = r.to_markdown()
    assert md.startswith("# Reel review — 🔧 revise")
    assert md.index("[blocking] idea") < md.index("[important] hook")   # severity order, not input order


def test_to_markdown_empty_findings_is_clean():
    md = Review(reel="r.mp4", summary="clean").to_markdown()
    assert "✅ No findings" in md
