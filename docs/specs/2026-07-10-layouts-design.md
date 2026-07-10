# Layouts Design — `fit-blur` and `insert` (spec §7)

_Date: 2026-07-10. Status: approved, ready for a plan._

The engine composes one layout today: `fill` — a canvas-aspect crop that follows
the subject. Spec §7 names five more. This design adds two of them, `fit-blur`
and `insert`, by generalizing the compositor rather than branching it, and closes
a silent-corruption hole the generalization exposes in `check_episode`.

## 1. Goal

Let an episode place a *framed rectangle* of source footage anywhere in the
canvas and fill the remainder, instead of always cropping the source to fill the
canvas edge to edge.

**In scope:** `fit-blur`, `insert`, the `blur` background filler, the geometry
and validation they need, and the `path.meta.json` sidecar that keeps
`check_episode` honest about what was actually cropped.

**Out of scope, each its own cycle:** `fit-solid` (a second filler — one branch
in the background generator), `split` (needs a second `segment`; changes the
manifest's shape, `check_episode`, and the storyboard), `pan` (generated motion,
takes start/end/duration instead of a route), vidstab stabilization, the tracking
degradation ladder, the golden-canon armature, and the executable landmine lint.

## 2. The model: three parameters, not five names

A layout is not a mode with its own code path. It is three independent choices:

1. **What to cut** — a crop aspect and a scale (the fraction of the largest crop
   of that aspect that fits the source).
2. **Where to put it** — a rectangle inside the canvas.
3. **What fills the rest** — a background generator.

The five §7 layouts are presets over these three:

| Layout | crop aspect | rect | background |
|---|---|---|---|
| `fill` (built) | canvas | whole canvas | none — nothing to fill |
| `fit-blur` | source | full width, centred | blur |
| `fit-solid` (later) | source | full width, centred | solid |
| `insert` | explicit | explicit | blur |
| `split` (later) | — | two rects, two sources | pad |
| `pan` (later) | canvas | whole canvas | none |

**Tracking is not a property of the layout.** It is a consequence of geometry:
horizontal freedom is `src_w - crop_w`. When the crop is as wide as the source,
freedom is zero and `compute_path` degenerates on its own — `clamp(x, 0, src_w -
crop_w)` is identically `0`. No special case is written for it. When
`crop_scale < 1.0`, freedom returns and the subject is followed, in *any* layout:
a `fit-blur` at `crop_scale=0.9` crops slightly for composition and tracks.

### 2.1 `LayoutSpec` (new, `scripts/lib/models.py`)

A config-spec by the repo convention: validates in `__post_init__`, raises
`ValueError` with a remedy. It lives in `models.py`, beside the other
config-specs and *above* `ReframeSpec` — which gains a `layout: LayoutSpec`
field. Putting it in `layout.py` would make `models → layout → models` an
import cycle, since `layout.resolve()` needs `Delivery`.

```python
@dataclass
class LayoutSpec:
    mode: str                                        # fill | fit-blur | insert
    crop_aspect: str | tuple[int, int] = "canvas"    # canvas | source | (w, h)
    crop_scale: float = 1.0                          # (0.0, 1.0]
    rect: tuple[float, float, float] | None = None   # (x, y, w), canvas fractions
    background: str = "blur"                         # v1: blur only
    border_px: int = 0                               # 0 = no border
    border_color: str = "white"                      # ffmpeg colour name or hex
```

**The border is chrome, and it changes what `rect_px` means.** `rect` is the
*outer* card. The border is drawn inside it, so the source pixels land in a
*content* rect inset by `border_px` on every side, and it is the **content**
that preserves the crop aspect:

```
ow = even(rect_w * out_w)          cw = ow - 2*border_px
ch = even(cw * crop_h / crop_w)    oh = ch + 2*border_px
rect_px = (ox + border_px, oy + border_px, cw, ch)
```

`rect_px` — in `ResolvedLayout` and in the `path.meta.json` sidecar — is the
content rect, never the outer card. Were it the card, `storyboard` would place
the hero marker on the border and `check_episode` would divide by a width that
includes chrome. At `border_px = 0` every formula above collapses to the
borderless one, and the emitted filtergraph is byte-identical.

`border_px` may be any non-negative int: `ow` is already even, so `cw = ow -
2*border_px` is even whatever the border's parity, and ffmpeg accepts odd `pad`
and `overlay` offsets under `yuv420p` without complaint. `fill` refuses a border
outright — it covers the canvas edge to edge, so a border has nothing to sit on;
a bordered frame is an `insert`.

