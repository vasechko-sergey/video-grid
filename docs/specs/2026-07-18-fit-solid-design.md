# fit-solid — the filler becomes a parameter

_2026-07-18 · design spec §7 (layouts), the misc-engine tail · slice A of A/B/D_

## 1. What this closes, and the name that lies

Design [§7](2026-07-05-montage-skillset-design.md) lists `fit-solid` — "scale-inside
+ solid pad, clean/graphic look" — as **planned**. This slice builds it.

The [layouts design](2026-07-10-layouts-design.md) already decided *how*:

> These names are presets, not code branches. A layout is three parameters: a
> crop (aspect + scale), a rectangle placed in the canvas, and a background
> filler. **Adding `fit-solid` means adding a filler, not a branch.**

The code already agrees. `fit-blur` and `insert` share one path through
`layout.resolve` and differ only by whether a `rect` was given; `background` is
already a `LayoutSpec` field and already reaches `ResolvedLayout`
(`scripts/lib/layout.py:133`). What is missing is two small things: `BACKGROUNDS`
knows exactly one value, and `reframe._filter_args` hardcodes the boxblur chain.

**But the mode name bakes the filler into itself.** The moment a second filler
exists, an EDL author has to write

```json
{"layout": "fit-blur", "background": "solid"}
```

which contradicts itself. A reader cannot tell which half wins, and the answer —
the `background` field — is not the half they read first.

So the filler cannot be added honestly without renaming the mode. That rename is
part of this slice, not a follow-on.

## 2. The rename: `fit-blur` → `fit`

The mode names a **geometry**; the filler names a **filler**. After the rename:

| mode | geometry | filler comes from |
|------|----------|-------------------|
| `fill` | crop carries the canvas aspect, covers it edge to edge | — (no filler exists) |
| `fit` | content spans the full canvas width, vertically centred | `background` |
| `insert` | content sits in an explicit `rect` | `background` |

`fit-blur` and `fit-solid` survive as **preset names in prose** (§7's table, the
edit-plan SKILL's vocabulary) that expand to the pair `(fit, blur)` /
`(fit, solid)`. They are not values any field holds.

**Surface** (production):

- `models.LAYOUT_MODES` and `manifest.LAYOUTS_SUPPORTED` → `("fill", "fit", "insert")`
- the validation messages that spell the vocabulary: `models.py` (mode-unknown,
  the fill/crop_aspect remedy, the `fit`-forbids-rect pair), `manifest.py:128`
- `reframe.py`'s `--layout` help
- comments in `layout.py:115` and `check_episode.py:70`

**Surface** (tests): ~40 spellings across `tests/lib/test_models.py`,
`test_manifest.py`, `test_layout.py`, `test_reel_final.py` and
`tests/integration/test_layouts.py`, `test_reframe.py`, `test_check_episode.py`,
`test_storyboard.py`.

**No alias, no deprecation shim, no normalizing `fit-blur` on input.** One
spelling. The precedent is this repo's own `TrackSpec.seed_bbox → pin` (cast →
hero-pin, 2026-07-16), renamed for the same reason: the name had stopped
describing the thing.

**Dated docs are history and are NOT rewritten** — the layouts design and plan,
the core plan, the orchestrator plan and every other dated file keep saying
`fit-blur`, because that is what was true when they were written. The living
docs are synced (§10).

## 3. The filler vocabulary

```python
BACKGROUNDS = ("blur", "solid")
```

`LayoutSpec` gains one field, and `ResolvedLayout` carries it through:

```python
background_color: str = "black"
```

Its validation **mirrors `border_color` exactly** — a non-empty string, and none
of `,:;'[]\` , the characters that would break out of an ffmpeg filtergraph
argument. Same rule, same remedy wording, because it is the same class of value
reaching the same parser.

### One new refusal

```python
if self.mode == "fill" and self.background != "blur":
    raise ValueError(...)
