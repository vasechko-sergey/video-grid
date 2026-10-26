"""Front-half SP1 driver (design docs/specs/2026-07-11-extract-spine-design.md):
a hand-authored EDL.json → a delivered REEL_v1.mp4. Extract every window, run
process_episode per episode across a bounded thread pool (`jobs`, default 3 — the
measured knee, see docs/specs/2026-07-18-cap3-fanout-design.md §2), assemble a
ReelManifest, then hand off to build_reel (loop-2). Every episode runs even when an
earlier one fails; the reported finding is chosen by INDEX, so it never depends on
thread scheduling. Canvas/delivery are resolved ONCE here and stored in each
ReelEpisode, because build_reel's reprocess re-runs process_episode without project=.

Phase 1 also splits, at the GEOMETRY boundary (design 2026-08-30 §2): build_geometry
tracks and gates every episode and stops before any encode, and render_from_geometry
renders over those frozen routes with the EDL's CURRENT colour block. The seam exists
so match_grade can measure the crop that actually ships — which needs the route to
exist — and so a re-authored grade costs no re-render.

A freeze (design 2026-10-21 §3) is never tracked: both tracking arms render it in a
second wave, over its predecessor's last route sample held for its length. That held
route is the one GEOMETRY.json records, so phase 1b and build_reel's reprocess read it
like any frozen route."""
import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from scripts import build_reel, extract, process_episode, track
from scripts.lib import (assembly, color_fidelity, episode_qc as qc_lib, gates as gates_lib,
                        hero as hero_lib, manifest as manifest_lib, provenance, reid,
                        kenburns, runlayout)
from scripts.lib.edl import EDL, preflight
from scripts.lib.episode_qc import ReelQC
from scripts.lib.footage import Cast
from scripts.lib.models import (EpisodeGeometry, MusicSpec, ReelEpisode, ReelGeometry,
                               ReelManifest, route_from_json, route_to_json)
from scripts.lib.project import ProjectConfig

DEFAULT_JOBS = 3      # measured knee (design §2): cap 4 buys nothing and costs latency

GEOMETRY_JSON = "GEOMETRY.json"   # phase 1a's output, in the episodes bucket beside
                                  # EPISODES.json — never in build/, which phase 1b
                                  # must not wipe (design 2026-08-30 §2.2)


def _note(msg: str) -> None:
    print(msg, file=sys.stderr)


def _wipe_scratch(work_dir: str, out_dir: str) -> None:
    """Clear this reel's build/ before a phase-1 render, and report either way.

    Phase 1 has no resume — every run re-renders every episode from scratch — so the
    wipe discards nothing that would have been reused. It must NOT happen between the
    phases: EPISODES.json carries absolute paths into build/ep{i}/ and phase 2's retry
    loop reads the frozen route from there (design §6)."""
    removed = runlayout.wipe_build(work_dir, out_dir)
    if removed is None:
        _note(f"edl_to_reel: {work_dir} is not the canonical build dir for {out_dir} "
              f"— leaving it alone. Scratch there accumulates across runs.")
    elif removed:
        _note(f"edl_to_reel: wiped {len(removed)} entries from {work_dir}")


def _deliveries_dir(explicit: str | None, out_dir: str) -> str:
    """Where REEL_v{n} goes: the episodes dir's sibling deliveries/, unless named.

    Phase 1 fills out_dir with ep{i}.mp4 and phase 2 delivers next door, because a
    delivery inside the render output is a delivery a human deletes when clearing the
    render output (design §0/§4)."""
    return explicit if explicit is not None else str(runlayout.deliveries_for(out_dir))


def _refuse_on_engine_drift(started: dict, now: dict) -> None:
    """#11 — a montage run must not straddle an engine change: if the code has moved
    since `started` was stamped, the stages already finished were produced by different
    code and this reel would be a chimera of two engines. An UNKNOWN stamp on either
    side cannot prove drift and never stops the run (design §7); neither does an absent
    one, which is a run started before this existed.

    Shared by phase 1 (`_build_manifest`, against project.json's own stamp) and phase 2
    (`assemble_reel`, against the SAME stamp carried across the EPISODES.json round-trip
    as `rm.provenance["engine_at_start"]`) — without this, the split leaves the whole
    delivery half of a run uncovered, which is exactly where the router's N-judge QC
    gate gives the engine time to move (review fix)."""
    if started.get("sha") and now.get("sha") and started != now:
        raise ValueError(
            f"the engine changed since this run started (project.json records "
            f"{started['sha']} {'dirty' if started.get('dirty') else 'clean'}, now "
            f"{now['sha']} {'dirty' if now.get('dirty') else 'clean'}) — a montage run must "
            f"not straddle an engine change, because the stages already finished were "
            f"produced by different code. Start a fresh run dir, or re-run project_init "
            f"against the current engine to re-baseline")


def _authored_gates(project_path: str) -> gates_lib.Gates:
    """GATES.json beside project.json, announced on stderr when it moves any bar.

    Found BY CONVENTION with no flag — the CONSTRAINTS.json / REGIONS.json rule (design
    2026-09-30 §0.5). A flag can be dropped on a re-run, and a dropped threshold flag reverts
    the bar in silence, which is the defect EDL.platform shipped with. Read HERE, at run time,
    and not at edit_plan time onto the EDL: a bar is discovered to be wrong after a check
    fails, and re-cutting a reel to change one is absurd.

    A file that exists and cannot be loaded stops the run with its own path in the message.
    There is no waiver and no fallback to defaults. The announcement is there because a
    GATES.json sitting beside the wrong project.json is otherwise indistinguishable from none:
    both read as silence."""
    authored = gates_lib.beside_project(project_path)
    if authored.gates:
        _note(f"edl_to_reel: gates: {len(authored.gates)} authored threshold(s) "
              f"({', '.join(g.field for g in authored.gates)}) from GATES.json beside "
              f"{project_path}")
    return authored


