# Cinematic look — design (backlog #9 look half, #18 remainder)

**Date:** 2026-08-13
**Status:** design approved, built 2026-08-13
**Backlog:** [#9](../fixes-backlog.md#9-cinematic-effects-library--mood-oriented-palettes)
(P1 look half), [#18](../fixes-backlog.md#18-cinematic-effects-were-born-as-live-patches--land-them-properly-and-verify-they-show)
(the whole remainder), playbook priority 4

---


> **Amended 2026-10-19 (retro 2026-10-16 S6, S18).** The bookend is no longer one
> number. `LookSpec.fade_in` sets the opening apart (absent = the same as `fade`, so
> every older file renders the same picture; its sound gains only the 20 ms
> anti-click ramp below), and every mood preset now opens on picture
> (`fade_in: 0`) — the second real run's hook opened on a black frame and all four
> reviews flagged it. `mix` keeps a 20 ms anti-click floor on the opening. And when
> the outro fit chose the reel's length as `line + fade`, `build_reel` now hands
> `mix` the FIT's fade for the music's close, not the look's: REEL_v5 held full
> level 0.7 s past its bar line. The text below is history where it says one fade.

## 0. Why this slice exists

The 2026-08-03 real montage run grew an effects wishlist by patching the engine
live. Two of the five patches have since landed as first-class knobs with their
own visibility proofs — `zoom` (2026-08-08) and the speed `ramp` (2026-08-09).
Three did not: the **look filters**, the `highlight_red` colour primitive, and
the `outline-bold` title style. This slice lands all three and closes #18.

#18's demand is specific and it is not "add the effect". It is:

> each effect needs an **"is it actually visible on the frame"** verification:
> the live-added **vignette came out invisible** (filter strength / chain order
> ate it), which no test caught.

So every knob here ships with a measurement of the pixels it moved, not an
assertion that a correct-looking argv was assembled.

**Grain is deliberately not in this slice.** It was measured and priced out —
see §11.2.

---

## 1. Where a look lives, and why there is only one place it can

A look is **reel-level** and rides **`deliver`'s one encode**, exactly where
titles already ride:

```
EDL.look → ReelManifest.look → build_reel → deliver's single filtergraph
```

That wire is a copy of `EDL.platform`, landed 2026-08-12. Nothing new is invented
for it.

Three positions were possible; two are wrong for reasons the code already
enforces.

**Not in `assemble`.** `check_reel` judges the assembled master, and its black
gate is `blackdetect=d=0.05:pic_th=0.98`. A bookend fade to black is 0.5s of
deliberate black frames at each end — it would fail the reel's own mechanical
gate. The fade is only legal *after* the check, which is where `deliver` sits.

**Not per-episode in `reframe`.** A vignette applied per episode would be
re-judged by `check_episode`'s composition and colour checks (which know nothing
about an intentional corner falloff), and would cost one re-encode per episode
instead of one for the reel. The colour stage already occupies the per-episode
actuator slot; a look is the reel's finish, not an episode's correction.

**In `deliver`.** After both gates, one encode, one filtergraph, and the look is
carried on the attested `EDL` so the record of what was applied travels with the
cut for free (the EDL's digest already covers it — no new provenance field).

---

## 2. The vignette's shape is the whole slice

### 2.1 ffmpeg's built-in `vignette` cannot do this

The built-in filter is a lens-falloff model: `cos⁴` from the frame centre, with
**no plateau**. On a 9:16 canvas that is not a vignette — it is a top-and-bottom
dimmer, because the vertical extremes sit 960px from the centre against the
horizontal 540px.

Measured on a flat `0x808080` 1080×1920 field at crf 18, as a fraction of the
frame centre (`sky` = the y 8–14% band above where a subject stands, `side` =
the mid-height left edge):

| filter | corner | sky | side |
|---|---|---|---|
| none | 1.000 | 0.998 | — |
| `vignette=angle=PI/8` | 0.728 | **0.843** | — |
| `vignette=angle=PI/5` (default) | 0.413 | **0.637** | 0.836 |
| `vignette=angle=PI/4` | 0.212 | 0.479 | 0.754 |
| `vignette=angle=PI/3` | 0.001 | — | — |
| `vignette=angle=PI/5:aspect=9/16` | 0.682 | 0.870 | 0.839 |
| `vignette=angle=PI/4:aspect=9/16` | 0.539 | 0.801 | 0.758 |
| `vignette=angle=PI/5:aspect=16/9` | **0.000** | **0.000** | 0.828 |

`aspect` reshapes the ellipse but cannot add a plateau: even at `9/16` the sky is
13% down and the mid-height side 16% down, at a corner of only 0.682. And
`aspect=16/9` on a tall frame drives the corners and the entire sky to **pure
black** — a one-character authoring slip that silently destroys the frame.

The parked live patch rejected the built-in filter for exactly this reason
("wrong on a tall 9:16 frame where the sky above the subject dims"). The
measurement confirms it.

### 2.2 The shape we want, and the three ways to get it

A **plateau vignette**: identity out to 55% of the corner radius, then a
smoothstep falloff to the corner. Measured on the textured source at crf 18:

| route | +encode (3s of 1080×1920) | corner/centre | sky/centre |
|---|---|---|---|
| no look | — (0.37s baseline) | 0.971 | 0.998 |
| built-in `vignette=angle=PI/8` | +0.33s | 0.728 | 0.843 |
| `geq`, per pixel per frame | **+4.69s** | 0.664 | 0.990 |
| **one-shot mask + `overlay`** | **+0.18s** | **0.709** | **0.995** |

The static mask is **26.4× cheaper than `geq`** and cheaper than the built-in
filter, while being the only one of the three with a real plateau. The centre is
untouched: overlay vs no-look, mean |ΔY| over the centre 240×240 is **0.144**.

**Decision: one-shot RGBA mask + `overlay`.**

### 2.3 The mask

Black pixels whose alpha ramps from 0 on the plateau to `255 × vignette` at the
corners, rendered **once** at the delivery's own dimensions:

```
format=rgba,geq=r=0:g=0:b=0:a='st(1,clip((hypot((X-W/2)/(W/2),(Y-H/2)/(H/2))/1.41421-0.55)/0.45,0,1));255*{v}*ld(1)*ld(1)*(3-2*ld(1))'
```

`1.41421` normalizes the corner distance to 1; `0.55` is the plateau radius and
`0.45` the remaining falloff; `ld(1)*ld(1)*(3-2*ld(1))` is smoothstep. At
1080×1920 the PNG is 105 kB and takes one frame to render.

**Overlay desaturates the corners; `geq` did not.** Corner chroma excursion from
neutral: plain 108.27, `geq` 108.28, overlay **74.89**. This is a real
difference and it is the *correct* one — an optical vignette is less light, and
less light is less saturation. `geq`'s chroma-preserving version holds full
saturation in a darkened corner, which reads slightly plastic. Recorded as a
deliberate choice, not an accident.

---

## 3. The mechanism

### 3.1 `lib/look.py` — pure, no IO

```python
LOOK_VIGNETTE_MAX = 0.6      # past this the corners read as a black border, not a vignette
LOOK_FADE_MAX     = 2.0      # mix already refuses dur < 2*fade; 2.0s needs a >=4s reel
VIGNETTE_PLATEAU  = 0.55     # identity radius, as a fraction of the corner distance
VIGNETTE_FALLOFF  = 0.45     # 1 - PLATEAU; named so the expression reads

@dataclass
class LookSpec:
    vignette: float = 0.0    # corner darkening, 0 = off
    fade: float = 0.0        # bookend fade seconds, 0 = off
```

Both default to 0, and **0 means the filter is not emitted at all** — the
identity-off convention `color.white_balance` already uses. A `LookSpec()`
renders exactly what today renders.

**`None` and `LookSpec()` are different, and the difference is load-bearing.**
`EDL.look is None` means *never authored* — `edit_plan` fills it from the mood
preset. `EDL.look == LookSpec()` means *authored as no look* — the preset does
not get to override it. Same shape as `EDL.variety` and `EDL.constraints`, where
`None` means "never evaluated" and is never read as "passed".

The JSON boundary must therefore test `is not None`, never truthiness — and the
reason is narrower than it first looks. `{"vignette": 0, "fade": 0}` is a
non-empty dict and so is truthy either way; the input that actually separates the
two spellings is `"look": {}`. Under `is not None` that is `LookSpec()`, an
authored decision; under truthiness it silently becomes `None` and the preset
overrides it. `EDL.from_json` is a documented hand-authored front door
(extract-spine SP1), so an empty object is reachable, and it is the case a test
has to name.

Functions:

- `LookSpec.has_vignette` — `vignette > 0`. The one predicate that decides
  whether `deliver` needs a second input at all.
- `mask_expr(vignette: float) -> str` — the geq expression above. Refuses
  outside `(0, LOOK_VIGNETTE_MAX]`; `0` is not passed here (the caller skips).
- `fade_args(fade: float, dur: float) -> list[str]` — the two `fade` filters, or
  `[]`. Refuses `2 * fade > dur` with the same shape of message
  `Title` uses for its own fade.
- `chain(spec: LookSpec | None, dur: float, titles: str = "") -> list[str]` —
  **this function owns the §4 order**: the title drawtext, then the bookend
  fades. An empty list means `deliver` emits no video-filter slot at all. The
  vignette overlay is *not* in this list: it needs a second input and is wired
  by label in `deliver`, which prepends it. Pure string assembly; the mask
  *file* is `deliver`'s business.

### 3.2 `deliver` grows one branch, and the off path stays byte-identical

Today `deliver` has, in its own words, "the SOLE `-vf` slot". A mask is a second
input, so a vignette needs `-filter_complex`. Two shapes, chosen by whether the
look asks for a mask:

- **No vignette** (including no look at all): unchanged `-vf`, unchanged argv,
  **byte-identical output to today**. A fade-only look still rides `-vf`.
- **Vignette**: `-loop 1 -i <mask.png>` plus `-filter_complex "[0:v][1:v]overlay=shortest=1,<titles>,<fades>[v]" -map "[v]"`.

The mask is written beside the title sidecars, in `out_dir`, at the dimensions
`assembly.probe_stream(master)` reports — the delivery's real pixels, never a
config's idea of them (the `Delivery.dims(native)` trap that made `draft.py`
render 8×16 is one call away from here).

**There is no `movie=` shortcut.** Trying to keep the single `-vf` slot by
sourcing the mask inside the graph fails two different ways, both silent — see
§8.2 and §8.3.

### 3.3 Threading

`EDL.look` (a `LookSpec | None`, `None` = never authored) → `edl_to_reel`
copies it onto `ReelManifest.look` → `build_reel` passes it to `deliver`. Line
for line the `platform` pipe from 2026-08-12, including the `edit_plan build`
log line that names what it resolved.

---

## 4. Chain order, and the one part of it that is measured

```
overlay(mask) → drawtext(titles) → fade in/out
```

- **Vignette before the titles**, so a bottom title is not dimmed by the corner
  falloff it happens to sit near.
- **Fade last, and this is the measured one.** With the fades at the end, the
  first frame reads **0.0** — the title goes black with the picture. Move them
  before `drawtext` and the title burns on at full brightness over a black
  frame. Measured on the full five-stage chain: first 0.0, mid 128.0, last 7.5
  (the last frame sits at t=2.967 with the fade-out ending at 3.0, so 7.5/255 is
  the sampling residue, not an unfinished fade).

The whole chain — overlay, noise, drawtext, two fades — composes in one
filtergraph and runs in 1.39s on 3s of 1080×1920.

---

## 5. The audio, and the defect the fade exposed

`mix.py` **already** fades the music: `_FADE = 0.5`, hardcoded, applied to the
music fragment before ambient and sfx are mixed in.

That placement is wrong, and the bookend fade is what makes it visible.
`_mix_graph` ducks the ambient with `sidechaincompress` **keyed on the music**.
When the music fades out, the key signal falls, the compressor **releases**, and
the nat-sound gets *louder* — at exactly the moment the picture goes black. The
synthesized whoosh is not faded at all.

**Fix:** the bookend fade moves off the music fragment and onto the **mixed**
stem, applied before `_measure` so `loudnorm` still measures what actually
ships. Everything fades together.

**`_FADE` stops being a constant** and becomes `mix(fade=)`, defaulting to the
0.5 it is today. `build_reel` passes `rm.look.fade` when a look exists; a reel
with no look, or a look whose `fade` is 0, keeps the 0.5s music fade unchanged —
the audio bookend is not something a missing look should switch off. One number,
two readers, agreeing by construction rather than by coincidence.

The music-only path is **not** claimed byte-identical, and the reason is worth
stating rather than discovering. Today the fade runs in the same pass that
decodes and trims, so the signal is quantized to s16 once. Moved, it is
quantized on the way into `frag.wav` and again after the fade — a **double
quantization** whose worst case is 1 LSB on the faded 0.5s at each end, and
zero everywhere else. The integration proof measures the delta rather than
asserting an identity that is not true. A reel *with* ambient changes
deliberately and audibly: its tail stops swelling.

A **silent reel** never calls `mix` at all, so a `fade` there is a picture-only
bookend. Correct, and worth saying out loud because the two halves of the fade
live in different modules.

---

## 6. `MoodPreset.look` — the brief's default

`MoodPreset` gains a fourth field, `look: LookSpec`. Its current docstring says
it carries "exactly the two fields its one consumer reads"; that sentence gets a
third consumer and is updated rather than quietly falsified.

First cut, declared guesses in the same breath as `shot_mix` and `asl`:

| preset | vignette | fade |
|---|---|---|
| fun | 0.00 | 0.3 |
| epic | 0.30 | 0.8 |
| moody | 0.40 | 1.0 |
| nostalgic | 0.25 | 0.8 |
| **balanced** (fallback) | 0.00 | 0.00 — never applied; see below |

**Corrected post-review (final-findings.md I-2).** This section originally said
`BALANCED` applies no vignette and the 0.5s fade `mix` already does, so the
autonomous path delivers exactly today's picture — and shipped that way:
`write_edit_plan` passed `preset.look` unconditionally, so a mood-less or
skipped brief set `EDL.look = LookSpec(vignette=0.0, fade=0.5)`, which reached
`deliver` as a real `fade=t=in`/`fade=t=out` pair. Every autonomous reel opened
on a black frame — an editorial decision nobody made, and the opposite of what
this section claimed. Pre-slice `deliver` had no video fade at all.

The mechanism that actually delivers today's picture is `EDL.look is None`, not
a zero-vignette preset row. `write_edit_plan` passes `look=None` to `build_edl`
whenever `moodpreset.resolve` falls back (`preset.name == "balanced"` is the
exact test — `BALANCED.anchor is None` keeps it out of the nearest-neighbour
search), and `None` is the state `deliver`/`build_reel` already read as "nothing
authored": no vignette, no picture fade, and `mix` keeps its own pre-existing
0.5s audio default (it is never told `fade=`, so its own default applies).
`BALANCED.look` itself is `LookSpec()` — vignette 0, fade 0 — as defence in
depth only, for a caller that reads the field directly rather than going
through `write_edit_plan`'s check. Filling it with any concrete value would
itself be a change to a brief-less run's output: a real fade imposes a taste
nobody chose, and even `fade=0.0` would reach `build_reel` as an **authored**
zero and switch off `mix`'s audio bookend (see §5's mechanism — an authored
`fade=0.0` is not the same as an absent look). `None` is the only value that
changes nothing, which is why the fallback's look is carried but never applied.

