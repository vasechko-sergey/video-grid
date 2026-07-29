# Titles animations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the parked `4841dd3` titles hunk faithfully — word/stair reveal +
fade + colour/scale/line-spacing on the `deliver`-burned drawtext, plus the coupled
safe-zone-per-platform fix — behind byte-identical defaults.

**Architecture:** All rendering lives in `scripts/lib/titles.py`; the six new
`Title` fields default to the historical behaviour, so a pre-existing TITLES.json
renders pixel-identically. `build_filterchain` grows a per-layer loop (`_layers`
bakes each reveal word's final x/y as fractions of `h`; `_measure` reads font
metrics), a `fade=0` no-alpha fast path, and a `platform` argument that routes the
`y` positions through `safe_zone_for(platform)` — the same table `check_reel`
judges the subject against. `deliver` threads `platform`; `build_reel` passes
`rm.platform`. `build_titles` and `check_reel` are untouched.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), pytest (`pythonpath = .`, run
scripts as modules), ffmpeg via `scripts/lib/ffbin` (drawtext needs libfreetype —
baseline `ffmpeg-full` carries it), Pillow (`PIL.ImageFont`, already a dependency).

**Design:** `docs/specs/2026-07-29-titles-animations-design.md` (§3 has the verbatim
units; §4 the mutation-proven invariants; §7 the honest byte-identical claim).

**Reference values (measured — do not re-derive):**
- `1.0 / 18 = 0.055556` (`fontsize=h*{scale/18:.6f}` at `scale=1.0`); `2.0/18 = 0.111111`.
- Safe-zone bottoms: generic/`""` `0.12`, `reel`(→`reels`) `0.16`, `tiktok` `0.18`, `shorts` `0.14`; tops: generic `0.08`.
- `LINE_SPACING = 1.15`; staircase per-step drop `= j * line_spacing * scale / 18` → `1.15/18 = 0.063889` per step at `scale=1.0`.

**Standing constraints:** commit per task (separate follow-up commits for review
fixes — never `--amend`); do NOT run installers/`setup.sh`; every guard gets a
mutation check (neutralize the line, confirm a *named* test flips red, restore).

---

### Task 0: constants + `Title` six fields + `_steps` + refusals

**Files:**
- Modify: `scripts/lib/titles.py` (constants after `STYLES`; six fields after `style`; refusals in `__post_init__`; `to_dict`; `_steps` at module end)
- Test: `tests/lib/test_titles.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/lib/test_titles.py`:

```python
def test_title_animation_defaults_and_roundtrip():
    t = Title(text="Hi", start=0.0, dur=2.0)
    assert (t.fade, t.reveal, t.reveal_step) == (0.0, "none", 0.35)
    assert (t.color, t.scale, t.line_spacing) == ("white", 1.0, 1.15)
    assert Title.from_dict(t.to_dict()) == t          # 12-key round-trip


@pytest.mark.parametrize("kw, msg", [
    (dict(text="x", start=0.0, dur=1.0, fade=0.6), "never reach full opacity"),
    (dict(text="x", start=0.0, dur=1.0, fade=-0.1), "fade"),
    (dict(text="x", start=0.0, dur=1.0, fade=True), "fade"),
    (dict(text="x", start=0.0, dur=1.0, color=" "), "color"),
    (dict(text="x", start=0.0, dur=1.0, scale=0.0), "scale"),
    (dict(text="x", start=0.0, dur=1.0, scale=6.0), "scale"),
    (dict(text="x", start=0.0, dur=1.0, scale=True), "scale"),
    (dict(text="x", start=0.0, dur=1.0, line_spacing=0.4), "line_spacing"),
    (dict(text="x", start=0.0, dur=1.0, line_spacing=3.1), "line_spacing"),
    (dict(text="x", start=0.0, dur=1.0, reveal="fly"), "reveal"),
    (dict(text="x", start=0.0, dur=1.0, reveal_step=0.0), "reveal_step"),
    (dict(text="x", start=0.0, dur=1.0, reveal_step=True), "reveal_step"),
    (dict(text="a b c d", start=0.0, dur=1.0, reveal="word", reveal_step=0.5),
     "would still be arriving"),
])
def test_title_animation_validation_fails_loud(kw, msg):
    with pytest.raises(ValueError, match=msg):
        Title(**kw)


def test_title_reveal_that_fits_is_accepted():
    # 3 words, step 0.4 → need (3-1)*0.4 = 0.8s <= dur 2.0s
    Title(text="a b c", start=0.0, dur=2.0, reveal="word", reveal_step=0.4)


def test_steps_word_splits_on_whitespace():
    from scripts.lib.titles import _steps
    assert _steps(Title("salt sun you", 0.0, 2.0, reveal="word")) == ["salt", "sun", "you"]


def test_steps_stair_splits_on_newlines_and_strips():
    from scripts.lib.titles import _steps
    t = Title("salt,\nsun\n& you", 0.0, 3.0, reveal="stair", reveal_step=0.5)
    assert _steps(t) == ["salt,", "sun", "& you"]
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -k "animation or steps or reveal_that_fits" -q`
Expected: FAIL (`Title.__init__` has no `fade`/… ; `_steps` undefined).