def _phase_one_setup(edl_path: str, project_path: str, footage_root: str,
                     work_dir: str, out_dir: str, jobs: int
                     ) -> tuple[EDL, dict, list[dict], dict | None, gates_lib.Gates]:
    """Everything phase 1 does before the pool: the two footage-root refusals, the
    same-directory refusal, the build wipe, the jobs gate, the engine-drift stop,
    preflight and the extract. Returns (edl, engine_at_start, mds, stop, authored) — the
    last being the GATES.json set found beside project.json, read before the extract so a
    broken file refuses ahead of the expensive step.

    Shared by _build_manifest (render straight through) and build_geometry (stop at
    the geometry boundary), so the two arms cannot drift apart on a guard: both fill
    the same two directories with .mp4, and both cut the same segments.

    Setup/IO errors — missing footage, a window running past EOF, unreadable JSON —
    raise ValueError (a hard setup error, not an editorial finding to route)."""
    # Both dirs receive .mp4 — out_dir the ep{i}.mp4 renders, work_dir the extracted
    # segments and the reel master; REEL_v{n} now lands in the deliveries dir next
    # door instead (see _deliveries_dir). In the footage folder these become source
    # clips for the next intake, exactly as draft.mp4 did (design 2026-08-25 §0).
    # This is phase 1's chokepoint: edl_to_reel() and process_episodes() both route
    # through here. Phase 2 needs no guard — it derives out_dir from the
    # EPISODES.json path this call already validated.
    runlayout.refuse_output_in_footage(footage_root, out_dir, "edl_to_reel's out_dir")
    runlayout.refuse_output_in_footage(footage_root, work_dir, "edl_to_reel's work_dir")
    # Never the same directory. The wipe's predicate is "work_dir is out_dir's sibling
    # named build", and one arrangement satisfies it destructively: pass the same path
    # for both and the wipe takes the episode output — a prior EPISODES.json included —
    # before this run has written anything (measured by the final review, 2026-08-27).
    if Path(work_dir).resolve() == Path(out_dir).resolve():
        raise ValueError(
            f"edl_to_reel's work_dir and out_dir are the same directory ({out_dir}) — "
            f"work_dir is scratch this stage WIPES at the start of every render, and "
            f"out_dir holds the ep{{i}}.mp4 clips episode-qc binds its verdicts to. "
            f"Point them at the reel's build/ and episodes/ instead")
    _wipe_scratch(work_dir, out_dir)
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"edl_to_reel: jobs must be an integer >= 1, got {jobs!r} "
                         f"(default {DEFAULT_JOBS} is the measured knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU)")
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    authored = _authored_gates(project_path)
    # #11 — a montage run must not straddle an engine change; see _refuse_on_engine_drift.
    # `started` is also threaded into rm.provenance below (engine_at_start) — the value
    # phase 2's own guard re-checks against, once the split carries it across the
    # EPISODES.json round-trip.
    started = cfg.provenance.get("engine") or {}
    _refuse_on_engine_drift(started, provenance.engine_stamp())
    seg_dir = str(Path(work_dir) / "segments")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # 1. resolve + preflight every episode — fail in ms, before any ffmpeg
    mds, stop = preflight(edl, cfg, seg_dir, out_dir)
    if stop:
        return edl, started, mds, stop, authored

    # 2. extract every window (paths match the seg_dir/ep{i}_raw.mp4 the bridge used)
    extract.extract_edl(edl, footage_root, seg_dir, project=cfg)
    return edl, started, mds, None, authored


def _refuse_in_app_without_music(edl: EDL, music: str | None) -> None:
    """The brief asked for the music to be attached in the app, and the note that needs
    names the track — so a run with no --music is refused BEFORE the pool renders every
    episode, not by ReelManifest after it (design 2026-10-20 §1)."""
    if edl.music_in_app and not music:
        raise ValueError("the brief asked for the music to be attached in the app "
                         "(EDL.music_in_app), and its sound note names the track — pass "
                         "edl_to_reel --music <MUSIC.json>, or re-brief without "
                         "--music-in-app")


def _cast_for(edl: EDL) -> Cast | None:
    """The reel's cast registry, loaded once for the warm-up's pin resolution.

    preflight already read and validated the same file, so this cannot fail here —
    a second read is cheaper than threading the object out of preflight's return."""
    return Cast.from_json(edl.cast) if edl.cast is not None else None


