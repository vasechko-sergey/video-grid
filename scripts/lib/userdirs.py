"""Where the runtime keeps its state, outside the code (design
docs/specs/2026-10-21-install-without-clone-design.md §1).

The code runs from wherever it is installed — Claude Code's version-keyed plugin
cache, or a developer's clone — and neither may hold state: a new version is a new
directory. So the venv, the weights and the per-machine config live in the XDG
directories, named here and nowhere else. Read at call time, not import time, so a
test (or a user) setting XDG_* sees its own directories.

bin/vg and setup.sh are shell and spell the same two roots; tests/test_userdirs.py
pins that they agree with this module.
"""
import hashlib
import os
from pathlib import Path

APP = "video-grid"
REPO = Path(__file__).resolve().parents[2]       # the code's own root, wherever installed


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or (Path.home() / fallback))


def config_dir() -> Path:
    """`${XDG_CONFIG_HOME:-~/.config}/video-grid` — ffmpeg.env, sourcing.env."""
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def data_dir() -> Path:
    """`${XDG_DATA_HOME:-~/.local/share}/video-grid` — the venv and the weights."""
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def venv_dir() -> Path:
    return data_dir() / "venv"


def models_dir() -> Path:
    """bin/vg's working directory: ultralytics downloads a bare model name into the
    working directory (packaging design §1.1), so this is where the weights land."""
    return data_dir() / "models"


REQUIREMENTS_STAMP = ".video-grid-requirements"   # setup.sh writes it into the venv


def requirements_digest(root: Path = REPO) -> str:
    """What a venv built by `root`'s setup.sh contains, as one sha256: requirements.txt,
    plus every `pip" install` line of setup.sh itself — demucs and torchreid with its
    named extras are installed OUTSIDE requirements.txt (a failed torch wheel must not
    abort the venv), so a digest of the file alone misses an update that changes them
    (the 2026-10-21 review). setup.sh and verify_runtime both call this, so the writer
    and the reader cannot hash two different things."""
    h = hashlib.sha256((root / "requirements.txt").read_bytes())
    for line in (root / "setup.sh").read_text().splitlines():
        if 'pip" install' in line:
            h.update(b"\n" + line.strip().encode())
    return h.hexdigest()


def launcher() -> Path:
    """This code's own bin/vg — what a dispatched judge is told to run, since its
    prompt is not a skill and nothing fills ${CLAUDE_PLUGIN_ROOT} into it."""
    return REPO / "bin" / "vg"


def config_file(name: str) -> Path | None:
    """The first of `<config_dir>/<name>` and the old in-tree `config/<name>` that
    exists, or None. The second keeps a clone set up before 0.27.0 working until
    setup.sh runs again — it moves the file over."""
    for p in (config_dir() / name, REPO / "config" / name):
        if p.is_file():
            return p
    return None


def read_key(name: str, key: str) -> str | None:
    """`KEY=value` out of config file `name`, or None."""
    p = config_file(name)
    if p is None:
        return None
    for line in p.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip() or None
    return None
