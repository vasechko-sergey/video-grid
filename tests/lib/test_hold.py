"""hold — the held-episode conventions (design 2026-10-21-photo-rhythm §1)."""
import pytest

from scripts import intake
from scripts.lib import hold


def test_the_conventions_hold_the_designed_values():
    assert hold.HOLD_DEFAULT == 2.0
    assert hold.HOLD_ROOM == 8.0
    assert hold.HOLD_MIN == 1 / 3
    assert hold.BAND_HOLD == {"release": 2.0, "build": 1.0, "peak": 0.5}


def test_intake_keeps_its_names_as_aliases_of_the_hold_conventions():
    # tests and FOOTAGE.json's photo clips read the intake names; one value, two names
    assert intake.PHOTO_HOLD == hold.HOLD_DEFAULT
    assert intake.PHOTO_ROOM == hold.HOLD_ROOM


# --- beats_for: a band's target seconds as a musical count (design §2.1) ---------------

def _period(bpm):
    return 60.0 / bpm


@pytest.mark.parametrize("bpm, release, build, peak", [
    (90.0, 4, 2, 1),       # 2.67 / 1.33 / 0.67 s
    (120.0, 4, 2, 1),      # 2.0 / 1.0 / 0.5 s
    (170.0, 8, 4, 2),      # 2.82 / 1.41 / 0.71 s — peak's 1.42 beats is log2 0.503, so 2
    (200.0, 8, 4, 2),      # one beat is 0.3 s, under HOLD_MIN: the floor is 2 beats
])
def test_beats_for_turns_each_band_into_the_nearest_power_of_two(bpm, release, build, peak):
    p = _period(bpm)
    got = tuple(hold.beats_for(hold.BAND_HOLD[b], p, hold.HOLD_MIN, hold.HOLD_ROOM)
                for b in ("release", "build", "peak"))
    assert got == (release, build, peak)


def test_the_floor_binds_only_above_180_bpm():
    assert hold.count_range(_period(180.0), hold.HOLD_MIN, hold.HOLD_ROOM) == (1, 24)
    assert hold.count_range(_period(181.0), hold.HOLD_MIN, hold.HOLD_ROOM) == (2, 24)
    # a target well under one beat rounds to 2**-2 and is lifted to the floor
    assert hold.beats_for(0.1, _period(200.0), hold.HOLD_MIN, hold.HOLD_ROOM) == 2
    assert hold.beats_for(0.1, _period(120.0), hold.HOLD_MIN, hold.HOLD_ROOM) == 1


def test_beats_for_is_clamped_to_the_ceiling():
    # 40 beats rounds to 32, past HOLD_ROOM's 16 at 120 BPM
    assert hold.beats_for(20.0, _period(120.0), hold.HOLD_MIN, hold.HOLD_ROOM) == 16


@pytest.mark.parametrize("args, match", [
    ((0.0, 0.5, 1 / 3, 8.0), "seconds"),
    ((1.0, 0.0, 1 / 3, 8.0), "period"),
    ((1.0, True, 1 / 3, 8.0), "period"),
    ((1.0, 0.5, 0.0, 8.0), "lo"),
    ((1.0, 0.5, 2.0, 1.0), "lo"),
    ((1.0, 10.0, 1 / 3, 8.0), "no whole number of beats"),   # one beat is past HOLD_ROOM
])
def test_beats_for_refuses_what_has_no_count(args, match):
    with pytest.raises(ValueError, match=match):
        hold.beats_for(*args)


# --- vary: never the same count three times in a run (design §2.1) --------------------

@pytest.mark.parametrize("k, run, k_lo, k_hi, want", [
    (2, (2, 2), 1, 16, 4),       # the third doubles
    (1, (1, 1), 1, 16, 2),
    (4, (4, 4), 1, 4, 2),        # doubling would pass the ceiling: it halves
    (3, (3, 3), 1, 4, 3),        # odd, and doubling passes the ceiling: unchanged
    (2, (2, 2), 2, 2, 2),        # halving would pass the floor: unchanged
    (2, (2, 2), 1, 4, 4),        # doubling exactly to the ceiling is allowed
    (2, (), 1, 16, 2),
    (2, (2,), 1, 16, 2),
    (2, (4, 2), 1, 16, 2),
    (2, (2, 4), 1, 16, 2),
])
def test_vary(k, run, k_lo, k_hi, want):
    assert hold.vary(k, run, k_lo, k_hi) == want


def test_a_build_reads_two_two_four_rather_than_a_metronome():
    run = ()
    for _ in range(6):
        run += (hold.vary(2, run, 1, 16),)
    assert run == (2, 2, 4, 2, 2, 4)
