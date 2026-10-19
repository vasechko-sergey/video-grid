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


from scripts.lib import catalog


def test_free_source_is_ccmixter_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    monkeypatch.setattr(catalog, "_SOURCING_ENV", tmp_path / "sourcing.env")  # absent
    assert catalog._free_source() == "ccmixter"


def test_free_source_is_jamendo_with_env_key(monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "abc123")
    assert catalog._free_source() == "jamendo"


def test_free_source_reads_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    env = tmp_path / "sourcing.env"
    env.write_text("JAMENDO_CLIENT_ID=fromfile\n")
    monkeypatch.setattr(catalog, "_SOURCING_ENV", env)
    assert catalog._jamendo_client_id() == "fromfile"
    assert catalog._free_source() == "jamendo"


def test_ytdlp_cmd_raises_when_absent(monkeypatch):
    monkeypatch.setattr(catalog, "has_ytdlp", lambda: False)
    with pytest.raises(ValueError, match="setup.sh --with-sourcing"):
        catalog.ytdlp_cmd()


# append to tests/lib/test_catalog.py
import json as _json


class _FakeResp:
    def __init__(self, body): self._body = body.encode()
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _mock_urlopen(monkeypatch, body):
    monkeypatch.setattr(catalog.urllib.request, "urlopen",
                        lambda req, timeout=0, context=None: _FakeResp(_json.dumps(body)))


def test_search_itunes_parses(monkeypatch):
    _mock_urlopen(monkeypatch, {"results": [
        {"trackName": "Sun", "artistName": "Nova", "previewUrl": "http://p/1",
         "trackViewUrl": "http://itunes/1"}]})
    cands = catalog._search_itunes("energetic", 5)
    assert cands[0].source == "itunes" and cands[0].title == "Sun"
    assert cands[0].ref == "Nova - Sun" and cands[0].preview_url == "http://p/1"


def test_search_deezer_parses(monkeypatch):
    _mock_urlopen(monkeypatch, {"data": [
        {"title": "Rain", "artist": {"name": "Cloud"}, "preview": "http://p/2"}]})
    cands = catalog._search_deezer("chill", 5)
    assert cands[0].source == "deezer" and cands[0].ref == "Cloud - Rain"


def test_search_itunes_skips_incomplete_rows(monkeypatch):
    _mock_urlopen(monkeypatch, {"results": [{"trackName": "NoArtist"}]})
    assert catalog._search_itunes("x", 5) == []


# append to tests/lib/test_catalog.py
def test_search_jamendo_parses_and_needs_key(monkeypatch):
    monkeypatch.setattr(catalog, "_jamendo_client_id", lambda: None)
    with pytest.raises(ValueError, match="Jamendo client_id"):
        catalog._search_jamendo("epic", 5)
    monkeypatch.setattr(catalog, "_jamendo_client_id", lambda: "cid")
    _mock_urlopen(monkeypatch, {"results": [
        {"name": "Rise", "artist_name": "Aurora", "audio": "http://a/s",
         "audiodownload": "http://a/dl", "license_ccurl": "http://cc/by"}]})
    cands = catalog._search_jamendo("epic", 5)
    assert cands[0].source == "jamendo" and cands[0].ref == "http://a/dl"
    assert cands[0].license == "http://cc/by" and cands[0].preview_url == "http://a/s"


def test_search_ccmixter_parses_list(monkeypatch):
    _mock_urlopen(monkeypatch, [
        {"upload_name": "Groove", "user_name": "dj", "license_name": "CC BY",
         "files": [{"download_url": "http://c/dl"}]}])
    cands = catalog._search_ccmixter("funk", 5)
    assert cands[0].source == "ccmixter" and cands[0].ref == "http://c/dl"
    assert cands[0].license == "CC BY"


# append to tests/lib/test_catalog.py
import subprocess as _sp


def _mock_ytdlp(monkeypatch, stdout, rc=0):
    monkeypatch.setattr(catalog, "has_ytdlp", lambda: True)
    monkeypatch.setattr(catalog, "ytdlp_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(catalog.subprocess, "run",
                        lambda *a, **k: _sp.CompletedProcess(a, rc, stdout, ""))


def test_search_youtube_parses_flat_json(monkeypatch):
    _mock_ytdlp(monkeypatch, '{"title": "Hype", "url": "vid1", "channel": "Ch"}\n')
    cands = catalog._search_youtube("hype", 3)
    assert cands[0].source == "youtube" and cands[0].ref == "vid1"
    assert cands[0].preview_url is None and cands[0].license == "unknown (any lane)"


