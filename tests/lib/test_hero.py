import json

import pytest

from scripts.lib import hero
from scripts.lib.footage import DESCRIPTOR_LEN, Cast, CastMember


def _desc(*head: float) -> tuple[float, ...]:
    """A registry-valid descriptor: DESCRIPTOR_LEN floats — `head`, zero-padded.
    CastMember rejects any other length, so a pin's descriptor is always this wide."""
    return tuple(head) + (0.0,) * (DESCRIPTOR_LEN - len(head))


_LENA = _desc(0.5, 0.25, 0.25)
_BO = _desc(0.1, 0.1, 0.8)


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


def test_bbox_elements_must_be_numbers():
    # Not in test_malformed_values_raise's loop on purpose: that loop asserts the
    # exception TYPE, and float("a") already raises ValueError — so type alone would
    # pass while the human read float()'s bare "could not convert string to float:
    # 'a'". resolve is validate()'s oracle; the message must be this module's own.
    for bad in (["900", 500, 120, 300], ("a", 500, 120, 300), [None, 500, 120, 300]):
        with pytest.raises(ValueError, match="is not a seed bbox") as e:
            hero.resolve(bad)
        assert "JSON number" in str(e.value)            # the remedy, in hero.py's voice


def test_bbox_oversized_int_does_not_escape_validate_as_overflowerror():
    """resolve() is validate()'s oracle and validate() catches ValueError ONLY, so an
    OverflowError out of float() escapes the soft gate as a crash — the gate's whole
    job is not to raise. json.loads happily builds a 400-digit int and
    isinstance(v, (int, float)) waves it straight through to float(), which cannot
    represent it.

    Same shape as the type-laundering fix beside it ("900"→900.0, True→1.0): that one
    closed type, this one closes magnitude.
    """
    huge = json.loads("[" + "9" * 400 + ", 500, 120, 300]")
    assert isinstance(huge[0], int)              # the guard's type test passes it
    with pytest.raises(ValueError, match="is not a seed bbox"):
        hero.resolve(huge)


def test_bbox_non_finite_elements_are_refused():
    """json.loads accepts Infinity/-Infinity/NaN by default and float() passes them
    straight through, so these used to clear validate() clean and reach _seed_track —
    where the IoU arithmetic goes nan, matches nobody, and comes back out as
    hero-unmatched: "the pinned person may not be in this episode". The pin is
    malformed, not absent; a coordinate that names no pixel must die at the gate.
    """
    for lit in ("Infinity", "-Infinity", "NaN"):
        bad = json.loads("[%s, 500, 120, 300]" % lit)
        with pytest.raises(ValueError, match="is not a seed bbox") as e:
            hero.resolve(bad)
        assert "finite" in str(e.value), lit          # the remedy names what it checked


def test_bbox_finite_edge_values_still_resolve():
    # the magnitude guard must reject only what float() cannot carry — a plain
    # coordinate, a float one, and 0.0 are all legitimate pins
    assert hero.resolve([0, 0.0, 1e308, 300]).kind == "bbox"


def test_bbox_bool_element_is_not_laundered():
    # float(True) is 1.0 — a bool element must not become a coordinate. resolve
    # coerces before handing over, so without this check HeroPin.bbox's own bool
    # guard could never fire on the only path that builds a bbox pin.
    with pytest.raises(ValueError) as e:
        hero.resolve((True, 500, 120, 300))
    assert "is not a seed bbox" in str(e.value) and "True" in str(e.value)


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


def test_cast_name_remedy_names_no_cli_flag():
    """One resolver, three callers, two different flag spellings — so the shared
    remedy must name the ARTEFACT, never one caller's flag.

    manifest.validate() has no CLI at all; edit_plan.py spells it --cast; track.py
    spells it --cast-json. A remedy saying "or pass --cast" is right for exactly one
    of the three, and actively hostile on track.py, where following it literally
    lands a stranger in a second, unrelated failure:
    `error: ambiguous option: --cast could match --cast-name, --cast-json`.
    """
    with pytest.raises(ValueError) as e:
        hero.resolve("Lena")
    msg = str(e.value)
    assert "cast.json" in msg          # the artefact all three callers share
    assert "--cast" not in msg         # no flag: they disagree, and one caller has none


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