`rect` carries **three** numbers, not four. Its height is derived from its width
and the crop aspect. A rectangle cannot disagree with what is placed inside it,
because the disagreement is inexpressible — a whole class of validation is
removed by construction rather than by a check. `rect=None` means full width,
vertically centred.

**Validation (raises, with remedy):**

- `mode` in `("fill", "fit-blur", "insert")`.
- `background` in `("blur",)` — `solid` lands with `fit-solid`.
- `0.0 < crop_scale <= 1.0`.
- `crop_aspect` is `"canvas"`, `"source"`, or a positive `(w, h)` pair.
- `mode == "fill"` ⇒ `crop_aspect == "canvas"` and `rect` is `None` or `(0, 0, 1)`;
  `background` is ignored (nothing is left to fill) and is not validated against it.
- `mode == "fit-blur"` ⇒ `rect is None`.
- `mode == "insert"` ⇒ `rect is not None`.
- `rect` fractions are in `[0, 1]`, `w > 0`, and `x + w <= 1`. The derived height
  must satisfy `y + h <= 1` — checked once the canvas aspect is known, in
  `resolve()` below, not in `__post_init__` (the spec alone does not know the canvas).

The `mode` constraints keep the manifest honest: a `fill` with a small `rect` is
an `insert` and must say so.

## 3. Geometry

Two pure functions join `scripts/lib/geometry.py`:

```python
def crop_for(aspect: tuple[int, int], scale: float, src_w: int, src_h: int) -> tuple[int, int]
def freedom(crop_w: int, src_w: int) -> int
```

