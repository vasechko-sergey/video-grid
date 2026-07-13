"""Draft-preview helpers (montage §5.9): the burnt caption text and the per-segment
scale-fit + label filter string. Pure — no ffmpeg, no writes; the ffmpeg driver is
scripts/draft.py. Split out so these fail fast in unit tests. Font resolution moved to
scripts/lib/fonts.py (re-exported below for back-compat; the drawtext fontfile landmine
— design §12 — now fails loud there)."""
from scripts.lib.fonts import FONT_CANDIDATES, resolve_font  # noqa: F401  (moved to fonts.py; re-export for back-compat)


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
