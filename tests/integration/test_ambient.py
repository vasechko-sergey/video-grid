"""Real-ffmpeg proofs for the ambient bed (design §8): (A) mix with a bed still hits
−14 LUFS; (B) sidechaincompress ducks — the ambient band is quieter under loud music.
Synthetic known-answer signals, mirroring tests/integration/test_mood.py / test_offset.py."""
import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, mix
from scripts.lib import ffbin, proc
from scripts.lib.models import MusicSpec

_SR = 22050


def _tone_wav(path, secs, freq, amp, first_half_only=False):
    """A sine at `freq`. first_half_only → loud for [0, secs/2), silent after (a
    music envelope that makes ducking differential and measurable)."""
    t = np.arange(int(secs * _SR)) / _SR
    y = amp * np.sin(2 * np.pi * freq * t)
    if first_half_only:
        y[t >= secs / 2] = 0.0
    wavfile.write(path, _SR, y.astype(np.float32))
    return str(path)


def _music(path, secs, freq=220.0, amp=0.6, first_half_only=False):
    _tone_wav(path, secs, freq, amp, first_half_only)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(path), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3,), energy_hz=2.0)


def _band_rms(samples, sr, freq):
    """RMS magnitude at `freq` via a single-bin DFT — isolates the ambient tone."""
    n = len(samples)
    k = np.exp(-2j * np.pi * freq * np.arange(n) / sr)
    return abs(np.dot(samples, k)) / n


@pytest.mark.integration
def test_mix_with_ambient_hits_target_loudness(tmp_path):
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    ms = _music(tmp_path / "m.wav", secs=6)
    seg = _tone_wav(tmp_path / "seg.wav", secs=6, freq=880, amp=0.5)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0, segments=[(seg, 6.0)])
    measured = check_reel._loudnorm_measure(stem)
    assert abs(measured - (-14.0)) <= 1.0            # check_reel's real loudness gate (±1 of −14)


@pytest.mark.integration
def test_ambient_ducks_under_loud_music(tmp_path):
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    # music (220 Hz) loud for the first half, silent after; ambient (880 Hz) constant.
    ms = _music(tmp_path / "m.wav", secs=6, first_half_only=True)
    seg = _tone_wav(tmp_path / "seg.wav", secs=6, freq=880, amp=0.5)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0, segments=[(seg, 6.0)])
    dec = str(tmp_path / "dec.wav")
    proc.run([ffbin.ffmpeg(), "-y", "-i", stem, "-ac", "1", "-ar", str(_SR), dec])
    sr, y = wavfile.read(dec)
    y = y.astype(np.float64)
    half = len(y) // 2
    loud = _band_rms(y[:half], sr, 880)              # music loud here → ambient ducked
    quiet = _band_rms(y[half:], sr, 880)             # music silent here → ambient full
    assert loud < quiet * 0.9                        # the duck attenuates the ambient band
