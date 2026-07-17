import pytest

from scripts.lib import safezones
from scripts.lib.safezones import SafeZone, SAFE_ZONES
from scripts.lib.models import RoutePoint, CropPath, PathMeta


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


def _geom(x, y):
    # fill 1000x2000; subject centre at (x,y) source px, crop-x 0
    route = [RoutePoint(0.0, x, y, 100.0, 200.0), RoutePoint(2.0, x, y, 100.0, 200.0)]
    path = CropPath([0, 0])
    meta = PathMeta("fill", 1000, 2000, 0, (1000, 2000), (1000, 2000), (1000, 2000),
                    (0, 0, 1000, 2000), 0)
    return route, path, meta


def test_subject_marks_samples_five_points_across_the_episode():
    route, path, meta = _geom(500.0, 900.0)
    marks = safezones.subject_marks(route, path, meta, dur=2.0)
    assert len(marks) == 5
    assert marks == [(0.5, 0.45)] * 5             # constant route → constant marks


def test_evaluate_passes_when_every_subject_is_inside():
    zone = safezones.safe_zone_for("generic")
    inside = [(0.5, 0.45), (0.33, 0.5)]
    passed, detail = safezones.evaluate([inside, inside], zone)
    assert passed is True and detail["advisory"] is True and detail["episodes"] == 2


def test_evaluate_flags_the_worst_offender_episode():
    zone = safezones.safe_zone_for("tiktok")       # bottom band 0.18
    ep0 = [(0.5, 0.45)]                             # safe
    ep1 = [(0.5, 0.70), (0.5, 0.99)]               # 0.99 is deepest under the caption band
    passed, detail = safezones.evaluate([ep0, ep1], zone)
    assert passed is False
    assert detail["worst_episode"] == 1
    assert detail["worst_mark"] == [0.5, 0.99]
    assert detail["advisory"] is True


def test_subject_extents_samples_five_corner_boxes_across_the_episode():
    route, path, meta = _geom(500.0, 900.0)        # fill 1000x2000, subject 100x200
    ext = safezones.subject_extents(route, path, meta, dur=2.0)
    assert len(ext) == 5
    assert ext == [(0.45, 0.4, 0.55, 0.5)] * 5     # constant route → constant extents
