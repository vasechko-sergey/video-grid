import json
import sys
from pathlib import Path

import pytest

from scripts import montage
from scripts.lib import constraints, matchgrade, provenance, runlayout
from scripts.montage import Stage, V1_STAGES, next_action


def _touch(run, stage_key, name=None):
    """Create the artifact that marks `stage_key` done, in its own bucket.

    match-grade and reel-review each gained a real freshness reader this task (design
    2026-09-09 §6) that a bare "{}" cannot satisfy — it is not fresh, so `_exists`-only
    "done" is no longer true for these two. Both get minimal but self-consistent content
    instead: match-grade an empty decisions list against an equally-empty EDL (0 == 0
    episodes, so tone_drift reports nothing); reel-review a REVIEW.json naming whatever
    delivery already exists. Touch reel-review AFTER deliver, or it binds to nothing on
    disk yet and reads stale — same as no review at all.
    """
    st = next(s for s in montage.V1_STAGES if s.key == stage_key)
    lay = runlayout.RunLayout(run)
    d = lay.bucket(st.bucket)
    d.mkdir(parents=True, exist_ok=True)
    if stage_key == "match-grade":
        edl = lay.reel_dir / "EDL.json"
        edl.parent.mkdir(parents=True, exist_ok=True)
        edl.write_text(json.dumps({"episodes": []}))
        matchgrade.MatchReport(target=(0.0, 128.0, 255.0), eps=matchgrade.MATCH_EPS,
                               decisions=(), edl=str(edl)).write(d / "MATCH.json")
        return
    if stage_key == "reel-review":
        newest = montage._newest_delivery(lay.deliveries)
        reel = str(lay.deliveries / newest) if newest else ""
        (d / "REVIEW.json").write_text(json.dumps({"reel": reel, "findings": []}))
        return
    (d / (name or st.artifact.replace("*", "1"))).write_text("{}")


# ---- Stage config-spec ----

def test_stage_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        Stage("x", "x.json", "bogus", "runs it", None)


def test_stage_rejects_bad_checkpoint():
    with pytest.raises(ValueError, match="checkpoint"):
        Stage("x", "x.json", "required", "runs it", "bogus")


def test_stage_accepts_good():
    s = Stage("x", "x.json", "required", "runs it", "spec")
    assert s.kind == "required" and s.checkpoint == "spec" and s.bucket == "reel"


def test_an_unknown_bucket_is_refused():
    with pytest.raises(ValueError) as e:
        montage.Stage("x", "X.json", "required", "runner", None, "scratch")
    assert "scratch" in str(e.value)


# ---- V1_STAGES table ----

def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "contact-sheet", "reel-brief", "edit-plan", "music-and-mood", "pacing", "episodes-geometry", "match-grade",
        "assemble-draft", "titles", "episodes", "episode-qc", "deliver", "reel-review"]


def test_v1_stages_kinds_and_flags():
    by = {s.key: s for s in V1_STAGES}
    # Every stage is built: trend-scan, the one deferred stage, was removed on
    # 2026-10-20 (backlog U1) and the `deferred` kind went with it.
    assert {s.kind for s in V1_STAGES} == {"required", "optional"}
    assert montage._KINDS == ("required", "optional")
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
    assert by["assemble-draft"].bucket == "reel"
    assert by["titles"].kind == "optional"
    assert by["titles"].artifact == "TITLES.json"
    assert by["titles"].checkpoint == "final"
    assert by["titles"].bucket == "reel"
    assert by["reel-review"].kind == "required"
    assert by["reel-review"].artifact == "REVIEW.json"
    assert by["reel-review"].checkpoint == "final"
    assert by["reel-review"].bucket == "reel"
    assert by["deliver"].bucket == "deliveries" and by["deliver"].artifact == "REEL_v*.*"
    assert by["project-init"].checkpoint == "spec"
    assert by["edit-plan"].checkpoint == "edl"
    assert by["deliver"].checkpoint == "final"
    assert by["match-grade"].kind == "required"
    assert by["match-grade"].artifact == "MATCH.json"
    assert by["match-grade"].checkpoint is None
    assert by["match-grade"].bucket == "reel"
    assert by["episodes-geometry"].kind == "required"
    assert by["episodes-geometry"].artifact == "GEOMETRY.json"
    assert by["episodes-geometry"].checkpoint is None
    assert by["episodes-geometry"].bucket == "episodes"
    assert by["contact-sheet"].kind == "required"
    assert by["contact-sheet"].artifact == "SHEETS.md"
    assert by["contact-sheet"].checkpoint is None
    assert by["contact-sheet"].bucket == "footage"


def test_every_stage_declares_a_known_bucket():
    assert all(s.bucket in runlayout.BUCKETS for s in montage.V1_STAGES)


def test_no_stage_lives_in_build():
    """build/ is wiped at every render — a stage marker there would make a
    finished stage un-finish itself (design §1)."""
    assert all(s.bucket != "build" for s in montage.V1_STAGES)


def test_every_stage_lands_in_the_bucket_the_design_assigns_it():
    """Written as a literal table, never derived from Stage.bucket.

    The _touch helper takes the write location FROM the field under test, so a
    suite built only from _touch calls proves self-consistency, not correctness:
    a wrong bucket makes the test write to the wrong place and look there too.
    Measured on this file — moving episode-qc to "deliveries" left all 50 tests
    green, where the pre-layout suite caught the same mistake with 4 failures.
    """
    assert {s.key: s.bucket for s in V1_STAGES} == {
        "project-init": "run",
        "footage-intake": "footage",
        "contact-sheet": "footage",
        "reel-brief": "reel",
        "edit-plan": "reel",
        "music-and-mood": "reel",
        "pacing": "reel",
        "episodes-geometry": "episodes",
        "match-grade": "reel",
        "assemble-draft": "reel",
        "titles": "reel",
        "episodes": "episodes",
        "episode-qc": "episodes",
        "deliver": "deliveries",
        "reel-review": "reel",
    }


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
        "key": "project-init", "artifact": "project.json", "bucket": "run",
        "path": str(tmp_path / "project.json"), "kind": "required",
        "state": "next", "stale_reason": "", "checkpoint": "spec",
        "runner": "project-init SKILL -> project_init CLI"}


