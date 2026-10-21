"""Real-ffmpeg proofs for the shutter accent (design 2026-10-21 §4): the white flash in
deliver's one encode and the click in mix's SFX bed.

The flash is three frames of white over the delivered picture and nothing in the
master, so the look gate — which compares the two — has to sample around it. The
controls that make that exclusion load-bearing judge the SAME delivered file with a
gate that does not know about the flash: the vignette's sample sits on the flash at
0.5 x the reel and the vignette fails (a 0.029 drop against a 0.20 floor, 0.346 when
it steps around it), and a title that never rendered, sampled on a flash, passes.

Synthetic known-answer inputs: a flat 0x808080 field decodes to luma 128, and white to
255, so a flashed frame's centre reads 128 + a x (255 - 128) for each opacity a. Grey
carries no chroma, so the blend's chroma half is proven separately, over saturated
patches.
"""
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, deliver as deliver_mod, mix
from scripts.lib import assembly, ffbin, proc, provenance
from scripts.lib.look import FLASH_ALPHA, FLASH_FRAMES, LookSpec
from scripts.lib.models import MusicSpec, REEL_H264, ReelCheckSpec, ReelReport
from scripts.lib.titles import Title, Titles

pytestmark = pytest.mark.integration

_FPS = 30
_DUR = 4.0
_GREY = 128.0          # 0x808080's decoded luma
_CENTRE = 60           # half-side of the centre patch, px — inside the vignette's plateau
_SR = 22050


def _grey_master(path: Path) -> str:
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c=0x808080:s=360x640:d={_DUR}:r={_FPS}", "-t", f"{_DUR}",
              "-pix_fmt", "yuv420p", str(path)])
    return str(path)


def _gray(path: str) -> np.ndarray:
    """Every frame as an (n, h, w) float luma array — one decode."""
    si = assembly.probe_stream(path)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", path,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    n = si.w * si.h
    return np.frombuffer(raw, np.uint8)[:len(raw) // n * n].reshape(-1, si.h, si.w) \
        .astype(float)


def _centre(frame: np.ndarray) -> float:
    h, w = frame.shape
    return float(frame[h // 2 - _CENTRE:h // 2 + _CENTRE,
                       w // 2 - _CENTRE:w // 2 + _CENTRE].mean())


def test_the_flash_is_in_the_delivery_not_the_master_and_the_look_gate_steps_around_it(
        tmp_path, need_filter):
    need_filter("drawtext")
    master = _grey_master(tmp_path / "master.mp4")
    out_dir, scratch = tmp_path / "out", tmp_path / "scratch"
    rep = check_reel.run(master, [master], ReelCheckSpec(target_dur=_DUR),
                         str(tmp_path / "reel.json"))
    assert rep.overall is True
    tj = tmp_path / "TITLES.json"
    # a title whose own midpoint (2.0) is the second flash: its sample has to move too
    Titles(items=(Title("hook", 1.6, 0.8, pos="top"),)).write(tj)
    look = LookSpec(vignette=0.4, fade=0.5)
    flashes = [1.0, _DUR / 2]                  # the second sits where the vignette is judged
    out = deliver_mod.deliver(master, REEL_H264, str(out_dir), "shutter proof", rep,
                              scratch_dir=str(scratch), titles=str(tj), look=look,
                              flashes=flashes)

    att = json.loads(Path(out).with_suffix(".attest.json").read_text())
    by = {f["check"]: f["status"] for f in att["look_checks"]}
    assert by == {"vignette": "pass", "fade-in": "pass", "fade-out": "pass",
                  "titles:0 hook": "pass"}

    m, d = _gray(master), _gray(out)
    for t in flashes:
        n0 = round(t * _FPS)
        for k, a in enumerate(FLASH_ALPHA):        # one frame per opacity, none spilled
            want = _GREY + a * (255.0 - _GREY)
            assert abs(_centre(d[n0 + k]) - want) < 4.0, (t, k, _centre(d[n0 + k]))
            assert abs(_centre(m[n0 + k]) - _GREY) < 2.0          # the master never flashes
        for n in (n0 - 1, n0 + FLASH_FRAMES):      # a frame either side reads as the master
            assert abs(_centre(d[n]) - _centre(m[n])) < 2.0, (t, n, _centre(d[n]))

    # The control: the same delivered file judged as if there were no flash. The
    # vignette's sample at 0.5 x the reel lands on the white frame, whose corners are as
    # bright as its centre, and the check fails.
    blind = deliver_mod._verify_look(master, out, look, str(tj), "")
    assert {f.check: f.status for f in blind}["vignette"] == "fail"


def _rgb(path: str) -> np.ndarray:
    """Every frame as an (n, h, w, 3) float RGB array — one decode."""
    si = assembly.probe_stream(path)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", path,
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
    n = si.w * si.h * 3
    return np.frombuffer(raw, np.uint8)[:len(raw) // n * n] \
        .reshape(-1, si.h, si.w, 3).astype(float)


def test_the_flash_blends_the_colour_once_not_the_chroma_four_times(tmp_path):
    """Every flashed frame reads a x white + (1 - a) x the picture in all three
    channels. The patches are a red (chroma far off neutral in V) and a blue (in U),
    because grey has no chroma to compound: drawbox, which blends a 4:2:0 chroma sample
    once per luma pixel it covers, landed these same frames 20-65 codes off in one
    channel, and passes the grey proof above all the same (design 2026-10-21 §4).
    Measured through this encode: 3.45 codes at worst, every frame either side 0."""
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    master = str(tmp_path / "colour.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c=0xC82828:s=180x640:d={_DUR}:r={_FPS}[a];"
              f"color=c=0x2828C8:s=180x640:d={_DUR}:r={_FPS}[b];[a][b]hstack",
              "-t", f"{_DUR}", "-pix_fmt", "yuv420p", master])
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))
    out = deliver_mod.deliver(master, REEL_H264, str(tmp_path / "out"), "colour", rep,
                              scratch_dir=str(tmp_path / "scratch"), flashes=[1.0])
    m, d = _rgb(master), _rgb(out)
    n0 = round(1.0 * _FPS)
    for x in (90, 270):                            # the centre of each patch
        def patch(f):
            return f[320 - 40:320 + 40, x - 40:x + 40].reshape(-1, 3).mean(0)
        for k, a in enumerate(FLASH_ALPHA):
            want = a * 255.0 + (1 - a) * patch(m[n0 + k])
            got = patch(d[n0 + k])
            assert np.abs(got - want).max() < 5.0, (x, a, got.round(1), want.round(1))
        for n in (n0 - 1, n0 + FLASH_FRAMES):      # and the frames either side untouched
            assert np.abs(patch(d[n]) - patch(m[n])).max() < 2.0, (x, n)


def _music(path: Path, secs: float) -> MusicSpec:
    """A steady 220 Hz tone: nothing in the click's band, so the click is measurable at
    full music level."""
    n = int(secs * _SR)
    wavfile.write(str(path), _SR,
                  (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / _SR)).astype(np.float32))
    return MusicSpec(track=str(path), start_offset=0.0, duration=secs, tempo=120.0,
                     beats=tuple(k * 0.5 for k in range(int(secs / 0.5))), energy=(0.3,),
                     energy_hz=2.0)


