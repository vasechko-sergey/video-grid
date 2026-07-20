"""ffbin resolves the binaries the pipeline runs (design 2026-07-20 §3)."""
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


def test_the_PATH_rung_yields_an_absolute_path_not_a_bare_name(monkeypatch, tmp_path):
    # shutil.which, never a bare "ffmpeg" — a log must name the binary that ran.
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/opt/x/{name}")
    assert ffbin.ffmpeg().startswith("/")


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
