"""Real ffmpeg. The probe's central claim is that its frames are the frames the full
render ships; the look gate's is that a declared effect reached the delivered pixels.
Both are pixel claims and are proved on pixels."""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from scripts import check_episode, deliver as deliver_mod, probe, process_episode, reframe
from scripts.lib import (assembly, color, ffbin, gradedamage, layout as layout_lib,
                         orchestration as orch, proc, provenance)
from scripts.lib.edl import EDL, EDLEpisode, write_edl
from scripts.lib.look import LookSpec
from scripts.lib.manifest import Manifest, strip_colour
from scripts.lib.models import (CheckSpec, Delivery, EpisodeGeometry, ExportProfile, PanSpec,
                                ReelEpisode, ReelGeometry, ReelManifest, ReelReport, ReframeSpec)

pytestmark = pytest.mark.integration


def _grainy(tmp_path: Path, w: int = 640, h: int = 360, dur: float = 3.0) -> str:
    """Grain is the WORST case for x264 at crf 18, so the probe-vs-shipped gap this
    measures is an upper bound on real footage."""
    dst = str(tmp_path / "src.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"testsrc2=s={w}x{h}:r=30:d={dur:g}",
              "-vf", "noise=alls=40:allf=t+u",
              "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
              "-pix_fmt", "yuv420p", dst])
    return dst


def _spec() -> ReframeSpec:
    return ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(112.0, 118.0, 130.0),
                       delivery=Delivery.from_spec("short_edge:360"),
                       pan=PanSpec(start=0.0, end=0.3),
                       tone_src=[18.0, 110.0, 220.0], tone_dst=[26.0, 118.0, 210.0],
                       black_point=0.08, saturation=1.1)


def test_the_probes_frames_are_the_frames_the_render_ships(tmp_path):
    """crf 18 is lossy so these cannot be byte-identical. What must hold is that the
    STATISTIC the grade decision reads — mean luma — agrees. Measured 2026-08-15 on a
    1080p and a 4K grain source: within 0.14 codes."""
    src = _grainy(tmp_path)
    sp = _spec()
    out = str(tmp_path / "shipped.mp4")
    reframe.reframe(sp, src, None, out, str(tmp_path / "path.json"))
    plan = reframe.plan_render(sp, src, None)
    n = 3
    times = [((i + 0.5) / n) * plan.dur for i in range(n)]
    probed = probe._render(plan, src, times, tmp_path / "probe")
    shipped = assembly.frames_rgb(out, [round(t * plan.fps) / plan.fps for t in times],
                                  plan.fps)
    assert len(probed) == len(shipped) == n
    for a, b in zip(probed, shipped):
        assert a.shape == b.shape
        assert abs(float(a.mean()) - float(b.mean())) < 0.5


def _flat(dst_dir: Path, name: str, hexcolor: str, w: int = 640, h: int = 360,
         dur: float = 3.0) -> str:
    """A lightly-textured near-solid clip at one brightness. Two of these, far apart in
    brightness, give plan_render nothing to tell apart geometrically (same w/h/fps/dur
    either way) but leave a large, easy-to-measure pixel gap — exactly the shape a
    content swap that a geometry-only drift check cannot see needs."""
    dst = str(dst_dir / name)
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"color=c={hexcolor}:s={w}x{h}:d={dur:g}:r=30",
              "-vf", "noise=alls=10:allf=t+u",
              "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
              "-pix_fmt", "yuv420p", dst])
    return dst


