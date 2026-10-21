import json
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
    assert "-an" in cmd and cmd[-1].endswith(".REEL_v1.part.mp4") and master in cmd
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


def test_deliver_cli_passes_the_opening_fade_apart(monkeypatch, tmp_path):
    from scripts.lib.look import LookSpec
    seen = {}
    monkeypatch.setattr(deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rep = tmp_path / "r.json"
    rep.write_text('{"checks": {}, "episode_count": 0, "fail_reasons": []}')
    monkeypatch.setattr(sys, "argv",
                        ["deliver", "m.mp4", "--out-dir", str(tmp_path),
                         "--scratch-dir", str(tmp_path / "scratch"),
                         "--report", str(rep), "--fade", "0.8", "--fade-in", "0"])
    deliver.main()
    assert seen["look"] == LookSpec(fade=0.8, fade_in=0.0)


def test_a_look_with_only_an_opening_fade_still_gets_the_reels_duration(tmp_path, monkeypatch):
    """has_fade, not .fade: an opening-only look still needs the reel's duration for the
    overlap check — reading .fade passed dur=0 and fade_args refused the reel."""
    from scripts.lib.look import LookSpec
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    probed = []
    real = deliver.assembly.probe_duration
    monkeypatch.setattr(deliver.assembly, "probe_duration",
                        lambda p: probed.append(p) or (10.0 if p == master else real(p)))
    monkeypatch.setattr(deliver, "_verify_look", lambda *a, **k: [])
    deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "", rep,
                    scratch_dir=str(tmp_path / "s"), look=LookSpec(fade=0.0, fade_in=0.5))
    assert master in probed


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
                                          "overrides": [{"field": "variety_min",
                                                         "value": 4, "default": 8}],
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
    assert att.overrides == [{"field": "variety_min", "value": 4, "default": 8}]
    # design §8/§10: which clips were judged and which left the gate behind, verbatim
    assert att.episode_qc == {"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [1]}
    assert att.delivered_at                                     # non-empty ISO stamp
    assert provenance.verify_delivery(out, rehash=True)["state"] == "attested"


def test_deliver_records_the_authored_gates_it_was_handed(tmp_path, monkeypatch):
    """The attestation is where a later reader learns which bars judged the reel and why
    they were moved (design 2026-09-30 §2.4 item 2). deliver does not derive the rows — it
    holds no manifest — it carries what the driver put in run_provenance, exactly as it does
    `overrides`. The control rides in the same test, so the instrument has just been shown able
    to see the key before it reports its absence: a delivery handed no gates writes a sidecar
    with no `gates` key at all, byte-identical in shape to one made before gates existed."""
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    rows = [{"field": "entropy_floor", "value": 0.85, "default": 0.9, "scope": "episode",
             "blocking": True, "why": "log profile"}]
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                          scratch_dir=str(tmp_path / "scratch"),
                          run_provenance={"gates": rows})
    assert provenance.Attestation.from_json(provenance.attest_path(out)).gates == rows

    plain = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                            scratch_dir=str(tmp_path / "scratch"))
    assert "gates" not in provenance.attest_path(plain).read_text()


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
    # (pad 0.6*3/18 = 0.100 of h against the generic zone's 0.08 top margin), and a
    # staircase pushes the padded bottom past the frame.
    big_top = Title("hi", 0.0, 1.0, pos="top", scale=3.0)
    assert deliver._title_band(big_top, 1920, "")[0] == 0
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


def test_the_partial_does_not_raise_the_version_floor(tmp_path):
    """_next_version's glob must skip it, or a killed encode burns a version."""
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / ".REEL_v2.part.mp4").write_text("half")
    assert deliver._next_version(str(tmp_path), "mp4") == 2


def test_ffmpeg_is_handed_a_partial_never_the_delivered_name(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path), "first cut", rep,
                          scratch_dir=str(tmp_path / "scratch"))
    assert calls[0][-1] == str(tmp_path / ".REEL_v1.part.mp4")
    assert out == str(tmp_path / "REEL_v1.mp4")
    assert not (tmp_path / ".REEL_v1.part.mp4").exists()      # renamed, not copied


def test_the_partial_sits_beside_the_delivery_not_in_scratch(tmp_path, monkeypatch):
    """Same directory, so os.replace is a same-filesystem rename and therefore atomic;
    scratch_dir may be on another mount."""
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    out_dir = tmp_path / "deliveries"
    deliver.deliver(master, REEL_H264, str(out_dir), "x", rep,
                    scratch_dir=str(tmp_path / "scratch"))
    assert Path(calls[0][-1]).parent == out_dir


