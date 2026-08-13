"""Real-ffmpeg visibility proofs for the cinematic look (design 2026-08-13 §9).

Backlog #18 is not "add the effect". It is that a vignette added live to the engine
came out INVISIBLE — the strength or the chain order ate it — and no test noticed,
because the tests that existed measured the argv. So every proof in this file
decodes the pixels (or the samples) ffmpeg actually produced.

Each proof also measures a CONTROL that must not move. Without one, "the corners are
darker" cannot be told from "the whole frame is darker", which is exactly the failure
mode ffmpeg's own `vignette` filter has on a tall canvas (design §2.1) and exactly
what a strength-eaten effect looks like from the argv.

Every threshold below carries the number it was set against, measured on
2026-08-13 with the ffmpeg config/ffmpeg.env resolves (8.1.1, homebrew ffmpeg-full)
on the `sample_clip` session fixture: 3s, 1920x1080, 30fps, a white 140x320 box
sliding over a flat 0x303030 field. The field decodes to luma 48 and the box to 255,
so a flat-field measurement here is exact rather than approximate — several of the
"did not move" numbers below are 0.000 for that reason, and would be small but
non-zero on textured footage (design §2.2 measured 0.144 for the centre plateau).
"""
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, deliver as deliver_mod, mix, reframe
from scripts.lib import assembly, color, ffbin, proc
from scripts.lib.look import LookSpec
from scripts.lib.models import (Delivery, LayoutSpec, MusicSpec, REEL_H264,
                                ReelCheckSpec, ReframeSpec)

pytestmark = pytest.mark.integration

_MID_FRAME = 15        # t=0.5s on the 30fps fixture — inside the reel, clear of both fades
_CORNER_PATCH = 30     # corner square side, px: the falloff's deepest region
_CENTRE_PATCH = 240    # centre square side, px — design §2.2's own "centre 240x240"
_SR = 22050            # probe sample rate for the audio measurements (test_ambient.py's)


# --- delivery scaffolding ---------------------------------------------------

def _report(master: str, out_dir: Path):
    """A real passing ReelReport, bound by digest to THIS master.

    check_reel.run is the only producer deliver accepts (it refuses an unstamped or
    mismatched master_digest), and it is 0.18s on this fixture — cheap enough to run
    per delivery rather than fake. Same shape as
    tests/integration/test_reel_backhalf.py, with the master standing in as its own
    single episode: one episode makes color_across_cuts/variety "n/a" rather than
    failing, and target_dur comes from the master's own probe because nothing here
    is testing the length gate.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = ReelCheckSpec(target_dur=check_reel._probe_dur(master))
    rep = check_reel.run(master, [master], spec, str(out_dir / "reel.json"))
    assert rep.overall is True, rep.fail_reasons
    return rep


def _deliver(out_dir, master, *, look=None, audio=None) -> str:
    """Deliver `master` into a fresh out_dir → the REEL_v1.mp4 path."""
    out_dir = Path(out_dir)
    rep = _report(str(master), out_dir)
    return deliver_mod.deliver(str(master), REEL_H264, str(out_dir), "look proof", rep,
                               look=look, audio=audio)


# --- pixel measurement ------------------------------------------------------

def _all_gray(path) -> np.ndarray:
    """Every frame of `path` as an (n, h, w) uint8 luma array — ONE decode.

    rawvideo/gray out of a pipe, the way tests/integration/test_ramp.py's
    _diff_curve reads frames, but through proc.run (which lints the argv) and
    reshaped for numpy rather than differenced by hand.
    """
    si = assembly.probe_stream(str(path))
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    n = si.w * si.h
    assert len(raw) >= n, f"{path} decoded no full frame ({len(raw)} bytes)"
    return np.frombuffer(raw, dtype=np.uint8)[:len(raw) // n * n].reshape(-1, si.h, si.w)


def _gray(path, idx: int) -> np.ndarray:
    """Frame `idx` of `path` as a float luma array."""
    return _all_gray(path)[idx].astype(float)


def _centre(frame: np.ndarray) -> np.ndarray:
    """The centre _CENTRE_PATCH square — the vignette's untouched plateau."""
    h, w = frame.shape
    s = _CENTRE_PATCH // 2
    return frame[h // 2 - s:h // 2 + s, w // 2 - s:w // 2 + s].astype(float)


def _corner_ratio(frame: np.ndarray) -> float:
    """mean luma of the four corner patches ÷ mean luma of the centre patch.

    A RATIO and not a difference, so it cannot be satisfied by dimming everything:
    a whole-frame dimmer leaves it where it was, which is the discrimination
    design §2.1 needs (ffmpeg's built-in filter dims the sky as hard as the corner).
    """
    k = _CORNER_PATCH
    corners = (frame[:k, :k], frame[:k, -k:], frame[-k:, :k], frame[-k:, -k:])
    return float(np.mean([c.mean() for c in corners]) / _centre(frame).mean())


def _rgb(path, idx: int) -> np.ndarray:
    """Frame `idx` of `path` as a float (h, w, 3) RGB array."""
    si = assembly.probe_stream(str(path))
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path),
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
    n = si.w * si.h * 3
    assert len(raw) >= (idx + 1) * n, f"{path} has no frame {idx}"
    return np.frombuffer(raw, dtype=np.uint8)[idx * n:(idx + 1) * n] \
        .reshape(si.h, si.w, 3).astype(float)


