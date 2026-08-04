"""Edit-plan authoring (design docs/specs/2026-07-12-edit-plan-spine-design.md, stage 5.7).

The 5.7 driver: an agent-authored selection.json (window references + editorial
fields) → a typed EDL.json + a human EDL.md map, which the existing edl_to_reel
(SP1) takes to a delivered reel. Selection lives in the agent's judgment; this
module is the thin mechanical half — projection + preflight + render. Contract
vs. logic split mirrors footage.py (contract) ↔ intake.py (logic).

The mechanical window fields (source/start/dur/shot_type/description) reach the
EDL BY REFERENCE through window_to_episode — never retyped by the agent, because
a retyped start/dur is the silent-wrong-cut class (montage §12). selection.json
carries only integer window indices + editorial enums/notes.
"""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

from scripts.lib import gridfit
from scripts.lib.edl import EDL, EDLEpisode, preflight, write_edl
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.pacing import Spine
from scripts.lib.project import ProjectConfig


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


_BACK_EDGE_TOL = 1e-6      # a realized total within this of the spine target "fills the spine"


def window_to_episode(clip: FootageClip, window: FootageWindow, start_offset: float = 0.0,
                      **editorial: object) -> EDLEpisode:
    """Project a scored FootageWindow onto an EDLEpisode. Mechanical fields come
    from the clip/window by reference; editorial fields (composition/grid required;
    layout/motion/hero/crop_*/rect/background*/border_*/color_means/beat_slot/
    white_balance/black_point/highlight/saturation/shadow_red/mid_blue/dip/tone_*
    optional) are forwarded to EDLEpisode, whose __post_init__ is the single
    value-validation site. shot_type/processing_notes default to the window's
    shot_type/description but an editorial value overrides. An unknown or missing
    editorial field raises ValueError naming it.

    `start_offset` moves the in-point later inside the SAME shot — the fine-tune atop
    intake's activity units (2026-07-25 activity-units): a unit is anchored on an
    activity peak with its lead-in, but the exact frame to cut on can still sit a beat
    inside it, and an offset reaches it without re-carving. It shifts the in-point
    ONLY; `dur` still comes from the window
    (and then from the spine), so an offset can never silently lengthen an episode.
    Crossing a scene cut is refused: the in-point would land in a different shot than
    the one the window scored, so its shot_type/description would describe other footage.
    """
    if isinstance(start_offset, bool) or not isinstance(start_offset, (int, float)):
        raise ValueError(f"window_to_episode: start_offset must be a number of seconds, "
                         f"got {start_offset!r}")
    if start_offset < 0:
        raise ValueError(f"window_to_episode: start_offset must be >= 0 seconds, got "
                         f"{start_offset!r} — to start EARLIER, reference an earlier window")
    start = window.start + start_offset
    if start >= clip.dur:
        raise ValueError(
            f"window_to_episode: start_offset {start_offset}s puts the in-point at {start:.2f}s, "
            f"past the end of {clip.source} ({clip.dur:.2f}s)")
    crossed = [c for c in clip.scene_cuts if window.start < c <= start]
    if crossed:
        raise ValueError(
            f"window_to_episode: start_offset {start_offset}s crosses a scene cut at "
            f"{crossed[0]:.2f}s in {clip.source} — the in-point would land in a DIFFERENT shot "
            f"than the window scored. Reference the window that starts after the cut instead")
    room = clip.room_after(start)
    if window.dur > room:
        raise ValueError(
            f"window_to_episode: start_offset {start_offset}s puts the out-point at "
            f"{start + window.dur:.2f}s, past the {room:.2f}s of room the shot has after "
            f"{start:.2f}s in {clip.source} — the episode would cross a scene cut or run "
            f"past the clip. Pick an earlier in-point (a smaller start_offset) or a "
            f"shorter window")
    defaults = {"shot_type": window.shot_type, "processing_notes": window.description}
    try:
        return EDLEpisode(source=clip.source, start=start, dur=window.dur,
                          **{**defaults, **editorial})
    except TypeError as ex:
        raise ValueError(f"window_to_episode: unknown or missing editorial field — {ex}") from ex


