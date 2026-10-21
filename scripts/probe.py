"""Cheap frame probes (design docs/specs/2026-08-15-frame-probe-look-gate-design.md).

`grade` renders N frames of ONE episode through the SAME chain reframe would encode,
over the FROZEN route, and measures them — so a grade converges here instead of
costing a reel per attempt. It skips the tracking pass, the storyboard, the check and
the x264 encode; measured, a tracking pass alone costs 5.00s against the encode's
0.59-2.41s on the same 1080p/3s clip.

`look` re-runs the delivered-reel check deliver already gates on, by hand.

This driver decides nothing about colour. The sensors it prints have uncalibrated
first-cut thresholds (naturalness.py says so itself), and a solver over an
uncalibrated taste function invents a target — match_grade remains the deterministic
lane. The agent looks, edits the EDL, probes again.
"""
import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import color_measure, deliver, process_episode, reframe
from scripts.lib import (assembly, color, edl as edl_lib, ffbin, gates as gates_lib,
                         gradedamage, naturalness, proc, provenance, sheet)
from scripts.lib.edl import EDL
from scripts.lib.look import LookSpec
from scripts.lib.manifest import COLOUR_IDENTITY, COLOUR_KEYS
from scripts.lib.models import CheckSpec, CropPath, PathMeta, ReelGeometry, ReelManifest

# FRAMES/sample_times live in color (scripts/lib/color.py) now (design
# 2026-08-31 grade-sensor-references §6) — check_episode needs them and cannot
# import color_measure (color_measure imports process_episode, which imports
# check_episode: a cycle). A probe defining its own FRAMES would be a second
# constant that must agree with the conductor's and the gate's, which is
# exactly the drift this slice removes.


def source_for(md: dict, epdir: Path | str) -> str:
    """The file reframe ACTUALLY consumed for this episode.

    Under `stabilize` that is the pre-stage's output, not md["segment"] — process_episode
    runs vidstab.stabilize and hands ITS output to both the tracker and reframe (design
    2026-07-20 §1). A probe that reaches for the raw segment there renders different
    pixels than shipped and reports them as the episode's, which is precisely the
    silent-wrong-answer this whole slice exists to prevent.
    """
    if not md.get("stabilize"):
        return md["segment"]
    st = Path(epdir) / "stabilized.mp4"
    if not st.exists():
        raise FileNotFoundError(
            f"this episode declares stabilize but {st} is gone — reframe consumed the "
            f"stabilized pre-stage output, so probing {md['segment']} would render pixels "
            f"the episode never shipped. Re-run the episode (process_episode leaves the "
            f"file beside path.json), or drop stabilize from the EDL")
    return str(st)


_DEFAULT_ENTROPY_FLOOR = CheckSpec.__dataclass_fields__["entropy_floor"].default


def _entropy_floor(authored: gates_lib.Gates) -> float:
    """The floor check_episode's grade_damage will judge by: the authored one, else CheckSpec's own
    default. The probe predicts that gate without a reel re-render, and a prediction made against
    a different bar than the gate will use is worse than none — the cry-wolf mechanism with the
    sign flipped, a tool saying "this will fail" about a render that will pass (design
    2026-09-30 §2.3). It read the dataclass default directly until GATES.json existed, which the
    design's census missed because nothing here constructs a CheckSpec."""
    return authored.for_spec(CheckSpec).get("entropy_floor", _DEFAULT_ENTROPY_FLOOR)


