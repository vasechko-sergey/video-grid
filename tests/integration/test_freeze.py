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
not."""
import json
from dataclasses import replace

import numpy as np
import pytest

from scripts import edit_plan, extract
from scripts.lib import assembly, ffbin, proc
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.footage import Footage, FootageClip

pytestmark = pytest.mark.integration


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
