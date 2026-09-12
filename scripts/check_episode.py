"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageStat
from scripts import reframe
from scripts.lib import (assembly, checks as checks_mod, color, color_fidelity, ffbin,
                         geometry, gradedamage, proc)
from scripts.lib.models import CheckResult, CheckSpec, PathMeta, Report, route_from_json, CropPath, RoutePoint
from scripts.lib.motion import classify, travel_direction


def _duration(clip: str) -> float:
    out = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", clip], text=True)
    return float(out.stdout.strip())


def _frame_lumas(clip: str, where: str, n: int = 3) -> list[float]:
    """Mean luma of n frames at 'boundary' (head+tail) or 'body' (interior)."""
    lumas = []
    with tempfile.TemporaryDirectory() as tmp:
        if where == "boundary":
            proc.run([ffbin.ffmpeg(), "-y", "-i", clip, "-frames:v", str(n), f"{tmp}/head%02d.png"])
            proc.run([ffbin.ffmpeg(), "-y", "-sseof", "-0.5", "-i", clip, f"{tmp}/tail%02d.png"])
            files = sorted(Path(tmp).glob("head*.png")) + sorted(Path(tmp).glob("tail*.png"))[-n:]
        else:  # body: sample the interior via an even fps grab, drop the extremes
            # fps normalized to the clip's own duration so the n+2 grabs land
            # spread across the WHOLE clip — fps=(n+2)/1 would instead cap at
            # -frames:v and only ever sample the first ~1s, letting a leading
            # defect (e.g. a black lead-in) contaminate the body reference itself
            dur = max(_duration(clip), 0.001)
            proc.run([ffbin.ffmpeg(), "-y", "-i", clip, "-vf", f"fps={n + 2}/{dur}",
                      "-frames:v", str(n + 2), f"{tmp}/b%02d.png"])
            files = sorted(Path(tmp).glob("b*.png"))[1:-1]
        for f in files:
            lumas.append(ImageStat.Stat(Image.open(f).convert("L")).mean[0])
    return lumas


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _black_frames_check(clip: str, black_floor: float = 6.0, black_rel: float = 0.35) -> dict:
    """Spec §9: boundary-only — the seek landmine bites at cut edges. Bug #3:
    the gate is now RELATIVE to the clip body, not an absolute floor — a
    boundary frame is a defect only if it's BOTH near-black AND far below the
    clip's own median luma, so a legitimately dark/night clip still passes.

    The relative gate degenerates when the body itself is black: `ref` → 0 makes
    `worst < black_rel * ref` collapse to `0 < 0` (False), silently passing a
    fully-black clip. So keep the relative gate for the boundary defect, but OR
    in an absolute body-black floor — a body median below `black_floor` is never
    a legitimate delivery, only the seek/lutrgb corruption we're guarding."""
    boundary = _frame_lumas(clip, "boundary")
    body = _frame_lumas(clip, "body") or boundary
    ref = _median(body)
    worst = min(boundary) if boundary else ref
    is_black = (worst < black_floor and worst < black_rel * ref) or ref < black_floor
    return {"pass": not is_black, "boundary_lumas": [round(l, 1) for l in boundary],
            "body_median": round(ref, 1)}


# Where in the route's own span the subject is sampled. Five, not three: the
# batched decode below makes the marginal cost of a sample one PNG, and every
# threshold in the design was measured through exactly these fractions (§2.2).
SAMPLE_FRACS = (0.1, 0.3, 0.5, 0.7, 0.9)


