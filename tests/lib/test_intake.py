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


def _line(n_from_to):   # helper: build a timeline [(t, people, bbox)] at 1s steps
    return [(float(t), n, (500, 500, 200, 300) if n else None) for t, n in n_from_to]


def test_carve_long_take_splits_by_length():
    # one 8s take, person present throughout, NO scene cuts → several windows in the band
    tl = _line([(t, 1) for t in range(9)])
    spans = intake.carve_windows([], tl, 8.0)
    assert len(spans) >= 2
    assert all(intake.WIN_MIN <= d <= intake.WIN_MAX + 1e-6 for _, d in spans)
    assert abs(sum(d for _, d in spans) - 8.0) < 1e-6      # cover the take, no gaps


def test_carve_splits_on_presence_transition():
    # empty 0–3, person 3–6 → boundary at 3
    tl = _line([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)])
    spans = intake.carve_windows([], tl, 6.0)
    assert any(abs(s - 3.0) < 1e-6 for s, _ in spans)


def test_carve_short_clip_yields_one_window():
    spans = intake.carve_windows([], _line([(0, 1)]), 0.8)   # < WIN_MIN
    assert spans == [(0.0, 0.8)]
