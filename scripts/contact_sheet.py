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
from scripts.lib.footage import Footage, FootageWindow


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _tail(err: str) -> str:
    """The last non-blank line of an exception message. `proc.run`'s failure banner
    runs to ~30 lines of ffmpeg stderr; a SHEETS.md with 99 skipped clips must not
    become ~3000 lines over it — one bullet per skip, carrying the one line that
    actually names what went wrong, not the whole banner."""
    lines = [ln for ln in err.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else err


def _label(source: str, idx: int, w: FootageWindow) -> tuple[str, str]:
    """The two label lines of a window's cell: what it is, then how it measured."""
    star = " ★" if w.best else ""
    return (f"{Path(source).name} #{idx}",
            f"{w.shot_type} · {w.dur:.1f}s · {w.score:.2f}{star}")


def _markdown(footage: Footage, n_cells: int, written: list[tuple[Path, str, str]],
              skipped: list[tuple[str, str]], *, best_only: bool) -> str:
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
        "`best` (a dedup survivor in the top half of this shoot's ranking). It is a",
        "fact to weigh, **not a ranking to follow**: `score` is a percentile within",
        "THIS shoot (design 2026-08-06-intake-motion-scoring §4.2), never an absolute",
        "quality bar, so a calm, personality-forward moment can rank below action",
        "even when it is the better cut.",
        "",
    ]
    for path, first, last in written:
        lines += [f"## {path.stem} — {first} … {last}", "",
                  f"![{path.stem}](sheets/{path.name})", ""]
    if not written:
        # skipped is empty whenever build_sheets actually reaches this point: a clip
        # that HAD a candidate window and failed to decode makes build_sheets raise
        # before _markdown is ever called (the floor in build_sheets below), so this
        # branch is not reachable through that caller today. It stays anyway — this
        # function's own contract is "an honest answer for what it was given", not
        # "whatever its one caller happens to guarantee" — and it is what makes the
        # two empty causes distinguishable if that guarantee ever changes.
        if skipped:
            lines += ["No sheets: every clip with a candidate window failed to "
                      "decode — see Not sheeted below.", ""]
        else:
            lines += ["No sheets: no window matched the selection.", ""]
    if skipped:
        lines += ["## Not sheeted", ""]
        lines += [f"- `{src}` — {err}" for src, err in skipped]
        lines += [""]
    return "\n".join(lines)


def build_sheets(footage_path: str, footage_root: str, out_dir: str, *,
                 best_only: bool = False) -> dict:
    """FOOTAGE.json -> <out_dir>/sheets/sheet_NN.png + <out_dir>/SHEETS.md.

    One cell per window, one frame at the window's MIDPOINT, in clip-then-index order
    — timeline order, not score order, so the eye is not led by a scorer that already
    leans toward action. Every window by default; best_only narrows.

    `footage_root` joins against `FootageClip.source`, which is a BARE filename:
    intake stores only `Path(path).name`, never the path it was given. Same
    convention as `edl_to_reel`/`draft`'s `--footage-root` for `EDL.source`.

    A clip that will not decode is skipped, named under "Not sheeted" in SHEETS.md
    with its error, and the remaining clips are still sheeted — aborting the build
    over one bad file would lose every other clip's sheet (intake's
    quarantine-and-report precedent). Skipped, never silently.

    But EVERY candidate window failing is not "one bad file" — it is what a wrong
    footage_root, a moved footage folder, or a broken ffmpeg install looks like, and
    writing a normal-looking SHEETS.md over it would let a run reach edit-plan having
    shown not one real frame. That raises instead (the floor below) rather than
    writing an artifact that silently claims success; a build with no CANDIDATE
    windows at all (nothing to attempt — an empty FOOTAGE or a --best-only that
    matched nothing) keeps the honest-empty SHEETS.md from design §7, because an
    absent artifact would wedge the router on this stage forever."""
    footage = Footage.from_json(footage_path)
    out = Path(out_dir)
    cells: list[sheet.Cell] = []
    index: list[str] = []
    skipped: list[tuple[str, str]] = []
    for clip in footage.clips:
        picked = [(i, w) for i, w in enumerate(clip.windows) if w.best or not best_only]
        if not picked:
            continue
        src = str(Path(footage_root) / clip.source)
        times = [w.start + w.dur / 2 for _, w in picked]
        try:
            frames = assembly.frames_rgb(src, times, clip.fps)
        except (RuntimeError, ValueError) as ex:
            _log(f"contact-sheet: {clip.source} skipped — {ex}")
            skipped.append((clip.source, _tail(str(ex))))
            continue
        for (i, w), frame in zip(picked, frames):
            cells.append(sheet.Cell(image=frame, lines=_label(clip.source, i, w),
                                    marked=w.best))
            index.append(f"{Path(clip.source).name} #{i}")
    if not cells and skipped:
        first_src, first_err = skipped[0]
        raise RuntimeError(
            f"contact-sheet: every one of {len(skipped)} clip(s) with a candidate "
            f"window failed to decode (first: {first_src!r} — {first_err}) — zero "
            f"frames would be shown. This is what a wrong --footage-root, a moved "
            f"footage folder, or a broken ffmpeg install look like, not one corrupt "
            f"file. Check --footage-root={footage_root!r} is the dir the FOOTAGE "
            f"'source' names actually resolve against (or fix the ffmpeg install), "
            f"then re-run; no SHEETS.md was written.")
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


