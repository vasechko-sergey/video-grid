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

from scripts.lib.edl import EDL, EDLEpisode, preflight
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.pacing import Spine
from scripts.lib.project import ProjectConfig


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


_BACK_EDGE_TOL = 1e-6      # a realized total within this of the spine target "fills the spine"


def window_to_episode(clip: FootageClip, window: FootageWindow, **editorial: object) -> EDLEpisode:
    """Project a scored FootageWindow onto an EDLEpisode. Mechanical fields come
    from the clip/window by reference; editorial fields (composition/grid required;
    layout/motion/hero/crop_*/rect/background/border_*/color_means/beat_slot
    optional) are forwarded to EDLEpisode, whose __post_init__ is the single
    value-validation site. shot_type/processing_notes default to the window's
    shot_type/description but an editorial value overrides. An unknown or missing
    editorial field raises ValueError naming it."""
    defaults = {"shot_type": window.shot_type, "processing_notes": window.description}
    try:
        return EDLEpisode(source=clip.source, start=window.start, dur=window.dur,
                          **{**defaults, **editorial})
    except TypeError as ex:
        raise ValueError(f"window_to_episode: unknown or missing editorial field — {ex}") from ex


def _bind_pacing(episodes: list, spine: Spine) -> list:
    """Bind selected episodes to spine slots by position (design §5): episode i → slot
    i (beat_slot=i, dur re-timed to the slot, window start preserved). Zip-to-min; a
    window shorter than its slot keeps its own dur (can't stretch footage) + logs; an
    over/underflow is logged, never a silent drop (§4.1)."""
    n = min(len(episodes), len(spine.slots))
    bound = []
    for i in range(n):
        slot, ep = spine.slots[i], episodes[i]
        new_dur = min(ep.dur, slot.dur)
        if ep.dur < slot.dur:
            _log(f"pacing: episode {i} window {ep.dur:.2f}s is shorter than its slot "
                 f"{slot.dur:.2f}s — keeping the window (can't stretch footage); the "
                 f"length gate will see the shortfall")
        bound.append(dataclasses.replace(ep, beat_slot=i, dur=new_dur))
    if len(episodes) > len(spine.slots):
        _log(f"pacing: {len(episodes)} episodes exceed the {len(spine.slots)}-slot spine "
             f"— the {len(episodes) - len(spine.slots)} tail episode(s) keep beat_slot=None; "
             f"extend the track fragment or drop episodes")
        bound.extend(episodes[n:])
    elif len(spine.slots) > len(episodes):
        _log(f"pacing: {len(spine.slots)} slots exceed the {len(episodes)} episodes — the "
             f"{len(spine.slots) - len(episodes)} tail slot(s) are unfilled")
    return bound


def _back_edge_target(episodes: list, spine: Spine) -> float:
    """The paced reel's target length (design §4): the realized footage, clamped to the
    spine's fragment. An under-fill re-times the target DOWN to what the footage actually
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
    episode to its slot (beat_slot + re-timed dur, §5.6). Each selection episode references a
    window by (source, integer index) into FOOTAGE and supplies editorial fields;
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
        if not (isinstance(source, str) and source):
            raise ValueError(f"selection episode {k}: 'source' must be a clip path string")
        if isinstance(window, bool) or not isinstance(window, int):
            raise ValueError(f"selection episode {k}: 'window' must be an integer index into FOOTAGE")
        clip = by_source.get(source)
        if clip is None:
            raise ValueError(f"selection episode {k}: source {source!r} not in FOOTAGE — "
                             f"have {sorted(by_source)}")
        if not 0 <= window < len(clip.windows):
            raise ValueError(f"selection episode {k}: window {window} out of range for {source} "
                             f"(has {len(clip.windows)})")
        episodes.append(window_to_episode(clip, clip.windows[window], **ed))
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
    edl_path.write_text(json.dumps(edl.to_dict(), indent=2))
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
