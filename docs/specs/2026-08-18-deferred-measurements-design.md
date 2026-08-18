# Three deferred measurements — the outro floor, layer 3, and the conductor's residual

**Date:** 2026-08-18 · **Status:** design · **Size:** M

## 0. Why this slice exists

Three P2 backlog rows, unrelated in subject, identical in shape: each parks a
number or a mechanism with the note "nobody measured this". None of the three
needs the real footage run the project owner has deferred — the track, the routes
and the source frames from the one real run are all already on disk.

| row | asked | answered by |
|---|---|---|
| Validate `outro.TAIL_MIN` against editing practice | is 0.5s right? | the run's own track, through the shipped sensor |
| Re-assess §6.1a layer 3 against track-stitch | is there a real remainder? | the run's seven `route.json` + `route.meta.json` |
| Diagnose the conductor's 6.5–11.5-unit residual | which of three candidates? | a four-way separation over two real source frames |

**Two of the three overturned the question they were asked.** `TAIL_MIN` is not
mis-tuned, it is wrong in kind. The conductor's residual is not one of the three
candidates the row named — all three are eliminated by measurement, and the cause
is a fourth nobody had listed. Only layer 3 came back with the answer its row
expected, and even there the evidence points the opposite way from the framing.

---

## 1. `outro.TAIL_MIN` — a floor on audio the reel never plays

### 1.1 Where it binds at all

`fit_outro`'s gap rung requires `free_after(line) >= need`, with

```python
need = max(TAIL_MIN, float(fade))
```

so `TAIL_MIN = 0.5` decides nothing unless the resolved fade is under 0.5s. Every
fade the pipeline can produce:

| path | fade | binds |
|---|---|---|
| `fun` preset | 0.3 | **TAIL_MIN** |
| `epic` / `nostalgic` | 0.8 | fade |
| `moody` | 1.0 | fade |
| no look authored (`_MIX_DEFAULT_FADE`) | 0.5 | tie — indistinguishable |
| an authored `look.fade: 0` | 0.0 | **TAIL_MIN** |

Two of five, a tie in a third, dead in the rest.

### 1.2 What it constrains

The reel is `line + fade` seconds long and `mix` fades over `[line, line + fade]`.
Nothing past `line + fade` is ever rendered. `need = max(TAIL_MIN, fade)` with
`fade < 0.5` therefore demands vocal-free space in a region **the listener cannot
hear** — the span from `line + fade` to `line + 0.5` is not in the stem.

The audible requirement is exactly `free_after(line) >= fade`: no singing under the
fade. That is arithmetic, not taste, and it needs no citation.

### 1.3 The inversion, measured

The extra floor does not merely over-constrain. When it bites, the ladder's next
rung is strictly worse *against the very thing the floor protects*. One bar line, a
vocal-free span of 0.35s after it, the `fun` preset's 0.3s fade:

| rule | rung | reel | fade | singing under the fade |
|---|---|---|---|---|
| `max(TAIL_MIN, fade)` | no-gap | 31.50 | 1.50 | **1.15s** |
| `fade` alone | gap | 30.30 | 0.30 | **0.00s** |

The 0.3s fade sits entirely inside the gap. `TAIL_MIN` rejects it and takes a 1.5s
fade that covers 1.15s of vocals, because the `no-gap` rung does not check the tail
at all.

### 1.4 It disagrees with the sensor that defines a gap

`offset.vocal_gaps(min_gap=0.35)` drops any below-threshold run shorter than 0.35s
as a between-words dip. Every span in `MusicSpec.vocal_spans` is therefore ≥ 0.35s
**by construction** — and `TAIL_MIN = 0.5` disqualifies the whole 0.35–0.5s band
outright, wherever the line falls in it. Two constants in two modules disagreeing
about what a vocal-free space is.

On the real run's own track (Walking on Sunshine, 228s, through the shipped
demucs → `vocal_gaps` path): **25 gaps, 4 of them (16%) in that band.**

```
min=0.372  p25=0.650  median=1.068  max=9.752
[0.35, 0.5)   4  (16.0%)      [0.5, 1.0)  8  (32.0%)      >= 1.0  13  (52.0%)
```

Counted as landing zone — seconds of the track where a bar line is a legal outro:

| path | fade | legal @ `fade` | legal @ `max(0.5, fade)` | lost |
|---|---|---|---|---|
| `fun` | 0.3 | 44.88s | 40.26s | **10.3%** |
| authored 0 | 0.0 | 52.38s | 40.26s | **23.1%** |
| no-look default | 0.5 | 40.26s | 40.26s | 0% |
| `epic`/`nostalgic` | 0.8 | 34.74s | 34.74s | 0% |
| `moody` | 1.0 | 32.05s | 32.05s | 0% |

