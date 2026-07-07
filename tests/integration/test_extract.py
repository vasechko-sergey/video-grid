import json, subprocess
import pytest
from scripts import extract

def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])

@pytest.mark.integration
def test_extract_window_duration(sample_clip, tmp_path):
    out = tmp_path / "seg.mp4"
    extract.extract(src=str(sample_clip), start=1.0, dur=1.5, out=str(out))
    assert out.exists()
    assert abs(_duration(out) - 1.5) < 0.15   # frame-accurate re-encode
