# Unmeasured, named — design (2026-09-10)

**Backlog:** the L1/L2 half of the "domain leaks into general machinery" audit.
Sibling of [named absence](2026-09-07-named-absence-design.md): that slice was
about a report **discarding a number it had computed**; this one is about a
report **claiming a measurement it never made**.

**Thesis (§1):** an instrument's report must name what it could not measure.

**Two sites:** the variety census, which counts a person detector's silence as a
wide shot; and the window scorer, whose largest weight separated three windows
out of 1508 and says so nowhere.

---

## §0 The measurement half

Every number below is read off the only real artifact set —
`FOOTAGE.json` from the 2026-06 run: **99 clips, 1508 windows**. It is probed
read-only; nothing is written there.

### §0.1 The scoring term that separated three windows

`scripts/intake.py:157`:

```python
blend = [W_PRESENT * w.present + W_MOTION * m + W_STABLE * s ...]
#         0.44                   0.28           0.28
```

`motion` and `stable` are **percentile ranks** — the 2026-08-06 motion-scoring
slice made them so. `present` was deliberately left absolute, with a stated
reason: *"its fraction already meaning what it says"*.

On the real pool `present` barely varies:

| value | windows | share |
|---|---:|---:|
| `present == 1.0` | 1505 | 99.8% |
| `present == 0.0` | 1 | 0.1% |
| `0 < present < 1` | 2 | 0.1% |