_MERGE_TOL = 1e-3   # s: FOOTAGE stores round(start, 3) and round(dur, 3) independently, so a
                    # merged envelope end can sit up to ~1ms past its true cut/clip-end boundary;
                    # tolerate (and clamp) that slop so a span ending on a cut or the clip end is
                    # not falsely refused as a straddle.


def _merge_windows(clip: FootageClip, i: int, j: int) -> FootageWindow:
    """Merge adjacent footage windows i..j (inclusive) into one FootageWindow covering
    [min start .. max end] — an episode spanning several activity units plus the connective
    footage between them (design 2026-07-26-edit-plan-span-merge §3, "turn -> drive -> turn").

    The merged window inherits window i's shot_type/description as the projection seed (an
    editorial override still wins in window_to_episode) and unions the track_ids across the
    range. It refuses a range whose envelope straddles a scene cut — that would splice two
    shots into one episode; `room_after` is the single geometric authority (the same rule
    window_to_episode applies), naming the offending cut for a span-specific remedy. Crossing
    a presence transition inside one shot is allowed (scene_cuts holds only real cuts, and
    room_after stops only at cuts). An envelope end within _MERGE_TOL of a cut/clip-end
    boundary is a rounding artefact (FOOTAGE rounds start and dur independently), so it is
    clamped to the boundary rather than refused; beyond the tolerance with no cut inside, the
    last window lies past the clip and the merge fails loud. Assumes a valid
    0 <= i < j < len(clip.windows); build_edl bounds-checks."""
    wins = clip.windows[i:j + 1]
    start = min(w.start for w in wins)
    end = max(w.start + w.dur for w in wins)
    tids = sorted({t for w in wins for t in w.track_ids})
    room = clip.room_after(start)
    if end - start > room + _MERGE_TOL:
        inside = [c for c in clip.scene_cuts if start < c < end]
        if inside:
            raise ValueError(
                f"_merge_windows: span [{i}, {j}] runs {end - start:.2f}s from {start:.2f}s in "
                f"{clip.source}, but a scene cut at {min(inside):.2f}s lies inside it — a span cannot "
                f"cross a scene cut (it would splice two shots into one episode). Split it into two "
                f"episodes, one on each side of the cut")
        raise ValueError(
            f"_merge_windows: span [{i}, {j}] envelope ends at {end:.2f}s, past the end of "
            f"{clip.source} ({clip.dur:.2f}s) — the last window extends beyond the clip; re-run "
            f"footage-intake to regenerate FOOTAGE.json")
    return dataclasses.replace(clip.windows[i], start=start,
                               dur=min(end - start, room), track_ids=tids)


def _resolve_window(clip: FootageClip, window: object, source: str, k: int) -> FootageWindow:
    """Resolve a selection episode's `window` ref to one FootageWindow. An int is a single
    window (the 5.7 behaviour); a two-element [i, j] list is a span merged into one episode
    (§3b). Fail-loud on a bad shape, a bad type, or an out-of-range index — naming episode k."""
    if isinstance(window, list):
        if len(window) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in window):
            raise ValueError(f"selection episode {k}: a span 'window' must be [i, j] — two "
                             f"integer indices, got {window!r}")
        i, j = window
        if not 0 <= i < j < len(clip.windows):
            raise ValueError(f"selection episode {k}: span window {window} out of range for "
                             f"{source} (need 0 <= i < j < {len(clip.windows)}; for a single "
                             f'window use "window": i)')
        return _merge_windows(clip, i, j)
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError(f"selection episode {k}: 'window' must be an integer index or a "
                         f"[i, j] span into FOOTAGE")
    if not 0 <= window < len(clip.windows):
        raise ValueError(f"selection episode {k}: window {window} out of range for {source} "
                         f"(has {len(clip.windows)})")
    return clip.windows[window]


_SNAP_TOL = 1e-3      # s of float slack when comparing a slot against its episode


