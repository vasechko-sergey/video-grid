"""Loud subprocess wrapper: ffmpeg/ffprobe failures surface stderr (hard rule §12)."""
import subprocess

from scripts.lib import lint


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
    # Always on, never behind an env flag. The obvious argument for gating this is
    # "keep production fast" — a handful of string scans over a ~20-element list,
    # against a command that runs for seconds to minutes. The saving is
    # unmeasurable and a guard that is off in production does not protect
    # production. Refusing to run a command that will silently corrupt the output
    # beats running it (design §3).
    #
    # Before the try: block on purpose, so it cannot disturb the FileNotFoundError
    # / TimeoutExpired / CalledProcessError handling below. Those RuntimeErrors
    # say the ENVIRONMENT failed; this ValueError says the CALLER is wrong.
    #
    # Every command is inspected, not just those whose argv[0] is "ffmpeg":
    # scripts/draft.py:24 passes the binary as a parameter, which is the template
    # for a future bypass of any check keyed on argv[0] (design §5).
    #
    # str() for the CHECK only — `cmd` itself goes to subprocess.run untouched.
    # subprocess accepts os.PathLike natively and this repo passes Paths around
    # everywhere, but check_argv's `in`/regex tests raise TypeError on a Path.
    # Without the coercion `proc.run(["ffmpeg", "-i", src_path])` would die with
    # a traceback pointing at the lint instead of running, or instead of the
    # ValueError-with-a-remedy this guard exists to give. The error paths below
    # already assume non-str elements are legal (`' '.join(map(str, cmd))`).
    problems = lint.check_argv([str(a) for a in cmd])
    if problems:
        raise ValueError(
            "refusing to run a command carrying a design §12 landmine:\n  "
            + "\n  ".join(problems)
            + f"\ncommand: {' '.join(map(str, cmd))}")
    kwargs.setdefault("check", True)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT_S)
    try:
        return subprocess.run(cmd, **kwargs)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"{cmd[0]!r} not found on PATH — install it "
            "(ffmpeg/ffprobe: `bash setup.sh`, which installs ffmpeg-full and "
            "records where it landed; `brew install ffmpeg` gets the slim build)") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"command timed out after {e.timeout:g}s: {' '.join(map(str, cmd))}\n"
            "two causes are common: a filtergraph that cannot terminate — an "
            "unbounded synthesized source (`color`/`testsrc` with no `d=`) never "
            "sends end-of-stream, so ffmpeg encodes until something kills it — or "
            "a genuinely long pass over raw footage (e.g. vidstabdetect over an "
            "un-extracted clip) that simply needs more time than this default. If "
            "it's the latter, pass an explicit `timeout=` at the call site, scaled "
            "to the input's length, rather than raising this default") from e
    except subprocess.CalledProcessError as e:
        err = e.stderr or b""
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        tail = "\n".join(err.strip().splitlines()[-30:])
        raise RuntimeError(
            f"command failed (exit {e.returncode}): {' '.join(map(str, cmd))}\n"
            f"--- stderr tail ---\n{tail}") from e
