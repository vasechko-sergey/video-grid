# Titles animations — design

**Status:** designed 2026-07-29 (slice 3 of the parked-run campaign, after
track-stitch and path-quality). Port of the parked `4841dd3` `lib/titles.py` hunk
(“word reveal / stair / fade”), written live during the first real montage run
(2026-07-22..24, 99 clips) and never designed. Faithful port — the constants were
field-measured against that footage; we do not re-derive them.

Stage **§5.16** (titles). This slice adds *motion and colour* to the on-screen text
that already burns into `deliver`’s one encode; it does not change *when* or *whether*
titles are authored (that stays the titles SKILL’s judgment).

---

## §1 Why

The first montage run shipped titles that could only hard-cut a whole line into
place in one white block, laid out against the generic safe zone. Three gaps
surfaced, from one run:

1. **No entrance.** A hook that *pops* whole reads as a slide, not a reveal. The
   run wanted a hook that builds word-by-word and titles that ramp in and out
   rather than blink. drawtext can express both inside the same call it already
   makes — a fade is an `alpha=` expression, a word reveal is one drawtext per word
   — so this is a render change, not a new stage.

2. **Titles laid out against the wrong safe zone.** `check_reel` judges the
   *subject* against `safe_zone_for(platform)` (Reels keeps 16 % clear at the
   bottom, TikTok 18 %, the generic table only 12 %). Titles judged *themselves*
   against `default_zone()`. The two halves disagreed about where “safe” is, and
   only the picture half was right: a bottom title laid against the generic table
   renders **under the app’s own caption and button chrome** on exactly the
   platforms this repo delivers to. This is a silent framing bug — nothing fails,
   the title just lands in the dead band.

3. **White is not always legible, and one size does not fit every face.** A warm
   tint reads far better over cold water than white does — that is a look, not a
   fix — and a script face with tall ascenders needs its line spacing tightened.
   `color`, `scale`, and `line_spacing` arrived alongside the reveal machinery
   (the staircase drop math *needs* `scale` and `line_spacing`); they are folded
   in here because they are inseparable from it, not as scope creep.

Defects 1 and 3 are the animation charter. Defect 2 is a coupled bug fix: its
patch lives in the exact `build_filterchain`/`deliver` lines the animation port
rewrites, so landing it separately would re-touch and re-review the same hot `y=`
line twice. Coupled → one slice; orthogonal → out (see §2).

## §2 Scope

**In:**

- Six new `Title` fields (`fade`, `reveal`, `reveal_step`, `color`, `scale`,
  `line_spacing`) with validate-and-raise refusals, `to_dict` round-trip.
- The render machinery: `_steps`, `_measure` (PIL font metrics), `_layers`
  (per-word x/y baked as fractions of `h`), and `build_filterchain`’s per-layer
  loop with the `fade=0` no-alpha fast path.
- The coupled safe-zone fix: `y_exprs(platform)` replacing the `_Y_EXPR` module
  constant, threaded `deliver(platform=…)` + `--platform` CLI, one-line
  `build_reel` wiring (`platform=rm.platform`).
- `skills/titles/SKILL.md` guidance on the six fields and the refusal math.

**Out (orthogonal — not this slice):**

- The parked `deliver --audio` CLI fix (a hand re-deliver dropping the stem
  silently). Real bug, but in `deliver.main`’s audio path, unrelated to titles.
  Its own micro-slice.
- `scripts/titles.py build_titles` — the mechanical drafter stays dumb. All six
  fields default to the historical behaviour, so its output is unchanged; which
  title animates how is the titles SKILL’s judgment, exactly as its docstring
  already says.
- `check_reel` — titles burn into `deliver`’s encode *after* `check_reel` has run
  on the untitled master. Nothing grades the animation. The safe-zone fix only
  makes the titles *agree* with a check that already exists; it adds no check.

## §3 The units (verbatim port)

### §3.1 Module constants (`scripts/lib/titles.py`)

```python
REVEALS: tuple[str, ...] = ("none", "word", "stair")

FONTSIZE_DIV = 18      # drawtext fontsize is h/FONTSIZE_DIV — one spelling, two readers
                       # (build_filterchain's own fontsize=, and the width arithmetic a
                       # word reveal needs, which is only resolution-independent because
                       # every width scales with the same h)
_MEASURE_AT = 100      # px font size the metrics are taken at, then scaled by h
LINE_SPACING = 1.15    # multiples of the font size between staircase lines
```

The existing chain hardcodes `fontsize=h/18`; the port replaces the literal `18`
with `FONTSIZE_DIV` so the fontsize and the reveal’s width arithmetic read the
same divisor (§4 invariant 5).

### §3.2 `Title` — six fields + refusals