def test_project_only_next_is_footage(tmp_path):
    _touch(tmp_path, "project-init")
    res = next_action(str(tmp_path))
    assert res["next"] == "footage-intake"
    assert _state(res, "project-init") == "done"


def test_music_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")     # contact-sheet is required and comes first
    res = next_action(str(tmp_path))
    assert res["next"] == "edit-plan"
    assert _state(res, "music-and-mood") == "optional"   # absent optional never blocks
    _touch(tmp_path, "music-and-mood")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "music-and-mood") == "done"
    assert res2["next"] == "edit-plan"


def test_pacing_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")     # contact-sheet is required and comes first
    res = next_action(str(tmp_path))
    assert _state(res, "pacing") == "optional"   # absent optional never blocks
    assert res["next"] == "edit-plan"
    _touch(tmp_path, "pacing")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "pacing") == "done"
    assert res2["next"] == "edit-plan"


# ---- episodes-geometry / match-grade: both required (design 2026-08-30 §6) ----
# episodes-geometry freezes the route match-grade measures; match-grade flipped
# optional -> required so the router no longer walks silently past the only
# stage that converges colour (design §6, closing the retro's R4.2).

def test_episodes_geometry_required_absent_then_present(tmp_path):
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan"):
        _touch(tmp_path, key)
    res = next_action(str(tmp_path))
    assert res["next"] == "episodes-geometry"
    assert _state(res, "episodes-geometry") == "next"      # absent required blocks `next`
    assert _state(res, "match-grade") == "pending"          # required too, blocked behind it
    _touch(tmp_path, "episodes-geometry")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "episodes-geometry") == "done"
    assert res2["next"] == "match-grade"


def test_match_grade_required_absent_then_present(tmp_path):
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry"):
        _touch(tmp_path, key)
    res = next_action(str(tmp_path))
    assert res["next"] == "match-grade"
    assert _state(res, "match-grade") == "next"             # absent required blocks `next`
    _touch(tmp_path, "match-grade")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "match-grade") == "done"
    assert res2["next"] == "episodes"


def test_episodes_geometry_sits_between_pacing_and_match_grade():
    """Order, not just presence (design 2026-08-30 §6): match-grade cannot measure
    a crop that has no frozen route yet, and episodes cannot render one that
    hasn't been geometry-checked and (now, unconditionally) grade-conducted."""
    keys = [s.key for s in montage.V1_STAGES]
    assert (keys.index("pacing") < keys.index("episodes-geometry")
           < keys.index("match-grade") < keys.index("episodes"))


def test_reel_brief_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project-init")
    res = next_action(str(tmp_path))
    assert _state(res, "reel-brief") == "optional"   # absent optional never blocks
    assert res["next"] == "footage-intake"           # next unaffected by an optional stage
    _touch(tmp_path, "reel-brief")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-brief") == "done"
    assert res2["next"] == "footage-intake"


def test_assemble_draft_optional_absent_then_present(tmp_path):
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan"):
        _touch(tmp_path, key)
    res = next_action(str(tmp_path))
    assert _state(res, "assemble-draft") == "optional"   # absent optional never blocks
    assert res["next"] == "episodes-geometry"             # next unaffected by an optional stage
    _touch(tmp_path, "assemble-draft")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "assemble-draft") == "done"
    assert res2["next"] == "episodes-geometry"


def test_titles_optional_absent_then_present(tmp_path):
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan"):
        _touch(tmp_path, key)
    res = next_action(str(tmp_path))
    assert _state(res, "titles") == "optional"   # absent optional never blocks
    assert res["next"] == "episodes-geometry"
    _touch(tmp_path, "titles")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "titles") == "done"
    assert res2["next"] == "episodes-geometry"


def test_reel_review_required_absent_then_present(tmp_path):
    # review runs AFTER deliver; it is required (design §8) and blocks `next` until reviewed
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry", "match-grade"):
        _touch(tmp_path, key)
    _touch(tmp_path, "episodes")      # episode-qc's two upstream required stages
    _touch(tmp_path, "episode-qc")
    _touch(tmp_path, "deliver", name="REEL_v1.mp4")
    res = next_action(str(tmp_path))
    assert res["delivered"] is True and res["next"] == "reel-review"
    assert _state(res, "reel-review") == "next"   # absent required blocks `next`
    _touch(tmp_path, "reel-review")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-review") == "done"
    assert res2["next"] is None                    # nothing required outstanding now


def test_edl_present_next_is_episodes_geometry(tmp_path):
    # the EDL alone no longer reaches deliver directly (design 2026-08-08 §9): the
    # episode render + QC gate are required stages sitting between edit-plan and deliver
    # — and since design 2026-08-30 §6, episodes-geometry + match-grade sit between
    # edit-plan and the render too, both required.
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan"):
        _touch(tmp_path, key)
    res = next_action(str(tmp_path))
    assert res["next"] == "episodes-geometry"
    assert res["delivered"] is False