def test_the_probes_frames_are_the_frames_the_render_ships_under_stabilize(tmp_path):
    """Row 15 of the Task 7 mutation battery: source_for's whole point is that a probe
    renders the file reframe actually consumed, and no existing test called
    probe_grade end-to-end on a stabilize episode to prove it. A probe_grade that
    rendered md["segment"] while still labelling the report with source_for()'s path
    would have nothing to catch it: raw.mp4 and stabilized.mp4 share dims/fps/dur, so
    plan_render's geometry — and therefore _refuse_on_drift — is identical either way.
    Only the PIXELS differ, which is exactly what this measures instead.

    raw.mp4 (md["segment"]) is dark and must never be read; stabilized.mp4 (what the
    pre-stage actually produced, in epdir as source_for expects) is bright and must be
    the only thing rendered. The luma gap (~32 vs ~224) is far past anything the
    identity-gain grade below could produce by itself."""
    epdir = tmp_path / "ep0"
    epdir.mkdir()
    raw = _flat(tmp_path, "raw.mp4", "0x202020")                # must never reach the render
    stabilized = _flat(epdir, "stabilized.mp4", "0xE0E0E0")     # what reframe actually ran on

    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0),        # == color.TARGET: identity gain,
                       delivery=Delivery.from_spec("native"),    # so only the source pixels move the mean
                       pan=PanSpec(start=0.0, end=0.3))
    clip = str(epdir / "clip.mp4")
    path_json = str(epdir / "path.json")
    reframe.reframe(spec, stabilized, None, clip, path_json, stabilized=True)

    md = {"segment": raw, "out_path": clip, "composition": "center", "grid": "thirds",
          "canvas": [9, 16], "target_dur": 3.0, "pan": {"from": 0.0, "to": 0.3},
          "stabilize": True}
    ep = ReelEpisode(manifest=md, clip=clip, route=None, path=path_json,
                     meta=str(Path(path_json).with_suffix(".meta.json")))
    ep_json = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=3.0).write(ep_json)

    report = probe.probe_grade(str(ep_json), 0, out_dir=str(tmp_path / "probe_out"))

    assert report["source"] == stabilized
    p5, p50, p95 = report["tone_profile"]      # one pooled reading for the episode
                                               # (design 2026-08-30 §4/§0.5), not a
                                               # list of per-frame readings
    assert p50 > 150, (
        f"probe reported p50={p50}, which reads as raw.mp4's dark content (~32) "
        f"rather than stabilized.mp4's bright one (~224) — probe_grade rendered "
        f"md['segment'] instead of source_for()'s output")


def test_a_select_ahead_of_the_tail_collapses_to_one_frame(tmp_path):
    """The §3.1 landmine, kept as an executable measurement: this is WHY with_tail
    appends at the end. If ffmpeg ever stops duplicating here, this test says so.

    The "ahead" argv built below is no longer reachable through this repo's own
    call path: scripts/lib/lint.py's _select_before_fps (Task 3, landed ahead of
    this test in the same slice) refuses it inside proc.run before ffmpeg ever
    starts — asserted first, against THIS render's real filter chain rather than
    test_lint.py's hand-written fixture, which is a stronger proof that the guard
    actually covers the shape a real render would have produced pre-with_tail.
    That refusal is exactly what Task 3 set out to build, and it is also why the
    frame-duplication measurement itself has to bypass proc.run for the "ahead"
    case via a direct subprocess call: production code can no longer construct
    that argv at all, so the only way left to check ffmpeg's OWN behaviour — the
    fact that justifies both with_tail's append-only contract and the lint rule —
    is a narrow, deliberate bypass, in the same spirit
    test_reframe.py/test_layouts.py/test_outro.py already use subprocess directly
    for work outside the production call path. ffbin.ffmpeg() still resolves the
    binary either way — constraint 5 is about never hardcoding the literal, not
    about routing through proc.run.
    """
    src = _grainy(tmp_path)
    plan = reframe.plan_render(_spec(), src, None)
    nums = [round(((i + 0.5) / 3) * plan.dur * plan.fps) for i in range(3)]
    sel = "select='" + "+".join(rf"eq(n\,{k})" for k in nums) + "'"
    first = list(plan.filter_args)
    first[-1] = f"{sel},{first[-1]}"

    with pytest.raises(ValueError, match="select ahead of fps="):
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, *first, "-t", f"{plan.dur:.6f}",
                  "-vsync", "0", "-frames:v", "3", str(tmp_path / "unreachable_f%03d.png")])

    def hashes(args, sub, *, raw=False):
        d = tmp_path / sub
        d.mkdir()
        cmd = [ffbin.ffmpeg(), "-y", "-i", src, *args, "-t", f"{plan.dur:.6f}",
               "-vsync", "0", "-frames:v", "3", str(d / "f%03d.png")]
        if raw:
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            proc.run(cmd)
        return [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.glob("*.png"))]

    assert len(set(hashes(first, "first", raw=True))) == 1      # one frame, three times
    assert len(set(hashes(plan.with_tail(sel), "last"))) == 3


