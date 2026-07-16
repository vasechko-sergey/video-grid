# Cast → hero-pin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the manifest's `hero` pin mean something — resolve every §5.10 pin form (seed bbox, `largest`/`leftmost` rule, track id, cast name) into a typed `HeroPin`, and stop-and-report when a pin cannot be honoured, instead of silently falling back to intent scoring.

**Architecture:** One pure resolver (`lib/hero.resolve`) turns `manifest.hero` + `cast.json` into a typed `HeroPin` at one boundary. `track.py` gains a rung per pin kind, siblings of the existing `_seed_track`; a pin given means the rung decides, with no fallback. `TrackMeta.pin_matched` reports the outcome, so `orchestration` can raise `hero-unmatched` and `is_seed_pin` can be deleted outright. The descriptor primitives move from `intake.py` to `lib/appearance.py` so a driver need not import a driver.

**Tech Stack:** Python 3, numpy + Pillow (colour histograms over YOLO-seg masks), ultralytics/ByteTrack (mocked in tests — see Testing Notes), pytest.

**Spec:** [docs/specs/2026-07-16-cast-hero-pin-design.md](../specs/2026-07-16-cast-hero-pin-design.md) — read it before Task 0. Section numbers below refer to it.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/appearance.py` **(new)** | Appearance primitives: `HIST_BINS`, `CAST_MATCH`, `build_descriptor`, `descriptor_dist`, `crop_and_mask`. Shared by `intake` (surfaces the cast) and `track` (matches a pinned cast member). No knowledge of pins or manifests. |
| `scripts/lib/hero.py` **(new)** | `resolve(hero, cast) -> HeroPin \| None`. Pure: reads descriptors out of a `Cast`, never computes one. Raises with a remedy on anything unresolvable. |
| `scripts/lib/models.py` | Vocab (`HERO_RULES`, `HERO_KINDS`) + the `HeroPin` config-spec; `TrackSpec.pin`; `TrackMeta.pin_matched`. |
| `scripts/track.py` | The rungs (`_rule_track`, `_id_track`, `_descriptor_track`) + the dispatch in `build_route`. Owns `AMBIG_MARGIN`. |
| `scripts/lib/orchestration.py` | `hero-unmatched` before `no-track`. Loses `is_seed_pin` and `detect_contradictions`' `hero` param. |
| `scripts/lib/manifest.py` | `cast` path field; `validate(m, cast=None)` using `hero.resolve` as its oracle. |
| `scripts/lib/edl.py` | `EDL.cast`; `to_manifest_dict(..., cast=)`; `preflight` loads the registry once. |
| `scripts/process_episode.py` | Loads the cast, resolves the pin, threads it into `TrackSpec`. |
| `scripts/edit_plan.py` | `build_edl(cast=)` / `write_edit_plan(cast=)` / `--cast`. |
| `scripts/intake.py` | Loses the moved primitives, re-imports them. Keeps `CAST_DEDUP` (a `surface_crops` policy, not a primitive). |

**Task order is chosen so every commit is green.** Additive work first (T0–T6); the one unavoidably-breaking change — `TrackSpec.seed_bbox` → `pin`, which breaks `track.py` and `process_episode.py` together — lands atomically in T7.

## Testing Notes (read before writing any test)

- **YOLO is faked in every test in this repo, and that is deliberate.** The synthetic `sample_clip` "is a box, not a person, so real YOLO tracking returns an empty route" (`tests/integration/test_front_spine.py:6`, `tests/integration/test_intake.py:5`); `tests/integration/test_layouts.py` uses a frozen route "so no YOLO runs". **Do not write a test that calls real YOLO.** It cannot detect a synthetic person and will return an empty route.
- The descriptor math is *not* faked in T10: the fake `res` carries real numpy pixels, so `crop_and_mask` / `build_descriptor` / `descriptor_dist` execute for real.
- Run tests with the venv module runner: `.venv/bin/python -m pytest …`. Never pipe pytest through `tail`; append `; echo "EXIT: $?"` if you need the status.
- Full suite before every commit: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`. Baseline at the start of this plan: **835 passed / 8 skipped**.
- Do **not** install anything (no brew/pip/apt/uv, no `setup.sh`). Everything this plan needs is already in the venv.

---

### Task 0: `lib/appearance.py` — the descriptor primitives move out of intake

**Files:**
- Create: `scripts/lib/appearance.py`
- Create: `tests/lib/test_appearance.py`
- Modify: `scripts/intake.py` (imports, constants at lines 30-31, `_crop_and_mask` at 209-226, `build_descriptor`/`_descriptor_dist` at 251-266, call sites at 198/254/266/276/280)

Spec §3. A verbatim move — a driver (`track.py`) must not import a driver (`intake.py`). Same move, same reason, as `marks_at_times` → `lib/geometry` in the safe-zones slice.

- [ ] **Step 1: Find every reference before moving anything**

Run: `grep -rn "_descriptor_dist\|build_descriptor\|_crop_and_mask\|_HIST_BINS" scripts/ tests/`

Expected: hits in `scripts/intake.py` only (definitions + call sites). If any test references a private name, that reference must be updated in this task — note it now, do not discover it at commit time.

- [ ] **Step 2: Write the failing test**

Create `tests/lib/test_appearance.py`:

```python
import numpy as np

from scripts.lib import appearance


def _crop(rgb):
    """A 4x4 crop of one solid colour."""
    return np.full((4, 4, 3), rgb, dtype=np.uint8)


def test_descriptor_is_l1_normalized():
    d = appearance.build_descriptor(_crop((200, 10, 10)), None)
    assert len(d) == 3 * appearance.HIST_BINS
    assert abs(sum(d) - 1.0) < 1e-9


def test_descriptor_dist_range_is_zero_to_two():
    red = appearance.build_descriptor(_crop((250, 0, 0)), None)
    blue = appearance.build_descriptor(_crop((0, 0, 250)), None)
    assert appearance.descriptor_dist(red, red) == 0.0
    # disjoint supports → the maximum
    assert abs(appearance.descriptor_dist(red, blue) - 2.0) < 1e-9


def test_descriptor_uses_mask_pixels_only():
    # left half red (masked in), right half blue (masked out) → the descriptor
    # must equal the all-red one: the mask cuts the background away (§6.1a)
    crop = np.zeros((4, 4, 3), dtype=np.uint8)
    crop[:, :2] = (250, 0, 0)
    crop[:, 2:] = (0, 0, 250)
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[:, :2] = 255
    assert appearance.build_descriptor(crop, mask) == appearance.build_descriptor(_crop((250, 0, 0)), None)


def test_descriptor_falls_back_to_whole_crop_when_mask_is_empty():
    crop = _crop((250, 0, 0))
    assert appearance.build_descriptor(crop, np.zeros((4, 4), dtype=np.uint8)) == \
           appearance.build_descriptor(crop, None)


def test_crop_and_mask_without_orig_img_is_none():
    class _Res:
        orig_img = None
    assert appearance.crop_and_mask(_Res(), 0, object()) == (None, None)


def test_cast_match_is_below_the_distance_maximum():
    assert 0.0 < appearance.CAST_MATCH < 2.0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_appearance.py -q; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.appearance'`

- [ ] **Step 4: Create `scripts/lib/appearance.py`**

```python
"""Appearance descriptors — the identity primitives (§6.1a layer 1).

Shared by intake (surfaces and names the cast) and track (matches a pinned cast
member against this episode's tracks). They live here, not in intake.py, because
a driver must not import a driver — the same reason marks_at_times moved to
lib/geometry. numpy + Pillow, no cv2.
"""
import numpy as np
from PIL import Image

HIST_BINS = 8
CAST_MATCH = 0.6      # max L1 descriptor distance for "this track IS that cast member".
                      # descriptor_dist ranges [0.0, 2.0], so this is 30% of the max:
                      # necessarily looser than intake's CAST_DEDUP (0.30, "are these two
                      # crops the same person") because a cast descriptor is snapped from a
                      # different clip's lighting and pose — yet tight enough that "the
                      # pinned person is not in this episode at all" still fails. A FIRST
                      # CUT, not a derived number: the real discriminator is min-distance
                      # among the tracks present plus track.py's margin rule; this only
                      # guards absence. Deriving it from cast_candidates.json's distance
                      # distribution is a deferred slice (design §11).


def build_descriptor(crop_rgb: object, mask: object) -> list[float]:
    """L1-normalized color histogram over the segmentation-mask pixels only
    (clothing/gear — background removed; §6.1a). numpy + Pillow, no cv2."""
    px = crop_rgb[mask > 0] if mask is not None else crop_rgb.reshape(-1, 3)
    if px.size == 0:
        px = crop_rgb.reshape(-1, 3)
    hist: list[float] = []
    for c in range(3):
        h, _ = np.histogram(px[:, c], bins=HIST_BINS, range=(0, 255))
        hist.extend(h.tolist())
    total = float(sum(hist)) or 1.0
    return [v / total for v in hist]


def descriptor_dist(a: list[float], b: list[float]) -> float:
    """L1 distance between two descriptors. Range [0.0, 2.0]: each descriptor is
    normalized over its GRAND total, so both sum to 1.0 and the maximum is
    attained exactly when their supports are disjoint."""
    return sum(abs(x - y) for x, y in zip(a, b))


def crop_and_mask(res: object, idx: int, box: object) -> tuple:
    """Extract the box's crop (RGB) + seg mask from an ultralytics result. Returns
    (None, None) when the frame image or masks are unavailable (mocked tests)."""
    img = getattr(res, "orig_img", None)
    if img is None:
        return None, None
    arr = np.asarray(img)[..., ::-1]                       # ultralytics orig_img is BGR → RGB
    x, y, w, h = (float(v) for v in box.xywh[0])
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = arr[t:b_, l:r_]
    mask = None
    masks = getattr(res, "masks", None)
    if masks is not None and getattr(masks, "data", None) is not None:
        m = np.asarray(masks.data[idx])                    # (H, W) in model space
        m = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((arr.shape[1], arr.shape[0])))
        mask = m[t:b_, l:r_]
    return (crop if crop.size else None), mask
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_appearance.py -q; echo "EXIT: $?"`
Expected: PASS (6 tests)