def _band_mask(frame: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Pixels whose own Rec.601 luma sits in [lo, hi]."""
    y = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
    m = (y >= lo) & (y <= hi)
    assert m.any(), f"no pixels in the [{lo}, {hi}] luma band — wrong fixture?"
    return m


def _rb_in_band(path, lo: float, hi: float, idx: int = _MID_FRAME) -> float:
    """Mean R−B over the pixels whose luma is in [lo, hi]. Neutral reads 0."""
    f = _rgb(path, idx)
    m = _band_mask(f, lo, hi)
    return float((f[..., 0][m] - f[..., 2][m]).mean())


def _blue_in_band(path, lo: float, hi: float, idx: int = _MID_FRAME) -> float:
    """Mean B over the same band — the channel highlight_red must NOT touch."""
    f = _rgb(path, idx)
    m = _band_mask(f, lo, hi)
    return float(f[..., 2][m].mean())


# --- stream probes ----------------------------------------------------------

def _probe(path, stream: str, entry: str) -> str:
    return proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", stream,
                     "-show_entries", entry, "-of", "csv=p=0", str(path)]
                    ).stdout.decode().strip()


def _has_audio(path) -> bool:
    return bool(_probe(path, "a", "stream=codec_name"))


def _audio_dur(path) -> float:
    return float(_probe(path, "a", "stream=duration"))


def _video_dur(path) -> float:
    return float(_probe(path, "v", "stream=duration"))


# --- audio measurement ------------------------------------------------------

def _samples(stem) -> tuple[int, np.ndarray]:
    """Decode an aac stem to mono float samples (scipy, as test_ambient.py does)."""
    dec = str(Path(stem).with_suffix(".probe.wav"))
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(stem), "-ac", "1", "-ar", str(_SR), dec])
    sr, y = wavfile.read(dec)
    return sr, y.astype(np.float64)


def _rms_windows(stem, win: float) -> list[float]:
    """RMS of the stem in consecutive `win`-second windows."""
    sr, y = _samples(stem)
    n = int(win * sr)
    return [float(np.sqrt(np.mean(y[i * n:(i + 1) * n] ** 2))) for i in range(len(y) // n)]


def _band_rms(y: np.ndarray, sr: int, freq: float, t0: float, t1: float) -> float:
    """RMS magnitude at `freq` over [t0, t1) — a single-bin DFT, test_ambient.py's
    trick, which isolates the AMBIENT tone from the music sitting on top of it."""
    seg = y[int(t0 * sr):int(t1 * sr)]
    k = np.exp(-2j * np.pi * freq * np.arange(len(seg)) / sr)
    return float(abs(np.dot(seg, k)) / len(seg))


def _tone(path, secs: float, freq: float, amp: float) -> str:
    t = np.arange(int(secs * _SR)) / _SR
    wavfile.write(path, _SR, (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32))
    return str(path)


def _music(path, secs: float) -> MusicSpec:
    """A 220 Hz music track + the MusicSpec mix needs (test_ambient.py's fixture)."""
    _tone(path, secs, 220.0, 0.6)
    return MusicSpec(track=str(path), start_offset=0.0, duration=float(secs),
                     tempo=120.0,
                     beats=tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5))),
                     energy=(0.3,), energy_hz=2.0)


# --- the grade path (highlight_red rides reframe, not the look) -------------

