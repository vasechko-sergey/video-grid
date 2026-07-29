from types import SimpleNamespace

import pytest

from scripts import deliver
from scripts.lib.models import CheckResult, ExportProfile, ReelReport, REEL_H264


def test_next_version_is_1_on_empty_dir(tmp_path):
    assert deliver._next_version(str(tmp_path), "mp4") == 1


def test_next_version_is_max_plus_one(tmp_path):
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / "REEL_v2.mp4").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    assert deliver._next_version(str(tmp_path), "mp4") == 3


def test_next_version_skips_gaps_uses_max_not_count(tmp_path):
    # a deleted middle version must not cause reuse: highest + 1, never count + 1
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / "REEL_v3.mp4").write_text("x")
    assert deliver._next_version(str(tmp_path), "mp4") == 4


def test_log_version_creates_header_then_appends(tmp_path):
    deliver._log_version(str(tmp_path), 1, "first cut")
    deliver._log_version(str(tmp_path), 2, "regraded ep1")
    text = (tmp_path / "VERSIONS.md").read_text()
    assert text.startswith("# Reel versions")
    assert "| first cut" in text and "- v2 |" in text and "| regraded ep1" in text


def _green():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _red():
    return ReelReport(checks={"length": CheckResult("length", False, {})}, episode_count=2)


def test_deliver_refuses_a_failed_reel(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: SimpleNamespace(stdout=b""))
    with pytest.raises(RuntimeError, match="does not ship a failed reel"):
        deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "x", _red())


def test_deliver_refuses_a_failed_reel_leaves_no_side_effects(tmp_path, monkeypatch):
    # the gate must fire BEFORE any mkdir/encode/version-bump: a failed reel
    # produces no out dir, no file, no VERSIONS.md, and never calls proc.run.
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    out_dir = tmp_path / "would-be-created"
    with pytest.raises(RuntimeError, match="does not ship a failed reel"):
        deliver.deliver("m.mp4", REEL_H264, str(out_dir), "x", _red())
    assert not out_dir.exists()
    assert calls == []


def test_deliver_encodes_v1_and_logs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    out = deliver.deliver("master.mp4", REEL_H264, str(tmp_path), "first cut", _green())
    assert out.endswith("REEL_v1.mp4")
    cmd = calls[0]
    assert "-an" in cmd and cmd[-1].endswith("REEL_v1.mp4") and "master.mp4" in cmd
    assert "scale=" not in " ".join(map(str, cmd))          # no re-scale
    assert (tmp_path / "VERSIONS.md").read_text().count("- v1 |") == 1


def test_deliver_second_run_is_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: SimpleNamespace(stdout=b""))
    deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "a", _green())
    (tmp_path / "REEL_v1.mp4").write_text("x")               # simulate the file the mock skipped
    out2 = deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "b", _green())
    assert out2.endswith("REEL_v2.mp4")


def test_deliver_muxes_audio_when_given(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    deliver.deliver(str(tmp_path / "m.mp4"), REEL_H264, str(tmp_path / "out"), "v1",
                    _green(), audio=str(tmp_path / "a.m4a"))
    cmd = calls[0]
    assert str(tmp_path / "a.m4a") in cmd and cmd.count("-i") == 2
    assert "0:v:0" in cmd and "1:a:0" in cmd
    assert "-an" not in cmd                              # profile's video-only -an is stripped for the mux
    assert "-shortest" in cmd
    assert cmd.count("-c:a") == 1 and cmd[cmd.index("-c:a") + 1] == "copy"


def test_deliver_silent_when_no_audio(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    deliver.deliver(str(tmp_path / "m.mp4"), REEL_H264, str(tmp_path / "out"), "v1", _green())
    assert "-an" in calls[0] and "1:a:0" not in calls[0]


def test_deliver_mux_forces_copy_over_profile_acodec(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    prof = ExportProfile(acodec="aac", abitrate_kbps=192)
    deliver.deliver(str(tmp_path / "m.mp4"), prof, str(tmp_path / "out"), "v1",
                    _green(), audio=str(tmp_path / "a.m4a"))
    cmd = calls[0]
    assert cmd.count("-c:a") == 1 and cmd[cmd.index("-c:a") + 1] == "copy"   # profile acodec overridden
    assert "-b:a" not in cmd                                                 # profile audio bitrate dropped


def test_deliver_threads_platform_into_the_filterchain(tmp_path, monkeypatch):
    # spy on build_filterchain so the test needs no real font on disk; the chain's
    # own platform behaviour is covered in test_titles.py.
    from scripts.lib.titles import Title, Titles
    seen = {}

    def _spy(titles, work_dir, resolve=None, platform="", measure=None):
        seen["platform"] = platform
        return ""                                   # empty chain → no -vf, encode still runs
    monkeypatch.setattr(deliver, "build_filterchain", _spy)
    monkeypatch.setattr(deliver.proc, "run", lambda cmd, **k: SimpleNamespace(stdout=b""))
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("hi", 0.0, 2.0),)).write(tj)
    deliver.deliver(str(tmp_path / "m.mp4"), REEL_H264, str(tmp_path / "out"), "v1",
                    _green(), titles=str(tj), platform="reel")
    assert seen["platform"] == "reel"


def test_deliver_cli_passes_platform(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rep = tmp_path / "r.json"
    rep.write_text('{"checks": {}, "episode_count": 0, "fail_reasons": []}')
    monkeypatch.setattr(deliver.sys, "argv",
                        ["deliver", "m.mp4", "--out-dir", str(tmp_path),
                         "--report", str(rep), "--platform", "tiktok"])
    deliver.main()
    assert seen.get("platform") == "tiktok"