def test_a_killed_encode_leaves_a_partial_and_no_delivery(tmp_path, monkeypatch):
    """The whole point: the process dies inside ffmpeg. Nothing is renamed, so no file
    bears a delivered name, no version is logged, and the partial is the record."""
    real_run = deliver.proc.run
    def run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            return real_run(cmd, *a, **k)
        Path(cmd[-1]).write_bytes(b"half-an-encode")   # ffmpeg wrote some bytes...
        raise RuntimeError("killed")                    # ...then the process died
    monkeypatch.setattr(deliver.proc, "run", run)
    master, rep = _bound(tmp_path)
    with pytest.raises(RuntimeError, match="killed"):
        deliver.deliver(master, REEL_H264, str(tmp_path), "x", rep,
                        scratch_dir=str(tmp_path / "scratch"))
    assert not (tmp_path / "REEL_v1.mp4").exists()
    assert (tmp_path / ".REEL_v1.part.mp4").read_bytes() == b"half-an-encode"
    assert not (tmp_path / "VERSIONS.md").exists()
    assert not (tmp_path / "REEL_v1.attest.json").exists()


def test_the_next_delivery_after_a_kill_reuses_the_version_and_clears_the_partial(
        tmp_path, monkeypatch):
    (tmp_path / ".REEL_v1.part.mp4").write_bytes(b"half-an-encode")
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path), "retry", rep,
                          scratch_dir=str(tmp_path / "scratch"))
    assert out.endswith("REEL_v1.mp4")                 # the killed version is retried
    assert not (tmp_path / ".REEL_v1.part.mp4").exists()


def test_title_times_does_not_clamp_an_opening_that_has_no_fade():
    """retro 2026-10-16 S6: a reel that opens on picture has no fade-in ramp, so a title
    at the very start is sampled where it sits, not pushed past a ramp that is not there."""
    items = (Title("hook", 0.0, 1.0, pos="top"), Title("later", 20.0, 2.0, pos="top"))
    t_in, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0, fade_in=0.0)
    assert skipped == "" and t_in == 0.5
    assert all(w <= 33.0 for w in witnesses)          # the closing ramp still clamps


def test_verify_look_decodes_only_the_ends_a_look_declares(tmp_path, monkeypatch):
    import numpy as np
    from scripts.lib.look import LookSpec
    # an opening of 0 needs no first frame: decoding it would cost a seek for nothing
    seen = []
    monkeypatch.setattr(deliver.assembly, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(deliver.assembly, "probe_stream",
                        lambda p: SimpleNamespace(w=100, h=200, fps=30.0))
    monkeypatch.setattr(deliver.assembly, "frames_rgb",
                        lambda p, ts, fps: (seen.append(("frames", tuple(ts))),
                                            [np.zeros((200, 100, 3), np.uint8)] * len(ts))[1])
    monkeypatch.setattr(deliver.assembly, "last_frame_rgb",
                        lambda p, fps: (seen.append(("last",)), np.zeros((200, 100, 3), np.uint8))[1])
    monkeypatch.setattr(deliver.lookcheck, "evaluate", lambda *a, **k: (seen.append(("eval", k)), [])[1])
    deliver._verify_look("m.mp4", "d.mp4", LookSpec(fade=0.8, fade_in=0.0), None, "")
    assert ("frames", (0.0,)) not in seen and ("last",) in seen
    ev = next(k for tag, *rest in seen if tag == "eval" for k in rest)
    assert (ev["fade"], ev["fade_in"]) == (0.8, 0.0)


def test_the_version_log_says_whether_the_cut_changed_since_the_last_delivery(tmp_path, monkeypatch):
    """retro 2026-10-16 S11: all five lines of the second run's VERSIONS.md were the same
    words. Comparing this delivery's EDL digest with the previous attestation's says
    whether a version is a re-cut or a re-render of the same cut."""
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out_dir = str(tmp_path / "out")
    for k, digest in enumerate(("e1", "e1", "e2"), 1):
        deliver.deliver(master, REEL_H264, out_dir, f"note {k}", rep,
                        scratch_dir=str(tmp_path / "s"),
                        run_provenance={"edl": {"digest": digest, "state": "intact"}})
    lines = (Path(out_dir) / "VERSIONS.md").read_text().splitlines()
    assert lines[-3].endswith("note 1")
    assert lines[-2].endswith("note 2 · same EDL as v1")
    assert lines[-1].endswith("note 3 · EDL changed since v2")


@pytest.mark.parametrize("now,before,want", [
    ("e2", "e1", " · EDL changed since v1"),
    ("e1", "e1", " · same EDL as v1"),
    ("", "e1", ""),                 # this run carries no digest: say nothing
    ("e1", "", ""),                 # the previous one carried none: never "changed"
])
def test_since_last_says_only_what_both_digests_support(tmp_path, now, before, want):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"x")
    provenance.attest_path(reel).write_text(json.dumps(
        {"v": 1, "reel": reel.name, "reel_digest": "d", "master_digest": "m",
         "report_digest": "r", "overall": True, "edl": {"digest": before}}))
    rp = {"edl": {"digest": now}}
    assert deliver._since_last(str(tmp_path), 2, "mp4", rp) == want
    assert deliver._since_last(str(tmp_path), 1, "mp4", rp) == ""          # no previous