Note this reads *opposite* to `BALANCED`'s variety row, where the fallback
deliberately keeps a gate armed: skipping a brief must not disable a **quality
gate**, but it also must not silently apply a **taste**. The two rows differ
because a gate and a look are different kinds of thing.

The authored `EDL.look` always wins over the preset's default; the preset only
fills an unauthored one when its mood MATCHED, and `edit_plan build` logs which
source won (`selection.json`, the `<mood>` preset, or "left unauthored" when
nothing matched).

---

## 7. The two parked leftovers

Both are already written on `wip/montage-run-patches` and were explicitly *not*
ported by the speed-ramp slice. Neither is a look filter; they ride along
because #18 names them and nothing else will.

**`highlight_red`** — a red-channel `curves` that pulls only the shoulder down,
so specular foam carrying a red board's reflection reads neutral while water,
skin and the board itself (all below the 0.60 knee) keep their red. It is
**colour**, so it lands in `color.py` beside `shadow_red_arg` (its mirror) and is
authored per-episode through `ReframeSpec`, not on the reel's look.
`HIGHLIGHT_RED_MAX = 0.35`, `HIGHLIGHT_RED_KNEE = 0.60`, both carried over with
their reasons.

**`outline-bold`** — a fourth entry in `titles._STYLE_FRAGMENTS`:
`borderw=7:bordercolor=black:shadowcolor=black@0.55:shadowx=3:shadowy=3`, and a
fourth member of `STYLES`.

