# Cast → hero-pin — resolving the §6.1a hero pin (design)

**Related:** montage §5.10 (the `hero?` field — the authoritative list of pin
forms); §6.1a hero identity (layer 1 cast registry, layer 2 candidate scoring +
margin rule); §4.1 stop-and-report; the footage-intake design (SP2 — what wrote
`cast.json`); the engine-hardening design (the soft-manifest / hard-engine
validation split this slice extends).

**Intent:** make the manifest's `hero` pin **mean something**. `cast.json` has
shipped since 5.2 but nothing reads it back — `Cast.from_json` is called only
from tests. Meanwhile `orch.is_seed_pin` accepts a non-empty tuple and nothing
else, so a cast name, an `edit-plan`-documented rule (`largest`/`leftmost`), and
plain garbage all silently fall back to intent scoring. The SKILL promises a pin
the code drops, and `manifest.validate()` does not mention `hero` at all, so
`hero: "asdf"` validates clean. This slice resolves every §5.10 pin form, fails
loud on a pin that cannot be honoured, and closes §6.1a's modes 1 and 4.

## Scope decisions (locked in brainstorming)

- **All three §5.10 pin forms**, not just the cast name: a seed bbox (built), a
  rule (`largest` / `leftmost`), an explicit track id, and a cast name. They are
  one defect with one predicate and one set of tests; splitting them would churn
  `is_seed_pin`'s tests twice.
- **Descriptor matching inside `track.py`**, as a hero-priority rung — a sibling
  of `_seed_track`. Rejected: a pre-track resolver that samples first frames into
  a seed bbox (costs a *second* YOLO pass over the segment, misses a hero who
  enters late, and degrades "descriptor similarity outranks kinematics" into
  IoU-on-frame-0); and blending the descriptor into `_pick_hero`'s score (a blend
  can be outvoted by kinematics, which is precisely what §6.1a forbids, and it
  has no coherent margin rule).
- **A pin that matches nothing is a stop-and-report**, never a fallback. This
  also closes the same hole on the existing bbox seed, which today falls through
  to `_pick_hero` when `_seed_track` finds no overlap.
- **§6.1a layer 3 (descriptor continuity re-match) is out** — a different
  mechanism (per-frame descriptors along the route, jump detection, route
  splitting) against a different failure mode (3, mid-episode ID switch). The
  design itself splits them: "Ingestion plan = cast registry + interactive naming
  + descriptor wiring into manifests. process-episode plan = descriptor-based
  continuity re-match." This slice is the ingestion half.

## 1. Architecture

The pin stops being a `hero` value guessed at with `isinstance` and becomes a
**typed `HeroPin`, resolved once, at the boundary**. Everything below consumes
the resolved pin, so no two call sites can disagree about what a pin is.

```
cast.json ─┐
           ├─► hero.resolve(m.hero, cast) ─► HeroPin ─► TrackSpec.pin ─► track rungs
m.hero ────┘        │                                                        │
                    └─ raises (unknown name / malformed / not a rule)        ▼
                       └─► validate()'s oracle → needs_input        TrackMeta.pin_matched
                                                                             │
                                                    detect_contradictions ───┴─► hero-unmatched
```

| File | Change | Why |
|------|--------|-----|
| `scripts/lib/appearance.py` | **new** — `HIST_BINS`, `CAST_MATCH`, `build_descriptor`, `descriptor_dist`, `crop_and_mask` | The descriptor primitives move out of `intake.py`: `track.py` needs them and a driver must not import a driver. Same move, same reason, as `marks_at_times` → `lib/geometry` in the safe-zones slice. |
| `scripts/lib/hero.py` | **new** — `resolve(hero, cast) -> HeroPin \| None` | The pure resolver. No numpy: it reads descriptors out of a `Cast`, it does not compute them. |
| `scripts/lib/models.py` | `HERO_RULES`; `HeroPin` config-spec; `TrackSpec.seed_bbox` → `pin`; `TrackMeta.pin_matched` | Vocab + wire-contracts have one home. `HERO_RULES` sits with `COMPOSITIONS`/`GRIDS`/`MOTIONS`/`INTENTS`. |
| `scripts/intake.py` | descriptor primitives move out; re-import | Keeps `intake.build_descriptor` resolving for the existing tests (the `storyboard` re-export trick). |
| `scripts/track.py` | `_iter_detections` yields the whole `res`; `_rule_track` / `_id_track` / `_descriptor_track`; `build_route` dispatches on the pin | The rungs. |
| `scripts/lib/orchestration.py` | `is_seed_pin` **deleted**; `detect_contradictions` drops `hero`, gains `hero-unmatched` | The tracker now knows whether the pin resolved, so the shared-predicate hazard disappears. |
| `scripts/lib/manifest.py` | `cast` path field; `validate(m, cast=None)` with the hero oracle | The soft gate finally sees `hero`. |
| `scripts/lib/edl.py` | `EDL.cast`; `to_manifest_dict(..., cast=)`; `preflight` loads the cast once | The EDL↔manifest boundary carries the registry. |
| `scripts/process_episode.py` | loads the cast, resolves the pin, threads it | The shell. |
| `scripts/edit_plan.py` | `write_edit_plan(cast=)` + `--cast` | The authoring end. |
| `SKILLS/edit-plan/SKILL.md` | the `hero` docs stop lying | — |

