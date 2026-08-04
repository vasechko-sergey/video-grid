import importlib.util

import pytest

from scripts.lib import vocals


def test_has_demucs_true(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert vocals.has_demucs() is True


def test_has_demucs_false(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert vocals.has_demucs() is False


def test_separate_vocal_energy_raises_a_remedy_when_absent(monkeypatch):
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    with pytest.raises(ValueError, match="bash setup.sh"):
        vocals.separate_vocal_energy("track.wav")
