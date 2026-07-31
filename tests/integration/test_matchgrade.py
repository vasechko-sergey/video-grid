"""Real-ffmpeg proof of the conductor: two clips of different exposure, each with tonal
range, converge toward the median target once the authored tone_arg curve is rendered."""
import pytest
from scripts import match_grade
from scripts.color_measure import measure_profile
from scripts.lib import color, ffbin, proc
from scripts.lib.edl import EDL, EDLEpisode

pytestmark = pytest.mark.integration


def _three_band(path, lo, mid, hi):
    """A clip whose left 1/4 is `lo`, middle 1/2 is `mid`, right 1/4 is `hi` — a real
    tonal range with well-separated p5 < p50 < p95 around a controllable exposure. A
    50/50 two-band frame would collapse p5==p50 (invalid tone_src); the 1:2:1 split keeps
    all three anchors apart. (Mirrors tests/integration/test_color_measure.py's lavfi pattern.)"""
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c={lo}:s=80x240:d=2:r=25",
              "-f", "lavfi", "-i", f"color=c={mid}:s=160x240:d=2:r=25",
              "-f", "lavfi", "-i", f"color=c={hi}:s=80x240:d=2:r=25",
              "-filter_complex", "hstack=inputs=3", "-pix_fmt", "yuv420p", str(path)])
    return path


def _ep(source):
    return EDLEpisode(source=source, start=0.0, dur=2.0, shot_type="wide",
                      composition="center", grid="thirds")


def _graded_profile(clip, src, dst, out):
    """Apply the REAL tone_arg curve (what reframe's grade_chain emits) and measure the result."""
    vf = color.tone_arg(src, dst).rstrip(",")            # strip the chain-joining comma
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(clip), "-vf", vf, "-pix_fmt", "yuv420p", str(out)])
    return measure_profile(str(out))


def test_authored_tone_converges_two_exposures(tmp_path):
    dark = _three_band(tmp_path / "d.mp4", "0x101010", "0x404040", "0x808080")
    bright = _three_band(tmp_path / "b.mp4", "0x505050", "0xA0A0A0", "0xE0E0E0")
    edl = EDL(episodes=(_ep("d.mp4"), _ep("b.mp4")))

    out, target, decisions = match_grade.conduct(edl, str(tmp_path))
    assert all(d.action == "author" for d in decisions)   # both deviate from the median

    p_dark, p_bright = measure_profile(str(dark)), measure_profile(str(bright))
    for k in range(3):                                    # target (median of 2) lies between the sources
        lo, hi = sorted((p_dark[k], p_bright[k]))
        assert lo <= target[k] <= hi

    src_spread = abs(p_dark[1] - p_bright[1])             # p50 gap before grading
    g_dark = _graded_profile(dark, out.episodes[0].tone_src, out.episodes[0].tone_dst,
                             tmp_path / "gd.mp4")
    g_bright = _graded_profile(bright, out.episodes[1].tone_src, out.episodes[1].tone_dst,
                               tmp_path / "gb.mp4")
    graded_spread = abs(g_dark[1] - g_bright[1])

    assert graded_spread < src_spread                     # the reel converged
    assert abs(g_dark[1] - target[1]) < abs(p_dark[1] - target[1])       # each moved toward target
    assert abs(g_bright[1] - target[1]) < abs(p_bright[1] - target[1])


def test_tone_arg_curve_is_actually_emitted():
    # the actuator the conductor feeds is a curves=all=... fragment
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert frag.startswith("curves=all='") and frag.endswith("',")
