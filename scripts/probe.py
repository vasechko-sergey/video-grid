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
import dataclasses
import json
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import process_episode, reframe
from scripts.lib import (assembly, color, edl as edl_lib, ffbin, lookcheck,
                         naturalness, orchestration as orch, proc, provenance, sheet)
from scripts.lib.edl import EDL
from scripts.lib.manifest import Manifest
from scripts.lib.models import CropPath, Delivery, PathMeta, ReelManifest

FRAMES = 3          # start / middle / end of the window, at (i+0.5)/N — never the
                    # first or last frame, which a dip or a bookend can own

# The colour block, as it crosses edl.to_manifest_dict. A CLOSED set, because regrade
# below must DROP these before re-applying: to_manifest_dict omits highlight_red,
# tone_src and tone_dst at their identity, so a plain merge would keep a value the
# author has just deleted from the EDL.
_COLOUR_KEYS = ("color_means", "white_balance", "black_point", "highlight",
                "highlight_red", "saturation", "shadow_red", "mid_blue", "dip",
                "tone_src", "tone_dst")

# The value Manifest.from_dict falls back to for each of _COLOUR_KEYS when the JSON
# key is absent or explicitly null — compare white_balance=float(d.get("white_balance")
# or 0.0) in manifest.py against Manifest's own `white_balance: float = 0.0` field
# declaration, and so on for all eleven: from_dict's fallback logic was written to
# reproduce the field default, not to invent a second number. DERIVED from Manifest's
# dataclass fields rather than hand-copied here, so this cannot drift the day someone
# edits a default in manifest.py and forgets this file exists — reading the dataclass
# IS agreeing with Manifest's own behaviour, not a second, independently-maintained
# opinion about it. (Only 3 of the 11 are ever actually consulted below — regrade's
# `fresh.get(k, ...)` — since to_manifest_dict emits the other 8 unconditionally; kept
# total anyway so this map's meaning does not depend on to_manifest_dict's internals.)
#
# Safe only because every Manifest field uses a plain `= value` default, never
# `field(default_factory=...)` (manifest.py imports `dataclass` but never `field`) — a
# default_factory field's own .default is dataclasses.MISSING and would poison this
# map silently. Verified empirically for all eleven names; re-check that invariant
# before ever widening _COLOUR_KEYS to a field manifest.py declares differently.
_COLOUR_IDENTITY = {f.name: f.default for f in dataclasses.fields(Manifest)
                    if f.name in _COLOUR_KEYS}


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


