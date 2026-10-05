import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.lib import gates, provenance
from scripts.lib.models import ReelCheckSpec, ReelEpisode, ReelManifest


def test_digest_obj_ignores_the_provenance_key_and_key_order():
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2, "provenance": {"anything": "at all"}}
    assert provenance.digest_obj(a) == provenance.digest_obj(b)


def test_digest_obj_sees_a_value_change():
    assert provenance.digest_obj({"a": 1}) != provenance.digest_obj({"a": 2})


def test_stamp_then_check_is_intact():
    d = {"episodes": [1, 2], "cap": 3}
    d["provenance"] = provenance.stamp(d)
    assert provenance.check(d)[0] == "intact"


def test_a_mutated_field_is_tampered_and_the_detail_names_both_digests():
    d = {"episodes": [1, 2], "cap": 3}
    d["provenance"] = provenance.stamp(d)
    d["cap"] = 9
    state, detail = provenance.check(d)
    assert state == "tampered"
    assert "recorded digest" in detail and "hash to" in detail


def test_a_missing_block_is_unstamped_not_tampered():
    assert provenance.check({"cap": 3})[0] == "unstamped"
    assert provenance.check({"cap": 3, "provenance": {}})[0] == "unstamped"


def test_stamp_records_inputs_verbatim(tmp_path):
    src = tmp_path / "selection.json"
    src.write_text('{"episodes": []}')
    block = provenance.stamp({"a": 1}, inputs={"selection": provenance.digest_file(src)})
    assert block["inputs"]["selection"] == provenance.digest_file(src)
    assert block["v"] == provenance.PROV_V


def test_stamp_carries_no_timestamp(tmp_path):
    # a written_at would make every stamped artifact byte-unstable run to run
    assert set(provenance.stamp({"a": 1})) == {"v", "engine", "self", "inputs"}


def test_digest_file_matches_a_known_sha256(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert provenance.digest_file(f) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_engine_stamp_on_a_non_repo_is_unknown_and_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "_ROOT", tmp_path)     # a dir with no .git
    assert provenance.engine_stamp() == {"sha": "", "dirty": None}


def test_engine_stamp_on_this_repo_reports_a_sha():
    st = provenance.engine_stamp()
    assert isinstance(st["sha"], str) and len(st["sha"]) >= 7
    assert st["dirty"] in (True, False)


def test_spec_overrides_is_empty_for_a_default_spec():
    assert provenance.spec_overrides(ReelCheckSpec(target_dur=10.0)) == []


def test_spec_overrides_names_the_loosened_field():
    spec = ReelCheckSpec(target_dur=10.0, variety_min=4)
    assert provenance.spec_overrides(spec) == [
        {"field": "variety_min", "value": 4, "default": 8}]


def test_spec_overrides_covers_a_field_the_spec_gains_later():
    # the whole point of a diff over a registry: a threshold added to a spec is
    # covered the day it lands, with no second place to remember.
    @dataclass
    class Later:
        target_dur: float
        brand_new_gate: int = 5

    assert provenance.spec_overrides(Later(target_dur=1.0, brand_new_gate=9)) == [
        {"field": "brand_new_gate", "value": 9, "default": 5}]


def test_attest_path_sits_beside_the_reel():
    assert provenance.attest_path("/o/REEL_v3.mp4").name == "REEL_v3.attest.json"


def _att(**kw):
    base = dict(reel="REEL_v1.mp4", reel_digest="d" * 64, master_digest="m" * 64,
                report_digest="r" * 64, overall=True)
    return provenance.Attestation(**{**base, **kw})


