"""Contact sheet with grid overlays for verification/editorial (spec §6.1)."""
import argparse, json, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.lib.geometry import grid_lines
from scripts.lib import proc
from scripts.lib.models import StoryboardSpec, RoutePoint, CropPath, PathMeta


def _duration(src: str) -> float:
    r = proc.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", src], text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def _sample_times(dur: float, n: int) -> list[float]:
    return [(k + 0.5) * dur / n for k in range(n)]


def _sample_frames(src: str, n: int, tmp: str, times: list[float]) -> list[Path]:
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


def _overlay(img: Image.Image, grids: tuple[str, ...],
             mark: tuple[float, float] | None = None) -> Image.Image:
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


def _interp(ts: list[float], xs: list[float], t: float) -> float:
    if t <= ts[0]:
        return xs[0]
    if t >= ts[-1]:
        return xs[-1]
    for i in range(1, len(ts)):
        if t <= ts[i]:
            f = (t - ts[i - 1]) / (ts[i] - ts[i - 1]) if ts[i] != ts[i - 1] else 0.0
            return xs[i - 1] + f * (xs[i] - xs[i - 1])
    return xs[-1]


def marks_at_times(route: list[RoutePoint], path: CropPath, meta: PathMeta,
                   times: list[float]) -> list[tuple[float, float]]:
    """(fx, fy) subject fractions in the OUTPUT frame at each sample TIME.

    The crop is placed inside `meta.rect_px`, which for `fill` is the whole
    output — so this reduces to the old (x - cx) / crop_w there, and stays
    correct when the crop is a card in a larger canvas. fy divides by crop_h
    and honours meta.crop_y, so a canvas with vertical freedom maps right too.

    Route x/y and crop-x are interpolated on t so the marks align with the
    frames storyboard samples BY TIME (fixes index/time desync on a gappy
    route, #4)."""
    if not route or len(route) != len(path):
        raise ValueError(f"route/path must be non-empty parallel arrays, "
                         f"got {len(route)} vs {len(path)}")
    ts = [p.t for p in route]
    xs = [p.x for p in route]
    ys = [p.y for p in route]
    cxs = path.xs
    rx, ry, rw, rh = meta.rect_px
    out_w, out_h = meta.out_dims
    marks = []
    for t in times:
        x = _interp(ts, xs, t)
        y = _interp(ts, ys, t)
        cx = _interp(ts, cxs, t)
        fx = (rx + rw * (x - cx) / meta.crop_w) / out_w
        fy = (ry + rh * (y - meta.crop_y) / meta.crop_h) / out_h
        marks.append((fx, fy))
    return marks


def build(src: str, out: str, spec: StoryboardSpec, route: list[RoutePoint] | None = None,
          path: CropPath | None = None, meta: PathMeta | None = None) -> tuple[str, list[float]]:
    """Contact sheet + grid/hero-mark overlays (spec §6.1). `spec` is a
    StoryboardSpec (n, grids, marks). When route/path/meta are ALL given, marks
    are computed at the SAME sample times as the frames (fixes #4 — the old
    index-sampled marker could drift onto the wrong frame on a gappy route) and
    mapped into canvas coords via meta.rect_px; otherwise spec.marks (if any) is
    used positionally.
    Returns (out, times) — times lets the caller reuse the exact sample points."""
    dur = _duration(src)
    times = _sample_times(dur, spec.n)
    marks = spec.marks
    if None not in (route, path, meta):
        marks = marks_at_times(route, path, meta, times)
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
