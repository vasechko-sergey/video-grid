from pathlib import Path

import pytest

from scripts import extract
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
    """Both halves are emitted. Converting without tagging leaves a player
    re-expanding an already-expanded image; tagging without converting IS the
    corruption this exists to stop. And -ss still lands after -i (§12)."""
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