def test_attestation_round_trips_through_json(tmp_path):
    a = _att(engine_at_start={"sha": "aaa", "dirty": False},
             engine_at_deliver={"sha": "aaa", "dirty": False},
             edl={"digest": "e", "state": "intact"},
             overrides=[{"field": "variety_min", "value": 4, "default": 8}],
             episode_qc={"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [1]},
             look_checks=[{"check": "vignette", "status": "pass", "detail": "",
                           "measured": 9.1, "expected": 8.0}],
             delivered_at="2026-08-04T10:00:00")
    p = tmp_path / "REEL_v1.attest.json"
    a.write(p)
    back = provenance.Attestation.from_json(p)
    assert back.to_dict() == a.to_dict()
    assert back.episode_qc == {"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [1]}


def test_verify_delivery_without_a_sidecar_is_unattested(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"hand-made")
    got = provenance.verify_delivery(reel)
    assert got["state"] == "unattested"
    assert "not produced by deliver" in got["detail"]


def test_verify_delivery_reads_state_without_rehashing(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel)).write(provenance.attest_path(reel))
    reel.write_bytes(b"two")                       # swapped AFTER delivery
    assert provenance.verify_delivery(reel)["state"] == "attested"          # cheap read
    assert provenance.verify_delivery(reel, rehash=True)["state"] == "digest-mismatch"


def test_verify_delivery_flags_a_failed_gate(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(overall=False, reel_digest=provenance.digest_file(reel)).write(
        provenance.attest_path(reel))
    assert provenance.verify_delivery(reel, rehash=True)["state"] == "failed-gate"


def test_verify_delivery_engine_drift_flag(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         engine_at_start={"sha": "aaa", "dirty": False},
         engine_at_deliver={"sha": "bbb", "dirty": False}).write(provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["engine_drift"] is True


def test_verify_delivery_unknown_stamps_are_not_drift(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         engine_at_start={"sha": "", "dirty": None},
         engine_at_deliver={"sha": "bbb", "dirty": False}).write(provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["engine_drift"] is False


def test_verify_delivery_on_corrupt_json_is_unattested(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    provenance.attest_path(reel).write_text("{not json")
    got = provenance.verify_delivery(reel)
    assert got["state"] == "unattested" and "unreadable" in got["detail"]


def test_verify_delivery_without_a_sidecar_reports_episode_qc_unknown(tmp_path):
    # No sidecar at all -> no QC record to report either way — design §10's
    # vocabulary has no fourth word for "nothing was delivered here".
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"hand-made")
    assert provenance.verify_delivery(reel)["episode_qc"] == "unknown"


def test_verify_delivery_reports_a_judged_episode_qc_state(tmp_path):
    # design §10/§7: montage verify must be able to tell a judged reel from an
    # unjudged one — the whole point of the two-phase gate is lost if the record it
    # writes cannot be read back.
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         episode_qc={"state": "judged", "judged": {"0": "aa"}}).write(
        provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["episode_qc"] == "judged"


def test_verify_delivery_reports_an_absent_episode_qc_state(tmp_path):
    # the single-command edl_to_reel path (and build_reel's own CLI bypass) stamp
    # "absent" rather than staying silent on the question (design §10).
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         episode_qc={"state": "absent"}).write(provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["episode_qc"] == "absent"


def test_verify_delivery_reports_unknown_for_an_old_sidecar_with_no_episode_qc_key(tmp_path):
    # A sidecar written before this field existed — the raw JSON carries no
    # "episode_qc" key at all, not even an empty one. Attestation.from_dict defaults
    # it to {}, so this must read as "unknown", the same as a producer bug that wrote
    # a state-less block (neither "judged" nor "absent" — see the build_reel CLI fix).
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    stale = _att(reel_digest=provenance.digest_file(reel)).to_dict()
    del stale["episode_qc"]
    provenance.attest_path(reel).write_text(json.dumps(stale))
    assert provenance.verify_delivery(reel)["episode_qc"] == "unknown"


def test_verify_delivery_reports_unknown_for_a_state_less_episode_qc_block(tmp_path):
    # The exact shape the build_reel-CLI-bypass bug produced before its fix:
    # {"reprocessed_after": [...]} with no "state" key — neither word, so "unknown".
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         episode_qc={"reprocessed_after": []}).write(provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["episode_qc"] == "unknown"


# --- 2026-08-18 re-judge: the fourth episode_qc state ----------------------------

def test_a_judged_delivery_that_re_rendered_after_the_verdict_reads_stale():
    """design 2026-08-18 §3: the record was always in the sidecar — the inspector used
    to drop it, so a reel carrying unjudged renders reported a clean `judged` at the one
    place CP3 tells a human to look."""
    att = _att(episode_qc={"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [0]})
    assert provenance._episode_qc_state(att) == "stale"


def test_a_judged_delivery_that_re_rendered_nothing_stays_judged():
    att = _att(episode_qc={"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": []})
    assert provenance._episode_qc_state(att) == "judged"


def test_an_unjudged_delivery_cannot_be_stale():
    """A reel with no verdict has no stale one — `absent` is the honest answer and must
    not be upgraded to a QC word it never earned."""
    att = _att(episode_qc={"state": "absent", "reprocessed_after": [0, 1]})
    assert provenance._episode_qc_state(att) == "absent"


def test_verify_delivery_surfaces_the_stale_state(tmp_path):
    """The arm has to reach the dict montage verify actually prints, not only the helper."""
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"reel")
    _att(reel_digest=provenance.digest_file(reel),
         episode_qc={"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [0]}).write(
        provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["episode_qc"] == "stale"


def test_an_unattested_file_detail_does_not_assert_the_least_likely_cause(tmp_path):
    """deliver DOES write the file before the look gate withholds an attestation, and
    (since 2026-09-09) before the attestation is written at all — so 'this file was not
    produced by deliver()' is the one reading that is usually false."""
    p = tmp_path / "REEL_v1.mp4"
    p.write_text("x")
    detail = provenance.verify_delivery(p)["detail"]
    assert "no attestation sidecar" in detail
    assert "was not produced by deliver()" not in detail
    assert "look gate" in detail and "interrupted" in detail


# --- 2026-09-30 threshold surface Task 5: the attestation names every authored gate ---
# (design §2.4 item 2.)

def test_the_attestation_records_every_authored_gate_with_its_reason_and_scope(tmp_path):
    authored = gates.Gates.from_dict(
        {"entropy_floor": {"value": 0.85, "why": "log profile"},
         "beat_tol": {"value": 0.08, "why": "no click track"}})
    a = _att(gates=authored.record())
    p = tmp_path / "REEL_v1.attest.json"
    a.write(p)
    back = provenance.Attestation.from_json(p)
    assert back.gates == a.gates
    assert json.loads(p.read_text())["gates"] == [
        {"field": "entropy_floor", "value": 0.85, "default": 0.9, "scope": "episode",
         "blocking": True, "why": "log profile"},
        {"field": "beat_tol", "value": 0.08, "default": 0.05, "scope": "reel",
         "blocking": False, "why": "no click track"}]


def test_an_attestation_that_authored_no_gates_has_no_gates_key(tmp_path):
    """Absent, not []: the sidecar of a run that authored nothing is the one it always was
    (design §3). A sidecar written before the field existed reads as authoring none, which is
    true of it — no gate could be authored then."""
    assert "gates" not in _att().to_dict()
    old = {k: v for k, v in _att().to_dict().items() if k != "gates"}
    assert provenance.Attestation.from_dict(old).gates == []


def test_verify_delivery_surfaces_the_authored_gates_beside_overrides(tmp_path):
    """montage status reads deliveries[] from this function, and it is the one place a human
    looks. `overrides` reads [] on EVERY sanctioned run (design §0.4: spec_overrides runs once, in
    phase 1, and no producer sets variety_min), so a status that showed only `overrides` would say
    "no waivers" about a delivery whose sidecar carries them — the silence §2.4 exists to end. The
    first sidecar below is that exact case: overrides empty, one authored gate. The second is its
    mirror, an override and no gate (what a hand-edited EPISODES.json can produce), so each list
    is pinned by a value its own default does not equal — a pass-through that dropped either one
    would otherwise read as the empty default."""
    rows = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "log profile"}}).record()
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel), overrides=[], gates=rows).write(
        provenance.attest_path(reel))
    got = provenance.verify_delivery(reel)
    assert got["state"] == "attested" and got["overrides"] == [] and got["gates"] == rows

    mirror = tmp_path / "REEL_v2.mp4"
    mirror.write_bytes(b"two")
    waiver = [{"field": "variety_min", "value": 4, "default": 8}]
    _att(reel="REEL_v2.mp4", reel_digest=provenance.digest_file(mirror), overrides=waiver).write(
        provenance.attest_path(mirror))
    got = provenance.verify_delivery(mirror)
    assert got["overrides"] == waiver and got["gates"] == [] and got["overall"] is True


def test_spec_overrides_is_unchanged_by_this_slice():
    """It answers a different question — what differs from the default, WHATEVER the source —
    so a reel-scope gate appears in both lists and the two lists keep different shapes: this
    one is reason-free, and the attestation's `gates` carries the reason (design §2.4 item 2).
    Deduplicating them is the tidy-looking edit this pins against: the variety_min tests above
    cannot see it, because variety_min is not a gate."""
    m = ReelManifest(episodes=[ReelEpisode(manifest={}, clip="c.mp4", route=None)],
                     target_dur=6.0,
                     gates={"loudness_tol": {"value": 2.0, "why": "live room"}})
    assert provenance.spec_overrides(m.check_spec) == [
        {"field": "loudness_tol", "value": 2.0, "default": 1.0}]
