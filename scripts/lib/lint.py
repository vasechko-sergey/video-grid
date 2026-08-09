"""Machine-check the §12 silent-corruption patterns in an emitted ffmpeg argv.

Pure: every function takes an argv list and returns a list of violation messages
(empty = clean). No I/O, no ffmpeg, no filesystem.

Two consumers, both wired up, and neither subsumes the other (design §2):
  * scripts/lib/proc.py's run() — an always-on guard that raises before
    subprocess.run, so it sees the ASSEMBLED command including the graphs that
    reach it through a splat (`*_filter_args(...)`), but only on paths some test
    actually exercises.
  * tests/lib/test_landmine_scan.py — an AST scan of scripts/ for banned filter
    names in string literals, complete for those names (they are never computed
    anywhere in this repo) including on paths no test reaches, but blind through
    those same splats.

check_argv's contract is list[str]. proc.run coerces every element with str()
before calling in: subprocess.run accepts os.PathLike, and the string tests below
raise TypeError on a Path rather than reporting a landmine.

A recurring trap in here, hit five times during review, and it cuts both ways.
ffmpeg's vocabulary is full of tokens that CONTAIN a shorter token — `boxcolor=`
contains `color=`, `-sseof` contains `-ss`, `seed=` and `pad=` contain `d=` — and
just as many that are CONTAINED BY a longer one: `testsrc` opens the filename
`testsrc.mp4`, and `-c:v` opens `-c:v:0`. The first direction produces false
positives, the second silent misses, and this guard raises in production, so
neither is affordable. Every comparison below is therefore anchored on BOTH
sides — an exact token via fullmatch, or a regex with a boundary at each end. A
bare `in` is almost always a bug here, and so is an unanchored prefix.

See docs/specs/2026-07-20-landmine-lint-design.md.
"""
import re

# design §12: lutrgb renders black frames. colorchannelmixer is the only colour op.
BANNED_FILTERS = ("lutrgb",)

# lavfi sources that never send end-of-stream unless bounded (design §12).
# Five is deliberately not exhaustive: ffmpeg has a dozen more infinite sources
# and every one reads clean here. Those are MISSES, the safe direction; widening
# is a later call, but the under-coverage is written down rather than implied
# away — in the landmine-lint design §5, which NAMES them and is the one place
# that does. This comment deliberately does not repeat the list: it carried a
# copy that had already drifted to ten of the twelve, and a stale roster of what
# a safety check misses is worse than a pointer to a current one.
SYNTH_SOURCES = ("color=", "testsrc", "anullsrc", "anoisesrc", "sine=")

# Where a filtergraph element ENDS: at the next filter (`,`), the next chain
# (`;`), or a label (`[`). One constant, two readers — _element slices on it and
# _SYNTH_RE anchors its right-hand boundary against it. Two copies of this set
# could drift into a checker that finds a source its own slicer cannot delimit.
_GRAPH_SEPS = ",;["

# A source NAME — not a parameter that merely ends in one, and not a FILENAME that
# merely begins with one. Both anchors are load-bearing.
#
# LEFT: the name must START an element — string start, or just after a `,` / `;` /
# `]`. Two distinct ways to be a parameter, and excluding only word characters
# catches just the first:
#   * `boxcolor=` / `fontcolor=` — glued to a letter (scripts/lib/draft.py:28).
#   * `:color=` / `=color=` — a parameter of drawbox, pad, anoisesrc. Live at
#     tests/integration/test_pan.py:27-31, which a word-only rule flags on correct
#     code. This guard raises in production, so a false positive breaks a render.
# `(?<![^,;\]])` succeeds at string start too: a negative lookbehind with nothing
# behind it has nothing to reject.
#
# RIGHT: and string start is exactly where the left anchor is WEAKEST, because an
# `-i` value is an element too. With no right anchor, `-i testsrc.mp4` reads as a
# source and RAISES — measured, one violation on a command with nothing wrong.
# Argv position would settle it (a source is only a source inside a filtergraph or
# an `-i` value, and a filename is neither), but a per-element scan cannot see argv
# position. What it CAN see is spelling: a real source is `name` or `name=params`,
# never `name.ext` — so the name must be followed by `=`, by an element separator,
# or by nothing at all. That distinction is exact, not heuristic, and it needs no
# guess about which argv slot the element occupies.
# The anchor applies only to the `=`-less entries: for `color=` and `sine=` the
# trailing `=` in the name already IS this requirement, spelled literally.
#
# `\s*` after the separator: every graph in this repo is built with `";".join(...)`
# so no whitespace appears today, but a future `"; ".join(...)` for readability
# would otherwise switch this check off silently. The source name is group 1 —
# the whitespace must not land in the reported name or in the element slice, and
# the right anchor is a lookahead so it stays out of group 1 too.
_SYNTH_RE = re.compile(r"(?<![^,;\]])\s*(" + "|".join(
    re.escape(s) if s.endswith("=")
    else re.escape(s) + r"(?=[=" + re.escape(_GRAPH_SEPS) + r"]|\Z)"
    for s in SYNTH_SOURCES) + r")")

