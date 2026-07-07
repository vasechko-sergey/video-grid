"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse, json
from pathlib import Path
from scripts.lib import checks, geometry, proc
from scripts.lib.motion import classify


def _duration(clip):
    out = proc.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", clip], text=True)
    return float(out.stdout.strip())


def _boundary_luma(clip, n_frames=3):
    """Mean luma of the first/last n frames (spec §9: black-frame check is
    boundary-only — the seek landmine bites at cut edges; a dark mid-shot
    is legitimate footage, not a defect)."""
    import tempfile
    from PIL import Image, ImageStat
    lumas = []
    with tempfile.TemporaryDirectory() as tmp:
        proc.run(["ffmpeg", "-y", "-i", clip, "-frames:v", str(n_frames),
                  f"{tmp}/head%02d.png"])
        proc.run(["ffmpeg", "-y", "-sseof", "-0.5", "-i", clip,
                  f"{tmp}/tail%02d.png"])
        heads = sorted(Path(tmp).glob("head*.png"))
        tails = sorted(Path(tmp).glob("tail*.png"))[-n_frames:]
        for f in heads + tails:
            lumas.append(ImageStat.Stat(Image.open(f).convert("L")).mean[0])
    return lumas


def run(clip, route_path, path_path, composition, grid, target_dur, out,
        canvas=(9, 16), src_dims=(1920, 1080), attempt=1):
    """crop_w derives from canvas+src; direction from the route itself —
    no hardcoded 607 / "right" (left-moving and non-9:16 episodes exist)."""
    route = json.loads(Path(route_path).read_text())
    path = json.loads(Path(path_path).read_text())
    crop_w, _ = geometry.crop_size(canvas[0], canvas[1], src_dims[0], src_dims[1])
    _, direction = classify(route, src_dims[0], src_dims[1])
    # static/head-on routes have no direction; "right" is an arbitrary but
    # deterministic default for the lead-line pick (spec has no answer here —
    # a lead composition over non-lateral motion is already a soft mismatch)
    direction = direction or "right"
    results = {}

    if composition == "center":
        results["centered"] = checks.centered(route, path, crop_w)
    elif composition == "lead":
        left, right = geometry.grid_lines(grid)
        tf = left if direction == "right" else right
        results["on_line"] = checks.on_line(route, path, crop_w, tf)
    elif composition == "break":
        # spec §6.2: break is tracked but relaxed — postcheck editorial only,
        # no numeric fail; no "pass" key so it can't fail `overall`
        results["framing"] = {"status": "editorial-only"}
    else:
        raise ValueError(f"unknown composition: {composition!r} — expected lead/center/break")
    results["jitter"] = checks.jitter(path, direction,
                                      max_reversal=max(2.0, crop_w * 0.005))
    results["continuity"] = checks.continuity(route, src_dims[0])
    results["length"] = checks.length(_duration(clip), target_dur)
    lumas = _boundary_luma(clip)
    results["black_frames"] = {"pass": all(l > 8 for l in lumas),
                               "boundary_lumas": [round(l, 1) for l in lumas]}
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