---

## 8. Landmines found while measuring — all five silent

None of these fails loud. Each belongs in the design-spec §12 registry.

### 8.1 `blend=all_mode=multiply` with a gray mask destroys chroma

The obvious way to apply a luma mask. The luma comes out roughly right, and the
colour is annihilated: against the `geq` reference, **mean |ΔU| 63.44, |ΔV|
62.76**. U and V sit at 128 for neutral, so multiplying them by `mask/255` drags
every pixel toward 0 — a maximal colour shift. Restricting the blend to the luma
plane (`extractplanes` → blend → `mergeplanes`) fixes it (ΔU/ΔV 0.18) at the
cost of a five-node graph. `overlay` through alpha avoids the whole problem.

This one is worth a **sixth `lint.check_argv` check** — it is exactly the class
of the four already there.

### 8.2 `movie=` inside `-vf` without `loop` truncates the reel to one frame

The tempting way to keep the single `-vf` slot. ffmpeg exits **0** and writes a
valid mp4 with `nb_frames=1`: the PNG source ends after its single frame and
`overlay=shortest=1` ends the graph with it. The whole reel becomes a still.

### 8.3 `movie=…:loop=0` inside `-vf` hangs

The obvious repair for §8.2. The output file stalled at 48 bytes and made no
progress for six minutes before being killed, against 0.55s for the same work
through a real `-loop 1 -i` input.