- [ ] **Step 3: Add the constants** — after `STYLES` (line 16):

```python
REVEALS: tuple[str, ...] = ("none", "word", "stair")

FONTSIZE_DIV = 18      # drawtext fontsize is h/FONTSIZE_DIV — one spelling, two readers
                       # (build_filterchain's own fontsize=, and the width arithmetic a
                       # word reveal needs, resolution-independent because every width
                       # scales with the same h)
_MEASURE_AT = 100      # px font size the metrics are taken at, then scaled by h
LINE_SPACING = 1.15    # multiples of the font size between staircase lines
```

- [ ] **Step 4: Add the six fields** — after `style: str = "bold-box"` in the `Title` dataclass:

```python
    fade: float = 0.0         # seconds to ramp alpha in AND out; 0.0 = hard cut (historical
                              # default; an existing TITLES.json renders pixel-identically)
    reveal: str = "none"      # "none" | "word" (one word at a time at its FINAL x) |
                              # "stair" (same, each step also drops a line). word splits on
                              # spaces, stair on NEWLINES — see _steps
    reveal_step: float = 0.35 # seconds between word entrances (ignored when reveal="none")
    color: str = "white"      # drawtext fontcolor: a name, 0xRRGGBB, or either with @alpha
    scale: float = 1.0        # multiplies the h/FONTSIZE_DIV default size
    line_spacing: float = LINE_SPACING  # multiples of the font size between staircase lines
```

- [ ] **Step 5: Add the refusals** — at the end of `__post_init__`, after the `style` check:

```python
        if isinstance(self.fade, bool) or not isinstance(self.fade, (int, float)):
            raise ValueError(f"Title.fade must be a number (seconds), got {self.fade!r}")
        if not math.isfinite(self.fade) or self.fade < 0:
            raise ValueError(f"Title.fade must be a finite number >= 0 seconds, got {self.fade!r}")
        # Two ramps inside ONE window: past dur/2 the in-ramp still climbs while the
        # out-ramp already falls, so the title never reaches full opacity and the author's
        # colour is never on screen. Refused, not clamped (invisible-creative-change class).
        if 2 * self.fade > self.dur:
            raise ValueError(
                f"Title.fade {self.fade}s twice over exceeds the {self.dur}s window — the "
                f"title would never reach full opacity. Use fade <= {self.dur / 2:g}s, or "
                "lengthen dur")
        if not (isinstance(self.color, str) and self.color.strip()):
            raise ValueError(f"Title.color must be a non-empty drawtext colour "
                             f"(a name, 0xRRGGBB, or either with @alpha), got {self.color!r}")
        if (isinstance(self.scale, bool) or not isinstance(self.scale, (int, float))
                or not math.isfinite(self.scale) or not 0 < self.scale <= 5):
            raise ValueError(f"Title.scale must be a multiplier in (0, 5], got {self.scale!r}")
        if (isinstance(self.line_spacing, bool)
                or not isinstance(self.line_spacing, (int, float))
                or not math.isfinite(self.line_spacing) or not 0.5 <= self.line_spacing <= 3):
            raise ValueError(f"Title.line_spacing must be a multiplier in [0.5, 3], "
                             f"got {self.line_spacing!r}")
        if self.reveal not in REVEALS:
            raise ValueError(f"Title.reveal {self.reveal!r} not in {REVEALS}")
        if (isinstance(self.reveal_step, bool)
                or not isinstance(self.reveal_step, (int, float))
                or not math.isfinite(self.reveal_step) or self.reveal_step <= 0):
            raise ValueError(f"Title.reveal_step must be a positive number of seconds, "
                             f"got {self.reveal_step!r}")
        if self.reveal in ("word", "stair"):
            # The LAST word must arrive, hold, and still leave inside the window; if it
            # cannot, the line is never once whole on screen — the one thing a word reveal
            # builds up to. Refused, not silently compressed.
            n = len(_steps(self))
            need = (n - 1) * self.reveal_step + 2 * self.fade
            if need > self.dur:
                raise ValueError(
                    f"Title.reveal={self.reveal!r} needs {need:g}s for {n} steps at "
                    f"reveal_step {self.reveal_step}s (+2x fade {self.fade}s) but the window is "
                    f"{self.dur}s — the last word would still be arriving as the title leaves. "
                    "Shorten reveal_step, shorten fade, or lengthen dur")
```

