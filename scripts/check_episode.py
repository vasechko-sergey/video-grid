"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse, json, subprocess, re
from pathlib import Path
from scripts.lib import checks, geometry
from scripts.lib.motion import classify


def _duration(clip):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", clip], capture_output=True, text=True,
        check=True)
    return float(out.stdout.strip())


def _black_frames(clip):
    out = subprocess.run(
        ["ffmpeg", "-i", clip, "-vf", "blackdetect=d=0.05:pic_th=0.98",
         "-an", "-f", "null", "-"], capture_output=True, text=True)
    return len(re.findall(r"black_start", out.stderr))


def run(clip, route_path, path_path, composition, grid, target_dur, out,
        canvas=(9, 16), src_dims=(1920, 1080), attempt=1):
    """crop_w derives from canvas+src; direction from the route itself —
    no hardcoded 607 / "right" (left-moving and non-9:16 episodes exist)."""
    route = json.loads(Path(route_path).read_text())
    path = json.loads(Path(path_path).read_text())
    crop_w, _ = geometry.crop_size(canvas[0], canvas[1], src_dims[0], src_dims[1])
    _, direction = classify(route, src_dims[0], src_dims[1])
    direction = direction or "right"
    results = {}

    if composition == "center":
        results["centered"] = checks.centered(route, path, crop_w)
    elif composition == "lead":
        left, right = geometry.grid_lines(grid)
        tf = left if direction == "right" else right
        results["on_line"] = checks.on_line(route, path, crop_w, tf)
    results["jitter"] = checks.jitter(path, direction,
                                      max_reversal=max(2.0, crop_w * 0.005))
    results["continuity"] = checks.continuity(route, src_dims[0])
    results["length"] = checks.length(_duration(clip), target_dur)
    results["black_frames"] = {"pass": _black_frames(clip) == 0}
    # spec'd but not yet implementable (§9): report honestly, never silent-pass
    results["horizon"] = {"status": "not-implemented"}
    results["head_power_point"] = {"status": "not-implemented"}

    overall = all(v.get("pass", True) for v in results.values())
    fail_reasons = [k for k, v in results.items() if v.get("pass") is False]
    report = {"checks": results, "overall": overall,
              "attempt": attempt, "fail_reasons": fail_reasons}
    Path(out).write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("route"); ap.add_argument("path")
    ap.add_argument("out")
    ap.add_argument("--composition", default="lead")
    ap.add_argument("--grid", default="thirds")
    ap.add_argument("--target-dur", type=float, required=True)
    ap.add_argument("--canvas", default="9:16")
    ap.add_argument("--src-dims", default="1920x1080",
                    help="source WxH the route coords live in")
    ap.add_argument("--attempt", type=int, default=1)
    a = ap.parse_args()
    cw, ch = (int(v) for v in a.canvas.split(":"))
    sw, sh = (int(v) for v in a.src_dims.split("x"))
    run(a.clip, a.route, a.path, a.composition, a.grid, a.target_dur, a.out,
        canvas=(cw, ch), src_dims=(sw, sh), attempt=a.attempt)
