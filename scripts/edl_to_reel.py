"""Front-half SP1 driver (design docs/specs/2026-07-11-extract-spine-design.md):
a hand-authored EDL.json → a delivered REEL_v1.mp4. The thin SEQUENTIAL loop-1
fan-out — extract every window, run process_episode per episode, assemble a
ReelManifest — then hand off to build_reel (loop-2). The cap-3 PARALLEL router +
episode-choice curation (montage §5.1) is a later optimization that wraps this.
Canvas/delivery are resolved ONCE here and stored in each ReelEpisode, because
build_reel's reprocess re-runs process_episode without project=."""
import argparse
import json
from pathlib import Path

from scripts import build_reel, extract, process_episode
from scripts.lib import manifest as manifest_lib
from scripts.lib.edl import EDL, to_manifest_dict
from scripts.lib.models import ReelEpisode, ReelManifest
from scripts.lib.project import ProjectConfig, resolve_manifest


def _stop(reason: str, idx: int, **extra) -> dict:
    return {"status": "stop_and_report", "finding": {"reason": reason, "episode_idx": idx, **extra}}


def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, music: str | None = None) -> dict:
    """Drive EDL.json → REEL_v1.mp4, or a machine-readable stop-and-report."""
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    seg_dir = str(Path(work_dir) / "segments")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # 1. bridge + resolve + preflight — fail in ms, before any ffmpeg (mirrors the layouts plan)
    mds: list[dict] = []
    for i, ep in enumerate(edl.episodes):
        seg = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        md = resolve_manifest(to_manifest_dict(ep, seg, str(Path(out_dir) / f"ep{i}.mp4")), cfg)
        try:
            m = manifest_lib.Manifest.from_dict(md)
        except (KeyError, TypeError, ValueError) as e:
            return _stop("edl-invalid", i, problems=[str(e)])
        problems = manifest_lib.validate(m)
        if problems:
            return _stop("edl-invalid", i, problems=problems)
        mds.append(md)

    # 2. extract every window (paths match the seg_dir/ep{i}_raw.mp4 the bridge used)
    extract.extract_edl(edl, footage_root, seg_dir)

    # 3. loop-1 fan-out: one process_episode per episode (sequential)
    episodes: list[ReelEpisode] = []
    for i, md in enumerate(mds):
        epdir = str(Path(work_dir) / f"ep{i}")
        res = process_episode.process_episode(md, epdir)   # md already resolved → no project= needed
        if res.get("status") != "mechanical_pass":
            return {"status": "stop_and_report",
                    "finding": {"reason": "episode-failed", "episode_idx": i,
                                "sub_status": res.get("status")}, "sub": res}
        episodes.append(ReelEpisode(manifest=md, clip=res["clip"],
                                    route=str(Path(epdir) / "route.json")))

    # 4. loop-2: assemble the ReelManifest and drive build_reel
    target = edl.target_dur if edl.target_dur is not None else sum(ep.dur for ep in edl.episodes)
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=str(Path(out_dir) / "VERSIONS.md"), music=music or edl.music)
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"))


def main() -> None:
    ap = argparse.ArgumentParser(description="drive a hand-authored EDL.json → delivered REEL_v1.mp4")
    ap.add_argument("edl", help="path to an EDL.json (design docs/specs/2026-07-11-extract-spine-design.md)")
    ap.add_argument("--project", required=True, help="project.json — episodes inherit its canvas/delivery")
    ap.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    ap.add_argument("--work-dir", required=True, help="scratch for segments / per-episode / reel master")
    ap.add_argument("--out-dir", required=True, help="delivery dir for ep{i}.mp4 + REEL_v{n}.mp4")
    ap.add_argument("--music", default=None, help="MUSIC.json path; overrides the EDL's music field")
    a = ap.parse_args()
    result = edl_to_reel(a.edl, a.project, a.footage_root, a.work_dir, a.out_dir, music=a.music)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
