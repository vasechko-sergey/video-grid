from scripts import deliver as deliver_mod
from scripts.lib.models import CheckResult, REEL_H264, ReelReport
from scripts.lib.titles import Title, Titles


def _passing_report():
    # ReelReport.overall is a computed property (all checks passed, none False) —
    # there is no overall=/failures= constructor kwarg (scripts/lib/models.py).
    return ReelReport(checks={"length": CheckResult("length", True, {})})


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(deliver_mod.proc, "run", lambda cmd, *a, **k: calls.append(cmd) or None)
    return calls


def test_deliver_without_titles_has_no_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    deliver_mod.deliver("m.mp4", REEL_H264, str(tmp_path), "cl", _passing_report())
    assert "-vf" not in calls[0]


def test_deliver_with_titles_injects_drawtext_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    deliver_mod.deliver("m.mp4", REEL_H264, str(tmp_path), "cl", _passing_report(), titles=str(tj))
    cmd = calls[0]
    assert "-vf" in cmd
    assert "drawtext=" in cmd[cmd.index("-vf") + 1]


def test_deliver_with_empty_titles_has_no_vf(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    tj = tmp_path / "TITLES.json"
    Titles().write(tj)
    deliver_mod.deliver("m.mp4", REEL_H264, str(tmp_path), "cl", _passing_report(), titles=str(tj))
    assert "-vf" not in calls[0]


def test_deliver_with_titles_and_audio_muxes_and_burns(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    f = tmp_path / "f.ttf"
    f.write_text("x")
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("Hook", 0.0, 2.0, font=str(f)),)).write(tj)
    deliver_mod.deliver("m.mp4", REEL_H264, str(tmp_path), "cl", _passing_report(),
                        audio="a.aac", titles=str(tj))
    cmd = calls[0]
    assert "-vf" in cmd and "drawtext=" in cmd[cmd.index("-vf") + 1]
    assert cmd.count("-map") == 2 and "copy" in cmd   # mux path: -vf + -map + -c:a copy together
