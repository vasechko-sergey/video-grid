"""Reel retry-loop driver (design §5, Phase A.5). Consumes a ReelManifest of
locked episode clips and loops assemble → check_reel → reprocess the culprit via
process_episode → until the reel passes and delivers, or stops with a precise
machine-readable finding. Mirrors process_episode.py: the editorial judgment ran
per-episode in loop-1; this shell owns only the mechanical reel loop.
Deterministic for a non-stabilized episode — a reprocess reuses its frozen
route, so nothing changes between rounds. A stabilized episode re-tracks
instead: its frozen route's pixel provenance cannot be proven (nothing yet
records whether a route was measured on raw or stabilized pixels), so
process_episode refuses the combination and this module withholds the route
rather than risk replaying it against the wrong coordinate system
(design 2026-07-20 §1)."""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

from scripts import check_reel, color_measure, deliver, mix, probe, process_episode
from scripts.lib import assembly, color, color_fidelity, episode_qc as qc_lib, reel_orchestration
from scripts.lib.models import ReelManifest, MusicSpec, REEL_H264


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _predict(rm: ReelManifest) -> list:
    """One (p5, p50, p95) per episode: what its OWN full declared chain produces.

    The reference check_reel.grade_faithful compares the master against. Built here
    rather than inside check_reel because this is where the manifests are, and built
    ONCE rather than per retry round because a reprocess re-renders with the same
    manifest — the declaration cannot move between rounds, the same argument
    tone_dsts already makes just below.

    probe.source_for, not md["segment"]: under `stabilize` reframe consumed the
    pre-stage's output, and planning against the raw segment would predict pixels
    the episode never shipped.

    probe._refuse_on_drift, reused verbatim rather than a second oracle: it is the
    one check that the plan rebuilt here is the geometry that shipped. Since
    2026-09-24 the rebuild carries the params the render RECORDED
    (process_episode.rendered_params off this episode's path.meta.json), so an
    episode whose accepted attempt was not attempt 1 rebuilds correctly instead of
    drifting — before that, its rescaled max_speed/smooth_window_s existed nowhere
    and the recomputed crop trajectory disagreed with the frozen one even though
    nothing about the DECLARED colour had changed. The oracle stays, because a
    sidecar written before the fields existed still records nothing, and because a
    re-track or a swapped source drifts for reasons no params record can fix.
    Without it that disagreement would still produce a profile and grade_faithful
    would report it as a colour residual — the wrong remedy (process-episode
    cannot fix a geometry mismatch by re-grading). `probe.probe_grade` guards the
    identical hazard the identical way, right after building the identical plan.

    An episode whose plan cannot be built, or whose recomputed geometry drifts from
    what shipped, contributes None. check_reel NAMES it in not_checked; losing one
    episode's reading must not cost the reel its gate.
    """
    out = []
    for e in rm.episodes:
        try:
            md = dict(e.manifest)
            src = probe.source_for(md, Path(e.path).parent)
            plan = process_episode.plan_for(
                md, src, e.route, params=process_episode.rendered_params(e.meta))
            probe._refuse_on_drift(plan, e.path, e.meta)
            out.append(color_measure.crop_percentiles(
                plan, src, color.sample_times(plan.dur)))
        except Exception as ex:                     # noqa: BLE001 — reported, not swallowed
            _log(f"build_reel: no grade prediction for {e.clip}: {ex}")
            out.append(None)
    return out