### 1.5 What replaces it

`TAIL_MIN` is deleted. `need` becomes

```python
need = float(fade) + TAIL_MARGIN
```

with `TAIL_MARGIN = 0.05` — **two bins of the vocal envelope** at
`vocals._SPAN_HZ = 40.0` (~23 ms each). Not taste: it is the sensor's own boundary
quantization, and it is the only number here that is not either audible or derived.
The two jobs it does:

- **at any fade** — the fade gets a margin against the gap boundary's ±1-bin error;
- **at `fade == 0`** — it is the only thing keeping the line out of a vocal. With
  `need = 0`, `free_after(line) >= -_EPS` is true even when `free_after` returns
  `0.0` for a line *outside every gap*, and the music would stop dead mid-word.
  `need > 0` forces the line inside a gap. This is why the replacement is
  `fade + TAIL_MARGIN` and not `max(fade, TAIL_MARGIN)`: at fade 0 the two agree,
  but only the sum gives a positive fade a margin too.

Re-measured on the same track:

| path | fade | now | proposed | change |
|---|---|---|---|---|
| `fun` | 0.3 | 40.26s | 43.63s | **+3.38s** |
| authored 0 | 0.0 | 40.26s | 51.13s | **+10.88s** |
| no-look default | 0.5 | 40.26s | 39.25s | −1.01s |
| `epic`/`nostalgic` | 0.8 | 34.74s | 34.03s | −0.71s |
| `moody` | 1.0 | 32.05s | 31.40s | −0.65s |

The three fade-dominated paths pay ~0.7–1.0s for a margin they never had. The two
the old floor was actively hurting get their landing zone back.

### 1.6 `OutroFit.need` — the message was already wrong

`EDL.to_markdown`'s no-gap sentence quotes `outro_mod.TAIL_MIN` as the amount that
was not available. Under `max(TAIL_MIN, fade)` that was **already inaccurate** for
three of five paths — `moody` needed 1.00s and the artifact said 0.50s. After this
change the required amount depends on the original fade, which the no-gap rung does
not carry (`o.fade` is `NO_GAP_FADE` by then).

So `OutroFit` gains `need: float` — the vocal-free seconds the gap rung asked for.
Provenance beside `tail`, additive on the wire (`from_dict` defaults it), and it
makes the sentence exact on every rung instead of quoting a module constant that
may not be the number that applied.

---

## 2. §6.1a layer 3 vs track-stitch — the remainder is real, the evidence is not

### 2.1 They point in opposite directions

- **`track.stitch_ids`** — the tracker CORRECTLY opened a new id after an occlusion.
  One person, two ids. Stitch **joins** them.
- **§6.1a layer 3** — the tracker INCORRECTLY kept one id across two people (a MOT
  "ID switch"). Two people, one id. Layer 3 **splits** and re-matches.

Neither can subsume the other; they are inverse operations. The row's question
("does a real remainder exist") answers **yes**.

### 2.2 What is already built of layer 3

Layer 3 is detection + repair. The detection's geometric half already ships:
`checks.continuity` flags a per-frame |Δx| above `4% of src_w`, `check_episode`
runs it, and it sits in `orchestration._UNFIXABLE` so a hit stops and reports. The
descriptor and area corroboration the design asks for, and the automatic
split-and-re-match repair, are the actual remainder.

### 2.3 The evidence says do not build it yet

Every route the real run produced, re-measured:

| ep | frames | worst \|Δx\| | cap | headroom | stitched |
|---|---|---|---|---|---|
| ep0 | 282 | 7.8 | 153.6 | 19.6× | `[]` |
| ep1 | 130 | 13.9 | 76.8 | 5.5× | `[]` |
| ep2 | 197 | 7.8 | 76.8 | 9.8× | `[]` |
| ep3 | 165 | 12.7 | 76.8 | 6.1× | `[]` |
| ep4 | 262 | 6.8 | 76.8 | 11.2× | `[]` |
| ep6 | 227 | 8.0 | 76.8 | 9.6× | `[]` |
| ep7 | 255 | 5.9 | 76.8 | 13.0× | `[]` |

(ep5 is a pan — `not-checked`, no tracked subject.) Zero continuity failures, zero
stitches, and the closest any route came to the gate was 5.5×.

More to the point, the failure mode needs **two comparable people in one shot**, and
the run barely offered one. Per-episode `route.meta.json` features, largest
non-hero track by mean area against the hero's:

| ep | hero area | next largest | ratio | that track's frames |
|---|---|---|---|---|
| ep0 | 35 129 | 898 | 2.6% | 4 of 282 |
| ep1 | 46 712 | 26 976 | 58% | **2** of 130 |
| ep2 | 41 470 | — | single track | — |
| ep3 | 62 938 | 46 969 (border 1.0) | **75%** | 53 of 165 |
| ep4 | 25 781 | 4 917 | 19% | 28 of 262 |
| ep6 | 26 313 | 8 250 | 31% | 39 of 227 |
| ep7 | 17 270 | 3 377 | 20% | 51 of 255 |

The frame column is what makes the ratio readable: ep1's 58% is a **two-frame**
detection, not a co-present person. **ep3 is the only genuine opportunity for a
two-people-one-id swap on the whole shoot — a second body at 75% of the hero's area
for a third of the episode — and that body is pinned to the frame edge for every
one of its 53 frames (`border: 1.0`).** It did not swap.

### 2.4 What the gate can and cannot see

`4% of src_w` is a *physically impossible teleport* gate, not an ID-switch gate. On
the run's footage (96 clips at 1920×1080@60, 3 at 3840×2160@60) that cap is 4603
and 9207 px/s — the subject crossing the frame in 0.42s. An ID switch between two
people fires it only when they are **more than 4% of the frame apart** at the swap
moment; a swap between two adjacent people is invisible to it. That is a real hole
in the shipped detector, and it is the honest reason "zero failures" is weaker
evidence than it looks.

### 2.5 The decision

Do not build. Close the row with the evidence and a **named trigger**: build layer 3
when a real run produces either a `continuity` stop or an episode-QC `hero` finding
that names a mid-episode swap. Both already exist as signals — the QC judge's fifth
axis is `hero` — so the trigger costs nothing to wait for.

---

## 3. The conductor's residual — one cause, and it is not on the row's list

### 3.1 What the row listed

mood-grade §3 measured the conductor landing 6.5–11.5 luma units from the target it
authored, and named three candidates: **the spline fitted through `TONE_SAMPLES`,
the encode, the measurement itself.** None had been separated.

### 3.2 The separation

One frame from each of the run's two cameras, decoded to lossless FFV1 so nothing
downstream is the encode's fault, then the shipped `color.tone_arg` curve applied
and re-measured. Target `(50, 100, 195)` throughout.

**The spline — eliminated.** A 256-code grayscale ramp through the same curve, read
back per column:

```
DJI    T( 73.0) ->  50.0   asked  50.0   error +0.0
       T(137.0) -> 100.0   asked 100.0   error +0.0
       T(196.0) -> 195.0   asked 195.0   error +0.0
Canon  T( 49.0) ->  50.0 / T(110.0) -> 100.0 / T(188.0) -> 194.0   (worst −1.0)
```

`TONE_SAMPLES = 13` plus the anchors leaves the fitted spline no room to wander.
The comment claiming so is correct, and now has a number.

**The encode — eliminated.** Same frame, same curve, lossless vs h264 crf 18:
worst per-anchor difference **2 units**.

**The measurement's downscale — real, but not the residual.** `measure_profile`
renders `scale=160:-2,format=gray`, so it histograms a 160-wide frame. On the drone
frame that costs **9 units at p95** (native 205, @160 196); on the Canon frame, 1.
It is a genuine bias — but removing it makes the delivered error *worse*, not
better (see §3.4).

**The cause — `curves=all` is a per-CHANNEL transfer and the target is a LUMA
statistic.** For a non-affine `T`, `luma(T(R), T(G), T(B)) ≠ T(luma(R, G, B))`;
Jensen's inequality, and the gap grows with channel spread. The control is the whole
proof — the same frame, the same curve builder, the same measurement, differing
only in whether the three channels carry different values:

| source | delivered (p5, p50, p95) | error |
|---|---|---|
| DJI, colour | (50, 105, 188) | [0, **+5**, **−7**] |
| DJI, grayscale (R=G=B) | (50, 100, 195) | **[0, 0, 0]** |
| Canon, colour | (50, 101, 192) | [0, +1, −3] |
| Canon, grayscale | (50, 100, 194) | [0, 0, −1] |

Anchors measured natively on each file, verdict measured natively. **Exactly zero
on all three anchors** once the channels agree.

### 3.3 The residual is content, not a system constant

DJI [0, +5, −7] against Canon [0, +1, −3], same code path. mood-grade §3's
"6.5–11.5" is the drone's channel spread — a small blazing specular patch on dark
water — seen through a 160-wide ruler. On evenly-lit footage the same conductor
lands inside 3 units.

### 3.4 The trap: the two biases partially cancel today

The obvious fix — drop the 160-wide downscale so the anchors describe the pixels
the curve actually transforms — makes the delivered p95 **worse**:

| anchors from | delivered native p95 error (DJI) |
|---|---|
| `@160` (as shipped) | **−1** |
| native | **−7** |

