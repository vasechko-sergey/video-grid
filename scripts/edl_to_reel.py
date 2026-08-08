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
from scripts.lib import episode_qc as qc_lib, hero as hero_lib, provenance, reid
from scripts.lib.edl import EDL, preflight
from scripts.lib.episode_qc import ReelQC
from scripts.lib.footage import Cast
from scripts.lib.models import ReelEpisode, ReelManifest
from scripts.lib.project import ProjectConfig

DEFAULT_JOBS = 3      # measured knee (design §2): cap 4 buys nothing and costs latency


def _build_manifest(edl_path: str, project_path: str, footage_root: str,
                    work_dir: str, out_dir: str, *, music: str | None = None,
                    jobs: int = DEFAULT_JOBS, color_delta_max: float | None = None,
                    changelog: str = "") -> tuple[ReelManifest | None, dict | None]:
    """Everything up to the ReelManifest: preflight, extract, the loop-1 fan-out, the
    run provenance. Returns (rm, None) or (None, stop_and_report).

    Setup/IO errors — missing footage, a window running past EOF, unreadable JSON —
    raise ValueError instead (a hard setup error, not an editorial finding to route).

    `color_delta_max` overrides the across-cut mean-RGB ceiling (ReelCheckSpec's own
    default stands when None). The default guards GRADE consistency within one scene;
    a reel that deliberately cuts between scenes of different exposure — open water to
    a bright beach — carries a real jump the grade cannot and should not flatten. Raise
    it only for such a reel, with the measured delta in hand, never to silence a grade
    that is genuinely wrong."""
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"edl_to_reel: jobs must be an integer >= 1, got {jobs!r} "
                         f"(default {DEFAULT_JOBS} is the measured knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU)")
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    # #11 — a montage run must not straddle an engine change. project.json records the
    # engine at run START; if the code has moved since, the stages already finished were
    # produced by different code and this reel would be a chimera of two engines. An
    # UNKNOWN stamp on either side cannot prove drift and never stops the run (design §7);
    # neither does an absent one, which is a run started before this existed.
    started = cfg.provenance.get("engine") or {}
    now = provenance.engine_stamp()
    if started.get("sha") and now.get("sha") and started != now:
        raise ValueError(
            f"the engine changed since this run started (project.json records "
            f"{started['sha']} {'dirty' if started.get('dirty') else 'clean'}, now "
            f"{now['sha']} {'dirty' if now.get('dirty') else 'clean'}) — a montage run must "
            f"not straddle an engine change, because the stages already finished were "
            f"produced by different code. Start a fresh run dir, or re-run project_init "
            f"against the current engine to re-baseline")
    seg_dir = str(Path(work_dir) / "segments")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # 1. resolve + preflight every episode — fail in ms, before any ffmpeg
    mds, stop = preflight(edl, cfg, seg_dir, out_dir)
    if stop:
        return None, stop

    # 2. extract every window (paths match the seg_dir/ep{i}_raw.mp4 the bridge used)
    extract.extract_edl(edl, footage_root, seg_dir)

    # 3. loop-1 fan-out: one process_episode per episode, up to `jobs` concurrently.
    # Safe to parallelise because each episode owns its scratch (work_dir/ep{i}) and its
    # output (out_dir/ep{i}.mp4) — process_episode's docstring names the clobber this
    # would otherwise cause, and preflight built both paths per index.
    for model in sorted({(md.get("model") or track.MODEL) for md in mds}):
        track.ensure_model(model)      # before ANY worker: N cold workers would race the
                                       # same weights download into the same path (§5)
    # Same weights-race, the OTHER model: a cast-identity pin drives process_episode ->
    # track.build_route -> reid.embed -> a cold OSNet weight download, and N cold workers
    # would race it into the same path — the concurrent-writer landmine track.ensure_model
    # above already closes for YOLO (design 2026-08-04 §3.1/§10). Guarded so a scenery reel
    # never forces the heavy torchreid import or a needless model build: warm ONLY when some
    # episode actually resolves to a cast pin (tested first — the resolve is pure) AND reID
    # is installed. The resolve mirrors process_episode's own — cheap, idempotent, and
    # guaranteed not to raise here because preflight already validated every pin against
    # this same registry (a bad name/descriptor would have returned a stop above).
    cast = Cast.from_json(edl.cast) if edl.cast is not None else None
    pins = (hero_lib.resolve(md.get("hero"), cast) for md in mds)
    if any(p is not None and p.kind == "cast" for p in pins) and reid.available():
        reid.ensure_model()
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(process_episode.process_episode, md,
                             str(Path(work_dir) / f"ep{i}"))   # md already resolved → no project=
                   for i, md in enumerate(mds)]
    # the `with` block joined every worker, so each future below is already done and this
    # ONE loop reads them in index order — no dependence on completion order anywhere.
    #
    # One pass, not two. An episode can fail through either channel (a raised setup error
    # or a returned non-pass status), and the two must be ordered AGAINST EACH OTHER, not
    # each within itself: draining every exception first would let a raise at episode 2
    # beat a routable stop_and_report at episode 0 — which the sequential loop returned
    # before it ever reached episode 2. Whichever problem sits at the lowest index wins,
    # whatever kind it is; that is what makes the finding identical to the sequential one.
    episodes: list[ReelEpisode] = []
    for i, (md, fut) in enumerate(zip(mds, futures, strict=True)):
        try:
            res = fut.result()
        except Exception as e:         # a hard setup error stays an exception, per the docstring
            e.add_note(f"raised while processing episode {i} (segment {md['segment']})")
            raise
        if res.get("status") != "mechanical_pass":
            return None, {"status": "stop_and_report",
                          "finding": {"reason": "episode-failed", "episode_idx": i,
                                      "sub_status": res.get("status")}, "sub": res}
        epdir = str(Path(work_dir) / f"ep{i}")
        # A pan episode has no route.json — process_episode wrote none, deliberately.
        # Naming a path that was never written would be a lie the reel manifest then
        # carries around; None states the absence. check_reel does not depend on this
        # (it branches on the meta sidecar's provenance bit, which is what actually
        # happened rather than what a caller remembered to pass) — this is the
        # contract telling the truth, not the crash fix.
        episodes.append(ReelEpisode(
            manifest=md, clip=res["clip"],
            route=None if md.get("pan") is not None else str(Path(epdir) / "route.json"),
            path=str(Path(epdir) / "path.json"),
            meta=str(Path(epdir) / "path.meta.json")))

    # 4. loop-2: assemble the ReelManifest and drive build_reel
    target = edl.target_dur if edl.target_dur is not None else sum(ep.dur for ep in edl.episodes)
    extra = {} if color_delta_max is None else {"color_delta_max": color_delta_max}
    # #16: this argument is the version-log NOTE, not the log's path. Passing
    # str(out_dir/"VERSIONS.md") here is what made 12 of 13 entries in a real run's
    # VERSIONS.md log the file's own path instead of the reason for the version.
    note = changelog or f"delivered from {Path(edl_path).name}"
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=note, music=music or edl.music, **extra)
    # The run's record, assembled where all three parts are in hand (design §6). The
    # override list is a DIFF of the effective check spec against a default one, so a
    # threshold added to ReelCheckSpec later is covered without touching this line.
    rm.provenance = {"edl": {"digest": edl.provenance.get("self", ""),
                             # Same predicate provenance.check() uses (block.get("self")),
                             # not plain dict truthiness — a hand-authored provenance object
                             # with no "self" key is "unstamped" to check() (from_json rightly
                             # admits it), and the attestation must record that SAME judgement
                             # rather than re-derive a different one that can drift from it.
                             "state": "intact" if edl.provenance.get("self") else "unstamped"},
                     "engine_at_start": started,
                     "overrides": provenance.spec_overrides(rm.check_spec)}
    return rm, None


