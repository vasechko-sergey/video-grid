# Mood presets + shot-size variety — design (2026-08-06)

Cinematic-quality playbook P3, slice **S2** (`docs/cinematic-quality-playbook.md`
§3 mood presets + §4 priority 3; backlog `docs/fixes-backlog.md` **#19** shot-type
variety). S1 (footage contact sheet, 2026-08-05) gave the edit-plan agent its first
look at pixels. This slice gives the cut a **mood** and an objective it can be held
to: use the shot-size variety the footage actually offers.

Two things ship together because one is useless without the other:

1. A typed `MoodPreset` — the §3 spine, resolved from `SPEC.mood`, with exactly the
   fields its one consumer reads.
2. A **variety gate** in `edit_plan build`: refuse a cut that takes *zero* of a shot
   size the preset wants and the footage offers, unless the selection carries a
   written waiver.

And one prerequisite without which the gate cannot fire on real footage at all:
intake stops discarding the measurement behind `shot_type` (§5), so shot size can be
re-derived in **delivered** geometry (§6).

---

## 1. The problem, in code coordinates

The 2026-08-03 real run delivered a reel in which every shot was the same
medium-wide side-on "surfer on a wave" — no close-ups, no faces, none of the
*"laughs and moments, personality-forward"* the `fun and playful` brief asked for
(backlog #19). Competent, monotonous.

Three separate mechanisms let that through.

**a. Variety is nobody's objective.** `scripts/edit_plan.py` projects whatever
`selection.json` names. `edl.preflight` validates structure — source, window,
shot-type membership, layout parameters — never the *shape of the cut*. The word
"variety" appears in `check_reel`, but that check measures pixel-level frame
difference across cuts, not shot grammar.

**b. Mood is a music-search string.** `Spec.mood` is free text. Its only readers are
`scripts/mood.py` and `scripts/music_find.py`, both of which pass it to
`mood.mood_target` to rank audio. Nothing about the picture consults it. The
`fun and playful` brief produced a dark industrial reel and no mechanism could
notice the contradiction.

**b′. …and that brief matched nothing.** `mood.mood_target` tokenizes on word
boundaries and averages the tokens that are `MOOD_ANCHORS` keys. Neither `fun` nor
`playful` is a key. The real brief therefore fell straight into
`rank_by_drive` — the documented no-match fallback — so even the music ranking was
running blind. Four anchors are added in §4.3.

**c. The shot-size tag cannot discriminate on this footage.** `intake.shot_type`
buckets on the primary person's bbox area as a fraction of the **source** frame:
`> 0.30` close, `>= 0.08` medium, else wide. A surfer shot from the beach occupies
one to two percent of a 4K frame. Every window is tagged `wide`, so a target
distribution over `shot_type` would be unreachable by construction — the gate would
be decoration. §5 and §6 are the fix.

### 1.1 The scoring bias, measured — correcting an earlier framing

The contact-sheet design (2026-08-05 §1.1) recorded that `_motion_fit` is a triangle
with zero at static, so "a calm, personality-forward moment ranks below action even
when it is the better cut", and assigned the fix to this slice. The arithmetic says
the effect is narrower than that phrasing implies. For a window with people present
throughout, no shake, and a good duration:

```
score = 0.40·present + 0.25·motion_fit + 0.25·stability + 0.10·dur_fit
      = 0.40·1.0     + 0.25·0.0        + 0.25·1.0       + 0.10·1.0     = 0.75
```

`BEST_FLOOR` is `0.50`. **A static window with a person in it already passes into
`best`.** The bias costs it 0.25 of *rank*, not membership. The scorer does not
suppress calm moments; it sorts them downward.

Two consequences, both load-bearing here:

- The gate must not filter its `available` pool by `best` — but the reason is
  ordering hygiene and the phash cull, not rescue from exclusion.
- **`_motion_fit` is not re-tuned in this slice.** No real footage has been scored
  through a corrected curve, so any new constant would be invented — the same
  refusal `SHAKY_CLIP` already carries in `intake.py` ("deliberately NOT re-tuned to
  compensate — no real footage has been through this pipeline, so any new value
  would be invented"). What this slice does instead is store the curve's *inputs*
  (§5), after which re-tuning costs nothing and can be done against a real
  `FOOTAGE.json`.

---

## 2. Decisions locked

| # | Decision | Why |
|---|----------|-----|
| 1 | One consumer in v1: `edit_plan`. Music/colour/effects/QC are not wired to the preset. | A field nothing reads is a placeholder, and the repo bans those. Music is already mood-driven through `mood.py`. |
| 2 | Preset carries `shot_mix` + `asl` only. | Exactly what the consumer reads. |
| 3 | `shot_mix` is load-bearing, not decoration: it decides **which** under-use is refusable. | A size the preset does not want is reported, never refused. |
| 4 | `asl` is measured and printed, never enforced. | Shot length is set by the footage and by `pacing`'s grid fit. Refusing on it would blame the editor for the material. |
| 5 | The gate compares **available vs used**, not used vs an ideal distribution. | The machine can prove "the footage offered close-ups and you took none". It cannot prove that an ideal mix was reachable. |
| 6 | Refusal only on `used[s] == 0`; deviation from the target fractions is reported. | The cheapest non-vacuous rule. Anything finer needs thresholds nobody can justify yet. |
| 7 | Refusal is overridable by a **written waiver** in `selection.json`, which rides into the stamped `EDL.json`. | A hard gate with no exit is satisfied by inserting a bad shot — it would damage the reel it protects. The attested-run invariant applies: not *no bypass*, but *no silent bypass*. |
| 8 | Both sides of the comparison are measured in **delivered** geometry at the project's default framing. | Source-geometry tags cannot discriminate (§1c). Mixing the two units makes the comparison meaningless. |
| 9 | `CACHE_VERSION` 6→7: intake stores `subject_w`, `subject_h`, `present`. | The measurement behind `shot_type` and behind `score` is currently thrown away. Storing it once ends a whole class of future re-scans. |
| 10 | No `SPEC.json` → the `balanced` preset, gate still live. | Skipping the optional reel-brief must not disable a quality gate. |

---

## 3. Module boundary

```
lib/mood.py         MoodVector + MOOD_ANCHORS + mood_target   (+4 anchors, §4.3)
                         ▲ resolution reuses this vocabulary — no second lexicon
lib/moodpreset.py   NEW. MoodPreset, PRESETS, BALANCED, resolve,
                    VarietyReport, evaluate.  Pure, stdlib + lib.mood only.
lib/footage.py      FootageWindow +3 measured fields; shot_type(w,h) moves here
                    from intake with its thresholds; delivered_shot(...) added.
lib/geometry.py     crop_for(...)  — unchanged, consumed by delivered_shot
lib/edl.py          EDL.variety: VarietyReport | None
scripts/intake.py   _build_window stores what it already computes; CACHE_VERSION 7
scripts/edit_plan.py counts both sides, calls evaluate, refuses or attaches
```

`moodpreset.py` holds both the table and the evaluation, following `safezones.py`
(which holds `SafeZone`, the platform table, and `evaluate` in one module) rather
than splitting a 120-line pure module in two.

The evaluation takes plain count dicts, not `Footage`/`EDL` objects, so it has no
import edge to the contracts and every branch is unit-testable on literals. The
counting — walking clips, windows and episodes — stays in `edit_plan`, which owns
those objects already.

---

## 4. `lib/moodpreset.py`

### 4.1 The type

```python
@dataclass
class MoodPreset:
    name: str
    anchor: mood.MoodVector | None    # None ⇒ fallback-only, never a match target
    shot_mix: dict[str, float]        # keys exactly footage.SHOT_TYPES; values sum to 1.0
    asl: tuple[float, float]          # (lo, hi) seconds, lo < hi
```

`__post_init__` refuses: an empty name; `shot_mix` keys that are not exactly
`footage.SHOT_TYPES`; a value outside `[0, 1]`; a sum that misses `1.0` by more than
`1e-6`; a non-positive or inverted `asl`.

`SHOT_TYPES = ("close", "medium", "wide")` is new, and it lands in `footage.py`
beside the classifier that produces those tags (§6) — the vocabulary and the
function that emits it belong together, and both the preset table and the census
then read the same tuple instead of three scattered literals.

### 4.2 The table

Hand-tuned **first cut**. No footage has been cut against them, so they are declared
as guesses in one place, the way `CLUSTER_COS` and `MAX_CAST` are.

| preset | anchor (energy, brightness, pace) | close | medium | wide | ASL band (s) |
|--------|-----------------------------------|-------|--------|------|--------------|
| `fun` | 0.74, 0.84, 0.72 | 0.35 | 0.40 | 0.25 | 1.2 – 2.5 |
| `epic` | 0.80, 0.55, 0.55 | 0.25 | 0.35 | 0.40 | 1.5 – 3.5 |
| `moody` | 0.48, 0.22, 0.42 | 0.30 | 0.35 | 0.35 | 2.5 – 5.0 |
| `nostalgic` | 0.32, 0.45, 0.34 | 0.35 | 0.40 | 0.25 | 2.0 – 4.0 |
| `balanced` | — (fallback only) | 0.25 | 0.40 | 0.35 | 1.5 – 4.0 |

`BALANCED` is deliberately **outside** the nearest-neighbour search. A mid-range
anchor placed in the table would swallow every mood that sits between the four
named ones; as a pure fallback it fires only when nothing matched at all.

`BALANCED`'s own mix is not neutral-by-abstention: at `close = 0.25` it is above
`WANT_FLOOR`, so the autonomous path — no reel-brief, no `SPEC.json` — still gets a
live gate. §1.1 of the playbook makes the grammar rule universal: a montage that
stays one size reads amateur, whatever the mood.

### 4.3 Resolution — one vocabulary, not two

```python
def resolve(mood_text: str | None) -> MoodPreset:
    """SPEC.mood → the closest named preset. Empty/unknown → BALANCED."""
```

`mood.mood_target(text)` maps the free text into the existing `MoodVector` space by
averaging every token that is a `MOOD_ANCHORS` key; `mood.distance` then picks the
nearest preset anchor. No new lexicon, no second place to keep synonyms in sync.

`mood_target` returning `None` (no token recognised) → `BALANCED`. Because
`BALANCED` is never a match target, `preset.name == "balanced"` is an exact test for
"nothing matched", which is what `edit_plan` logs against — the fallback is never
silent, mirroring `scripts/mood.py`'s existing no-anchor log.

Four anchors are added to `MOOD_ANCHORS`, from the real brief and the §1.3 matrix:

| token | energy | brightness | pace |
|-------|--------|------------|------|
| `fun` | 0.75 | 0.85 | 0.72 |
| `playful` | 0.72 | 0.82 | 0.70 |
| `nostalgic` | 0.35 | 0.45 | 0.35 |
| `adventure` | 0.80 | 0.60 | 0.65 |

This changes landed behaviour: a brief containing these words previously fell into
`rank_by_drive` and now ranks by distance. That is the point of the fix (§1b′), and
it is covered by a test that pins `mood_target("fun and playful")` non-`None`.

---

## 5. What the cache stops throwing away — `CACHE_VERSION` 6→7

`scripts/lib/intake_cache.py` persists `FootageClip.to_dict()`, its phashes, and its
cast. The per-sample timeline is not persisted, and `_build_window` reduces the
primary bbox to a three-way bucket before storing. Both the bbox and the presence
fraction — **already computed as locals in `_build_window`** — are then discarded.

That is why nothing downstream can re-derive shot size in another geometry, and why
re-tuning `score` needs a full re-scan. `FootageWindow` gains three floats:

```python
subject_w: float = 0.0   # primary person's bbox width, fraction of the SOURCE frame width
subject_h: float = 0.0   # …height. 0.0 / 0.0 ⇒ no person detected in this window
present:   float = 0.0   # fraction of the window's samples holding ≥ 1 person
```

All three are validated into `[0, 1]`. All three are *measurements*; `shot_type` and
`score` remain the derived verdicts, kept for readability and back-compat.

Fractions, not pixels: the CV runs on the 960-long-side analysis proxy, and the
2026-08-01 design already relies on every measurement being scale-normalized so that
"only the divisor width changes". Storing fractions keeps that invariant.

**Cost, stated plainly:** the key term is `CACHE_VERSION`, so every cached clip
misses and the next `footage-intake` re-scans the whole folder. That cost is paid
once, and it is paid *now* rather than twice, because the `_motion_fit` re-tune
(§1.1) would have required its own bump later — after this slice it requires none,
since `present`, `motion`, `shake` and `dur` are all on disk and `score` becomes
recomputable outside Phase 1 forever.

**Old artifacts fail loud.** A `FOOTAGE.json` written before this slice has no
`present` key, and the three fields carry dataclass defaults of `0.0` — so
reconstruction would succeed while silently claiming "no people anywhere", exactly
the quiet wrong answer the fail-loud contract exists to prevent. The defaults cannot
be dropped (they keep `FootageWindow(...)` constructible in tests and in
`_build_window`), so the guard goes where the artifact is parsed:
`FootageClip.from_dict` checks key *presence* on each window dict before it calls
`FootageWindow(**w)`, and raises

```
FootageClip.from_dict: windows[3] predates the 2026-08-06 shot-size fields
(missing 'present') — re-run footage-intake to rescan.
```

This is the same boundary that already refuses a non-dict window with a remedy, and
it is the only reader of the artifact, so one guard covers every consumer.

---

## 6. Delivered-geometry shot size

`intake.shot_type(bbox, res)` becomes `footage.shot_type(w_frac, h_frac)` — thresholds
`CLOSE_AREA = 0.30` and `MEDIUM_AREA = 0.08` move with it — so one classifier serves
both geometries and there is no second copy to drift. `intake` calls it with source
fractions; `edit_plan` calls it with delivered ones through:

```python
def delivered_shot(subject_w: float, subject_h: float, res: tuple[int, int],
                   aspect: tuple[int, int], crop_scale: float = 1.0) -> str:
    crop_w, crop_h = geometry.crop_for(aspect, crop_scale, *res)
    return shot_type(min(1.0, subject_w * res[0] / crop_w),
                     min(1.0, subject_h * res[1] / crop_h))
```

The clamp matters: a subject wider than the crop is fully framed, and an area
fraction above 1.0 is not a thing. A window with no people carries `0.0 / 0.0`, so
it classifies as `wide` — the same answer `intake.shot_type` gives today for a
`None` bbox, and the reason scenery reads as `wide` in both geometries.

**What this buys, and what it does not.** `fill` from 16:9 to 9:16 crops width only:
for 3840×2160 the crop is 1215×2160, a multiplier of `3840/1215 = 3.16` on width and
`1.0` on height, so the area fraction scales by 3.16. The `medium` boundary therefore
moves from 8 % of the source frame to **2.5 %**, and `close` from 30 % to **9.5 %**.
That is a three-times wider net and it is what makes a distribution exist where
before there was a single bucket. It does not manufacture close-ups: a subject still
has to fill 9.5 % of the source frame to be tagged one.

**Both sides use the project's default framing** — layout `fill`, `crop_scale = 1.0`,
the canvas from `project.json`. A per-episode `fit`, `insert`, or punch-in is not
reflected. The alternative (per-episode geometry for `used`, default for `available`)
puts the two sides of the comparison back into different units, which is the failure
§1c is about.

---

## 7. The gate

```
available[s] = windows over ALL clips whose delivered_shot == s
used[s]      = EDL episodes whose window's delivered_shot == s

gap(s)  ⟺  used[s] == 0
       and available[s] >= MIN_AVAIL          (3)
       and preset.shot_mix[s] >= WANT_FLOOR   (0.20)
```

- **`available` counts every window, never only `best`.** `best` is a threshold on a
  score whose ordering leans toward motion (§1.1); a denominator drawn from it would
  inherit the very lean the gate exists to correct. Windows the phash cull removed
  are already absent from `FOOTAGE.json` and so are correctly outside the pool.
- **`MIN_AVAIL = 3`** — one stray misdetection must not block a reel.
- **`WANT_FLOOR = 0.20`** — a size the preset genuinely asks for.
- Counting is by **window**, not by duration: the grammar rule is about how many
  shots, not how many seconds.
- A span episode (`"window": [i, j]`) inherits window `i`'s shot size, matching the
  existing `_merge_windows` rule for `shot_type`.

A gap is a `stop_and_report` with reason **`variety-gap`** — its own reason, not
`edl-invalid`, so the failure is attributable without parsing prose. The message
names the preset, each gapped size with its available count, and the **top three
candidate windows by score** so the fix is mechanical:

```
variety-gap: preset 'fun' wants close (target 0.35) and the footage offers 11
close windows, but the cut uses 0.
  Candidates: MVI_3821.mp4 #4 (score 0.82), MVI_3799.mp4 #2 (0.79),
              MVI_4146.mp4 #7 (0.74)
Add one, or state a reason in selection.json: "variety_waiver": "<why>".
```

Deviation from the target fractions when `used[s] > 0`, and the realized ASL against
the preset's band, are **reported** — numbers in `EDL.md` — and never refused
(decisions 4 and 6).

Before evaluating, `edit_plan build` logs the delivered-geometry census
(`available` per size). This is deliberately a log line and not a section of
`FOOTAGE.md`: `Footage.to_markdown` has no canvas, so anything it printed would be
in source geometry, and two geometries in one report is the confusion §6 exists to
end.

---

## 8. The waiver

`selection.json` gains one optional top-level key:

```json
{ "episodes": [ ... ], "variety_waiver": "every close window is out of focus" }
```

A present-but-blank waiver is refused — `"a variety_waiver must state a reason"` —
because an empty string is a bypass wearing the costume of a decision.

The reason rides into `EDL.variety.waiver`, is printed in `EDL.md`, and lands inside
the artifact `edl.write_edl` stamps (2026-08-04). Editing it afterwards makes the
digest mismatch and `EDL.from_json` refuses the file. The exception is therefore
recorded where it cannot be quietly revised.

---

## 9. Contract and rendering

```python
@dataclass
class VarietyReport:
    preset: str
    available: dict[str, int]
    used: dict[str, int]
    asl: float
    asl_band: tuple[float, float]
    gaps: tuple[str, ...] = ()
    waiver: str | None = None

    @property
    def ok(self) -> bool:
        return not self.gaps or bool(self.waiver)
```

`EDL.variety: VarietyReport | None`, round-tripped by `to_dict`/`from_json`. `None`
means the EDL was not evaluated — a hand-authored EDL entering through
`edl_to_reel`'s SP1 front door — and is not an error.

The object has to carry the numbers because `EDL.to_markdown` renders from the
object; a report that lived only in the driver could not be printed. `EDL.md` gains
a `## Variety` section: preset name, an available-vs-used row per shot size, ASL
against the band, and the waiver line when one is present.

---

## 10. Wiring

`edit_plan build` gains one optional flag:

```
python -m scripts.edit_plan build --footage FOOTAGE.json \
  --selection selection.json --project project.json --out-dir . \
  [--cast cast.json] [--spec SPEC.json]
```

No `SPEC.json` → `BALANCED` (decision 10). No new `V1_STAGES` row and no new
artifact: the gate lives inside a stage that already exists and already refuses.
The `edit-plan` SKILL documents the objective, the waiver, and `--spec`; the
`using-montage` router passes `--spec` when a brief exists.

---

## 11. Failure modes

| Situation | Behaviour |
|-----------|-----------|
| `FOOTAGE.json` predates the new fields | `ValueError` naming the missing key and the remedy (§5) |
| `SPEC.mood` matches no anchor | `BALANCED`, logged by name — never silent (§4.3) |
| No `SPEC.json` at all | `BALANCED`, gate live |
| A preset's `shot_mix` does not sum to 1.0 | Construction-time `ValueError` — the table cannot ship broken |
| Footage has fewer than `MIN_AVAIL` windows of a wanted size | No gap; the size is reported as unavailable |
| Footage has no windows at all | `available` all zero, no gap possible, report still written |
| A blank `variety_waiver` | Refused (§8) |
| Hand-authored EDL through `edl_to_reel` | Not evaluated; `EDL.variety` is `None` (§13.5) |

---

## 12. Testing

**Unit, pure.** `MoodPreset` validation (each refusal); the five-row table sums;
`resolve` for each named preset, for `"fun and playful"`, for an unknown string, for
`None` and `""`; `evaluate` across gap / no-gap / waiver / `MIN_AVAIL` boundary /
`WANT_FLOOR` boundary; `VarietyReport.ok` for all four combinations of gaps × waiver.

**Unit, geometry.** `footage.shot_type` at the exact `0.08` and `0.30` boundaries;
`delivered_shot` reproducing the 3.16× multiplier for 3840×2160 → 9:16, including a
window that is `wide` in source geometry and `medium` in delivered; the clamp for an
over-wide subject; a people-less window classifying `wide`; `FootageClip.from_dict`
refusing a window dict without `present`.

**Unit, driver.** The gate refuses with `variety-gap` and the message names the
candidates; a waiver passes it; a blank waiver does not.

**Integration.** The intake golden re-pins with the three new fields present. The
SP3→SP1 golden carries a `variety` block through `EDL.json` → `EDL.md`.

**Mutation checks — steps, not suggestions.** Each must turn a test red:

1. Filter `available` to `best` windows only.
2. Drop the delivered scaling — classify on source fractions.
3. Accept a blank waiver.
4. Count `available` by duration instead of by window.
5. Put `BALANCED` into the nearest-neighbour search.

---

## 13. Honest limits

1. **`shot_type` is bbox area.** It knows nothing about faces, expression, or
   framing intent. Two `close` windows of the same person in the same pose satisfy
   the gate completely.
2. **Delivered geometry widens the net; it does not create shots.** The multiplier
   is exactly `src_w / crop_w` (3.16 for 16:9 → 9:16). Footage whose subject never
   exceeds 2.5 % of the source frame is still legitimately all-`wide`, and then the
   gate cannot fire at all. It proves *"you used what was there"*. It never proves
   *"the reel is varied"*.
3. **One geometry for both sides.** Per-episode `fit`, `insert`, and punch-in
   framings are invisible to the census (§6).
4. **ASL is measured, never enforced** (decision 4).
5. **The SP1 front door bypasses the gate entirely.** A hand-authored `EDL.json`
   driven straight through `edl_to_reel` never runs `edit_plan` — the same
   deliberate perimeter the attested-run design draws around unstamped EDLs.
6. **The waiver is self-granted.** The agent that authored the monotone cut is the
   agent that writes the reason. What it buys is a recorded, tamper-evident decision
   surfaced to the human at review — not an independent check. The invariant is *no
   silent monotony*, not *no monotony*.
7. **The preset numbers have no footage behind them.** Five rows of hand-tuned
   fractions and four hand-placed anchor vectors, tunable in one place, to be
   calibrated on the first real run that uses them.
8. **The ranking stays action-leaning.** `_motion_fit` is untouched (§1.1), so
   `FOOTAGE.md`'s order still favours motion. The gate is blind to `best` precisely
   so that it does not inherit that ordering.

---

## 14. Deferred, with reasons

- **Hero-conditioned re-scan** — after cast naming, re-measure the windows holding a
  named hero, cropped to that hero: their *own* bbox rather than the largest
  person's, plus face visibility. This is the richer half of the same idea and it is
  its own slice: face detection is a new model, a new download, and a new
  `verify_runtime` gate, and the cheap full-pool census this slice needs does not
  depend on it.
- **`_motion_fit` re-tune** — free after §5's bump, and blocked on having real
  footage to tune against rather than on code (§1.1).
- **Colour palette from the preset** — biasing `match_grade`'s common target by mood
  instead of by source median. Touches a landed conductor and needs its own
  real-ffmpeg convergence proofs.
- **Effects from the preset** — blocked on #7/#18, whose only copy still lives on
  the parked `wip/montage-run-patches` branch.
- **Per-episode QC against the preset** (#3) — the preset finally gives QC something
  concrete to judge, but the judging stage is a separate build.
- **Shot-order grammar** — "never two same-size shots back to back" is measurable
  from the same counts, but it is a second rule with its own threshold debate; the
  numbers this slice records make it cheap to add later.
