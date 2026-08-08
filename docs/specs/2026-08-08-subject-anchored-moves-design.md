# Subject-anchored frame moves — design

**Status:** design approved 2026-08-08. Closes fixes-backlog #17 (and the
frame-moving half of #18); the first slice of playbook priority 4, "cinematic
effects done right".

**Scope:** one rule, two applications — a `zoom` that rides the tracked route
and therefore stays inside every check, and a `pan` that may no longer be
authored over a shot the intake measured as holding people.

---

## 0. What the run showed

The 2026-08-03 montage run shipped ep5 as a `pan`, and its `report.json` reads:

- `framing`: `{"status": "editorial-only", "reason": "generated path — no tracked subject"}`
- `continuity`: `{"status": "not-checked", "reason": "generated path — no tracked subject"}`
- `color_fidelity`: `{"status": "not-checked", "reason": "no source clip or no tracked subject"}`

Three of `check_episode`'s checks reported nothing at all, and the episode
passed. Each of those three arms is individually correct — you cannot judge
composition against a subject you never observed, and `checks.continuity([])`
returns `pass=True` through a `zip` that never iterates, so the absence had to
be *stated* or it would have read as a green tick (design 2026-07-19 §2.1).

The defect is not in the arms. It is that **nothing ever established the
premise they rest on.** `pan` asserts "there is no tracked subject", and the
engine accepted that assertion from the author, about a shot with a surfer in
it. A field that turns off three checks, believed on the author's word, is an
escape hatch — which is exactly the shape governance #8 spent a slice closing
everywhere else.

Backlog #17 states the rule the run wanted: a zoom and a pan *must not be blind
route-less crop animations — when there is a hero they must be anchored to the
tracked route and keep the subject composed by the picture rules throughout the
move.* Route-less generation stays legitimate for pure scenery.

---

## 1. The rule

A frame move is one of exactly two things:

1. **Subject-anchored.** Its geometry is a function of the REAL tracked route.
   Every check applies unchanged — there is a subject, it was observed, and the
   move can be judged against it.
2. **Scenery.** Its geometry is generated. There is no subject — and that must
   be **established by measurement**, never accepted as a claim.

There is no third kind. A move that changes the frame while a subject is
present, without reading that subject, is the thing this design removes.

### 1.1 Why this does not contradict the pan design

The pan design (2026-07-19 §6.1) refused to write a `route.json` under a pan,
and refused to let `check_episode` judge composition against one, with this
argument: *"Judging composition here would compare the crop against a subject
derived from that same crop."*

That argument is about a **synthesized** route — one derived from the generated
path. It is untouched here, and nothing in this design synthesizes a route.

A **tracked** route is an independent observation: YOLO measured where a person
was, without reference to any crop. Judging a crop against it is not circular,
which is why every non-pan episode has been judged that way since the engine
existed. So "anchor the move to the tracked route" is not a reversal of the pan
design — it is the branch the pan design already had, reached by a move that
previously refused to enter it.

---

## 2. Half A — `pan` stops being an escape hatch

### 2.1 The gate is measured, not declared

`FootageWindow.present` already exists: the fraction of a window's samples that
held at least one person, written by intake's YOLO pass. It costs nothing to
read and it is not the author's claim.

**`edit_plan.window_to_episode` refuses a `pan` when `window.present >
PAN_PRESENCE_MAX`.** That function is the right site because it is the only
place that holds both the requested editorial fields and the measured window;
`EDLEpisode` alone cannot see the footage, and `manifest.validate` is one layer
further from it still.

```python
PAN_PRESENCE_MAX = 0.10   # a person in <=10% of a window's samples is incidental,
                          # not the shot's subject. FIRST CUT — see §10.
```

### 2.2 The declared gate, for the door with no footage

