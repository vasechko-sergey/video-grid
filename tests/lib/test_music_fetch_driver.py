# tests/lib/test_music_fetch_driver.py
"""music_fetch driver — mocks fetch.download (no network). Asserts pick + explicit-name paths."""
import json

import pytest

from scripts import music_fetch as mf
from scripts.lib import catalog, fetch


def _shortlist(tmp_path):
    p = tmp_path / "MUSIC_SHORTLIST.json"
    p.write_text(json.dumps({"candidates": [
        {"title": "T1", "artist": "A", "source": "youtube", "ref": "v1",
         "license": "unknown (any lane)", "preview_url": None},
        {"title": "T2", "artist": "B", "source": "youtube", "ref": "v2",
         "license": "unknown (any lane)", "preview_url": None}]}))
    return p


def _fake_track(path="/cache/x.m4a"):
    return fetch.FetchedTrack(path=path, title="T", artist="A", source="youtube",
                              source_url="v", license="unknown (any lane)", date="2026-07-14")


def test_fetch_pick_downloads_selected_row(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(mf.fetch, "download",
                        lambda cand, mode, cd, date: seen.setdefault("ref", cand.ref) or _fake_track())
    mf.fetch_pick(str(_shortlist(tmp_path)), 2, "any", str(tmp_path), "2026-07-14")
    assert seen["ref"] == "v2"


def test_fetch_pick_out_of_range_raises(tmp_path):
    with pytest.raises(ValueError, match="out of range"):
        mf.fetch_pick(str(_shortlist(tmp_path)), 9, "any", str(tmp_path), "2026-07-14")


def test_fetch_named_resolves_top1(tmp_path, monkeypatch):
    monkeypatch.setattr(mf.catalog, "search",
                        lambda mode, q, n: [catalog.Candidate("Named", "A", "youtube", "vN",
                                                              "unknown (any lane)", None)])
    monkeypatch.setattr(mf.fetch, "download", lambda cand, mode, cd, date: _fake_track(cand.ref))
    tr = mf.fetch_named("some song", "any", str(tmp_path), "2026-07-14")
    assert tr.path == "vN"


def test_cli_from_shortlist_needs_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["music_fetch", "--mode", "any", "--from-shortlist",
                                     str(_shortlist(tmp_path)), "--cache-dir", str(tmp_path),
                                     "--date", "2026-07-14"])
    with pytest.raises(SystemExit):        # --from-shortlist without --pick → ap.error
        mf.main()


def test_cli_pick_prints_cached_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mf.fetch, "download",
                        lambda cand, mode, cd, date: _fake_track("/cache/hit.m4a"))
    monkeypatch.setattr("sys.argv", ["music_fetch", "--mode", "any", "--from-shortlist",
                                     str(_shortlist(tmp_path)), "--pick", "1",
                                     "--cache-dir", str(tmp_path), "--date", "2026-07-14"])
    mf.main()                                     # exercises the fetch_pick dispatch + print
    assert capsys.readouterr().out.strip() == "/cache/hit.m4a"
