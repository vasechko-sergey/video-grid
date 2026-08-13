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
— the highlight_red row re-measured after 1b120dc densified that curve's sub-knee
anchors — on the `sample_clip` session fixture: 3s, 1920x1080, 30fps, a white 140x320 box
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
from scripts.lib.titles import Title, Titles, build_filterchain

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
    """Pixels whose Rec.601 luma sits in [lo, hi].

    Callers take this ONCE, off the UNGRADED frame, and hand the same mask to both
    sides — see _rb_over. Choosing it per-frame would let a grade that moved a pixel
    across a band edge change the population as well as the measurement, so the two
    sides would no longer be comparable. (On this fixture they coincide exactly:
    1196 highlight and 56304 shadow pixels either way, and both routes return the
    same numbers to four decimals. Verified, not assumed — a future fixture with
    pixels near a band edge would not be so kind.)
    """
    y = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
    m = (y >= lo) & (y <= hi)
    assert m.any(), f"no pixels in the [{lo}, {hi}] luma band — wrong fixture?"
    return m


def _rb_over(frame: np.ndarray, mask: np.ndarray) -> float:
    """Mean R−B over `mask`. Neutral reads 0."""
    return float((frame[..., 0][mask] - frame[..., 2][mask]).mean())


def _blue_over(frame: np.ndarray, mask: np.ndarray) -> float:
    """Mean B over `mask` — the channel highlight_red must NOT touch."""
    return float(frame[..., 2][mask].mean())


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


_MUSIC_HZ = 220.0      # the music fundamental
_AMBIENT_HZ = 700.0    # the nat-sound probe tone. NOT a harmonic of _MUSIC_HZ: at the
                       # 880 Hz this started on (exactly 4x), any codec or loudnorm
                       # distortion product of the music lands in the same DFT bin as
                       # the thing being measured. Re-measured at both — 700 Hz gives
                       # a band ratio of 0.4933 faded / 0.9997 un-faded against 880's
                       # 0.4931 / 0.9993, i.e. no worse and the question does not arise.


