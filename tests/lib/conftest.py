import pytest

from scripts.lib import vocals


@pytest.fixture(autouse=True)
def _reset_vocal_spans():
    """vocals._SPANS is a process-global memo keyed on track path (hazard note at
    its definition in scripts/lib/vocals.py). Tests across this directory reuse
    the same stand-in path "t.wav" for choose_offset/vocal_spans — without a
    reset, one test's memo entry can silently shadow a later test's guard (e.g.
    a has_demucs stub never gets reached because the cache already answers).
    Found 2026-08-14 (music-outro-fit task 1 review): a manual per-test
    vocals._SPANS.clear() closed the one test that broke; this autouse fixture
    closes the hazard structurally for every test in tests/lib/, including the
    six tasks still to land in this slice that extend vocal_spans/choose_offset."""
    vocals._SPANS.clear()
    yield
    vocals._SPANS.clear()
