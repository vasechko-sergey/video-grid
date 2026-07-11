"""Reel retry-loop driver (design §5, Phase A.5). Consumes a ReelManifest of
locked episode clips and loops assemble → check_reel → reprocess the culprit via
process_episode → until the reel passes and delivers, or stops with a precise
machine-readable finding. Mirrors process_episode.py: the editorial judgment ran
per-episode in loop-1; this shell owns only the mechanical reel loop.
Deterministic — a reprocess reuses the episode's frozen route, so the only thing
that changes between rounds is the compounded colour factor."""
import argparse
import json
from pathlib import Path

from scripts import check_reel, deliver, process_episode
from scripts.lib import assembly, reel_orchestration
from scripts.lib.color import corrected
from scripts.lib.models import ReelManifest, REEL_H264


def _compound(prev: tuple[float, float, float], ratio: tuple[float, float, float]) -> tuple[float, float, float]:
    """Compound a per-round colour ratio onto the stored absolute factor, clamped to
    the grade's soft band [LO, HI] (design §4). Compounding (not per-round-relative)
    is what makes the correction converge instead of revert. Delegates to
    color.corrected — the same clamp-compose primitive the base grade uses."""
    return corrected(prev, ratio)


def build_reel(rm: ReelManifest, out_dir: str, work_dir: str) -> dict:
    """Drive rm's locked clips to a delivered reel or a stop-and-report finding."""
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    clips = [e.clip for e in rm.episodes]
    si = assembly.probe_stream(clips[0])          # actual delivered dims/fps (episodes uniform by construction)
    dims, fps = (si.w, si.h), si.fps
    master = str(Path(work_dir) / "master.mp4")
    report_path = str(Path(work_dir) / "reel_report.json")
    attempts: dict[int, int] = {}
    cc: dict[int, tuple[float, float, float]] = {}
    for _ in range(rm.cap * len(rm.episodes) + 1):   # defensive bound; next_action is the real terminator
        assembly.assemble(clips, dims, fps, master)
        report = check_reel.run(master, clips, rm.check_spec, report_path)
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap)
        if action.kind == "deliver":
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report)
            return {"status": "delivered", "output": out, "report": report.to_dict()}
        if action.kind == "escalate":
            return {"status": "stop_and_report", "finding": action.finding,
                    "report": report.to_dict(), "attempts": dict(attempts)}
        for item in action.reprocess:                # sequential — one process_episode saturates the box
            # black item (ratio None) adds no new correction but must NOT reset cc — the episode
            # keeps its standing colour factor, else a black fix reverts colour and flip-flops
            if item.color_correct is not None:
                cc[item.idx] = _compound(cc.get(item.idx, (1.0, 1.0, 1.0)), item.color_correct)
            epdir = str(Path(work_dir) / f"ep{item.idx}")
            res = process_episode.process_episode(
                rm.episodes[item.idx].manifest, epdir,
                route_path=rm.episodes[item.idx].route, color_correct=cc.get(item.idx))
            if res["status"] != "mechanical_pass":
                return {"status": "stop_and_report",
                        "finding": {"reason": "reprocess-failed", "episode_idx": item.idx,
                                    "sub_status": res["status"]},
                        "sub": res, "attempts": dict(attempts)}
            clips[item.idx] = res["clip"]
            attempts[item.idx] = attempts.get(item.idx, 0) + 1
    return {"status": "stop_and_report",             # defensive: next_action escalates a capped reel first
            "finding": {"reason": "reel-cap-exhausted"}, "attempts": dict(attempts)}


def main() -> None:
    ap = argparse.ArgumentParser(description="drive the reel retry loop → delivered reel | stop-and-report")
    ap.add_argument("reel_manifest", help="path to a reel manifest JSON (design §2)")
    ap.add_argument("--out-dir", required=True, help="delivery dir for REEL_v{n}")
    ap.add_argument("--work-dir", required=True, help="scratch for master/report + per-episode reprocess")
    a = ap.parse_args()
    rm = ReelManifest.from_json(a.reel_manifest)
    result = build_reel(rm, a.out_dir, a.work_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
