"""Whole-reel mechanical gate (design §4, montage §5.13 mechanical half). Silent
phase: audio/safe-zone checks report passed=None, never a silent pass. Returns a
ReelReport with attributed fail_reasons for the Phase A.5 driver."""
import argparse
import os
import re
import tempfile
import time
from itertools import accumulate

import imagehash
from PIL import Image

from scripts.lib import ffbin, proc, provenance, reel_final, safezones
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

_LENGTH_TOL = 0.5      # the length gate's own ± band; build_reel absorbs a further
                       # (_LENGTH_TOL, spec.length_retime_max] of SHORTFALL on top (§3)


def _probe_dur(video: str) -> float:
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", video]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError:
        raise RuntimeError(f"{video} reports no usable duration (ffprobe gave {out!r}) — the file "
                           "may be truncated or durationless; re-render it") from None


def _black_hits(master: str) -> list[float]:
    # blackdetect prints "black_start:<t>" to stderr; any hit fails (spec §9 gate)
    r = proc.run([ffbin.ffmpeg(), "-i", master, "-vf", "blackdetect=d=0.05:pic_th=0.98",
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
    proc.run([ffbin.ffmpeg(), "-y", "-i", video, "-ss", f"{t}", "-frames:v", "1", dst])
    return dst


def _boundaries(durations: list[float]) -> list[float]:
    return list(accumulate(durations))[:-1]            # internal cut times


def _midpoints(durations: list[float]) -> list[float]:
    starts = [0.0] + list(accumulate(durations))[:-1]
    return [s + d / 2 for s, d in zip(starts, durations)]


def _phash_bits(video: str, t: float) -> imagehash.ImageHash:
    with tempfile.TemporaryDirectory() as d:
        f = _sample_frame(video, t, os.path.join(d, "f.png"))
        return imagehash.phash(Image.open(f))


def _hamming(a: imagehash.ImageHash, b: imagehash.ImageHash) -> int:
    return int(a - b)          # imagehash __sub__ returns numpy.int64; coerce so detail stays JSON-serializable


def _loudnorm_measure(audio: str) -> float:
    """Integrated loudness (LUFS) via ffmpeg loudnorm's analysis pass — the same
    measure loudnorm normalizes to, so the gate reads what deliver ships (§5)."""
    r = proc.run([ffbin.ffmpeg(), "-i", audio, "-af", "loudnorm=print_format=json", "-f", "null", "-"])
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
        geometry: list[tuple[str, str, str]] | None = None, platform: str = "",
        outro: dict | None = None) -> ReelReport:
    t0 = time.monotonic()
    durations = [_probe_dur(e) for e in episodes]
    total = _probe_dur(master)
    checks: dict[str, CheckResult] = {}
    fails: list[ReelFailure] = []

    hits = _black_hits(master)
    checks["black"] = CheckResult("black", not hits, {"black_start": hits})
    for h in hits:
        fails.append(ReelFailure("black", "reprocess", _span_of(h, durations), {"t": h}))

    length_ok = abs(total - spec.target_dur) <= _LENGTH_TOL
    checks["length"] = CheckResult("length", length_ok,
                                   {"dur": round(total, 3), "target": spec.target_dur})
    if not length_ok:
        fails.append(ReelFailure("length", "pacing", None,
                                 {"dur": round(total, 3), "target": spec.target_dur}))

    cuts = _boundaries(durations)      # _beat_check reads these below
    mids = _midpoints(durations)       # the phash variety check reads these below

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

    if outro is not None:
        # OUTRO — advisory. Three states, each named. No key at all means no fit ever
        # ran; "n/a" means a fit ran and chose nothing; a measurement means a bar line
        # was chosen and this is how far the delivered master sits from line + fade
        # (design 2026-08-16 §6). mix fades over [master_dur - fade, master_dur], so
        # this residual IS the distance between the fade's start and the bar line.
        # `passed` keys on the length gate's own _LENGTH_TOL — a REPORTING boundary
        # borrowed from a neighbouring check, not a claim about when an ending stops
        # resolving. Nobody has measured that, and a number invented here would be a
        # third un-measured constant wearing a threshold's clothes. (The example this
        # comment used to give was TAIL_MIN; that one WAS measured on 2026-08-18 and is
        # gone — the point survives, the illustration did not.)
        if outro.get("rung", "unchanged") == "unchanged":
            checks["outro"] = CheckResult("outro", None, {
                "status": "n/a", "reason": "the fit chose no bar line (rung 'unchanged')",
                "advisory": True})
        else:
            asked = float(outro["reel_dur"])
            residual = total - asked
            checks["outro"] = CheckResult("outro", abs(residual) <= _LENGTH_TOL, {
                "line": outro.get("line"), "fade": outro.get("fade"),
                "rung": outro.get("rung"), "asked": round(asked, 3),
                "delivered": round(total, 3), "residual": round(residual, 3),
                "tol": _LENGTH_TOL, "advisory": True})

    if geometry is not None:
        # metas FIRST: each carries the provenance bit the route-dependent checks
        # branch on, exactly as check_episode reads its sidecar before deciding
        # what it is entitled to judge.
        paths = [CropPath.from_json(p) for (_, p, _) in geometry]
        metas = [PathMeta.from_json(m) for (_, _, m) in geometry]
        # A pan episode has NO route file — process_episode wrote none, because an
        # empty route.json already means "the tracker found nobody". Read only the
        # ones that exist; the generated episodes contribute an EMPTY mark list
        # below rather than being dropped, so `worst_episode` keeps pointing at the
        # reel's own episode number instead of an index into a filtered list.
        #
        # A TRACKED episode (pan=false) whose route is None is a self-contradicting
        # manifest, not a fact about the footage — check_episode has refused this
        # exact mismatch one level down since the pan slice landed. Without the
        # guard, route_from_json(None) dies inside pathlib naming neither the
        # episode nor a remedy.
        routes = []
        for i, ((r, _, _), me) in enumerate(zip(geometry, metas)):
            if me.pan:
                routes.append(None)
            elif r is None:
                raise ValueError(
                    f"check_reel needs a route for episode {i}: the sidecar says this path "
                    "was tracked (pan=false), but route_path is None — pass the route.json "
                    "reframe used, or re-render with a pan")
            else:
                routes.append(route_from_json(r))
        panned = [i for i, me in enumerate(metas) if me.pan]
        zone = safezones.safe_zone_for(platform)
        marks_per_ep = [[] if rt is None else safezones.subject_marks(rt, pa, me, dur)
                        for rt, pa, me, dur in zip(routes, paths, metas, durations)]
        extents_per_ep = [[] if rt is None else safezones.subject_extents(rt, pa, me, dur)
                          for rt, pa, me, dur in zip(routes, paths, metas, durations)]
        if len(panned) == len(metas):
            # EVERY episode is generated. evaluate() over a list of empty lists
            # returns pass=True — a green tick for having examined nothing, the
            # same shape checks.continuity([]) has one level down. Say so instead.
            for name in ("safe_zones", "key_action"):
                checks[name] = CheckResult(name, None,
                                           {"status": "not-checked", "advisory": True,
                                            "reason": "every episode is a generated pan — "
                                                      "no tracked subject to project"})
        else:
            sz_pass, sz_detail = safezones.evaluate(marks_per_ep, zone)
            ka_pass, ka_detail = reel_final.evaluate_key_action(extents_per_ep, spec.clip_tol)
            if panned:
                # name what was NOT examined; a count of "episodes" that silently
                # included un-examined ones would overstate the coverage
                sz_detail = {**sz_detail, "skipped_episodes": panned}
                ka_detail = {**ka_detail, "skipped_episodes": panned}
            checks["safe_zones"] = CheckResult("safe_zones", sz_pass, sz_detail)
            checks["key_action"] = CheckResult("key_action", ka_pass, ka_detail)
        # pad_bars and transitions read ONLY the metas, so a generated path is no
        # excuse to skip them — the same reason check_episode keeps running
        # jitter/length/black_frames under a pan.
        pb_pass, pb_detail = reel_final.evaluate_pad_bars(metas, spec.bar_symmetry_tol)
        checks["pad_bars"] = CheckResult("pad_bars", pb_pass, pb_detail)
        tr_pass, tr_detail = reel_final.evaluate_transitions(metas, spec.layout_jump_max)
        checks["transitions"] = CheckResult("transitions", tr_pass, tr_detail)

    for name, reason in _UNCHECKED.items():
        checks.setdefault(name, CheckResult(name, None, {"status": "not-checked", "reason": reason}))

    rep = ReelReport(checks=checks, fail_reasons=fails, episode_count=len(episodes),
                     wall_s=round(time.monotonic() - t0, 3),
                     master_digest=provenance.digest_file(master))
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
