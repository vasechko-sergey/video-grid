"""Loud subprocess wrapper: ffmpeg/ffprobe failures surface stderr (hard rule §12)."""
import subprocess


# Generous on purpose: a real 4K encode runs for minutes, and this ceiling exists
# to catch a command that can NEVER finish, not to police a slow one. An unbounded
# synthesized ffmpeg source (`color`/`testsrc` with no `d=`) never sends EOF, so
# the encode runs forever; without a timeout that HANGS the caller — measured at
# 90s-and-killed against a 0.8s normal run — and this machine has no timeout(1) to
# bound it from outside. An unbounded wait is not a test result.
DEFAULT_TIMEOUT_S = 900.0


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run with check+capture+timeout; on failure re-raise with stderr tail.

    Keeps the last 30 lines of stderr — enough to see ffmpeg's actual error
    ("No such file or directory", "width not divisible by 2", ...) instead of
    a bare exit code.

    A caller that genuinely needs longer passes its own `timeout=`; passing
    `timeout=None` restores the old unbounded behaviour and should be rare.
    """
    kwargs.setdefault("check", True)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT_S)
    try:
        return subprocess.run(cmd, **kwargs)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"{cmd[0]!r} not found on PATH — install it "
            "(ffmpeg/ffprobe: `brew install ffmpeg`)") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"command timed out after {e.timeout:g}s: {' '.join(map(str, cmd))}\n"
            "a filtergraph that cannot terminate is the usual cause — an unbounded "
            "synthesized source (`color`/`testsrc` with no `d=`) never sends "
            "end-of-stream, so ffmpeg encodes until something kills it") from e
    except subprocess.CalledProcessError as e:
        err = e.stderr or b""
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        tail = "\n".join(err.strip().splitlines()[-30:])
        raise RuntimeError(
            f"command failed (exit {e.returncode}): {' '.join(map(str, cmd))}\n"
            f"--- stderr tail ---\n{tail}") from e
