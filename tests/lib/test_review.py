import pytest

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


def test_vocab_constants_are_the_allowed_sets():
    assert REVIEW_AXES == ("idea", "mood", "hook", "ending", "spine",
                           "edl_completeness", "trend_flavor")
    assert REVIEW_SEVERITY == ("blocking", "important", "minor")
    assert REVIEW_ROUTES == ("edit-plan", "pacing", "music", "reprocess", "titles", "none")
    assert REVIEW_CONFIDENCE == ("high", "medium", "low")