A hand-authored `EDL.json` driven through `edl_to_reel` never sees
`FOOTAGE.json`. That door keeps the weaker check that needs no footage:
**`pan` together with a hero pin or a cast name is refused** — in
`manifest.validate` (which already validates `hero`/`cast`) and in
`edl.preflight`. Pinning a hero and then declaring there is no subject is a
self-contradiction readable from the EDL alone.

This does not close the hand-authored door completely; §10 records what it
leaves open.

### 2.3 The span-merge presence bug, found while reading for this

`edit_plan._merge_windows` builds a merged window with
`dataclasses.replace(clip.windows[i], start=..., dur=..., track_ids=tids)` —
it unions `track_ids` across the range but inherits **window i's** `present`.
A span whose first window is empty and whose later windows are full of people
would therefore report the first window's presence, and pass the §2.1 gate.

Fix: `present = max(w.present for w in wins)`, alongside the existing
`track_ids` union. Not a new feature — the same aggregation the merge already
performs for the other measured field, applied to the one it forgot.

### 2.4 What the check arms become

The three arms in `check_episode` stay exactly as they are. What changes is
that they are now only reachable on a shot the engine has measured to be
subject-less. Their `reason` strings stop being an unverified premise and start
being a consequence. The comments that explain them are updated to say so.

---

## 3. Half B — `zoom`

### 3.1 The contract

```python
@dataclass
class ZoomSpec:
    """A subject-anchored push-in / pull-out (design 2026-08-08).

    `start`/`end` are fractions of the layout's crop WIDTH: 1.0 is the crop the
    layout resolved, 0.7 is a 1.43x push-in. Direction is the sign of
    `end - start` — no direction vocabulary, for the same reason PanSpec has
    none (a second spelling of what the numbers already say).

    Both ends are in (0, 1]: above 1.0 the crop would need pixels the layout's
    rect does not contain, and the base crop would have to grow — which would
    silently change the composition the layout resolved.

    WIRE NAMES `from`/`to`, exactly as PanSpec, and for the same reason: `from`
    is a Python keyword. `from_dict`/`to_dict` carry the mapping.
    """
    start: float
    end: float
```

Fractions of the crop width, not of the source width, for the same reason
`PanSpec` measures freedom rather than source width: the layout's crop is what
actually exists to zoom inside, and it is already the number the layouts model
reasons in.

### 3.2 Where the geometry comes from

The composition rule is unchanged. At each route sample the crop's left edge is
chosen by the same `geometry.crop_x` against the same grid line — only the
width it is given changes. The subject therefore sits on its composition line
at every instant of the move, which is precisely what #17 asks for and what
makes the move checkable.

Concretely, per route sample `i` over the route's own time span `[t0, t1]`:

```
s(t)  = start + (end - start) * (t - t0) / (t1 - t0)     # linear in time
z(t)  = 1 / s(t)                                         # what ffmpeg is given
w_i   = int(W0 / z_i)                                    # what ffmpeg will cut
h_i   = int(H0 / z_i)
```

`w_i` is defined **from `z`**, not from `s`, so the recorded rect is the rect
ffmpeg's own `iw/z` produces rather than a parallel computation that could
disagree with it. §10 records the residual.

`W0`/`H0` are the layout's resolved crop (`ResolvedLayout.crop_w/crop_h`) and
`cy` the base crop's y, all three unchanged from today: with both ends of the
zoom at or below 1.0, the layout's crop **is** the widest rect the move ever
needs, so the `crop` filter keeps the same size and the same constant `y` it
already has. Only its `x` expression is derived differently (§3.3), and only
under a zoom.

### 3.3 The render chain

`crop`'s `w`/`h` cannot vary with time. Measured, not assumed:

```
$ ffmpeg -f lavfi -i testsrc2=... -vf "crop=w='320+100*t':h=240:x=0:y=0" -f null -
[Parsed_crop_0] Error when evaluating the expression '320+100*t'
[Parsed_crop_0] Failed to configure input pad on Parsed_crop_0
```

