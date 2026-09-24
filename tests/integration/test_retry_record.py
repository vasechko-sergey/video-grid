"""The retry loop's record, proved against real pixels (design 2026-09-24 §4).

Every test here uses `golden_ride_segment` — the committed golden_ride.mp4 through
the range conversion — and the committed golden_route.json sampled against that
clip's own timeline. The real run cannot prove any of this any more: four of its
eight episodes, including the one retried episode the row was filed from, are
refused by plan_render's range guard before the drift oracle runs (§0.4).
"""
import json

import pytest

from scripts import process_episode, probe, reframe
from scripts.lib import orchestration as orch
from scripts.lib.models import Delivery, ReframeSpec

ROUTE = "tests/fixtures/golden_route.json"


def _spec(**over):
    kw = dict(composition="center", grid="thirds", canvas=(9, 16),
              color_means=(128.0, 128.0, 128.0), delivery=Delivery.from_spec("native"))
    kw.update(over)
    return ReframeSpec(**kw)


@pytest.mark.integration
def test_one_ladder_step_moves_the_crop_path(golden_ride_segment):
    """§0.5, kept as a test. If this ever reports 0 moved samples the slice's whole
    premise is gone — the params would be unobservable in the geometry and nothing
    would need recording.

    Both knobs are asserted separately because they are NOT equally load-bearing:
    on this fixture the smoothing window does all the work and max_speed moves one
    sample by one pixel. Recording max_speed is still required, because
    _refuse_on_drift compares the path exactly and one pixel refuses as loudly as
    five — but a reader must not be told the two matter equally.
    """
    src = str(golden_ride_segment)
    base = reframe.plan_render(_spec(), src, ROUTE)
    stepped = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["jitter"])
    assert stepped == {"max_speed": 450.0, "smooth_window_s": 0.5}

    after = reframe.plan_render(_spec(**stepped), src, ROUTE)
    moved = [i for i, (a, b) in enumerate(zip(base.path, after.path)) if a != b]
    assert len(base.path) == len(after.path) == 95
    assert len(moved) == 74
    assert max(abs(a - b) for a, b in zip(base.path, after.path)) == 5

    speed_only = reframe.plan_render(_spec(max_speed=450.0), src, ROUTE)
    window_only = reframe.plan_render(_spec(smooth_window_s=0.5), src, ROUTE)
    assert sum(1 for a, b in zip(base.path, speed_only.path) if a != b) == 1
    assert sum(1 for a, b in zip(base.path, window_only.path) if a != b) == 74


@pytest.mark.integration
def test_a_first_lag_retry_moves_nothing_on_this_footage(golden_ride_segment):
    """§0.5's sharper half, kept so the slice cannot over-claim. The lag branch
    raises max_speed to 1125 and leaves the window alone — its own halving is
    `max(lo, w / 2)` where w starts AT lo, so it is inert until an earlier round has
    already widened it. The result here is a byte-identical path: on this footage a
    first on_line/centered retry was never broken, the oracle always passed, and a
    reader rebuilding at the defaults was already right.

    Recorded as a test and not only as a design sentence because it is the one
    number that bounds this slice's claim, and a change to the ladder or to
    pathsmooth would move it silently."""
    src = str(golden_ride_segment)
    base = reframe.plan_render(_spec(), src, ROUTE)
    lag = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["on_line"])
    assert lag == {"max_speed": 1125.0, "smooth_window_s": 0.25}
    after = reframe.plan_render(_spec(**lag), src, ROUTE)
    assert list(after.path) == list(base.path)


#: Every check name check_episode.run can put in report.fail_reasons — the only
#: strings adjust_reframe_params is ever called with in production. Pinned as a
#: literal rather than imported, because the claim below is about THIS set: a check
#: added to check_episode without a decision about the retry ladder should break
#: this test, which importing the live list would prevent it from doing.
_EPISODE_CHECKS = ("framing", "centered", "on_line", "jitter", "continuity",
                   "length", "black_frames", "grade_damage", "horizon",
                   "head_power_point")


def test_exactly_three_fail_reasons_move_a_retry_knob():
    """§0.6, and the bound on where this slice's defect can bite. A retry for any
    other reason re-renders the same geometry, so it records nothing and needs no
    record.

    Exhaustive over check_episode's own vocabulary, not a hand-picked sample: the
    first version of this test listed `composition`, `black` and `hero` among the
    negatives, and none of the three can ever reach adjust_reframe_params —
    `composition` and `hero` are episode-QC judge axes, `black` is the reel-level
    spelling of `black_frames`. The function does plain string membership with no
    validation, so those three passed for free while the three real non-movers
    (`length`, `continuity`, `black_frames`) went untested.

    Asserted on the params dict, not on a rendered path: this is a claim about the
    ladder's own branching, and comparing renders would rest it on the renderer's
    determinism instead.
    """
    base = dict(orch.DEFAULT_PARAMS)
    movers = {r for r in _EPISODE_CHECKS
              if orch.adjust_reframe_params(base, [r]) != base}
    assert movers == {"on_line", "centered", "jitter"}
    # and every _UNFIXABLE reason is among the non-movers, which is the pairing that
    # matters: a reason the ladder cannot fix must also not be one it silently
    # rescales a knob for.
    assert set(orch._UNFIXABLE) & movers == set()


@pytest.mark.integration
def test_the_sidecar_lets_a_retried_render_be_replanned_exactly(golden_ride_segment, tmp_path):
    """§4.4, the round trip. Render at attempt-2 params, then rebuild the plan from
    the sidecar: the oracle passes. Rebuild it from the manifest alone and the
    oracle refuses — which is what every reader did before this slice."""
    src = str(golden_ride_segment)
    d = tmp_path / "ep0"
    d.mkdir()
    out = str(d / "out.mp4")
    path_out = str(d / "path.json")
    meta_out = str(d / "path.meta.json")
    spec = _spec(max_speed=450.0, smooth_window_s=0.5)
    reframe.reframe(spec, src, ROUTE, out, path_out)

    md = {"segment": src, "out_path": out, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "canvas": [9, 16]}

    params = process_episode.rendered_params(meta_out)
    assert params == {"max_speed": 450.0, "smooth_window_s": 0.5}
    probe._refuse_on_drift(process_episode.plan_for(md, src, ROUTE, params=params),
                           path_out, meta_out)

    with pytest.raises(RuntimeError, match=r"recomputed crop path does not match"):
        probe._refuse_on_drift(process_episode.plan_for(md, src, ROUTE),
                               path_out, meta_out)


@pytest.mark.integration
def test_an_unretried_render_writes_the_sidecar_it_always_wrote(golden_ride_segment, tmp_path):
    """The control that must not move. An episode at the defaults writes neither
    key, so every golden sidecar and every byte-identity claim in the suite holds."""
    d = tmp_path / "ep0"
    d.mkdir()
    reframe.reframe(_spec(), str(golden_ride_segment), ROUTE,
                    str(d / "out.mp4"), str(d / "path.json"))
    written = json.loads((d / "path.meta.json").read_text())
    assert "max_speed" not in written and "smooth_window_s" not in written
    assert process_episode.rendered_params(d / "path.meta.json") is None