def _run_pool(mds: list[dict], work_dir: str, jobs: int, *,
              authored: gates_lib.Gates,
              cast: Cast | None = None,
              stop_after: str | None = None,
              prepared: list[tuple[str | None, str | None]] | None = None,
              indices: list[int] | None = None
              ) -> tuple[list[dict], dict | None]:
    """One process_episode per episode over a bounded pool, results in index order.

    `indices` runs only those episodes (default: every one), each still under its own
    EDL index — its scratch dir, its finding, its raised note. _run_episodes uses it to
    hold the freezes back for a second wave.

    `prepared[i]` is (route_path, prepared_source) for episode i — the frozen pair
    phase 1a recorded (design 2026-08-30 §2.3), or a freeze's held route (design
    2026-10-21 §3). An episode handed a route never
    tracks, so the two weight warm-ups below cover only the ROUTE-LESS rest of the
    pool — with `prepared=None` that is every episode, exactly as before the split.

    `authored` is the GATES.json set, handed to every episode WHOLE — both scopes,
    unpartitioned: process_episode partitions where a CheckSpec is built, so no caller does
    (design 2026-09-30 §2.3). Required rather than defaulted to "none", because a pool
    caller that forgot it would judge every episode against the defaults and say nothing;
    there are three callers, and the third (phase 1b) is the one the conveyor renders through.

    That set is a safe SUPERSET, not an exact one, and deliberately: under `prepared`
    its members are the pans, and a pan does not track either (process_episode
    short-circuits to an empty route, timings["track"] = 0.0). Narrowing it would mean
    a second copy of process_episode's rung logic here, free to drift from the
    original silently; over-warming costs one idempotent weights check on a reel that
    is about to spend real encodes anyway.

    Returns (results, None), one result per episode, or (results-so-far, stop)
    naming the LOWEST-index episode that did not reach the expected status.

    One pass, not two. An episode can fail through either channel (a raised setup
    error or a returned non-pass status), and the two must be ordered AGAINST EACH
    OTHER, not each within itself: draining every exception first would let a raise
    at episode 2 beat a routable stop_and_report at episode 0 — which the sequential
    loop returned before it ever reached episode 2. Whichever problem sits at the
    lowest index wins, whatever kind it is; that is what makes the finding identical
    to the sequential one."""
    # Per-episode kwargs, and the subset this pool will actually track. Passing a
    # kwarg only when it carries something keeps the call shape identical to the
    # pre-split one for a plain render — and to the pre-gates one for a reel that authored
    # none.
    run = list(range(len(mds))) if indices is None else list(indices)
    kwargs: list[dict] = []
    tracking: list[dict] = []
    for i in run:
        md = mds[i]
        kw: dict = {}
        if stop_after is not None:
            kw["stop_after"] = stop_after
        if authored.gates:
            kw["gates"] = authored.to_dict()
        route, src = prepared[i] if prepared is not None else (None, None)
        if route is None:
            if src is not None:
                raise ValueError(
                    f"episode {i} was handed a prepared source ({src}) with no frozen "
                    f"route — the pair asserts 'this route was measured on these "
                    f"pixels', so the source alone asserts nothing and process_episode "
                    f"refuses it. Record the route in GEOMETRY.json, or drop the "
                    f"prepared source and let this episode run its own pre-stage.")
            tracking.append(md)
        else:
            kw["route_path"] = route
            if src is not None:
                kw["prepared_source"] = src
        kwargs.append(kw)

    # Safe to parallelise because each episode owns its scratch (work_dir/ep{i}) and its
    # output (out_dir/ep{i}.mp4) — process_episode's docstring names the clobber this
    # would otherwise cause, and preflight built both paths per index.
    for model in sorted({(md.get("model") or track.MODEL) for md in tracking}):
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
    pins = (hero_lib.resolve(md.get("hero"), cast) for md in tracking)
    if any(p is not None and p.kind == "cast" for p in pins) and reid.available():
        reid.ensure_model()
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(process_episode.process_episode, mds[i],
                             str(Path(work_dir) / f"ep{i}"),   # md already resolved → no project=
                             **kw)
                   for i, kw in zip(run, kwargs, strict=True)]
    # the `with` block joined every worker, so each future below is already done and this
    # ONE loop reads them in index order — no dependence on completion order anywhere.
    expect = "geometry" if stop_after == "geometry" else "mechanical_pass"
    results: list[dict] = []
    for i, fut in zip(run, futures, strict=True):
        md = mds[i]
        try:
            res = fut.result()
        except Exception as e:         # a hard setup error stays an exception, per the docstring
            e.add_note(f"raised while processing episode {i} (segment {md['segment']})")
            raise
        if res.get("status") != expect:
            return results, {"status": "stop_and_report",
                             "finding": {"reason": "episode-failed", "episode_idx": i,
                                         "sub_status": res.get("status")}, "sub": res}
        results.append(res)
    return results, None


def _route_left(md: dict, epdir: str | Path) -> str | None:
    """The route.json a rendered episode left in its scratch dir: none for a pan or a
    still, which follow nobody (process_episode writes none for either). A full render's
    result does not name it, so _build_manifest and _run_episodes both derive it here —
    the same path the geometry stop's result names."""
    if md.get("pan") is not None or md.get("still"):
        return None
    return str(Path(epdir) / "route.json")


def _hold_route(prev_route: str | None, segment: str, out: Path) -> str | None:
    """A freeze's held route (design 2026-10-21 §3): the previous episode's LAST route
    sample — where it left the subject — repeated at t = k/fps for every frame k of the
    freeze's own segment, counted and rated off that segment. Written to `out`; None when
    the previous episode has no sample to hold.

    The previous episode's route.meta.json is COPIED beside it, byte for byte: it names
    whom that episode followed, which is whom the freeze holds, and it already passed the
    contradiction gate there. A route with no sidecar (a hand-supplied one) gets none
    here either, which process_episode reads as unambiguous — the same reading — and a
    stale one from an earlier run in an unwiped scratch dir is removed for that reason."""
    points = route_from_json(prev_route) if prev_route is not None else []
    if not points:
        return None
    n, fps = assembly.count_frames(segment), assembly.probe_stream(segment).fps
    out.parent.mkdir(parents=True, exist_ok=True)
    route_to_json([replace(points[-1], t=k / fps) for k in range(n)], out)
    meta, held_meta = Path(prev_route).with_suffix(".meta.json"), out.with_suffix(".meta.json")
    if meta.exists():
        shutil.copyfile(meta, held_meta)
    else:
        held_meta.unlink(missing_ok=True)
    return str(out)


def _run_episodes(edl: EDL, mds: list[dict], work_dir: str, jobs: int, *,
                  authored: gates_lib.Gates, cast: Cast | None = None,
                  stop_after: str | None = None) -> tuple[list[dict], dict | None]:
    """Phase 1's pool for the two callers that TRACK (_build_manifest, build_geometry).

    A freeze is not tracked (design 2026-10-21 §3): re-tracking one cloned frame loses
    whom the previous episode followed. So the cut runs in two waves. Wave 1 is every
    other episode, exactly as before; wave 2 is the freezes, each over a held route built
    from its predecessor's (_hold_route) — which is why the predecessors must finish
    first. A cut with no freeze is one _run_pool call, the call it always was.

    Results come back in EDL index order. A stop in wave 1 returns before wave 2 runs, so
    a freeze BELOW that index is never judged and the finding is the lowest among the
    episodes that ran; a stop in wave 2 carries its own EDL index. On a stop the results
    are the passing episodes that ran, in index order — no caller reads them past it."""
    freezes = [i for i, ep in enumerate(edl.episodes) if ep.freeze]
    if not freezes:
        return _run_pool(mds, work_dir, jobs, authored=authored, cast=cast,
                         stop_after=stop_after)
    played = [i for i in range(len(mds)) if i not in set(freezes)]
    first, stop = _run_pool(mds, work_dir, jobs, authored=authored, cast=cast,
                            stop_after=stop_after, indices=played)
    done = dict(zip(played, first))
    if stop:
        return [done[i] for i in sorted(done)], stop
    prepared: list[tuple[str | None, str | None]] = [(None, None)] * len(mds)
    for f in freezes:
        p = f - 1      # EDL refuses a freeze at 0 or after a held episode, so p is played
        epdir = Path(work_dir) / f"ep{p}"
        prev_route = done[p]["route"] if "route" in done[p] else _route_left(mds[p], epdir)
        held = _hold_route(prev_route, mds[f]["segment"],
                           Path(work_dir) / f"ep{f}" / "route.json")
        if held is None:
            return [done[i] for i in sorted(done)], {
                "status": "stop_and_report",
                "finding": {"reason": "freeze-no-route", "episode_idx": f, "previous_idx": p,
                            "detail": f"episode {f} is a freeze of episode {p}, which left no "
                                      f"route sample to hold — a freeze holds the subject "
                                      f"where the previous episode left them, and a pan or a "
                                      f"still follows nobody. Freeze an episode that tracks "
                                      f"someone, or drop the freeze"}}
        prepared[f] = (held, None)
    second, stop = _run_pool(mds, work_dir, jobs, authored=authored, cast=cast,
                             stop_after=stop_after, prepared=prepared, indices=freezes)
    done.update(zip(freezes, second))
    return [done[i] for i in sorted(done)], stop


