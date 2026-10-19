"""Titles: on-screen text (the brief's literal words) rendered into the reel at
deliver (design docs/specs/2026-07-13-titles-design.md, §5.16). A hard config-spec —
Title/Titles validate-and-raise in __post_init__, JSON round-trip, markdown preview —
like edl.py's EDL / spec.py's Spec. build_filterchain (Task 2) is the drawtext chain
deliver injects into its one encode. drawtext only; explicit fontfile= + per-title
textfile dodge the filtergraph-escaping landmines (§12)."""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

from scripts.lib.fonts import resolve_font
from scripts.lib import safezones

POSITIONS: tuple[str, ...] = ("top", "center", "bottom")
STYLES: tuple[str, ...] = ("bold-box", "outline", "outline-bold", "plain")
REVEALS: tuple[str, ...] = ("none", "word", "stair")

FONTSIZE_DIV = 18      # drawtext fontsize is h/FONTSIZE_DIV — one spelling, two readers
                       # (build_filterchain's own fontsize=, and the width arithmetic a
                       # word reveal needs, resolution-independent because every width
                       # scales with the same h)
_MEASURE_AT = 100      # px font size the metrics are taken at, then scaled by h
LINE_SPACING = 1.15    # multiples of the font size between staircase lines


@dataclass(frozen=True)
class Title:
    text: str
    start: float
    dur: float
    font: str = "system"      # "system" -> resolve_font default; else a name/path (fonts.py)
    pos: str = "bottom"       # one of POSITIONS (safe-margin preset)
    style: str = "bold-box"   # one of STYLES
    fade: float = 0.0         # seconds to ramp alpha in AND out; 0.0 = hard cut (historical
                              # default; an existing TITLES.json renders pixel-identically)
    reveal: str = "none"      # "none" | "word" (one word at a time at its FINAL x) |
                              # "stair" (same, each step also drops a line). word splits on
                              # spaces, stair on NEWLINES — see _steps
    reveal_step: float = 0.35 # seconds between word entrances (ignored when reveal="none")
    color: str = "white"      # drawtext fontcolor: a name, 0xRRGGBB, or either with @alpha
    scale: float = 1.0        # multiplies the h/FONTSIZE_DIV default size
    line_spacing: float = LINE_SPACING  # multiples of the font size between staircase lines

    def __post_init__(self) -> None:
        if not (isinstance(self.text, str) and self.text.strip()):
            raise ValueError(f"Title.text must be a non-empty string, got {self.text!r}")
        for name in ("start", "dur"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"Title.{name} must be a number (seconds), got {v!r}")
            if not math.isfinite(v):
                raise ValueError(f"Title.{name} must be a finite number (seconds), got {v!r}")
        if self.start < 0:
            raise ValueError(f"Title.start must be >= 0 seconds, got {self.start!r}")
        if self.dur <= 0:
            raise ValueError(f"Title.dur must be > 0 seconds, got {self.dur!r}")
        if not (isinstance(self.font, str) and self.font.strip()):
            raise ValueError(f"Title.font must be a non-empty name/path, got {self.font!r}")
        if self.pos not in POSITIONS:
            raise ValueError(f"Title.pos {self.pos!r} not in {POSITIONS}")
        if self.style not in STYLES:
            raise ValueError(f"Title.style {self.style!r} not in {STYLES}")
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

    def to_dict(self) -> dict:
        return {"text": self.text, "start": self.start, "dur": self.dur,
                "font": self.font, "pos": self.pos, "style": self.style,
                "fade": self.fade, "reveal": self.reveal,
                "reveal_step": self.reveal_step, "color": self.color,
                "scale": self.scale, "line_spacing": self.line_spacing}

    @classmethod
    def from_dict(cls, d: dict) -> "Title":
        if not isinstance(d, dict):
            raise ValueError(f"Title.from_dict: expected an object, got {type(d).__name__}")
        try:
            return cls(**d)            # missing-required / unknown key → TypeError → remedy below
        except TypeError as ex:
            raise ValueError(f"Title.from_dict: {d!r} has a missing or unknown field — {ex}") from ex


