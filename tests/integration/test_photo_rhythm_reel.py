"""One reel, on real ffmpeg, of the whole slice (design 2026-10-21 §6): a video window, a
freeze of its last frame, a photo and a second video window, cut to music — and a control
reel built the same way with the shutter off everywhere.

The cut is the conveyor's own: edit_plan.build_edl projects a selection, pacing fits it
onto a synthetic 120 BPM MUSIC.json, build_edl binds the fit, and the reel goes down the
router's road — build_geometry, render_from_geometry, the episode-QC gate, assemble_reel.
Stubbed is only what the other integration tests stub: the person detector (one person
standing still at the frame's centre, so the crop a freeze is framed over is the one its
window ended on) and the weights. The episode-QC judges are agents; their approving
verdicts are written as the gate reads them, bound to the clips' own digests.

The freeze cannot sit after the photo: a freeze holds the previous episode's last frame,
and a photo has no frame of its own to hold (EDL refuses it). So the order is window,
freeze, photo, window — a run of two holds, the first cut inside the run on a beat and
the second, the cut back to footage, on the level's line.

Why the held lengths come out as they do (the energy table below, one value per beat):
the freeze opens at 2.0 s on a bar reading 0.7 of the track's range (peak: one beat);
the photo opens at 2.5 s on a bar reading 0.45 (build: planned two beats) and, as the
run's last hold, ends on the bar line at 4.0 — three beats. Neither is HOLD_DEFAULT's
2.0 s, which is what every photo held before this slice.

The clip runs at 24 fps — not extract's 30/1 default — so "every episode on the video's
clock" cannot pass by accident; at 120 BPM one beat is exactly 12 of its frames. Every
test runs twice, on two clips (`_CLIPS`): full range with a BT.709 description, as camera
footage arrives (test_freeze's clip), and one that describes no colour at all. The master
splices the episodes by `-c copy`, so the photo's segment takes the video's description
the way it takes the video's clock (design §7): the first version stamped every photo
BT.709, and beside the undescribed clip this same reel was refused."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from scipy.io import wavfile

from scripts import edit_plan, edl_to_reel, extract, pacing as pacing_driver, track
from scripts.lib import assembly, ffbin, hold, proc, provenance
from scripts.lib.edl import EDL, write_edl
from scripts.lib.episode_qc import EpisodeVerdict, ReelQC
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.look import FLASH_ALPHA, FLASH_FRAMES
from scripts.lib.models import ReelManifest

pytestmark = pytest.mark.integration

_FPS = 24
_BEAT = 0.5                    # s, 120 BPM
_SR = 22050
_W, _H = 640, 360              # the clip; a 9:16 crop of it is 202 x 360
_PHOTO = (600, 800)
# Per-beat energy (energy_hz 2.0 = one value per beat). Already min-max normalized, so
# the planner reads these numbers as they are: beats 4-7 (the freeze's bar) average 0.7,
# beats 5-8 (the photo's) 0.45.
_ENERGY = (0.5,) * 4 + (1.0, 0.6, 0.6, 0.6, 0.0) + (0.5,) * 7
_MUSIC_S = 8.0
# The clip's colour, as its encoder writes it. "undescribed" is the reel the first version
# refused: its master changed description at the photo, ffmpeg re-initialized its filter
# graph there, and grade_faithful read the wrong frames (residuals 0/34/76/16 against 4.0).
_CLIPS = {
    "described": ["-pix_fmt", "yuvj420p", "-color_range", "pc", "-color_primaries", "bt709",
                  "-color_trc", "bt709", "-colorspace", "bt709"],
    "undescribed": ["-pix_fmt", "yuv420p"],
}
_TAGS = ("color_space", "color_primaries", "color_transfer", "color_range")


class _Box:
    """An ultralytics box: centre-format xywh, a track id, class 0 (person)."""
    def __init__(self, xywh, tid):
        self.xywh, self.id, self.cls = [xywh], [tid], [0]


class _Res:
    def __init__(self, boxes):
        self.boxes, self.orig_img, self.masks = boxes, None, None


def _detections(src, **_):
    """The person detector: one person in every frame of the segment, standing still at
    its centre. Real build_route picks them, writes the route and its sidecar."""
    si = assembly.probe_stream(src)
    box = [si.w / 2, si.h / 2, si.w / 12, si.h / 3]
    return iter(enumerate(_Res([_Box(box, 1)]) for _ in range(assembly.count_frames(src))))


def _footage() -> Footage:
    """The pool, as intake would describe it: two windows of one clip and one photo."""
    def win(start, dur, shot):
        return FootageWindow(start=start, dur=dur, shot_type=shot, people=1, motion=0.3,
                             shake=0.0, description=shot, score=0.8, best=True,
                             subject_w=0.08, subject_h=0.33, present=1.0)
    return Footage(clips=[
        FootageClip(source="clip.mp4", dur=8.0, res=(_W, _H), fps=float(_FPS),
                    windows=[win(0.0, 2.0, "wide"), win(4.0, 2.0, "wide")]),
        FootageClip(source="IMG_P.png", dur=hold.HOLD_ROOM, res=_PHOTO, fps=0.0,
                    windows=[win(0.0, hold.HOLD_DEFAULT, "medium")], kind="photo")])


def _selection(shutter: bool) -> dict:
    editorial = {"composition": "center", "grid": "thirds"}
    return {"episodes": [
        {"source": "clip.mp4", "window": 0, **editorial},
        {"freeze": True, "shutter": shutter},
        {"source": "IMG_P.png", "window": 0, "shutter": shutter, **editorial},
        {"source": "clip.mp4", "window": 1, **editorial}]}


def _reel(base: Path, root: Path, music: Path, shutter: bool) -> dict:
    """selection -> EDL -> PACING -> bound EDL -> the router's road -> a delivery."""
    base.mkdir()
    footage = _footage()
    fj = base / "FOOTAGE.json"
    fj.write_text(json.dumps(footage.to_dict()))
    edl_path = base / "EDL.json"
    write_edl(edit_plan.build_edl(footage, _selection(shutter), aspect=(9, 16)), edl_path)
    spine = pacing_driver.build_pacing(str(edl_path), str(fj), [str(music)],
                                       str(base))["spine"]
    write_edl(edit_plan.build_edl(footage, _selection(shutter), pacing=spine,
                                  aspect=(9, 16)), edl_path)
    project = base / "project.json"
    project.write_text(json.dumps({"canvas": [9, 16], "delivery": "short_edge:360",
                                   "purpose": "reel", "quality": "preview"}))
    reel = base / "reels" / "main"
    work, out = str(reel / "build"), str(reel / "episodes")
    geo, stop = edl_to_reel.build_geometry(str(edl_path), str(project), str(root), work, out)
    assert stop is None, stop
    rm, stop = edl_to_reel.render_from_geometry(str(Path(out) / "GEOMETRY.json"),
                                                str(project), work, out, music=str(music))
    assert stop is None, stop
    episodes = edl_to_reel._episodes_ready(rm, out)["episodes"]
    ReelQC(episodes=tuple(
        EpisodeVerdict(idx=i, clip=ep.clip, clip_digest=provenance.digest_file(ep.clip),
                       summary="approved", reviewer="integration")
        for i, ep in enumerate(rm.episodes))).write(Path(out) / "EPISODE_QC.json")
    res = edl_to_reel.assemble_reel(episodes, work)
    return {"res": res, "edl": EDL.from_json(edl_path), "spine": spine,
            "rm": ReelManifest.from_json(episodes),
            "master": str(Path(work) / "reel" / "master.mp4")}


