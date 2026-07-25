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
        "edit-plan", "music-and-mood", "pacing", "assemble-draft", "titles",
        "deliver", "reel-review"]


def test_v1_stages_kinds_and_flags():
    by = {s.key: s for s in V1_STAGES}
    assert [s.key for s in V1_STAGES if s.kind == "deferred"] == ["trend-scan"]
    assert by["pacing"].kind == "optional"
    assert by["pacing"].artifact == "PACING.md"
    assert by["pacing"].checkpoint is None
    assert by["music-and-mood"].kind == "optional"
    assert by["reel-brief"].kind == "optional"
    assert by["reel-brief"].artifact == "SPEC.json"
    assert by["reel-brief"].checkpoint == "spec"
    assert by["assemble-draft"].kind == "optional"
    assert by["assemble-draft"].artifact == "draft.mp4"
    assert by["assemble-draft"].checkpoint == "edl"
    assert by["assemble-draft"].in_out is False
    assert by["titles"].kind == "optional"
    assert by["titles"].artifact == "TITLES.json"
    assert by["titles"].checkpoint == "final"
    assert by["titles"].in_out is False
    assert by["reel-review"].kind == "optional"
    assert by["reel-review"].artifact == "REVIEW.json"
    assert by["reel-review"].checkpoint == "final"
    assert by["reel-review"].in_out is False
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
    # whole-object: pin the per-stage dict shape (a dropped key must fail)
    assert res["stages"][0] == {
        "key": "project-init", "artifact": "project.json", "kind": "required",
        "state": "next", "checkpoint": "spec",
        "runner": "project-init SKILL -> project_init CLI"}


def test_deferred_stages_always_skip(tmp_path):
    res = next_action(str(tmp_path))
    assert _state(res, "trend-scan") == "skip"


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


def test_pacing_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    res = next_action(str(tmp_path))
    assert _state(res, "pacing") == "optional"   # absent optional never blocks
    assert res["next"] == "edit-plan"
    _touch(tmp_path, "PACING.md")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "pacing") == "done"
    assert res2["next"] == "edit-plan"


def test_reel_brief_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project.json")
    res = next_action(str(tmp_path))
    assert _state(res, "reel-brief") == "optional"   # absent optional never blocks
    assert res["next"] == "footage-intake"           # next unaffected by an optional stage
    _touch(tmp_path, "SPEC.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-brief") == "done"
    assert res2["next"] == "footage-intake"


def test_assemble_draft_optional_absent_then_present(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert _state(res, "assemble-draft") == "optional"   # absent optional never blocks
    assert res["next"] == "deliver"                       # next unaffected by an optional stage
    _touch(tmp_path, "draft.mp4")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "assemble-draft") == "done"
    assert res2["next"] == "deliver"


def test_titles_optional_absent_then_present(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert _state(res, "titles") == "optional"   # absent optional never blocks
    assert res["next"] == "deliver"
    _touch(tmp_path, "TITLES.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "titles") == "done"
    assert res2["next"] == "deliver"


def test_reel_review_optional_absent_then_present(tmp_path):
    # review runs AFTER deliver; it is optional and never blocks `next`
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    out = tmp_path / "out"
    out.mkdir()
    (out / "REEL_v1.mp4").write_text("x")
    res = next_action(str(tmp_path))
    assert res["delivered"] is True and res["next"] is None
    assert _state(res, "reel-review") == "optional"   # absent optional never blocks
    _touch(tmp_path, "REVIEW.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-review") == "done"
    assert res2["next"] is None                        # still nothing required outstanding


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


# ---- status CLI ----

def test_status_cli_prints_json_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["montage", "status", "--run-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        montage.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next"] == "project-init"
    assert payload["delivered"] is False


def test_status_cli_out_dir_override(tmp_path, monkeypatch, capsys):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    alt = tmp_path / "delivery"
    alt.mkdir()
    (alt / "REEL_v1.mp4").write_text("x")
    monkeypatch.setattr(sys, "argv",
                        ["montage", "status", "--run-dir", str(tmp_path),
                         "--out-dir", str(alt)])
    with pytest.raises(SystemExit) as e:
        montage.main()
    assert e.value.code == 0
    assert json.loads(capsys.readouterr().out)["delivered"] is True


# ---- scenario-first order: edit-plan before music/pacing ----

def test_edit_plan_comes_before_music_and_pacing():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("edit-plan") < keys.index("music-and-mood")
    assert keys.index("edit-plan") < keys.index("pacing")


def test_pacing_still_follows_the_music_it_fits_against():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("music-and-mood") < keys.index("pacing")


def test_a_run_with_footage_but_no_edl_asks_for_edit_plan_not_music(tmp_path):
    (tmp_path / "project.json").write_text("{}")
    (tmp_path / "FOOTAGE.json").write_text("{}")
    assert montage.next_action(str(tmp_path))["next"] == "edit-plan"
