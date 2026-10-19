"""Font resolution shared by the draft-preview labels (§5.9) and the titles render
(§5.16): the system-font fallback list, the friendly-name → cask-filename map, and
resolve_font. drawtext needs an explicit fontfile= — there is no reliable fontconfig
default on macOS (design §12). Extracted from draft.py so titles need not import the
draft-preview module."""
import hashlib
import os
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import cmap_format_12
from fontTools.varLib import instancer

FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",     # macOS system
    "/System/Library/Fonts/Helvetica.ttc",              # macOS system
    str(Path.home() / "Library/Fonts/DejaVuSans.ttf"),  # macOS, `brew install --cask font-dejavu`
    "/Library/Fonts/Arial.ttf",                         # macOS (older installs)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",           # Fedora/Arch
)

# friendly name -> the files `brew install --cask font-<x>` may drop in ~/Library/Fonts,
# first existing wins. The casks install VARIABLE fonts today (Montserrat[wght].ttf,
# InterVariable.ttf, Oswald[wght].ttf); the *-Regular.ttf names are older static installs.
# Listing only the old names made three of the four fail with "run bash setup.sh", which
# could not fix it (S19, found reviewing retro 2026-10-16 S13). A variable font is drawn
# at TITLE_WEIGHT — see static_instance.
FONT_NAMES: dict[str, tuple[str, ...]] = {
    "Montserrat": ("Montserrat[wght].ttf", "Montserrat-Regular.ttf"),
    "Inter": ("InterVariable.ttf", "Inter-Regular.ttf"),
    "Bebas Neue": ("BebasNeue-Regular.ttf",),
    "BebasNeue": ("BebasNeue-Regular.ttf",),
    "Oswald": ("Oswald[wght].ttf", "Oswald-Regular.ttf"),
    "Noto Emoji": ("NotoEmoji[wght].ttf",),    # monochrome icons for titles (cover_glyphs)
}
TITLE_WEIGHT = 400     # the weight a variable title font is drawn at (Regular). drawtext
                       # alone draws its DEFAULT instance — 100, Thin, for Montserrat[wght]

# The font a title's icons (📍 🗓 …) are taken from when its own font lacks them. The
# second real run's brief asked for a map pin and a calendar; no curated font draws them,
# and drawtext renders a missing glyph as an empty box — so the agent downloaded Noto
# Emoji and merged it by hand (retro 2026-10-16 S13). setup.sh installs it.
ICON_FONT = "Noto Emoji"

# Characters that draw nothing: variation selectors, joiners, zero-width marks, tags.
# drawtext (HarfBuzz) lays a missing one out as nothing, so demanding a glyph for it
# would refuse a title that renders fine — 🗓 is text-style by default, and emoji
# pickers insert U+1F5D3 U+FE0F. Never required, never merged.
_INVISIBLE = (set(range(0x200B, 0x2010)) | set(range(0x2060, 0x2065))
              | set(range(0xFE00, 0xFE10)) | set(range(0xE0000, 0xE0080))
              | set(range(0xE0100, 0xE01F0)))
_MERGE_VERSION = 2     # bump when _merge_icons changes what it writes: it keys the cache

_SYSTEM = (None, "", "system")


def _system_default() -> str:
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise ValueError(
        f"no usable font found among {FONT_CANDIDATES} — pass a .ttf/.ttc path "
        "(drawtext needs an explicit fontfile=; there is no fontconfig default on "
        "macOS), or run `bash setup.sh` to install one")


def resolve_font(font: str | None = None) -> str:
    """A drawtext fontfile= path. `font`:
      None / "" / "system"  -> first existing FONT_CANDIDATES (system default)
      an explicit path       -> that path (must exist)
      a known NAME           -> ~/Library/Fonts/<cask file>, if installed
    Nothing usable → ValueError with the remedy. A NAMED font never silently falls
    back to a different one — that would change the creative output invisibly."""
    if font in _SYSTEM:
        return _system_default()
    looks_like_path = "/" in font or font.lower().endswith((".ttf", ".ttc", ".otf"))
    if looks_like_path:
        if Path(font).exists():
            return font
        raise ValueError(f"font path {font!r} does not exist — pass a real .ttf/.ttc/.otf")
    if font in FONT_NAMES:
        lib = Path.home() / "Library/Fonts"
        for name in FONT_NAMES[font]:
            if (lib / name).exists():
                return str(lib / name)
        raise ValueError(
            f"font {font!r} is not installed in {lib} (looked for "
            f"{', '.join(FONT_NAMES[font])}) — run `bash setup.sh`, which installs the "
            "curated set, or pass a .ttf/.ttc path")
    raise ValueError(
        f"font {font!r} is neither an existing path nor a known name {tuple(FONT_NAMES)} "
        "— pass a .ttf/.ttc/.otf path, or install & name one via `bash setup.sh`")


def _open(font_path: str) -> TTFont:
    """A collection (.ttc) opens as its first face — what drawtext's fontfile= uses."""
    return TTFont(font_path, fontNumber=0) if font_path.lower().endswith(".ttc") else TTFont(font_path)


def _static(font: TTFont) -> TTFont:
    """A variable font pinned: wght at TITLE_WEIGHT (clamped to the axis), every other
    axis at its default. A no-op on a static font."""
    if "fvar" not in font:
        return font
    loc = {a.axisTag: (min(max(TITLE_WEIGHT, a.minValue), a.maxValue) if a.axisTag == "wght"
                       else a.defaultValue) for a in font["fvar"].axes}
    return instancer.instantiateVariableFont(font, loc, updateFontNames=False)