It fails loud, which is the good case. The time-varying rect therefore comes
from `zoompan`, inserted between the existing `crop` and the existing `scale`:

```
crop=W0:H0:x='A(t)':y=cy,
zoompan=z='Z(it)':x='XX(it)':y='YY(it)':d=1:s=W0xH0:fps=<source fps>,
scale=...                                   # unchanged
```

with

```
A_i  = clamp(x_i + w_i/2 - W0/2, 0, src_w - W0)    # base crop follows the rect's centre
XX_i = x_i  - A_i                                   # offsets into the base crop
YY_i = cy_i - cy
cy_i = clamp(round(centre_y - h_i/2), 0, src_h - h_i),  centre_y = cy + H0/2
```

`A`, `XX` and `YY` are pixel series and are emitted through the existing
`_xexpr` piecewise-linear knot builder, which gains a variable-name parameter so
the `crop` argument keeps `t` while the `zoompan` arguments get `it`. Their
knot simplification is the one `reframe` already applies to the crop path, so
`A` and `XX` each stay within the builder's epsilon of their sampled series and
their sum stays within twice it of the intended left edge — the same order of
error the crop path has carried since the engine existed.

**`Z` is emitted in closed form**, `1/(s0 + k*(it - t0))`, and not through the
knot builder. Two reasons, both disqualifying: `_xexpr` formats knots at `.1f`,
which would quantize a 1.4286 zoom to 1.4 and put the recorded `crop_ws` some
30px away from the rendered rect; and `z = 1/s` is hyperbolic, so a two-knot
linear approximation of it is 6.6% wrong at the midpoint of a 1.0→0.6 push-in.
The closed form is exact at every instant, has no knots to disagree about, and
cannot divide by zero — `s` is linear between two ends that are both in
`(0, 1]`, so it is bounded below by `min(start, end) > 0`.

**Containment holds by construction.** If `A_i` clamps to 0 then
`x_i + w_i/2 - W0/2 < 0`, hence `x_i + w_i < W0/2 + w_i/2 <= W0` — the rect is
inside the base crop. The right edge is symmetric, and the vertical follows the
same argument from `h_i <= H0` about a shared centre. So `XX_i` and `YY_i` are
always within `[0, W0-w_i]` / `[0, H0-h_i]`, and nothing needs clamping at
render time.

**`s=W0xH0` is forced, not chosen.** zoompan clamps `z` to a minimum of 1 —
measured: at `z=0.5` the output frame is byte-identical to `z=1`
(sha256 `1754b4a0a2617e45` for both). Setting `s` to the delivery size would
make `z = out_w/w_i < 1` for any normal 4K-to-1080 episode, and the zoom would
silently not render at all. With `s` equal to zoompan's own input size,
`z = W0/w_i >= 1` always.

The price is one extra resample: the region is scaled up to `W0xH0` and the
existing tail then scales down to the canvas. The alternative — scale to the
canvas first and zoom into the delivered raster — is both softer and the `z<1`
trap again.

**zoompan's `x`/`y` are in ITS INPUT's coordinates,** not in the zoomed image's.
Measured: `zoompan=z=2:x=160:y=120` against `crop=320:240:160:120,scale=640:480`
differs by a mean of `[0.94, 0.43, 1.28]` per channel — scaler noise, not a
geometric offset — while the same comparison in scaled coordinates differs by
`[121.64, 205.31, 130.08]`.

### 3.4 The clock

`crop`'s x expression uses `t`; zoompan has no `t` and uses `it` (input
timestamp). Both are the same frame's presentation time, and `crop` does not
touch timestamps, so the base rect and the zoom window stay on one clock by
construction. `on/fps` was the alternative and is rejected: it would assume an
exact frame cadence the rest of the chain does not, and any drift between the
two expressions would walk the zoom window toward the edge of the base crop.
`it`'s own failure mode is trap 4's cousin, and §8 records it.

---