def test_the_probe_refuses_a_path_that_no_longer_matches_the_render(tmp_path):
    src = _grainy(tmp_path)
    sp = _spec()
    pj = tmp_path / "path.json"
    reframe.reframe(sp, src, None, str(tmp_path / "o.mp4"), str(pj))
    plan = reframe.plan_render(sp, src, None)
    pj.write_text(json.dumps([x + 7 for x in plan.path]))
    with pytest.raises(RuntimeError, match="recomputed crop path"):
        probe._refuse_on_drift(plan, str(pj), str(pj.with_suffix(".meta.json")))


def test_the_probe_refuses_a_crop_y_that_no_longer_matches_the_render(tmp_path):
    """final review I-1: the path comparison alone cannot catch this — CropPath
    carries only x, so a route whose y moved while every x stayed put passes it
    unchanged. Before the fix, an 1100px vertical shift (cy 127 vs 1227, the
    reviewer's own reproduction) passed BOTH halves of _refuse_on_drift silently."""
    src = _grainy(tmp_path)
    sp = _spec()
    pj = tmp_path / "path.json"
    reframe.reframe(sp, src, None, str(tmp_path / "o.mp4"), str(pj))
    plan = reframe.plan_render(sp, src, None)
    meta_path = pj.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text())
    meta["crop_y"] = meta["crop_y"] + 1100
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(RuntimeError, match="recomputed geometry"):
        probe._refuse_on_drift(plan, str(pj), str(meta_path))


def test_a_delivered_vignette_and_fade_pass_the_gate(tmp_path):
    """The positive control. Without it, a gate that always failed would look correct
    to the negative test below. Covers BOTH bookend edges (final review I-3): a
    fade is fade=t=in AND fade=t=out, and the old gate only ever proved the first."""
    src = _grainy(tmp_path)
    master = str(tmp_path / "master.mp4")
    reframe.reframe(_spec(), src, None, master, str(tmp_path / "p.json"))
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))
    out = deliver_mod.deliver(master, ExportProfile(), str(tmp_path / "out"), "look",
                              rep, scratch_dir=str(tmp_path / "scratch"),
                              look=LookSpec(vignette=0.3, fade=0.5))
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    by = {c["check"]: c for c in att["look_checks"]}
    assert by["vignette"]["status"] == "pass"
    assert by["fade-in"]["status"] == "pass"
    assert by["fade-out"]["status"] == "pass"


def test_a_delivered_fade_out_truncated_by_a_short_audio_stem_is_refused(tmp_path):
    """Reproduces the reachable miss final review I-3 names: `deliver` computes the
    fade-out's start from the MASTER's duration, but the mux's `-shortest` can
    truncate the DELIVERED file short of that point — fade-in still renders (it is
    unaffected), so a gate that only ever looked at t=0 would report 'pass' on a
    reel whose closing half never reached black."""
    src = _grainy(tmp_path)
    master = str(tmp_path / "master.mp4")
    reframe.reframe(_spec(), src, None, master, str(tmp_path / "p.json"))
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))
    # a real AAC stem shorter than the master by well over one fade window (0.5s):
    # -shortest then truncates the encode before fade=t=out ever reaches black.
    m_dur = assembly.probe_duration(master)
    stem = str(tmp_path / "short.aac")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"anullsrc=r=44100:cl=stereo:d={max(0.1, m_dur - 1.2):g}",
              "-c:a", "aac", stem])
    with pytest.raises(RuntimeError, match="does not carry the look it declared"):
        deliver_mod.deliver(master, ExportProfile(), str(tmp_path / "out"), "look",
                            rep, scratch_dir=str(tmp_path / "scratch"),
                            audio=stem, look=LookSpec(vignette=0.3, fade=0.5))
    out_dir = tmp_path / "out"
    assert list(out_dir.glob("REEL_v*.mp4"))                  # left on disk to look at
    assert not list(out_dir.glob("*.attest.json"))             # but never attested


