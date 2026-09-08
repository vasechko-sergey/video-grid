"""Per-episode QC driver (design docs/specs/2026-08-08-episode-qc-design.md §6/§7).

Two commands, both mechanical:
  pack   — one evidence directory per episode: a frame strip from the DELIVERED clip,
           the storyboard, the mechanical report, and the naturalness sensor's numbers.
  build  — validate each judge's raw findings into EPISODE_QC.json + .md, stamping the
           clip digest HERE (never from the judge's file, design §7).

Judgment belongs to the subagents skills/episode-qc dispatches; this module is their
typed sink. Mirror of reel_review.py — contract in lib, driver here."""
import argparse
import json
from pathlib import Path

from scripts import contact_sheet, probe, process_episode, reframe
from scripts.lib import assembly, color, naturalness, provenance
from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC
from scripts.lib.models import ReelManifest

FRAMES = 9           # strip cells per episode — enough to read a path across a 2-4s cut
# (k+0.5)/5 happens to produce check_episode.SAMPLE_FRACS' five fractions, but of a
# different quantity — clip duration here, route span there — and NOTHING ties the two.
# Either can move without the other noticing; no code depends on the agreement
# (design 2026-08-28 §9.9).
SENSOR_FRAMES = 5    # frames the naturalness sensor averages over


def _epdir(ep, i: int) -> Path:
    """process_episode writes route/path/report/storyboard into ONE directory per
    episode, and ReelEpisode.path names a file inside it — so the scratch dir is
    derived, never passed. A manifest with no sidecar (legal in the contract, and what
    a hand-authored reel manifest may carry) has none to derive, and is refused by
    name rather than guessed at."""
    if not ep.path:
        raise ValueError(f"episode {i} has no path sidecar, so its per-episode scratch "
                         f"(report.json, storyboard.jpg) cannot be located — pack the "
                         f"EPISODES.json a two-phase edl_to_reel wrote, not a hand-built one")
    return Path(ep.path).parent


def _evidence(ep, i: int, clip_stats: dict, strip: dict,
              clip_px: tuple[int, int]) -> dict:
    """What the judge reads besides the pixels. The episode's declared INTENT is in
    here deliberately: composition is judged against what this episode asked for, never
    against a global rule (design §6)."""
    d = _epdir(ep, i)
    m = ep.manifest
    storyboard = d / "storyboard.jpg"
    out: dict = {
        "idx": i, "clip": ep.clip,
        "intent": {k: m.get(k) for k in ("composition", "grid", "hero", "target_dur",
                                         "layout", "pan", "stabilize", "canvas")},
        # Absent is reported as absent, never as a path that resolves to nothing — the
        # same rule the loop below applies to the other three sidecars, and the one the
        # `hero` axis stands on (design §6): a judge must be able to tell "there was no
        # storyboard" from "there was one".
        "storyboard": str(storyboard) if storyboard.exists() else None,
        # The strip was never named here at all: its path reached the judge only
        # through the SKILL's template fill, so a reader of this file alone could not
        # tell whether one existed (design §3).
        "strip": strip["strip"],
        # The picture size of ONE frame, in each artifact. RENDERED, not what a
        # reader's own downsample leaves — the packet cannot know that. Reported,
        # never gated: there is nothing here to derive a "below X you cannot judge"
        # threshold from, and the point is that the judge can prefer the right
        # artifact and say which one it used (design §3).
        "strip_px": list(strip["cell_px"]),
        # storyboard.build pastes each sampled frame at FULL resolution, so one of its
        # cells IS the delivered clip's own frame — 129x the strip's area rendered,
        # 22x as read (design §0.2).
        "storyboard_px": [clip_px[0], clip_px[1]] if storyboard.exists() else None,
        "naturalness": clip_stats,
    }
    for name, key in (("report.json", "checks"), ("route.meta.json", "track"),
                      ("path.meta.json", "geometry")):
        p = d / name
        # Absent is reported as absent, never as an empty reading: a judge must be able
        # to tell "the tracker said nothing" from "there was no tracker".
        out[key] = json.loads(p.read_text()) if p.exists() else None
    return out


