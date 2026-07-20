"""Machine-check the §12 silent-corruption patterns in an emitted ffmpeg argv.

Pure: every function takes an argv list and returns a list of violation messages
(empty = clean). No I/O, no ffmpeg, no filesystem.

Two consumers are PLANNED, and neither will subsume the other (design §2).
Neither is wired up yet — this module is currently called only by its own tests:
  * proc.run's runtime guard (Task 5) — will see the ASSEMBLED command, including
    the graphs that reach it through a splat (`*_filter_args(...)`), but only on
    paths some test actually exercises.
  * tests/lib/test_landmine_scan.py (Task 6) — a literal scan of scripts/,
    complete for filter NAMES (they are never computed anywhere in this repo)
    including on paths no test reaches, but blind through those same splats.

A recurring trap in here, hit three times during review: ffmpeg's vocabulary is
full of tokens that CONTAIN a shorter token. `boxcolor=` contains `color=`,
`-sseof` contains `-ss`, `seed=` and `pad=` contain `d=`. Every comparison below
is therefore anchored — exact token, or a regex with a boundary. A bare `in` is
almost always a bug here.

See docs/specs/2026-07-20-landmine-lint-design.md.
"""
import re

# design §12: lutrgb renders black frames. colorchannelmixer is the only colour op.
BANNED_FILTERS = ("lutrgb",)

# lavfi sources that never send end-of-stream unless bounded (design §12).
# Five is deliberately not exhaustive — design §5 lists the uncovered infinite
# sources (nullsrc, aevalsrc, smptebars, gradients, cellauto, life, mandelbrot,
# allrgb, allyuv, haldclutsrc). Those are MISSES, the safe direction; widening is
# a later call, but the under-coverage is written down rather than implied away.
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
# `\s*` after the separator: every graph in this repo is built with `";".join(...)`
# so no whitespace appears today, but a future `"; ".join(...)` for readability
# would otherwise switch this check off silently. The source name is group 1 —
# the whitespace must not land in the reported name or in the element slice.
_SYNTH_RE = re.compile(r"(?<![^,;\]])\s*(" + "|".join(
    re.escape(s) for s in SYNTH_SOURCES) + r")")

# The source's own duration. `d=` cannot be a substring test: `seed=` contains it,
# and so do `speed=` and the literal `pad=`. `seed=` is a real parameter of
# anoisesrc, testsrc, gradients, cellauto, life and mandelbrot — so a bare
# `"d=" in element` reads scripts/mix.py:109's whoosh as bounded even with its
# `d=` deleted, i.e. it silently exempts the exact command this check exists for.
# Third instance of the contains-a-shorter-token trap in this module; hence a
# boundary, not paranoia.
_BOUND_RE = re.compile(r"(?<![A-Za-z0-9_])(?:d|duration)=")

# Copying the video stream means no re-encode, so no re-encode boundary to corrupt.
# `-c:a copy` is deliberately NOT here: it copies audio while the video is still
# re-encoded, which is precisely when the seek landmine bites.
_VIDEO_COPY_FLAGS = ("-c", "-c:v")


def _banned_filters(cmd: list[str]) -> list[str]:
    """§12: lutrgb renders black frames — a wrong-pixels failure with no traceback.

    Substring matching is correct here and nowhere else in this module: `lutrgb`
    is a whole filter name that no longer token contains, and it may appear
    anywhere inside a filtergraph argument rather than as its own argv token.
    """
    return [f"banned filter {b!r} in {a!r} — design §12: lutrgb renders black frames. "
            f"Use colorchannelmixer instead (scripts/lib/color.py mixer_arg builds it)."
            for a in cmd for b in BANNED_FILTERS if b in a]


