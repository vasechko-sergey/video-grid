# scripts/pacing.py
"""Pacing driver (design docs/specs/2026-07-24-scenario-first-pacing-design.md §6):
read the EDL the scenario produced, the footage it came from and one or more analyzed
music windows, fit the cuts onto the coarsest reachable grid, write PACING.{json,md}.

The stage runs AFTER edit-plan, not before it: the cuts are the input, the grid is the
output. edit_plan then re-runs with --pacing to apply the fit."""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

from scripts.lib import anchors, gridfit, pacing, runlayout, ramp as ramp_mod
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage
from scripts.lib.models import MusicSpec, RampSpec
from scripts.lib.pacing import music_identity


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _bounds(edl: EDL, footage: Footage, allow: float) -> list[tuple[float, float]]:
    """Per-episode (lo, hi) the snap may move an out-point by. `hi` is whichever is
    smaller: the allowance, or the room the episode's own shot still has after the
    SCENARIO's out-point. `lo` is the allowance, floored so the episode cannot vanish,
    and — for a ramped episode — further capped by `ramp.tail_room` so the snap cannot
    shrink the window into the still-slowed ramp region; that cap is itself floored at
    0.0, because a window whose end sits exactly at the region's own end makes
    `tail_room` a float hair negative (rounding, not a real overhang already refused at
    validation), which would otherwise turn `lo` POSITIVE and hand gridfit.fit_level an
    empty interval."""
    by_source = {c.source: c for c in footage.clips}
    out = []
    for i, ep in enumerate(edl.episodes):
        clip = by_source.get(ep.source)
        if clip is None:
            raise ValueError(f"pacing: EDL episode {i} references {ep.source!r}, which is "
                             f"not in FOOTAGE.json — have {sorted(by_source)}")
        room = clip.room_after(ep.start)
        # The SCENARIO's source length, for the same reason build_pacing fits the
        # scenario's played length: the room a cut may grow into is a property of the
        # shot and the scenario's out-point, not of whatever a previous bind left behind.
        base = ep.base_dur if ep.base_dur is not None else ep.dur
        spec = None if ep.ramp is None else RampSpec.from_dict(ep.ramp)
        shrink = max(0.0, min(allow, base / 2.0, ramp_mod.tail_room(spec, base)))
        # Outward: the speed is exactly 1 outside the ramp region, so extending the
        # PLAYED length by d costs d of source — `room - base` is already the
        # right bound in source seconds and needs no conversion.
        out.append((-shrink, min(allow, max(0.0, room - base))))
    return out


