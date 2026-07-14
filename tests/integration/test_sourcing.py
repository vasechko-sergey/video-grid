# tests/integration/test_sourcing.py
"""Sourcing integration (design §11): a real keyless iTunes smoke (skipped when the network
is down) + a fully-local find that runs REAL librosa mood on fixture WAVs with the catalog
stubbed — proving find → mood_features → rank end-to-end offline (the demucs-skip ethos)."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import music_find as find
from scripts.lib import catalog


def _mix_wav(path, sr, secs, freq, bpm, amp):
    t = np.arange(int(secs * sr)) / sr
    env = np.zeros_like(t)
    step = int(sr * 60.0 / bpm)
    for i in range(0, len(env), step):
        env[i:i + max(1, step // 4)] = 1.0
    wavfile.write(path, sr, (amp * np.sin(2 * np.pi * freq * t) * env).astype(np.float32))
    return str(path)


@pytest.mark.integration
def test_itunes_search_smoke_or_skip():
    try:
        cands = catalog._search_itunes("energetic electronic", 3)
    except ValueError as e:
        pytest.skip(f"no network for the iTunes smoke: {e}")
    assert cands and cands[0].source == "itunes"


@pytest.mark.integration
def test_find_local_fixture_ranks_energetic_first(tmp_path, monkeypatch):
    e = _mix_wav(tmp_path / "e.wav", 22050, 8, freq=5000, bpm=150, amp=0.9)   # bright + fast
    c = _mix_wav(tmp_path / "c.wav", 22050, 8, freq=250, bpm=70, amp=0.3)     # dark + slow
    cands = [catalog.Candidate("Energetic", "A", "youtube", "u-e", "unknown (any lane)", None),
             catalog.Candidate("Chill", "B", "youtube", "u-c", "unknown (any lane)", None)]
    clips = {cands[0].slug(): e, cands[1].slug(): c}
    monkeypatch.setattr(find.catalog, "search", lambda *a, **k: cands)
    monkeypatch.setattr(find.catalog, "preview_clip", lambda cand, d: clips[cand.slug()])
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "energetic", str(out))          # REAL beats.mood_features
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["candidates"][0]["title"] == "Energetic"
