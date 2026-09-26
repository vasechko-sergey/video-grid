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
    _stub_all(monkeypatch, reid=(False, "not installed"))
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 0                     # advisory never changes the exit code


def test_cli_exit_1_on_demucs_miss(monkeypatch, capsys):
    """demucs is REQUIRED since 2026-08-14 — it used to sit in the advisory row
    above, where a miss exited 0 and the run proceeded on a proxy that answered
    wrongly. Pinned separately so a flip back to advisory fails here, not in a reel."""
    _stub_all(monkeypatch, demucs=(False, "not installed"))
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 1
    assert "demucs: cd " in capsys.readouterr().out


def test_cli_json(monkeypatch, capsys):
    _stub_all(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["verify_runtime", "--json"])
    with pytest.raises(SystemExit):
        verify_runtime.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["results"][0]["key"] == "plugin"


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


def _install_record(tmp_path, entries):
    """Write a Claude Code installed_plugins.json carrying `entries` for this
    plugin, and point the probe's config dir at it."""
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {verify_runtime._plugin_id(): entries}}))
    return cfg


def _clone_manifest(tmp_path, version):
    """Give the probe a clone root whose plugin.json carries `version`.

    The fake marketplace is deliberately NOT named "video-grid": in the real
    manifests the plugin and the marketplace share a name, so a fixture that
    copied that could not tell which file each half of the id came from, and a
    probe reading `name` twice out of plugin.json would pass."""
    cp = tmp_path / "clone" / ".claude-plugin"
    cp.mkdir(parents=True, exist_ok=True)
    (cp / "plugin.json").write_text(json.dumps(
        {"name": "video-grid", "version": version}))
    (cp / "marketplace.json").write_text(json.dumps({"name": "vg-market"}))
    return tmp_path / "clone"


def test_plugin_id_is_derived_from_the_two_manifests(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    assert verify_runtime._plugin_id() == "video-grid@vg-market"


def test_probe_plugin_passes_when_there_is_no_record_file(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True and "no install record" in detail


def test_probe_plugin_passes_on_a_matching_install(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = _install_record(tmp_path, [{"scope": "user", "version": "9.9.9"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True and "9.9.9" in detail


def test_probe_plugin_fails_on_a_stale_install(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = _install_record(tmp_path, [{"scope": "user", "version": "0.2.1"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False and "0.2.1" in detail and "9.9.9" in detail


def test_probe_plugin_passes_when_the_record_lists_other_plugins_only(
        monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"superpowers@elsewhere": [
            {"scope": "user", "version": "6.2.0"}]}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True and "not installed as a plugin" in detail


def test_probe_plugin_defaults_to_the_home_config_dir(monkeypatch, tmp_path):
    """Without CLAUDE_CONFIG_DIR the record lives under ~/.claude. Path.home()
    honours HOME on posix, which is how this is reachable in a test at all."""
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cfg = tmp_path / "home" / ".claude"
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {verify_runtime._plugin_id(): [
            {"scope": "user", "version": "0.2.1"}]}}))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False and "0.2.1" in detail


@pytest.mark.parametrize("body,says", [
    ("{ not json", "Expecting"),                      # json's own parse message
    ('{"version": 2}', "plugins"),                    # the missing key, by name
    ('{"version": 2, "plugins": []}', "not a mapping"),
])
def test_an_unreadable_record_blocks_and_never_reads_as_fine(
        monkeypatch, tmp_path, body, says):
    """Cannot-answer is not allowed to read as 'nothing installed' — that is the
    silent-off this check exists to prevent — and it is not allowed to surface as
    a bare traceback either. It blocks, the detail names the path, and it names
    WHICH shape it could not read.

    That last assertion is what makes the three cases distinguishable: all three
    reach `ok is False`, two of them by a bare exception, so a test that only
    checked the boolean could not see the `isinstance` guard being deleted — a
    list with no `.get` raises anyway, just less legibly."""
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    rec = cfg / "plugins" / "installed_plugins.json"
    rec.write_text(body)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False
    assert str(rec) in detail
    assert says in detail
    assert "Traceback" not in detail


def test_a_record_entry_without_a_version_is_unreadable_not_skipped(
        monkeypatch, tmp_path):
    """Dropping it would turn a shape the reader does not understand into
    'nothing to compare', which passes."""
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = _install_record(tmp_path, [{"scope": "user"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False
    # The KIND of failure is the assertion that discriminates. A lenient
    # projection (`e.get("version", "")`) also returns False — "" mismatches
    # every clone version — so it would report a STALE install where the truth is
    # a record shape the reader does not understand. Only the message separates
    # the two.
    assert "unreadable" in detail


def test_an_unreadable_clone_manifest_blocks_rather_than_raising(
        monkeypatch, tmp_path):
    """The clone is the tree the probe executes from and test_plugin_manifests.py
    gates its shape, so this is not an expected state — but it must not escape as
    a stack fragment through run()'s catch-all.

    An install record must exist for this scenario to even reach the clone-side
    read: a missing record short-circuits to an unconditional pass before either
    of the clone's manifests is opened (design §2.2), so this fixture needs one —
    same shape as test_a_broken_marketplace_manifest_names_itself_not_the_install_record."""
    cp = tmp_path / "clone" / ".claude-plugin"
    cp.mkdir(parents=True)
    (cp / "plugin.json").write_text("{ not json")
    (cp / "marketplace.json").write_text('{"name": "video-grid"}')
    monkeypatch.setattr(verify_runtime, "_ROOT", tmp_path / "clone")
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False and "Traceback" not in detail


def test_a_broken_marketplace_manifest_names_itself_not_the_install_record(
        monkeypatch, tmp_path):
    """Both manifests are the clone's, but only plugin.json used to be read in a
    try that names the clone. A corrupt marketplace.json raised inside the record's
    try instead and was reported as an unreadable install record — blocking
    correctly, and sending the reader to the wrong file."""
    cp = tmp_path / "clone" / ".claude-plugin"
    cp.mkdir(parents=True)
    (cp / "plugin.json").write_text(json.dumps(
        {"name": "video-grid", "version": "9.9.9"}))
    (cp / "marketplace.json").write_text("{ not json")
    monkeypatch.setattr(verify_runtime, "_ROOT", tmp_path / "clone")
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False
    assert "marketplace.json" in detail
    assert "installed_plugins.json" not in detail
    assert "Traceback" not in detail


def test_no_install_record_does_not_read_the_clone_manifests_at_all(
        monkeypatch, tmp_path):
    """A missing record is an unconditional pass (design §2.2). The clone's own
    manifests are irrelevant to it, so a broken one must not block a machine that
    has no installed skills — and the boolean is the whole assertion here, because
    the previous shape returned False with a perfectly accurate message."""
    cp = tmp_path / "clone" / ".claude-plugin"
    cp.mkdir(parents=True)
    (cp / "plugin.json").write_text("{ not json")
    (cp / "marketplace.json").write_text("{ not json")
    monkeypatch.setattr(verify_runtime, "_ROOT", tmp_path / "clone")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True
    assert "no install record" in detail


def test_the_remedy_names_the_id_the_probe_actually_looks_up():
    """The plugin id lives in two places: derived from the manifests by
    _plugin_id(), and typed into the remedy a user is told to run. A remedy that
    updates a different id than the check reads would 'fix' nothing and the check
    would stay red with no way to clear it."""
    remedy = next(c.remedy for c in preflight.CHECKS if c.key == "plugin")
    assert remedy == f"claude plugin update {verify_runtime._plugin_id()}"
