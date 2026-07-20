from pathlib import Path

import pytest
from scripts.lib import proc

def test_run_surfaces_stderr_on_failure():
    with pytest.raises(RuntimeError, match="No such file"):
        proc.run(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration", "/nonexistent/clip.mp4"])

def test_run_passes_through_on_success():
    r = proc.run(["ffprobe", "-version"])
    assert r.returncode == 0

def test_run_missing_binary_reports_remedy():
    # a missing binary raises FileNotFoundError under the hood; proc.run must
    # turn it into a loud RuntimeError with an actionable remedy (hard rule §12).
    with pytest.raises(RuntimeError, match="not found on PATH"):
        proc.run(["vg-nonexistent-binary-xyz"])

def test_run_times_out_loudly_instead_of_hanging():
    # A filtergraph that cannot terminate (an unbounded `color`/`testsrc` with no
    # d=) makes ffmpeg encode forever. Without a timeout that HANGS the suite
    # rather than failing it — measured at 90s-and-killed against a 0.8s normal
    # run — and this machine has no timeout(1) to bound it from outside.
    # An unbounded wait is not a test result.
    with pytest.raises(RuntimeError, match="timed out after 0.5s"):
        proc.run(["sleep", "30"], timeout=0.5)

def test_run_timeout_names_the_command_and_the_usual_cause():
    with pytest.raises(RuntimeError) as ei:
        proc.run(["sleep", "30"], timeout=0.5)
    msg = str(ei.value)
    assert "sleep 30" in msg                      # which command hung
    assert "cannot terminate" in msg              # and the usual reason

def test_run_has_a_default_timeout():
    # The default must be REAL — a None default would leave every unbounded graph
    # hanging exactly as before, and no test would notice.
    assert isinstance(proc.DEFAULT_TIMEOUT_S, (int, float))
    assert proc.DEFAULT_TIMEOUT_S > 0

def test_run_applies_the_default_timeout_when_the_caller_gives_none(monkeypatch):
    # The WIRING, not the constant. Asserting DEFAULT_TIMEOUT_S is a positive
    # number says nothing about whether run() passes it on: deleting the
    # `kwargs.setdefault("timeout", ...)` line left the whole file green, because
    # the two timeout tests above hand in their own explicit timeout=0.5 and so
    # never exercise the default path at all.
    seen = {}
    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        raise AssertionError("stop — the kwargs are the whole point")
    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    with pytest.raises(AssertionError, match="the kwargs are the whole point"):
        proc.run(["ffprobe", "-version"])
    assert seen["timeout"] == proc.DEFAULT_TIMEOUT_S

def test_the_default_timeout_actually_fires(monkeypatch):
    # ...and end to end: with no explicit timeout, a command that outlives the
    # default must raise rather than run to completion. Belt to the braces above —
    # this one would also catch a setdefault that passed something unusable.
    monkeypatch.setattr(proc, "DEFAULT_TIMEOUT_S", 0.5)
    with pytest.raises(RuntimeError, match="timed out after 0.5s"):
        proc.run(["sleep", "30"])

def test_an_explicit_timeout_still_overrides_the_default(monkeypatch):
    seen = {}
    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        raise AssertionError("stop")
    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    with pytest.raises(AssertionError):
        proc.run(["ffprobe", "-version"], timeout=12.0)
    assert seen["timeout"] == 12.0

def test_run_refuses_a_command_carrying_a_landmine(monkeypatch):
    """The guard must fire BEFORE the command executes. Asserting on the outcome
    would pass for the wrong reason (ffmpeg failing on its own), so subprocess.run
    is monkeypatched to fail if it is called at all — the shape §12's smoothing
    entry prescribes, for the same reason."""
    def _never(*a, **k):
        raise AssertionError("subprocess.run was reached — the guard did not fire")
    monkeypatch.setattr(proc.subprocess, "run", _never)
    with pytest.raises(ValueError, match="lutrgb"):
        proc.run(["ffmpeg", "-y", "-i", "a.mp4", "-vf", "lutrgb=r=val", "out.mp4"])

def test_run_lets_a_clean_command_through(monkeypatch):
    seen = {}
    def _fake(cmd, **k):
        seen["cmd"] = cmd
        return "ok"
    monkeypatch.setattr(proc.subprocess, "run", _fake)
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "colorchannelmixer=rr=1.0", "o.mp4"]
    assert proc.run(cmd) == "ok"
    assert seen["cmd"] == cmd

def test_the_refusal_reports_every_violation_not_only_the_first(monkeypatch):
    """Two landmines in one command should surface together — fixing one and
    re-running to discover the next is a slow way to learn."""
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: pytest.fail("guard did not fire"))
    with pytest.raises(ValueError) as e:
        proc.run(["ffmpeg", "-y", "-ss", "1.0", "-i", "a.mp4", "-t", "2.0",
                  "-vf", "lutrgb=r=val", "out.mp4"])
    # Assert on text only the per-violation MESSAGES carry. The refusal ends with
    # `command: <the argv>`, which contains both "lutrgb" and "-ss" verbatim — so
    # asserting on those pins nothing: deleting _seek_order from check_argv left
    # this test green.
    assert "banned filter" in str(e.value) and "input-side -ss" in str(e.value)

def test_the_guard_fires_before_the_environment_is_consulted(monkeypatch):
    """A landmine command whose binary does not even exist must report the
    LANDMINE, not the missing binary.

    proc.run's RuntimeErrors describe the ENVIRONMENT failing (binary missing,
    timeout, non-zero exit); a landmine is the CALLER being wrong — a programming
    error, which every config-spec in models.py raises ValueError for. The guard
    sits before the try: block precisely so the caller's own bug surfaces first,
    and this is what pins that ordering: move the guard inside the try: and the
    FileNotFoundError handler answers instead, with a remedy about PATH that
    would send the author off to reinstall ffmpeg over a filtergraph bug.
    """
    with pytest.raises(ValueError, match="lutrgb"):
        proc.run(["vg-nonexistent-binary-xyz", "-vf", "lutrgb=r=val", "o.mp4"])

def test_a_path_element_reaches_subprocess_unchanged(monkeypatch):
    """subprocess.run accepts os.PathLike and this repo passes Paths everywhere,
    but check_argv's `in`/regex tests raise TypeError on one. The guard therefore
    coerces with str() for the CHECK only — proc.run(["ffmpeg", "-i", src_path])
    must still reach subprocess.run with the Path intact, not a stringified copy,
    and must not die inside the lint."""
    seen = {}
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda cmd, **k: seen.setdefault("cmd", cmd))
    src, out = Path("/w/a.mp4"), Path("/w/o.mp4")
    proc.run(["ffmpeg", "-y", "-i", src, "-c", "copy", out])
    assert seen["cmd"] == ["ffmpeg", "-y", "-i", src, "-c", "copy", out]
    assert seen["cmd"][3] is src            # the object, not a str() of it

def test_the_guard_still_reads_a_landmine_carried_by_a_path_element(monkeypatch):
    """The coercion must feed the check, not bypass it: a banned filter riding in
    a non-str element is still a landmine."""
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: pytest.fail("guard did not fire"))
    with pytest.raises(ValueError, match="lutrgb"):
        proc.run(["ffmpeg", "-vf", Path("lutrgb=r=val"), "o.mp4"])
