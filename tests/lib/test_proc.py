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
