import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deliver
from scripts.lib import provenance
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


def _red():
    return ReelReport(checks={"length": CheckResult("length", False, {})}, episode_count=2)


def _bound(tmp_path, *, passing=True):
    """A master that exists on disk plus a report bound to it — the only shape
    deliver accepts now."""
    master = tmp_path / "m.mp4"
    master.write_bytes(b"master-bytes")
    rep = ReelReport(checks={"length": CheckResult("length", passing, {})}, episode_count=2,
                     master_digest=provenance.digest_file(master))
    return str(master), rep


def _fake_encode(monkeypatch, calls=None):
    """ffmpeg stub that actually PRODUCES its output file — deliver now hashes the
    delivered reel for the attestation, so a stub that writes nothing is not a stub
    of ffmpeg.

    Passes a `git` argv through to the REAL proc.run: deliver.proc and
    provenance.proc are the same module object (both do `from scripts.lib import
    proc`), so a blanket monkeypatch here also swallows engine_stamp()'s git
    shell-out — without this passthrough it returns a bare SimpleNamespace with no
    `returncode`/`stdout`, and provenance._git blows up on `r.returncode`."""
    real_run = deliver.proc.run
    def run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            return real_run(cmd, *a, **k)
        if calls is not None:
            calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"encoded-reel")
        return SimpleNamespace(stdout=b"")
    monkeypatch.setattr(deliver.proc, "run", run)


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
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path), "first cut", rep)
    assert out.endswith("REEL_v1.mp4")
    cmd = calls[0]
    assert "-an" in cmd and cmd[-1].endswith("REEL_v1.mp4") and master in cmd
    assert "scale=" not in " ".join(map(str, cmd))          # no re-scale
    assert (tmp_path / "VERSIONS.md").read_text().count("- v1 |") == 1


def test_deliver_second_run_is_v2(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    deliver.deliver(master, REEL_H264, str(tmp_path), "a", rep)  # _fake_encode writes REEL_v1 for real
    out2 = deliver.deliver(master, REEL_H264, str(tmp_path), "b", rep)
    assert out2.endswith("REEL_v2.mp4")


def test_deliver_muxes_audio_when_given(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "v1",
                    rep, audio=str(tmp_path / "a.m4a"))
    cmd = calls[0]
    assert str(tmp_path / "a.m4a") in cmd and cmd.count("-i") == 2
    assert "0:v:0" in cmd and "1:a:0" in cmd
    assert "-an" not in cmd                              # profile's video-only -an is stripped for the mux
    assert "-shortest" in cmd
    assert cmd.count("-c:a") == 1 and cmd[cmd.index("-c:a") + 1] == "copy"


def test_deliver_silent_when_no_audio(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "v1", rep)
    assert "-an" in calls[0] and "1:a:0" not in calls[0]


def test_deliver_mux_forces_copy_over_profile_acodec(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    prof = ExportProfile(acodec="aac", abitrate_kbps=192)
    deliver.deliver(master, prof, str(tmp_path / "out"), "v1",
                    rep, audio=str(tmp_path / "a.m4a"))
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
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("hi", 0.0, 2.0),)).write(tj)
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "v1",
                    rep, titles=str(tj), platform="reel")
    assert seen["platform"] == "reel"


def test_deliver_cli_passes_platform(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rep = tmp_path / "r.json"
    rep.write_text('{"checks": {}, "episode_count": 0, "fail_reasons": []}')
    monkeypatch.setattr(sys, "argv",
                        ["deliver", "m.mp4", "--out-dir", str(tmp_path),
                         "--report", str(rep), "--platform", "tiktok"])
    deliver.main()
    assert seen.get("platform") == "tiktok"


def test_deliver_refuses_a_report_with_no_master_digest(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master = tmp_path / "m.mp4"
    master.write_bytes(b"x")
    rep = ReelReport(checks={"length": CheckResult("length", True, {})})   # unbound
    with pytest.raises(RuntimeError, match="did not come from check_reel"):
        deliver.deliver(str(master), REEL_H264, str(tmp_path / "out"), "x", rep)


def test_deliver_refuses_a_report_bound_to_a_different_master(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    Path(master).write_bytes(b"hand-assembled-instead")        # the #13 bypass
    with pytest.raises(RuntimeError, match="different file"):
        deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep)


def test_deliver_writes_an_attestation_beside_the_reel(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "first cut", rep,
                          run_provenance={"engine_at_start": {"sha": "aaa", "dirty": False},
                                          "edl": {"digest": "e", "state": "intact"},
                                          "overrides": [{"field": "color_delta_max",
                                                         "value": 20.0, "default": 12.0}],
                                          "episode_qc": {"state": "judged",
                                                         "judged": {"0": "aa"},
                                                         "reprocessed_after": [1]}})
    att = provenance.Attestation.from_json(provenance.attest_path(out))
    assert att.reel == "REEL_v1.mp4"
    assert att.master_digest == rep.master_digest
    assert att.reel_digest == provenance.digest_file(out)
    assert att.overall is True
    assert att.engine_at_start == {"sha": "aaa", "dirty": False}
    assert att.engine_at_deliver["sha"] == provenance.engine_stamp()["sha"]
    assert att.edl == {"digest": "e", "state": "intact"}
    assert att.overrides == [{"field": "color_delta_max", "value": 20.0, "default": 12.0}]
    # design §8/§10: which clips were judged and which left the gate behind, verbatim
    assert att.episode_qc == {"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [1]}
    assert att.delivered_at                                     # non-empty ISO stamp
    assert provenance.verify_delivery(out, rehash=True)["state"] == "attested"


def test_deliver_attests_without_run_provenance(tmp_path, monkeypatch):
    # build_reel may deliver a manifest that carries none — the sidecar still lands
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep)
    assert provenance.attest_path(out).exists()


def test_an_unjudged_delivery_says_so(tmp_path, monkeypatch):
    # design §10: edl_to_reel with neither two-phase flag is still the SP1 front door
    # for a hand-authored EDL, and it ships a reel no judge saw — the attestation makes
    # that distinguishable rather than silently looking like a judged one.
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                          run_provenance={"episode_qc": {"state": "absent"}})
    att = provenance.Attestation.from_json(provenance.attest_path(out))
    assert att.episode_qc == {"state": "absent"}


def test_the_failed_reel_gate_still_fires_before_any_hashing(tmp_path, monkeypatch):
    # ordering matters: a failed reel must produce no out dir, no file, no hashing —
    # so the overall gate stays FIRST, before the master is even read
    calls = []
    monkeypatch.setattr(deliver.proc, "run", lambda cmd, *a, **k: calls.append(cmd))
    rep = ReelReport(checks={"length": CheckResult("length", False, {})})
    with pytest.raises(RuntimeError, match="does not ship a failed reel"):
        deliver.deliver("does-not-exist.mp4", REEL_H264, str(tmp_path / "out"), "x", rep)
    assert calls == [] and not (tmp_path / "out").exists()


def test_the_version_note_is_the_reason_not_a_path(tmp_path, monkeypatch):
    # #16: 12 of 13 entries in a real run's VERSIONS.md logged the path of
    # VERSIONS.md itself as the note. The bug was in the caller (Task 4), but the
    # log must never accept a value that is obviously the log's own path.
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out_dir = tmp_path / "out"
    deliver.deliver(master, REEL_H264, str(out_dir), "regraded ep1", rep)
    text = (out_dir / "VERSIONS.md").read_text()
    assert "regraded ep1" in text
    assert "VERSIONS.md" not in text.split("\n", 2)[-1]
