"""mix ambient path — unit level, proc.run mocked (the real ffmpeg proof lives in
tests/integration/test_ambient.py). Asserts branch selection + command shape only."""
from scripts import mix
from scripts.lib.models import MusicSpec


class _R:
    def __init__(self, stdout=b"", stderr=b""):
        self.stdout, self.stderr = stdout, stderr


def test_build_ambient_all_silent_returns_none(tmp_path, monkeypatch):
    # every ffprobe audio probe returns empty → no segment has audio → None
    calls = []
    monkeypatch.setattr(mix.proc, "run", lambda cmd, **k: (calls.append(cmd), _R())[1])
    monkeypatch.setattr(mix.assembly, "concat", lambda entries, out: out)
    res = mix._build_ambient([("s0.mp4", 3.0), ("s1.mp4", 2.0)], str(tmp_path))
    assert res is None
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "anullsrc" in joined                       # silent segments synth silence


def test_build_ambient_audio_present_concats_one_wav_per_segment_in_order(tmp_path, monkeypatch):
    def fake_run(cmd, **k):
        stdout = b"aac\n" if "-select_streams" in cmd else b""   # probe → audio present
        return _R(stdout=stdout)
    monkeypatch.setattr(mix.proc, "run", fake_run)
    seen = {}
    monkeypatch.setattr(mix.assembly, "concat",
                        lambda entries, out: (seen.setdefault("entries", list(entries)), out)[1])
    res = mix._build_ambient([("s0.mp4", 3.0), ("s1.mp4", 2.0)], str(tmp_path))
    assert res is not None
    assert len(seen["entries"]) == 2                  # one bed wav per segment, EDL order


def test_build_ambient_mixed_returns_bed_when_any_has_audio(tmp_path, monkeypatch):
    def fake_run(cmd, **k):
        # only s0's probe reports audio; s1 is video-only
        stdout = b"aac\n" if ("-select_streams" in cmd and "s0.mp4" in cmd) else b""
        return _R(stdout=stdout)
    monkeypatch.setattr(mix.proc, "run", fake_run)
    monkeypatch.setattr(mix.assembly, "concat", lambda entries, out: out)
    res = mix._build_ambient([("s0.mp4", 3.0), ("s1.mp4", 2.0)], str(tmp_path))
    assert res is not None                            # one real audio stream → a bed (s1 = silence)


def _ms(tmp_path):
    return MusicSpec(track=str(tmp_path / "t.wav"), start_offset=0.0, duration=6.0,
                     tempo=120.0, beats=(0.0, 0.5), energy=(0.3,), energy_hz=2.0)


def _loudnorm_stderr():
    # _measure scrapes these four keys from ffmpeg's stderr; feed a valid set
    return (b'"input_i" : "-20.0", "input_tp" : "-3.0", '
            b'"input_lra" : "5.0", "input_thresh" : "-30.0"')


def test_mix_music_only_makes_no_sidechain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    out = mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0)           # segments=None
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" not in joined and "asplit" not in joined  # unchanged path
    assert out.endswith("audio.m4a")


def test_mix_with_ambient_inserts_sidechain_and_pins_length(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 3.0)])
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" in joined                              # ambient graph inserted
    assert "amix=inputs=2:duration=first" in joined                   # length pinned to the music


def test_mix_all_silent_bed_falls_back_to_music_only(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: None)  # every segment silent
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 3.0)])
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" not in joined                          # None → music-only