def test_search_free_never_returns_youtube(monkeypatch):
    monkeypatch.setattr(catalog, "_free_source", lambda: "ccmixter")
    _mock_urlopen(monkeypatch, [{"upload_name": "G", "user_name": "u",
                                 "files": [{"download_url": "http://c/dl"}]}])
    cands = catalog.search("free", "funk", 3)
    assert all(c.source != "youtube" for c in cands)   # rights invariant


def test_search_free_rejects_catalog_arg(monkeypatch):
    with pytest.raises(ValueError, match="any-lane"):
        catalog.search("free", "funk", 3, catalog="itunes")


def test_search_any_defaults_to_youtube(monkeypatch):
    _mock_ytdlp(monkeypatch, '{"title": "T", "url": "v", "channel": "C"}\n')
    assert catalog.search("any", "x", 1)[0].source == "youtube"


def test_search_any_catalog_itunes(monkeypatch):
    _mock_urlopen(monkeypatch, {"results": [{"trackName": "S", "artistName": "A"}]})
    assert catalog.search("any", "x", 1, catalog="itunes")[0].source == "itunes"


def test_search_rejects_local_mode(monkeypatch):
    with pytest.raises(ValueError, match="local is the music-match lane"):
        catalog.search("local", "x", 1)


def test_search_zero_candidates_raises(monkeypatch):
    _mock_ytdlp(monkeypatch, "")
    with pytest.raises(ValueError, match="no candidates"):
        catalog.search("any", "zzz", 3)


# append to tests/lib/test_catalog.py
def test_preview_clip_http_when_preview_url(tmp_path, monkeypatch):
    c = Candidate("t", "a", "itunes", "a - t", "unknown (any lane)", "http://p/x.mp3")
    monkeypatch.setattr(catalog, "http_download",
                        lambda url, dest: dest.write_bytes(b"AUDIO"))
    path = catalog.preview_clip(c, str(tmp_path))
    assert path.endswith(".preview.mp3") and open(path, "rb").read() == b"AUDIO"


def test_preview_clip_ytdlp_section_when_no_preview(tmp_path, monkeypatch):
    c = Candidate("t", "a", "youtube", "vid", "unknown (any lane)", None)
    monkeypatch.setattr(catalog, "has_ytdlp", lambda: True)
    monkeypatch.setattr(catalog, "ytdlp_cmd", lambda: ["yt-dlp"])
    def fake_run(cmd, **k):
        (tmp_path / f"{c.slug()}.preview.m4a").write_bytes(b"YT")
        return _sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(catalog.subprocess, "run", fake_run)
    path = catalog.preview_clip(c, str(tmp_path))
    assert path.endswith(".preview.m4a")


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_candidate_from_dict_rejects_a_non_object_top_level(d, name):
    # `k not in d` raised a bare TypeError ("argument of type 'int' is not iterable") on a
    # scalar top level, and mis-reported a list/str one as "missing key(s)". No production
    # reader today (music_find writes candidates via to_dict, nobody reads them back through
    # from_dict), but from_dict is public contract surface and owes one documented type per
    # coding-standards: ValueError-with-remedy for wrong-type construction.
    with pytest.raises(ValueError) as ei:
        Candidate.from_dict(d)
    msg = str(ei.value)
    assert "expected a candidate object" in msg          # what was expected
    assert f"got {name}" in msg                          # what actually arrived
    assert "re-run music-source" in msg                  # the remedy
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg                            # not a laundered low-level exception


def test_every_request_verifies_against_certifi_not_the_interpreters_store(monkeypatch, tmp_path):
    """The second real run (retro 2026-10-16 S3): a python.org interpreter ships no CA
    bundle until its 'Install Certificates' script is run, so every Deezer request failed
    CERTIFICATE_VERIFY_FAILED and the agent prefixed every music command with
    SSL_CERT_FILE. Both transports must carry a context built on certifi's bundle."""
    import certifi
    import ssl
    built, seen = [], []
    real = ssl.create_default_context

    def spy(*a, **kw):
        built.append(kw.get("cafile"))
        return real(*a, **kw)

    monkeypatch.setattr(catalog.ssl, "create_default_context", spy)

    class _Stream(_FakeResp):                    # copyfileobj reads in sized chunks
        def read(self, n=-1):
            body, self._body = self._body, b""
            return body

    def fake(req, timeout=0, context=None):
        seen.append(context)
        return _Stream(_json.dumps({"results": []}))

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fake)
    catalog._get_json("https://example.invalid/x")
    catalog.http_download("https://example.invalid/y", tmp_path / "y.bin")
    assert built == [certifi.where(), certifi.where()]
    assert len(seen) == 2 and all(isinstance(c, ssl.SSLContext) for c in seen)
