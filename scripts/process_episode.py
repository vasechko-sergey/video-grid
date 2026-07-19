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
from scripts.lib import hero as hero_lib
from scripts.lib import layout as layout_lib
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.footage import Cast
from scripts.lib.models import (TrackSpec, ReframeSpec, CheckSpec, StoryboardSpec,
                                Delivery, LayoutSpec, route_from_json, CropPath, PathMeta,
                                PanSpec)
from scripts.lib.project import ProjectConfig, resolve_manifest


def _load_route(route_path: str | Path) -> tuple[list[dict], dict]:
    route = json.loads(Path(route_path).read_text())
    meta_path = Path(route_path).with_suffix(".meta.json")
    if not meta_path.exists():
        return route, {"ambiguous": False}          # sidecar optional; absent = unambiguous
    try:
        return route, json.loads(meta_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{meta_path} is corrupt ({e}) — delete it and re-track, "
                         "or fix the sidecar; it drives the §6.1a hero-ambiguity gate") from e


def process_episode(manifest_dict: dict, project_dir: str | Path, route_path: str | None = None,
                    max_attempts: int = 3,
                    project: ProjectConfig | str | Path | None = None,
                    color_correct: tuple | None = None) -> dict:
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
    # load the cast registry ONCE, here — the same object backs both validate()'s
    # oracle call below and the real resolution in the tracking step further down,
    # so the two cannot see different registries.
    #
    # The isinstance guard is load-bearing, not decoration. This load necessarily
    # runs BEFORE validate() (validate needs the loaded Cast as its hero oracle), so
    # it is the one step no gate has vetted, and Manifest.from_dict passes `cast`
    # through raw. Cast.from_json's first statement is Path(path) — it runs before a
    # byte of JSON is read, so a non-str m.cast raises TypeError there, outside the
    # except below, escaping the gate whose whole job is not to raise. Skipping the
    # load instead leaves cast=None and lets validate() report the bad field as a
    # problem string, the same channel every other manifest problem uses.
    #
    # Past that guard, (OSError, ValueError) IS Cast.from_json's whole failure
    # surface — OSError for a missing/unreadable file, ValueError for bad syntax, a
    # non-object top level (from_dict guards it) or a bad member — so no bare
    # AttributeError/TypeError can escape here.
    cast = None
    if isinstance(m.cast, str) and m.cast:
        try:
            cast = Cast.from_json(m.cast)
        except (OSError, ValueError) as e:
            return {"status": "needs_input", "attempt": 0,
                    "problems": [f"cast {m.cast!r} is unreadable — {e}"]}
    problems = manifest_lib.validate(m, cast=cast)
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

    # probe the source ONCE and thread the real dims through the checks (contract
    # fix). This runs BEFORE tracking so a manifest the layout cannot satisfy
    # fails in milliseconds, not after YOLO has walked the whole segment.
    src_w, src_h, _fps, _dur = reframe._probe(m.segment)

    # the layout is editorial intent, not a retry parameter: it does not change
    # between attempts, so build it once. validate() already proved it constructs.
    lspec = LayoutSpec(mode=m.layout, crop_aspect=m.crop_aspect, crop_scale=m.crop_scale,
                       rect=m.rect, background=m.background,
                       background_color=m.background_color,
                       border_px=m.border_px, border_color=m.border_color)

    # 0. layout preflight. Everything below the manifest gate is HARD: resolve()
    # raises on a rect that overflows its canvas, a border wider than its own
    # card, or a native canvas past MAX_SIDE. validate() cannot catch any of
    # those — they depend on the source dims, which exist only now that we have
    # probed. Resolving here turns a manifest typo back into needs_input, the
    # same channel every other manifest problem uses, instead of letting a
    # ValueError escape the shell as a traceback on attempt 1. The engine keeps
    # raising for anyone who calls reframe directly. `rl` is kept (not discarded)
    # — the pan preflight just below needs its `freedom`, and resolving a second
    # time would only repeat the same computation.
    try:
        rl = layout_lib.resolve(lspec, m.canvas, (src_w, src_h), delivery)
    except ValueError as e:
        return {"status": "needs_input", "problems": [str(e)], "attempt": 0}

    # the pan is editorial intent, not a retry parameter — build it once, beside
    # the layout. validate() already proved it constructs.
    pan = PanSpec.from_dict(m.pan) if m.pan is not None else None

    # 0b. pan preflight. Like the layout above, the HARD engine gate needs numbers
    # validate() cannot see: freedom and the implied px/s both depend on the probed
    # source. Resolving here turns them back into needs_input rather than letting a
    # ValueError escape as a traceback on attempt 1. Reuses `rl` from the layout
    # preflight above instead of resolving a second time.
    if pan is not None:
        try:
            reframe.generate_pan_path(pan, rl.freedom, _fps, _dur,
                                      orch.DEFAULT_PARAMS["max_speed"])
        except ValueError as e:
            return {"status": "needs_input", "problems": [str(e)], "attempt": 0}

    # 1. tracking — or a supplied frozen route (answer channel / determinism, §5.10),
    #    or NOTHING AT ALL when the path is generated.
    if pan is not None:
        # A pan follows nobody, so there is nothing to track and no route to write.
        # This is a real saving (a whole YOLO pass) and the honest statement that
        # no observation exists — see design 2026-07-19 §6.1 for why an empty
        # route.json would be a fabricated one.
        route, track_meta, rp = [], {"ambiguous": False}, None
        timings["track"] = 0.0
    elif route_path is None:
        rp = str(Path(project_dir) / "route.json")
        # resolve() cannot raise here: validate() above already ran hero_lib.resolve
        # on this same (m.hero, cast) pair and returned no problems, so a second,
        # identical call is guaranteed not to raise — the same contract
        # layout_lib.resolve relies on just above ("validate() already proved it
        # constructs").
        tspec = TrackSpec(src=m.segment, model=m.model,
                          pin=hero_lib.resolve(m.hero, cast), intent=intent)
        _timed("track", lambda: track.build_route(tspec, rp))
        route, track_meta = _load_route(rp)
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0

    # 2. contradiction gate (§4.1: no improvising past the manifest). SKIPPED under
    # a pan: this gate compares a manifest CLAIM against a tracker OBSERVATION, and
    # with no observation there is nothing to contradict. Running it on the empty
    # route would fire `no-track`, whose remedy ("check the segment, model size, or
    # hero pin") misdescribes a deliberate authoring choice.
    if pan is None:
        findings = orch.detect_contradictions(m.motion, route, track_meta,
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
                            color_means=m.color_means, delivery=delivery, layout=lspec,
                            max_speed=params["max_speed"], color_correct=color_correct,
                            pan=pan)
        _timed("reframe", lambda: reframe.reframe(rspec, m.segment, rp, m.out_path, path_out))
        cspec = CheckSpec(composition=m.composition, grid=m.grid, target_dur=m.target_dur,
                          attempt=attempt)
        report = _timed("check", lambda: check_episode.run(
            m.out_path, rp, path_out, cspec, str(Path(project_dir) / "report.json")))
        if report.overall:
            sheet = str(Path(project_dir) / "storyboard.jpg")
            # hero marker (§6.1a layer 4): draw the followed subject on every
            # sampled frame so the editorial gate can confirm "right person" —
            # without marks the SKILL's marker check has nothing to look at.
            # storyboard.build computes marks INTERNALLY from these ingredients,
            # reading the SAME path.meta.json sidecar the checks read so the
            # marker maps into canvas coords under any layout (Task 8), not just
            # fill.
            route_pts = None if pan is not None else route_from_json(rp)
            path_obj = CropPath.from_json(path_out)
            path_meta = PathMeta.from_json(Path(path_out).with_suffix(".meta.json"))
            sspec = StoryboardSpec(n=6, grids=(m.grid,))
            _timed("storyboard", lambda: storyboard.build(
                m.out_path, sheet, sspec, route=route_pts, path=path_obj,
                meta=path_meta))
            return {"status": "mechanical_pass", "clip": m.out_path, "report": report.to_dict(),
                    "storyboard": sheet, "attempt": attempt, "timings": timings,
                    "degraded": None}
        esc = orch.escalation(attempt, report.fail_reasons, max_attempts)
        if esc is None and pan is not None:
            # The retry ladder tunes ONE thing: max_speed, via
            # adjust_reframe_params. For a tracked path that is the smoothing
            # damper. For a generated one it is only the speed CEILING, so a
            # retry re-renders byte-identical pixels — three identical ffmpeg
            # passes ending in "max-retries", a reason that describes nothing.
            #
            # Worse, the ladder would actively break the pan: a jitter fail
            # multiplies max_speed by 0.6, so a pan that cleared the ceiling at
            # 750 px/s on attempt 1 hits generate_pan_path's raise at 450 on
            # attempt 2 — a ValueError escaping the loop as a traceback.
            #
            # orch.escalation runs FIRST so its better-attributed reasons
            # (unfixable-by-reframe, conflicting-framing-fails) still win where
            # they apply; this only catches what it would have retried.
            esc = {"escalate_to": "edit-plan", "reason": "pan-not-retryable",
                   "fail_reasons": report.fail_reasons}
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
