"""Compose one episode: route + rules → cropped/colored clip (spec §6)."""
import argparse, json
from scripts.lib import geometry as g
from scripts.lib import pathsmooth, color, proc
from scripts.lib.motion import classify
from scripts.lib.models import ReframeSpec, RoutePoint, CropPath, route_from_json, Delivery


def compute_path(route, composition, grid, canvas, src, motion, max_step):
    crop_w, _ = g.crop_size(canvas[0], canvas[1], src[0], src[1])
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
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame
    return [int(g.clamp(round(x), 0, src[0] - crop_w)) for x in smoothed]


def _simplify(path, times, eps=2.0, max_knots=80):
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
    def run(eps):
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


def _xexpr(path, times):
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


def _probe(src):
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


def reframe(spec, src, route_path, out, path_out):
    """Compose one episode from a tracked route (spec §6): crop/scale/color per `spec`.

    spec: a ReframeSpec (scripts/lib/models.py) — composition/grid/canvas/color_means/
    delivery/max_speed. src/route_path/out/path_out stay explicit per-call I/O paths,
    not config. spec.max_speed: crop-x speed cap in px/sec — frame-rate independent
    (25 px/frame at the session's 30fps ≡ 750 px/s). stabilize is refused upstream
    (manifest gate + ReframeSpec.__post_init__) — this function never sees it.
    """
    src_w, src_h, fps = _probe(src)   # NEVER assume dims/fps: real footage is 4K/60
    route = route_from_json(route_path)               # list[RoutePoint]
    if not route:
        raise ValueError(
            f"route {route_path} is empty — tracker found no hero frames; "
            "check route.meta.json (ambiguous? wrong seed pin?) before reframing")
    route_dicts = [p.to_dict() for p in route]        # compute_path/classify still take dicts
    motion = classify(route_dicts, src_w, src_h)
    path = compute_path(route_dicts, spec.composition, spec.grid, spec.canvas,
                        (src_w, src_h), motion, max_step=spec.max_speed / fps)
    CropPath(path).to_json(path_out)

    crop_w, crop_h = g.crop_size(spec.canvas[0], spec.canvas[1], src_w, src_h)
    out_w, out_h = spec.delivery.dims(crop_w, crop_h)      # #F: was hardcoded 1080x1920
    rr, gg, bb = color.gains_for_means(spec.color_means)
    times = [p.t for p in route]
    xexpr = _xexpr(path, times)
    mean_y = sum(p.y for p in route) / len(route)
    cy = g.crop_y(mean_y, crop_h, src_h)
    vf = (f"crop={crop_w}:{crop_h}:x='{xexpr}':y={cy},"
          f"scale={out_w}:{out_h},{color.mixer_arg(rr, gg, bb)},"
          f"fps={fps:.6g},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    proc.run(cmd)
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
    ap.add_argument("--path-out", required=True)
    a = ap.parse_args()
    cw, ch = (int(v) for v in a.canvas.split(":"))
    means = tuple(float(v) for v in a.color.split(","))
    spec = ReframeSpec(composition=a.composition, grid=a.grid, canvas=(cw, ch),
                       color_means=means, delivery=Delivery.from_spec(a.delivery))
    reframe(spec, a.src, a.route, a.out, a.path_out)
