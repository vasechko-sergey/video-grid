"""On a completed `bash setup.sh` install, the baseline contract holds (design §8).
The 'needs the user's install' proof — same shape as the ffmpeg-baseline slice.

It is RED on purpose whenever the machine running it does not satisfy the contract,
and it is deliberately NOT skip-gated on any single component: skipping is how an
incomplete install stops being visible. The ffmpeg-baseline slice found the never-
working vidstab shake path precisely because this shape refuses to look away. When
this fails, read the printed report — it names the missing piece and its remedy —
and run that command yourself; the suite is telling the truth about the machine, not
about the code."""
import pytest

from scripts import verify_runtime

pytestmark = pytest.mark.integration


def test_real_runtime_is_ready():
    report = verify_runtime.run()
    assert report.ok, "\n" + report.to_text()      # show the failing checks if red
