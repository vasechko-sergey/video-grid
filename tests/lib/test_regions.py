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


def test_the_two_closed_sets_and_their_order():
    """ANCHORS' ORDER is load-bearing, not cosmetic: it is the order of a profile
    tuple, so assemble indexes (p5, p50, p95) by it."""
    assert regions.ANCHORS == ("toe", "mid", "shoulder")
    assert regions.KINDS == ("subject", "background", "crop")


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
    readings = {
        "subject": regions.RegionReading("subject", 0.0, None),
        "background": regions.RegionReading("background", 0.0, None),
        "crop": regions.RegionReading("crop", 1.0, (50.0, 110.0, 200.0))}
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = regions.assemble(decl, readings)
    assert profile == (50.0, 110.0, 200.0)
    assert rows[0].fallback == "no-route"


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