def _bind_pacing(episodes: list, spine: Spine) -> list:
    """Apply a FITTED spine: episode i takes slot i's duration and `beat_slot=i`.

    The spine was fitted TO these episodes (scripts/pacing.py reads the same EDL), so a
    slot may differ from its episode only by the snap the fit was allowed — half a beat.
    A larger difference means this spine was fitted to a DIFFERENT edit, and copying its
    length across would truncate a shot exactly the way the generator used to: a 7.3s
    ride into a 4.6s slot, in silence. Refuse instead.

    Zip-to-min; an over/underflow is logged, never a silent drop (§4.1)."""
    allow = gridfit.allowance(spine.tempo) + _SNAP_TOL
    n = min(len(episodes), len(spine.slots))
    bound = []
    for i in range(n):
        slot, ep = spine.slots[i], episodes[i]
        if abs(slot.dur - ep.dur) > allow:
            raise ValueError(
                f"pacing: slot {i} is {slot.dur:.2f}s against a {ep.dur:.2f}s episode — "
                f"further apart than the {allow:.2f}s snap allows, so this PACING.json "
                f"was fitted to a different edit. Re-run pacing against the current "
                f"EDL.json before binding")
        bound.append(dataclasses.replace(ep, beat_slot=i, dur=slot.dur))
    if len(episodes) > len(spine.slots):
        _log(f"pacing: {len(episodes)} episodes exceed the {len(spine.slots)}-slot spine "
             f"— the {len(episodes) - len(spine.slots)} tail episode(s) keep beat_slot=None; "
             f"re-run pacing against the current EDL.json")
        bound.extend(episodes[n:])
    elif len(spine.slots) > len(episodes):
        _log(f"pacing: {len(spine.slots)} slots exceed the {len(episodes)} episodes — the "
             f"{len(spine.slots) - len(episodes)} tail slot(s) are unfilled")
    return bound


def _back_edge_target(episodes: list, spine: Spine) -> float:
    """The reel's target length: the realized footage, clamped to the fitted spine. This
    is now the ORDINARY way a target is computed (design 2026-07-24 §1) rather than a
    rescue for an under-fill — the music is cut to the reel, not the reel to the music.
    An under-fill re-times the target DOWN to what the footage actually
    delivers — the montage §4.1 pacing-gate back-edge — so the reel's length gate passes by
    construction instead of escalating a whole pipeline later. An over-flow keeps the
    fragment length, so the excess escalates at the reel gate rather than reaching mix,
    which refuses a stem longer than its fragment (§2). `realized` sums EVERY bound episode,
    including an over-flow tail left at beat_slot=None — the reel is as long as everything
    in it. Both directions log; neither is silent."""
    realized = sum(e.dur for e in episodes)
    if realized < spine.target_dur - _BACK_EDGE_TOL:
        _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s of the "
             f"{spine.target_dur:.2f}s spine — re-timing the reel target to {realized:.2f}s; "
             f"for a tighter cut re-pick a shorter fragment "
             f"(beats --auto-start --duration {realized:.0f}) and re-derive the spine")
    elif realized > spine.target_dur + _BACK_EDGE_TOL:
        _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s against a "
             f"{spine.target_dur:.2f}s spine — the target stays at the fragment length; the "
             f"excess {realized - spine.target_dur:.2f}s escalates at the reel gate "
             f"(extend the fragment or drop episodes — music cannot be invented)")
    return min(realized, spine.target_dur)


