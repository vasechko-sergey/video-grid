import pytest

from scripts.lib import safezones
from scripts.lib.safezones import SafeZone, SAFE_ZONES


def test_safezone_contains_inside_and_outside():
    z = SafeZone(top=0.08, bottom=0.12, left=0.05, right=0.05)
    assert z.contains(0.5, 0.45) is True          # centred subject
    assert z.contains(0.5, 0.95) is False         # under the bottom band (0.95 > 1-0.12)
    assert z.contains(0.97, 0.5) is False          # in the right rail
    assert z.contains(0.05, 0.08) is True          # exact corner is inside (inclusive)


@pytest.mark.parametrize("kw,msg", [
    (dict(top=0.5, bottom=0.1, left=0.05, right=0.05), "top"),        # >= 0.5
    (dict(top=-0.01, bottom=0.1, left=0.05, right=0.05), "top"),      # < 0
    (dict(top=0.1, bottom="x", left=0.05, right=0.05), "bottom"),     # non-numeric
    (dict(top=0.1, bottom=True, left=0.05, right=0.05), "bottom"),    # bool is not a fraction
])
def test_safezone_validation_fails_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        SafeZone(**kw)


def test_safe_zone_for_known_alias_and_default():
    assert safezones.safe_zone_for("tiktok") is SAFE_ZONES["tiktok"]
    assert safezones.safe_zone_for("Instagram") is SAFE_ZONES["reels"]   # alias, case-insensitive
    assert safezones.safe_zone_for("YT") is SAFE_ZONES["shorts"]
    assert safezones.safe_zone_for("") is SAFE_ZONES["generic"]          # empty → generic
    assert safezones.safe_zone_for("myspace") is SAFE_ZONES["generic"]   # unknown → generic


def test_default_zone_is_generic_and_matches_titles_presets():
    z = safezones.default_zone()
    assert z is SAFE_ZONES["generic"]
    assert (z.top, z.bottom) == (0.08, 0.12)      # == titles _Y_EXPR presets
