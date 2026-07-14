"""pacing core — pure stdlib, no librosa/numpy; exact-slot asserts (bit-exact)."""
import pytest

from scripts.lib import pacing
from scripts.lib.pacing import Slot, Spine


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


def _spine():
    return Spine(slots=(
        Slot(0, 0.0, 1.0, 0.05, "hook"),
        Slot(1, 1.0, 4.0, 0.28, "release"),
        Slot(2, 5.0, 1.0, 0.95, "peak")), target_dur=6.0, tempo=120.0)


def test_spine_round_trips():
    sp = _spine()
    assert Spine.from_dict(sp.to_dict()) == sp
    assert sp.to_dict()["target_dur"] == 6.0 and len(sp.to_dict()["slots"]) == 3


def test_spine_to_markdown_has_row_per_slot_hook_first():
    md = _spine().to_markdown()
    assert md.count("\n|") >= 4                     # header sep + 3 rows
    assert "hook" in md.splitlines()[4]             # first data row is the hook
    assert "120" in md.splitlines()[0]              # header names the tempo


@pytest.mark.parametrize("slots, match", [
    ((Slot(0, 0.0, 1.0, 0.5, "build"),), "hook"),                     # slot 0 not hook
    ((Slot(0, 0.5, 1.0, 0.5, "hook"),), "0.0"),                       # slot 0 start != 0
    ((Slot(0, 0.0, 1.0, 0.5, "hook"), Slot(1, 2.0, 1.0, 0.5, "peak")), "contiguous"),  # gap
    ((), "non-empty"),                                                # empty
])
def test_spine_rejects_bad_shape(slots, match):
    with pytest.raises(ValueError, match=match):
        Spine(slots=slots, target_dur=10.0, tempo=120.0)


def test_spine_rejects_wrong_duration_sum():
    with pytest.raises(ValueError, match="sum"):
        Spine(slots=(Slot(0, 0.0, 1.0, 0.5, "hook"),), target_dur=9.0, tempo=120.0)


def test_spine_rejects_misordered_index():
    with pytest.raises(ValueError, match="index-ordered"):
        Spine(slots=(Slot(0, 0.0, 1.0, 0.5, "hook"), Slot(5, 1.0, 1.0, 0.5, "peak")),
              target_dur=2.0, tempo=120.0)
