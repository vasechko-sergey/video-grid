"""mix ambient path — unit level, proc.run mocked (the real ffmpeg proof lives in
tests/integration/test_ambient.py). Asserts branch selection + command shape only."""
import json

import pytest

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


# --- transition SFX (§5.12) -------------------------------------------------

def test_major_cuts_needs_two_clips():
    assert mix._major_cuts([5.0]) == []


def test_major_cuts_uniform_pacing_has_none():
    assert mix._major_cuts([2.0, 2.0, 2.0]) == []          # nothing exceeds the median → no accent


def test_major_cuts_one_held_shot():
    assert mix._major_cuts([3.0, 0.5, 0.5]) == pytest.approx([3.0])   # cut after the 3.0s hold


def test_major_cuts_throttle_drops_close_second():
    # majors fall at 4.0, 4.3, 8.3; 4.3 is within _MIN_GAP (0.6) of 4.0 → dropped
    assert mix._major_cuts([4.0, 0.3, 4.0, 0.3, 0.3]) == pytest.approx([4.0, 8.3])


def test_build_sfx_no_major_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mix.proc, "run", lambda *a, **k: _R())
    monkeypatch.setattr(mix, "_whoosh", lambda d: d + "/w.wav")
    assert mix._build_sfx([2.0, 2.0, 2.0], str(tmp_path)) is None


def test_build_sfx_places_a_whoosh_at_each_major_cut(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run", lambda cmd, **k: (calls.append(cmd), _R())[1])
    monkeypatch.setattr(mix, "_whoosh", lambda d: d + "/w.wav")
    res = mix._build_sfx([3.0, 0.5, 0.5], str(tmp_path))
    assert res is not None and res.endswith("sfx.wav")
    joined = " ".join(map(str, calls[-1]))
    assert "asplit=1" in joined                                   # one major cut → one whoosh copy
    assert "adelay=2800:all=1" in joined                          # t=3.0 − _SFX_LEAD(0.2) = 2.8s
    assert "amix=inputs=2:duration=first:normalize=0" in joined   # base + 1 whoosh, levels kept


def test_mix_sfx_only_makes_no_sidechain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_sfx", lambda durs, d: d + "/sfx.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0,
            segments=[("s0.mp4", 3.0), ("s1.mp4", 3.0)], ambient=False, sfx=True)
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" not in joined and "asplit" not in joined  # no ambient duck
    assert "[sfx]" in joined and "amix=inputs=2:duration=first" in joined  # music + sfx on top


def test_mix_ambient_and_sfx_compose_three_inputs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    monkeypatch.setattr(mix, "_build_sfx", lambda durs, d: d + "/sfx.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0,
            segments=[("s0.mp4", 3.0), ("s1.mp4", 3.0)], ambient=True, sfx=True)
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" in joined                              # ambient still ducked
    assert "[sfx]" in joined                                          # sfx term present
    assert "amix=inputs=3:duration=first" in joined                  # music + ducked ambient + sfx


def test_mix_sfx_false_leaves_ambient_graph_unchanged(tmp_path, monkeypatch):
    # regression: sfx defaults off → the ambient-only graph is byte-identical to today
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 6.0)])
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert ("[0:a]asplit=2[msum][mkey];[1:a]volume=0.6[amb];"
            "[amb][mkey]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=300[duck];"
            "[msum][duck]amix=inputs=2:duration=first[mixed]") in joined
    assert "[sfx]" not in joined


# --- the bookend fade moves onto the mixed stem (Task 4) --------------------
# design 2026-08-13 §5: _mix_graph's sidechaincompress keys the ambient duck on the
# music (input 0). With the fade baked into the music fragment, the key falls at the
# reel's end, the duck RELEASES, and the nat-sound gets louder exactly as the picture
# goes to black — and the sfx whoosh was never faded at all. The fix moves `afade`
# onto the fully-mixed stem, after the duck/whoosh mix and before `_measure`.

def test_the_fragment_extract_no_longer_carries_the_fade(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0)
    frag_cmd = " ".join(map(str, calls[0]))
    assert "afade" not in frag_cmd


def test_the_fade_runs_on_the_mixed_stem_before_loudnorm(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0,
            segments=[("s0.mp4", 3.0), ("s1.mp4", 3.0)])
    joined = [" ".join(map(str, c)) for c in calls]
    fade_i = next(i for i, c in enumerate(joined) if "afade=t=in" in c)
    mix_i = next(i for i, c in enumerate(joined) if "sidechaincompress" in c)
    norm_i = next(i for i, c in enumerate(joined) if "loudnorm=I=" in c and "print_format" not in c)
    assert mix_i < fade_i < norm_i     # ambient is ducked, THEN faded, THEN normalized


def test_the_fade_is_a_parameter_and_zero_leaves_only_the_anti_click(tmp_path, monkeypatch):
    # fade=0 is "no bookend". The opening still gets ANTICLICK seconds: the music is
    # cut mid-track at its start_offset, and a hard start is a click, not a style.
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, fade=0.0)
    af = [" ".join(map(str, c)) for c in calls if "afade" in " ".join(map(str, c))]
    assert len(af) == 1
    assert f"afade=t=in:st=0:d={mix.ANTICLICK}" in af[0] and "afade=t=out" not in af[0]


