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
        "project-init", "footage-intake", "contact-sheet", "reel-brief", "trend-scan",
        "edit-plan", "music-and-mood", "pacing", "match-grade", "assemble-draft", "titles",
        "episodes", "episode-qc", "deliver", "reel-review"]


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
    assert by["reel-review"].kind == "required"
    assert by["reel-review"].artifact == "REVIEW.json"
    assert by["reel-review"].checkpoint == "final"
    assert by["reel-review"].in_out is False
    assert by["deliver"].in_out is True and by["deliver"].artifact == "REEL_v*.*"
    assert by["project-init"].checkpoint == "spec"
    assert by["edit-plan"].checkpoint == "edl"
    assert by["deliver"].checkpoint == "final"
    assert by["match-grade"].kind == "optional"
    assert by["match-grade"].artifact == "MATCH.md"
    assert by["match-grade"].checkpoint is None
    assert by["match-grade"].in_out is False
    assert by["contact-sheet"].kind == "required"
    assert by["contact-sheet"].artifact == "SHEETS.md"
    assert by["contact-sheet"].checkpoint is None
    assert by["contact-sheet"].in_out is False


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
    _touch(tmp_path, "SHEETS.md")     # contact-sheet is required and comes first
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
    _touch(tmp_path, "SHEETS.md")     # contact-sheet is required and comes first
    res = next_action(str(tmp_path))
    assert _state(res, "pacing") == "optional"   # absent optional never blocks
    assert res["next"] == "edit-plan"
    _touch(tmp_path, "PACING.md")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "pacing") == "done"
    assert res2["next"] == "edit-plan"


def test_match_grade_optional_absent_then_present(tmp_path):
    (tmp_path / "EDL.json").write_text("{}")
    res = next_action(str(tmp_path))
    assert _state(res, "match-grade") == "optional"      # absent optional never blocks
    (tmp_path / "MATCH.md").write_text("x")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "match-grade") == "done"


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
    for n in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert _state(res, "assemble-draft") == "optional"   # absent optional never blocks
    assert res["next"] == "episodes"                      # next unaffected by an optional stage
    _touch(tmp_path, "draft.mp4")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "assemble-draft") == "done"
    assert res2["next"] == "episodes"