New fields, each defaulting to the historical behaviour:

```python
    fade: float = 0.0         # seconds to ramp alpha in AND out; 0.0 = hard cut
    reveal: str = "none"      # "none" | "word" | "stair"
    reveal_step: float = 0.35 # seconds between word entrances (ignored when reveal="none")
    color: str = "white"      # drawtext fontcolor: name, 0xRRGGBB, or either with @alpha
    scale: float = 1.0        # multiplies the h/FONTSIZE_DIV default size
    line_spacing: float = LINE_SPACING  # multiples of the font size between staircase lines
```

Refusals added in `__post_init__` (validate-and-raise, the config-spec house
rule; bool rejected before the numeric check, as every spec in this repo does):

- `fade`: a finite number `>= 0`.
- **`2 * fade > dur` → refuse.** Two ramps inside one window means anything past
  `dur/2` has the in-ramp still climbing when the out-ramp starts falling: the
  title never reaches full opacity, so the author’s chosen colour is never the
  colour on screen. Refused, not clamped — a silently-shortened fade is the
  invisible-creative-change class (§4 invariant 3).
- `color`: a non-empty string.
- `scale`: a finite number in `(0, 5]`.
- `line_spacing`: a finite number in `[0.5, 3]` (below ~0.5 the lines overlap
  into illegibility).
- `reveal` in `REVEALS`; `reveal_step` a finite number `> 0`.
- **`reveal in ("word","stair")` and `(n-1)*reveal_step + 2*fade > dur` → refuse**
  (`n = len(_steps(self))`). The last word has to arrive, hold, and still leave
  inside the window; if it cannot, the line is never once whole on screen — the
  one thing a word reveal exists to build up to. Refused, not compressed.

`to_dict` gains the six keys. `from_dict` is unchanged: `cls(**d)` picks the new
keys up, and because every default is the historical value, a TITLES.json written
before this slice round-trips and renders unchanged.

### §3.3 `_steps` — how a reveal chunks

```python
def _steps(t: Title) -> list[str]:
    if t.reveal == "stair":
        return [ln.strip() for ln in t.text.splitlines() if ln.strip()]
    return t.text.split()
```

`"word"` splits on whitespace — one word per entrance, all on one line. `"stair"`
splits on **newlines**, so the author groups the words themselves
(`"salt,\nsun\n& you"` is three steps). Splitting a staircase on spaces would
force one word per line and make a four-word title a quarter-frame tall with no
way to say otherwise.

### §3.4 `_measure` — font metrics (why the ink-box top matters)

```python
def _measure(font_path: str, text: str) -> tuple[float, float]:
    """(advance width, ink-box top) for `text` at _MEASURE_AT px, in px."""
    from PIL import ImageFont      # local: only a word reveal needs metrics
    f = ImageFont.truetype(font_path, _MEASURE_AT)
    return float(f.getlength(text)), float(f.getbbox(text)[1])
```

drawtext places the **ink box** of whatever string it is given at `y`, so a word
of pure x-height letters (`"sun"`) and a word with ascenders and a comma
(`"salt,"`) do not share a baseline when each is drawn as its own layer at one
`y`. Shifting each layer by its own box top relative to the full line’s box top
puts every word back on the line’s baseline. PIL is already a dependency (12.3.0);
the import is local so only a reveal pays for it, and a test injects a stub so the
unit suite needs no font on disk (§5).

### §3.5 `_layers` — one drawtext per step, each at its FINAL x

```python
def _layers(t: Title, font: str, measure) -> list[tuple[str, float, str, str]]:
    if t.reveal == "none":
        return [(t.text, t.start, "(w-tw)/2", "")]
    k = t.scale / (FONTSIZE_DIV * _MEASURE_AT)   # measured px -> multiples of h
    steps = _steps(t)
    joined = " ".join(steps)
    total, top_full = measure(font, joined)
    layers = []
    for j, step in enumerate(steps):
        prefix = measure(font, " ".join(steps[:j]) + " ")[0] * k if j else 0.0
        drop = (measure(font, step)[1] - top_full) * k
        if t.reveal == "stair":
            drop += j * t.line_spacing * t.scale / FONTSIZE_DIV
        layers.append((step, t.start + j * t.reveal_step,
                       f"(w-{total * k:.6f}*h)/2+{prefix:.6f}*h",
                       f"+{drop:.6f}*h" if drop >= 0 else f"-{-drop:.6f}*h"))
    return layers
```