No cycles: `models` imports nothing new; `hero` imports `models` + `footage`;
`manifest` imports `hero`; `edl` imports `manifest` + `footage`. None of
`models`/`footage` import `hero`/`manifest`/`edl`.

## 2. `HeroPin` + `hero.resolve` — the pure resolver

`models.py`:

```python
HERO_RULES = ("largest", "leftmost")
HERO_KINDS = ("bbox", "rule", "track", "cast")

@dataclass(frozen=True)
class HeroPin:
    kind: str
    bbox: tuple[float, float, float, float] | None = None
    rule: str = ""
    track_id: int | None = None
    name: str = ""
    descriptor: tuple[float, ...] = ()
```

`__post_init__` validates the kind and exactly the fields that kind needs — a
`bbox` pin carries a 4-tuple, a `rule` pin a member of `HERO_RULES`, a `track`
pin a non-bool int, a `cast` pin a non-empty name **and** a non-empty
descriptor. Frozen, so `resolve` hands it in already-coerced (tuples, not lists).

`hero.py`:

```python
def resolve(hero: object, cast: Cast | None = None) -> HeroPin | None
```

| `hero` | → | Notes |
|--------|---|-------|
| `None` | `None` | No pin — `_pick_hero` decides, exactly as today. |
| `(x, y, w, h)` | `HeroPin("bbox", bbox=…)` | Centre-format source px, per §5.10. Any other tuple length raises. |
| `int` (not `bool`) | `HeroPin("track", track_id=…)` | |
| `str` in `HERO_RULES` | `HeroPin("rule", rule=…)` | |
| other non-empty `str` | `HeroPin("cast", name=…, descriptor=…)` | Looked up in `cast`. |
| anything else | **raises** | `()`, `""`, `[1,2,3]`, `True`, `{}`, `4.2` … |

**Raises** (each with a remedy, per the fail-loud contract):

- a cast name with `cast=None` → *"hero 'Lena' is a cast name but no cast.json
  was supplied — set `EDL.cast` (or pass `--cast`) so the name can be resolved"*
- a name absent from the cast → *"hero 'Lena' is not in cast.json — known names
  are: Ann, Bo. Fix the name, or re-run footage-intake to register them"* (the
  known-name list is the remedy: a typo is the likeliest cause)
- a malformed value → names what it got and lists the four accepted forms

**Why raise rather than return `None`:** `None` means "no pin, score by intent",
which is exactly the silent fallback this slice exists to kill. An unresolvable
pin is never the same thing as an absent one.

**`bool` before `int`.** `isinstance(True, int)` is `True` in Python, so
`hero: true` would otherwise resolve to track id 1. `resolve` and
`HeroPin.__post_init__` both reject bools explicitly — the repo's standing
numeric-guard idiom (`SafeZone.__post_init__`, `EDLEpisode.beat_slot`).

## 3. `lib/appearance.py` — the descriptor primitives move out of intake

Moved **verbatim** from `intake.py` (`_HIST_BINS` → `HIST_BINS`,
`build_descriptor`, `_descriptor_dist` → `descriptor_dist`, `_crop_and_mask` →
`crop_and_mask`). `intake.py` re-imports them, so `intake.build_descriptor` and
the intake tests keep resolving; `CAST_DEDUP` **stays in intake** — it is a
`surface_crops` dedup policy, not an appearance primitive.

New in `appearance.py`:

```python
CAST_MATCH = 0.6    # max L1 descriptor distance for "this track is that cast member"
```