def _gates_for_geometry(geo: ReelGeometry) -> tuple[gates_lib.Gates, str]:
    """(the gates authored beside the project GEOMETRY.json recorded, "") — or (no gates, why the
    file could not even be looked for). The second is a NAMED absence, never "none authored":
    nothing has been encoded yet, so there is no EPISODES.json to read the frozen set from, and
    the set phase 1b will use is found beside the project at that run's own time.

    The project may not resolve from here — nothing recorded (a GEOMETRY.json from before the
    field), a project that has since moved, or a bare relative name read from another working
    directory — and in each the gates cannot be looked for at all. Answering with the default
    floor and no word would read as "no gates authored", which nobody stated. The test is the
    project FILE and not its parent directory, for the reason match_grade._find_regions gives:
    the parent of a bare "project.json" is ".", which exists from any directory, so a directory
    test would look for ./GATES.json wherever the probe happens to run and call the answer "none".

    A file that resolves and cannot be loaded is not caught: phase 1b would refuse it the same
    way, so a probe predicting a gate that cannot run has nothing honest to say."""
    if not geo.project:
        return gates_lib.Gates(), "GEOMETRY.json records no project"
    project = Path(geo.project)
    if not project.is_file():
        return gates_lib.Gates(), (f"{geo.project} does not resolve from here — no file at "
                                   f"{project.resolve()}")
    return gates_lib.beside_project(project), ""


def regrade(md: dict, edl_path: str, index: int) -> dict:
    """`md` with its colour block replaced by EDL episode `index`'s.

    Dropped and re-applied, never merged — see COLOUR_KEYS. Everything else (the
    segment, the resolved canvas/delivery the project filled in, the layout, the
    hero) stays exactly as the run resolved it: this probes a NEW GRADE on the SAME
    episode, and re-deriving the rest would silently probe a different cut.

    edl_lib.to_manifest_dict OMITS a colour key from its result when the episode
    holds that field at its identity value (highlight_red 0.0; tone_src/tone_dst
    None), to keep an authored EDL terse. Read literally, "update with what's
    there" would then leave `out` without that key at all rather than at its new
    (identity) value — not the stale OLD value a plain merge would keep, but still
    not the fact this function's whole job is to state: what the episode's colour
    block IS now. COLOUR_IDENTITY supplies the value to_manifest_dict left
    implicit, so every one of COLOUR_KEYS is always present in `out`.

    `edl_path` must reach here through the ordinary front door: edit
    `selection.json`, then re-run `edit_plan build`, which re-stamps EDL.json
    (design §4, amended). A hand-edited EDL.json fails EDL.from_json's own tamper
    check (design 2026-08-04, provenance.check) — this catches THAT refusal and
    re-raises one naming this loop specifically, chained with `from e` so the
    original digest mismatch is not lost. It does NOT weaken or bypass the check:
    governance says editorial changes go through selection.json, and a probe that
    read a tampered EDL anyway would itself be the second authoring surface the
    design forbids.
    """
    try:
        e = EDL.from_json(edl_path)
    except ValueError as ex:
        raw = None
        try:
            raw = json.loads(Path(edl_path).read_text())
        except (OSError, json.JSONDecodeError):
            pass
        if not (isinstance(raw, dict) and provenance.check(raw)[0] == "tampered"):
            raise      # a different failure (bad JSON, an unreadable episode field,
                       # ...) — its own message and remedy are already right
        raise ValueError(
            f"{edl_path} was hand-edited after edit_plan wrote it ({ex}), so the "
            f"probe will not read it either. Converge a grade through "
            f"selection.json, never EDL.json directly: edit the episode's colour "
            f"fields in selection.json, re-run `edit_plan build` (a pure "
            f"projection — no ffmpeg — that re-stamps EDL.json), then probe THAT "
            f"freshly-written file again") from ex
    if not 0 <= index < len(e.episodes):
        raise IndexError(f"--edl has {len(e.episodes)} episodes; index {index} is out of "
                         f"range. The index is the episode's position in BOTH EDL.json and "
                         f"EPISODES.json — they must describe the same cut")
    fresh = edl_lib.to_manifest_dict(e.episodes[index], md["segment"], md["out_path"])
    out = {k: v for k, v in md.items() if k not in COLOUR_KEYS}
    out.update({k: fresh.get(k, COLOUR_IDENTITY[k]) for k in COLOUR_KEYS})
    return out


