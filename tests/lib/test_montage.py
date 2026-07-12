import json
import sys

import pytest

from scripts import montage
from scripts.montage import Stage, V1_STAGES, next_action


def _touch(d, name):
    (d / name).write_text("{}")


# ---- Stage config-spec ----

def test_stage_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        Stage("x", "x.json", "bogus", "runs it", None)


def test_stage_rejects_bad_checkpoint():
    with pytest.raises(ValueError, match="checkpoint"):
        Stage("x", "x.json", "required", "runs it", "bogus")


def test_stage_accepts_good():
    s = Stage("x", "x.json", "required", "runs it", "spec")
    assert s.kind == "required" and s.checkpoint == "spec" and s.in_out is False


# ---- V1_STAGES table ----

def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "reel-brief", "trend-scan",
        "music-and-mood", "pacing", "edit-plan", "deliver"]


def test_v1_stages_kinds_and_flags():
    by = {s.key: s for s in V1_STAGES}
    assert [s.key for s in V1_STAGES if s.kind == "deferred"] == [
        "reel-brief", "trend-scan", "pacing"]
    assert by["music-and-mood"].kind == "optional"
    assert by["deliver"].in_out is True and by["deliver"].artifact == "REEL_v*.*"
    assert by["project-init"].checkpoint == "spec"
    assert by["edit-plan"].checkpoint == "edl"
    assert by["deliver"].checkpoint == "final"


# ---- next_action inspector ----

def _state(res, key):
    return next(s["state"] for s in res["stages"] if s["key"] == key)


def test_empty_run_next_is_project_init(tmp_path):
    res = next_action(str(tmp_path))
    assert res["next"] == "project-init"
    assert res["delivered"] is False
    assert _state(res, "project-init") == "next"
    assert _state(res, "footage-intake") == "pending"


def test_deferred_stages_always_skip(tmp_path):
    res = next_action(str(tmp_path))
    for k in ("reel-brief", "trend-scan", "pacing"):
        assert _state(res, k) == "skip"


def test_project_only_next_is_footage(tmp_path):
    _touch(tmp_path, "project.json")
    res = next_action(str(tmp_path))
    assert res["next"] == "footage-intake"
    assert _state(res, "project-init") == "done"


def test_music_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    res = next_action(str(tmp_path))
    assert res["next"] == "edit-plan"
    assert _state(res, "music-and-mood") == "optional"   # absent optional never blocks
    _touch(tmp_path, "MUSIC.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "music-and-mood") == "done"
    assert res2["next"] == "edit-plan"


def test_edl_present_next_is_deliver(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert res["next"] == "deliver"
    assert res["delivered"] is False


def test_delivered_when_reel_in_out(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    out = tmp_path / "out"
    out.mkdir()
    (out / "REEL_v1.mp4").write_text("x")
    res = next_action(str(tmp_path))
    assert res["next"] is None
    assert res["delivered"] is True
    assert _state(res, "deliver") == "done"


def test_broken_resume_surfaces_honestly(tmp_path):
    # EDL present but FOOTAGE missing -> footage-intake is next, edit-plan still 'done'
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "EDL.json")
    res = next_action(str(tmp_path))
    assert res["next"] == "footage-intake"
    assert _state(res, "edit-plan") == "done"
    assert _state(res, "deliver") == "pending"


def test_out_dir_override(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    alt = tmp_path / "delivery"
    alt.mkdir()
    (alt / "REEL_v2.mkv").write_text("x")   # glob matches any container/version
    res = next_action(str(tmp_path), str(alt))
    assert res["delivered"] is True