**Range and reasoning.** `build_descriptor` L1-normalizes over the *grand* total
of a 3 × `HIST_BINS`(=8) = 24-dim histogram, so every descriptor sums to 1.0 and
`descriptor_dist` ∈ **[0.0, 2.0]** (2.0 iff the supports are disjoint).
`CAST_MATCH = 0.6` is 30% of that maximum. It is **a first cut, not a derived
number**: the bar must be looser than intake's `CAST_DEDUP = 0.30`, because a
cast descriptor is snapped from one best crop in one clip and the episode's crop
comes from different footage, lighting, and pose — but tight enough that "the
pinned person is not in this episode at all" still fails. The real discriminator
is not the threshold: it is min-distance among the tracks actually present, plus
the margin rule below. The threshold only guards absence.

**What the golden fixture actually showed (2026-07-16, Task 10):** a matched
track↔cast pair measured `descriptor_dist == 0.0`; every unmatched pair
measured `1.333`. This does **not** contradict `0.6` — both sit comfortably
on their expected side of it — but the fixture's two flat-colour tracks sit
far enough apart that almost any threshold in `[0.05, 1.3]` would have passed
equally well. The proof validates the *mechanism* (descriptor distance
correctly separates a matched pair from an unmatched one, end to end, over
real pixels), not the *constant's tightness* for the hard case this section
names — two people in genuinely similar clothing, where real distances would
sit much closer together than 0.0 vs. 1.333. `0.6` remains an unverified
first cut for that case.

## 4. `track.py` — the pin rungs