- [ ] **Step 6: Extend `to_dict`** — replace the `Title.to_dict` return with:

```python
    def to_dict(self) -> dict:
        return {"text": self.text, "start": self.start, "dur": self.dur,
                "font": self.font, "pos": self.pos, "style": self.style,
                "fade": self.fade, "reveal": self.reveal,
                "reveal_step": self.reveal_step, "color": self.color,
                "scale": self.scale, "line_spacing": self.line_spacing}
```

- [ ] **Step 7: Add `_steps`** — at the very end of `scripts/lib/titles.py`:

```python
def _steps(t: Title) -> list[str]:
    """The chunks a reveal arrives in. "word" splits on whitespace (one word per
    entrance, one line); "stair" splits on NEWLINES, so the author groups the words
    themselves ("salt,\\nsun\\n& you" is three steps). Splitting a staircase on spaces
    would force one word per line and make a four-word title a quarter-frame tall."""
    if t.reveal == "stair":
        return [ln.strip() for ln in t.text.splitlines() if ln.strip()]
    return t.text.split()
```

- [ ] **Step 8: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -q`
Expected: PASS (existing tests unaffected — defaults are historical; new tests green).

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/titles.py tests/lib/test_titles.py
git commit -m "feat: Title gains fade/reveal/colour/scale fields (validated, historical defaults)"
```

---

### Task 1: `_measure` + `_layers` (pure geometry, stub-injected)

**Files:**
- Modify: `scripts/lib/titles.py` (add `_measure`, `_layers` near `_steps`)
- Test: `tests/lib/test_titles.py`

- [ ] **Step 1: Write the failing tests** — append:

```python
def _stub_measure(font, text):
    # width proportional to length; a flat ink-box top (baseline shift = 0)
    return (float(len(text)) * 10.0, 0.0)


def test_layers_none_is_one_centered_layer():
    from scripts.lib.titles import _layers
    t = Title("whole line", 0.0, 2.0)
    assert _layers(t, "/f.ttf", _stub_measure) == [("whole line", 0.0, "(w-tw)/2", "")]


def test_layers_word_places_each_word_at_its_final_x():
    from scripts.lib.titles import _layers
    t = Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _stub_measure)
    assert [ly[0] for ly in layers] == ["a", "bb"]          # one layer per word
    assert [ly[1] for ly in layers] == [0.0, 0.5]           # appears at start + j*step
    # x is the FULL line centred + this word's measured prefix — never (w-tw)/2.
    # total="a bb"→40px, k=1/(18*100); prefix word0=0, word1="a "→20px.
    assert layers[0][2] == "(w-0.022222*h)/2+0.000000*h"
    assert layers[1][2] == "(w-0.022222*h)/2+0.011111*h"
    assert all("*h" in ly[2] for ly in layers)              # resolution-independent (inv 5)


def test_layers_stair_drops_a_line_per_step():
    from scripts.lib.titles import _layers
    t = Title("salt,\nsun\n& you", 0.0, 3.0, reveal="stair", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _stub_measure)
    assert [ly[0] for ly in layers] == ["salt,", "sun", "& you"]   # newline split
    # per-step drop = j * line_spacing(1.15) * scale(1.0) / 18 = 0.063889 * j
    assert [ly[3] for ly in layers] == ["+0.000000*h", "+0.063889*h", "+0.127778*h"]


def test_layers_baseline_shift_uses_ink_box_top():
    from scripts.lib.titles import _layers

    def _measure_with_tops(font, text):
        tops = {"a bb": 0.0, "a": 5.0, "bb": 0.0, "a ": 20.0}
        return (float(len(text)) * 10.0, tops.get(text, 0.0))
    t = Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5)
    layers = _layers(t, "/f.ttf", _measure_with_tops)
    # word "a" sits 5px above the line's top → shifted DOWN by (5-0)*k = +0.002778*h
    assert layers[0][3] == "+0.002778*h"
    assert layers[1][3] == "+0.000000*h"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -k layers -q`
Expected: FAIL (`_layers` undefined).

- [ ] **Step 3: Add `_measure` and `_layers`** — before `_steps` at the end of the module:

