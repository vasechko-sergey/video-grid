"""Measure a clip's (p5, p50, p95) luma — the authoring aid for ReframeSpec.tone
(design 2026-07-26 §5). Pure percentile math lives in color.percentiles; this driver
only produces the histogram from a decoded still."""
import argparse
import numpy as np
from scripts import process_episode, reframe
from scripts.lib import assembly, color, ffbin, proc


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


def _percentiles_from_gray(raw: bytes, want: int, w: int, h: int,
                           where: str) -> tuple[float, float, float]:
    """(p5, p50, p95) of a pooled gray rawvideo buffer — the ONE ruler.

    Pooled, not averaged per frame: the three frames describe one distribution,
    which is what a tone profile is. Checked against `want * w * h` bytes EXACTLY,
    not merely divisibility by `want`: a divisibility-only check is vacuous at
    production frame sizes — 1920x1080 and 1080x1920 both have frame_bytes % 3 == 0,
    so for want=3 (the only value FRAMES takes) a select that silently returned 1,
    2, 4 or 7 frames instead of 3 would still pass it. Only the exact byte count
    catches the §12 select landmine this guard exists for, in the form it takes
    when nothing crashes."""
    if not raw:
        raise RuntimeError(f"{where}: ffmpeg decoded no frames")
    frame_bytes = w * h
    if len(raw) != want * frame_bytes:
        got = len(raw) / frame_bytes if frame_bytes else float("nan")
        raise RuntimeError(
            f"{where}: asked for {want} frames of {w}x{h} gray ({want * frame_bytes} "
            f"bytes), got {len(raw)} bytes ({got:g} frames) — a frame is missing or "
            f"duplicated; check the select expression's position")
    hist = np.bincount(np.frombuffer(raw, dtype=np.uint8), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def clip_percentiles(clip: str, times: list[float]) -> tuple[float, float, float]:
    """The ruler over a FINISHED file, one span at a time — no crop, no manifest.

    NOT a production path any more: since Task 6's fix round check_reel's grade_faithful
    check (named tone_match before design 2026-08-31) reads the master through
    clip_percentiles_batch, which decodes once for every episode instead of once per
    episode. What is left is the single-span primitive —
    the independently-trusted reading that batch is checked AGAINST
    (test_clip_percentiles_batch_matches_the_per_span_calls), and the one-liner a proof or a
    hand measurement reaches for when it wants one clip's profile. It is deliberately
    not folded into the batch version: a batch that reconstructs the singles is only
    evidence while the singles are computed some other way."""
    info = assembly.probe_stream(clip)
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", clip,
                    "-vf", f"{color.select_frames(times, info.fps)},format=gray",
                    "-vsync", "0", "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    return _percentiles_from_gray(out, len(times), info.w, info.h,
                                  f"clip_percentiles({clip})")


