"""Real-ffmpeg proof for the freeze (design 2026-10-21 §3).

A window and a freeze of its last frame are cut from a clip whose frames all differ,
through the same path a reel takes (edit_plan resolves the freeze's label, extract cuts
both), and the pixels are read back: the freeze must be the frame the window's own
segment ends on — its last DECODED frame, not its neighbour — held for its whole length,
silent, on the segment range contract.

The windows are off the frame grid on purpose. Measured while fixing the Task 1 review's
I3: the formula `start + dur - 1/fps`, used as a source time, named a neighbour of the
segment's last frame in 5 of 28 random off-grid cuts, in both directions — (0.152 s,
1.209 s) and (0.154 s, 0.847 s at 30000/1001) one frame early, (0.482 s, 1.592 s) one
late. The review's own worked case (0.51 s, 1.51 s) was not one of them; it is kept
because it was the case named. Taking the frame by count from the segment is right in
every case by construction, and these are the cases where the source-time reading was
not.

The last proof takes a freeze through edl_to_reel's geometry split on the committed
golden ride, with the tracker replaced by its committed route: the freeze is never
tracked, and the route it is framed over is its predecessor's last sample, held."""
import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from scripts import edit_plan, edl_to_reel, extract, track
from scripts.lib import assembly, ffbin, models, proc
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.footage import Footage, FootageClip

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="module")
def counting_clip(tmp_path_factory):
    """`counting_clip(rate)` → a 3s 640x360 testsrc2 at that rate — its pattern moves and
    it prints a frame counter, so no two frames are alike — with a tone on it, so the
    freeze's silence is a drop. FULL range with a bt709 description, as camera footage
    arrives: ffmpeg writes the range flag only beside a colour description (conftest's
    pc_ramp_clip), so the segment's conversion to tv is visible."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    root = tmp_path_factory.mktemp("freeze")
    made: dict = {}

    def make(rate: str):
        if rate not in made:
            out = root / f"count_{rate.replace('/', '_')}.mp4"
            proc.run([binary, "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r={rate}:d=3",
                      "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-t", "3",
                      "-c:v", "libx264", "-pix_fmt", "yuvj420p", "-color_range", "pc",
                      "-color_primaries", "bt709", "-color_trc", "bt709",
                      "-colorspace", "bt709", "-c:a", "aac", str(out)])
            made[rate] = out
        return made[rate]
    return make


def _streams(path, kind: str) -> list[dict]:
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", kind,
                    "-count_frames", "-show_entries", "stream=nb_read_frames,color_range",
                    "-of", "json", str(path)]).stdout
    return json.loads(out)["streams"]


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def _first(path, fps: float) -> np.ndarray:
    return assembly.frames_rgb(str(path), [0.0], fps)[0]


@pytest.mark.parametrize("rate, start, dur", [
    ("30", 0.51, 1.51),            # the review's worked case
    ("30", 0.152, 1.209),          # the source-time formula was one frame EARLY here
    ("30", 0.482, 1.592),          # ...and one frame LATE here
    ("30000/1001", 0.154, 0.847),  # NTSC, off-grid both ends: one early
])
def test_a_freeze_holds_the_last_frame_its_segment_decodes(counting_clip, tmp_path,
                                                           rate, start, dur):
    clip = counting_clip(rate)
    num, den = (float(v) for v in (rate.split("/") + ["1"])[:2])
    fps = num / den
    footage = Footage(clips=[FootageClip(source=clip.name, dur=3.0, res=(640, 360), fps=fps)])
    played = EDLEpisode(source=clip.name, start=start, dur=dur, shot_type="wide",
                        composition="lead", grid="thirds")
    eps = edit_plan._resolve_freezes([played, replace(played, freeze=True, dur=1.0)], footage)
    seg, held = extract.extract_edl(EDL(episodes=tuple(eps)), str(clip.parent),
                                    str(tmp_path / "seg"))

    n = assembly.count_frames(seg)
    second_last, last = assembly.frames_rgb(seg, [(n - 2) / fps, (n - 1) / fps], fps)
    frozen = assembly.frames_rgb(held, [k / fps for k in range(assembly.count_frames(held))],
                                 fps)
    gap = _dist(last, second_last)
    # nearer the segment's last decoded frame than the one before it, and within encode
    # noise of it — the ordering alone cannot see a frame one LATE, which also sits nearer
    # the last frame than the second-to-last (measured 5.09 against 8.17 on this pattern)
    assert _dist(frozen[0], last) < _dist(frozen[0], second_last)
    assert _dist(frozen[0], last) < gap / 4

    # The bound can tell them apart, re-measured on every run rather than trusted: a
    # freeze of the frame BEFORE lands on the second-to-last, and a freeze of the frame
    # AFTER fails the bound. The early control's segment is this one trimmed by a frame;
    # the late one's is the window cut one frame longer, checked to end one frame later.
    short = tmp_path / "short.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-i", seg, "-vf", f"trim=end_frame={n - 1}",
              "-an", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(short)])
    early = _first(extract.extract_freeze(str(short), 1.0, str(tmp_path / "early.mp4")), fps)
    assert _dist(early, second_last) < _dist(early, last)
    longer = extract.extract(str(clip), start, dur + 1 / fps, str(tmp_path / "longer.mp4"))
    assert assembly.count_frames(longer) == n + 1
    assert _dist(assembly.frames_rgb(longer, [(n - 1) / fps], fps)[0], last) < gap / 4
    late = _first(extract.extract_freeze(longer, 1.0, str(tmp_path / "late.mp4")), fps)
    assert not _dist(late, last) < gap / 4

    assert len(frozen) == round(1.0 * fps)
    assert max(_dist(f, frozen[0]) for f in frozen) < gap / 10    # one frame, encode noise
    assert _streams(seg, "a") != [] and _streams(held, "a") == []  # the tone was dropped
    assert _streams(clip, "v:0")[0]["color_range"] == "pc"    # the control
    assert _streams(held, "v:0")[0]["color_range"] == "tv"


def test_a_freeze_crosses_the_geometry_split_over_a_held_route_untracked(tmp_path,
                                                                        monkeypatch):
    """Phase 1a then phase 1b on real ffmpeg. YOLO is replaced by the committed golden
    route — written where a rung-1 pass writes it, its sidecar beside it — and every
    call is recorded, so "the freeze was not tracked" is an observation, not a reading
    of the code. Everything else — extract, the contradiction gate, reframe,
    check_episode — runs for real."""
    route = json.loads((FIX / "golden_route.json").read_text())
    meta = json.loads((FIX / "golden_route.meta.json").read_text())
    tracked: list[str] = []

    def build_route(spec, out):
        tracked.append(spec.src)
        pts = [p for p in route if p["t"] <= assembly.probe_duration(spec.src)]
        Path(out).write_text(json.dumps(pts))
        Path(out).with_suffix(".meta.json").write_text(json.dumps(meta))
        return [models.RoutePoint.from_dict(p) for p in pts]
    monkeypatch.setattr(track, "build_route", build_route)
    monkeypatch.setattr(track, "ensure_model", lambda model=track.MODEL: None)
    monkeypatch.setattr(track, "available", lambda descriptor=False: True)

    foot = tmp_path / "footage"
    foot.mkdir()
    shutil.copy(FIX / "golden_ride.mp4", foot / "ride.mp4")
    fps = assembly.probe_stream(str(foot / "ride.mp4")).fps
    row = {"source": "ride.mp4", "shot_type": "wide", "grid": "thirds",
           "composition": "center"}
    edl = tmp_path / "EDL.json"
    edl.write_text(json.dumps({"episodes": [
        {**row, "start": 0.0, "dur": 0.75},
        {**row, "start": 0.75 - 1 / fps, "dur": 0.5, "freeze": True}]}))
    project = tmp_path / "project.json"
    # 1:1 against 1280x720 under native: a 720x720 crop that nothing resamples
    project.write_text(json.dumps({"purpose": "reel", "canvas": [1, 1], "delivery": "native"}))
    reel = tmp_path / "reels" / "main"
    work, out = str(reel / "build"), str(reel / "episodes")

    geo, stop = edl_to_reel.build_geometry(str(edl), str(project), str(foot), work, out)
    assert stop is None, stop
    seg0, seg1 = (str(Path(work) / "segments" / f"ep{i}_raw.mp4") for i in (0, 1))
    assert tracked == [seg0]                       # the freeze never reached the tracker
    played = json.loads(Path(geo.episodes[0].route).read_text())
    held = json.loads(Path(geo.episodes[1].route).read_text())
    n = assembly.count_frames(seg1)
    assert n == round(0.5 * fps)
    assert held == [{**played[-1], "t": k / fps} for k in range(n)]   # constant, the last
    assert played[-1] != played[0]                 # ...and the last is not the first
    assert json.loads(Path(geo.episodes[1].route).with_suffix(".meta.json").read_text()) == meta

    rm, stop = edl_to_reel.render_from_geometry(str(Path(out) / "GEOMETRY.json"),
                                                str(project), work, out)
    assert stop is None, stop
    assert tracked == [seg0]                       # phase 1b tracks nothing at all
    assert rm.episodes[1].route == geo.episodes[1].route
    assert Path(rm.episodes[1].clip).exists()