def build_reel(rm: ReelManifest, out_dir: str, work_dir: str, titles: str | None = None) -> dict:
    """Drive rm's locked clips to a delivered reel or a stop-and-report finding."""
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    clips = [e.clip for e in rm.episodes]
    si = assembly.probe_stream(clips[0])          # actual delivered dims/fps (episodes uniform by construction)
    dims, fps = (si.w, si.h), si.fps
    master = str(Path(work_dir) / "master.mp4")
    report_path = str(Path(work_dir) / "reel_report.json")
    music = MusicSpec.from_json(rm.music) if rm.music else None   # None → silent reel, exactly as Phase A.5
    # The length re-time only ever SHRINKS the target, so a target that starts outside the music
    # window can never be rescued downstream — mix refuses a stem longer than its fragment. Refuse
    # it here, before any ffmpeg, rather than let the absorb carry it into mix's raise (design §6).
    if music is not None and rm.target_dur > music.duration + 0.1:
        raise ValueError(f"build_reel: target_dur {rm.target_dur}s exceeds the analyzed music "
                         f"window {music.duration}s — this reel can never be mixed (mix refuses a "
                         f"stem longer than its fragment); re-pick the fragment "
                         f"(beats --auto-start --duration {rm.target_dur:.0f}) or lower the target")
    attempts: dict[int, int] = {}
    reprocessed: set[int] = set()          # design §8: which clips left the gate behind
    spec = rm.check_spec          # mutable across rounds: a length re-time replaces target_dur
    audio: str | None = None
    geometry = ([(e.route, e.path, e.meta) for e in rm.episodes]   # frozen sidecars — constant across rounds
                if all(e.path and e.meta for e in rm.episodes) else None)
    # The convergence gate's per-episode half (design 2026-08-30 §5): which episodes are
    # BOUND to rm.tone_target. A parallel list, exactly like `geometry` above and for the
    # same reason — check_reel.run stays callable from its own CLI, which has neither.
    # Constant across rounds: a reprocess re-renders with the SAME manifest, so the pair
    # it grades toward cannot move between rounds either.
    tone_dsts = [e.manifest.get("tone_dst") for e in rm.episodes]
    # Per-episode chroma displacement, for check_reel's advisory chroma_spread. A
    # parallel list like `geometry` and `tone_dsts` above, for the same reason —
    # check_reel.run stays callable from its own CLI, which has none of them. NOT
    # constant across rounds, unlike those two: a reprocess re-renders the episode
    # and check_episode measures it again, so the reprocess arm below replaces the
    # entry rather than letting a stale number outlive the clip it described.
    chroma = [e.chroma for e in rm.episodes]
    predicted = _predict(rm)
    need_assemble = True
    # A fit whose rung is "unchanged" chose nothing — the reel kept its footage-derived
    # length — so it must not block the absorb. .get with a default rather than [] :
    # OutroFit.from_dict (the manifest's shape/rung oracle) DEFAULTS a missing "rung"
    # to "unchanged" rather than refusing it, and never writes that normalized value
    # back into the raw dict ReelManifest stores as rm.outro — so the stored dict can
    # genuinely lack the key. The default here is load-bearing, not merely defensive:
    # it is what makes a dict with no "rung" at all degrade to today's behaviour
    # instead of raising a bare KeyError.
    outro_fixed = (rm.outro is not None
                   and rm.outro.get("rung", "unchanged") != "unchanged")
    for _ in range(rm.cap * len(rm.episodes) + 3):   # defensive bound; +3 leaves headroom for the
                                                     # once-after-picture mix `continue`, one
                                                     # length-retime `continue`, and the deliver pass
        if need_assemble:
            assembly.assemble(clips, dims, fps, master)
            need_assemble = False
        report = check_reel.run(master, clips, spec, report_path,
                                music=music, audio=audio, geometry=geometry,
                                platform=rm.platform, outro=rm.outro,
                                predicted=predicted,
                                tone_target=rm.tone_target, tone_dsts=tone_dsts,
                                brief_len=rm.brief_len, chroma=chroma)
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap,
                                                spec.length_retime_max, outro_fixed)
        if action.retime is not None:      # absorb a within-band shortfall: the reel IS this long
            _log(f"build_reel: reel is {action.retime:.2f}s against a {spec.target_dur:.2f}s target "
                 f"— inside the {spec.length_retime_max:.2f}s band, re-timing the target to the "
                 f"reel's real length (the stem is already cut to the master, so audio stays in sync)")
            spec = dataclasses.replace(spec, target_dur=action.retime)
        if action.kind == "retime":
            continue                       # re-check with the re-timed target; clips unchanged,
                                           # need_assemble stays False so nothing is re-assembled
        if action.kind == "deliver":
            # design 2026-08-18 §2: the picture has converged, but loop-2 below may have
            # rewritten a clip AFTER episode_qc stamped its digest — and it writes to the
            # episode manifest's own out_path, which IS the file the verdict names, so
            # that verdict is about bytes that no longer exist. Refuse HERE, at the top of
            # the arm: before the stem, before deliver, before a version number is spent.
            # The remedy is a re-judge of exactly the named episodes, and the SECOND pass
            # delivers, because the corrected clips are already on disk where EPISODES.json
            # points (§2.2). Judged reels only — with no verdict there is nothing to
            # invalidate, and build_reel's own CLI must keep working (§2.1).
            reason, problems = qc_lib.reprocess_gate(
                (rm.provenance.get("episode_qc") or {}).get("state", ""), sorted(reprocessed))
            if reason:
                return {"status": "stop_and_report",
                        "finding": {"reason": reason, "episode_idx": None,
                                    "problems": problems},
                        "report": report.to_dict(), "reprocessed": sorted(reprocessed)}
            if music is not None and audio is None:  # picture passed → build the stem once, re-check with it
                want = rm.ambient or rm.sfx
                segments = ([(e.manifest["segment"], e.manifest["target_dur"]) for e in rm.episodes]
                            if want else None)
                # A look's fade is the ONE number both bookends use. No look → mix keeps
                # its own default; a look with fade=0 → the author asked for no bookend at
                # all, in the picture and in the sound (design 2026-08-13 §5).
                fade_kw = {} if rm.look is None else {"fade": rm.look.fade}
                audio = mix.mix(music, work_dir, check_reel._probe_dur(master),
                                segments=segments, ambient=rm.ambient, sfx=rm.sfx, **fade_kw)
                continue                             # need_assemble stays False — clips unchanged, no re-assemble
            # design §8: loop-2 re-renders culprits AFTER the QC gate ran, so a verdict on a
            # reprocessed episode is one render out of date the moment it is rebuilt. That
            # cannot be undone here, but it must not be hidden either — merge the set of
            # touched episodes into whatever episode_qc state edl_to_reel already assembled
            # (possibly nothing) so the attestation names exactly which ones.
            prov = dict(rm.provenance)
            qc = dict(prov.get("episode_qc") or {})
            # A manifest can reach here with no episode_qc block at all — build_reel's own
            # CLI reads an EPISODES.json directly, the same state-less bypass the
            # single-command edl_to_reel path closes by stamping "absent" (design §10/§12).
            # setdefault, not assignment: assemble_reel's two-phase path already stamped
            # "judged" before calling here, and that must survive the merge unclobbered.
            qc.setdefault("state", "absent")
            qc["reprocessed_after"] = sorted(reprocessed)
            prov["episode_qc"] = qc
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report,
                                  scratch_dir=work_dir,   # build/reel — never the deliveries bucket
                                  audio=audio, titles=titles, platform=rm.platform,
                                  look=rm.look, run_provenance=prov)
            return {"status": "delivered", "output": out, "report": report.to_dict(),
                    "reprocessed": sorted(reprocessed)}
        if action.kind == "escalate":
            return {"status": "stop_and_report", "finding": action.finding,
                    "report": report.to_dict(), "attempts": dict(attempts)}
        for item in action.reprocess:                # sequential: a reprocess batch is typically one
                                                     # or two culprits, so the fan-out's measured 1.70x
                                                     # (docs/specs/2026-07-18-cap3-fanout-design.md §2)
                                                     # has little to bite on here. Parallelising loop-2
                                                     # is deferred — NOT because one process_episode
                                                     # saturates the box; measured, it takes three.
            ep = rm.episodes[item.idx]
            # Beside the record it replaces, not under this driver's own work dir.
            # ReelEpisode is frozen and nothing rewrites EPISODES.json, so its
            # path/meta keep naming phase 1's directory — and a second directory is
            # a second record with nothing keeping the two in step. The clip already
            # has this property: it is overwritten in place, which is why a re-pack
            # reads fresh pixels beside a stale report, storyboard, geometry and
            # track record (design 2026-09-24 §0.7). Same derivation
            # episode_qc._epdir already uses, so the packet and the render agree on
            # where one episode's scratch lives.
            #
            # This deliberately writes OUTSIDE work_dir: in a two-phase run phase 1
            # owns build/ep{i} and this driver is handed build/reel, so "beside the
            # record" is always outside it, and a guard refusing that would refuse
            # the only case that matters.
            #
            # The empty-path arm is not defensive padding: ReelEpisode.path defaults
            # to "" and a hand-authored reel manifest may carry none, where
            # Path("").parent is Path(".") — the current working directory, silently.
            epdir = (str(Path(ep.path).parent) if ep.path
                     else str(Path(work_dir) / f"ep{item.idx}"))
            manifest = ep.manifest
            # A stabilized episode's frozen route was measured on loop-1's stabilized
            # pixels and would be safe to reuse — but process_episode refuses
            # stabilize + a supplied route (design 2026-07-20 §1) because nothing yet
            # records a route's pixel provenance, so it cannot tell this safe route
            # from a dangerous one. Re-track on the re-stabilized (deterministic)
            # segment instead: one YOLO pass on the rare reprocess path, the honest
            # price of not having the provenance bit. ReelEpisode.route stays
            # populated regardless — check_reel reads it, and raises for a tracked
            # (pan=false) episode whose route is None.
            route = None if manifest.get("stabilize") else ep.route
            res = process_episode.process_episode(manifest, epdir, route_path=route)
            # A REJECTED re-render is already on disk. reframe writes m.out_path before
            # check_episode.run reads it (process_episode.py), so this early return
            # leaves ep{i}.mp4 overwritten by the render that just failed, and skips the
            # reprocessed.add() below — the run stops with a clip nobody recorded as
            # touched. Not a silent bypass: episode_qc.gate's stale-digest arm refuses on
            # the next --from-episodes, because the clip no longer hashes to what was
            # judged. But nothing in this finding says a clip was rewritten (backlog row).
            if res["status"] != "mechanical_pass":
                return {"status": "stop_and_report",
                        "finding": {"reason": "reprocess-failed", "episode_idx": item.idx,
                                    "sub_status": res["status"]},
                        "sub": res, "attempts": dict(attempts)}
            clips[item.idx] = res["clip"]
            chroma[item.idx] = color_fidelity.shift_from_report(res.get("report") or {})
            attempts[item.idx] = attempts.get(item.idx, 0) + 1
            reprocessed.add(item.idx)
            need_assemble = True
    return {"status": "stop_and_report",             # defensive: next_action escalates a capped reel first
            "finding": {"reason": "reel-cap-exhausted"}, "attempts": dict(attempts)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="drive the reel retry loop → delivered reel | stop-and-report")
    ap.add_argument("reel_manifest", help="path to a reel manifest JSON (design §2)")
    ap.add_argument("--out-dir", required=True, help="delivery dir for REEL_v{n}")
    ap.add_argument("--work-dir", required=True, help="scratch for master/report + per-episode reprocess")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the reel (§5.16)")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    rm = ReelManifest.from_json(a.reel_manifest)
    result = build_reel(rm, a.out_dir, a.work_dir, titles=a.titles)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
