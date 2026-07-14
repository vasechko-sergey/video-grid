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


def test_build_shortlist_same_slug_candidates_do_not_cross_attribute(tmp_path, monkeypatch):
    # Two catalog hits collapse to the same slug (realistic: iTunes/Deezer single vs album
    # cut — same artist/title, different ref/preview). Keying rows by slug would give a row
    # the WRONG candidate's identity while keeping its own mood vector — silent corruption
    # music_fetch would then act on. Rows must key by index so ref never crosses.
    a = Candidate("Dup", "A", "itunes", "ref-single", "unknown (any lane)", "http://p/a")
    b = Candidate("Dup", "A", "itunes", "ref-album", "unknown (any lane)", "http://p/b")
    assert a.slug() == b.slug()                      # precondition: the collision
    monkeypatch.setattr(find.catalog, "search", lambda *a_, **k: [a, b])
    monkeypatch.setattr(find.catalog, "preview_clip", lambda c, d: d)   # unique per-candidate subdir
    seen = []
    def fake_features(path):
        seen.append(path)
        return MoodVector(0.9, 0.7, 0.85) if len(seen) == 1 else MoodVector(0.2, 0.5, 0.3)
    monkeypatch.setattr(find.beats, "mood_features", fake_features)
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["candidates"][0]["ref"] == "ref-single"   # energetic vector => the single, not the album cut
    assert data["candidates"][1]["ref"] == "ref-album"


def test_free_default_query_gets_instrumental_hint(tmp_path, monkeypatch):
    x = _c("X", source="ccmixter")
    seen = {}
    def fake_search(mode, q, n, catalog=None):
        seen["q"] = q
        return [x]
    monkeypatch.setattr(find.catalog, "search", fake_search)
    monkeypatch.setattr(find.catalog, "preview_clip", lambda c, d: d)
    monkeypatch.setattr(find.beats, "mood_features", lambda p: MoodVector(0.5, 0.5, 0.5))
    out = tmp_path / "o"; out.mkdir()
    find.build_shortlist("free", "energetic", str(out))
    assert seen["q"] == "energetic instrumental"          # free default → hint appended
    find.build_shortlist("any", "energetic", str(out))
    assert seen["q"] == "energetic"                       # any → no hint
    find.build_shortlist("free", "energetic", str(out), query="my exact query")
    assert seen["q"] == "my exact query"                  # --query overrides verbatim


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
