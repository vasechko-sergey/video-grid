"""Resolve the ffmpeg/ffprobe binaries the pipeline runs (design 2026-07-20 §3).

setup.sh installs a full-featured ffmpeg (drawtext + vidstab) and records where it
put it, because homebrew's ffmpeg-full is keg-only and never lands on PATH. This
module reads that record: `<config_dir>/ffmpeg.env` since 0.27.0 (lib/userdirs —
the code may run from a plugin cache that holds no state), else the old in-tree
`config/ffmpeg.env` of a clone set up before it.

The PATH is frozen at install time; the FILTERS are probed at runtime, every time
(design §4). A stale path fails loud — the file is gone and subprocess raises. A
stale capability record would fail SILENTLY: the code would skip its own gate on a
false premise, which is the §12 failure shape this repo exists to avoid.
"""
import os
import shutil

from scripts.lib import proc, userdirs

ENV_FILE = "ffmpeg.env"


def _from_file(key: str) -> str | None:
    """`KEY=value` out of the recorded ffmpeg.env, or None. Same shape as sourcing.env."""
    return userdirs.read_key(ENV_FILE, key)


def _resolve(key: str, binary: str) -> str:
    """$KEY -> the recorded ffmpeg.env -> PATH. Always an ABSOLUTE path.

    The PATH rung goes through shutil.which rather than returning a bare name, so
    a log or an error message always names the binary that actually ran — the
    machine may carry two ffmpeg builds and mixing them is the thing worth seeing.

    abspath on which's result is not belt-and-braces: shutil.which returns a
    RELATIVE path when PATH carries a relative entry (a bare "." is enough), and
    passing that through would make this docstring's promise false the moment the
    process changed directory.
    """
    for candidate in (os.environ.get(key), _from_file(key)):
        if candidate:
            return candidate
    found = shutil.which(binary)
    if found:
        return os.path.abspath(found)
    raise ValueError(
        f"cannot find {binary}: ${key} is unset, {userdirs.config_dir() / ENV_FILE} "
        f"has no {key}=, and {binary} is not on PATH — run setup (/video-grid:setup, "
        f"or `bash setup.sh`), which installs ffmpeg-full and records where it landed")


def ffmpeg() -> str:
    return _resolve("FFMPEG", "ffmpeg")


def ffprobe() -> str:
    return _resolve("FFPROBE", "ffprobe")


def has_filter(name: str) -> bool:
    """Is `name` in the resolved ffmpeg's filter list?

    The ONE place this question is asked. Four sites used to ask it four ways —
    two production gates and three test guards — and the moment production moved
    to a different binary than the guards probed, those guards would have skipped
    forever against a working pipeline: a green suite with three integration tests
    silently uncovered (design §5).

    Deliberately uncached: see design §4 on why a stale answer is worth more than
    the 50ms it would save.
    """
    out = proc.run([ffmpeg(), "-hide_banner", "-filters"]).stdout
    return name.encode() in out


def require_filter(name: str, remedy: str) -> None:
    """Fail loud when the resolved build lacks `name`, naming the binary."""
    if not has_filter(name):
        raise ValueError(f"{ffmpeg()} has no {name} filter — {remedy}")
