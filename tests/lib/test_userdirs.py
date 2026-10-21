"""lib/userdirs — where the runtime's state lives (design 2026-10-21 §1)."""
import re
from pathlib import Path

import pytest

from scripts.lib import userdirs

REPO = Path(__file__).resolve().parents[2]


def test_the_defaults_are_the_xdg_fallbacks(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = Path.home()
    assert userdirs.data_dir() == home / ".local/share/video-grid"
    assert userdirs.config_dir() == home / ".config/video-grid"
    assert userdirs.venv_dir() == home / ".local/share/video-grid/venv"
    assert userdirs.models_dir() == home / ".local/share/video-grid/models"


def test_xdg_variables_move_both_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    assert userdirs.models_dir() == tmp_path / "d" / "video-grid" / "models"
    assert userdirs.config_dir() == tmp_path / "c" / "video-grid"


def test_bin_vg_and_setup_spell_the_same_directories():
    """Three spellings of two directories: shell in bin/vg and setup.sh, Python here.
    A drift between them sends the weights or the venv somewhere the others never
    look, and nothing else would notice."""
    vg = (REPO / "bin" / "vg").read_text()
    setup = (REPO / "setup.sh").read_text()
    data = '"${XDG_DATA_HOME:-$HOME/.local/share}/video-grid"'
    assert f"DATA={data}" in vg and 'PY="$DATA/venv/bin/python"' in vg
    assert 'cd "$DATA/models"' in vg
    assert f"VG_DATA={data}" in setup
    assert 'VENV="$VG_DATA/venv"' in setup and 'MODELS_DIR="$VG_DATA/models"' in setup
    assert 'VG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/video-grid"' in setup
    assert userdirs.APP == "video-grid"
    assert userdirs.venv_dir().relative_to(userdirs.data_dir()) == Path("venv")
    assert userdirs.models_dir().relative_to(userdirs.data_dir()) == Path("models")


def test_the_users_config_beats_an_old_clones_in_tree_file(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setattr(userdirs, "REPO", tmp_path / "code")
    assert userdirs.config_file("ffmpeg.env") is None
    old = tmp_path / "code" / "config"
    old.mkdir(parents=True)
    (old / "ffmpeg.env").write_text("FFMPEG=/old\n")
    assert userdirs.read_key("ffmpeg.env", "FFMPEG") == "/old"
    new = tmp_path / "c" / "video-grid"
    new.mkdir(parents=True)
    (new / "ffmpeg.env").write_text("FFMPEG=/new\nFFPROBE=\n")
    assert userdirs.read_key("ffmpeg.env", "FFMPEG") == "/new"
    assert userdirs.read_key("ffmpeg.env", "FFPROBE") is None      # empty is not a value
    assert userdirs.read_key("ffmpeg.env", "OTHER") is None


def test_the_launcher_is_this_codes_own():
    assert userdirs.launcher() == REPO / "bin" / "vg"


def test_the_requirements_digest_sees_setups_own_pip_lines_not_its_comments(tmp_path):
    """demucs and torchreid are installed outside requirements.txt, so an update that
    changes them must move the digest too (the review's M5) — and a comment must not."""
    (tmp_path / "requirements.txt").write_text("numpy\n")
    (tmp_path / "setup.sh").write_text('# install\n"$VENV/bin/pip" install demucs\n')
    first = userdirs.requirements_digest(tmp_path)
    (tmp_path / "setup.sh").write_text('# install it, really\n"$VENV/bin/pip" install demucs\n')
    assert userdirs.requirements_digest(tmp_path) == first
    (tmp_path / "setup.sh").write_text('"$VENV/bin/pip" install demucs tensorboard\n')
    assert userdirs.requirements_digest(tmp_path) != first
    (tmp_path / "setup.sh").write_text('"$VENV/bin/pip" install demucs\n')
    (tmp_path / "requirements.txt").write_text("numpy\nscipy\n")
    assert userdirs.requirements_digest(tmp_path) != first
