"""Real-ffmpeg proof for the titles stage (design docs/specs/2026-07-13-titles-design.md,
§5.16): a TITLES.json burned by deliver changes pixels in the title's time window, and
(with audio) rides the mux branch's single encode. Uses the shared sample_clip fixture;
skips where this machine's ffmpeg lacks drawtext (same guard as the draft golden).

A third golden (design docs/specs/2026-07-29-titles-animations-design.md §5) proves the
fade + reveal="word" chain directly: build_filterchain with a REAL resolve_font/_measure
(no stub) builds, and real ffmpeg accepts and renders the resulting drawtext -vf."""
from pathlib import Path

import pytest

from scripts import deliver as deliver_mod
from scripts.lib import assembly, ffbin, proc, provenance
from scripts.lib.fonts import resolve_font
from scripts.lib.models import REEL_H264, CheckResult, ReelReport
from scripts.lib.titles import Title, Titles, build_filterchain


@pytest.fixture(autouse=True)
def _need_drawtext(need_filter):
    need_filter("drawtext")


def _passing_report(master):
    # bound to the real master on disk — deliver now refuses an unbound report
    # (design §4); both deliver() calls in a test below ship the SAME sample_clip,
    # so one digest binds both.
    return ReelReport(checks={"length": CheckResult("length", True, {})},
                      master_digest=provenance.digest_file(master))


def _frame_bytes(src, tmp_path, name):
    """One PNG frame at t=1.0 (inside the [0,3] title window). Input-seek (`-ss` before
    `-i`) is a justified exception for a single verification still — same call shape as
    scripts/storyboard.py's frame grabs, NOT the §12 cut-boundary landmine (do not copy
    this idiom into a cut/re-encode). The title shows for the whole window, so any
    in-window frame carries it."""
    png = tmp_path / name
    proc.run([ffbin.ffmpeg(), "-y", "-ss", "1.0", "-i", str(src), "-frames:v", "1", str(png)])
    return png.read_bytes()


@pytest.mark.integration
def test_title_burns_into_the_silent_encode(sample_clip, tmp_path):
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("HELLO", 0.0, 3.0, pos="center", style="bold-box"),)).write(tj)
    rep = _passing_report(sample_clip)
    scratch_dir = str(tmp_path / "scratch")
    titled = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "t"),
                                 "titled", rep, scratch_dir=scratch_dir, titles=str(tj))
    plain = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "p"),
                                "plain", rep, scratch_dir=scratch_dir)
    assert Path(titled).exists() and Path(plain).exists()
    codec = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                      "stream=codec_type", "-of", "csv=p=0", titled]).stdout.decode()
    assert "video" in codec
    # the centered box changed the frame inside the title window
    assert _frame_bytes(titled, tmp_path, "a.png") != _frame_bytes(plain, tmp_path, "b.png")


@pytest.mark.integration
def test_title_burns_into_the_mux_encode_with_audio(sample_clip, tmp_path):
    # the production path: music + titles -> deliver's mux branch (-vf + -map + -c:a copy)
    # stem is deliberately longer (10s) than the 3s sample_clip so deliver's -shortest can
    # only ever trim the audio, never the picture (the duration assert below verifies it)
    aac = tmp_path / "stem.aac"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
              "-c:a", "aac", str(aac)])
    tj = tmp_path / "TITLES.json"
    Titles(items=(Title("HELLO", 0.0, 3.0, pos="center", style="bold-box"),)).write(tj)
    rep = _passing_report(sample_clip)
    scratch_dir = str(tmp_path / "scratch")
    titled = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "t"),
                                 "titled+audio", rep, scratch_dir=scratch_dir,
                                 audio=str(aac), titles=str(tj))
    plain = deliver_mod.deliver(str(sample_clip), REEL_H264, str(tmp_path / "p"),
                                "plain", rep, scratch_dir=scratch_dir)
    # the muxed output carries BOTH a video and an audio stream...
    types = proc.run([ffbin.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type",
                      "-of", "csv=p=0", titled]).stdout.decode()
    assert "video" in types and "audio" in types
    # ...-shortest bounded the mux to the picture (the 10s stem did NOT extend it): the
    # muxed duration matches the titleless, video-length encode — no dead-air tail
    assert abs(assembly.probe_duration(titled) - assembly.probe_duration(plain)) < 0.2
    # ...and the title still burned into the picture (frame differs from the titleless encode)
    assert _frame_bytes(titled, tmp_path, "a.png") != _frame_bytes(plain, tmp_path, "b.png")


@pytest.mark.integration
def test_word_reveal_with_fade_burns_into_a_real_encode(tmp_path):
    # a 2-word hook, fade in/out, revealed word-by-word — the chain must build with a
    # REAL font (exercises _measure/PIL, not the unit suite's stub) and real ffmpeg
    # must accept and render it (fade alpha + per-word x-offsets).
    ts = Titles(items=(Title("hello world", 0.0, 2.0, fade=0.4,
                             reveal="word", reveal_step=0.5, pos="bottom"),))
    chain = build_filterchain(ts, str(tmp_path), resolve=resolve_font, platform="reel")
    assert chain.count("drawtext=") == 2                 # one per word
    assert "alpha='max(0,min(1," in chain                # fade present
    assert "y=h-th-h*0.16" in chain                      # reel zone
    # render a bounded colour source through the chain — real ffmpeg must exit 0
    out = tmp_path / "titled.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x284:d=3",
              "-vf", chain, "-frames:v", "1", str(out)])
    assert out.exists() and out.stat().st_size > 0


def _ink(font, text, tmp_path, name):
    """White text on black through real drawtext; the count of lit pixels."""
    import numpy as np
    tf = tmp_path / f"{name}.txt"
    tf.write_text(text)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=320x160:d=1:r=1", "-vf",
                    f"drawtext=fontfile='{font}':textfile='{tf}':fontsize=96:"
                    f"fontcolor=white:x=40:y=20", "-frames:v", "1", "-f", "rawvideo",
                    "-pix_fmt", "gray", "-"]).stdout
    return int((np.frombuffer(raw, np.uint8) > 128).sum())


@pytest.mark.integration
def test_an_icon_merged_into_the_title_font_draws_ink_where_the_bare_font_draws_a_box(
        tmp_path, make_ttf):
    """retro 2026-10-16 S13, through real drawtext: the system title font has no map
    pin, so the bare font draws its .notdef box; the font cover_glyphs builds draws the
    icon font's glyph (here a filled square) at that place instead."""
    from scripts.lib import fonts
    pin = chr(0x1F4CD)
    base = resolve_font()
    assert fonts.missing_glyphs(base, pin) == [pin]               # the premise
    icons = make_ttf(tmp_path / "icons.ttf", [0x1F4CD])
    merged = fonts.cover_glyphs(base, pin, str(tmp_path / "w"), icon_font=icons)
    bare, covered = _ink(base, pin, tmp_path, "bare"), _ink(merged, pin, tmp_path, "covered")
    assert covered > 3 * max(bare, 1), (bare, covered)
