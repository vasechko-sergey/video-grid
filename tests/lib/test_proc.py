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
