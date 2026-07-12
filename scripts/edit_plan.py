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
import json
from pathlib import Path

from scripts.lib.edl import EDL, EDLEpisode, preflight
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.project import ProjectConfig


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


def build_edl(footage: Footage, selection: dict) -> EDL:
    """Assemble an EDL from a selection dict. Each selection episode references a
    window by (source, integer index) into FOOTAGE and supplies editorial fields;
    window_to_episode projects the mechanical fields. Reel knobs (music/cap/
    target_dur) ride at the top level. Fail-loud on a source not in FOOTAGE or an
    out-of-range window index (a typo would else surface as a FileNotFound deep in
    extract — montage §12)."""
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
    cap = selection.get("cap")
    return EDL(episodes=tuple(episodes), music=selection.get("music"),
               cap=cap if cap is not None else 3, target_dur=selection.get("target_dur"))


def write_edit_plan(footage_path: str, selection_path: str, project_path: str, out_dir: str) -> dict:
    """Author EDL.json + EDL.md from FOOTAGE + a selection, gated by the project's
    manifest preflight. Nothing is written when preflight fails — a bad EDL never
    lands as a half-valid artifact. Returns {"status": "written", ...} or the
    preflight stop_and_report verbatim."""
    footage = Footage.from_json(footage_path)
    try:
        selection = json.loads(Path(selection_path).read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{selection_path} is not valid JSON ({e}) — fix the selection syntax") from e
    cfg = ProjectConfig.from_json(project_path)
    edl = build_edl(footage, selection)
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
    a = ap.parse_args()
    result = write_edit_plan(a.footage, a.selection, a.project, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "written" else 1)


if __name__ == "__main__":
    main()
