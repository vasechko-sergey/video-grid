"""pacing core — pure stdlib, no librosa/numpy; exact-slot asserts (bit-exact)."""
import pytest

from scripts.lib import pacing
from scripts.lib.pacing import Slot


def test_slot_round_trips():
    s = Slot(index=0, start=0.0, dur=1.5, energy=0.4, kind="hook")
    assert Slot.from_dict(s.to_dict()) == s
    assert s.to_dict() == {"index": 0, "start": 0.0, "dur": 1.5, "energy": 0.4, "kind": "hook"}


def test_slot_coerces_ints_to_float():
    s = Slot(index=1, start=2, dur=3, energy=1, kind="peak")
    assert s.start == 2.0 and s.dur == 3.0 and s.energy == 1.0
    assert isinstance(s.start, float) and isinstance(s.dur, float)


@pytest.mark.parametrize("kw, match", [
    (dict(index=0, start=0.0, dur=0.0, energy=0.5, kind="hook"), "dur"),
    (dict(index=0, start=0.0, dur=1.0, energy=1.5, kind="hook"), "energy"),
    (dict(index=0, start=-1.0, dur=1.0, energy=0.5, kind="hook"), "start"),
    (dict(index=0, start=0.0, dur=1.0, energy=0.5, kind="bogus"), "kind"),
    (dict(index=True, start=0.0, dur=1.0, energy=0.5, kind="hook"), "index"),
    (dict(index=-1, start=0.0, dur=1.0, energy=0.5, kind="hook"), "index"),
])
def test_slot_rejects_bad(kw, match):
    with pytest.raises(ValueError, match=match):
        Slot(**kw)


def test_slot_from_dict_missing_key_raises():
    with pytest.raises(ValueError, match="missing"):
        Slot.from_dict({"index": 0, "start": 0.0, "dur": 1.0, "energy": 0.5})