def _reel_manifest(mds: list[dict], results: list[dict], routes: list[str | None],
                   epdirs: list[str], edl: EDL, edl_path: str, *,
                   music: str | None, changelog: str, started: dict,
                   authored: gates_lib.Gates = gates_lib.Gates()) -> ReelManifest:
    """The ReelManifest both phase-1 arms assemble from their pool's results.

    `routes[i]` is the episode's route.json or None. A pan episode has no route.json
    — process_episode wrote none, deliberately — and naming a path that was never
    written would be a lie the reel manifest then carries around; None states the
    absence. check_reel does not depend on this (it branches on the meta sidecar's
    provenance bit, which is what actually happened rather than what a caller
    remembered to pass) — this is the contract telling the truth, not the crash fix.

    `authored` (the GATES.json set) defaults to empty so the pure-assembly tests that call
    this with results in hand keep their shape. Both real callers pass it, and the manifest
    assertion in test_the_pool_hands_the_authored_gates_to_every_episode pins that they do."""
    episodes = [ReelEpisode(manifest=md, clip=res["clip"], route=routes[i],
                            path=str(Path(epdirs[i]) / "path.json"),
                            meta=str(Path(epdirs[i]) / "path.meta.json"),
                            # What the grade did to this episode's colour, from the
                            # render pair check_episode already decoded. Phase 2 runs
                            # from EPISODES.json alone and never sees a phase-1
                            # report, so the number has to ride the contract
                            # (design 2026-09-17 §2.3).
                            chroma=color_fidelity.shift_from_report(res.get("report") or {}))
                for i, (md, res) in enumerate(zip(mds, results, strict=True))]
    # PLAYED lengths: check_reel measures the master's real duration against this
    # number, and a ramped episode contributes more screen time than its source
    # window (design §6).
    target = (edl.target_dur if edl.target_dur is not None
              else sum(ep.play_dur() for ep in edl.episodes))
    # Deliberate seam for a ReelManifest field a caller could override. The retired
    # --color-delta-max used to populate it (design 2026-08-29 §2); GATES.json is its first
    # filler since (design 2026-09-30 §2.3) — the WHOLE authored set, both scopes, so the
    # EPISODES.json round trip carries it to build_reel's reprocess arm. No CLI flag fills it:
    # the file is found beside project.json, because a flag can be dropped on a re-run.
    extra: dict = {}
    if authored.gates:
        extra["gates"] = authored.to_dict()
    # #16: this argument is the version-log NOTE, not the log's path. Passing
    # str(out_dir/"VERSIONS.md") here is what made 12 of 13 entries in a real run's
    # VERSIONS.md log the file's own path instead of the reason for the version.
    # retro 2026-10-16 S11: the old default ("delivered from EDL.json") made five lines
    # of the second run's VERSIONS.md identical. The note now states what this cut IS —
    # always — and an authored reason (--changelog) leads it.
    note = _cut_summary(edl, target, music or edl.music)
    if changelog:
        note = f"{changelog} — {note}"
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=note, music=music or edl.music, platform=edl.platform,
                      look=edl.look,
                      # the fit that chose this reel's length, so the reel loop can tell a
                      # CHOSEN length from a derived one (design 2026-08-16 §5)
                      outro=edl.outro.to_dict() if edl.outro is not None else None,
                      # the one tone every episode was graded toward, so the delivery
                      # records what the conductor aimed at rather than only the
                      # per-episode pairs it authored (design 2026-08-30 §6)
                      tone_target=edl.tone_target,
                      # SPEC.length_s. The only length in the manifest that did not
                      # come from the cut, so it is the only one check_reel's length
                      # arithmetic cannot be circular about (design 2026-09-07 §4)
                      brief_len=edl.brief_len,
                      # SPEC.music_in_app: the deliver arm also writes the reel without
                      # the song and its sound note (design 2026-10-20)
                      music_in_app=edl.music_in_app,
                      # the episodes whose cut carries the shutter accent; build_reel
                      # places it on the master's real cut time (design 2026-10-21 §4)
                      shutters=tuple(i for i, ep in enumerate(edl.episodes) if ep.shutter),
                      **extra)
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
    return rm


def _cut_summary(edl: EDL, target: float, music: str | None) -> str:
    """'6 episodes · 45.7s · music: lets-go-surfing @ 49.0s' — the facts a VERSIONS.md
    line needs to tell one delivery from the next. A MUSIC.json that cannot be read is
    named as such rather than failing a delivery over a log line."""
    head = f"{len(edl.episodes)} episodes · {target:.1f}s"
    if not music:
        return f"{head} · no music"
    try:
        ms = MusicSpec.from_json(music)
    except (OSError, ValueError):
        return f"{head} · music: {Path(music).name} (unreadable)"
    return f"{head} · music: {Path(ms.track).stem} @ {ms.start_offset:.1f}s"