def test_a_vignette_that_renders_nothing_is_refused(tmp_path, monkeypatch):
    """Simulates the real failure: the mask input is there and carries no darkening,
    exactly as a dropped filter would look downstream."""
    src = _grainy(tmp_path)
    master = str(tmp_path / "master.mp4")
    reframe.reframe(_spec(), src, None, master, str(tmp_path / "p.json"))
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))

    def _clear_mask(m: str, out_dir: str, vignette: float) -> str:
        si = assembly.probe_stream(m)
        mask = str(Path(out_dir) / "look_mask.png")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
                  "-i", f"nullsrc=s={si.w}x{si.h}:d=1:r=1",
                  "-vf", "format=rgba,geq=r=0:g=0:b=0:a=0",
                  "-frames:v", "1", mask])
        return mask

    monkeypatch.setattr(deliver_mod, "_render_mask", _clear_mask)
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="does not carry the look it declared"):
        deliver_mod.deliver(master, ExportProfile(), str(out_dir), "look", rep,
                            scratch_dir=str(tmp_path / "scratch"), look=LookSpec(vignette=0.5))
    assert list(out_dir.glob("REEL_v*.mp4"))
    assert not list(out_dir.glob("*.attest.json"))


# --- 2026-08-31 grade-sensor-references Task 8: probe predicts BOTH gates ---------

ROUTE = "tests/fixtures/golden_route.json"     # sampled against golden_ride_segment's
                                               # own timeline (see that fixture's docstring)


def _grade_md(seg: str, out: str, **colour) -> dict:
    """Same shape as test_grade_sensor_calibration.py's _md — the fixture pairing the
    entropy floor this slice introduced against a legitimate grade and a damaging one."""
    md = {"segment": seg, "out_path": out, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "layout": "fill",
          "canvas": [9, 16], "delivery": "short_edge:480"}
    md.update(colour)
    return md


def _probe_one(tmp_path: Path, golden_ride_segment, **colour) -> dict:
    """One probe_grade call over golden_ride_segment/ROUTE. Renders for real first:
    probe_grade's _refuse_on_drift needs a genuine path.json/path.meta.json to check
    the recomputed crop against, exactly as
    test_the_probes_frames_are_the_frames_the_render_ships_under_stabilize does above."""
    d = tmp_path / "probe_one"
    d.mkdir()
    src = str(golden_ride_segment)
    out = str(d / "ep0.mp4")
    md = _grade_md(src, out, **colour)
    path_json = str(d / "path.json")
    rspec = process_episode.build_reframe_spec(
        Manifest.from_dict(md), Delivery.from_spec(md["delivery"]), dict(orch.DEFAULT_PARAMS))
    reframe.reframe(rspec, src, ROUTE, out, path_json)
    ep = ReelEpisode(manifest=md, clip=out, route=ROUTE, path=path_json,
                     meta=str(Path(path_json).with_suffix(".meta.json")))
    ep_json = d / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=md["target_dur"]).write(ep_json)
    return probe.probe_grade(str(ep_json), 0, out_dir=str(d / "probe_out"))


def _check_episode_grade_damage(tmp_path: Path, golden_ride_segment, **colour) -> dict:
    """What check_episode.run's OWN grade_damage check computes for the same episode
    — the production function itself, not a re-implementation of its maths, so a
    change to _grade_damage's own wiring (e.g. which floor it reads, which plan is
    'graded') would be caught here too.

    route_pts=None short-circuits _subject_delta_advisory before it ever touches
    path_obj/meta (`if source is None or not route_pts: return ...`), which is what
    makes passing None for both safe without a real tracked route or sidecars; `clip`
    is never dereferenced on that branch either, so a path that names no real file
    is fine there."""
    d = tmp_path / "check_one"
    d.mkdir()
    src = str(golden_ride_segment)
    out = str(d / "ep0.mp4")
    md = _grade_md(src, out, **colour)
    plans = (process_episode.plan_for(md, src, ROUTE), process_episode.plan_ungraded(md, src, ROUTE))
    spec = CheckSpec(composition="center", grid="thirds", target_dur=md["target_dur"])
    return check_episode._grade_damage(out, src, plans, None, None, None, spec).detail


def test_probe_json_predicts_BOTH_gates(tmp_path, golden_ride_segment):
    """The P2 row this closes: an operator converging on stills could not see the
    stop coming, and probe was the only cheap way to converge at all."""
    rep = _probe_one(tmp_path, golden_ride_segment, saturation=0.8, black_point=0.1)
    assert rep["grade_damage"]["ratio"] > 0.0
    assert "below" in rep["grade_damage"]
    assert rep["predicted_profile"] == rep["tone_profile"]


