"""Reel retry-loop driver (design §5, Phase A.5). Consumes a ReelManifest of
locked episode clips and loops assemble → check_reel → reprocess the culprit via
process_episode → until the reel passes and delivers, or stops with a precise
machine-readable finding. Mirrors process_episode.py: the editorial judgment ran
per-episode in loop-1; this shell owns only the mechanical reel loop.
Deterministic for a non-stabilized episode — a reprocess reuses its frozen
route, so the only thing that changes between rounds is the compounded colour
factor. A stabilized episode re-tracks instead: its frozen route's pixel
provenance cannot be proven (nothing yet records whether a route was measured
on raw or stabilized pixels), so process_episode refuses the combination and
this module withholds the route rather than risk replaying it against the
wrong coordinate system (design 2026-07-20 §1)."""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

from scripts import check_reel, deliver, mix, process_episode
from scripts.lib import assembly, reel_orchestration
from scripts.lib.color import corrected
from scripts.lib.models import ReelManifest, MusicSpec, REEL_H264


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _compound(prev: tuple[float, float, float], ratio: tuple[float, float, float]) -> tuple[float, float, float]:
    """Compound a per-round colour ratio onto the stored absolute factor, clamped to
    the grade's soft band [LO, HI] (design §4). Compounding (not per-round-relative)
    is what makes the correction converge instead of revert. Delegates to
    color.corrected — the same clamp-compose primitive the base grade uses."""
    return corrected(prev, ratio)


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
    cc: dict[int, tuple[float, float, float]] = {}
    spec = rm.check_spec          # mutable across rounds: a length re-time replaces target_dur
    audio: str | None = None
    geometry = ([(e.route, e.path, e.meta) for e in rm.episodes]   # frozen sidecars — constant across rounds
                if all(e.path and e.meta for e in rm.episodes) else None)
    need_assemble = True
    # A fit whose rung is "unchanged" chose nothing — the reel kept its footage-derived
    # length — so it must not block the absorb. .get with a default rather than [] : the
    # manifest's own validation already guarantees the key, and if that ever regresses,
    # degrading to today's behaviour beats stopping a deliverable reel.
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
                                platform=rm.platform, outro=rm.outro)
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
            # black item (ratio None) adds no new correction but must NOT reset cc — the episode
            # keeps its standing colour factor, else a black fix reverts colour and flip-flops
            if item.color_correct is not None:
                cc[item.idx] = _compound(cc.get(item.idx, (1.0, 1.0, 1.0)), item.color_correct)
            epdir = str(Path(work_dir) / f"ep{item.idx}")
            manifest = rm.episodes[item.idx].manifest
            # A stabilized episode's frozen route was measured on loop-1's stabilized
            # pixels and would be safe to reuse — but process_episode refuses
            # stabilize + a supplied route (design 2026-07-20 §1) because nothing yet
            # records a route's pixel provenance, so it cannot tell this safe route
            # from a dangerous one. Re-track on the re-stabilized (deterministic)
            # segment instead: one YOLO pass on the rare reprocess path, the honest
            # price of not having the provenance bit. ReelEpisode.route stays
            # populated regardless — check_reel reads it, and raises for a tracked
            # (pan=false) episode whose route is None.
            route = None if manifest.get("stabilize") else rm.episodes[item.idx].route
            res = process_episode.process_episode(
                manifest, epdir, route_path=route, color_correct=cc.get(item.idx))
            if res["status"] != "mechanical_pass":
                return {"status": "stop_and_report",
                        "finding": {"reason": "reprocess-failed", "episode_idx": item.idx,
                                    "sub_status": res["status"]},
                        "sub": res, "attempts": dict(attempts)}
            clips[item.idx] = res["clip"]
            attempts[item.idx] = attempts.get(item.idx, 0) + 1
            reprocessed.add(item.idx)
            need_assemble = True
    return {"status": "stop_and_report",             # defensive: next_action escalates a capped reel first
            "finding": {"reason": "reel-cap-exhausted"}, "attempts": dict(attempts)}


def main() -> None:
    ap = argparse.ArgumentParser(description="drive the reel retry loop → delivered reel | stop-and-report")
    ap.add_argument("reel_manifest", help="path to a reel manifest JSON (design §2)")
    ap.add_argument("--out-dir", required=True, help="delivery dir for REEL_v{n}")
    ap.add_argument("--work-dir", required=True, help="scratch for master/report + per-episode reprocess")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the reel (§5.16)")
    a = ap.parse_args()
    rm = ReelManifest.from_json(a.reel_manifest)
    result = build_reel(rm, a.out_dir, a.work_dir, titles=a.titles)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
