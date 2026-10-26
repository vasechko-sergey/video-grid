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

from scripts.lib import anchors, gridfit, hold, pacing, ramp as ramp_mod
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage
from scripts.lib.models import MUSIC_OVERRUN_TOL, MusicSpec, RampSpec
from scripts.lib.pacing import music_identity, reanalysis_duration


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
    empty interval.

    A held episode (a photo or a freeze) gets (0.0, 0.0): the grid AUTHORS its length
    instead of snapping it, and gridfit's held walk never reads its bound (design
    2026-10-21 §2.2) — a placeholder, not a claim that it cannot move."""
    by_source = {c.source: c for c in footage.clips}
    out = []
    for i, ep in enumerate(edl.episodes):
        clip = by_source.get(ep.source)
        if clip is None:
            raise ValueError(f"pacing: EDL episode {i} references {ep.source!r}, which is "
                             f"not in FOOTAGE.json — have {sorted(by_source)}")
        if ep.held():
            out.append((0.0, 0.0))     # never read: see the docstring
            continue
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


def _unplayable_hold(edl: EDL, music: MusicSpec, path: str) -> str | None:
    """Why this window cannot play the cut's authored holds, or None when it can.

    An authored `hold` is a count of beats, so its length is the window's tempo's to
    decide — and one outside [HOLD_MIN, HOLD_ROOM] would be silently clamped by the walk
    into a count the author did not write (design 2026-10-21 §2.3). Judged per window:
    the caller drops such a window from the candidates and refuses only when none is
    left, since another window at another tempo may play the same count (final review
    M2)."""
    beat = 2.0 * gridfit.allowance(music.tempo)
    for i, ep in enumerate(edl.episodes):
        if ep.hold is None:
            continue
        secs = ep.hold * beat
        if not hold.HOLD_MIN - 1e-9 <= secs <= hold.HOLD_ROOM + 1e-9:
            return (f"episode {i} authors a hold of {ep.hold} "
                    f"beat{'' if ep.hold == 1 else 's'} — {secs:.2f}s at "
                    f"{music.tempo:.1f} BPM ({Path(path).name}), outside the "
                    f"[{hold.HOLD_MIN:.2f}, {hold.HOLD_ROOM:.1f}]s a held episode may last")
    return None


def _report(spine, fit, rejected, music_path: str, anchor_map: dict) -> str:
    rho, used, total, why = pacing.energy_agreement(spine.slots)
    # "used", not "measured": energy_agreement COUNTS a beats_in == -1 slot (not
    # recorded, design §5) as usable, so a pre-slice spine would otherwise claim
    # "18 of 18 slots measured" when nothing was ever recorded as measured (free fix,
    # final review).
    agreement = (f"{rho:+.2f} (Spearman rho, {used} of {total} slots used)"
                 if rho is not None else f"not computed — {why}")
    held = [(s.index, round(s.dur * spine.tempo / 60.0)) for s in spine.slots if s.held]
    counts = ", ".join(f"episode {i} = {n} beat{'' if n == 1 else 's'}" for i, n in held)
    # silent without a held episode, so a video-only report reads exactly as before
    held_line = ([f"- **Held:** {len(held)} of {len(spine.slots)} episodes (photos or "
                  f"freezes) — the grid authored their lengths in whole beats: {counts}"]
                 if held else [])
    # An all-held reel has no cut matched against a level's lines (gridfit.every_cut_held):
    # naming a level and phase there would describe a grid no cut sits on.
    # And only a fitting one may say "on a detected beat": a held cut past the music's
    # last beat, or across a gap in the grid, is placed off the beats, and the verdict
    # below says OFF-GRID (final re-review m1).
    if gridfit.every_cut_held([s.held for s in spine.slots]):
        off = sum(1 for d in fit.devs if d > gridfit.FIT_EPS)
        level = (f"{fit.level} — every cut is a held cut on a detected beat" if fit.fits else
                 f"{fit.level} — every cut is a held cut; {off} of {len(fit.devs)} are off "
                 f"the detected beats (see below)")
    else:
        level = f"{fit.level} (every {fit.level_n} beat(s), phase {fit.phase})"
    lines = ["# Pacing — fit report", "",
             f"- **Music:** `{Path(music_path).name}`",
             f"- **Level:** {level}",
             f"- **Verdict:** {'fits' if fit.fits else 'OFF-GRID — see below'}",
             # `dev` and `fits` were the whole summary, and they cannot tell a
             # wrong-but-aligned cut from a right one: the run's shipped spine and the
             # 18-episode cut it came from both fit, and differ by 1.08 in this number
             # (design 2026-09-07 §0.3).
             f"- **Energy agreement:** {agreement}",
             "  Negative = shorter shots where the music is louder. A DESCRIPTION, not "
             "a verdict — no threshold has been measured (design 2026-09-07 §7).",
             *held_line,
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


def _overrun(spine, durs: list[float], held, music: MusicSpec, path: str) -> str:
    """The one line naming a fitted reel that runs past its music window. Not a refusal:
    the reel gate already escalates an over-flow, and an off-window reel can still be
    re-cut — but here, before any episode is rendered, is where it can be said cheaply."""
    over = spine.target_dur - music.duration
    grown = ""
    idx = [i for i, h in enumerate(held or []) if h is not None]
    if idx:
        g = sum(spine.slots[i].dur - durs[i] for i in idx)
        grown = (f", and the lengths the grid authored for the {len(idx)} held "
                 f"episode{'' if len(idx) == 1 else 's'} grew the reel {g:+.2f}s from their "
                 f"placeholders")
    return (f"pacing: the fitted reel ({spine.target_dur:.2f}s) overruns its music window "
            f"({music.duration:.2f}s, {Path(path).name}) by {over:.2f}s — the scenario's "
            f"cuts sum to {sum(durs):.2f}s{grown}. build_reel refuses a reel longer than "
            f"its window: re-analyse with headroom (beats --auto-start --duration "
            f"{reanalysis_duration(spine.target_dur, music.tempo)}) and re-run pacing")


def build_pacing(edl_json: str, footage_json: str, music_jsons: list[str], out_dir: str,
                 footage_root: str | None = None, with_anchors: bool = False) -> dict:
    """Fit the EDL's cuts onto the best of the supplied music windows.

    Every candidate window is fitted; a window the fitted reel does not overrun beats one
    it does, then the coarsest best level wins (ties broken by the smaller worst
    deviation). Returns {"json", "md", "spine", "fit", "music"}."""
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
    # A photo or a freeze: the grid authors its length in beats, between HOLD_MIN and
    # HOLD_ROOM; an authored `hold` outranks the planner (design 2026-10-21 §2).
    held = [gridfit.Held(ep.hold, hold.HOLD_MIN, hold.HOLD_ROOM) if ep.held() else None
            for ep in edl.episodes]
    # No held episode → no list at all, so a video-only fit takes the walk that existed
    # before held episodes did, by structure rather than by an all-None list staying
    # equivalent to it forever (and builds no planner)
    held = held if any(h is not None for h in held) else None
    best, unplayable = None, []
    for path in music_jsons:
        m = MusicSpec.from_json(path)
        why = _unplayable_hold(edl, m, path)
        if why is not None:
            unplayable.append(why)
            _log(f"pacing: {Path(path).name} dropped from the candidates — {why}")
            continue
        bounds = _bounds(edl, footage, gridfit.allowance(m.tempo))
        spine, fit, rejected = pacing.fit_spine(durs, m.beats, m.energy, m.energy_hz,
                                                m.tempo, bounds, held=held)
        # A window the fitted reel overruns (past MUSIC_OVERRUN_TOL, the tolerance
        # build_reel's own refusal uses) ranks below every window that covers it,
        # whatever its level: build_reel refuses a reel longer than its window, and held
        # lengths the grid authored can grow the reel past the length the window was
        # analysed for (design 2026-10-21 §2.3). Then the coarsest FITTING level wins — a
        # window whose best level misses ranks below every window that fits — and ties
        # break on the smaller worst deviation.
        covers = spine.target_dur <= m.duration + MUSIC_OVERRUN_TOL
        rank = (covers, fit.level_n if fit.fits else 0, -fit.worst)
        if best is None or rank > best[0]:
            best = (rank, spine, fit, rejected, path, m)
    if best is None:
        raise ValueError(
            f"pacing: no music window can play every authored hold — "
            f"{'; '.join(unplayable)}. Author a count that fits one of these tempos, or "
            f"drop `hold` and let the grid choose")
    _rank, spine, fit, rejected, music_path, music = best
    # Bind the spine to the WINDOW it was fitted to, not merely to a BPM (design §4).
    digest = music_identity(music.track, music.start_offset, music.duration)
    if not digest:
        _log(f"pacing: {music.track!r} could not be read, so PACING.json records no "
             f"music_digest — edit_plan will fall back to comparing tempo, which cannot "
             f"see a start_offset change. That is a not-checked, not a 'same track'")
    spine = dataclasses.replace(spine, music_digest=digest)
    if spine.target_dur > music.duration + MUSIC_OVERRUN_TOL:
        _log(_overrun(spine, durs, held, music, music_path))
    if not fit.fits:
        _log(f"pacing: no level fits — best is {fit.level} with a worst cut of "
             f"{fit.worst:.3f}s. Try another window (beats --auto-start), another "
             f"scenario length, or accept an off-grid reel (check_reel's beat gate is "
             f"advisory)")
    anchor_map: dict[int, tuple[list[float], float]] = {}
    if with_anchors:
        root = Path(footage_root or ".")
        for i, ep in enumerate(edl.episodes):
            if ep.held():
                continue        # a photo or a held frame has no motion curve to anchor on
                                # (designs 2026-10-20, 2026-10-21 §2.3)
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