def build_edl(footage: Footage, selection: dict, pacing: Spine | None = None,
              cast: str | None = None) -> EDL:
    """Assemble an EDL from a selection dict; when a pacing Spine is supplied, bind each
    episode to its slot (beat_slot + the FITTED dur, which is the episode's own length plus
    at most a half-beat snap — binding applies a fit, it does not re-time). Each selection
    episode references a
    window by (source, integer index) — or a two-element `[i, j]` span merged into one
    episode (§3b) — into FOOTAGE and supplies editorial fields;
    window_to_episode projects the mechanical fields. Reel knobs (music/cap/
    target_dur) ride at the top level — except target_dur is instead DERIVED from the spine
    (the pacing-gate back-edge, §4) when pacing is supplied, since pacing owns a paced reel's
    length; cast is the cast.json path (§6.1a) — a driver-level knob like pacing, not an
    editorial field in selection.json, since it names the registry an episode's hero *name*
    resolves against, not a per-episode choice. Fail-loud on a source not in FOOTAGE or an
    out-of-range window index (a typo would else surface as a FileNotFound deep in extract —
    montage §12)."""
    eps_in = selection.get("episodes")
    if not isinstance(eps_in, list) or not eps_in:
        raise ValueError("selection.episodes must be a non-empty list of episode objects")
    by_source = {c.source: c for c in footage.clips}
    episodes: list[EDLEpisode] = []
    for k, sel in enumerate(eps_in):
        if not isinstance(sel, dict):
            raise ValueError(f"selection episode {k} must be an object, got {type(sel).__name__}")
        ed = dict(sel)
        source = ed.pop("source", None)
        window = ed.pop("window", None)
        # popped like source/window, not forwarded as editorial: it is a MECHANICAL
        # field (it moves the cut), and EDLEpisode would reject it as unknown.
        start_offset = ed.pop("start_offset", 0.0)
        if not (isinstance(source, str) and source):
            raise ValueError(f"selection episode {k}: 'source' must be a clip path string")
        clip = by_source.get(source)
        if clip is None:
            raise ValueError(f"selection episode {k}: source {source!r} not in FOOTAGE — "
                             f"have {sorted(by_source)}")
        fw = _resolve_window(clip, window, source, k)
        episodes.append(window_to_episode(clip, fw, start_offset=start_offset, **ed))
    target = selection.get("target_dur")
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
        target = _back_edge_target(episodes, pacing)   # pacing owns a paced reel's length (§4)
    cap = selection.get("cap")
    return EDL(episodes=tuple(episodes), music=selection.get("music"), cast=cast,
               cap=cap if cap is not None else 3, target_dur=target)


def write_edit_plan(footage_path: str, selection_path: str, project_path: str, out_dir: str,
                    pacing_path: str | None = None, cast: str | None = None) -> dict:
    """Author EDL.json + EDL.md from FOOTAGE + a selection, gated by the project's
    manifest preflight. Nothing is written when preflight fails — a bad EDL never
    lands as a half-valid artifact. cast is cast.json from intake — required if any
    episode pins a cast name (§6.1a); preflight below loads the registry and reports
    an unresolved name as part of its normal stop_and_report, not a raise. Returns
    {"status": "written", ...} or the preflight stop_and_report verbatim."""
    footage = Footage.from_json(footage_path)
    try:
        selection = json.loads(Path(selection_path).read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{selection_path} is not valid JSON ({e}) — fix the selection syntax") from e
    cfg = ProjectConfig.from_json(project_path)
    pacing = Spine.from_json(pacing_path) if pacing_path else None
    edl = build_edl(footage, selection, pacing=pacing, cast=cast)
    _, stop = preflight(edl, cfg, str(Path(out_dir) / "segments"), out_dir)
    if stop:
        return stop
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    edl_path, md_path = Path(out_dir) / "EDL.json", Path(out_dir) / "EDL.md"
    write_edl(edl, edl_path, selection=selection_path)
    md_path.write_text(edl.to_markdown())
    return {"status": "written", "edl": str(edl_path), "md": str(md_path),
            "episodes": len(edl.episodes)}


def main() -> None:
    ap = argparse.ArgumentParser(description="author EDL.json + EDL.md from FOOTAGE + a selection (stage 5.7)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build EDL.json + EDL.md from a selection")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from intake (stage 5.2)")
    b.add_argument("--selection", required=True, help="selection.json — window refs + editorial fields")
    b.add_argument("--project", required=True, help="project.json — canvas/delivery for the preflight")
    b.add_argument("--out-dir", required=True, help="dir for EDL.json + EDL.md")
    b.add_argument("--pacing", help="PACING.json — bind episodes to the energy spine (optional, §5.6)")
    b.add_argument("--cast", help="cast.json from intake — required if any episode pins a cast name (§6.1a)")
    a = ap.parse_args()
    result = write_edit_plan(a.footage, a.selection, a.project, a.out_dir, a.pacing, cast=a.cast)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "written" else 1)


if __name__ == "__main__":
    main()
