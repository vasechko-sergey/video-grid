import pytest

from scripts.lib import hero
from scripts.lib.footage import Cast, CastMember

_LENA = (0.5, 0.25, 0.25)
_BO = (0.1, 0.1, 0.8)


def _cast():
    return Cast(members=[CastMember(name="Lena", descriptor=list(_LENA)),
                         CastMember(name="Bo", descriptor=list(_BO))])


def test_none_is_no_pin():
    assert hero.resolve(None) is None
    assert hero.resolve(None, _cast()) is None


def test_bbox_tuple():
    p = hero.resolve((900, 500, 120, 300))
    assert p.kind == "bbox" and p.bbox == (900, 500, 120, 300)
    # 900 == 900.0 so the line above passes either way — pin the coercion itself:
    # JSON gives ints, HeroPin.bbox is typed tuple[float, ...].
    assert all(isinstance(v, float) for v in p.bbox)


def test_bbox_list_is_coerced():
    assert hero.resolve([900, 500, 120, 300]).bbox == (900, 500, 120, 300)


def test_rule():
    assert hero.resolve("largest").kind == "rule"
    assert hero.resolve("leftmost").rule == "leftmost"


def test_track_id():
    p = hero.resolve(3)
    assert p.kind == "track" and p.track_id == 3
    assert hero.resolve(0).track_id == 0          # 0 is falsy but a real track id


def test_cast_name_carries_the_descriptor():
    p = hero.resolve("Lena", _cast())
    assert p.kind == "cast" and p.name == "Lena" and p.descriptor == _LENA


def test_cast_name_without_a_cast_raises_with_a_remedy():
    with pytest.raises(ValueError, match="cast.json"):
        hero.resolve("Lena")


def test_unknown_cast_name_lists_the_known_names():
    with pytest.raises(ValueError) as e:
        hero.resolve("Lna", _cast())
    assert "Lena" in str(e.value) and "Bo" in str(e.value)      # the remedy IS the name list


def test_bool_is_not_a_track_id():
    # isinstance(True, int) is True — `hero: true` must not become track id 1.
    # match on "not a pin" (resolve's own rejection), not just "hero" — that
    # substring is in almost every message this module raises, so it wouldn't
    # discriminate resolve's own bool-guard firing from some unrelated raise.
    for bad in (True, False):
        with pytest.raises(ValueError, match="not a pin"):
            hero.resolve(bad)


def test_malformed_values_raise():
    for bad in ((), "", [1, 2, 3], (1, 2, 3), {}, 4.2, [], {"rule": "largest"}):
        with pytest.raises(ValueError):
            hero.resolve(bad, _cast())
