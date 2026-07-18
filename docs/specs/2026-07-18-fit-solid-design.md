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
color=c={background_color}:s={out_w}x{out_h}:r={fps:.6g}[bg];
[0:v]crop={crop_w}:{crop_h}:x='{xexpr}':y={cy},scale={rw}:{rh}{pad}[fg];
[bg][fg]overlay={ox}:{oy}:shortest=1,{tail}
```

The two graphs differ in shape, and the difference is **caused by the filler** —
`split` exists only to serve blur's second read. That is parameterization, not a
branch: the composite structure (a `[bg]`, a `[fg]`, one `overlay`, the shared
`tail`) is identical. In code this is one helper that returns the `[bg]` producer
and the label `[fg]` reads from; `boxblur`'s radius arithmetic moves inside the
blur arm, so a solid render never computes a blur radius it will not use.

### `shortest=1` is load-bearing

`color` is an **infinite** source. Without `shortest=1` the overlay never sees an
end-of-stream on either input and the encode does not terminate. It is not a
tidiness flag; it is the thing that makes the command finish.

It is proved by a real-ffmpeg test asserting the rendered duration equals the
source duration — not by reading the filtergraph string.

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
- the solid string, whole, including `shortest=1`.
- **the blur string, whole, byte-identical to today's** — the regression pin.
- `fill`'s `-vf` fast path unchanged.

**Unit — the sidecar** (`tests/lib/test_models.py`)
- `PathMeta` round-trips `background`.
- a dict with no `background` key reads as `"blur"` (and still raises
  `RuntimeError` for any *other* missing field — the exemption is one key, not a
  loosening).

**Unit — the advisory check** (`tests/lib/test_reel_final.py`)
- two episodes, same `mode`, different `background` ⇒ the mode penalty applies.
- same `mode`, same `background` ⇒ it does not.

**Real ffmpeg** (`tests/integration/test_layouts.py`)
- a `fit` + `solid` render **terminates and its duration equals the source's** —
  the `shortest=1` proof.
- a pad pixel is the requested colour (sample a corner, assert against the
  colour asked for).
- the same frame rendered with `blur` differs there — otherwise the test cannot
  tell a solid pad from a blurred one, and would pass against the old code.

## 8. Landmines (candidates for design §12)

- **`color` is infinite.** Any overlay against a synthesized source needs
  `shortest=1` (or an explicit `d=`), or the encode never ends. Silent in the
  filtergraph string; visible only as a command that does not return.
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