def _build_manifest(edl_path: str, project_path: str, footage_root: str,
                    work_dir: str, out_dir: str, *, music: str | None = None,
                    jobs: int = DEFAULT_JOBS,
                    changelog: str = "") -> tuple[ReelManifest | None, dict | None]:
    """Everything up to the ReelManifest: preflight, extract, the loop-1 fan-out, the
    run provenance. Returns (rm, None) or (None, stop_and_report)."""
    edl, started, mds, stop, authored = _phase_one_setup(edl_path, project_path,
                                                         footage_root, work_dir, out_dir, jobs)
    if stop:
        return None, stop
    _refuse_in_app_without_music(edl, music)
    # 3. loop-1 fan-out: one process_episode per episode, up to `jobs` concurrently —
    #    a freeze in a second wave, over its predecessor's held route (_run_episodes).
    results, stop = _run_episodes(edl, mds, work_dir, jobs, cast=_cast_for(edl),
                                  authored=authored)
    if stop:
        return None, stop

    # 4. loop-2: assemble the ReelManifest and drive build_reel
    epdirs = [str(Path(work_dir) / f"ep{i}") for i in range(len(mds))]
    routes = [_route_left(md, d) for md, d in zip(mds, epdirs, strict=True)]
    return _reel_manifest(mds, results, routes, epdirs, edl, edl_path, music=music,
                          changelog=changelog, started=started, authored=authored), None


def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, *, deliveries_dir: str | None = None,
                music: str | None = None, jobs: int = DEFAULT_JOBS,
                changelog: str = "",
                titles: str | None = None) -> dict:
    """The SP1 front door: a hand-authored EDL.json -> a delivered REEL_v1.mp4 in one
    command. No per-episode QC runs on this path — the delivery's attestation records
    `episode_qc: absent` so an unjudged reel is DISTINGUISHABLE from a judged one, which
    is the honest half of the gate (design §10): no silent bypass, not no bypass."""
    rm, stop = _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir,
                               music=music, jobs=jobs,
                               changelog=changelog)
    if stop:
        return stop
    rm.provenance["episode_qc"] = {"state": "absent"}
    return build_reel.build_reel(rm, _deliveries_dir(deliveries_dir, out_dir),
                                 str(Path(work_dir) / "reel"), titles=titles)


def process_episodes(edl_path: str, project_path: str, footage_root: str,
                     work_dir: str, out_dir: str, *, music: str | None = None,
                     jobs: int = DEFAULT_JOBS,
                     changelog: str = "") -> dict:
    """Phase 1: render every episode, then STOP. Writes EPISODES.json (a serialized
    ReelManifest) beside the ep{i}.mp4 it describes, so the verdicts and the judged
    clips cannot be separated (design §3)."""
    rm, stop = _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir,
                               music=music, jobs=jobs,
                               changelog=changelog)
    if stop:
        return stop
    return _episodes_ready(rm, out_dir)


def _episodes_ready(rm: ReelManifest, out_dir: str) -> dict:
    """Write EPISODES.json beside the ep{i}.mp4 it describes, so the verdicts and the
    judged clips cannot be separated. Both phase-1 render arms end here — the one that
    started from the EDL, and the one that started from a frozen geometry."""
    p = Path(out_dir) / "EPISODES.json"
    rm.write(p)
    return {"status": "episodes_ready", "episodes": str(p), "count": len(rm.episodes),
            "clips": [e.clip for e in rm.episodes]}


def _jsonable(md: dict) -> dict:
    """`md` as it survives a JSON round-trip.

    Not decoration: Manifest's `color_means` default is a TUPLE, so a freshly derived
    manifest and one read back out of GEOMETRY.json differ on it by type alone, and
    the frozen-cut comparison below would refuse every run."""
    return json.loads(json.dumps(md))


def _cut_identity(edl: EDL) -> list[dict]:
    """What determines each episode's extracted segment, and nothing else.

    `source`/`start`/`dur`/`ramp` are exactly `extract`'s inputs — the pixels the
    frozen route was measured on — and NOT ONE of them crosses `to_manifest_dict`, so
    the stripped-manifest comparison cannot see any of them. Phase 1b deliberately
    does not re-extract, so without this an author who nudged a window would get the
    old one back, silently: the reel would ship a cut the EDL no longer describes.

    A photo's `still` move is the same kind of input — it is rendered into the segment
    and does not cross either (design 2026-10-20 §4) — so it joins the identity, for
    photos only: a GEOMETRY.json written before photos keeps comparing equal. `freeze`
    joins it for freezes only, for the same reason: `source`/`start`/`dur` cannot tell
    a held frame from a played window that starts there (design 2026-10-21 §3)."""
    return [{"source": ep.source, "start": ep.start, "dur": ep.dur, "ramp": ep.ramp,
             **({"still": ep.still or kenburns.DEFAULT_MOVE.to_dict()}
                if runlayout.is_photo(ep.source) else {}),
             **({"freeze": True} if ep.freeze else {})}
            for ep in edl.episodes]


def build_geometry(edl_path: str, project_path: str, footage_root: str,
                   work_dir: str, out_dir: str, *, jobs: int = DEFAULT_JOBS
                   ) -> tuple[ReelGeometry | None, dict | None]:
    """Phase 1a: extract, stabilize, track, gate — then STOP, before any encode.

    Writes GEOMETRY.json into out_dir (the episodes bucket, NOT build/, which the next
    phase must not wipe). The colour block is stripped from every stored manifest: what
    phase 1b re-derives from the EDL and compares against is the CUT, so a changed grade
    passes and a changed cut is refused (design 2026-08-30 §2.2).

    This is the seam match_grade measures the shipped crop in: the route exists, and no
    episode has been encoded yet, so a re-authored grade costs nothing to apply."""
    edl, started, mds, stop, authored = _phase_one_setup(edl_path, project_path,
                                                         footage_root, work_dir, out_dir, jobs)
    if stop:
        return None, stop
    results, stop = _run_episodes(edl, mds, work_dir, jobs, cast=_cast_for(edl),
                                  stop_after="geometry", authored=authored)
    if stop:
        return None, stop
    geo = ReelGeometry(
        episodes=tuple(EpisodeGeometry(manifest=_jsonable(manifest_lib.strip_colour(md)),
                                       route=res["route"], source=res["source"],
                                       project_dir=str(Path(work_dir) / f"ep{i}"))
                       for i, (md, res) in enumerate(zip(mds, results, strict=True))),
        edl=str(edl_path),
        project=str(project_path) if project_path else "",
        # the two things phase 1b re-checks: #11's engine stamp (the split gives the
        # conductor, and a human, time for the engine to move) and the cut identity
        # the stored manifests cannot carry.
        provenance={"engine_at_start": started, "cuts": _cut_identity(edl)})
    geo.write(Path(out_dir) / GEOMETRY_JSON)
    return geo, None


