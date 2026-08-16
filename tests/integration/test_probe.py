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
from scripts.lib.models import Delivery, ExportProfile, PanSpec, ReelReport, ReframeSpec

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


def test_a_delivered_vignette_and_fade_pass_the_gate(tmp_path):
    """The positive control. Without it, a gate that always failed would look correct
    to the negative test below."""
    src = _grainy(tmp_path)
    master = str(tmp_path / "master.mp4")
    reframe.reframe(_spec(), src, None, master, str(tmp_path / "p.json"))
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))
    out = deliver_mod.deliver(master, ExportProfile(), str(tmp_path / "out"), "look",
                              rep, look=LookSpec(vignette=0.3, fade=0.5))
    att = json.loads(Path(provenance.attest_path(out)).read_text())
    by = {c["check"]: c for c in att["look_checks"]}
    assert by["vignette"]["status"] == "pass"
    assert by["fade"]["status"] == "pass"


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