def test_the_opening_and_closing_fades_are_separate(tmp_path, monkeypatch):
    """retro 2026-10-16 S6: one fade served both ends, so a reel could not open on
    picture and still close softly."""
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, fade=1.5, fade_in=0.0)
    af = next(" ".join(map(str, c)) for c in calls if "afade" in " ".join(map(str, c)))
    assert f"afade=t=in:st=0:d={mix.ANTICLICK}" in af
    assert "afade=t=out:st=4.5:d=1.5" in af             # dur(6.0) - fade(1.5)


def test_an_opening_and_closing_fade_that_meet_are_refused(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        mix.mix(_ms(tmp_path), str(tmp_path / "out"), 2.0, fade=1.5, fade_in=0.6)


def test_a_long_close_fits_a_reel_whose_sound_opens_without_a_fade(tmp_path, monkeypatch):
    # the old rule (dur < 2 * fade) refused this; the opening is only ANTICLICK long
    monkeypatch.setattr(mix.proc, "run", lambda cmd, **k: _R(stderr=_loudnorm_stderr()))
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 1.6, fade=1.5, fade_in=0.0)


def test_a_custom_fade_reaches_both_ends(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, fade=0.8)
    af = next(" ".join(map(str, c)) for c in calls if "afade=t=in" in " ".join(map(str, c)))
    assert "afade=t=in:st=0:d=0.8" in af
    assert "afade=t=out:st=5.2:d=0.8" in af             # dur(6.0) - fade(0.8)


def test_overlapping_fades_are_refused_with_the_authored_number(tmp_path):
    with pytest.raises(ValueError, match="1.5s"):
        mix.mix(_ms(tmp_path), str(tmp_path / "out"), 2.0, fade=1.5)


# --- the music-less stem (design 2026-10-20 §2, backlog U3) ------------------

_FADES = ["afade=t=in:st=0:d=0.02", "afade=t=out:st=5.0:d=1.0"]


def test_the_music_less_graph_is_the_music_stem_with_the_track_muted():
    """No key and no compressor; each layer keeps the 1/N weight the music mix's amix gave
    it (N = 3: music + ambient + sfx), summed with normalize=0; the music stem's own gain,
    not a second loudnorm; the same fades; a ceiling that does NOT auto-level."""
    g = mix._nomusic_graph(True, True, 6.0, _FADES, 6.0)
    assert g == ("[0:a]volume=0.200000[amb];[1:a]volume=0.333333[sfx];"
                 "[amb][sfx]amix=inputs=2:duration=longest:normalize=0[nm];"
                 "[nm]apad,atrim=0:6.0,volume=6.000dB,"
                 "afade=t=in:st=0:d=0.02,afade=t=out:st=5.0:d=1.0,"
                 "alimiter=limit=0.8414:level=0:latency=1[out]")
    assert "sidechaincompress" not in g and "loudnorm" not in g


def test_one_layer_keeps_the_weight_it_had_beside_the_music():
    g = mix._nomusic_graph(True, False, -3.0, _FADES, 6.0)
    assert g.startswith("[0:a]volume=0.300000[amb];[amb]apad,atrim=0:6.0,volume=-3.000dB,")


def test_the_music_less_graph_refuses_an_empty_reel():
    with pytest.raises(ValueError, match="silence"):
        mix._nomusic_graph(False, False, 0.0, _FADES, 6.0)


def _run_with_layout(calls):
    """proc.run stand-in: loudnorm stats on stderr, and a 48 kHz stereo layout for the
    one ffprobe _layout asks."""
    def run(cmd, **k):
        calls.append(cmd)
        return _R(stdout=b"48000,2\n", stderr=_loudnorm_stderr())
    return run


def test_mix_renders_the_music_less_stem_with_the_music_stems_gain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run", _run_with_layout(calls))
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    nm = str(tmp_path / "out" / "no_music.m4a")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 6.0)],
            without_music=nm)
    last = " ".join(map(str, calls[-1]))
    # _loudnorm_stderr measures -20 LUFS, so the music stem was lifted 6 dB: the same 6 dB
    assert last.endswith(nm) and "volume=6.000dB" in last
    assert "[0:a]volume=0.300000[amb]" in last and "sidechaincompress" not in last
    assert "-ac 2 -ar 48000" in last                 # the music stem's layout, probed


def test_a_reel_with_nothing_but_music_gets_a_silent_music_less_stem(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run", _run_with_layout(calls))
    nm = str(tmp_path / "out" / "no_music.m4a")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, without_music=nm)
    last = " ".join(map(str, calls[-1]))
    assert "anullsrc" in last and "-t 6.0" in last and last.endswith(nm)


def test_no_music_less_stem_unless_asked(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0)
    assert not any("alimiter" in " ".join(map(str, c)) for c in calls)



@pytest.mark.parametrize("tp, linear", [(-3.0, False), (-9.0, True)])
def test_mix_records_what_the_music_less_stem_holds_and_whether_the_gain_is_exact(
        tmp_path, monkeypatch, tp, linear):
    """loudnorm stays linear only while the lifted true peak fits its target; past it,
    the music stem rode a dynamic gain and the music-less one sits a few dB away."""
    stats = (f'"input_i" : "-20.0", "input_tp" : "{tp}", '
             f'"input_lra" : "5.0", "input_thresh" : "-30.0"').encode()
    calls = []
    monkeypatch.setattr(mix.proc, "run", lambda cmd, **k: (calls.append(cmd),
                        _R(stdout=b"48000,2\n", stderr=stats))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    nm = tmp_path / "out" / "no_music.m4a"
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 6.0)],
            without_music=str(nm))
    assert json.loads(nm.with_suffix(".json").read_text()) == {
        "ambient": True, "sfx": False, "gain_db": 6.0, "linear": linear}
