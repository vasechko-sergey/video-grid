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

def _freeze_cmd(monkeypatch, *args, frames=61, fps=30.0):
    """extract_freeze's argv, with the previous segment probed as `frames` decoded frames
    at `fps`; records which file each probe was asked about."""
    seen = {"probed": []}
    monkeypatch.setattr(extract.ffbin, "ffmpeg", lambda: "FFMPEG")
    monkeypatch.setattr(extract.proc, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    monkeypatch.setattr(extract.assembly, "count_frames",
                        lambda p: (seen["probed"].append(("count", p)), frames)[1])
    monkeypatch.setattr(extract.assembly, "probe_stream", lambda p: (
        seen["probed"].append(("rate", p)), type("S", (), {"fps": fps})())[1])
    extract.extract_freeze(*args)
    return seen


def test_extract_freeze_takes_the_previous_segments_last_frame_by_count_with_no_seek(
        monkeypatch):
    seen = _freeze_cmd(monkeypatch, "seg/ep0_raw.mp4", 1.0, "o.mp4", frames=61)
    assert seen["cmd"] == [
        "FFMPEG", "-y", "-i", "seg/ep0_raw.mp4", "-vf",
        "trim=start_frame=60,setpts=PTS-STARTPTS,"
        "tpad=stop_mode=clone:stop=29,scale=in_range=auto:out_range=tv",
        "-color_range", "tv", "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "o.mp4"]
    # the count and the rate are the PREVIOUS SEGMENT's, never the source's
    assert sorted(seen["probed"]) == [("count", "seg/ep0_raw.mp4"),
                                      ("rate", "seg/ep0_raw.mp4")]


def test_extract_freeze_holds_at_the_previous_segments_rate(monkeypatch):
    seen = _freeze_cmd(monkeypatch, "p.mp4", 1.0, "o.mp4", fps=30000 / 1001)
    assert "tpad=stop_mode=clone:stop=29," in seen["cmd"][seen["cmd"].index("-vf") + 1]
    seen = _freeze_cmd(monkeypatch, "p.mp4", 1.0, "o.mp4", fps=60.0)
    assert "tpad=stop_mode=clone:stop=59," in seen["cmd"][seen["cmd"].index("-vf") + 1]


def test_extract_freeze_holds_at_least_the_one_frame(monkeypatch):
    seen = _freeze_cmd(monkeypatch, "p.mp4", 0.01, "o.mp4")
    assert "tpad=stop_mode=clone:stop=0," in seen["cmd"][seen["cmd"].index("-vf") + 1]


def test_extract_freeze_passes_the_landmine_lint(monkeypatch):
    """Vacuous for the seek rule, and said so: lint._seek_order returns [] for any argv
    without `-t`/`-to`, so this would pass with an input-side `-ss` added too. The sole
    guard on "no `-ss`" is the exact-argv test above. What this does cover is the other
    checks — banned filters, and the rest of check_argv's table."""
    assert lint.check_argv(_freeze_cmd(monkeypatch, "p.mp4", 2.0, "o.mp4",
                                       fps=29.97)["cmd"]) == []


def _freeze_edl(**prev):
    base = dict(source="a.mp4", shot_type="medium", composition="lead", grid="thirds")
    return EDL(episodes=[EDLEpisode(**{**base, "start": 0.0, "dur": 4.0, **prev}),
                         EDLEpisode(**base, start=4.0 - 1 / 25, dur=2.0, freeze=True)])


def _fake_cuts(monkeypatch, durs):
    """Fake cuts that write marker bytes; the fake freeze records the bytes its previous
    segment held AT THE MOMENT it was called, so a test sees what pixels it was handed."""
    calls = []
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (
                            calls.append(("cut", src, start, dur, out)),
                            Path(out).write_bytes(b"cut"), out)[2])
    monkeypatch.setattr(extract, "extract_freeze",
                        lambda prev, dur, out, **kw: (
                            calls.append(("freeze", prev, Path(prev).read_bytes(), dur, out)),
                            Path(out).write_bytes(b"held"), out)[2])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: durs[Path(p).name])
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 25.0, "w": 1920, "h": 1080})())
    return calls


