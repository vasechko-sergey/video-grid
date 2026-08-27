import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deliver
from scripts.lib import provenance, titles as titles_lib
from scripts.lib.titles import Title
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
        deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "x", _red(),
                        scratch_dir=str(tmp_path / "scratch"))


def test_deliver_refuses_a_failed_reel_leaves_no_side_effects(tmp_path, monkeypatch):
    # the gate must fire BEFORE any mkdir/encode/version-bump: a failed reel
    # produces no out dir, no scratch dir, no file, no VERSIONS.md, and never calls proc.run.
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    out_dir = tmp_path / "would-be-created"
    scratch_dir = tmp_path / "scratch"
    with pytest.raises(RuntimeError, match="does not ship a failed reel"):
        deliver.deliver("m.mp4", REEL_H264, str(out_dir), "x", _red(),
                        scratch_dir=str(scratch_dir))
    assert not out_dir.exists()
    assert not scratch_dir.exists()
    assert calls == []


def test_deliver_encodes_v1_and_logs(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path), "first cut", rep,
                          scratch_dir=str(tmp_path / "scratch"))
    assert out.endswith("REEL_v1.mp4")
    cmd = calls[0]
    assert "-an" in cmd and cmd[-1].endswith("REEL_v1.mp4") and master in cmd
    assert "scale=" not in " ".join(map(str, cmd))          # no re-scale
    assert (tmp_path / "VERSIONS.md").read_text().count("- v1 |") == 1


def test_deliver_second_run_is_v2(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    scratch_dir = str(tmp_path / "scratch")
    deliver.deliver(master, REEL_H264, str(tmp_path), "a", rep,
                    scratch_dir=scratch_dir)  # _fake_encode writes REEL_v1 for real
    out2 = deliver.deliver(master, REEL_H264, str(tmp_path), "b", rep, scratch_dir=scratch_dir)
    assert out2.endswith("REEL_v2.mp4")


def test_deliver_muxes_audio_when_given(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "v1",
                    rep, scratch_dir=str(tmp_path / "scratch"), audio=str(tmp_path / "a.m4a"))
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
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "v1", rep,
                    scratch_dir=str(tmp_path / "scratch"))
    assert "-an" in calls[0] and "1:a:0" not in calls[0]


def test_deliver_mux_forces_copy_over_profile_acodec(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    prof = ExportProfile(acodec="aac", abitrate_kbps=192)
    deliver.deliver(master, prof, str(tmp_path / "out"), "v1",
                    rep, scratch_dir=str(tmp_path / "scratch"), audio=str(tmp_path / "a.m4a"))
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
    # titles=... makes deliver's post-encode look gate (_verify_look) sample real
    # frames from the fake encoded file this test's stub produces; irrelevant to what
    # this test checks (platform threading into build_filterchain), so stub it away
    # the same way tests/test_deliver.py isolates it in its own argv-shape tests.
    monkeypatch.setattr(deliver, "_verify_look", lambda *a, **kw: [])
    master, rep = _bound(tmp_path)
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("hi", 0.0, 2.0),)).write(tj)
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "v1",
                    rep, scratch_dir=str(tmp_path / "scratch"), titles=str(tj), platform="reel")
    assert seen["platform"] == "reel"


