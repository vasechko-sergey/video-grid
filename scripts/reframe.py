"""Compose one episode: route + rules → cropped/colored clip (spec §6)."""
import argparse, json, subprocess
from pathlib import Path
from scripts.lib import geometry as g
from scripts.lib import pathsmooth, color
from scripts.lib.motion import classify


def compute_path(route, composition, grid, canvas, src, motion, max_step):
    crop_w, _ = g.crop_size(canvas[0], canvas[1], src[0], src[1])
    _, direction = motion if motion[0] == "lateral" else (motion[0], "right")
    raw = [g.crop_x(pt["x"], composition, direction, grid, crop_w, src[0])
           for pt in route]
    if composition == "center" or motion[0] != "lateral":
        # center / head-on / static: aim crop centre at subject, no lead
        raw = [g.clamp(round(pt["x"] - crop_w / 2), 0, src[0] - crop_w)
               for pt in route]
    smoothed = pathsmooth.smooth(raw, max_step=max_step)
    # clamp AFTER smoothing: savgol overshoots on ramps and can leave the frame
    return [int(g.clamp(round(x), 0, src[0] - crop_w)) for x in smoothed]


def _simplify(path, fps, eps=2.0):
    """Douglas-Peucker over (t, x): per-frame path → a few linear knots.

    Keeps the crop expression short (nested per-frame if() hits ffmpeg's
    expression parser limits on 60fps clips) and makes motion piecewise-linear
    — smoother than piecewise-constant per-frame steps.
    """
    pts = [(i / fps, float(x)) for i, x in enumerate(path)]

    def dp(lo, hi):
        if hi - lo < 2:
            return []
        (t0, x0), (t1, x1) = pts[lo], pts[hi]
        worst, wi = 0.0, None
        for i in range(lo + 1, hi):
            t, x = pts[i]
            xh = x0 + (x1 - x0) * ((t - t0) / (t1 - t0))
            if abs(x - xh) > worst:
                worst, wi = abs(x - xh), i
        if worst <= eps:
            return []
        return dp(lo, wi) + [wi] + dp(wi, hi)

    keep = sorted(set([0] + dp(0, len(pts) - 1) + [len(pts) - 1]))
    return [pts[i] for i in keep]


def _xexpr(path, fps):
    # piecewise-LINEAR x(t) over simplified knots: lerp inside each segment
    knots = _simplify(path, fps)
    if len(knots) == 1:
        return f"{knots[0][1]:.1f}"
    expr = f"{knots[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in zip(knots[-2::-1], knots[:0:-1]):
        slope = (x1 - x0) / max(1e-9, t1 - t0)
        seg = f"({x0:.1f}+({slope:.3f})*(t-{t0:.4f}))"
        expr = f"if(lt(t,{t1:.4f}),{seg},{expr})"
    return expr


def _probe(src):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate",
         "-of", "json", src], capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / (float(den) or 1.0)


def reframe(src, route_path, out, composition, grid, canvas,
            color_means, stabilize, path_out, max_speed=750.0):
    """max_speed: crop-x speed cap in px/sec — frame-rate independent
    (25 px/frame at the session's 30fps ≡ 750 px/s)."""
    src_w, src_h, fps = _probe(src)   # NEVER assume dims/fps: real footage is 4K/60
    src_dims = (src_w, src_h)
    route = json.loads(Path(route_path).read_text())
    motion = classify(route, src_w, src_h)
    path = compute_path(route, composition, grid, canvas, src_dims, motion,
                        max_step=max_speed / fps)
    Path(path_out).write_text(json.dumps(path))

    crop_w, crop_h = g.crop_size(canvas[0], canvas[1], src_w, src_h)
    out_w = 1080 if canvas == (9, 16) else crop_w
    out_h = 1920 if canvas == (9, 16) else crop_h
    rr, gg, bb = color.gains_for_means(color_means)
    xexpr = _xexpr(path, fps)
    vf = (f"crop={crop_w}:{crop_h}:x='{xexpr}':y=0,"
          f"scale={out_w}:{out_h},{color.mixer_arg(rr, gg, bb)},"
          f"fps={fps:.6g},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("route"); ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--canvas", default="9:16")
    ap.add_argument("--color", default="105,122,137")
    ap.add_argument("--stabilize", action="store_true")
    ap.add_argument("--path-out", required=True)
    a = ap.parse_args()
    cw, ch = (int(v) for v in a.canvas.split(":"))
    means = tuple(float(v) for v in a.color.split(","))
    reframe(a.src, a.route, a.out, a.composition, a.grid, (cw, ch),
            means, a.stabilize, a.path_out)
