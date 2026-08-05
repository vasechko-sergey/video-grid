"""Footage contact sheets (design docs/specs/2026-08-05-footage-contact-sheet-design.md,
stage 5.2b): the edit-plan agent's first look at actual pixels.

`build` renders ONE frame per FOOTAGE window across the whole shoot -> sheets/*.png +
SHEETS.md, the artifact the router keys on. `strip` renders MANY frames inside ONE
window -> a single image, for the timing and identity questions a single frame cannot
answer. Sampling and I/O live here; the layout is pure in lib/sheet.py.

No ffmpeg argv is built here — frames come from assembly.frames_rgb, which decodes
once per 60-frame chunk with a select filter (never -ss, montage §12).
"""
import argparse
import json
import sys
from pathlib import Path

from scripts.lib import assembly, sheet
from scripts.lib.footage import Footage

STRIP_COLS = 6      # a strip reads left-to-right in time; 6 keeps the row inside the
                    # image-size limit while staying wide enough to see a motion arc.


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _label(source: str, idx: int, w) -> tuple[str, str]:
    """The two label lines of a window's cell: what it is, then how it measured."""
    star = " ★" if w.best else ""
    return (f"{Path(source).name} #{idx}",
            f"{w.shot_type} · {w.dur:.1f}s · {w.score:.2f}{star}")


def _markdown(footage: Footage, n_cells: int, written: list, skipped: list,
              *, best_only: bool) -> str:
    """The index the reader actually opens. It states the scoring bias in place,
    because the ★ column is exactly where a reader would otherwise defer to the
    ranking (design §1.1)."""
    wins = [w for c in footage.clips for w in c.windows]
    n_best = sum(1 for w in wins if w.best)
    scope = "best windows only" if best_only else "every window"
    lines = [
        f"# Contact sheets — {len(footage.clips)} clips, {len(wins)} windows "
        f"({n_best} best), {n_cells} shown ({scope})",
        "",
        "Cells run in timeline order — clip, then window index. ★ marks intake's",
        "`best` (a dedup survivor scoring >= 0.50). It is a fact to weigh,",
        "**not a ranking to follow**: the window score peaks at motion 0.35 and",
        "is zero at static, so calm, personality-forward moments rank below",
        "action even when they are the better cut.",
        "",
    ]
    for path, first, last in written:
        lines += [f"## {path.stem} — {first} … {last}", "",
                  f"![{path.stem}](sheets/{path.name})", ""]
    if not written:
        lines += ["No sheets: no window matched the selection.", ""]
    if skipped:
        lines += ["## Not sheeted", ""]
        lines += [f"- `{src}` — {err}" for src, err in skipped]
        lines += [""]
    return "\n".join(lines)


def build_sheets(footage_path: str, out_dir: str, *, best_only: bool = False) -> dict:
    """FOOTAGE.json -> <out_dir>/sheets/sheet_NN.png + <out_dir>/SHEETS.md.

    One cell per window, one frame at the window's MIDPOINT, in clip-then-index order
    — timeline order, not score order, so the eye is not led by a scorer that already
    leans toward action. Every window by default; best_only narrows.

    A clip that will not decode is skipped, named under "Not sheeted" in SHEETS.md
    with its error, and the remaining clips are still sheeted — aborting the build
    over one bad file would lose every other clip's sheet (intake's
    quarantine-and-report precedent). Skipped, never silently."""
    footage = Footage.from_json(footage_path)
    out = Path(out_dir)
    cells: list[sheet.Cell] = []
    index: list[str] = []
    skipped: list[tuple[str, str]] = []
    for clip in footage.clips:
        picked = [(i, w) for i, w in enumerate(clip.windows) if w.best or not best_only]
        if not picked:
            continue
        times = [w.start + w.dur / 2 for _, w in picked]
        try:
            frames = assembly.frames_rgb(clip.source, times, clip.fps)
        except (RuntimeError, ValueError) as ex:
            _log(f"contact-sheet: {clip.source} skipped — {ex}")
            skipped.append((clip.source, str(ex)))
            continue
        for (i, w), frame in zip(picked, frames):
            cells.append(sheet.Cell(image=frame, lines=_label(clip.source, i, w),
                                    marked=w.best))
            index.append(f"{Path(clip.source).name} #{i}")
    pages = sheet.paginate(cells)
    out.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, str, str]] = []
    at = 0
    for n, page in enumerate(pages):
        (out / "sheets").mkdir(parents=True, exist_ok=True)
        path = out / "sheets" / f"sheet_{n:02d}.png"
        sheet.tile(page).save(path)
        written.append((path, index[at], index[at + len(page) - 1]))
        at += len(page)
    md = out / "SHEETS.md"
    md.write_text(_markdown(footage, len(cells), written, skipped, best_only=best_only))
    return {"status": "written", "sheets": [str(p) for p, _, _ in written],
            "cells": len(cells), "skipped": [s for s, _ in skipped], "md": str(md)}


