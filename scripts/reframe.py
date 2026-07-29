"""Compose one episode: route + rules → cropped/colored clip (spec §6)."""
import argparse, json
from pathlib import Path
from scripts.lib import geometry as g
from scripts.lib import pathsmooth, color, ffbin, proc
from scripts.lib import layout as layout_lib
from scripts.lib.layout import ResolvedLayout
from scripts.lib.motion import classify, travel_direction as classify_direction
from scripts.lib.models import (ReframeSpec, CropPath, route_from_json, Delivery,
                                PathMeta, LayoutSpec, BACKGROUNDS, PanSpec)


def compute_path(route: list[dict[str, float]], composition: str, grid: str,
                 canvas: tuple[int, int], src: tuple[int, int],
                 motion: tuple[str, str | None], max_step: float,
                 crop_w: int, smooth_window: int = pathsmooth.DEFAULT_WINDOW) -> list[int]:
    # crop_w comes from the resolved layout — the caller already cut it; deriving
    # it from `canvas` here would be right only while every layout is `fill`.
    kind, direction = motion if motion[0] == "lateral" else (motion[0], "right")
    if composition == "lead" and kind != "lateral" and len(route) >= 2:
        # motion.classify refuses to call a shot lateral when the subject ALSO grows
        # toward the camera — its "ambiguous zone", which falls through to static
        # deliberately because a centred crop is the SAFE framing when nobody said
        # otherwise. A surfer riding across the frame and toward a beach-side telephoto
        # is exactly that shape: measured on one, dx was 30% of frame width (lateral
        # needs 15%) and the box grew 3.1x (head-on needs 1.6x), so the shot was called
        # static and the authored `lead` silently rendered as `center`.
        #
        # Picking a safe default for an unstated intent is not the same as VETOING a
        # stated one, and quietly substituting a different composition is the class of
        # silent swap this repo refuses everywhere else. So honour the request and take
        # the direction from the route's own net travel — the one thing the ambiguous
        # zone never made ambiguous (it enters that zone only when |dx| is LARGE).
        kind, direction = "lateral", classify_direction(route)
    if composition in ("center", "break") or kind != "lateral":
        # center / head-on / static: aim crop centre at subject, no lead.
        # break (spec §6.2): tracked but relaxed — v1 center-tracks; extreme
        # framing is editorial territory, checks are editorial-only.
        raw = [g.clamp(round(pt["x"] - crop_w / 2), 0, src[0] - crop_w)
               for pt in route]
    else:
        raw = [g.crop_x(pt["x"], composition, direction, grid, crop_w, src[0])
               for pt in route]
    smoothed = pathsmooth.smooth(raw, max_step=max_step, window=smooth_window)
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame.
    # At zero freedom (crop_w == src_w) this clamps to a constant 0 — a
    # whole-frame layout has nowhere to travel, and needs no special case.
    return [int(g.clamp(round(x), 0, src[0] - crop_w)) for x in smoothed]