Measuring at 160 reads the drone's p95 nine units low, so the authored curve maps
`196 → 195` and the real p95 pixel (205) lands at ~198 — over-shooting by about as
much as the channel effect under-shoots. The two errors are independent and happen
to be opposite in sign on this footage. **Anyone "fixing" the measurement in
isolation would make the conductor less accurate and have no way to know why.**
That is the finding this section exists to record.

### 3.5 What this slice does about it

Nothing to the code. The fix is a luma-only transfer (`curves` is RGB-only; the
route would be a `lutyuv` on the Y plane), and it is **not a free swap** — a
per-channel curve on a lift also raises saturation, so luma-only ships a visibly
different grade. That is a taste decision with its own design, not a chore. This
slice records the diagnosis, corrects mood-grade §3's reasoning, and files two
backlog rows (§6).

`MoodPreset.tone_bias`'s 15–20-unit vectors stay as they are: they were sized
against the worst case, and the worst case is unchanged.

---

## 4. What this slice builds

1. `outro.TAIL_MARGIN` replaces `TAIL_MIN`; `need = fade + TAIL_MARGIN`.
2. `OutroFit.need` carries the requirement; `EDL.to_markdown` quotes it instead of a
   module constant.
3. A machine-checked pin that `TAIL_MARGIN == 2.0 / vocals._SPAN_HZ`, so the margin
   and the sensor it is derived from cannot drift apart silently.
4. `check_reel`'s "inventing `TAIL_MIN` a second time" comment loses its example —
   `TAIL_MIN` is measured now, and the comment's point (`_LENGTH_TOL` is a borrowed
   reporting boundary, not a measured one) survives without it.
5. Docs: mood-grade §3's correction, cast-hero-pin §11's layer-3 disposition,
   backlog rows closed and opened, build-status.

No change to `match_grade`, `color`, `check_episode`, `track`, or `checks`.

## 5. Testing

- The inversion of §1.3 becomes a regression pin: fade 0.3, tail 0.35 → **gap**, and
  the delivered fade covers no singing.
- `test_gap_rung_needs_tail_min_not_just_the_fade` is **rewritten, not deleted** —
  its job (discriminate the floor from a bare `need = fade`) still exists, at the
  new scale: fade 0.0 with a 0.02s tail must refuse, with 0.06s must accept.
- `test_fade_zero_needs_only_tail_min` keeps its name's intent: at fade 0 the margin
  alone is the bar. Its 0.6s tail still clears it.
- The `_EPS`-boundary test stays exactly as it is — it pins the `>=`/`>` operator,
  not the constant, and it constructs its tie from `need` rather than `0.5`.
- `EDL.to_markdown`'s no-gap sentence asserts `o.need`, not `outro_mod.TAIL_MIN`.
- A mutation battery over the new expression (§7 of the plan).

## 6. Deferred → backlog rows

- **Decide whether the tone transfer should be luma-only** (P3, M) — the fix §3.5
  identifies. Carries a taste trade-off (`curves` per-channel raises saturation on a
  lift, `lutyuv` on Y does not), needs its own design, and `lutyuv` needs a landmine
  assessment of its own — `lutrgb` is already banned in this repo for producing
  black frames.
- **`measure_profile` histograms a 160-wide frame** (P3, S) — a 9-unit p95 bias on
  specular footage that currently masks part of §3's channel error. Must **not** be
  changed alone; it is entangled with the row above and §3.4 says why.
- **Build §6.1a layer 3 when a run trips its trigger** (P4) — §2.5's named
  condition, replacing the open re-assessment row.
- **`checks.continuity` cannot see a swap between adjacent people** (P4, S) — §2.4.
  The gate is a teleport gate; nothing claims otherwise in code, and now nothing
  claims otherwise in the docs either.

## 7. Honest limits

- **§1's landing-zone table is one track.** Walking on Sunshine, one tempo, one
  genre — the same single-song basis the downbeat-confidence slice already flagged.
  The *inversion* in §1.3 is structural and holds on any track; the *percentages*
  are this song's.
- **`TAIL_MARGIN = 0.05` is derived, not validated.** Two envelope bins is a
  quantization argument, not a listening test. Nobody has heard a fade land 23 ms
  inside a vocal and judged it.
- **§2's evidence is one shoot of predominantly single-subject footage.** "Zero ID
  switches" over seven episodes with one real two-person opportunity is weak
  evidence of absence, and §2.4 names the blind spot that makes it weaker.
- **§3's separation is two frames, one per camera, at t=1.0s.** The mechanism is
  exact (the grayscale control is zero by construction, not by luck), but the
  *magnitudes* are two frames' worth.
- **Nothing here makes a reel better.** One rung of one fitter reaches more bar
  lines; two open questions become one answered question and four narrower rows.
