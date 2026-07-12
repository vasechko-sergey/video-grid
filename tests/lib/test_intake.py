import types
import pytest
from scripts import intake


def test_shot_type_buckets():
    res = (1000, 1000)
    assert intake.shot_type((500, 500, 700, 700), res) == "close"    # area 0.49 > CLOSE_AREA
    assert intake.shot_type((500, 500, 300, 300), res) == "medium"   # area 0.09 in [0.08, 0.30)
    assert intake.shot_type((500, 500, 100, 100), res) == "wide"     # area 0.01 < MEDIUM_AREA
    assert intake.shot_type(None, res) == "wide"


def test_require_vidstab_raises_when_absent(monkeypatch):
    monkeypatch.setattr(intake.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=b"... scale ... overlay ..."))
    with pytest.raises(ValueError, match="vidstab"):
        intake._require_vidstab()


def test_require_vidstab_ok_when_present(monkeypatch):
    monkeypatch.setattr(intake.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=b"... vidstabdetect ..."))
    intake._require_vidstab()   # no raise