def _refuse_on_drift(plan: reframe.RenderPlan, path_json: str, meta_json: str) -> None:
    """Refuse unless the recomputed geometry is what actually shipped.

    The probe's whole claim is that its pixels are the pixels the next render ships.
    That holds because a grade cannot move the crop (design §2). So if the recomputed
    geometry does NOT match the frozen sidecars, the claim is already false.

    The PATH comparison is the load-bearing half: a retry-adjusted max_speed or
    smooth_window_s moves every x while leaving the recorded rect identical, so the
    meta check alone would wave it straight through.

    The meta comparison carries `cy` for the SAME reason, in the other axis:
    CropPath.xs is x only, so a route whose vertical placement moved while every x
    stayed put (final review I-1 — e.g. a re-track that only shifted where the
    subject sits top-to-bottom) would pass the path comparison unchanged and,
    without cy here, pass the meta comparison too. `cy` derives from the route's
    mean y where the path derives from its x, so this is the one place y is ever
    checked at all.
    """
    frozen = CropPath.from_json(path_json).xs
    if list(plan.path) != list(frozen):
        where = next((i for i, (a, b) in enumerate(zip(plan.path, frozen)) if a != b),
                     min(len(plan.path), len(frozen)))
        raise RuntimeError(
            f"the recomputed crop path does not match the frozen {path_json} "
            f"({len(plan.path)} points vs {len(frozen)}, first difference at index "
            f"{where}) — a grade cannot move the crop, so something else changed: a "
            f"re-track, a retry-adjusted max_speed/smooth_window_s, or a different "
            f"source file. Re-render this episode, then probe the render you got")
    meta = PathMeta.from_json(meta_json)
    got = (plan.rl.mode, plan.rl.crop_w, plan.rl.crop_h, plan.cy,
           (plan.rl.out_w, plan.rl.out_h))
    want = (meta.mode, meta.crop_w, meta.crop_h, meta.crop_y, tuple(meta.out_dims))
    if got != want:
        raise RuntimeError(
            f"the recomputed geometry does not match the frozen {meta_json}: "
            f"mode/crop/crop_y/out {got} vs {want}. The layout, the delivery, or the "
            f"crop's vertical placement changed since this episode was rendered — cy "
            f"comes from the route's mean y, which the path comparison above never "
            f"looks at (it carries only x), so a route whose y moved without its x "
            f"would have passed that check and shown up only here. The probe would "
            f"show a frame this episode never produced. Re-render it first")


def _render(plan: reframe.RenderPlan, src: str, times: list[float],
            out_dir: Path) -> list[np.ndarray]:
    """The probe's sink: the plan's own chain plus a select, straight to PNG.

    No -ss anywhere. An input seek would reset each frame's timestamp, and the crop's
    x is a function of t — the crop would land somewhere else, silently (§12's seek
    landmine in its worst form). select never moves a timestamp.
    """
    sel = color.select_frames(times, plan.fps)
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("f*.png"):
        p.unlink()
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, *plan.with_tail(sel),
              "-t", f"{plan.dur:.6f}", "-vsync", "0",
              "-frames:v", str(len(times)), str(out_dir / "f%03d.png")])
    pngs = sorted(out_dir.glob("f*.png"))
    if len(pngs) != len(times):
        raise RuntimeError(
            f"probe asked for {len(times)} frames at {times} and ffmpeg emitted "
            f"{len(pngs)} — a frame number is past the stream's end (against a "
            f"{plan.dur:.3f}s source at {plan.fps:.4g}fps)")
    return [np.asarray(Image.open(p).convert("RGB")) for p in pngs]


