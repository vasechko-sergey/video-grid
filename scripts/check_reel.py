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

from scripts import color_measure
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

_TONE_BIND_EPS = 1e-6  # "is this episode's tone_dst the reel's common target?" — an
                       # identity test, not a threshold. Both triples are the SAME
                       # floats the conductor wrote, so this only absorbs the
                       # int-vs-float / list-vs-tuple round trip through JSON. It cannot
                       # swallow a real difference: color.percentiles returns whole 0-255
                       # codes, so the smallest one is 1.0 and color.TONE_MIN_GAP — the
                       # gap two anchors must keep to stay orderable at all — is 6.0.


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


def _same_target(dst, target: tuple[float, float, float]) -> bool:
    """Is this episode's `tone_dst` the reel's own common target (design 2026-08-30 §5)?

    Only a BOUND episode can be judged against the target: one the conductor skipped
    carries no pair (flat-source, within-eps) or a different one (hand-authored), and
    measuring it against a target it was never graded toward would report a failure
    the grade never claimed. `None` and a wrong-length value both read as simply not
    the target — the everyday shapes an unbound episode's manifest legitimately
    carries (edl_to_reel's own path: reframe refuses a malformed pair long before the
    reel is assembled, so neither shape reaching here is ever real corruption on that
    path).

    A right-length value with a NON-NUMERIC element is a different fact, found in fix
    round 1: that shape is not one reframe's validation, on ANY path, ever produces —
    but build_reel's own CLI reads an arbitrary reel-manifest JSON with no reframe or
    edl_to_reel validation upstream of it, so a hand-edited or corrupt manifest CAN
    reach here with one. Refusing it loud, with a remedy, beats letting `abs(a - b)`
    below raise a bare unattributed TypeError (CONSTRAINTS §4)."""
    if not isinstance(dst, (list, tuple)) or len(dst) != len(target):
        return False
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in dst):
        raise ValueError(
            f"check_reel: an episode's tone_dst {dst!r} is not a triple of luma "
            "numbers (p5, p50, p95) — the reel manifest is corrupt; regenerate it "
            "(match-grade always authors tone_dst as three numbers, or leaves it "
            "null — a non-numeric value did not come from there)")
    return all(abs(a - b) <= _TONE_BIND_EPS for a, b in zip(dst, target))


def _loudness_check(measured: float, spec: ReelCheckSpec) -> tuple[CheckResult, ReelFailure | None]:
    """LOUDNESS — hard gate. In band → pass; out → a ReelFailure that next_action
    escalates via escalate_to='audio-mix' (a bad mix stops-and-reports, §5)."""
    ok = abs(measured - spec.loudness_target) <= spec.loudness_tol
    detail = {"measured": round(measured, 2), "target": spec.loudness_target}
    fail = None if ok else ReelFailure("loudness", "audio-mix", None, dict(detail))
    return CheckResult("loudness", ok, detail), fail