def test_delivered_when_deliver_artifact_exists(tmp_path):
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry", "match-grade"):
        _touch(tmp_path, key)
    _touch(tmp_path, "episodes")      # episode-qc's two upstream required stages
    _touch(tmp_path, "episode-qc")
    _touch(tmp_path, "deliver", name="REEL_v1.mp4")
    res = next_action(str(tmp_path))
    assert res["next"] == "reel-review"   # deliver is done; reel-review is required and next
    assert res["delivered"] is True
    assert _state(res, "deliver") == "done"


def test_delivered_with_a_non_mp4_container(tmp_path):
    """The deliver stage marks done on any REEL_v*.* file, not just .mp4."""
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan"):
        _touch(tmp_path, key)
    _touch(tmp_path, "episodes")
    _touch(tmp_path, "episode-qc")
    _touch(tmp_path, "deliver", name="REEL_v2.mkv")
    res = next_action(str(tmp_path))
    assert res["delivered"] is True
    assert _state(res, "deliver") == "done"


def test_broken_resume_surfaces_honestly(tmp_path):
    # EDL present but FOOTAGE missing -> footage-intake is next, edit-plan still 'done'
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "edit-plan")
    res = next_action(str(tmp_path))
    assert res["next"] == "footage-intake"
    assert _state(res, "edit-plan") == "done"
    assert _state(res, "deliver") == "pending"


# ---- layout resolution (design 2026-08-26-run-layout-lifetimes-design.md §5) ----

def test_each_stage_reports_its_resolved_path(tmp_path):
    """The path comes back in the same answer as `next` — the moment the agent is
    asking where to write (design §5)."""
    got = {s["key"]: s["path"] for s in montage.next_action(str(tmp_path))["stages"]}
    assert got["footage-intake"] == str(tmp_path / "footage" / "FOOTAGE.json")
    assert got["edit-plan"] == str(tmp_path / "reels" / "main" / "EDL.json")
    assert got["episodes"] == str(tmp_path / "reels" / "main" / "episodes"
                                  / "EPISODES.json")
    assert got["episode-qc"] == str(tmp_path / "reels" / "main" / "episodes"
                                    / "EPISODE_QC.json")
    assert got["deliver"] == str(tmp_path / "reels" / "main" / "deliveries"
                                 / "REEL_v*.*")
    assert got["project-init"] == str(tmp_path / "project.json")


def test_an_artifact_outside_the_layout_does_not_count(tmp_path):
    """The enforcement, stated as a test: EDL.json at the run root is invisible, so
    the router re-runs edit-plan into the canonical path (design §5)."""
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    (tmp_path / "EDL.json").write_text("{}")          # the 0.2.x place
    assert montage.next_action(str(tmp_path))["next"] == "edit-plan"


def test_the_result_carries_the_whole_layout(tmp_path):
    got = montage.next_action(str(tmp_path))
    assert got["layout"] == runlayout.RunLayout(tmp_path).to_dict()
    assert got["reel"] == "main"


def test_the_result_lists_the_reels_that_exist(tmp_path):
    (tmp_path / "reels" / "main").mkdir(parents=True)
    (tmp_path / "reels" / "upbeat").mkdir()
    assert montage.next_action(str(tmp_path))["reels"] == ["main", "upbeat"]


def test_a_variant_has_its_own_progress(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    lay = runlayout.RunLayout(tmp_path, "main")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.reel_dir / "EDL.json").write_text("{}")
    assert montage.next_action(str(tmp_path), "main")["next"] != "edit-plan"
    assert montage.next_action(str(tmp_path), "upbeat")["next"] == "edit-plan"


