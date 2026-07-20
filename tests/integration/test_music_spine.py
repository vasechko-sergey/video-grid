"""Real-ffmpeg proofs for the music spine (design §7): (A) mix hits −14 LUFS;
(B) build_reel delivers a reel WITH an audio stream end-to-end (added in Task 7).
Clips are built with the real reframe encoder, matching test_reel_retry.py's precedent."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import build_reel, check_reel, mix, reframe
from scripts.lib import ffbin, proc
from scripts.lib.models import (Delivery, LayoutSpec, MusicSpec, ReframeSpec,
                                ReelCheckSpec, ReelEpisode, ReelManifest)


def _tone_music(tmp_path, secs=6, sr=22050):
    """A steady 220 Hz tone + a MusicSpec describing it (a beat every 0.5s)."""
    n = int(secs * sr)
    y = (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / sr)).astype(np.float32)
    wav = tmp_path / "tone.wav"
    wavfile.write(wav, sr, y)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(wav), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3, 0.3, 0.3), energy_hz=2.0)


@pytest.mark.integration
def test_mix_hits_target_loudness(tmp_path):
    ms = _tone_music(tmp_path, secs=6)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0)
    measured = check_reel._loudnorm_measure(stem)
    spec = ReelCheckSpec(target_dur=6.0)
    assert abs(measured - spec.loudness_target) <= spec.loudness_tol   # mix must satisfy check_reel's real gate (±1 of −14)


def _reframe(src, tmp, x_const, name):
    """A clip via the real reframe encoder with a constant-x crop route. A distinct
    x_const frames sample_clip's moving box differently → distinct phash, so two
    clips at 645 vs 1045 clear the variety check (test_reel_retry.py's precedent)."""
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"
    rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(src), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_build_reel_delivers_reel_with_audio_stream(tmp_path, sample_clip):
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    ep1 = _reframe(sample_clip, tmp_path, 1045, "ep1")
    dur = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    ms = _tone_music(tmp_path, secs=max(2, int(round(dur)) + 1))     # track at least the reel length
    music_json = tmp_path / "MUSIC.json"
    music_json.write_text(json.dumps({**ms.to_dict(), "duration": dur,
                                      "beats": [b for b in ms.beats if b <= dur]}))
    d0 = check_reel._probe_dur(ep0)
    d1 = check_reel._probe_dur(ep1)
    # ep0/ep1 are silent (reframe strips audio with -an) → _build_ambient returns
    # None → music-only stem; proves the default ambient=True path survives real
    # audioless segments
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": ep0, "target_dur": d0}, clip=ep0, route=str(tmp_path / "r0.json")),
                  ReelEpisode(manifest={"segment": ep1, "target_dur": d1}, clip=ep1, route=str(tmp_path / "r1.json"))],
        target_dur=dur, variety_min=4, color_delta_max=40.0, music=str(music_json))
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    r = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
                  "stream=codec_name", "-of", "default=nk=1:nw=1", res["output"]])
    assert r.stdout.decode().strip().startswith("aac")           # the delivered reel carries an aac stem
    assert res["report"]["checks"]["loudness"]["pass"] is True    # loudness gate green
    assert "worst_dev" in res["report"]["checks"]["beat"]         # beat measured (advisory)