```

A `fill` covers the canvas edge to edge — there is no background to fill. This
mirrors the refusal `fill` already makes on `border_px` ("a border has nothing to
sit on"). Without it, `fill` + `solid` would construct, resolve, and render a
filler nobody can see: an inert setting that reads as if it did something.

`background_color` is deliberately **not** refused under `blur` or under `fill`.
It has a default, and a default is indistinguishable from an explicit value of
the same string — a refusal keyed on "did the author mean it" cannot be written
honestly, so it is not written.

### The authoring path

`background` already rides manifest → `LayoutSpec`; `background_color` must be
given the same ride, or the filler is settable only from Python. Three contracts
carry it: `LayoutSpec` (above), `Manifest` (the field, `OPTIONAL`, `from_dict`,
and the `LayoutSpec` oracle inside `validate` — so the **soft** gate sees the same
truth the hard backstop will, and a bad colour comes back as a problem string
rather than a raise), and `EDLEpisode` (the field, `to_dict`, and the
`to_manifest_dict` field map). `process_episode` passes it into the `LayoutSpec`
it builds.

### insert + solid

Falls out for free. The filler is orthogonal to the rect, which is the whole
point of the three-parameter model. It costs no code and gets a test.

## 4. The filtergraph

`fill` keeps its `-vf` fast path untouched.

The blur composite reads the source **twice** — once scaled-and-blurred for the
background, once cropped for the content — which is why it splits:

```
[0:v]split=2[a][b];
[a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},boxblur={radius}:2[bg];
[b]crop={crop_w}:{crop_h}:x='{xexpr}':y={cy},scale={rw}:{rh}{pad}[fg];
[bg][fg]overlay={ox}:{oy},{tail}
```

A solid background is **synthesized**, not derived from the source, so it needs
no second read and therefore no split:

```
color=c={background_color}:s={out_w}x{out_h}:r={fps:.6g}:d={dur:.6f}[bg];
[0:v]crop={crop_w}:{crop_h}:x='{xexpr}':y={cy},scale={rw}:{rh}{pad}[fg];
[bg][fg]overlay={ox}:{oy},{tail}
```

The two graphs differ in shape, and the difference is **caused by the filler** —
`split` exists only to serve blur's second read. That is parameterization, not a
branch: the composite structure (a `[bg]`, a `[fg]`, one `overlay`, the shared
`tail`) is identical. In code this is one helper that returns the `[bg]` producer
and the label `[fg]` reads from; `boxblur`'s radius arithmetic moves inside the
blur arm, so a solid render never computes a blur radius it will not use.

### Bounding the source with `d=`, not truncating the overlay

`color` is an **infinite** source. Left unbounded the overlay never sees an
end-of-stream on either input and the encode does not terminate — measured, it
encoded 4m12s of video from a 2-second source in 20s of wall clock and was still
going. Something must end it.

There are two ways, and **the obvious one is wrong**. `overlay=…:shortest=1` ends
the output when the shorter input ends, which does terminate — but it lands
**exactly one frame short of the source, every time**. Measured on the golden
fixture: source 1.584917s / 95 frames, blur 1.584916s / 95 frames, solid
1.568232s / **94** frames; reproduced on synthetic 1s/3s/5s sources, always
exactly one frame, so it is not a rounding artifact. `eof_action=endall` behaves
identically — the truncation is inherent to ending an overlay against an infinite
source, not to the spelling.

One frame is not negligible here, because it **accumulates against a real gate**.
`check_reel` measures the assembled reel's total duration against
`ReelCheckSpec._LENGTH_TOL` (0.5s), so ~30 solid episodes at 59.94fps — or ~15 at
30fps — consume the entire length band from this artifact alone, and eat into
`length_retime_max` on top. A filler must not change how long the reel is.

So the background is **bounded at the source** instead: `color=…:d={dur}`, with
`dur` the probed source duration, and the overlay left alone.

**That is necessary and not sufficient**, which measurement caught and reasoning
did not. `d=` alone is correct on the 59.94fps golden fixture and catastrophic on
a 30fps one:

| source | `d=` only | `-t` only | `d=` **and** `-t` |
|---|---|---|---|
| 24fps, 2s (48 fr) | **24576 fr** | 48 ✓ | 48 ✓ |
| 25fps, 2s (50 fr) | **25600 fr** | 50 ✓ | 50 ✓ |
| 30fps, 3s (90 fr) | **killed at 24.6s** | 90 ✓ | 90 ✓ |
| 60fps, 2s (120 fr) | **30720 fr** | 120 ✓ | 120 ✓ |
| 29.97 NTSC, 2s (60 fr) | 60 ✓ | 60 ✓ | 60 ✓ |
| golden_ride 59.94 (95 fr) | 96 fr / 1.601599s | 95 ✓ | 95 ✓ |

`color`'s timebase is `1/r`; a decoded mp4 carries its **container's** (`1/15360`
at 30fps). `overlay` inherits the **first** input's timebase — the synthesized
background — so the tail's `fps` filter reads the mismatch as a stream longer by
exactly the ratio between them: 15360/30 = 512, and 3s × 512 = 1536s. Every
blow-up ratio measured matches `container_tb / fps`. `settb` variants either
failed to help or cost a frame.

**What actually discriminates is not the frame rate** — it is whether the emitted
`r=` string reproduces the source's rational rate *exactly*. golden_ride blows up
too when given `r=60000/1001`; it escapes only because `f"{fps:.6g}"` mangles that
into `59.9401`, which no longer matches. Integer rates (24/25/30/50/60) round-trip
through `:.6g` unchanged, match exactly, and blow up. So the NTSC fixtures this
repo reaches for by default are safe **by a formatting accident**, and the common
integer rates are not.

So the **output** is bounded: `-t {dur}` on the ffmpeg command, applied to **every**
layout — measured a no-op for `fill` and `blur` at both rates, and unconditional
means no future filler can forget it. **`-t` alone is sufficient**; it is what pins
the length. `d=` is kept only so that a graph copied out of a test into a shell
terminates at all rather than running forever — it does **not** make such a graph
produce the right length, and it is output-neutral in the shipped command.

With both, blur and solid are **duration-symmetric** — the property that matters,
since a reel mixes them freely. Measured through real `reframe()`: golden_ride
source 95 fr / 1.584917s, blur 95 fr / 1.584916s, solid 95 fr / 1.584916s;
sample_clip 90 fr / 3.000000s for all three.

This costs one number: `reframe._probe` already runs `ffprobe` for dims and fps
and now asks for `duration` in the same call — no extra process. A source whose
duration cannot be probed **raises**; it does not silently fall back to
`shortest=1`, because that fallback would reintroduce the truncation invisibly on
exactly the files nobody looked at.

Proved by a real-ffmpeg test asserting the rendered duration equals the source's
**to within HALF a frame period** — deliberately tighter than one frame, because
the `shortest=1` regression is exactly one frame at any rate and a one-frame
tolerance would accept precisely the failure being guarded. Measured headroom
under the shipped command: ~1e-6s.

### The blur string does not change

Byte-identical to what ships today, pinned by a regression test. Same discipline
the transition-SFX slice applied to its ambient-only graph: a slice that adds a
case must leave the existing cases' commands untouched, or the goldens are no
longer guarding what they claim to guard.

## 5. The sidecar

`PathMeta` gains `background`. The sidecar's job is to record **what reframe
actually composed**, and the filler is part of that composition — the same reason
it already carries `mode`, `rect_px` and `freedom`.

`from_dict` reads a missing `background` as `"blur"`. This is not a guessed
default: before this slice, `blur` was the only value the field could have held,
so the substitution is provably the truth for every sidecar written up to now.
(A missing field otherwise raises `RuntimeError` as sidecar corruption; this one
key is exempt, with the reason written at the call site.)

### Consequence: the transitions check

`reel_final.evaluate_transitions` penalizes a cut whose **layout mode** changes
(`_layout_of` returns `meta.mode`, and `LAYOUT_MODE_PENALTY` is added on a
change). After this slice a cut from `(fit, blur)` to `(fit, solid)` would report
"mode unchanged" while the pad's appearance changes hard — a wrong verdict the
moment `solid` ships.

The layout identity used for the penalty therefore becomes the **pair**
`(mode, background)`. The check is advisory (excluded from `overall`), so the
blast radius of the change is zero; leaving it wrong was the only option with a
real cost.

`LAYOUT_MODE_PENALTY`'s comment (`reel_final.py:11`) currently reads "a mode
change (fill↔insert)" — it is re-worded with the constant, since after this slice
the penalty also fires on a filler change at a constant mode.

## 6. Edge cases

- **`fill` + `solid`** → `ValueError` at construction (§3).
- **A stale `path.meta.json` with no `background`** → reads as `blur` (§5).
- **`background_color` with a filtergraph-breaking character** → `ValueError`
  before any ffmpeg runs, same message shape as `border_color`'s.
- **`insert` + `solid` + a border** → the border still sits outside the content
  rect and is still painted by the `pad` filter; the solid fills what the card
  does not cover. Both are simply colours in the same graph.
- **A solid render of a `fit` whose content exactly covers the canvas** → the
  overlay covers every background pixel. Legal and harmless; no bars is not an
  error, and `pad_bars` already reports symmetric-zero as a pass.

## 7. Testing

**Unit — vocabulary and validation** (`tests/lib/test_models.py`)
- `LayoutSpec(mode="fit", background="solid")` constructs; the whole object is
  asserted, not one field.
- `mode="fill", background="solid"` raises, and the message names the reason.
- `background_color` validation mirrors `border_color`'s: empty string raises,
  each filtergraph-breaking character raises, a hex literal and a colour name
  both pass.
- `LAYOUT_MODES == ("fill", "fit", "insert")` — the rename pinned as a fact, so a
  future re-introduction of `fit-blur` fails a test rather than quietly working.

**Unit — resolution** (`tests/lib/test_layout.py`)
- `resolve` carries `background` **and** `background_color` onto
  `ResolvedLayout` (today only `background` is carried; the pin makes the pass-
  through a tested contract rather than an accident).

**Unit — the filtergraph** (`tests/integration/test_reframe.py`, beside the five
`test_filter_args_*` cases that already pin `fill`, `fit-blur` and `insert`)
- the solid string, whole, including `d=` and the **absence** of `shortest=1`.
- **the blur string, whole, byte-identical to today's** — the regression pin.
- `fill`'s `-vf` fast path unchanged.
- the `-t {duration}` output bound, on **every** layout — the decision to apply it
  unconditionally needs a guard, or a future filler quietly loses it.
- an unknown `background` raises out of `_background_args` rather than falling
  through to blur.

**Unit — the sidecar** (`tests/lib/test_models.py`)
- `PathMeta` round-trips `background`.
- a dict with no `background` key reads as `"blur"` (and still raises
  `RuntimeError` for any *other* missing field — the exemption is one key, not a
  loosening).

**Unit — the advisory check** (`tests/lib/test_reel_final.py`)
- two episodes, same `mode`, different `background` ⇒ the mode penalty applies.
- same `mode`, same `background` ⇒ it does not.

**Real ffmpeg — duration** (`tests/integration/test_reframe.py`'s
`test_solid_and_blur_are_duration_symmetric_with_the_source` and
`test_reframe_bounds_every_layout_to_the_source_length`)
- a `fit` + `solid` render **terminates, and its duration matches the source's to
  within HALF a frame period** — the `-t` proof. Half, not one: a `shortest=1`
  regression is exactly one frame at any rate, so a one-frame tolerance would
  accept it. Derive the tolerance from the probed fps, not from a literal — a
  hardcoded `0.5 / 30.0` goes silently wrong when the fixture changes.
- **at an integer frame rate**, not only on the 59.94fps golden ride. The
  timebase blow-up fires on exact rate matches, so an NTSC-only proof would have
  missed it entirely (§8).

**Real ffmpeg — pixels** (`tests/integration/test_layouts.py`)
- a pad pixel is the requested colour (sample a corner, assert against the
  colour asked for).
- the same frame rendered with `blur` differs there — otherwise the test cannot
  tell a solid pad from a blurred one, and would pass against the old code.

## 8. Landmines (candidates for design §12)

- **`color` is infinite, and BOTH obvious fixes are wrong.** An unbounded `color`
  behind an `overlay` never ends — measured, 4m12s of output from a 2s source in
  20s of wall clock, still going. `overlay=…:shortest=1` truncates **exactly one
  frame** off every render at any rate, which accumulates straight into
  `check_reel`'s 0.5s length band (~30 episodes at 59.94fps eats all of it).
  Bounding the source with `d={duration}` does not fix the length either (next
  entry). **Bound the OUTPUT: `-t {duration}`.** All three failures are silent in
  the filtergraph string — a command that never returns, a reel that is
  mysteriously short, or a 3-second clip that renders as 1536 seconds.
- **A synthesized source and a decoded one have different timebases, and
  `overlay` inherits the FIRST input's.** `color`'s timebase is `1/r`; a decoded
  mp4 carries its container's — `1/15360` at 30fps. With the synthesized
  background as the overlay's first input, the tail's `fps` filter reads the
  mismatch as a stream longer by exactly `container_tb / fps`: 15360/30 = 512,
  turning a 3s source into **1536s / 46080 frames**. Bounding the source with `d=`
  does not prevent it; bounding the *output* with `-t {duration}` does.

  **The trigger is an exact rate match, NOT a particular frame rate** — this is
  the part that will mislead you. It fires when the emitted `r=` reproduces the
  source's rational rate exactly, so **integer rates (24/25/30/50/60) blow up**
  while NTSC fractional ones do not. The 59.94fps golden fixture blows up too
  when handed `r=60000/1001`; it survives only because `f"{fps:.6g}"` mangles that
  to `59.9401`. So this repo's default fixtures are safe by a **formatting
  accident**, and adding a 29.97fps fixture to "cover another rate" would prove
  nothing. Cover an integer rate, or cover nothing.
- **`proc.run` carried no timeout.** The first filtergraph capable of running
  forever turned a test failure into a hung suite (90s and killed, against a 0.8s
  normal run) — and the machine has no `timeout`/`gtimeout` binary to bound it
  from outside. Subprocess calls now take a generous default timeout that raises;
  an unbounded wait is not a test result.
- **`background_color` reaches an ffmpeg argument.** It carries the same
  injection surface as `border_color` and gets the same guard. A colour string is
  not a safe literal just because it is short.

## 9. Non-goals

- **Gradient.** §7 says "solid/gradient pad"; a gradient is a different
  filtergraph (`gradients` source or a generated overlay) with its own parameters
  (two colours, an angle). Its own slice, if ever — YAGNI today.
- **Auto-derived colour** (dominant / edge colour of the clip). A different
  feature: it needs a probe pass and a decision rule. The explicit field does not
  block it later.
- **`split`** — the one genuinely remaining *layout* (two sources → two rects,
  and it changes the manifest's shape). Excluded by decision.
- **`pan`** — slice B; a generated x(t) motion source, not a layout mode.
- **Any `fit-blur` alias or deprecation path.**

## 10. Doc sync

Living docs updated in the slice's last task:

- **design spec §7** — the layouts table: `fit-solid` **planned → built**, and
  the mode column re-spelled `fit`; the "names are presets" paragraph gains the
  expansion `fit-blur = (fit, blur)`, `fit-solid = (fit, solid)`.
- **design spec §12** — the two landmines from §8.
- **`docs/pipeline-map.md`** — the §7 misc-engine roadmap entry loses
  `fit-solid` and keeps `split` / `pan` / stabilization / the degradation ladder.
- **`docs/build-status.md`** — a Done entry; the next-action list loses
  `fit-solid` from "the remaining layouts".
- **`CLAUDE.md`** — two registry rows (this design, its plan).
- **`SKILLS/edit-plan/SKILL.md`** — the layout vocabulary it offers an author.

Dated specs and plans are **not** edited (§2).