def resolve_window(footage_path: str, footage_root: str, source: str,
                   index: int) -> tuple[str, float, float, float]:
    """(clip path, start, dur, fps) for one FOOTAGE window — the --window sugar over
    an explicit --start/--dur. `source` is the exact `FootageClip.source` key — a BARE
    filename, since intake stores only `Path(path).name`, never the path it was given
    — and `footage_root` is the dir that name resolves against (same convention as
    `edl_to_reel`/`draft`'s `--footage-root`). Returns the JOINED path, so the caller
    gets something it can actually decode, not the bare name alone.

    A source not in FOOTAGE fails loud listing the ones that ARE there (build_edl's
    precedent for a mistyped source: a typo must not surface as a FileNotFound deep
    inside a decode). A resolved path absent from disk fails loud too, naming
    footage_root and source separately (extract.extract_edl's precedent), so a user
    sees which half is wrong."""
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
    src = str(Path(footage_root) / clip.source)
    if not Path(src).exists():
        raise ValueError(f"strip: source not found: {src!r} "
                         f"(footage_root={footage_root!r} + source={clip.source!r}) — "
                         f"one of the two is wrong: check footage_root is the dir the "
                         f"clip actually lives in, and source matches its real filename.")
    return src, w.start, w.dur, clip.fps