## 4. The path contract

`PathMeta` gains three optional parallel arrays:

```python
crop_ws: list[int] | None = None    # effective crop width per route sample
crop_hs: list[int] | None = None
crop_ys: list[int] | None = None
```

`None` means a constant rect — today's behaviour, and today's sidecar, byte for
byte. `path.json` is not touched at all: it stays a bare list of crop-x values.

**There is no `zoom: bool` field.** `pan` is a bool because it records a fact
with no other representation; a zoom bit would have to agree with the arrays,
and two representations of one fact are a contradiction surface. `PathMeta`
gains a `zoomed` *property* (`crop_ws is not None`) instead, which cannot
disagree with anything.

The arrays are written by `reframe` from the same computation that built the
ffmpeg expressions — recorded, not re-derived. This is the rule `PathMeta`
exists to enforce (design 2026-07-10 §6): consumers read what was cut, they do
not recompute it.

---

## 5. The checks

Every consumer that divides by a crop dimension takes it per sample.

| Consumer | Change |
|---|---|
| `checks.on_line` / `centered` | `crop_w: int` becomes `crop_ws: list[int]`, one shape, no union. `check_episode` passes `meta.crop_ws or [meta.crop_w] * len(path)`. |
| `checks.jitter` | measures reversals of the rect's **centre** (`x + w/2`) instead of its left edge. |
| `geometry.extent_at_times` | interpolates `w`/`h`/`y` from the arrays at each sample time instead of reading three scalars. |
| `geometry.marks_at_times` | same. |
| `reframe.compute_path` | `crop_w: int` becomes `crop_ws: list[int]` — the composition is evaluated at the width in force at that sample. |

`extent_at_times` and `marks_at_times` are the two chokepoints that make this
cheap: fixing them fixes `safezones.subject_extents`,
`reel_final.evaluate_key_action`, the storyboard's marks, and `check_reel`'s
geometry section, none of which need to know a zoom exists.

**The `jitter` move is a no-op for every existing episode.** With a constant
width, `x + w/2` is `x` plus a constant, and the reversals of a
constant-shifted series are identical to the original's. Under a zoom it is the
honest measurement: the left edge moves monotonically inward during a push-in
even when the subject is still, and measuring reversals of the centre keeps the
zoom's own contribution monotone.

`check_episode` gains no new arm. Under a zoom there is a route, so
composition, continuity and colour fidelity are all judged exactly as they are
on any tracked episode — which is the whole point of the slice. One existing
arm is narrowed: `elif meta.freedom == 0` reports `editorial-only` because "the
crop is as wide as the source: nobody controls composition". Under a zoom that
is false — a push-in creates freedom that the layout did not have — so the arm
applies only when the episode is not zoomed.

---

## 6. Refusals

All fail loud, at the earliest layer that can see the contradiction.

1. `start`/`end` outside `(0, 1]` — above 1.0 needs pixels outside the layout's
   crop; at or below 0 is not a rectangle.
2. `start == end` — that is not a zoom, it is a smaller crop; the remedy names
   `crop_scale`.
3. `zoom` together with `pan` — one says there is a subject to anchor to, the
   other says there is none.
