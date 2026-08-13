import pytest

from scripts import reframe
from scripts.lib import lint


def test_check_argv_passes_a_clean_command():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "colorchannelmixer=rr=1.0", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_banned_filter_lutrgb_is_reported():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "lutrgb=r=val*1.1", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "lutrgb" in msgs[0]


def test_the_lutrgb_message_names_the_replacement_not_just_the_ban():
    """A ban with no remedy makes the next author guess. §12 names the replacement."""
    cmd = ["ffmpeg", "-vf", "lutrgb=r=val", "out.mp4"]
    assert "colorchannelmixer" in lint.check_argv(cmd)[0]


def test_colorchannelmixer_is_not_mistaken_for_a_banned_filter():
    cmd = ["ffmpeg", "-i", "a.mp4", "-vf", "colorchannelmixer=rr=0.9:gg=1.0:bb=1.1", "o.mp4"]
    assert lint.check_argv(cmd) == []


# --- the -ss seek-order check -------------------------------------------------
# Design §4.2. Each exemption gets its own test, so a mutation deleting any single
# condition turns exactly one of these red.

def test_input_side_ss_on_a_re_encoded_window_is_reported():
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0",
           "-c:v", "libx264", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "-ss" in msgs[0]


def test_output_side_ss_on_a_window_is_clean():
    """-ss AFTER the -i it applies to is the fix, not the landmine."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-ss", "5.0", "-t", "2.0",
           "-c:v", "libx264", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_accurate_seek_exempts_an_input_side_window():
    """§12 lists three remedies and -accurate_seek is one of them (scripts/mix.py)."""
    cmd = ["ffmpeg", "-y", "-accurate_seek", "-ss", "5.0", "-i", "a.wav",
           "-t", "2.0", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_a_still_grab_is_exempt_because_it_is_not_a_cut():
    """scripts/storyboard.py:30 — grabbing one still deep inside a clip is not a cut.

    The -t carries no weight for storyboard (which passes none) and is here only to
    ISOLATE this exemption: without it the not-a-window early return answers first,
    the -frames:v condition is never consulted, and deleting that condition leaves
    this test green — i.e. the test would pin nothing. The window-less storyboard
    shape is already pinned by the test below.
    """
    cmd = ["ffmpeg", "-y", "-ss", "1.2", "-i", "a.mp4", "-t", "0.5",
           "-frames:v", "1", "f.png"]
    assert lint.check_argv(cmd) == []


@pytest.mark.parametrize("flag", ["-frames:v", "-vframes", "-frames:v:0"])
def test_every_spelling_of_a_still_grab_is_exempt(flag):
    """Same class as the copy-flag spellings, same measured false positive:
    `-vframes 1` is the deprecated alias every ffmpeg tutorial still teaches, so
    a still grab written that way and carrying a `-t` raised on correct code.

    The `-t` isolates this exemption — without it the not-a-window early return
    answers first and the condition under test is never consulted.
    """
    cmd = ["ffmpeg", "-y", "-ss", "1.2", "-i", "a.mp4", "-t", "0.5", flag, "1", "f.png"]
    assert lint.check_argv(cmd) == []


def test_an_audio_frame_count_is_not_a_still_grab():
    """`-frames:a` is the same option family aimed at audio: it grabs no still,
    so it must not exempt a re-encoded video window. Pins that the widening is
    anchored on `:v` rather than on the word `frames`."""
    cmd = ["ffmpeg", "-y", "-ss", "1.2", "-i", "a.mp4", "-t", "0.5", "-frames:a", "1",
           "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_an_open_ended_input_seek_is_exempt_because_it_is_not_a_window():
    """No -t/-to: the command is not cutting a window, so the cut-boundary
    landmine cannot apply."""
    cmd = ["ffmpeg", "-y", "-ss", "1.2", "-i", "a.mp4", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_sseof_is_never_mistaken_for_ss():
    """-sseof contains '-ss' as a prefix, MUST precede -i, and is a different
    option. A substring match flags it — that is a bug in the lint, not a finding.
    Live example: scripts/check_episode.py:24."""
    cmd = ["ffmpeg", "-y", "-sseof", "-0.5", "-i", "a.mp4", "-t", "0.5",
           "-c:v", "libx264", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_ss_is_input_side_when_any_i_follows_it_not_only_the_first():
    """ffmpeg binds -ss to the input AFTER it. In `-i a -ss 5 -i b` the seek is
    input-side for b; a 'before the FIRST -i' test reads it as an output seek and
    misses the violation. scripts/mix.py:207 already builds multi-input commands."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-ss", "5.0", "-i", "b.mp4",
           "-t", "2.0", "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_a_stream_copy_window_is_exempt():
    """A copy-trim cannot produce the landmine: with no re-encode there is no
    re-encode boundary to put black frames at — it can only cut on a keyframe.
    No site pairs `-c copy` with a `-ss` window today, but assembly.py:84,
    draft.py:66/:71 and deliver.py:81 already stream-copy, so the first to gain
    a window would otherwise raise mid-render."""
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c", "copy",
           "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_a_video_stream_copy_window_is_exempt():
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c:v", "copy",
           "out.mp4"]
    assert lint.check_argv(cmd) == []