def _source_reading(ep, graded: dict) -> dict:
    """The episode's own source IN ITS OWN CROP, and the delta against the delivered
    clip (design 2026-08-31 §5).

    It used to measure a whole segment frame against a reframed crop of that frame —
    often 9:16 out of 16:9 — so the "delta" carried the crop as well as the grade.
    The ungraded render this slice added is exactly the source in the delivered
    geometry, which makes the two readings comparable for the first time: the
    branch's own test recorded source contrast 0.0 against graded 123.6 with no
    grade at all — that is a crop, not a grade.

    probe.source_for, not ep.manifest["segment"]: on a stabilized episode the two
    colour sensors used to describe changes from two different starting points
    (design 2026-08-28 §9.8, the backlog row this closes).

    A manifest whose source is gone — or too thin to plan a render from at all —
    reports both as None: absent is reported as absent, never as a clean reading,
    the same rule the rest of _evidence applies to the sidecars.

    The `Path(src).exists()` check is explicit and comes BEFORE plan_ungraded,
    not folded into the except clause: a segment path that names no file makes
    plan_ungraded reach reframe.plan_render's ffprobe, which fails through
    proc.run as a RuntimeError ("No such file or directory"), not a
    FileNotFoundError/KeyError/ValueError — measured directly against proc.run,
    not assumed. Catching RuntimeError here too would also swallow a genuinely
    broken ffmpeg install or a corrupt (but present) file, which is exactly the
    fail-loud case this function must NOT report as a quiet 'absent'."""
    md = dict(ep.manifest)
    try:
        src = probe.source_for(md, Path(ep.path).parent)
        if not Path(src).exists():
            return {"source": None, "delta": None}
        plan = process_episode.plan_ungraded(md, src, ep.route)
    except (FileNotFoundError, KeyError, ValueError):
        return {"source": None, "delta": None}
    frames = reframe.plan_frames_rgb(plan, src, color.sample_times(plan.dur, SENSOR_FRAMES))
    src_stats = naturalness.measure(frames)
    return {"source": src_stats, "delta": naturalness.evaluate_delta(src_stats, graded)}


def pack(episodes_path: str, out_dir: str, *, frames: int = FRAMES) -> dict:
    """Write one evidence directory per episode under out_dir. Returns a status dict."""
    rm = ReelManifest.from_json(episodes_path)
    for i, ep in enumerate(rm.episodes):
        _epdir(ep, i)          # every sidecar checked BEFORE any decode: a packet run that
                               # cannot finish must fail in ms, not after N episodes of ffmpeg
    packets = []
    for i, ep in enumerate(rm.episodes):
        d = Path(out_dir) / f"ep{i}"
        d.mkdir(parents=True, exist_ok=True)
        info = assembly.probe_stream(ep.clip)
        dur = assembly.probe_duration(ep.clip)
        strip = contact_sheet.build_strip(ep.clip, str(d / "strip.jpg"), start=0.0,
                                          dur=dur, frames=frames, fps=info.fps)
        times = color.sample_times(dur, SENSOR_FRAMES)
        stats = naturalness.measure(assembly.frames_rgb(ep.clip, times, info.fps))
        clip_stats = {"stats": stats, "flags": naturalness.evaluate(stats),
                      **_source_reading(ep, stats)}
        (d / "evidence.json").write_text(json.dumps(
            _evidence(ep, i, clip_stats, strip, (info.w, info.h)), indent=2))
        packets.append(str(d))
    return {"status": "packed", "episodes": len(packets), "packets": packets}


def _raw(packets: str, i: int) -> dict:
    p = Path(packets) / f"ep{i}" / "findings.json"
    if not p.exists():
        raise ValueError(f"episode {i} has no findings.json in {p.parent} — every episode "
                         f"must be judged before the reel is assembled; dispatch the "
                         f"episode-qc judge for it, or delete the packet and re-pack")
    # read_text can raise OSError of its own (a findings.json that is a directory, a
    # permission error); that is NOT caught here, deliberately — build_qc's call site
    # collects it alongside every other complaint rather than letting one packet's
    # filesystem trouble abort the other episodes.
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e}) — the judge writes "
                         f"{{'summary','reviewer','findings'}}") from e
    if not isinstance(d, dict):
        raise ValueError(f"{p}: expected a {{'summary','reviewer','findings'}} object, "
                         f"got {type(d).__name__}")
    return d


