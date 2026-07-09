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


def test_resolve_manifest_fills_absent():
    cfg = pj.resolve_project("square")             # (1,1), native
    ep = {"segment": "s.mp4", "out_path": "o.mp4", "composition": "lead",
          "grid": "thirds", "target_dur": 3.0}     # no canvas / delivery
    out = pj.resolve_manifest(ep, cfg)
    assert out["canvas"] == [1, 1] and out["delivery"] == "native"


def test_resolve_manifest_episode_overrides():
    cfg = pj.resolve_project("reel")               # (9,16), native
    ep = {"canvas": [16, 9], "delivery": "short_edge:1080"}
    out = pj.resolve_manifest(ep, cfg)
    assert out["canvas"] == [16, 9] and out["delivery"] == "short_edge:1080"


def test_resolve_manifest_null_inherits():
    cfg = pj.resolve_project("reel")
    out = pj.resolve_manifest({"canvas": None, "delivery": None}, cfg)
    assert out["canvas"] == [9, 16] and out["delivery"] == "native"


def test_resolve_manifest_does_not_mutate_input():
    cfg = pj.resolve_project("reel")
    ep = {"segment": "s.mp4"}
    out = pj.resolve_manifest(ep, cfg)
    assert "canvas" not in ep                       # input untouched
    assert out["canvas"] == [9, 16] and out is not ep


def test_project_init_cli_writes_json(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import project_init
    argv = ["project_init", "--purpose", "youtube", "--quality", "4k",
            "--project-dir", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    project_init.main()
    out = tmp_path / "project.json"
    assert out.exists()
    cfg = pj.ProjectConfig.from_json(out)
    assert cfg.canvas == (16, 9) and cfg.delivery == "long_edge:2160"
    assert capsys.readouterr().out.strip().endswith("project.json")


def test_project_init_cli_custom(tmp_path, monkeypatch):
    import sys
    from scripts import project_init
    monkeypatch.setattr(sys, "argv",
                        ["project_init", "--purpose", "custom", "--canvas", "4:5",
                         "--project-dir", str(tmp_path)])
    project_init.main()
    assert pj.ProjectConfig.from_json(tmp_path / "project.json").canvas == (4, 5)


def test_project_init_cli_bad_purpose_raises(tmp_path, monkeypatch):
    import sys
    from scripts import project_init
    monkeypatch.setattr(sys, "argv",
                        ["project_init", "--purpose", "bogus", "--project-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="purpose"):
        project_init.main()


def test_from_json_corrupt_fails_loud(tmp_path):
    fp = tmp_path / "project.json"
    fp.write_text("{not valid json")
    with pytest.raises(ValueError, match="corrupt"):
        pj.ProjectConfig.from_json(fp)
