"""Real-ffmpeg proofs for transition SFX (design §8): (A) mix with a whoosh layer
still hits −14 LUFS; (B) the whoosh lands on the major cut and only there. Synthetic
known-answer signals, mirroring tests/integration/test_ambient.py."""
import shutil

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, mix
from scripts.lib import proc
from scripts.lib.models import MusicSpec

_SR = 22050


def _music(path, secs, amp=0.3):
    """A steady 220 Hz tone + a MusicSpec describing it (a beat every 0.5s)."""
    n = int(secs * _SR)
    y = (amp * np.sin(2 * np.pi * 220 * np.arange(n) / _SR)).astype(np.float32)
    wavfile.write(path, _SR, y)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(path), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3,), energy_hz=2.0)


def _band_rms(y, sr, t0, t1, lo, hi):
    """RMS of the [lo,hi] Hz band inside the [t0,t1] s window, via rFFT. Isolates the
    broadband whoosh (centred ~1200 Hz) from the tonal 220 Hz music, which contributes
    ~nothing in that band — so placement is provable with the music at full level."""
    seg = y[int(t0 * sr):int(t1 * sr)]
    if len(seg) == 0:
        return 0.0
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    band = np.abs(np.fft.rfft(seg))[(freqs >= lo) & (freqs < hi)]
    return float(np.sqrt(np.mean(band ** 2))) if len(band) else 0.0


@pytest.mark.integration
def test_mix_with_sfx_hits_target_loudness(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ms = _music(tmp_path / "m.wav", secs=6)
    seg = str(tmp_path / "m.wav")                          # ambient off → seg path unused; durs drive sfx
    segments = [(seg, 3.0), (seg, 0.5), (seg, 0.5)]        # median 0.5 → one major cut at t≈3.0
    stem = mix.mix(ms, str(tmp_path / "out"), dur=4.0, segments=segments, ambient=False, sfx=True)
    measured = check_reel._loudnorm_measure(stem)
    assert abs(measured - (-14.0)) <= 1.0                 # loudnorm still lands with the whoosh layer


@pytest.mark.integration
def test_sfx_lands_on_the_major_cut_only(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ms = _music(tmp_path / "m.wav", secs=6)                # music at a normal level (amp 0.3)
    seg = str(tmp_path / "m.wav")
    segments = [(seg, 3.0), (seg, 0.5), (seg, 0.5)]        # only the cut after ep0 (max(3,0.5)>0.5) is major
    stem = mix.mix(ms, str(tmp_path / "out"), dur=4.0, segments=segments, ambient=False, sfx=True)
    dec = str(tmp_path / "dec.wav")
    proc.run(["ffmpeg", "-y", "-i", stem, "-ac", "1", "-ar", str(_SR), dec])
    sr, y = wavfile.read(dec)
    y = y.astype(np.float64)
    # the whoosh is broadband noise centred ~1200 Hz; measure ITS band, where the 220 Hz
    # music is absent — so a strong cut/control ratio proves placement, not just loudness.
    at_cut = _band_rms(y, sr, 2.85, 3.25, 1000, 1600)     # the whoosh straddles t=3.0
    control = _band_rms(y, sr, 1.30, 1.70, 1000, 1600)    # steady music only, no cut here
    assert at_cut > control * 50                          # the whoosh dominates its band at the cut, not elsewhere
