"""beats.py tests. The downsample unit tests moved to tests/lib/test_offset.py
(scripts/lib/offset.py owns that logic now — see docs/specs/2026-07-13-
start-offset-intelligence-design.md). Repopulated by later start-offset tasks."""
import numpy as np
import pytest

from scripts import beats
from scripts.lib import offset, vocals
from scripts.lib.models import MusicSpec


def _fake_librosa(monkeypatch, track_seconds, sr=2000):
    """Make beats' lazy `import librosa` return a stub whose load() yields a signal
    of the requested length and whose feature.rms() returns a dummy frame array.
    offset.downsample is separately monkeypatched, so the rms values don't matter."""
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(track_seconds * sr), dtype=np.float32), sr))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.0]]))


def test_choose_offset_track_shorter_than_reel_returns_zero(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=2.0)
    assert beats.choose_offset("t.wav", duration=5.0) == 0.0
    assert "whole track" in capsys.readouterr().err


def test_choose_offset_gaps_come_from_the_vocal_stem(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0], 2.0))
    monkeypatch.setattr(vocals, "vocal_spans", lambda *a, **k: ((1.5, 2.5),))
    off = beats.choose_offset("t.wav", duration=2.0)
    assert off == 1.5
    assert "via vocal" in capsys.readouterr().err


def test_choose_offset_gaps_are_not_the_mix_envelope(monkeypatch):
    """Discriminates the deleted mix-proxy: the mix envelope has its own quiet run
    that the vocal stem does not. Reading gaps off the mix would pick 3.0s."""
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([0.0, 0.0, 1.0, 5.0, 5.0, 5.0, 0.0, 0.0], 2.0))
    monkeypatch.setattr(vocals, "vocal_spans", lambda *a, **k: ((1.5, 2.5),))
    assert beats.choose_offset("t.wav", duration=2.0) == 1.5


def test_choose_offset_refuses_without_demucs(monkeypatch):
    """demucs is REQUIRED (2026-08-14): the mix-proxy fallback is gone because it
    does not fail, it silently returns a wrong answer — measured 2 gaps in a 228s
    dense pop track, so every candidate collapsed to 0.0."""
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    with pytest.raises(ValueError, match="demucs"):
        beats.choose_offset("t.wav", duration=2.0)


def test_cli_auto_start_requires_duration(monkeypatch):
    monkeypatch.setattr("sys.argv", ["beats", "t.wav", "--auto-start", "--out", "M.json"])
    with pytest.raises(SystemExit):                          # argparse error() → SystemExit(2)
        beats.main()


def test_cli_auto_start_computes_offset(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(beats, "choose_offset", lambda track, dur: seen.setdefault("off", 7.5) or 7.5)

    def fake_analyze(track, start, duration):
        seen["start"] = start
        return MusicSpec(track=track, start_offset=start, duration=10.0, tempo=120.0,
                         beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)

    monkeypatch.setattr(beats, "analyze", fake_analyze)
    # main() now always measures vocal_spans too (Step 7); stub it so this test, which
    # is only about the --auto-start offset wiring, doesn't drive a real demucs call.
    monkeypatch.setattr(vocals, "vocal_spans", lambda t: ())
    out = tmp_path / "M.json"
    monkeypatch.setattr("sys.argv", ["beats", "t.wav", "--auto-start", "--duration", "10",
                                     "--out", str(out)])
    beats.main()
    assert seen["off"] == 7.5 and seen["start"] == 7.5 and out.exists()


from scripts.lib import mood


def _fake_librosa_mood(monkeypatch, *, tempo, centroid, rms_after_norm):
    """Stub beats' lazy librosa for mood_features: beat_track→tempo, spectral_centroid
    →centroid, rms→a frame whose mean is rms_after_norm. load() returns a peak=1.0
    signal so peak-normalization runs (rms is mocked, so its input doesn't matter)."""
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.array([1.0, -1.0], dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda *a, **k: (np.array([tempo]), np.array([])))
    monkeypatch.setattr(librosa.feature, "spectral_centroid",
                        lambda *a, **k: np.array([[centroid]]))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[rms_after_norm]]))


def test_mood_features_maps_into_the_vector_space(monkeypatch):
    _fake_librosa_mood(monkeypatch, tempo=120.0, centroid=2750.0, rms_after_norm=0.175)
    v = beats.mood_features("t.wav")
    assert v == mood.MoodVector(energy=mood.norm01(0.175, *mood.ENERGY_RMS),
                                brightness=mood.norm01(2750.0, *mood.BRIGHT_HZ),
                                pace=mood.norm01(120.0, *mood.PACE_BPM))
    # 120 BPM, 2750 Hz, 0.175 RMS are the axis midpoints → ~0.5 each
    assert v.energy == pytest.approx(0.5)
    assert v.brightness == pytest.approx(0.5)
    assert v.pace == pytest.approx(0.5)


def test_mood_features_silent_track_guards_zero_division(monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, "load", lambda *a, **k: (np.zeros(100, dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track", lambda *a, **k: (np.array([90.0]), np.array([])))
    monkeypatch.setattr(librosa.feature, "spectral_centroid", lambda *a, **k: np.array([[1000.0]]))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.0]]))
    v = beats.mood_features("silent.wav")     # peak=0 → guarded, no ZeroDivisionError
    assert v.energy == 0.0


