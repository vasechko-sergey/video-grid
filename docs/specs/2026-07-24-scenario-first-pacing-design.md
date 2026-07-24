# Scenario-first pacing — the material owns the cut, the music is fitted to it

**Status:** design · 2026-07-24 (§5.6 re-cut; supersedes the generator half of
[pacing](2026-07-14-pacing-design.md))
**Scope:** invert the conveyor's front half — `edit-plan` runs before the music, cut
lengths come from the footage, and pacing becomes a *fitter* that chooses a musical
grid for cuts that already exist.

_Last updated: 2026-07-24._

## 0. What the first real run proved

A 99-clip, 16 GB surf run (2026-07-22..24) delivered 27 reel versions over 26 hours.
Two of its long-running fights trace to one root, and both are structural, not
editorial.

**The music was chosen before the footage was known.** The scan started at 21:05 and
finished at 23:19; the track shortlist was built at 21:26 and the track picked at
23:04. So `SPEC` (23:08), `MUSIC` and `PACING` were all authored against a track,
and the edit was then bent to fit six slots — rather than the six shots the material
actually had.

**The slot ladder cannot express a calm reel.** `_beats_per_slot` returns 2/4/8 beats
by energy band and `HOOK_BEATS` is 2. At the run's 104.17 BPM a beat is 0.576 s, so
the widest reachable slot is 4.6 s — against a surf ride of 6–9 s that must never be
cut (`SPEC.notes` says so in the brief's own words). The run's answer was to patch
`slot_scale`/`bands` into `build_spine` mid-flight and set the scale to ~2, which
produced 9.14 s slots.

That number is the tell: 9.14 s is a **4-bar phrase** at this tempo (9.216 s). The
patch had stumbled onto the right abstraction — a coarser grid level — by scaling the
wrong one. This design names it.

## 1. The inversion

```
was:  intake → [brief] → music → pacing → edit-plan → draft → deliver
is:   intake → [brief] → edit-plan → music → pacing(fit) → draft → deliver
```

`edit_plan build` already accepts an absent `--pacing`; what changes is that this
becomes the normal path rather than the degraded one, and `montage.V1_STAGES` moves
`music-and-mood` and `pacing` behind `edit-plan`.

The reel's length becomes the realized sum of its episodes. `SPEC.length` is the
target the **scenario** aims at; it is no longer the length the music dictates.
`MusicSpec.duration` is set from the realized cut, so `mix` and the length gate agree
by construction. `edit_plan._back_edge_target` stops being a rescue for an under-fill
and becomes the ordinary way the target is computed.

## 2. Who owns duration

Today `_bind_pacing` re-times every episode: `new_dur = min(room, slot.dur)`. The
music is the boss of the cut, and a 7.3 s ride inside a 4.6 s slot is silently
truncated — the exact operation the brief forbade.

After this change, an episode's duration comes from the material: the scored window,
extended into the room its own shot still has (`_room_in_shot`), with `start_offset`
choosing the in-point inside that shot. The spine no longer generates lengths. It
receives them.

## 3. Grid levels — which lines may be cut on

A grid level is **not** a shot length. It answers a different question: *which points
in the music count as legal cut points.*

Beats are not equal. Every 4th beat opens a bar; every 4th bar opens a phrase, which
is usually where the song itself changes. A cut on a downbeat reads as intended; a cut
on the third beat of a bar reads as accidental even though it is "on the beat".

The current code fuses the two questions into one constant — a slot *is* 2/4/8 beats —
which is why the ladder both fixes the cut length and pins the grid. Once §2 moves
length ownership to the material, only the grid question is left.

```
GRID_LEVELS = (("beat", 1), ("half-bar", 2), ("bar", 4), ("2-bar", 8), ("phrase", 16))
```

Lines at level *n* are every *n*-th detected beat, from a phase `p ∈ [0, n)`. Detected
beats — not a synthetic metronome — because librosa's grid is what the reel is checked
against downstream, and a metronome would drift away from it.

**The rule replacing the ladder:** take the **coarsest level that still fits inside the
allowance**. One rule instead of three hardcoded beat counts. Coarser lines are further
apart, so they are harder to hit and more musical when hit; the search states the
trade-off in numbers rather than deciding it in a constant.

**Two search axes**, both cheap:

- *phase* `p ∈ [0, n)` — exact, integer, no cost.
- *window* — the track fragment. `offset.best_offset` currently returns one pick; it
  returns the top *K* here, and each is a candidate whose beat grid is re-phased.

Measured on the run's own reel (cuts at 4.98 / 14.12 / 23.26 / 32.42 / 41.27 s,
104.17 BPM, allowance ±0.288 s):

