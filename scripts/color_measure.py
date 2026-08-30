"""Measure a clip's (p5, p50, p95) luma — the authoring aid for ReframeSpec.tone
(design 2026-07-26 §5). Pure percentile math lives in color.percentiles; this driver
only produces the histogram from a decoded still."""
import argparse
import numpy as np
from scripts import process_episode, reframe
from scripts.lib import assembly, color, ffbin, proc
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.models import Delivery


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


FRAMES = 3          # start / middle / end of a span, at (i+0.5)/N — never the first
                    # or last frame, which a dip or a bookend can own. Measured
                    # (design 2026-08-30 §0.4): 5 and 9 frames give the same residual
                    # median and a slightly worse maximum, because the residual is not
                    # sampling noise.


def sample_times(dur: float, frames: int = FRAMES) -> list[float]:
    """`frames` sample times spread over `dur`, at (k+0.5)/frames of it."""
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"frames must be an integer >= 1, got {frames!r}")
    return [((k + 0.5) / frames) * dur for k in range(frames)]


def _select(times: list[float], fps: float) -> str:
    nums = [round(t * fps) for t in times]
    return "select='" + "+".join(rf"eq(n\,{n})" for n in nums) + "'"


def _percentiles_from_gray(raw: bytes, want: int, where: str) -> tuple[float, float, float]:
    """(p5, p50, p95) of a pooled gray rawvideo buffer — the ONE ruler.

    Pooled, not averaged per frame: the three frames describe one distribution,
    which is what a tone profile is. `want` frames are demanded so a select that
    silently returned fewer fails here instead of reporting a profile of whatever
    arrived (§12's select landmine, in the form it takes when nothing crashes)."""
    if not raw:
        raise RuntimeError(f"{where}: ffmpeg decoded no frames")
    if len(raw) % want:
        raise RuntimeError(f"{where}: {len(raw)} bytes is not divisible by the "
                           f"{want} frames requested — a frame is missing or "
                           f"duplicated; check the select expression's position")
    hist = np.bincount(np.frombuffer(raw, dtype=np.uint8), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def clip_percentiles(clip: str, times: list[float]) -> tuple[float, float, float]:
    """The ruler over a FINISHED file — what check_reel reads off the master."""
    info = assembly.probe_stream(clip)
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", clip,
                    "-vf", f"{_select(times, info.fps)},format=gray",
                    "-vsync", "0", "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    return _percentiles_from_gray(out, len(times), f"clip_percentiles({clip})")


def crop_percentiles(plan: "reframe.RenderPlan", src: str,
                     times: list[float]) -> tuple[float, float, float]:
    """The ruler over the pixels a RenderPlan would encode — the crop, scaled to
    the delivery, with whatever colour the plan carries. The select is appended at
    the END through with_tail: before the chain's own `fps=` it would emit one
    frame N times (§12)."""
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src,
                    *plan.with_tail(f"{_select(times, plan.fps)},format=gray"),
                    "-t", f"{plan.dur:.6f}", "-vsync", "0",
                    "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    return _percentiles_from_gray(out, len(times), f"crop_percentiles({src})")


def plan_ungraded(manifest_dict: dict, src: str,
                  route: str | None) -> "reframe.RenderPlan":
    """The render this episode would get with NO grade — the plan a measurement
    reads through, and the plan probe renders stills from when it is showing the
    footage rather than a grade."""
    m = manifest_lib.Manifest.from_dict(manifest_lib.strip_colour(manifest_dict))
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        params["smooth_window_s"] = m.smooth_window_s
    spec = process_episode.build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    return reframe.plan_render(spec, src, route)


def measure_crop(manifest_dict: dict, src: str, route: str | None, *,
                 frames: int = FRAMES) -> tuple[float, float, float]:
    """(p5, p50, p95) of the episode's own tracked crop, ungraded — the reading
    `color.tone_arg`'s docstring has always asked its callers for.

    Measured (design 2026-08-30 §0.1) against the whole source frame at the window
    midpoint, which is what match_grade read before this: seven of eight real
    episodes differ by more than matchgrade.MATCH_EPS, median 14 and max 36 luma
    units. Costs 0.65s per episode."""
    plan = plan_ungraded(manifest_dict, src, route)
    return crop_percentiles(plan, src, sample_times(plan.dur, frames))


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
