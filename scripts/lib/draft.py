"""Draft-preview helpers (montage §5.9): font resolution, the burnt caption text,
and the per-segment scale-fit + label filter string. Pure — no ffmpeg, no writes;
the ffmpeg driver is scripts/draft.py. Split out so these fail fast in unit tests
(the drawtext fontfile landmine — design §12 — is caught here, not at render)."""
from pathlib import Path

FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",     # macOS
    "/System/Library/Fonts/Helvetica.ttc",              # macOS
    "/Library/Fonts/Arial.ttf",                         # macOS (older installs)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",           # Fedora/Arch
)


def resolve_font(override: str | None = None) -> str:
    """First existing font path for drawtext. `override` wins (must exist). None
    found → ValueError with the --font remedy. drawtext needs an explicit fontfile=
    (design §5.9, §12): macOS has no reliable fontconfig default, so an unset font
    silently renders no text — fail loud instead."""
    if override is not None:
        if not Path(override).exists():
            raise ValueError(
                f"--font {override!r} does not exist — pass a path to a .ttf/.ttc/.otf")
        return override
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise ValueError(
        f"no usable draft-label font found among {FONT_CANDIDATES} — pass --font "
        "PATH to a .ttf/.ttc/.otf (drawtext needs an explicit fontfile=; there is no "
        "fontconfig default on macOS)")


def label_text(idx: int, shot_type: str, processing_notes: str) -> str:
    """The burnt caption for episode `idx`: a '#idx shot_type' header, plus a second
    line with processing_notes when the author gave any. Written to a textfile so
    drawtext's textfile= sidesteps filtergraph escaping of ':' / apostrophes."""
    head = f"#{idx} {shot_type}"
    notes = processing_notes.strip()
    return f"{head}\n{notes}" if notes else head


def segment_filter(dims: tuple[int, int], fps: float, font: str, textfile: str) -> str:
    """The -vf string for one draft segment: scale-fit + letterbox pad into the SPEC
    canvas `dims` (no creative crop — that is process-episode), fps-normalize,
    yuv420p, then the drawtext label (semi-opaque box, bottom-left). force_divisible_by=2
    keeps the scaled intermediate even (the even-dims landmine, design §12)."""
    w, h = dims
    # font/textfile are single-quoted for the filtergraph; callers pass a resolved
    # system font and a skill-controlled work-dir path (no apostrophes). A "'" in
    # either would need filtergraph escaping — not hit in v1 (design §12); the free
    # caption text dodges it entirely by living in the textfile, not the graph.
    label = (f"drawtext=fontfile='{font}':textfile='{textfile}':fontsize=h/24:"
             f"fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=12:x=40:y=h-th-40")
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,{label}")