- [ ] **Step 6: Gut intake.py of the moved code**

In `scripts/intake.py`: delete the `build_descriptor`, `_descriptor_dist` and `_crop_and_mask` definitions and the `_HIST_BINS = 8` constant. **Keep `CAST_DEDUP = 0.30`** — it is a `surface_crops` dedup policy, not an appearance primitive. Add to the import block (line 18 region):

```python
from scripts.lib import assembly, footage, proc
from scripts.lib.appearance import build_descriptor, crop_and_mask, descriptor_dist
```

Then update the three call sites to the public names:
- line ~198 (`_people_timeline`): `crop_rgb, mask = crop_and_mask(r, j, b)`
- line ~276 (`surface_crops`): `items.append((tid, conf, crop_rgb, mask, build_descriptor(crop_rgb, mask)))` — unchanged, `build_descriptor` is now imported
- line ~280 (`surface_crops`): `if all(descriptor_dist(it[4], p[4]) > CAST_DEDUP for p in picked):`

`np`/`Image` stay imported in intake — it still uses them elsewhere. If ruff/flake reports either as unused, remove that import; do not leave a dead one.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: **841 passed / 8 skipped**, EXIT 0 (835 + the 6 new). If an intake test fails on a private name, fix the reference — Step 1 should have found it.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/appearance.py scripts/intake.py tests/lib/test_appearance.py
git commit -m "refactor: appearance descriptors → lib/appearance (track must not import intake)"
```

---

### Task 1: `models.py` — `HERO_RULES`, `HERO_KINDS`, the `HeroPin` config-spec

**Files:**
- Modify: `scripts/lib/models.py:11-15` (vocab), and append `HeroPin` near `TrackSpec`
- Test: `tests/lib/test_models.py`

Spec §2. Vocab lives with `COMPOSITIONS`/`GRIDS`/`MOTIONS`/`INTENTS`; the config-spec validates-and-raises in `__post_init__` like every other one.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_models.py`:

```python
def test_hero_pin_bbox():
    p = models.HeroPin(kind="bbox", bbox=(900.0, 500.0, 120.0, 300.0))
    assert p.kind == "bbox" and p.bbox == (900.0, 500.0, 120.0, 300.0)


def test_hero_pin_rule_rejects_unknown_rule():
    assert models.HeroPin(kind="rule", rule="largest").rule == "largest"
    with pytest.raises(ValueError, match="HERO_RULES|largest"):
        models.HeroPin(kind="rule", rule="tallest")


def test_hero_pin_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        models.HeroPin(kind="vibes")


def test_hero_pin_bbox_must_be_a_4_tuple():
    for bad in (None, (1, 2, 3), [1, 2, 3, 4], (1, 2, 3, 4, 5)):
        with pytest.raises(ValueError, match="bbox"):
            models.HeroPin(kind="bbox", bbox=bad)


def test_hero_pin_track_id_rejects_bool_and_none():
    assert models.HeroPin(kind="track", track_id=0).track_id == 0   # 0 is a real track id
    for bad in (None, True, 1.5, "3"):
        with pytest.raises(ValueError, match="track_id"):
            models.HeroPin(kind="track", track_id=bad)


def test_hero_pin_cast_needs_a_name_and_a_descriptor():
    p = models.HeroPin(kind="cast", name="Lena", descriptor=(0.5, 0.5))
    assert p.name == "Lena" and p.descriptor == (0.5, 0.5)
    with pytest.raises(ValueError, match="name"):
        models.HeroPin(kind="cast", name="", descriptor=(0.5, 0.5))
    with pytest.raises(ValueError, match="descriptor"):
        models.HeroPin(kind="cast", name="Lena", descriptor=())


def test_hero_pin_is_frozen():
    p = models.HeroPin(kind="rule", rule="leftmost")
    with pytest.raises(Exception):
        p.rule = "largest"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k hero_pin -q; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.models' has no attribute 'HeroPin'`

- [ ] **Step 3: Add the vocab**

`scripts/lib/models.py`, after line 15 (`INTENTS = ("action", "static")`):

```python
HERO_RULES = ("largest", "leftmost")          # §5.10 rule pins — mechanical, no identity claim
HERO_KINDS = ("bbox", "rule", "track", "cast")
```

- [ ] **Step 4: Add the config-spec**

`scripts/lib/models.py`, immediately above `TrackSpec`:

```python
@dataclass(frozen=True)
class HeroPin:
    """A RESOLVED §5.10 hero pin — the one shape every consumer agrees on.

    The manifest's `hero` is a raw value (tuple / str / int); this is what
    hero.resolve() turns it into, once, at the boundary. Frozen: resolve hands it
    over already-coerced, so nothing downstream re-guesses with isinstance.
    """
    kind: str
    bbox: tuple[float, float, float, float] | None = None
    rule: str = ""
    track_id: int | None = None
    name: str = ""
    descriptor: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in HERO_KINDS:
            raise ValueError(f"HeroPin.kind {self.kind!r} unknown — expected one of {HERO_KINDS}")
        if self.kind == "bbox" and not (isinstance(self.bbox, tuple) and len(self.bbox) == 4
                                        and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                for v in self.bbox)):
            raise ValueError(f"HeroPin(kind='bbox').bbox must be a 4-tuple of numbers "
                             f"(centre-format x,y,w,h in source px), got {self.bbox!r}")
        if self.kind == "rule" and self.rule not in HERO_RULES:
            raise ValueError(f"HeroPin(kind='rule').rule {self.rule!r} unknown — "
                             f"expected one of {HERO_RULES}")
        if self.kind == "track" and (isinstance(self.track_id, bool)
                                     or not isinstance(self.track_id, int)):
            # bool first: isinstance(True, int) is True, so `hero: true` would become track 1
            raise ValueError(f"HeroPin(kind='track').track_id must be an int, got {self.track_id!r}")
        if self.kind == "cast":
            if not (isinstance(self.name, str) and self.name):
                raise ValueError("HeroPin(kind='cast').name must be a non-empty cast name")
            if not (isinstance(self.descriptor, tuple) and self.descriptor):
                raise ValueError(f"HeroPin(kind='cast').descriptor must be a non-empty tuple "
                                 f"of numbers, got {self.descriptor!r}")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k hero_pin -q; echo "EXIT: $?"`
Expected: PASS (7 tests)

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **848 passed / 8 skipped**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: HeroPin config-spec + HERO_RULES/HERO_KINDS vocab (§5.10 pin forms)"
```

---

### Task 2: `lib/hero.py` — the pure resolver

**Files:**
- Create: `scripts/lib/hero.py`
- Create: `tests/lib/test_hero.py`

Spec §2. Every §5.10 form in; a `HeroPin` or `None` out; a `ValueError` with a remedy for anything else. **`None` means "no pin, score by intent" and nothing else** — returning it for an unresolvable pin would re-create the exact silent fallback this slice deletes.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_hero.py`:

```python
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
    # isinstance(True, int) is True — `hero: true` must not become track id 1
    for bad in (True, False):
        with pytest.raises(ValueError, match="hero"):
            hero.resolve(bad)


def test_malformed_values_raise():
    for bad in ((), "", [1, 2, 3], (1, 2, 3), {}, 4.2, [], {"rule": "largest"}):
        with pytest.raises(ValueError):
            hero.resolve(bad, _cast())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_hero.py -q; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.hero'`

- [ ] **Step 3: Create `scripts/lib/hero.py`**

```python
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
            raise ValueError(f"hero {list(hero)!r} is not a seed bbox — a bbox pin is 4 numbers "
                             f"[x, y, w, h], centre-format, in source px; got {len(hero)}")
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
    known = [m.name for m in cast.members]
    for m in cast.members:
        if m.name == hero:
            return HeroPin(kind="cast", name=m.name, descriptor=tuple(m.descriptor))
    raise ValueError(f"hero {hero!r} is not in cast.json — known names are: "
                     f"{', '.join(known) if known else '(the cast is empty)'}. Fix the name, "
                     f"or re-run footage-intake to register the hero.")
```

