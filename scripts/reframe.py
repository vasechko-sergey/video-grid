"""Compose one episode: route + rules → cropped/colored clip (spec §6)."""
import argparse, json
from pathlib import Path
from scripts.lib import geometry as g
from scripts.lib import pathsmooth, color, proc
from scripts.lib import layout as layout_lib
from scripts.lib.layout import ResolvedLayout
from scripts.lib.motion import classify
from scripts.lib.models import (ReframeSpec, CropPath, route_from_json, Delivery,
                                PathMeta, LayoutSpec)


def compute_path(route: list[dict[str, float]], composition: str, grid: str,
                 canvas: tuple[int, int], src: tuple[int, int],
                 motion: tuple[str, str | None], max_step: float,
                 crop_w: int) -> list[int]:
    # crop_w comes from the resolved layout — the caller already cut it; deriving
    # it from `canvas` here would be right only while every layout is `fill`.
    _, direction = motion if motion[0] == "lateral" else (motion[0], "right")
    if composition in ("center", "break") or motion[0] != "lateral":
        # center / head-on / static: aim crop centre at subject, no lead.
        # break (spec §6.2): tracked but relaxed — v1 center-tracks; extreme
        # framing is editorial territory, checks are editorial-only.
        raw = [g.clamp(round(pt["x"] - crop_w / 2), 0, src[0] - crop_w)
               for pt in route]
    else:
        raw = [g.crop_x(pt["x"], composition, direction, grid, crop_w, src[0])
               for pt in route]
    smoothed = pathsmooth.smooth(raw, max_step=max_step)
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame.
    # At zero freedom (crop_w == src_w) this clamps to a constant 0 — a
    # whole-frame layout has nowhere to travel, and needs no special case.
    return [int(g.clamp(round(x), 0, src[0] - crop_w)) for x in smoothed]


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


def _probe(src: str) -> tuple[int, int, float]:
    out = proc.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate",
         "-of", "json", src], text=True)
    s = json.loads(out.stdout)["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    fps = float(num) / (float(den) or 1.0)
    if fps <= 0:
        raise ValueError(
            f"{src}: probed fps is {fps} — corrupt/streamed source? re-encode it first")
    return int(s["width"]), int(s["height"]), fps


def _filter_args(rl: ResolvedLayout, xexpr: str, cy: int,
                 gains: tuple[float, ...], fps: float) -> list[str]:
    """The ffmpeg filter arguments for one layout.

    fill takes the fast path: one -vf chain, byte-identical to what this script
    emitted before layouts existed. That is not an optimization — it is how the
    golden fixture is protected from a silent change of command.
    """
    mixer = color.mixer_arg(*gains)
    tail = f"{mixer},fps={fps:.6g},format=yuv420p"
    if rl.fast_path:
        return ["-vf", (f"crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},"
                        f"scale={rl.out_w}:{rl.out_h},{tail}")]
    rx, ry, rw, rh = rl.rect_px          # the CONTENT rect; the border sits outside it
    b = rl.border_px
    ox, oy, ow, oh = rx - b, ry - b, rw + 2 * b, rh + 2 * b
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
    pad = f",pad={ow}:{oh}:{b}:{b}:{rl.border_color}" if b else ""
    return ["-filter_complex",
            (f"[0:v]split=2[a][b];"
             f"[a]scale={rl.out_w}:{rl.out_h}:force_original_aspect_ratio=increase,"
             f"crop={rl.out_w}:{rl.out_h},boxblur={radius}:2[bg];"
             f"[b]crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},scale={rw}:{rh}{pad}[fg];"
             f"[bg][fg]overlay={ox}:{oy},{tail}")]


def reframe(spec: ReframeSpec, src: str, route_path: str, out: str, path_out: str) -> str:
    """Compose one episode from a tracked route (spec §6): crop/scale/color per `spec`.

    spec: a ReframeSpec (scripts/lib/models.py) — composition/grid/canvas/color_means/
    delivery/layout/max_speed/color_correct. src/route_path/out/path_out stay explicit
    per-call I/O paths, not config. spec.max_speed: crop-x speed cap in px/sec — frame-rate
    independent (25 px/frame at the session's 30fps ≡ 750 px/s). spec.color_correct: an
    optional per-channel factor the reel retry loop composes onto the grade to pull one
    episode toward the reel median (None = base grade only). stabilize is refused
    upstream (manifest gate + ReframeSpec.__post_init__) — this function never sees it.

    Writes `out` (the clip), `path_out` (the crop path) and `path_out`'s `.meta.json`
    sidecar — what was actually cut, for check_episode/storyboard to read back instead
    of re-deriving the crop from the canvas (silently wrong under a non-fill layout).
    """
    src_w, src_h, fps = _probe(src)   # NEVER assume dims/fps: real footage is 4K/60
    route = route_from_json(route_path)               # list[RoutePoint]
    if not route:
        raise ValueError(
            f"route {route_path} is empty — tracker found no hero frames; "
            "check route.meta.json (ambiguous? wrong seed pin?) before reframing")
    rl = layout_lib.resolve(spec.layout, spec.canvas, (src_w, src_h), spec.delivery)
    route_dicts = [p.to_dict() for p in route]        # compute_path/classify still take dicts
    motion = classify(route_dicts, src_w, src_h)
    path = compute_path(route_dicts, spec.composition, spec.grid, spec.canvas,
                        (src_w, src_h), motion, max_step=spec.max_speed / fps,
                        crop_w=rl.crop_w)
    CropPath(path).to_json(path_out)

    gains = color.gains_for_means(spec.color_means)
    if spec.color_correct is not None:  # reel retry loop; see docstring
        gains = color.corrected(gains, spec.color_correct)
    times = [p.t for p in route]
    xexpr = _xexpr(path, times)
    mean_y = sum(p.y for p in route) / len(route)
    cy = g.crop_y(mean_y, rl.crop_h, src_h)
    cmd = ["ffmpeg", "-y", "-i", src,
           *_filter_args(rl, xexpr, cy, gains, fps),
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    proc.run(cmd)

    PathMeta(mode=rl.mode, crop_w=rl.crop_w, crop_h=rl.crop_h, crop_y=cy,
             src_dims=(src_w, src_h), canvas=spec.canvas, out_dims=(rl.out_w, rl.out_h),
             rect_px=rl.rect_px, freedom=rl.freedom
             ).write(Path(path_out).with_suffix(".meta.json"))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("route"); ap.add_argument("out")
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
    spec = ReframeSpec(composition=a.composition, grid=a.grid, canvas=(cw, ch),
                       color_means=means, delivery=Delivery.from_spec(a.delivery),
                       layout=lspec)
    reframe(spec, a.src, a.route, a.out, a.path_out)
