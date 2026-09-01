"""Unit tests for check_episode's pure pixel-sampling helper — a synthetic
numpy frame is all `_box_mean_rgb` needs, so this needs no ffmpeg and does not
belong in tests/integration/test_color_fidelity.py.

_box_mean_rgb's clamp is asymmetric by construction and was NOT symmetric
before fix round 2 (2026-08-28 grade-delta-sensors Task 2 review): x0/y0 were
only lower-bounded (`max(0, x0)`), so a box beginning past the frame's right or
bottom edge left x0 (or y0) sitting beyond the frame. The subsequent x1/y1
clamp could then only shrink DOWN to that same out-of-range x0/y0, producing an
empty slice — and `.mean()` of an empty array returns (nan, nan, nan) with only
a RuntimeWarning, never a raise. The fix clamps x0/y0 into [0, w-1]/[0, h-1]
FIRST, so they can never sit past the frame themselves, before x1/y1 are
clamped relative to them.

The `grade_damage` section below (design 2026-08-31 §3) is a different shape —
it needs a real (graded, plain) RenderPlan pair, which needs a real manifest and
a real render, so it goes through `golden_ride_segment` + the committed
`tests/fixtures/golden_route.json` rather than a synthetic numpy frame.
"""
import numpy as np

from scripts import check_episode, process_episode, reframe
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.models import CheckSpec, Delivery


def test_box_entirely_past_the_right_edge_reproduces_the_reported_case():
    """The reviewer's own repro: box (700, 100, 750, 150) against a 640x360
    frame — x0 and x1 both past the right edge (640). The fixed clamp
    collapses this to the frame's single rightmost column; fill that column
    with a known colour so the result is a real, predictable RGB rather than
    (nan, nan, nan)."""
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[:, 639] = (200, 100, 50)          # the rightmost column, known colour
    r, g, b = check_episode._box_mean_rgb(frame, (700, 100, 750, 150))
    assert not any(np.isnan(v) for v in (r, g, b)), (r, g, b)
    assert (r, g, b) == (200.0, 100.0, 50.0)


def test_box_entirely_past_the_bottom_edge():
    """y0 and y1 both past the frame's height (20): collapses to the bottom row."""
    frame = np.zeros((20, 10, 3), dtype=np.uint8)
    frame[19, :] = (5, 15, 25)              # the bottom row, known colour
    r, g, b = check_episode._box_mean_rgb(frame, (2, 25, 8, 30))
    assert not any(np.isnan(v) for v in (r, g, b)), (r, g, b)
    assert (r, g, b) == (5.0, 15.0, 25.0)


def test_box_entirely_left_and_above_with_negative_coordinates():
    """All four coordinates negative: collapses to the single top-left pixel
    (0, 0) — not the top-left corner of some wider clamped region. (This side
    of the clamp was already lower-bounded correctly before the fix; kept here
    as a regression pin so a future rewrite of the clamp can't break it while
    fixing the other side.)"""
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[0, 0] = (9, 99, 199)               # the one pixel this must land on
    r, g, b = check_episode._box_mean_rgb(frame, (-30, -20, -10, -5))
    assert (r, g, b) == (9.0, 99.0, 199.0)


def test_normal_in_bounds_box_reads_the_predicted_mean():
    """No clamping at all: a box straddling two known colour halves must read
    their exact analytic mean, so the fix didn't disturb the ordinary path."""
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:, 5:] = (100, 100, 100)           # right half of the frame
    # box=(3,2,7,6): cols 3,4 (left half, 0) + 5,6 (right half, 100), rows 2-5.
    r, g, b = check_episode._box_mean_rgb(frame, (3, 2, 7, 6))
    assert (r, g, b) == (50.0, 50.0, 50.0)


# --- grade_damage (design 2026-08-31 §3): the entropy-ratio verdict, plans-gated ---
#
# `plans` is a real (graded, plain) RenderPlan pair — plan_frames_rgb decodes real
# ffmpeg bytes from them even in the tests below that stub gradedamage.evaluate, so
# a synthetic numpy frame (this file's usual style, above) cannot stand in for one.
# Built the same way process_episode will build it once Task 5 wires it through:
# process_episode.plan_for/plan_ungraded against a real manifest and the suite's
# own committed golden_ride_segment + golden_route.json (the same pair
# tests/lib/test_process_episode_plans.py and
# tests/integration/test_grade_sensor_calibration.py already build plans from).

