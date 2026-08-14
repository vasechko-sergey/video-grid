import importlib

import pytest

from scripts.lib import vocals


def test_has_demucs_true(monkeypatch):
    monkeypatch.setattr(importlib, "import_module", lambda name: object())
    assert vocals.has_demucs() is True


def test_has_demucs_false(monkeypatch):
    def _missing(name):
        raise ModuleNotFoundError(f"No module named {name!r}")
    monkeypatch.setattr(importlib, "import_module", _missing)
    assert vocals.has_demucs() is False


def test_has_demucs_false_when_installed_but_unimportable(monkeypatch):
    """The probe must IMPORT, not merely find a spec. torchreid 0.2.5 shipped exactly
    this shape on 2026-08-14 — pip installs it, `find_spec` finds it, and importing it
    raises ModuleNotFoundError because it under-declares `gdown`. A spec-only probe
    would report a REQUIRED capability present and hand the run a module that explodes
    at the first real call."""
    def _broken(name):
        raise ModuleNotFoundError("No module named 'some_undeclared_dep'")
    monkeypatch.setattr(importlib, "import_module", _broken)
    assert vocals.has_demucs() is False


def test_has_demucs_false_on_a_non_import_error(monkeypatch):
    """A broken C-extension can raise something that is not an ImportError at all
    (verify_runtime._importable catches bare Exception for this reason). Unusable is
    unusable — the probe must not let it through."""
    def _boom(name):
        raise OSError("dlopen failed: incompatible architecture")
    monkeypatch.setattr(importlib, "import_module", _boom)
    assert vocals.has_demucs() is False


def test_separate_vocal_energy_raises_a_remedy_when_absent(monkeypatch):
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    with pytest.raises(ValueError, match="bash setup.sh"):
        vocals.separate_vocal_energy("track.wav")
