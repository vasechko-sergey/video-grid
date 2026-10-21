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
from scripts.lib import assembly, color, naturalness, prompts, provenance, userdirs
from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC
from scripts.lib.models import ReelManifest

FRAMES = 9           # strip cells per episode — enough to read a path across a 2-4s cut
# Independent of every other sample count in the tree. The coincidence design
# 2026-08-28 §9.9 recorded — these five fractions equalling check_episode's
# SAMPLE_FRACS — retired with that constant on 2026-09-16, when the grade
# description moved onto the render pair's own color.sample_times.
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
        # What these pixels ARE (design 2026-09-09 §4). The verdict has carried a
        # clip digest since 2026-08-08 and the packet never did, so a re-render
        # between pack and judge left the judge reading one render while its verdict
        # was stamped against another — which is what happened on the real run, and
        # only a judge's own blocking verdict caught it.
        "clip_digest": provenance.digest_file(ep.clip),
        "intent": {k: m.get(k) for k in ("composition", "grid", "hero", "target_dur",
                                         "layout", "pan", "stabilize", "still",
                                         "canvas")},
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
    unreadable: dict[str, str] = {}
    for name, key in (("report.json", "checks"), ("route.meta.json", "track"),
                      ("path.meta.json", "geometry")):
        p = d / name
        # Absent is reported as absent, never as an empty reading: a judge must be able
        # to tell "the tracker said nothing" from "there was no tracker".
        if not p.exists():
            out[key] = None
            continue
        try:
            out[key] = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            # A THIRD state the two above never anticipated: present and unparseable,
            # which a render that died mid-write leaves behind. It used to propagate
            # out of pack() and cost every LATER episode its packet — the same crash
            # _source_reading's own guard was added to prevent, reached two lines
            # further down the same iteration. The reading is None like an absent
            # sidecar, because there is no reading; the distinction the judge needs
            # rides in `unreadable` rather than in a sentinel inside `out[key]`, where
            # it could not be told apart from a sidecar that genuinely carries that
            # shape. build_qc's own loop already collects per-episode complaints
            # instead of aborting; this is the same choice one stage earlier.
            out[key] = None
            unreadable[name] = str(e)
    if unreadable:
        # Emitted only when non-empty, so every packet written before this existed
        # stays byte-identical.
        out["unreadable"] = unreadable
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
    fail-loud case this function must NOT report as a quiet 'absent'.

    Since 2026-09-24 the plan carries the params the render RECORDED
    (process_episode.rendered_params off ep.meta) and is checked against the frozen
    sidecars before anything is decoded. Absence is reported for a plan that cannot
    be shown to be the shipped geometry — a number read through the wrong crop is
    worse than no number, because the judge cannot tell it from a real one."""
    md = dict(ep.manifest)
    # The frozen sidecar first, on its own. rendered_params raises RuntimeError for a
    # path.meta.json that exists and will not parse — deliberately, so no caller
    # silently plans on the defaults instead (design §2.2) — and in THIS caller that
    # is one episode's geometry being unreadable, which is a named absence, not a
    # reason to abandon the packet run over the others. build_reel._predict already
    # degrades the identical failure to None for one episode via its broad clause;
    # this is that same decision, made narrowly.
    #
    # plan_ungraded deliberately does NOT share this clause: its own RuntimeError
    # comes from proc.run — a broken ffmpeg install, a corrupt but present video —
    # and reporting either as a clean 'absent' is exactly the swallow the clause
    # below was written to prevent.
    try:
        params = process_episode.rendered_params(ep.meta)
    except RuntimeError:
        return {"source": None, "delta": None}
    try:
        src = probe.source_for(md, Path(ep.path).parent)
        if not Path(src).exists():
            return {"source": None, "delta": None}
        plan = process_episode.plan_ungraded(md, src, ep.route, params=params)
    except (FileNotFoundError, KeyError, ValueError):
        return {"source": None, "delta": None}
    try:
        probe._refuse_on_drift(plan, ep.path, ep.meta)
    except (RuntimeError, OSError, ValueError, TypeError):
        # The oracle the other two consumers of this plan map have always had
        # (build_reel._predict, probe.probe_grade) and this one never did — so a
        # retried episode's source was read through a crop it never shipped and
        # reported to the judge as its own (design 2026-09-24 §0.3). Recording the
        # render's params fixes every episode rendered from now on; this catches
        # the ones whose sidecar predates the field, and any drift a params record
        # cannot explain — a re-track, a swapped source.
        #
        # Caught HERE, at the oracle's own call, and not by widening the clause
        # above: that clause excludes RuntimeError for a measured reason — proc.run
        # raises it for a broken ffmpeg install or a corrupt-but-present file, and
        # reporting either as a clean 'absent' is exactly the swallow it was
        # written to prevent.
        #
        # Widened past RuntimeError alone (final whole-branch review, Important 1):
        # _refuse_on_drift's OWN first read, CropPath.from_json(ep.path), is a bare
        # json.loads(Path(path).read_text()) with no wrapping at all — a missing
        # path.json raises FileNotFoundError, a truncated one raises
        # json.JSONDecodeError (a ValueError), and a path.json holding valid JSON of
        # the wrong shape (e.g. null, or a bare number) raises TypeError from the
        # `[int(x) for x in ...]` comprehension. And PathMeta.from_json(ep.meta)
        # itself escapes IsADirectoryError, not RuntimeError, when ep.meta is ""
        # (ReelEpisode.meta's own documented absence): Path("") normalizes to
        # Path("."), a directory .exists() reports True for, so from_json's
        # existence guard passes and read_text() raises on the directory. None of
        # those four is a RuntimeError, so the narrower clause was letting exactly
        # the failure it exists to prevent through — one missing or corrupt sidecar
        # aborting pack()'s loop for every episode after it. Safe to widen HERE,
        # unlike the clause above: this try wraps only two sidecar reads and never
        # reaches proc.run, so it cannot mask a broken ffmpeg install.
        #
        # Absence and not a raise: _evidence already reports every other sidecar
        # this way, and one episode's unreadable geometry must not abort a packet
        # run over the other seven.
        return {"source": None, "delta": None}
    frames = reframe.plan_frames_rgb(plan, src, color.sample_times(plan.dur, SENSOR_FRAMES))
    src_stats = naturalness.measure(frames)
    return {"source": src_stats, "delta": naturalness.evaluate_delta(src_stats, graded)}


_NONE = "none recorded"


def _sidecar(ev: dict, key: str, name: str) -> str:
    """One sidecar reading, in the three states the judge must tell apart: read,
    never written (`none recorded`), and written but unparseable (`unreadable: why`)."""
    why = (ev.get("unreadable") or {}).get(name)
    if why is not None:
        return f"unreadable: {why}"
    return _NONE if ev.get(key) is None else json.dumps(ev[key], indent=1, ensure_ascii=False)


def judge_prompt(ev: dict, d: Path) -> str:
    """The judge's prompt for one episode, filled from its own evidence.json (retro
    2026-10-16 S14: the second real run's agent wrote a script to do this by hand).
    Paths are absolute: the judge runs its commands through bin/vg, which works in
    its own models directory, and writes its findings with a tool that wants one."""
    def px(v):
        return _NONE if v is None else "x".join(str(n) for n in v)
    return prompts.render(prompts.JUDGE_TEMPLATE, {
        "INTENT": json.dumps(ev["intent"], indent=1, ensure_ascii=False),
        "CHECKS": _sidecar(ev, "checks", "report.json"),
        "TRACK": _sidecar(ev, "track", "route.meta.json"),
        "GEOMETRY": _sidecar(ev, "geometry", "path.meta.json"),
        "NATURALNESS": json.dumps(ev["naturalness"], indent=1, ensure_ascii=False),
        "STRIP_PATH": str(Path(ev["strip"]).resolve()),
        "STRIP_PX": px(ev["strip_px"]),
        "STORYBOARD_PATH": _NONE if ev["storyboard"] is None
                           else str(Path(ev["storyboard"]).resolve()),
        "STORYBOARD_PX": px(ev["storyboard_px"]),
        "CLIP": str(Path(ev["clip"]).resolve()),
        "FINDINGS_PATH": str((d / "findings.json").resolve()),
        # the launcher of the code that packed this evidence: a dispatched judge's
        # prompt is not a skill, so nothing fills the plugin root into it (design
        # 2026-10-21 §2)
        "VG": str(userdirs.launcher()),
    })


def pack(episodes_path: str, out_dir: str, *, frames: int = FRAMES) -> dict:
    """Write one evidence directory per episode under out_dir. Returns a status dict."""
    rm = ReelManifest.from_json(episodes_path)
    for i, ep in enumerate(rm.episodes):
        _epdir(ep, i)          # every sidecar checked BEFORE any decode: a packet run that
                               # cannot finish must fail in ms, not after N episodes of ffmpeg
    packets, written = [], []
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
        ev = _evidence(ep, i, clip_stats, strip, (info.w, info.h))
        (d / "evidence.json").write_text(json.dumps(ev, indent=2))
        (d / "judge_prompt.md").write_text(judge_prompt(ev, d))
        packets.append(str(d))
        written.append(str(d / "judge_prompt.md"))
    return {"status": "packed", "episodes": len(packets), "packets": packets,
            "prompts": written}


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


def _packed_digest(packets: str, i: int) -> str:
    """The clip digest `pack` recorded in this episode's evidence.json.

    An absent file or an absent key both return "" — reported by the caller as
    'records no clip digest', which is the true statement about a packet written
    before this binding existed. read_text's own OSError is not caught here, exactly
    as _raw does not catch its own: build_qc's call site collects it with every other
    complaint rather than letting one packet's filesystem trouble abort the rest."""
    p = Path(packets) / f"ep{i}" / "evidence.json"
    if not p.exists():
        return ""
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e}) — re-run `episode_qc pack`") from e
    return d.get("clip_digest") or "" if isinstance(d, dict) else ""


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
    would be a reel partly unjudged.

    Two bindings, not one (design 2026-09-09 §4). The verdict's digest says WHICH
    render was judged; the packet's says which render the judge LOOKED AT. They must
    agree, or the verdict claims to bind pixels nobody saw — and a false binding is
    worse than an absent one, which is why this refuses rather than reports."""
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
            actual = provenance.digest_file(ep.clip)
            packed = _packed_digest(packets, i)
        except (ValueError, OSError) as e:
            problems.append(f"  ep{i}: {e}")
            continue
        if not packed:
            problems.append(
                f"  ep{i}: its evidence packet records no clip digest, so nothing says "
                f"which render the judge looked at. A packet written before this binding "
                f"existed reads exactly like a stale one — re-run `episode_qc pack`, then "
                f"re-dispatch the judge for this episode")
            continue
        if packed != actual:
            problems.append(
                f"  ep{i}: its evidence packet was packed from a different render than "
                f"the clip on disk (packet {packed[:12]}…, clip {actual[:12]}…). The "
                f"judge read pixels that no longer exist, so its verdict cannot be "
                f"stamped against this render — re-run `episode_qc pack`, then re-dispatch "
                f"the judge for this episode")
            continue
        try:
            verdicts.append(EpisodeVerdict(
                idx=i, clip=ep.clip, clip_digest=actual,
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="per-episode QC: pack the evidence, then validate the judges' findings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="one evidence dir per episode (strip + storyboard + numbers)",
                       description="write one evidence directory per episode — a frame "
                                   "strip of the delivered clip, its storyboard, its "
                                   "mechanical report, a colour reading, and the clip's "
                                   "own digest. A judge subagent reads what this writes.")
    p.add_argument("--episodes", required=True, help="EPISODES.json from edl_to_reel --from-geometry (or --stop-after-episodes)")
    p.add_argument("--out-dir", required=True, help="dir for the ep{i}/ packet dirs")
    p.add_argument("--frames", type=int, default=FRAMES, help=f"strip cells per episode (default {FRAMES})")
    b = sub.add_parser("build", help="validate every judge's findings.json -> EPISODE_QC.json + .md",
                       description="validate every judge's findings.json into "
                                   "EPISODE_QC.json + .md, stamping each verdict with the "
                                   "clip digest read from disk. Refuses a verdict whose "
                                   "clip was re-rendered after it was packed.")
    b.add_argument("--episodes", required=True, help="the same EPISODES.json")
    b.add_argument("--packets", required=True, help="the pack --out-dir holding ep{i}/findings.json")
    b.add_argument("--out-dir", required=True,
                   help="dir for EPISODE_QC.json/.md — must be the dir holding EPISODES.json")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    result = (pack(a.episodes, a.out_dir, frames=a.frames) if a.cmd == "pack"
              else build(a.episodes, a.packets, a.out_dir))
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
