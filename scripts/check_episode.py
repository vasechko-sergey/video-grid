"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse
import tempfile
from pathlib import Path
from PIL import Image, ImageStat
from scripts.lib import checks as checks_mod, color_fidelity, ffbin, geometry, proc
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


def _region_mean_rgb(clip: str, t: float, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
    """Mean (R,G,B) of a pixel box in one grabbed frame at time t. box = (x0,y0,x1,y1)."""
    with tempfile.TemporaryDirectory() as tmp:
        f = f"{tmp}/f.png"
        proc.run([ffbin.ffmpeg(), "-y", "-i", clip, "-ss", f"{t:.3f}",
                  "-frames:v", "1", f])          # -ss AFTER -i (§12 seek order)
        im = Image.open(f).convert("RGB")
        x0, y0, x1, y1 = box
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(im.width, max(x1, x0 + 1)), min(im.height, max(y1, y0 + 1))
        return tuple(ImageStat.Stat(im.crop((x0, y0, x1, y1))).mean[:3])


def _colour_fidelity(clip: str, source: str | None, route_pts: list[RoutePoint] | None,
                     path_obj: CropPath, meta: PathMeta, spec: CheckSpec) -> CheckResult:
    """Advisory subject hue-drift, source vs graded (design 2026-07-26 §7).

    Sample the tracked subject's mean RGB in the SOURCE (pre-grade segment, at
    the route bbox in source px) and in the graded `clip` (at the subject's
    projected location, via geometry.extent_at_times) at K times, and delegate
    to the pure color_fidelity.evaluate for the hue-angle verdict. `passed` is
    always None — hue drift never fails an episode, it is reported."""
    if source is None or not route_pts:
        return CheckResult("color_fidelity", None,
                           {"status": "not-checked",
                            "reason": "no source clip or no tracked subject"})
    ts = [p.t for p in route_pts]
    times = [ts[0] + (ts[-1] - ts[0]) * f for f in (0.25, 0.5, 0.75)]
    extents = geometry.extent_at_times(route_pts, path_obj, meta, times)   # output fractions
    out_w, out_h = meta.out_dims
    pairs = []
    for t, (fx0, fy0, fx1, fy1) in zip(times, extents):
        p = min(route_pts, key=lambda q: abs(q.t - t))          # nearest source bbox
        sbox = (round(p.x - p.w / 2), round(p.y - p.h / 2),
                round(p.x + p.w / 2), round(p.y + p.h / 2))
        gbox = (round(fx0 * out_w), round(fy0 * out_h), round(fx1 * out_w), round(fy1 * out_h))
        pairs.append((_region_mean_rgb(source, t, sbox), _region_mean_rgb(clip, t, gbox)))
    return CheckResult("color_fidelity", None,
                       color_fidelity.evaluate(pairs, spec.hue_drift_max))


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
        source: str | None = None) -> Report:
    """The sidecar is read FIRST — it carries the provenance (`meta.pan`) that the
    rest of this function branches on, before anything asks for a route at all.

    Geometry comes from the sidecar reframe wrote — never re-derived here.
    Re-deriving crop_w from the canvas is right only while every layout is
    `fill`. Under fit it returns the canvas-aspect width, and on_line then
    divides by a width that was never cut.

    `source` (the pre-grade segment) feeds the advisory color_fidelity check
    only — None (the default) reports that check `not-checked` and changes
    nothing else; process_episode passes the reframe input segment here.
    """
    path = CropPath.from_json(path_path).xs
    path_obj = CropPath.from_json(path_path)   # extent_at_times needs the object, not just .xs
    meta = PathMeta.from_json(Path(path_path).with_suffix(".meta.json"))
    crop_w = meta.crop_w
    crop_ws = [meta.crop_w] * len(path)
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
    elif meta.freedom == 0:
        # the crop is as wide as the source: nobody controls composition, so it
        # can neither be failed nor silently passed (design 2026-07-10 §6)
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
    checks["color_fidelity"] = _colour_fidelity(clip, source, route_pts, path_obj, meta, spec)
    # spec'd but not yet implementable (§9): report honestly, never silent-pass
    checks["horizon"] = CheckResult("horizon", None, {"status": "not-implemented"})
    checks["head_power_point"] = CheckResult("head_power_point", None, {"status": "not-implemented"})

    report = Report(checks=checks, attempt=spec.attempt)
    report.write(out)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("route", nargs="?", default=None,
                    help="route.json (omit under a generated pan — the sidecar says so)")
    ap.add_argument("path")
    ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--target-dur", type=float, required=True)
    ap.add_argument("--attempt", type=int, default=1)
    a = ap.parse_args()
    spec = CheckSpec(composition=a.composition, grid=a.grid, target_dur=a.target_dur,
                     attempt=a.attempt)
    run(a.clip, a.route, a.path, spec, a.out)