def probe_grade(episodes_path: str, index: int, *, edl_path: str | None = None,
                out_dir: str | None = None, frames: int = color.FRAMES) -> dict:
    """Render and measure `frames` frames of episode `index`. Returns the report dict
    it also writes to probe.json, beside a probe.jpg of the frames themselves.

    With `edl_path`, the colour block comes from that (edited) EDL through the same
    bridge the real run uses, so what converges is exactly what ships. Without it, the
    grade that WAS rendered — the baseline to compare against.
    """
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"probe: frames must be an integer >= 1, got {frames!r}")
    rm = ReelManifest.from_json(episodes_path)
    if not 0 <= index < len(rm.episodes):
        raise IndexError(f"{episodes_path} has {len(rm.episodes)} episodes; index "
                         f"{index} is out of range. The index is the episode's "
                         f"position within EPISODES.json (and, when --edl is also "
                         f"passed, must be that SAME episode's position in EDL.json "
                         f"too) — pick an index in [0, {len(rm.episodes)})")
    ep = rm.episodes[index]
    epdir = Path(ep.path).parent
    md = dict(ep.manifest)
    if edl_path is not None:
        md = regrade(md, edl_path, index)
    src = source_for(md, epdir)
    # The params this episode's render RECORDED, not the declaration's: an episode
    # whose accepted attempt was not attempt 1 shipped with rescaled
    # max_speed/smooth_window_s, and rebuilding at the defaults made _refuse_on_drift
    # refuse the probe with a remedy — "re-render, then probe" — that could not
    # restore them (design 2026-09-24 §0.3). Read ONCE and used for both halves of
    # the pair below: two reads could not disagree today, but two call sites is how
    # one of them later stops being updated.
    params = process_episode.rendered_params(ep.meta)
    plan = process_episode.plan_for(md, src, ep.route, params=params)
    _refuse_on_drift(plan, ep.path, ep.meta)

    d = Path(out_dir) if out_dir is not None else epdir / "probe"
    times = color.sample_times(plan.dur, frames)
    imgs = _render(plan, src, times, d)
    stats = naturalness.measure(imgs)
    tone = color_measure.crop_percentiles(plan, src, times)
    # The same pair check_episode.grade_damage renders: `imgs` above is the graded
    # half, this is the plain one — every colour knob at identity, from the SAME
    # md/src/route the graded render came from. A predictor that disagreed with the
    # gate it predicts would be worse than none (design 2026-08-31 §3/§8).
    plain = process_episode.plan_ungraded(md, src, ep.route, params=params)
    # grade_damage here and predicted_profile below (in `report`) both predict a
    # gate that ALWAYS samples at the DEFAULT count — check_episode._grade_damage
    # and build_reel._predict, neither takes a `frames` argument. --frames widens
    # the STILLS a human looks at (`imgs`, `tone_profile`) and must move neither
    # prediction, or a probe run with a non-default --frames would silently report
    # numbers the real gates were never going to compare against (Task 8 fix round
    # 1 fixed this for predicted_profile; fix round 2 does the same here). When
    # `frames` is already the default, `times` already IS the default sample set
    # and the graded frames rendered above (`imgs`) are reused at zero extra cost;
    # only a non-default --frames pays for a second, small, default-count render.
    if frames == color.FRAMES:
        damage_times, damage_graded = times, imgs
    else:
        damage_times = color.sample_times(plan.dur)
        damage_graded = reframe.plan_frames_rgb(plan, src, damage_times)
    # The set that judged THESE clips: the manifest froze it, so it is the bar the prediction
    # must use (design §2.3). probe_grade_geometry has no manifest and finds it beside the project.
    authored = gates_lib.Gates.from_dict(rm.gates, where="ReelManifest.gates")
    damage = gradedamage.evaluate(
        plain=reframe.plan_frames_rgb(plain, src, damage_times),
        graded=damage_graded,
        floor=_entropy_floor(authored))
    report = {
        "episode": index, "episodes": episodes_path, "edl": edl_path,
        "source": src, "frames": len(imgs),
        "times": [round(t, 3) for t in times],
        "grade": plan.grade,
        "colour": {k: md[k] for k in COLOUR_KEYS if k in md},
        "tone_profile": [round(v, 1) for v in tone],
        # predicted_profile: same reasoning as grade_damage above — always the
        # default sample count, independent of --frames.
        "predicted_profile": [round(v, 1) for v in color_measure.crop_percentiles(
            plan, src, color.sample_times(plan.dur))],
        "grade_damage": damage,
        "naturalness": {"stats": stats, "flags": naturalness.evaluate(stats)},
    }
    (d / "probe.json").write_text(json.dumps(report, indent=2))
    cells = [sheet.Cell(image=f, lines=(f"t={t:.2f}s",)) for f, t in zip(imgs, times)]
    sheet.tile(cells).save(str(d / "probe.jpg"), quality=90)
    return report