def _box_mean_rgb(frame: np.ndarray, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
    """Mean (R, G, B) of a pixel box in one HxWx3 uint8 RGB frame. box = (x0,y0,x1,y1),
    clamped into the frame and never empty — a route point can sit partly or wholly
    outside the frame it was measured on (a subject that has left the delivered
    crop), and an empty slice would mean() to NaN in silence.

    x0/y0 are clamped into [0, w-1]/[0, h-1] FIRST — never just lower-bounded — so a
    box that starts past the right or bottom edge cannot leave x0/y0 sitting beyond
    the frame; x1/y1 are then clamped into (x0, w]/(y0, h] as before. A box with no
    overlap with the frame at all therefore collapses to a single pixel at the
    nearest edge: a poor measurement of a subject no longer in frame, but a defined
    one, never a NaN."""
    x0, y0, x1, y1 = box
    h, w = frame.shape[:2]
    x0, y0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    x1, y1 = min(w, max(x1, x0 + 1)), min(h, max(y1, y0 + 1))
    px = frame[y0:y1, x0:x1].reshape(-1, 3)
    return tuple(float(px[:, c].mean()) for c in range(3))


def _last_sampleable_t(*clips: str) -> tuple[list[float], float]:
    """Per-clip fps, and the latest time every one of `clips` can still decode.
    frames_rgb selects frame round(t*fps) and raises when that frame is past the
    stream end, so the times are clamped ONCE against the shortest clip, before the
    geometry is projected — clamping afterwards would sample the pixels at one time
    and the crop rect at another."""
    fpses, lasts = [], []
    for c in clips:
        fps = assembly.probe_stream(c).fps
        fpses.append(fps)
        lasts.append(max(0.0, assembly.probe_duration(c) - 1.0 / fps))
    return fpses, min(lasts)


def _subject_delta_advisory(clip: str, source: str | None, route_pts: list[RoutePoint] | None,
                            path_obj: CropPath, meta: PathMeta) -> dict:
    """The tracked subject's source-vs-graded dE00, as a DESCRIPTION (design
    2026-08-31 §3). Same sampling as the old blocking color_fidelity gate; the
    only change is that nothing votes on it any more.

    Sample the tracked subject's mean RGB in the SOURCE (pre-grade segment, at the
    route bbox in source px) and in the graded `clip` (at the subject's projected
    location, via geometry.extent_at_times) at SAMPLE_FRACS of the route's span, and
    delegate to the pure color_fidelity.evaluate for the median-dE00 description.

    One decode per file, not one per sample: assembly.frames_rgb batches the whole
    set through a single select pass, so five samples cost two decodes where three
    used to cost six.
    """
    if source is None or not route_pts:
        return {"advisory_delta_e": True, "delta_e": None,
                "delta_reason": "no source clip or no tracked subject"}
    ts = [p.t for p in route_pts]
    (s_fps, g_fps), last = _last_sampleable_t(source, clip)
    times = [min(ts[0] + (ts[-1] - ts[0]) * f, last) for f in SAMPLE_FRACS]
    extents = geometry.extent_at_times(route_pts, path_obj, meta, times)   # output fractions
    out_w, out_h = meta.out_dims
    s_frames = assembly.frames_rgb(source, times, s_fps)
    g_frames = assembly.frames_rgb(clip, times, g_fps)
    pairs = []
    for t, (fx0, fy0, fx1, fy1), sf, gf in zip(times, extents, s_frames, g_frames):
        p = min(route_pts, key=lambda q: abs(q.t - t))          # nearest source bbox
        sbox = (round(p.x - p.w / 2), round(p.y - p.h / 2),
                round(p.x + p.w / 2), round(p.y + p.h / 2))
        gbox = (round(fx0 * out_w), round(fy0 * out_h), round(fx1 * out_w), round(fy1 * out_h))
        pairs.append((_box_mean_rgb(sf, sbox), _box_mean_rgb(gf, gbox)))
    d = color_fidelity.evaluate(pairs)
    return {"advisory_delta_e": True, **d}


def _grade_damage(clip: str, source: str | None,
                  plans: "tuple[reframe.RenderPlan, reframe.RenderPlan] | None",
                  route_pts: list[RoutePoint] | None, path_obj: CropPath, meta: PathMeta,
                  spec: CheckSpec) -> CheckResult:
    """Does the DECLARED grade destroy information (design 2026-08-31 §3)?

    Renders the same episode twice — once with its colour block, once with every
    knob at identity — and compares the luma-histogram entropy of the two. Both
    sides come from a render, never from the shipped clip: measured directly and
    reproduced five times (design §3, §9.1), a clip-read's entropy comes back
    HIGHER than a render-pair's — CRF-18 quantization and deblocking SPREAD the
    luma histogram rather than collapsing it — so a clip-read comparison would be
    slightly more LENIENT than this one, not stricter. The risk to guard against
    is therefore missing real damage, not flagging a legitimate grade. The
    consequence is explicit and paired: THIS sensor judges the declared map, and
    check_reel's grade_faithful judges the delivered pixels.

    `plans` is (graded, plain) and comes from process_episode, which owns the
    attempt's own params — building the pair here from orch defaults would compare
    two renders the episode never made. `None` reports not-checked and does not
    block, exactly the shape `source` uses; a source-less episode reports the same
    status but a different reason, so a reader can tell "nobody passed plans" from
    "this episode has no pre-grade source clip".

    The subject dE00 rides along as an ADVISORY description, not a verdict. It was
    the verdict until 2026-08-31, and it could not tell a grade from damage: on the
    reference run a real conductor pair puts five of eight episodes over the old
    5.0 ceiling, two at over twice it, and none of them is damage (design §0.1).
    """
    if plans is None or source is None:
        return CheckResult("grade_damage", None,
                           {"status": "not-checked",
                            "reason": "no render plans" if source else "no source clip"})
    graded_plan, plain_plan = plans
    times = color.sample_times(graded_plan.dur)
    g_frames = reframe.plan_frames_rgb(graded_plan, source, times)
    p_frames = reframe.plan_frames_rgb(plain_plan, source, times)
    d = gradedamage.evaluate(plain=p_frames, graded=g_frames, floor=spec.entropy_floor)
    d.update(_subject_delta_advisory(clip, source, route_pts, path_obj, meta))
    if "status" in d:
        return CheckResult("grade_damage", None, d)
    return CheckResult("grade_damage", not d["below"], d)


ROUTE_SMOOTH_S = 0.08     # the span over which a crop reversal becomes visible (~5 frames @60fps)


def _route_window(route: list[dict]) -> int:
    """Frames spanning ROUTE_SMOOTH_S at the route's OWN cadence — see checks.jitter
    on why the route is filtered before it is differenced. Derived from the route's
    timestamps rather than an ffprobe fps: the route is what is being filtered, and a
    gappy or resampled one has a cadence of its own that the container never states.
    Degenerate input (too few points, or no elapsed time) → 1, the historical
    frame-to-frame behaviour, which is exactly right when there is nothing to filter."""
    if len(route) < 2:
        return 1
    span = route[-1]["t"] - route[0]["t"]
    if span <= 0:
        return 1
    return max(1, round((len(route) - 1) / span * ROUTE_SMOOTH_S))


def run(clip: str, route_path: str | None, path_path: str, spec: CheckSpec, out: str,
        source: str | None = None,
        plans: "tuple[reframe.RenderPlan, reframe.RenderPlan] | None" = None) -> Report:
    """The sidecar is read FIRST — it carries the provenance (`meta.pan`) that the
    rest of this function branches on, before anything asks for a route at all.

    Geometry comes from the sidecar reframe wrote — never re-derived here.
    Re-deriving crop_w from the canvas is right only while every layout is
    `fill`. Under fit it returns the canvas-aspect width, and on_line then
    divides by a width that was never cut.

    `source` (the pre-grade segment) and `plans` (the (graded, plain) RenderPlan
    pair) both feed the grade_damage check only — either absent (the default)
    reports that check `not-checked` (non-blocking, `passed` stays None) and
    changes nothing else; process_episode passes the reframe input segment as
    `source` and builds `plans` from the same manifest, which is what makes the
    check blocking in practice (design 2026-08-31 §3).
    """
    path = CropPath.from_json(path_path).xs
    path_obj = CropPath.from_json(path_path)   # extent_at_times needs the object, not just .xs
    meta = PathMeta.from_json(Path(path_path).with_suffix(".meta.json"))
    crop_w = meta.crop_w
    # One width per sample: the scalars for a constant rect, the sidecar's record under a
    # zoom. Built once here so every check below is handed the same series (design §5).
    crop_ws = meta.crop_ws or [meta.crop_w] * len(path)
    src_w, src_h = meta.src_dims
    # The sidecar is authoritative about provenance — reframe wrote it. A caller
    # that also hands over a route under a pan is redundant, not wrong, so the
    # route is ignored rather than refused; the reverse (a tracked sidecar with no
    # route) IS refused below, because there the missing input is load-bearing.
    if meta.pan:
        # A GENERATED path (design 2026-07-19 §5). There is no route, so there is
        # nothing to classify — take the direction off the path itself, or a
        # right-to-left pan would be read as reversing on every single frame.
        # Not read anywhere under a pan — centered/on_line/continuity all sit behind
        # arms the meta.pan branches short-circuit past. Bound anyway so the two
        # arms stay symmetric and a future ungated read fails on the empty list
        # rather than on an unbound name.
        route: list[dict] = []
        # `>=`, not `>`: a flat-ended path has no direction of its own, and "right"
        # matches the tracked branch's own default-to-right convention one arm down.
        direction = "right" if path[-1] >= path[0] else "left"
    else:
        if route_path is None:
            raise ValueError(
                f"check_episode needs a route for {path_path}: the sidecar says this path "
                "was tracked (pan=false), but route_path is None — pass the route.json "
                "reframe used, or re-render with a pan")
        route = [p.to_dict() for p in route_from_json(route_path)]
        _, direction = classify(route, src_w, src_h)
        # static/head-on routes carry no direction of their own. reframe does NOT
        # centre in that case when the author asked for `lead` — it lays the crop out
        # against the route's net travel (see compute_path) — so scoring against a
        # fixed "right" would grade the wrong line for a left-moving subject and
        # report a correct render as broken. Same helper, same answer, both sides.
        direction = direction or travel_direction(route)
    # Independent of the branch above: a pan has no observation to sample the
    # subject from (route_pts stays None) regardless of whether a route_path
    # was also handed over — same "ignored, not refused" stance as `route` above.
    route_pts = None if (meta.pan or route_path is None) else route_from_json(route_path)
    checks = {}

    if meta.pan:
        # NOT "no horizontal freedom" — a pan needs freedom and has it. Nobody is
        # being composed because nobody was observed, which is a different fact and
        # deserves a different reason. Judging composition here would compare the
        # crop against a subject derived from that same crop.
        checks["framing"] = CheckResult("framing", None,
                                        {"status": "editorial-only",
                                         "reason": "generated path — no tracked subject"})
    elif meta.freedom == 0 and not meta.zoomed:
        # the crop is as wide as the source: nobody controls composition, so it
        # can neither be failed nor silently passed (design 2026-07-10 §6). A ZOOM
        # is the exception: a push-in creates the freedom the layout did not have,
        # so the composition it produces is real and gets judged (design 2026-08-08 §5).
        checks["framing"] = CheckResult("framing", None,
                                        {"status": "editorial-only",
                                         "reason": "no horizontal freedom"})
    elif spec.composition == "center":
        d = checks_mod.centered(route, path, crop_ws)
        checks["centered"] = CheckResult("centered", d["pass"], {k: v for k, v in d.items() if k != "pass"})
    elif spec.composition == "lead":
        left, right = geometry.grid_lines(spec.grid)
        tf = left if direction == "right" else right
        d = checks_mod.on_line(route, path, crop_ws, tf)
        checks["on_line"] = CheckResult("on_line", d["pass"], {k: v for k, v in d.items() if k != "pass"})
    elif spec.composition == "break":
        # spec §6.2: break is tracked but relaxed — editorial only, no numeric fail
        checks["framing"] = CheckResult("framing", None, {"status": "editorial-only"})
    else:
        raise ValueError(f"unknown composition: {spec.composition!r}")

    # route is [] under a pan (there is no observation), so a generated path keeps
    # the historical vacuum-judged behaviour; a tracked one gets the subject's own
    # counter-motion discounted (see checks.jitter).
    #
    # max_reversal scales off crop_w, the BASE (widest) crop — not the per-sample
    # crop_ws in force at each instant. Under a zoom this is a fixed tolerance
    # measured against a shrinking rect: at a 0.6 push-in the tightest sample is
    # judged 1/0.6 = 1.67x more generously than the wide end. Not scaled to
    # crop_ws[i] here — undecided whether jitter tolerance should track the zoom
    # or stay anchored to the layout's own crop; noted, not fixed.
    dj = checks_mod.jitter(path, direction, max_reversal=max(2.0, crop_w * 0.005),
                           route=route or None, route_window=_route_window(route),
                           crop_ws=crop_ws)
    checks["jitter"] = CheckResult("jitter", dj["pass"], {k: v for k, v in dj.items() if k != "pass"})
    if meta.pan:
        # checks.continuity([]) returns pass=True — its zip never iterates — so the
        # honest answer has to be stated, not left to fall through to a green tick.
        checks["continuity"] = CheckResult("continuity", None,
                                           {"status": "not-checked",
                                            "reason": "generated path — no tracked subject"})
    else:
        dc = checks_mod.continuity(route, src_w)
        checks["continuity"] = CheckResult("continuity", dc["pass"],
                                           {k: v for k, v in dc.items() if k != "pass"})
    dl = checks_mod.length(_duration(clip), spec.target_dur)
    checks["length"] = CheckResult("length", dl["pass"], {k: v for k, v in dl.items() if k != "pass"})
    bf = _black_frames_check(clip, black_floor=spec.black_floor, black_rel=spec.black_rel)
    checks["black_frames"] = CheckResult("black_frames", bf["pass"], {k: v for k, v in bf.items() if k != "pass"})
    checks["grade_damage"] = _grade_damage(clip, source, plans, route_pts, path_obj, meta, spec)
    # spec'd but not yet implementable (§9): report honestly, never silent-pass
    checks["horizon"] = CheckResult("horizon", None, {"status": "not-implemented"})
    checks["head_power_point"] = CheckResult("head_power_point", None, {"status": "not-implemented"})

    report = Report(checks=checks, attempt=spec.attempt)
    report.write(out)
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="judge one rendered episode mechanically — composition, path "
                    "quality, black frames, grade damage → report.json. Reads the "
                    "clip with its route.json and path.json; process_episode runs "
                    "it after every reframe attempt and the retry ladder reads the "
                    "verdict.")
    ap.add_argument("clip")
    ap.add_argument("route", nargs="?", default=None,
                    help="route.json (omit under a generated pan — the sidecar says so)")
    ap.add_argument("path")
    ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--target-dur", type=float, required=True)
    ap.add_argument("--attempt", type=int, default=1)
    return ap


def main() -> None:
    a = build_parser().parse_args()
    spec = CheckSpec(composition=a.composition, grid=a.grid, target_dur=a.target_dur,
                     attempt=a.attempt)
    run(a.clip, a.route, a.path, spec, a.out)


if __name__ == "__main__":
    main()