def build_strip(source: str, out: str, *, start: float, dur: float, frames: int,
                fps: float | None = None) -> dict:
    """Many frames inside ONE range -> a single image, one cell per frame labelled with
    its ABSOLUTE timestamp, so a chosen frame converts straight into a `start_offset`
    for selection.json. This is the answer to "where exactly is the peak?" that one
    midpoint frame on the overview sheet cannot give.

    Not a conveyor stage: it writes only where --out says and leaves no artifact
    behind, because it is asked for when a question arises.

    The layout is FITTED to this clip's own aspect and to sheet.READER_LONG_SIDE
    (design §2) — a delivered 9:16 reel gets a 9:16 cell instead of losing 68% of
    every cell to a 16:9 box — and `cell_px` reports what one frame actually
    rendered at, which is what the QC packet passes to its judge."""
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise ValueError(f"strip: frames must be >= 1, got {frames!r}")
    if dur <= 0:
        raise ValueError(f"strip: dur must be > 0 seconds, got {dur!r}")
    rate = fps if fps is not None else assembly.probe_stream(source).fps
    times = [start + (k + 0.5) * dur / frames for k in range(frames)]
    images = assembly.frames_rgb(source, times, rate)
    if not images:
        raise ValueError(f"strip: decoded no frames from {source} over "
                         f"[{start:.3f}, {start + dur:.3f}]s — the range may sit past "
                         f"the clip's end, or the decode dropped every frame")
    h0, w0 = images[0].shape[:2]
    cols, cell_w = sheet.fit_layout(len(images), w0 / h0)
    # Never upscale. A cell wider than the source frame renders an interpolated
    # picture and would report its BOX as the evidence's resolution; nothing here
    # creates pixels (design §7.3), and cell_px is read by the QC packet.
    cell_w = min(cell_w, w0)
    # int(), not round(): fit_layout TRUNCATES cell_w precisely so the sheet never
    # lands past its budget, and rounding the derived height back UP undoes that
    # guarantee one function later — measured, a 1920x1080 source at 13-15 frames
    # (cols=3, cell_w=497) rounds to cell_h 280 -> a 1491x1570 sheet, 2px past the
    # 1568 budget, where int() gives 279 -> 1565 (design 2026-09-08 §2).
    cell_h = max(1, int(cell_w * h0 / w0))
    cells = [sheet.Cell(image=im, lines=(f"{t:.2f}s",)) for im, t in zip(images, times)]
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.tile(cells, cols=cols, cell_w=cell_w, cell_h=cell_h).save(path)
    return {"status": "written", "strip": str(path), "frames": frames,
            "cols": cols, "cell_px": [cell_w, cell_h],
            "times": [round(t, 3) for t in times]}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="footage contact sheets (stage 5.2b): look before you cut")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="one frame per FOOTAGE window -> sheets + SHEETS.md",
                       description="one frame per FOOTAGE.json window, tiled into sheets "
                                   "in timeline order → the sheets plus SHEETS.md. The "
                                   "required look-before-you-cut stage between intake "
                                   "and edit-plan.")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from footage-intake")
    b.add_argument("--footage-root", required=True,
                   help="dir the FOOTAGE 'source' paths resolve against")
    b.add_argument("--out-dir", required=True, help="dir for SHEETS.md + sheets/")
    b.add_argument("--best-only", action="store_true",
                   help="show only intake's `best` windows (default: every window)")
    s = sub.add_parser("strip", help="many frames inside ONE window -> one image",
                       description="many frames from inside ONE window — or any file and "
                                   "time range — tiled into a single image. Use it to "
                                   "look closer at a window the sheets flagged, or at a "
                                   "delivered clip.")
    s.add_argument("--source", required=True,
                   help="clip path, or the FOOTAGE clip source when --footage is given")
    s.add_argument("--out", required=True, help="the image to write")
    s.add_argument("--frames", type=int, default=12, help="how many frames to sample")
    s.add_argument("--start", type=float,
                   help="range start, seconds (ignored if --footage/--window are both "
                        "given — the window sugar takes precedence)")
    s.add_argument("--dur", type=float,
                   help="range length, seconds (ignored if --footage/--window are both "
                        "given — the window sugar takes precedence)")
    s.add_argument("--footage", help="FOOTAGE.json — with --window, resolves the range "
                   "(takes precedence over --start/--dur when both are given)")
    s.add_argument("--footage-root",
                   help="dir the FOOTAGE 'source' paths resolve against (required "
                        "together with --footage/--window)")
    s.add_argument("--window", type=int, help="window index into --footage's clip "
                   "(with --footage, takes precedence over --start/--dur)")
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    if a.cmd == "build":
        result = build_sheets(a.footage, a.footage_root, a.out_dir, best_only=a.best_only)
    else:
        if a.footage is not None and a.window is not None:
            if a.footage_root is None:
                ap.error("strip --footage/--window needs --footage-root too")
            src, start, dur, fps = resolve_window(a.footage, a.footage_root, a.source,
                                                   a.window)
        elif a.start is not None and a.dur is not None:
            src, start, dur, fps = a.source, a.start, a.dur, None
        else:
            ap.error("strip needs either --start/--dur or --footage with --window")
        result = build_strip(src, a.out, start=start, dur=dur, frames=a.frames, fps=fps)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