def probe_grade_geometry(geometry_path: str, index: int, *, out_dir: str | None = None,
                         frames: int = color.FRAMES) -> dict:
    """Render and measure `frames` frames of episode `index` from GEOMETRY.json —
    edl_to_reel --stop-after-geometry's output — before any episode has EVER been
    encoded. Returns the report dict it also writes to probe.json, beside a probe.jpg.

    R3.1's "draft 2" (design 2026-08-30 §4): a stage taking source + route + colour
    block and emitting stills, so a grade converges in seconds instead of a reel per
    attempt. Two differences from probe_grade:

    There is no "grade that was rendered" to fall back to, because nothing has
    rendered yet — so unlike probe_grade's OPTIONAL `edl_path`, this ALWAYS applies
    the EDL's CURRENT colour block, through the same `regrade` probe_grade uses,
    reading `geo.edl` VERBATIM (never resolve()d — the rest of the pipeline reads it
    the same way, and tests pin that). The `md["segment"]`/`md["out_path"]` regrade
    needs to rebuild the fresh manifest come from `eg.manifest`: build_geometry stores
    it colour-STRIPPED, but segment/out_path are not colour fields and survive the
    strip untouched.

    And there is no `_refuse_on_drift`: that oracle exists to catch the recomputed
    geometry disagreeing with a FROZEN path.json/path.meta.json, and neither sidecar
    exists yet — the plan IS the source of truth before an encode. The report SAYS so
    (`drift_checked: False`) rather than silently omitting the check; the `--episodes`
    mode keeps the oracle.

    `source` is `EpisodeGeometry.source` — the file reframe will actually consume —
    rather than `source_for`'s filename inference, which has nothing on disk to infer
    from before process_episode has ever run this episode.

    A pan episode (`eg.route is None`) is not special-cased: `process_episode.plan_for`
    generates its path exactly as a real render would (design 2026-08-30 plan, Task 4
    proved this with real ffmpeg against `measure_crop`).
    """
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"probe: frames must be an integer >= 1, got {frames!r}")
    geo = ReelGeometry.from_json(geometry_path)
    if not 0 <= index < len(geo.episodes):
        raise IndexError(f"{geometry_path} has {len(geo.episodes)} episodes; index "
                         f"{index} is out of range. The index is the episode's "
                         f"position in BOTH GEOMETRY.json and the EDL it names "
                         f"({geo.edl}) — pick an index in [0, {len(geo.episodes)})")
    eg = geo.episodes[index]
    md = regrade(dict(eg.manifest), geo.edl, index)
    # process_episode.plan_for probes eg.source; source_for's own FileNotFoundError has
    # no reach here (nothing is inferred from a filename in geometry mode), so the same
    # condition is refused with the same remedy before any ffprobe (whole-branch review,
    # minor 5). AFTER regrade: a tampered EDL is the more specific complaint of the two,
    # and answering "your file is missing" to it would send the reader to the wrong place.
    eg.require_inputs(index)
    # Before anything is rendered: a GATES.json that resolves and cannot be loaded raises here,
    # and a probe that has just spent its renders should not be what reports it.
    authored, unread = _gates_for_geometry(geo)
    plan = process_episode.plan_for(md, eg.source, eg.route)

    d = Path(out_dir) if out_dir is not None else Path(eg.project_dir) / "probe"
    times = color.sample_times(plan.dur, frames)
    imgs = _render(plan, eg.source, times, d)
    stats = naturalness.measure(imgs)
    tone = color_measure.crop_percentiles(plan, eg.source, times)
    # Same pair as probe_grade (see its comment) — eg.source/eg.route rather than a
    # source_for()-resolved path, since geometry mode has nothing rendered yet to
    # infer one from.
    plain = process_episode.plan_ungraded(md, eg.source, eg.route)
    # grade_damage/predicted_profile: same reasoning as probe_grade's comment —
    # both predict a gate that always samples at the default count, independent
    # of --frames, reusing the frames already rendered above when frames is
    # already the default and paying for a second small render only when it is not.
    if frames == color.FRAMES:
        damage_times, damage_graded = times, imgs
    else:
        damage_times = color.sample_times(plan.dur)
        damage_graded = reframe.plan_frames_rgb(plan, eg.source, damage_times)
    damage = gradedamage.evaluate(
        plain=reframe.plan_frames_rgb(plain, eg.source, damage_times),
        graded=damage_graded,
        floor=_entropy_floor(authored))
    report = {
        "episode": index, "geometry": geometry_path, "edl": geo.edl,
        "source": eg.source, "frames": len(imgs),
        "times": [round(t, 3) for t in times],
        "grade": plan.grade,
        "colour": {k: md[k] for k in COLOUR_KEYS if k in md},
        "tone_profile": [round(v, 1) for v in tone],
        # predicted_profile: same reasoning as grade_damage above — always the
        # default sample count, independent of --frames.
        "predicted_profile": [round(v, 1) for v in color_measure.crop_percentiles(
            plan, eg.source, color.sample_times(plan.dur))],
        "grade_damage": damage,
        "naturalness": {"stats": stats, "flags": naturalness.evaluate(stats)},
        "drift_checked": False,     # there is no path.json yet: the plan IS the
                                    # source of truth before the encode. The
                                    # --episodes mode keeps the oracle.
    }
    if unread:
        # A named absence, present only when the gates could not be looked for — so a probe
        # with a resolvable project keeps the report it always had, and this key means
        # exactly "the floor above was NOT read from GATES.json, it is the default".
        report["gates"] = {"status": "not-read", "reason": (
            f"{unread}, so GATES.json cannot be looked for beside it. grade_damage.floor is "
            f"therefore CheckSpec's DEFAULT ({_DEFAULT_ENTROPY_FLOOR}), which is not "
            f"necessarily the bar these episodes will be judged by — run the probe from the "
            f"directory the project was recorded in, or re-run edl_to_reel "
            f"--stop-after-geometry with an absolute --project")}
    (d / "probe.json").write_text(json.dumps(report, indent=2))
    cells = [sheet.Cell(image=f, lines=(f"t={t:.2f}s",)) for f, t in zip(imgs, times)]
    sheet.tile(cells).save(str(d / "probe.jpg"), quality=90)
    return report