Note the `float()` coercion on the bbox: JSON gives ints, `_seed_track` does float maths, and `HeroPin` demands numbers — coerce once, here.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_hero.py -q; echo "EXIT: $?"`
Expected: PASS (10 tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **858 passed / 8 skipped**

```bash
git add scripts/lib/hero.py tests/lib/test_hero.py
git commit -m "feat: hero.resolve — every §5.10 pin form → a typed HeroPin, raises with a remedy"
```

---

### Task 3: `track.py` — `AMBIG_MARGIN` + the two kinematic rungs

**Files:**
- Modify: `scripts/track.py` (add `AMBIG_MARGIN` near `MODEL` at line 13; add `_rule_track`/`_id_track` after `_seed_track` at line 66; `_pick_hero` line 125 uses the constant)
- Test: `tests/integration/test_track.py`

Spec §4. Pure functions over the `feats` dict — additive, nothing breaks.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_track.py`:

```python
def _feats():
    # tid 1: left + small; tid 2: right + large
    return {1: {"n": 10, "disp": 0.0, "area": 100.0, "x0": 300.0, "speed": 0.0, "border": None},
            2: {"n": 10, "disp": 0.0, "area": 900.0, "x0": 1500.0, "speed": 0.0, "border": None}}


def test_rule_track_largest():
    assert track._rule_track(_feats(), "largest") == 2


def test_rule_track_leftmost():
    assert track._rule_track(_feats(), "leftmost") == 1


def test_rule_track_breaks_ties_on_the_lowest_id():
    feats = {5: {"area": 100.0, "x0": 10.0}, 2: {"area": 100.0, "x0": 10.0}}
    assert track._rule_track(feats, "largest") == 2
    assert track._rule_track(feats, "leftmost") == 2


def test_rule_track_empty_feats_is_unmatched():
    assert track._rule_track({}, "largest") is None


def test_id_track_hit_and_miss():
    assert track._id_track(_feats(), 2) == 2
    assert track._id_track(_feats(), 99) is None


def test_ambig_margin_is_the_one_spelling_of_the_margin_rule():
    assert track.AMBIG_MARGIN == 0.8
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -k "rule_track or id_track or ambig" -q; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.track' has no attribute '_rule_track'`

- [ ] **Step 3: Add the constant**

`scripts/track.py`, after `MODEL = "yolo11n-seg.pt"` (line 13):

```python
AMBIG_MARGIN = 0.8      # §6.1a margin rule: top-2 within ~20% ⇒ ambiguous ⇒ stop-and-report.
                        # One spelling, two readers (_pick_hero, _descriptor_track).
```

- [ ] **Step 4: Add the rungs after `_seed_track`**

```python
def _rule_track(feats: dict[int, dict], rule: str) -> int | None:
    """Track id chosen by a mechanical §5.10 rule pin. Ties break on the lowest
    track id so a re-run is deterministic.

    A rule makes no claim about identity — the human said "largest", so largest
    wins — which is why, unlike _descriptor_track and _pick_hero, this never
    reports ambiguity.
    """
    if not feats:
        return None
    if rule == "largest":
        return min(feats, key=lambda tid: (-feats[tid]["area"], tid))
    return min(feats, key=lambda tid: (feats[tid]["x0"], tid))      # leftmost


def _id_track(feats: dict[int, dict], track_id: int) -> int | None:
    """Track id pinned explicitly (§5.10). Absent from this segment ⇒ unmatched."""
    return track_id if track_id in feats else None
```

`_rule_track` reads `feats[tid]["x0"]`, which already exists: `_track_features` seeds `x0` at line 77 and its cleanup deletes only the `_`-prefixed keys. Do not add it.

- [ ] **Step 5: Point `_pick_hero` at the constant**

In `_pick_hero`, replace the inline literal:

```python
    ambiguous = (len(ranked) > 1
                 and score(ranked[1][1]) >= AMBIG_MARGIN * score(ranked[0][1]))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -q; echo "EXIT: $?"`
Expected: PASS — the 6 new plus all 9 existing (the `_pick_hero` edit is value-identical).

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **864 passed / 8 skipped**

```bash
git add scripts/track.py tests/integration/test_track.py
git commit -m "feat: _rule_track/_id_track rungs + AMBIG_MARGIN (one spelling of the §6.1a margin)"
```

---

### Task 4: `track.py` — masks reach the tracker; `_descriptor_track`

