# Speed ramp — design

**Date:** 2026-08-09 · **Backlog:** [#7](../fixes-backlog.md) (+ the speed half of
[#18](../fixes-backlog.md)) · **Playbook:** [§4 priority 4](../cinematic-quality-playbook.md),
first slice after #17.

**Status:** design approved 2026-08-09.

---

## 0. Why this slice, and what the parked WIP actually got wrong

The 2026-08-03 run added slow-mo by patching the engine live. The code survives on
one parked commit, `wip/montage-run-patches` (`fbcd052`, "NOT suite-validated"):
`scripts/lib/ramp.py` plus wiring in `extract`/`edl`/`models`/`draft`.

Reading it against today's `main` turns up three separate problems, and only the
first is the one the backlog entry names.

**It fixes the wrong half of the length coupling.** Backlog #7's whole point is
that a ramp *changes the length of the reel*, and scenario-first pacing computes
episode and reel lengths from the footage. The parked patch updates exactly two
readers — `to_manifest_dict`'s `target_dur` and `EDL.to_markdown`'s total. It
leaves the beat-grid fitter, the pacing binding guard, the back-edge target and
`edl_to_reel`'s reel target all reading `ep.dur`. So the grid is fitted to the
length of the *source window* while the reel plays a different length: every cut
after the first ramp drifts off its musical line, silently. §6 enumerates all
eight readers.

**Its renderer bypasses the engine's own safety net.** `apply_ramp` opens a
decoder `Popen` and an encoder `Popen` and pumps raw RGB frames between them in
Python. Today only three modules import `subprocess` — `lib/fetch`, `lib/catalog`
and `lib/proc` — and that is not an accident: `proc.run` is the chokepoint the
landmine lint stands on, seeing every assembled argv (landmine-lint design §5,
ffmpeg-baseline design §5). A fourth importer, pumping bytes through a pipe that
`proc.run` never sees, puts the one effect most likely to be re-tuned by hand
outside the guard. §3 replaces it with one ordinary `proc.run` call.

**Half the file is dead.** `apply_zoom`/`validate_zoom`/`ZOOM_MIN`/`ZOOM_MAX`
were superseded on 2026-08-08 by the subject-anchored zoom slice (#17), which
puts the zoom on the tracked route inside reframe's single encode and inside
every `check_episode` check. The parked file's own comment claims `zoompan`
"quantises the zoom to integer crop positions and JITTERS on a video stream" and
"often does not ramp at all" — written mid-run, never tested, and contradicted by
the landed slice's real-ffmpeg proof (a 24px→39px push-in, measured ratio 1.625
against 1.6667 expected). §9 lists what is not ported and why.

What is worth keeping from the parked file is the *math*: the cosine speed
profile, the `O(t) = ∫1/s` output-time map, and the insight that `s ≤ 1` means
frames are only ever duplicated, never dropped, so no motion is lost. That
survives into `lib/ramp.py` here.

---

## 1. The rule: an episode with a ramp has two lengths, and each one is named

- **`dur`** — how much SOURCE the episode consumes, in seconds of the clip.
- **`play_dur()`** — how long it PLAYS in the reel: `dur + ramp_extra(ramp, dur)`.

Without a ramp they are equal, which is why the codebase has managed with one
word for both. Every consumer in §6 is a place that word now has to be chosen
deliberately. The failure mode this prevents is not a crash: it is a beat grid
fitted to one length while the viewer watches another.

---

## 2. The ramp region must fit inside the window — a refusal

`RampSpec` occupies the closed interval

```
[ at − hold/2 − ease ,  at + hold/2 + ease ]
```

and both ends must lie inside `[0, dur]`. A spec that pokes out is refused at
validation, naming the overhang.

This is not tidiness. It buys three things:

**`ramp_extra` becomes independent of `dur`.** Outside the region the speed is
exactly 1, so `∫1/s` accrues time only inside it. Once the region is fully
enclosed, lengthening or shortening the window changes `O(dur)` and `dur` by the
same amount, and the extra is constant. That makes the length algebra linear and
invertible in closed form — which §6 needs, because `_bind_pacing` has to solve
"what source window plays for exactly `slot.dur` seconds?" If the region could be
truncated by the window edge, that inversion would be numeric, and the refusal
message when it failed would be unexplainable.

This holds of the *approximation* too, not merely of the exact integral, but only
because §3.2 anchors the knots to the region. Evenly spaced knots satisfy the
mathematics and break the arithmetic.

**`_bounds` gets a defined shrink floor.** Pacing may move an out-point inward;
it must not move it inside the ramp region. The headroom is
`dur − (at + hold/2 + ease)`, well-defined only under this rule.

**It is editorially right anyway.** A cut that lands while the shot is still
slowed — the ramp never returning to speed — is a visible artefact, not a style.

---

## 3. The render: one ffmpeg pass

### 3.1 The mechanism

`setpts` remaps each input frame's timestamp through an arbitrary expression of
`T` (the input time, in seconds). Our output-time map `O(t)` is exactly such a
monotonic function, so the ramp is a timestamp remap followed by a resample:

```
setpts='<O(T) as a knot expression>/TB',fps=<source fps>
```

`setpts` moves the frames in time; `fps=` re-quantizes to a constant rate,
duplicating frames where the stream has been stretched. Both are ordinary
filters, so the whole thing is one `proc.run` argv the landmine lint can read.

`O(t)` has no elementary closed form — the cosine ease makes it `∫dt/(a+b·cos)`
— so it is emitted as a **piecewise-linear knot expression**, the same nested
`if(lt(…),…)` shape `reframe._xexpr` already uses for the zoom's crop path.

### 3.2 The knots are anchored to the region, not spread evenly

The obvious scheme — `N` evenly spaced knots across `[0, dur]` — is wrong in a way
that matters, and measurement caught it while this design's own plan was being
written. Evenly spaced knots move relative to the eases as `dur` changes, so the
approximated `ramp_extra` **drifts with the window length**: 2.0812s at
`dur=3.5` against 2.0779s at `dur=6.0` for the reference spec, a 3.3 ms spread,
and up to 124 ms on a shorter ease. §2's whole argument is that the extra is
constant in `dur`; an approximation that quietly breaks it would make
`_bind_pacing`'s subtraction wrong by exactly that drift.

So knots are placed **by structure instead**:

| segment | knots | why |
|---|---|---|
| `[0, region start]` | one interval | speed is exactly 1, so `1/s` is constant and the trapezoid is exact |
| the ease-in | `RAMP_EASE_KNOTS` subdivisions | the only curved part |
| the plateau | one interval | `1/s` is exactly `1/factor` |
| the ease-out | `RAMP_EASE_KNOTS` subdivisions | the other curved part |
| `[region end, dur]` | one interval | speed 1 again |

Zero-width segments are dropped (a `hold` of 0, or a region flush with an edge).

Two things fall out. **`ramp_extra` becomes independent of `dur` to within float
precision (~1e-15)** — bit-identical across `dur ∈ {3.5, 4.0, 6.0, 9.0}`, because
every knot's position is fixed by the spec alone, though not literally exact at
any `dur`: float cancellation drifts it ~3.6e-15 s by `dur=100`. And the accuracy
improves by twelve orders of magnitude: worst error against an independent
Simpson integration drops from 5.3 ms (uniform) to **1.8e-15 s**.

The accuracy is not luck. `RAMP_EASE_KNOTS = 16` converges to machine precision
because the integrand's derivative vanishes at both ends of each ease — which is
precisely the property the cosine was chosen for editorially, so the speed has no
visible corner where the ramp starts or stops. Under Euler–Maclaurin that same
property kills every correction term and the trapezoid rule converges
exponentially rather than as `O(h²)`. Measured: the value stops moving between 8
and 16 subdivisions (Δ = 1.4e-10) and is pure float noise thereafter.

The reference spec yields **36 knots and a 1758-character expression** — the same
order as the zoom's crop-path expression.

### 3.2.1 What the render still costs

Rendered for real, the reference spec produced **6.0667s against an analytic
6.0811s**. That 14.5 ms is *not* knot error — with anchored knots there is
effectively none. It is frame quantization and nothing else: 6.0811s × 30fps is
182.43 frames, and `fps=` emitted 182. A frame is atomic, so the residual is
always under one frame by construction.

### 3.3 Record and render read the SAME knots

One `knots()` function serves both — `ramp_extra` reads its last value, the filter
expression reads all of them — so the recorded length and the rendered one cannot
drift apart. The "record, don't re-derive" principle the zoom slice established
for `PathMeta.crop_ws`.

With §3.2's anchored placement the two agree to machine precision anyway, so this
is no longer what stands between the EDL and a lie. It is what keeps it that way:
change `RAMP_EASE_KNOTS`, move a knot, swap the quadrature — and the record
follows the render automatically, instead of the two being separately correct
until one of them is edited.

### 3.4 Measured against the parked approach

1080p60, 3s source (305 output frames), same near-lossless intermediate:

| approach | wall clock | output | bytes through a Python pipe |
|---|---:|---:|---:|
| one ffmpeg pass (`setpts`+`fps`) | 0.85 s | 5.083 s | — |
| parked Python raw-RGB pipe | 1.12 s | 5.083 s | 1.90 GB |

Identical output length; the pipe is 1.32× the cost. At 4K the byte count
quadruples. But speed is the weakest of the three arguments — the decisive ones
are that the one-pass version goes through `proc.run` (§0), and that ~60 lines of
hand-rolled frame pumping stop existing.

### 3.5 Near-lossless intermediate

The pre-stage encodes at **crf 8**, and the parked file's reason is worth keeping
verbatim in the code: a held slow-mo frame is later ENLARGED by a tight hero crop
in reframe, which magnifies intermediate compression into visible whitewater
macroblocks. crf 18 was measured too lossy for that second-generation crop.

---

## 4. Where it runs: a pre-stage at extract, exactly like stabilize

`extract_edl` cuts `ep{i}_raw.mp4`, then — when the episode carries a ramp —
retimes it and replaces that file in place. Everything downstream sees one longer
segment and knows nothing about ramps.

The reason it is a pre-stage writing a file, rather than a filter in reframe's
chain, is the argument the stabilize design already made (2026-07-20 §1): the
route must be measured on the pixels that ship. A route tracked on un-retimed
time, applied to retimed pixels, would place the crop at the wrong moment — and
`check_episode` would confirm the framing, because path and route would agree
with each other while only the pixels disagreed. Feeding the SAME retimed file to
both the tracker and reframe makes route and pixels one coordinate system by
construction.

Two consequences fall out for free:

**`check_episode` learns nothing.** Composition, continuity, colour fidelity and
the safe-zone geometry all measure the retimed segment, where the route is
already correct. No check becomes ramp-aware. (`checks.jitter` will read *lower*
on a slowed shot, which is true rather than a bug: the subject really does move
less per frame.)

**A reprocess does not re-ramp.** `build_reel`'s retry loop reuses
`e.manifest["segment"]`, so the retimed file persists and the ramp is applied
exactly once. Deterministic.

---

## 5. The judder gate

Slowing by duplication leaves `fps × factor` **unique** frames per second on the
plateau — 60×0.4 = 24 (cinematic), 30×0.5 = 15 (visible stutter).

`MIN_RAMP_FPS = 24.0`, a **hard refusal**, checked in two places:

- **`edit_plan`**, against `FootageClip.fps` — early, free, before any encode.
- **the extract pre-stage**, against the probed fps — the number that actually
  ships, in case the EDL was hand-authored past the first gate.

The message names the maximum `factor` this clip supports
(`MIN_RAMP_FPS / fps`). **No waiver** — the same rule the editorial-constraint and
variety gates follow (governance #8): a subagent cannot quiet a quality gate.

Interpolated slow-mo (`minterpolate`) is deliberately **not** offered. On the
footage this engine was built for, whitewater and spray are the worst case for
optical flow — it produces melting artefacts, which is a worse failure than
honest judder. Deferred, not rejected forever (§13).

---

## 6. The eight places length leaks

| # | site | reads today | must read |
|---|------|-------------|-----------|
| 1 | `pacing.build_pacing` (`pacing.py:74`) | `[ep.dur …]` | `[ep.play_dur() …]` |
| 2 | `pacing._bounds` (`pacing.py:35`) | `room − ep.dur` | unchanged for the tail, plus the §2 shrink floor |
| 3 | `edit_plan._bind_pacing` guard (`edit_plan.py:201`) | `abs(slot.dur − ep.dur)` | `abs(slot.dur − ep.play_dur())` |
| 4 | `edit_plan._bind_pacing` assign (`edit_plan.py:207`) | `dur = slot.dur` | `dur = slot.dur − ramp_extra` |
| 5 | `edit_plan._back_edge_target` (`edit_plan.py:230`) | `sum(e.dur)` | `sum(e.play_dur())` |
| 6 | `edl.to_manifest_dict` (`edl.py:341`) | `ep.dur` | `ep.play_dur()` |
| 7 | `edl_to_reel` reel target (`edl_to_reel.py:144`) | `sum(ep.dur)` | `sum(ep.play_dur())` |
| 8 | `edit_plan.build_edl` ASL average (`edit_plan.py:370`) | `sum(e.dur) / len(episodes)` | `sum(e.play_dur()) / len(episodes)` |

Plus `EDL.to_markdown`: the header total, and a ramp annotation in the row.

**On #2.** Outside the ramp region the speed is 1, so an out-point moved outward
by δ costs exactly δ of source — `room − ep.dur` is already the right bound in
source seconds and needs no conversion. Inward is the asymmetric direction: the
window may not shrink into the ramp region, so `lo` is floored at
`−(dur − (at + hold/2 + ease))` as well as the existing `−ep.dur/2`.

**On #4.** This is why §2 exists. With the region enclosed, `ramp_extra` is a
constant for this episode, so the source window that plays for `slot.dur` is
`slot.dur − ramp_extra` — one subtraction, no solver.

**On #7.** `check_reel`'s length gate compares the measured master duration
against `ReelCheckSpec.target_dur`, which `edl_to_reel` computes from the EDL. Fix
the sum and the gate is correct; the gate itself needs no change.

**On #8.** Not in the original seven — found by the final whole-branch review,
after Tasks 0–10 had already landed, not anticipated while this design was being
written. Average shot length is SCREEN time; summing `dur` under-reports exactly
the episodes a ramp was authored on. `moodpreset.py` only ever REPORTS `asl`
against a band (never enforces it), so the miscount was mechanically harmless —
but it falsified this table's own claim that every length consumer had been
converted.

---

## 7. Stage order enforces itself

A ramp is authored in the EDL, which is written **before** pacing. A ramp added
afterwards invalidates the fit — and the binding guard (#3 above) catches it: the
slot and the played length diverge past the half-beat allowance and the run
refuses, naming "re-run pacing against the current EDL.json". The coupling
backlog #7 identified is mechanically enforced, not merely documented.

---

## 8. The contract and the authoring path

`RampSpec` is a frozen dataclass in `models.py`, beside `ZoomSpec` and `PanSpec`
— not the parked file's raw dict. Wire form:

```json
"ramp": {"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}
```

- `at` — the peak moment, seconds from the WINDOW start (not the clip start)
- `factor` — minimum speed, `0 < factor ≤ 1`; 0.4 means 2.5× slower
- `ease` — cosine ramp-in and ramp-out length, seconds each side, `> 0`
- `hold` — plateau length at `factor`, seconds, `≥ 0`

Refusals, all refuse-not-clamp: a non-numeric field; `factor` outside `(0, 1]`;
`ease ≤ 0` (a step change is not a ramp); `hold < 0`; the §2 region overhang; and
the §5 judder floor wherever fps is known.

`factor` is a literal speed multiplier rather than a "2.5× slower" figure, for the
same reason `ZoomSpec` took literal `from`/`to` scale numbers: the wire format
states the quantity the filter uses, and the SKILL documents the translation.

**Authoring costs nothing extra.** `edit_plan.window_to_episode` already splats
`**editorial` into `EDLEpisode`, so `ramp` is writable straight from
`selection.json` the moment the field exists.

---

## 9. What is NOT ported from the parked branch

- **`apply_zoom` / `validate_zoom` / `ZOOM_MIN` / `ZOOM_MAX`** — superseded by
  #17 (2026-08-08). That slice's zoom rides the tracked route through the same
  composition rule as any crop, so `check_episode` judges it in full; the parked
  version was a separate blind centre-crop encode at extract time, outside every
  check. Its disparaging `zoompan` comment is unmeasured and contradicted by the
  landed proof.
- **`highlight_red`** — a real gap, but backlog #18's colour item, not this
  slice's. It needs its own visibility proof.
- **`EDLEpisode.smooth_window_s`** — `ReframeSpec.smooth_window_s` landed with
  path-quality (2026-07-28); the EDL cannot author it. A genuine one-field
  authoring hole, but unrelated to length; separate slice.
- **`draft.py`'s `Delivery.from_spec(...).dims(...)` fix** — a correct fix (the
  canvas is an aspect, delivery sets the pixels) but independent of the ramp;
  it should land on its own evidence, not smuggled in here.

---

## 10. New landmines for the §12 registry

1. **A filtergraph value containing a comma must be single-quoted inside the
   `-vf` string.** In argv form there is no shell to strip quotes, and ffmpeg's
   own parser treats a bare comma as a filter separator: the knot expression's
   first `if(lt(T,…))` splits the chain and ffmpeg reports `No such filter:
   '0.125000)'`. Measured while building this design.
2. **`setpts` remaps timestamps; it does not resample.** Without a following
   `fps=`, the output is a variable-frame-rate stream that concat and the
   uniformity check will not accept. The pair is mandatory.

**Already in the registry, re-confirmed here:** `drawbox`'s `x`/`y` are inert —
`tests/conftest.py` records that on the baseline ffmpeg the `t` variable reads as
INT32_MAX, so a `t`-dependent box never appears at all. The measurement work for
this design walked into it again before finding that note. `overlay`'s position
expressions DO evaluate per frame, which is how the existing `sample_clip`
fixture moves anything.

---

## 11. Proofs

**The proofs need their own fixture.** The shared `sample_clip` is 30 fps, and
§5's `MIN_RAMP_FPS = 24.0` therefore admits only `factor ≥ 0.8` on it — a 1.25×
slowdown, too shallow to separate from measurement noise. The ramp tests build a
small **60 fps** clip (a box moved by `overlay`, per the landmine above), where
`factor = 0.4` is legal and the effect is unambiguous. This is a constraint the
judder gate imposes on its own test suite, and it is worth stating rather than
discovering.

- **Length.** A real-ffmpeg render of the reference spec lands within one frame
  of `play_dur()`, and `play_dur()` is computed from the same knots the filter
  used.
- **Visibility — backlog #18's demand.** Mean `|frame − prev|` over decoded gray
  frames, the way `lib/anchors` already measures motion. Measured on the shipped
  fixture (`at=1.0, factor=0.4, ease=0.25, hold=0.5` on the 60fps `ramp_clip`,
  `tests/integration/test_ramp.py::test_the_ramp_actually_slows_the_picture`):
  normal band 0.657, plateau band 0.257, **ratio 0.391 against a `factor` of
  0.40**. The residual is the ease shoulders bleeding into the measured band
  plus frame-duplication quantization. The test asserts the ratio tracks
  `factor`, not that the argv looked correct.
- **Length propagation.** An end-to-end SP3→SP1 run with a ramped episode:
  `PACING.md` fits the grid to the played lengths, and the reel's measured
  duration matches the EDL's `play_dur()` sum.
- **The judder refusal** fires on a 30fps clip at `factor` 0.5 and names 0.8 as
  the maximum that clip supports.
- **Unramped byte-identity.** An episode with `ramp: null` must produce the same
  argv and the same segment bytes as before this slice — the golden fixtures
  depend on it.

---

## 12. Honest limits

**Slowing duplicates frames; it does not create them.** `MIN_RAMP_FPS` refuses
the cases where duplication becomes visible stutter, but nothing here recovers
detail that was never shot. A 24 fps plateau from a 60 fps source is the ceiling
of this design, not a floor it improves on.

**A ramped segment loses its natural sound.** Slowed audio is pitch garbage, so
the pre-stage drops it. `mix._build_ambient` already substitutes `anullsrc`
silence sized to the episode's length, so the ambient bed stays in sync by
construction — but that episode contributes silence. Recorded in
`processing_notes`, not left to be discovered.

**Record and render differ by under one frame.** `fps=` cannot emit a fraction of
a frame, so a `play_dur()` of 6.0811s at 30fps renders as 182 frames = 6.0667s.
That is the entire discrepancy — the knot expression itself contributes nothing
measurable (§3.2). Three orders of magnitude under the length gate's ±0.5s band,
but the EDL's number is not bit-exact against the file.

**The ramp costs a second encode generation.** crf 8 keeps it near-lossless for
the tight-crop case that motivated it (§3.5), but it is still a re-encode that a
non-ramped episode does not pay.

**`ramp.retime` writes with no post-condition.** Unlike `vidstab.stabilize`,
which probes its own output and refuses a geometry change or a duration drift
past 2 frames, `ramp.retime` verifies nothing about what it wrote. A wrong
retime — a knot bug, an fps mismatch, a bad expression — surfaces only
downstream, at `check_reel`'s ±0.5s reel-length gate, and is then attributed to
the REEL rather than to the episode that actually caused it. Not implemented
here: a probe-and-refuse post-condition is new behaviour and needs its own
evidence, the way vidstab's did — recorded as a gap, not fixed as a
side-effect of a review.

**`MIN_RAMP_FPS = 24.0` is a convention, not a measurement.** It is the film
frame rate, chosen because it is the standard below which duplication reads as
stutter — not calibrated against this engine's footage. It is the one constant
here most likely to want revisiting.

**The hand-authored front door still bypasses the early gate.** An `EDL.json`
driven straight through `edl_to_reel`'s SP1 door never sees `edit_plan`'s judder
check — only the extract pre-stage's. That is one gate rather than two, which is
the same shape #17 and #14 recorded: no *silent* bypass, not no bypass.

**The gate proves the premise, never the taste.** Nothing here judges whether
this was the right moment to slow down. It proves the ramp is renderable, that
the length it claims is the length it plays, and that the slowdown is visible in
pixels.

---

## 13. Deferred

- **`minterpolate` interpolated slow-mo** (§5) — real intermediate frames instead
  of duplicates. Needs its own artefact study on water and spray before it is
  offered.
- **Speed-UP** (`factor > 1`). The whole design rests on `s ≤ 1` meaning frames
  are only duplicated, never dropped; a speed-up drops motion and needs a
  different argument about what is lost.
- **A ramp spanning more than one plateau** — two slow moments in one shot. The
  contract admits one region by construction.
- **Auto-placing `at` from the action anchors** `lib/anchors` already computes.
  Tempting, and exactly the kind of guess #12 says to stop making without
  looking; it needs the QC judge's eyes, not a heuristic.

  > **Measured 2026-08-18 — not buildable on this sensor, and the wariness above was
  > right for a sharper reason than it knew.** The anchors do not carry the
  > information. `measure_curve` is *global* frame-to-frame difference, so on a moving
  > camera the camera's own motion is the signal and it is roughly constant: across the
  > 2026-08-03 run's eight episodes, **seven have 100% of their samples above
  > `ANCHOR_REL * peak`** (peak/min 1.23–1.64). The relative floor selects nothing, and
  > what `anchors_from_curve` returned was its `min_gap` thinning grid.
  >
  > On ep5 — **the one episode of that run that actually carries a ramp**
  > (`MVI_3998`, `at: 3.42`) — the finder returned five "anchors" in seven seconds
  > (1.0/2.0/3.0/4.0/5.33), four of them inside the legal enclosure band. The nearest
  > is 0.42s from the human's choice, which reads as agreement and is not: at that
  > density **every** point in the band is within ~0.5s of one. The metric cannot fail,
  > so it measures nothing.
  >
  > The slice built the honesty instead: `anchors.curve_contrast` + `ANCHOR_FLAT_FRAC`,
  > and `PACING.md` now says *"flat — no moment is distinguishable"* where it used to
  > list those five as advice. Auto-placement needs a sensor that separates subject from
  > camera motion (`carve.track_displacements`, or a vidstab-subtracted curve) — filed.
  > See `docs/specs/2026-08-18-deferred-measurements-design.md` §4.