@pytest.fixture(scope="module", params=sorted(_CLIPS))
def reels(request, tmp_path_factory):
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    tmp = tmp_path_factory.mktemp(f"photo_rhythm_{request.param}")
    root = tmp / "footage"
    root.mkdir()
    proc.run([binary, "-y", "-v", "error", "-f", "lavfi",
              "-i", f"testsrc2=s={_W}x{_H}:r={_FPS}:d=8", "-c:v", "libx264",
              *_CLIPS[request.param], str(root / "clip.mp4")])
    im = Image.new("RGB", _PHOTO, (230, 120, 40))
    im.paste(Image.new("RGB", (_PHOTO[0] // 8, _PHOTO[1] // 3), (20, 20, 30)),
             (int(_PHOTO[0] * 0.6), _PHOTO[1] // 3))
    im.save(root / "IMG_P.png")
    # A steady 220 Hz tone: nothing in the click's band, so the click is measurable at
    # full music level (test_shutter's measurement).
    tone = tmp / "tone.wav"
    n = int(_MUSIC_S * _SR)
    wavfile.write(str(tone), _SR,
                  (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / _SR)).astype(np.float32))
    music = tmp / "MUSIC.json"
    music.write_text(json.dumps({
        "track": str(tone), "start_offset": 0.0, "duration": _MUSIC_S, "tempo": 120.0,
        "beats": [k * _BEAT for k in range(int(_MUSIC_S / _BEAT))],
        "energy": list(_ENERGY), "energy_hz": 2.0}))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(track, "_iter_detections", _detections)
        mp.setattr(track, "ensure_model", lambda model=track.MODEL: None)
        mp.setattr(track, "available", lambda descriptor=False: True)
        mp.setattr(extract.still, "people", lambda rgb, model: [
            (rgb.shape[1] * 0.6 + rgb.shape[1] / 16, rgb.shape[0] / 2, rgb.shape[1] / 8,
             rgb.shape[0] / 3)])
        accent = _reel(tmp / "accent", root, music, shutter=True)
        control = _reel(tmp / "control", root, music, shutter=False)
    return {"accent": accent, "control": control}


def _probe_rate(path: str) -> str:
    return json.loads(proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=r_frame_rate", "-of", "json",
                                path]).stdout)["streams"][0]["r_frame_rate"]


def _description(path: str) -> tuple:
    """The stream's four colour tags as ffprobe reads them, None where it carries none."""
    s = json.loads(proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=" + ",".join(_TAGS), "-of", "json",
                             path]).stdout)["streams"][0]
    return tuple(s.get(k) for k in _TAGS)


