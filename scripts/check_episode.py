"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageStat
from scripts import reframe
from scripts.lib import (checks as checks_mod, color, color_fidelity, ffbin,
                         geometry, gradedamage, proc, regions)
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


def _region_pairs(plain, graded, mask) -> list[tuple]:
    """One (plain_rgb, graded_rgb) mean pair per frame, over that frame's own mask.

    A frame whose mask slice holds no pixels contributes NO pair rather than a
    fabricated one: an empty slice would mean() to NaN in silence. The count that
    survives is what color_fidelity.evaluate reports as `samples`."""
    pairs = []
    for i in range(len(graded)):
        m = mask[i]
        if not m.any():
            continue
        pairs.append((tuple(float(plain[i][m][:, c].mean()) for c in range(3)),
                      tuple(float(graded[i][m][:, c].mean()) for c in range(3))))
    return pairs


def _subject_delta_advisory(plain_frames, graded_frames, times: list[float],
                            route_pts: list[RoutePoint] | None,
                            path_obj: CropPath, meta: PathMeta) -> dict:
    """The grade's dE00 over a NAMED region, as a DESCRIPTION (design 2026-09-16).

    Both stacks come from the (graded, plain) render pair _grade_damage has
    already decoded: same geometry, same times, same baseline as the entropy
    ratio that carries the verdict. Until 2026-09-16 this decoded the raw source
    and the shipped clip instead — two more decodes and four more ffprobes, in a
    different geometry at a different time set, two lines after the pair it could
    have used. Zero coverage was lost by the swap: the advisory is only ever
    reached after _grade_damage has returned on a missing pair (design §0.3).

    The order of the two stacks is load-bearing and NOT symmetric: the three
    signed components read plain -> graded, so swapping them inverts every one of
    them while leaving dE00 itself identical. `delta_l`'s sign is asserted in the
    proofs for exactly that reason.

    The region is resolved by regions.subject_mask/refuse — the SAME rule the
    tone stage authors a grade with — so a subject under regions.MIN_REGION_FRAC
    reads the crop and SAYS which, instead of reporting the grade's effect on
    whatever a 0.23%-of-frame box happened to contain (design §0.2: that box is
    exactly where the region choice is worth the most and trustworthy the least).

    `background_delta_e` rides along only when the subject supplied the reading:
    after a fallback the reading IS the crop, and a crop and its background agree
    to 0.03 on seven of the eight real episodes (design §0.1) — two names for one
    number. So a subject fallback drops BOTH background keys: the contrast has
    nothing to contrast with.

    When the subject does supply the reading, the background goes through the SAME
    regions.refuse — it is a kind in regions.KINDS with a fraction of its own, and
    a bbox that covers the whole output frame leaves no background at all, which
    subject_mask's clamping makes ordinary on a tight reframe. `background_fallback`
    is then the named absence (one of regions.FALLBACKS) and `background_delta_e` is
    simply not emitted: a bare null beside a real delta_e reads either as "the
    background did not move" or as an error, with nothing telling them apart, which
    is the unnamed absence this slice exists to remove (design §1, rule 1). The
    background's own fraction is not reported — it is 1 - region_fraction exactly,
    and a second representation of one number is a contradiction surface.

    `crop_delta_c`/`crop_delta_h` ride along on the SAME `fallback is None` arm as
    `background_delta_e` — beside it, not nested under its own `is None` guard —
    for a different reason and a different reader. The reel-level chroma_spread
    check (design 2026-09-17 §2.2) needs ONE pixel set defined identically on
    every episode, and the crop — subject UNION background, the whole rendered
    frame — is the only region that is always present: `subject` falls back by
    name and `background` is not reported at all after a subject fallback, so
    neither can serve. Emitted ONLY when the subject supplied the reading: on a
    fallback, `delta_c`/`delta_h` in this same dict already ARE the crop's own
    (`read` is the full frame there too), and a second key holding the same
    number would be exactly the contradiction surface the paragraph above names
    for the background's fraction. Sitting beside `background_delta_e` rather
    than inside its guard is load-bearing: a subject that covers the whole frame
    leaves no background at all (`background_fallback` is then a name, not None)
    but still supplies a crop reading of its own.
    """
    g, p = np.asarray(graded_frames), np.asarray(plain_frames)
    if g.shape != p.shape:
        raise ValueError(f"check_episode: the graded and plain frames must have the "
                         f"same shape — got {g.shape} and {p.shape}. They are two "
                         f"renders of ONE plan pair; a disagreement is a caller "
                         f"error, not an input to broadcast over")
    n, h, w = g.shape[:3]
    if route_pts:
        extents = geometry.extent_at_times(route_pts, path_obj, meta, times)
        mask, frac = regions.subject_mask(extents, n, h, w)
        located = True
    else:
        mask, frac, located = None, 0.0, False
    # A mask holding no pixels has a fraction of exactly 0.0 — it is the SAME
    # array answering both questions — so the size gate names it `too-small` on
    # its own. regions.refuse carried a separate `empty` argument for that case
    # until this slice's final review; see its docstring for why it went.
    fallback = regions.refuse("subject", located=located, fraction=frac)
    whole = np.ones((n, h, w), dtype=bool)
    read = whole if fallback else mask
    # A bare read, never an absence: `whole` holds pixels in every one of n >= 1
    # frames (color.sample_times returns FRAMES >= 1 times), and a subject read
    # only runs when regions.refuse DECLINED to refuse, which is the statement
    # that the mask holds pixels. So an empty pair list is a broken producer, not
    # an input to describe. It must raise, because the alternative shape
    # color_fidelity.evaluate would return here is {status, reason} — and
    # _grade_damage merges this dict flat into the entropy verdict, where until
    # 2026-09-21 `status` was the discriminator that decided whether a BLOCKING
    # verdict counted (design §0.1). The background arm below has followed this
    # rule since 2026-09-16; this is the read it was asymmetric with.
    pairs = _region_pairs(p, g, read)
    if not pairs:
        raise ValueError(
            f"check_episode: the {'crop' if fallback else 'subject'} read came back "
            f"with no sample pairs over {n} frames. A crop read is the whole frame "
            f"and a subject read only happens when regions.refuse declined to "
            f"refuse, so both hold pixels by construction — an empty read is a "
            f"contract break in regions.subject_mask or _region_pairs, not an "
            f"input to report as a not-checked advisory.")
    out = {"advisory_delta_e": True,
           # the fraction of the region ASKED for — on a too-small row it is the
           # small number that is the evidence, never the crop's 1.0 it fell back
           # to. regions.AnchorReading.fraction's own convention (design §2.3).
           "region": "crop" if fallback else "subject",
           "region_fraction": round(frac, 4),
           "region_fallback": fallback,
           **color_fidelity.evaluate(pairs)}
    if fallback is None:
        bg = ~mask
        out["background_fallback"] = regions.refuse(
            "background", located=located, fraction=1.0 - frac)
        if out["background_fallback"] is None:
            # A bare subscript, never .get: a background that refused nothing holds
            # pixels in at least one frame, so _region_pairs cannot come back empty
            # and evaluate cannot return its no-samples shape. If that ever stops
            # holding, a KeyError is the right answer — a None here is the defect.
            out["background_delta_e"] = color_fidelity.evaluate(
                _region_pairs(p, g, bg))["delta_e"]
        # The CROP's own signed displacement, for the reel-level chroma_spread check
        # (design 2026-09-17 §2.2). The reel needs one pixel set defined identically
        # on every episode, and the crop is the only region that is always present:
        # `subject` falls back by name and `background` is not reported at all after
        # a subject fallback. Emitted only on this arm — when the subject fell back,
        # delta_c/delta_h ALREADY are the crop's, and a second key holding the same
        # number is the contradiction surface 2026-09-16 §2.3 refused for the
        # background's fraction. The consumer reads `region` to know which pair to
        # take. Bare subscripts for the same reason as the background's above: a
        # full-frame mask holds pixels in every frame.
        crop = color_fidelity.evaluate(_region_pairs(p, g, whole))
        out["crop_delta_c"], out["crop_delta_h"] = crop["delta_c"], crop["delta_h"]
    return out


