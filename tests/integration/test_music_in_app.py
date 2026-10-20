"""Real-ffmpeg proofs for the music-less stem (design 2026-10-20 §2): it is the music
stem with the track muted — no music in it, no duck pumping to a song that is gone, the
ambient at the level the music stem gave it, and silence when there is nothing to keep.
Synthetic known-answer signals, the idiom of tests/integration/test_ambient.py."""
import shutil
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import build_reel, mix
from scripts.lib import ffbin, proc
from scripts.lib.models import MusicSpec, ReelEpisode, ReelManifest

_SR = 22050


def _need_ffmpeg():
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))


def _tone(path, secs, freq, amp, first_half_only=False, stereo=False):
    t = np.arange(int(secs * _SR)) / _SR
    y = amp * np.sin(2 * np.pi * freq * t)
    if first_half_only:
        y[t >= secs / 2] = 0.0
    wavfile.write(path, _SR, (np.stack([y, y], axis=1) if stereo else y).astype(np.float32))
    return str(path)


def _music(path, secs, **kw):
    _tone(path, secs, 220.0, 0.6, **kw)
    return MusicSpec(track=str(path), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5))),
                     energy=(0.3,), energy_hz=2.0)


def _decode(path, tmp_path, name):
    out = str(tmp_path / f"{name}.wav")
    proc.run([ffbin.ffmpeg(), "-y", "-i", path, "-ac", "1", "-ar", str(_SR), out])
    sr, y = wavfile.read(out)
    return y.astype(np.float64), sr


def _band(y, sr, freq, t0, t1):
    seg = y[int(t0 * sr):int(t1 * sr)]
    k = np.exp(-2j * np.pi * freq * np.arange(len(seg)) / sr)
    return abs(np.dot(seg, k)) / len(seg)


@pytest.mark.integration
@pytest.mark.parametrize("stereo", [False, True], ids=["mono-track", "stereo-track"])
def test_the_music_less_stem_is_the_music_stem_with_the_track_muted(tmp_path, stereo):
    _need_ffmpeg()
    # music (220 Hz) loud for the first half only; ambient (880 Hz) constant throughout.
    # Both track layouts: the music stem takes the TRACK's, and a mono track beside a
    # stereo bed once put the two stems 3 dB apart.
    ms = _music(tmp_path / "m.wav", 6, first_half_only=True, stereo=stereo)
    seg = _tone(tmp_path / "seg.wav", 6, 880.0, 0.5)
    nm_path = str(tmp_path / "out" / "no_music.m4a")
    stem = mix.mix(ms, str(tmp_path / "out"), 6.0, segments=[(seg, 6.0)], without_music=nm_path)
    with_m, sr = _decode(stem, tmp_path, "with")
    nm, _ = _decode(nm_path, tmp_path, "without")
    # 1. no music in it: the 220 Hz band is gone, the 880 Hz ambient is there
    assert _band(nm, sr, 220.0, 0.5, 2.5) < 0.01 * _band(nm, sr, 880.0, 0.5, 2.5)
    # 2. no pump: the ambient is as loud under the (now absent) music as after it,
    #    while the music stem's ambient IS ducked there — the control
    first, second = _band(nm, sr, 880.0, 0.5, 2.5), _band(nm, sr, 880.0, 3.5, 5.0)
    assert 0.9 < first / second < 1.1
    assert _band(with_m, sr, 880.0, 0.5, 2.5) < 0.9 * _band(with_m, sr, 880.0, 3.5, 5.0)
    # 3. the music stem's gain, not a re-normalization: where the music stem's duck has
    #    released (music silent), its ambient and the music-less ambient are one level
    ratio = second / _band(with_m, sr, 880.0, 3.5, 5.0)
    assert 0.97 < ratio < 1.03                    # the gain is exact in loudnorm's linear mode


@pytest.mark.integration
def test_a_reel_with_nothing_but_music_gets_a_silent_music_less_stem(tmp_path):
    _need_ffmpeg()
    ms = _music(tmp_path / "m.wav", 6)
    nm_path = str(tmp_path / "out" / "no_music.m4a")
    mix.mix(ms, str(tmp_path / "out"), 6.0, without_music=nm_path)
    nm, sr = _decode(nm_path, tmp_path, "without")
    assert len(nm) >= int(5.9 * sr) and np.max(np.abs(nm)) < 1e-3


def _video_md5(path):
    r = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", path, "-map", "0:v", "-c", "copy",
                  "-f", "md5", "-"])
    return r.stdout.decode().strip()


@pytest.mark.integration
def test_the_music_less_delivery_keeps_the_delivered_picture_byte_for_byte(tmp_path, sample_clip):
    """The picture is stream-copied from the attested reel (design 2026-10-20 §3), so
    titles and look survive and nothing is re-encoded; only the sound changes."""
    _need_ffmpeg()
    out = tmp_path / "deliveries"
    out.mkdir()
    delivered = out / "REEL_v2.mp4"
    shutil.copy(sample_clip, delivered)
    stem = str(tmp_path / "nm.m4a")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
              "-t", "3", "-c:a", "aac", stem])
    (tmp_path / "nm.json").write_text(            # the record mix writes beside its stem
        '{"ambient": false, "sfx": false, "gain_db": 0.0, "linear": true}')
    ms = _music(tmp_path / "m.wav", 6)
    rm = ReelManifest(episodes=[ReelEpisode(manifest={"segment": "s.mp4"}, clip=str(sample_clip),
                                            route=None)],
                      target_dur=3.0, music=str(tmp_path / "MUSIC.json"), music_in_app=True)
    res = build_reel._deliver_without_music(str(delivered), stem, ms, rm)
    nm = res["no_music"]
    assert _video_md5(nm) == _video_md5(str(delivered))
    r = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
                  "-show_entries", "stream=codec_name", "-of", "csv=p=0", nm])
    assert r.stdout.decode().strip() == "aac"
    assert sorted(p.name for p in out.glob("REEL_v*")) == ["REEL_v2.mp4"]
    assert "and silent" in Path(res["sound_note"]).read_text()