def test_since_last_survives_a_hand_corrupted_sidecar(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"x")
    provenance.attest_path(reel).write_text(json.dumps({"edl": "x"}))
    assert deliver._since_last(str(tmp_path), 2, "mp4", {"edl": {"digest": "e"}}) == ""


# --- the shutter flash is in the delivery and not in the master (design 2026-10-21 §4) --

def test_title_times_takes_the_longest_flash_free_part_of_its_window():
    from scripts.lib import look
    items = (Title("hook", 2.0, 1.0),)
    w = look.flash_windows([2.4], 30.0)                 # [2.3667, 2.5333)
    t_in, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0, windows=w)
    assert skipped == "" and t_in == pytest.approx((w[0][1] + 3.0) / 2)
    assert look.clear_of_flash(t_in, w) == t_in
    # with no flash the in-window time is the midpoint it always was
    assert deliver._title_times(items, 0, dur=34.0, fade=0.0)[0] == 2.5


def test_title_times_skips_a_title_that_sits_wholly_on_a_flash():
    from scripts.lib import look
    items = (Title("snap", 2.0, 0.1),)
    _, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0,
                                         windows=look.flash_windows([2.0], 30.0))
    assert "shutter flash" in skipped and "[2, 2.1]" in skipped


def test_title_times_drops_a_witness_that_sits_on_a_flash():
    """The first title-free grid instant is 6.375s; without the flash it is the first
    witness, so the drop is observable."""
    from scripts.lib import look
    items = (Title("a", 0.0, 5.0),)
    assert deliver._title_times(items, 0, dur=34.0, fade=0.0)[1][0] == pytest.approx(6.375)
    w = look.flash_windows([6.375], 30.0)
    _, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0, windows=w)
    assert skipped == "" and witnesses
    assert all(look.clear_of_flash(x, w) == x for x in witnesses)
    assert 6.375 not in witnesses


def _spy_verify(monkeypatch, seen):
    import numpy as np
    monkeypatch.setattr(deliver.assembly, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(deliver.assembly, "probe_stream",
                        lambda p: SimpleNamespace(w=100, h=200, fps=30.0))
    monkeypatch.setattr(deliver.assembly, "frames_rgb",
                        lambda p, ts, fps: (seen.append((p, tuple(ts))),
                                            [np.zeros((200, 100, 3), np.uint8)] * len(ts))[1])
    monkeypatch.setattr(deliver.assembly, "last_frame_rgb",
                        lambda p, fps: np.zeros((200, 100, 3), np.uint8))
    monkeypatch.setattr(deliver.lookcheck, "evaluate", lambda *a, **k: [])


def test_verify_look_moves_an_interior_sample_off_a_flash(monkeypatch):
    """A flash on 0.5 x the reel is exactly where the vignette is judged: the sample
    moves to the end of the flash's window, the other two stay where they were."""
    from scripts.lib import look
    from scripts.lib.look import LookSpec
    seen = []
    _spy_verify(monkeypatch, seen)
    deliver._verify_look("m.mp4", "d.mp4", LookSpec(vignette=0.3), None, "", flashes=[5.0])
    end = look.flash_windows([5.0], 30.0)[0][1]
    assert seen == [("m.mp4", (2.5, end, 7.5)), ("d.mp4", (2.5, end, 7.5))]
    seen.clear()
    deliver._verify_look("m.mp4", "d.mp4", LookSpec(vignette=0.3), None, "")
    assert seen == [("m.mp4", (2.5, 5.0, 7.5)), ("d.mp4", (2.5, 5.0, 7.5))]


def test_verify_look_keeps_the_titles_samples_off_a_flash(tmp_path, monkeypatch):
    from scripts.lib import look
    seen = []
    _spy_verify(monkeypatch, seen)
    tj = tmp_path / "TITLES.json"
    titles_lib.Titles(items=(Title("hook", 2.0, 1.0, pos="top"),)).write(tj)
    w = look.flash_windows([2.4, 6.0], 30.0)
    deliver._verify_look("m.mp4", "d.mp4", None, str(tj), "", flashes=[2.4, 6.0])
    sampled = {t for _, ts in seen for t in ts}
    assert sampled and all(look.clear_of_flash(t, w) == t for t in sampled)


def test_a_flash_alone_declares_nothing_for_the_gate_to_prove(monkeypatch):
    seen = []
    _spy_verify(monkeypatch, seen)
    assert deliver._verify_look("m.mp4", "d.mp4", None, None, "", flashes=[1.0]) == []
    assert seen == []
