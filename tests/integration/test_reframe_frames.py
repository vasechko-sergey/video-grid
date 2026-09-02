"""reframe.plan_frames_rgb over real ffmpeg — the plan's RGB sink."""
import hashlib
import subprocess

import numpy as np
import pytest

from scripts import process_episode, reframe
from scripts.lib import color, ffbin, proc

pytestmark = pytest.mark.integration


def _manifest(seg: str, out: str) -> dict:
    return {"segment": seg, "out_path": out, "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480"}


def test_plan_frames_rgb_returns_one_frame_per_time_at_output_dims(golden_ride_segment, tmp_path):
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    times = [0.2, 0.6, 1.0]
    frames = reframe.plan_frames_rgb(plan, str(golden_ride_segment), times)
    assert len(frames) == 3
    for f in frames:
        assert f.shape == (plan.rl.out_h, plan.rl.out_w, 3)
        assert f.dtype == np.uint8


def test_a_select_ahead_of_the_tail_collapses_to_one_frame(golden_ride_segment, tmp_path):
    """The §12 landmine, proved rather than assumed — mirrors test_probe.py's
    test_a_select_ahead_of_the_tail_collapses_to_one_frame (the committed, established
    pattern for this exact landmine on the sibling sink). A test that only asserts
    distinctness on the CORRECT construction never demonstrates it would have caught
    the mistake with_tail exists to prevent; this one builds the broken argv too and
    shows it actually collapses.

    proc.run's own lint (lib.lint._select_before_fps) already refuses to let
    production code build the "ahead" argv at all — asserted first, against this
    render's own real filter chain, which is a stronger proof than a hand-written
    lint fixture that the guard covers the shape a real render would produce. Seeing
    ffmpeg's own behaviour on that argv therefore needs a narrow, deliberate
    subprocess bypass, exactly as test_probe.py's version does.
    """
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    times = [0.1, 0.7, 1.3]
    sel = color.select_frames(times, plan.fps)
    w, h = plan.rl.out_w, plan.rl.out_h
    stride = w * h * 3

    # "ahead": select+format spliced in immediately BEFORE the chain's own fps=,
    # instead of appended after the whole tail via with_tail.
    head, _, after_fps_kw = plan.filter_args[-1].partition(",fps=")
    ahead = list(plan.filter_args[:-1]) + [f"{head},{sel},format=rgb24,fps={after_fps_kw}"]

    with pytest.raises(ValueError, match="select ahead of fps="):
        proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(golden_ride_segment), *ahead,
                  "-t", f"{plan.dur:.6f}", "-vsync", "0", "-frames:v", str(len(times)),
                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])

    def _hashes(args) -> list:
        # Deliberate, narrow bypass of proc.run — mirrors test_probe.py's own
        # raw=True branch — since production code can no longer construct this argv
        # at all; this is the only way left to observe ffmpeg's actual behaviour on
        # the shape with_tail's append-only contract exists to avoid.
        raw = subprocess.run(
            [ffbin.ffmpeg(), "-v", "error", "-i", str(golden_ride_segment), *args,
             "-t", f"{plan.dur:.6f}", "-vsync", "0", "-frames:v", str(len(times)),
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            check=True, capture_output=True).stdout
        assert len(raw) == len(times) * stride
        return [hashlib.sha256(raw[i * stride:(i + 1) * stride]).hexdigest()
                for i in range(len(times))]

    assert len(set(_hashes(ahead))) == 1      # one frame, three times — the landmine

    correct = reframe.plan_frames_rgb(plan, str(golden_ride_segment), times)
    correct_hashes = {hashlib.sha256(f.tobytes()).hexdigest() for f in correct}
    assert len(correct_hashes) == 3           # with_tail: three genuinely distinct frames


def test_plan_frames_rgb_batch_frames_match_independent_single_frame_reads(golden_ride_segment, tmp_path):
    """Pins the buffer-slicing arithmetic (`offset=i*stride`): writing `offset=i`
    instead keeps shape and dtype correct (`count=stride` is fixed) and yields three
    overlapping, WRONG slices that are still pairwise different on photographic
    data — so the two tests above would both stay green while every frame is
    garbage a damage sensor would happily compute an entropy over. Comparing each of
    a batch's frames against an INDEPENDENT single-frame read at the same timestamp
    catches a wrong offset immediately, which mere pairwise distinctness cannot."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    times = [0.2, 0.6, 1.0]
    batch = reframe.plan_frames_rgb(plan, str(golden_ride_segment), times)
    for i, t in enumerate(times):
        single = reframe.plan_frames_rgb(plan, str(golden_ride_segment), [t])
        assert np.array_equal(batch[i], single[0]), (
            f"batch frame {i} (t={t}) does not match an independent single-frame "
            "read at the same timestamp — check the buffer-slicing offset")


def test_plan_frames_rgb_refuses_a_short_buffer(golden_ride_segment, tmp_path):
    """A time past the stream's end yields fewer frames; the exact-byte check must
    catch it rather than reshape whatever arrived."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    with pytest.raises(RuntimeError, match="asked for"):
        reframe.plan_frames_rgb(plan, str(golden_ride_segment), [0.1, 999.0])


def test_plan_frames_rgb_refuses_a_buffer_that_is_a_MULTIPLE_of_the_wanted_size(
        golden_ride_segment, tmp_path, monkeypatch):
    """The exact-byte check must be `!=`, never `% want == 0`: the mutation-battery
    row for this line (grade-sensor-references Task 10) found that
    test_plan_frames_rgb_refuses_a_short_buffer above does NOT discriminate `!=`
    from `% want != 0` — its own shortfall (1 real frame against 2 requested) is
    not a whole multiple of `want`, so both forms raise for it. The function's own
    comment names the real vacuous case: a buffer that is SOME OTHER exact multiple
    of `want` (double, triple, ... or empty) satisfies a modulo check while still
    being the wrong length. Forced here by feeding a real, correctly-shaped buffer
    back TWICE — `2*want % want == 0`, so a modulo guard would silently accept it
    and go on to slice frames out of it, while `!=` still catches the wrong length."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    real_run = reframe.proc.run

    def _doubled_stdout(cmd):
        result = real_run(cmd)
        result.stdout = result.stdout * 2
        return result

    monkeypatch.setattr(reframe.proc, "run", _doubled_stdout)
    with pytest.raises(RuntimeError, match="asked for"):
        reframe.plan_frames_rgb(plan, str(golden_ride_segment), [0.2, 0.6, 1.0])