def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, *, music: str | None = None,
                titles: str | None = None, jobs: int = DEFAULT_JOBS,
                color_delta_max: float | None = None, changelog: str = "") -> dict:
    """The SP1 front door: a hand-authored EDL.json -> a delivered REEL_v1.mp4 in one
    command. No per-episode QC runs on this path — the delivery's attestation records
    `episode_qc: absent` so an unjudged reel is DISTINGUISHABLE from a judged one, which
    is the honest half of the gate (design §10): no silent bypass, not no bypass."""
    rm, stop = _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir,
                               music=music, jobs=jobs, color_delta_max=color_delta_max,
                               changelog=changelog)
    if stop:
        return stop
    rm.provenance["episode_qc"] = {"state": "absent"}
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"), titles=titles)


def process_episodes(edl_path: str, project_path: str, footage_root: str,
                     work_dir: str, out_dir: str, *, music: str | None = None,
                     jobs: int = DEFAULT_JOBS, color_delta_max: float | None = None,
                     changelog: str = "") -> dict:
    """Phase 1: render every episode, then STOP. Writes EPISODES.json (a serialized
    ReelManifest) beside the ep{i}.mp4 it describes, so the verdicts and the judged
    clips cannot be separated (design §3)."""
    rm, stop = _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir,
                               music=music, jobs=jobs, color_delta_max=color_delta_max,
                               changelog=changelog)
    if stop:
        return stop
    p = Path(out_dir) / "EPISODES.json"
    rm.write(p)
    return {"status": "episodes_ready", "episodes": str(p), "count": len(rm.episodes),
            "clips": [e.clip for e in rm.episodes]}


