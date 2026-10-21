from pathlib import Path

import pytest

from scripts import extract
from scripts.lib import lint
from scripts.lib.edl import EDL, EDLEpisode


def _edl(**kw):
    # NOTE: composition="lead" (not "thirds" — "thirds" is a GRIDS member, not a
    # COMPOSITIONS member; see scripts/lib/models.py COMPOSITIONS/GRIDS).
    base = dict(source="a.mp4", start=0.0, dur=4.0, shot_type="medium",
                composition="lead", grid="thirds")
    return EDL(episodes=[EDLEpisode(**{**base, **kw})])


def test_extract_edl_retimes_a_ramped_segment_in_place(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    seg = tmp_path / "seg"
    calls = {}

    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"raw"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 4.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 60.0, "w": 1920, "h": 1080})())

    def fake_retime(src, dst, spec, dur, fps):
        calls["args"] = (src, dst, spec.factor, dur, fps)
        Path(dst).write_bytes(b"ramped")
        return dst

    monkeypatch.setattr(extract.ramp, "retime", fake_retime)
    out = extract.extract_edl(
        _edl(ramp={"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}),
        str(tmp_path), str(seg))

    assert out == [str(seg / "ep0_raw.mp4")]
    # the RETIMED bytes must sit at the raw name: draft.py and the reel manifest
    # both reference ep{i}_raw.mp4, so a ramp written beside it would be ignored
    assert (seg / "ep0_raw.mp4").read_bytes() == b"ramped"
    assert calls["args"][2:] == (0.4, 4.0, 60.0)


def test_extract_edl_leaves_an_unramped_segment_untouched(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    seg = tmp_path / "seg"
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"raw"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 4.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 60.0, "w": 1920, "h": 1080})())
    monkeypatch.setattr(extract.ramp, "retime",
                        lambda *a, **k: pytest.fail("no ramp, no retime"))
    extract.extract_edl(_edl(), str(tmp_path), str(seg))
    assert (seg / "ep0_raw.mp4").read_bytes() == b"raw"