**Files:**
- Modify: `scripts/track.py:33-46` (`_iter_detections`), `:143-155` (`build_route`'s detection loop), add `_track_crops` + `_descriptor_track`
- Modify: `tests/integration/test_track.py` — **all nine** monkeypatches (see below)

Spec §4 + §10. `_iter_detections` yields the whole `res` instead of `res.boxes`. Masks are only *touched* when a cast pin is set — but the yield shape changes for everyone, which is why every existing fake must gain a wrapper.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_track.py`:

```python
def _desc(*channels):
    """A hand-built descriptor: `channels` are per-channel weights, HIST_BINS wide."""
    from scripts.lib.appearance import HIST_BINS
    d = []
    for w in channels:
        d.extend([w / HIST_BINS] * HIST_BINS)
    return tuple(d)


def test_descriptor_track_picks_the_closest():
    crops = {1: [1.0, 0.0, 0.0] + [0.0] * 21, 2: [0.0, 0.0, 1.0] + [0.0] * 21}
    pin = tuple([0.0, 0.0, 1.0] + [0.0] * 21)
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id == 2 and ambiguous is False


def test_descriptor_track_beyond_the_threshold_is_unmatched():
    # both tracks sit at the maximum distance (disjoint supports) → nobody matches
    crops = {1: [1.0] + [0.0] * 23, 2: [1.0] + [0.0] * 23}
    pin = tuple([0.0] * 23 + [1.0])
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id is None and ambiguous is False


def test_descriptor_track_margin_flags_ambiguity():
    # two near-identical descriptors → d1 >= 0.8*d2 → §6.1a mode 1
    crops = {1: [0.50, 0.50] + [0.0] * 22, 2: [0.52, 0.48] + [0.0] * 22}
    pin = tuple([0.51, 0.49] + [0.0] * 22)
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id in (1, 2) and ambiguous is True


def test_descriptor_track_single_track_is_never_ambiguous():
    crops = {7: [1.0, 0.0] + [0.0] * 22}
    hero_id, ambiguous = track._descriptor_track(crops, tuple([1.0, 0.0] + [0.0] * 22))
    assert hero_id == 7 and ambiguous is False


def test_descriptor_track_no_crops_is_unmatched():
    assert track._descriptor_track({}, _desc(1.0, 0.0, 0.0)) == (None, False)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -k descriptor_track -q; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.track' has no attribute '_descriptor_track'`

- [ ] **Step 3: Change `_iter_detections` to yield the result**

```python
def _iter_detections(src: str, model_path: str = MODEL) -> Iterator[tuple[int, Any]]:
    """Yield (frame_index, ultralytics_result) using YOLO+ByteTrack.

    Yields the whole result, not just .boxes: a cast-name hero pin needs the seg
    masks + frame pixels to build a per-track appearance descriptor (§6.1a). The
    masks are only READ on that path — every other pin costs nothing extra.
    Isolated for testability; res.boxes expose .xywh, .id, .cls like ultralytics.
    """
    # lazy import: heavy optional dep (ultralytics/torch)
    from ultralytics import YOLO
    model = YOLO(model_path)
    # imgsz=960: detect on downscaled frames (~10x faster on 4K); ultralytics
    # rescales box coords back to source resolution itself.
    for i, res in enumerate(model.track(src, stream=True, persist=True,
                                        classes=[0], tracker="bytetrack.yaml",
                                        imgsz=960, verbose=False)):
        yield i, res
```

- [ ] **Step 4: Add `_track_crops` + `_descriptor_track`**

After `_id_track`:

```python
def _track_crops(res: object, boxes: list, crops: dict) -> None:
    """Accumulate the highest-confidence crop DESCRIPTOR per track id, in place.

    Mirrors intake._people_timeline: one crop_and_mask per confidence improvement
    (≈ once per track), never once per frame. crop_and_mask carries the two
    landmines — ultralytics' orig_img is BGR, and the mask is in model space and
    must be resized to source dims — and returns (None, None) for a mocked result
    with no pixels, which is how every track test drives this.
    """
    for j, b in enumerate(boxes):
        if getattr(b, "id", None) is None:
            continue
        tid = int(b.id[0])
        conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
        if conf <= crops.get(tid, (-1.0,))[0]:
            continue
        crop_rgb, mask = appearance.crop_and_mask(res, j, b)
        if crop_rgb is not None:
            crops[tid] = (conf, appearance.build_descriptor(crop_rgb, mask))


def _descriptor_track(descs: dict[int, list[float]],
                      pin: tuple[float, ...]) -> tuple[int | None, bool]:
    """Track id whose appearance descriptor is closest to the pinned cast member's
    (§6.1a layer 2: a cast name makes descriptor similarity outrank kinematics).

    Returns (hero_id, ambiguous). Nobody within CAST_MATCH ⇒ (None, False) — the
    pinned person is not in this episode. The margin rule is expressed on DISTANCE
    (d1 >= AMBIG_MARGIN * d2 ⇒ ambiguous: the best match is not meaningfully closer
    than the runner-up), not on a similarity ratio, because lower-is-better here —
    a similarity transform pushes both terms to ~1.0 whenever both matches are
    good and would call every clean match ambiguous. Two people in similar
    clothing is §6.1a's mode 1, the failure a colour histogram is most exposed to.
    """
    if not descs:
        return None, False
    ranked = sorted(((appearance.descriptor_dist(d, list(pin)), tid)
                     for tid, d in descs.items()))
    d1, hero_id = ranked[0]
    if d1 > appearance.CAST_MATCH:
        return None, False
    ambiguous = len(ranked) > 1 and ranked[1][0] > 0 and d1 >= AMBIG_MARGIN * ranked[1][0]
    return hero_id, ambiguous
```

Add to the imports at the top of `track.py`:

```python
from scripts.lib import appearance, proc
```

`_descriptor_track` takes `{tid: descriptor}` while `_track_crops` stores `{tid: (conf, descriptor)}` — `build_route` (Task 7) strips the conf. Keeping conf in the accumulator is what makes "highest-confidence wins" work; keeping it out of the matcher is what makes the matcher a pure function of descriptors.

- [ ] **Step 5: Rewrite `build_route`'s detection loop for the new yield**

In `build_route`, replace the `for idx, boxes in _iter_detections(...)` block:

```python
    per_frame, crops = [], {}
    for idx, res in _iter_detections(spec.src, model_path=spec.model):
        boxes = list(res.boxes) if getattr(res, "boxes", None) is not None else []
        dets = []
        for b in boxes:
            if b.id is None:
                # unconfirmed ByteTrack detection (normal in first frames /
                # after occlusion) — do NOT fabricate a shared tid=-1 track,
                # it would merge unrelated people into one fake "hero"
                continue
            x, y, w, h = [float(v) for v in b.xywh[0]]
            tid = int(b.id[0])
            dets.append((tid, x, y, w, h))
        per_frame.append((idx, dets))
```

Leave the rest of `build_route` alone — the pin dispatch lands in Task 7. `crops` is declared here but not filled until then; that is fine and keeps this commit green.

- [ ] **Step 6: Give the test fakes a result wrapper**

At the top of `tests/integration/test_track.py`, after `_FakeBox`:

```python
class _FakeRes:
    """An ultralytics-result-shaped fake: boxes only. No orig_img/masks, so
    appearance.crop_and_mask returns (None, None) — the same way the intake tests
    drive it. Tests that need real pixels build their own (see test_cast_pin.py)."""
    def __init__(self, boxes):
        self.boxes = boxes
        self.orig_img = None
        self.masks = None


def _fake_iter(frames):
    """The monkeypatch body every track test shares: frames of boxes → (i, res)."""
    return lambda src, **k: iter(enumerate(_FakeRes(f) for f in frames))
```

Then replace all nine two-line monkeypatches (`test_track.py` lines 12, 26, 42, 53, 72, 84, 96, 110) with the one-liner:

```python
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
```

- [ ] **Step 7: Run the whole track file to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_track.py -q; echo "EXIT: $?"`
Expected: PASS — 9 existing + 6 from Task 3 + 5 new = 20.

- [ ] **Step 8: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **869 passed / 8 skipped**

```bash
git add scripts/track.py tests/integration/test_track.py
git commit -m "feat: _descriptor_track + per-track crop descriptors (track keeps masks on the cast path)"
```

---

### Task 5: `manifest.py` — the `cast` field and the hero the gate never checked

**Files:**
- Modify: `scripts/lib/manifest.py:14` (`OPTIONAL`), `:31` (`hero` type), `:70-87` (`from_dict`), `:90` (`validate` signature) and its body
- Test: `tests/lib/test_manifest.py`

Spec §6. `validate()` does **no I/O** — a documented, deliberate convention (`manifest.py:119`: *"the gate would have to probe the file, and this gate runs before YOLO. Do not 'fix' it to probe here."*). So the caller loads the registry and hands it in, and `hero.resolve` becomes the oracle — a calque of the `LayoutSpec` pattern already at `:109-114`.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_manifest.py`:

```python
from scripts.lib.footage import Cast, CastMember


def _cast():
    return Cast(members=[CastMember(name="Lena", descriptor=[0.5, 0.5])])


def test_cast_path_round_trips():
    m = mf.Manifest.from_dict(_ok_dict(cast="proj/cast.json"))
    assert m.cast == "proj/cast.json"


def test_cast_defaults_to_empty():
    assert mf.Manifest.from_dict(_ok_dict()).cast == ""


def test_hero_track_id_survives_from_dict():
    assert mf.Manifest.from_dict(_ok_dict(hero=3)).hero == 3


def test_validate_accepts_a_rule_hero_without_a_cast():
    assert mf.validate(mf.Manifest.from_dict(_ok_dict(hero="largest"))) == []


def test_validate_accepts_a_known_cast_name():
    m = mf.Manifest.from_dict(_ok_dict(hero="Lena", cast="proj/cast.json"))
    assert mf.validate(m, cast=_cast()) == []


def test_validate_flags_a_cast_name_with_no_registry():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(hero="Lena")))
    assert any("cast.json" in p for p in problems)


def test_validate_flags_an_unknown_cast_name():
    m = mf.Manifest.from_dict(_ok_dict(hero="Lna", cast="proj/cast.json"))
    assert any("Lena" in p for p in mf.validate(m, cast=_cast()))


def test_validate_flags_a_malformed_hero():
    for bad in ([1, 2, 3], True, 4.2):
        assert mf.validate(mf.Manifest.from_dict(_ok_dict(hero=bad))), bad
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py -k "cast or hero" -q; echo "EXIT: $?"`
Expected: FAIL — `KeyError: manifest has unknown field(s) ['cast']`

- [ ] **Step 3: Widen the contract**

`scripts/lib/manifest.py`:

```python
OPTIONAL = ("layout", "motion", "hero", "cast", "color_means", "stabilize", "model", "delivery",
            "crop_aspect", "crop_scale", "rect", "background", "border_px", "border_color")
```

The `hero` field's type and a new `cast`:

```python
    hero: tuple | str | int | None = None
    cast: str = ""                       # cast.json path — a cast-name hero needs the registry,
                                         # and the manifest is a self-contained brief (§14.4)
```

In `from_dict`, after the existing `hero` list→tuple coercion, add `cast` to the constructor call:

```python
            hero=hero, cast=d.get("cast") or "",
```

- [ ] **Step 4: Add the oracle to `validate`**

```python
def validate(m: Manifest, cast: Cast | None = None) -> list[str]:
    """Return a list of human-readable problem strings (empty = ok).

    `cast` is the LOADED registry, handed in by the caller: this gate does no
    I/O (see the crop_aspect note below), so it cannot read m.cast itself.
    """
```

and, next to the `LayoutSpec` oracle block:

```python
    # hero.resolve is the HARD backstop; here it is the soft gate's oracle, exactly
    # like LayoutSpec above. Its ValueError (a malformed pin, a cast name with no
    # registry, a name absent from the cast) becomes a problem string — the gate
    # never raises. One function for validation and for the shell's real
    # resolution, so the two cannot drift apart.
    try:
        hero_lib.resolve(m.hero, cast)
    except ValueError as e:
        problems.append(str(e))
```

Imports at the top of `manifest.py`:

```python
from scripts.lib import hero as hero_lib
from scripts.lib.footage import Cast
from scripts.lib.models import COMPOSITIONS, GRIDS, MODELS, MOTIONS, Delivery, LayoutSpec
```

(`hero` is aliased because `Manifest.hero` would shadow the module inside methods.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py -q; echo "EXIT: $?"`
Expected: PASS. `test_hero_string_rule_kept` still passes — `"largest"` is a rule and always was kept.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **877 passed / 8 skipped**

```bash
git add scripts/lib/manifest.py tests/lib/test_manifest.py
git commit -m "feat: manifest carries the cast path; validate() finally gates hero (resolve as oracle)"
```

---

### Task 6: `edl.py` — the registry rides at EDL level

**Files:**
- Modify: `scripts/lib/edl.py:42` (`hero` type), `:93-146` (`EDL`), `:165-187` (`to_manifest_dict`), `:190-213` (`preflight`)
- Test: `tests/lib/test_edl.py`

Spec §7. `cast.json` is one file per project, so it rides on `EDL` beside `music` and crosses to each manifest in the field map that documents the boundary.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_edl.py`:

```python
def test_edl_cast_round_trips():
    e = edl.EDL(episodes=(_ep(),), cast="proj/cast.json")
    assert edl.EDL.from_dict(e.to_dict()).cast == "proj/cast.json"


def test_edl_cast_defaults_to_none():
    assert edl.EDL(episodes=(_ep(),)).cast is None


def test_edl_cast_rejects_an_empty_string():
    with pytest.raises(ValueError, match="cast"):
        edl.EDL(episodes=(_ep(),), cast="")


def test_episode_hero_accepts_a_track_id():
    assert _ep(hero=3).hero == 3


def test_bridge_forwards_the_cast_path():
    md = edl.to_manifest_dict(_ep(hero="Lena"), "s.mp4", "o.mp4", cast="proj/cast.json")
    assert md["hero"] == "Lena" and md["cast"] == "proj/cast.json"


def test_bridge_omits_the_cast_when_absent():
    assert "cast" not in edl.to_manifest_dict(_ep(), "s.mp4", "o.mp4")
```

`_ep(**kw)` is the file's existing episode factory — reuse it; if it does not accept `hero`, pass it through its `**kw`.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -k cast -q; echo "EXIT: $?"`
Expected: FAIL — `TypeError: EDL.__init__() got an unexpected keyword argument 'cast'`

- [ ] **Step 3: Widen `EDLEpisode.hero`**

`scripts/lib/edl.py:42`:

```python
    hero: tuple | str | int | None = None   # seed bbox / rule / track id / cast name (§5.10);
                                            # NOT validated here — see the class docstring: the
                                            # manifest gate reached via preflight is its one home
```

Add **no** validation. `EDLEpisode`'s docstring already sets the rule: *"Layout-parameter cross-validation … is NOT duplicated here — it has one home, LayoutSpec, reached via the manifest gate in the driver's preflight."* The hero's one home is `validate(m, cast=)`.

- [ ] **Step 4: Add `EDL.cast`**

```python
    episodes: tuple[EDLEpisode, ...]
    music: str | None = None       # MUSIC.json path; None → a silent reel (Phase A.5 path)
    cast: str | None = None        # cast.json path; needed only when an episode pins a cast name
    cap: int = 3                   # build_reel reprocess cap
    target_dur: float | None = None
```

In `__post_init__`, beside the `music` guard:

```python
        if self.cast is not None and not (isinstance(self.cast, str) and self.cast):
            raise ValueError("EDL.cast must be a cast.json path or null, got an empty/non-str value")
```

In `from_dict`: `cast=d.get("cast")`. In `to_dict`: `"cast": self.cast`.

- [ ] **Step 5: Carry the cast across the bridge**

```python
def to_manifest_dict(ep: EDLEpisode, segment: str, out_path: str,
                     cast: str | None = None) -> dict:
```

and, at the end of the body:

```python
    if ep.hero is not None:
        md["hero"] = list(ep.hero) if isinstance(ep.hero, tuple) else ep.hero
    if cast is not None:
        md["cast"] = cast          # reel-level, but a cast-name hero is resolved per episode,
                                   # and the manifest must stay a self-contained brief (§14.4)
    return md
```

- [ ] **Step 6: Load the registry once in `preflight`**

```python
    mds: list[dict] = []
    cast = None
    if edl.cast is not None:
        try:
            cast = Cast.from_json(edl.cast)
        except (OSError, ValueError) as e:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": None,
                                     "problems": [f"EDL.cast {edl.cast!r} is unreadable — {e}"]}}
    for i, ep in enumerate(edl.episodes):
        seg = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        md = resolve_manifest(to_manifest_dict(ep, seg, str(Path(out_dir) / f"ep{i}.mp4"),
                                               cast=edl.cast), cfg)
        try:
            m = Manifest.from_dict(md)
        except (KeyError, TypeError, ValueError) as e:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": i, "problems": [str(e)]}}
        problems = validate(m, cast=cast)
        if problems:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": i, "problems": problems}}
        mds.append(md)
    return mds, None
```

Import `Cast`: `from scripts.lib.footage import Cast`. Loading it **once, before the loop** is the point — a 12-episode EDL must not read the registry 12 times. Amend the docstring's "validate() never touches the filesystem" sentence to say that preflight reads `EDL.cast` once, before the loop, and hands the loaded registry to each `validate`.

- [ ] **Step 7: Run the tests, the full suite, and commit**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q; echo "EXIT: $?"` → PASS
Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **883 passed / 8 skipped**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat: EDL.cast rides to each manifest; preflight loads the registry once"
```

---

### Task 7: `TrackSpec.pin` + the dispatch + the shell (the atomic rename)

**Files:**
- Modify: `scripts/lib/models.py:44-57` (`TrackMeta`), `:270-288` (`TrackSpec`)
- Modify: `scripts/track.py` (`build_route` dispatch, CLI at `:184-200`)
- Modify: `scripts/process_episode.py:94-100`
- Test: `tests/lib/test_models.py`, `tests/integration/test_track.py`, `tests/integration/test_process_episode.py`

Spec §4 + §7. `TrackSpec.seed_bbox` → `pin` breaks `track.py` and `process_episode.py` at once — hence one task, so the suite is never red at a commit. A deprecation shuffle for a single-consumer internal config-spec would be over-engineering.

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_models.py`:

```python
def test_track_spec_takes_a_pin():
    p = models.HeroPin(kind="rule", rule="largest")
    assert models.TrackSpec(src="s.mp4", pin=p).pin is p
    assert models.TrackSpec(src="s.mp4").pin is None


def test_track_spec_rejects_a_raw_hero_value():
    with pytest.raises(ValueError, match="pin"):
        models.TrackSpec(src="s.mp4", pin=(900, 500, 120, 300))


def test_track_meta_pin_matched_round_trips():
    for v in (True, False, None):
        m = models.TrackMeta(hero=1, pin_matched=v)
        assert models.TrackMeta.from_dict(m.to_dict()).pin_matched is v


def test_track_meta_pin_matched_defaults_to_none():
    assert models.TrackMeta().pin_matched is None
```

`tests/integration/test_track.py` — replace `test_route_seed_pin` and add the rung tests:

```python
def test_route_bbox_pin(monkeypatch, tmp_path):
    # two persistent tracks; the seed bbox must pin the RIGHT one as hero
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 120, 300], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="bbox", bbox=(1500.0, 500.0, 120.0, 300.0)))
    route = track.build_route(spec, out=str(out))
    assert all(pt.x == 1500 for pt in route)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is True