def test_probe_grade_damage_agrees_with_check_episode_on_the_same_episode(
        tmp_path, golden_ride_segment):
    """A predictor that disagrees with the gate it predicts is worse than none."""
    rep = _probe_one(tmp_path, golden_ride_segment, black_point=0.35)
    from_check = _check_episode_grade_damage(tmp_path, golden_ride_segment,
                                             black_point=0.35)
    assert rep["grade_damage"]["ratio"] == pytest.approx(from_check["ratio"], abs=0.02)
    assert rep["grade_damage"]["below"] is from_check["below"]


# --- Task 8 fix round 2: grade_damage must predict its gate at ANY --frames ------

def _two_region_clip(tmp_path: Path, da: float, db: float) -> str:
    """A synthetic clip built from two very different regions concatenated end to
    end: `da` seconds near-black with faint noise, then `db` seconds mid-gray with
    heavy noise. Built because golden_ride_segment could NOT discriminate this
    round's bug at any legal colour knob or any N up to 31 (measured while writing
    this test: black_point at 0.05/0.1/0.2/0.35, saturation combos, N in
    {3,5,7,9,15,21,31} all agreed to within 0.006) — that clip is ~1.585s of one
    real, fairly uniform shot, and (k+0.5)/N sampling of a smooth, roughly unimodal
    per-frame entropy curve gives the SAME median for any two ODD N (color.FRAMES'
    own comment already documents this for 5 vs 9: "the residual is not sampling
    noise"). This fixture is deliberately adversarial instead of naturalistic: a
    black_point of 0.35 crushes the near-black region's noise to EXACTLY zero
    entropy (a hard nonlinearity, not a sampling artifact) while barely touching
    the mid-gray region's, so the two regions' per-frame ratios are almost exactly
    0.0 and 1.1 — bimodal, not smooth. At `da`/`db` chosen so ODD N=3 lands a
    2-of-3 majority in one region (an extreme, take-all median) while EVEN N=4
    lands 2-and-2 (an averaged median, ~0.55) the two counts diverge by the whole
    ~0.55 gap — measured stable and reproducible across independent rebuilds
    (byte-identical ratios both times: the noise amplitude is far too small to
    survive the crush, so its exact realization does not matter)."""
    a = tmp_path / "region_a.mp4"
    b = tmp_path / "region_b.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"color=c=0x060606:s=320x240:d={da:g}:r=30",
              "-vf", "noise=alls=6:allf=t+u", "-c:v", "libx264", "-crf", "12",
              "-pix_fmt", "yuv420p", str(a)])
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"color=c=0x808080:s=320x240:d={db:g}:r=30",
              "-vf", "noise=alls=50:allf=t+u", "-c:v", "libx264", "-crf", "12",
              "-pix_fmt", "yuv420p", str(b)])
    out = tmp_path / "two_region.mp4"
    concat_list = tmp_path / "concat.txt"
    concat_list.write_text(f"file '{a}'\nfile '{b}'\n")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "concat", "-safe", "0",
              "-i", str(concat_list), "-c", "copy", str(out)])
    return str(out)


def _two_region_md(src: str, out: str, dur: float) -> dict:
    """A route-less PAN episode (no tracker involved) over the whole synthetic
    clip. crop_scale < 1.0 gives the pan horizontal freedom to be a pan at all —
    canvas matches the source's own 4:3 aspect, so nothing here is about framing,
    only about the colour chain and the timeline."""
    return {"segment": src, "out_path": out, "target_dur": dur,
           "composition": "center", "grid": "thirds", "canvas": [4, 3],
           "layout": "fill", "delivery": "native", "crop_scale": 0.8,
           "pan": {"from": 0.0, "to": 0.3}, "black_point": 0.35}