```python
def _measure(font_path: str, text: str) -> tuple[float, float]:
    """(advance width, ink-box top) for `text` at _MEASURE_AT px, in px. Its own
    function so a test can inject a stub instead of a real font on disk.

    The TOP is not decoration: drawtext places the INK BOX at `y`, so a word of pure
    x-height letters and one with ascenders/a comma do not share a baseline when each
    is a layer at one `y`. Shifting each layer by its own box top relative to the full
    line's box top puts every word back on the line's baseline."""
    from PIL import ImageFont      # local: only a word reveal needs metrics
    f = ImageFont.truetype(font_path, _MEASURE_AT)
    return float(f.getlength(text)), float(f.getbbox(text)[1])


def _layers(t: Title, font: str, measure) -> list[tuple[str, float, str, str]]:
    """(text, appears_at, x_expression, y_drop_expression) per drawtext this title needs.

    reveal="none" is one layer, centred by ffmpeg's own `tw` — unchanged. A reveal is
    one layer per step, each landing where it will sit in the FINISHED line: centring
    each by (w-tw)/2 would shuffle the line sideways on every entrance. Widths are
    measured here and baked into x as fractions of `h` (fontsize is h/FONTSIZE_DIV, so a
    width at _MEASURE_AT px becomes width * (h/FONTSIZE_DIV)/_MEASURE_AT) —
    resolution-independent, which is what lets titles.py know nothing about the canvas.
    stair keeps the same x and drops a line per step."""
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

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -k layers -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/titles.py tests/lib/test_titles.py
git commit -m "feat: _measure + _layers bake reveal words at their final x as fractions of h"
```

---

### Task 2: `y_exprs` + `build_filterchain` rewrite (platform, layers, fade)

**Files:**
- Modify: `scripts/lib/titles.py` (add `y_exprs`; delete `_Z`/`_Y_EXPR`; rewrite `build_filterchain`)
- Test: `tests/lib/test_titles.py` (re-pin two assertions; add render tests)

- [ ] **Step 1: Re-pin the two default-render assertions.**

In `test_build_filterchain_positions_and_styles`, replace line 111
(`assert "x=(w-tw)/2" in vf and "fontsize=h/18" in vf`) with:

```python
    assert "x=(w-tw)/2" in vf and "fontsize=h*0.055556" in vf   # h/18, respelled
```

Replace the whole `test_titles_margins_are_sourced_from_the_safe_zone_table`
(currently asserting `titles._Z` / `titles._Y_EXPR`, both deleted this task) with:

```python
def test_y_exprs_generic_matches_the_default_zone():
    from scripts.lib import titles, safezones
    z = safezones.default_zone()
    assert titles.y_exprs("") == {"top": f"h*{z.top}", "center": "(h-th)/2",
                                  "bottom": f"h-th-h*{z.bottom}"}
    assert not hasattr(titles, "_Y_EXPR")      # the frozen constant is gone


def test_y_exprs_platform_zone_pushes_the_bottom_title_up():
    from scripts.lib import titles
    # reels reserves 0.16 of the bottom vs the generic 0.12 → the bottom y moves up
    assert titles.y_exprs("reel")["bottom"] == "h-th-h*0.16"
    assert titles.y_exprs("reel")["bottom"] != titles.y_exprs("")["bottom"]
    assert titles.y_exprs("reel")["top"] == titles.y_exprs("")["top"]   # top zone equal
```

- [ ] **Step 2: Write the new render tests** — append:

```python
def test_build_filterchain_fade_zero_emits_no_alpha(tmp_path):
    ts = Titles(items=(Title("Hook", 0.0, 2.0),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "alpha=" not in vf                        # the historical fast path


def test_build_filterchain_fade_emits_a_trapezoid_alpha(tmp_path):
    ts = Titles(items=(Title("Hook", 0.0, 2.0, fade=0.5),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "alpha='max(0,min(1,min((t-0.0)/0.5,(2.0-t)/0.5)))'" in vf


def test_build_filterchain_platform_shifts_the_bottom_title(tmp_path):
    ts = Titles(items=(Title("hi", 0.0, 2.0, pos="bottom"),))
    generic = build_filterchain(ts, str(tmp_path / "g"), resolve=_fake_resolve)
    reel = build_filterchain(ts, str(tmp_path / "r"), resolve=_fake_resolve, platform="reel")
    assert "y=h-th-h*0.12" in generic
    assert "y=h-th-h*0.16" in reel


def test_build_filterchain_word_reveal_lays_each_word_at_final_x(tmp_path):
    ts = Titles(items=(Title("a bb", 0.0, 2.0, reveal="word", reveal_step=0.5),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve, measure=_stub_measure)
    assert vf.count("drawtext=") == 2
    assert "enable='between(t,0.0,2.0)'" in vf and "enable='between(t,0.5,2.0)'" in vf
    assert "x=(w-tw)/2" not in vf                    # never naively centred per word
    assert "+0.000000*h" in vf and "+0.011111*h" in vf   # word0 / word1 baked prefixes
    assert (tmp_path / "title_0_0.txt").read_text() == "a"
    assert (tmp_path / "title_0_1.txt").read_text() == "bb"


def test_build_filterchain_scale_and_colour(tmp_path):
    ts = Titles(items=(Title("hi", 0.0, 2.0, scale=2.0, color="0xffcc00"),))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve)
    assert "fontsize=h*0.111111" in vf and "fontcolor=0xffcc00" in vf
```

