"""Real-ffmpeg proof of the conductor: two clips of different exposure, each with tonal
range, converge toward the median target once the authored tone_arg curve is rendered."""
from pathlib import Path

import pytest
from scripts import match_grade
from scripts.color_measure import measure_profile
from scripts.lib import color, ffbin, matchgrade, moodpreset, proc
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

    out, target, decisions, _ = match_grade.conduct(edl, str(tmp_path))
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


def test_tone_arg_transfer_is_actually_emitted():
    # re-pinned 2026-08-19: the actuator the conductor feeds is a lutyuv LUT over
    # the Y plane, not an RGB spline.
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")


def test_a_moody_bias_renders_darker_than_the_plain_median(tmp_path):
    """The visibility proof (design 2026-08-17 §7). Not 'the curve was built' — the
    delivered frame's own percentiles must sit below the unbiased render's, in the
    direction the preset asked for. Same clip, same source profile, two targets."""
    clip = _three_band(tmp_path / "m.mp4", "0x101010", "0x404040", "0x808080")
    prof = measure_profile(str(clip))
    plain = matchgrade.common_target([prof, (60.0, 130.0, 220.0)])
    moody, k = matchgrade.biased_target(plain, moodpreset.resolve("moody").tone_bias)
    assert k == 1.0                      # the fixture leaves room; if not, the test lies

    got_plain = _graded_profile(clip, prof, plain, tmp_path / "plain.mp4")
    got_moody = _graded_profile(clip, prof, moody, tmp_path / "moody.mp4")
    assert got_moody[0] < got_plain[0]   # shadows crushed
    assert got_moody[1] < got_plain[1]   # midtones darker


# --- the ruler: design 2026-08-19 §1 -----------------------------------------

def _grid(path, field: str, spark: str):
    """The same idea built by geq, which can draw the grid in one pass."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"color=c={field}:s=240x240:d=1:r=25",
              "-vf", f"format=gray,geq=lum='if(lt(mod(X,8),2)+lt(mod(Y,8),2),240,32)',"
                     "format=yuv420p",
              "-frames:v", "1", str(path)])
    return path


def test_measure_profile_reads_the_frames_own_fine_highlights(tmp_path):
    """design §1. `scale=160:-2` reduced the area 12x before histogramming and read
    the run's drone frame's p95 NINE UNITS LOW (196 against 205) — specular
    highlights are small and bright, and averaging is what a downscale does.

    The control is the same frame's p5: a bulk statistic, which never moved. Without
    it "p95 is high" cannot be told from "the whole frame got brighter"."""
    clip = _grid(tmp_path / "grid.mp4", "0x202020", "0xF0F0F0")
    p5, _, p95 = measure_profile(str(clip), at=0.0)
    assert p95 > 200, f"the fine structure never reached p95 (got {p95}) — averaged away"
    assert p5 < 60, f"the dark bulk moved too ({p5}) — this is not a p95-only effect"


# --- the transfer itself: design 2026-08-19 §2 -------------------------------

def _ramp_y(frag: str) -> list[int]:
    """A lossless 256-step ramp through `frag`, in and out as the raw Y PLANE — one
    sample per input code, no encode and no pixel-format conversion anywhere.

    yuv444p in and not gray-then-format, which is the harness's own version of the
    trap this slice is about: `format=yuv444p` from a gray source runs swscale, and
    swscale converts full range to tv on the way, so code 16 arrives at the filter
    as 30 and every reading is shifted (measured while writing this test). Handing
    ffmpeg the plane directly leaves nothing between the codes and the LUT."""
    y = bytes(bytearray([x for x in range(256) for _ in range(8)]))
    raw = y + bytes([128]) * (2 * len(y))          # U and V neutral
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuv444p",
                    "-s", "2048x1", "-i", "-", "-vf", frag,
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"],
                   input=raw).stdout
    assert len(out) >= 2048, f"no frame out of {frag[:60]!r}"
    return [out[i * 8] for i in range(256)]


def test_the_tone_map_renders_within_a_code_of_itself():
    """design §2.3. A LUT has no spline to overshoot, so the four segments ARE the
    map — the only error left is the integer rounding of storing it.

    The control is the map's own arithmetic: `_lerp` through the SAME knots, in
    full range, converted at both ends exactly as the emitted expression does. A
    test that compared the render only against itself would pass on any map."""
    src, dst = (73.0, 137.0, 196.0), (61.0, 123.5, 192.0)
    got = _ramp_y(color.tone_arg(src, dst).rstrip(","))
    segs = color._segments(src, dst)
    want = [color.TV_LO + color._lerp(segs, (y - color.TV_LO) * 255 / color.TV_SPAN)
            * color.TV_SPAN / 255 for y in range(256)]
    worst = max(abs(g - w) for g, w in zip(got[16:236], want[16:236]))   # the legal range
    assert worst <= 1.0, f"the LUT is {worst:.2f} codes off its own map"
    assert all(b >= a for a, b in zip(got[16:236], got[17:236])), "the transfer bands"


def test_the_tone_transfer_leaves_chroma_byte_identical(tmp_path):
    """design §2.2. lutyuv never writes U or V, so a tone move cannot shift a hue.

    The CONTROL is the same knots emitted the old way — a curves=all spline over
    RGB — which must move them. Without it, "chroma did not change" cannot be told
    from "nothing rendered at all"."""
    clip = _three_band(tmp_path / "c.mp4", "0x402010", "0x80A040", "0xC0E0F0")
    src, dst = (30.0, 120.0, 200.0), (40.0, 130.0, 190.0)

    def planes(frag):
        a = [ffbin.ffmpeg(), "-v", "error", "-i", str(clip)]
        out = proc.run(a + (["-vf", frag] if frag else []) +
                       ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"]).stdout
        n = len(out) // 3
        return out[n:]                                    # U and V, as bytes

    base = planes("")
    assert planes(color.tone_arg(src, dst).rstrip(",")) == base, "lutyuv touched chroma"

    segs = color._segments(src, dst)
    pts = " ".join(f"{x/255:.4f}/{color._lerp(segs, x)/255:.4f}" for x in range(0, 256, 20))
    assert planes(f"curves=all='{pts}'") != base, (
        "the per-channel control did NOT move chroma — the comparison proves nothing")


def _pcts(path, width) -> tuple[float, float, float]:
    """(p5,p50,p95) of the gray histogram at `width`, or at the frame's own if None —
    measure_profile's two instruments, side by side."""
    vf = "format=gray" if width is None else f"scale={width}:-2,format=gray"
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path), "-frames:v", "1",
                    "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    hist = [0] * 256
    for b in out:
        hist[b] += 1
    return color.percentiles(hist)


