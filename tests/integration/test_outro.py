"""The outro fit, end to end on real bytes (design
docs/specs/2026-08-14-music-outro-fit-design.md §9).

The claim under test is the one §1 rests on: choosing reel_dur = line + fade makes
mix's EXISTING afade start exactly on the bar line, with no change to any ffmpeg
stage. A unit test cannot show that — only a delivered file can.

Fixture modelled on tests/integration/test_edit_plan.py's SP3->SP1 golden (same
_fake_track_pe/_footage_json/_selection_json/_project_json shapes, and the same
reason the mechanical middle is faked: the synthetic clip is a box, not a person,
so real YOLO tracking returns an empty route) plus tests/integration/
test_front_spine.py's test_edl_drives_a_reel_with_music for the real-tone
MUSIC.json recipe. tests/integration/test_ramp.py's Task 8 fixture is where the
small 640x360 source + long_edge:240 delivery combination (fast real encodes)
comes from.

mix.py/deliver.py/check_reel.py/build_reel.py/edl_to_reel.py are untouched by this
slice (design §1) — this file only calls them, never edits them.

`_pacing_json` below is deliberately NO-SLACK — exactly as many slots as episodes,
`target_dur` equal to the pre-fit total — because an earlier, slacker version of this
same fixture (an extra unfilled tail slot) masked the exact defect this file exists to
prove: `edit_plan._back_edge_target`'s over-flow clamp discarding the outro fit's own
growth (Task 5b; design 2026-08-14 §6's correction has the mechanism)."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from scripts import edit_plan, edl_to_reel
from scripts.lib import ffbin, outro, proc
from scripts.lib.edl import EDL
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.models import MusicSpec
from scripts.lib.pacing import Slot, Spine

pytestmark = pytest.mark.integration

W, H, FPS = 640, 360, 30.0        # small + fast, like test_ramp.py's Task 8 fixture
CLIP_DUR = 20.0                   # room for both windows plus the outro fit's growth
TEMPO = 120.0                     # -> outro.bar_seconds == 2.0s
FADE = 0.5                        # mix's own default (no look authored in selection.json)
LINE = 10.2                       # the sole bar line: realized (pre-fit) is 6.0+4.0=10.0s,
                                  # 0.2s SHORT of it — the fit must grow the reel to reach it
MUSIC_DUR = 20.0


def _probe_dur(path):
    r = subprocess.run([ffbin.ffprobe(), "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nk=1:nw=1", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def _rms(path, ss, t):
    raw = subprocess.run([ffbin.ffmpeg(), "-v", "error", "-ss", str(ss), "-i", str(path),
                          "-t", str(t), "-vn", "-ac", "1", "-ar", "22050",
                          "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    return float(np.sqrt((a ** 2).mean())) if len(a) else 0.0


@pytest.fixture(scope="module")
def outro_clip(tmp_path_factory):
    """20s 640x360 clip: a white box sliding across a dark field — same recipe as
    conftest.py's sample_clip/ramp_clip (overlay, not drawbox: drawbox's x/y
    expressions are inert under this ffmpeg), just longer. 20s leaves room for a
    window at [10.0, 14.0) plus the outro fit's own growth past 14.0s, on a clip
    still small/short enough to encode fast."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "outro_src.mp4"
    bg = f"color=c=0x202020:s={W}x{H}:d={CLIP_DUR}:r={FPS}"
    box = f"color=c=white:s=40x80:d={CLIP_DUR}:r={FPS}"
    proc.run([binary, "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
              "-filter_complex", "[0][1]overlay=x='40+t*25':y=140",
              "-t", str(CLIP_DUR), "-pix_fmt", "yuv420p", str(out)])
    return out


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    """A 220Hz tone at constant amplitude for the whole analysed window — same
    recipe as test_front_spine.py's test_edl_drives_a_reel_with_music. Constant on
    purpose: the RMS drop the second assert measures must come from mix's OWN
    afade, not from any silence already baked into the source track."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("audio") / "tone.wav"
    proc.run([binary, "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={MUSIC_DUR}",
              "-ac", "2", str(out)])
    return out


def _fake_track_pe(monkeypatch):
    """Copied from test_edit_plan.py's _fake_track_pe, dims adjusted to this
    module's own WxH — see that file's module comment for why the mechanical
    middle is faked at all (the synthetic clip is a box, not a person, so real
    YOLO tracking returns an empty route)."""
    def fake_pe(manifest, project_dir, route_path=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": W // 2, "y": H // 2, "w": 40, "h": 80, "id": 1}]))
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


def _footage_json(tmp_path, source):
    # window 0: [0.5, 6.5) — window 1: [10.0, 14.0), the CLOSING shot the outro fit
    # grows. No scene cuts: room_after(10.0) == CLIP_DUR - 10.0 == 10.0s, comfortably
    # more than the fit's grow_max (6.0s, see test_delivered_reel_ends_at_line_plus_fade)
    # needs. The two windows sit far apart in time so the sliding box gives adjacent
    # episodes distinct phash (test_edit_plan.py's own reason for the same spacing).
    f = Footage(clips=[FootageClip(source=source, dur=CLIP_DUR, res=(W, H), fps=FPS, windows=[
        FootageWindow(start=0.5, dur=6.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=10.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _selection_json(tmp_path, source):
    sel = {"episodes": [
        {"source": source, "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": source, "window": 1, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}]}
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(sel))
    return str(p)


def _project_json(tmp_path):
    # small + fast delivery, like test_ramp.py's Task 8 fixture (long_edge:240 on a
    # 640x360 source keeps deliver's one real x264 encode quick).
    #
    # canvas = the SOURCE's own aspect (was [1080, 1920], a 9:16 "reel" canvas), to
    # agree with what `_fake_track_pe` actually delivers. `_fake_track_pe` skips
    # reframe entirely — a plain `-c:v copy`, no crop — and its own path.meta.json
    # already says so honestly (`"canvas": [W, H]`, matching src_dims, not the
    # project's declared 9:16). A 9:16 project canvas left the two disagreeing: the
    # MANIFEST (which is what a real reframe, and now `build_reel._predict`, reads)
    # still declared a 9:16 crop nobody rendered. Nothing noticed until design
    # 2026-08-31 Task 7 wired `check_reel.grade_faithful` to predict each episode
    # fresh from that same declaration — nothing here was mis-cropped, the
    # declaration was always a fiction this fixture's fake never enacted, and nothing
    # before Task 7 ever compared the two. `grade_faithful` correctly refused it
    # (episode 1's tracked-box window sits inside the fictional crop's centre column,
    # residual 222 against a 4.0 ceiling). Matching canvas to source, like the
    # sidecar already does, removes the crop this fixture never actually took.
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [W, H], "delivery": "long_edge:240"}))
    return str(p)


def _pacing_json(tmp_path):
    """2 slots for 2 episodes — NO SLACK: target_dur is the pre-fit total exactly
    (6.0 + 4.0 = 10.0), which is what pacing.fit_spine actually produces (as many
    slots as episodes, nothing left unfilled).

    _bind_pacing fits episode i's dur to slot i's dur EXACTLY (both windows already
    match their slots: 6.0/4.0), so after binding `realized == spine.target_dur`
    always, for any 1:1 slot:episode spine — the sum is definitionally the same sum.
    The outro fit then GROWS the closing episode past that total, so BEFORE Task 5b's
    fix, edit_plan._back_edge_target's own over-flow branch ("keeps the fragment
    length... the excess escalates at the reel gate") clamped EDL.target_dur straight
    back down to the PRE-fit 10.0s — and check_reel's length gate treats a master
    LONGER than its recorded target as unrecoverable over-length
    (reel_orchestration._shortfall returns None for dur > target, so next_action
    escalates rather than delivers — "an over-length reel is never absorbed").

    An earlier version of this fixture gave the spine a 3rd, unfilled tail slot
    purely to buy 2.0s of slack the two bound episodes never consumed — enough room
    for the fit's own +0.7s growth to land inside spine.target_dur instead of past
    it, so the old (unfixed) _back_edge_target took its UNDER-fill branch instead of
    its over-flow one and happened to return the grown total anyway. That made this
    proof pass while hiding the real defect (Task 5b) — on THIS no-slack spine the
    old code got back `edl_to_reel` status stop_and_report, check "length", detail
    {"dur": 10.7, "target": 10.0} — `_back_edge_target` was never actually exercised
    on the shape `fit_spine` produces. Now that `build_edl` makes the outro fit
    authoritative whenever it chose a line (Task 5b; design 2026-08-14 §6's
    correction), this NO-SLACK spine is what proves the fix rather than avoiding the
    question.
    """
    spine = Spine(slots=(
        Slot(0, 0.0, 6.0, 0.5, "hook", line=6.0, dev=0.0),
        Slot(1, 6.0, 4.0, 0.5, "peak", line=10.0, dev=0.0),
    ), target_dur=10.0, tempo=TEMPO)
    p = tmp_path / "PACING.json"
    p.write_text(json.dumps(spine.to_dict()))
    return str(p)


def _music_json(tmp_path, track, *, bars):
    """bars=(LINE,) places the ONE qualifying bar line the reel's realized 10.0s is
    0.2s short of, with a vocal-free tail well past `fade + TAIL_MARGIN`. bars=() (the
    control, Step 2) is the SAME track/window with no detected grid at all —
    outro.fit_outro's honest 'unchanged' answer, never a weaker variant of the
    'gap' fixture."""
    vocal_spans = ((LINE, LINE + 1.8),) if bars else ()
    ms = MusicSpec(track=str(track), start_offset=0.0, duration=MUSIC_DUR, tempo=TEMPO,
                   beats=tuple(i * 0.5 for i in range(int(MUSIC_DUR / 0.5))),
                   energy=(0.3,) * 10, energy_hz=2.0, bars=bars, vocal_spans=vocal_spans)
    p = tmp_path / "MUSIC.json"
    p.write_text(json.dumps(ms.to_dict()))
    return str(p)


def _build(tmp_path, clip, track, *, bars, monkeypatch):
    """The real chain: FOOTAGE + selection + project + pacing + music -> edit_plan
    build --pacing --music -> edl_to_reel -> a delivered reel. Returns (out_reel,
    the written EDL)."""
    _fake_track_pe(monkeypatch)
    fj = _footage_json(tmp_path, clip.name)
    sj = _selection_json(tmp_path, clip.name)
    pj = _project_json(tmp_path)
    pacing = _pacing_json(tmp_path)
    mj = _music_json(tmp_path, track, bars=bars)
    plan_out = tmp_path / "plan"

    res = edit_plan.write_edit_plan(fj, sj, pj, str(plan_out), pacing_path=pacing, music=mj)
    assert res["status"] == "written", res
    edl = EDL.from_json(plan_out / "EDL.json")

    reel = edl_to_reel.edl_to_reel(
        str(plan_out / "EDL.json"), pj, footage_root=str(clip.parent),
        work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"), music=mj)
    assert reel["status"] == "delivered", reel
    return reel["output"], edl


def test_delivered_reel_ends_at_line_plus_fade(outro_clip, tone, tmp_path, monkeypatch):
    # The realized (pre-fit) picture is 6.0 + 4.0 = 10.0s. The closing shot (window 1,
    # [10.0, 14.0) on the 20s clip, no scene cuts) can grow up to
    # room_after(10.0) - dur(4.0) = (20.0 - 10.0) - 4.0 = 6.0s, so grow_max never
    # binds here; shrink_max is irrelevant since the move is a growth. Checked
    # directly against outro.fit_outro BEFORE building any video (and cross-checked
    # against edit_plan._apply_outro on equivalent synthetic episodes during Task 6)
    # so the expected numbers are derived, not guessed.
    realized = 6.0 + 4.0
    grow_max = (CLIP_DUR - 10.0) - 4.0
    shrink_max = 4.0 - outro.MIN_LAST
    fit = outro.fit_outro((LINE,), ((LINE, LINE + 1.8),), reel_dur=realized,
                          bar_s=outro.bar_seconds(TEMPO), fade=FADE, music_dur=MUSIC_DUR,
                          grow_max=grow_max, shrink_max=shrink_max)
    assert fit.rung == "gap"
    assert fit.line == LINE and fit.fade == FADE
    expected_line, expected_fade, expected_dur = fit.line, fit.fade, fit.reel_dur

    out_reel, edl = _build(tmp_path, outro_clip, tone, bars=(LINE,), monkeypatch=monkeypatch)
    # the EDL agrees with the pure fit above, and the back-edge target was NOT
    # clamped back down to the pre-fit 10.0s (see _pacing_json's docstring)
    assert edl.outro is not None and edl.outro.rung == "gap"
    assert edl.outro.reel_dur == pytest.approx(expected_dur)
    assert edl.target_dur == pytest.approx(expected_dur)

    dur = _probe_dur(out_reel)
    assert dur == pytest.approx(expected_line + expected_fade, abs=0.10)
    # the fade lives AFTER the line: loud just before it, quiet at the very end
    assert _rms(out_reel, expected_line - 0.30, 0.20) > 5 * _rms(out_reel, dur - 0.10, 0.08)


def test_unfitted_reel_keeps_its_footage_derived_length(outro_clip, tone, tmp_path, monkeypatch):
    """Step 2 — the control that must NOT move. The SAME fixture with bars=() in
    MUSIC.json must deliver at the un-fitted realized length (6.0+4.0=10.0s), not at
    line + fade. Without this, the first test would pass for any implementation
    that always extends the reel regardless of what MUSIC.json says."""
    realized = 6.0 + 4.0
    out_reel, edl = _build(tmp_path, outro_clip, tone, bars=(), monkeypatch=monkeypatch)
    assert edl.outro is not None and edl.outro.rung == "unchanged" and edl.outro.line is None
    assert edl.target_dur == pytest.approx(realized)

    dur = _probe_dur(out_reel)
    assert dur == pytest.approx(realized, abs=0.10)
