"""vidstab — the one place this repo talks to libvidstab (design 2026-07-20 §3)."""
import types

import pytest

from scripts.lib import ffbin, vidstab


def _filters(monkeypatch, text: str) -> None:
    """Stand in for `ffmpeg -filters` output. Patch the RESOLVER's proc, because
    that is where ffbin.has_filter issues the probe (design 2026-07-20 §5)."""
    monkeypatch.setattr(ffbin.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=text.encode()))


def test_require_is_silent_when_both_filters_are_present(monkeypatch):
    _filters(monkeypatch, " .. vidstabdetect ...\n .. vidstabtransform ...\n")
    assert vidstab.require() is None


def test_require_raises_when_detect_is_absent(monkeypatch):
    _filters(monkeypatch, " .. scale ...\n .. overlay ...\n")
    with pytest.raises(ValueError, match="vidstabdetect.*setup.sh"):
        vidstab.require()


def test_require_raises_when_only_transform_is_absent(monkeypatch):
    """The gate used to check vidstabdetect alone, which was honest while detect
    was the only pass. This slice adds a transform pass, so a build carrying one
    filter and not the other must not get through — libvidstab supplies both or
    neither, and this firing means something stranger than a missing library."""
    _filters(monkeypatch, " .. vidstabdetect ...\n .. scale ...\n")
    with pytest.raises(ValueError, match="vidstabtransform.*setup.sh"):
        vidstab.require()


_TRF = "\n".join([
    "VID.STAB 1",
    "Frame 1 (List 0 [])",
    "Frame 2 (List 2 [(LM 3 4 100 100 0.5 0.9) (LM 6 8 200 200 0.5 0.9)])",  # mags 5, 10 → median 10
    "Frame 3 (List 1 [(LM 0 0 100 100 0.5 0.9)])",                            # mag 0
])


def test_parse_trf_median_magnitudes():
    assert vidstab.parse_trf(_TRF) == [0.0, 10.0, 0.0]


def test_parse_trf_bad_header_raises():
    with pytest.raises(ValueError, match="unrecognized header.*setup.sh"):
        vidstab.parse_trf("not a vidstab file\nFrame 1 (List 0 [])")


def test_parse_trf_empty_raises():
    with pytest.raises(ValueError, match="empty .trf"):
        vidstab.parse_trf("")


def test_a_binary_trf_names_the_format_and_the_option(tmp_path):
    """libvidstab's DEFAULT serializer is binary and this parser reads the ASCII
    one, so this is the shape a caller hits when `fileformat=ascii` goes missing.
    Before the guard, Path.read_text() raised UnicodeDecodeError several frames
    up, naming a byte offset instead of a remedy."""
    trf = tmp_path / "t.trf"
    trf.write_bytes(b"TRF1\x0f\x00\x00\x00\x05\x00\x00\x00\xd0?")
    with pytest.raises(ValueError, match="BINARY .trf.*fileformat=ascii"):
        vidstab.read_trf(trf)


def test_an_undecodable_trf_with_no_known_magic_still_fails_loud(tmp_path):
    trf = tmp_path / "t.trf"
    trf.write_bytes(b"\xd0\xd0\xd0 not utf-8 and not TRF")
    with pytest.raises(ValueError, match="cannot trust the shake estimate.*setup.sh"):
        vidstab.read_trf(trf)


def test_ascii_trf_decodes_unchanged(tmp_path):
    trf = tmp_path / "t.trf"
    trf.write_text(_TRF)
    assert vidstab.read_trf(trf) == _TRF


def test_the_detect_recipe_sets_shakiness_and_nothing_that_is_already_default():
    """Design §4/§5. `shakiness=8` is the one non-default detect option — accuracy
    is 15 by default, so writing it would perform a choice that was never made and
    a later reader could not tell the two apart. The transform pass's options are
    a different namespace and belong in TRANSFORM_ARGS, not here.

    This is pinned rather than left to review because the constant is SHARED with
    intake specifically so both report the same measurement (§5). Anyone adding a
    knob here silently re-scales FOOTAGE.md's shake column.
    """
    assert vidstab.DETECT_ARGS == "shakiness=8"


def _stub_detect_run(seen: dict):
    """A proc.run stand-in that writes a minimal valid .trf wherever the real
    vidstabdetect command would have written one, and records the argv and kwargs."""
    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen.update(kwargs)
        # the -vf value is `vidstabdetect=<args>:result=<path>:fileformat=ascii`,
        # so the path ends at the next option separator, not at end-of-string.
        trf_path = cmd[cmd.index("-vf") + 1].split("result=", 1)[1].split(":", 1)[0]
        with open(trf_path, "w") as f:
            f.write(_TRF)
        return types.SimpleNamespace(stdout=b"")
    return fake_run


def test_detect_emits_the_recipe_and_returns_parsed_magnitudes(monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(vidstab.proc, "run", _stub_detect_run(seen))
    trf = str(tmp_path / "t.trf")
    assert vidstab.detect("in.mp4", trf, dur=2.0) == [0.0, 10.0, 0.0]
    vf = seen["cmd"][seen["cmd"].index("-vf") + 1]
    assert vf == f"vidstabdetect=shakiness=8:result={trf}:fileformat=ascii"
    assert "-f" in seen["cmd"] and seen["cmd"][seen["cmd"].index("-f") + 1] == "null"


def test_detect_scales_its_timeout_to_the_input_length(monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(vidstab.proc, "run", _stub_detect_run(seen))
    vidstab.detect("in.mp4", str(tmp_path / "t.trf"), dur=500.0)
    assert seen["timeout"] == pytest.approx(500.0 * vidstab.SHAKE_TIMEOUT_REALTIME_MULTIPLE)


def test_detect_keeps_the_default_floor_for_a_short_input(monkeypatch, tmp_path):
    # A 2s segment must not get a 20s timeout — the floor keeps a short input at
    # proc's already-generous default rather than an unrealistically tight one.
    seen: dict = {}
    monkeypatch.setattr(vidstab.proc, "run", _stub_detect_run(seen))
    vidstab.detect("in.mp4", str(tmp_path / "t.trf"), dur=2.0)
    assert seen["timeout"] == vidstab.proc.DEFAULT_TIMEOUT_S


def test_mean_shake_normalises_by_frame_width():
    assert vidstab.mean_shake([0.0, 10.0, 0.0, 0.0], 1000) == pytest.approx(0.0025)


def test_mean_shake_of_nothing_is_zero_not_a_crash():
    # a .trf with a header and no Frame lines parses to []; dividing by len() there
    # would be a ZeroDivisionError inside an error path, hiding the real cause.
    assert vidstab.mean_shake([], 1000) == 0.0


def test_mean_shake_refuses_a_width_the_probe_could_not_supply():
    """A zero width is a FAILED PROBE, not a degenerate frame. The inherited
    `or 1` did not return a wrong magnitude, it returned a different unit — raw
    pixels named "fraction of frame width" — which then meets SHAKY_CLIP and
    culls footage that was never shaky. FootageClip already rejects a res with a
    zero side; this is the same refusal one layer earlier."""
    with pytest.raises(ValueError, match="frame width is 0.*probe_stream.*re-render"):
        vidstab.mean_shake([10.0], 0)


def test_mean_shake_refuses_a_broken_width_even_with_no_magnitudes():
    # order matters: the empty-mags early return must not shadow a broken width,
    # or the failed probe goes unreported on exactly the windows that carry no frames.
    with pytest.raises(ValueError, match="frame width is 0"):
        vidstab.mean_shake([], 0)