def assemble_reel(episodes_path: str, work_dir: str, *, titles: str | None = None) -> dict:
    """Phase 2: the QC gate, then build_reel. The out dir is EPISODES.json's own
    directory — one fewer flag to point at the wrong place, and the gate's artifact is
    found there BY CONVENTION (design §3/§7).

    Every refusal below happens before a single ffmpeg call and writes nothing."""
    rm = ReelManifest.from_json(episodes_path)
    out_dir = str(Path(episodes_path).parent)
    qc_path = Path(out_dir) / "EPISODE_QC.json"
    if not qc_path.exists():
        return {"status": "stop_and_report",
                "finding": {"reason": "episode-qc-missing", "episode_idx": None,
                            "problems": [
                                f"no EPISODE_QC.json beside {episodes_path} — every episode "
                                f"must be judged before the reel is assembled: run "
                                f"`episode_qc pack`, dispatch the episode-qc judges, then "
                                f"`episode_qc build`"]}}
    qc = ReelQC.from_json(qc_path)
    digests = {i: provenance.digest_file(ep.clip) for i, ep in enumerate(rm.episodes)}
    reason, problems = qc_lib.gate(qc, digests)
    if reason:
        return {"status": "stop_and_report",
                "finding": {"reason": reason, "episode_idx": None, "problems": problems}}
    prov = dict(rm.provenance)
    prov["episode_qc"] = {"state": "judged",
                          "judged": {str(i): d for i, d in sorted(digests.items())}}
    rm.provenance = prov
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"), titles=titles)


def main() -> None:
    ap = argparse.ArgumentParser(description="drive a hand-authored EDL.json → delivered REEL_v1.mp4")
    ap.add_argument("edl", nargs="?", default=None,
                    help="path to an EDL.json (omit with --from-episodes)")
    ap.add_argument("--project", default=None, help="project.json — episodes inherit canvas/delivery")
    ap.add_argument("--footage-root", default=None, help="dir the EDL 'source' paths resolve against")
    ap.add_argument("--work-dir", required=True, help="scratch for segments / per-episode / reel master")
    ap.add_argument("--out-dir", required=True, help="delivery dir for ep{i}.mp4 + REEL_v{n}.mp4")
    ap.add_argument("--music", default=None, help="MUSIC.json path; overrides the EDL's music field")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the reel (§5.16)")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"episodes to process concurrently (default {DEFAULT_JOBS} — the "
                         f"measured knee; lower on a memory-constrained box)")
    ap.add_argument("--color-delta-max", type=float,
                    help="across-cut mean-RGB ceiling (default 12.0). Raise ONLY for a reel "
                         "that deliberately cuts between scenes of different exposure "
                         "(open water -> bright beach), with the measured delta in hand")
    ap.add_argument("--changelog", default="",
                    help="version-log note for this delivery — the REASON for the version "
                         "(e.g. 'regraded ep1'), not a path; defaults to 'delivered from <EDL>'")
    phase = ap.add_mutually_exclusive_group()
    phase.add_argument("--stop-after-episodes", action="store_true",
                       help="render every episode, write EPISODES.json, and stop — the "
                            "seam the per-episode QC gate sits in (design 2026-08-08)")
    phase.add_argument("--from-episodes", default=None,
                       help="an EPISODES.json from --stop-after-episodes: gate on "
                            "EPISODE_QC.json beside it, then assemble and deliver")
    a = ap.parse_args()
    if a.from_episodes:
        if a.edl or a.project or a.footage_root:
            ap.error("--from-episodes resumes a run whose episodes are already rendered; "
                     "the EDL / --project / --footage-root are not read again")
        result = assemble_reel(a.from_episodes, a.work_dir, titles=a.titles)
    else:
        missing = [n for n, v in (("edl", a.edl), ("--project", a.project),
                                  ("--footage-root", a.footage_root)) if not v]
        if missing:
            ap.error(f"missing {', '.join(missing)} — required unless --from-episodes is given")
        fn = process_episodes if a.stop_after_episodes else edl_to_reel
        kw = {} if a.stop_after_episodes else {"titles": a.titles}
        result = fn(a.edl, a.project, a.footage_root, a.work_dir, a.out_dir,
                    music=a.music, jobs=a.jobs, color_delta_max=a.color_delta_max,
                    changelog=a.changelog, **kw)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] in ("delivered", "episodes_ready") else 1)


if __name__ == "__main__":
    main()
