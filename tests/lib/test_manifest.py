import pytest
from scripts.lib import manifest as mf


def _ok_dict(**over):
    d = dict(segment="seg.mp4", out_path="out.mp4", composition="lead",
             grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_from_dict_defaults():
    m = mf.Manifest.from_dict(_ok_dict())
    assert m.layout == "fill"
    assert m.stabilize is False
    assert m.color_means == (105, 122, 137)
    assert m.canvas == (9, 16)           # list coerced to tuple
    assert m.model == "yolo11n-seg.pt"


def test_from_dict_missing_required_raises():
    d = _ok_dict(); del d["composition"]
    with pytest.raises(KeyError, match="composition"):
        mf.Manifest.from_dict(d)


def test_validate_ok():
    assert mf.validate(mf.Manifest.from_dict(_ok_dict())) == []


def test_validate_unknown_composition():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(composition="Lead")))
    assert any("composition" in p for p in problems)


def test_validate_unknown_grid():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(grid="golden-canon")))
    assert any("grid" in p for p in problems)


def test_validate_layout_not_fill_refused():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(layout="fit-blur")))
    assert any("layout" in p and "fill" in p for p in problems)


def test_validate_stabilize_refused():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(stabilize=True)))
    assert any("stabilize" in p for p in problems)


def test_validate_nonpositive_duration():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(target_dur=0)))
    assert any("target_dur" in p for p in problems)


def test_validate_bad_canvas():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(canvas=[9, 16, 1])))
    assert any("canvas" in p for p in problems)


def test_validate_bad_motion_string():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(motion="sideways")))
    assert any("motion" in p for p in problems)


def test_validate_accepts_known_motion():
    for good in ("lateral:right", "lateral:left", "head-on", "static"):
        assert mf.validate(mf.Manifest.from_dict(_ok_dict(motion=good))) == []
