"""Whole-reel mechanical gate (design §4, montage §5.13 mechanical half). Silent
phase: audio/safe-zone checks report passed=None, never a silent pass. Returns a
ReelReport with attributed fail_reasons for the Phase A.5 driver."""
import argparse
import os
import re
import statistics
import tempfile
import time
from itertools import accumulate

import imagehash
import numpy as np
from PIL import Image

from scripts.lib import proc, reel_final, safezones
from scripts.lib.models import (CheckResult, CropPath, MusicSpec, PathMeta, ReelCheckSpec,
                                ReelFailure, ReelReport, route_from_json)

# beat/loudness/safe_zones/key_action/pad_bars/transitions ARE implemented — they fall through
# to "not-checked" only when the reel lacks the input each needs (music/audio for beat/loudness;
# per-episode geometry for safe_zones/key_action/pad_bars/transitions). Nothing is genuinely
# "not-implemented" anymore.
_UNCHECKED = {"beat": "not checked — no MUSIC.json supplied (silent reel)",
              "loudness": "not checked — no audio stem supplied (silent reel)",
              "safe_zones": "not checked — no per-episode geometry supplied",
              "key_action": "not checked — no per-episode geometry supplied",
              "pad_bars": "not checked — no per-episode geometry supplied",
              "transitions": "not checked — no per-episode geometry supplied"}


def _probe_dur(video: str) -> float:
    out = proc.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", video]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError:
        raise RuntimeError(f"{video} reports no usable duration (ffprobe gave {out!r}) — the file "
                           "may be truncated or durationless; re-render it") from None