def test_a_legacy_run_is_flagged(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text("{}")
    got = montage.next_action(str(tmp_path))
    assert got["legacy_layout"] is True


def test_a_current_run_is_not_flagged(tmp_path):
    assert montage.next_action(str(tmp_path))["legacy_layout"] is False


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


def test_status_cli_reel_override(tmp_path, monkeypatch, capsys):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    _touch(tmp_path, "edit-plan")            # lands in reels/main, not reels/upbeat
    monkeypatch.setattr(sys, "argv",
                        ["montage", "status", "--run-dir", str(tmp_path),
                         "--reel", "upbeat"])
    with pytest.raises(SystemExit) as e:
        montage.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reel"] == "upbeat"
    assert payload["next"] == "edit-plan"    # "upbeat" hasn't been cut yet, unlike "main"


# ---- scenario-first order: edit-plan before music/pacing ----

def test_edit_plan_comes_before_music_and_pacing():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("edit-plan") < keys.index("music-and-mood")
    assert keys.index("edit-plan") < keys.index("pacing")


def test_pacing_still_follows_the_music_it_fits_against():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("music-and-mood") < keys.index("pacing")


def test_a_run_with_footage_but_no_edl_asks_for_edit_plan_not_music(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    assert montage.next_action(str(tmp_path))["next"] == "edit-plan"


# ---- reel-review required (#15) + delivery attestation reporting (design §6) ----

def test_reel_review_is_next_after_delivery(tmp_path):
    # #15: CP3 must not be free. Every required artifact present except REVIEW.json.
    run = tmp_path / "run"
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry", "match-grade"):
        _touch(run, key)
    _touch(run, "episodes")
    _touch(run, "episode-qc")
    _touch(run, "deliver", name="REEL_v1.mp4")
    got = montage.next_action(str(run))
    assert got["delivered"] is True
    assert got["next"] == "reel-review"


def test_a_run_is_only_finished_when_the_review_exists(tmp_path):
    run = tmp_path / "run"
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry", "match-grade"):
        _touch(run, key)
    _touch(run, "episodes")
    _touch(run, "episode-qc")
    _touch(run, "deliver", name="REEL_v1.mp4")
    _touch(run, "reel-review")    # AFTER deliver: _touch binds REVIEW.json to whatever
                                   # delivery already exists on disk (see _touch's docstring)
    assert montage.next_action(str(run))["next"] is None


def test_status_reports_an_unattested_delivery(tmp_path):
    run = tmp_path / "run"
    lay = runlayout.RunLayout(run)
    lay.deliveries.mkdir(parents=True)
    (lay.deliveries / "REEL_v1.mp4").write_bytes(b"hand-concatenated")
    got = montage.next_action(str(run))["deliveries"]
    assert got == [{"file": "REEL_v1.mp4", "state": "unattested", "overall": None,
                    "overrides": [], "gates": [], "engine_drift": False, "episode_qc": "unknown",
                    "detail": ("no attestation sidecar — the look gate withheld it, the "
                               "delivery was interrupted after the encode, or this file "
                               "was not produced by deliver at all. The file itself is "
                               "complete: deliver renames the encode into place before any "
                               "of the three (design 2026-09-09 §5)")}]


def test_status_does_not_list_the_sidecar_as_a_delivery(tmp_path):
    run = tmp_path / "run"
    lay = runlayout.RunLayout(run)
    lay.deliveries.mkdir(parents=True)
    (lay.deliveries / "REEL_v1.mp4").write_bytes(b"x")
    (lay.deliveries / "REEL_v1.attest.json").write_text("{}")
    assert [d["file"] for d in montage.next_action(str(run))["deliveries"]] == ["REEL_v1.mp4"]


def test_verify_rehashes_and_catches_a_swapped_reel(tmp_path):
    run = tmp_path / "run"
    lay = runlayout.RunLayout(run)
    lay.deliveries.mkdir(parents=True)
    reel = lay.deliveries / "REEL_v1.mp4"
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
    run = tmp_path / "run"
    lay = runlayout.RunLayout(run)
    lay.deliveries.mkdir(parents=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_bytes(b"delivered")
    provenance.Attestation(reel="REEL_v1.mp4", reel_digest=provenance.digest_file(reel),
                           master_digest="m" * 64, report_digest="r" * 64,
                           overall=True).write(provenance.attest_path(reel))
    reel.write_bytes(b"swapped after delivery")
    assert montage.next_action(str(run))["deliveries"][0]["state"] == "attested"
    assert montage.verify(str(run))["deliveries"][0]["state"] == "digest-mismatch"


def test_verify_reads_the_deliveries_bucket(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True)
    (lay.deliveries / "REEL_v1.mp4").write_bytes(b"x")
    assert len(montage.verify(str(tmp_path))["deliveries"]) == 1


# ---- contact-sheet required before edit-plan (design 2026-08-05 §6) ----

def test_footage_without_sheets_asks_for_the_contact_sheet(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    assert next_action(str(tmp_path))["next"] == "contact-sheet"


def test_the_sheet_unblocks_edit_plan(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    res = next_action(str(tmp_path))
    assert res["next"] == "edit-plan"
    assert _state(res, "contact-sheet") == "done"


def test_the_sheet_comes_after_the_footage_it_sheets_and_before_the_cut():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("footage-intake") < keys.index("contact-sheet")
    assert keys.index("contact-sheet") < keys.index("edit-plan")


def test_no_footage_still_asks_for_intake_first(tmp_path):
    # the sheet is not reachable before the FOOTAGE it reads
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "contact-sheet")
    assert next_action(str(tmp_path))["next"] == "footage-intake"


# ---- episode-qc stage split (design 2026-08-08-episode-qc-design.md §9) ----

def test_the_qc_stage_sits_between_the_episodes_and_the_reel():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("episodes") < keys.index("episode-qc") < keys.index("deliver")
    assert all(s.kind == "required" for s in montage.V1_STAGES
               if s.key in ("episodes", "episode-qc"))


def test_next_points_at_the_qc_stage_once_the_episodes_exist(tmp_path):
    """A run with rendered episodes and no verdicts is NOT ready to deliver."""
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry", "match-grade"):
        _touch(tmp_path, key)               # touch the artifacts the earlier stages need
    _touch(tmp_path, "episodes")
    assert next_action(str(tmp_path))["next"] == "episode-qc"


# ---- editorial constraints (design 2026-08-17 §3) ----

def test_status_reports_no_constraints_file(tmp_path):
    res = next_action(str(tmp_path))
    assert res["constraints"] == {"present": False, "rules": [], "error": None}


def test_status_reports_the_authored_rules(tmp_path):
    (tmp_path / "CONSTRAINTS.json").write_text(json.dumps(
        {"rules": [{"kind": "open_with", "hero": "Mika", "stated": "open on Mika"}]}))
    res = next_action(str(tmp_path))
    assert res["constraints"] == {
        "present": True,
        "rules": [{"kind": "open_with", "stated": "open on Mika", "hero": "Mika"}],
        "error": None}


def test_a_broken_constraints_file_reports_rather_than_raises(tmp_path):
    # The inspector is called constantly by the router. A refusal escaping here
    # replaces the whole status report with a traceback; reporting an empty rule
    # list instead would answer "nothing binds this cut" when the truth is
    # "nobody can tell" (design §3.1). Neither: present, empty, and WHY.
    (tmp_path / "CONSTRAINTS.json").write_text('{"rules": [{"kind": "bogus", "stated": "no idea"}]}')
    res = next_action(str(tmp_path))                     # must not raise
    assert res["constraints"]["present"] is True
    assert res["constraints"]["rules"] == []
    assert "bogus" in res["constraints"]["error"]


def test_status_softens_nothing_the_loader_still_refuses(tmp_path):
    # _constraints catches the refusal for its own report; the LOADER it calls
    # must keep raising, because write_edit_plan's no-waiver gate stands on
    # exactly this call. This pins the shared mechanism — the gate itself is
    # proven separately by test_edit_plan.py's
    # test_write_edit_plan_propagates_a_corrupt_rule_file.
    (tmp_path / "CONSTRAINTS.json").write_text('{"rules": [{"kind": "bogus", "stated": "no idea"}]}')
    with pytest.raises(ValueError, match="bogus"):
        constraints.Constraints.from_json(tmp_path / "CONSTRAINTS.json")


# ---- authored gates (design 2026-09-30 §2.4 item 3) ----
# `_gates` mirrors `_constraints`: found beside project.json, three states, and the load
# refusal caught HERE and nowhere else. "Nothing moved the bars" for a file nobody can read
# would be the worse of the two lies — _constraints' own ruling (design 2026-08-17 §3.1).

_BEAT = {"beat_tol": {"value": 0.08, "why": "no click track"}}
_BEAT_ROW = {"field": "beat_tol", "value": 0.08, "default": 0.05, "scope": "reel",
             "blocking": False, "why": "no click track"}


def test_status_names_the_three_gates_states(tmp_path):
    assert montage._gates(tmp_path) == {"present": False, "gates": [], "error": None}
    (tmp_path / "GATES.json").write_text(json.dumps(_BEAT))
    assert montage._gates(tmp_path) == {"present": True, "gates": [_BEAT_ROW], "error": None}
    (tmp_path / "GATES.json").write_text("{broken")
    out = montage._gates(tmp_path)
    assert out["present"] is True and out["gates"] == [] and out["error"]
    assert str(tmp_path / "GATES.json") in out["error"]


def test_a_gates_file_that_authors_nothing_is_present_and_empty_not_absent(tmp_path):
    """`{}` is legal and means every bar at its default — but the FILE is there, and a status
    that said `present: False` would send a reader looking for why their file was ignored."""
    (tmp_path / "GATES.json").write_text("{}")
    assert montage._gates(tmp_path) == {"present": True, "gates": [], "error": None}


def test_status_carries_the_gates_block_beside_the_constraints_one(tmp_path):
    (tmp_path / "GATES.json").write_text(json.dumps(_BEAT))
    res = next_action(str(tmp_path))
    assert res["gates"] == {"present": True, "gates": [_BEAT_ROW], "error": None}
    assert "frozen" not in res["gates"]         # no EPISODES.json: nothing has been frozen yet


def test_a_gates_path_that_cannot_be_read_reports_rather_than_raises(tmp_path):
    """Present but unreadable in a way the loader's own ValueError does not cover: a directory
    where the file should be raises OSError from read_text. _constraints catches only the
    ValueError; the other two readers in this module answer an unreadable file with a report, and
    "nobody can tell" is not "no gates" here either."""
    (tmp_path / "GATES.json").mkdir()
    out = montage._gates(tmp_path)
    assert out["present"] is True and out["gates"] == [] and "GATES.json" in out["error"]


def _freeze(run, doc):
    """EPISODES.json as phase 1b leaves it, reduced to the one block the inspector reads — raw,
    because the inspector reads raw (a typed load would refuse a file the status must report)."""
    ep = runlayout.RunLayout(run).episodes
    ep.mkdir(parents=True, exist_ok=True)
    (ep / "EPISODES.json").write_text(json.dumps({"gates": doc} if doc is not None else {}))


def test_status_says_which_phase_froze_the_set(tmp_path):
    """Phase 2 (--from-episodes) judges against what phase 1b wrote into EPISODES.json and never
    re-reads GATES.json — correctly: that set is the record of which bars judged these clips
    (design §6). So an operator looking at status is told where the set was frozen and what
    that means for an edit, even while the two still agree."""
    # The file's reason is PADDED and the frozen one is not: Gates strips it on the way in, so the
    # frozen set (written from the loaded Gates) never carries the padding, and a comparison of
    # the raw file against it would read every hand-indented file as drifted.
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"beat_tol": {"value": 0.08, "why": "  no click track  "}}))
    _freeze(tmp_path, _BEAT)
    frozen = next_action(str(tmp_path))["gates"]["frozen"]
    assert frozen["state"] == "same"
    assert "EPISODES.json froze this set" in frozen["detail"]
    assert "phase 1" in frozen["detail"] and "--from-episodes" in frozen["detail"]
    assert "never re-reads GATES.json" in frozen["detail"]


def test_status_says_plainly_when_the_file_no_longer_matches_what_phase_1_froze(tmp_path):
    """All three ways a file drifts from the frozen set, named by field — added, removed and
    changed — and what it means: phase 2 ignores the edit, and the remedy is re-running
    phase 1, which for a reel-scope bar re-renders every episode."""
    _freeze(tmp_path, {**_BEAT, "loudness_tol": {"value": 2.0, "why": "live room"}})
    (tmp_path / "GATES.json").write_text(json.dumps({
        "beat_tol": {"value": 0.09, "why": "no click track"},              # changed
        "entropy_floor": {"value": 0.85, "why": "log profile"}}))          # added; loudness_tol gone
    frozen = next_action(str(tmp_path))["gates"]["frozen"]
    assert frozen["state"] == "differs"
    d = frozen["detail"]
    assert "authored in the file but not frozen: entropy_floor" in d
    assert "frozen but no longer in the file: loudness_tol" in d
    assert "changed since: beat_tol" in d
    assert "FROZEN set" in d and "changes nothing for phase 2" in d
    assert "edl_to_reel --from-geometry" in d and "re-rendering every episode" in d
    # The exception to "changes nothing" (final review I1): a hand re-render reads the LIVE
    # file, so it would judge one episode against a bar the attestation does not record.
    assert "process_episode --project" in d and "LIVE file" in d
    assert "attestation" in d


def test_deleting_the_gates_file_does_not_lift_a_bar_from_a_reel_that_froze_it(tmp_path):
    """No silent bypass: a bar frozen into EPISODES.json keeps judging phase 2 after the file
    that authored it is gone, and status says so instead of reading as 'no gates'."""
    _freeze(tmp_path, _BEAT)
    res = next_action(str(tmp_path))["gates"]
    assert res["present"] is False and res["gates"] == []
    assert res["frozen"]["state"] == "differs"
    assert "frozen but no longer in the file: beat_tol" in res["frozen"]["detail"]


@pytest.mark.parametrize("doc", [None, {}], ids=["no-key", "empty"])
def test_status_is_silent_about_freezing_when_nothing_was_authored_or_frozen(tmp_path, doc):
    """EPISODES.json exists and no GATES.json does: there is no set to have frozen, and a
    `frozen` block on every unauthored run would be noise on the report the router reads most."""
    _freeze(tmp_path, doc)
    assert next_action(str(tmp_path))["gates"] == {"present": False, "gates": [], "error": None}


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    json.dumps({"gates": {"beat_tol": 0.08}}),
    None,
], ids=["not-json", "not-an-object", "corrupt-block", "directory"])
def test_an_unreadable_frozen_set_reads_as_unreadable_not_a_traceback(tmp_path, text):
    """The inspector never replaces a whole status report with a traceback, and a frozen set it
    cannot read is neither 'same' nor 'nothing frozen'. Four ways: broken JSON (a ValueError out of
    json), valid JSON that is not an object (`.get` on a list: an AttributeError), a gates block the
    loader refuses (a bare value, no reason), which a comparison of the raw block would have
    trusted instead of refusing, and an EPISODES.json that is a DIRECTORY: it exists, so the
    missing-file arm does not fire, and read_text() raises an OSError that no loader ever sees.
    Between them every member of the except tuple has a case that fails without it."""
    ep = runlayout.RunLayout(tmp_path).episodes
    ep.mkdir(parents=True)
    if text is None:
        (ep / "EPISODES.json").mkdir()
    else:
        (ep / "EPISODES.json").write_text(text)
    frozen = next_action(str(tmp_path))["gates"]["frozen"]
    assert frozen["state"] == "unreadable" and "EPISODES.json" in frozen["detail"]
    # The broken thing is EPISODES.json, so GATES.json must not be named as the culprit: the
    # loader words its refusal after the document it is told it was handed, and a message that
    # said GATES.json would send the operator to edit a file that is not the problem.
    assert "GATES.json" not in frozen["detail"]