def _copies_video(cmd: list[str]) -> bool:
    """True when the video stream is stream-copied rather than re-encoded.

    Exact tokens in the value position: `-c copy` / `-c:v copy`. A copy-trim
    cannot produce the §12 black-frames-at-a-re-encode failure because it does
    not re-encode — it can only cut on a keyframe. No site pairs a copy with a
    `-ss` window today, but assembly.py:84, draft.py:66/:71 and deliver.py:81
    already pass `-c copy`, so the first one to gain a window would otherwise
    raise mid-render.
    """
    return any(a in _VIDEO_COPY_FLAGS and cmd[i + 1:i + 2] == ["copy"]
               for i, a in enumerate(cmd))


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
    if _copies_video(cmd):
        return []                    # no re-encode ⇒ no re-encode boundary
    out: list[str] = []
    for i, a in enumerate(cmd):
        # Input-side iff some -i FOLLOWS this -ss — not "before the first -i".
        # ffmpeg binds -ss to the input after it, so `-i a -ss 5 -i b` seeks b.
        if a == "-ss" and "-i" in cmd[i + 1:]:
            out.append("input-side -ss on a re-encoded window — design §12: this is the "
                       "black-frames-at-a-cut landmine. Move -ss after the -i it applies "
                       "to (output seek), or pass -accurate_seek if the input seek is "
                       "deliberate (see scripts/mix.py:193).")
    return out


def _element(text: str, start: int) -> str:
    """The filtergraph element beginning at `start` — up to the next separator.

    §4.3 asks about EACH source's own bound. Testing the whole argument lets a
    `d=` belonging to a neighbour (`afade=...:d=0.5`) exempt an unbounded source
    sitting beside it.
    """
    end = len(text)
    for sep in (",", ";", "["):
        i = text.find(sep, start)
        if i != -1:
            end = min(end, i)
    return text[start:end]


def _unbounded_source(cmd: list[str]) -> list[str]:
    """The §12 infinite-source hang: an unbounded `color`/`testsrc`/`anullsrc`/
    `anoisesrc`/`sine` never sends end-of-stream, so the encode runs until
    something kills it — measured at 90s-and-killed against a 0.8s normal run.

    Bounded means EITHER an output `-t`/`-to` OR a source-side `d=`/`duration=`.
    Both stop the hang. Only `-t` also fixes the LENGTH (a `d=` frame count need
    not match a real input's — 96 rendered against a source's 95), and that half
    stays pinned by test_reframe_bounds_every_layout_to_the_source_length. Two
    failures, two guards; do not collapse them.

    Every source is judged on its OWN element (finditer, not search): one graph
    may hold several, and a bound on one says nothing about the next.
    """
    if "-t" in cmd or "-to" in cmd:
        return []
    out: list[str] = []
    for a in cmd:
        for m in _SYNTH_RE.finditer(a):
            if _BOUND_RE.search(_element(a, m.start(1))):
                continue
            out.append(
                f"unbounded synthesized source {m.group(1)!r} in {a!r} — design §12: "
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

    A literal `drawtext=` inside a quoted VALUE would be miscounted as a second
    filter. Unreachable today only because both producers (draft.py:28,
    titles.py:148) route free text through `textfile=` rather than `text=` — and
    they do that for filtergraph escaping, not for this. If a producer ever
    inlines `text=`, this needs a real parser.
    """
    out: list[str] = []
    for a in cmd:
        segs = a.split("drawtext=")[1:]
        for n, seg in enumerate(segs, 1):
            if "fontfile=" not in seg:
                # Name WHICH one: a six-title chain quoting only the whole -vf
                # argument tells the reader nothing about where to look.
                out.append(
                    f"drawtext #{n} of {len(segs)} has no fontfile= (segment: "
                    f"{('drawtext=' + seg)[:48]!r}) in {a!r} — design §12: drawtext "
                    "and its font are decoupled, so with no explicit path it fails "
                    "or picks a garbage face on macOS. Resolve one with "
                    "scripts/lib/fonts.py resolve_font() and pass fontfile='<path>'.")
    return out


def check_argv(cmd: list[str]) -> list[str]:
    """Every §12 landmine violation in one ffmpeg argv. Empty list = clean."""
    out: list[str] = []
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font):
        out.extend(check(cmd))
    return out
