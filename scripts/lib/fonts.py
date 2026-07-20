"""Font resolution shared by the draft-preview labels (§5.9) and the titles render
(§5.16): the system-font fallback list, the friendly-name → cask-filename map, and
resolve_font. drawtext needs an explicit fontfile= — there is no reliable fontconfig
default on macOS (design §12). Extracted from draft.py so titles need not import the
draft-preview module."""
from pathlib import Path

FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",     # macOS system
    "/System/Library/Fonts/Helvetica.ttc",              # macOS system
    str(Path.home() / "Library/Fonts/DejaVuSans.ttf"),  # macOS, `brew install --cask font-dejavu`
    "/Library/Fonts/Arial.ttf",                         # macOS (older installs)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",           # Fedora/Arch
)

# friendly name -> the file `brew install --cask font-<x>` drops in ~/Library/Fonts
FONT_NAMES: dict[str, str] = {
    "Montserrat": "Montserrat-Regular.ttf",
    "Inter": "Inter-Regular.ttf",
    "Bebas Neue": "BebasNeue-Regular.ttf",
    "BebasNeue": "BebasNeue-Regular.ttf",
    "Oswald": "Oswald-Regular.ttf",
}

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
        p = Path.home() / "Library/Fonts" / FONT_NAMES[font]
        if p.exists():
            return str(p)
        raise ValueError(
            f"font {font!r} is not installed at {p} — run `bash setup.sh`, which installs "
            "the curated set, or pass a .ttf/.ttc path")
    raise ValueError(
        f"font {font!r} is neither an existing path nor a known name {tuple(FONT_NAMES)} "
        "— pass a .ttf/.ttc/.otf path, or install & name one via `bash setup.sh`")
