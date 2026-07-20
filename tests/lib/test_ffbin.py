"""ffbin resolves the binaries the pipeline runs (design 2026-07-20 §3)."""
from pathlib import Path

import pytest

from scripts.lib import ffbin


def test_the_environment_variable_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG", "/from/env/ffmpeg")
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=/from/file/ffmpeg\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    assert ffbin.ffmpeg() == "/from/env/ffmpeg"


def test_the_config_file_beats_PATH(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=/from/file/ffmpeg\nFFPROBE=/from/file/ffprobe\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    assert ffbin.ffmpeg() == "/from/file/ffmpeg"
    assert ffbin.ffprobe() == "/from/file/ffprobe"


def test_a_missing_config_falls_through_to_PATH(monkeypatch, tmp_path):
    # the portability rung: setup.sh is macOS-only, so a Linux box has no config
    # file and import must still work (design §3).
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ffbin.ffmpeg() == "/usr/bin/ffmpeg"


def test_a_relative_PATH_hit_is_made_absolute(monkeypatch, tmp_path):
    """shutil.which returns a RELATIVE path when PATH carries a relative entry —
    a bare "." is enough. The contract says absolute, so passing which's result
    straight through would make it false as soon as anything chdir'd.

    Replaces a `.startswith("/")` assertion that could not fail here: with an
    absolute mock it could not tell "returned which's result" from "returned
    something absolute", and the realistic mutation it claimed to guard is
    already pinned by test_a_missing_config_falls_through_to_PATH.
    """
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"./{name}")
    assert ffbin.ffmpeg() == str(Path.cwd() / "ffmpeg")


def test_an_empty_value_in_the_file_is_not_a_path(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ffbin.ffmpeg() == "/usr/bin/ffmpeg"


def test_nothing_resolves_fails_loud_with_the_remedy(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="bash setup.sh"):
        ffbin.ffmpeg()
