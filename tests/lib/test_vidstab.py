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
    """Design §4/§5. `shakiness=8` is the one non-default in the recipe — accuracy
    is 15 by default and optzoom is 1 by default, so writing them would perform a
    choice that was never made and a later reader could not tell the two apart.

    This is pinned rather than left to review because the constant is SHARED with
    intake specifically so both report the same measurement (§5). Anyone adding a
    knob here silently re-scales FOOTAGE.md's shake column.
    """
    assert vidstab.DETECT_ARGS == "shakiness=8"