def test_grade_damage_agrees_with_check_episode_at_a_non_default_frame_count(tmp_path):
    """Task 8 fix round 2. grade_damage must predict check_episode._grade_damage's
    own reading regardless of --frames — check_episode._grade_damage never takes a
    frames argument, so it always samples at the default count, and grade_damage
    has to match that gate at ANY --frames, not only the default one
    test_probe_grade_damage_agrees_with_check_episode_on_the_same_episode already
    proves. That other test always calls probe_grade at the default --frames, so it
    can never exercise the non-default branch a --frames-driven regression hides
    in — this fixture (see _two_region_clip) is built specifically to make that
    branch matter: measured, the default N=3 reads 0.0 and N=4 reads ~0.55."""
    src = _two_region_clip(tmp_path, da=1.1, db=0.9)
    dur = assembly.probe_duration(src)
    out = str(tmp_path / "ep0.mp4")
    md = _two_region_md(src, out, dur)
    path_json = str(tmp_path / "path.json")
    rspec = process_episode.build_reframe_spec(
        Manifest.from_dict(md), Delivery.from_spec(md["delivery"]), dict(orch.DEFAULT_PARAMS))
    reframe.reframe(rspec, src, None, out, path_json)
    ep = ReelEpisode(manifest=md, clip=out, route=None, path=path_json,
                     meta=str(Path(path_json).with_suffix(".meta.json")))
    ep_json = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=dur).write(ep_json)

    rep = probe.probe_grade(str(ep_json), 0, out_dir=str(tmp_path / "probe_out"), frames=4)
    assert len(rep["times"]) == 4           # the --frames override really landed on the stills

    plans = (process_episode.plan_for(md, src, None), process_episode.plan_ungraded(md, src, None))
    spec = CheckSpec(composition="center", grid="thirds", target_dur=dur)
    from_check = check_episode._grade_damage(out, src, plans, None, None, None, spec).detail

    assert from_check["ratio"] < 0.05, from_check    # ground truth: the default N=3 reading
    assert rep["grade_damage"]["ratio"] == pytest.approx(from_check["ratio"], abs=0.05)
    assert rep["grade_damage"]["below"] is from_check["below"]


def test_grade_damage_agrees_with_check_episode_at_a_non_default_frame_count_geometry(
        tmp_path):
    """Task 8 fix round 2, geometry mode. probe_grade_geometry takes the same
    --frames parameter as probe_grade and got the identical fix (see its own
    comment, "same reasoning as probe_grade's comment") — this is the same proof
    as test_grade_damage_agrees_with_check_episode_at_a_non_default_frame_count
    above, driven through GEOMETRY.json/EDL.json instead of EPISODES.json, so the
    fix is proved in both modes rather than assumed to carry over because the code
    looks the same."""
    src = _two_region_clip(tmp_path, da=1.1, db=0.9)
    dur = assembly.probe_duration(src)
    out = str(tmp_path / "ep0.mp4")
    # EpisodeGeometry.manifest is stored colour-STRIPPED in the real pipeline
    # (design 2026-08-30 §2.2) — regrade replaces COLOUR_KEYS from the EDL
    # regardless, so this is about matching the real shape, not about the result.
    stripped_md = strip_colour(_two_region_md(src, out, dur))
    eg = EpisodeGeometry(manifest=stripped_md, route=None, source=src,
                         project_dir=str(tmp_path))
    edl_path = tmp_path / "EDL.json"
    write_edl(EDL(episodes=(EDLEpisode(source=src, start=0.0, dur=dur, shot_type="wide",
                                       composition="center", grid="thirds",
                                       black_point=0.35),)), edl_path)
    geo = ReelGeometry(episodes=(eg,), edl=str(edl_path))
    geo_path = tmp_path / "GEOMETRY.json"
    geo.write(geo_path)

    rep = probe.probe_grade_geometry(str(geo_path), 0, out_dir=str(tmp_path / "probe_out"),
                                     frames=4)
    assert len(rep["times"]) == 4           # the --frames override really landed on the stills

    md = probe.regrade(dict(eg.manifest), geo.edl, 0)
    plans = (process_episode.plan_for(md, src, None), process_episode.plan_ungraded(md, src, None))
    spec = CheckSpec(composition="center", grid="thirds", target_dur=dur)
    from_check = check_episode._grade_damage(out, src, plans, None, None, None, spec).detail

    assert from_check["ratio"] < 0.05, from_check    # ground truth: the default N=3 reading
    assert rep["grade_damage"]["ratio"] == pytest.approx(from_check["ratio"], abs=0.05)
    assert rep["grade_damage"]["below"] is from_check["below"]