- [ ] **Step 3: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -q`
Expected: FAIL (`y_exprs` undefined; fade/platform/word behaviour absent; the two
re-pinned assertions fail against the old code).

- [ ] **Step 4: Replace `_Z`/`_Y_EXPR` with `y_exprs`.**

Delete these lines (currently after `_STYLE_FRAGMENTS`):

```python
_Z = safezones.default_zone()
_Y_EXPR: dict[str, str] = {          # safe-margin presets from the shared SafeZone table (§5.13/§5.16)
    "top": f"h*{_Z.top}",
    "center": "(h-th)/2",
    "bottom": f"h-th-h*{_Z.bottom}",
}
```

Add in their place:

```python
def y_exprs(platform: str = "") -> dict[str, str]:
    """Per-position y expressions, keyed off the PLATFORM's safe zone (§5.13/§5.16).

    Not a module constant: the margin is not a constant. The generic zone keeps 12%
    clear at the bottom, Reels 16%, TikTok 18% — a bottom title laid against the
    generic table renders UNDER the app's caption/button chrome on exactly the
    platforms this repo delivers to. check_reel already judges the subject against
    safe_zone_for(platform); this is the same spelling, so the two halves can no
    longer disagree. Empty/unknown platform → the generic zone, unchanged."""
    z = safezones.safe_zone_for(platform)
    return {"top": f"h*{z.top}",
            "center": "(h-th)/2",
            "bottom": f"h-th-h*{z.bottom}"}
```

- [ ] **Step 5: Rewrite `build_filterchain`** — replace the whole function body with:

```python
def build_filterchain(titles: Titles, work_dir: str, resolve=resolve_font,
                      platform: str = "", measure=None) -> str:
    """The drawtext chain deliver injects into its encode -vf. One drawtext per Title
    (or per reveal step), shown only in [start, start+dur] via enable=. Positions use
    ffmpeg's own w/h/tw/th expressions (resolution-agnostic — no python dims). Each
    layer's free text goes to a per-layer textfile (textfile= dodges filtergraph
    escaping of ':'/apostrophes). Empty Titles -> "" (deliver then encodes with no -vf).
    font/textfile are single-quoted; a resolved font path and a skill-controlled
    work-dir carry no apostrophe.

    `platform` selects the safe-zone margins the y positions lay out against (see
    y_exprs); unset keeps the generic table, what every caller got before the argument.
    `measure` overrides the font-metrics function a reveal="word"/"stair" title needs
    (see _layers); it is never called for reveal="none"."""
    if not titles.items:
        return ""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
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
            # A zero fade emits NO alpha= at all, so a title authored before this field
            # existed produces the same drawtext it always did (only the fontsize spelling
            # h/18 -> h*0.055556 differs — same rendered size; see design §7).
            alpha = ""
            if t.fade > 0:
                # ramp up over `fade`, hold at 1, ramp down over `fade`. min() of the two
                # ramps IS the trapezoid; max(0, ...) only guards the instants `enable`
                # already excludes, where the leading ramp is still negative.
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

- [ ] **Step 6: Run — expect pass (whole file)**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -q`
Expected: PASS — including the untouched `test_build_filterchain_one_drawtext_per_title_with_windows`
(default titles still write `title_0.txt`/`title_1.txt`) and the re-pinned assertions.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/titles.py tests/lib/test_titles.py
git commit -m "feat: build_filterchain renders reveals/fade and lays out against the platform safe zone"
```

---

### Task 3: `deliver` threads `platform` + `--platform` CLI + `build_reel` wiring

**Files:**
- Modify: `scripts/deliver.py` (`deliver` signature + call + docstring; `main` `--platform`)
- Modify: `scripts/build_reel.py` (one line — pass `platform=rm.platform` to `deliver.deliver`)
- Test: `tests/lib/test_deliver.py`, `tests/lib/test_build_reel.py`