def test_downbeat_phase_finds_the_bass_phase(monkeypatch):
    """§3 — the kick marks the downbeat. Synthesize a 4/4 grid whose every 4th beat
    (phase 2 here) carries a 60 Hz thump and the rest carry a 1 kHz tick, and the
    detector must return 2. Onset strength cannot do this (measured: all four phases
    within 1%), which is why the band is the bass band."""
    sr = 22050
    period = 0.5
    times = [i * period for i in range(16)]
    y = np.zeros(int(sr * (times[-1] + period)), dtype=np.float32)
    t = np.arange(int(sr * 0.12)) / sr
    thump = (0.9 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)
    tick = (0.9 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    for i, bt in enumerate(times):
        a = int(bt * sr)
        pulse = thump if i % 4 == 2 else tick
        y[a:a + len(pulse)] += pulse
    assert beats._downbeat_phase(y, sr, times) == 2


def test_downbeat_phase_none_when_too_few_beats():
    """A phase argmax over one or two samples per group is noise; () is the honest
    answer and the outro fit reads it as the 'unchanged' rung."""
    assert beats._downbeat_phase(np.zeros(1000, dtype=np.float32), 22050,
                                 [0.0, 0.5, 1.0, 1.5]) is None


def test_analyze_fills_bars_from_the_detected_phase(monkeypatch):
    import librosa
    times = [i * 0.5 for i in range(16)]
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(8.0 * 22050), dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda *a, **k: (np.array([120.0]), np.arange(16)))
    monkeypatch.setattr(librosa, "frames_to_time", lambda f, **k: np.array(times))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.1]]))
    monkeypatch.setattr(beats, "_downbeat_phase", lambda *a, **k: 1)
    ms = beats.analyze("t.wav")
    assert ms.bars == (0.5, 2.5, 4.5, 6.5)


def test_analyze_leaves_bars_empty_when_the_phase_is_unknown(monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(8.0 * 22050), dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda *a, **k: (np.array([120.0]), np.arange(4)))
    monkeypatch.setattr(librosa, "frames_to_time",
                        lambda f, **k: np.array([0.0, 0.5, 1.0, 1.5]))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.1]]))
    monkeypatch.setattr(beats, "_downbeat_phase", lambda *a, **k: None)
    assert beats.analyze("t.wav").bars == ()


def test_cli_fills_vocal_spans_windowed_to_the_stem(monkeypatch, tmp_path):
    """The spans MusicSpec stores are stem-relative and clipped to the window; the
    sensor measures track-relative. main() is where the one conversion happens."""
    monkeypatch.setattr(vocals, "vocal_spans", lambda t: ((3.0, 4.0), (19.0, 30.0)))
    monkeypatch.setattr(beats, "analyze", lambda track, start, duration: MusicSpec(
        track=track, start_offset=start, duration=10.0, tempo=120.0,
        beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0, bars=(0.0,)))
    out = tmp_path / "M.json"
    monkeypatch.setattr("sys.argv", ["beats", "t.wav", "--start-offset", "12",
                                     "--duration", "10", "--out", str(out)])
    beats.main()
    ms = MusicSpec.from_json(out)
    assert ms.vocal_spans == ((7.0, 10.0),)     # (19,30) clipped; (3,4) is before the window


def test_downbeat_phase_declines_a_flat_distribution():
    """The four tracks measured on 2026-08-17 (design §3) put every phase within
    ~3% of the others; argmax still returned one, confidently, and the outro fit
    landed the reel on a beat it then called a bar line. A flat input is the
    honest None — the same answer as too-few-beats, reached for the same reason."""
    sr = 22050
    period = 0.5
    times = [i * period for i in range(16)]
    y = np.zeros(int(sr * (times[-1] + period)), dtype=np.float32)
    t = np.arange(int(sr * 0.12)) / sr
    thump = (0.9 * np.sin(2 * np.pi * 40 * t)).astype(np.float32)
    for bt in times:                       # every beat identical — no phase preference
        a = int(bt * sr)
        y[a:a + len(thump)] += thump
    assert beats._downbeat_phase(y, sr, times) is None


def test_downbeat_phase_margin_is_the_ranked_gap_not_the_spread():
    """max/min does NOT discriminate (design §4): a track with one QUIET phase
    scores a high spread while its winner barely leads. Build exactly that — one
    silent phase, three near-equal loud ones — and the detector must decline
    even though max/min is enormous."""
    sr = 22050
    period = 0.5
    times = [i * period for i in range(16)]
    y = np.zeros(int(sr * (times[-1] + period)), dtype=np.float32)
    t = np.arange(int(sr * 0.12)) / sr
    for i, bt in enumerate(times):
        if i % 4 == 1:                     # phase 1 silent -> max/min is huge
            continue
        amp = 0.90 if i % 4 == 2 else 0.88  # winner leads by 2%, far under the margin
        a = int(bt * sr)
        y[a:a + len(t)] += (amp * np.sin(2 * np.pi * 40 * t)).astype(np.float32)
    assert beats._downbeat_phase(y, sr, times) is None
