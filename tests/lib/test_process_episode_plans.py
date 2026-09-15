"""process_episode.plan_for / plan_ungraded — the ONE manifest -> RenderPlan map."""
import dataclasses
import json
from pathlib import Path

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
    would be measuring a crop, not a grade.

    Exhaustive on purpose, not sampled: a later task's sensor takes the two plans'
    entropy ratio as a pure colour reading only because EVERY other field agrees, so
    a field this test forgot to check is a field the sensor's premise silently stops
    holding for. `dataclasses.astuple` covers the whole of ResolvedLayout, including
    any field added to it after this test was written, rather than the two fields
    (out_w/out_h) a hand-picked list would freeze in place.
    """
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    a = process_episode.plan_for(_md(src), src, route)
    b = process_episode.plan_ungraded(_md(src), src, route)
    assert a.path == b.path
    assert dataclasses.astuple(a.rl) == dataclasses.astuple(b.rl)
    assert a.src_w == b.src_w and a.src_h == b.src_h
    assert a.crop_ws == b.crop_ws and a.crop_hs == b.crop_hs and a.crop_ys == b.crop_ys
    assert a.cy == b.cy and a.fps == b.fps and a.dur == b.dur
    assert a.grade != b.grade
    # filter_args is the actual argv the render consumes, not just the geometry that
    # derives it — reframe._filter_args always splices `grade` in literally (right
    # before the shared ",fps=...,format=yuv420p" tail), on both the fast-path -vf
    # string and the -filter_complex graph, so subtracting each plan's own grade
    # substring from its own chain isolates everything else the chain carries.
    assert a.filter_args[0] == b.filter_args[0]
    assert a.grade in a.filter_args[1] and b.grade in b.filter_args[1]
    assert a.filter_args[1].replace(a.grade, "") == b.filter_args[1].replace(b.grade, "")


def test_plan_for_honours_an_AUTHORED_smooth_window_s_not_just_the_default(golden_ride_segment):
    """`plan_for`'s own docstring says it builds from orch.DEFAULT_PARAMS 'plus an
    authored smooth_window_s' — nothing else in this file supplies one, so a
    regression that read the default unconditionally (ignoring `m.smooth_window_s`)
    left every other test here green (grade-sensor-references Task 10 mutation
    battery, row 10). A real route with real movement (golden_route.json) is what
    makes the savgol window observable at all: a much wider window (1.5s) against
    the 0.25s default must smooth the crop path into a DIFFERENT trajectory."""
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    default = process_episode.plan_for(_md(src), src, route)
    wide = process_episode.plan_for(dict(_md(src), smooth_window_s=1.5), src, route)
    assert wide.path != default.path


def test_color_measure_no_longer_owns_a_second_copy():
    assert not hasattr(color_measure, "plan_ungraded")


def test_plan_ungraded_is_plan_for_of_a_stripped_manifest(golden_ride_segment):
    src, route = str(golden_ride_segment), "tests/fixtures/golden_route.json"
    a = process_episode.plan_ungraded(_md(src), src, route)
    b = process_episode.plan_for(manifest_lib.strip_colour(_md(src)), src, route)
    assert a.grade == b.grade and a.filter_args == b.filter_args


def test_plan_and_meta_ungraded_needs_no_rendered_sidecar(tmp_path, golden_ride_segment):
    """Measured: stop_after='geometry' returns at process_episode.py:437, before
    reframe runs — and reframe is what writes path.json. At conductor time the
    sidecar does not exist. This is the guard on that."""
    md = _md(golden_ride_segment)
    route = str(tmp_path / "route.json")
    Path(route).write_text(json.dumps(
        [dict(t=0.0, x=960.0, y=540.0, w=120.0, h=120.0),
         dict(t=1.0, x=960.0, y=540.0, w=120.0, h=120.0)]))
    plan, path, meta = process_episode.plan_and_meta_ungraded(
        md, golden_ride_segment, route)
    assert len(path) == len(plan.path)
    assert meta.out_dims == (plan.rl.out_w, plan.rl.out_h)
    assert not (tmp_path / "path.json").exists()     # writes nothing
    assert not (tmp_path / "path.meta.json").exists()
