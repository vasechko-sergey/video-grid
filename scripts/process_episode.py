"""process-episode orchestrator shell (§5.10, crown jewel).

Deterministic loop over the shipped engine. All judgment (ask-before-start on
genuine ambiguity, the editorial gate) lives in skills/process-episode/SKILL.md;
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
from scripts.lib import zoom as zoom_lib   # aliased: this task introduces a local `zoom`
                                           # variable below, and a bare `import zoom` would
                                           # be shadowed by it — same reason hero_lib is
                                           # aliased above.
from scripts.lib import flow, keyframes, reid, vidstab
from scripts.lib.footage import Cast
from scripts.lib.models import (TrackSpec, ReframeSpec, CheckSpec, StoryboardSpec,
                                Delivery, LayoutSpec, route_from_json, CropPath, PathMeta,
                                PanSpec, ZoomSpec)
from scripts.lib.project import ProjectConfig, resolve_manifest


def build_reframe_spec(m: manifest_lib.Manifest, delivery: Delivery, params: dict) -> ReframeSpec:
    """The ONE place a Manifest becomes a ReframeSpec.

    Extracted so the frame probe (scripts/probe.py, design 2026-08-15) renders from
    the same field map the real render uses. A probe carrying its own copy of this
    mapping would drift field by field, and a probe that renders a different grade
    than the next render is worse than no probe: it converges on pixels nobody gets.

    `params` is the retry-parameter dict (orchestration.DEFAULT_PARAMS, possibly
    adjusted).
    """
    lspec = LayoutSpec(mode=m.layout, crop_aspect=m.crop_aspect, crop_scale=m.crop_scale,
                       rect=m.rect, background=m.background,
                       background_color=m.background_color,
                       border_px=m.border_px, border_color=m.border_color)
    return ReframeSpec(composition=m.composition, grid=m.grid, canvas=m.canvas,
                       color_means=m.color_means, delivery=delivery, layout=lspec,
                       max_speed=params["max_speed"],
                       smooth_window_s=params["smooth_window_s"],
                       white_balance=m.white_balance, black_point=m.black_point,
                       highlight=m.highlight, highlight_red=m.highlight_red,
                       saturation=m.saturation,
                       shadow_red=m.shadow_red, mid_blue=m.mid_blue, dip=m.dip,
                       tone_src=m.tone_src, tone_dst=m.tone_dst,
                       pan=PanSpec.from_dict(m.pan) if m.pan is not None else None,
                       zoom=ZoomSpec.from_dict(m.zoom) if m.zoom is not None else None)


def rendered_params(meta_json: str | Path | None) -> dict | None:
    """The reframe params the render that wrote this sidecar actually used, or None
    when the sidecar does not say.

    None is the named absence and it has two causes nothing here distinguishes: a
    sidecar written before PathMeta carried these fields, and one whose render used
    the defaults. Safe, but NOT because the two reconstruct identically — they do
    not: a defaults render is reproduced exactly at params=None, and a PRE-SLICE
    retried render's geometry is reproduced WRONGLY (design 2026-09-24 §2.1's
    table). What makes both outcomes correct is that a caller receiving None must
    still check the rebuilt plan against the frozen sidecars before trusting it —
    probe._refuse_on_drift — so the second case is refused by name instead of read
    as a measurement.

    A path that is empty or names no file is also None — ReelEpisode.meta defaults
    to "" and a hand-authored reel manifest may carry no sidecar, which is an
    absence and not a fault. A sidecar that EXISTS and will not parse still raises
    through PathMeta.from_json: machine-written content gone wrong is a fault, and
    answering "the defaults, then" would hand the caller a plan built on a guess.

    `is_file`, not `exists`: a Path("") is truthy like every Path and normalizes to
    Path("."), which exists — so the falsy check alone lets a directory through to
    a read that raises IsADirectoryError, which is neither of this function's two
    documented answers. A path naming a directory is not a sidecar.

    Keys the sidecar omits are filled from orch.DEFAULT_PARAMS and never from the
    manifest's authored smooth_window_s. A recorded sidecar is a COMPLETE account
    of what the render used, so an omitted key means the render used the default —
    after a retry the authored value is exactly what the ladder overrode.
    """
    if not meta_json or not Path(meta_json).is_file():
        return None
    meta = PathMeta.from_json(meta_json)
    if meta.max_speed is None and meta.smooth_window_s is None:
        return None
    p = dict(orch.DEFAULT_PARAMS)
    if meta.max_speed is not None:
        p["max_speed"] = meta.max_speed
    if meta.smooth_window_s is not None:
        p["smooth_window_s"] = meta.smooth_window_s
    return p


def _plan_parts(manifest_dict: dict, src: str, route: str | None,
                params: dict | None = None) -> tuple[manifest_lib.Manifest, ReframeSpec,
                                                     reframe.RenderPlan]:
    """The manifest -> (Manifest, ReframeSpec, RenderPlan) map, in ONE place.

    Private because every caller wants one of the two public shapes below; it
    exists because they want DIFFERENT parts of the same map — plan_for the plan,
    plan_and_meta_ungraded the plan AND the spec (path_meta needs it) AND the
    Manifest (its `stabilize` flag). Copying four lines to hand back a third
    field is exactly the field-by-field drift plan_for's own docstring is about:
    the copy read `orch.DEFAULT_PARAMS` and the smooth_window_s override
    independently, so a change to either reached one geometry and not the other.

    `params`, when given, REPLACES the derivation rather than merging over it: it
    is a complete account of what a past render used (see rendered_params), so the
    manifest's authored smooth_window_s must not win over it — a retry is precisely
    the case where the ladder overrode that value. Two independently-produced
    mappings merged into one is also the shape the 2026-09-21 slice found reading
    as a defect the day anything downstream discriminates on a shared key; there is
    nothing to merge here.
    """
    m = manifest_lib.Manifest.from_dict(manifest_dict)
    if params is None:
        params = dict(orch.DEFAULT_PARAMS)
        if m.smooth_window_s is not None:
            params["smooth_window_s"] = m.smooth_window_s
    spec = build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    return m, spec, reframe.plan_render(spec, src, route)


def plan_for(manifest_dict: dict, src: str, route: str | None,
             *, params: dict | None = None) -> reframe.RenderPlan:
    """The RenderPlan this manifest would render — the ONE manifest -> plan map.

    Lives here because build_reframe_spec does, and its docstring already names the
    risk this function exists to remove: a caller carrying its own copy of the map
    drifts field by field. Two callers used to have one each (color_measure's
    stripped variant and probe's graded one) and check_episode now needs a third.

    With `params` omitted, params come from orch.DEFAULT_PARAMS plus the manifest's
    authored smooth_window_s: a plan from a manifest ALONE, which is what a caller
    with nothing rendered yet — probe's geometry mode, the match-grade conductor —
    wants. The retry loop below still does not come through here; it carries the
    attempt's own params into build_reframe_spec directly.

    `params` is for reconstructing a PAST render: hand it
    rendered_params(<the episode's path.meta.json>) and the plan is the geometry
    that shipped, rather than the geometry the declaration describes. Before this
    existed, an episode whose accepted attempt was not attempt 1 could not be
    replanned at all — the recomputed path disagreed with the frozen one and every
    reader either lost its reading or reported a wrong one (design 2026-09-24 §0.3).
    """
    return _plan_parts(manifest_dict, src, route, params)[2]


def plan_ungraded(manifest_dict: dict, src: str, route: str | None,
                  *, params: dict | None = None) -> reframe.RenderPlan:
    """`plan_for` with every colour knob at identity — the render a measurement reads
    through, and the plain half of the damage sensor's pair.

    `params` must carry whatever the graded half carried, or the pair compares two
    geometries and reports the difference as a grade."""
    return plan_for(manifest_lib.strip_colour(manifest_dict), src, route, params=params)


def plan_and_meta_ungraded(manifest_dict: dict, src: str,
                           route: str | None) -> tuple[reframe.RenderPlan, CropPath, PathMeta]:
    """`plan_ungraded` plus the CropPath and PathMeta its render would write.

    For a caller that must place the tracked subject inside the crop BEFORE the
    crop has been rendered — the conductor, which runs at the geometry seam where
    process_episode returns before reframe and so before path.json exists. Writes
    nothing.

    Goes through the SAME _plan_parts as plan_for/plan_ungraded, so its first
    return value is `plan_ungraded(...)` exactly, not a second reading of the same
    map (pinned by
    test_plan_and_meta_ungraded_returns_the_same_plan_as_plan_ungraded)."""
    m, spec, plan = _plan_parts(manifest_lib.strip_colour(manifest_dict), src, route)
    return plan, CropPath(plan.path), reframe.path_meta(plan, spec, stabilized=m.stabilize)


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
                    keyframes_path: str | None = None,
                    stop_after: str | None = None,
                    prepared_source: str | None = None) -> dict:
    """Drive one episode manifest → checked clip (§5.10). Returns a status dict;
    callers MUST branch on result["status"] before reading status-specific keys
    (only mechanical_pass/escalate carry "report"; needs_input/stop_and_report
    do not). One fresh project_dir per episode — its route/path/report/storyboard
    files are written flat and would clobber a sibling episode sharing the dir.

    `stop_after="geometry"` returns after the contradiction gate, before any
    encode: the split edl_to_reel's phase 1 takes so a colour measurement can be
    made on the crop that will ship (design 2026-08-30 §2.1). Every refusal above
    the seam behaves exactly as it does in a full run.

    `prepared_source` is that split's other half — the caller asserting "the
    frozen route in route_path was measured on THIS file", which is the one thing
    the stabilize refusal below cannot know. Not on the CLI: only a driver that
    produced both halves can honestly assert it.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if stop_after not in (None, "geometry"):
        return {"status": "needs_input", "attempt": 0, "problems": [
            f"stop_after must be None or 'geometry', got {stop_after!r} — 'geometry' "
            f"returns after tracking and the contradiction gate, before any encode"]}
    if prepared_source is not None and route_path is None:
        return {"status": "needs_input", "attempt": 0, "problems": [
            "prepared_source needs route_path: it exists to assert that a frozen route "
            "was measured on that file, and with no route there is nothing to assert. "
            "Pass both, or neither."]}
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
    # fails in milliseconds, not after YOLO has walked the whole segment. _probe
    # now also reports pix_fmt/color_range (design 2026-08-27 §4.3); this preflight
    # has no use for them — the colour guard lives in plan_render, exercised later
    # when the real render runs — so they are unpacked and discarded, not read.
    src_w, src_h, _fps, _dur, _pix_fmt, _color_range = reframe._probe(m.segment)

    # the layout is editorial intent, not a retry parameter: it does not change
    # between attempts, so build it once. validate() already proved it constructs.
    # Also built inside build_reframe_spec (the ONE map). Kept here because the layout
    # and pan preflights below need the resolved objects BEFORE any encode; both
    # constructions are pure and validate() already proved they succeed.
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

    # the zoom is editorial intent, not a retry parameter — build it once, beside the pan,
    # so the ladder below can never mutate it
    zoom = ZoomSpec.from_dict(m.zoom) if m.zoom is not None else None

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

    # zoom preflight — mirrors the pan preflight just above, one layer simpler (zoom
    # validation needs no path generation). The HARD engine gate needs numbers only
    # reframe has — the resolved layout's crop/delivery widths and the probed duration —
    # so run it here, before any encode. Unlike a pan, a zoom still needs a tracked route
    # (design §1), so "before any encode" must also mean before tracking starts below:
    # letting a doomed zoom reach the tracker would cost a real YOLO/optical-flow pass for
    # nothing.
    if zoom is not None:
        try:
            zoom_lib.validate(zoom, rl.crop_w, rl.out_w, _dur)
        except ValueError as e:
            return {"status": "needs_input", "problems": [str(e)], "attempt": 0}

    # --keyframes (rung 3, the manual channel) is authored by hand against the RAW
    # segment in source coordinates, with the human — not a pin, not a tracker —
    # naming the subject. Three inputs contradict that channel, and manifest.validate
    # cannot catch any of them (keyframes_path is not a manifest field), so refuse here,
    # loudly, rather than silently drop the marks or apply them to the wrong pixels.
    # Together they are one invariant: --keyframes drives the raw, unpinned,
    # unstabilized, un-pre-routed segment — nothing else (design 2026-07-21 §2).
    if keyframes_path is not None:
        if m.hero is not None:
            # A hero pin and hand-authored keyframes both answer "which subject": the
            # pin tells the automatic tracker whom to follow, the keyframes ARE the
            # human answering it directly, so the pin is moot the moment they are drawn.
            # Passing both silently drops the keyframes — they sit under flow_eligible,
            # False for a pin — with no signal they were ignored. Optical-flow's
            # identity-blindness (§1.1) keeps a pinned episode out of rung 2; the manual
            # rung 3 is excluded here for this DIFFERENT, louder reason: a human CAN
            # honor the pin, so the conflict is one of mechanism, not identity-blindness.
            return {"status": "needs_input", "attempt": 0, "problems": [
                "a hero pin cannot be combined with --keyframes: hand-authored keyframes "
                "ARE the identity assertion — they name the subject directly and "
                "supersede any pin. Drop the hero pin from the manifest and re-run with "
                "--keyframes, or drop --keyframes and let the pinned tracker run."]}
        if m.stabilize:
            # Keyframes are drawn in the RAW segment's coordinates, but the stabilization
            # pre-stage below hands reframe a per-frame-shifted copy; source-coord marks
            # on those pixels land the crop off by the displacement vidstab removed.
            # Sparse linear marks cannot re-inject the high-frequency shake the --route
            # refusal below exists for (they are low-frequency by construction) — the
            # milder low-frequency-offset case — but it is the SAME coordinate-mismatch
            # class, and there is no correct way to hand-author against the stabilized
            # scratch, which the human never sees. Refuse it symmetrically.
            return {"status": "needs_input", "attempt": 0, "problems": [
                "stabilize=true cannot be combined with --keyframes: keyframes are "
                "authored in the raw segment's coordinates, but stabilization feeds "
                "reframe a shifted copy, so the marks land the crop off by the shake "
                "vidstab removed. Turn stabilize off to hand-author marks in source "
                "coordinates, or drop --keyframes and let the tracker re-track on the "
                "stabilized segment."]}
        if route_path is not None:
            # --route is already a COMPLETE frozen route (tracking is skipped entirely);
            # --keyframes is the manual rung that would AUTHOR one. Two competing route
            # sources, and today --route silently wins while the keyframes are dropped.
            # Refuse: pick one channel.
            return {"status": "needs_input", "attempt": 0, "problems": [
                "--route cannot be combined with --keyframes: --route supplies a complete "
                "frozen route and --keyframes supplies sparse marks to build one, so the "
                "two are competing route sources. Drop whichever you did not mean — keep "
                "--route for a full frozen path, or --keyframes to interpolate sparse "
                "marks."]}

    # A supplied --route was measured against SOME pixels, and nothing here proves
    # they were the stabilized ones. Applying it to the stabilized copy would
    # re-inject exactly the shake vidstab removed (design 2026-07-20 §1) — the
    # failure this whole ordering exists to prevent, arriving through the one door
    # the pre-stage cannot close by construction. Refuse it rather than corrupt
    # silently; manifest.validate cannot, because route_path is not a manifest field.
    if m.stabilize and route_path is not None and prepared_source is None:
        return {"status": "needs_input", "attempt": 0, "problems": [
            "stabilize=true cannot be combined with a supplied --route: the frozen "
            "route was measured against unknown pixels, and applying it to the "
            "stabilized segment would re-inject the shake vidstab removed. Drop "
            "--route (a pan ignores it; a tracked episode re-tracks on the "
            "stabilized segment), or turn stabilize off for this episode."]}

    # 0c. the stabilization pre-stage (design 2026-07-20 §1). NOT a filter in
    # reframe's chain: the route is measured on unstabilized pixels, so a crop
    # placed from it against transformed pixels leaves the subject offset by
    # exactly the shake vidstab removed — a steady background with a jittering
    # subject — and check_episode confirms the framing anyway, because path and
    # route are both in source coordinates and agree with each other. Only the
    # pixels disagree. Writing a file that BOTH the tracker and reframe read makes
    # route and pixels one coordinate system by construction.
    #
    # After the preflights, so a manifest the layout cannot satisfy still fails in
    # milliseconds rather than after two 4K ffmpeg passes; outside the retry loop,
    # because it is the loop's input, not one of its parameters — the ladder only
    # tunes max_speed, which stabilization does not depend on.
    src = m.segment
    stabilize_report = None
    if prepared_source is not None:
        # The caller has already produced these pixels and measured the route on
        # them (design §2.3). Re-running the pre-stage would spend two 4K passes to
        # recreate a file we were handed, and — because vidstabtransform is not
        # bit-reproducible across runs of a different length — could produce pixels
        # the frozen route no longer matches.
        src = prepared_source
    elif m.stabilize:
        src = str(Path(project_dir) / "stabilized.mp4")
        before, after = _timed("stabilize", lambda: vidstab.stabilize(
            m.segment, src, (src_w, src_h), _fps, _dur))
        stabilize_report = {"before": before, "after": after}

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
        # The degradation ladder (design 2026-07-21 §2). Each rung, on success, leaves
        # the SAME route.json + route.meta.json pair _load_route reads one line down.
        rp = str(Path(project_dir) / "route.json")
        pinned = m.hero is not None
        # Resolve the pin ONCE, up front: the rung-1 gate below now depends on the pin
        # KIND (a cast pin needs reID), and the TrackSpec reuses it. resolve() cannot
        # raise: validate() above already ran hero_lib.resolve on this same (m.hero,
        # cast) pair and returned no problems, so a second identical call is guaranteed
        # not to. wants_reid marks a cast (identity) pin — the one kind that must not
        # degrade to the ladder's identity-blind optical flow (design 2026-08-04 §6).
        pin = hero_lib.resolve(m.hero, cast)
        wants_reid = pin is not None and pin.kind == "cast"
        # A cast-identity pin needs torchreid person-re-ID. When the tracker itself IS
        # present but reID is not, stop HERE with the honest remedy rather than let the
        # ladder speak for it: build_route would fall to an empty route and the
        # contradiction gate would fire `no-track` ("hero never detected"), a MISLEADING
        # remedy for an install gap (§12 forbids those) — and the pinned-⇒-no-flow rule
        # would otherwise leave the real cause unnamed. (Both trackers absent is a
        # different story: _ultra_available() is False, this block is skipped, and the
        # normal ladder's `no-track` is then the correct diagnosis.)
        if wants_reid and track._ultra_available() and not reid.available():
            result = {"status": "stop_and_report", "attempt": 0, "timings": timings,
                      "findings": [{"reason": "reid-unavailable",
                                    "detail": "this episode pins a hero by cast identity, which needs "
                                              "torchreid person-re-ID, and it is not installed. Install it "
                                              "with `bash setup.sh` and re-run, or pin the hero another way "
                                              "(--seed bbox / --rule / --track-id) that does not need reID."}]}
            if stabilize_report is not None:
                result["stabilize"] = stabilize_report
            return result
        # rung 1: YOLO — gated so an absent ultralytics falls to the ladder instead of
        # raising a traceback inside build_route on attempt 1. descriptor=wants_reid so a
        # cast pin ALSO requires reID (available() returns False without it); the empty
        # route then falls through the pinned-⇒-no-flow rule, never to optical flow.
        if track.available(descriptor=wants_reid):
            tspec = TrackSpec(src=src, model=m.model, pin=pin, intent=intent)
            _timed("track", lambda: track.build_route(tspec, rp))
            route, track_meta = _load_route(rp)
        else:
            route, track_meta = [], {}
            timings["track"] = 0.0
        # rung 2: optical-flow — only when a rung gave NOTHING and nobody was pinned
        # (flow is identity-blind; an empty route under a pin is hero-unmatched, handled
        # by detect_contradictions below).
        if orch.flow_eligible(pinned, route_empty=not route):
            if flow.available():
                _timed("flow", lambda: flow.build_route(src, rp, _fps, (src_w, src_h)))
                route, track_meta = _load_route(rp)
            # rung 3: manual keyframes — flow unavailable or itself empty.
            if not route:
                if keyframes_path is not None:
                    _timed("keyframes", lambda: keyframes.write_route(
                        keyframes_path, rp, _fps, _dur))
                    route, track_meta = _load_route(rp)
                else:
                    result = {"status": "stop_and_report", "attempt": 0, "timings": timings,
                              "findings": [{"reason": "no-track",
                                            "detail": "both automatic trackers produced no "
                                                      "route — YOLO detected nobody and "
                                                      "optical-flow found no motion (or cv2 is "
                                                      "unavailable). Supply sparse marks via "
                                                      "--keyframes ([{t,x,y,w,h}]), a full route "
                                                      "via --route, or pin a hero and re-run."}]}
                    if stabilize_report is not None:
                        result["stabilize"] = stabilize_report
                    return result
    else:
        route, track_meta = _load_route(route_path)
        rp = route_path
        timings["track"] = 0.0

    # which rung authored the route (design 2026-07-21 §5): None for YOLO/pan/supplied.
    degraded = track_meta.get("degraded")

    # 2. contradiction gate (§4.1: no improvising past the manifest). SKIPPED under
    # a pan: this gate compares a manifest CLAIM against a tracker OBSERVATION, and
    # with no observation there is nothing to contradict. Running it on the empty
    # route would fire `no-track`, whose remedy ("check the segment, model size, or
    # hero pin") misdescribes a deliberate authoring choice.
    if pan is None:
        findings = orch.detect_contradictions(m.motion, route, track_meta,
                                              src_w, src_h, composition=m.composition)
        if findings:
            result = {"status": "stop_and_report", "findings": findings, "attempt": 0,
                      "timings": timings, "route": rp}
            if stabilize_report is not None:
                result["stabilize"] = stabilize_report
            if degraded is not None:
                result["degraded"] = degraded
            return result

    if stop_after == "geometry":
        result = {"status": "geometry", "route": rp, "source": src,
                  "timings": timings, "degraded": degraded}
        if stabilize_report is not None:
            result["stabilize"] = stabilize_report
        return result

    # 3. reframe → check retry loop
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        # an authored window is this loop's STARTING value, not just its lag-branch
        # floor (set at the adjust_reframe_params call below) — attempt 1 must render
        # at the author's own value, not the module default.
        params["smooth_window_s"] = m.smooth_window_s
    path_out = str(Path(project_dir) / "path.json")
    report = None
    for attempt in range(1, max_attempts + 1):
        rspec = build_reframe_spec(m, delivery, params)
        _timed("reframe", lambda: reframe.reframe(rspec, src, rp, m.out_path, path_out,
                                                  stabilized=m.stabilize))
        # The damage sensor's pair: the SAME render twice, differing only in the
        # colour tail. Built from this attempt's own `params`, not through
        # plan_for/plan_ungraded, which read orch defaults — a retry that adjusted
        # smooth_window_s would otherwise compare two different geometries and the
        # entropy ratio would be measuring a crop instead of a grade.
        plain_m = manifest_lib.Manifest.from_dict(manifest_lib.strip_colour(manifest_dict))
        plain_spec = build_reframe_spec(plain_m, delivery, params)
        plans = (reframe.plan_render(rspec, src, rp),
                 reframe.plan_render(plain_spec, src, rp))
        cspec = CheckSpec(composition=m.composition, grid=m.grid, target_dur=m.target_dur,
                          attempt=attempt)
        report = _timed("check", lambda: check_episode.run(
            m.out_path, rp, path_out, cspec, str(Path(project_dir) / "report.json"),
            source=src, plans=plans))
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
            result = {"status": "mechanical_pass", "clip": m.out_path,
                      "report": report.to_dict(), "storyboard": sheet, "attempt": attempt,
                      "timings": timings, "degraded": degraded}
            if stabilize_report is not None:
                result["stabilize"] = stabilize_report
            return result
        esc = orch.escalation(attempt, report.fail_reasons, max_attempts)
        if esc is None and pan is not None:
            # The retry ladder tunes max_speed and smooth_window_s, via
            # adjust_reframe_params. For a tracked path those are the damper and
            # the averaging span. For a generated one smooth_window_s is not read
            # at all (generate_pan_path never smooths) and max_speed is only the
            # speed CEILING, so a retry re-renders byte-identical pixels — three
            # identical ffmpeg passes ending in "max-retries", a reason that
            # describes nothing.
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
            result = {"status": "escalate", **esc, "report": report.to_dict(),
                      "attempt": attempt, "timings": timings}
            if stabilize_report is not None:
                result["stabilize"] = stabilize_report
            if degraded is not None:
                result["degraded"] = degraded
            return result
        params = orch.adjust_reframe_params(params, report.fail_reasons, floor=m.smooth_window_s)

    # defensive: escalation() fires at max_attempts, so this is unreachable
    result = {"status": "escalate", "escalate_to": "edit-plan", "reason": "max-retries",
              "fail_reasons": report.fail_reasons if report else [],
              "report": report.to_dict() if report else None,
              "attempt": max_attempts, "timings": timings}
    if stabilize_report is not None:
        result["stabilize"] = stabilize_report
    if degraded is not None:
        result["degraded"] = degraded
    return result


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="process one episode manifest → checked clip")
    ap.add_argument("manifest", help="path to a JSON manifest file (§5.10)")
    ap.add_argument("--project-dir", required=True, help="scratch dir for route/path/report")
    ap.add_argument("--route", default=None, help="frozen route.json (skip tracking)")
    ap.add_argument("--keyframes", default=None,
                    help="sparse keyframes.json ([{t,x,y,w,h}]) — the manual rung when both "
                         "automatic trackers give nothing (design 2026-07-21 §4)")
    ap.add_argument("--project", default=None,
                    help="path to project.json — the episode inherits its canvas/delivery")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    md = json.loads(Path(a.manifest).read_text())
    result = process_episode(md, a.project_dir, route_path=a.route, project=a.project,
                             keyframes_path=a.keyframes)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "mechanical_pass" else 1)


if __name__ == "__main__":
    main()
