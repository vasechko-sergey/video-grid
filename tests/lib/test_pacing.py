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


def test_kind_bands():
    assert pacing._kind(0.0) == "release" and pacing._kind(0.32) == "release"
    assert pacing._kind(0.33) == "build" and pacing._kind(0.65) == "build"
    assert pacing._kind(0.66) == "peak" and pacing._kind(1.0) == "peak"


def test_beats_per_slot_bands():
    assert pacing._beats_per_slot(0.1) == pacing.SLOW_BEATS
    assert pacing._beats_per_slot(0.5) == pacing.MID_BEATS
    assert pacing._beats_per_slot(0.9) == pacing.FAST_BEATS


def test_beat_energy_min_max_normalizes_within_track():
    # 4 beats every 1s over 4s; energy 2 Hz => 8 samples; quiet first half, loud second
    beats = [0.0, 1.0, 2.0, 3.0]
    energy = [0.1, 0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.9]   # samples at 0.0,0.5,...,3.5s
    n = pacing._beat_energy(beats, energy, energy_hz=2.0, duration=4.0)
    assert len(n) == 4
    assert n[0] == 0.0 and n[3] == 1.0                  # min-max: quietest→0, loudest→1
    assert n[2] == 1.0                                  # beat 2 spans [2,3): loud samples


def test_beat_energy_flat_curve_is_mid():
    n = pacing._beat_energy([0.0, 1.0], [0.5, 0.5, 0.5, 0.5], energy_hz=2.0, duration=2.0)
    assert n == [0.5, 0.5]                              # range < _FLAT_EPS → uniform 0.5


def _grid(n_beats, duration):
    step = duration / n_beats
    return [round(i * step, 6) for i in range(n_beats)]


def test_build_spine_hook_first_and_covers_duration():
    beats = _grid(24, 12.0)                              # 24 beats over 12s
    energy = [0.5] * 24                                  # uniform 2 Hz-ish curve
    sp = pacing.build_spine(beats, energy, energy_hz=2.0, duration=12.0, tempo=120.0)
    assert sp.slots[0].kind == "hook" and sp.slots[0].start == 0.0
    assert sp.slots[0].dur == beats[pacing.HOOK_BEATS]   # hook spans HOOK_BEATS beats
    assert abs(sum(s.dur for s in sp.slots) - 12.0) < 1e-9   # covers [0,12] exactly
    assert sp.slots[-1].start + sp.slots[-1].dur == 12.0


def test_build_spine_uniform_energy_uses_mid_slots():
    beats = _grid(24, 12.0)
    sp = pacing.build_spine(beats, [0.5] * 24, energy_hz=2.0, duration=12.0, tempo=120.0)
    # after the hook, uniform (0.5) energy → build slots of MID_BEATS beats each
    assert all(s.kind == "build" for s in sp.slots[1:])
    assert all(abs(s.dur - pacing.MID_BEATS * 0.5) < 1e-9 for s in sp.slots[1:-1])


def test_build_spine_cut_density_rises_with_energy():
    beats = _grid(24, 12.0)
    # quiet first third (beats 0-7), loud middle (8-15), quiet last third (16-23)
    energy = [0.05] * 8 + [0.95] * 8 + [0.05] * 8
    sp = pacing.build_spine(beats, energy, energy_hz=2.0, duration=12.0, tempo=120.0)
    loud = [s for s in sp.slots if 4.0 <= s.start < 8.0]
    quiet = [s for s in sp.slots if s.start >= 8.0]
    assert len(loud) > len(quiet)                        # more (shorter) slots where loud
    assert any(s.kind == "peak" for s in loud)


def test_build_spine_single_beat_is_one_hook_slot():
    sp = pacing.build_spine([0.0], [0.5, 0.5], energy_hz=2.0, duration=3.0, tempo=90.0)
    assert len(sp.slots) == 1 and sp.slots[0].kind == "hook" and sp.slots[0].dur == 3.0


def test_build_spine_beat_on_duration_makes_no_zero_width_tail():
    beats = _grid(8, 8.0) + [8.0]                        # a beat sitting exactly on duration
    sp = pacing.build_spine(beats, [0.5] * 16, energy_hz=2.0, duration=8.0, tempo=120.0)
    assert all(s.dur > 0 for s in sp.slots)              # no zero-width slot
    assert abs(sum(s.dur for s in sp.slots) - 8.0) < 1e-9


def test_build_spine_no_beats_raises():
    with pytest.raises(ValueError, match="no beats"):
        pacing.build_spine([], [0.5], energy_hz=2.0, duration=5.0, tempo=120.0)


def test_beat_energy_fewer_samples_than_beats_uses_fallback():
    # spec §8: a COARSE curve with fewer energy samples than beats still yields one
    # value per beat — exercises the empty-segment fallback (the i0>=len guard the
    # 2 Hz-vs-slower-curve case relies on). 2 samples (0.5 Hz → t=0s, 2s) for 4 beats.
    n = pacing._beat_energy([0.0, 1.0, 2.0, 3.0], [0.2, 0.8], energy_hz=0.5, duration=4.0)
    assert len(n) == 4                                  # one value per beat, no crash on the tail
    assert n[0] == 0.0 and n[-1] == 1.0                 # min-max over the resolved per-beat means


def test_build_spine_interior_boundaries_are_beat_times():
    # spec §8 + §12(b): every interior cut lands on a beat. Each slot after the hook
    # starts exactly on a beat time (start=beats[i]); by contiguity that is also the
    # prior slot's cut point, so this pins "boundaries are beat-aligned".
    beats = _grid(24, 12.0)
    energy = [0.05] * 8 + [0.95] * 8 + [0.05] * 8
    sp = pacing.build_spine(beats, energy, energy_hz=2.0, duration=12.0, tempo=120.0)
    beat_set = set(beats)
    assert all(s.start in beat_set for s in sp.slots[1:])
