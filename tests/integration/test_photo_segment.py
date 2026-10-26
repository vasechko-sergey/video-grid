"""Real-ffmpeg proofs for the photo segment (design 2026-10-20 §3, §4; 2026-10-21 §7).

These read the pixels back. The contract fields are probed from the file, the colour
is decoded and compared against what was drawn, and the move is compared frame by frame
against zoompan's — the premise U6 was filed on."""
import json

import cv2

import numpy as np
import pytest
from PIL import Image

from scripts import extract
from scripts.lib import assembly, ffbin, kenburns, proc, still
from scripts.lib.kenburns import Rect
from scripts.lib.models import StillSpec

pytestmark = pytest.mark.integration

PATCHES = [(230, 30, 40), (40, 180, 60), (30, 60, 220), (224, 172, 140), (128, 128, 128)]


def _chart(w=640, h=360) -> still.Still:
    """Five flat patches across the width — red, green, blue, a skin tone, grey."""
    rgb = np.zeros((h, w, 3), np.uint8)
    step = w // len(PATCHES)
    for i, c in enumerate(PATCHES):
        rgb[:, i * step:(i + 1) * step] = c
    return still.Still(rgb=rgb, record={})


def _probe(path) -> dict:
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-show_streams", "-count_frames",
                    "-of", "json", str(path)]).stdout
    return json.loads(out)


def _static(st: still.Still, n: int) -> list[Rect]:
    w, h = st.dims
    return [Rect(0.0, 0.0, float(w), float(h))] * n