def test_titles_optional_absent_then_present(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert _state(res, "titles") == "optional"   # absent optional never blocks
    assert res["next"] == "episodes"
    _touch(tmp_path, "TITLES.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "titles") == "done"
    assert res2["next"] == "episodes"


def test_reel_review_required_absent_then_present(tmp_path):
    # review runs AFTER deliver; it is required (design §8) and blocks `next` until reviewed
    for n in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        _touch(tmp_path, n)
    out = tmp_path / "out"
    out.mkdir()
    _touch(out, "EPISODES.json")      # episode-qc's two upstream required stages
    _touch(out, "EPISODE_QC.json")
    (out / "REEL_v1.mp4").write_text("x")
    res = next_action(str(tmp_path))
    assert res["delivered"] is True and res["next"] == "reel-review"
    assert _state(res, "reel-review") == "next"   # absent required blocks `next`
    _touch(tmp_path, "REVIEW.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-review") == "done"
    assert res2["next"] is None                    # nothing required outstanding now


def test_edl_present_next_is_episodes(tmp_path):
    # the EDL alone no longer reaches deliver directly (design 2026-08-08 §9): the
    # episode render + QC gate are required stages sitting between edit-plan and deliver
    for n in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert res["next"] == "episodes"
    assert res["delivered"] is False


def test_delivered_when_reel_in_out(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        _touch(tmp_path, n)
    out = tmp_path / "out"
    out.mkdir()
    _touch(out, "EPISODES.json")      # episode-qc's two upstream required stages
    _touch(out, "EPISODE_QC.json")
    (out / "REEL_v1.mp4").write_text("x")
    res = next_action(str(tmp_path))
    assert res["next"] == "reel-review"   # deliver is done; reel-review is required and next
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
    (tmp_path / "SHEETS.md").write_text("{}")
    assert montage.next_action(str(tmp_path))["next"] == "edit-plan"


# ---- reel-review required (#15) + delivery attestation reporting (design §6) ----

def test_reel_review_is_next_after_delivery(tmp_path):
    # #15: CP3 must not be free. Every required artifact present except REVIEW.json.
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    for name in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        (run / name).write_text("{}")
    for name in ("EPISODES.json", "EPISODE_QC.json"):
        (out / name).write_text("{}")
    (out / "REEL_v1.mp4").write_text("x")
    got = montage.next_action(str(run))
    assert got["delivered"] is True
    assert got["next"] == "reel-review"


def test_a_run_is_only_finished_when_the_review_exists(tmp_path):
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    for name in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json", "REVIEW.json"):
        (run / name).write_text("{}")
    for name in ("EPISODES.json", "EPISODE_QC.json"):
        (out / name).write_text("{}")
    (out / "REEL_v1.mp4").write_text("x")
    assert montage.next_action(str(run))["next"] is None


def test_status_reports_an_unattested_delivery(tmp_path):
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    (out / "REEL_v1.mp4").write_bytes(b"hand-concatenated")
    got = montage.next_action(str(run))["deliveries"]
    assert got == [{"file": "REEL_v1.mp4", "state": "unattested", "overall": None,
                    "overrides": [], "engine_drift": False, "episode_qc": "unknown",
                    "detail": "no attestation sidecar — this file was not produced by deliver()"}]


def test_status_does_not_list_the_sidecar_as_a_delivery(tmp_path):
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    (out / "REEL_v1.mp4").write_bytes(b"x")
    (out / "REEL_v1.attest.json").write_text("{}")
    assert [d["file"] for d in montage.next_action(str(run))["deliveries"]] == ["REEL_v1.mp4"]


def test_verify_rehashes_and_catches_a_swapped_reel(tmp_path):
    from scripts.lib import provenance
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    reel = out / "REEL_v1.mp4"
    reel.write_bytes(b"delivered")
    provenance.Attestation(reel="REEL_v1.mp4", reel_digest=provenance.digest_file(reel),
                           master_digest="m" * 64, report_digest="r" * 64,
                           overall=True).write(provenance.attest_path(reel))
    assert montage.verify(str(run))["deliveries"][0]["state"] == "attested"
    reel.write_bytes(b"swapped after delivery")
    assert montage.verify(str(run))["deliveries"][0]["state"] == "digest-mismatch"


def test_status_does_not_rehash_but_verify_does(tmp_path):
    # The whole point of the two-command split: status is cheap (sidecar-only, safe
    # to call on every router tick), verify is the one that proves the shipped bytes
    # still match. Same swapped-reel setup as test_verify_rehashes_and_catches_a_
    # swapped_reel above, but this time asserting BOTH sides in one test — status
    # must stay "attested" (stale, but that is the cheap-read contract) while verify
    # alone catches the swap as "digest-mismatch".
    from scripts.lib import provenance
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    reel = out / "REEL_v1.mp4"
    reel.write_bytes(b"delivered")
    provenance.Attestation(reel="REEL_v1.mp4", reel_digest=provenance.digest_file(reel),
                           master_digest="m" * 64, report_digest="r" * 64,
                           overall=True).write(provenance.attest_path(reel))
    reel.write_bytes(b"swapped after delivery")
    assert montage.next_action(str(run))["deliveries"][0]["state"] == "attested"
    assert montage.verify(str(run))["deliveries"][0]["state"] == "digest-mismatch"


# ---- contact-sheet required before edit-plan (design 2026-08-05 §6) ----

def test_footage_without_sheets_asks_for_the_contact_sheet(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    assert next_action(str(tmp_path))["next"] == "contact-sheet"


def test_the_sheet_unblocks_edit_plan(tmp_path):
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "FOOTAGE.json")
    _touch(tmp_path, "SHEETS.md")
    res = next_action(str(tmp_path))
    assert res["next"] == "edit-plan"
    assert _state(res, "contact-sheet") == "done"


def test_the_sheet_comes_after_the_footage_it_sheets_and_before_the_cut():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("footage-intake") < keys.index("contact-sheet")
    assert keys.index("contact-sheet") < keys.index("edit-plan")


def test_no_footage_still_asks_for_intake_first(tmp_path):
    # the sheet is not reachable before the FOOTAGE it reads
    _touch(tmp_path, "project.json")
    _touch(tmp_path, "SHEETS.md")
    assert next_action(str(tmp_path))["next"] == "footage-intake"


# ---- episode-qc stage split (design 2026-08-08-episode-qc-design.md §9) ----

def test_the_qc_stage_sits_between_the_episodes_and_the_reel():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("episodes") < keys.index("episode-qc") < keys.index("deliver")
    assert all(s.kind == "required" for s in montage.V1_STAGES
               if s.key in ("episodes", "episode-qc"))


def test_next_points_at_the_qc_stage_once_the_episodes_exist(tmp_path):
    """A run with rendered episodes and no verdicts is NOT ready to deliver."""
    for n in ("project.json", "FOOTAGE.json", "SHEETS.md", "EDL.json"):
        _touch(tmp_path, n)               # touch the artifacts the earlier stages need
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "EPISODES.json").write_text("{}")
    assert next_action(str(tmp_path))["next"] == "episode-qc"
