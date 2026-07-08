"""Contact sheet with grid overlays for verification/editorial (spec §6.1)."""
import argparse, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.lib.geometry import grid_lines
from scripts.lib import proc
from scripts.lib.models import StoryboardSpec


def _duration(src):
    import json as _j
    r = proc.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", src], text=True)
    return float(_j.loads(r.stdout)["format"]["duration"])


def _sample_times(dur, n):
    return [(k + 0.5) * dur / n for k in range(n)]


def _sample_frames(src, n, tmp, times):
    # one still per explicit TIME — input-side -ss is a fast, keyframe-near
    # seek (fine for a preview thumbnail; the design §12 "-ss after -i"
    # landmine is about black frames on a CUT/re-encode boundary, not about
    # grabbing a single still deep inside a clip). n kept for call-site
    # symmetry; times already fixes the count.
    files = []
    for i, t in enumerate(times):
        f = f"{tmp}/f{i:02d}.png"
        proc.run(["ffmpeg", "-y", "-ss", f"{t}", "-i", src, "-frames:v", "1", f])
        files.append(Path(f))
    return files


def _overlay(img, grids, mark=None):
    d = ImageDraw.Draw(img); w, h = img.size
    palette = {"thirds": (0, 255, 255), "phi": (255, 128, 0)}
    for grid in grids:
        left, right = grid_lines(grid)
        for fx in (left, right):
            d.line([(fx * w, 0), (fx * w, h)], fill=palette.get(grid), width=2)
        for fy in (left, right):   # horizontals at the grid's OWN fractions (phi != 1/3)
            d.line([(0, fy * h), (w, fy * h)], fill=palette.get(grid), width=1)
    if mark is not None:           # hero marker (spec §6.1a): (fx, fy) fractions
        mx, my, r = mark[0] * w, mark[1] * h, max(6, w // 60)
        d.ellipse([mx - r, my - r, mx + r, my + r], outline=(0, 255, 0), width=3)
    return img


def _interp(ts, xs, t):
    if t <= ts[0]:
        return xs[0]
    if t >= ts[-1]:
        return xs[-1]
    for i in range(1, len(ts)):
        if t <= ts[i]:
            f = (t - ts[i - 1]) / (ts[i] - ts[i - 1]) if ts[i] != ts[i - 1] else 0.0
            return xs[i - 1] + f * (xs[i] - xs[i - 1])
    return xs[-1]


def marks_at_times(route, path, crop_w, src_h, times):
    """(fx, fy) subject fractions in the OUTPUT frame at each sample TIME —
    interpolate route x/y and crop-x on t, so marks align with the frames
    storyboard samples by time (fixes index/time desync on gappy routes, #4)."""
    if not route or len(route) != len(path):
        raise ValueError(f"route/path must be non-empty parallel arrays, "
                         f"got {len(route)} vs {len(path)}")
    ts = [p.t for p in route]
    xs = [p.x for p in route]
    ys = [p.y for p in route]
    cxs = path.xs
    marks = []
    for t in times:
        x = _interp(ts, xs, t)
        y = _interp(ts, ys, t)
        cx = _interp(ts, cxs, t)
        marks.append(((x - cx) / crop_w, y / src_h))
    return marks


def build(src, out, spec, route=None, path=None, crop_w=None, src_h=None):
    """Contact sheet + grid/hero-mark overlays (spec §6.1). `spec` is a
    StoryboardSpec (n, grids, marks). When route/path/crop_w/src_h are ALL
    given, marks are computed at the SAME sample times as the frames (fixes
    #4 — the old index-sampled marker could drift onto the wrong frame on a
    gappy route); otherwise spec.marks (if any) is used positionally.
    Returns (out, times) — times lets the caller reuse the exact sample points."""
    dur = _duration(src)
    times = _sample_times(dur, spec.n)
    marks = spec.marks
    if None not in (route, path, crop_w, src_h):
        marks = marks_at_times(route, path, crop_w, src_h, times)
    with tempfile.TemporaryDirectory() as tmp:
        frames = _sample_frames(src, spec.n, tmp, times)
        imgs = [_overlay(Image.open(f).convert("RGB"), spec.grids,
                         mark=(marks[i] if marks and i < len(marks) else None))
                for i, f in enumerate(frames)]
        if not imgs:
            raise RuntimeError("no frames sampled")
        cols = min(len(imgs), 4)
        rows = (len(imgs) + cols - 1) // cols
        tw, th = imgs[0].size
        sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
        for i, im in enumerate(imgs):
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
        sheet.save(out, quality=90)
    return out, times


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--grids", default="thirds,phi")
    a = ap.parse_args()
    spec = StoryboardSpec(n=a.n, grids=tuple(a.grids.split(",")))
    build(a.src, a.out, spec)
