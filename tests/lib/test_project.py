import json
import pytest
from scripts.lib import project as pj


def test_resolve_project_purposes():
    assert pj.resolve_project("reel").canvas == (9, 16)
    assert pj.resolve_project("tiktok").canvas == (9, 16)
    assert pj.resolve_project("youtube").canvas == (16, 9)
    assert pj.resolve_project("square").canvas == (1, 1)
    assert pj.resolve_project("cinema").canvas == (21, 9)


def test_resolve_project_quality_default_native():
    assert pj.resolve_project("reel").delivery == "native"           # default = no downscale
    assert pj.resolve_project("reel", quality="social").delivery == "short_edge:1080"
    assert pj.resolve_project("youtube", quality="4k").delivery == "long_edge:2160"


def test_resolve_project_custom_needs_canvas():
    with pytest.raises(ValueError, match="custom"):
        pj.resolve_project("custom")
    c = pj.resolve_project("custom", canvas=(4, 5))
    assert c.canvas == (4, 5) and c.delivery == "native"


def test_resolve_project_explicit_delivery_overrides_quality():
    c = pj.resolve_project("reel", quality="social", delivery="exact:1080x1920")
    assert c.delivery == "exact:1080x1920"


def test_resolve_project_unknown_raises():
    with pytest.raises(ValueError, match="purpose"):
        pj.resolve_project("bogus")
    with pytest.raises(ValueError, match="quality"):
        pj.resolve_project("reel", quality="ultra")


def test_projectconfig_validation():
    pj.ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native")
    with pytest.raises(ValueError, match="purpose"):
        pj.ProjectConfig(purpose="nope", canvas=(9, 16), delivery="native")
    with pytest.raises(ValueError, match="canvas"):
        pj.ProjectConfig(purpose="reel", canvas=(9, 0), delivery="native")
    with pytest.raises(ValueError, match="delivery"):
        pj.ProjectConfig(purpose="reel", canvas=(9, 16), delivery="huge:9x")


def test_projectconfig_json_roundtrip(tmp_path):
    c = pj.resolve_project("youtube", quality="4k", notes="tv cut")
    fp = tmp_path / "project.json"
    c.write(fp)
    on_disk = json.loads(fp.read_text())
    assert on_disk == {"purpose": "youtube", "canvas": [16, 9],
                       "delivery": "long_edge:2160", "notes": "tv cut"}
    back = pj.ProjectConfig.from_json(fp)
    assert back.canvas == (16, 9) and back.delivery == "long_edge:2160"
