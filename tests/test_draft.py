from types import SimpleNamespace

import pytest

from scripts import draft


def _fake_filters(text):
    return lambda cmd, **k: SimpleNamespace(stdout=text.encode())


def test_ensure_drawtext_passes_when_present(monkeypatch):
    monkeypatch.setattr(draft.proc, "run",
                        _fake_filters(" T.. drawtext   V->V   Draw text on top of video.\n"))
    draft.ensure_drawtext()   # no raise


def test_ensure_drawtext_fails_loud_when_absent(monkeypatch):
    monkeypatch.setattr(draft.proc, "run",
                        _fake_filters(" T.. scale       V->V   Scale the input video.\n"))
    with pytest.raises(ValueError, match="drawtext"):
        draft.ensure_drawtext()
