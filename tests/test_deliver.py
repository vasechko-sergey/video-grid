import json
from pathlib import Path

import pytest

from scripts import deliver as deliver_mod
from scripts.lib import lookcheck, provenance
from scripts.lib.assembly import StreamInfo
from scripts.lib.look import LookSpec
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
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"))
    assert "-vf" not in calls[0]


def test_deliver_with_titles_injects_drawtext_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"), titles=str(tj))
    cmd = calls[0]
    assert "-vf" in cmd
    assert "drawtext=" in cmd[cmd.index("-vf") + 1]


def test_deliver_with_empty_titles_has_no_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    tj = tmp_path / "TITLES.json"
    Titles().write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"), titles=str(tj))
    assert "-vf" not in calls[0]


def test_deliver_with_titles_and_audio_muxes_and_burns(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"),
                        audio="a.aac", titles=str(tj))
    cmd = calls[0]
    assert "-vf" in cmd and "drawtext=" in cmd[cmd.index("-vf") + 1]
    assert cmd.count("-map") == 2 and "copy" in cmd   # mux path: -vf + -map + -c:a copy together


def test_no_look_argv_is_unchanged(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"))
    cmd = calls[-1]
    assert "-filter_complex" not in cmd
    assert "-vf" not in cmd
    assert not (tmp_path / "look_mask.png").exists()


def test_fade_only_look_stays_on_the_vf_slot(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"), look=LookSpec(fade=0.5))
    cmd = calls[-1]
    assert "-filter_complex" not in cmd
    assert cmd[cmd.index("-vf") + 1].startswith("fade=t=in:st=0:d=0.500")
    assert not (tmp_path / "look_mask.png").exists()


def test_vignette_renders_a_mask_and_moves_to_filter_complex(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"),
                        titles=str(tj), look=LookSpec(vignette=0.35))
    mask_cmd, enc = calls[-2], calls[-1]
    # the mask is rendered at the MASTER's probed dims, one frame
    assert "nullsrc=s=1080x1920:d=1:r=1" in mask_cmd
    assert "format=rgba,geq=r=0:g=0:b=0:a=" in mask_cmd[mask_cmd.index("-vf") + 1]
    assert mask_cmd[mask_cmd.index("-frames:v") + 1] == "1"
    # the encode takes the mask as input 1 and reads the video from a label
    assert enc[enc.index("-loop") + 1] == "1"
    assert enc[enc.index("-loop") + 2] == "-i"
    assert enc[enc.index("-loop") + 3].endswith("look_mask.png")
    assert enc[enc.index("-filter_complex") + 1].startswith("[0:v][1:v]overlay=shortest=1")
    assert enc[enc.index("-filter_complex") + 1].endswith("[v]")
    assert "-vf" not in enc
    # I-1 (final whole-branch review): a title actually passed in alongside a vignette
    # must survive the -filter_complex branch too. deliver builds its filtergraph in
    # two branches over the same `parts` list (titles + the bookend fade); dropping
    # *parts from the -filter_complex branch ONLY, while keeping the overlay and the
    # fade, left the WHOLE suite green (2761 passed) because no test anywhere before
    # this one exercised titles and a vignette together — every on-screen title was
    # silently deleted for `epic`/`moody`/`nostalgic`, which all ship vignette+fade.
    g = enc[enc.index("-filter_complex") + 1]
    assert "drawtext" in g, "every title vanished on the vignette branch"
    assert g.index("overlay") < g.index("drawtext")


def test_the_mask_is_sized_from_the_probed_master_not_a_constant(tmp_path, monkeypatch):
    # a hardcoded nullsrc size would pass the other vignette assertions too (they only
    # check that SOME correctly-shaped nullsrc/geq/frames:v argv was built) — this test
    # records the probe CALL, not just its return, and uses dims that appear nowhere
    # else in this file so a constant cannot coincidentally match.
    calls = _capture(monkeypatch)
    seen = []

    def _probe(path):
        seen.append(path)
        return StreamInfo(w=606, h=1078, fps=30.0, pix_fmt="yuv420p",
                          vcodec="h264", color_range="tv")

    monkeypatch.setattr(deliver_mod.assembly, "probe_stream", _probe)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"), look=LookSpec(vignette=0.35))
    assert seen == [master]                     # probed THE MASTER, not something else
    assert "nullsrc=s=606x1078:" in " ".join(calls[-2])   # and spent what it returned


def test_audio_input_index_shifts_when_a_mask_is_present(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    master, rep = _bound(tmp_path)
    stem = tmp_path / "stem.aac"
    stem.write_bytes(b"aac-bytes")
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"),
                        audio=str(stem), look=LookSpec(vignette=0.35))
    enc = calls[-1]
    # master=0, mask=1, audio=2 — mapping 1:a:0 here would mux the PNG
    assert "2:a:0" in enc
    assert "1:a:0" not in enc


def test_audio_input_index_is_one_without_a_mask(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    master, rep = _bound(tmp_path)
    stem = tmp_path / "stem.aac"
    stem.write_bytes(b"aac-bytes")
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"), audio=str(stem))
    assert "1:a:0" in calls[-1]


def test_titles_and_fade_share_one_slot_in_the_right_order(tmp_path, monkeypatch):
    # titles first, fade last — the chain order look.chain owns
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"),
                        titles=str(tj), look=LookSpec(fade=0.5))
    graph = calls[-1][calls[-1].index("-vf") + 1]
    assert graph.index("drawtext") < graph.index("fade=t=in")


def _finding(check="vignette", status="fail"):
    return lookcheck.LookFinding(check=check, status=status, detail="d",
                                 measured=0.4, expected=2.0)


def test_deliver_refuses_a_declared_look_that_changed_nothing(tmp_path, monkeypatch):
    """The cinematic-look review found a filter-list drop that would have silently
    killed the bookend and every title for three of four mood presets. This is the
    gate for that class."""
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    # look=vignette>0 hits the pre-existing _render_mask path (assembly.probe_stream on
    # the master) before _verify_look is ever reached — unrelated to this task's gate,
    # but the fake "master-bytes" file needs the same probe_stream stub the pre-existing
    # vignette tests above already use, or proc.run's stub-return None crashes it first.
    monkeypatch.setattr(deliver_mod.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [_finding()])
    with pytest.raises(RuntimeError, match="does not carry the look it declared"):
        deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "v", rep,
                            scratch_dir=str(tmp_path / "scratch"), look=LookSpec(vignette=0.3))


def test_deliver_writes_no_attestation_when_the_look_gate_fails(tmp_path, monkeypatch):
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    # look=fade>0 hits the pre-existing `dur = assembly.probe_duration(master)` line
    # before _verify_look is reached — same fixture gap as above, other constant.
    monkeypatch.setattr(deliver_mod.assembly, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(deliver_mod, "_verify_look",
                        lambda *a, **kw: [_finding(check="fade")])
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError):
        deliver_mod.deliver(master, REEL_H264, str(out_dir), "v", rep,
                            scratch_dir=str(tmp_path / "scratch"), look=LookSpec(fade=0.5))
    assert list(out_dir.glob("REEL_v*.mp4"))                  # the file is left to look at
    assert not list(out_dir.glob("*.attest.json"))            # but nothing attests it


def test_deliver_records_the_look_checks_in_the_attestation(tmp_path, monkeypatch):
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [
        lookcheck.LookFinding(check="vignette", status="not-checked",
                              detail="corners already black", measured=3.0,
                              expected=8.0)])
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "v", rep,
                              scratch_dir=str(tmp_path / "scratch"), look=LookSpec(vignette=0.3))
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    assert att["look_checks"] == [{"check": "vignette", "status": "not-checked",
                                   "detail": "corners already black",
                                   "measured": 3.0, "expected": 8.0}]


def test_a_look_less_delivery_runs_no_look_check_at_all(tmp_path, monkeypatch):
    """Zero cost and zero blast radius when nothing was declared."""
    master, rep = _bound(tmp_path)
    _capture(monkeypatch)
    calls: list = []
    monkeypatch.setattr(deliver_mod.assembly, "frames_rgb",
                        lambda *a, **kw: calls.append(a) or [])
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "v", rep,
                              scratch_dir=str(tmp_path / "scratch"))
    assert calls == []
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    assert att["look_checks"] == []