# The source's own duration. `d=` cannot be a substring test: `seed=` contains it,
# and so do `speed=` and the literal `pad=`. `seed=` is a real parameter of
# anoisesrc, testsrc, gradients, cellauto, life and mandelbrot — so a bare
# `"d=" in element` reads scripts/mix.py:109's whoosh as bounded even with its
# `d=` deleted, i.e. it silently exempts the exact command this check exists for.
# Third instance of the contains-a-shorter-token trap in this module; hence a
# boundary, not paranoia.
_BOUND_RE = re.compile(r"(?<![A-Za-z0-9_])(?:d|duration)=")

# Copying the video stream means no re-encode, so no re-encode boundary to corrupt.
# ffmpeg spells that one instruction seven ways: `-c` / `-codec` for every stream,
# a `:v` specifier for the video one, `:v:N` to pick among several, and the
# deprecated `-vcodec` alias every tutorial still teaches. A tuple naming only the
# two forms this repo happens to emit raises on the other five — measured, on
# otherwise clean argvs, which re-opens the door §4.2 added this exemption to shut.
#
# fullmatch, never a prefix or endswith test: `-acodec` and `-codec:a` end in the
# same letters, copy AUDIO while the video is still re-encoded, and that is
# precisely when the seek landmine bites. Excluding them is the point, and it is
# why this is a regex rather than a wider string test.
#
# Two spellings are left out on purpose, both because matching them would EXEMPT a
# re-encoded window — a miss, and this module widens toward false positives from
# nobody: `-c:0 copy` (copy stream 0 by index) cannot be known from argv to mean
# video, and bare `-frames` below is the same shape.
_VIDEO_COPY_RE = re.compile(r"-(?:vcodec|(?:c|codec)(?::v(?::\d+)?)?)")

