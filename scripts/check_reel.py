"""Whole-reel mechanical gate (design §4, montage §5.13 mechanical half). Silent
phase: audio/safe-zone checks report passed=None, never a silent pass. Returns a
ReelReport with attributed fail_reasons for the Phase A.5 driver."""
import re
import time

from scripts.lib import proc
from scripts.lib.models import CheckResult, ReelCheckSpec, ReelFailure, ReelReport

_NOT_IMPL = {"beat": "silent reel — lands in Phase B (music)",
             "loudness": "silent reel — lands in Phase B (audio-mix)",
             "safe_zones": "needs per-episode route + a platform safe-margin table"}


def _probe_dur(video: str) -> float:
    out = proc.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", video]).stdout.decode().strip()
    return float(out)


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


def run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str) -> ReelReport:
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

    for name, reason in _NOT_IMPL.items():
        checks[name] = CheckResult(name, None, {"status": "not-implemented", "reason": reason})

    rep = ReelReport(checks=checks, fail_reasons=fails, episode_count=len(episodes),
                     wall_s=round(time.monotonic() - t0, 3))
    rep.write(out_report)
    return rep