def generate_pan_path(pan: PanSpec, freedom: int, fps: float, dur: float,
                      max_speed: float) -> tuple[list[int], list[float]]:
    """A constant-velocity crop path with no route behind it (design 2026-07-19 §4).

    Returns (path, times) at the clip's own frame cadence — the same pair
    `reframe` otherwise derives from a tracked route, so `_xexpr` and
    `CropPath` are reached identically either way.

    IT DOES NOT SMOOTH, and that is a rule about provenance rather than shape.
    `pathsmooth.smooth` exists to tame OBSERVATION NOISE; a generated line has
    none, and running it through the smoother can only hurt in two ways — the
    rate limiter caps each per-frame delta and so silently prevents the pan from
    ever reaching `end` (the reveal the author asked for does not happen, and
    nothing in the report says so), while savgol fits a polynomial across the
    endpoints and bends a line that was already exactly right.

    Because the rate limiter is gone, the speed cap becomes a GATE instead of a
    silent correction (see the raise below). `max_speed` is reused as a CEILING,
    not a target: a cinematic reveal sits far below it, and its job here is to
    catch the absurd (a crop_scale typo turning a slow pan into a whip), not to
    express taste. No new threshold is invented.

    The pan spans the WHOLE episode by construction — there is no parameter for
    when it starts or stops, which is what makes dividing by `dur` correct below.
    Both degenerate inputs — no freedom to travel across, and no duration to
    travel during — are REFUSED rather than absorbed: each would otherwise
    produce a plausible-looking path that is not the move the author asked for.
    """
    if freedom <= 0:
        raise ValueError(
            f"a pan needs horizontal freedom and this layout has {freedom}px: the crop is "
            "as wide as the source, so the pan would clamp to a constant and render a "
            "STATIC frame — which looks like an ffmpeg bug, not a manifest one. Set "
            "crop_scale below 1.0, or pick a narrower crop_aspect")
    # Guards the division below. Without it dur=0 raises ZeroDivisionError, which
    # names neither the offending value nor a remedy, and a NEGATIVE dur is worse:
    # v comes out negative, slips under the max_speed ceiling untouched, and n
    # collapses to 2 — a silently truncated two-frame pan. Unreachable through
    # reframe today (_probe already refuses dur <= 0), but this is a public pure
    # function, and the freedom guard one line up would be arbitrary without its twin.
    if dur <= 0:
        raise ValueError(
            f"a pan needs a duration to travel across and this episode has {dur}s — "
            "a clip with no length has no room for a camera move. Check that the "
            "segment probes to a real duration, or drop the `pan` field")
    x0 = round(pan.start * freedom)
    x1 = round(pan.end * freedom)
    if x0 == x1:
        # PanSpec refuses start == end, but it validates FRACTIONS and cannot see
        # the freedom they get multiplied by. A span narrower than half a pixel
        # rounds both ends onto the same integer, and the render is then a static
        # frame the author never asked for — the same silent-static-frame failure
        # the freedom guard above exists to prevent, reached by a different road.
        raise ValueError(
            f"pan {pan.start}→{pan.end} spans {abs(pan.end - pan.start):.6g} of {freedom}px "
            f"of freedom, so both ends round to {x0}px — the render would be a STATIC "
            "frame. Widen the from→to span, or drop the `pan` field")
    v = abs(x1 - x0) / dur
    if v > max_speed:
        raise ValueError(
            f"pan {pan.start}→{pan.end} travels {abs(x1 - x0)}px across {dur:.3f}s = "
            f"{v:.0f} px/s, past max_speed {max_speed:.0f} px/s. Shrink the extent "
            f"(a smaller from→to span), give the episode a longer duration, or raise "
            f"max_speed if the whip is deliberate")
    # floored at 2 so the i/(n-1) denominator below can never be zero; a clip that
    # rounds to a single frame had no time to travel anyway, and two knots at the
    # same instant render as the constant that honestly describes it
    n = max(2, round(dur * fps))
    times = [i / fps for i in range(n)]
    # endpoints are EXACT: at i=0 the term is 0, at i=n-1 the ratio is exactly 1.0
    path = [round(x0 + (x1 - x0) * i / (n - 1)) for i in range(n)]
    return path, times