def test_the_segment_is_on_the_video_contract(tmp_path):
    st = _chart()
    out = tmp_path / "seg.mp4"
    facts = still.render(st, _static(st, 30), (320, 180), "30000/1001", str(out),
                         colour=still.BT709, timescale=30000)
    streams = _probe(out)["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]          # no audio stream
    v = streams[0]
    assert (v["width"], v["height"]) == (320, 180)
    assert v["pix_fmt"] == "yuv420p" and v["color_range"] == "tv"
    assert v["color_space"] == "bt709" and v["color_primaries"] == "bt709"
    assert v["color_transfer"] == "bt709"
    assert v["sample_aspect_ratio"] == "1:1"
    assert v["r_frame_rate"] == "30000/1001" and v["time_base"] == "1/30000"
    assert int(v["nb_read_frames"]) == 30
    assert facts == {"prescale": 0.5, "upscale": 0.5, "levels": 1}


def test_a_big_move_drops_to_a_coarser_level_rather_than_alias(tmp_path):
    """The review's M8: 1.0 -> 0.3 samples its widest frame at 3.3 source pixels per
    output pixel from the 1:1-at-tight pre-scale; past MAX_DENSITY it takes a half level."""
    st = _texture(1600, 900)
    pl = kenburns.plan(st.dims, (16, 9), 1.0, None, "center", "thirds",
                       StillSpec(1.0, 0.3), 30)
    facts = still.render(st, pl.frames, (320, 180), "30/1", str(tmp_path / "big.mp4"),
                         colour=still.BT709)
    assert facts["levels"] == 2
    small = kenburns.plan(st.dims, (16, 9), 1.0, None, "center", "thirds",
                          StillSpec(1.0, 0.92), 30)
    assert still.render(st, small.frames, (320, 180), "30/1",
                        str(tmp_path / "small.mp4"), colour=still.BT709)["levels"] == 1


def test_the_colour_survives_and_an_untagged_segment_would_not(tmp_path):
    """Drawn patches decode back within a few codes. The control is the trap §4 names: a
    plain rgb24 pipe with no matrix and no tags encodes BT.601 untagged — ffmpeg decodes
    that as 601 and agrees with itself, while a player that reads untagged HD as BT.709
    (decoded here explicitly as 709) moves the saturated patches by far more."""
    st = _chart()
    out = tmp_path / "seg.mp4"
    still.render(st, _static(st, 2), (640, 360), "30/1", str(out), colour=still.BT709)
    step = 640 // len(PATCHES)

    def worst(path, vf):
        raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path), "-frames:v", "1",
                        "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
        f = np.frombuffer(raw, np.uint8).reshape(360, 640, 3).astype(int)
        return max(int(np.abs(f[180, i * step + step // 2] - np.array(c)).max())
                   for i, c in enumerate(PATCHES))

    as709 = "scale=in_color_matrix=bt709,format=rgb24"
    assert worst(out, "format=rgb24") <= 4 and worst(out, as709) <= 4

    naive = tmp_path / "naive.mp4"
    proc.feed([ffbin.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", "640x360", "-framerate", "30", "-i", "-",
               "-vf", "scale=out_range=tv,format=yuv420p", "-c:v", "libx264", "-crf", "18",
               "-pix_fmt", "yuv420p", "-an", str(naive)], [st.rgb.tobytes()] * 2)
    assert worst(naive, "format=rgb24") <= 4          # ffmpeg agrees with itself...
    assert worst(naive, as709) > 12                   # ...a 709 reader does not


# How a camera describes the chart, as the encoder options that write it. The matrix is
# the one the description names, so ffmpeg reads each camera's colours back.
_CAMERAS = {
    "undescribed": "scale=out_range=tv,format=yuv420p",
    "bt709": "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
             "setparams=colorspace=bt709",
    "smpte170m": "scale=out_color_matrix=smpte170m:out_range=tv,format=yuv420p,"
                 "setparams=colorspace=smpte170m",
}
_TAGS = ("color_space", "color_primaries", "color_transfer", "color_range")
_N = 6                                   # frames per episode of the spliced master


def _video_segment(st: still.Still, camera: str, out) -> str:
    """The chart as a video segment the pipeline holds: a camera's encode of it, cut by
    extract like any window."""
    cam = out.with_name(out.stem + "_cam.mp4")
    proc.feed([ffbin.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", "640x360", "-framerate", "30", "-i", "-", "-vf", _CAMERAS[camera],
               "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(cam)],
              [st.rgb.tobytes()] * _N)
    return extract.extract(str(cam), 0.0, _N / 30, str(out))


def _master(tmp_path, camera: str, colour: still.Colour | None = None):
    """video, photo, video — spliced by `-c copy` as assemble splices a reel. The photo
    takes the first video segment's clock and, unless `colour` overrides it, its colour
    description, exactly as extract_edl hands them over."""
    st = _chart()
    a = _video_segment(st, camera, tmp_path / "a.mp4")
    b = _video_segment(st, camera, tmp_path / "b.mp4")
    rate, ts = assembly.probe_rate(a)
    photo = tmp_path / "photo.mp4"
    still.render(st, _static(st, _N), (640, 360), rate, str(photo),
                 colour=colour or still.colour_of(a), timescale=ts)
    return assembly.concat([a, str(photo), b], str(tmp_path / "master.mp4")), a


def _tags(path, of: str = "stream") -> list[tuple]:
    """The four colour tags of the video stream, or of every decoded frame (`of="frame"`:
    what the decoder hands the filter graph, carried-over descriptions included); None
    where ffprobe reads none."""
    rows = json.loads(proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
                                "-show_entries", f"{of}=" + ",".join(_TAGS), "-of", "json",
                                str(path)]).stdout)[f"{of}s"]
    return [tuple(r.get(k) for k in _TAGS) for r in rows]


def _patch_errors(path) -> list[int]:
    """Each frame's worst patch, decoded by ffmpeg's own reading of each frame's
    description — the decoder every sensor of this pipeline reads the master through."""
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path), "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "-"]).stdout
    step = 640 // len(PATCHES)
    return [max(int(np.abs(f[180, i * step + step // 2] - np.array(c)).max())
                for i, c in enumerate(PATCHES))
            for f in np.frombuffer(raw, np.uint8).reshape(-1, 360, 640, 3).astype(int)]


@pytest.mark.parametrize("camera", sorted(_CAMERAS))
def test_between_video_segments_the_photo_takes_their_description(tmp_path, camera):
    """Design 2026-10-21 §7. The photo is described as the video beside it, so the master
    never changes description — no frame of it, the photo's and the video's after it
    included — and every frame's patches decode back within the colour test's 4 codes."""
    master, a = _master(tmp_path, camera)
    assert _tags(master, of="frame") == _tags(a) * (3 * _N)
    errors = _patch_errors(master)
    assert len(errors) == 3 * _N and max(errors) <= 4, errors


def test_a_bt709_stamped_photo_between_undescribed_video_changes_the_masters_description(
        tmp_path):
    """The control — the stamp every photo carried before this fix. The decoder carries
    the photo's description over to video frames whose own parameter sets name none —
    every frame after the photo, and (decode order) the last two before it — so those
    decode through BT.709 instead of the BT.601 they were encoded with, and their
    saturated patches move: measured 21 codes."""
    master, _ = _master(tmp_path, "undescribed", colour=still.BT709)
    tags, errors = _tags(master, of="frame"), _patch_errors(master)
    assert tags[0] == (None,) * 4 and tags[-1] == ("bt709", "bt709", "bt709", "tv")
    for i in [*range(_N), *range(2 * _N, 3 * _N)]:
        # a video frame decodes right exactly when it keeps its own (absent) description
        assert (errors[i] <= 4) == (tags[i] == (None,) * 4), (i, tags[i], errors[i])
    assert max(errors[_N:2 * _N]) <= 4                  # the photo itself reads right
    assert min(errors[2 * _N:]) > 12, errors            # all of the video after it does not


def _texture(w: int, h: int, seed: int = 7) -> still.Still:
    rng = np.random.default_rng(seed)
    return still.Still(rgb=rng.integers(0, 256, (h, w, 3), dtype=np.uint8), record={})


def _blob(w: int, h: int) -> still.Still:
    """One soft dot off-centre on black: a push moves it, and its centroid is a
    sub-pixel ruler for where the frame went."""
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-((xx - w * 0.25) ** 2 + (yy - h * 0.3) ** 2) / (2 * (w / 250) ** 2))
    return still.Still(rgb=(np.repeat(g[..., None], 3, axis=2) * 255).astype(np.uint8),
                       record={})


def _wobble(path, w, h, n) -> float:
    """RMS distance, in output pixels, of the dot's x from a smooth cubic over the middle
    half of the move — how far the motion strays from the curve it should ride."""
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path), "-f", "rawvideo",
                    "-pix_fmt", "gray", "-"]).stdout
    xs = []
    for f in np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(float):
        f[f < 20] = 0
        xs.append((f * np.arange(w)[None, :]).sum() / f.sum())
    x, k = np.array(xs)[n // 4:3 * n // 4], np.arange(n)[n // 4:3 * n // 4]
    return float(np.sqrt(((x - np.polyval(np.polyfit(k, x, 3), k)) ** 2).mean()))


def test_the_float_warp_rides_a_smooth_curve_where_zoompan_stair_steps(tmp_path):
    """The same slow 5 % push over 3 s, from a source 1.2x the output (the density the
    planner's pre-scale leaves for an 8 % push). zoompan truncates its crop to whole
    source pixels every frame, so the dot wanders off the curve; the float warp does not.
    Measured 2026-10-20: 0.46 px against 0.02 here, 0.28 against 0.03 at 2x."""
    n, W, H = 90, 320, 180
    st = _blob(384, 216)
    pl = kenburns.plan(st.dims, (16, 9), 1.0, None, "center", "thirds",
                       StillSpec(1.0, 0.95), n)
    ours = tmp_path / "warp.mp4"
    still.render(st, pl.frames, (W, H), "30/1", str(ours), colour=still.BT709)
    src = tmp_path / "blob.png"
    Image.fromarray(st.rgb).save(src)
    zp = tmp_path / "zoompan.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-i", str(src), "-vf",
              f"zoompan=z='1+({1 / 0.95 - 1:.6f})*on/{n - 1}':x='iw/2-(iw/zoom/2)'"
              f":y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps=30",
              "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
              str(zp)])
    warp, zoompan = _wobble(ours, W, H, n), _wobble(zp, W, H, n)
    print(f"wobble off a smooth curve: float warp {warp:.3f} px, zoompan {zoompan:.3f} px")
    assert warp < 0.06
    assert zoompan > 0.2 and zoompan > 5 * warp