def test_extract_edl_freezes_the_previous_segment_after_it_is_cut(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    seg = tmp_path / "seg"
    calls = _fake_cuts(monkeypatch, {"ep0_raw.mp4": 4.0, "ep1_raw.mp4": 2.0})
    out = extract.extract_edl(_freeze_edl(), str(tmp_path), str(seg))
    assert out == [str(seg / "ep0_raw.mp4"), str(seg / "ep1_raw.mp4")]
    # the freeze is cut from ep0's own segment, never from the source at `start`
    assert calls == [("cut", str(tmp_path / "a.mp4"), 0.0, 4.0, out[0]),
                     ("freeze", out[0], b"cut", 2.0, out[1])]


def test_extract_edl_freezes_a_ramped_segment_after_its_retime(monkeypatch, tmp_path):
    # the retime replaces ep0_raw.mp4 in place BEFORE the freeze reads it, so the frame it
    # holds is the one that plays, not the un-ramped cut's
    (tmp_path / "a.mp4").write_bytes(b"x")
    calls = _fake_cuts(monkeypatch, {"ep0_raw.mp4": 4.0, "ep1_raw.mp4": 2.0})
    monkeypatch.setattr(extract.ramp, "retime",
                        lambda src, dst, spec, dur, fps: Path(dst).write_bytes(b"ramped"))
    extract.extract_edl(_freeze_edl(ramp={"at": 2.0, "factor": 0.5, "ease": 0.5, "hold": 1.0}),
                        str(tmp_path), str(tmp_path / "seg"))
    assert calls[1][:3] == ("freeze", str(tmp_path / "seg" / "ep0_raw.mp4"), b"ramped")


def test_extract_edl_refuses_a_freeze_with_no_segment_cut_before_it(monkeypatch, tmp_path):
    # EDL itself refuses this shape; the guard holds the LOOP's order, so the EDL is
    # reshuffled after construction to reach it
    (tmp_path / "a.mp4").write_bytes(b"x")
    calls = _fake_cuts(monkeypatch, {"ep0_raw.mp4": 2.0, "ep1_raw.mp4": 4.0})
    edl = _freeze_edl()
    edl.episodes = edl.episodes[::-1]
    with pytest.raises(ValueError, match="EDL episode 0 is a freeze, and episode -1 has no "
                                         "played segment cut before it"):
        extract.extract_edl(edl, str(tmp_path), str(tmp_path / "seg"))
    assert calls == []


def test_extract_edl_gates_a_short_freeze_like_any_segment(monkeypatch, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    _fake_cuts(monkeypatch, {"ep0_raw.mp4": 4.0, "ep1_raw.mp4": 0.5})
    with pytest.raises(ValueError, match="EDL episode 1 segment is 0.500s — shorter than its "
                                         "2.0s hold of episode 0's last frame"):
        extract.extract_edl(_freeze_edl(), str(tmp_path), str(tmp_path / "seg"))


def _photo_run(monkeypatch, tmp_path, *eps):
    """extract_edl over `eps` with every cut, probe and render faked; returns what each
    photo's render was handed and which segment the colour was read off."""
    for n in ("a.mp4", "p.png"):
        (tmp_path / n).write_bytes(b"x")
    seen = {"renders": [], "colour_of": []}
    monkeypatch.setattr(extract, "extract",
                        lambda src, start, dur, out, **kw: (Path(out).write_bytes(b"cut"), out)[1])
    monkeypatch.setattr(extract, "_probe_dur", lambda p: 2.0)
    monkeypatch.setattr(extract.assembly, "probe_stream",
                        lambda p: type("S", (), {"fps": 25.0, "w": 1920, "h": 1080})())
    monkeypatch.setattr(extract.assembly, "probe_rate", lambda p: ("25/1", 12800))

    def colour_of(path):
        seen["colour_of"].append(Path(path).name)
        return extract.still.Colour(space="smpte170m")

    def render_photo(ep, src, out, project, rate, delivery=None, *, colour, colour_from):
        seen["renders"].append((Path(out).name, rate, colour, colour_from))
        return {}

    monkeypatch.setattr(extract.still, "colour_of", colour_of)
    monkeypatch.setattr(extract, "render_photo", render_photo)
    monkeypatch.setattr(extract, "_photo_delivery", lambda *a: None)
    monkeypatch.setattr(extract.track, "ensure_model", lambda m: None)
    extract.extract_edl(EDL(episodes=list(eps)), str(tmp_path), str(tmp_path / "seg"),
                        project=object())
    return seen


def _ep(source):
    return EDLEpisode(source=source, start=0.0, dur=2.0, shot_type="medium",
                      composition="center", grid="thirds")


def test_a_photo_takes_the_first_video_segments_colour_as_it_takes_its_clock(
        monkeypatch, tmp_path):
    # the photo opens the reel here, so "the first video segment" is episode 1, not 0
    seen = _photo_run(monkeypatch, tmp_path, _ep("p.png"), _ep("a.mp4"), _ep("p.png"))
    assert seen["colour_of"] == ["ep1_raw.mp4"]                 # read once, for every photo
    want = (("25/1", 12800), extract.still.Colour(space="smpte170m"), "ep1_raw.mp4")
    assert seen["renders"] == [("ep0_raw.mp4", *want), ("ep2_raw.mp4", *want)]


def test_a_reel_of_photos_alone_takes_the_default_clock_and_bt709(monkeypatch, tmp_path):
    seen = _photo_run(monkeypatch, tmp_path, _ep("p.png"))
    assert seen["colour_of"] == []
    assert seen["renders"] == [("ep0_raw.mp4", extract.PHOTO_RATE, extract.still.BT709, None)]