4. A zoom on an episode with no duration to travel across (mirrors
   `generate_pan_path`'s duration refusal).
5. `abs(end - start) / dur > ZOOM_MAX_RATE` — the whip-zoom guard, the analogue
   of the pan design's speed cap, and for the same reason: to catch the absurd
   (a typo turning a push-in into a lurch), not to police taste.
6. `int(W0 / (1/min(start, end))) < out_w / ZOOM_MAX_UPSCALE` — the push-in
   upsamples past a bounded allowance. A push-in below the delivery's own width
   ships magnified pixels that were never resolved, so this is a real quality
   gate; but refusing ANY upsample was measured to make the feature useless on
   the flagship path, and the correction is recorded here rather than hidden:

   | canvas / delivery | crop width | out width | max push-in |
   |---|---|---|---|
   | 9:16, native | 1215 | 1214 | 1.001× |
   | 9:16, 1080x1920 | 1215 | 1080 | 1.125× |
   | 16:9, 1920x1080 | 3840 | 1920 | 2.000× |

   A 9:16 crop of a 16:9 4K source is already at the delivery's resolution — it
   takes the full 2160 height and only 1215 of width — so a zero-upsample rule
   caps the reel format this engine exists for at 1.125×, below the threshold of
   visibility. `ZOOM_MAX_UPSCALE = 1.5` names how far past 1:1 a push-in may
   resample: on 9:16 that allows ~1.69×, so a `1.0 → 0.7` push-in ships pixels
   resampled about 1.3× at its tightest instant. Uncalibrated first cut, like
   every other threshold in this design (§10).
7. `pan` on a window with `present > PAN_PRESENCE_MAX` (§2.1), and `pan` with a
   hero pin or cast name (§2.2).

---

## 7. Authoring and wiring

`ZoomSpec` follows `PanSpec` through every layer it already passes:

- `EDLEpisode.zoom: dict | None` — `to_dict`/`from_dict`, and a `zoom 1.0→0.7`
  entry in `EDL.md`'s motion column beside the existing pan entry.
- `edl.to_manifest_dict` carries it, as it carries `pan`.
- `Manifest.zoom: dict | None`, added to `OPTIONAL`.
- `process_episode` builds the `ZoomSpec` from the wire dict, exactly as it
  builds `PanSpec` and `LayoutSpec`.
- `ReframeSpec.zoom: ZoomSpec | None`.
- `edit_plan.window_to_episode` forwards it with the other editorial fields —
  no allowlist change is needed, since `**editorial` goes straight to
  `EDLEpisode` and an unknown field already raises there.

**No orchestration change.** A zoom is retryable in the ordinary way: it has a
route, so every existing rung of the ladder still applies, and the ladder's
`crop_scale` knob composes with the zoom's fractions (they are relative to
whatever `W0` the layout resolved). `pan`'s `pan-not-retryable` arm is
untouched, and the zoom does not enter it.

**No `check_reel` change** beyond what §5's two chokepoints already give it,
and no `ReelEpisode` change: a zoomed episode always has a route, so the
`route: str | None` the pan slice introduced is not exercised further.

---

## 8. The landmine registry — four new silent-corruption entries

All four measured on this machine's `ffmpeg-full` on 2026-08-08. None of them
fails; each produces wrong pixels quietly, which is what the montage design's
§12 landmine registry is for.

1. **`zoompan` `s` defaults to `hd720`.** A `zoompan` without an explicit `s`
   silently resizes the episode to 1280x720.
2. **`zoompan` `fps` defaults to 25.** On the 60fps footage this engine targets,
   an omitted `fps` silently resamples the episode's frame rate.
3. **`zoompan` `d` defaults to 90.** Each input frame would be held for 90
   output frames — a 3-second episode becomes minutes of stutter.
4. **`zoompan` clamps `z` below 1 to 1, silently.** `z=0.5` and `z=1` produce a
   byte-identical frame. Any formulation that asks zoompan to shrink renders no
   zoom at all and reports nothing.

The landmine lint (design 2026-07-20) gains its fifth check, over the assembled
argv the way the other four run: a `zoompan=` argument must carry explicit
`s=`, `fps=` and `d=`. The lint cannot check trap 4 — it is arithmetic on a
runtime expression, not a literal — so trap 4's detector is the pixel proof in
§9, and that is stated rather than papered over.

---

## 9. Proofs (real ffmpeg, no stubs)

1. **The region really shrank.** Render a synthetic clip with a marked subject
   and `zoom 1.0 → 0.6`; assert the subject's on-screen width grew by
   approximately `1/0.6`, and that its normalized x stayed on the composition
   line at start, middle and end. This is the one proof that catches trap 4 —
   under a silent clamp the subject's size would not change at all.