def resolve_window(footage_path: str, source: str, index: int) -> tuple[str, float, float, float]:
    """(clip source, start, dur, fps) for one FOOTAGE window — the --window sugar over
    an explicit --start/--dur. A source not in FOOTAGE fails loud listing the ones that
    ARE there (build_edl's precedent for a mistyped source: a typo must not surface as
    a FileNotFound deep inside a decode)."""
    footage = Footage.from_json(footage_path)
    by_source = {c.source: c for c in footage.clips}
    clip = by_source.get(source)
    if clip is None:
        raise ValueError(f"strip: source {source!r} is not in {footage_path} — have "
                         f"{sorted(by_source)}")
    if not 0 <= index < len(clip.windows):
        raise ValueError(f"strip: window {index} out of range for {source} "
                         f"(has {len(clip.windows)})")
    w = clip.windows[index]
    return clip.source, w.start, w.dur, clip.fps


def build_strip(source: str, out: str, *, start: float, dur: float, frames: int,
                fps: float | None = None) -> dict:
    """Many frames inside ONE range -> a single image, one cell per frame labelled with
    its ABSOLUTE timestamp, so a chosen frame converts straight into a `start_offset`
    for selection.json. This is the answer to "where exactly is the peak?" that one
    midpoint frame on the overview sheet cannot give.

    Not a conveyor stage: it writes only where --out says and leaves no artifact
    behind, because it is asked for when a question arises."""
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise ValueError(f"strip: frames must be >= 1, got {frames!r}")
    if dur <= 0:
        raise ValueError(f"strip: dur must be > 0 seconds, got {dur!r}")
    rate = fps if fps is not None else assembly.probe_stream(source).fps
    times = [start + (k + 0.5) * dur / frames for k in range(frames)]
    images = assembly.frames_rgb(source, times, rate)
    cells = [sheet.Cell(image=im, lines=(f"{t:.2f}s",)) for im, t in zip(images, times)]
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.tile(cells, cols=min(frames, STRIP_COLS)).save(path)
    return {"status": "written", "strip": str(path), "frames": frames,
            "times": [round(t, 3) for t in times]}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="footage contact sheets (stage 5.2b): look before you cut")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="one frame per FOOTAGE window -> sheets + SHEETS.md")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from footage-intake")
    b.add_argument("--out-dir", required=True, help="dir for SHEETS.md + sheets/")
    b.add_argument("--best-only", action="store_true",
                   help="show only intake's `best` windows (default: every window)")
    s = sub.add_parser("strip", help="many frames inside ONE window -> one image")
    s.add_argument("--source", required=True,
                   help="clip path, or the FOOTAGE clip source when --footage is given")
    s.add_argument("--out", required=True, help="the image to write")
    s.add_argument("--frames", type=int, default=12, help="how many frames to sample")
    s.add_argument("--start", type=float, help="range start, seconds")
    s.add_argument("--dur", type=float, help="range length, seconds")
    s.add_argument("--footage", help="FOOTAGE.json — with --window, resolves the range")
    s.add_argument("--window", type=int, help="window index into --footage's clip")
    a = ap.parse_args()
    if a.cmd == "build":
        result = build_sheets(a.footage, a.out_dir, best_only=a.best_only)
    else:
        if a.footage is not None and a.window is not None:
            src, start, dur, fps = resolve_window(a.footage, a.source, a.window)
        elif a.start is not None and a.dur is not None:
            src, start, dur, fps = a.source, a.start, a.dur, None
        else:
            ap.error("strip needs either --start/--dur or --footage with --window")
        result = build_strip(src, a.out, start=start, dur=dur, frames=a.frames, fps=fps)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