`_iter_detections` currently yields `res.boxes` and discards the rest, on
purpose (`intake._iter_seg`: *"Mirror track.py's YOLO+ByteTrack config but keep
masks (track omits them for speed)"*). It now yields the whole `res`, and
`build_route` extracts boxes as before. **Masks are only touched when the pin is
a cast pin** — no cost on any other path.

Crop accumulation mirrors `intake.py:185-206` exactly: keep the **highest-`conf`
crop per track id**, so `crop_and_mask` runs about once per track, not once per
frame. Both of intake's landmines port with it:

- `orig_img` from ultralytics is **BGR** → `[..., ::-1]` to RGB. A silent
  channel swap would not crash; it would just match the wrong person.
- The mask is in **model space** (imgsz=960) and must be resized to source dims
  before indexing the crop.

The priority ladder in `build_route`:

```
pin.kind == "bbox"   → _seed_track(per_frame, pin.bbox)      # IoU, unchanged
pin.kind == "rule"   → _rule_track(feats, pin.rule)
pin.kind == "track"  → _id_track(feats, pin.track_id)
pin.kind == "cast"   → _descriptor_track(crops, pin.descriptor)
pin is None          → _pick_hero(feats, intent)             # unchanged
```

**A pin given ⇒ the rung decides. There is no fallback to `_pick_hero`** — a
rung returning `None` sets `pin_matched=False` and leaves `hero=None`, which
yields an empty route and a `hero-unmatched` stop-and-report. `pin_matched` is
`None` when no pin was given.

- `_rule_track` — `largest` = max `feats[tid]["area"]`; `leftmost` = min
  `feats[tid]["x0"]`. **`x0` already exists**: `_track_features` seeds it at
  track.py:77 and its cleanup only deletes the `_`-prefixed keys, so no change is
  needed there. Ties break deterministically on the lowest track id. Only an
  empty `feats` is unmatched.
- `_id_track` — `tid if tid in feats else None`.
- `_descriptor_track` — per-track descriptor vs `pin.descriptor`; min distance
  wins; **all distances > `CAST_MATCH` ⇒ unmatched**.

**Rules never set `ambiguous`.** "largest" is a mechanical rule with no claim
about identity — the human said largest, largest wins. Only the descriptor rung
and `_pick_hero` make identity claims, so only they can be ambiguous.

**The descriptor margin rule (§6.1a).** With `d1 ≤ d2` the two closest
distances: `d1 >= 0.8 * d2` ⇒ `ambiguous = True`. The best match is not
meaningfully closer than the runner-up — two people in similar clothing, which
is §6.1a's **mode 1** ("intake mislabels who is in a clip — similar outfits,
distance, backlight"), the exact failure a colour histogram is most exposed to.
Expressed on distance rather than on `_pick_hero`'s score ratio because
lower-is-better: a similarity transform would push both terms to ~1.0 whenever
both matches are good and call everything ambiguous.

`_pick_hero`'s existing inline `0.8` (track.py:125) and this one become one
named `AMBIG_MARGIN` constant in `track.py` — both readers live there, and
§6.1a's margin should have one spelling.

`TrackMeta.pin_matched` must round-trip through `to_dict`: the sidecar is how the
shell learns the outcome (`_load_route` hands `detect_contradictions` the parsed
dict), so a field that does not serialize is a gate that never fires.

## 5. `orchestration.py` — the gate collapses

```python
if (track_meta or {}).get("pin_matched") is False:
    findings.append({"reason": "hero-unmatched", "detail": …})
    return findings                    # an unmatched pin explains the empty route
if not route:
    findings.append({"reason": "no-track", …})
    return findings
if (track_meta or {}).get("ambiguous"):
    findings.append({"reason": "hero-ambiguous", …})
```

**The order is load-bearing.** An unmatched pin produces an empty route, and
`no-track` ("tracker produced an empty route — hero never detected") would be a
*wrong diagnosis* pointing at the segment or the model when the real answer is
"the person you pinned is not in this clip".

`is_seed_pin` is **deleted**, and its docstring's warning — *"The ambiguity gate
and the shell's seed gate MUST share this one predicate or a named-but-unseeded
hero silently suppresses stop-and-report"* — goes with it. There is no longer a
predicate to share: the rungs consume the pin, so `TrackMeta.ambiguous` is
honest on its own. Pin given and resolved → `False`. No pin → `_pick_hero`
decides, as today. Pin given and genuinely ambiguous → `True`, **and the gate
now fires**, where today a pin suppresses it.

`detect_contradictions` loses its `hero` parameter: `is_seed_pin(hero)` was its
only use. Every caller and test moves; leaving a dead argument on a §4.1 decision
core would be worse.

## 6. Validation — soft gate, hard oracle

`validate()` does **no I/O**, and that is a documented, deliberate convention
(manifest.py:119: *"the gate would have to probe the file, and this gate runs
before YOLO. Do not 'fix' it to probe here."*). So the caller loads the registry
and hands it in:

```python
def validate(m: Manifest, cast: Cast | None = None) -> list[str]:
    ...
    try:
        hero.resolve(m.hero, cast)
    except ValueError as e:
        problems.append(str(e))
```

This is a **calque of the LayoutSpec pattern** already at manifest.py:109-114 —
*"LayoutSpec is the HARD backstop; here it is the soft gate's oracle. Its
ValueError … becomes a problem string — the gate never raises."* One resolver,
used twice: as the gate's oracle, and as the shell's real resolution. Validation
and behaviour cannot drift apart, because they are the same function.

It closes today's hole: `hero: "asdf"` (neither rule nor cast name),
`hero: "Lena"` with no `cast.json`, `hero: [1,2,3]`, `hero: true` — all become
`needs_input` problem strings instead of a silently ignored pin.

`Manifest.hero`'s type widens to `tuple | str | int | None`.

## 7. Contract wiring

`cast.json` is one file per project, so it rides at EDL level and crosses to each
episode's manifest at the documented boundary:

- `EDL.cast: str | None = None` — a `cast.json` path, mirroring `EDL.music`.
- `EDLEpisode.hero`'s type widens to `tuple | str | int | None` (a track id is a
  §5.10 form). It gains **no** validation: `EDLEpisode`'s docstring already sets
  the rule — *"Layout-parameter cross-validation … is NOT duplicated here — it
  has one home … reached via the manifest gate in the driver's preflight."* The
  hero has one home too, and `preflight`'s `validate(m, cast=cast)` is it.
- `to_manifest_dict(ep, segment, out_path, cast: str | None = None)` → sets
  `md["cast"]` when given. The cast crosses the EDL↔manifest boundary
  *explicitly*, in the field map that documents that boundary.
- `Manifest.cast: str = ""` (in `OPTIONAL`). **The manifest stays a
  self-contained brief** (§14.4) — a process-episode subagent receives only the
  manifest, so the path to the registry must be in it or a cast name is
  unresolvable.
- `preflight` loads the registry **once**, before the per-episode loop, and
  passes it to every `validate(m, cast=cast)`. A missing or malformed
  `cast.json` becomes a `stop_and_report` `edl-invalid`, not a traceback.
- `process_episode` loads `m.cast` (when set) → `validate(m, cast=cast)` →
  `hero.resolve(m.hero, cast)` → `TrackSpec(pin=pin)`. Unreadable path →
  `needs_input`. By the time `resolve` runs for real, `validate` has already
  proved it does not raise — the same contract `layout_lib.resolve` relies on at
  process_episode.py:76.
- `edl_to_reel` needs **no change**: `preflight` already returns manifest dicts
  that carry `cast`.
- `edit_plan.write_edit_plan(cast=…)` + `--cast` sets `EDL.cast`.

## 8. Edge cases

| Case | Behaviour |
|------|-----------|
| No `hero` | `pin=None`, `pin_matched=None` — today's path exactly, unchanged. |
| Cast name, hero absent from the episode | all `d > CAST_MATCH` → `hero-unmatched` → stop-and-report. |
| Cast name, two similar-looking people | `d1 >= 0.8·d2` → `ambiguous` → `hero-ambiguous` → stop-and-report. |
| `hero` set but the segment has no people at all | `feats` empty → every rung returns `None` → `hero-unmatched` (**not** `no-track`) — the pin is the more specific diagnosis, and the route is empty either way. |
| Cast member with an empty `descriptor` | impossible: `CastMember.__post_init__` already rejects it. |
| Frozen-route path (`route_path` supplied) | untouched — no tracking runs, so no pin is resolved; the answer channel (§5.10) stays a route, not a pin. |
| Rule pin, one track | it wins; a rule makes no identity claim, so never ambiguous. |
| `hero: 0` (track id 0) | a valid pin — `0` is falsy but not `None`, so `resolve` must test `is None`, never truthiness. |

## 9. Landmines

- **BGR → RGB** on `orig_img` (§3) — silent wrong-person matching, not a crash.
- **Mask resize model-space → source-space** before indexing the crop.
- **`isinstance(True, int)`** — `hero: true` must not become track id 1.
- **Falsy-but-valid pins** — `hero: 0` (track 0) and `d == 0.0` (a perfect
  descriptor match) both demand `is None` / explicit comparisons, never
  truthiness. The old `is_seed_pin` had exactly this bug class as its reason to
  exist (`len(hero) > 0` for `()`).
- **Ordering in `detect_contradictions`** (§5) — `hero-unmatched` before
  `no-track`, or the diagnosis is wrong.

## 10. Testing

**Unit (pure, no YOLO):**
- `hero.resolve` — every form in the §2 table, every raise, with the remedy text
  asserted for the unknown-name case (the known-name list is the remedy).
- `HeroPin.__post_init__` — kind/field cross-validation, bool rejection.
- `_rule_track` / `_id_track` — over hand-built `feats`, including ties and the
  empty case.
- `_descriptor_track` — match, unmatched (all beyond `CAST_MATCH`), margin
  (`d1 >= 0.8·d2` → ambiguous), single-track.
- `detect_contradictions` — `hero-unmatched` fires; it precedes `no-track`; the
  ambiguity gate no longer consults `hero`.
- `validate(m, cast=)` — each hero problem string.

**Deleted** — four tests in `test_orchestration.py`, all pinning behaviour this
slice reverses. The last two carry comments scoping themselves to "this slice
(cast.json is the ingestion plan)": they were written to be deleted by this one.
- `::test_named_or_rule_hero_does_not_resolve_ambiguity`
- `::test_is_seed_pin_only_true_for_nonempty_tuple`
- `::test_ambiguous_hero_with_pin_is_resolved` — asserts a bbox pin *suppresses*
  `hero-ambiguous`. Now impossible in both directions: the gate no longer reads
  `hero`, and a pin can no longer coexist with `ambiguous` (the pin's rung
  resolves it, so `_pick_hero` — the only source of kinematic ambiguity — never
  runs).
- `::test_ambiguous_hero_with_empty_pin_is_a_contradiction` — `""`/`()`/`[]` now
  raise in `hero.resolve` and never reach the tracker; the coverage moves to the
  resolver's own raise tests.

**Moved:** `test_track.py::test_route_seed_pin` (seed → pin),
`test_process_episode.py::test_seed_bbox_threaded_to_track`,
`test_manifest.py::test_hero_string_rule_kept`, and every
`detect_contradictions` caller (signature).

**Test-double churn — the priced cost of §4's choice.** All eight pre-existing
tests in `test_track.py` monkeypatch `_iter_detections` to yield `(idx, [_FakeBox, …])`,
so yielding the whole `res` breaks every one. They gain a `_FakeRes` wrapper
(`.boxes`, no `orig_img`/`masks`) behind one shared helper — a one-line change
per test. `crop_and_mask`'s existing `getattr(…, None)` guards mean a maskless
fake returns `(None, None)` and never reaches numpy, which is exactly how the
intake tests already mock it. This is real churn, and it is the reason option B
looked cheap; option B's second YOLO pass over 4K footage is worse.

**Integration — real descriptor math, YOLO mocked.** Not real YOLO: this repo
fakes YOLO in *every* test, and its own comments say why — *"sample_clip is a
box, not a person, so real YOLO tracking returns an empty route"*
(`test_front_spine.py:6`, `test_intake.py:5`); `test_layouts.py` uses a frozen
route "so no YOLO runs". A synthetic clip cannot contain a detectable person, so
a "real-YOLO" proof of this slice is not constructible.

What *is* constructible, and is the honest maximum: mock `_iter_detections` (as
all eight pre-existing track tests do) but hand the fake `res` a **real numpy
`orig_img` and `masks`** — two people wearing differently-coloured blocks of
pixels. Then `crop_and_mask` (both landmines), `build_descriptor`,
`descriptor_dist` and the whole rung run for real, over real pixels. The proof:
a cast pin naming the red-clothed person puts *that* track in the route and not
the blue one; the same clip with a green-descriptor name returns
`hero-unmatched`; a near-duplicate second person trips the margin into
`ambiguous`. This is the first test that exercises descriptor → `cast.json` →
route end to end, and the only YOLO-shaped thing it fakes is the detector the
repo already fakes everywhere.

## 11. Non-goals / deferred

- **A computed `CAST_MATCH`** — the data to derive it is already on disk:
  `cast_candidates.json` holds every surfaced identity's descriptor, so the
  distance distribution *between known-distinct people* is observable, and the
  min pairwise distance between cast members upper-bounds how close a stranger
  may legitimately sit. A constant ships now because it is testable now;
  deriving it is its own slice with its own evidence. **The golden landed
  (2026-07-16, Task 10) and measured 0.0 for a matched pair vs. 1.333 for
  every unmatched pair** — consistent with `0.6`, but too wide a margin to
  say the constant is *tight*: almost any threshold in `[0.05, 1.3]` would
  have passed the same fixture. It remains unverified for the hard case (two
  people in similar clothing) this deferral exists to eventually address —
  see §3's "What the golden fixture actually showed".
- **§6.1a layer 3 — descriptor continuity re-match** (mid-episode ID switch:
  descriptor jump + x-teleport + area jump ⇒ split the route, re-match the
  pieces). Different mechanism, different failure mode; the design assigns it to
  the process-episode plan. It becomes *buildable* after this slice, because
  `cast.json` will finally be read.
- **Candidate crops in the stop-and-report** — §6.1a layer 2 specifies "what to
  show = the crops", and `TrackMeta` carries none today. Unchanged here: the
  finding stays text-only.
- **Face recognition** — the design excludes it explicitly ("faces are small/wet/
  blurred in action footage; heavy dependency — the layers above make it
  unnecessary").
- **Auto-registering a chosen hero back into the cast** — §6.1a's "the answer =
  a `hero` pin, **optionally** saved into the cast". Optional, and it needs the
  crops above to be worth anything.

## 12. Doc sync

- `docs/pipeline-map.md` — the `cast → hero-pin` row `❌ → ✅` (and its
  "silently falls back to intent scoring" note goes); the **Router + curation**
  roadmap bullet loses its cast half, leaving cap-3 fan-out as its only
  remainder; the tally is untouched (cast → hero-pin is a sub-item, not one of
  the 16 stages).
- `docs/build-status.md` — a DONE entry; the `cast → hero-pin` next-action bullet
  and the "descriptor continuity re-match needs the cast **wiring**" deferred
  line both flip (layer 3's blocker is gone).
- `docs/specs/2026-07-05-montage-skillset-design.md` — §5.10's `hero?` gains
  "built"; §6.1a's plan-split line records that the ingestion half has landed.
- `SKILLS/edit-plan/SKILL.md` — the `hero` forms become true, and gain the cast
  requirement (`--cast`, and a name must exist in `cast.json`).
- `SKILLS/footage-intake/SKILL.md` — "wiring hero descriptors into episode
  manifests (cast-name hero pins) is a later plan" is now this plan.
- `CLAUDE.md` — two registry rows (design + plan).
