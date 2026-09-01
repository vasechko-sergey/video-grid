"""reframe.frames_rgb over real ffmpeg — the plan's RGB sink."""
import numpy as np
import pytest

from scripts import process_episode, reframe

pytestmark = pytest.mark.integration


def _manifest(seg: str, out: str) -> dict:
    return {"segment": seg, "out_path": out, "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480"}


def test_frames_rgb_returns_one_frame_per_time_at_output_dims(golden_ride_segment, tmp_path):
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    times = [0.2, 0.6, 1.0]
    frames = reframe.frames_rgb(plan, str(golden_ride_segment), times)
    assert len(frames) == 3
    for f in frames:
        assert f.shape == (plan.rl.out_h, plan.rl.out_w, 3)
        assert f.dtype == np.uint8


def test_frames_rgb_returns_DIFFERENT_frames_not_one_repeated(golden_ride_segment, tmp_path):
    """The §12 select landmine: a select before the chain's own fps= emits ONE frame
    N times and the count still comes out right, so a length assertion cannot see it."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    frames = reframe.frames_rgb(plan, str(golden_ride_segment), [0.1, 0.7, 1.3])
    assert not np.array_equal(frames[0], frames[1])
    assert not np.array_equal(frames[1], frames[2])


def test_frames_rgb_refuses_a_short_buffer(golden_ride_segment, tmp_path):
    """A time past the stream's end yields fewer frames; the exact-byte check must
    catch it rather than reshape whatever arrived."""
    md = _manifest(str(golden_ride_segment), str(tmp_path / "ep.mp4"))
    plan = process_episode.plan_for(md, str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    with pytest.raises(RuntimeError, match="asked for"):
        reframe.frames_rgb(plan, str(golden_ride_segment), [0.1, 999.0])
