"""Contact sheet with grid overlays for verification/editorial (spec §6.1)."""
import argparse, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.lib.geometry import grid_lines


def _duration(src):
    import json as _j
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", src], capture_output=True, text=True, check=True)
    return float(_j.loads(r.stdout)["format"]["duration"])


def _sample_frames(src, n, tmp):
    rate = max(1, n) / max(0.001, _duration(src))
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-vf", f"fps={rate}",
         "-frames:v", str(n), f"{tmp}/f%02d.png"],
        check=True, capture_output=True)
    return sorted(Path(tmp).glob("f*.png"))


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


def build(src, out, n=8, grids=("thirds",), marks=None):
    """marks: optional per-sampled-frame (fx, fy) subject fractions in the
    OUTPUT frame — the caller derives them from route+path ((x-crop_x)/crop_w).
    The editorial gate then confirms "right person" at a glance."""
    with tempfile.TemporaryDirectory() as tmp:
        frames = _sample_frames(src, n, tmp)
        imgs = [_overlay(Image.open(f).convert("RGB"), grids,
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
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--grids", default="thirds,phi")
    a = ap.parse_args()
    build(a.src, a.out, a.n, tuple(a.grids.split(",")))