`reveal="none"` is one layer, centred by ffmpeg’s own `tw` — unchanged. For a
reveal, each word lands where it will sit in the **finished** line: centring each
by `(w-tw)/2` would put every one in the middle and shuffle the line sideways on
each entrance (a layout bug, not a reveal). Widths are measured here and baked
into the x expression as fractions of `h`: fontsize is `h/FONTSIZE_DIV`, so a
width measured at `_MEASURE_AT` px becomes `width * (h/FONTSIZE_DIV) / _MEASURE_AT`
— resolution-independent, the property that lets `titles.py` keep knowing nothing
about the canvas size (§4 invariant 5). `stair` keeps the same x and drops a line
per step, so the block spans exactly the single line’s width while the eye follows
the left-to-right path the words arrive in.

> Correction to the parked source: its `_layers` return annotation reads
> `list[tuple[str, float, str]]` but the body yields four-tuples (the y-drop was
> added without updating the annotation). The port ships the correct
> `list[tuple[str, float, str, str]]`.

### §3.6 `y_exprs` — the coupled safe-zone fix

```python
def y_exprs(platform: str = "") -> dict[str, str]:
    """Per-position y expressions, keyed off the PLATFORM's safe zone (§5.13/§5.16)."""
    z = safezones.safe_zone_for(platform)
    return {"top": f"h*{z.top}",
            "center": "(h-th)/2",
            "bottom": f"h-th-h*{z.bottom}"}
```

Replaces the `_Y_EXPR` module constant, which was frozen at `default_zone()`. An
empty/unknown platform still resolves to the generic zone, so a delivery that
never named one is unchanged. This is the exact spelling `check_reel` uses for the
subject (`safezones.safe_zone_for(platform)`), so the two halves can no longer
disagree (§4 invariant 4).

### §3.7 `build_filterchain` — per-layer loop + fade fast path

```python
def build_filterchain(titles: Titles, work_dir: str, resolve=resolve_font,
                      platform: str = "", measure=None) -> str:
    if not titles.items:
        return ""
    work = Path(work_dir); work.mkdir(parents=True, exist_ok=True)
    y_expr = y_exprs(platform)
    measure = measure or _measure
    parts: list[str] = []
    for i, t in enumerate(titles.items):
        font = resolve(t.font)
        style = _STYLE_FRAGMENTS[t.style]
        end = t.start + t.dur
        for j, (text, appears, x_expr, y_drop) in enumerate(_layers(t, font, measure)):
            tf = work / (f"title_{i}.txt" if t.reveal == "none" else f"title_{i}_{j}.txt")
            tf.write_text(text)
            alpha = ""
            if t.fade > 0:
                alpha = (f"alpha='max(0,min(1,min((t-{appears})/{t.fade},"
                         f"({end}-t)/{t.fade})))':")
            parts.append(
                f"drawtext=fontfile='{font}':textfile='{tf}':"
                f"fontsize=h*{t.scale / FONTSIZE_DIV:.6f}:"
                f"fontcolor={t.color}:x={x_expr}:y={y_expr[t.pos]}{y_drop}:"
                f"{alpha}"
                f"{style + ':' if style else ''}"
                f"enable='between(t,{appears},{end})'")
    return ",".join(parts)
```

`min()` of the two ramps *is* the trapezoid; `max(0, …)` only guards the instants
`enable` already excludes. **`fade == 0` emits no `alpha=` at all** — the fast path
that keeps a title authored before this field existed producing the same drawtext
(§4 invariant 1). `textfile=` still dodges filtergraph escaping of `:`/apostrophes,
now generalized to one file per layer; `fontfile`/`textfile` are single-quoted and
carry no apostrophe (a resolved system/cask font path and a skill-controlled
work-dir — draft’s assumption, unchanged).

### §3.8 Wiring

- `deliver(..., platform: str = "")` passes `platform` to `build_filterchain`;
  a `--platform` CLI arg (the safe-zone table key — `reel`/`tiktok`/`shorts`/…).
- `build_reel`’s existing `deliver.deliver(master, REEL_H264, out_dir,
  rm.changelog, report, audio=audio, titles=titles)` gains `platform=rm.platform`.
  `rm.platform` already exists on the manifest (`build_reel` already passes it to
  `check_reel`), so this is the whole path — one line.

## §4 Invariants (each mutation-proven — neutralize the guarded line, a named test flips red)

1. **`fade == 0` emits no `alpha=`.** The historical no-fade path is string-
   preserving. *Mutation:* emit an `alpha=` unconditionally → a “no alpha at
   fade 0” test flips.
2. **A reveal word lands at its FINAL x — the line never re-centres.** x is baked
   from measured widths, not `(w-tw)/2` per word. *Mutation:* center each layer by
   `(w-tw)/2` → a “word x carries the measured prefix / line stays put” test flips.
3. **Refuse, never clamp.** `2*fade > dur` and the reveal-doesn’t-fit inequality
   both `raise`. *Mutation:* turn either refusal into a silent clamp → the
   corresponding refusal test flips.
