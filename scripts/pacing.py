# scripts/pacing.py
"""Pacing driver (design docs/specs/2026-07-24-scenario-first-pacing-design.md §6):
read the EDL the scenario produced, the footage it came from and one or more analyzed
music windows, fit the cuts onto the coarsest reachable grid, write PACING.{json,md}.

The stage runs AFTER edit-plan, not before it: the cuts are the input, the grid is the
output. edit_plan then re-runs with --pacing to apply the fit."""
import argparse
import json
import sys
from pathlib import Path

from scripts.lib import anchors, gridfit, pacing, ramp as ramp_mod
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage
from scripts.lib.models import MusicSpec, RampSpec


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _bounds(edl: EDL, footage: Footage, allow: float) -> list[tuple[float, float]]:
    """Per-episode (lo, hi) the snap may move an out-point by. `hi` is whichever is
    smaller: the allowance, or the room the episode's own shot still has after it ends.
    `lo` is the allowance, floored so the episode cannot vanish, and — for a ramped
    episode — further capped by `ramp.tail_room` so the snap cannot shrink the window
    into the still-slowed ramp region; that cap is itself floored at 0.0, because a
    window whose end sits exactly at the region's own end makes `tail_room` a float
    hair negative (rounding, not a real overhang already refused at validation), which
    would otherwise turn `lo` POSITIVE and hand gridfit.fit_level an empty interval."""
    by_source = {c.source: c for c in footage.clips}
    out = []
    for i, ep in enumerate(edl.episodes):
        clip = by_source.get(ep.source)
        if clip is None:
            raise ValueError(f"pacing: EDL episode {i} references {ep.source!r}, which is "
                             f"not in FOOTAGE.json — have {sorted(by_source)}")
        room = clip.room_after(ep.start)
        # Outward: the speed is exactly 1 outside the ramp region, so extending the
        # PLAYED length by d costs d of source — `room - ep.dur` is already the
        # right bound in source seconds and needs no conversion.
        #
        # Inward is the asymmetric direction. The window may not shrink into the
        # ramp region: a cut landing while the shot is still slowed is the artefact
        # ramp.validate_window exists to refuse (design §2, §6). Floored at 0.0: a
        # window flush with the ramp region's own end (validate_window already
        # guarantees tail_room >= 0 up to float slop) can make tail_room a hair
        # negative, which would otherwise make `lo` positive and empty the interval
        # against a `hi` of 0.0 — exactly the case of a ramp on a clip's LAST window.
        spec = None if ep.ramp is None else RampSpec.from_dict(ep.ramp)
        shrink = max(0.0, min(allow, ep.dur / 2.0, ramp_mod.tail_room(spec, ep.dur)))
        out.append((-shrink, min(allow, max(0.0, room - ep.dur))))
    return out


def _report(spine, fit, rejected, music_path: str, anchor_map: dict) -> str:
    lines = ["# Pacing — fit report", "",
             f"- **Music:** `{Path(music_path).name}`",
             f"- **Level:** {fit.level} (every {fit.level_n} beat(s), phase {fit.phase})",
             f"- **Verdict:** {'fits' if fit.fits else 'OFF-GRID — see below'}", "",
             "| level | step | worst | needed | verdict |",
             "|-------|-----:|------:|-------:|---------|"]
    for f in list(rejected) + ([fit] if fit.fits else []):
        need = max(f.needs) if f.needs else 0.0
        lines.append(f"| {f.level} | {f.level_n} beats | {f.worst:.3f} | {need:.3f} | "
                     f"{'fits' if f.fits else 'misses'} |")
    lines += ["", spine.to_markdown()]
    if anchor_map:
        lines += ["## Action anchors (advisory)", "",
                  "A proxy — global frame difference, so a camera whip reads as an event "
                  "too. Move an in-point onto one by setting `start_offset` in "
                  "selection.json and re-running edit-plan.", "",
                  "| episode | anchors (s from the in-point) |",
                  "|--------:|-------------------------------|"]
        for i, ts in sorted(anchor_map.items()):
            lines.append(f"| {i} | {', '.join(f'{t:.2f}' for t in ts) or '–'} |")
    return "\n".join(lines) + "\n"


def build_pacing(edl_json: str, footage_json: str, music_jsons: list[str], out_dir: str,
                 footage_root: str | None = None, with_anchors: bool = False) -> dict:
    """Fit the EDL's cuts onto the best of the supplied music windows.

    Every candidate window is fitted; the one whose best level is coarsest (ties broken by
    the smaller worst deviation) wins. Returns {"json", "md", "spine", "fit", "music"}."""
    if not music_jsons:
        raise ValueError("pacing: at least one --music MUSIC.json is required — the fit "
                         "needs a beat grid (a silent reel skips this stage entirely)")
    edl = EDL.from_json(edl_json)
    footage = Footage.from_json(footage_json)
    # PLAYED lengths, not source windows: the grid is fitted to what the viewer
    # watches. Reading `dur` here is what let a ramped episode drift every later
    # cut off its musical line (design §6).
    durs = [ep.play_dur() for ep in edl.episodes]
    best = None
    for path in music_jsons:
        m = MusicSpec.from_json(path)
        bounds = _bounds(edl, footage, gridfit.allowance(m.tempo))
        spine, fit, rejected = pacing.fit_spine(durs, m.beats, m.energy, m.energy_hz,
                                                m.tempo, bounds)
        # Coarsest FITTING level wins; a window whose best level misses ranks below every
        # window that fits, and ties break on the smaller worst deviation.
        rank = (fit.level_n if fit.fits else 0, -fit.worst)
        if best is None or rank > best[0]:
            best = (rank, spine, fit, rejected, path)
    _rank, spine, fit, rejected, music_path = best
    if not fit.fits:
        _log(f"pacing: no level fits — best is {fit.level} with a worst cut of "
             f"{fit.worst:.3f}s. Try another window (beats --auto-start), another "
             f"scenario length, or accept an off-grid reel (check_reel's beat gate is "
             f"advisory)")
    anchor_map: dict[int, list[float]] = {}
    if with_anchors:
        root = Path(footage_root or ".")
        for i, ep in enumerate(edl.episodes):
            curve = anchors.measure_curve(str(root / ep.source), ep.start, ep.dur)
            anchor_map[i] = anchors.anchors_from_curve(curve)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "PACING.json", out / "PACING.md"
    json_path.write_text(json.dumps(spine.to_dict(), indent=2))
    md_path.write_text(_report(spine, fit, rejected, music_path, anchor_map))
    return {"json": str(json_path), "md": str(md_path), "spine": spine, "fit": fit,
            "music": music_path}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="fit the EDL's cuts onto a musical grid -> PACING.{json,md}")
    ap.add_argument("--edl", required=True, help="EDL.json from edit-plan (the cuts)")
    ap.add_argument("--footage", required=True, help="FOOTAGE.json (for each shot's room)")
    ap.add_argument("--music", required=True, action="append",
                    help="MUSIC.json — repeat to compare several analyzed windows")
    ap.add_argument("--out-dir", required=True, help="where to write PACING.{json,md}")
    ap.add_argument("--footage-root", help="root the EDL's sources resolve against "
                                           "(required with --anchors)")
    ap.add_argument("--anchors", action="store_true",
                    help="measure action anchors for each episode (one ffmpeg pass each)")
    a = ap.parse_args()
    if a.anchors and not a.footage_root:
        ap.error("--anchors needs --footage-root to find the clips")
    res = build_pacing(a.edl, a.footage, a.music, a.out_dir, a.footage_root, a.anchors)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