# A still grab is not a cut (storyboard.py:30) — the same spellings problem one
# option over. `-vframes 1` is the deprecated alias, `-frames:v:N` the stream-
# specifier form. Anchored on `:v`, not on the word `frames`, so `-frames:a` — an
# audio frame count, which grabs no still — cannot exempt a video window.
_STILL_GRAB_RE = re.compile(r"-(?:vframes|frames:v(?::\d+)?)")


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

    Any of the seven spellings of a video codec flag (see _VIDEO_COPY_RE) with
    `copy` in the value position. A copy-trim cannot produce the §12
    black-frames-at-a-re-encode failure because it does not re-encode — it can
    only cut on a keyframe. No site pairs a copy with a `-ss` window today, but
    assembly.py:84, draft.py:66/:71 and deliver.py:81 already pass `-c copy`, so
    the first one to gain a window would otherwise raise mid-render.
    """
    return any(_VIDEO_COPY_RE.fullmatch(a) and cmd[i + 1:i + 2] == ["copy"]
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
    if any(_STILL_GRAB_RE.fullmatch(a) for a in cmd):   # a still grab is not a cut
        return []
    if "-t" not in cmd and "-to" not in cmd:
        return []                    # not cutting a window ⇒ no cut boundary
    if _copies_video(cmd):
        return []                    # no re-encode ⇒ no re-encode boundary
    # Input-side iff some -i FOLLOWS this -ss — not "before the first -i".
    # ffmpeg binds -ss to the input after it, so `-i a -ss 5 -i b` seeks b.
    # Collected before reporting so each message can say "#n of m": a multi-seek
    # command otherwise yields byte-identical messages and the reader cannot tell
    # WHICH seek to move. Same reason _drawtext_font numbers its offenders.
    # cmd[i + 1] is safe to read: a trailing -ss has no -i after it, so it is
    # never flagged.
    seeks = [i for i, a in enumerate(cmd) if a == "-ss" and "-i" in cmd[i + 1:]]
    return [f"input-side -ss #{n} of {len(seeks)} (argv[{i}], seeking to "
            f"{cmd[i + 1]!r}) — design §12: this is the black-frames-at-a-cut "
            "landmine. Move -ss after the -i it applies to (output seek), or pass "
            "-accurate_seek if the input seek is deliberate (see scripts/mix.py:193)."
            for n, i in enumerate(seeks, 1)]


def _element(text: str, start: int) -> str:
    """The filtergraph element beginning at `start` — up to the next separator
    OUTSIDE a quoted option value.

    §4.3 asks about EACH source's own bound. Testing the whole argument lets a
    `d=` belonging to a neighbour (`afade=...:d=0.5`) exempt an unbounded source
    sitting beside it.

    Quote-blind found a live false positive, not a hypothetical one:
    reframe._xexpr emits a moving x=/y= as ffmpeg's `if(lt(it,T),then,else)`
    whenever a path has two or more knots — always, in practice, since the
    Douglas-Peucker simplifier keeps both endpoints. That `if(...)`'s own
    commas sit one syntax level down, inside the `'...'`-quoted option value,
    and a scan that treats every `,`/`;`/`[` alike stops there — discarding the
    REAL `:d=1:s=...:fps=...` that follows and reporting a fully correct
    zoompan as missing all three. Because proc.run's guard is always-on, that
    refused every real zoom render before ffmpeg ever ran (measured: all four
    tests/integration/test_zoom.py proofs failed on this ValueError, not on
    pixels).

    Tracked with a toggle, not a real parser: this repo's own emitters never
    put an apostrophe inside a quoted value (an ffmpeg eval expression has none
    of its own), so "flip on every `'`" is exact for every string this module
    sees today, not a heuristic that merely happens to hold. A separator before
    the first quote, or after the last one closes, behaves exactly as before —
    so this is a strict widening of what counts as "inside an element", never a
    narrowing, and every existing caller (_unbounded_source included) keeps
    its prior verdict on every quote-free argument.
    """
    end = len(text)
    in_quote = False
    for i in range(start, len(text)):
        c = text[i]
        if c == "'":
            in_quote = not in_quote
        elif not in_quote and c in _GRAPH_SEPS:
            end = i
            break
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


_ZOOMPAN_REQUIRED = ("s=", "fps=", "d=")

# `s=` cannot be a bare substring test: `fps=` ENDS in the same two characters,
# so `"s=" in body` reads a fully-specified `fps=30` as also satisfying `s=` and
# never reports a genuinely missing size — the exact hd720 silent-resize this
# check exists to catch, defeated by the one option an author is least likely to
# ALSO drop. The contains-a-shorter-token trap this module's header already
# warns about, found empirically the first time these tests ran rather than
# reasoned in advance (see the two now-red-then-fixed cases in test_lint.py).
# Anchored the same way _BOUND_RE is: a negative lookbehind for a word
# character, so a match must START a `:`-delimited option rather than land
# inside one — sufficient here because zoompan's own vocabulary (z/x/y/d/s/fps)
# has exactly one such collision, and this is it.
_ZOOMPAN_RE = {k: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(k))
    for k in _ZOOMPAN_REQUIRED}


def _zoompan_defaults(cmd: list[str]) -> list[str]:
    """§12: zoompan's three defaults each corrupt SILENTLY (design 2026-08-08 §8).

    `s` defaults to hd720 — the episode is resized to 1280x720. `fps` defaults to
    25 — a 60fps clip is resampled. `d` defaults to 90 — every input frame is held
    for 90 output frames. None of the three errors; all three ship wrong pixels.

    Split on the filter name so EACH zoompan is judged on its own segment, and
    bound that segment at the next graph separator so a neighbour's `fps=` cannot
    exempt it — the same two rules _drawtext_font and _unbounded_source follow.

    What this CANNOT check is the fourth trap: zoompan clamps a `z` below 1 to 1
    byte-identically, and z is a runtime expression, not a literal. Its detector
    is the pixel proof in tests/integration/test_zoom.py.
    """
    out: list[str] = []
    for a in cmd:
        segs = a.split("zoompan=")[1:]
        for n, seg in enumerate(segs, 1):
            body = _element(seg, 0)
            missing = [k for k in _ZOOMPAN_REQUIRED if not _ZOOMPAN_RE[k].search(body)]
            if missing:
                out.append(
                    f"zoompan #{n} of {len(segs)} omits {', '.join(missing)} (segment: "
                    f"{('zoompan=' + seg)[:48]!r}) in {a!r} — design §12: zoompan's "
                    "defaults are s=hd720, fps=25 and d=90, each of which silently "
                    "resizes, resamples or stalls the episode. Pass all three explicitly.")
    return out


def check_argv(cmd: list[str]) -> list[str]:
    """Every §12 landmine violation in one ffmpeg argv. Empty list = clean."""
    out: list[str] = []
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font,
                  _zoompan_defaults):
        out.extend(check(cmd))
    return out