@dataclass(frozen=True)
class Titles:
    items: tuple[Title, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(t, Title) for t in self.items):
            raise ValueError("Titles.items must all be Title instances")
        object.__setattr__(self, "items", tuple(self.items))

    def to_dict(self) -> dict:
        return {"items": [t.to_dict() for t in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> "Titles":
        # Top level checked FIRST, before d.get — 'items' was validated carefully while `d`
        # itself was not, so a wrong-shaped TITLES.json raised a bare AttributeError out of
        # deliver.py's bare from_json call instead of naming a remedy.
        if not isinstance(d, dict):
            raise ValueError(f"Titles.from_dict: expected a TITLES.json object with an 'items' list, "
                             f"got {type(d).__name__} — re-run titles to regenerate TITLES.json")
        items_in = d.get("items", ())
        if not isinstance(items_in, (list, tuple)):
            raise ValueError(
                f"Titles.from_dict: 'items' must be a list, got {type(items_in).__name__}")
        items = []
        for i, t in enumerate(items_in):
            if not isinstance(t, dict):
                raise ValueError(
                    f"Titles.from_dict: items[{i}] must be an object, got {type(t).__name__}")
            items.append(Title.from_dict(t))
        return cls(items=tuple(items))

    @classmethod
    def from_json(cls, path: str | Path) -> "Titles":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run titles to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def to_markdown(self) -> str:
        lines = ["# Titles", "",
                 "| # | text | start→end | pos | style | font |",
                 "|---|------|-----------|-----|-------|------|"]
        for i, t in enumerate(self.items):
            lines.append(f"| {i} | {t.text.replace(chr(10), ' ')} | "
                         f"{t.start:.1f}→{t.start + t.dur:.1f} | {t.pos} | {t.style} | {t.font} |")
        if not self.items:
            lines.append("| – | (none) | – | – | – | – |")
        return "\n".join(lines)


_STYLE_FRAGMENTS: dict[str, str] = {
    "bold-box": "box=1:boxcolor=black@0.5:boxborderw=16",
    "outline": "borderw=4:bordercolor=black",
    # a heavier outline PLUS an offset shadow: `outline` alone disappears against
    # bright water, which is what the 2026-08-03 run hit
    "outline-bold": "borderw=7:bordercolor=black:shadowcolor=black@0.55:shadowx=3:shadowy=3",
    "plain": "",
}


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


def ink_extent(t: Title, platform: str = "") -> tuple[float, float]:
    """(top, bottom) of the rows this title's ink can occupy, as FRACTIONS of frame
    height. Fractions and not pixels for the reason build_filterchain gives: the
    drawtext chain is resolution-agnostic, and so is everything derived from it.

    Two readers, one spelling (design 2026-08-19 §5): zone_overflow compares this
    against the platform's safe zone, and deliver multiplies it by the delivered
    frame's own height to get the band lookcheck measures. They cannot disagree.

    The estimate is deliberately CONSERVATIVE — `th` (drawtext's own rendered text
    height, which Python cannot know without rendering) is approximated by the font
    size, and a staircase's drop is taken at its maximum step. Measured on real
    footage it predicts [0.784, 1.032] of frame height where the ink reached
    [0.799, 0.967]: over-estimating widens a band (harmless — it only dilutes the
    evidence fraction) and refuses a title that would have just fitted (a loud
    refusal carrying its own remedy). Under-estimating would ship the defect."""
    z = safezones.safe_zone_for(platform)
    fs = t.scale / FONTSIZE_DIV                     # font size as a fraction of h
    if t.pos == "top":
        top = z.top
    elif t.pos == "center":
        top = 0.5 - fs / 2
    else:
        top = 1.0 - z.bottom - fs
    drop = 0.0
    if t.reveal == "stair":
        # _layers pushes step j down by j * line_spacing * scale / FONTSIZE_DIV of h,
        # and NOTHING lifts the base y to make room — the last step is the extent.
        drop = (len(_steps(t)) - 1) * t.line_spacing * t.scale / FONTSIZE_DIV
    return top, top + fs + drop


# The ordinary bottom title's ink box ends EXACTLY on the zone's inner edge, so the
# comparison needs slack for float arithmetic or the refusal fires on every title this
# repo authors. Sized at the arithmetic's own noise, not at a real margin.
ZONE_EPS = 1e-9


def zone_overflow(t: Title, platform: str = "") -> str:
    """"" if the title's ink stays inside the platform's safe zone, else the remedy.

    A title is laid out AGAINST the zone (y_exprs), so a single line is inside by
    construction. What is not: a `reveal="stair"`, whose per-step drop `_layers` adds
    below the base y with nothing lifting the base to make room. Measured 2026-08-19
    on the reels table at 1080x1920 — a four-step bottom staircase renders 244px into
    the app's caption/button chrome, and nothing refused it (design §5).

    Only the BOTTOM is guarded, and that is measured rather than assumed: over every
    position x platform x legal scale the ink's top never comes closer to the top
    margin than exactly 0 (`pos="top"` sits on it, the other two are pushed down by
    half a font size and a whole one), and a stair moves only the bottom. A top guard
    would be unreachable — see test_no_title_can_rise_above_a_zones_top_margin, which
    reddens if a future position makes it reachable.

    A string and not a bool so both readers quote the same sentence: the chokepoint
    refusal in build_filterchain and the authoring preflight in scripts/titles.py."""
    z = safezones.safe_zone_for(platform)
    bottom = ink_extent(t, platform)[1]
    if bottom <= 1.0 - z.bottom + ZONE_EPS:
        return ""
    return (f"a {t.pos!r} title{' staircase' if t.reveal == 'stair' else ''} at scale "
            f"{t.scale:g} reaches {bottom:.4f} of frame height, below the "
            f"{safezones.zone_name(platform)} safe zone's inner edge at "
            f"{1.0 - z.bottom:.4f} (bottom margin {z.bottom:g}) — the app draws its "
            f"caption and buttons there")


def refuse_zone_overflow(items: "tuple[Title, ...]", platform: str = "") -> None:
    """Raise on the first title whose ink would leave the platform's safe zone.

    ONE message, two callers — build_filterchain (the chokepoint, which runs at
    deliver) and scripts/titles.py's `check` (the preflight, which runs at authoring).
    They were two near-identical copies for one commit; a drift between them makes the
    preflight either useless (passes what deliver refuses) or worse than useless (the
    reverse). test_check_titles_is_the_same_verdict_build_filterchain_would_give pins
    the agreement, and this is what makes it structural rather than lucky."""
    for i, t in enumerate(items):
        why = zone_overflow(t, platform)
        if why:
            raise ValueError(
                f"TITLES.json item {i} ({t.text.splitlines()[0]!r}) leaves the "
                f"{safezones.zone_name(platform)} safe zone: {why}. Shorten the "
                f"staircase, lower line_spacing, use pos='top', or reduce scale — the "
                f"layout is not moved for you, because relocating a title the author "
                f"positioned is an invisible creative change. `titles check --titles "
                f"TITLES.json --platform <p>` runs this before the encode")


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
    refuse_zone_overflow(titles.items, platform)
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


def _measure(font_path: str, text: str) -> tuple[float, float]:
    """(advance width, ink-box top) for `text` at _MEASURE_AT px, in px. Its own
    function so a test can inject a stub instead of a real font on disk.

    The TOP is not decoration: drawtext places the INK BOX at `y`, so a word of pure
    x-height letters and one with ascenders/a comma do not share a baseline when each
    is a layer at one `y`. Shifting each layer by its own box top relative to the full
    line's box top puts every word back on the line's baseline."""
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
    stair reuses that same cumulative left-to-right x as a single line — each step still
    pushed right by the widths of the steps before it — and additionally drops a line per
    step, so the steps land in a diagonal staircase, not a stacked column."""
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


def _steps(t: Title) -> list[str]:
    """The chunks a reveal arrives in. "word" splits on whitespace (one word per
    entrance, one line); "stair" splits on NEWLINES, so the author groups the words
    themselves ("salt,\\nsun\\n& you" is three steps). Splitting a staircase on spaces
    would force one word per line and make a four-word title a quarter-frame tall."""
    if t.reveal == "stair":
        return [ln.strip() for ln in t.text.splitlines() if ln.strip()]
    return t.text.split()
