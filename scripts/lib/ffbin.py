"""Resolve the ffmpeg/ffprobe binaries the pipeline runs (design 2026-07-20 §3).

setup.sh installs a full-featured ffmpeg (drawtext + vidstab) and records where it
put it, because homebrew's ffmpeg-full is keg-only and never lands on PATH. This
module reads that record.

The PATH is frozen at install time; the FILTERS are probed at runtime, every time
(design §4). A stale path fails loud — the file is gone and subprocess raises. A
stale capability record would fail SILENTLY: the code would skip its own gate on a
false premise, which is the §12 failure shape this repo exists to avoid.
"""
import os
import shutil
from pathlib import Path

from scripts.lib import proc

# repo-root/config — mirrors catalog._SOURCING_ENV, and gitignored for the same
# reason: the resolved path is per-machine, not per-checkout.
_FFMPEG_ENV = Path(__file__).resolve().parents[2] / "config" / "ffmpeg.env"


def _from_file(key: str) -> str | None:
    """`KEY=value` out of config/ffmpeg.env, or None. Same shape as sourcing.env."""
    if not _FFMPEG_ENV.exists():
        return None
    for line in _FFMPEG_ENV.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip() or None
    return None


def _resolve(key: str, binary: str) -> str:
    """$KEY -> config/ffmpeg.env -> PATH. Always an ABSOLUTE path.

    The PATH rung goes through shutil.which rather than returning a bare name, so
    a log or an error message always names the binary that actually ran — the
    machine may carry two ffmpeg builds and mixing them is the thing worth seeing.
    """
    for candidate in (os.environ.get(key), _from_file(key)):
        if candidate:
            return candidate
    found = shutil.which(binary)
    if found:
        return found
    raise ValueError(
        f"cannot find {binary}: ${key} is unset, {_FFMPEG_ENV} has no {key}=, and "
        f"{binary} is not on PATH — run `bash setup.sh`, which installs ffmpeg-full "
        f"and records where it landed")


def ffmpeg() -> str:
    return _resolve("FFMPEG", "ffmpeg")


def ffprobe() -> str:
    return _resolve("FFPROBE", "ffprobe")