### 8.4 `color=c=white` is 253, not 255

A mask built by grading a white source has a plateau of **253**, so the
"untouched" centre is dimmed by 0.8% everywhere. Building the mask on `nullsrc`
with an explicit `255*(…)` alpha expression gives a true 255 plateau.

### 8.5 The built-in `vignette` on a vertical canvas

§2.1. Worst form: `aspect=16/9` on a 9:16 frame drives the corners **and the
entire sky** to pure black at any angle.

---

## 9. Visibility proofs (#18's actual demand)

One real-ffmpeg measurement per knob, each asserting the pixels moved in the
direction commanded and that the pixels which should not move did not:

| knob | proof |
|---|---|
| `vignette` | corner/centre ratio falls with strength; centre 240×240 mean \|ΔY\| stays under 1 |
| `fade` | first and last frame mean luma → ~0; the mid frame is unchanged from no-fade |
| `look` off | argv is byte-identical to today's, and so is the delivered file |
| audio fade | the stem's last 0.5s falls monotonically, with ambient on as well as off |
| `highlight_red` | R−B falls in the highlight band and does not move below the knee |
| `outline-bold` | the rendered glyph's ink extent is wider than the same title in `outline` |

---

## 10. Out of scope, named

- **Grain.** Measured and priced out — §11.2.
- **Film LUTs, halation, light leaks, chromatic aberration, letterbox bars.**
  The P3 look tail. LUTs need licensed asset files, which is a distribution
  question before a code one.
