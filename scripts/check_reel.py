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
from scripts.lib import color, ffbin, proc, provenance, reel_final, safezones
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


def _grade_faithful_check(master: str, durations: list[float], cuts: list[float],
                          spec: ReelCheckSpec, predicted: list | None,
                          tone_target: tuple[float, float, float] | None,
                          tone_dsts: list | None) -> tuple[CheckResult, ReelFailure | None]:
    """GRADE_FAITHFUL — did the delivered pixels get the declaration (design
    2026-08-31 §2)?

    BLOCKING, and now unconditionally justified. The old reference was the reel's
    common tone target, and the justification was that percentiles commute with a
    monotone map — true, and irrelevant: it holds only while the tone curve is the
    LAST luma operation, and six luma-moving filters follow it in
    color.grade_chain. Measured (§0.2) on the reference run, all eight episodes
    carry a post-tone knob, the knobs displace the reading by up to 4.0 units and
    one of eight crossed the old 12.0 ceiling while being correctly graded.

    `predicted[i]` is the (p5, p50, p95) that episode i's OWN full declared chain
    produces, rendered fresh by the caller. Fresh, never recorded at render time: a
    recorded prediction goes stale the moment build_reel's retry loop re-renders an
    episode, and a stale binding is this repo's most repeated wound.

    Every episode is judged, not only the ones bound to a common target —
    faithfulness is a property of any declaration, including an empty one. An
    episode whose prediction could not be built is NAMED in `not_checked`, never
    silently passed.

    `target_dev` is ADVISORY: max|prediction - target| for bound episodes, i.e. does
    the declared grade actually land this episode on the reel's common tone. It
    carries two jobs the blocking reading gives up — a reference independent of
    process_episode.build_reframe_spec, which the prediction now shares with the
    render, and the only remaining measure of cross-episode agreement. It is not a
    gate because making it one re-opens the deadlock from the other side (§2.1).
    An empty `target_dev` is ambiguous by itself — no target at all, and a target
    with nothing bound to it, both render as `{}` — so `target_dev_reason` names
    which one it is ("no-target" / "no-episode-bound" / `None` once something is
    bound); design §9.7 records what that reason still cannot say.

    Read off the MASTER, not the delivered reel: the look's vignette and the bookend
    fade ride deliver's one encode and both move percentiles. Every span is measured
    in ONE clip_percentiles_batch call.

    Escalates to process-episode — the pixels did not get the declaration, so the
    remedy is a re-render, not a re-authoring — and escalates for free:
    reel_orchestration._REPROCESS_CLASS is ("black",)."""
    if predicted is None:
        return CheckResult("grade_faithful", None, {
            "status": "not-checked", "reason": "no-predictions",
            "remedy": "check_reel was called without per-episode predictions; "
                      "build_reel supplies them, and the CLI cannot (it has no "
                      "manifests to plan from)"}), None
    # Unreachable from any production or CLI path today (final review M-7):
    # build_reel._predict always returns one entry per rm.episodes, so `predicted`
    # and `durations` already agree by construction on that path, and the bare CLI
    # never supplies `predicted` at all (the `is None` branch above catches that).
    # Kept anyway, the same reason _same_target's own non-numeric guard is kept
    # below: this is a public keyword parameter on `run`, and a caller who builds
    # `predicted` by hand gets a named refusal here instead of a silently truncated
    # zip a few lines down.
    if len(predicted) != len(durations):
        raise ValueError(
            f"check_reel: predicted carries {len(predicted)} profiles for "
            f"{len(durations)} episodes — they are parallel lists; build_reel "
            f"builds one per episode, None where a plan could not be made")
    starts = [0.0] + cuts
    not_checked: dict[str, str] = {}
    idx: list[int] = []
    spans: list[list[float]] = []
    for i, (st, dur, p) in enumerate(zip(starts, durations, predicted)):
        if p is None:
            not_checked[str(i)] = "no-prediction"
            continue
        idx.append(i)
        spans.append([st + t for t in color.sample_times(dur)])
    residuals: dict[str, float] = {}
    worst, worst_i = 0.0, None
    if spans:
        got_profiles = color_measure.clip_percentiles_batch(master, spans)
        for i, got in zip(idx, got_profiles):
            d = max(abs(a - b) for a, b in zip(got, predicted[i]))
            # 2 decimals, not 1 — a worst of 4.04 against a 4.0 max must still fail,
            # and a reader must be able to see WHY from the report alone instead of a
            # residual that rounds to look identical to the ceiling it just missed.
            # _loudness_check already rounds to 2; length to 3.
            residuals[str(i)] = round(d, 2)
            if d > worst:
                worst, worst_i = d, i
    # target_dev: ADVISORY agreement-with-the-common-target, for BOUND episodes only
    # (design §2.1). Uses the same _same_target/_TONE_BIND_EPS identity test the old
    # gate used to decide bound-ness — that part of the shape survives; only its
    # consequence (a gate) does not.
    #
    # tone_dsts is still a REQUIRED parallel list once tone_target is given, exactly
    # as the old _tone_match_check demanded — advisory does not mean unchecked-input.
    # `tone_dsts is None` used to mean "the caller forgot the parallel list", and
    # silently reading it as [None]*len(predicted) would report every episode
    # "not bound", indistinguishable from the true fact that a conductor really did
    # skip every episode (fix round 1, Important 5). A too-short list is the same
    # caller mistake in a different shape; without this guard `dsts[i]` below raises
    # a bare, unattributed IndexError instead of naming the fix.
    # target_dev_reason (final review I-3): an empty target_dev is ambiguous on its
    # own — "no EDL.tone_target at all" and "a target exists but nothing is bound to
    # it" both render as `{}`, and the old tone_match gate reported the FIRST as a
    # visible not-checked absence, never a clean reading. Named here instead of left
    # for a reader to guess: `None` once at least one episode is actually bound (the
    # everyday case, and the only one where an absent reason would mislead), else
    # "no-target" or "no-episode-bound" — distinct strings because they are distinct
    # facts (a missing target names a stage that never ran; a present-but-unbound
    # target names episodes that are all hand-authored, skipped, or off by more than
    # _TONE_BIND_EPS).
    target_dev: dict[str, float] = {}
    target_dev_reason: str | None = "no-target"
    if tone_target is not None:
        if tone_dsts is None or len(tone_dsts) != len(predicted):
            raise ValueError(
                f"check_reel: tone_target {list(tone_target)} was supplied with "
                f"{'no' if tone_dsts is None else len(tone_dsts)} per-episode tone_dst "
                f"values for {len(predicted)} episodes — they are parallel lists; pass "
                "[e.manifest.get('tone_dst') for e in rm.episodes] (build_reel does), or "
                "pass no tone_target at all to skip the advisory target_dev reading")
        for i, p in enumerate(predicted):
            if p is not None and _same_target(tone_dsts[i], tone_target):
                target_dev[str(i)] = round(max(abs(a - b) for a, b in zip(p, tone_target)), 2)
        target_dev_reason = None if target_dev else "no-episode-bound"
    detail = {"residuals": residuals, "not_checked": not_checked,
              "max": spec.grade_residual_max,
              "target_dev": target_dev, "target_dev_advisory": True,
              "target_dev_reason": target_dev_reason}
    if not residuals:
        # Every episode's prediction failed to build — the check examined nothing.
        # passed=True here would be a green tick for having looked at zero pixels,
        # the same vacuous shape the all-pan safe_zones branch refuses to fall
        # through to. Say so instead.
        return CheckResult("grade_faithful", None, {
            **detail, "status": "not-checked", "reason": "no-episode-predicted",
            "remedy": "no episode could be planned — read the per-episode reasons "
                      "in not_checked"}), None
    ok = worst <= spec.grade_residual_max
    detail["worst"] = round(worst, 2)
    fail = None if ok else ReelFailure("grade_faithful", "process-episode", worst_i,
                                       {"residual": round(worst, 2),
                                        "max": spec.grade_residual_max})
    return CheckResult("grade_faithful", ok, detail), fail


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
        predicted: list | None = None,
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

    cr, fail = _grade_faithful_check(master, durations, cuts, spec, predicted,
                                     tone_target, tone_dsts)
    checks["grade_faithful"] = cr
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
