import pytest

from scripts.lib.catalog import Candidate, SOURCES


def test_candidate_roundtrip_and_slug():
    c = Candidate(title="Blinding Lights", artist="The Weeknd", source="youtube",
                  ref="https://y/abc", license="unknown (any lane)", preview_url=None)
    assert c.to_dict()["title"] == "Blinding Lights"
    assert Candidate.from_dict(c.to_dict()) == c
    assert c.slug() == "youtube-the-weeknd-blinding-lights"


def test_candidate_rejects_empty_field():
    with pytest.raises(ValueError, match=r"Candidate.title.*non-empty"):
        Candidate(title="", artist="a", source="youtube", ref="r", license="l", preview_url=None)


def test_candidate_rejects_unknown_source():
    with pytest.raises(ValueError, match=r"source.*not in"):
        Candidate(title="t", artist="a", source="soundcloud", ref="r", license="l", preview_url=None)


def test_candidate_preview_url_optional_but_nonempty_when_present():
    assert Candidate("t", "a", "itunes", "r", "l", "http://p").preview_url == "http://p"
    with pytest.raises(ValueError, match="preview_url"):
        Candidate("t", "a", "itunes", "r", "l", "   ")


def test_sources_are_the_five_lanes():
    assert SOURCES == ("jamendo", "ccmixter", "youtube", "itunes", "deezer")
