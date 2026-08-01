import json
import sys

import pytest

from scripts import verify_runtime


def test_probe_deps_reports_missing(monkeypatch):
    real = verify_runtime.importlib.import_module

    def fake(name):
        if name == "librosa":
            raise ImportError("no librosa")
        return real(name)

    monkeypatch.setattr(verify_runtime.importlib, "import_module", fake)
    ok, detail = verify_runtime._probe_deps()
    assert ok is False and "librosa" in detail


def test_probe_weights_present_and_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", tmp_path)
    ok, _ = verify_runtime._probe_weights()
    assert ok is False
    (tmp_path / verify_runtime.MODELS[0]).write_bytes(b"x")
    ok, detail = verify_runtime._probe_weights()
    assert ok is True and verify_runtime.MODELS[0] in detail


def test_probes_keys_match_registry():
    from scripts.lib.preflight import CHECKS
    assert set(verify_runtime._PROBES) == {c.key for c in CHECKS}