def test_deliver_cli_passes_platform(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rep = tmp_path / "r.json"
    rep.write_text('{"checks": {}, "episode_count": 0, "fail_reasons": []}')
    monkeypatch.setattr(sys, "argv",
                        ["deliver", "m.mp4", "--out-dir", str(tmp_path),
                         "--scratch-dir", str(tmp_path / "scratch"),
                         "--report", str(rep), "--platform", "tiktok"])
    deliver.main()
    assert seen.get("platform") == "tiktok"


def test_deliver_refuses_a_report_with_no_master_digest(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master = tmp_path / "m.mp4"
    master.write_bytes(b"x")
    rep = ReelReport(checks={"length": CheckResult("length", True, {})})   # unbound
    with pytest.raises(RuntimeError, match="did not come from check_reel"):
        deliver.deliver(str(master), REEL_H264, str(tmp_path / "out"), "x", rep,
                        scratch_dir=str(tmp_path / "scratch"))


def test_deliver_refuses_a_report_bound_to_a_different_master(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    Path(master).write_bytes(b"hand-assembled-instead")        # the #13 bypass
    with pytest.raises(RuntimeError, match="different file"):
        deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                        scratch_dir=str(tmp_path / "scratch"))


def test_deliver_writes_an_attestation_beside_the_reel(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "first cut", rep,
                          scratch_dir=str(tmp_path / "scratch"),
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
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                          scratch_dir=str(tmp_path / "scratch"))
    assert provenance.attest_path(out).exists()


def test_an_unjudged_delivery_says_so(tmp_path, monkeypatch):
    # design §10: edl_to_reel with neither two-phase flag is still the SP1 front door
    # for a hand-authored EDL, and it ships a reel no judge saw — the attestation makes
    # that distinguishable rather than silently looking like a judged one.
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                          scratch_dir=str(tmp_path / "scratch"),
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
        deliver.deliver("does-not-exist.mp4", REEL_H264, str(tmp_path / "out"), "x", rep,
                        scratch_dir=str(tmp_path / "scratch"))
    assert calls == [] and not (tmp_path / "out").exists()


def test_the_version_note_is_the_reason_not_a_path(tmp_path, monkeypatch):
    # #16: 12 of 13 entries in a real run's VERSIONS.md logged the path of
    # VERSIONS.md itself as the note. The bug was in the caller (Task 4), but the
    # log must never accept a value that is obviously the log's own path.
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out_dir = tmp_path / "out"
    deliver.deliver(master, REEL_H264, str(out_dir), "regraded ep1", rep,
                    scratch_dir=str(tmp_path / "scratch"))
    text = (out_dir / "VERSIONS.md").read_text()
    assert "regraded ep1" in text
    assert "VERSIONS.md" not in text.split("\n", 2)[-1]


def test_title_times_clamps_the_in_window_sample_out_of_the_fade_in():
    """measured (design 2026-08-19 §4): a t_in at alpha 0.10 scores 0.0000% on a
    correctly rendered title — a false FAIL on a no-waiver gate.

    The title has to STRADDLE the ramp for this to discriminate: with a window wide
    enough to hold its own midpoint clear of the fade, the clamp is a no-op and
    dropping it changes nothing (mutation battery row 10 survived that version).
    Here [0.0, 1.2] against a 1.0s fade has an unclamped midpoint of 0.6, inside the
    ramp; clamped, the window is [1.0, 1.2] and the midpoint 1.1."""
    items = (Title("hook", 0.0, 1.2),)
    t_in, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0)
    assert skipped == ""
    assert t_in == pytest.approx(1.1)


def test_title_times_clamps_the_witness_out_of_the_fade_out():
    """The other end, and the dangerous one: a witness faded toward black makes
    |d_in - d_out| large with no title involved, which is a false PASS (measured 4.6x
    inflation).

    Same discrimination problem in reverse — the tail candidate is only ever sampled
    when the titles cover everything before it, so the title runs to 31.0s of a 34s
    reel. Unclamped, the last free instant is 33.31; clamped, 32.33."""
    items = (Title("hook", 0.0, 31.0),)
    _, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0)
    assert skipped == "" and witnesses
    assert max(witnesses) <= 33.0


def test_title_times_keeps_every_sample_inside_the_legal_window():
    items = (Title("hook", 0.0, 3.0),)
    t_in, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0)
    assert skipped == "" and witnesses
    assert 1.0 <= t_in <= 33.0
    assert all(1.0 <= w <= 33.0 for w in witnesses)


def test_title_times_skips_a_title_buried_in_the_fade():
    items = (Title("hook", 0.0, 0.5),)
    _, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0)
    assert "bookend fade" in skipped


def test_title_times_skips_when_the_fade_covers_the_whole_reel():
    items = (Title("hook", 0.0, 3.0),)
    _, _, skipped = deliver._title_times(items, 0, dur=4.0, fade=2.0)
    assert "whole" in skipped


def test_title_times_skips_when_no_instant_is_title_free():
    items = (Title("a", 0.0, 20.0), Title("b", 19.0, 15.0))
    _, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0)
    assert "title-free" in skipped