def _high_band(stem: str, tmp_path: Path, name: str) -> tuple[int, np.ndarray]:
    dec = str(tmp_path / f"{name}.wav")
    proc.run([ffbin.ffmpeg(), "-y", "-i", stem, "-ac", "1", "-ar", str(_SR), dec])
    sr, y = wavfile.read(dec)
    return sr, y.astype(np.float64)


def _band_rms(y: np.ndarray, sr: int, t0: float, t1: float, lo=2500.0, hi=9000.0) -> float:
    seg = y[int(t0 * sr):int(t1 * sr)]
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    band = np.abs(np.fft.rfft(seg))[(freqs >= lo) & (freqs < hi)]
    return float(np.sqrt(np.mean(band ** 2)))


def test_the_click_is_a_short_high_burst_on_the_cut(tmp_path):
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    ms = _music(tmp_path / "m.wav", 4.0)
    seg = str(tmp_path / "m.wav")             # ambient off: the segments only size the bed
    segments = [(seg, 1.0), (seg, 2.0)]
    with_click = mix.mix(ms, str(tmp_path / "a"), dur=3.0, segments=segments,
                         ambient=False, shutters=[1.0])
    without = mix.mix(ms, str(tmp_path / "b"), dur=3.0, segments=segments, ambient=False)
    sr, y = _high_band(with_click, tmp_path, "a")
    _, c = _high_band(without, tmp_path, "b")
    at = _band_rms(y, sr, 1.0, 1.1)           # both bursts: 0-15 ms and 70-85 ms past the cut
    assert at > 20 * _band_rms(c, sr, 1.0, 1.1)       # the control has no burst there
    assert at > 20 * _band_rms(y, sr, 1.2, 1.5)       # and it is short: gone by 1.2 s
    assert at > 20 * _band_rms(y, sr, 0.6, 0.9)       # and on the cut, not before it
    assert check_reel._loudnorm_measure(with_click) == pytest.approx(-14.0, abs=1.0)


def test_a_title_sampled_on_a_flash_would_read_as_rendered_when_it_was_not(
        tmp_path, need_filter, monkeypatch):
    """The titles' half of the exclusion. The encode carries NO drawtext while deliver
    still believes it declared one — the bug class the titles gate exists for — and the
    title's midpoint is a flash. The gate that steps around the flash refuses the
    delivery (measured 0.0000% of the band carries ink); judged as if there were no
    flash, the white frame reads as ink and the missing title passes (100%, against
    the 0.02% bar)."""
    need_filter("drawtext")
    master = _grey_master(tmp_path / "master.mp4")
    rep = check_reel.run(master, [master], ReelCheckSpec(target_dur=_DUR),
                         str(tmp_path / "reel.json"))
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("hook", 1.6, 0.8, pos="top"),)).write(tj)
    monkeypatch.setattr(deliver_mod, "build_filterchain", lambda *a, **k: "")
    out_dir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="titles:0 hook"):
        deliver_mod.deliver(master, REEL_H264, str(out_dir), "shutter proof", rep,
                            scratch_dir=str(tmp_path / "scratch"), titles=str(tj),
                            flashes=[2.0])
    out = str(out_dir / "REEL_v1.mp4")          # left on disk by the refused gate
    blind = deliver_mod._verify_look(master, out, None, str(tj), "")
    assert {f.check: f.status for f in blind} == {"titles:0 hook": "pass"}
