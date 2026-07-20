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


def _seek_order(cmd: list[str]) -> list[str]:
    """The §12 seek landmine: an input-side -ss on a re-encoded WINDOW puts black
    frames at the cut boundary.

    Comparison is exact-token throughout. Substring matching would flag `-sseof`,
    which starts with `-ss`, must precede `-i` by ffmpeg's own contract, and is a
    different option — a false positive on correct code, which for a guard that
    raises in production is worse than a miss.
    """
    if "-accurate_seek" in cmd:      # §12 names this as one of its three remedies
        return []
    if "-frames:v" in cmd:           # a still grab is not a cut (storyboard.py:30)
        return []
    if "-t" not in cmd and "-to" not in cmd:
        return []                    # not cutting a window ⇒ no cut boundary
    for i, a in enumerate(cmd):
        # Input-side iff some -i FOLLOWS this -ss — not "before the first -i".
        # ffmpeg binds -ss to the input after it, so `-i a -ss 5 -i b` seeks b.
        if a == "-ss" and "-i" in cmd[i + 1:]:
            return ["input-side -ss on a re-encoded window — design §12: this is the "
                    "black-frames-at-a-cut landmine. Move -ss after the -i it applies "
                    "to (output seek), or pass -accurate_seek if the input seek is "
                    "deliberate (see scripts/mix.py:193)."]
    return []


def check_argv(cmd: list[str]) -> list[str]:
    """Every §12 landmine violation in one ffmpeg argv. Empty list = clean."""
    out: list[str] = []
    for check in (_banned_filters, _seek_order):
        out.extend(check(cmd))
    return out
