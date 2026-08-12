"""Real-ffmpeg proofs for the speed ramp (design §11).

These render actual pixels. A correct-looking argv is not evidence that a frame
moved — backlog #18's whole finding is that a live-added vignette came out
invisible and no test caught it.
"""
import json
from pathlib import Path
import subprocess

import pytest

from scripts.lib import assembly, ffbin, proc, ramp
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.models import RampSpec

pytestmark = pytest.mark.integration

SPEC = RampSpec(at=1.0, factor=0.4, ease=0.25, hold=0.5)   # region [0.5, 1.5]
DUR, FPS, W, H = 2.0, 60.0, 640, 360


def _diff_curve(path, w, h):
    """mean |frame - prev| per frame, gray, one decode — the way lib/anchors
    measures motion. Slowing must drop this on the plateau."""
    p = subprocess.Popen(                                  # noqa: S603 - test-only probe
        [ffbin.ffmpeg(), "-v", "error", "-i", str(path),
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE)
    n, prev, out = w * h, None, []
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            if prev is not None:
                out.append(sum(abs(a - b) for a, b in zip(buf, prev)) / n)
            prev = buf
    finally:
        p.stdout.close()
        p.wait()
    return out


def _band(curve, t0, t1, fps=FPS):
    seg = curve[max(0, int(t0 * fps)):min(len(curve), int(t1 * fps))]
    assert seg, f"empty band [{t0}, {t1}]"
    return sum(seg) / len(seg)


def test_the_rendered_length_matches_the_recorded_one(ramp_clip, tmp_path):
    """play_dur() must not be a number the file disagrees with."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    want = DUR + ramp.ramp_extra(SPEC, DUR)
    got = assembly.probe_duration(dst)
    assert got == pytest.approx(want, abs=2.0 / FPS), (
        f"recorded {want:.4f}s against a rendered {got:.4f}s — record and render "
        f"read the same knots, so they may differ only by fps= quantization")


def test_the_ramp_actually_slows_the_picture(ramp_clip, tmp_path):
    """Backlog #18's demand: measure the effect in pixels, not in the argv."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)

    ts, o = ramp.knots(SPEC, DUR)

    def o_at(t):
        """Where source time t lands in the output. Knots are NOT evenly spaced
        (design §3.2), so find the interval rather than dividing by a step."""
        i = max(0, min(len(ts) - 2, next(k for k in range(len(ts) - 1)
                                         if ts[k + 1] >= t)))
        return o[i] + (o[i + 1] - o[i]) * (t - ts[i]) / (ts[i + 1] - ts[i])

    curve = _diff_curve(dst, W, H)
    normal = _band(curve, 0.05, o_at(0.25) - 0.05)          # before the region
    plateau = _band(curve, o_at(0.75) + 0.05, o_at(1.25) - 0.05)
    ratio = plateau / normal
    assert ratio == pytest.approx(SPEC.factor, abs=0.12), (
        f"plateau/normal frame difference is {ratio:.3f} against a factor of "
        f"{SPEC.factor} — the picture is not actually slowing")


def test_the_retimed_stream_is_constant_frame_rate(ramp_clip, tmp_path):
    """setpts without fps= yields VFR, which assembly.concat will not accept."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    assert assembly.probe_stream(dst).fps == pytest.approx(FPS, abs=0.01)


def test_the_retimed_stream_actually_holds_fps_many_frames_per_second(ramp_clip, tmp_path):
    """Coverage hole found by the Task 9 mutation battery: dropping the `,fps=...`
    suffix from retime's `vf` (row 3) survived the test above. probe_stream reads
    ffprobe's r_frame_rate, which is the container's DECLARED nominal rate — for
    an libx264 mp4 with no explicit `-r`, it stays pinned to the source's own fps
    whether or not a `fps=` filter ran (measured directly: r_frame_rate reports
    60/1 either way). What `fps=` actually does — duplicate frames until the
    stream holds FPS of them per second of its own, now-longer, duration — shows
    up only in the real frame COUNT. Without it, setpts alone re-times each
    frame's PTS but the filter still emits just the source's original frame
    count, spread thinner over the stretched duration: the exact stutter
    MIN_RAMP_FPS exists to refuse, invisible to a check that reads declared
    metadata instead of measuring it (measured: 120 frames either way the source
    holds, against ~182 wanted for this SPEC/DUR/FPS — a gap no `abs=` on
    r_frame_rate could ever see, because r_frame_rate does not move)."""
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    out_dur = DUR + ramp.ramp_extra(SPEC, DUR)
    nb_frames = int(proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-of", "csv=p=0", dst]
    ).stdout.decode().strip())
    want = out_dur * FPS
    assert nb_frames == pytest.approx(want, abs=2), (
        f"{nb_frames} frames on disk against ~{want:.1f} wanted for {out_dur:.3f}s "
        f"at {FPS:g}fps — fps= must duplicate frames to fill the stretched "
        f"duration, not leave the source's own frame count spread over more time")


def test_the_retimed_segment_carries_no_audio(ramp_clip, tmp_path):
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
    streams = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", dst]).stdout.decode()
    assert streams.strip() == ""


def test_retime_drops_a_source_that_actually_has_audio(ramp_clip, tmp_path):
    """Coverage hole found by the Task 9 mutation battery: dropping `-an` from
    retime's argv (row 5) left the test above green. ramp_clip, like sample_clip,
    is built from lavfi color=/overlay sources with no audio input at all — the
    source has NO audio stream to begin with, so "the output carries none either"
    holds whether or not `-an` ran; there is nothing for a dropped `-an` to leak
    through. This test gives retime a source that genuinely carries audio
    (ramp_clip's picture muxed against a synthesized tone), so a dropped `-an`
    has something to fail on."""
    av = str(tmp_path / "with_audio.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(ramp_clip), "-f", "lavfi",
              "-i", "sine=frequency=440:duration=2", "-shortest",
              "-c:v", "copy", "-c:a", "aac", av])
    have = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", av]).stdout.decode()
    assert have.strip() != "", "fixture setup: the muxed source must actually carry audio"

    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(av, dst, SPEC, DUR, FPS)
    streams = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", dst]).stdout.decode()
    assert streams.strip() == ""


def test_a_deeper_ramp_slows_more_than_a_shallow_one(ramp_clip, tmp_path):
    """The gate's own arithmetic, proved in pixels: factor is a real dial, not a
    flag that merely switches slowdown on."""
    shallow = RampSpec(at=1.0, factor=0.8, ease=0.25, hold=0.5)
    a, b = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")
    ramp.retime(str(ramp_clip), a, shallow, DUR, FPS)
    ramp.retime(str(ramp_clip), b, SPEC, DUR, FPS)
    assert assembly.probe_duration(b) > assembly.probe_duration(a) + 0.2


def test_an_unramped_extract_is_unchanged_by_this_slice(sample_clip, tmp_path, monkeypatch):
    """No ramp: two independent runs produce byte-identical output, and a spy on
    ramp.retime proves the ramp branch itself was never entered.

    A glob for `*_ramped.mp4` has NO discriminating power here: extract_edl always
    does `ramp.retime(out, ramped, ...)` then `Path(ramped).replace(out)`, and
    Path.replace() renames — so `ep{i}_ramped.mp4` never persists on disk whether or
    not the branch ran. That assertion was unconditionally true and proved nothing
    (Task 7 review finding). Monkeypatching ramp.retime to record its own calls and
    asserting it was never called is a predicate that actually depends on the code
    under test: a regression that ramped an unramped episode would call the spy and
    fail this test, where the old glob assertion would have passed silently."""
    from scripts import extract
    from scripts.lib.edl import EDL, EDLEpisode
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.mp4").write_bytes(sample_clip.read_bytes())
    e = EDL(episodes=[EDLEpisode(source="a.mp4", start=0.0, dur=1.0,
                                 shot_type="medium", composition="center",
                                 grid="thirds")])

    calls = []
    monkeypatch.setattr(extract.ramp, "retime",
                        lambda *a, **k: calls.append((a, k)))

    one = extract.extract_edl(e, str(src_dir), str(tmp_path / "s1"))
    two = extract.extract_edl(e, str(src_dir), str(tmp_path / "s2"))
    from pathlib import Path
    assert Path(one[0]).read_bytes() == Path(two[0]).read_bytes()
    assert calls == [], f"ramp.retime was called for an unramped episode: {calls}"


# --- Task 8: end to end, SP3 -> SP1 (design docs/specs/2026-07-11-extract-spine-design.md).
#
# Scaffolding copied from tests/integration/test_edit_plan.py's _project_json/_footage_json/
# _selection_json/_fake_track_pe (test_selection_becomes_edl_becomes_reel is the SP3->SP1 seam
# this mirrors), adapted: _write_footage takes an `fps` and emits ONE window covering the whole
# [0.0, 2.0] of ramp.mp4; footage_root is tmp_path itself here (unlike sample_clip's own
# session-scoped media dir), so ramp_clip is copied in under the name FOOTAGE.json/selection.json
# reference it by.
#
# process_episode IS faked here, same as test_edit_plan.py and for the same reason: driving the
# FULL real chain on this synthetic fixture does not raise — it ESCALATES. ramp_clip's drawn
# white box is not a person, so real YOLO returns an empty route, the tracking ladder falls to
# optical flow (design 2026-07-21), and the flow-derived route is too jittery for
# check_episode's on_line/continuity gates: process_episode's retry loop exhausts and
# edl_to_reel returns stop_and_report with fail_reasons ['on_line', 'continuity'] instead of
# delivering. tests/integration/test_tracking_ladder.py::test_empty_yolo_route_falls_to_optical_flow
# documents the same fallback on the sibling sample_clip fixture. That failure is a correct,
# orthogonal finding about composition on synthetic footage — not a length bug — so faking
# process_episode's mechanical middle (real YOLO/flow/reframe/check_episode never run) is what
# keeps this test's scope on the thing Task 8 is actually about.
#
# Consequently, what the two tests below PROVE is LENGTH ONLY: extract's retime pre-stage and
# every play_dur()-reading consumer from there down through assemble/check_reel/deliver. They do
# NOT prove tracking or framing correctness on a ramped clip — that is out of scope for a length
# proof, and staying honest about the boundary matters more than chasing a broader claim.


def _write_project(tmp_path):
    # 9:16, long_edge 240 — small and fast: canvas sets the crop aspect against the 640x360
    # source, delivery caps the final encode small so the real extract/track/reframe/deliver
    # passes below stay quick (mirrors test_zoom.py's reason for the same delivery value).
    p = tmp_path / "project.json"
    p.write_text(json.dumps(
        {"purpose": "reel", "canvas": [1080, 1920], "delivery": "long_edge:240"}))
    return str(p)


def _write_footage(tmp_path, clip, fps):
    dst = tmp_path / "ramp.mp4"
    dst.write_bytes(Path(clip).read_bytes())
    f = Footage(clips=[FootageClip(source="ramp.mp4", dur=DUR, res=(W, H), fps=fps, windows=[
        FootageWindow(start=0.0, dur=DUR, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _write_selection(tmp_path, episodes):
    base = {"composition": "lead", "grid": "thirds", "crop_scale": 0.8}
    sel = {"episodes": [{**base, **ep} for ep in episodes]}
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(sel))
    return str(p)


def _fake_track_pe(monkeypatch):
    """Copied from tests/integration/test_edit_plan.py's _fake_track_pe, dims adjusted
    to ramp_clip's own 640x360 (W, H) instead of sample_clip's 1920x1080 — see the
    module comment above for why the mechanical middle is faked at all."""
    from scripts import edl_to_reel

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": W // 2, "y": H // 2, "w": 40, "h": 80, "id": 1}]))
        # real process_episode writes path.json + path.meta.json beside route.json on every
        # mechanical_pass (reframe emits both); mirror that so build_reel's frozen safe_zones
        # geometry reads real files. CropPath [0] is parallel to the single route point above;
        # a plain fill sidecar at the clip's own W x H dims (safe_zones is advisory — this
        # test doesn't assert it, so the values need only be valid, not "safe").
        (Path(project_dir) / "path.json").write_text(json.dumps([0]))
        (Path(project_dir) / "path.meta.json").write_text(json.dumps(
            {"mode": "fill", "crop_w": W, "crop_h": H, "crop_y": 0,
             "src_dims": [W, H], "canvas": [W, H], "out_dims": [W, H],
             "rect_px": [0, 0, W, H], "freedom": 0}))
        proc.run([ffbin.ffmpeg(), "-y", "-i", manifest["segment"], "-c:v", "copy", "-an",
                 manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    # process_episode is faked, but edl_to_reel calls track.ensure_model ITSELF above
    # the pool — unstubbed, this ffmpeg golden also constructs a real YOLO (importing
    # torch, and downloading 6MB on a cold cache) for a tracking pass it never runs.
    monkeypatch.setattr(edl_to_reel.track, "ensure_model", lambda m: None)


def test_a_ramped_episode_reaches_the_reel_at_its_played_length(ramp_clip, tmp_path, monkeypatch):
    """The whole point of backlog #7, end to end: the reel is as long as the episodes
    PLAY, not as long as their source windows. (Scope: see the module comment above
    this section — process_episode is faked, so this proves LENGTH, not framing.)"""
    from scripts import edit_plan, edl_to_reel
    from scripts.lib.edl import EDL

    proj = _write_project(tmp_path)
    foot = _write_footage(tmp_path, ramp_clip, fps=FPS)
    sel = _write_selection(tmp_path, [
        {"source": "ramp.mp4", "window": 0,
         "ramp": {"at": 1.0, "factor": 0.4, "ease": 0.25, "hold": 0.5}},
    ])
    # NOTE: write_edit_plan's real signature is (footage_path, selection_path, project_path,
    # out_dir, ...) — footage first, matching test_edit_plan.py's own call.
    plan = edit_plan.write_edit_plan(foot, sel, proj, str(tmp_path))
    assert plan["status"] == "written", plan

    e = EDL.from_json(str(tmp_path / "EDL.json"))
    ep = e.episodes[0]
    assert ep.play_dur() > ep.dur

    _fake_track_pe(monkeypatch)
    res = edl_to_reel.edl_to_reel(
        str(tmp_path / "EDL.json"), proj, str(tmp_path),
        str(tmp_path / "work"), str(tmp_path / "out"))
    assert res["status"] == "delivered", res
    assert assembly.probe_duration(res["output"]) == pytest.approx(
        ep.play_dur(), abs=0.2)


def test_the_edl_markdown_reports_the_ramp(ramp_clip, tmp_path):
    from scripts import edit_plan

    proj = _write_project(tmp_path)
    foot = _write_footage(tmp_path, ramp_clip, fps=FPS)
    sel = _write_selection(tmp_path, [
        {"source": "ramp.mp4", "window": 0,
         "ramp": {"at": 1.0, "factor": 0.4, "ease": 0.25, "hold": 0.5}},
    ])
    plan = edit_plan.write_edit_plan(foot, sel, proj, str(tmp_path))
    assert plan["status"] == "written", plan
    md = (tmp_path / "EDL.md").read_text()
    assert "ramp x2.5" in md and "plays" in md
