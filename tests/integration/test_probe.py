"""Real ffmpeg. The probe's central claim is that its frames are the frames the full
render ships; the look gate's is that a declared effect reached the delivered pixels.
Both are pixel claims and are proved on pixels."""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from scripts import deliver as deliver_mod, probe, reframe
from scripts.lib import assembly, color, ffbin, layout as layout_lib, proc, provenance
from scripts.lib.look import LookSpec
from scripts.lib.models import (Delivery, ExportProfile, PanSpec, ReelEpisode, ReelManifest,
                                ReelReport, ReframeSpec)

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
    for p5, p50, p95 in report["tone"]:
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
                              rep, look=LookSpec(vignette=0.3, fade=0.5))
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
                            rep, audio=stem, look=LookSpec(vignette=0.3, fade=0.5))
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
                            look=LookSpec(vignette=0.5))
    assert list(out_dir.glob("REEL_v*.mp4"))
    assert not list(out_dir.glob("*.attest.json"))
