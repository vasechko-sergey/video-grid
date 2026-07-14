# tests/integration/test_mood.py
"""Real-librosa integration for mood-match (design §7): mood_features on synthetic
known signals (a real dep, a known-answer input — the test_beats ethos), and a
2-track golden proving build_shortlist ranks the energetic track first. All ±tol —
librosa isn't bit-exact on synthetic audio."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats, mood as driver


def _sine_wav(path, sr, secs, freq, amp=0.5):
    t = np.arange(int(secs * sr)) / sr
    wavfile.write(path, sr, (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32))
    return str(path)


def _mix_wav(path, sr, secs, freq, bpm, amp):
    """A tone at `freq` gated into clicks at `bpm` — carries both a spectral centroid
    (freq → brightness) and a tempo (bpm → pace), so mood_features reads both axes."""
    t = np.arange(int(secs * sr)) / sr
    tone = np.sin(2 * np.pi * freq * t)
    env = np.zeros_like(t)
    step = int(sr * 60.0 / bpm)
    width = max(1, step // 4)
    for i in range(0, len(env), step):
        env[i:i + width] = 1.0
    wavfile.write(path, sr, (amp * tone * env).astype(np.float32))
    return str(path)


@pytest.mark.integration
def test_mood_features_brightness_tracks_frequency(tmp_path):
    dark = beats.mood_features(_sine_wav(tmp_path / "d.wav", 22050, 4, freq=200))
    bright = beats.mood_features(_sine_wav(tmp_path / "b.wav", 22050, 4, freq=6000))
    assert bright.brightness > dark.brightness


@pytest.mark.integration
def test_mood_features_energy_is_loudness_robust(tmp_path):
    loud = beats.mood_features(_sine_wav(tmp_path / "l.wav", 22050, 4, freq=1000, amp=0.9))
    quiet = beats.mood_features(_sine_wav(tmp_path / "q.wav", 22050, 4, freq=1000, amp=0.1))
    assert loud.energy == pytest.approx(quiet.energy, abs=0.05)   # peak-normalized → equal


@pytest.mark.integration
def test_mood_features_pace_tracks_tempo(tmp_path):
    slow = beats.mood_features(_mix_wav(tmp_path / "s.wav", 22050, 8, freq=1000, bpm=70, amp=0.6))
    fast = beats.mood_features(_mix_wav(tmp_path / "f.wav", 22050, 8, freq=1000, bpm=150, amp=0.6))
    assert fast.pace > slow.pace


@pytest.mark.integration
def test_build_shortlist_golden_ranks_energetic_first(tmp_path):
    folder = tmp_path / "trk"; folder.mkdir()
    _mix_wav(folder / "energetic.wav", 22050, 8, freq=5000, bpm=150, amp=0.9)  # bright + fast
    _mix_wav(folder / "chill.wav", 22050, 8, freq=250, bpm=70, amp=0.3)        # dark + slow
    out = tmp_path / "out"; out.mkdir()
    driver.build_shortlist(str(folder), "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["candidates"][0]["track"] == "energetic.wav"