- [ ] **Step 1: Write the failing tests.**

Append to `tests/lib/test_deliver.py`:

```python
def test_deliver_threads_platform_into_the_filterchain(tmp_path, monkeypatch):
    # spy on build_filterchain so the test needs no real font on disk; the chain's
    # own platform behaviour is covered in test_titles.py.
    from scripts.lib.titles import Title, Titles
    seen = {}

    def _spy(titles, work_dir, resolve=None, platform="", measure=None):
        seen["platform"] = platform
        return ""                                   # empty chain → no -vf, encode still runs
    monkeypatch.setattr(deliver, "build_filterchain", _spy)
    monkeypatch.setattr(deliver.proc, "run", lambda cmd, **k: SimpleNamespace(stdout=b""))
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("hi", 0.0, 2.0),)).write(tj)
    deliver.deliver(str(tmp_path / "m.mp4"), REEL_H264, str(tmp_path / "out"), "v1",
                    _green(), titles=str(tj), platform="reel")
    assert seen["platform"] == "reel"


def test_deliver_cli_passes_platform(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rep = tmp_path / "r.json"
    rep.write_text('{"checks": {}, "episode_count": 0, "fail_reasons": []}')
    monkeypatch.setattr(sys, "argv",
                        ["deliver", "m.mp4", "--out-dir", str(tmp_path),
                         "--report", str(rep), "--platform", "tiktok"])
    deliver.main()
    assert seen.get("platform") == "tiktok"
```

> Corrected post-hoc (Task 6 docs sync): `deliver.main()`'s `master` is a
> **positional** arg (`ap.add_argument("master")`), not `--master`, and
> `deliver.py` never imports `sys` (argparse reads the real `sys.argv`
> directly) — so the patch target is the test module's own `import sys`, not
> `deliver.sys`. The shipped test (`tests/lib/test_deliver.py`) has always
> used this correct form; only this plan snippet had drifted.

Append to `tests/lib/test_build_reel.py`:

```python
def test_build_reel_forwards_platform_to_deliver(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    res = build_reel.build_reel(_rm(platform="reel"), str(tmp_path / "out"),
                                str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["deliver_platform"] == "reel"       # rm.platform → deliver(platform=)
```

- [ ] **Step 2: Update the `test_build_reel` fixture so the new kwarg is tolerated and captured.**

In `_wire`, add `"deliver_platform": ""` to the `seen` dict, and change `fake_deliver`:

```python
    def fake_deliver(m, prof, od, cl, rep, audio=None, titles=None, platform=""):
        seen["deliver"].append(od)
        seen["titles"].append(titles)
        seen["deliver_platform"] = platform
        return f"{od}/REEL_v1.mp4"
```

Change the `_rm` helper to accept a platform:

```python
def _rm(cap=3, n=2, platform=""):
    eps = [ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=f"c{i}.mp4", route=f"r{i}.json")
           for i in range(n)]
    return ReelManifest(episodes=eps, target_dur=6.0, color_delta_max=12.0, cap=cap,
                        platform=platform)
```

- [ ] **Step 3: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py tests/lib/test_build_reel.py -q`
Expected: FAIL (`deliver()` has no `platform`; `deliver.sys` unused/undefined for the CLI
test; build_reel does not pass `platform`, so `seen["deliver_platform"]` stays `""`).

- [ ] **Step 4: Thread `platform` through `deliver`.**

In `scripts/deliver.py`, add `import sys` at the top if absent. Change the signature:

```python
def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, *, audio: str | None = None, titles: str | None = None,
            platform: str = "") -> str:
```

Extend the docstring with a line:

```python
    With `titles` (a TITLES.json path), burn the drawtext chain into this one encode
    (design §5.16) — no second pass. `platform` is the same safe-zone table key
    check_reel judges the PICTURE against; it must reach here too, or a bottom title
    is laid out against generic margins and lands under the app's chrome.
```

Change the `build_filterchain` call:

```python
        chain = build_filterchain(Titles.from_json(titles), out_dir, platform=platform)
```

In `main()`, add the argument (place it after `--titles`), and pass it through:

```python
    ap.add_argument("--platform", default="", help="safe-zone table key (reel/tiktok/shorts/…) — "
                                                   "where the app's chrome sits; titles lay out inside it")
```

```python
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report,
                  titles=a.titles, platform=a.platform)
```

> Do **not** add the parked `--audio` CLI argument — it is out of scope for this
> slice (see design §2). Leave `main`'s audio handling exactly as it is.

- [ ] **Step 5: Wire `build_reel`** — the `deliver.deliver(...)` call (around line 87) gains one kwarg:

```python
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report,
                                  audio=audio, titles=titles, platform=rm.platform)
