import json
from pathlib import Path

from scripts import deliver as deliver_mod
from scripts.lib import provenance
from scripts.lib.models import CheckResult, REEL_H264, ReelReport
from scripts.lib.titles import Title, Titles


def _bound(tmp_path, *, passing=True):
    """A master that exists on disk plus a report bound to it — the only shape
    deliver accepts now. ReelReport.overall is a computed property (all checks
    passed, none False) — there is no overall=/failures= constructor kwarg
    (scripts/lib/models.py)."""
    master = tmp_path / "m.mp4"
    master.write_bytes(b"master-bytes")
    rep = ReelReport(checks={"length": CheckResult("length", passing, {})},
                     master_digest=provenance.digest_file(master))
    return str(master), rep


def _capture(monkeypatch):
    """ffmpeg stub that PRODUCES its output file (deliver now hashes it for the
    attestation) and passes a `git` argv through to the REAL proc.run: deliver_mod.proc
    and provenance.proc are the same module object, so a blanket monkeypatch here
    would otherwise also swallow engine_stamp()'s git shell-out inside deliver()."""
    calls = []
    real_run = deliver_mod.proc.run
    def run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            return real_run(cmd, *a, **k)
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"encoded-reel")
        return None
    monkeypatch.setattr(deliver_mod.proc, "run", run)
    return calls


def test_deliver_without_titles_has_no_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep)
    assert "-vf" not in calls[0]


def test_deliver_with_titles_injects_drawtext_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep, titles=str(tj))
    cmd = calls[0]
    assert "-vf" in cmd
    assert "drawtext=" in cmd[cmd.index("-vf") + 1]


def test_deliver_with_empty_titles_has_no_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    tj = tmp_path / "TITLES.json"
    Titles().write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep, titles=str(tj))
    assert "-vf" not in calls[0]


def test_deliver_with_titles_and_audio_muxes_and_burns(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        audio="a.aac", titles=str(tj))
    cmd = calls[0]
    assert "-vf" in cmd and "drawtext=" in cmd[cmd.index("-vf") + 1]
    assert cmd.count("-map") == 2 and "copy" in cmd   # mux path: -vf + -map + -c:a copy together


def test_the_attestation_carries_the_qc_state(tmp_path, monkeypatch):
    # design §10: the attestation records which clip digests were judged and which
    # episodes build_reel re-rendered after the verdict (design §8) — both threaded
    # through run_provenance["episode_qc"] verbatim into the sidecar.
    _capture(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path), "note", rep, run_provenance={
        "engine_at_start": {}, "edl": {}, "overrides": [],
        "episode_qc": {"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [1]}})
    att = json.loads(provenance.attest_path(out).read_text())
    assert att["episode_qc"] == {"state": "judged", "judged": {"0": "aa"},
                                 "reprocessed_after": [1]}


def test_an_unjudged_delivery_says_so(tmp_path, monkeypatch):
    # design §10: edl_to_reel with neither two-phase flag is still the SP1 front door
    # for a hand-authored EDL, and it ships a reel no judge saw — the attestation makes
    # that distinguishable rather than silently looking like a judged one.
    _capture(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path), "note", rep,
                              run_provenance={"episode_qc": {"state": "absent"}})
    assert json.loads(provenance.attest_path(out).read_text())["episode_qc"] == {"state": "absent"}