def clip_percentiles_batch(clip: str, spans: list[list[float]]) -> list[tuple[float, float, float]]:
    """(p5, p50, p95) luma for EACH span in `spans`, from ONE decode of `clip` (design
    2026-08-30 Task 6 fix round 1, minor 1).

    check_reel's grade_faithful gate (named tone_match before design 2026-08-31) used to
    call clip_percentiles once per bound episode;
    each call re-decodes `clip` from t=0 (no -ss, per §12) through only THAT episode's
    own last sample — so summed over N episodes the master is decoded roughly N/2 times
    over (episode 0 decodes a little of it, episode N-1 decodes almost all of it).
    Selecting every span's times back-to-back in the SAME ffmpeg call decodes `clip`
    exactly once no matter how many spans are asked for — the same batching the
    grade-delta-sensors slice already used to fold three samples' worth of decodes down
    to two.

    `spans` must already be in ASCENDING, NON-OVERLAPPING time order — check_reel's
    episode spans always are, since they partition the master from its start to its
    end. select's own OUTPUT order follows the decoded stream's natural frame order,
    never the order frames are named in the filter expression, so slicing the one raw
    buffer back into per-span groups by each span's own frame count only reconstructs
    the right groups because the request order already matches stream order; an
    out-of-order span would silently hand one episode another's pixels with no error
    to catch it, which is why this is a documented precondition and not a parameter.

    The total byte count is checked BEFORE any slicing (a frame missing or duplicated
    anywhere could otherwise make one span's slice quietly borrow bytes that belong to
    its neighbour, past the point where a single span's own length still happens to
    come out right); each span's slice is then handed to _percentiles_from_gray — the
    SAME pooling call clip_percentiles itself makes, and the only other reason this
    function exists (it re-validates that one slice's own byte count too) — so
    color.percentiles stays reached from exactly the two places the plan's invariant 2
    names. Batching changes how many decodes happen, never the ruler."""
    if not spans:
        raise ValueError("clip_percentiles_batch: spans is empty — nothing to measure")
    info = assembly.probe_stream(clip)
    all_times = [t for span in spans for t in span]
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", clip,
                    "-vf", f"{color.select_frames(all_times, info.fps)},format=gray",
                    "-vsync", "0", "-frames:v", str(len(all_times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    frame_bytes = info.w * info.h
    want_bytes = len(all_times) * frame_bytes
    if len(out) != want_bytes:
        got = len(out) / frame_bytes if frame_bytes else float("nan")
        raise RuntimeError(
            f"clip_percentiles_batch({clip}): asked for {len(all_times)} frames across "
            f"{len(spans)} spans of {info.w}x{info.h} gray ({want_bytes} bytes), got "
            f"{len(out)} bytes ({got:g} frames) — a frame is missing or duplicated; "
            "check the select expression's position")
    results = []
    offset = 0
    for i, span in enumerate(spans):
        n = len(span)
        chunk = out[offset * frame_bytes:(offset + n) * frame_bytes]
        results.append(_percentiles_from_gray(chunk, n, info.w, info.h,
                                              f"clip_percentiles_batch({clip})[{i}]"))
        offset += n
    return results


def crop_percentiles(plan: "reframe.RenderPlan", src: str,
                     times: list[float]) -> tuple[float, float, float]:
    """The ruler over the pixels a RenderPlan would encode — the crop, scaled to
    the delivery, with whatever colour the plan carries. The select is appended at
    the END through with_tail: before the chain's own `fps=` it would emit one
    frame N times (§12)."""
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src,
                    *plan.with_tail(f"{color.select_frames(times, plan.fps)},format=gray"),
                    "-t", f"{plan.dur:.6f}", "-vsync", "0",
                    "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    return _percentiles_from_gray(out, len(times), plan.rl.out_w, plan.rl.out_h,
                                  f"crop_percentiles({src})")


def measure_crop(manifest_dict: dict, src: str, route: str | None, *,
                 frames: int = color.FRAMES) -> tuple[float, float, float]:
    """(p5, p50, p95) of the episode's own tracked crop, ungraded — the reading
    `color.tone_arg`'s docstring has always asked its callers for.

    Measured (design 2026-08-30 §0.1) against the whole source frame at the window
    midpoint, which is what match_grade read before this: seven of eight real
    episodes differ by more than matchgrade.MATCH_EPS, median 14 and max 36 luma
    units. Costs 0.65s per episode."""
    plan = process_episode.plan_ungraded(manifest_dict, src, route)
    return crop_percentiles(plan, src, color.sample_times(plan.dur, frames))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="measure a clip's (p5,p50,p95) luma for ReframeSpec.tone")
    ap.add_argument("clip")
    ap.add_argument("--at", type=float, default=None, help="sample time in seconds (default 1.0)")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    p5, p50, p95 = measure_profile(a.clip, a.at)
    print(f"p5={p5:.1f} p50={p50:.1f} p95={p95:.1f}")
    print(f'tone_src: [{p5:.0f}, {p50:.0f}, {p95:.0f}]')


if __name__ == "__main__":
    main()