4. **Titles lay out against the SAME zone `check_reel` judges the subject
   against.** `y_exprs` calls `safe_zone_for(platform)`. *Mutation:* revert to
   `default_zone()` → a “bottom y follows the platform zone, not the generic one”
   test flips.
5. **Resolution independence.** Every width and drop is scaled by `h` through the
   single `FONTSIZE_DIV`/`_MEASURE_AT` divisor, so a reveal’s layout is correct at
   any canvas and `titles.py` reads no canvas dims. *Mutation:* drop the `*h` (bake
   an absolute px) → a “same layers at two heights” test flips.

## §5 Testing

- **Unit (`tests/lib/test_titles.py`, stubbed `measure`):** the six fields
  round-trip through `to_dict`/`from_dict`; each refusal raises with its message
  (fade-past-half, reveal-doesn’t-fit, `scale`/`line_spacing`/`reveal_step`
  bounds, bad `reveal`, empty `color`); `fade=0` produces no `alpha=` substring;
  a `reveal="word"` title’s layer x-expressions carry the measured prefix and the
  line’s total width (injected stub returns known widths); `reveal="stair"` drops
  a line per step and splits on newlines; `y_exprs("reel")["bottom"]` differs from
  `y_exprs("")["bottom"]`; empty `Titles` → `""`.
- **`tests/lib/test_deliver.py`:** `deliver(..., platform="reel")` lays a bottom
  title against the reel zone (the chain contains the reel `bottom` y-expr);
  default platform unchanged.
- **Real-ffmpeg golden (`tests/integration/`):** a `Titles` with a `fade` and a
  `reveal="word"` burns into a real encode on the baseline ffmpeg (libfreetype
  present) — the encode runs, the drawtext lands, the fade alpha and the per-word
  x-offsets are present in the emitted `-vf`. Mirrors the existing titles golden
  (TT Task 8).
- **Mutation battery:** one probe per §4 invariant plus the two refusal
  boundaries; every probe must flip a *named* test red, then be restored.

## §6 Landmines

- **`fade=0` fast path is an anti-regression pin** — the no-alpha branch is the
  only thing keeping a pre-existing TITLES.json’s render unchanged. A refactor that
  always emits `alpha=` is a silent creative change to every un-faded title.
- **`textfile=` dodges filtergraph escaping** (§12) — now one file per layer; the
  free text never touches the filtergraph string.
- **drawtext needs libfreetype** — the baseline `ffmpeg-full` carries it (ffmpeg
  baseline slice). The unit suite injects a stub `measure` so it needs no font on
  disk; only the integration golden touches a real font.
- **`_measure` needs a real, resolvable font** — `resolve_font` returns a real
  path on the baseline (curated fonts, baseline since 2026-07-20); a word reveal
  over an unresolvable font would raise from PIL, loud, not silent.

## §7 File map + the honest byte-identical claim

**Modify:** `scripts/lib/titles.py` (fields + machinery + `y_exprs`),
`scripts/deliver.py` (`platform` param + `--platform`), `scripts/build_reel.py`
(one line: `platform=rm.platform`).
**Test:** `tests/lib/test_titles.py`, `tests/lib/test_deliver.py`,
`tests/integration/` (titles golden).
**Skill/docs:** `skills/titles/SKILL.md`; `docs/build-status.md`,
`docs/pipeline-map.md`, `CLAUDE.md` registry row, this design’s Status line.

**Byte-identical — pixel-identical, NOT string-identical.** A default `Title`
(`fade=0`, `reveal="none"`, `color="white"`, `scale=1.0`,
`line_spacing=1.15`) with an empty platform renders the **same pixels** it does
today, but its filterchain *string* changes in two spellings:

- `fontsize=h/18` → `fontsize=h*0.055556`. Numerically `1/18 = 0.0555…`; rounded to
  six places the two differ by <0.001 px and ffmpeg rounds fontsize to an integer,
  so the rendered size is identical — but the literal string is not.
- The `_Y_EXPR` module constant becomes the `y_exprs()` function; `y_exprs("")`
  returns the identical generic-zone expressions the constant held.

The `fade=0` no-alpha branch *is* string-preserving; the two spellings above are
the only default-path string changes. Exactly **two** unit assertions re-pin
(`test_build_filterchain_positions_and_styles`’ `"fontsize=h/18"` literal, and the
`titles._Y_EXPR[...]` assertions → `titles.y_exprs()[...]` plus a platform
variant). **No integration golden pins the filterchain string**, so the render
goldens do not move. Do not claim a string-level byte-identity in the commit — the
honest claim is pixel-identical defaults with a re-spelled (equivalent) fontsize
and a constant-turned-function, both proven by the re-pinned unit assertions.