def _refuse_on_changed_cut(geo: ReelGeometry, edl: EDL, mds: list[dict],
                           geometry_path: str) -> None:
    """Every episode must still be the one its frozen route was measured on.

    Two halves, because neither sees the other's fields: the stripped manifest catches
    a changed layout / crop / hero / canvas, and the cut identity catches a changed
    window, source clip or ramp. Only the colour block may move between the phases —
    that is the seam."""
    frozen = geo.provenance.get("cuts")
    if (not isinstance(frozen, list) or len(frozen) != len(geo.episodes)
            or any(not isinstance(c, dict) for c in frozen)):
        raise ValueError(
            f"{geometry_path} records no cut identity for its {len(geo.episodes)} "
            f"episodes, so nothing here can tell whether the EDL's windows still "
            f"describe the segments the frozen routes were measured on. It was not "
            f"written by `edl_to_reel --stop-after-geometry` — re-run that.")
    if len(mds) != len(geo.episodes):
        raise ValueError(
            f"the EDL now has {len(mds)} episodes and this geometry froze "
            f"{len(geo.episodes)} — a route was measured per episode, and there is no "
            f"honest way to pair them across an inserted or deleted cut. Re-run "
            f"`edl_to_reel --stop-after-geometry`, or restore the EDL.")
    fresh_cuts = _cut_identity(edl)
    for i, (md, eg) in enumerate(zip(mds, geo.episodes, strict=True)):
        fresh = _jsonable(manifest_lib.strip_colour(md))
        changed = sorted(k for k in set(fresh) | set(eg.manifest)
                         if fresh.get(k) != eg.manifest.get(k))
        changed += sorted(k for k, v in fresh_cuts[i].items()
                          if v != frozen[i].get(k))
        if changed:
            raise ValueError(
                f"episode {i}'s cut changed after its geometry was frozen "
                f"({', '.join(changed)}): the GEOMETRY.json in hand was built from a "
                f"different window, layout or hero, and its route no longer describes "
                f"this episode. Only the colour block may change between the phases — "
                f"that is the seam. Re-run `edl_to_reel --stop-after-geometry`, or "
                f"restore the EDL. (If the list above is only segment/out_path, nothing "
                f"editorial moved: pass the same --work-dir/--out-dir the geometry was "
                f"built with.)")


def _refuse_on_missing_inputs(geo: ReelGeometry, mds: list[dict]) -> dict | None:
    """Phase 1b's inputs — the frozen routes, the extracted segments, the stabilize
    pre-stage's output — all live in build/, and the gap between the phases is a HUMAN
    turn. Any plain `edl_to_reel` or `--stop-after-episodes` run on the same reel dirs
    in that window calls _wipe_scratch and takes them, while GEOMETRY.json survives
    next door in episodes/ and _refuse_on_changed_cut passes (not one path changed).
    Without this the run dies inside reframe._probe with a bare ffprobe error carrying
    no remedy — the same class assemble_reel's `episode-clips-missing` stop was added
    for, and the same answer: a routed finding, before any ffmpeg."""
    problems: list[str] = []
    for i, (md, eg) in enumerate(zip(mds, geo.episodes, strict=True)):
        # keyed by PATH so the common case (source == segment) is reported once, and
        # the first label wins
        wanted: dict[str, str] = {}
        if eg.route is not None:
            wanted[eg.route] = "frozen route"
        wanted.setdefault(md["segment"], "extracted segment")
        wanted.setdefault(eg.source, "source reframe would consume")
        problems += [
            f"episode {i}'s {what} is gone ({path}) — the build dir was wiped between "
            f"the phases (a plain edl_to_reel or --stop-after-episodes run on the same "
            f"reel does exactly that), and a frozen route cannot be recovered without "
            f"re-tracking. Re-run `edl_to_reel --stop-after-geometry`, then re-apply "
            f"the grade with `match_grade` before rendering"
            for path, what in wanted.items() if not Path(path).exists()]
    if not problems:
        return None
    return {"status": "stop_and_report",
            "finding": {"reason": "geometry-inputs-missing", "episode_idx": None,
                        "problems": problems}}