def _black_hits(master: str) -> list[float]:
    # blackdetect prints "black_start:<t>" to stderr; any hit fails (spec §9 gate)
    r = proc.run(["ffmpeg", "-i", master, "-vf", "blackdetect=d=0.05:pic_th=0.98",
                  "-an", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    return [float(m) for m in re.findall(r"black_start:(\d+\.?\d*)", err)]


def _span_of(t: float, durations: list[float]) -> int:
    edge = 0.0
    for i, d in enumerate(durations):
        edge += d
        if t < edge:
            return i
    return len(durations) - 1


def _sample_frame(video: str, t: float, dst: str) -> str:
    # output-seek (-ss AFTER -i) keeps the landmine lint clean; clips are short so
    # decoding to t is cheap. One still frame at t.
    proc.run(["ffmpeg", "-y", "-i", video, "-ss", f"{t}", "-frames:v", "1", dst])
    return dst


def _frame_mean(video: str, t: float) -> tuple[float, float, float]:
    with tempfile.TemporaryDirectory() as d:
        f = _sample_frame(video, t, os.path.join(d, "f.png"))
        a = np.asarray(Image.open(f).convert("RGB"), dtype=float)
    return float(a[..., 0].mean()), float(a[..., 1].mean()), float(a[..., 2].mean())


def _rgb_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / 3.0


def _boundaries(durations: list[float]) -> list[float]:
    return list(accumulate(durations))[:-1]            # internal cut times


def _midpoints(durations: list[float]) -> list[float]:
    starts = [0.0] + list(accumulate(durations))[:-1]
    return [s + d / 2 for s, d in zip(starts, durations)]


def _channel_median(means: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    return tuple(statistics.median(m[c] for m in means) for c in range(3))


def _phash_bits(video: str, t: float) -> imagehash.ImageHash:
    with tempfile.TemporaryDirectory() as d:
        f = _sample_frame(video, t, os.path.join(d, "f.png"))
        return imagehash.phash(Image.open(f))


def _hamming(a: imagehash.ImageHash, b: imagehash.ImageHash) -> int:
    return int(a - b)          # imagehash __sub__ returns numpy.int64; coerce so detail stays JSON-serializable


def _loudnorm_measure(audio: str) -> float:
    """Integrated loudness (LUFS) via ffmpeg loudnorm's analysis pass — the same
    measure loudnorm normalizes to, so the gate reads what deliver ships (§5)."""
    r = proc.run(["ffmpeg", "-i", audio, "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    m = re.search(r'"input_i"\s*:\s*"?(-?\d+\.?\d*)"?', err)
    if not m:
        raise RuntimeError(f"loudnorm printed no input_i for {audio} — the file may have no audio "
                           "stream; mix must produce the stem before the loudness gate runs")
    return float(m.group(1))


def _loudness_check(measured: float, spec: ReelCheckSpec) -> tuple[CheckResult, ReelFailure | None]:
    """LOUDNESS — hard gate. In band → pass; out → a ReelFailure that next_action
    escalates via escalate_to='audio-mix' (a bad mix stops-and-reports, §5)."""
    ok = abs(measured - spec.loudness_target) <= spec.loudness_tol
    detail = {"measured": round(measured, 2), "target": spec.loudness_target}
    fail = None if ok else ReelFailure("loudness", "audio-mix", None, dict(detail))
    return CheckResult("loudness", ok, detail), fail


def _beat_check(cuts: list[float], beats: tuple[float, ...], tol: float) -> CheckResult:
    """BEAT — advisory. Worst deviation of a cut from its nearest beat; reported,
    never a ReelFailure (excluded from overall via _ADVISORY_CHECKS, §5). The
    'advisory' flag self-documents report.json — a False here doesn't block."""
    if not cuts:
        return CheckResult("beat", None, {"status": "n/a", "reason": "single episode, no cut"})
    worst = max(min(abs(t - b) for b in beats) for t in cuts)
    return CheckResult("beat", worst <= tol,
                       {"worst_dev": round(worst, 3), "tol": tol, "n_cuts": len(cuts), "advisory": True})


def run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str,
        music: MusicSpec | None = None, audio: str | None = None,
        geometry: list[tuple[str, str, str]] | None = None, platform: str = "") -> ReelReport:
    t0 = time.monotonic()
    durations = [_probe_dur(e) for e in episodes]
    total = _probe_dur(master)
    checks: dict[str, CheckResult] = {}
    fails: list[ReelFailure] = []

    hits = _black_hits(master)
    checks["black"] = CheckResult("black", not hits, {"black_start": hits})
    for h in hits:
        fails.append(ReelFailure("black", "reprocess", _span_of(h, durations), {"t": h}))

    length_ok = abs(total - spec.target_dur) <= 0.5
    checks["length"] = CheckResult("length", length_ok,
                                   {"dur": round(total, 3), "target": spec.target_dur})
    if not length_ok:
        fails.append(ReelFailure("length", "pacing", None,
                                 {"dur": round(total, 3), "target": spec.target_dur}))

    cuts = _boundaries(durations)
    mids = _midpoints(durations)
    if cuts:
        span_means = [_frame_mean(master, m) for m in mids]
        median = _channel_median(span_means)
        color_ok = True
        worst = None
        for i, bt in enumerate(cuts):
            left = _frame_mean(master, max(0.0, bt - 0.05))
            right = _frame_mean(master, bt + 0.05)
            delta = _rgb_dist(left, right)
            if delta >= spec.color_delta_max:
                color_ok = False
                # farther-from-median span is the culprit. On a tie — notably every
                # 2-episode reel, whose 2-value median is equidistant from both spans
                # — blame the later episode, matching the variety check's "second of
                # the pair" default (design §4).
                culprit = (i if _rgb_dist(span_means[i], median) > _rgb_dist(span_means[i + 1], median)
                           else i + 1)
                fails.append(ReelFailure("color_across_cuts", "reprocess", culprit,
                                         {"cut": i, "delta": round(delta, 2),
                                          "target": [round(x, 2) for x in median],
                                          "culprit_mean": [round(x, 2) for x in span_means[culprit]]}))
                worst = round(delta, 2) if worst is None else max(worst, round(delta, 2))
        checks["color_across_cuts"] = CheckResult("color_across_cuts", color_ok,
                                                  {"worst_delta": worst} if worst is not None else {})
    else:
        checks["color_across_cuts"] = CheckResult("color_across_cuts", None,
                                                  {"status": "n/a", "reason": "single episode, no cut"})

    if len(episodes) > 1:
        hashes = [_phash_bits(master, m) for m in mids]
        var_ok = True
        worst = None
        for i in range(len(hashes) - 1):
            dist = _hamming(hashes[i], hashes[i + 1])
            if dist < spec.variety_min:
                var_ok = False
                fails.append(ReelFailure("variety", "edit-plan", i + 1,
                                         {"pair": [i, i + 1], "distance": dist}))
                worst = dist if worst is None else min(worst, dist)
        checks["variety"] = CheckResult("variety", var_ok,
                                        {"min_distance": worst} if worst is not None else {})
    else:
        checks["variety"] = CheckResult("variety", None,
                                        {"status": "n/a", "reason": "single episode"})

    if audio is not None:
        cr, fail = _loudness_check(_loudnorm_measure(audio), spec)
        checks["loudness"] = cr
        if fail is not None:
            fails.append(fail)
    if music is not None:
        checks["beat"] = _beat_check(cuts, music.beats, spec.beat_tol)

    if geometry is not None:
        routes = [route_from_json(r) for (r, _, _) in geometry]
        paths = [CropPath.from_json(p) for (_, p, _) in geometry]
        metas = [PathMeta.from_json(m) for (_, _, m) in geometry]
        zone = safezones.safe_zone_for(platform)
        marks_per_ep = [safezones.subject_marks(rt, pa, me, dur)
                        for rt, pa, me, dur in zip(routes, paths, metas, durations)]
        sz_pass, sz_detail = safezones.evaluate(marks_per_ep, zone)
        checks["safe_zones"] = CheckResult("safe_zones", sz_pass, sz_detail)
        extents_per_ep = [safezones.subject_extents(rt, pa, me, dur)
                          for rt, pa, me, dur in zip(routes, paths, metas, durations)]
        ka_pass, ka_detail = reel_final.evaluate_key_action(extents_per_ep, spec.clip_tol)
        checks["key_action"] = CheckResult("key_action", ka_pass, ka_detail)
        pb_pass, pb_detail = reel_final.evaluate_pad_bars(metas, spec.bar_symmetry_tol)
        checks["pad_bars"] = CheckResult("pad_bars", pb_pass, pb_detail)
        tr_pass, tr_detail = reel_final.evaluate_transitions(metas, spec.layout_jump_max)
        checks["transitions"] = CheckResult("transitions", tr_pass, tr_detail)

    for name, reason in _UNCHECKED.items():
        checks.setdefault(name, CheckResult(name, None, {"status": "not-checked", "reason": reason}))

    rep = ReelReport(checks=checks, fail_reasons=fails, episode_count=len(episodes),
                     wall_s=round(time.monotonic() - t0, 3))
    rep.write(out_report)
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description="Whole-reel mechanical check.")
    ap.add_argument("master")
    ap.add_argument("episodes", nargs="+", help="ordered locked episode paths")
    ap.add_argument("--target-dur", type=float, required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    rep = run(a.master, a.episodes, ReelCheckSpec(target_dur=a.target_dur), a.report)
    raise SystemExit(0 if rep.overall else 1)


if __name__ == "__main__":
    main()
