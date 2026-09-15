"""The two thresholds this slice introduces, measured on real bytes.

Not a proof of behaviour — a proof that the CONSTANTS are where the footage puts
them. Each assertion brackets the measured value loosely enough to survive an
ffmpeg point release and tightly enough to fail if the number moves for a reason.
"""
import pytest

from scripts import color_measure, process_episode, reframe
from scripts.lib import color, gradedamage
from scripts.lib import orchestration as orch
from scripts.lib.manifest import Manifest
from scripts.lib.models import Delivery

pytestmark = pytest.mark.integration

ROUTE = "tests/fixtures/golden_route.json"


def _md(seg: str, out: str, **colour) -> dict:
    md = {"segment": seg, "out_path": out, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "layout": "fill",
          "canvas": [9, 16], "delivery": "short_edge:480"}
    md.update(colour)
    return md


def _ratio(md: dict, src: str) -> float:
    graded = process_episode.plan_for(md, src, ROUTE)
    plain = process_episode.plan_ungraded(md, src, ROUTE)
    times = color.sample_times(graded.dur)
    d = gradedamage.evaluate(plain=reframe.plan_frames_rgb(plain, src, times),
                             graded=reframe.plan_frames_rgb(graded, src, times),
                             floor=0.90)
    return d["ratio"]


def test_the_entropy_floor_sits_between_a_legitimate_grade_and_a_damaging_one(
        golden_ride_segment, tmp_path):
    """§0.4's 1.2% margin, re-measured on the fixture the suite owns.

    A legitimate grade is a conductor-shaped tone pair: measure this crop's own
    profile and pull it toward a plausible common target. A damaging one is
    black_point at its documented maximum."""
    src = str(golden_ride_segment)
    prof, _ = color_measure.measure_crop(_md(src, str(tmp_path / "a.mp4")), src, ROUTE)
    target = [round(prof[0] + 12, 1), round(prof[1] - 10, 1), round(prof[2] - 18, 1)]
    legit = _ratio(_md(src, str(tmp_path / "b.mp4"),
                       tone_src=list(prof), tone_dst=target), src)
    damaged = _ratio(_md(src, str(tmp_path / "c.mp4"), black_point=0.35), src)
    print(f"\nMEASURED entropy ratio: legitimate {legit:.3f}  damaging {damaged:.3f}")
    assert damaged < legit, "the classes must not invert on this fixture"
    assert damaged < 0.90 <= legit, (
        f"entropy_floor = 0.90 must separate them: legit {legit}, damaged {damaged}")


def test_an_ungraded_episode_reads_exactly_one(golden_ride_segment, tmp_path):
    """The control that must not move: with no colour block the two plans are the
    same render, so the ratio is 1.0 by construction. A sensor that drifts here is
    measuring the render, not the grade."""
    src = str(golden_ride_segment)
    assert _ratio(_md(src, str(tmp_path / "d.mp4")), src) == pytest.approx(1.0, abs=1e-3)


def test_the_faithfulness_residual_of_a_healthy_render_is_small(
        golden_ride_segment, tmp_path):
    """grade_residual_max's floor: render the episode for real, then compare the
    master's own profile against what the plan predicts. This is the number the
    ceiling must clear."""
    src = str(golden_ride_segment)
    out = str(tmp_path / "ep.mp4")
    md = _md(src, out, tone_src=[40.0, 120.0, 200.0], tone_dst=[52.0, 104.0, 192.0],
             black_point=0.05)
    plan = process_episode.plan_for(md, src, ROUTE)
    rspec = process_episode.build_reframe_spec(
        Manifest.from_dict(md), Delivery.from_spec(md["delivery"]),
        dict(orch.DEFAULT_PARAMS))
    reframe.reframe(rspec, src, ROUTE, out, str(tmp_path / "path.json"))
    times = color.sample_times(plan.dur)
    predicted = color_measure.crop_percentiles(plan, src, times)
    got = color_measure.clip_percentiles(out, times)
    residual = max(abs(a - b) for a, b in zip(got, predicted))
    print(f"\nMEASURED faithfulness residual (healthy, WITH a post-tone knob): {residual:.2f}")
    assert residual < 4.0, (
        f"a healthy render must sit well inside grade_residual_max; got {residual}")
