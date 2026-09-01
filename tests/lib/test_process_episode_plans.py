"""process_episode.plan_for / plan_ungraded — the ONE manifest -> RenderPlan map."""
import pytest

from scripts import color_measure, process_episode
from scripts.lib import manifest as manifest_lib


def _md(seg: str) -> dict:
    return {"segment": seg, "out_path": "/tmp/ep.mp4", "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480",
            "saturation": 0.8, "black_point": 0.1}


def test_plan_for_carries_the_colour_block(golden_ride_segment):
    plan = process_episode.plan_for(_md(str(golden_ride_segment)),
                                    str(golden_ride_segment),
                                    "tests/fixtures/golden_route.json")
    assert "eq=saturation=0.8000" in plan.grade
    assert "colorlevels" in plan.grade


def test_plan_ungraded_strips_it(golden_ride_segment):
    plan = process_episode.plan_ungraded(_md(str(golden_ride_segment)),
                                         str(golden_ride_segment),
                                         "tests/fixtures/golden_route.json")
    assert "eq=saturation" not in plan.grade
    assert "colorlevels" not in plan.grade


def test_the_two_plans_differ_ONLY_in_the_colour_tail(golden_ride_segment):
    """The damage sensor's whole premise. If geometry moved too, the entropy ratio
    would be measuring a crop, not a grade."""
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    a = process_episode.plan_for(_md(src), src, route)
    b = process_episode.plan_ungraded(_md(src), src, route)
    assert a.path == b.path
    assert (a.rl.out_w, a.rl.out_h) == (b.rl.out_w, b.rl.out_h)
    assert a.crop_ws == b.crop_ws and a.crop_hs == b.crop_hs and a.crop_ys == b.crop_ys
    assert a.cy == b.cy and a.fps == b.fps and a.dur == b.dur
    assert a.grade != b.grade


def test_color_measure_no_longer_owns_a_second_copy():
    assert not hasattr(color_measure, "plan_ungraded")


def test_plan_ungraded_is_plan_for_of_a_stripped_manifest(golden_ride_segment):
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    a = process_episode.plan_ungraded(_md(src), src, route)
    b = process_episode.plan_for(manifest_lib.strip_colour(_md(src)), src, route)
    assert a.grade == b.grade and a.filter_args == b.filter_args