_GOLDEN_ROUTE = "tests/fixtures/golden_route.json"


def _fake_manifest(src: str) -> dict:
    """Same shape as test_process_episode_plans.py's _md() — a real colour block
    (saturation/black_point) so plan_for's graded plan and plan_ungraded's plain
    plan actually differ, which is the damage sensor's whole premise."""
    return {"segment": src, "out_path": "/tmp/ep.mp4", "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480",
            "saturation": 0.8, "black_point": 0.1}


def _fake_plans(golden_ride_segment):
    """A (graded, plain) RenderPlan pair, real and renderable against
    golden_ride_segment — see the section banner above for why."""
    src = str(golden_ride_segment)
    md = _fake_manifest(src)
    return (process_episode.plan_for(md, src, _GOLDEN_ROUTE),
            process_episode.plan_ungraded(md, src, _GOLDEN_ROUTE))


def _run_check_episode(tmp_path, monkeypatch, golden_ride_segment, plans):
    """One real episode — golden_ride_segment + golden_route.json, rendered for
    real through reframe.reframe (mirrors
    tests/integration/test_color_fidelity.py's _render_episode) — then checked by
    check_episode.run, with `plans` threaded through as the grade_damage
    ingredient. `monkeypatch` is accepted (unused here) for symmetry with the
    caller, which patches scripts.lib.gradedamage.evaluate BEFORE calling this,
    not from inside it.

    A REAL render, not a hand-built sidecar: the route/path.json/path.meta.json
    it produces must agree with `source` (golden_ride_segment itself — the exact
    file `plans` was built against) for extent_at_times' projection, and for
    plan_frames_rgb's decode, to mean anything.
    """
    del monkeypatch
    src = str(golden_ride_segment)
    md = _fake_manifest(src)
    rspec = process_episode.build_reframe_spec(
        manifest_lib.Manifest.from_dict(md), Delivery.from_spec(md["delivery"]),
        dict(orch.DEFAULT_PARAMS))
    clip = str(tmp_path / "ep.mp4")
    reframe.reframe(rspec, src, _GOLDEN_ROUTE, clip, str(tmp_path / "path.json"))
    spec = CheckSpec(composition="center", grid="thirds", target_dur=1.5)
    return check_episode.run(clip, _GOLDEN_ROUTE, str(tmp_path / "path.json"), spec,
                             str(tmp_path / "report.json"), source=src, plans=plans)


def test_grade_damage_is_not_checked_without_plans(tmp_path, monkeypatch, golden_ride_segment):
    """Same shape `source` already uses: absent input reports absent, never a
    clean pass, and never blocks."""
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment, plans=None)
    d = rep.checks["grade_damage"]
    assert d.passed is None
    assert d.detail["status"] == "not-checked"
    assert "color_fidelity" not in rep.checks


def test_grade_damage_blocks_when_the_ratio_is_below_the_floor(tmp_path, monkeypatch,
                                                               golden_ride_segment):
    # NOTE: the brief's stub used positional-looking names (p, g, floor); _grade_damage
    # calls gradedamage.evaluate with KEYWORD arguments (plain=, graded=, floor=) —
    # deliberately, per gradedamage.evaluate's own keyword-only signature — so the
    # stub's parameter names must match those keywords or the call raises TypeError
    # before ever reaching this stub.
    monkeypatch.setattr(check_episode.gradedamage, "evaluate",
                        lambda plain, graded, floor: {"ratio": 0.80, "plain_bits": 7.0,
                                                       "graded_bits": 5.6, "floor": floor,
                                                       "frames": 3, "below": True})
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment,
                             plans=_fake_plans(golden_ride_segment))
    assert rep.checks["grade_damage"].passed is False
    assert "grade_damage" in rep.fail_reasons


def test_the_subject_dE00_survives_as_an_advisory_number(tmp_path, monkeypatch,
                                                          golden_ride_segment):
    """It is a good DESCRIPTION of what a grade did and the QC judge reads it. It
    is not a gate: a conductor pair puts 5 of 8 real episodes over the old 5.0
    ceiling and none of them is damage (design §0.1)."""
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment,
                             plans=_fake_plans(golden_ride_segment))
    d = rep.checks["grade_damage"].detail
    assert "delta_e" in d and "dominant" in d
    assert d["advisory_delta_e"] is True
    assert d["samples"] == 5