def render_from_geometry(geometry_path: str, project_path: str, work_dir: str,
                         out_dir: str, *, music: str | None = None,
                         jobs: int = DEFAULT_JOBS, changelog: str = ""
                         ) -> tuple[ReelManifest | None, dict | None]:
    """Phase 1b: render every episode over its frozen route, with the EDL's CURRENT
    colour block. Returns (rm, None) or (None, stop_and_report).

    Refuses, before any ffmpeg, a build dir that was wiped between the phases (see
    _refuse_on_missing_inputs).

    Does NOT wipe build/ — the routes it needs live there — and does NOT re-extract:
    phase 1a already cut the segments those routes were measured against, so cutting
    them again would be waste on top of a lie about which pixels were tracked.

    Reads GATES.json beside `project_path` itself, at this phase's own run time (see
    _authored_gates): this is the phase that renders and runs the checks, and GEOMETRY.json
    carries no gates.

    No footage-root guard here, and none is missing: both directories are pinned by
    the stored manifests' own `segment`/`out_path`, and any other pair is refused by
    _refuse_on_changed_cut below."""
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"edl_to_reel: jobs must be an integer >= 1, got {jobs!r} "
                         f"(default {DEFAULT_JOBS} is the measured knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU)")
    geo = ReelGeometry.from_json(geometry_path)
    edl = EDL.from_json(geo.edl)
    _refuse_in_app_without_music(edl, music)
    cfg = ProjectConfig.from_json(project_path)
    # Found again HERE, not carried over from phase 1a: this phase never calls
    # _phase_one_setup, and it is the one that RENDERS and so runs the checks. A bar is
    # discovered to be wrong after a check fails, which is after 1a — GEOMETRY.json therefore
    # holds no gates, and the file is read at the moment it is acted on.
    authored = _authored_gates(project_path)
    # #11, at the third stop point (design §9.7): the conductor measures, a human reads
    # MATCH.md and may re-cut the grade — exactly the gap where the engine moves. The
    # stamp phase 1a recorded is the one this compares against, the same way
    # assemble_reel re-checks EPISODES.json's.
    started = geo.provenance.get("engine_at_start") or {}
    _refuse_on_engine_drift(started, provenance.engine_stamp())
    seg_dir = str(Path(work_dir) / "segments")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    mds, stop = preflight(edl, cfg, seg_dir, out_dir)
    if stop:
        return None, stop
    _refuse_on_changed_cut(geo, edl, mds, geometry_path)
    stop = _refuse_on_missing_inputs(geo, mds)
    if stop:
        return None, stop
    # The frozen pair, per episode (design §2.3). The prepared source is gated on the
    # ROUTE as well as on `stabilize`: a pan is stabilizable — the two are independent
    # EDL fields and nothing refuses the pair — and a pan has no route, which
    # process_episode refuses a prepared source without. Such an episode is handed
    # NEITHER half and re-runs its own pre-stage: wasteful, but correct, since a
    # generated path was never measured against pixels in the first place.
    prepared = [(eg.route,
                 eg.source if (md.get("stabilize") and eg.route is not None) else None)
                for md, eg in zip(mds, geo.episodes, strict=True)]
    results, stop = _run_pool(mds, work_dir, jobs, cast=_cast_for(edl),
                              prepared=prepared, authored=authored)
    if stop:
        return None, stop
    epdirs = [str(Path(work_dir) / f"ep{i}") for i in range(len(mds))]
    # the routes come from the geometry, not re-derived: it is the record of what was
    # actually written, pan (None) included.
    rm = _reel_manifest(mds, results, [eg.route for eg in geo.episodes], epdirs, edl,
                        geo.edl, music=music, changelog=changelog, started=started,
                        authored=authored)
    return rm, None


