import json

import numpy as np
import pytest

from scripts.lib import color, regions


def test_a_full_declaration_round_trips():
    d = {"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"},
        {"anchor": "shoulder", "name": "frame", "of": "crop"}]}
    r = regions.Regions.from_dict(d)
    assert r.to_dict() == d
    assert r.declared("toe") == regions.AnchorRegion("toe", "wetsuit", "subject")


def test_an_undeclared_anchor_is_the_crop_and_says_so_in_its_name():
    r = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    assert r.declared("mid") == regions.AnchorRegion("mid", "crop", "crop")


def test_an_unknown_anchor_slot_is_refused_by_name():
    with pytest.raises(ValueError, match="knee"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "knee", "name": "x", "of": "crop"}]})


def test_an_unknown_region_kind_is_refused_by_name():
    with pytest.raises(ValueError, match="sky"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "x", "of": "sky"}]})


def test_an_empty_author_name_is_refused():
    with pytest.raises(ValueError, match="name"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "  ", "of": "subject"}]})


def test_one_anchor_declared_twice_is_refused_at_load():
    with pytest.raises(ValueError, match="toe"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "a", "of": "subject"},
            {"anchor": "toe", "name": "b", "of": "background"}]})


def test_an_extra_field_is_refused_not_ignored():
    with pytest.raises(ValueError, match="band"):
        regions.Regions.from_dict({"anchors": [
            {"anchor": "toe", "name": "a", "of": "subject", "band": [0, 0.4]}]})


def test_a_non_object_top_level_is_refused():
    with pytest.raises(ValueError, match="REGIONS.json"):
        regions.Regions.from_dict([])


def test_a_missing_anchors_list_is_refused():
    with pytest.raises(ValueError, match="anchors"):
        regions.Regions.from_dict({})


def test_from_json_names_the_file_on_a_syntax_error(tmp_path):
    p = tmp_path / "REGIONS.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match=str(p)):
        regions.Regions.from_json(p)


def test_the_three_closed_sets_and_their_order():
    """ANCHORS' ORDER is load-bearing, not cosmetic: it is the order of a profile
    tuple, so assemble indexes (p5, p50, p95) by it.

    FALLBACKS is pinned here for the same reason the other two are: it is a
    closed vocabulary the report prints verbatim, so its members are a contract
    with the reader (design §3 names exactly these three)."""
    assert regions.ANCHORS == ("toe", "mid", "shoulder")
    assert regions.KINDS == ("subject", "background", "crop")
    assert regions.FALLBACKS == ("no-route", "too-small", "unorderable")


def test_a_fallback_outside_the_set_is_refused_by_name():
    """The enforcement that makes FALLBACKS observable. Without it, renaming a
    literal inside `assemble` ("too-small" -> "tooSmall") would print a reason no
    vocabulary contains and nothing anywhere would notice."""
    with pytest.raises(ValueError, match="tooSmall"):
        regions.AnchorReading("toe", "wetsuit", "subject", "crop", 0.0, 50.0, "tooSmall")


def test_every_named_fallback_is_constructible():
    """The other half of the pin: the refusal must not be so strict that the three
    names `assemble` actually emits are themselves rejected."""
    for fb in (None, *regions.FALLBACKS):
        assert regions.AnchorReading("toe", "w", "subject", "crop", 0.0, 50.0, fb).fallback == fb


def _frames(rows):
    """(n, h, w) uint8 luma from a list of 2-D lists."""
    return np.array(rows, dtype=np.uint8)


def _split_frame(h=100, w=100, subject=40, bg=200):
    """One frame: a dark 10x10 block top-left in a bright field."""
    f = np.full((h, w), bg, dtype=np.uint8)
    f[0:10, 0:10] = subject
    return f[None, ...]


def test_measure_reports_the_three_regions_and_their_area_fractions():
    out = regions.measure(_split_frame(), [(0.0, 0.0, 0.1, 0.1)])
    assert out["subject"].fraction == pytest.approx(0.01)
    assert out["background"].fraction == pytest.approx(0.99)
    assert out["crop"].fraction == 1.0
    assert out["subject"].profile == (40.0, 40.0, 40.0)
    # This background assertion is NOT load-bearing and Task 7's battery (row 9)
    # proved it: the subject is exactly 1% of the frame, i.e. below p5, so pooling
    # it back into the background — `bg = frames` instead of `frames[~mask]` —
    # leaves all three percentiles at 200 and this test green.
    # test_measure_axis_mapping_on_non_square_frame_and_asymmetric_extent is what
    # actually catches that mutation: its subject is 6%, above the p5 cut.
    assert out["background"].profile == (200.0, 200.0, 200.0)


