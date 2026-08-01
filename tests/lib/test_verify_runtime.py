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


def _stub_all(monkeypatch, **overrides):
    """Force every probe to a chosen (ok, detail); default all-pass."""
    for key in verify_runtime._PROBES:
        result = overrides.get(key, (True, "ok"))
        monkeypatch.setitem(verify_runtime._PROBES, key, lambda r=result: r)


def test_run_all_pass_is_ready(monkeypatch):
    _stub_all(monkeypatch)
    assert verify_runtime.run().ok is True


def test_run_required_miss_not_ready(monkeypatch):
    _stub_all(monkeypatch, vidstab=(False, "vidstabdetect absent"))
    r = verify_runtime.run()
    assert r.ok is False and [f.key for f in r.failures] == ["vidstab"]


def test_cli_exit_0_when_ready(monkeypatch, capsys):
    _stub_all(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 0
    assert "runtime ready" in capsys.readouterr().out


def test_cli_exit_1_on_required_miss(monkeypatch, capsys):
    _stub_all(monkeypatch, drawtext=(False, "absent"))
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 1
    assert "drawtext: bash setup.sh" in capsys.readouterr().out


def test_cli_exit_0_on_advisory_only_miss(monkeypatch, capsys):
    _stub_all(monkeypatch, demucs=(False, "not installed"))
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 0                     # advisory never changes the exit code


def test_cli_json(monkeypatch, capsys):
    _stub_all(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["verify_runtime", "--json"])
    with pytest.raises(SystemExit):
        verify_runtime.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["results"][0]["key"] == "deps"
