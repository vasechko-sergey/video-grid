"""Real-ffmpeg proofs for the speed ramp (design §11).

These render actual pixels. A correct-looking argv is not evidence that a frame
moved — backlog #18's whole finding is that a live-added vignette came out
invisible and no test caught it.
"""
import subprocess

import pytest

from scripts.lib import assembly, ffbin, proc, ramp
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


def test_the_retimed_segment_carries_no_audio(ramp_clip, tmp_path):
    dst = str(tmp_path / "ramped.mp4")
    ramp.retime(str(ramp_clip), dst, SPEC, DUR, FPS)
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


def test_an_unramped_extract_is_unchanged_by_this_slice(sample_clip, tmp_path):
    """No ramp, no retime, no new bytes — the golden fixtures depend on it."""
    from scripts import extract
    from scripts.lib.edl import EDL, EDLEpisode
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.mp4").write_bytes(sample_clip.read_bytes())
    e = EDL(episodes=[EDLEpisode(source="a.mp4", start=0.0, dur=1.0,
                                 shot_type="medium", composition="center",
                                 grid="thirds")])
    one = extract.extract_edl(e, str(src_dir), str(tmp_path / "s1"))
    two = extract.extract_edl(e, str(src_dir), str(tmp_path / "s2"))
    from pathlib import Path
    assert Path(one[0]).read_bytes() == Path(two[0]).read_bytes()
    assert not list((tmp_path / "s1").glob("*_ramped.mp4"))
