"""Resolve a manifest's raw `hero` value into a typed HeroPin (§5.10, §6.1a).

The ONE place that decides what a pin is. Pure: it reads descriptors out of a
Cast, it never computes one (that is lib/appearance). It is used twice — as
manifest.validate()'s oracle (its ValueError becomes a problem string) and as the
shell's real resolution — so validation and behaviour cannot drift apart.

Raising (rather than returning None) on an unresolvable pin is the point of the
module: None means "no pin, score by intent", and quietly returning it for a
typo'd cast name is exactly the silent fallback this replaces.
"""
from scripts.lib.footage import Cast
from scripts.lib.models import HERO_RULES, HeroPin

_FORMS = ("a seed bbox [x, y, w, h] in source px, a rule "
          f"{list(HERO_RULES)}, an integer track id, or a cast name from cast.json")
# the shared half of the two bbox rejections, so they keep reading as a pair
_BBOX_FORM = "a bbox pin is 4 numbers [x, y, w, h], centre-format, in source px"


def resolve(hero: object, cast: Cast | None = None) -> HeroPin | None:
    """manifest.hero (+ the cast registry) → a HeroPin, or None for "no pin".

    Raises ValueError with a remedy on anything that cannot be honoured.
    """
    if hero is None:
        return None
    if isinstance(hero, bool):
        # bool first: isinstance(True, int) is True, so `hero: true` would
        # otherwise resolve to track id 1
        raise ValueError(f"hero {hero!r} is not a pin — expected {_FORMS}")
    if isinstance(hero, (tuple, list)):
        if len(hero) != 4:
            raise ValueError(f"hero {list(hero)!r} is not a seed bbox — {_BBOX_FORM}; "
                             f"got {len(hero)}")
        # Deliberately the same predicate HeroPin.bbox uses (same landmine, same
        # spelling), and it runs BEFORE float() on purpose: float() would launder
        # "900"→900.0 and True→1.0, which both defeats that guard on the only wired
        # path and hands a human float()'s bare "could not convert string to float"
        # via validate(). float() stays — JSON gives ints, _seed_track wants floats.
        bad = [v for v in hero if not (isinstance(v, (int, float)) and not isinstance(v, bool))]
        if bad:
            raise ValueError(f'hero {list(hero)!r} is not a seed bbox — {_BBOX_FORM}; got {bad!r}. '
                             f'Write each as a bare JSON number — 900, not "900" or true.')
        return HeroPin(kind="bbox", bbox=tuple(float(v) for v in hero))
    if isinstance(hero, int):
        return HeroPin(kind="track", track_id=hero)
    if not isinstance(hero, str) or not hero:
        raise ValueError(f"hero {hero!r} is not a pin — expected {_FORMS}")
    if hero in HERO_RULES:
        return HeroPin(kind="rule", rule=hero)
    # a non-rule string is a cast name
    if cast is None:
        raise ValueError(f"hero {hero!r} is a cast name but no cast.json was supplied — set "
                         f"EDL.cast (or pass --cast) so the name can be resolved, or use "
                         f"a rule {list(HERO_RULES)} / a seed bbox instead")
    for m in cast.members:
        if m.name == hero:
            return HeroPin(kind="cast", name=m.name, descriptor=tuple(m.descriptor))
    known = [m.name for m in cast.members]
    raise ValueError(f"hero {hero!r} is not in cast.json — known names are: "
                     f"{', '.join(known) if known else '(the cast is empty)'}. Fix the name, "
                     f"or re-run footage-intake to register the hero.")
