"""Real integration for start-offset intelligence (design §7). demucs is REQUIRED
since 2026-08-14, so the vocal path is the ONLY path: its test skips when demucs is
absent (mirrors the vidstab-gated goldens) and the refusal test runs everywhere.
Synthetic audio can't semantically exercise a vocal-trained net, so the vocal test is
a wiring smoke-test — semantic correctness is carried by the pure offset unit tests."""
import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats
from scripts.lib import vocals


def _has_demucs() -> bool:
    # the SAME probe the production gate uses — a skip must not rest on a weaker
    # question than the code it guards (see vocals.has_demucs' 2026-08-14 note)
    return vocals.has_demucs()


def _tone_wav(path, sr=22050, secs=12):
    """12s: a quiet 110 Hz bed throughout, a loud 300 Hz 'vocal' tone only in [4,8)s."""
    t = np.arange(int(secs * sr)) / sr
    bed = 0.05 * np.sin(2 * np.pi * 110 * t)
    vocal = 0.6 * np.sin(2 * np.pi * 300 * t) * ((t >= 4) & (t < 8))
    wavfile.write(path, sr, (bed + vocal).astype(np.float32))
    return str(path)


@pytest.mark.integration
def test_choose_offset_refuses_on_real_bytes_without_demucs(tmp_path, monkeypatch):
    """The fallback is gone: on a machine without demucs the driver stops with a
    remedy instead of quietly answering off the mix envelope."""
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    wav = _tone_wav(tmp_path / "t.wav")
    with pytest.raises(ValueError, match=r"bash setup\.sh"):
        beats.choose_offset(wav, duration=4.0)


@pytest.mark.integration
@pytest.mark.skipif(not _has_demucs(), reason="needs demucs (bash setup.sh)")
def test_choose_offset_vocal_path_wiring(tmp_path):
    # smoke: the whole demucs→envelope→decision path runs on real bytes and returns
    # a valid offset (slow — real separation). Semantic correctness is unit-tested.
    wav = _tone_wav(tmp_path / "t.wav")
    off = beats.choose_offset(wav, duration=4.0)
    assert 0.0 <= off <= 12.0 - 4.0