def test_extract_edl_refuses_a_juddering_ramp_at_the_probed_rate(monkeypatch, tmp_path):
    # The EDL may have been hand-authored past edit_plan's early gate; this is the
    # gate against the fps that actually ships.
    (tmp_path / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"raw"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 4.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 30.0, "w": 1920, "h": 1080})())
    with pytest.raises(ValueError, match="unique frames per second"):
        extract.extract_edl(
            _edl(ramp={"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}),
            str(tmp_path), str(tmp_path / "seg"))


def test_extract_normalizes_the_range_and_keeps_the_seek_order(monkeypatch, tmp_path):
    """Both halves are emitted — and this test is why that can be checked at all.

    Measured 2026-08-27: given `-pix_fmt yuv420p`, the filter alone, the tag alone
    and both together produce byte-identical output, so no assertion over rendered
    pixels can notice one of them going missing or going wrong. The argv IS the
    only place the difference exists. And -ss still lands after -i (§12)."""
    seen = {}
    monkeypatch.setattr(extract.proc, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    extract.extract("a.mp4", 1.0, 2.0, str(tmp_path / "o.mp4"))
    cmd = seen["cmd"]
    assert cmd[cmd.index("-vf") + 1] == "scale=in_range=auto:out_range=tv"
    assert cmd[cmd.index("-color_range") + 1] == "tv"
    assert cmd.index("-ss") > cmd.index("-i")
    # The equality above is what pins "no dimensions in the scale" — resolution
    # stays native because reframe crops from native pixels (design §3). Do not
    # replace it with a looser digit scan: `"scale=640:360:in_range=auto:out_range=tv"
    # .split("=")` yields no element for which `.isdigit()` is true, so a scan
    # like that reads as a guard and catches nothing.


def test_extract_names_tv_not_pc_in_the_scale_filter(monkeypatch, tmp_path):
    """Mutation battery row 12 (2026-08-27): `out_range=tv` -> `out_range=pc`, the
    filter half now asking for the WRONG range while `-color_range tv` still asks
    for the right one. Measured: on the shipped ffmpeg this stays byte-identical at
    the pixel level — raw Y-plane min/max/mean identical (16/234/124.9 both ways) on
    a real full-range ramp, because the explicit `-color_range tv` output tag makes
    ffmpeg auto-insert a matching conversion that overrides a conflicting `out_range`
    in the `-vf` chain. So a wrong value here, like a missing one (§4.1), is
    invisible to any assertion over rendered bytes; only the argv can catch it.

    NOT a coverage hole this closed, and the branch's first write-up said it was.
    The final review pointed out that `test_extract_normalizes_the_range_and_keeps_
    the_seek_order` asserts full string equality on the `-vf` value, so it already
    goes red under this mutation. Row 12 was declared a hole from a PIXEL-level
    selection alone; at the argv level it was covered before this test existed.
    Kept because it names the specific failure in its own right, but it is a
    second lock on one door, not a new one."""
    seen = {}
    monkeypatch.setattr(extract.proc, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    extract.extract("a.mp4", 1.0, 2.0, str(tmp_path / "o.mp4"))
    vf = seen["cmd"][seen["cmd"].index("-vf") + 1]
    assert "out_range=tv" in vf and "out_range=pc" not in vf


# --- the freeze (design 2026-10-21 §3) --------------------------------------------------

def _freeze_cmd(monkeypatch, *args):
    seen = {}
    monkeypatch.setattr(extract.ffbin, "ffmpeg", lambda: "FFMPEG")
    monkeypatch.setattr(extract.proc, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    extract.extract_freeze(*args)
    return seen["cmd"]


def test_extract_freeze_trims_one_frame_and_clones_it_with_no_seek(monkeypatch):
    cmd = _freeze_cmd(monkeypatch, "a.mp4", 7.9, 1.0, 30.0, "o.mp4")
    assert cmd == [
        "FFMPEG", "-y", "-i", "a.mp4", "-vf",
        "trim=start=7.9,setpts=PTS-STARTPTS,trim=end_frame=1,"
        "tpad=stop_mode=clone:stop=29,scale=in_range=auto:out_range=tv",
        "-color_range", "tv", "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "o.mp4"]


def test_extract_freeze_holds_at_least_the_one_frame(monkeypatch):
    cmd = _freeze_cmd(monkeypatch, "a.mp4", 0.0, 0.01, 30.0, "o.mp4")
    assert "tpad=stop_mode=clone:stop=0," in cmd[cmd.index("-vf") + 1]


def test_extract_freeze_passes_the_landmine_lint(monkeypatch):
    assert lint.check_argv(_freeze_cmd(monkeypatch, "a.mp4", 2.5, 2.0, 29.97, "o.mp4")) == []


def _freeze_edl():
    base = dict(source="a.mp4", shot_type="medium", composition="lead", grid="thirds")
    return EDL(episodes=[EDLEpisode(**base, start=0.0, dur=4.0),
                         EDLEpisode(**base, start=4.0 - 1 / 25, dur=2.0, freeze=True)])


def _fake_cuts(monkeypatch, durs):
    calls = []
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (
                            calls.append(("cut", src, start, dur, out)),
                            Path(out).write_bytes(b"cut"), out)[2])
    monkeypatch.setattr(extract, "extract_freeze",
                        lambda src, t, dur, fps, out, **kw: (
                            calls.append(("freeze", src, t, dur, fps, out)),
                            Path(out).write_bytes(b"held"), out)[2])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: durs[Path(p).name])
    # the SOURCE probes 25 fps and every segment 50, so the test sees which one was asked
    monkeypatch.setattr(extract.assembly, "probe_stream", lambda p: type(
        "S", (), {"fps": 25.0 if p.endswith("a.mp4") else 50.0, "w": 1920, "h": 1080})())
    return calls


def test_extract_edl_cuts_a_freeze_from_the_source_at_its_own_rate(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    seg = tmp_path / "seg"
    calls = _fake_cuts(monkeypatch, {"ep0_raw.mp4": 4.0, "ep1_raw.mp4": 2.0})
    out = extract.extract_edl(_freeze_edl(), str(tmp_path), str(seg))
    src = str(tmp_path / "a.mp4")
    assert out == [str(seg / "ep0_raw.mp4"), str(seg / "ep1_raw.mp4")]
    assert calls == [("cut", src, 0.0, 4.0, out[0]),
                     ("freeze", src, 4.0 - 1 / 25, 2.0, 25.0, out[1])]


def test_extract_edl_gates_a_short_freeze_like_any_segment(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    _fake_cuts(monkeypatch, {"ep0_raw.mp4": 4.0, "ep1_raw.mp4": 0.5})
    with pytest.raises(ValueError, match="EDL episode 1 segment is 0.500s — shorter than its "
                                         "2.0s hold"):
        extract.extract_edl(_freeze_edl(), str(tmp_path), str(tmp_path / "seg"))
