import math

import pytest

from scripts.lib import kenburns
from scripts.lib.kenburns import Rect
from scripts.lib.models import StillSpec

PORTRAIT = (3024, 4032)
LANDSCAPE = (4000, 3000)


def _inside(r: Rect, photo, eps=1e-6) -> bool:
    return (r.x >= -eps and r.y >= -eps and r.x + r.w <= photo[0] + eps
            and r.y + r.h <= photo[1] + eps)


def test_the_base_frame_is_the_float_crop_not_the_truncated_one():
    assert kenburns.base_size(PORTRAIT, (9, 16), 1.0) == (2268.0, 4032.0)
    assert kenburns.base_size(LANDSCAPE, (9, 16), 1.0) == (1687.5, 3000.0)   # crop_for: 1687
    assert kenburns.base_size(LANDSCAPE, (4000, 3000), 0.5) == (2000.0, 1500.0)


def test_center_puts_the_subject_mid_frame_and_clamps_at_the_edge():
    size = kenburns.base_size(LANDSCAPE, (9, 16), 1.0)
    mid = kenburns.place(LANDSCAPE, size, Rect(1900, 1000, 200, 800), "center", "thirds")
    assert mid.x + mid.w / 2 == pytest.approx(2000)
    edge = kenburns.place(LANDSCAPE, size, Rect(3900, 1000, 100, 800), "center", "thirds")
    assert edge.x == pytest.approx(LANDSCAPE[0] - size[0])          # clamped, not off the photo


def test_lead_keeps_the_photographers_side():
    size = kenburns.base_size(LANDSCAPE, (9, 16), 1.0)
    left = kenburns.place(LANDSCAPE, size, Rect(1200, 1000, 200, 800), "lead", "thirds")
    right = kenburns.place(LANDSCAPE, size, Rect(2700, 1000, 200, 800), "lead", "thirds")
    assert (1300 - left.x) / left.w == pytest.approx(1 / 3)        # subject left of centre
    assert (2800 - right.x) / right.w == pytest.approx(2 / 3)      # ... and right of it


def test_no_subject_centres_the_frame_and_the_move_on_the_photo():
    pl = kenburns.plan(LANDSCAPE, (9, 16), 1.0, None, "lead", "thirds", StillSpec(1.0, 0.9), 30)
    assert pl.base.x == pytest.approx((4000 - 1687.5) / 2)
    assert pl.anchor == pytest.approx((2000.0, 1500.0))
    last = pl.frames[-1]
    assert last.x + last.w / 2 == pytest.approx(2000.0)


def test_the_subject_holds_still_on_screen_through_the_whole_move():
    subj = Rect(1200, 900, 300, 900)
    pl = kenburns.plan(LANDSCAPE, (9, 16), 1.0, subj, "lead", "thirds", StillSpec(1.0, 0.8), 60)
    px, py = pl.anchor
    rel = {(round((px - f.x) / f.w, 9), round((py - f.y) / f.h, 9)) for f in pl.frames}
    assert len(rel) == 1                                              # a homothety: P is fixed
    assert all(_inside(f, LANDSCAPE) for f in pl.frames)


def test_scale_runs_log_linear_over_a_smoothstep_from_end_to_end():
    pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, None, "center", "thirds", StillSpec(1.0, 0.81), 101)
    s = [f.w / pl.base.w for f in pl.frames]
    assert s[0] == pytest.approx(1.0) and s[-1] == pytest.approx(0.81)
    assert s[50] == pytest.approx(math.sqrt(0.81))                   # geometric midpoint
    steps = [abs(b - a) for a, b in zip(s, s[1:])]
    assert steps[0] < steps[50] / 20 and steps[-1] < steps[50] / 20  # eased ends
    assert all(b < a for a, b in zip(s, s[1:]))                      # monotone, no stall


def test_a_pull_out_starts_tight():
    pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, None, "center", "thirds", StillSpec(0.9, 1.0), 10)
    assert pl.frames[0].w == pytest.approx(0.9 * pl.base.w)
    assert pl.frames[-1].w == pytest.approx(pl.base.w)


def test_a_still_without_a_move_repeats_the_base_frame():
    pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, None, "center", "thirds", StillSpec(1.0, 1.0), 5)
    assert {f for f in pl.frames} == {pl.base}


def _keeps(frame: Rect, box: Rect, eps=1e-6) -> bool:
    return (frame.x <= box.x + eps and frame.y <= box.y + eps
            and frame.x + frame.w >= box.x + box.w - eps
            and frame.y + frame.h >= box.y + box.h - eps)


