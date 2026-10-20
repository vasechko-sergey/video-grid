"""Real-ffmpeg proofs for the photo segment (design 2026-10-20 §3, §4).

These read the pixels back. The contract fields are probed from the file, the colour
is decoded and compared against what was drawn, and the move is compared frame by frame
against zoompan's — the premise U6 was filed on."""
import json

import numpy as np
import pytest
from PIL import Image

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
                         timescale=30000)
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
    facts = still.render(st, pl.frames, (320, 180), "30/1", str(tmp_path / "big.mp4"))
    assert facts["levels"] == 2
    small = kenburns.plan(st.dims, (16, 9), 1.0, None, "center", "thirds",
                          StillSpec(1.0, 0.92), 30)
    assert still.render(st, small.frames, (320, 180), "30/1",
                        str(tmp_path / "small.mp4"))["levels"] == 1


def test_the_colour_survives_and_an_untagged_segment_would_not(tmp_path):
    """Drawn patches decode back within a few codes. The control is the trap §4 names: a
    plain rgb24 pipe with no matrix and no tags encodes BT.601 untagged — ffmpeg decodes
    that as 601 and agrees with itself, while a player that reads untagged HD as BT.709
    (decoded here explicitly as 709) moves the saturated patches by far more."""
    st = _chart()
    out = tmp_path / "seg.mp4"
    still.render(st, _static(st, 2), (640, 360), "30/1", str(out))
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
    still.render(st, pl.frames, (W, H), "30/1", str(ours))
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
