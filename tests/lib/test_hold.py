"""hold — the held-episode conventions (design 2026-10-21-photo-rhythm §1)."""
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