def test_title_times_witness_avoids_every_titles_window():
    items = (Title("a", 0.0, 5.0), Title("b", 20.0, 5.0))
    _, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0)
    assert skipped == "" and witnesses
    for w in witnesses:
        assert not (0.0 <= w <= 5.0) and not (20.0 <= w <= 25.0)


def test_title_band_pads_the_extent_and_clamps_to_the_frame():
    t = Title("hi", 0.0, 1.0, pos="bottom")
    lo, hi = deliver._title_band(t, 1920, "reels")
    top, bottom = titles_lib.ink_extent(t, "reels")
    assert lo < top * 1920 and hi > bottom * 1920      # padded on BOTH sides
    assert 0 <= lo < hi <= 1920
    # the clamps, at both ends. A big enough font pushes the padded top negative
    # (pad 0.6*3/18 = 0.100 of h against the reels zone's 0.08 top margin), and a
    # staircase pushes the padded bottom past the frame.
    big_top = Title("hi", 0.0, 1.0, pos="top", scale=3.0)
    assert deliver._title_band(big_top, 1920, "reels")[0] == 0
    stair = Title("a\nb\nc\nd", 0.0, 4.0, pos="bottom", reveal="stair", reveal_step=0.4)
    assert deliver._title_band(stair, 1920, "reels")[1] == 1920


def test_the_next_version_reads_the_log_when_the_file_is_gone(tmp_path):
    """R5.1, measured: 14 delivering runs left 2 log records because _next_version
    counted surviving files, so numbering restarted and three different reels
    shipped as REEL_v1.mp4."""
    (tmp_path / "VERSIONS.md").write_text(
        "# Reel versions\n\n- v1 | 2026-08-25 | first\n- v2 | 2026-08-25 | second\n")
    assert deliver._next_version(str(tmp_path), "mp4") == 3


def test_the_next_version_takes_the_higher_of_log_and_files(tmp_path):
    """The glob stays as a FLOOR: a log deleted by hand must not renumber over a
    reel that is still on disk."""
    (tmp_path / "VERSIONS.md").write_text("# Reel versions\n\n- v1 | 2026-08-25 | a\n")
    (tmp_path / "REEL_v4.mp4").write_bytes(b"x")
    assert deliver._next_version(str(tmp_path), "mp4") == 5


def test_the_next_version_is_one_on_an_empty_directory(tmp_path):
    assert deliver._next_version(str(tmp_path), "mp4") == 1


def test_the_log_reader_ignores_prose(tmp_path):
    # The regex must require the pipe anchor to reject a line that starts with "- v"
    # but isn't a log entry (e.g. a hand-written note between entries). Both "version 7
    # was skipped" (no "- v" prefix) and "- v9 not a real entry" (no pipe anchor) must
    # be ignored, only "[2]" returned.
    (tmp_path / "VERSIONS.md").write_text(
        "# Reel versions\n\nversion 7 was skipped\n- v9 not a real entry\n- v2 | 2026-08-25 | real\n")
    assert deliver._logged_versions(str(tmp_path)) == [2]


def test_the_log_reader_is_empty_with_no_log(tmp_path):
    assert deliver._logged_versions(str(tmp_path)) == []


def test_deliver_refuses_a_scratch_dir_equal_to_the_out_dir(tmp_path):
    """The required keyword proves a caller passed SOMETHING; only this proves it
    passed a different directory. The final review measured that swapping
    build_reel's `scratch_dir=work_dir` to `out_dir` left the whole suite
    byte-identical — that call site is the one production line keeping the mask and
    title sidecars out of the append-only bucket, and nothing failed when it broke."""
    master, rep = _bound(tmp_path)
    out_dir = tmp_path / "deliveries"
    with pytest.raises(ValueError) as e:
        deliver.deliver(master, REEL_H264, str(out_dir), "x", rep,
                        scratch_dir=str(out_dir))
    assert "same directory" in str(e.value)


def test_deliver_requires_a_scratch_dir():
    """deliveries/ is append-only; the mask and the title sidecars are scratch.
    A default of out_dir would keep the leak one forgotten argument away."""
    import inspect
    p = inspect.signature(deliver.deliver).parameters["scratch_dir"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is inspect.Parameter.empty
