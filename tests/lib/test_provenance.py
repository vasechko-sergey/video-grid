import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.lib import provenance
from scripts.lib.models import ReelCheckSpec


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
    spec = ReelCheckSpec(target_dur=10.0, color_delta_max=20.0)
    assert provenance.spec_overrides(spec) == [
        {"field": "color_delta_max", "value": 20.0, "default": 12.0}]


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
             overrides=[{"field": "color_delta_max", "value": 20.0, "default": 12.0}],
             delivered_at="2026-08-04T10:00:00")
    p = tmp_path / "REEL_v1.attest.json"
    a.write(p)
    assert provenance.Attestation.from_json(p).to_dict() == a.to_dict()


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