- **Mood biasing the match-grade target** (the long-deferred "mood LUT"). That
  is the grade half of #9 and stays P2; this slice touches the *look*.
- **`draft.py` showing the look.** The draft is a QA preview of the cut;
  delivery finish does not belong in it.
- **A `check_reel` gate on the look.** §11.1.

---

## 11. Honest limits

### 11.1 Nothing checks that the look happened

`check_reel` runs on the master, before `deliver` encodes — so no gate ever sees
the vignette, the fade or the titles. The proofs in §9 live in the test suite and
prove the *engine* renders them; they cannot prove that a given delivered reel
carries what its EDL asked for. This is the same boundary titles have shipped
with since 2026-07-13, and it is the reason #18 exists at all: an effect that
silently does nothing is invisible to every gate in this pipeline.

The cheapest real fix is #10's 3-frame probe, which is a P2 row and generalizes
to effect visibility, not just colour.

### 11.2 Grain: measured, then dropped

At the delivery profile's own crf 18, on a textured source:

| `noise=alls` | delivered σ (flat field) | file size |
|---|---|---|
| 4 | 0.61 | ×1.27 |
| 8 | 1.56 | **×4.36** |
| 12 | 3.78 | ×8.82 |
| 20 | 6.63 | ×14.08 |

The first setting with any real presence costs **4.4× the file**. A 30s reel goes
from ~37 MB to ~160 MB, and the platform re-encodes on upload anyway — so the
cost is paid and the grain is then destroyed by someone else's encoder. Capping
with `maxrate` returns the bitrate by taking detail away from the water and the
faces, which is a worse trade than not having grain. Deferred to P3 with these
numbers attached, so the next person does not re-measure.

