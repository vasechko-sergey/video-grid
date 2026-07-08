"""Run mechanical episode checks → report.json (spec §9, §4.1)."""
import argparse
from pathlib import Path
from scripts.lib import checks as checks_mod, geometry, proc
from scripts.lib.models import CheckResult, CheckSpec, Report, route_from_json, CropPath
from scripts.lib.motion import classify


def _duration(clip):
    out = proc.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", clip], text=True)
    return float(out.stdout.strip())


def _frame_lumas(clip, where, n=3):
    """Mean luma of n frames at 'boundary' (head+tail) or 'body' (interior)."""
    import tempfile
    from PIL import Image, ImageStat
    lumas = []
    with tempfile.TemporaryDirectory() as tmp:
        if where == "boundary":
            proc.run(["ffmpeg", "-y", "-i", clip, "-frames:v", str(n), f"{tmp}/head%02d.png"])
            proc.run(["ffmpeg", "-y", "-sseof", "-0.5", "-i", clip, f"{tmp}/tail%02d.png"])
            files = sorted(Path(tmp).glob("head*.png")) + sorted(Path(tmp).glob("tail*.png"))[-n:]
        else:  # body: sample the interior via an even fps grab, drop the extremes
            # fps normalized to the clip's own duration so the n+2 grabs land
            # spread across the WHOLE clip — fps=(n+2)/1 would instead cap at
            # -frames:v and only ever sample the first ~1s, letting a leading
            # defect (e.g. a black lead-in) contaminate the body reference itself
            dur = max(_duration(clip), 0.001)
            proc.run(["ffmpeg", "-y", "-i", clip, "-vf", f"fps={n + 2}/{dur}",
                      "-frames:v", str(n + 2), f"{tmp}/b%02d.png"])
            files = sorted(Path(tmp).glob("b*.png"))[1:-1]
        for f in files:
            lumas.append(ImageStat.Stat(Image.open(f).convert("L")).mean[0])
    return lumas


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _black_frames_check(clip, black_floor=6.0, black_rel=0.35):
    """Spec §9: boundary-only — the seek landmine bites at cut edges. Bug #3:
    the gate is now RELATIVE to the clip body, not an absolute floor — a
    boundary frame is a defect only if it's BOTH near-black AND far below the
    clip's own median luma, so a legitimately dark/night clip still passes."""
    boundary = _frame_lumas(clip, "boundary")
    body = _frame_lumas(clip, "body") or boundary
    ref = _median(body)
    worst = min(boundary) if boundary else ref
    is_black = worst < black_floor and worst < black_rel * ref
    return {"pass": not is_black, "boundary_lumas": [round(l, 1) for l in boundary],
            "body_median": round(ref, 1)}


def run(clip, route_path, path_path, spec, out):
    """crop_w derives from canvas+src; direction from the route itself —
    no hardcoded 607 / "right" (left-moving and non-9:16 episodes exist)."""
    route = [p.to_dict() for p in route_from_json(route_path)]
    path = CropPath.from_json(path_path).xs
    crop_w, _ = geometry.crop_size(spec.canvas[0], spec.canvas[1],
                                   spec.src_dims[0], spec.src_dims[1])
    _, direction = classify(route, spec.src_dims[0], spec.src_dims[1])
    # static/head-on routes have no direction; "right" is an arbitrary but
    # deterministic default for the lead-line pick (spec has no answer here —
    # a lead composition over non-lateral motion is already a soft mismatch)
    direction = direction or "right"
    checks = {}

    if spec.composition == "center":
        d = checks_mod.centered(route, path, crop_w)
        checks["centered"] = CheckResult("centered", d["pass"], {k: v for k, v in d.items() if k != "pass"})
    elif spec.composition == "lead":
        left, right = geometry.grid_lines(spec.grid)
        tf = left if direction == "right" else right
        d = checks_mod.on_line(route, path, crop_w, tf)
        checks["on_line"] = CheckResult("on_line", d["pass"], {k: v for k, v in d.items() if k != "pass"})
    elif spec.composition == "break":
        # spec §6.2: break is tracked but relaxed — postcheck editorial only,
        # no numeric fail; passed=None so it can't fail `overall`
        checks["framing"] = CheckResult("framing", None, {"status": "editorial-only"})
    else:
        raise ValueError(f"unknown composition: {spec.composition!r}")

    dj = checks_mod.jitter(path, direction, max_reversal=max(2.0, crop_w * 0.005))
    checks["jitter"] = CheckResult("jitter", dj["pass"], {k: v for k, v in dj.items() if k != "pass"})
    dc = checks_mod.continuity(route, spec.src_dims[0])
    checks["continuity"] = CheckResult("continuity", dc["pass"], {k: v for k, v in dc.items() if k != "pass"})
    dl = checks_mod.length(_duration(clip), spec.target_dur)
    checks["length"] = CheckResult("length", dl["pass"], {k: v for k, v in dl.items() if k != "pass"})
    bf = _black_frames_check(clip, black_floor=spec.black_floor, black_rel=spec.black_rel)
    checks["black_frames"] = CheckResult("black_frames", bf["pass"], {k: v for k, v in bf.items() if k != "pass"})
    # spec'd but not yet implementable (§9): report honestly, never silent-pass
    checks["horizon"] = CheckResult("horizon", None, {"status": "not-implemented"})
    checks["head_power_point"] = CheckResult("head_power_point", None, {"status": "not-implemented"})

    report = Report(checks=checks, attempt=spec.attempt)
    report.write(out)
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
    spec = CheckSpec(composition=a.composition, grid=a.grid, target_dur=a.target_dur,
                     canvas=(cw, ch), src_dims=(sw, sh), attempt=a.attempt)
    run(a.clip, a.route, a.path, spec, a.out)