@pytest.mark.parametrize(
    "flag", ["-c", "-codec", "-c:v", "-codec:v", "-vcodec", "-c:v:0", "-codec:v:1"])
def test_every_spelling_of_a_video_copy_exempts_a_window(flag):
    """ffmpeg spells one instruction seven ways and a two-entry tuple knew two.

    Each unknown spelling was MEASURED as a false positive on this exact argv —
    and a false positive re-opens precisely the door design §4.2 added condition
    5 to close: "the first stream-copy site to gain a window would have raised
    mid-render." Recognising `-c:v` but not `-vcodec` closes that door one
    spelling over and calls it shut.

    `-codec` is included although the review named only three: it is the long
    form of the already-exempt `-c`, and it measured as a false positive too.
    """
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", flag, "copy",
           "out.mp4"]
    assert lint.check_argv(cmd) == []


@pytest.mark.parametrize("flag", ["-c:a", "-acodec", "-codec:a", "-c:a:0"])
def test_no_spelling_of_an_audio_copy_exempts_a_re_encoded_window(flag):
    """The widening must not leak into the exempting direction, which is a MISS.

    Every one of these copies AUDIO while the video is still re-encoded —
    exactly when the landmine bites. `-acodec` matters most: it ends in the same
    `codec` the video spellings do, so a substring or endswith test admits it.
    """
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", flag, "copy",
           "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_an_audio_only_copy_does_not_exempt_a_re_encoded_window():
    """`-c:a copy` copies AUDIO while the video is still re-encoded — precisely
    when the landmine bites. Excluding it from the exemption is deliberate."""
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c:a", "copy",
           "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_a_copy_flag_without_the_copy_value_does_not_exempt():
    """The value position matters: `-c:v libx264` is a re-encode, not a copy."""
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c:v", "libx264",
           "-metadata", "comment=copy", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_a_to_bounded_window_is_still_a_window():
    """`-to` sits beside `-t` in the contract and had no test in either check."""
    cmd = ["ffmpeg", "-y", "-ss", "5.0", "-i", "a.mp4", "-to", "7.0",
           "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_every_input_side_seek_is_reported_not_only_the_first():
    """check_argv promises EVERY violation. _seek_order used to `return` inside
    its loop, so a command with two input-side seeks confessed to one and the
    author would fix it, re-run, and meet the next.

    Each message must also say WHICH seek it means. Two byte-identical messages
    satisfy `len == 2` while leaving the reader nothing to act on — the same gap
    _drawtext_font's '#n of m' already closes.
    """
    cmd = ["ffmpeg", "-y", "-ss", "1.0", "-i", "a.mp4", "-ss", "2.0", "-i", "b.mp4",
           "-t", "2.0", "-c:v", "libx264", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 2
    assert "#1 of 2" in msgs[0] and "argv[2]" in msgs[0] and "'1.0'" in msgs[0]
    assert "#2 of 2" in msgs[1] and "argv[6]" in msgs[1] and "'2.0'" in msgs[1]


def test_the_seek_message_names_both_remedies():
    cmd = ["ffmpeg", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c:v", "libx264", "o.mp4"]
    msg = lint.check_argv(cmd)[0]
    assert "output seek" in msg and "accurate_seek" in msg


# --- the unbounded synthesized source check -----------------------------------

def test_an_unbounded_color_source_is_reported():
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "color=" in msgs[0]


def test_an_output_bound_makes_a_synth_source_clean():
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-t", "3.0", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_a_source_side_duration_makes_a_synth_source_clean():
    """scripts/mix.py:109 — anoisesrc with d= and no -t. The d= IS the whoosh's
    length; there is no real input for it to mismatch.

    The real command also carries `seed=7`, dropped here so the `d=` is the only
    thing that can be answering. With it present this test passed whether or not
    the `d=` was there at all, because `seed=` contains the substring `d=`.
    """
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           "anoisesrc=color=pink:r=48000:d=0.35:a=0.9", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_an_unbounded_anoisesrc_is_reported():
    """The positive half. Without it `anoisesrc` could drop out of SYNTH_SOURCES
    and every anoisesrc test would stay green — an unrecognised source and a
    bounded one are indistinguishable to an `== []` assertion."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:r=48000",
           "out.wav"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "anoisesrc" in msgs[0]


def test_a_seed_or_speed_parameter_does_not_bound_a_source():
    """`seed=` and `speed=` both CONTAIN `d=`. A substring test reads either as
    the source's duration and exempts a genuinely infinite source — the first is
    scripts/mix.py:109's own shape with its `d=` removed, i.e. exactly the
    command this check exists to catch."""
    seeded = ["ffmpeg", "-y", "-f", "lavfi", "-i",
              "anoisesrc=color=pink:r=48000:a=0.9:seed=7", "out.wav"]
    speeded = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=2x2:speed=2",
               "out.mp4"]
    assert len(lint.check_argv(seeded)) == 1
    assert len(lint.check_argv(speeded)) == 1


def test_the_duration_spelling_also_bounds_a_source():
    """§4.3 names `d=` OR `duration=`. The long spelling had no test at all."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=64x64:duration=2",
           "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_an_unbounded_sine_source_is_reported():
    """`sine=` appeared in no test — it could leave SYNTH_SOURCES unnoticed."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440", "out.wav"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "sine=" in msgs[0]


def test_an_output_to_bound_also_makes_a_synth_source_clean():
    """`-to` is documented contract beside `-t` and had no test in either check."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-to", "3.0", "out.wav"]
    assert lint.check_argv(cmd) == []


def test_a_synth_source_inside_a_filter_complex_is_seen():
    """reframe emits `color=...` inside -filter_complex, not as an -i value."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "color=c=black:s=64x64:r=30[bg];[bg][0:v]overlay=0:0", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_boxcolor_is_not_mistaken_for_a_color_source():
    """THE substring trap: 'color=' sits inside boxcolor= and fontcolor=, which
    scripts/lib/draft.py:28 emits on every draft render. Matching 'color=' as a
    bare substring raises on correct code — and this guard raises in production."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf",
           ("drawtext=fontfile='/f.ttf':textfile='/t.txt':fontsize=h/24:"
            "fontcolor=white:box=1:boxcolor=black@0.5:x=40:y=40"), "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_a_synth_source_after_a_graph_separator_is_still_seen():
    """The boundary rule must not become 'only at the start of the string'."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "[0:v]scale=64:64[v];testsrc=s=64x64[t];[v][t]overlay=0:0", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_a_synth_source_after_a_comma_is_seen():
    """`,` is in the boundary set. ffmpeg itself would reject a source mid-chain
    (a source takes no input), so this shape is defensive breadth rather than a
    form the repo emits — pinned so that narrowing the set is a deliberate act
    with a red test, not a silent loss of coverage."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "[0:v]scale=64:64,testsrc=s=64x64", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 1


def test_a_synth_source_after_a_label_close_is_seen():
    """`]` is in the boundary set — same defensive rationale as the comma."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "[0:v]anullsrc=r=48000", "out.wav"]
    assert len(lint.check_argv(cmd)) == 1


def test_whitespace_after_a_separator_does_not_disable_the_check():
    """Every graph here is built with `";".join(...)`, so no whitespace appears
    today. A future `"; ".join(...)` for readability would otherwise turn this
    check off silently — the worst kind of regression, since nothing goes red."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-filter_complex",
           "[0:v]scale=64:64[v]; color=c=black:s=64x64[bg];[v][bg]overlay=0:0",
           "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "color=" in msgs[0]


def test_a_colour_parameter_is_not_a_colour_source():
    """`color=` after ':' names a filter's PARAMETER; only after a graph separator
    does it name the lavfi source. Excluding just [A-Za-z0-9_] catches boxcolor=
    but still admits `:color=` — and this exact argv is live at
    tests/integration/test_pan.py:27-31, feeding three real render assertions. The
    guard raises in production, so admitting it breaks a working test.
    """
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=1280x720:d=2.0:r=30",
           "-vf", ("drawbox=x=40:y=310:w=120:h=120:color=red@1.0:t=fill,"
                   "drawbox=x=1120:y=310:w=120:h=120:color=blue@1.0:t=fill"),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "edges.mp4"]
    assert lint.check_argv(cmd) == []


def test_the_letterbox_pad_colour_parameter_is_not_a_source():
    """pad's own `color=` — the canonical letterbox form this repo will reach for.

    It reads clean today only by accident: `pad=` itself contains the substring
    `d=`, which the whole-argument duration test mistook for a source bound. Once
    that test became per-element this shape had nothing left masking it, so the
    boundary rule is the only thing holding it out.
    """
    cmd = ["ffmpeg", "-i", "a.mp4", "-vf",
           "scale=1080:1920,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black", "o.mp4"]
    assert lint.check_argv(cmd) == []


def test_a_filename_that_merely_starts_with_a_source_name_is_not_a_source():
    """The FIFTH instance of the boundary family, and a measured false positive.

    The boundary rule's "string start counts" arm exists so a bare `-i` VALUE
    like `color=c=black:…` matches — but it also means any argv element merely
    BEGINNING with a source name reads as a source. Measured before the fix:
    `-i testsrc.mp4` reported one violation on a command with nothing wrong.

    Only a bare basename bites. The same path written absolutely is clean by
    accident — the `/` sits in the lookbehind's reject set — which is exactly
    the kind of accident that makes a bug look absent until someone passes a
    relative path. Both directions are pinned so neither can drift.
    """
    for name in ("testsrc.mp4", "anullsrc.wav", "anoisesrc_take2.mov"):
        assert lint.check_argv(["ffmpeg", "-y", "-i", name, "out.mp4"]) == [], name
    assert lint.check_argv(["ffmpeg", "-y", "-i", "/w/testsrc.mp4", "out.mp4"]) == []


@pytest.mark.parametrize("graph, expect", [
    # A real source is `name` alone or `name=params` — never `name.ext`. These
    # are every shape of "alone" the graph syntax allows, and all must survive.
    ("anullsrc=r=48000:cl=stereo", "anullsrc"),   # params — mix.py:75's own form
    ("anullsrc", "anullsrc"),                     # parameterless, ends the element
    ("testsrc[t]", "testsrc"),                    # an output label follows
    ("testsrc,format=yuv420p", "testsrc"),        # a filter chain follows
    ("testsrc;[0:v]null", "testsrc"),             # a new graph chain follows
])
def test_a_real_source_still_matches_after_the_filename_fix(graph, expect):
    """The other half of the fix: narrowing must not switch the check off.

    Written as the five things that may legally follow a source NAME (`=`, end
    of element, `[`, `,`, `;`), because that set is what the fix keys on — if it
    is ever narrowed further, one of these goes green-to-red rather than the
    check going quietly blind, which is the failure mode this module fears most.
    """
    msgs = lint.check_argv(["ffmpeg", "-y", "-f", "lavfi", "-i", graph, "out.mp4"])
    assert len(msgs) == 1
    assert expect in msgs[0]


def test_each_source_in_a_graph_needs_its_own_bound():
    """§4.3 asks whether EVERY synthesized source is bounded, not whether the
    argument mentions a duration somewhere. A bounded source beside an unbounded
    one must still report the unbounded one."""
    cmd = ["ffmpeg", "-y", "-filter_complex",
           "color=c=black:s=64x64:r=30:d=2[bg];testsrc=s=64x64[t];[bg][t]overlay=0:0",
           "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "testsrc" in msgs[0]


def test_a_neighbours_duration_does_not_exempt_an_unbounded_source():
    """The `d=` must belong to the SOURCE. Here it belongs to the afade beside it
    — a real shape (scripts/mix.py builds afade chains) — and an argument-wide
    test would read it as the anullsrc's bound and stay silent."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           "anullsrc=r=48000:cl=stereo,afade=t=in:st=0:d=0.5", "out.wav"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "anullsrc" in msgs[0]


# --- the drawtext font check --------------------------------------------------

def test_drawtext_without_fontfile_is_reported():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf", "drawtext=text='hi':fontsize=24",
           "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    assert "fontfile" in msgs[0]


def test_drawtext_with_fontfile_is_clean():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf",
           "drawtext=fontfile='/f.ttf':text='hi':fontsize=24", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_each_drawtext_in_a_chain_needs_its_own_font():
    """scripts/lib/titles.py:152 joins per-title drawtext pieces with ','. Asking
    whether the WHOLE string contains 'fontfile=' passes a chain where only the
    first piece has one — and the fontless title is the one that renders garbage."""
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-vf",
           ("drawtext=fontfile='/f.ttf':text='a':x=0:y=0,"
            "drawtext=text='b':x=0:y=100"), "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1
    # WHICH one, not just how many: quoting the whole -vf argument leaves the
    # reader of a six-title chain no way to find the offender.
    assert "#2 of 2" in msgs[0]
    assert "text='b'" in msgs[0]


# --- the zoompan defaults check ------------------------------------------------
# design 2026-08-08 §8: zoompan's three defaults (s=hd720, fps=25, d=90) each
# corrupt SILENTLY. See scripts/lib/lint.py's _zoompan_defaults docstring for the
# fourth trap (a sub-1 `z` clamped to 1) that no argv scan can reach.

def test_zoompan_without_an_explicit_size_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1.2':x='0':y='0':d=1:fps=30", "o.mp4"])
    assert any("s=" in m for m in out)


def test_zoompan_without_an_explicit_fps_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1.2':x='0':y='0':d=1:s=100x200", "o.mp4"])
    assert any("fps=" in m for m in out)


def test_zoompan_without_an_explicit_d_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1.2':x='0':y='0':s=100x200:fps=30", "o.mp4"])
    assert any("d=" in m for m in out)


def test_a_fully_specified_zoompan_is_clean():
    assert lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                            "crop=100:200:x='0':y=0,"
                            "zoompan=z='1.2':x='0':y='0':d=1:s=100x200:fps=30,"
                            "scale=50:100", "o.mp4"]) == []


def test_each_zoompan_in_a_chain_is_judged_on_its_own_segment():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1':x='0':y='0':d=1:s=10x20:fps=30,"
                           "zoompan=z='1':x='0':y='0':d=1:fps=30", "o.mp4"])
    assert len(out) == 1 and "#2 of 2" in out[0]


def test_a_neighbouring_filters_fps_does_not_exempt_a_zoompan_missing_its_own():
    """The remedy text in EVERY message this check emits names all three
    defaults verbatim ("s=hd720, fps=25 and d=90"), so a bare `"fps=" in m`
    substring check is satisfied by any zoompan-defaults message at all — it
    cannot alone prove fps= was the omission actually detected. What pins that
    is `"omits fps="` below, which only appears when fps= lands in `missing`.

    The real target is the one-line regression this fixture is built to catch:
    dropping the `_element(seg, 0)` bound and testing `"fps=" in seg` against
    the raw, unbounded split segment instead. `fps` is also a genuine ffmpeg
    filter (`-vf fps=30` sets the output rate), so a neighbour spelled exactly
    that way is a realistic chain, not a contrived one — and without the bound,
    that neighbour's own `fps=30` would satisfy the zoompan's missing key,
    leaving `out` empty here instead of reporting the omission.
    """
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-vf",
                           "zoompan=z='1':x='0':y='0':d=1:s=100x200,"
                           "fps=30", "o.mp4"])
    assert any("omits fps=" in m for m in out)


# --- _element is quote-aware ---------------------------------------------------
# A CRITICAL fix, found independently by two reviewers: reframe._xexpr emits a
# moving x=/y= as `if(lt(it,T),then,else)` whenever a path has two or more knots
# — always, in practice, since the Douglas-Peucker simplifier keeps both
# endpoints. That `if(...)`'s own commas sit INSIDE the quoted x=/y= value, one
# syntax level below the graph separators _element used to bound on blindly. The
# old scan stopped at the first one, discarded the real `:d=1:s=...:fps=...`
# that followed, and reported a fully correct zoompan as missing all three —
# and because proc.run's guard is always-on, that refused every real zoom
# render before ffmpeg ever ran. All four tests/integration/test_zoom.py proofs
# failed on exactly this ValueError before the fix below (see task-12-report.md
# for the measured before/after). Built from the real emitter (reframe._xexpr),
# not a hand-written stand-in, so a future change to its shape is what these
# track — the sanity assertions below exist so a change that removes the comma
# from _xexpr's output does not leave this section silently vacuous.

def _real_xexpr() -> str:
    """The exact shape that triggered the bug: a 5-knot path, so `_simplify`
    cannot collapse it to a single point and `_xexpr` must emit nested
    `if(lt(it,T),...)` calls — multiple commas, multiple quote-nesting levels."""
    return reframe._xexpr([100, 100, 250, 400, 400], [0.0, 0.5, 1.0, 1.5, 2.0], var="it")


def test_a_multi_knot_xexpr_zoompan_with_every_default_set_is_clean():
    expr = _real_xexpr()
    assert expr.count(",") >= 2, "fixture no longer exercises the quoted-comma shape"
    cmd = ["ffmpeg", "-i", "a.mp4", "-vf",
           f"zoompan=z='1.2':x='{expr}':y='{expr}':d=1:s=100x200:fps=30,scale=50:100",
           "o.mp4"]
    assert lint.check_argv(cmd) == []


def test_a_multi_knot_xexpr_zoompan_missing_one_default_is_still_flagged():
    """The fix must not turn the check off: a quote-aware bound still has to SEE
    a genuinely absent key sitting past the real `if(...)` expression, not just
    stop looking once it steps outside a quote. Pinned on the EXACT clause
    (`"omits s= ("`, not a bare `"s="`) because the remedy text names all three
    defaults regardless of which is actually missing — a bare substring would
    pass just as well under the pre-fix bug, which over-reported all three."""
    expr = _real_xexpr()
    cmd = ["ffmpeg", "-i", "a.mp4", "-vf",
           f"zoompan=z='1.2':x='{expr}':y='{expr}':d=1:fps=30", "o.mp4"]
    out = lint.check_argv(cmd)
    assert len(out) == 1
    assert "omits s= (" in out[0]


def test_a_quoted_comma_does_not_truncate_a_sources_own_bound():
    """The same fix, pinned on _unbounded_source's OWN guarantee: a quoted value
    holding a raw comma must not stop the scan before a real d= that follows it.
    No production source embeds a quoted expression today (color=/testsrc=/etc.
    take bare key=value params only) — defensive breadth, the same shape as
    test_a_synth_source_after_a_comma_is_seen beside it — but the scan must not
    go blind the day one does, and the pre-fix code demonstrably did: dropping
    back to a raw `text.find(sep, start)` per separator reproduces a reported
    violation on this exact clean command."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           "color=c=black:s=64x64:note='a,b':d=2", "out.mp4"]
    assert lint.check_argv(cmd) == []


def test_a_quoted_comma_does_not_hide_a_genuinely_unbounded_source():
    """The complement: quote-awareness widens what _element INCLUDES in an
    element, and this proves it does not also widen what counts as a bound —
    a source with a quoted comma and no d=/duration= anywhere must still be
    reported, exactly as an unquoted one would be."""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           "color=c=black:s=64x64:note='a,b'", "out.mp4"]
    msgs = lint.check_argv(cmd)
    assert len(msgs) == 1 and "color=" in msgs[0]


def test_an_unclosed_quote_falls_back_to_the_quote_blind_bound():
    """The residual the quote-aware fix left behind (parked at review, closed
    here): an ODD apostrophe count — here, a dropped closing quote on z= —
    latches in_quote=True for the rest of the scan, so an un-hardened _element
    would return EVERYTHING to end-of-string as "the element". That swallows
    the comma before the next, unrelated filter and reads ITS s=/fps=/d= as
    satisfying THIS zoompan's requirement — a silent MISS, even though this
    zoompan's own params set none of the three. `junk=` is not a real ffmpeg
    filter; it stands in for "any neighbour with its own s=/fps=/d=", the same
    role `note=` plays in the quoted-comma tests above.

    Reproduced directly against the pre-fallback code before this test was
    written (commenting out the `if in_quote:` branch reverts check_argv(cmd)
    to [] — the exact miss) and reverted with an editor edit, per the no-
    git-checkout rule this slice's own ledger exists to enforce.
    """
    cmd = ["ffmpeg", "-i", "a.mp4", "-vf",
           "zoompan=z='1.2:x=0:y=0,junk=s=99x99:fps=99:d=99", "o.mp4"]
    out = lint.check_argv(cmd)
    assert len(out) == 1
    assert "omits s=, fps=, d=" in out[0]


# --- every real call site in the tree must lint clean -------------------------
# Design §4.2's table, as executable fixtures. If a future edit to the predicate
# starts firing on production code, THIS is what goes red — before the guard has
# a chance to raise in the middle of somebody's render.
#
# Transcribed from the SHIPPED commands, not from the design's prose: the filter
# strings below were printed out of the real builders (reframe._filter_args,
# mix._mix_graph, titles.build_filterchain, draft.segment_filter), so a fixture
# edited to satisfy a wrong predicate destroys the only evidence that the lint
# matches reality. Fix the predicate; never the fixture.
#
# Wider than the design's seven-row table, in two directions the fix rounds
# proved load-bearing:
#   * The three SPLAT sites design §2 names — reframe.py:380, deliver.py:76/:80,
#     mix.py:207 — assemble their argv through `*builder(...)`. Static analysis
#     cannot see through that, so runtime is the ONLY layer covering them and
#     one fixture per background variant is cheap insurance.
#   * The shapes that were live false positives: `drawbox=…:color=red@1.0`
#     (test_pan.py:27), `pad=…` (whose literal `d=` masked a second bug, design
#     §6), `seed=` beside a real `d=`, and `-sseof`.
#
# WHAT THESE PIN, EXACTLY: that no production command fires. They are not where
# the individual exemption CONDITIONS are pinned, and reading a clean verdict as
# evidence for a particular rule is the "an earlier condition answers first" trap
# this slice has already hit once. Most of these argvs are answered by an early
# return long before the interesting rule is consulted. Measured, not reasoned:
#   * check_episode.py:24 carries no -t, so _seek_order exits at not-a-window and
#     the -sseof exact-token rule is never reached. That rule is pinned by
#     test_sseof_is_never_mistaken_for_ss, which supplies a -t.
#   * check_reel.py:47 holds no synth-source token at all, so its blackdetect
#     `d=` is never examined. The bound rule is pinned by
#     test_a_seed_or_speed_parameter_does_not_bound_a_source.
#   * both reframe solid variants carry an output -t, so _unbounded_source
#     returns immediately: neither the boundary rule nor the per-element bound
#     runs, the bordered `pad=` included. Those are pinned by
#     test_the_letterbox_pad_colour_parameter_is_not_a_source and
#     test_each_source_in_a_graph_needs_its_own_bound.
# Two fixtures do reach the scanner and earn their keep there: test_pan.py:27
# (matches a bounded `color=` AND boundary-rejects two drawbox `color=` params)
# and mix.py:109 (per-element bound, with `seed=` sitting beside a real `d=`).

_FONT = "/System/Library/Fonts/Helvetica.ttc"

REAL_SITES = {
    "extract.py:16 — output seek on a window": [
        "ffmpeg", "-y", "-i", "src.mp4", "-ss", "3.5", "-t", "2.0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "out.mp4"],
    "check_reel.py:47 — blackdetect analysis pass": [
        "ffmpeg", "-i", "master.mp4", "-vf", "blackdetect=d=0.05:pic_th=0.98",
        "-an", "-f", "null", "-"],
    "check_reel.py:65 — output seek, still grab": [
        "ffmpeg", "-y", "-i", "reel.mp4", "-ss", "1.5", "-frames:v", "1", "f.png"],
    "check_episode.py:24 — sseof tail grab": [
        "ffmpeg", "-y", "-sseof", "-0.5", "-i", "clip.mp4", "/w/tail%02d.png"],
    "check_episode.py:32 — body sample on an fps grid": [
        "ffmpeg", "-y", "-i", "clip.mp4", "-vf", "fps=5/2.0",
        "-frames:v", "5", "/w/b%02d.png"],
    "storyboard.py:36 — input seek, still grab, no window": [
        "ffmpeg", "-y", "-ss", "1.2", "-i", "src.mp4", "-frames:v", "1", "/w/f00.png"],
    "mix.py:74 — a segment's nat-sound bed": [
        "ffmpeg", "-y", "-i", "seg.mp4", "-t", "2.5", "-vn", "-ac", "2",
        "-ar", "48000", "-af", "apad", "-c:a", "pcm_s16le", "amb_000.wav"],
    "mix.py:77 — anullsrc bounded by -t": [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "2.5", "-c:a", "pcm_s16le", "amb_000.wav"],
    "mix.py:111 — anoisesrc bounded by d=, with seed= beside it": [
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "anoisesrc=color=pink:r=48000:d=0.35:a=0.9:seed=42",
        "-af", ("bandpass=f=1200:width_type=q:w=0.7,afade=t=in:st=0:d=0.08,"
                "afade=t=out:st=0.08:d=0.27"),
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", "whoosh.wav"],
    "mix.py:139 — sfx bed, the -t sitting AHEAD of the lavfi source": [
        "ffmpeg", "-y", "-t", "18.000000", "-f", "lavfi", "-i",
        "anullsrc=r=48000:cl=stereo", "-i", "whoosh.wav", "-filter_complex",
        ("[1:a]asplit=2[w0][w1];[w0]adelay=2800:all=1[d0];"
         "[w1]adelay=7300:all=1[d1];"
         "[0:a][d0][d1]amix=inputs=3:duration=first:normalize=0[sfx]"),
        "-map", "[sfx]", "-c:a", "pcm_s16le", "sfx.wav"],
    "mix.py:205 — input seek on a window, accurate_seek": [
        "ffmpeg", "-y", "-accurate_seek", "-ss", "12.5", "-i", "track.mp3",
        "-t", "18.0", "frag.wav"],
    "mix.py:225 — the post-mix bookend fade, before loudnorm (fades the MIXED "
    "stem, not the fragment — design 2026-08-13 §5)": [
        "ffmpeg", "-y", "-i", "mixed.wav", "-af",
        "afade=t=in:st=0:d=0.5,afade=t=out:st=17.5:d=0.5", "faded.wav"],
    "mix.py:217 — the ducking mix graph (a splat site)": [
        "ffmpeg", "-y", "-i", "frag.wav", "-i", "ambient.wav", "-i", "sfx.wav",
        "-filter_complex",
        ("[0:a]asplit=2[msum][mkey];[1:a]volume=0.6[amb];"
         "[amb][mkey]sidechaincompress=threshold=0.03:ratio=4:attack=20:"
         "release=300[duck];[2:a]volume=1.0[sfx];"
         "[msum][duck][sfx]amix=inputs=3:duration=first[mixed]"),
        "-map", "[mixed]", "mixed.wav"],
    "reframe.py:380 — fill, the fast path (the crown-jewel -vf)": [
        "ffmpeg", "-y", "-i", "src.mp4", "-vf",
        ("crop=405:720:x='if(lt(t,1.0000),(100.0+(12.500)*(t-0.0000)),200.0)':y=0,"
         "scale=1080:1920,colorchannelmixer=rr=1.000:gg=1.050:bb=1.100,"
         "fps=30,format=yuv420p"),
        "-t", "2.000000", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-an", "out.mp4"],
    "reframe.py:380 — solid background composite": [
        "ffmpeg", "-y", "-i", "src.mp4", "-filter_complex",
        ("color=c=black:s=1080x1920:r=30:d=2.000000[bg];"
         "[0:v]crop=405:720:x='0.0':y=0,scale=1080:1920[fg];"
         "[bg][fg]overlay=0:0,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
         "fps=30,format=yuv420p"),
        "-t", "2.000000", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-an", "out.mp4"],
    "reframe.py:380 — blur background composite": [
        "ffmpeg", "-y", "-i", "src.mp4", "-filter_complex",
        ("[0:v]split=2[a][b];[a]scale=1080:1920:"
         "force_original_aspect_ratio=increase,crop=1080:1920,boxblur=18:2[bg];"
         "[b]crop=405:720:x='0.0':y=0,scale=1080:1920[fg];"
         "[bg][fg]overlay=0:0,colorchannelmixer=rr=1.000:gg=1.000:bb=1.000,"
         "fps=30,format=yuv420p"),
        "-t", "2.000000", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-an", "out.mp4"],
    # Shape-wise this is design §6's masking pair in one command — a bounded
    # `color=…:d=` beside a `pad=` whose literal `d=` once read as that source's
    # bound. It does NOT exercise it: the output -t makes _unbounded_source
    # return first. Kept as the shipped shape; the masking pair itself is pinned
    # by test_the_letterbox_pad_colour_parameter_is_not_a_source.
    "reframe.py:380 — insert over solid, bordered": [
        "ffmpeg", "-y", "-i", "src.mp4", "-filter_complex",
        ("color=c=black:s=1080x1920:r=30:d=2.000000[bg];"
         "[0:v]crop=720:720:x='0.0':y=0,scale=956:956,pad=972:972:8:8:white[fg];"
         "[bg][fg]overlay=54:480,colorchannelmixer=rr=0.900:gg=1.000:bb=1.100,"
         "fps=30,format=yuv420p"),
        "-t", "2.000000", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-an", "out.mp4"],
    "draft.py:56 — drawtext label with a resolved font": [
        "ffmpeg", "-y", "-i", "seg.mp4", "-vf",
        ("scale=1080:1920:force_original_aspect_ratio=decrease:"
         "force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30.0,"
         f"format=yuv420p,drawtext=fontfile='{_FONT}':"
         "textfile='/w/labels/label_0.txt':fontsize=h/24:fontcolor=white:box=1:"
         "boxcolor=black@0.5:boxborderw=12:x=40:y=h-th-40"),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-an", "ep0.mp4"],
    "draft.py:66 — silent draft, stream copy": [
        "ffmpeg", "-y", "-i", "draft_master.mp4", "-c", "copy", "draft.mp4"],
    "deliver.py:76 — a two-title drawtext chain (a splat site)": [
        "ffmpeg", "-y", "-i", "master.mp4", "-vf",
        (f"drawtext=fontfile='{_FONT}':textfile='/o/title_0.txt':fontsize=h/18:"
         "fontcolor=white:x=(w-tw)/2:y=h*0.08:box=1:boxcolor=black@0.5:"
         "boxborderw=16:enable='between(t,0.0,1.5)',"
         f"drawtext=fontfile='{_FONT}':textfile='/o/title_1.txt':fontsize=h/18:"
         "fontcolor=white:x=(w-tw)/2:y=h-th-h*0.12:"
         "enable='between(t,8.0,10.0)'"),
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", "REEL_v1.mp4"],
    "deliver.py:80 — mux the pre-normalized stem (a splat site)": [
        "ffmpeg", "-y", "-i", "master.mp4", "-i", "audio.m4a",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy", "-shortest",
        "REEL_v1.mp4"],
    "assembly.py:83 — lossless concat": [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "/w/_concat.txt",
        "-c", "copy", "master.mp4"],
    "test_pan.py:27 — drawbox colour PARAMS over a bounded colour source": [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=1280x720:d=2.0:r=30",
        "-vf", ("drawbox=x=40:y=310:w=120:h=120:color=red@1.0:t=fill,"
                "drawbox=x=1120:y=310:w=120:h=120:color=blue@1.0:t=fill"),
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "edges.mp4"],
}


def test_blend_all_mode_multiply_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-loop", "1", "-i", "m.png",
                           "-filter_complex",
                           "[1:v]format=gray[m];[0:v][m]blend=all_mode=multiply:shortest=1[v]",
                           "out.mp4"])
    assert len(out) == 1
    assert "all_mode=multiply" in out[0]
    assert "chroma" in out[0]
    assert "overlay" in out[0]        # the message must name the working alternative


def test_per_plane_blend_multiply_is_legal():
    # c0_mode targets ONE plane, which is the correct way to multiply luma only
    assert lint.check_argv(["ffmpeg", "-i", "a.mp4", "-filter_complex",
                            "[0][1]blend=c0_mode=multiply[v]", "out.mp4"]) == []


def test_other_blend_modes_are_legal():
    assert lint.check_argv(["ffmpeg", "-i", "a.mp4", "-filter_complex",
                            "[0][1]blend=all_mode=screen[v]", "out.mp4"]) == []


def test_the_overlay_route_is_clean():
    assert lint.check_argv(["ffmpeg", "-y", "-i", "a.mp4", "-loop", "1", "-i", "m.png",
                            "-filter_complex", "[0:v][1:v]overlay=shortest=1[v]",
                            "-map", "[v]", "out.mp4"]) == []


@pytest.mark.parametrize("name", sorted(REAL_SITES))
def test_every_real_call_site_lints_clean(name):
    assert lint.check_argv(REAL_SITES[name]) == [], name