def test_route_rule_pin(monkeypatch, tmp_path):
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 300, 700], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="rule", rule="largest"))
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    assert all(pt.x == 1500 for pt in route)


def test_route_track_id_pin(monkeypatch, tmp_path):
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 120, 300], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="track", track_id=1))
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    assert all(pt.x == 300 for pt in route)


def test_unmatched_pin_never_falls_back_to_scoring(monkeypatch, tmp_path):
    # the pinned track id is not in this segment: the route must be EMPTY and the
    # sidecar must say so — silently following whoever scored highest is the bug
    # this slice deletes
    frames = [[_FakeBox([300, 500, 140, 320], 1)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="track", track_id=99))
    route = track.build_route(spec, out=str(out))
    assert route == []
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is False and meta.hero is None


def test_no_pin_leaves_pin_matched_none(monkeypatch, tmp_path):
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    track.build_route(models.TrackSpec(src="ignored.mp4", fps=30), out=str(out))
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is None
```

`tests/integration/test_process_episode.py` — replace `test_seed_bbox_threaded_to_track`'s assertion so the fake captures `spec.pin` instead of `spec.seed_bbox`, and assert:

```python
    assert calls["track_pin"] == models.HeroPin(kind="bbox", bbox=(900.0, 500.0, 120.0, 300.0))
```

(`HeroPin` is a frozen dataclass, so `==` is structural.)

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/integration/test_track.py -q; echo "EXIT: $?"`
Expected: FAIL — `TypeError: TrackSpec.__init__() got an unexpected keyword argument 'pin'`

- [ ] **Step 3: `TrackMeta.pin_matched`**

```python
@dataclass
class TrackMeta:
    hero: int | None = None        # int track id or None
    ambiguous: bool = False
    intent: str = "action"
    features: dict = field(default_factory=dict)
    pin_matched: bool | None = None    # None = no pin was given; False = a pin was given and
                                       # nothing matched it → orchestration raises hero-unmatched

    @classmethod
    def from_dict(cls, d: dict) -> "TrackMeta":
        return cls(hero=d.get("hero"), ambiguous=bool(d.get("ambiguous", False)),
                   intent=d.get("intent", "action"), features=d.get("features", {}),
                   pin_matched=d.get("pin_matched"))

    def to_dict(self) -> dict:
        return {"hero": self.hero, "ambiguous": self.ambiguous,
                "intent": self.intent, "features": self.features,
                "pin_matched": self.pin_matched}
```

`pin_matched` **must** round-trip: the sidecar is how the shell learns the outcome, and a field that does not serialize is a gate that never fires.