def _report(spine, fit, rejected, music_path: str, anchor_map: dict) -> str:
    rho, used, total, why = pacing.energy_agreement(spine.slots)
    # "used", not "measured": energy_agreement COUNTS a beats_in == -1 slot (not
    # recorded, design §5) as usable, so a pre-slice spine would otherwise claim
    # "18 of 18 slots measured" when nothing was ever recorded as measured (free fix,
    # final review).
    agreement = (f"{rho:+.2f} (Spearman rho, {used} of {total} slots used)"
                 if rho is not None else f"not computed — {why}")
    lines = ["# Pacing — fit report", "",
             f"- **Music:** `{Path(music_path).name}`",
             f"- **Level:** {fit.level} (every {fit.level_n} beat(s), phase {fit.phase})",
             f"- **Verdict:** {'fits' if fit.fits else 'OFF-GRID — see below'}",
             # `dev` and `fits` were the whole summary, and they cannot tell a
             # wrong-but-aligned cut from a right one: the run's shipped spine and the
             # 18-episode cut it came from both fit, and differ by 1.08 in this number
             # (design 2026-09-07 §0.3).
             f"- **Energy agreement:** {agreement}",
             "  Negative = shorter shots where the music is louder. A DESCRIPTION, not "
             "a verdict — no threshold has been measured (design 2026-09-07 §7).",
             "",
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
                  "**Read the contrast column first.** It is the fraction of the shot's "
                  "motion curve that clears the anchor floor. Near 100% the floor is "
                  "admitting the whole curve, there is no distinguished moment, and the "
                  "row says *flat* rather than listing noise as advice — measured on the "
                  "2026-08-03 run, seven of eight episodes were exactly that "
                  "(design 2026-08-18 §4).", "",
                  "| episode | contrast | anchors (s from the in-point) |",
                  "|--------:|---------:|-------------------------------|"]
        for i, (ts, contrast) in sorted(anchor_map.items()):
            cell = ", ".join(f"{t:.2f}" for t in ts) or (
                "flat — no moment is distinguishable" if contrast > anchors.ANCHOR_FLAT_FRAC
                else "–")
            lines.append(f"| {i} | {100 * contrast:.0f}% | {cell} |")
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
    # Say so HERE, where a base_dur-less EDL.json is actually READ — not only inside
    # edit_plan._bind_pacing's refusal three stages later (final review Finding 1).
    # The population that deadlocks does not always carry the arm note there: a stale
    # PACING.json fitted against a base_dur-less EDL (this branch, right now) is later
    # re-applied against a FRESHLY projected episode list, and window_to_episode always
    # sets base_dur — so the refusal's per-episode arm note never fires for exactly the
    # run that needed it. Naming the cause at the point it is true fixes that.
    no_base = [i for i, ep in enumerate(edl.episodes) if ep.base_dur is None]
    if no_base:
        _log(f"pacing: {edl_json} has {len(no_base)} of {len(edl.episodes)} episode(s) "
             f"with no `base_dur` (index {no_base}) — this EDL.json predates the "
             f"2026-08-16 fixed-point slice, or was hand-authored through the SP1 front "
             f"door. The fit below falls back to each such episode's already-bound "
             f"length instead of the scenario's (design §2.2) — legal on its own, but "
             f"if this EDL.json ALSO carries an outro fit, re-applying the PACING.json "
             f"this call writes will refuse. Escape: rebuild the EDL WITHOUT "
             f"--pacing/--music first, re-run pacing against THAT EDL.json, then "
             f"re-apply with --pacing --music")
    # The SCENARIO's played lengths, not what a previous bind or outro fit left in
    # EDL.json. Reading play_dur() here made the stage fit its own previous output:
    # a re-fit against a different window landed every cut a beat early, and after an
    # outro fit the re-apply deadlocked outright (design 2026-08-16 §1). base_play_dur()
    # falls back to play_dur() for a hand-authored SP1 EDL, which has no scenario.
    durs = [ep.base_play_dur() for ep in edl.episodes]
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
            best = (rank, spine, fit, rejected, path, m)
    _rank, spine, fit, rejected, music_path, music = best
    # Bind the spine to the WINDOW it was fitted to, not merely to a BPM (design §4).
    digest = music_identity(music.track, music.start_offset, music.duration)
    if not digest:
        _log(f"pacing: {music.track!r} could not be read, so PACING.json records no "
             f"music_digest — edit_plan will fall back to comparing tempo, which cannot "
             f"see a start_offset change. That is a not-checked, not a 'same track'")
    spine = dataclasses.replace(spine, music_digest=digest)
    if not fit.fits:
        _log(f"pacing: no level fits — best is {fit.level} with a worst cut of "
             f"{fit.worst:.3f}s. Try another window (beats --auto-start), another "
             f"scenario length, or accept an off-grid reel (check_reel's beat gate is "
             f"advisory)")
    anchor_map: dict[int, tuple[list[float], float]] = {}
    if with_anchors:
        root = Path(footage_root or ".")
        for i, ep in enumerate(edl.episodes):
            if runlayout.is_photo(ep.source):
                continue        # a still has no motion curve to anchor on (design 2026-10-20)
            curve = anchors.measure_curve(str(root / ep.source), ep.start, ep.dur)
            # the contrast rides along: without it a `–` cannot be told apart from
            # "the curve was a plateau and the floor selected nothing" (design §4)
            anchor_map[i] = (anchors.anchors_from_curve(curve),
                             anchors.curve_contrast(curve))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "PACING.json", out / "PACING.md"
    json_path.write_text(json.dumps(spine.to_dict(), indent=2))
    md_path.write_text(_report(spine, fit, rejected, music_path, anchor_map))
    return {"json": str(json_path), "md": str(md_path), "spine": spine, "fit": fit,
            "music": music_path}


def build_parser() -> argparse.ArgumentParser:
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
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    if a.anchors and not a.footage_root:
        ap.error("--anchors needs --footage-root to find the clips")
    res = build_pacing(a.edl, a.footage, a.music, a.out_dir, a.footage_root, a.anchors)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