def test_the_level_change_is_blended_not_a_jump_in_sharpness(tmp_path):
    """The re-review's Minor: a hard switch between pyramid levels read as one frame
    suddenly sharper than the last (Laplacian variance 719 -> 2269 between neighbours).
    Blended, sharpness changes smoothly frame to frame. Measured 2026-10-20 on this
    fixture: 1.28 blended, 6.40 with the hard switch put back."""
    st = _texture(1600, 900)
    n, W, H = 60, 320, 180
    pl = kenburns.plan(st.dims, (16, 9), 1.0, None, "center", "thirds", StillSpec(1.0, 0.3), n)
    out = tmp_path / "big.mp4"
    still.render(st, pl.frames, (W, H), "30/1", str(out), colour=still.BT709)
    sharp = [float(cv2.Laplacian(f.astype(np.float64), cv2.CV_64F).var())
             for f in _gray_frames(out, W, H)]
    jumps = [max(a, b) / min(a, b) for a, b in zip(sharp, sharp[1:])]
    print(f"worst frame-to-frame sharpness ratio {max(jumps):.2f}")
    assert max(jumps) < 2.0


def _gray_frames(path, w, h) -> np.ndarray:
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path), "-f", "rawvideo",
                    "-pix_fmt", "gray", "-"]).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.int16)