def test_the_crop_region_is_every_pixel_pooled_across_frames():
    f = np.concatenate([_split_frame(), _split_frame(subject=10)])
    out = regions.measure(f, [(0.0, 0.0, 0.1, 0.1)] * 2)
    hist = np.bincount(f.ravel(), minlength=256)[:256]
    assert out["crop"].profile == color.percentiles([int(c) for c in hist])


def test_no_route_leaves_subject_and_background_unmeasured():
    out = regions.measure(_split_frame(), None)
    assert out["subject"].profile is None and out["subject"].fraction == 0.0
    assert out["background"].profile is None
    assert out["crop"].profile is not None
    # `located` is the discriminator assemble reads for `no-route`; without it
    # here, a located-but-empty subject would be reported as a pan's missing route.
    assert out["subject"].located is False and out["background"].located is False
    assert out["crop"].located is True


def test_assemble_takes_each_anchor_from_its_declared_region():
    readings = {
        "subject": regions.RegionReading("subject", 0.2, (10.0, 20.0, 30.0)),
        "background": regions.RegionReading("background", 0.8, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (10.0, 120.0, 200.0)      # subject p5, background p50, crop p95
    assert [r.of for r in rows] == ["subject", "background", "crop"]
    assert [r.name for r in rows] == ["wetsuit", "water", "crop"]
    assert all(r.fallback is None for r in rows)


def test_a_region_under_the_area_gate_falls_back_to_crop_and_is_named():
    readings = {
        "subject": regions.RegionReading("subject", 0.002, (250.0, 251.0, 252.0)),
        "background": regions.RegionReading("background", 0.998, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    toe = rows[0]
    assert toe.fallback == "too-small" and toe.used == "crop"
    assert toe.of == "subject" and toe.fraction == pytest.approx(0.002)


def test_an_unmeasured_region_falls_back_as_no_route():
    """`located=False` is what `measure` sets when there are no extents at all —
    a pan episode, whose path is generated and whose route therefore does not
    exist. It is the ONLY thing that produces `no-route`."""
    readings = {
        "subject": regions.RegionReading("subject", 0.0, None, located=False),
        "background": regions.RegionReading("background", 0.0, None, located=False),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert rows[0].fallback == "no-route"


def test_a_located_but_empty_region_is_too_small_not_no_route():
    """Review finding 8. An episode WITH a route whose subject clamps to empty at
    every sample time — the rider walks fully out of the delivered frame — has a
    profile of None exactly as a pan's does, and the old `r.profile is None` test
    called it `no-route`, which is a false claim about an episode that has one.
    It is a region located and measured at 0.0 of the frame: `too-small`."""
    readings = {
        "subject": regions.RegionReading("subject", 0.0, None),          # located
        "background": regions.RegionReading("background", 1.0, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert rows[0].fallback == "too-small" and rows[0].fraction == 0.0
    assert rows[0].used == "crop" and rows[0].of == "subject"


def test_an_unorderable_profile_drops_the_WHOLE_episode_to_the_crop():
    # toe from a BRIGHT subject would land above the background's own p50
    readings = {
        "subject": regions.RegionReading("subject", 0.3, (150.0, 200.0, 240.0)),
        "background": regions.RegionReading("background", 0.7, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert [r.fallback for r in rows] == ["unorderable"] * 3
    assert [r.used for r in rows] == ["crop"] * 3


def test_a_profile_inside_the_gap_but_ordered_is_still_unorderable():
    # ordered, but the toe sits closer than TONE_MIN_GAP to the mid
    gap = color.TONE_MIN_GAP
    readings = {
        "subject": regions.RegionReading("subject", 0.3, (110.0 - gap / 2, 0.0, 0.0)),
        "background": regions.RegionReading("background", 0.7, (0.0, 112.0, 0.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"},
        {"anchor": "mid", "name": "water", "of": "background"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert [r.fallback for r in rows] == ["unorderable"] * 3


def test_no_declaration_is_three_crop_anchors_and_no_fallback():
    readings = {
        "subject": regions.RegionReading("subject", 0.2, (10.0, 20.0, 30.0)),
        "background": regions.RegionReading("background", 0.8, (60.0, 120.0, 180.0)),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    profile, rows = regions.assemble(regions.Regions(), readings)
    assert profile == (50.0, 110.0, 200.0)
    assert all(r.used == "crop" and r.fallback is None for r in rows)


def test_a_flat_crop_is_not_reported_as_three_unorderable_fallbacks():
    """A uniform crop cannot order, and no declaration caused that. Reporting it
    as a region fallback would blame the declaration for the footage; a flat
    source is matchgrade.valid_src's business and is skipped downstream as
    `flat-source`."""
    readings = {
        "subject": regions.RegionReading("subject", 0.0, None),
        "background": regions.RegionReading("background", 0.0, None),
        "crop": regions.RegionReading("crop", 1.0, (100.0, 100.0, 100.0))}
    profile, rows = regions.assemble(regions.Regions(), readings)
    assert profile == (100.0, 100.0, 100.0)
    assert all(r.fallback is None for r in rows)


def test_the_area_gate_is_one_percent():
    assert regions.MIN_REGION_FRAC == 0.01


def test_measure_axis_mapping_on_non_square_frame_and_asymmetric_extent():
    """The subject mask must not confuse x and y coordinates. A square frame
    and symmetric extent (like the other tests use) cannot detect this — swapping
    fx/fy or slicing [x0:x1, y0:y1] instead of [y0:y1, x0:x1] would select the
    same pixels and pass all existing assertions. This test uses a non-square
    frame (100 tall x 200 wide) and an off-origin asymmetric box."""
    # Frame: 100 tall x 200 wide, subject at [40:60, 40:100] = 20 rows x 60 cols
    f = np.full((100, 200), 200, dtype=np.uint8)
    f[40:60, 40:100] = 50  # subject region: distinct value
    frames = f[None, ...]  # shape (1, 100, 200)
    # Extent (fx0, fy0, fx1, fy1) in output-frame fractions maps to:
    # x0=40, x1=100 (0.2*200=40, 0.5*200=100)
    # y0=40, y1=60 (0.4*100=40, 0.6*100=60)
    out = regions.measure(frames, [(0.2, 0.4, 0.5, 0.6)])
    # Subject: 20 rows * 60 cols = 1200 pixels of value 50
    # Total: 100 * 200 = 20000 pixels
    expected_frac = 1200 / 20000  # 0.06
    assert out["subject"].fraction == pytest.approx(expected_frac)
    assert out["subject"].profile == (50.0, 50.0, 50.0)
    assert out["background"].fraction == pytest.approx(1.0 - expected_frac)
    assert out["background"].profile == (200.0, 200.0, 200.0)


def test_the_region_ruler_is_color_percentiles_where_another_estimator_would_disagree():
    """One ruler (plan Global Constraints: percentiles come from
    `color.percentiles` and from nowhere else) — pinned where the claim is
    actually observable.

    Found by Task 7's mutation battery, row 10: swapping `_profile`'s body for
    `np.percentile(pixels, [5, 50, 95])` — the obvious substitute — left ALL 23
    tests in this file green, plus tests/integration/test_color_measure.py,
    test_matchgrade.py, tests/lib/test_match_grade.py and the real-footage
    proofs in tests/integration/test_named_regions.py. Every one of those uses a
    frame whose bands are far enough apart, or a subject small enough, that the
    two rules land on the SAME code, so none of them was measuring the ruler.

    A 50/50 two-value frame is where the two rules provably part.
    `color.percentiles` walks a 256-bin histogram and returns the FIRST code
    whose cumulative count reaches the target, so at an exact 50% tie p50 is the
    DARK value; `np.percentile` interpolates between the two middle samples and
    returns their midpoint. The second assertion is what makes the first one a
    RULER test rather than a value pin: it states, on this same frame, the
    number the rejected estimator would have produced."""
    f = np.full((1, 100, 100), 200, dtype=np.uint8)
    f[:, :50, :] = 0
    out = regions.measure(f, None)
    assert out["crop"].profile == (0.0, 0.0, 200.0)
    assert float(np.percentile(f.ravel(), 50)) == 100.0     # the estimator NOT used


def test_subject_mask_marks_the_projected_box_and_reports_its_fraction():
    # One 10x10 frame, a box covering the middle 5x4 = 20 of 100 cells.
    mask, frac = regions.subject_mask([(0.2, 0.3, 0.7, 0.7)], 1, 10, 10)
    assert mask.shape == (1, 10, 10)
    assert mask[0, 3:7, 2:7].all()
    assert mask.sum() == 20
    assert frac == 0.2


def test_subject_mask_keeps_the_part_of_a_straddling_box_that_is_still_in_frame():
    """A subject walking off the left edge is ordinary; what ships is what is
    left inside. The mask must not fabricate pixels at the edge to replace it."""
    mask, frac = regions.subject_mask([(-0.5, 0.0, 0.2, 1.0)], 1, 10, 10)
    assert mask[0, :, :2].all()
    assert not mask[0, :, 2:].any()
    assert frac == 0.2


def test_subject_mask_of_a_box_wholly_outside_the_frame_is_empty_not_clamped():
    mask, frac = regions.subject_mask([(1.4, 1.4, 1.9, 1.9)], 1, 10, 10)
    assert not mask.any()
    assert frac == 0.0


def test_subject_mask_of_a_box_wholly_outside_on_the_negative_side_is_empty():
    """The proof above only overflows past the bottom-right edge, where x1/y1 are
    clamped by `min(w, ...)`/`min(h, ...)` to a value >= 0 and a Python slice
    START beyond the array length silently clips to empty either way — so it
    cannot tell the `if x1 > x0 and y1 > y0` guard apart from no guard at all
    (Task 7's mutation battery, row 3: deleting the guard left every test in this
    file, and the whole suite, green).

    A box wholly outside past the TOP-LEFT edge is different: x0/y0 are floored
    at 0 by `max(0, ...)`, but x1/y1 are only capped from above, so a box far
    enough to the left projects a NEGATIVE x1 — and a negative Python slice bound
    is not 'out of range', it counts backward from the end. Without the guard,
    `mask[i, 0:-2, 0:-2]` marks most of the frame instead of none of it."""
    mask, frac = regions.subject_mask([(-0.5, -0.5, -0.2, -0.2)], 1, 10, 10)
    assert not mask.any()
    assert frac == 0.0


def test_subject_mask_refuses_extents_that_are_not_parallel_to_the_frames():
    with pytest.raises(ValueError, match="2 frames but 1 extents"):
        regions.subject_mask([(0.0, 0.0, 1.0, 1.0)], 2, 4, 4)


def test_refuse_names_no_route_for_a_region_that_was_never_located():
    assert regions.refuse("subject", located=False, fraction=0.0, empty=True) == "no-route"


def test_refuse_names_too_small_for_a_located_region_under_the_floor():
    assert regions.refuse("subject", located=True, fraction=0.009, empty=False) == "too-small"
    assert regions.refuse("subject", located=True, fraction=0.011, empty=False) is None


def test_refuse_is_not_too_small_at_exactly_the_floor():
    """The gate is `fraction < MIN_REGION_FRAC`, a strict inequality — a region
    sitting EXACTLY on the floor clears it. The neighbouring test above pins
    0.009 (under) and 0.011 (over) but never the boundary itself, so Task 7's
    mutation battery (row 5: `<` -> `<=`) found every test in the suite green.
    MIN_REGION_FRAC is pinned to 0.01 elsewhere (test_the_area_gate_is_one_percent);
    this test uses the constant itself so it keeps meaning "the floor" even if
    that value is ever retuned."""
    assert regions.refuse("subject", located=True,
                          fraction=regions.MIN_REGION_FRAC, empty=False) is None


def test_refuse_names_too_small_for_a_located_region_that_holds_no_pixels():
    """Located and empty has a route and a real measured fraction of 0.0, so it
    is too-small and never no-route — an episode that HAS a route must not be
    told it has none."""
    assert regions.refuse("subject", located=True, fraction=0.0, empty=True) == "too-small"


def test_refuse_names_too_small_for_an_empty_region_whatever_fraction_is_claimed():
    """`fraction` and `empty` are NOT correlated in general — only inside
    measure() are they, because RegionReading.profile is None implies
    fraction == 0.0. A second reader (check_episode, over RGB frames) supplies
    its own pair, and for it a subject can cover 20% of the frame across a
    stack while one frame's mask slice is empty. A region that holds no pixels
    is refused whatever fraction is claimed for it — this pins `empty` as its
    own, independent branch, not a restatement of the area gate reachable only
    through fraction == 0.0."""
    assert regions.refuse("subject", located=True, fraction=0.5, empty=True) == "too-small"


def test_refuse_never_gates_the_crop_on_size():
    """Every fallback lands on the crop, so a crop under the floor would have
    nowhere to fall back to."""
    assert regions.refuse("crop", located=True, fraction=0.001, empty=False) is None


def test_refuse_rejects_a_kind_outside_the_vocabulary():
    with pytest.raises(ValueError, match="unknown kind"):
        regions.refuse("skin", located=True, fraction=0.5, empty=False)


def test_refuse_returns_only_names_from_the_closed_set():
    for located, empty in ((False, True), (True, True), (True, False)):
        got = regions.refuse("subject", located=located, fraction=0.0, empty=empty)
        assert got is None or got in regions.FALLBACKS
