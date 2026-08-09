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
seven readers.

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

### 3.2 The knot count is measured, not guessed

Reconstruction error of the piecewise-linear `O` against a 4000-step integral,
for the reference spec `{at: 2.0, factor: 0.4, ease: 0.5, hold: 1.0}` over a 4.0s
window at 30fps (analytic `out_dur` 6.0811s, extra 2.0811s):

| knots | worst \|O_lin − O_exact\| | in frames @30 | expression length |
|------:|--------------------------:|--------------:|------------------:|
| 8     | 169.86 ms                 | 5.096         | 408 chars         |
| 16    | 51.94 ms                  | 1.558         | 808 chars         |
| **32**| **16.14 ms**              | **0.484**     | **1608 chars**    |
| 64    | 6.23 ms                   | 0.187         | 3208 chars        |

`RAMP_KNOTS = 32` — the first row under half a frame. 64 halves the error again
but doubles an already long `-vf` argument for a residual that `fps=`'s own frame
quantization swallows.

Rendered with 32 knots, real ffmpeg produced **6.067s against the analytic
6.081s** — 0.43 frames, entirely accounted for by the 0.484-frame knot
approximation above. The error is understood, not merely small.

### 3.3 Record and render read the SAME knots

`play_dur()` must not integrate finely while the render approximates coarsely:
that would put a ~16 ms lie in every EDL. One `knots()` function serves both —
`ramp_extra` reads its last value, the filter expression reads all of them. Record
and render then agree by construction. This is the "record, don't re-derive"
principle the zoom slice established for `PathMeta.crop_ws`.

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

## 6. The seven places length leaks

| # | site | reads today | must read |
|---|------|-------------|-----------|
| 1 | `pacing.build_pacing` (`pacing.py:74`) | `[ep.dur …]` | `[ep.play_dur() …]` |
| 2 | `pacing._bounds` (`pacing.py:35`) | `room − ep.dur` | unchanged for the tail, plus the §2 shrink floor |
| 3 | `edit_plan._bind_pacing` guard (`edit_plan.py:201`) | `abs(slot.dur − ep.dur)` | `abs(slot.dur − ep.play_dur())` |
| 4 | `edit_plan._bind_pacing` assign (`edit_plan.py:207`) | `dur = slot.dur` | `dur = slot.dur − ramp_extra` |
| 5 | `edit_plan._back_edge_target` (`edit_plan.py:230`) | `sum(e.dur)` | `sum(e.play_dur())` |
| 6 | `edl.to_manifest_dict` (`edl.py:341`) | `ep.dur` | `ep.play_dur()` |
| 7 | `edl_to_reel` reel target (`edl_to_reel.py:144`) | `sum(ep.dur)` | `sum(ep.play_dur())` |

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
2. **`drawbox`'s `x`/`y` do not re-evaluate per frame** on the baseline ffmpeg
   (there is no `eval` option to enable it), so a `t`-dependent box silently
   renders nothing at all — not a box at t=0, *nothing*. Only relevant to test
   fixtures, but it cost a debugging round here and will cost one again.
3. **`setpts` remaps timestamps; it does not resample.** Without a following
   `fps=`, the output is a variable-frame-rate stream that concat and the
   uniformity check will not accept. The pair is mandatory.

---

## 11. Proofs

- **Length.** A real-ffmpeg render of the reference spec lands within one frame
  of `play_dur()`, and `play_dur()` is computed from the same knots the filter
  used.
- **Visibility — backlog #18's demand.** Mean `|frame − prev|` over decoded gray
  frames, the way `lib/anchors` already measures motion. Measured on the
  reference spec: normal band 3.275, plateau band 1.483, **ratio 0.453 against a
  `factor` of 0.40**. The residual is the ease shoulders bleeding into the
  measured band plus frame-duplication quantization. The test asserts the ratio
  tracks `factor`, not that the argv looked correct.
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

**Record and render can differ by up to one frame.** `fps=` quantizes; the knot
expression carries a further 0.484-frame worst-case error at `RAMP_KNOTS = 32`.
Both are below the length gate's ±0.5s band by three orders of magnitude, but the
EDL's number is not bit-exact against the file.

**The ramp costs a second encode generation.** crf 8 keeps it near-lossless for
the tight-crop case that motivated it (§3.5), but it is still a re-encode that a
non-ramped episode does not pay.

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