def assemble_reel(episodes_path: str, work_dir: str, *, deliveries_dir: str | None = None,
                  titles: str | None = None) -> dict:
    """Phase 2: the QC gate, then build_reel. The out dir is EPISODES.json's own
    directory — one fewer flag to point at the wrong place, and the gate's artifact is
    found there BY CONVENTION (design §3/§7).

    Every refusal below happens before a single ffmpeg call and writes nothing."""
    rm = ReelManifest.from_json(episodes_path)
    # #11, extended to the delivery half (review fix): the router's default path splits
    # phase 1 and phase 2 with N judge subagents (plus any fix round they trigger) in
    # between — exactly where the engine can move. rm.provenance["engine_at_start"]
    # survives the EPISODES.json round-trip (ReelManifest.to_dict/from_dict carry
    # provenance), so the same guard _build_manifest applies at phase 1 start applies here.
    _refuse_on_engine_drift(rm.provenance.get("engine_at_start") or {}, provenance.engine_stamp())
    out_dir = str(Path(episodes_path).parent)
    # A cleaned-but-not-fully-cleaned out dir — EPISODES.json kept, the ep{i}.mp4 clips it
    # names gone — must stop with a routed finding, not a bare FileNotFoundError traceback
    # out of provenance.digest_file below (review fix).
    gone = [i for i, ep in enumerate(rm.episodes) if not Path(ep.clip).exists()]
    if gone:
        return {"status": "stop_and_report",
                "finding": {"reason": "episode-clips-missing", "episode_idx": None,
                            "problems": [
                                f"episode {i}'s clip is gone ({rm.episodes[i].clip}) — the "
                                f"out dir was cleaned while EPISODES.json was left behind; "
                                f"re-run phase 1 (edl_to_reel --from-geometry, or "
                                f"--stop-after-episodes for a hand-driven run) before "
                                f"assembling" for i in gone]}}
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
    return build_reel.build_reel(rm, _deliveries_dir(deliveries_dir, out_dir),
                                 str(Path(work_dir) / "reel"), titles=titles)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="drive a hand-authored EDL.json → delivered REEL_v1.mp4")
    ap.add_argument("edl", nargs="?", default=None,
                    help="path to an EDL.json (omit with --from-episodes / --from-geometry)")
    ap.add_argument("--project", default=None,
                    help="project.json — episodes inherit canvas/delivery, and a GATES.json "
                         "beside it (if any) moves the check thresholds (design 2026-09-30); "
                         "every phase-1 run reads it afresh, and --from-episodes carries the "
                         "set phase 1 froze into EPISODES.json")
    ap.add_argument("--footage-root", default=None, help="dir the EDL 'source' paths resolve against")
    ap.add_argument("--work-dir", required=True, help="scratch for segments / per-episode / reel master")
    ap.add_argument("--out-dir", default=None,
                    help="dir for ep{i}.mp4 renders — required unless --from-episodes, "
                         "which refuses it: phase 2 derives its out dir from the "
                         "EPISODES.json path instead (design §3)")
    ap.add_argument("--deliveries-dir", default=None,
                    help="where REEL_v{n} lands (default: the episodes dir's sibling "
                         "deliveries/) — never the same dir as --out-dir")
    ap.add_argument("--music", default=None,
                    help="MUSIC.json path; overrides the EDL's music field — phase-1-only; "
                         "refused with --from-episodes (already baked into EPISODES.json)")
    ap.add_argument("--titles", default=None,
                    help="TITLES.json — burn on-screen text into the reel (§5.16); refused "
                         "with --stop-after-episodes (titles are burned in at delivery, not "
                         "the per-episode render)")
    ap.add_argument("--jobs", type=int, default=None,
                    help=f"episodes to process concurrently (default {DEFAULT_JOBS} — the "
                         f"measured knee; lower on a memory-constrained box); refused with "
                         f"--from-episodes (phase 2 renders nothing)")
    ap.add_argument("--changelog", default="",
                    help="version-log note for this delivery — the REASON for the version "
                         "(e.g. 'regraded ep1'), not a path. It leads the VERSIONS.md line, "
                         "before the cut's own facts (episodes · length · music), which are "
                         "always written; refused with --from-episodes (already baked into "
                         "EPISODES.json) — pass it at --from-geometry")
    phase = ap.add_mutually_exclusive_group()
    phase.add_argument("--stop-after-episodes", action="store_true",
                       help="render every episode, write EPISODES.json, and stop — the "
                            "seam the per-episode QC gate sits in (design 2026-08-08)")
    phase.add_argument("--from-episodes", default=None,
                       help="an EPISODES.json from --from-geometry (or --stop-after-episodes): "
                            "gate on EPISODE_QC.json beside it, then assemble and deliver")
    phase.add_argument("--stop-after-geometry", action="store_true",
                       help="stabilize, track and gate every episode, write GEOMETRY.json "
                            "and stop — the seam match_grade measures the crop in, before "
                            "any encode (design 2026-08-30 §2)")
    phase.add_argument("--from-geometry", default=None, metavar="GEOMETRY.json",
                       help="render every episode over the routes that file froze, with the "
                            "EDL's CURRENT colour block, and stop at EPISODES.json. Refuses "
                            "a changed cut.")
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    # The three phase-1 arms that stop before delivery. Titles are burned into the ONE
    # encode at delivery and REEL_v{n} lands in the deliveries dir there, so neither
    # flag has anywhere to go here — and being accepted-and-dropped is exactly the
    # class every other refusal in this parser exists to prevent.
    stopper = ("--stop-after-episodes" if a.stop_after_episodes else
               "--stop-after-geometry" if a.stop_after_geometry else
               "--from-geometry" if a.from_geometry else None)
    if stopper and a.titles:
        ap.error(f"--titles has no effect with {stopper}: titles are burned into the ONE "
                 f"encode at delivery (phase 2), and the phase-1 drivers take no titles "
                 f"parameter at all — pass --titles to the --from-episodes invocation "
                 f"instead")
    if stopper and a.deliveries_dir:
        ap.error(f"--deliveries-dir has no effect with {stopper}: REEL_v{{n}} lands there "
                 f"only at delivery (phase 2), and the phase-1 drivers never deliver and "
                 f"take no deliveries_dir parameter at all — pass --deliveries-dir to the "
                 f"--from-episodes invocation instead")
    jobs = a.jobs if a.jobs is not None else DEFAULT_JOBS
    if a.from_episodes:
        if (a.edl or a.project or a.footage_root or a.out_dir or a.music
                or a.jobs is not None or a.changelog):
            ap.error("--from-episodes resumes a run whose episodes are already rendered; "
                     "the EDL / --project / --footage-root are not read again, --out-dir "
                     "is not read at all — phase 2 delivers into the episodes dir's "
                     "SIBLING deliveries/, never beside EPISODES.json, so clearing the "
                     "render output can never take a delivered reel with it (design "
                     "2026-08-26 §0/§4) — and --music / --jobs / --changelog only "
                     "affect phase-1 rendering, already baked into EPISODES.json, so "
                     "passing any of them here would silently be discarded")
        result = assemble_reel(a.from_episodes, a.work_dir,
                               deliveries_dir=a.deliveries_dir, titles=a.titles)
    elif a.from_geometry:
        if a.edl or a.footage_root:
            ap.error("--from-geometry renders over routes that are already frozen: the EDL "
                     "is named by GEOMETRY.json itself (a different one would render a cut "
                     "those routes do not describe), and nothing is extracted again — the "
                     "segments the routes were measured on are already in --work-dir, so "
                     "--footage-root is not read at all. Drop the positional EDL / "
                     "--footage-root; to change the cut, re-run --stop-after-geometry")
        missing = [n for n, v in (("--project", a.project), ("--out-dir", a.out_dir))
                   if not v]
        if missing:
            ap.error(f"missing {', '.join(missing)} — required with --from-geometry "
                     f"(--out-dir must be the same episodes dir the geometry was built "
                     f"with, and --project resolves canvas/delivery exactly as phase 1a did)")
        rm, stop = render_from_geometry(a.from_geometry, a.project, a.work_dir, a.out_dir,
                                        music=a.music, jobs=jobs, changelog=a.changelog)
        result = stop if stop else _episodes_ready(rm, a.out_dir)
    else:
        missing = [n for n, v in (("edl", a.edl), ("--project", a.project),
                                  ("--footage-root", a.footage_root),
                                  ("--out-dir", a.out_dir)) if not v]
        if missing:
            ap.error(f"missing {', '.join(missing)} — required unless --from-episodes "
                     f"or --from-geometry is given")
        if a.stop_after_geometry:
            if a.music or a.changelog:
                ap.error("--music / --changelog have no effect with --stop-after-geometry: "
                         "both are baked into the ReelManifest, and phase 1a assembles none "
                         "— GEOMETRY.json carries routes, not a reel. Pass them to the "
                         "--from-geometry invocation instead")
            geo, stop = build_geometry(a.edl, a.project, a.footage_root, a.work_dir,
                                       a.out_dir, jobs=jobs)
            result = stop if stop else {
                "status": "geometry_ready",
                "geometry": str(Path(a.out_dir) / GEOMETRY_JSON),
                "count": len(geo.episodes)}
        else:
            fn = process_episodes if a.stop_after_episodes else edl_to_reel
            kw = ({} if a.stop_after_episodes
                  else {"titles": a.titles, "deliveries_dir": a.deliveries_dir})
            result = fn(a.edl, a.project, a.footage_root, a.work_dir, a.out_dir,
                        music=a.music, jobs=jobs,
                        changelog=a.changelog, **kw)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] in ("delivered", "episodes_ready",
                                               "geometry_ready") else 1)


if __name__ == "__main__":
    main()
