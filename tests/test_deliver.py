import json
from pathlib import Path

import pytest

from scripts import deliver as deliver_mod
from scripts.lib import look as look_lib, lookcheck, provenance
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


def test_deliver_with_titles_injects_drawtext_vf(tmp_path, monkeypatch, make_ttf):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    make_ttf(f, [ord(c) for c in "Hook"])   # a font that draws the title
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


def test_deliver_with_titles_and_audio_muxes_and_burns(tmp_path, monkeypatch, make_ttf):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    make_ttf(f, [ord(c) for c in "Hook"])   # a font that draws the title
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


def test_vignette_renders_a_mask_and_moves_to_filter_complex(tmp_path, monkeypatch, make_ttf):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    make_ttf(f, [ord(c) for c in "Hook"])   # a font that draws the title
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


def test_titles_and_fade_share_one_slot_in_the_right_order(tmp_path, monkeypatch, make_ttf):
    # titles first, fade last — the chain order look.chain owns
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod.assembly, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **kw: [])
    f = tmp_path / "f.ttf"
    make_ttf(f, [ord(c) for c in "Hook"])   # a font that draws the title
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


# --- the shutter accent's flash (design 2026-10-21 §4) --------------------------------

def _stub_probes(monkeypatch, *, dur=10.0, fps=30.0, seen=None):
    def stream(p):
        if seen is not None:
            seen.append(("stream", p))
        return StreamInfo(1080, 1920, fps, "yuv420p", "h264")

    def duration(p):
        if seen is not None:
            seen.append(("duration", p))
        return dur
    monkeypatch.setattr(deliver_mod.assembly, "probe_stream", stream)
    monkeypatch.setattr(deliver_mod.assembly, "probe_duration", duration)


def _encode_argv(tmp_path, monkeypatch, **kw):
    """The encode argv of one delivery, with the look gate stubbed (its own tests are in
    tests/lib/test_deliver.py)."""
    calls = _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **k: [])
    master, rep = _bound(tmp_path)
    deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "cl", rep,
                        scratch_dir=str(tmp_path / "scratch"), **kw)
    return calls[-1], master


def test_a_delivery_with_no_flash_keeps_its_argv_byte_for_byte(tmp_path, monkeypatch):
    """Pinned before the flash existed: a vignette + fade + stem delivery, and a plain
    one. Passing no flash, or an empty list, changes neither."""
    _stub_probes(monkeypatch)
    stem = tmp_path / "stem.aac"
    stem.write_bytes(b"aac-bytes")
    ff = deliver_mod.ffbin.ffmpeg()
    for k, extra in enumerate(({}, {"flashes": ()}, {"flashes": []})):
        d = tmp_path / f"v{k}"
        d.mkdir()
        cmd, master = _encode_argv(d, monkeypatch, audio=str(stem),
                                   look=LookSpec(vignette=0.3, fade=0.5), **extra)
        assert cmd == [ff, "-y", "-i", master, "-loop", "1", "-i",
                       str(d / "scratch" / "look_mask.png"), "-i", str(stem),
                       "-filter_complex",
                       "[0:v][1:v]overlay=shortest=1,fade=t=in:st=0:d=0.500,"
                       "fade=t=out:st=9.500:d=0.500[v]",
                       *deliver_mod._video_only_args(REEL_H264), "-map", "[v]",
                       "-map", "2:a:0", "-c:a", "copy", "-shortest",
                       str(d / "out" / ".REEL_v1.part.mp4")]
        d = tmp_path / f"p{k}"
        d.mkdir()
        cmd, master = _encode_argv(d, monkeypatch, **extra)
        assert cmd == [ff, "-y", "-i", master, *REEL_H264.args(),
                       str(d / "out" / ".REEL_v1.part.mp4")]


def test_the_attestation_lists_the_flashes_and_a_delivery_without_one_has_no_key(
        tmp_path, monkeypatch):
    """design 2026-10-21 §4: the delivered file is deliberately not the master at the
    accents, and the attestation is where a reader holding master_digest looks."""
    _stub_probes(monkeypatch)
    _capture(monkeypatch)
    monkeypatch.setattr(deliver_mod, "_verify_look", lambda *a, **k: [])
    for name, extra, want in (("a", {"flashes": [1.0, 2.0 + 1 / 3]}, [1.0, 2.333333]),
                              ("b", {}, None)):
        d = tmp_path / name
        d.mkdir()
        master, rep = _bound(d)
        out = deliver_mod.deliver(master, REEL_H264, str(d / "out"), "cl", rep,
                                  scratch_dir=str(d / "scratch"), **extra)
        att = json.loads(Path(provenance.attest_path(out)).read_text())
        assert att.get("flashes") == want


def test_a_flash_alone_still_takes_the_vf_slot(tmp_path, monkeypatch):
    seen = []
    _stub_probes(monkeypatch, seen=seen)
    cmd, master = _encode_argv(tmp_path, monkeypatch, flashes=[1.0, 2.5])
    assert "-filter_complex" not in cmd
    assert cmd[cmd.index("-vf") + 1] == ",".join(look_lib.flash_args([1.0, 2.5], 30.0))
    assert ("stream", master) in seen                   # the flash is placed at the MASTER's rate


def test_the_flash_rides_after_the_vignette_and_before_the_titles_and_fade(tmp_path,
                                                                         monkeypatch, make_ttf):
    _stub_probes(monkeypatch, fps=25.0)
    f = tmp_path / "f.ttf"
    make_ttf(f, [ord(c) for c in "Hook"])
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    cmd, _ = _encode_argv(tmp_path, monkeypatch, titles=str(tj),
                          look=LookSpec(vignette=0.3, fade=0.5), flashes=[4.0])
    g = cmd[cmd.index("-filter_complex") + 1]
    flash = ",".join(look_lib.flash_args([4.0], 25.0))
    assert g.startswith("[0:v][1:v]overlay=shortest=1," + flash + ",drawtext=")
    assert g.index("drawtext") < g.index("fade=t=in") and g.endswith("[v]")


def test_no_flash_probes_nothing_it_did_not_probe_before(tmp_path, monkeypatch):
    seen = []
    _stub_probes(monkeypatch, seen=seen)
    _encode_argv(tmp_path, monkeypatch)
    assert seen == []


def test_a_flash_whose_frames_do_not_fit_in_the_reel_is_refused_before_the_encode(
        tmp_path, monkeypatch):
    """A flash needs its three frames and a frame after them inside the reel; one placed
    later renders partly or not at all, and nothing would notice."""
    _stub_probes(monkeypatch, dur=10.0, fps=30.0)
    calls = _capture(monkeypatch)
    master, rep = _bound(tmp_path)
    with pytest.raises(ValueError, match=r"flash at 9\.9s.*10s reel"):
        deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "cl", rep,
                            scratch_dir=str(tmp_path / "scratch"), flashes=[1.0, 9.9])
    assert calls == []
    _encode_argv(tmp_path, monkeypatch, flashes=[10.0 - 4 / 30])   # the last one that fits
