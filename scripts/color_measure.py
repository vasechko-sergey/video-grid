"""Measure a clip's (p5, p50, p95) luma — the authoring aid for ReframeSpec.tone
(design 2026-07-26 §5). Pure percentile math lives in color.percentiles; this driver
only produces the histogram from a decoded still."""
import argparse
import numpy as np
from scripts.lib import color, ffbin, proc


def measure_profile(clip: str, at: float | None = None) -> tuple[float, float, float]:
    """(p5, p50, p95) luma of `clip` at time `at` (default: 1s in — a settled frame).

    Decodes ONE grayscale still at the clip's OWN resolution, histograms it, and
    delegates the percentiles to color.percentiles (numpy stays in this driver, out of
    lib/color).

    Not downscaled, and that is measured (design 2026-08-19 §1): `scale=160:-2` reduced
    the area 12x and read the run's drone frame's p95 NINE UNITS LOW — 196 against the
    frame's real 205 — because specular highlights are small and bright and averaging is
    what a downscale does. p5 and p50 are bulk statistics and did not move at all. The
    full frame costs 66.9ms against 61.0ms for 144x the samples: the decode was always
    the price and the scale filter never was."""
    t = 1.0 if at is None else at
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", clip, "-ss", f"{t:.3f}",
                    "-frames:v", "1", "-vf", "format=gray",
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout      # -ss AFTER -i (§12)
    if not out:
        raise RuntimeError(f"color_measure: no frame decoded from {clip} at {t:.2f}s")
    hist = np.bincount(np.frombuffer(out, dtype=np.uint8), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def main() -> None:
    ap = argparse.ArgumentParser(description="measure a clip's (p5,p50,p95) luma for ReframeSpec.tone")
    ap.add_argument("clip")
    ap.add_argument("--at", type=float, default=None, help="sample time in seconds (default 1.0)")
    a = ap.parse_args()
    p5, p50, p95 = measure_profile(a.clip, a.at)
    print(f"p5={p5:.1f} p50={p50:.1f} p95={p95:.1f}")
    print(f'tone_src: [{p5:.0f}, {p50:.0f}, {p95:.0f}]')


if __name__ == "__main__":
    main()