def _frame_descriptions(path: str) -> set[tuple]:
    """Every decoded frame's colour description — what the decoder hands each filter
    graph, carried-over descriptions included."""
    frames = json.loads(proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
                                  "-show_entries", "frame=" + ",".join(_TAGS), "-of", "json",
                                  path]).stdout)["frames"]
    return {tuple(f.get(k) for k in _TAGS) for f in frames}


def _cuts(rm: ReelManifest) -> list[float]:
    """Where each episode starts on the master: the probed clip lengths, summed — the
    clock build_reel places the accents on."""
    durs = [assembly.probe_duration(ep.clip) for ep in rm.episodes]
    return [float(sum(durs[:i])) for i in range(len(durs))]


def _gray(path: str) -> np.ndarray:
    """Every frame as an (n, h, w) float luma array — one decode."""
    si = assembly.probe_stream(path)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", path,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    n = si.w * si.h
    return np.frombuffer(raw, np.uint8)[:len(raw) // n * n].reshape(-1, si.h, si.w) \
        .astype(float)


def _audio(path: str, tmp: Path, name: str) -> np.ndarray:
    dec = tmp / f"{name}.wav"
    proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-i", path, "-vn", "-ac", "1",
              "-ar", str(_SR), str(dec)])
    _, y = wavfile.read(str(dec))
    return y.astype(np.float64)


def _band_rms(y: np.ndarray, t0: float, t1: float, lo=2500.0, hi=9000.0) -> float:
    seg = y[int(t0 * _SR):int(t1 * _SR)]
    freqs = np.fft.rfftfreq(len(seg), 1 / _SR)
    band = np.abs(np.fft.rfft(seg))[(freqs >= lo) & (freqs < hi)]
    return float(np.sqrt(np.mean(band ** 2)))


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def test_the_reel_is_delivered_with_every_episode_on_the_videos_clock(reels):
    for r in (reels["accent"], reels["control"]):
        assert r["res"]["status"] == "delivered", r["res"]
        assert [ep.freeze for ep in r["edl"].episodes] == [False, True, False, False]
        rates = {_probe_rate(ep.clip) for ep in r["rm"].episodes}
        assert rates == {f"{_FPS}/1"}, rates          # the photo and the freeze included
        assert _probe_rate(r["res"]["output"]) == f"{_FPS}/1"
    assert reels["accent"]["rm"].shutters == (1, 2)
    assert reels["control"]["rm"].shutters == ()