def regrade(md: dict, edl_path: str, index: int) -> dict:
    """`md` with its colour block replaced by EDL episode `index`'s.

    Dropped and re-applied, never merged — see _COLOUR_KEYS. Everything else (the
    segment, the resolved canvas/delivery the project filled in, the layout, the
    hero) stays exactly as the run resolved it: this probes a NEW GRADE on the SAME
    episode, and re-deriving the rest would silently probe a different cut.

    edl_lib.to_manifest_dict OMITS a colour key from its result when the episode
    holds that field at its identity value (highlight_red 0.0; tone_src/tone_dst
    None), to keep an authored EDL terse. Read literally, "update with what's
    there" would then leave `out` without that key at all rather than at its new
    (identity) value — not the stale OLD value a plain merge would keep, but still
    not the fact this function's whole job is to state: what the episode's colour
    block IS now. _COLOUR_IDENTITY supplies the value to_manifest_dict left
    implicit, so every one of _COLOUR_KEYS is always present in `out`.

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
    out = {k: v for k, v in md.items() if k not in _COLOUR_KEYS}
    out.update({k: fresh.get(k, _COLOUR_IDENTITY[k]) for k in _COLOUR_KEYS})
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


def _tone(f: np.ndarray) -> tuple[float, float, float]:
    """(p5, p50, p95) luma — the same three anchors ReframeSpec.tone_src/tone_dst speak
    in, so a probe reading drops straight into an EDL pair.

    Computed in numpy from RGB with the BT.601 weights, where color_measure gets its
    histogram from ffmpeg's `format=gray`. The two can differ by a code or so on the
    same frame; both feed the same three anchors, and a tone pair is authored in whole
    codes.
    """
    luma = 0.299 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.114 * f[:, :, 2]
    hist = np.bincount(luma.astype(np.uint8).ravel(), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def _render(plan: reframe.RenderPlan, src: str, times: list[float],
            out_dir: Path) -> list[np.ndarray]:
    """The probe's sink: the plan's own chain plus a select, straight to PNG.

    No -ss anywhere. An input seek would reset each frame's timestamp, and the crop's
    x is a function of t — the crop would land somewhere else, silently (§12's seek
    landmine in its worst form). select never moves a timestamp.
    """
    nums = [round(t * plan.fps) for t in times]
    sel = "select='" + "+".join(rf"eq(n\,{n})" for n in nums) + "'"
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("f*.png"):
        p.unlink()
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, *plan.with_tail(sel),
              "-t", f"{plan.dur:.6f}", "-vsync", "0",
              "-frames:v", str(len(nums)), str(out_dir / "f%03d.png")])
    pngs = sorted(out_dir.glob("f*.png"))
    if len(pngs) != len(nums):
        raise RuntimeError(
            f"probe asked for {len(nums)} frames {nums} and ffmpeg emitted {len(pngs)} "
            f"— a frame number is past the stream's end (times {times} against a "
            f"{plan.dur:.3f}s source at {plan.fps:.4g}fps)")
    return [np.asarray(Image.open(p).convert("RGB")) for p in pngs]


def probe_grade(episodes_path: str, index: int, *, edl_path: str | None = None,
                out_dir: str | None = None, frames: int = FRAMES) -> dict:
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
    m = Manifest.from_dict(md)
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        params["smooth_window_s"] = m.smooth_window_s
    spec = process_episode.build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    src = source_for(md, epdir)
    plan = reframe.plan_render(spec, src, ep.route)
    _refuse_on_drift(plan, ep.path, ep.meta)

    d = Path(out_dir) if out_dir is not None else epdir / "probe"
    times = [((i + 0.5) / frames) * plan.dur for i in range(frames)]
    imgs = _render(plan, src, times, d)
    stats = naturalness.measure(imgs)
    report = {
        "episode": index, "episodes": episodes_path, "edl": edl_path,
        "source": src, "frames": len(imgs),
        "times": [round(t, 3) for t in times],
        "grade": plan.grade,
        "colour": {k: md[k] for k in _COLOUR_KEYS if k in md},
        "tone": [[round(v, 1) for v in _tone(f)] for f in imgs],
        "naturalness": {"stats": stats, "flags": naturalness.evaluate(stats)},
    }
    (d / "probe.json").write_text(json.dumps(report, indent=2))
    cells = [sheet.Cell(image=f,
                        lines=(f"t={t:.2f}s",
                               "p5/p50/p95 " + "/".join(f"{v:.0f}" for v in tone)))
             for f, t, tone in zip(imgs, times, report["tone"])]
    sheet.tile(cells).save(str(d / "probe.jpg"), quality=90)
    return report


def probe_look(master: str, delivered: str, *, vignette: float = 0.0,
               fade: float = 0.0, titles: bool = False) -> list[dict]:
    """The delivered-look check deliver gates on, run by hand against two files."""
    dur = assembly.probe_duration(delivered)
    ts = [dur * 0.25, dur * 0.5, dur * 0.75]
    m_fps, d_fps = assembly.probe_stream(master).fps, assembly.probe_stream(delivered).fps
    mm = assembly.frames_rgb(master, ts, m_fps)
    dd = assembly.frames_rgb(delivered, ts, d_fps)
    f_m = f_d = l_m = l_d = None
    if fade:
        f_m = assembly.frames_rgb(master, [0.0], m_fps)[0]
        f_d = assembly.frames_rgb(delivered, [0.0], d_fps)[0]
        # each file's TRUE last frame, via last_frame_rgb rather than a computed
        # timestamp — sampling both sides at one shared timestamp would miss exactly
        # the failure this check exists to catch (deliver derives the fade-out from
        # the MASTER's duration; a shorter muxed audio stem truncates the DELIVERED
        # file before the fade-out reaches black), and a computed `dur - 1/fps` can
        # itself land past a file's real last frame (design 2026-08-15 §7, amended —
        # final review I-3; see assembly.last_frame_rgb)
        l_m = assembly.last_frame_rgb(master, m_fps)
        l_d = assembly.last_frame_rgb(delivered, d_fps)
    return [f.to_dict() for f in lookcheck.evaluate(
        mm, dd, f_m, f_d, l_m, l_d, vignette=vignette, fade=fade, fps=d_fps,
        titles=titles)]


def main() -> None:
    ap = argparse.ArgumentParser(description="cheap frame probes: converge a grade, "
                                             "or re-check a delivered look")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grade", help="render+measure N frames of one episode over its "
                                     "frozen route")
    g.add_argument("--episodes", required=True, help="EPISODES.json from "
                                                     "edl_to_reel --stop-after-episodes")
    g.add_argument("--index", type=int, required=True)
    g.add_argument("--edl", default=None, help="take the colour block from this "
                                               "(edited) EDL.json instead of the "
                                               "grade that was rendered")
    g.add_argument("--out-dir", default=None, help="default: <epdir>/probe")
    g.add_argument("--frames", type=int, default=FRAMES)

    lk = sub.add_parser("look", help="re-check a delivered reel against its master")
    lk.add_argument("master")
    lk.add_argument("delivered")
    lk.add_argument("--vignette", type=float, default=0.0)
    lk.add_argument("--fade", type=float, default=0.0)
    lk.add_argument("--titles", action="store_true")

    a = ap.parse_args()
    if a.cmd == "grade":
        r = probe_grade(a.episodes, a.index, edl_path=a.edl, out_dir=a.out_dir,
                        frames=a.frames)
        print(json.dumps(r, indent=2))
    else:
        print(json.dumps(probe_look(a.master, a.delivered, vignette=a.vignette,
                                    fade=a.fade, titles=a.titles), indent=2))


if __name__ == "__main__":
    main()