```

- [ ] **Step 6: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py tests/lib/test_build_reel.py -q`
Expected: PASS (all existing deliver/build_reel tests + the three new ones).

- [ ] **Step 7: Commit**

```bash
git add scripts/deliver.py scripts/build_reel.py tests/lib/test_deliver.py tests/lib/test_build_reel.py
git commit -m "feat: deliver threads platform to titles; build_reel passes rm.platform"
```

---

### Task 4: real-ffmpeg integration golden (fade + word reveal burn in)

**Files:**
- Create/Modify: `tests/integration/test_titles.py` (add an animated-title golden; follow the existing titles golden pattern if one lives elsewhere — search first)
- Test: the new integration test

- [ ] **Step 1: Locate the existing titles integration golden** (TT Task 8) to mirror its fixture and markers:

Run: `grep -rln "build_filterchain\|drawtext\|TITLES" tests/integration/`
Read whichever file renders titles through ffmpeg; reuse its real-font resolution
(`resolve_font`), its `require_filter`/skip guard for drawtext, and its tiny-clip fixture.

- [ ] **Step 2: Write the failing test** — an animated title actually encodes on real ffmpeg:

```python
def test_word_reveal_with_fade_burns_into_a_real_encode(tmp_path):
    # a 2-word hook, fade in/out, revealed word-by-word — the chain must build with a
    # REAL font (exercises _measure/PIL) and ffmpeg must accept and render it.
    from scripts.lib.titles import Title, Titles, build_filterchain
    from scripts.lib.fonts import resolve_font
    from scripts.lib import ffbin
    # (use the module's shared drawtext-availability skip guard here)
    ts = Titles(items=(Title("hello world", 0.0, 2.0, fade=0.4,
                             reveal="word", reveal_step=0.5, pos="bottom"),))
    chain = build_filterchain(ts, str(tmp_path), resolve=resolve_font, platform="reel")
    assert chain.count("drawtext=") == 2                 # one per word
    assert "alpha='max(0,min(1," in chain                # fade present
    assert "y=h-th-h*0.16" in chain                      # reel zone
    # render a 3s colour source through the chain — ffmpeg must exit 0
    out = tmp_path / "titled.mp4"
    ffbin.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x284:d=3",
               "-vf", chain, "-frames:v", "1", str(out)])
    assert out.exists() and out.stat().st_size > 0
```

Adjust the exact `ffbin` entrypoint names/helpers to whatever the existing integration
golden uses (this repo resolves ffmpeg only through `scripts/lib/ffbin` — never PATH).

- [ ] **Step 3: Run — expect pass** (real ffmpeg with libfreetype)