def test_the_move_is_shortened_rather_than_cut_the_subjects_upper_half():
    subj = Rect(400, 500, 1400, 3000)              # most of a 2268-wide portrait frame
    pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, subj, "center", "thirds", StillSpec(1.0, 0.5), 30)
    assert pl.applied.end > 0.5 and "shortened" in pl.note
    assert all(_keeps(f, kenburns.held(subj)) for f in pl.frames)
    assert pl.planned == StillSpec(1.0, 0.5)       # what was asked stays on the record


def test_a_standing_figure_on_the_bottom_edge_keeps_its_head():
    """The 2026-10-20 review's case: a person whose box runs to the bottom of the photo.
    The old rule gave up when the margin crossed the edge, ran the full push and cut
    65 px off the head; the feet are what a portrait push may cut."""
    subj = Rect(900, 100, 1200, 3932)
    for move in (StillSpec(1.0, 0.92), StillSpec(1.0, 0.8)):
        pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, subj, "center", "thirds", move, 40)
        head = kenburns.held(subj)
        assert all(_keeps(f, head) for f in pl.frames), move
        assert pl.frames[-1].y <= head.y - 50 + 1e-6      # half the 100 px it had
        assert pl.applied.end < 0.96 and "shortened" in pl.note   # it still moves
        assert "outside" not in pl.note and "already cuts" not in pl.note


def test_the_gap_kept_is_the_margin_or_half_the_room_whichever_is_smaller():
    base = Rect(0, 0, 2268, 4032)
    tight = Rect(500, 30, 1000, 1000)               # 30 px of room above: keep 15
    assert kenburns.hold_scale(base, (1000.0, 530.0), tight) == pytest.approx(
        (530 - 15) / 530)
    roomy = Rect(1084, 800, 100, 1000)              # 800 px above: keep the 50 px margin
    assert kenburns.hold_scale(base, (1134.0, 1300.0), roomy) == pytest.approx(
        (1300 - 750) / 1300)
    touching = Rect(500, 0, 1000, 1000)             # no room at all: no move keeps it
    assert kenburns.hold_scale(base, (1000.0, 500.0), touching) == 1.0


def test_a_side_the_base_frame_already_cuts_sets_no_limit():
    subj = Rect(100, 500, 2900, 3000)              # wider than the 2268 frame
    pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, subj, "center", "thirds", StillSpec(1.0, 0.9), 10)
    assert pl.applied == StillSpec(1.0, 0.9)
    assert "already cuts the subject's upper half on the left/right" in pl.note


def test_break_clamps_the_anchor_into_the_frame_so_no_frame_leaves_the_photo():
    subj = Rect(3800, 100, 150, 300)               # far right; a `break` frame sits mid-photo
    pl = kenburns.plan(LANDSCAPE, (9, 16), 1.0, subj, "break", "thirds", StillSpec(1.0, 0.6), 40)
    assert pl.base.x == pytest.approx((4000 - 1687.5) / 2)
    assert pl.anchor[0] == pytest.approx(pl.base.x + pl.base.w)
    assert all(_inside(f, LANDSCAPE) for f in pl.frames)


def test_one_frame_is_the_end_of_the_move():
    pl = kenburns.plan(PORTRAIT, (9, 16), 1.0, None, "center", "thirds", StillSpec(1.0, 0.9), 1)
    assert pl.frames[0].w == pytest.approx(0.9 * pl.base.w)
    with pytest.raises(ValueError, match="at least one frame"):
        kenburns.plan(PORTRAIT, (9, 16), 1.0, None, "center", "thirds", StillSpec(1.0, 0.9), 0)


@pytest.mark.parametrize("bad", [0.0, 1.01, -0.5, True, "0.9", None])
def test_still_spec_refuses_a_fraction_outside_the_frame(bad):
    with pytest.raises(ValueError, match="StillSpec"):
        StillSpec(start=1.0, end=bad)


def test_still_spec_wire_form_and_its_refusals():
    assert StillSpec.from_dict({"from": 1.0, "to": 0.92}).to_dict() == {"from": 1.0, "to": 0.92}
    for d in ({"from": 1.0}, {"from": 1, "to": 1, "x": 1}, [1, 0.9]):
        with pytest.raises(ValueError, match="StillSpec.from_dict"):
            StillSpec.from_dict(d)
