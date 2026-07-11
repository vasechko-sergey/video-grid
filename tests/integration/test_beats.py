"""Real-librosa golden for beats-core (design §3). A synthetic click track at a
known BPM is a deterministic known-answer input — librosa isn't bit-exact on real
songs, so we pin tempo/beat-spacing within tolerance, not exactly."""
import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats
from scripts.lib.models import MusicSpec


def _click_wav(path, bpm=120, secs=8, sr=22050):
    """`secs` of silence with a short 1 kHz burst on every beat."""
    n = int(secs * sr)
    y = np.zeros(n, dtype=np.float32)
    burst = (0.9 * np.sin(2 * np.pi * 1000 * np.arange(int(0.02 * sr)) / sr)).astype(np.float32)
    period = 60.0 / bpm
    for k in range(int(secs / period)):
        i = int(k * period * sr)
        y[i:i + len(burst)] += burst[:max(0, n - i)]
    wavfile.write(path, sr, y)
    return str(path)


@pytest.mark.integration
def test_analyze_recovers_tempo_beats_and_energy(tmp_path):
    wav = _click_wav(tmp_path / "click.wav", bpm=120, secs=8)
    ms = beats.analyze(wav, start_offset=0.0, duration=None)
    assert isinstance(ms, MusicSpec)
    assert abs(ms.tempo - 120) <= 5   # librosa lands ~117.45 (lag-bin resolution @ hop 512); ±5 still fails an octave error (60/240)
    assert len(ms.beats) >= 12                               # ~16 beats in 8s @120bpm; generous floor
    gaps = [b2 - b1 for b1, b2 in zip(ms.beats, ms.beats[1:])]
    assert abs(float(np.median(gaps)) - 0.5) <= 0.08         # median inter-beat ≈ 0.5s
    assert all(0.0 <= b <= ms.duration for b in ms.beats)    # reel-relative, in-window
    assert len(ms.energy) > 0 and ms.energy_hz > 0           # coarse RMS curve present