def probe_look(master: str, delivered: str, *, vignette: float = 0.0,
               fade: float = 0.0, titles: str | None = None,
               fade_in: float | None = None, platform: str = "",
               flashes: Sequence[float] = ()) -> list[dict]:
    """The delivered-look check deliver gates on, run by hand against two files — and
    it IS deliver's gate (deliver._verify_look), not a second copy of its sampling: the
    bookend frames, the interior frames moved off every shutter flash, and each title's
    in-window and witness frames (`titles`, the TITLES.json burned into the delivery,
    laid out against `platform`).

    `flashes` are the shutter flash times on the master, as the delivery's attestation
    lists them (design 2026-10-21 §4). Leave them out on a flashed delivery and its
    white frames are compared against the master as if they were a look — the false
    vignette or title readings the real gate steps around."""
    return [f.to_dict() for f in deliver._verify_look(
        master, delivered, LookSpec(vignette=vignette, fade=fade, fade_in=fade_in),
        titles, platform, flashes)]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="cheap frame probes: converge a grade, "
                                             "or re-check a delivered look")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grade", help="render+measure N frames of one episode over its "
                                     "frozen route",
                       description="render and measure N frames of one episode over its "
                                   "frozen route, through the same chain the real encode "
                                   "uses → probe.jpg + probe.json. Converges a colour "
                                   "grade without re-rendering the reel. Its grade_damage "
                                   "prediction uses the entropy_floor the run's GATES.json "
                                   "authored — read from EPISODES.json with --episodes, from "
                                   "beside the project GEOMETRY.json records with --geometry, "
                                   "where an unresolvable project is reported as `gates: "
                                   "not-read` rather than read as no gates.")
    mode = g.add_mutually_exclusive_group()
    mode.add_argument("--episodes", default=None, help="EPISODES.json from "
                                                       "edl_to_reel --from-geometry (or "
                                                       "--stop-after-episodes) — the grade "
                                                       "that WAS rendered")
    mode.add_argument("--geometry", default=None, help="GEOMETRY.json from edl_to_reel "
                                                       "--stop-after-geometry — renders "
                                                       "before any episode is ever "
                                                       "encoded, always on the EDL's "
                                                       "CURRENT colour block (the EDL "
                                                       "itself is the file GEOMETRY.json "
                                                       "names, not a separate flag)")
    g.add_argument("--index", type=int, required=True, help="which episode, 0-based")
    g.add_argument("--edl", default=None, help="--episodes only: take the colour block "
                                               "from this (edited) EDL.json instead of "
                                               "the grade that was rendered")
    g.add_argument("--out-dir", default=None, help="default: <epdir>/probe")
    g.add_argument("--frames", type=int, default=color.FRAMES,
                   help="how many frames to render and measure")

    lk = sub.add_parser("look", help="re-check a delivered reel against its master",
                        description="re-check a delivered reel against its master for a "
                                    "declared vignette, bookend fade and title ink — the "
                                    "same gate deliver runs after its encode, runnable by "
                                    "hand.")
    lk.add_argument("master", help="the reel master the delivery was encoded from")
    lk.add_argument("delivered", help="the delivered reel to re-check")
    lk.add_argument("--vignette", type=float, default=0.0,
                    help="the vignette strength that was declared, 0..0.6")
    lk.add_argument("--fade", type=float, default=0.0,
                    help="the closing fade that was declared, seconds (and the opening "
                         "one, unless --fade-in)")
    lk.add_argument("--fade-in", type=float, default=None,
                    help="the opening fade that was declared, seconds, when it differs "
                         "from --fade (0 = the reel opens on picture)")
    lk.add_argument("--titles", default=None,
                    help="the TITLES.json burned into the delivery — also check that its "
                         "ink reached the pixels")
    lk.add_argument("--platform", default="",
                    help="the safe-zone table key the titles were laid out against "
                         "(reel/tiktok/shorts/…), as deliver was given it")
    lk.add_argument("--flash", type=float, action="append", default=[], metavar="SECONDS",
                    help="a shutter flash's time on the master, in seconds — repeat per "
                         "flash; the delivery's attestation lists them as `flashes`. The "
                         "check steps around each, as deliver's does")
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    if a.cmd == "grade":
        if not a.episodes and not a.geometry:
            ap.error("grade needs exactly one of --episodes or --geometry: --episodes "
                     "reads the grade that WAS rendered (edl_to_reel --from-geometry, or "
                     "--stop-after-episodes); --geometry renders before any episode is "
                     "ever encoded (edl_to_reel --stop-after-geometry)")
        if a.geometry and a.edl:
            ap.error("--edl has no effect with --geometry: geometry mode always applies "
                     "the EDL's CURRENT colour block, read from the path GEOMETRY.json "
                     "itself names — there is no 'grade that was rendered' to fall back "
                     "to, because nothing has been encoded yet")
        if a.geometry:
            r = probe_grade_geometry(a.geometry, a.index, out_dir=a.out_dir,
                                     frames=a.frames)
        else:
            r = probe_grade(a.episodes, a.index, edl_path=a.edl, out_dir=a.out_dir,
                            frames=a.frames)
        print(json.dumps(r, indent=2))
    else:
        print(json.dumps(probe_look(a.master, a.delivered, vignette=a.vignette,
                                    fade=a.fade, fade_in=a.fade_in, titles=a.titles,
                                    platform=a.platform, flashes=a.flash), indent=2))


if __name__ == "__main__":
    main()
