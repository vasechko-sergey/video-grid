# tests/integration/test_pacing.py
"""pacing integration — a real MUSIC.json from librosa.analyze on a synthetic quiet/loud
WAV proves the energy→cut-density path end-to-end (the unit test's hand-built curve
stands in for this). Real dep, known-answer input — the test_mood/test_beats ethos."""
import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats
from scripts.lib import pacing

pytestmark = pytest.mark.integration


def _half_wav(path, sr=22050, secs=12.0, bpm=120.0):
    """A pulse train at `bpm` (→ a regular beat grid) with a quiet first half and a
    loud second half (→ a clear energy step at the midpoint)."""
    t = np.arange(int(secs * sr)) / sr
    tone = np.sin(2 * np.pi * 220 * t)
    period = 60.0 / bpm
    pulse = ((t % period) / period < 0.05).astype(np.float32)   # a click each beat → onsets
    loud = np.where(t < secs / 2, 0.15, 1.0)                    # quiet → loud step
    sig = loud * (0.3 * tone + pulse)
    wavfile.write(str(path), sr, sig.astype(np.float32))


def test_loud_half_gets_more_slots(tmp_path):
    wav = tmp_path / "m.wav"
    _half_wav(wav)
    music = beats.analyze(str(wav))                              # real MUSIC.json
    spine = pacing.build_spine(music.beats, music.energy, music.energy_hz,
                               music.duration, music.tempo)
    mid = music.duration / 2
    loud = [s for s in spine.slots if s.start >= mid]
    quiet = [s for s in spine.slots if s.start < mid]
    assert len(loud) > len(quiet)                               # density ∝ energy
    assert abs(sum(s.dur for s in spine.slots) - music.duration) < 1e-6
    assert spine.slots[0].kind == "hook"
