"""On a completed `bash setup.sh` install, the baseline contract holds (design §8).
The 'needs the user's install' proof — same shape as the ffmpeg-baseline slice."""
import pytest

from scripts import verify_runtime

pytestmark = pytest.mark.integration


def test_real_runtime_is_ready():
    report = verify_runtime.run()
    assert report.ok, "\n" + report.to_text()      # show the failing checks if red
