import json
import sys

import pytest

from scripts import verify_runtime
from scripts.lib import preflight


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


def test_probe_reid_reports_installed_and_absent(monkeypatch):
    # mirrors test_probe_deps_reports_missing's style: drive _probe_reid via
    # importlib rather than the real machine, since torchreid stays absent/mocked
    # in this suite (design 2026-08-04 §7/§8) regardless of what is installed here.
    monkeypatch.setattr(verify_runtime.importlib, "import_module", lambda name: object())
    ok, detail = verify_runtime._probe_reid()
    assert ok is True and detail == "installed"

    def fake_absent(name):
        raise ImportError("no torchreid")

    monkeypatch.setattr(verify_runtime.importlib, "import_module", fake_absent)
    ok, detail = verify_runtime._probe_reid()
    assert ok is False and detail == "not installed"


def test_probes_keys_match_registry():
    from scripts.lib.preflight import CHECKS
    assert set(verify_runtime._PROBES) == {c.key for c in CHECKS}


def test_probe_filter_survives_a_non_executable_binary(monkeypatch):
    """A resolved-but-non-executable/corrupted ffmpeg makes subprocess raise
    PermissionError (an OSError), not ValueError/RuntimeError — ffbin.has_filter
    does not wrap it. _probe_filter (and therefore _probe_drawtext/_probe_vidstab)
    must catch it too, or it propagates through run() and crashes the checker."""
    def raise_permission_error(name):
        raise PermissionError(f"[Errno 13] Permission denied: {name!r}")

    monkeypatch.setattr(verify_runtime.ffbin, "has_filter", raise_permission_error)
    ok, detail = verify_runtime._probe_drawtext()
    assert ok is False and detail == "ffmpeg unavailable"


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
    out = capsys.readouterr().out
    assert "drawtext: cd " in out and "&& bash setup.sh" in out   # cwd-independent


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


def test_run_survives_a_raising_probe(monkeypatch):
    """A probe must never crash the checker. Guard test for that invariant: force
    one probe to raise and confirm run() still returns a RuntimeReport (not
    propagate) with that check reported as a failure, while every other probe is
    still evaluated normally (the crash is contained to the one check)."""
    _stub_all(monkeypatch)

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setitem(verify_runtime._PROBES, "font", boom)
    r = verify_runtime.run()
    assert isinstance(r, preflight.RuntimeReport)
    font_result = next(x for x in r.results if x.key == "font")
    assert font_result.ok is False and "probe raised" in font_result.detail
    assert all(x.ok for x in r.results if x.key != "font")


def test_run_remedies_carry_their_own_cd_so_they_run_from_any_cwd(monkeypatch):
    """Regression: the remedy was a bare `bash setup.sh`, which fails from any cwd
    but the clone (the user clicked Run in ~/Downloads and got 'No such file').
    run() must render it absolute — `cd <clone> && bash setup.sh` — so Run works
    wherever the shell is."""
    _stub_all(monkeypatch, deps=(False, "missing"))
    dep = next(x for x in verify_runtime.run().results if x.key == "deps")
    assert dep.remedy.startswith("cd ") and dep.remedy.endswith("&& bash setup.sh")
    assert str(verify_runtime._ROOT) in dep.remedy
