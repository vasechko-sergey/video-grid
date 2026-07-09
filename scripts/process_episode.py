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
from scripts.lib import geometry
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.models import (TrackSpec, ReframeSpec, CheckSpec, StoryboardSpec,
                                Delivery, route_from_json, CropPath)
from scripts.lib.project import ProjectConfig, resolve_manifest


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


def process_episode(manifest_dict, project_dir, route_path=None, max_attempts=3, project=None):
    """Drive one episode manifest → checked clip (§5.10). Returns a status dict;
    callers MUST branch on result["status"] before reading status-specific keys
    (only mechanical_pass/escalate carry "report"; needs_input/stop_and_report
    do not). One fresh project_dir per episode — its route/path/report/storyboard
    files are written flat and would clobber a sibling episode sharing the dir."""
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if project is not None:
        cfg = project if isinstance(project, ProjectConfig) else ProjectConfig.from_json(project)
        manifest_dict = resolve_manifest(manifest_dict, cfg)
    try:
        m = manifest_lib.Manifest.from_dict(manifest_dict)
    except (KeyError, TypeError, ValueError) as e:
        return {"status": "needs_input", "problems": [str(e)], "attempt": 0}
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

    intent = orch.derive_intent(m.composition, m.motion)
    delivery = Delivery.from_spec(m.delivery)

    # 1. tracking — or a supplied frozen route (answer channel / determinism, §5.10)
    if route_path is None:
        rp = str(Path(project_dir) / "route.json")
        tspec = TrackSpec(src=m.segment, model=m.model,
                          seed_bbox=m.hero if orch.is_seed_pin(m.hero) else None,
                          intent=intent)
        _timed("track", lambda: track.build_route(tspec, rp))
        route, track_meta = _load_route(rp)
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0

    # probe the source ONCE and thread the real dims through the checks (contract fix)
    src_w, src_h, _fps = reframe._probe(m.segment)

    # 2. contradiction gate (§4.1: no improvising past the manifest)
    findings = orch.detect_contradictions(m.motion, m.hero, route, track_meta,
                                          src_w, src_h, composition=m.composition)
    if findings:
        return {"status": "stop_and_report", "findings": findings, "attempt": 0,
                "timings": timings, "route": rp}

    # 3. reframe → check retry loop
    params = dict(orch.DEFAULT_PARAMS)
    path_out = str(Path(project_dir) / "path.json")
    report = None
    for attempt in range(1, max_attempts + 1):
        rspec = ReframeSpec(composition=m.composition, grid=m.grid, canvas=m.canvas,
                            color_means=m.color_means, delivery=delivery,
                            max_speed=params["max_speed"])
        _timed("reframe", lambda: reframe.reframe(rspec, m.segment, rp, m.out_path, path_out))
        cspec = CheckSpec(composition=m.composition, grid=m.grid, target_dur=m.target_dur,
                          canvas=m.canvas, src_dims=(src_w, src_h), attempt=attempt)
        report = _timed("check", lambda: check_episode.run(
            m.out_path, rp, path_out, cspec, str(Path(project_dir) / "report.json")))
        if report.overall:
            sheet = str(Path(project_dir) / "storyboard.jpg")
            # hero marker (§6.1a layer 4): draw the followed subject on every
            # sampled frame so the editorial gate can confirm "right person" —
            # without marks the SKILL's marker check has nothing to look at.
            # storyboard.build computes marks INTERNALLY from these ingredients.
            crop_w, _ = geometry.crop_size(m.canvas[0], m.canvas[1], src_w, src_h)
            route_pts = route_from_json(rp)
            path_obj = CropPath.from_json(path_out)
            sspec = StoryboardSpec(n=6, grids=(m.grid,))
            _timed("storyboard", lambda: storyboard.build(
                m.out_path, sheet, sspec, route=route_pts, path=path_obj,
                crop_w=crop_w, src_h=src_h))
            return {"status": "mechanical_pass", "clip": m.out_path, "report": report.to_dict(),
                    "storyboard": sheet, "attempt": attempt, "timings": timings,
                    "degraded": None}
        esc = orch.escalation(attempt, report.fail_reasons, max_attempts)
        if esc:
            return {"status": "escalate", **esc, "report": report.to_dict(),
                    "attempt": attempt, "timings": timings}
        params = orch.adjust_reframe_params(params, report.fail_reasons)

    # defensive: escalation() fires at max_attempts, so this is unreachable
    return {"status": "escalate", "escalate_to": "edit-plan", "reason": "max-retries",
            "fail_reasons": report.fail_reasons if report else [],
            "report": report.to_dict() if report else None,
            "attempt": max_attempts, "timings": timings}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="process one episode manifest → checked clip")
    ap.add_argument("manifest", help="path to a JSON manifest file (§5.10)")
    ap.add_argument("--project-dir", required=True, help="scratch dir for route/path/report")
    ap.add_argument("--route", default=None, help="frozen route.json (skip tracking)")
    ap.add_argument("--project", default=None,
                    help="path to project.json — the episode inherits its canvas/delivery")
    a = ap.parse_args()
    md = json.loads(Path(a.manifest).read_text())
    result = process_episode(md, a.project_dir, route_path=a.route, project=a.project)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "mechanical_pass" else 1)
