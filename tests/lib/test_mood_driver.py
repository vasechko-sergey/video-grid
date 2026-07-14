"""scripts/mood.py driver — mocks beats.mood_features so no librosa runs here."""
import json
from pathlib import Path

import pytest

from scripts import mood as driver
from scripts.lib.mood import MoodVector


def _fake_folder(base, names):
    base.mkdir(parents=True, exist_ok=True)
    for n in names:
        (base / n).write_bytes(b"\x00")     # content irrelevant — mood_features is mocked
    return base


def _mock_features(monkeypatch, vecs):
    monkeypatch.setattr(driver.beats, "mood_features", lambda p: vecs[Path(p).name])


def test_build_shortlist_ranks_and_writes(tmp_path, monkeypatch):
    folder = _fake_folder(tmp_path / "trk", ["chill.wav", "energetic.wav"])
    _mock_features(monkeypatch, {"chill.wav": MoodVector(0.2, 0.5, 0.3),
                                 "energetic.wav": MoodVector(0.9, 0.7, 0.85)})
    out = tmp_path / "out"; out.mkdir()
    driver.build_shortlist(str(folder), "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["mood_text"] == "energetic" and data["fallback"] is None
    assert data["target"] is not None
    assert [c["track"] for c in data["candidates"]] == ["energetic.wav", "chill.wav"]
    assert "fit" in data["candidates"][0] and "distance" in data["candidates"][0]
    assert (out / "MUSIC_SHORTLIST.md").exists()


def test_build_shortlist_empty_folder_raises(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    with pytest.raises(ValueError, match="no audio files"):
        driver.build_shortlist(str(empty), "energetic", str(tmp_path))


def test_build_shortlist_unknown_mood_falls_back_to_drive(tmp_path, monkeypatch, capsys):
    folder = _fake_folder(tmp_path / "trk", ["a.wav", "b.wav"])
    _mock_features(monkeypatch, {"a.wav": MoodVector(0.1, 0.5, 0.1),    # drive 0.2
                                 "b.wav": MoodVector(0.9, 0.5, 0.9)})   # drive 1.8
    out = tmp_path / "out"; out.mkdir()
    driver.build_shortlist(str(folder), "purple wombat", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["fallback"] == "drive" and data["target"] is None
    assert [c["track"] for c in data["candidates"]] == ["b.wav", "a.wav"]   # higher drive first
    assert "drive" in data["candidates"][0] and "distance" not in data["candidates"][0]
    assert "ranking by drive" in capsys.readouterr().err


def test_cli_requires_spec_or_mood(tmp_path, monkeypatch):
    _fake_folder(tmp_path / "trk", ["x.wav"])
    monkeypatch.setattr("sys.argv", ["mood", "--folder", str(tmp_path / "trk"),
                                     "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):        # mutually-exclusive group required → argparse error
        driver.main()


def test_cli_mood_text_writes_shortlist(tmp_path, monkeypatch):
    folder = _fake_folder(tmp_path / "trk", ["a.wav"])
    _mock_features(monkeypatch, {"a.wav": MoodVector(0.5, 0.5, 0.5)})
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr("sys.argv", ["mood", "--folder", str(folder), "--mood", "chill",
                                     "--out-dir", str(out)])
    driver.main()
    assert (out / "MUSIC_SHORTLIST.json").exists()


def test_cli_reads_mood_from_spec(tmp_path, monkeypatch):
    from scripts.lib.spec import Spec
    folder = _fake_folder(tmp_path / "trk", ["a.wav"])
    _mock_features(monkeypatch, {"a.wav": MoodVector(0.9, 0.7, 0.85)})
    spec = tmp_path / "SPEC.json"
    Spec(canvas=(1080, 1920), length_s=30.0, mood="energetic", hook="x").write(spec)
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr("sys.argv", ["mood", "--folder", str(folder), "--spec", str(spec),
                                     "--out-dir", str(out)])
    driver.main()
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["mood_text"] == "energetic"