Run: `.venv/bin/python -m pytest tests/integration/test_titles.py -q`
Expected: PASS (or SKIP only if the module's drawtext guard trips — it must not on the baseline).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_titles.py
git commit -m "test: real-ffmpeg golden burns a fading word-reveal into an encode"
```

---

### Task 5: `skills/titles/SKILL.md` — author guidance for the six fields

**Files:**
- Modify: `skills/titles/SKILL.md`

- [ ] **Step 1: Read the current SKILL** to match its voice and section layout:

Run: `sed -n '1,200p' skills/titles/SKILL.md`

- [ ] **Step 2: Add a "Motion & colour" subsection** documenting, with a worked example, the
six fields and — critically — the refusal math the author must size against:

- `fade` (seconds each way) must satisfy `2*fade <= dur`.
- `reveal="word"` splits on spaces; `reveal="stair"` splits on **newlines** (group words yourself).
- a reveal needs `(#steps - 1) * reveal_step + 2*fade <= dur`, else it is refused — the last word must land whole before the title leaves.
- `color` (name / `0xRRGGBB` / `@alpha`), `scale` (`(0,5]`), `line_spacing` (`[0.5,3]`, tighten a script face).
- these are set by editing `TITLES.json`; `build_titles` still drafts static defaults.

Include a JSON snippet showing a faded, word-revealed hook so the author can copy it.

- [ ] **Step 3: Verify no lint/reference breakage** (the SKILL is text; just confirm the file reads cleanly):

Run: `.venv/bin/python -m pytest tests/ -k lint -q`
Expected: PASS (no new landmine/argv lint touched — this is docs).

- [ ] **Step 4: Commit**

```bash
git add skills/titles/SKILL.md
git commit -m "docs: titles SKILL — motion/colour fields and the reveal/fade refusal math"
```

---

### Task 6: docs sync + mutation battery + full suite + final review

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md` (registry rows),
  `docs/specs/2026-07-29-titles-animations-design.md` (Status → landed)

- [ ] **Step 1: Run the mutation battery.** For EACH, make the one-line edit, run the named
test, confirm it goes RED, then `git checkout -- <file>` to restore before the next:

| # | Mutation | Named test that must flip |
|---|----------|---------------------------|
| 1 | `build_filterchain`: drop `if t.fade > 0:` (always emit `alpha=`) | `test_build_filterchain_fade_zero_emits_no_alpha` |
| 2 | `_layers` reveal branch: return `"(w-tw)/2"` for x | `test_build_filterchain_word_reveal_lays_each_word_at_final_x` |
| 3 | `Title`: change `2 * self.fade > self.dur` → `... > self.dur + 999` | `test_title_animation_validation_fails_loud[...never reach full opacity...]` |
| 4 | `Title`: change `need > self.dur` → `need > self.dur + 999` | `test_title_animation_validation_fails_loud[...would still be arriving...]` |
| 5 | `y_exprs`: `safe_zone_for(platform)` → `default_zone()` | `test_y_exprs_platform_zone_pushes_the_bottom_title_up` |
| 6 | `_layers`: drop `*h` from the x expression (`{prefix:.6f}*h` → `{prefix:.6f}`) | `test_layers_word_places_each_word_at_its_final_x` |
| 7 | `deliver`: drop `platform=platform` from the `build_filterchain` call | `test_deliver_threads_platform_into_the_filterchain` |
| 8 | `build_reel`: drop `platform=rm.platform` | `test_build_reel_forwards_platform_to_deliver` |

Run per mutation, e.g.: `.venv/bin/python -m pytest tests/lib/test_titles.py -k fade_zero -q`

- [ ] **Step 2: Full suite green, no golden moved**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all; the two skips are pre-existing). Confirm no golden fixture changed
(`git status --porcelain tests/` shows only intended files).

- [ ] **Step 3: Docs sync.**
- `docs/build-status.md`: add the titles-animations DONE entry (fade/reveal/colour + platform safe-zone).
- `docs/pipeline-map.md`: note §5.16 titles now render motion/colour + lay out against the platform zone.
- `CLAUDE.md`: two registry rows (design + plan) in the Quick Reference table, in date order after track-stitch/path-quality.
- The design doc's Status line: `designed` → `landed 2026-07-29`.

- [ ] **Step 4: Commit**

```bash
git add docs/build-status.md docs/pipeline-map.md CLAUDE.md docs/specs/2026-07-29-titles-animations-design.md
git commit -m "docs: titles-animations landed — build-status, pipeline-map, registry rows"
```

- [ ] **Step 5: Final whole-slice review.** Dispatch an opus code-quality reviewer over
`git diff <design-commit>^..HEAD` (the whole branch): verify the four design §4
invariants hold in code, the byte-identical claim (§7) is accurate (pixel-identical
defaults; two re-pins; no golden moved), and the `--audio` exclusion held (deliver's
CLI gained only `--platform`). Address any Critical/Important finding as a **separate
follow-up commit** (never `--amend`), then re-run the affected test.

---

## Self-Review (plan vs spec)

- **Spec coverage:** §3.1 constants → T0.3; §3.2 fields+refusals → T0.4-5; `to_dict` → T0.6;
  §3.3 `_steps` → T0.7; §3.4 `_measure` → T1; §3.5 `_layers` → T1; §3.6 `y_exprs` → T2;
  §3.7 `build_filterchain` → T2; §3.8 wiring → T3; §4 invariants → T6 battery; §5 tests →
  T0-T4; §6 landmines → covered by fast-path/stub/real-golden tests; §7 file map + honest
  claim → T2 re-pins + T6 review. All covered.
- **Placeholders:** none — every code step carries full code; the two "match the existing
  golden/SKILL" steps (T4, T5) instruct a `grep`/`sed` first because those files' exact
  fixture/voice must be matched, not invented.
- **Type consistency:** `_layers` returns `list[tuple[str, float, str, str]]` (4-tuple),
  unpacked as `(text, appears, x_expr, y_drop)` in `build_filterchain` — consistent.
  `platform: str = ""` matches `ReelManifest.platform: str = ""` and `deliver(..., platform="")`.

## Execution Handoff

Plan complete and saved to `docs/plans/2026-07-29-titles-animations.md`. Recommended:
**subagent-driven development** (fresh implementer per task; spec-compliance then
code-quality review after each; opus for the logic-heavy Task 2). Two mutation checks
in Task 6 are steps, not suggestions.