def _grade_damage(source: str | None,
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

    Since 2026-09-16 that description rides THIS pair — the same two stacks, the
    same times, the same pre-encode baseline as the entropy ratio that carries the
    verdict (design 2026-09-16 §0.3). It used to decode the raw source and the
    shipped clip instead, two lines below the pair it could have used: four extra
    decodes and four extra ffprobes per episode, in a different geometry at a
    different time set, for two numbers about one grade. `clip` left this
    signature with them — it was passed in for the advisory and for nothing else.
    """
    if plans is None or source is None:
        return CheckResult("grade_damage", None,
                           {"status": "not-checked",
                            "reason": "no render plans" if source else "no source clip"})
    graded_plan, plain_plan = plans
    times = color.sample_times(graded_plan.dur)
    g_frames = reframe.plan_frames_rgb(graded_plan, source, times)
    p_frames = reframe.plan_frames_rgb(plain_plan, source, times)
    verdict = gradedamage.evaluate(plain=p_frames, graded=g_frames, floor=spec.entropy_floor)
    # The discriminator belongs to the dict it judges. `d` below is a FLAT merge of
    # this verdict and the advisory description, and both halves can spell
    # {status, reason} — so reading `"status" in d` made a blocking verdict depend
    # on a key the advisory could contribute (design §0.1/§2.1). The advisory can
    # no longer emit that shape at all, which is what closes the defect; branching
    # here keeps it closed against a future advisory key.
    unchecked = "status" in verdict
    d = dict(verdict)
    d.update(_subject_delta_advisory(p_frames, g_frames, times, route_pts, path_obj, meta))
    if unchecked:
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
    checks["grade_damage"] = _grade_damage(source, plans, route_pts, path_obj, meta, spec)
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
    ap.add_argument("clip", help="the rendered episode .mp4 to judge")
    ap.add_argument("route", nargs="?", default=None,
                    help="route.json (omit under a generated pan — the sidecar says so)")
    ap.add_argument("path", help="path.json — the per-frame crop rect reframe recorded")
    ap.add_argument("out", help="report.json output path")
    ap.add_argument("--composition", default="lead",
                    help="the rule the subject is judged against: lead | center | thirds")
    ap.add_argument("--grid", default="thirds", help="the guide grid: thirds | phi")
    ap.add_argument("--target-dur", type=float, required=True,
                    help="the length this episode was cut to, seconds")
    ap.add_argument("--attempt", type=int, default=1,
                    help="which retry attempt this is, 1-based — recorded in the report")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    spec = CheckSpec(composition=a.composition, grid=a.grid, target_dur=a.target_dur,
                     attempt=a.attempt)
    run(a.clip, a.route, a.path, spec, a.out)


if __name__ == "__main__":
    main()