def _simplify(path: list[int], times: list[float], eps: float = 2.0,
              max_knots: int = 80) -> list[tuple[float, float]]:
    """Douglas-Peucker over (t, x): per-frame path → a few linear knots.

    Keeps the crop expression short (nested per-frame if() hits ffmpeg's
    expression parser limits on 60fps clips) and makes motion piecewise-linear
    — smoother than piecewise-constant per-frame steps.

    The time axis comes from the route's real timestamps (`times`), not from
    the path index — routes may have tracking gaps (hero occluded; spec
    §6.1a), so index-derived time would desync the crop expression from the
    true video timeline once a gap has occurred.

    Real footage (thousands of frames, ±px post-smoothing jitter) can still
    produce far more knots than ffmpeg's expression parser can swallow — cap
    the count adaptively by doubling eps until we're under max_knots. eps
    growth always terminates (a huge eps collapses to the 2 endpoint knots).
    """
    pts = [(float(t), float(x)) for t, x in zip(times, path)]

    # Iterative (explicit stack) — a recursive dp() blows Python's recursion
    # limit on long real routes (thousands of frames); same split rule, just
    # a non-recursive traversal of the identical divide-and-conquer tree (#5).
    def run(eps: float) -> list[tuple[float, float]]:
        keep = {0, len(pts) - 1}
        stack = [(0, len(pts) - 1)]
        while stack:
            lo, hi = stack.pop()
            if hi - lo < 2:
                continue
            (t0, x0), (t1, x1) = pts[lo], pts[hi]
            worst, wi = 0.0, None
            for i in range(lo + 1, hi):
                t, x = pts[i]
                # duplicate lo/hi timestamps would divide by zero → fall back to x0
                # (unreachable on real routes: RoutePoint.t is strictly increasing)
                xh = x0 + (x1 - x0) * ((t - t0) / (t1 - t0)) if t1 != t0 else x0
                if abs(x - xh) > worst:
                    worst, wi = abs(x - xh), i
            if worst > eps and wi is not None:
                keep.add(wi)
                stack.append((lo, wi))
                stack.append((wi, hi))
        return [pts[i] for i in sorted(keep)]

    knots = run(eps)
    while len(knots) > max_knots:
        eps *= 2
        knots = run(eps)
    return knots


def _xexpr(path: list[int], times: list[float]) -> str:
    # piecewise-LINEAR x(t) over simplified knots: lerp inside each segment
    knots = _simplify(path, times)
    if len(knots) == 1:
        return f"{knots[0][1]:.1f}"
    expr = f"{knots[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in zip(knots[-2::-1], knots[:0:-1]):
        slope = (x1 - x0) / max(1e-9, t1 - t0)
        seg = f"({x0:.1f}+({slope:.3f})*(t-{t0:.4f}))"
        expr = f"if(lt(t,{t1:.4f}),{seg},{expr})"
    return expr


