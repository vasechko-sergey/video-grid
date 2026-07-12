import pytest

from scripts.lib.project import resolve_project
from scripts.lib.spec import Spec
from scripts.reel_brief import build_spec, write_reel_brief


def _project(tmp_path):
    cfg = resolve_project("reel", quality="native")
    cfg.write(tmp_path / "project.json")
    return str(tmp_path / "project.json")


def test_build_spec_reads_canvas_from_project(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="slow push")
    assert spec.canvas == (9, 16)          # reel purpose → 9:16, inherited not re-asked
    assert isinstance(spec, Spec)


def test_build_spec_missing_project_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_spec(str(tmp_path / "nope.json"), length_s=30, mood="x", hook="y")


def test_build_spec_forwards_cast_and_editorial(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=20, mood="calm", hook="h",
                      cast=["Anna", "Ben"], music_mode="local", style_lean="trend")
    assert spec.cast == ("Anna", "Ben") and spec.music_mode == "local"
    assert spec.style_lean == "trend"


def test_write_reel_brief_emits_both_files(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="slow push")
    res = write_reel_brief(spec, str(tmp_path))
    assert res["status"] == "written"
    assert (tmp_path / "SPEC.json").exists() and (tmp_path / "SPEC.md").exists()
    assert Spec.from_json(tmp_path / "SPEC.json").to_dict() == spec.to_dict()
    assert (tmp_path / "SPEC.md").read_text().startswith("# Reel brief —")
