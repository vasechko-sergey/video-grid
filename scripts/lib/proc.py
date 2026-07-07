"""Loud subprocess wrapper: ffmpeg/ffprobe failures surface stderr (hard rule §12)."""
import subprocess


def run(cmd, **kwargs):
    """subprocess.run with check+capture; on failure re-raise with stderr tail.

    Keeps the last 30 lines of stderr — enough to see ffmpeg's actual error
    ("No such file or directory", "width not divisible by 2", ...) instead of
    a bare exit code.
    """
    kwargs.setdefault("check", True)
    kwargs.setdefault("capture_output", True)
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.CalledProcessError as e:
        err = e.stderr or b""
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        tail = "\n".join(err.strip().splitlines()[-30:])
        raise RuntimeError(
            f"command failed (exit {e.returncode}): {' '.join(map(str, cmd))}\n"
            f"--- stderr tail ---\n{tail}") from e