@pytest.mark.parametrize("how", ["broken-json", "directory"])
def test_an_unreadable_gates_file_beside_a_frozen_set_reads_as_unreadable_not_a_traceback(
        tmp_path, how):
    """The other direction of the comparison. The file's own error is reported by `gates`, and the
    frozen block must not read 'same' or 'differs' against a file nobody can read. Broken JSON is
    the loader's ValueError; a directory where the file should be raises an OSError from
    read_text, which that arm does not cover — each member of this side's except tuple has a case."""
    _freeze(tmp_path, _BEAT)
    if how == "directory":
        (tmp_path / "GATES.json").mkdir()
    else:
        (tmp_path / "GATES.json").write_text("{broken")
    res = next_action(str(tmp_path))["gates"]
    assert res["error"]
    assert res["frozen"]["state"] == "unreadable"
    assert str(tmp_path / "GATES.json") in res["frozen"]["detail"]


def test_a_reason_only_edit_reads_as_drift_not_as_the_same_set(tmp_path):
    """The frozen set records why a bar was moved as well as to what, and the attestation carries
    that reason (design §2.4 item 2), so a file whose VALUE is untouched but whose reason was
    rewritten is a different record and must not read `same`. A comparison of values alone passes
    every other test here, because each of them changes a value or a key. Whitespace around a
    reason is NOT drift — the padded-`why` case in test_status_says_which_phase_froze_the_set,
    which the loader normalizes away — so this is exactly the line between the two."""
    _freeze(tmp_path, _BEAT)
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"beat_tol": {"value": 0.08, "why": "the click track is back, loosen it anyway"}}))
    frozen = next_action(str(tmp_path))["gates"]["frozen"]
    assert frozen["state"] == "differs"
    assert "changed since: beat_tol" in frozen["detail"]


