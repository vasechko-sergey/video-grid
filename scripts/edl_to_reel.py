"""Front-half SP1 driver (design docs/specs/2026-07-11-extract-spine-design.md):
a hand-authored EDL.json → a delivered REEL_v1.mp4. Extract every window, run
process_episode per episode across a bounded thread pool (`jobs`, default 3 — the
measured knee, see docs/specs/2026-07-18-cap3-fanout-design.md §2), assemble a
ReelManifest, then hand off to build_reel (loop-2). Every episode runs even when an
earlier one fails; the reported finding is chosen by INDEX, so it never depends on
thread scheduling. Canvas/delivery are resolved ONCE here and stored in each
ReelEpisode, because build_reel's reprocess re-runs process_episode without project=."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import build_reel, extract, process_episode, track
from scripts.lib.edl import EDL, preflight
from scripts.lib.models import ReelEpisode, ReelManifest
from scripts.lib.project import ProjectConfig

DEFAULT_JOBS = 3      # measured knee (design §2): cap 4 buys nothing and costs latency


def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, *, music: str | None = None,
                titles: str | None = None, jobs: int = DEFAULT_JOBS) -> dict:
    """Drive EDL.json → a delivered REEL_v1.mp4, or a machine-readable stop-and-report
    for a pipeline finding (invalid EDL, a failed episode, or a build_reel stop).
    Setup/IO errors — missing footage, a window running past EOF, unreadable JSON —
    raise ValueError instead (a hard setup error, not an editorial finding to route)."""
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"edl_to_reel: jobs must be an integer >= 1, got {jobs!r} "
                         f"(default {DEFAULT_JOBS} is the measured knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU)")
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    seg_dir = str(Path(work_dir) / "segments")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # 1. resolve + preflight every episode — fail in ms, before any ffmpeg
    mds, stop = preflight(edl, cfg, seg_dir, out_dir)
    if stop:
        return stop

    # 2. extract every window (paths match the seg_dir/ep{i}_raw.mp4 the bridge used)
    extract.extract_edl(edl, footage_root, seg_dir)

    # 3. loop-1 fan-out: one process_episode per episode, up to `jobs` concurrently.
    # Safe to parallelise because each episode owns its scratch (work_dir/ep{i}) and its
    # output (out_dir/ep{i}.mp4) — process_episode's docstring names the clobber this
    # would otherwise cause, and preflight built both paths per index.
    for model in sorted({(md.get("model") or track.MODEL) for md in mds}):
        track.ensure_model(model)      # before ANY worker: N cold workers would race the
                                       # same weights download into the same path (§5)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(process_episode.process_episode, md,
                             str(Path(work_dir) / f"ep{i}"))   # md already resolved → no project=
                   for i, md in enumerate(mds)]
    # the `with` block joined every worker, so each future below is already done and the
    # loop reads them IN INDEX ORDER — no dependence on completion order anywhere.
    results: list[dict] = []
    for i, fut in enumerate(futures):
        try:
            results.append(fut.result())
        except Exception as e:         # a hard setup error stays an exception, per the docstring
            e.add_note(f"raised while processing episode {i} (segment {mds[i]['segment']})")
            raise
    episodes: list[ReelEpisode] = []
    for i, (md, res) in enumerate(zip(mds, results, strict=True)):
        if res.get("status") != "mechanical_pass":
            return {"status": "stop_and_report",
                    "finding": {"reason": "episode-failed", "episode_idx": i,
                                "sub_status": res.get("status")}, "sub": res}
        epdir = str(Path(work_dir) / f"ep{i}")
        episodes.append(ReelEpisode(manifest=md, clip=res["clip"],
                                    route=str(Path(epdir) / "route.json"),
                                    path=str(Path(epdir) / "path.json"),
                                    meta=str(Path(epdir) / "path.meta.json")))

    # 4. loop-2: assemble the ReelManifest and drive build_reel
    target = edl.target_dur if edl.target_dur is not None else sum(ep.dur for ep in edl.episodes)
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=str(Path(out_dir) / "VERSIONS.md"), music=music or edl.music)
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"), titles=titles)


def main() -> None:
    ap = argparse.ArgumentParser(description="drive a hand-authored EDL.json → delivered REEL_v1.mp4")
    ap.add_argument("edl", help="path to an EDL.json (design docs/specs/2026-07-11-extract-spine-design.md)")
    ap.add_argument("--project", required=True, help="project.json — episodes inherit its canvas/delivery")
    ap.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    ap.add_argument("--work-dir", required=True, help="scratch for segments / per-episode / reel master")
    ap.add_argument("--out-dir", required=True, help="delivery dir for ep{i}.mp4 + REEL_v{n}.mp4")
    ap.add_argument("--music", default=None, help="MUSIC.json path; overrides the EDL's music field")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the reel (§5.16)")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"episodes to process concurrently (default {DEFAULT_JOBS} — the "
                         f"measured knee; lower on a memory-constrained box)")
    a = ap.parse_args()
    result = edl_to_reel(a.edl, a.project, a.footage_root, a.work_dir, a.out_dir,
                         music=a.music, titles=a.titles, jobs=a.jobs)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
