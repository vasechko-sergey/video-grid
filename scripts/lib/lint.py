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

# lavfi sources that never send end-of-stream unless bounded (design §12).
SYNTH_SOURCES = ("color=", "testsrc", "anullsrc", "anoisesrc", "sine=")

# A source NAME, not a parameter that merely ends in one. The name must START a
# filtergraph element: string start, or just after a `,` / `;` / `]`. Two distinct
# ways to be a parameter, and excluding only word characters catches just the first:
#   * `boxcolor=` / `fontcolor=` — glued to a letter (scripts/lib/draft.py:28).
#   * `:color=` / `=color=` — a parameter of drawbox, pad, anoisesrc. Live at
#     tests/integration/test_pan.py:27-31, which a word-only rule flags on correct
#     code. This guard raises in production, so a false positive breaks a render.
# `(?<![^,;\]])` succeeds at string start too: a negative lookbehind with nothing
# behind it has nothing to reject.
_SYNTH_RE = re.compile(r"(?<![^,;\]])(?:" + "|".join(
    re.escape(s) for s in SYNTH_SOURCES) + r")")


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


def _unbounded_source(cmd: list[str]) -> list[str]:
    """The §12 infinite-source hang: an unbounded `color`/`testsrc`/`anullsrc`
    never sends end-of-stream, so the encode runs until something kills it —
    measured at 90s-and-killed against a 0.8s normal run.

    Bounded means EITHER an output `-t`/`-to` OR a source-side `d=`/`duration=`.
    Both stop the hang. Only `-t` also fixes the LENGTH (a `d=` frame count need
    not match a real input's — 96 rendered against a source's 95), and that half
    stays pinned by test_reframe_bounds_every_layout_to_the_source_length. Two
    failures, two guards; do not collapse them.
    """
    if "-t" in cmd or "-to" in cmd:
        return []
    out = []
    for a in cmd:
        m = _SYNTH_RE.search(a)
        if m and "d=" not in a and "duration=" not in a:
            out.append(
                f"unbounded synthesized source {m.group()!r} in {a!r} — design §12: "
                "a lavfi source with no duration never sends end-of-stream, so the "
                "encode runs until it is killed. Bound the OUTPUT with -t (preferred: "
                "it also fixes the frame count) or give the source a d=.")
    return out


def _drawtext_font(cmd: list[str]) -> list[str]:
    """§12: drawtext without an explicit fontfile= fails, or picks garbage on
    macOS — the filter and the font are decoupled.

    Split on the filter name so EACH drawtext is judged on its own segment.
    scripts/lib/titles.py:152 joins per-title pieces with ',', so a whole-string
    test would pass a chain in which only the first piece carries a font.
    """
    out = []
    for a in cmd:
        for seg in a.split("drawtext=")[1:]:
            if "fontfile=" not in seg:
                out.append(
                    f"drawtext without fontfile= in {a!r} — design §12: drawtext and "
                    "its font are decoupled, so with no explicit path it fails or "
                    "picks a garbage face on macOS. Resolve one with "
                    "scripts/lib/fonts.py resolve_font() and pass fontfile='<path>'.")
    return out


def check_argv(cmd: list[str]) -> list[str]:
    """Every §12 landmine violation in one ffmpeg argv. Empty list = clean."""
    out: list[str] = []
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font):
        out.extend(check(cmd))
    return out