- [ ] **Step 4: `TrackSpec.pin`**

```python
@dataclass
class TrackSpec:
    src: str
    model: str = "yolo11n-seg.pt"
    pin: HeroPin | None = None     # a RESOLVED hero pin (hero.resolve), never a raw manifest value
    intent: str = "action"
    fps: float | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.src, str) and self.src):
            raise ValueError("TrackSpec.src must be a non-empty path")
        if self.model not in MODELS:
            raise ValueError(f"TrackSpec.model {self.model!r} not in {MODELS}")
        if self.intent not in INTENTS:
            raise ValueError(f"TrackSpec.intent {self.intent!r} not in {INTENTS}")
        if self.pin is not None and not isinstance(self.pin, HeroPin):
            raise ValueError(f"TrackSpec.pin must be a HeroPin or None, got {self.pin!r} — "
                             f"resolve the manifest's raw hero through hero.resolve() first")
```

- [ ] **Step 5: The dispatch in `build_route`**

Replace the hero-selection block (currently lines 157-162):

```python
    feats = _track_features(per_frame, src_w=src_w, src_h=src_h)
    # hero priority (§5.10): a pin decides, or intent-conditioned scoring does.
    # A pin that matches NOTHING does NOT fall through to scoring — that silent
    # substitution is the §6.1a bug this replaces. It reports pin_matched=False,
    # the route comes out empty, and orchestration raises hero-unmatched.
    hero_id, ambiguous, pin_matched = None, False, None
    if spec.pin is None:
        hero_id, ambiguous = _pick_hero(feats, spec.intent)
    elif spec.pin.kind == "bbox":
        hero_id = _seed_track(per_frame, spec.pin.bbox)
    elif spec.pin.kind == "rule":
        hero_id = _rule_track(feats, spec.pin.rule)
    elif spec.pin.kind == "track":
        hero_id = _id_track(feats, spec.pin.track_id)
    else:                                    # "cast" — HeroPin.kind is closed by HERO_KINDS
        hero_id, ambiguous = _descriptor_track({t: d for t, (_c, d) in crops.items()},
                                               spec.pin.descriptor)
    if spec.pin is not None:
        pin_matched = hero_id is not None
    meta = TrackMeta(hero=hero_id, ambiguous=ambiguous, intent=spec.intent,
                     features={str(k): {kk: f[kk] for kk in
                                        ("n", "disp", "area", "speed", "border")}
                               for k, f in feats.items()},
                     pin_matched=pin_matched)
```

and, in the detection loop from Task 4, fill `crops` only on the cast path:

```python
        per_frame.append((idx, dets))
        if spec.pin is not None and spec.pin.kind == "cast":
            _track_crops(res, boxes, crops)
```

The rest of `build_route` (the route assembly at lines 171-181, which filters `d[0] == hero`) is unchanged — rename its local `hero` to `hero_id` to match.

- [ ] **Step 6: The CLI**

Replace the `--seed` handling (lines 193-199):

```python
    ap.add_argument("--seed", default=None,
                    help="hero pin: first-frame centre bbox 'x,y,w,h' in source px")
    ap.add_argument("--rule", default=None, choices=list(HERO_RULES),
                    help="hero pin: a mechanical rule (§5.10)")
    ap.add_argument("--track-id", type=int, default=None, help="hero pin: an explicit track id")
    ap.add_argument("--cast-name", default=None, help="hero pin: a name from --cast-json")
    ap.add_argument("--cast-json", default=None, help="cast.json — required with --cast-name")
    ap.add_argument("--intent", default="action", choices=["action", "static"],
                    help="hero scoring mode (spec §6.1a)")
    a = ap.parse_args()
    raw = ([float(v) for v in a.seed.split(",")] if a.seed else
           a.rule if a.rule else
           a.track_id if a.track_id is not None else
           a.cast_name)
    cast = Cast.from_json(a.cast_json) if a.cast_json else None
    spec = TrackSpec(src=a.src, model=a.model, pin=hero_lib.resolve(raw, cast),
                     intent=a.intent, fps=a.fps)
    build_route(spec, a.out)
```

The CLI builds a *raw* value and hands it to the same `hero.resolve` everything else uses — the four flags are spellings, not a second resolver. Add to `track.py`'s imports: `from scripts.lib import appearance, hero as hero_lib, proc`, `from scripts.lib.footage import Cast`, and `HERO_RULES`/`HeroPin` from `models`.

- [ ] **Step 7: The shell**

`scripts/process_episode.py`, replacing lines 94-100:

```python
    # 1. tracking — or a supplied frozen route (answer channel / determinism, §5.10)
    if route_path is None:
        rp = str(Path(project_dir) / "route.json")
        tspec = TrackSpec(src=m.segment, model=m.model,
                          pin=hero_lib.resolve(m.hero, cast), intent=intent)
        _timed("track", lambda: track.build_route(tspec, rp))
        route, track_meta = _load_route(rp)
```

`resolve` cannot raise here: `validate` already proved it — the same contract `layout_lib.resolve` relies on at line 76 ("validate() already proved it constructs").

Load the registry just above the `validate` call (line 54):

```python
    cast = None
    if m.cast:
        try:
            cast = Cast.from_json(m.cast)
        except (OSError, ValueError) as e:
            return {"status": "needs_input", "attempt": 0,
                    "problems": [f"cast {m.cast!r} is unreadable — {e}"]}
    problems = manifest_lib.validate(m, cast=cast)
```

Imports: `from scripts.lib import hero as hero_lib`, `from scripts.lib.footage import Cast`.

- [ ] **Step 8: Run the affected files, the full suite, and commit**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/integration/test_track.py tests/integration/test_process_episode.py -q; echo "EXIT: $?"` → PASS
Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **892 passed / 8 skipped**

```bash
git add scripts/lib/models.py scripts/track.py scripts/process_episode.py \
        tests/lib/test_models.py tests/integration/test_track.py tests/integration/test_process_episode.py
git commit -m "feat: TrackSpec.pin dispatches every §5.10 rung; an unmatched pin never falls back"
```

---

### Task 8: `orchestration.py` — `hero-unmatched`, and `is_seed_pin` goes

**Files:**
- Modify: `scripts/lib/orchestration.py:24-31` (delete `is_seed_pin`), `:34-65` (`detect_contradictions`)
- Modify: `scripts/process_episode.py:108-109` (the call)
- Test: `tests/lib/test_orchestration.py`

Spec §5. The gate collapses to `if ambiguous` because the rungs now consume the pin. **The ordering is load-bearing.**

- [ ] **Step 1: Rewrite the tests**

In `tests/lib/test_orchestration.py`, **delete these four** — each pins behaviour this slice reverses:
- `test_ambiguous_hero_with_pin_is_resolved` — a bbox pin can no longer suppress the gate, and can no longer coexist with `ambiguous` (its rung resolves the hero, so `_pick_hero` never runs).
- `test_ambiguous_hero_with_empty_pin_is_a_contradiction` — `""`/`()`/`[]` now raise in `hero.resolve` and never reach the tracker; covered by `test_hero.py::test_malformed_values_raise`.
- `test_named_or_rule_hero_does_not_resolve_ambiguity` — its own comment scopes it to "this slice (cast.json is the ingestion plan)". This is that slice.
- `test_is_seed_pin_only_true_for_nonempty_tuple` — the function is gone.

Drop `hero=` from the five surviving callers (`test_no_contradictions_when_manifest_matches`, `test_direction_reversal_is_a_contradiction`, `test_ambiguous_hero_without_pin_is_a_contradiction`, `test_empty_route_is_a_contradiction`, `test_missing_track_meta_does_not_crash`), and add:

```python
def test_unmatched_pin_is_a_contradiction():
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"pin_matched": False},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-unmatched" for f in findings)


def test_unmatched_pin_outranks_no_track():
    # an unmatched pin PRODUCES the empty route, so "hero never detected" would be
    # the wrong diagnosis — it would point at the segment or the model
    findings = orch.detect_contradictions(motion=None, route=[],
                                          track_meta={"pin_matched": False},
                                          src_w=1920, src_h=1080)
    assert [f["reason"] for f in findings] == ["hero-unmatched"]


def test_matched_pin_is_not_a_contradiction():
    findings = orch.detect_contradictions(motion=None, route=_route_right(),
                                          track_meta={"pin_matched": True, "ambiguous": False},
                                          src_w=1920, src_h=1080)
    assert findings == []