def test_the_match_grade_stage_keys_on_the_json_not_the_markdown():
    """Every other stage's presence marker is its X.json; match-grade was the
    exception, and MATCH.md alone carries nothing a reader can check."""
    row = next(s for s in montage.V1_STAGES if s.key == "match-grade")
    assert row.artifact == "MATCH.json"


# ---- stale reports: a fifth state (design 2026-09-09 §6) ----
# `_full_run` does not exist in this file under that name (checked: no helper by any
# name fills every required stage in one call). The equivalent already repeated inline
# three times — test_reel_review_is_next_after_delivery, test_delivered_when_deliver_
# artifact_exists and (with reel-review touched too, the fully-done case this task
# needs) test_a_run_is_only_finished_when_the_review_exists — is promoted here to a
# helper rather than being typed a fourth time.
def _full_run(run):
    for key in ("project-init", "footage-intake", "contact-sheet", "edit-plan",
               "episodes-geometry", "match-grade"):
        _touch(run, key)
    _touch(run, "episodes")
    _touch(run, "episode-qc")
    _touch(run, "deliver", name="REEL_v1.mp4")
    _touch(run, "reel-review")    # AFTER deliver — see _touch's docstring


def _match_json(reel_dir, edl_path, *, authored=((0, (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)),)):
    """A MATCH.json whose decisions author a pair on each listed episode index."""
    decisions = [matchgrade.ToneDecision(i, "author", "authored", measured=src,
                                         tone_src=src, tone_dst=dst)
                 for i, src, dst in authored]
    matchgrade.MatchReport(target=(4.0, 5.0, 6.0), eps=4.0, decisions=tuple(decisions),
                           edl=str(edl_path)).write(Path(reel_dir) / "MATCH.json")