def _reframe_graded(out_dir, src, highlight_red: float) -> str:
    """One reframe pass over `src` at the given highlight_red, everything else at
    identity: canvas 16:9 against a 16:9 source (full-frame crop, zero freedom),
    color_means at color.TARGET so gains_for_means returns 1.0 on every channel and
    the mixer is an identity, delivery long_edge 320 to keep the encode small.
    Whatever moves between two of these came from highlight_red alone."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    route = out_dir / "route.json"
    route.write_text(json.dumps([{"t": i / 10, "x": 960.0, "y": 540.0,
                                  "w": 140.0, "h": 320.0} for i in range(30)]))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(16, 9),
                       color_means=color.TARGET, delivery=Delivery("long_edge", 320),
                       layout=LayoutSpec(mode="fill"), highlight_red=highlight_red)
    out = str(out_dir / "graded.mp4")
    reframe.reframe(spec, str(src), str(route), out, str(out_dir / "path.json"))
    return out


# --- the six proofs ---------------------------------------------------------

def test_the_vignette_darkens_the_corners_and_leaves_the_centre_alone(
        tmp_path, sample_clip, need_filter):
    """design §9 row 1. The corner/centre ratio must FALL, and the plateau must not
    move — a vignette that dims the whole frame is the built-in filter's failure
    (§2.1), not this one's.

    Measured: corner/centre 1.0000 with no look → 0.6042 at vignette=0.4 (the flat
    field makes the plain ratio exactly 1), and the centre 240x240 mean |ΔY| is
    0.000 with a max of 0.0 — the plateau is byte-identical, not merely close.
    Thresholds sit at a 0.15 fall (measured 0.396) and 0.5 luma (measured 0.000):
    a whole-frame dimmer at this strength would move the centre by ~19 luma and
    leave the ratio at 1.0, so both assertions still discriminate with margin.
    """
    need_filter("geq")
    need_filter("overlay")
    plain = _deliver(tmp_path / "a", sample_clip, look=None)
    vig = _deliver(tmp_path / "b", sample_clip, look=LookSpec(vignette=0.4))
    fp, fv = _gray(plain, _MID_FRAME), _gray(vig, _MID_FRAME)

    assert _corner_ratio(fv) < _corner_ratio(fp) - 0.15, (
        f"corner/centre {_corner_ratio(fv):.4f} against {_corner_ratio(fp):.4f} "
        f"with no look — the corners did not darken relative to the centre")
    centre_delta = np.abs(_centre(fv) - _centre(fp)).mean()
    assert centre_delta < 0.5, f"the plateau moved by {centre_delta:.3f} luma"


def test_the_bookend_fade_blacks_both_ends_and_not_the_middle(
        tmp_path, sample_clip, need_filter):
    """design §9 row 2. Both ends near zero, the middle untouched. §11.5: the last
    frame lands near 0, not at 0 — it is quantized to the frame grid.

    Measured: first frame 0.0000, last 3.303 (the last frame sits at t=2.9667 with
    the fade-out ending at 3.0, so 6.7% of the fade is left — §11.5's residue, not
    an unfinished fade), mid frame 52.4717 against an un-faded 52.4717, delta
    exactly 0.0. The un-faded control reads 52.472 at BOTH ends, so the two
    end-assertions are the difference between a fade and no fade, not a restatement
    of what the clip already looked like.
    """
    need_filter("fade")
    out = _deliver(tmp_path / "c", sample_clip, look=LookSpec(fade=0.5))
    plain = _deliver(tmp_path / "d", sample_clip, look=None)
    frames, unfaded = _all_gray(out), _all_gray(plain)
    mid = len(frames) // 2

    assert frames[0].mean() < 2.0, f"first frame is {frames[0].mean():.3f}, not black"
    assert frames[-1].mean() < 12.0, f"last frame is {frames[-1].mean():.3f}, not black"
    assert abs(frames[mid].mean() - unfaded[mid].mean()) < 1.0, (
        f"the middle moved: {frames[mid].mean():.3f} against {unfaded[mid].mean():.3f}")
    # The control: with no look the SAME two frames are full brightness. A reel that
    # merely rendered dark at both ends (a bad encode, a truncated master) would fail
    # here, and so would a fade measured on a fixture that was already black.
    assert unfaded[0].mean() > 40.0 and unfaded[-1].mean() > 40.0, (
        f"un-faded ends read {unfaded[0].mean():.3f}/{unfaded[-1].mean():.3f} — the "
        f"fixture is already dark, so the assertions above prove nothing")


def test_no_look_delivers_a_byte_identical_file(tmp_path, sample_clip, need_filter):
    """design §9 row 3. The off path must not have moved at all.

    Three files, because comparing the two OFF spellings to each other is a
    tautology on its own: a look that silently rendered at strength 0 would move
    both of them identically and still pass. So both are also compared to a
    REFERENCE encode built with the pre-look argv (`-i master` + the profile's
    args, no filter slot at all), and a fade-only look — the cheapest look that
    does reach the filter slot — is asserted to differ from it.

    Measured: all three identical at 16540 bytes; the fade-only delivery differs.
    """
    need_filter("fade")
    a = _deliver(tmp_path / "e", sample_clip, look=None)
    b = _deliver(tmp_path / "f", sample_clip, look=LookSpec())
    ref = str(tmp_path / "ref.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(sample_clip), *REEL_H264.args(), ref])

    assert Path(a).read_bytes() == Path(b).read_bytes()
    assert Path(a).read_bytes() == Path(ref).read_bytes(), (
        "a look-less delivery is no longer byte-identical to the plain encode — "
        "something is now emitted into the filter slot even with no look")
    lit = _deliver(tmp_path / "f2", sample_clip, look=LookSpec(fade=0.5))
    assert Path(lit).read_bytes() != Path(ref).read_bytes(), (
        "a fade-only look delivered the same bytes as no look at all — the byte "
        "comparison above cannot tell the two apart, so it proves nothing")


def test_a_vignette_and_a_muxed_stem_pick_the_right_audio_input(
        tmp_path, sample_clip, need_filter):
    """The mask is input 1 and the stem is input 2 — mapping 1:a:0 there would look
    for audio inside a PNG. Proven by probing the delivered file for an audio stream
    of the right duration, not by reading the argv.

    Measured: audio 3.000000s against a 2.966667s picture (delta 0.033 — the picture
    ends one frame short of 3s at 30fps), and the corner/centre ratio is 0.6458 at
    vignette=0.35. That second assertion is the control: the obvious way to "fix" a
    mis-mapped audio index is to drop the mask input, which would restore the audio
    and silently take the vignette away with it.
    """
    need_filter("geq")
    stem = str(tmp_path / "stem.m4a")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              "sine=frequency=440:duration=3", "-c:a", "aac", "-b:a", "128k", stem])
    out = _deliver(tmp_path / "g", sample_clip, look=LookSpec(vignette=0.35), audio=stem)

    assert _has_audio(out)
    assert abs(_audio_dur(out) - _video_dur(out)) < 0.2, (
        f"audio {_audio_dur(out):.3f}s against video {_video_dur(out):.3f}s")
    ratio = _corner_ratio(_gray(out, _MID_FRAME))
    assert ratio < 0.85, (
        f"corner/centre is {ratio:.4f} — the stem got muxed but the vignette did not "
        f"ride the same encode")


def test_the_audio_bookend_falls_with_ambient_on(tmp_path, need_filter):
    """design §9 row 4 + §5. The tail must FALL. Before this slice the duck released
    as the music faded and the ambient rose here.

    Two stems, one faded and one not, over the same 220 Hz music + 880 Hz nat-sound.
    Measured (0.1s windows, 60 of them over 6s):

    * faded  last/mid RMS = 0.1155   (assert < 0.35)
    * un-faded last/mid RMS = 1.0000 (assert > 0.9 — the control: the measurement
      is reading the fade, not a stem that always decays)
    * mid faded/un-faded = 1.0457    (assert within 15%: loudnorm re-normalizes the
      faded stem slightly upward, and that is the ONLY thing the fade does to the
      middle)
    * 880 Hz ambient band, last 0.5s ÷ the middle 0.5s: faded 0.4931 (assert < 0.7),
      un-faded 1.0006 (assert > 0.85). 0.4931 is the mean of a linear ramp over that
      window (~0.5), i.e. the ambient fades with everything else.

    That last pair is not decoration, and the number that proves it was measured:
    with mix.py reverted to the pre-slice placement (the fade on the music FRAGMENT,
    before _mix_graph), the ambient band ends at **1.8088** of its mid level — the
    sidechain key falls with the music, the compressor releases, and the nat-sound
    swells 81% as the picture goes black. Under that same mutation the BROADBAND
    assertions above still pass, because the music dominates the sum and the music
    really did fade. So the broadband tail check alone cannot see design §5's defect;
    only the band-isolated one can.
    """
    for f in ("sidechaincompress", "loudnorm", "afade", "amix"):
        need_filter(f)
    music = _music(tmp_path / "m.wav", 6.0)
    seg = _tone(tmp_path / "seg.wav", 6.0, 880.0, 0.5)
    segments = [(seg, 3.0), (seg, 3.0)]
    faded = mix.mix(music, str(tmp_path / "faded"), 6.0, segments=segments,
                    ambient=True, fade=0.5)
    plain = mix.mix(music, str(tmp_path / "plain"), 6.0, segments=segments,
                    ambient=True, fade=0.0)
    rf, rp = _rms_windows(faded, 0.1), _rms_windows(plain, 0.1)
    mid = len(rf) // 2

    assert rf[-1] < rf[mid] * 0.35, (
        f"the faded stem's tail is {rf[-1] / rf[mid]:.4f} of its middle — it is not "
        f"fading out")
    assert rp[-1] > rp[mid] * 0.9, (
        f"the UN-faded stem's tail is {rp[-1] / rp[mid]:.4f} of its middle — this "
        f"stem decays on its own, so the assertion above is not measuring the fade")
    assert rf[mid] == pytest.approx(rp[mid], rel=0.15), (
        f"the middle moved: {rf[mid]:.1f} against {rp[mid]:.1f}")

    sr, yf = _samples(faded)
    _, yp = _samples(plain)
    amb_f = _band_rms(yf, sr, 880.0, 5.5, 6.0) / _band_rms(yf, sr, 880.0, 2.75, 3.25)
    amb_p = _band_rms(yp, sr, 880.0, 5.5, 6.0) / _band_rms(yp, sr, 880.0, 2.75, 3.25)
    assert amb_f < 0.7, (
        f"the ambient band holds {amb_f:.4f} of its mid level through the fade — the "
        f"duck released and the nat-sound is swelling into the black (design §5)")
    assert amb_p > 0.85, (
        f"the un-faded ambient band is already at {amb_p:.4f} of its mid level, so "
        f"the assertion above is not reading the bookend")


def test_highlight_red_pulls_the_highlights_and_leaves_the_shadows(
        tmp_path, sample_clip, need_filter):
    """design §9 row 5. R−B must fall where the pull acts and hold where it does not.

    Measured on the reframe grade (highlight_red is per-episode colour, not the
    reel's look), frame 15 of a 320x180 delivery:

    | band (own luma) | R−B at 0.0 | R−B at 0.3 |
    |---|---|---|
    | 200..255 (the white box) | 0.000 | −71.122 |
    | 0..80 (the 0x303030 field) | 0.000 | **−2.054** |

    and B over the highlight band moves 252.30 → 251.46, i.e. only the RED channel
    was pulled. The shoulder assertion is set at a 30-unit fall against a measured
    71.1; the highlight-B control at 3 against a measured 0.84.

    **The shadow figure is a finding, not a rounding error.** color.highlight_red_arg's
    docstring says anchors below the knee are "pinned to identity so ffmpeg's spline
    cannot sag the mids"; they pin the spline AT 0.0/0.3/0.6 and not BETWEEN them.
    Probed losslessly through a 256-step ramp (reframe.verify_tone's method), the
    r-curve for pull=0.3 deviates from identity across the whole sub-knee range:
    −3 codes at input 48, −2 at 64, +4 at 100 and **+7 at 128**, returning to 0 only
    at the 153 knee anchor. The −2.054 above is that −3 at the field's own 48,
    softened by the yuv round trip. So the threshold is 3.5 (measured 2.054) rather
    than the ~0 the design predicts, and it still discriminates the failure it is
    for: a global red cut at this strength would move the shadow band by ~14.
    """
    need_filter("curves")
    plain = _reframe_graded(tmp_path / "h", sample_clip, highlight_red=0.0)
    pulled = _reframe_graded(tmp_path / "i", sample_clip, highlight_red=0.3)

    assert _rb_in_band(pulled, 200, 255) < _rb_in_band(plain, 200, 255) - 30.0, (
        f"R−B in the highlight band is {_rb_in_band(pulled, 200, 255):.3f} against "
        f"{_rb_in_band(plain, 200, 255):.3f} — the red shoulder was not pulled")
    shadow_delta = abs(_rb_in_band(pulled, 0, 80) - _rb_in_band(plain, 0, 80))
    assert shadow_delta < 3.5, (
        f"R−B below the knee moved by {shadow_delta:.3f} — the pull is reaching past "
        f"the shoulder (see this test's docstring for the measured sub-knee sag)")
    blue_delta = abs(_blue_in_band(pulled, 200, 255) - _blue_in_band(plain, 200, 255))
    assert blue_delta < 3.0, (
        f"B in the highlight band moved by {blue_delta:.3f} — the highlights were "
        f"dimmed, not de-redded")