def test_ambiguity_fires_even_with_a_pin():
    # a cast pin matching two look-alikes: the pin is what is ambiguous, so the
    # gate MUST fire — the old is_seed_pin suppression had this exactly backwards
    findings = orch.detect_contradictions(motion=None, route=_route_right(),
                                          track_meta={"pin_matched": True, "ambiguous": True},
                                          src_w=1920, src_h=1080)
    assert any(f["reason"] == "hero-ambiguous" for f in findings)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q; echo "EXIT: $?"`
Expected: FAIL — `TypeError: detect_contradictions() got an unexpected keyword argument 'motion'`… or missing `hero`. Either way, red.

- [ ] **Step 3: Delete `is_seed_pin` and rewrite the gate**

Delete `is_seed_pin` entirely (lines 24-31) — its docstring's warning ("The ambiguity gate and the shell's seed gate MUST share this one predicate…") describes a hazard that no longer exists: the rungs consume the pin, so there is no predicate to share.

```python
def detect_contradictions(motion: str | None, route: list[dict],
                          track_meta: dict, src_w: int, src_h: int,
                          composition: str | None = None) -> list[dict]:
    """Machine-detectable manifest-vs-reality conflicts (§4.1). Returns a list
    of {reason, detail} findings; non-empty ⇒ stop-and-report, never improvise."""
    findings = []
    meta = track_meta or {}
    if meta.get("pin_matched") is False:
        # ORDER IS LOAD-BEARING: an unmatched pin is what PRODUCED the empty
        # route below, so no-track ("hero never detected") would be the wrong
        # diagnosis — it points at the segment or the model, when the real answer
        # is "the person you pinned is not in this clip".
        findings.append({"reason": "hero-unmatched",
                         "detail": "the manifest's hero pin matched no track in this segment — "
                                   "the pinned person may not be in this episode, or the cast "
                                   "descriptor may not survive its lighting; re-check the window, "
                                   "or pin a seed bbox instead"})
        return findings
    if not route:
        findings.append({"reason": "no-track",
                         "detail": "tracker produced an empty route — hero never "
                                   "detected; check the segment, model size, or hero pin"})
        return findings          # nothing else is meaningful without a route
    if meta.get("ambiguous"):
        # No pin check: the rungs consume the pin themselves, so `ambiguous` is
        # honest on its own. A pin that resolved cleanly sets it False; a cast pin
        # matching two look-alikes sets it True — and then the PIN is what is
        # ambiguous, so suppressing the gate (as is_seed_pin did) was backwards.
        findings.append({"reason": "hero-ambiguous",
                         "detail": "top-2 candidate scores within margin (§6.1a) — "
                                   "pin a hero (seed bbox [x,y,w,h], a rule, a track id, "
                                   "or a cast name from cast.json) and retry"})
    if composition == "lead":
        obs_type, _ = classify(route, src_w, src_h)
        if obs_type != "lateral":
            findings.append({"reason": "composition-motion-mismatch",
                             "detail": f"composition 'lead' needs lateral motion, but the "
                                       f"tracker sees {obs_type} — set composition to "
                                       f"'center', or fix the window/segment"})
    if motion:
        obs_type, obs_dir = classify(route, src_w, src_h)
        observed = obs_type + (f":{obs_dir}" if obs_dir else "")
        if _motion_conflicts(motion, observed):
            findings.append({"reason": "motion-mismatch",
                             "detail": f"manifest declares {motion}, tracker sees {observed}"})
    return findings
```

- [ ] **Step 4: Update the one caller**

`scripts/process_episode.py:108-109`:

```python
    findings = orch.detect_contradictions(m.motion, route, track_meta,
                                          src_w, src_h, composition=m.composition)
```

Run `grep -rn "detect_contradictions\|is_seed_pin" scripts/ tests/` and confirm nothing else refers to either.

- [ ] **Step 5: Run the tests, the full suite, and commit**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q; echo "EXIT: $?"` → PASS
Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **892 passed / 8 skipped** (4 deleted, 4 added)

```bash
git add scripts/lib/orchestration.py scripts/process_episode.py tests/lib/test_orchestration.py
git commit -m "feat: hero-unmatched stop-and-report; delete is_seed_pin (the tracker knows now)"
```

---

### Task 9: `edit_plan.py` — the authoring end