| level | step | best shift | worst cut | verdict |
|-------|-----:|-----------:|----------:|---------|
| beat | 0.58 s | 0.30 | **0.131** | fits |
| half-bar | 1.15 s | 0.22 | 0.422 | misses |
| bar | 2.30 s | 0.22 | 0.422 | misses |
| phrase (4 bars) | 9.22 s | 4.83 | 0.424 | misses |

The table is computed on an idealized constant-tempo grid, with the shift free and
continuous. That makes it an **upper bound** on what the implementation can reach:
the real search moves the grid in two coarser steps — a window candidate (continuous,
but only the top-K the offset picker offers) times an integer phase. A level the bound
rejects cannot be rescued by the real search; a level it accepts still has to be
re-checked against the detected beats.

The interesting half is *why* phrase misses, and it is not uniform. Measured through the
real fitter (the Task 2 golden), each cut's distance to its nearest phrase line is
**0.204 / 0.076 / 0.076 / 0.056 / 0.366 s**. Three of the five are within a tenth of a
phrase — the two 9.14 s rides are 0.076 short of the 9.216 s phrase, the 9.16 s one 0.056
— so the middle of this reel really is a rounding error away from breathing in whole
phrases. The other two are not: the 4.98 s hook sits about half a phrase from any line,
and the last ride misses by **0.366 s**, past the 0.288 s allowance. That one cut is what
rejects the level.

The distinction matters because it names two different fixes. A uniform small drift is
absorbed by lengthening each ride slightly. A single large miss is not — it needs that
episode re-picked, or the hook rebuilt to a phrase. Nothing in the last run said either.
The fit report says both (§6).

## 4. The allowance, and the action anchor

**The allowance is ±½ beat, always — not ½ a grid line.** Half a phrase is 4.6 s;
an episode moved that far is a different episode. The level chooses which lines exist;
the allowance is a fixed, tempo-derived budget for reaching one.

**Only the out-point slides.** It may move up to ±½ beat, and never past the room its
own shot has. The in-point is the shot's meaning — the take-off, the step into the
water — and a continuous slide would erode it.

**The in-point may jump, not slide.** When a shot contains an active manoeuvre, the
in-point may move to the *next action anchor* if that lands a better ending — the
user's own case: start on the cross-step so the ride finishes on a line. A jump lands
on a detected event; it never stops halfway between two.

**Anchors are measured on demand, for the chosen shots only.** Six shots, not 99
clips: no re-scan. The measure is a global frame-difference curve (mean absolute
difference between consecutive downscaled frames), sampled at intake's `SAMPLE_FPS`;
anchors are its local maxima above a threshold, deduped by a minimum gap. This is a
**proxy** for "a manoeuvre happened", not a classifier, and the design says so — it
fires on any large motion change, including a camera whip. The pacing report names
each anchor it used with its timestamp so a wrong one is visible, not silent.

## 5. What is deleted

- `_beats_per_slot` and `HOOK_BEATS` as **generators of length**. The energy bands
  survive only as a `kind` label (hook/peak/build/release) in the report and as a hint
  for shot ordering; they no longer size anything.
- `slot_scale`, `bands`, `hook_beats` — the mid-run patch. They treated the symptom;
  §3 removes the disease. They go out with the ladder, in the same change, so no call
  site is left pointing at a knob whose meaning has changed.

`build_spine` keeps its name and its purity but changes its job: given cut boundaries
and a beat grid, it emits the fitted `Spine` (slot per episode, its line, its
deviation) instead of inventing slots from energy.

## 6. The fit report and the gate

