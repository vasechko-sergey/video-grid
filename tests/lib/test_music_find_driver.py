# tests/lib/test_music_find_driver.py
"""music_find driver — mocks catalog.search/preview_clip + beats.mood_features (no network,
no librosa here). Mirrors test_mood_driver.py."""
import json

import pytest

from scripts import music_find as find
from scripts.lib.catalog import Candidate
from scripts.lib.mood import MoodVector


def _stub(monkeypatch, cands, vecs):
    monkeypatch.setattr(find.catalog, "search", lambda *a, **k: cands)
    monkeypatch.setattr(find.catalog, "preview_clip", lambda c, d: c.slug())
    monkeypatch.setattr(find.beats, "mood_features", lambda slug: vecs[slug])


def _c(title, source="youtube"):
    return Candidate(title, "A", source, "ref-" + title, "unknown (any lane)", None)


def test_build_shortlist_ranks_and_writes(tmp_path, monkeypatch):
    e, c = _c("Energetic"), _c("Chill")
    _stub(monkeypatch, [e, c],
          {e.slug(): MoodVector(0.9, 0.7, 0.85), c.slug(): MoodVector(0.2, 0.5, 0.3)})
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["mode"] == "any" and data["fallback"] is None
    assert [r["title"] for r in data["candidates"]] == ["Energetic", "Chill"]
    assert "fit" in data["candidates"][0] and data["candidates"][0]["source"] == "youtube"
    assert (out / "MUSIC_SHORTLIST.md").exists()


def test_build_shortlist_unknown_mood_falls_back_to_drive(tmp_path, monkeypatch, capsys):
    a, b = _c("A"), _c("B")
    _stub(monkeypatch, [a, b],
          {a.slug(): MoodVector(0.1, 0.5, 0.1), b.slug(): MoodVector(0.9, 0.5, 0.9)})
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "purple wombat", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["fallback"] == "drive" and data["candidates"][0]["title"] == "B"
    assert "drive" in data["candidates"][0] and "distance" not in data["candidates"][0]
    assert "ranking by drive" in capsys.readouterr().err


def test_cli_reads_mood_from_spec(tmp_path, monkeypatch):
    from scripts.lib.spec import Spec
    x = _c("X")
    _stub(monkeypatch, [x], {x.slug(): MoodVector(0.9, 0.7, 0.85)})
    spec = tmp_path / "SPEC.json"
    Spec(canvas=(1080, 1920), length_s=30.0, mood="energetic", hook="h").write(spec)
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr("sys.argv", ["music_find", "--mode", "any", "--spec", str(spec),
                                     "--out-dir", str(out)])
    find.main()
    assert json.loads((out / "MUSIC_SHORTLIST.json").read_text())["mood_text"] == "energetic"


def test_cli_requires_free_or_any(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["music_find", "--mode", "local", "--mood", "x",
                                     "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):        # choices=(free, any) → argparse rejects local
        find.main()
