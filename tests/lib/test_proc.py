import pytest
from scripts.lib import proc

def test_run_surfaces_stderr_on_failure():
    with pytest.raises(RuntimeError, match="No such file"):
        proc.run(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration", "/nonexistent/clip.mp4"])

def test_run_passes_through_on_success():
    r = proc.run(["ffprobe", "-version"])
    assert r.returncode == 0
