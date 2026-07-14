# tests/lib/test_fetch.py
import json
import subprocess as _sp

import pytest

from scripts.lib import catalog, fetch


def _cc(**kw):
    d = dict(title="T", artist="A", source="jamendo", ref="http://a/dl",
             license="CC BY", preview_url=None)
    d.update(kw)
    return catalog.Candidate(**d)


def test_download_free_direct_writes_file_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.catalog, "http_download",
                        lambda url, dest: dest.write_bytes(b"MP3"))
    tr = fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")
    assert open(tr.path, "rb").read() == b"MP3" and tr.license == "CC BY"
    side = json.loads((tmp_path / f"{_cc().slug()}.json").read_text())
    assert side["source"] == "jamendo" and side["date"] == "2026-07-14"


def test_download_any_youtube_logs_responsibility(tmp_path, monkeypatch, capsys):
    c = _cc(source="youtube", ref="vid", license="unknown (any lane)")
    monkeypatch.setattr(fetch.catalog, "has_ytdlp", lambda: True)
    monkeypatch.setattr(fetch.catalog, "ytdlp_cmd", lambda: ["yt-dlp"])
    def fake_run(cmd, **k):
        (tmp_path / f"{c.slug()}.m4a").write_bytes(b"YT")
        return _sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(fetch.subprocess, "run", fake_run)
    tr = fetch.download(c, "any", str(tmp_path), "2026-07-14")
    assert tr.path.endswith(".m4a")
    assert "COPYRIGHTED" in capsys.readouterr().err        # responsibility log


def test_download_free_does_not_log_responsibility(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch.catalog, "http_download", lambda url, dest: dest.write_bytes(b"x"))
    fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")
    assert "COPYRIGHTED" not in capsys.readouterr().err


def test_download_reuses_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch.catalog, "http_download",
                        lambda url, dest: (calls.append(1), dest.write_bytes(b"x")))
    fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")
    fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")   # sidecar present → reuse
    assert len(calls) == 1


def test_download_free_rejects_youtube_source(tmp_path):
    with pytest.raises(ValueError, match="rights invariant"):
        fetch.download(_cc(source="youtube", ref="v", license="unknown (any lane)"),
                       "free", str(tmp_path), "2026-07-14")