def test_both_halves_are_needed_to_close_the_residual(tmp_path):
    """design §0, as a test. The conductor MEASURES, targets, AUTHORS and is then
    judged — so an instrument change has to change all four, which is what the
    earlier §3.4 reading got wrong by changing only the last one.

    Four combinations of (instrument, transfer). The pair must beat both halves;
    if a later change fixes one alone, this reddens with the number saying which."""
    a = _grid(tmp_path / "a.mp4", "0x202020", "0xF0F0F0")
    b = _three_band(tmp_path / "b.mp4", "0x303030", "0x909090", "0xF0F0F0")

    def residual(width, luma: bool) -> float:
        srcs = [_pcts(c, width) for c in (a, b)]
        tgt = tuple(sorted(s[i] for s in srcs)[len(srcs) // 2] for i in range(3))
        worst = 0.0
        for clip, src in zip((a, b), srcs):
            if not (src[0] + color.TONE_MIN_GAP <= src[1] <= src[2] - color.TONE_MIN_GAP):
                continue                       # tone_arg would refuse it; not this test's case
            frag = color.tone_arg(src, tgt).rstrip(",")
            if not luma:                       # the per-channel shape, from the same knots
                segs = color._segments(src, tgt)
                frag = "curves=all='" + " ".join(
                    f"{x/255:.4f}/{color._lerp(segs, x)/255:.4f}"
                    for x in range(0, 256, 20)) + "'"
            out = tmp_path / f"o_{width or 'full'}_{luma}_{Path(clip).stem}.mkv"
            proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-i", str(clip), "-vf", frag,
                      "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(out)])
            worst = max(worst, max(abs(g - t) for g, t in zip(_pcts(out, width), tgt)))
        return worst

    shipped = residual(160, luma=False)
    ruler_only = residual(None, luma=False)
    transfer_only = residual(160, luma=True)
    both = residual(None, luma=True)
    assert both < shipped, f"the pair did not improve on the shipped chain ({both} vs {shipped})"
    assert both <= ruler_only and both <= transfer_only, (
        f"one half alone matched the pair — pair {both}, ruler {ruler_only}, "
        f"transfer {transfer_only}. Each is a PARTIAL fix (design §0); if that has "
        f"stopped being true, the design's table is what needs re-measuring")