def _probe(src: str) -> tuple[int, int, float, float]:
    """(width, height, fps, duration) — one ffprobe call, four numbers.

    The duration is load-bearing engine input, not diagnostics: the `solid` filler
    bounds its synthesized background with `color=:d=<duration>` (design §4). Both
    the stream's and the container's duration are asked for in the same call, since
    some containers carry only the latter; the stream's is preferred.
    """
    out = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,duration:format=duration",
         "-of", "json", src], text=True)
    probe = json.loads(out.stdout)
    s = probe["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    fps = float(num) / (float(den) or 1.0)
    if fps <= 0:
        raise ValueError(
            f"{src}: probed fps is {fps} — corrupt/streamed source? re-encode it first")
    raw = s.get("duration") or probe.get("format", {}).get("duration")
    try:
        dur = float(raw)
    except (TypeError, ValueError):
        dur = 0.0
    if dur <= 0:
        # RAISE — never fall back to `overlay=:shortest=1`. That fallback terminates,
        # but truncates exactly one frame off every render (design §4), so it would
        # reintroduce the length regression invisibly on precisely the files nobody
        # looked at. A source whose length is unknowable is a source to re-encode.
        raise ValueError(
            f"{src}: no usable duration (ffprobe gave {raw!r}) — the file may be "
            "truncated, durationless or streamed. reframe needs the source length to "
            "bound a solid background's synthesized `color` source; re-encode it first")
    return int(s["width"]), int(s["height"]), fps, dur


def _background_args(rl: ResolvedLayout, fps: float, dur: float) -> tuple[str, str, str]:
    """(bg_chain, fg_source_label, overlay_opts) for one filler.

    blur reads the source TWICE — a scaled cover for the background and the
    tracked crop for the content — which is the only reason the composite
    splits. solid SYNTHESIZES its background and reads the source once, so it
    does not split. The difference in shape is caused by the filler, which is
    what makes this a parameter and not a branch: both arms hand back a [bg], a
    [fg] and one overlay, over the identical tail.

    The third element is the overlay's options, `""` for both fillers today. It
    stays in the tuple as the seam a future filler would use — collapsing it now
    only to re-add it later is churn.
    """
    if rl.background == "solid":
        # `color` is an INFINITE source, so something must end it — but NOT the
        # overlay. `overlay=:shortest=1` terminates and is the reflex remedy, yet it
        # lands EXACTLY one frame short of the source (measured: source 95 frames,
        # blur 95, solid 94; `eof_action=endall` is identical — the truncation is
        # inherent to ending an overlay against an infinite source). One frame
        # accumulates into a real gate: check_reel measures the assembled reel
        # against _LENGTH_TOL (0.5s), so ~30 solid episodes at 59.94fps eat the
        # whole band. A filler must not change how long the reel is.
        #
        # `d=` bounds the source, and is NOT sufficient. `color`'s timebase is 1/r
        # while the decoded source carries its CONTAINER's (1/15360 for a 30fps
        # mp4); `overlay` inherits the FIRST input's — the synthesized background —
        # so the tail's `fps` filter reads the mismatch as a stream longer by
        # exactly container_tb / fps. 15360/30 = 512, and 3s x 512 = 1536s / 46080
        # frames out of a 90-frame clip.
        #
        # The trigger is an EXACT RATE MATCH, not a particular frame rate — the
        # part that misleads. It fires when the emitted `r=` reproduces the
        # source's rational rate exactly, so integer rates (24/25/30/50/60) blow up
        # and NTSC fractional ones do not. golden_ride blows up too when handed
        # `r=60000/1001` (verified: SIGKILL); it survives only because `{fps:.6g}`
        # mangles that to `59.9401`, which no longer matches — and even then it
        # renders 96 frames against the source's 95. So the NTSC fixtures are safe
        # by a FORMATTING ACCIDENT; a 29.97fps fixture would prove nothing, and the
        # duration proof must run against an integer rate.
        #
        # reframe() therefore bounds the OUTPUT with `-t` (see there), which is
        # what actually pins the length. `d=` is kept for one narrow reason: a
        # graph copied out of a test into a shell then terminates AT ALL rather
        # than running forever. It does not make such a graph the right length,
        # and in the shipped command it is output-neutral.
        return (f"color=c={rl.background_color}:s={rl.out_w}x{rl.out_h}:"
                f"r={fps:.6g}:d={dur:.6f}[bg];",
                "[0:v]", "")
    if rl.background != "blur":
        # Terminal raise even though LayoutSpec validates the vocabulary upstream:
        # without it a new BACKGROUNDS entry would fall through and render as blur —
        # wrong pixels, no error. Same discipline as geometry.grid_lines/target_frac.
        raise ValueError(f"unknown background: {rl.background!r} — expected one of {BACKGROUNDS}")
    # boxblur rejects a radius at/above half the chroma plane; yuv420p halves the
    # plane again, so the ceiling is the largest radius STRICTLY under
    # min(out_w, out_h) / 4 — i.e. (min(out_w, out_h) - 1) // 4. ffmpeg 8.1.2
    # tightened this bound to a strict `<` (8.1.1 accepted radius == min/4), so a
    # 3840x200 cover now refuses 50 and survives at 49; a 1280x4 cover refuses 1
    # and survives at 0.
    #
    # The ceiling is applied LAST. Written as max(2, min(w // 60, ceiling)) the
    # floor wins whenever the ceiling is 0 or 1 — a canvas under 8px on its short
    # side would ask for radius 2 and ffmpeg would refuse it, which is the very
    # crash the ceiling exists to prevent. Below 8px the blur is meaningless
    # anyway; radius 0 is a legal no-op.
    radius = min(max(2, rl.out_w // 60), (min(rl.out_w, rl.out_h) - 1) // 4)
    return (f"[0:v]split=2[a][b];"
            f"[a]scale={rl.out_w}:{rl.out_h}:force_original_aspect_ratio=increase,"
            f"crop={rl.out_w}:{rl.out_h},boxblur={radius}:2[bg];",
            "[b]", "")


RAMP_PROBE_W = 256          # a 256-step ramp: one sample per output code


def verify_tone(frag: str) -> None:
    """Render a ramp through a tone fragment and refuse a non-monotone transfer.

    ffmpeg's `curves` fits a spline, and a spline through arbitrary anchors can dip
    below itself between control points even when the map it was given rises
    everywhere. A dip means a brighter input leaving darker than its neighbour: not
    visible as brightness, but it is a contour waiting to appear in any smooth
    gradient — a sky, a wall of water. Fuzzing random anchor triples put roughly a
    third of them 1-3 codes negative, so this is a real case and not a theoretical
    one; the six profiles this reel actually uses all come back clean.

    Cheap enough to run per episode (a 256x4 frame), and it turns a silent banding
    risk into a loud error naming the fix.
    """
    ramp = bytes(bytearray(
        [v for _ in range(4) for v in
         (b for x in range(RAMP_PROBE_W) for b in (x, x, x))]))
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{RAMP_PROBE_W}x4", "-i", "-", "-vf", frag.rstrip(","),
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                   input=ramp).stdout
    if len(out) < RAMP_PROBE_W * 3:
        raise RuntimeError(f"tone curve produced no frame — ffmpeg rejected {frag!r}; "
                           "two control points probably collapsed together")
    lut = [out[i * 3] for i in range(RAMP_PROBE_W)]
    dips = [(i, lut[i], lut[i + 1]) for i in range(RAMP_PROBE_W - 1) if lut[i + 1] < lut[i]]
    if dips:
        i, a, b = dips[0]
        raise RuntimeError(
            f"tone curve is not monotone: input {i} -> {a} but {i+1} -> {b} "
            f"({len(dips)} such steps). The fitted spline overshot between anchors — "
            "move the p5/p50/p95 targets closer to the measured source anchors, or "
            "widen the gap between two anchors that nearly coincide")


def _filter_args(rl: ResolvedLayout, xexpr: str, cy: int, grade: str,
                 fps: float, dur: float) -> list[str]:
    """The ffmpeg filter arguments for one layout.

    fill takes the fast path: one -vf chain, byte-identical to what this script
    emitted before layouts existed. That is not an optimization — it is how the
    golden fixture is protected from a silent change of command.

    Otherwise the composite delegates its background to `_background_args` — the
    one place the two fillers differ — and composes the identical [bg]/[fg]/
    overlay/tail shape around whatever it returns.

    `grade` is the FINISHED colour fragment from color.grade_chain — reframe builds
    it (and, for a tone curve, verifies it with verify_tone) before calling here, so
    this function stays a pure string-composer with no colour knowledge of its own.
    It is "" at every knob's default, which is exactly what keeps the fast path
    byte-identical to before colour-as-a-stage. reframe owns the trailing
    fps/format tail, appended after `grade` either way.
    """
    tail = f"{grade},fps={fps:.6g},format=yuv420p"
    if rl.fast_path:
        return ["-vf", (f"crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},"
                        f"scale={rl.out_w}:{rl.out_h},{tail}")]
    rx, ry, rw, rh = rl.rect_px          # the CONTENT rect; the border sits outside it
    b = rl.border_px
    ox, oy, ow, oh = rx - b, ry - b, rw + 2 * b, rh + 2 * b
    bg_chain, fg_src, ov_opts = _background_args(rl, fps, dur)
    pad = f",pad={ow}:{oh}:{b}:{b}:{rl.border_color}" if b else ""
    return ["-filter_complex",
            (f"{bg_chain}"
             f"{fg_src}crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},scale={rw}:{rh}{pad}[fg];"
             f"[bg][fg]overlay={ox}:{oy}{ov_opts},{tail}")]


def reframe(spec: ReframeSpec, src: str, route_path: str | None, out: str,
            path_out: str, *, stabilized: bool = False) -> str:
    """Compose one episode from a tracked route OR a generated pan (spec §6):
    crop/scale/color per `spec`.

    spec: a ReframeSpec (scripts/lib/models.py) — composition/grid/canvas/color_means/
    delivery/layout/max_speed/color_correct/pan. src/route_path/out/path_out stay explicit
    per-call I/O paths, not config. spec.max_speed: crop-x speed cap in px/sec — frame-rate
    independent (25 px/frame at the session's 30fps ≡ 750 px/s). spec.color_correct: an
    optional per-channel factor the reel retry loop composes onto the grade to pull one
    episode toward the reel median (None = base grade only). Stabilization is a
    PRE-STAGE, not part of this chain: the caller runs vidstab.stabilize and hands
    its output in as `src`, and `stabilized` (below) records that it did (design
    2026-07-20 §1).

    route_path is OPTIONAL and must be None under a pan: a pan's path is
    generated, so there is no route to read, and writing an empty route.json to
    keep a consumer happy would be a fabricated observation — an empty route
    already MEANS "the tracker ran and found nobody" (design 2026-07-19 §6.1).

    `stabilized` is a FACT ABOUT `src`, not an instruction: it says the caller
    already ran the vidstab pre-stage and handed us its output. reframe cannot
    stabilize — a ReframeSpec.stabilize would be a lie in the type — but it does
    write the sidecar, and whether the pixels were corrected is exactly the kind of
    thing PathMeta exists to record (design 2026-07-20 §6.2). It flows to PathMeta
    and nowhere else.

    Writes `out` (the clip), `path_out` (the crop path) and `path_out`'s `.meta.json`
    sidecar — what was actually cut, for check_episode/storyboard to read back instead
    of re-deriving the crop from the canvas (silently wrong under a non-fill layout).
    """
    # NEVER assume dims/fps: real footage is 4K/60. `dur` bounds a solid filler's
    # synthesized background so the render is exactly as long as the source (§4).
    src_w, src_h, fps, dur = _probe(src)
    rl = layout_lib.resolve(spec.layout, spec.canvas, (src_w, src_h), spec.delivery)
    if spec.pan is not None:
        # A GENERATED path: no route is read, and none is written. See
        # generate_pan_path for why it is neither smoothed nor rate-limited.
        path, times = generate_pan_path(spec.pan, rl.freedom, fps, dur, spec.max_speed)
        # no mean_y to place, so centre vertically (design §4.1)
        cy = max(0, (src_h - rl.crop_h) // 2)
    else:
        if route_path is None:
            raise ValueError(
                "reframe needs a route: route_path is None but spec.pan is None too, so "
                "there is no source for the crop's x(t). Pass a tracked route.json, or "
                "set spec.pan to generate the path instead")
        route = route_from_json(route_path)               # list[RoutePoint]
        if not route:
            raise ValueError(
                f"route {route_path} is empty — tracker found no hero frames; "
                "check route.meta.json (ambiguous? wrong seed pin?) before reframing")
        route_dicts = [p.to_dict() for p in route]        # compute_path/classify still take dicts
        motion = classify(route_dicts, src_w, src_h)
        path = compute_path(route_dicts, spec.composition, spec.grid, spec.canvas,
                            (src_w, src_h), motion, max_step=spec.max_speed / fps,
                            crop_w=rl.crop_w,
                            smooth_window=pathsmooth.window_frames(
                                spec.smooth_window_s, fps))
        times = [p.t for p in route]
        mean_y = sum(p.y for p in route) / len(route)
        cy = g.crop_y(mean_y, rl.crop_h, src_h)
    CropPath(path).to_json(path_out)

    gains = color.gains_for_means(spec.color_means)
    if spec.color_correct is not None:  # reel retry loop; see docstring
        gains = color.corrected(gains, spec.color_correct)
    wb = color.white_balance_arg(spec.color_means, spec.white_balance)
    tone = ""
    if spec.tone_src is not None:
        tone = color.tone_arg(tuple(spec.tone_src), tuple(spec.tone_dst))
        verify_tone(tone)      # a banding spline fails HERE, not in the delivered reel
    grade = color.grade_chain(gains, wb=wb, tone=tone, black_point=spec.black_point,
                              shadow_red=spec.shadow_red, mid_blue=spec.mid_blue,
                              saturation=spec.saturation, highlight=spec.highlight,
                              dip=spec.dip, dur=dur)
    xexpr = _xexpr(path, times)
    # `-t` pins the render to the source's length, and is the ONLY thing that does
    # (design §4). `color=:d=` alone leaves the overlay's output timebase mismatched
    # with the tail's `fps` filter: a 90-frame 3s clip came out 46080 frames / 1536s.
    # It fires whenever the emitted `r=` matches the source's rational rate exactly
    # — so on integer rates (24/25/30/50/60), NOT on the NTSC fixtures this repo
    # reaches for, which escape only because `{fps:.6g}` mangles 60000/1001.
    #
    # Applied to EVERY layout, not just solid: measured a no-op for fill and blur
    # (both already end with the source), and unconditional means no future filler
    # can forget it. That decision is pinned by a test — see
    # test_reframe_bounds_every_layout_to_the_source_length.
    cmd = [ffbin.ffmpeg(), "-y", "-i", src,
           *_filter_args(rl, xexpr, cy, grade, fps, dur),
           "-t", f"{dur:.6f}",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    proc.run(cmd)

    PathMeta(mode=rl.mode, crop_w=rl.crop_w, crop_h=rl.crop_h, crop_y=cy,
             src_dims=(src_w, src_h), canvas=spec.canvas, out_dims=(rl.out_w, rl.out_h),
             rect_px=rl.rect_px, freedom=rl.freedom, background=rl.background,
             pan=spec.pan is not None, stabilized=stabilized
             ).write(Path(path_out).with_suffix(".meta.json"))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("route", nargs="?", default=None)
    ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--canvas", default="9:16")
    ap.add_argument("--color", default="105,122,137")
    ap.add_argument("--delivery", default=None,
                    help="native (default) | short_edge:N | long_edge:N | exact:WxH")
    ap.add_argument("--layout", default="fill", help="fill | fit | insert")
    ap.add_argument("--crop-aspect", default=None, help="canvas | source | W:H")
    ap.add_argument("--crop-scale", type=float, default=1.0)
    ap.add_argument("--rect", default=None, help="insert only: x,y,w as canvas fractions")
    ap.add_argument("--background", default="blur",
                    help="blur | solid — the filler behind a fit/insert")
    ap.add_argument("--background-color", default="black",
                    help="solid only: ffmpeg colour name or hex")
    ap.add_argument("--border-px", type=int, default=0)
    ap.add_argument("--border-color", default="white")
    ap.add_argument("--path-out", required=True)
    ap.add_argument("--pan", default=None,
                    help="generated pan as FROM,TO — fractions of horizontal freedom "
                         "(e.g. 0,1 or 1,0 for right-to-left); replaces the route")
    a = ap.parse_args()
    cw, ch = (int(v) for v in a.canvas.split(":"))
    means = tuple(float(v) for v in a.color.split(","))
    aspect: str | tuple[int, int] = a.crop_aspect or ("canvas" if a.layout == "fill" else "source")
    if isinstance(aspect, str) and ":" in aspect:
        aw, ah = (int(v) for v in aspect.split(":"))
        aspect = (aw, ah)
    rect = tuple(float(v) for v in a.rect.split(",")) if a.rect else None
    lspec = LayoutSpec(mode=a.layout, crop_aspect=aspect, crop_scale=a.crop_scale, rect=rect,
                       background=a.background, background_color=a.background_color,
                       border_px=a.border_px, border_color=a.border_color)
    pan = None
    if a.pan is not None:
        pf, pt = (float(v) for v in a.pan.split(","))
        pan = PanSpec(start=pf, end=pt)
    spec = ReframeSpec(composition=a.composition, grid=a.grid, canvas=(cw, ch),
                       color_means=means, delivery=Delivery.from_spec(a.delivery),
                       layout=lspec, pan=pan)
    reframe(spec, a.src, a.route, a.out, a.path_out)
