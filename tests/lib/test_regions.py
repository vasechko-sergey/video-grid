import json

import pytest

from scripts.lib import regions


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