def _music(path, secs: float) -> MusicSpec:
    """A 220 Hz music track + the MusicSpec mix needs (test_ambient.py's fixture)."""
    _tone(path, secs, _MUSIC_HZ, 0.6)
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

    **This proof discharges only the second half of §9 row 3** ("and so is the
    delivered file"). The first half — "the argv is byte-identical to today's" — is
    pinned by tests/test_deliver.py::test_no_look_argv_is_unchanged, and it has to
    be, because the two halves are not the same claim: an always-emitted IDENTITY
    filter (`chain` returning `["null"]`, say) changes the argv and leaves the
    delivered bytes untouched, so this test stays green under it. Verified by
    running exactly that mutation. What this test does catch is an always-emitted
    filter that touches pixels — `eq=contrast=1.02` reds the reference comparison
    below.
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

    **This is also the ONLY proof that a vignette and a fade ride the same graph
    together** (plan mutation row 6b), which is why the look here is not
    vignette-only. `deliver` builds its filtergraph in TWO branches over the same
    `parts` list — `-vf` without a mask, `-filter_complex` with one — and `parts`
    carries the titles drawtext chain as well as the bookend fade. Dropping `*parts`
    from the -filter_complex branch alone passed the WHOLE suite (2759 tests) while
    silently deleting the fade and every on-screen title for `epic`, `moody` and
    `nostalgic` — three of the four mood presets, all of which ship vignette and
    fade together. The first-frame assertion below is what closes that hole.

    Measured with LookSpec(vignette=0.35, fade=0.5) + a muxed 3s stem: audio
    3.000000s against a 2.966667s picture (delta 0.033 — the picture ends one frame
    short of 3s at 30fps), first frame 0.0000, last frame 3.063, corner/centre
    0.6458 at frame 15 (identical to the vignette-only delivery: t=0.5 is exactly
    where the fade-in finishes, so the two effects do not contaminate each other's
    sample point). The corner-ratio assertion is the audio control's mirror: the
    obvious way to "fix" a mis-mapped audio index is to drop the mask input, which
    would restore the audio and silently take the vignette away with it.

    Frame 15 and not a later one: the fixture's white box slides right and enters
    the 240x240 centre patch at t≈1.49, which drags the corner/centre ratio to
    0.1837 at frame 45 for reasons that have nothing to do with the vignette.
    """
    need_filter("geq")
    need_filter("fade")
    stem = str(tmp_path / "stem.m4a")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              "sine=frequency=440:duration=3", "-c:a", "aac", "-b:a", "128k", stem])
    out = _deliver(tmp_path / "g", sample_clip,
                   look=LookSpec(vignette=0.35, fade=0.5), audio=stem)

    assert _has_audio(out)
    assert abs(_audio_dur(out) - _video_dur(out)) < 0.2, (
        f"audio {_audio_dur(out):.3f}s against video {_video_dur(out):.3f}s")
    frames = _all_gray(out)
    assert frames[0].mean() < 2.0, (
        f"first frame is {frames[0].mean():.3f}, not black — the fade did not reach "
        f"the -filter_complex branch the mask put this delivery on")
    assert frames[-1].mean() < 12.0, (
        f"last frame is {frames[-1].mean():.3f}, not black — only half the bookend "
        f"survived the mask branch")
    ratio = _corner_ratio(frames[_MID_FRAME].astype(float))
    assert ratio < 0.85, (
        f"corner/centre is {ratio:.4f} — the stem got muxed but the vignette did not "
        f"ride the same encode")


def test_the_audio_bookend_falls_with_ambient_on(tmp_path, need_filter):
    """design §9 row 4 + §5. The tail must FALL. Before this slice the duck released
    as the music faded and the ambient rose here.

    Two stems, one faded and one not, over the same 220 Hz music + 700 Hz nat-sound
    (see _AMBIENT_HZ for why 700 and not the 880 this started on).
    Measured (0.1s windows, 60 of them over 6s):

    * faded  last/mid RMS = 0.1155   (assert < 0.35)
    * un-faded last/mid RMS = 1.0001 (assert > 0.9 — the control: the measurement
      is reading the fade, not a stem that always decays)
    * mid faded/un-faded = 1.0457    (assert within 15%: loudnorm re-normalizes the
      faded stem slightly upward, and that is the ONLY thing the fade does to the
      middle)
    * 700 Hz ambient band, last 0.5s ÷ the middle 0.5s: faded 0.4933 (assert < 0.7),
      un-faded 0.9997 (assert > 0.85). 0.4933 is the mean of a linear ramp over that
      window (~0.5), i.e. the ambient fades with everything else.

    That last pair is not decoration, and the number that proves it was measured:
    with mix.py reverted to the pre-slice placement (the fade on the music FRAGMENT,
    before _mix_graph), the ambient band ends at **1.8139** of its mid level — the
    sidechain key falls with the music, the compressor releases, and the nat-sound
    swells 81% as the picture goes black. Under that same mutation the BROADBAND
    assertions above still pass, because the music dominates the sum and the music
    really did fade. So the broadband tail check alone cannot see design §5's defect;
    only the band-isolated one can.
    """
    for f in ("sidechaincompress", "loudnorm", "afade", "amix"):
        need_filter(f)
    music = _music(tmp_path / "m.wav", 6.0)
    seg = _tone(tmp_path / "seg.wav", 6.0, _AMBIENT_HZ, 0.5)
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
    amb_f = (_band_rms(yf, sr, _AMBIENT_HZ, 5.5, 6.0)
             / _band_rms(yf, sr, _AMBIENT_HZ, 2.75, 3.25))
    amb_p = (_band_rms(yp, sr, _AMBIENT_HZ, 5.5, 6.0)
             / _band_rms(yp, sr, _AMBIENT_HZ, 2.75, 3.25))
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
    reel's look), frame 15 of a 320x180 delivery, both sides over the SAME pixel
    set — the one the ungraded frame's own luma selects (see _band_mask):

    | band | pixels | R−B at 0.0 | R−B at 0.3 | assertion |
    |---|---|---|---|---|
    | 200..255 (the white box) | 1196 | 0.0000 | **−72.6756** | falls by > 30 |
    | 0..80 (the 0x303030 field) | 56304 | 0.0000 | **−0.0460** | moves by < 1.0 |

    and B over the highlight band moves 252.301 → 251.987 (Δ 0.314, assert < 1.5):
    only the RED channel was pulled, so the shoulder did not simply go dim.

    **The sub-knee threshold is 1.0 for a reason, and it is not the measurement.**
    At 0.046 measured, anything from 0.1 up would pass today. 1.0 is where the
    curve's own worst case sits: `color.highlight_red_arg` densified its sub-knee
    anchors in 1b120dc, and a lossless 256-step ramp probe (reframe.verify_tone's
    method) now shows at most ±1 code of residual spline curvature below the knee
    at pull=0.3 (±2 at the HIGHLIGHT_RED_MAX ceiling) — a full code landing on this
    field's own 48 would read ~1.0 here. Under the pre-fix sparse anchors the same
    measurement read **2.054** (the probe showed −3 codes at input 48 and +7 at
    128), so this threshold reds if that regression ever returns — verified by
    restoring the sparse anchors and watching it fail. A global red cut, the gross
    failure the control is nominally for, would move this band by ~14.
    """
    need_filter("curves")
    plain = _reframe_graded(tmp_path / "h", sample_clip, highlight_red=0.0)
    pulled = _reframe_graded(tmp_path / "i", sample_clip, highlight_red=0.3)
    fp, fq = _rgb(plain, _MID_FRAME), _rgb(pulled, _MID_FRAME)
    high, shadow = _band_mask(fp, 200, 255), _band_mask(fp, 0, 80)

    assert _rb_over(fq, high) < _rb_over(fp, high) - 30.0, (
        f"R−B in the highlight band is {_rb_over(fq, high):.3f} against "
        f"{_rb_over(fp, high):.3f} — the red shoulder was not pulled")
    shadow_delta = abs(_rb_over(fq, shadow) - _rb_over(fp, shadow))
    assert shadow_delta < 1.0, (
        f"R−B below the knee moved by {shadow_delta:.3f} — the pull is reaching past "
        f"the shoulder (see this test's docstring: the sub-knee anchors have gone "
        f"sparse again, or the knee moved)")
    blue_delta = abs(_blue_over(fq, high) - _blue_over(fp, high))
    assert blue_delta < 1.5, (
        f"B in the highlight band moved by {blue_delta:.3f} — the highlights were "
        f"dimmed, not de-redded")


# --- outline-bold: design §9 row 6 (I-4) -------------------------------------

def _style_frame(tmp_path, style: str, text: str = "HOOK BACK") -> np.ndarray:
    """One rendered frame (h, w) luma array: `text` centred in `style`, on a flat
    mid-grey 1920x1080 field — the SAME drawtext chain `deliver` burns in, run
    directly through `build_filterchain` rather than `deliver()`: a single-frame ink
    measurement needs no bound ReelReport/master, only the real filtergraph."""
    w, h = 1920, 1080
    work = tmp_path / style
    work.mkdir()
    titles = Titles(items=(Title(text, 0.0, 1.0, pos="center", style=style),))
    chain = build_filterchain(titles, str(work))
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-f", "lavfi",
                    "-i", f"color=c=gray:s={w}x{h}:d=1",
                    "-vf", chain, "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    assert len(raw) >= w * h, f"{style}: decoded no full frame ({len(raw)} bytes)"
    return np.frombuffer(raw, dtype=np.uint8)[:w * h].reshape(h, w).astype(float)


def _ink_extent(frame: np.ndarray, tol: float = 15.0) -> tuple[int, int, int]:
    """(bbox width, bbox height, ink pixel count) of pixels differing from the flat
    background by more than `tol`. The background dominates a title frame's pixel
    count (text is a small fraction of 1920x1080), so its own median IS the
    background reading — no hardcoded "gray is 128" assumption about how `color=`
    or the raw pixel format quantizes it."""
    bg = float(np.median(frame))
    ink = np.abs(frame - bg) > tol
    rows, cols = np.any(ink, axis=1), np.any(ink, axis=0)
    assert rows.any() and cols.any(), "no ink rendered at all — drawtext did not fire"
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return int(c1 - c0 + 1), int(r1 - r0 + 1), int(ink.sum())


def test_outline_bold_draws_a_heavier_glyph_than_outline(tmp_path, need_filter):
    """design §9 row 6. "the rendered glyph's ink extent is wider than the same title
    in `outline`" — a REAL pixel measurement, not the argv string test the plan's
    Task 8 shipped instead (I-4: dropped at plan time, in the slice whose whole
    premise is that string tests are how an invisible vignette got through).

    `outline-bold` (borderw=7 + an offset shadowx=3:shadowy=3) against plain
    `outline` (borderw=4, no shadow) — same text, size and position, on a flat
    mid-grey field so "ink" is simply whatever differs from the background.

    Measured on this text/font/machine (re-measure rather than trusting these —
    ffmpeg/font version can move them): outline 360x54 (12540 ink px), outline-bold
    369x63 (18871 ink px) — +9px wider, +9px taller, 1.51x the ink, consistent with
    a heavier border plus an offset shadow that outline alone does not draw.
    """
    need_filter("drawtext")
    plain = _style_frame(tmp_path, "outline")
    bold = _style_frame(tmp_path, "outline-bold")
    pw, ph, pn = _ink_extent(plain)
    bw, bh, bn = _ink_extent(bold)

    assert bw > pw, (
        f"outline-bold's ink extent is {bw}px wide, not wider than outline's {pw}px — "
        f"the heavier border/shadow did not reach the rendered pixels")
    assert bh > ph, (
        f"outline-bold's ink extent is {bh}px tall, not taller than outline's {ph}px")
    assert bn > pn * 1.1, (
        f"outline-bold's ink count is {bn}px against outline's {pn}px — not enough "
        f"more ink for a heavier border plus an offset shadow (only a wider bbox "
        f"with the same fill would still pass the width/height checks above)")