Ranked per term, how many windows each one actually **separated** (windows not
sitting at the term's modal value):

| term | distinct values | largest tie | separated |
|---|---:|---:|---:|
| `present` | 4 | 1505 | **3 / 1508** |
| `motion` | 376 | 79 | 1429 / 1508 |
| `shake` | 118 | 50 | 1458 / 1508 |

The largest single weight in the blend distinguished **three windows**. Nothing
in `FOOTAGE.json`, `FOOTAGE.md` or any log says so. This is the number the open
backlog row **R8.1** ("the score bought no part of the delivered reel") is
missing: not that the score was ignored, but that 44% of it had nothing to say.

### §0.2 The variety census counts a detector's silence as a wide shot

`VarietyReport.available` is rendered in `EDL.md` under **"Variety"** as a table
headed `available`, and quoted in the gate's own log line as *"footage offers
…"*. It is built at `scripts/edit_plan.py:384` from

```python
counts[delivered_shot(w.subject_w, w.subject_h, clip.res, aspect)] += 1
```

and `subject_w`/`subject_h` come from a **person detector** (`classes=[0]`, the
one deliberate domain binding — a hero is a person, and that is not in question
here). A window where nobody was detected carries `(0.0, 0.0)`, whose shot size
is `wide`.

On this pool that is **1 window of 1508** — the shoot is 99.8% people, so it
cannot exercise the defect. The reachable case is a shoot with no people in it.
Take a food or product shoot: every window is tagged `wide`, so

- `available == {close: 0, medium: 0, wide: N}`;
- no gap fires, because `available[close] == 0 < MIN_AVAIL` (3);
- the gate **passes silently**, and its report states that the footage offers
  zero close-ups — about footage that is entirely close-ups.

Not a refusal. A false measurement, presented in the same table as the real ones.

### §0.3 What this pool cannot tell us

Ranking `present` (§3) changes **nothing observable** here:

| | today | `present` ranked |
|---|---|---|
| Spearman of the two orderings | — | **0.999039** |
| `best` set size | 755 | 755 |
| `best` symmetric difference | — | **0** |
| top-8 / top-30 / top-100 overlap | — | **8/8 · 30/30 · 100/100** |

That is the strongest thing that can be said for the change and the weakest: it
is **provably free on the only pool that exists**, and that same pool cannot
show it doing any good. §3.2 is why "free" is the reason to do it now.

### §0.4 Two claims made while designing this, both overturned

Recorded because both are plausible-looking statistics that answer the wrong
question, and either would have shipped a wrong number in the report:

1. *"Ranking presence changes the stored score of 555 windows."* True and
   meaningless. `score` is `round(percentile, 3)`; when one window jumps 1505
   places, every percentile below it shifts by ~1/n, and the third decimal
   catches ~555 of those. **One** window reordered.
2. *"Leave-one-out says presence moves 493 windows."* Same artifact. Zeroing a
   near-constant term subtracts a constant from 1505 windows (no reorder among
   them) and nothing from the 3 outliers, so the outliers re-sort and the
   rounding churns. Leave-one-out on a **percentile** is not a measure of a
   term's contribution.

The statistic that survives is separation (§0.1) — how many windows the term's
own input distinguished — because it asks about the term, not about the
downstream rounding.

### §0.5 What is NOT the defect: `shot_type`

The first shape of this design proposed a fourth shot tag (`unknown`) for
`shot_type(0.0, 0.0)`. That is wrong, and the tree says so in three places:

```python
# tests/lib/test_footage.py:377
assert footage.shot_type(0.0, 0.0) == "wide"          # no subject → scenery
# tests/lib/test_footage.py:398
def test_delivered_shot_without_people_is_wide_in_any_geometry(): ...
# tests/lib/test_intake.py:22
assert footage.shot_type(0.0, 0.0) == "wide"
```

and in the function's own docstring: *"No subject — (0.0, 0.0) — is 'wide', the
same answer scenery gets."*

`shot_type` is a claim about the **frame** — how much of it the subject fills —
not about a person. Nothing fills it, so it is wide; a drone shot of an empty
coastline is a wide shot, correctly. The function is right. The defect is one
level up, where its output is aggregated into a census and **presented as a
description of the footage**. `shot_type` is not touched by this slice, and
neither are those three tests.

### §0.6 Why no migration and no re-scan

Both fixes land in code that runs downstream of the cache:

- `score_pool` is **Phase 2** (`scripts/intake.py:600`) — it runs after the
  per-clip cache is loaded, so a change to the blend costs no `CACHE_VERSION`
  bump and no re-scan of 99 clips.
- The variety census **never reads the stored `shot_type` field**. Both sides
  (`scripts/edit_plan.py:384` and `:507`) recompute through
  `delivered_shot(w.subject_w, w.subject_h, …)`, and `subject_w`/`subject_h`
  have been on disk since `CACHE_VERSION` 7 — the 2026-08-06 slice stored them
  precisely so the derived tag could be re-derived later for free.

So the fix reaches artifacts already written, without rewriting them.

---

## §1 The thesis

An instrument's report must name what it could not measure.

A report that omits its own blind spot does not read as incomplete — it reads
as a measurement. `available: {close: 0}` and a 0.44 weight both look like
findings. The remedy is never to make the instrument answer anyway (that is how
`shot_type(0,0) == "wide"` would have become a lie), and never to refuse (a
people-free reel is not an error). It is to publish the size of the silence
beside the answer.

---

## §2 The variety census names what it could not measure

`VarietyReport` gains one field:

```python
unmeasured: int = 0   # windows in the `available` pool carrying no detected
                      # subject (subject_w * subject_h == 0). They are counted
                      # in `available` as `wide` — see §0.5 — and this is how
                      # many of that count came from a silent detector.
```

- Validated in `__post_init__` as an `int >= 0`, and `<= sum(available.values())`.
- Round-trips through `to_dict`/`from_dict`; absent on an `EDL.json` written
  before this slice, where it reads back as `0` — the same "written before"
  arm `VarietyReport.gaps` already has.
- `moodpreset.evaluate()` takes it as a parameter and carries it through.
- `edit_plan._available_census` returns it alongside the counts.
- `EDL.md`'s Variety section names it, and only when it is non-zero — a
  zero line on a people-shoot is noise, and this project already rejects
  rendering a section that says nothing (`EDL.md`'s editorial-rules block).
- The gate's own log line (`scripts/edit_plan.py:761`) names it too, because
  that line is what a running agent sees.

### §2.1 Why only the `available` side

`available` is the side that makes a claim **about the footage** — "this is what
you had to choose from". `used` is 8–30 windows a human already chose and can
see. One count, on the side that can be wrong about something the reader cannot
check.

### §2.2 What this does not do

It does not make the gate work on people-free footage, and it must not: refusing
a landscape reel for having no close-ups would be the same domain leak pointing
the other way. It makes the gate's **silence legible**. On a food shoot the
report reads `wide N, of which N unmeasured` — i.e. *this gate measured nothing*.

---

## §3 The scorer's third term becomes a rank

```python
presence = _percentile_rank([w.present for w in windows])
blend = [W_PRESENT * p + W_MOTION * m + W_STABLE * s
         for p, m, s in zip(presence, motion_fit, stability)]
```

### §3.1 Pool-wide, not per-clip

`motion` ranks **within its own clip** above `CLIP_POOL_MIN` (5) because
"the active moment of this shot" is a within-shot question. `shake` ranks
**pool-wide** because steadiness is a camera property. Presence is the second
kind: "does this window hold the subject" is comparable across the whole shoot,
and a landscape clip's windows *should* rank below a portrait clip's when
presence is what is being asked.

Pool-wide is also what makes the term self-neutralising. On a shoot with no
people every `present` is `0.0`, `_percentile_rank` returns a **constant** (a
tied pool of six returns `0.5` for all six, verified), and the module's own
docstring already states that a constant factor is *"unable to distort the
ordering"* once the blend is itself ranked. The term contributes nothing exactly
where it has nothing to measure — instead of contributing a uniform 0 that still
outweighs two ranks on mixed footage.

### §3.2 Why fix a measured no-op

Today the term is an **absolute** quantity summed against two **ranks**. That is
a units mismatch, and it is harmless here only because the term is near-constant.
Where it is not, it dominates by construction:

| | best possible blend |
|---|---:|
| a window with no people (`present = 0`) | `0.28 + 0.28` = **0.56** |
| a window full of people (`present = 1`) | `0.44 + 0 + 0` = **0.44** |

A people-free window needs a mean rank of **0.786** across motion and shake
merely to tie the *worst possible* window containing a person. No such pool
exists yet, which is the argument: the correction is available now at a measured
cost of zero (§0.3), and will not be once a mixed shoot's ranking depends on it.

---

## §4 The scorer reports which terms did work

`score_pool` returns a small report; `Footage` carries it.

```python
scoring: dict | None = None
# {"windows": 1508, "separated": {"present": 3, "motion": 1429, "shake": 1458}}
# None on a FOOTAGE.json written before 2026-09-10 — the Footage.band precedent.
```

`separated[t]` is `len(windows) - (count at the modal value of term t's vector)`:
how many windows that term's input distinguished. Computed on the term vectors
the blend actually consumes — the ranked ones — so it measures what was spent,
not what was available.

### §4.1 Why this statistic and not the two that failed

§0.4 records both alternatives and why each answers the wrong question.
Separation asks about the term's own input and is immune to the percentile
rounding that made the other two report 555 and 493 for a three-window effect.

Its honest limit is `motion` alone: it ranks per-clip above `CLIP_POOL_MIN`, so
two windows in different clips can land on the same rank value by coincidence
(every clip's top window ranks 1.0). The count is therefore **exactly what the
blend consumed** — which is the number that matters — but a **lower bound** on
what the raw measurement distinguished. `present` and `shake` rank pool-wide and
carry no such gap.

Neither reading changes what the field exists for. A coincidence can only merge
two values, never split one, so an inert term cannot be inflated into looking
useful — which is the direction that would matter.

### §4.2 Where the report lives

- `Footage.scoring`, validated in `__post_init__`, serialized by `to_dict`,
  read back by `from_dict` (`None` when absent).
- One line in `FOOTAGE.md`'s header block, beside the existing sentence
  explaining that `score` is a percentile — the same paragraph a reader consults
  to know what the number means.
- `intake()` constructs `Footage` **after** scoring, so the field passes through
  validation rather than being assigned onto a built object:

```python
clips = [r.clip for r in ok]
scoring = score_pool(clips)
result = footage.Footage(clips=clips, band=band, scoring=scoring)
```

---

## §5 What does not change

- `shot_type` and its three pinning tests (§0.5).
- `classes=[0]` — a hero is a person; that binding is deliberate and out of
  scope.
- `SHOT_TYPES`, and therefore `MoodPreset.shot_mix`: a mood must never be able
  to ask for a share of "unmeasured".
- The gate's `gaps` logic. It already judges only what it could measure —
  `available[s] >= MIN_AVAIL` — and keeps doing so.
- `CACHE_VERSION`, `intake_cache.clip_key`, and every Phase-1 measurement.
- `W_PRESENT` / `W_MOTION` / `W_STABLE`. Re-weighting is a calibration question
  and needs a pool this one cannot supply (§7).

---

## §6 The honest half

- **Neither fix makes a reel better.** One makes a silent gate legible, the
  other corrects a units mismatch that is currently inert. Both remove a claim
  the instrument does not support. That is the whole benefit.
- **The only real pool cannot validate either.** It is 99.8% people, so it shows
  the presence fix is safe (§0.3) and cannot show it is useful, and it exercises
  the census defect exactly once. A people-free or mixed shoot is the evidence
  neither fix has.
- **Nothing proves anyone reads the new numbers.** `Footage.scoring` and
  `VarietyReport.unmeasured` are reports, not gates. This is the same limit the
  contact-sheet stage carries (2026-08-05 §9) and it is not closed here.
- **`separated` is a lower bound for `motion`** (§4.1).
- **The census still cannot see a subject the detector was never asked about.**
  `unmeasured` counts windows where the *person* detector found nothing. On a
  food shoot it will correctly report that the census measured nothing; it will
  not report what the plates were doing. Naming a non-person subject is a
  different instrument and is not in this slice.

---

## §7 Deferred

Per the backlog rule, every row below is filed in `docs/backlog.md` when this
slice lands.

| Item | Size | Why not here |
|---|---|---|
| **Re-derive `W_PRESENT`/`W_MOTION`/`W_STABLE` against a pool where presence varies.** The three weights are first cuts calibrated on one drone shoot, and §0.1 shows the largest of them separated 3 windows there. Re-weighting needs a pool with real presence variance, which does not exist. | S | No evidence to calibrate against; blocked on a mixed shoot. |
| **A non-person subject sensor.** `classes=[0]` is right for heroes (§5), but nothing measures what a people-free frame contains, so `unmeasured` can name the silence and never fill it. | L | A new instrument, not a report fix. |
| **Make `Footage.scoring` reachable at the moment of need.** It lands in `FOOTAGE.json`/`FOOTAGE.md`; no skill line tells an agent to read it, which is R4.2's exact shape. | S | Belongs with the R4.1/R4.2 discoverability slice, not scattered ahead of it. |
| **The colour knobs' one-shoot constants (L3).** `MID_BLUE_BAND`'s *"the midtone window skin sits in on this footage"* and `shadow_red_arg`'s neoprene reference are the same class of leak, in optional knobs a reel that does not set them never touches. | S | Separate blast radius; deliberately split out when this slice was scoped. |
