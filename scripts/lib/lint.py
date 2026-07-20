"""Machine-check the §12 silent-corruption patterns in an emitted ffmpeg argv.

Pure: every function takes an argv list and returns a list of violation messages
(empty = clean). No I/O, no ffmpeg, no filesystem.

Two consumers, and neither subsumes the other (design §2):
  * proc.run's runtime guard — sees the ASSEMBLED command, including the graphs
    that reach it through a splat (`*_filter_args(...)`), but only on paths some
    test actually exercises.
  * tests/lib/test_landmine_scan.py — a literal scan of scripts/, complete for
    filter NAMES (they are never computed anywhere in this repo) including on
    paths no test reaches, but blind through those same splats.

See docs/specs/2026-07-20-landmine-lint-design.md.
"""
import re

# design §12: lutrgb renders black frames. colorchannelmixer is the only colour op.
BANNED_FILTERS = ("lutrgb",)


def _banned_filters(cmd: list[str]) -> list[str]:
    return [f"banned filter {b!r} in {a!r} — design §12: lutrgb renders black frames. "
            f"Use colorchannelmixer instead (scripts/lib/color.py mixer_arg builds it)."
            for a in cmd for b in BANNED_FILTERS if b in a]


def check_argv(cmd: list[str]) -> list[str]:
    """Every §12 landmine violation in one ffmpeg argv. Empty list = clean."""
    out: list[str] = []
    for check in (_banned_filters,):
        out.extend(check(cmd))
    return out