def _edl_json(path, pairs):
    """A minimal EDL.json — raw, because the reader reads raw."""
    Path(path).write_text(json.dumps({"episodes": [
        {"source": f"s{i}.mp4", "start": 0.0, "dur": 2.0,
         "tone_src": None if s is None else list(s),
         "tone_dst": None if d is None else list(d)}
        for i, (s, d) in enumerate(pairs)]}))


def test_match_grade_is_fresh_when_the_edl_still_carries_its_pairs(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    edl = lay.reel_dir / "EDL.json"
    _edl_json(edl, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))])
    _match_json(lay.reel_dir, edl)
    assert montage._match_grade_state(lay.reel_dir) == ("fresh", "")


def test_match_grade_is_stale_when_a_pacing_rerun_wiped_the_pairs(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    edl = lay.reel_dir / "EDL.json"
    _edl_json(edl, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))])
    _match_json(lay.reel_dir, edl)
    _edl_json(edl, [(None, None)])                      # edit_plan --pacing wiped the tone
    state, why = montage._match_grade_state(lay.reel_dir)
    assert state == "stale"
    assert "episode 0 was authored a tone pair" in why


def test_an_unreadable_match_json_is_stale_and_says_so_rather_than_raising(tmp_path):
    """The inspector must never replace a whole status report with a traceback —
    _constraints' rule, for the same reason."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.reel_dir / "MATCH.json").write_text("{not json")
    state, why = montage._match_grade_state(lay.reel_dir)
    assert state == "stale" and "corrupt" in why


def test_a_stale_match_grade_stage_is_not_done_and_next_points_back_at_it(tmp_path):
    lay = runlayout.RunLayout(tmp_path)                  # the reel next_action inspects
    _full_run(tmp_path)                                  # by default ("main") — see above
    edl = lay.reel_dir / "EDL.json"
    _edl_json(edl, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))])
    _match_json(lay.reel_dir, edl)
    _edl_json(edl, [(None, None)])
    res = montage.next_action(str(tmp_path))
    row = next(s for s in res["stages"] if s["key"] == "match-grade")
    assert row["state"] == "stale"
    assert row["stale_reason"]
    assert res["next"] == "match-grade"


def test_a_review_of_the_newest_delivery_is_fresh(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v2.mp4").write_text("x")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(lay.deliveries / "REEL_v2.mp4"), "findings": []}))
    assert montage._review_state(lay.reel_dir, lay.deliveries) == ("fresh", "")


def test_a_review_of_an_older_version_is_stale_and_names_both(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("x")
    (lay.deliveries / "REEL_v2.mp4").write_text("x")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(lay.deliveries / "REEL_v1.mp4"), "findings": []}))
    state, why = montage._review_state(lay.reel_dir, lay.deliveries)
    assert state == "stale"
    assert "REEL_v1.mp4" in why and "REEL_v2.mp4" in why


def test_the_status_check_hashes_nothing(tmp_path, monkeypatch):
    """status is called constantly by the router; re-hashing a 100 MB reel on every
    call is the one thing these two checks must never do."""
    _full_run(tmp_path)
    monkeypatch.setattr(montage.provenance, "digest_file",
                        lambda p: pytest.fail(f"status hashed {p}"))
    montage.next_action(str(tmp_path))


def test_an_interrupted_delivery_is_reported_and_does_not_read_as_delivered(tmp_path):
    lay = runlayout.RunLayout(tmp_path)                  # the reel next_action inspects
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / ".REEL_v1.part.mp4").write_text("half")
    res = montage.next_action(str(tmp_path))
    assert res["interrupted"] == [".REEL_v1.part.mp4"]
    assert res["delivered"] is False


def test_verify_rehashes_the_review_against_the_reel_it_judged(tmp_path):
    lay = runlayout.RunLayout(tmp_path)                  # the reel verify inspects
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(reel), "reel_digest": provenance.digest_file(reel), "findings": []}))
    assert montage.verify(str(tmp_path))["review"]["state"] == "bound"
    reel.write_text("a different reel entirely")
    assert montage.verify(str(tmp_path))["review"]["state"] == "digest-mismatch"


def test_verify_calls_an_unstamped_review_unbound_not_mismatched(tmp_path):
    """A review written before the digest existed asserts nothing about bytes — the
    honest word for that is unbound, not a failed comparison."""
    lay = runlayout.RunLayout(tmp_path)                  # the reel verify inspects
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(lay.deliveries / "REEL_v1.mp4"), "findings": []}))
    assert montage.verify(str(tmp_path))["review"]["state"] == "unbound"


# ---- C-1 fix: wrong-shaped (but syntactically valid) JSON must not raise ----
# Review finding on this task: `_match_grade_state` indexed `e.get(...)` over
# `episodes` outside any guard, and `_review_state`/`_verify_review` called `.get()`
# on whatever `json.loads` returned without checking it was a dict. Six inputs from
# the review's own repro table, each driven through the real public entry point
# (never the private function) exactly as the review reproduced it.

def test_next_action_survives_an_edl_whose_episodes_is_a_dict(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "EDL.json").write_text(json.dumps({"episodes": {"0": {}}}))
    res = montage.next_action(str(tmp_path))              # must not raise
    row = next(s for s in res["stages"] if s["key"] == "match-grade")
    assert row["state"] == "stale"
    assert row["stale_reason"]


def test_next_action_survives_an_edl_whose_episodes_is_a_string(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "EDL.json").write_text(json.dumps({"episodes": "abc"}))
    res = montage.next_action(str(tmp_path))              # must not raise
    row = next(s for s in res["stages"] if s["key"] == "match-grade")
    assert row["state"] == "stale"
    assert row["stale_reason"]


def test_next_action_survives_an_edl_whose_episodes_is_a_list_of_non_dicts(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "EDL.json").write_text(json.dumps({"episodes": [1, 2, 3]}))
    res = montage.next_action(str(tmp_path))              # must not raise
    row = next(s for s in res["stages"] if s["key"] == "match-grade")
    assert row["state"] == "stale"
    assert row["stale_reason"]


def test_next_action_survives_an_edl_whose_episodes_is_null(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "EDL.json").write_text(json.dumps({"episodes": None}))
    res = montage.next_action(str(tmp_path))              # must not raise
    row = next(s for s in res["stages"] if s["key"] == "match-grade")
    assert row["state"] == "stale"
    assert row["stale_reason"]


def test_verify_survives_a_review_json_that_is_a_bare_list(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(["x"]))
    got = montage.verify(str(tmp_path))["review"]          # must not raise
    assert got["state"] != "bound"
    assert got["detail"]


def test_verify_survives_a_review_json_that_is_bare_null(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text("null")
    got = montage.verify(str(tmp_path))["review"]          # must not raise
    assert got["state"] != "bound"
    assert got["detail"]


# `_review_state` (next_action's own freshness reader for reel-review) reads
# REVIEW.json too, independently of `_verify_review` — the same two malformed
# shapes must not raise there either, or `montage status` would crash on a run
# whose REVIEW.json is a list/null even though `montage verify` was fixed.

def test_next_action_survives_a_review_json_that_is_a_bare_list(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(["x"]))
    res = montage.next_action(str(tmp_path))               # must not raise
    row = next(s for s in res["stages"] if s["key"] == "reel-review")
    assert row["state"] == "stale"
    assert row["stale_reason"]


def test_next_action_survives_a_review_json_that_is_bare_null(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "REVIEW.json").write_text("null")
    res = montage.next_action(str(tmp_path))               # must not raise
    row = next(s for s in res["stages"] if s["key"] == "reel-review")
    assert row["state"] == "stale"
    assert row["stale_reason"]


# ---- residual review (2026-09-09): a well-shaped REVIEW.json whose "reel"/
# "reel_digest" VALUES are the wrong JSON type must not raise either. The C-1 fix
# above closed the top-level shape (REVIEW.json itself a list/null, so `.get()`
# fails); this is one layer in — REVIEW.json is a plain object, `.get("reel")`
# succeeds, and the value it returns is a number/bool/list/dict that `Path()` (or
# `[:12]` slicing, for reel_digest) raises on regardless. Both `_as_str`'s guard and
# each site it protects are exercised only through the real public entry points.

def test_next_action_survives_a_review_json_whose_reel_is_a_number(tmp_path):
    """The exact repro from the finding: {"reel": 42, "findings": []}."""
    lay = runlayout.RunLayout(tmp_path)
    _full_run(tmp_path)
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps({"reel": 42, "findings": []}))
    res = montage.next_action(str(tmp_path))               # must not raise
    row = next(s for s in res["stages"] if s["key"] == "reel-review")
    assert row["state"] == "stale"
    assert row["stale_reason"]


def test_verify_survives_a_review_json_whose_reel_is_a_number_and_unbound(tmp_path):
    """No reel_digest recorded — the finding's first crash site, montage.py:334."""
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps({"reel": 42, "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "unbound"
    assert got["detail"]


def test_verify_survives_a_review_json_whose_reel_is_a_number_with_a_digest(tmp_path):
    """A reel_digest is also present — the finding's second crash site, montage.py:337."""
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": 42, "reel_digest": provenance.digest_file(reel), "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "missing"
    assert got["detail"]


def test_verify_survives_a_review_json_with_no_reel_field_but_a_digest_is_recorded(tmp_path):
    """A sibling landmine found while sweeping, not in the finding's own repro: an
    absent (or null) reel already read as "" before this fix via `or ""`, and a
    present reel_digest pushes past the unbound check to `Path("").exists()` — True,
    because pathlib normalizes "" to the cwd — and on into digest_file(""), whose raw
    open() does NOT do that normalization and raises FileNotFoundError instead.
    Confirmed by direct repro against the pre-fix code before writing this test."""
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel_digest": provenance.digest_file(reel), "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "missing"
    assert got["detail"]


def test_verify_survives_a_review_json_whose_reel_digest_is_a_number(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(reel), "reel_digest": 42, "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "unbound"
    assert got["detail"]


def test_verify_survives_a_review_json_whose_reel_digest_is_a_bool(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(reel), "reel_digest": True, "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "unbound"
    assert got["detail"]


def test_verify_survives_a_review_json_whose_reel_digest_is_a_list(tmp_path):
    """[1, 2, 3][:12] does not itself raise, so this one already returned rather than
    raised before the fix — but landed on "digest-mismatch" with a garbled detail
    ("...but the review records [1, 2, 3]..."). Hardening folds it into the same
    clean "unbound" every other non-string digest gets, which is what makes this
    "hardened" rather than merely "lucky"; the assertion below still discriminates
    pre/post fix even though neither raises."""
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(reel), "reel_digest": [1, 2, 3], "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "unbound"
    assert got["detail"]


def test_verify_survives_a_review_json_whose_reel_digest_is_a_dict(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(reel), "reel_digest": {"a": 1}, "findings": []}))
    got = montage.verify(str(tmp_path))["review"]           # must not raise
    assert got["state"] == "unbound"
    assert got["detail"]