**Files:**
- Modify: `scripts/edit_plan.py` (`build_edl`, `write_edit_plan:110-132`, CLI `:139-144`)
- Test: `tests/test_edit_plan.py` (or wherever `build_edl`'s unit tests live — `grep -rn "def test_build_edl" tests/`)

Spec §7.

- [ ] **Step 1: Write the failing test**

```python
def test_build_edl_carries_the_cast_path():
    edl = edit_plan.build_edl(_footage(), _selection(), cast="proj/cast.json")
    assert edl.cast == "proj/cast.json"


def test_build_edl_without_a_cast():
    assert edit_plan.build_edl(_footage(), _selection()).cast is None
```

`_footage()`/`_selection()` are the file's existing factories — reuse them.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_edit_plan.py -k cast -q; echo "EXIT: $?"`
Expected: FAIL — `TypeError: build_edl() got an unexpected keyword argument 'cast'`

- [ ] **Step 3: Thread it**

`build_edl` gains `cast: str | None = None` and passes it into the `EDL(...)` construction. `write_edit_plan` gains `cast: str | None = None` and forwards it:

```python
def write_edit_plan(footage_path: str, selection_path: str, project_path: str, out_dir: str,
                    pacing_path: str | None = None, cast: str | None = None) -> dict:
```
```python
    edl = build_edl(footage, selection, pacing=pacing, cast=cast)
```

CLI:

```python
    b.add_argument("--cast", help="cast.json from intake — required if any episode pins a cast name (§6.1a)")
```

and forward `cast=a.cast` at the call site.

- [ ] **Step 4: Run the tests, the full suite, and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **894 passed / 8 skipped**

```bash
git add scripts/edit_plan.py tests/test_edit_plan.py
git commit -m "feat: edit_plan --cast sets EDL.cast (a cast-name hero needs its registry)"
```

---

### Task 10: The integration proof — real descriptor math over real pixels

**Files:**
- Create: `tests/integration/test_cast_pin.py`

Spec §10. **Not real YOLO** — read the Testing Notes at the top of this plan before writing a line. This mocks the detector (as all nine track tests do) but hands the fake `res` **real numpy pixels and masks**, so `crop_and_mask` (both landmines), `build_descriptor`, `descriptor_dist` and the rung all execute for real.

- [ ] **Step 1: Write the test**

```python
"""Cast → hero-pin, end to end over REAL pixels (design §10).

YOLO itself is faked — this repo fakes it everywhere, because the synthetic clips
are boxes, not people, and real YOLO returns an empty route on them (see
tests/integration/test_intake.py:5). Everything BELOW the detector is real: the
fake result carries a real BGR frame and a real model-space mask, so
appearance.crop_and_mask (BGR→RGB + mask resize), build_descriptor and
descriptor_dist run on real arrays. This is the first test that takes a
descriptor from intake's own builder, through cast.json, to a route.
"""
import json

import numpy as np
import pytest

from scripts import intake, track
from scripts.lib import appearance, hero as hero_lib, models
from scripts.lib.footage import Cast, CastMember

_FRAME_W, _FRAME_H = 640, 360
_RED, _BLUE = (0, 0, 220), (220, 0, 0)      # BGR — orig_img is BGR, like ultralytics
_RED_X, _BLUE_X = 160, 480


class _Box:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [0.9]


class _Masks:
    def __init__(self, data):
        self.data = data


class _Res:
    """An ultralytics-result-shaped fake WITH pixels: two people, red-clothed at
    x=160 (track 1) and blue-clothed at x=480 (track 2)."""
    def __init__(self):
        img = np.zeros((_FRAME_H, _FRAME_W, 3), dtype=np.uint8)
        masks = []
        self.boxes = []
        for x, colour, tid in ((_RED_X, _RED, 1), (_BLUE_X, _BLUE, 2)):
            l, t, r, b = x - 40, 100, x + 40, 300
            img[t:b, l:r] = colour
            m = np.zeros((_FRAME_H, _FRAME_W), dtype=np.float32)
            m[t:b, l:r] = 1.0
            masks.append(m)
            self.boxes.append(_Box([float(x), 200.0, 80.0, 200.0], tid))
        self.orig_img = img
        self.masks = _Masks(masks)


def _descriptor_of(colour_bgr):
    """Build a cast descriptor the way intake does — same builder, same masking."""
    crop = np.full((200, 80, 3), colour_bgr[::-1], dtype=np.uint8)     # RGB for the builder
    return intake.build_descriptor(crop, np.full((200, 80), 255, dtype=np.uint8))


def _cast():
    return Cast(members=[CastMember(name="Red", descriptor=_descriptor_of(_RED)),
                         CastMember(name="Blue", descriptor=_descriptor_of(_BLUE)),
                         CastMember(name="Green", descriptor=_descriptor_of((0, 220, 0)))])


@pytest.mark.integration
def test_cast_pin_follows_the_named_person(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter((i, _Res()) for i in range(10)))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=hero_lib.resolve("Blue", _cast()))
    route = track.build_route(spec, out=str(out))
    # the BLUE-clothed person, not the red one — descriptor beats kinematics (§6.1a)
    assert route and all(pt.x == _BLUE_X for pt in route)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is True and meta.ambiguous is False


@pytest.mark.integration
def test_cast_pin_naming_an_absent_person_is_unmatched(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter((i, _Res()) for i in range(10)))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=hero_lib.resolve("Green", _cast()))   # nobody wears green
    route = track.build_route(spec, out=str(out))
    assert route == []
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is False


@pytest.mark.integration
def test_cast_descriptor_survives_the_cast_json_round_trip(tmp_path):
    # the descriptor intake writes is the descriptor track matches against
    path = tmp_path / "cast.json"
    path.write_text(json.dumps(_cast().to_dict()))
    pin = hero_lib.resolve("Blue", Cast.from_json(str(path)))
    assert appearance.descriptor_dist(list(pin.descriptor), _descriptor_of(_BLUE)) == 0.0
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/integration/test_cast_pin.py -q; echo "EXIT: $?"`
Expected: PASS (3 tests).

If `test_cast_pin_follows_the_named_person` fails with `pin_matched is False`, the red/blue descriptors are further apart from their cast entries than `CAST_MATCH = 0.6` — **do not widen the constant to make the test pass.** Print the two distances first (`appearance.descriptor_dist`) and report them: the spec (§3, §11) flags 0.6 as an unverified first cut, and this test is exactly the evidence that was meant to check it. A real mismatch here is a finding about the constant, not about the test.

- [ ] **Step 3: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **897 passed / 8 skipped**

```bash
git add tests/integration/test_cast_pin.py
git commit -m "test: cast pin follows the named person + unmatched reports (real descriptor math)"
```

---

### Task 11: SKILLs + docs sync

**Files:**
- Modify: `SKILLS/edit-plan/SKILL.md:46`, `SKILLS/footage-intake/SKILL.md:64-66`
- Modify: `docs/pipeline-map.md`, `docs/build-status.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `CLAUDE.md`
- Modify: `docs/plans/2026-07-16-cast-hero-pin.md` (tick every box)

Spec §12.

- [ ] **Step 1: `SKILLS/edit-plan/SKILL.md`**

The `hero` line currently offers `largest`/`leftmost` and a cast name with "(optional; resolving a cast name to a descriptor is a later task)". All four forms are now real. Rewrite it to document: a seed bbox `[x, y, w, h]` (centre-format, source px), a rule (`largest`/`leftmost`), an integer track id, or a cast name — **and that a cast name requires `--cast`**, must exist in `cast.json`, and that an unresolvable name is a preflight `edl-invalid`, while a pin matching nobody in the segment is a `hero-unmatched` stop-and-report.

- [ ] **Step 2: `SKILLS/footage-intake/SKILL.md`**

Lines 64-66 say "wiring hero descriptors into episode manifests (cast-name hero pins) is a later plan — 5.2 just produces `cast.json`". That later plan is this one: `cast.json` is now read by `edit-plan --cast` → `EDL.cast` → the manifest → `track`. Say so, and keep the naming pass's own scope unchanged.

- [ ] **Step 3: `docs/pipeline-map.md`**

The `cast → hero-pin` row (the last row of the "Remaining work" table): `❌ → ✅`, "Left to build" → `— (2026-07-16)`, and drop the "today a cast name (or an `edit-plan` `largest`/`leftmost` rule) silently falls back to intent scoring" clause and the "(written, never read back)" note. In the **Router + curation** roadmap bullet, remove the cast half — cap-3 parallel fan-out becomes its only remainder. The **tally is untouched**: cast → hero-pin is a sub-item, not one of the 16 stages. Bump `_Last updated_`.

- [ ] **Step 4: `docs/build-status.md`**

Add a DONE entry under the safe-zones one (plan + design paths, what landed, the final suite count). Then:
- Delete the `cast → hero-pin wiring` next-action bullet (it is done) — including its "**This also fixes a live defect**" paragraph.
- The "descriptor continuity re-match needs the cast **wiring**, not the artifact" line in **Deferred / open** flips: the wiring has landed, so §6.1a layer 3 is now unblocked and is the natural follow-on.
Bump `_Last updated_`.

- [ ] **Step 5: `docs/specs/2026-07-05-montage-skillset-design.md`**

§5.10's `hero?` paragraph describes all three forms as if built; mark that they now are, and that a cast name resolves through `cast.json` descriptors. §6.1a's **Plan split** line ("Ingestion plan = cast registry + interactive naming + descriptor wiring into manifests") records that the ingestion half has landed (2026-07-16) and that the process-episode half (layer 3, continuity re-match) is now unblocked.

- [ ] **Step 6: `CLAUDE.md`**

Two rows in the Quick Reference table, in the established one-line style:

```markdown
| Cast → hero-pin design | [2026-07-16-cast-hero-pin-design.md](docs/specs/2026-07-16-cast-hero-pin-design.md) | §6.1a ingestion half: every §5.10 pin form (bbox/rule/track-id/cast name) → typed `HeroPin` via one pure `hero.resolve`; descriptor rung in `track` (`lib/appearance` primitives move out of intake); a pin matching nothing is `hero-unmatched`, never a fallback; `is_seed_pin` deleted; `validate()` finally gates hero (resolve as its oracle). Layer 3 continuity re-match → its own slice. |
| Cast → hero-pin plan | [2026-07-16-cast-hero-pin.md](docs/plans/2026-07-16-cast-hero-pin.md) | Tasks 0-11: `lib/appearance` extraction, `HeroPin`+`hero.resolve`, track rungs + descriptor match, manifest `cast`+hero oracle, `EDL.cast`+preflight, `TrackSpec.pin` atomic rename, `hero-unmatched`, edit_plan `--cast`, real-pixel proof, docs. |
```

- [ ] **Step 7: Tick this plan's boxes, run the full suite, and commit**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"` → **897 passed / 8 skipped**, EXIT 0

```bash
git add docs/ CLAUDE.md SKILLS/
git commit -m "docs: cast → hero-pin landed — registry read, pin resolved, §6.1a layer 3 unblocked"
```

---

## Self-Review

**1. Spec coverage.**

| Spec § | Task |
|--------|------|
| §1 architecture / no cycles | T0-T2 (`appearance` imports nothing local; `hero` imports `models`+`footage`; `manifest` imports `hero`) |
| §2 `HeroPin` + `resolve` | T1, T2 |
| §3 appearance extraction + `CAST_MATCH` | T0 |
| §4 rungs, crop accumulation, landmines, margin, `AMBIG_MARGIN`, `pin_matched` to_dict | T3, T4, T7 |
| §5 gate collapse + ordering + `is_seed_pin` deletion + `hero` param drop | T8 |
| §6 `validate(m, cast=)` oracle, hero type widen | T5 |
| §7 `EDL.cast`, `EDLEpisode.hero` widen, bridge, preflight, `Manifest.cast`, shell, `edit_plan`; `edl_to_reel` needs no change | T5, T6, T7, T9 |
| §8 edge cases | `hero: 0` → T2; unmatched → T7; no-people → T7; frozen route → untouched by T7's `route_path` branch; rule never ambiguous → T3 |
| §9 landmines | BGR/mask-resize → T0 (moved verbatim) + T4; bool → T1, T2; falsy pins → T2, T7; ordering → T8 |
| §10 testing incl. deletions + `_FakeRes` churn | T4 (churn), T8 (deletions), T10 (proof) |
| §12 doc sync | T11 |

No gaps.

**2. Placeholder scan.** No TBD/TODO. Every code step carries the code. The two "reuse the file's existing factory" notes (T6 `_ep`, T9 `_footage`/`_selection`) name a `grep` to find them rather than inventing a duplicate.

**3. Type consistency.**
- `HeroPin(kind, bbox, rule, track_id, name, descriptor)` — same field names in T1 (definition), T2 (`resolve`), T7 (dispatch), T10 (proof). ✅
- `hero.resolve(hero, cast)` — same signature in T2, T5 (oracle), T7 (shell + CLI). ✅
- `_descriptor_track(descs, pin) -> (hero_id, ambiguous)` — T4 defines the 2-tuple; T7's dispatch unpacks two. ✅
- `_track_crops` stores `{tid: (conf, descriptor)}`; T7's dispatch strips conf with `{t: d for t, (_c, d) in crops.items()}`. ✅ (called out explicitly in T4 Step 4).
- `TrackMeta.pin_matched: bool | None` — T7 definition; T8 reads `meta.get("pin_matched") is False`; `is False` (not falsy) is what makes `None` ≠ `False`. ✅
- `validate(m, cast=None)` — T5 definition; T6 (`preflight`) and T7 (shell) both pass `cast=`. ✅
- `appearance.CAST_MATCH` / `HIST_BINS` / `build_descriptor` / `descriptor_dist` / `crop_and_mask` — T0 defines; T4 and T10 use those exact names. ✅
- `AMBIG_MARGIN` in `track.py` — T3 defines, `_pick_hero` (T3) and `_descriptor_track` (T4) both read it. ✅

**4. Green-at-every-commit.** T0-T6 are additive. T7 is the one breaking change and carries all three affected files plus their tests. T8's four deletions balance its four additions (892 → 892).