### 11.3 The numbers are first cuts

`LOOK_VIGNETTE_MAX = 0.6`, the 0.55 plateau, the 0.45 falloff and every row of
`MoodPreset.look` are hand-picked on synthetic test patterns. No real footage has
been graded against them. They live in one place each and are declared guesses,
the same honesty `CLUSTER_COS`, `MAX_CAST` and `shot_mix` already carry.

### 11.4 The corner desaturation is a choice, not a match

§2.3. The overlay route and the `geq` route agree on luma (mean |ΔY| 1.39) and
disagree on corner saturation by design. If a later slice wants the
chroma-preserving shape it must pay `geq`'s 26× or build the five-node
luma-plane blend.

### 11.5 The fade's edges are quantized to the frame

A 0.5s fade on a 30fps reel is 15 frames; the last frame lands wherever the
reel's duration puts it, so the final frame's luma is "near 0", not 0. Measured
7.5/255 on a 3s test. No visible consequence; recorded so nobody treats a
non-zero last frame as a bug.

### 11.6 One mask per delivery, one delivery per mask

The mask is rendered at the master's probed dimensions each time `deliver` runs.
Two deliveries of the same reel render it twice (one frame, ~0.1s). No cache,
deliberately — a cached mask keyed on the wrong dimensions is a silent
letterbox, and the thing being avoided costs a tenth of a second.

---

## 12. Deferred — every row goes to `docs/backlog.md`

Per the rule the 2026-08-12 housekeeping slice added: this slice is not finished
until each of these has a backlog row.

| item | bucket | why deferred |
|---|---|---|
| **Grain** (`noise`), with the §11.2 cost table attached | P3 (look tail) | ×4.4 file size at the first useful strength, and the platform re-encodes it away |
| **A `check_reel`-side or 3-frame-probe check that the look actually rendered** | P2, folded into #10 | no gate runs after `deliver`; #10 already owns the convergence loop this needs |
| **Calibrate `LOOK_VIGNETTE_MAX`, the plateau/falloff, and `MoodPreset.look`** on real footage | P2 | first cuts on synthetic patterns (§11.3) |
| **The chroma-preserving vignette** (luma-plane blend or `geq`) if the desaturation reads wrong on real footage | P4 | 26× the cost or a five-node graph, for a difference that may be an improvement (§11.4) |
| **A per-episode look override** | P4 | the reel's finish is reel-level by construction (§1); no request for it exists |

---

## 13. Files

| file | change |
|---|---|
| `scripts/lib/look.py` | **new** — `LookSpec`, `mask_expr`, `fade_args`, `chain`, the four constants |
| `scripts/lib/edl.py` | `EDL.look` carrier + validation + dict round-trip + `to_markdown` row |
| `scripts/lib/models.py` | `ReelManifest.look` carrier; `ReframeSpec.highlight_red` |
| `scripts/lib/moodpreset.py` | `MoodPreset.look` field + the five preset rows + the docstring correction |
| `scripts/lib/color.py` | `highlight_red_arg` + its two constants; `grade_chain(highlight_red=)` |
| `scripts/lib/titles.py` | `outline-bold` in `STYLES` and `_STYLE_FRAGMENTS` |
| `scripts/lib/lint.py` | sixth check — `blend=all_mode=multiply` (§8.1) |
| `scripts/deliver.py` | mask render + the `-vf` / `-filter_complex` branch |
| `scripts/mix.py` | the fade moves onto the mixed stem; `_FADE` becomes a parameter |
| `scripts/build_reel.py` | thread `rm.look` into `deliver` and `mix` |
| `scripts/edl_to_reel.py` | copy `edl.look` onto the `ReelManifest` |
| `scripts/edit_plan.py` | resolve the preset's look when unauthored; log which was used |
| `scripts/lib/edl.py` (EDLEpisode) | `highlight_red` authoring field |
| `scripts/process_episode.py` | pass `highlight_red` through to the grade |
| `skills/edit-plan/SKILL.md`, `skills/titles/SKILL.md`, `skills/using-montage/SKILL.md` | the new knobs |
| `docs/specs/2026-07-05-montage-skillset-design.md` §12 | the five landmines |
| `docs/backlog.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md` | status + registry |
