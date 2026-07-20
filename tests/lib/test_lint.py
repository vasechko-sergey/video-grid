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


def test_the_seek_message_names_both_remedies():
    cmd = ["ffmpeg", "-ss", "5.0", "-i", "a.mp4", "-t", "2.0", "-c:v", "libx264", "o.mp4"]
    msg = lint.check_argv(cmd)[0]
    assert "output seek" in msg and "accurate_seek" in msg
