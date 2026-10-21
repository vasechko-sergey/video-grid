"""Real-ffmpeg proof for the freeze (design 2026-10-21 §3).

A window and a freeze of its last frame are cut from a clip whose frames all differ,
through the same path a reel takes (edit_plan resolves the frozen frame, extract cuts
both), and the pixels are read back: the freeze must be the frame the window ends on,
not its neighbour, held for its whole length, silent, on the segment range contract."""
import json
from dataclasses import replace

import numpy as np
import pytest

from scripts import edit_plan, extract
from scripts.lib import assembly, ffbin, proc
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.footage import Footage, FootageClip

pytestmark = pytest.mark.integration

FPS = 30.0


@pytest.fixture(scope="module")
def counting_clip(tmp_path_factory):
    """3s 640x360 30fps testsrc2 — its pattern moves and it prints a frame counter, so
    no two frames are alike — with a tone on it, so the freeze's silence is a drop.
    FULL range with a bt709 description, as camera footage arrives: ffmpeg writes the
    range flag only beside a colour description (conftest's pc_ramp_clip), and a pc
    source is the one the freeze's range pair has to convert."""
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("freeze") / "count.mp4"
    proc.run([binary, "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3",
              "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-t", "3",
              "-c:v", "libx264", "-pix_fmt", "yuvj420p", "-color_range", "pc",
              "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
              "-c:a", "aac", str(out)])
    return out


def _streams(path, kind: str) -> list[dict]:
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", kind,
                    "-count_frames", "-show_entries", "stream=nb_read_frames,color_range",
                    "-of", "json", str(path)]).stdout
    return json.loads(out)["streams"]


def _frames(path) -> int:
    return int(_streams(path, "v:0")[0]["nb_read_frames"])


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def test_a_freeze_holds_the_last_frame_its_window_shows(counting_clip, tmp_path):
    name = counting_clip.name
    footage = Footage(clips=[FootageClip(source=name, dur=3.0, res=(640, 360), fps=FPS)])
    played = EDLEpisode(source=name, start=0.5, dur=1.5, shot_type="wide",
                        composition="lead", grid="thirds")
    eps = edit_plan._resolve_freezes([played, replace(played, freeze=True, dur=1.0)], footage)
    seg, held = extract.extract_edl(EDL(episodes=tuple(eps)), str(counting_clip.parent),
                                    str(tmp_path / "seg"))

    n = _frames(seg)
    second_last, last = assembly.frames_rgb(seg, [(n - 2) / FPS, (n - 1) / FPS], FPS)
    frozen = assembly.frames_rgb(held, [k / FPS for k in range(_frames(held))], FPS)
    # nearer the window's last frame than the one before it...
    assert _dist(frozen[0], last) < _dist(frozen[0], second_last)
    # ...and within encode noise of it, which a frame one LATE is not: measured, the
    # frame after the window sits nearer its last frame (5.09) than its second-to-last
    # (8.17), so the ordering alone cannot see it — the right frame is 0.49 off, against
    # a 4.37 step between neighbours
    gap = _dist(last, second_last)
    assert _dist(frozen[0], last) < gap / 4
    # ...and the comparison can tell them apart: a freeze one frame early lands on the
    # second-to-last, so the assertion above would fail against a wrong frame
    early = extract.extract_freeze(str(counting_clip), eps[1].start - 1 / FPS, 1.0, FPS,
                                   str(tmp_path / "early.mp4"))
    early0 = assembly.frames_rgb(early, [0.0], FPS)[0]
    assert _dist(early0, second_last) < _dist(early0, last)

    assert len(frozen) == round(1.0 * FPS)
    assert max(_dist(f, frozen[0]) for f in frozen) < gap / 10    # one frame, encode noise
    assert _streams(seg, "a") != [] and _streams(held, "a") == []  # the tone was dropped
    assert _streams(counting_clip, "v:0")[0]["color_range"] == "pc"    # the control
    assert _streams(held, "v:0")[0]["color_range"] == "tv"
