"""beats.py tests. The downsample unit tests moved to tests/lib/test_offset.py
(scripts/lib/offset.py owns that logic now — see docs/specs/2026-07-13-
start-offset-intelligence-design.md). Repopulated by later start-offset tasks."""
import numpy as np

from scripts import beats
from scripts.lib import offset, vocals


def _fake_librosa(monkeypatch, track_seconds, sr=2000):
    """Make beats' lazy `import librosa` return a stub whose load() yields a signal
    of the requested length and whose feature.rms() returns a dummy frame array.
    offset.downsample is separately monkeypatched, so the rms values don't matter."""
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(track_seconds * sr), dtype=np.float32), sr))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.0]]))


def test_choose_offset_track_shorter_than_reel_returns_zero(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=2.0)
    assert beats.choose_offset("t.wav", duration=5.0) == 0.0
    assert "whole track" in capsys.readouterr().err


def test_choose_offset_vocal_path_when_demucs_present(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=4.0)
    # fixed mix envelope: loud in the second half (mix_hz=2 → 8 samples = 4s)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0], 2.0))
    monkeypatch.setattr(vocals, "has_demucs", lambda: True)
    # vocal env silent at t=1.5s (sample 3) → a gap leading into the loud region
    monkeypatch.setattr(vocals, "separate_vocal_energy",
                        lambda *a, **k: ([9.0, 9.0, 9.0, 0.0, 0.0, 9.0, 9.0, 9.0], 2.0))
    off = beats.choose_offset("t.wav", duration=2.0, use_vocals=True)
    assert off == 1.5                                        # best_offset over the injected arrays
    assert "via vocal" in capsys.readouterr().err


def test_choose_offset_falls_back_to_mix_proxy_without_demucs(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0], 2.0))
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    called = {"vocal": False}
    monkeypatch.setattr(vocals, "separate_vocal_energy",
                        lambda *a, **k: called.__setitem__("vocal", True) or ([], 2.0))
    off = beats.choose_offset("t.wav", duration=2.0)
    assert called["vocal"] is False                         # vocal path not taken
    assert "mix-proxy" in capsys.readouterr().err
    assert 0.0 <= off <= 2.0