`crop_for` returns the largest crop of `aspect` that fits `(src_w, src_h)`,
multiplied by `scale`, floored to `int`. **The crop is not forced even** — ffmpeg's
`crop` filter accepts odd sizes, and today's `fill` genuinely cuts 405px wide.
Evenness is a constraint on what is *scaled and encoded*, not on what is cut, and
it is applied at the output. `crop_size` (today's, canvas-aspect) stays as-is and
becomes a caller of `crop_for`.

### 3.1 Native size: never upscale the subject

`Delivery.dims(crop_w, crop_h)` sizes the output from the crop today. That is
correct only while crop aspect equals canvas aspect. A `fit-blur` crops 16:9 and
must deliver 9:16.

The rule: **the composite is as large as it must be for the inserted frame to sit
at its native resolution.**

```
canvas_w = crop_w / rect_w                    # float
canvas_h = canvas_w * canvas_aspect_h / canvas_aspect_w
```

Both stay floats here. Evenness is applied **to each side independently**, at the
output, by `Delivery` — which already floors to even. Deriving one side from the
already-evened other would drift: `fill` gives `canvas = (405.0, 720.0)`, and
`even(405) * 16/9` is 718, not 720.

Odd dimensions plus `yuv420p` make libx264 fail with "width not divisible by 2"
(§12), and floor-truncated crop widths are odd half the time — hence the flooring
happens once, on the delivered dimensions.

`Delivery` is untouched: it stays a policy over the finished composite, and now
receives canvas dimensions instead of crop dimensions. For `fill` these are the
same numbers, which is why the fast path survives unchanged — and they are the
crop's *own* dimensions, not a re-derivation. `fill`'s crop already carries the
canvas aspect, so `canvas = (crop_w, crop_h)` exactly. Recomputing `canvas_h`
from `crop_w` drifts a 21:9 crop of 4K from 1644 to 1646.

### 3.2 A native canvas can explode

`canvas_w = crop_w / rect_w` reads innocently, but a *small* rect does not make a
small card — it makes an enormous canvas, because the card is pinned at native
resolution and the canvas grows around it. On the golden fixture, `insert` with a
1:1 crop:

| `rect_w` | canvas | |
|---|---|---|
| 0.9 | 800×1422 | 1.1 Mpx |
| 0.5 | 1440×2560 | 3.7 Mpx |
| 0.2 | 3600×6400 | 23 Mpx |
| 0.05 | 14400×25600 | 369 Mpx |
| 0.02 | 36000×64000 | **2304 Mpx** |

Nothing about this fails on its own: ffmpeg accepts the command and dies in swap
an hour later, naming none of it. So `resolve()` refuses any side past
`MAX_SIDE = 8192`, with a remedy that names the cause and the fix — widen `rect`,
or pin the output with `delivery: short_edge:N` / `exact:WxH`. The limit sits
immediately after `Delivery.dims`, before any card arithmetic runs inside a
canvas that should not exist.

**Worked examples** on the golden fixture (`golden_ride.mp4`, 1280×720):

| Layout | crop | freedom | canvas (float) | delivered `native` |
|---|---|---|---|---|
| `fill` | 405×720 | 875 | 405.0×720.0 | **404×720** — exactly today's output |
| `fit-blur` | 1280×720 | 0 | 1280.0×2275.6 | 1280×2276 — subject native, only the blurred background is upscaled |
| `insert`, `rect=(0.05, 0.25, 0.90)`, aspect `1:1` | 720×720 | 560 | 800.0×1422.2 | 800×1422 — card is 1:1, tracked, scale is identity |

### 3.2 `resolve()`

`layout.resolve(spec: LayoutSpec, canvas: tuple[int, int], src: tuple[int, int])`
returns a frozen `ResolvedLayout` — crop dims, freedom, canvas pixel dims, rect in
pixels, and whether the fast path applies. It raises when the derived rect height
overflows the canvas (`y + h > 1`), with the remedy naming `rect` and the aspect.

## 4. Render

### 4.1 The fast path is byte-identical

When the rect covers the canvas and the crop aspect equals the canvas aspect,
`reframe` emits exactly today's single `-vf` chain:

```
crop=CW:CH:x='<x(t)>':y=CY,scale=OW:OH,colorchannelmixer=...,fps=F,format=yuv420p
```

No `split`, no `overlay`. This is not an optimization; it is how the golden
fixture is protected. A whole-string unit test pins this chain so a refactor
cannot change it silently.

### 4.2 The composite path

```
[0:v]split=2[a][b];
[a]scale=CWpx:CHpx:force_original_aspect_ratio=increase,crop=CWpx:CHpx,boxblur=R:2[bg];
[b]crop=cw:ch:x='<x(t)>':y=cy,scale=rw:rh[fg];
[bg][fg]overlay=RX:RY,colorchannelmixer=...,fps=F,format=yuv420p
```

- `x(t)` is the existing `_xexpr` output — piecewise-linear over Douglas-Peucker
  knots, capped at ~80 knots (§12: the ffmpeg expression parser chokes past that).
  It lives in source coordinates, and `crop` in the composite path applies to the
  source stream, so it is reused unchanged.
- `R = max(2, canvas_w_px // 60)`. Tying the radius to canvas width keeps the
  background equally soft at 1080p and 4K; a constant radius is nearly sharp on 4K.
- `colorchannelmixer` sits **after** `overlay`, so the normalization covers the
  background too — which is correct, the background is made of the same frame.
- `lutrgb` appears nowhere (§12: black frames). A unit test asserts its absence
  in the emitted graph.

## 5. The sidecar, and the bug it fixes

`check_episode.run` re-derives the crop width itself:

```python
crop_w, _ = geometry.crop_size(spec.canvas[0], spec.canvas[1],
                               spec.src_dims[0], spec.src_dims[1])
```

That holds only while every layout is `fill`. Under `fit-blur` it returns 405
where `reframe` actually cut 1280; `checks.on_line` then divides by a width that
was never used and reports a verdict about a composition that never happened. It
does not crash. It quietly lies — the exact class of defect the core plan's
contract note anticipated ("or better: extend reframe to write canvas/src_dims
into a path sidecar that check_episode reads back").

**Fix.** `reframe` writes `path.meta.json` beside `path.json`, mirroring the
convention `track.py` already uses for `route.meta.json`. A new wire-contract in
`models.py`:

```python
@dataclass
class PathMeta:
    mode: str
    crop_w: int
    crop_h: int
    src_dims: tuple[int, int]
    canvas: tuple[int, int]
    out_dims: tuple[int, int]
    rect_px: tuple[int, int, int, int]
    freedom: int
```

It owns its JSON round-trip (`to_dict`/`from_dict`), and a round-trip test covers
it, as the testing guide requires of every wire contract.

`check_episode.run` derives nothing. It reads the sidecar, and fails loud with a
remedy when the file is absent ("re-run reframe — it writes path.meta.json beside
path.json"). `CheckSpec` **loses** `canvas` and `src_dims`; the CLI loses
`--canvas` and `--src-dims`. Their defaults (`1920x1080`) were, in the contract
note's words, "silently wrong on 4K/59.94 footage". They stop existing: the value
now has exactly one source, the code that did the cropping.

## 6. Checks: freedom decides, not the layout name

The composition check keys off geometry:

- `freedom > 0` → the numeric check runs as today (`on_line` / `centered`).
- `freedom == 0` → `CheckResult(passed=None, {"status": "editorial-only",
  "reason": "no horizontal freedom"})`.

Failing a rule nobody can obey is wrong; silently passing it is worse. `passed=None`
already means "editorial" in `Report.overall`, so nothing downstream changes. The
rule is stated over geometry rather than over `mode`, so it stays correct when
`split` and `pan` arrive.

`jitter`, `continuity`, `length`, and `black_frames` are unaffected. On a
zero-freedom path `jitter` trivially passes (a constant path has no reversals).

## 7. Validation boundary

Unchanged in kind: the manifest gate is **soft** (`validate()` accumulates problem
strings → `needs_input`), everything below is **hard** (raises).

- `manifest.LAYOUTS_SUPPORTED` becomes `("fill", "fit-blur", "insert")`.
- `Manifest` gains `crop_aspect`, `crop_scale`, `rect`, `background` as optional
  fields. JSON arrays become tuples on the way in, as `hero` already does.
- One new soft refusal: `composition == "lead"` together with zero horizontal
  freedom — that is, `crop_scale == 1.0` and `crop_aspect == "source"`. This is
  decidable without probing the file, so it is caught before YOLO runs, not after.
  Remedy: "set `crop_scale` below 1.0, or `composition: break`".

`orchestration.py` does not change. `detect_contradictions` keeps comparing the
manifest against what the tracker saw; the zero-freedom case is a manifest-internal
contradiction and belongs to the gate.

`process_episode` builds a `LayoutSpec` from the manifest, hands it to
`ReframeSpec` (which gains a `layout: LayoutSpec` field), and builds a `CheckSpec`
with two fields fewer.

## 8. Errors

Every failure names its remedy, per the fail-loud contract:

| Condition | Where | Behaviour |
|---|---|---|
| unknown `mode` / `background`, bad `crop_scale` / `crop_aspect` / `rect` | `LayoutSpec.__post_init__` | `ValueError` + remedy |
| derived rect height overflows the canvas | `layout.resolve` | `ValueError` naming `rect` and the aspect |
| `lead` with zero freedom | `manifest.validate` | problem string → `needs_input` |
| `path.meta.json` missing | `check_episode.run` | `RuntimeError` + "re-run reframe" |
| `insert` without `rect` | `LayoutSpec.__post_init__` | `ValueError` + remedy |

## 9. Testing

TDD throughout; whole-object asserts; real ffmpeg for anything that emits a
filtergraph.

**Unit.** `LayoutSpec` validation, one test per refusal, each asserting the remedy
text. `crop_for` / `freedom` / native-size math, including the even-dimension
floor. `PathMeta` JSON round-trip. `check_episode` with a missing sidecar, and with
`freedom == 0` (composition check is editorial, `overall` still true).

**Filtergraph.** The `fill` chain compared **whole-string** against a pinned
expected value — the regression guard for the golden fixture. The `fit-blur` graph
likewise. `assert "lutrgb" not in graph` on both.

**Integration** (`@pytest.mark.integration`, real ffmpeg, `golden_ride.mp4`):
`fit-blur` produces a 1280×2276 composite; `insert` with `rect=(0.05, 0.25, 0.90)`
and aspect `1:1` produces 800×1422; boundary frames of both are not black (§9);
and `process_episode` runs end to end from a `layout: fit-blur` manifest through
to a report.

Assertions are on delivered dimensions, never on a hardcoded resolution.

## 10. Landmines respected (§12)

- `-ss` after `-i` — this design adds no seek; `extract.py` keeps owning it.
- `lutrgb` banned — `colorchannelmixer` only, asserted in the graph tests.
- Even output dimensions for **every** canvas, enforced in the native-size math.
- Douglas-Peucker knot cap unchanged and reused, not re-implemented.
- Wade-in/out shots are never stabilized — no stabilization is added here.

## 11. Documentation to sync in the same commits

`docs/specs/2026-07-05-montage-skillset-design.md` §7 (the layout table gains the
three-parameter model), `docs/build-status.md`, the plan's checkboxes, and the
`LAYOUTS_SUPPORTED` refusal text in `manifest.py`.