def build_qc(episodes_path: str, packets: str) -> ReelQC:
    """Validate every episode's raw findings into a typed ReelQC. The clip digest is
    computed HERE from the file on disk — whatever `clip_digest` the judge's file
    carries is ignored, which is what turns "this episode was judged" into "this
    RENDER was judged" (design 2026-08-08 §7).

    Every complaint from one run is collected and raised TOGETHER (design 2026-09-08
    §6). The judges have all exited by the time this runs, so raising on the first bad
    finding buys nothing about the other seven episodes and costs a whole round to
    learn about the second. The refusal's STRENGTH is unchanged: one bad packet still
    refuses the whole run, because EPISODE_QC.json describes the reel and a partial one
    would be a reel partly unjudged."""
    rm = ReelManifest.from_json(episodes_path)
    verdicts: list[EpisodeVerdict] = []
    problems: list[str] = []
    for i, ep in enumerate(rm.episodes):
        try:
            raw = _raw(packets, i)                 # read once: three reads = three failure surfaces
        except (ValueError, OSError) as e:
            problems.append(f"  ep{i}: {e}")
            continue
        findings = raw.get("findings") or []
        if not isinstance(findings, (tuple, list)):
            problems.append(f"  ep{i}: 'findings' must be a JSON list, got "
                            f"{type(findings).__name__}")
            continue
        built: list[EpisodeFinding] = []
        before = len(problems)
        for k, f in enumerate(findings):
            try:
                built.append(EpisodeFinding.from_dict(f))
            except ValueError as e:
                problems.append(f"  ep{i} finding {k}: {e}")
        if len(problems) != before:
            continue                               # a packet with a bad finding builds no verdict
        try:
            verdicts.append(EpisodeVerdict(
                idx=i, clip=ep.clip, clip_digest=provenance.digest_file(ep.clip),
                findings=tuple(built),
                summary=raw.get("summary") or "", reviewer=raw.get("reviewer") or ""))
        except (ValueError, OSError) as e:
            problems.append(f"  ep{i}: {e}")
    if problems:
        raise ValueError(
            f"episode_qc build: {len(problems)} complaint(s) across "
            f"{len(rm.episodes)} packets.\n" + "\n".join(problems)
            + "\nEvery complaint from this run is listed above, so one pass names them "
              "all. Fix or re-dispatch the judges named, then re-run build.")
    return ReelQC(episodes=tuple(verdicts))


def build(episodes_path: str, packets: str, out_dir: str) -> dict:
    """build_qc + write EPISODE_QC.json/.md into out_dir (the dir phase 2 looks in)."""
    qc = build_qc(episodes_path, packets)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    qj, qm = Path(out_dir) / "EPISODE_QC.json", Path(out_dir) / "EPISODE_QC.md"
    qc.write(qj)
    qm.write_text(qc.to_markdown())
    blocking = sum(1 for e in qc.episodes for f in e.findings if f.severity == "blocking")
    return {"status": "written", "verdict": "approve" if qc.ok else "revise",
            "episodes": len(qc.episodes), "blocking": blocking,
            "qc": str(qj), "md": str(qm)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="per-episode QC: pack the evidence, then validate the judges' findings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="one evidence dir per episode (strip + storyboard + numbers)")
    p.add_argument("--episodes", required=True, help="EPISODES.json from edl_to_reel --from-geometry (or --stop-after-episodes)")
    p.add_argument("--out-dir", required=True, help="dir for the ep{i}/ packet dirs")
    p.add_argument("--frames", type=int, default=FRAMES, help=f"strip cells per episode (default {FRAMES})")
    b = sub.add_parser("build", help="validate every judge's findings.json -> EPISODE_QC.json + .md")
    b.add_argument("--episodes", required=True, help="the same EPISODES.json")
    b.add_argument("--packets", required=True, help="the pack --out-dir holding ep{i}/findings.json")
    b.add_argument("--out-dir", required=True,
                   help="dir for EPISODE_QC.json/.md — must be the dir holding EPISODES.json")
    a = ap.parse_args()
    result = (pack(a.episodes, a.out_dir, frames=a.frames) if a.cmd == "pack"
              else build(a.episodes, a.packets, a.out_dir))
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