`pacing` writes `PACING.json` + `PACING.md` as before, but they now report a fit:

- the ranked levels with `worst`/`total` deviation and a `fits` boolean (the §3 table);
- per cut: which line it was matched to, its deviation, whether the out-point moved and
  by how much, and any in-point anchor jump with its timestamp;
- when the coarsest requested level misses, the **reason in numbers** — "phrase misses:
  hook is 4.98 s against a 9.22 s line; cuts run 0.076 s short of a phrase each" — plus
  the three ways out (a different level, a different window, a different scenario
  length). It picks the coarsest level that fits — but never silently: every coarser
  level it rejected is listed with the number that rejected it.

`Slot` gains the two facts a fit has and a generated slot did not: `line` (the beat
index it was matched to) and `dev` (signed seconds from that line). `energy`/`kind`
stay, demoted to labels.

`check_reel`'s existing beat gate is unchanged and stays advisory. After a successful
fit the delivered deviation is ~0 (the cut sits *on* a line), so the 0.05 s tolerance
it already uses keeps its meaning. A cut whose shot had no room stays off-grid and the
gate reports it — the honest degradation.

## 7. Contracts touched

| File | Change |
|------|--------|
| `scripts/lib/gridfit.py` (new, pure) | `GRID_LEVELS`, `Fit`, `fit_level`, `best_fit` |
| `scripts/lib/anchors.py` (new, pure) | `anchors_from_curve` — local maxima, min-gap dedup |
| `scripts/lib/pacing.py` | `build_spine` becomes a fitter; ladder + patch knobs deleted |
| `scripts/pacing.py` | reads `EDL.json` + `MUSIC.json`, writes the fit report |
| `scripts/lib/offset.py` | `best_offsets` returns top-K; `best_offset` delegates at k=1 |
| `scripts/edit_plan.py` | `_bind_pacing` stops re-timing; `_back_edge_target` normal path |
| `scripts/montage.py` | `V1_STAGES` order: edit-plan before music/pacing |
| `skills/using-montage`, `skills/pacing`, `skills/edit-plan` | the new order + the gate |

`start_offset` and `_room_in_shot` (written mid-run on `wip/montage-run-hardening`, tests
green) are adopted rather than re-derived: they are the mechanism §2 needs. "Adopted" is
not "copied verbatim", and the difference is worth naming — `_room_in_shot(ep, clip)` was
a private helper inside `edit_plan` with no input validation, and it lands here as
`FootageClip.room_after(start)`: a method on the type that owns the fact, so `pacing` and
`edit_plan` share one implementation instead of two, with the bool/negative/past-the-end
refusals the original never had. The arithmetic is unchanged, which is the part that was
field-tested.

## 8. Testing

- **Pure, deterministic:** `gridfit` and `anchors` are stdlib-only and pinned by
  goldens, like `pacing`/`offset`/`mood` before them. The §3 table becomes a test —
  the run's real cut times and tempo, asserting beat fits and phrase does not, and
  pinning the per-cut distances so the *reason* is checked and not just the verdict.
- **Mutation checks, as steps not suggestions:** an allowance that reads ½ *line*
  instead of ½ *beat* must fail a test (§4's landmine); a fitter that silently picks a
  finer level when the requested one misses must fail another.
- **Real-ffmpeg proof:** one reel whose episodes keep their measured durations end to
  end — assemble → check → deliver — with `check_reel`'s beat deviation ≤ tolerance and
  no episode's duration equal to a slot length that the spine invented.
- **Anchor honesty:** a synthetic clip with one motion spike yields one anchor at its
  timestamp; a clip with a camera whip yields an anchor too, and the test asserts the
  report names it (the proxy is documented, not hidden).

## 9. Out of scope

- Ranking several **tracks** by fit (music choice stays mood + ears; the fit is
  reported for the chosen track only).
- Intake's per-clip checkpointing and the window band (`WIN_MIN/WIN_MAX` cut a ride
  into equal chunks) — slice **B**.
- The draft approval gate and per-episode agent review — slice **D**.
- Source provenance for externally graded files — slice **E**.
- Colour as a stage — slice **F**.