def test_every_episode_and_every_master_frame_carry_the_videos_colour_description(reels):
    """The photo takes the video's description (design §7), so the `-c copy` master never
    changes description mid-stream — not at the photo, and not after it, where a decoder
    carries a description over to frames whose own parameter sets name none."""
    for r in (reels["accent"], reels["control"]):
        video = _description(r["rm"].episodes[0].clip)
        assert {_description(ep.clip) for ep in r["rm"].episodes} == {video}
        assert _frame_descriptions(r["master"]) == {video}


def test_the_held_lengths_are_whole_beats_the_grid_chose(reels):
    r = reels["accent"]
    slots, eps = r["spine"].slots, r["edl"].episodes
    assert [s.held for s in slots] == [False, True, True, False]
    counts = []
    for i in (1, 2):
        beats = eps[i].dur / _BEAT
        assert eps[i].dur == pytest.approx(slots[i].dur)         # bound from the fit
        assert abs(beats - round(beats)) * _BEAT < 1 / _FPS       # a whole number of beats
        assert eps[i].dur != pytest.approx(hold.HOLD_DEFAULT)     # not the old placeholder
        clip = assembly.probe_duration(r["rm"].episodes[i].clip)
        assert clip == pytest.approx(eps[i].dur, abs=1 / _FPS)    # ...and what plays
        counts.append(round(beats))
    assert counts == [1, 3]      # peak: one beat; build: two planned, the bar line took 3
    # the control's grid is the same grid: the shutter is not an input to the fit
    assert [e.dur for e in reels["control"]["edl"].episodes] == [e.dur for e in eps]


def test_the_flash_is_in_the_delivered_file_at_each_accented_cut_and_not_in_the_master(
        reels):
    a, c = reels["accent"], reels["control"]
    cuts = _cuts(a["rm"])
    accented = [cuts[i] for i in a["rm"].shutters]
    att = json.loads(Path(provenance.attest_path(a["res"]["output"])).read_text())
    assert att["flashes"] == pytest.approx(accented, abs=1e-6)
    assert "flashes" not in json.loads(
        Path(provenance.attest_path(c["res"]["output"])).read_text())
    delivered, master = _gray(a["res"]["output"]), _gray(a["master"])
    plain = _gray(c["master"])
    for t in accented:
        n0 = round(t * _FPS)
        for k, alpha in enumerate(FLASH_ALPHA):
            m = master[n0 + k].mean()
            want = alpha * 255.0 + (1 - alpha) * m
            assert abs(delivered[n0 + k].mean() - want) < 4.0, (t, k, delivered[n0 + k].mean())
            # the master carries no flash: it is the control's master, frame for frame
            assert np.abs(master[n0 + k] - plain[n0 + k]).mean() < 1.0, (t, k)
        n = n0 + FLASH_FRAMES                              # one frame past the flash
        assert abs(delivered[n].mean() - master[n].mean()) < 2.0, (t, n)
    # the cut back to footage carries no accent, and no flash
    n = round(cuts[3] * _FPS)
    assert abs(delivered[n].mean() - master[n].mean()) < 2.0


def test_the_click_is_on_each_accented_cut_against_the_control(reels, tmp_path):
    a, c = reels["accent"], reels["control"]
    cuts = _cuts(a["rm"])
    y = _audio(a["res"]["output"], tmp_path, "accent")
    ctl = _audio(c["res"]["output"], tmp_path, "control")
    for i in a["rm"].shutters:
        t = cuts[i]
        at = _band_rms(y, t, t + 0.1)          # both bursts: 0-15 ms and 70-85 ms past it
        assert at > 20 * _band_rms(ctl, t, t + 0.1), (t, at, _band_rms(ctl, t, t + 0.1))
    # the cut back to footage has none: the accented reel reads as the control there
    t = cuts[3]
    assert _band_rms(y, t, t + 0.1) < 2 * _band_rms(ctl, t, t + 0.1) + 1.0


def test_the_freeze_holds_the_last_frame_of_the_episode_before_it(reels):
    rm = reels["accent"]["rm"]
    window, freeze = rm.episodes[0].clip, rm.episodes[1].clip
    n = assembly.count_frames(window)
    second_last, last = assembly.frames_rgb(window, [(n - 2) / _FPS, (n - 1) / _FPS], _FPS)
    first = assembly.frames_rgb(freeze, [0.0], _FPS)[0]
    gap = _dist(last, second_last)
    assert _dist(first, last) < _dist(first, second_last)
    assert _dist(first, last) < gap / 4, (_dist(first, last), gap)