def _tone_match_check(master: str, durations: list[float], cuts: list[float],
                      spec: ReelCheckSpec, tone_target: tuple[float, float, float] | None,
                      tone_dsts: list | None) -> tuple[CheckResult, ReelFailure | None]:
    """TONE_MATCH — did the declared grade reach the pixels (design 2026-08-30 §5)?

    BLOCKING, and cheap to justify — ON ONE CONDITION, which the pipeline does not
    guarantee. Percentiles commute with a monotone map and color.tone_arg builds one,
    so a graded episode's delivered p5/p50/p95 land ON the target by construction
    PROVIDED the tone curve is the LAST luma operation in its chain. In general it is
    not: color.grade_chain's order is wb -> tone -> black_point -> gain -> shadow_red
    -> mid_blue -> saturation -> highlight -> highlight_red -> dip, and the conductor
    solves the curve against color_measure.measure_crop, which reads through
    manifest.strip_colour — every knob at identity. So any POST-tone knob that moves
    luma displaces the very reading this gate takes: black_point, a non-default
    color_means (the mixer), shadow_red, mid_blue, highlight, highlight_red and dip.
    Two do not: white_balance runs BEFORE tone (and the measurement carries it), and
    saturation is an eq= chroma scale that leaves the luma plane alone.

    Measured (design 2026-08-30 §9.9) on a 3-band tv-range clip, ungraded 40/120/200
    onto target 52/103.5/191.5: tone alone lands 1.5 off; tone + black_point=0.05
    lands 12.0; tone + black_point=0.10 lands 25.0; tone + highlight=0.8 lands 19.5.
    black_point in [0, 0.35] and highlight in [0.6, 1.0] are documented, in-range,
    per-episode knobs, so a CORRECTLY graded episode carrying one can fail this gate,
    and at black_point=0.10 the residual is past the negative class's own minimum —
    the gate cannot then tell "the grade never reached the pixels" from "the author
    lifted a toe". It escalates to match-grade, which re-measures at identity and
    re-authors the identical pair: a second no-exit loop, the same shape as §9.8's
    but by a different mechanism. Filed P1 in docs/backlog.md; the open design
    question is whether the residual should be measured THROUGH the non-tone part of
    the chain, or whether post-tone knobs should be excluded from it.

    A large residual is therefore something really broken — a stale target, a colour
    block dropped between authoring and render — OR a second luma knob beside the
    tone pair, and nothing in this check separates the two. Measured (§0.6), on
    episodes graded by tone ALONE: the healthy maximum is 8.0 and the broken minimum
    19.5, and tone_match_max = 12.0 sits mid-gap.

    Read off the MASTER, not the delivered reel: the look's vignette and the bookend
    fade ride deliver's one encode and both move percentiles, so the master is the
    last artifact whose pixels are the episodes'. `cuts` already holds every internal
    boundary, so each episode's span costs nothing new. Every BOUND episode's span is
    measured in ONE clip_percentiles_batch call (fix round 1, minor 1) rather than one
    clip_percentiles call per episode — each of those re-decoded the master from t=0
    through only its own episode, so N episodes cost roughly N/2 full-master decodes
    summed; one batched decode costs one, regardless of N.

    Only episodes BOUND to the reel's common target are judged; the rest are NAMED,
    never silently passed. The two absences are different facts and carry different
    keys, so a reader never has to type-sniff: a reel that was never conducted reports
    `status: not-checked` with `reason: "no-target"` at the top level (its `remedy`
    names how many episodes already carry a tone_dst regardless, per fix round 1
    minor 2 — a reel graded before tone_target existed must not read as ungraded),
    while `not_checked` — present whenever a target exists — is ALWAYS a {episode
    index: reason} map. "not-bound" is one label for all three of the conductor's skip
    reasons (flat-source / within-eps / hand-authored) because the manifest cannot
    tell them apart; MATCH.md is where the conductor records which it was.

    Escalates to match-grade, and escalates for free: reel_orchestration's
    _REPROCESS_CLASS is ("black",), so every non-black reel failure already escalates
    rather than re-rendering — no reframe knob moves a colour."""
    if tone_target is None:
        graded = sum(1 for d in (tone_dsts or []) if d is not None)
        remedy = ("this reel declares no common tone target — run match-grade to "
                  "author one, or ship it ungraded (absence is not tampering)")
        if graded:
            # fix round 1, minor 2: an EDL graded before tone_target existed (or one
            # match-grade never touched but a human hand-authored per-episode pairs
            # onto) must not read as plain "ungraded" — the remedy above is still
            # correct (there is genuinely no reel-wide target to compare against), but
            # silently saying nothing about it would hide that these episodes ARE
            # graded from the one place a reader looks when a reel looks washed out.
            remedy += (f"; {graded}/{len(durations)} episode(s) already carry a "
                      "tone_dst pair, so this reel IS graded — match-grade just never "
                      "stamped the reel-wide target this check compares against")
        return CheckResult("tone_match", None, {
            "status": "not-checked", "reason": "no-target", "remedy": remedy}), None
    if tone_dsts is None or len(tone_dsts) != len(durations):
        raise ValueError(
            f"check_reel: tone_target {list(tone_target)} was supplied with "
            f"{'no' if tone_dsts is None else len(tone_dsts)} per-episode tone_dst "
            f"values for {len(durations)} episodes — they are parallel lists; pass "
            "[e.manifest.get('tone_dst') for e in rm.episodes] (build_reel does), or "
            "pass no tone_target at all to report the check not-checked")
    starts = [0.0] + cuts
    not_checked: dict[str, str] = {}
    bound_idx: list[int] = []
    bound_spans: list[list[float]] = []
    for i, (st, dur, dst) in enumerate(zip(starts, durations, tone_dsts)):
        if not _same_target(dst, tone_target):
            not_checked[str(i)] = "not-bound"
            continue
        bound_idx.append(i)
        bound_spans.append([st + t for t in color_measure.sample_times(dur)])
    residuals: dict[str, float] = {}
    worst, worst_i = 0.0, None
    if bound_spans:
        got_profiles = color_measure.clip_percentiles_batch(master, bound_spans)
        for i, got in zip(bound_idx, got_profiles):
            d = max(abs(a - b) for a, b in zip(got, tone_target))
            # fix round 1, minor 3: 2 decimals, not 1 — a worst of 12.04 against a
            # 12.0 max must still fail, and a reader must be able to see WHY from the
            # report alone instead of a residual that rounds to look identical to the
            # ceiling it just missed. _loudness_check already rounds to 2; length to 3.
            residuals[str(i)] = round(d, 2)
            if d > worst:
                worst, worst_i = d, i
    detail = {"target": list(tone_target), "residuals": residuals,
              "not_checked": not_checked, "max": spec.tone_match_max}
    if not residuals:
        # A target exists but nothing is bound to it — the reel where the conductor
        # skipped every episode. passed=True here would be a green tick for having
        # examined nothing, the same vacuous shape the all-pan safe_zones branch
        # refuses to fall through to. Say so instead.
        return CheckResult("tone_match", None, {
            **detail, "status": "not-checked", "reason": "no-episode-bound",
            "remedy": "no episode carries this reel's common target — read MATCH.md "
                      "for why the conductor skipped each one"}), None
    ok = worst <= spec.tone_match_max
    detail["worst"] = round(worst, 2)
    fail = None if ok else ReelFailure("tone_match", "match-grade", worst_i,
                                       {"residual": round(worst, 2),
                                        "max": spec.tone_match_max})
    return CheckResult("tone_match", ok, detail), fail


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
        outro: dict | None = None,
        tone_target: tuple[float, float, float] | None = None,
        tone_dsts: list | None = None) -> ReelReport:
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

    cr, fail = _tone_match_check(master, durations, cuts, spec, tone_target, tone_dsts)
    checks["tone_match"] = cr
    if fail is not None:
        fails.append(fail)

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
