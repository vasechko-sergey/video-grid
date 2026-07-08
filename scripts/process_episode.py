"""process-episode orchestrator shell (§5.10, crown jewel).

Deterministic loop over the shipped engine. All judgment (ask-before-start on
genuine ambiguity, the editorial gate) lives in SKILLS/process-episode/SKILL.md;
this shell owns everything mechanical: manifest validation, tracking, the
reframe→check retry loop, the canvas/src_dims contract, stage timing, and the
structured report. It never improvises past the manifest — a contradiction or a
run of failures returns a finding, it does not paper over them (§4.1).
"""
import argparse
import json
import time
from pathlib import Path

from scripts import track, reframe, storyboard, check_episode
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch


def _load_route(route_path):
    route = json.loads(Path(route_path).read_text())
    meta_path = Path(route_path).with_suffix(".meta.json")
    if not meta_path.exists():
        return route, {"ambiguous": False}          # sidecar optional; absent = unambiguous
    try:
        return route, json.loads(meta_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{meta_path} is corrupt ({e}) — delete it and re-track, "
                         "or fix the sidecar; it drives the §6.1a hero-ambiguity gate") from e


def process_episode(manifest_dict, project_dir, route_path=None, max_attempts=3):
    """Drive one episode manifest → checked clip (§5.10). Returns a status dict;
    callers MUST branch on result["status"] before reading status-specific keys
    (only mechanical_pass/escalate carry "report"; needs_input/stop_and_report
    do not). One fresh project_dir per episode — its route/path/report/storyboard
    files are written flat and would clobber a sibling episode sharing the dir."""
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    m = manifest_lib.Manifest.from_dict(manifest_dict)
    problems = manifest_lib.validate(m)
    if problems:
        return {"status": "needs_input", "problems": problems, "attempt": 0}
    Path(project_dir).mkdir(parents=True, exist_ok=True)   # scratch for route/path/report

    timings = {}

    def _timed(name, fn):
        t0 = time.monotonic()
        out = fn()
        timings[name] = round(time.monotonic() - t0, 3)
        return out

    # 1. tracking — or a supplied frozen route (answer channel / determinism, §5.10)
    if route_path is None:
        rp = str(Path(project_dir) / "route.json")
        _timed("track", lambda: track.build_route(m.segment, out=rp, seed_bbox=m.hero
                                                   if isinstance(m.hero, tuple) else None,
                                                   model_path=m.model))
        route, track_meta = _load_route(rp)
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0

    # probe the source ONCE and thread the real dims through the checks (contract fix)
    src_w, src_h, _fps = reframe._probe(m.segment)

    # 2. contradiction gate (§4.1: no improvising past the manifest)
    findings = orch.detect_contradictions(m.motion, m.hero, route, track_meta, src_w, src_h)
    if findings:
        return {"status": "stop_and_report", "findings": findings, "attempt": 0,
                "timings": timings, "route": rp}

    # 3. reframe → check retry loop
    params = dict(orch.DEFAULT_PARAMS)
    path_out = str(Path(project_dir) / "path.json")
    report = None
    for attempt in range(1, max_attempts + 1):
        _timed("reframe", lambda: reframe.reframe(
            m.segment, rp, m.out_path, m.composition, m.grid, m.canvas,
            m.color_means, m.stabilize, path_out, max_speed=params["max_speed"]))
        report = _timed("check", lambda: check_episode.run(
            m.out_path, rp, path_out, m.composition, m.grid, m.target_dur,
            str(Path(project_dir) / "report.json"),
            canvas=m.canvas, src_dims=(src_w, src_h), attempt=attempt))
        if report["overall"]:
            sheet = str(Path(project_dir) / "storyboard.jpg")
            _timed("storyboard", lambda: storyboard.build(m.out_path, sheet,
                                                          n=6, grids=(m.grid,)))
            return {"status": "mechanical_pass", "clip": m.out_path, "report": report,
                    "storyboard": sheet, "attempt": attempt, "timings": timings,
                    "degraded": None}
        esc = orch.escalation(attempt, report["fail_reasons"], max_attempts)
        if esc:
            return {"status": "escalate", **esc, "report": report,
                    "attempt": attempt, "timings": timings}
        params = orch.adjust_reframe_params(params, report["fail_reasons"])

    # defensive: escalation() fires at max_attempts, so this is unreachable
    return {"status": "escalate", "escalate_to": "edit-plan", "reason": "max-retries",
            "fail_reasons": report["fail_reasons"] if report else [], "report": report,
            "attempt": max_attempts, "timings": timings}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="process one episode manifest → checked clip")
    ap.add_argument("manifest", help="path to a JSON manifest file (§5.10)")
    ap.add_argument("--project-dir", required=True, help="scratch dir for route/path/report")
    ap.add_argument("--route", default=None, help="frozen route.json (skip tracking)")
    a = ap.parse_args()
    md = json.loads(Path(a.manifest).read_text())
    result = process_episode(md, a.project_dir, route_path=a.route)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "mechanical_pass" else 1)
