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
    author would fix it, re-run, and meet the next."""
    cmd = ["ffmpeg", "-y", "-ss", "1.0", "-i", "a.mp4", "-ss", "2.0", "-i", "b.mp4",
           "-t", "2.0", "-c:v", "libx264", "out.mp4"]
    assert len(lint.check_argv(cmd)) == 2


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