def static_instance(font_path: str, work_dir: str) -> str:
    """A fontfile= drawtext draws as intended: the font itself when it is static, else a
    cached copy pinned by _static. drawtext alone renders a variable font's DEFAULT
    instance, which for Montserrat[wght] is Thin (S19)."""
    font = _open(font_path)
    if "fvar" not in font:
        return font_path
    st = os.stat(font_path)
    key = hashlib.sha1(f"{TITLE_WEIGHT}|{font_path}|{st.st_size}|{st.st_mtime_ns}"
                       .encode()).hexdigest()[:12]
    out = Path(work_dir) / f"{Path(font_path).stem}-w{TITLE_WEIGHT}-{key}.ttf"
    if out.exists():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f".{out.name}.partial")
    _static(font).save(str(part))
    os.replace(part, out)
    return str(out)


def missing_glyphs(font_path: str, text: str) -> list[str]:
    """The characters of `text` the font has no glyph for, in first-seen order.
    Whitespace is free: drawtext lays it out without a glyph."""
    cmap = _open(font_path).getBestCmap() or {}
    out: list[str] = []
    for ch in text:
        if (not ch.isspace() and ord(ch) not in _INVISIBLE and ord(ch) not in cmap
                and ch not in out):
            out.append(ch)
    return out


def cover_glyphs(font_path: str, text: str, work_dir: str,
                 icon_font: str | None = None) -> str:
    """A fontfile= that draws every character of `text`: `font_path` itself when it
    already does; else a copy of it with the missing characters' glyphs taken from the
    icon font (ICON_FONT unless given), written under `work_dir` and reused when the
    same request comes again. A character neither font draws is refused BY NAME —
    drawtext would draw an empty box and nothing would notice."""
    miss = missing_glyphs(font_path, text)
    if not miss:
        return font_path
    icon = icon_font or resolve_font(ICON_FONT)
    icon_cmap = _open(icon).getBestCmap() or {}
    still = [c for c in miss if ord(c) not in icon_cmap]
    if still:
        raise ValueError(
            f"title text carries {still} ({', '.join(f'U+{ord(c):04X}' for c in still)}), "
            f"which neither {Path(font_path).name} nor the icon font {Path(icon).name} "
            f"draws — drawtext would render an empty box. Remove the character or pick a "
            f"font that has it")
    cps = sorted(ord(c) for c in miss)
    stamp = [(f, os.stat(f).st_size, os.stat(f).st_mtime_ns) for f in (font_path, icon)]
    key = hashlib.sha1(f"{_MERGE_VERSION}|{stamp}|{cps}".encode()).hexdigest()[:12]
    out = Path(work_dir) / f"{Path(font_path).stem}+icons-{key}.ttf"
    if out.exists():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f".{out.name}.partial")    # never reuse a half-written font
    _merge_icons(font_path, icon, cps, str(part))
    os.replace(part, out)
    return str(out)


def _merge_icons(base_path: str, icon_path: str, cps: list[int], out_path: str) -> None:
    """Copy each codepoint's glyph from the icon font into the base font, scaled to
    about 1.15x the base's cap height and sat on its baseline. TrueType outlines only:
    a CFF (.otf) base has no glyf table to add to, and is refused with the remedy."""
    base, icon = _static(_open(base_path)), _static(_open(icon_path))
    if "glyf" not in base or "glyf" not in icon:
        raise ValueError(
            f"cannot add icons to {Path(base_path).name}: icons are merged as TrueType "
            f"outlines and this font has none (a CFF .otf). Pick a .ttf title font")
    upem = base["head"].unitsPerEm
    cap = getattr(base["OS/2"], "sCapHeight", 0) or int(0.7 * upem)
    icon_cmap, icon_gs = icon.getBestCmap(), icon.getGlyphSet()
    order, mapping = list(base.getGlyphOrder()), dict(base.getBestCmap())
    for cp in cps:
        src = icon_cmap[cp]
        # Decomposed first: a composite glyph references components by name, which
        # TTGlyphPen(None) cannot resolve — and those names mean nothing in the base.
        rec = DecomposingRecordingPen(icon_gs)
        icon_gs[src].draw(rec)
        bounds = BoundsPen(None)
        rec.replay(bounds)
        name = f"icon_u{cp:X}"
        pen = TTGlyphPen(None)
        if bounds.bounds is None:           # an empty glyph draws nothing and advances 0
            glyph = pen.glyph()
            base["glyf"][name] = glyph
            base["hmtx"][name] = (0, 0)
        else:
            x0, y0, x1, y1 = bounds.bounds
            s = (cap * 1.15) / max(y1 - y0, 1)
            rec.replay(TransformPen(pen, (s, 0, 0, s, -x0 * s + 0.04 * upem,
                                          -y0 * s - 0.06 * cap)))
            glyph = pen.glyph()
            base["glyf"][name] = glyph
            glyph.recalcBounds(base["glyf"])
            base["hmtx"][name] = (round((x1 - x0) * s + 0.08 * upem),
                                  getattr(glyph, "xMin", 0))
        order.append(name)
        mapping[cp] = name
    base.setGlyphOrder(order)
    for tag in ("hdmx", "LTSH", "VDMX"):
        if tag in base:
            del base[tag]
    sub = cmap_format_12(12)
    sub.platformID, sub.platEncID, sub.language = 3, 10, 0
    sub.cmap = mapping
    base["cmap"].tables = [x for x in base["cmap"].tables
                           if not (x.platformID == 3 and x.platEncID == 10)] + [sub]
    if "post" in base and base["post"].formatType == 2.0:
        base["post"].extraNames, base["post"].mapping = [], {}
    base.save(out_path)