2. **The record matches the pixels.** Assert the measured region width at three
   times is within 2px of `PathMeta.crop_ws` at those samples.
3. **Nothing else moved.** A zoomed render has the same output dimensions and
   the same frame count as the unzoomed one.
4. **Zoom off is byte-identical.** With `spec.zoom is None`, the emitted argv
   contains no `zoompan` and equals today's argv exactly — the fast path's
   protection, the same standard `_filter_args` is already held to.
5. **The pan gate fires.** `window_to_episode` refuses a `pan` on a window with
   `present` above the threshold, and accepts it below; `manifest.validate`
   refuses `pan` + hero.
6. **The clock is shared.** Asserted implicitly by proof 1 — a NAN `it` (§3.4)
   collapses `z` to 1 and the subject's size would not change.

---

## 10. Honest limits

- **The hand-authored door keeps a hole.** `edl_to_reel`'s single-command SP1
  path never reads `FOOTAGE.json`, so a `pan` authored there with no hero pin
  is accepted on any shot. What closes for that door is only the
  self-contradicting case (§2.2). Running the tracker on every pan episode
  would close it fully and was rejected: pan exists precisely so a scenery shot
  does not pay for a YOLO pass.
- **`PAN_PRESENCE_MAX`, `ZOOM_MAX_RATE` and `ZOOM_MAX_UPSCALE` are first cuts.**
  None has been calibrated against a real shoot. `PAN_PRESENCE_MAX = 0.10` is a
  judgement about what "incidental" means, not a measurement.
  `ZOOM_MAX_UPSCALE = 1.5` is the sharper admission: it is the point at which
  this design stops refusing upsampled pixels and starts permitting them, chosen
  because the alternative measured out at 1.125× on the reel format the engine
  exists for (§6). Nobody has looked at a 1.5× push-in on real graded footage and
  said it holds up.
- **Recorded and rendered rects can differ by up to a pixel.** `w_i` is
  `int(W0/z_i)`, computed in Python; ffmpeg performs the same division in its
  own doubles. Defining `w_i` from `z` (§3.2) removes the systematic part of the
  disagreement; the rounding residual remains, and proof 2 measures it at 2px
  rather than asserting it away.
- **A zoom costs a second resample** (§3.3). Region to `W0xH0` to canvas, where
  an unzoomed episode resamples once. Measurable softness at large push-ins;
  refusal 6 bounds the worst case at the delivery's own resolution.
- **Presence is a proxy for "has a subject".** Intake's `present` counts frames
  in which YOLO found a person. A shot whose subject is a dog, a car or a
  drone reads as subject-less and may be panned. That is a real gap, and it is
  the same gap intake's whole people-first model already carries.
- **The gate proves the premise, not the taste.** It establishes that a panned
  shot held no people. It says nothing about whether the pan was a good move,
  and it cannot: that judgement belongs to the episode-QC judge and to CP3.

---

## 11. Deferred

- **A scenery zoom (Ken Burns).** A generated zoom over a subject-less shot is
  a legitimate classic move, and it would ride the same `editorial-only`
  reporting `pan` already has. Deliberately out of v1: this slice narrows the
  generated branch, and widening it in the same breath would undo the point.
- **A vertical component.** The zoom holds the frame's vertical centre; a move
  that also tilts needs the route's `y` to drive `cy_i`, and the composition
  rules for vertical framing (headroom) are not yet encoded anywhere.
- **Easing.** `s(t)` is linear, as `PanSpec`'s travel is. Cosine ease-in/out
  belongs with the speed-ramp slice (#7), which already carries an easing
  primitive on the parked branch.
- **Re-scoping `pan` as a special case of `zoom`.** Both are now
  "a rect path over time"; unifying them is tempting and premature until the
  scenery zoom above exists to unify with.
