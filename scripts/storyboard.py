"""Contact sheet with grid overlays for verification/editorial (spec §6.1)."""
import argparse, json, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.lib.geometry import grid_lines, marks_at_times
from scripts.lib import ffbin, proc
from scripts.lib.models import StoryboardSpec, RoutePoint, CropPath, PathMeta


def _duration(src: str) -> float:
    r = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", src], text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def _sample_times(dur: float, n: int) -> list[float]:
    return [(k + 0.5) * dur / n for k in range(n)]


def _sample_frames(src: str, n: int, tmp: str, times: list[float]) -> list[Path]:
    # one still per explicit TIME. Input-side -ss is the fast seek, but it is NOT
    # keyframe-approximate: ffmpeg's accurate_seek is on by default, so it lands on
    # the keyframe and then decodes forward to the exact timestamp. Verified against
    # the golden fixture, which carries a single keyframe — a keyframe-near seek
    # would return frame 0 for every t, and the hero marks (drawn from the route at
    # time t) would sit on the wrong frame entirely. They do not: input-seek and
    # output-seek produce byte-identical stills at t = 0.4, 0.75, 1.2.
    #
    # The design §12 "-ss after -i" landmine is a different failure: black frames at
    # a CUT/re-encode boundary. Grabbing one still deep inside a clip is not a cut.
    # n kept for call-site symmetry; times already fixes the count.
    files = []
    for i, t in enumerate(times):
        f = f"{tmp}/f{i:02d}.png"
        proc.run([ffbin.ffmpeg(), "-y", "-ss", f"{t}", "-i", src, "-frames:v", "1", f])
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
