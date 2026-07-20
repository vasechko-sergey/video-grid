from types import SimpleNamespace

import pytest

from scripts import draft
from scripts.lib import ffbin


def _fake_filters(text):
    return lambda cmd, **k: SimpleNamespace(stdout=text.encode())


def test_ensure_drawtext_passes_when_present(monkeypatch):
    # the probe now happens inside ffbin.has_filter (design 2026-07-20 §5) —
    # patch the resolver's proc, not draft's, so this exercises where the
    # filter-list check actually lives.
    monkeypatch.setattr(ffbin.proc, "run",
                        _fake_filters(" T.. drawtext   V->V   Draw text on top of video.\n"))
    draft.ensure_drawtext()   # no raise


def test_ensure_drawtext_fails_loud_when_absent(monkeypatch):
    monkeypatch.setattr(ffbin.proc, "run",
                        _fake_filters(" T.. scale       V->V   Scale the input video.\n"))
    with pytest.raises(ValueError, match="drawtext"):
        draft.ensure_drawtext()
