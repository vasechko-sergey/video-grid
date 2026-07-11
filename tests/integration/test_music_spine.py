"""Real-ffmpeg proofs for the music spine (design §7): (A) mix hits −14 LUFS;
(B) build_reel delivers a reel WITH an audio stream end-to-end (added in Task 7).
Clips are built with the real reframe encoder, matching test_reel_retry.py's precedent."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, mix
from scripts.lib.models import MusicSpec, ReelCheckSpec


def _tone_music(tmp_path, secs=6, sr=22050):
    """A steady 220 Hz tone + a MusicSpec describing it (a beat every 0.5s)."""
    n = int(secs * sr)
    y = (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / sr)).astype(np.float32)
    wav = tmp_path / "tone.wav"
    wavfile.write(wav, sr, y)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(wav), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3, 0.3, 0.3), energy_hz=2.0)


@pytest.mark.integration
def test_mix_hits_target_loudness(tmp_path):
    ms = _tone_music(tmp_path, secs=6)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0)
    measured = check_reel._loudnorm_measure(stem)
    spec = ReelCheckSpec(target_dur=6.0)
    assert abs(measured - spec.loudness_target) <= spec.loudness_tol   # mix must satisfy check_reel's real gate (±1 of −14)
