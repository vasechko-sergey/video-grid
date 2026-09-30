"""The authored-gate surface (design 2026-09-30)."""
import json
import subprocess
import sys
import textwrap
from dataclasses import fields as dc_fields
from pathlib import Path

import pytest

from scripts.lib import gates
from scripts.lib.models import CheckSpec, ReelCheckSpec, _ADVISORY_CHECKS

ROOT = Path(__file__).resolve().parents[1]


def test_the_vocabulary_is_derived_from_the_two_spec_classes_not_typed():
    # The row's twelve, arrived at from the dataclasses (design §0.6). This test is
    # what fails the day a thirteenth threshold lands without a decision about it.
    names = {f.name for f in dc_fields(ReelCheckSpec)} | {f.name for f in dc_fields(CheckSpec)}
    assert len(names) == 17
    assert set(gates.FIELDS) == names - set(gates.AUTHORED_ELSEWHERE)
    assert len(gates.FIELDS) == 12


def test_every_gateable_field_names_the_check_it_sets_the_bar_for():
    assert set(gates.OF_CHECK) == set(gates.FIELDS)


def test_the_blocking_set_is_derived_from_the_advisory_registry():
    assert gates.BLOCKING == frozenset(
        n for n, c in gates.OF_CHECK.items() if c not in _ADVISORY_CHECKS)
    assert gates.BLOCKING == {"loudness_target", "loudness_tol", "grade_residual_max",
                              "length_retime_max", "black_floor", "black_rel",
                              "entropy_floor"}


def test_an_authored_value_reaches_the_class_that_owns_it():
    g = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "log profile"},
                               "beat_tol": {"value": 0.08, "why": "no click track"}})
    assert g.for_spec(CheckSpec) == {"entropy_floor": 0.85}
    assert g.for_spec(ReelCheckSpec) == {"beat_tol": 0.08}


def test_a_non_object_document_is_refused():
    with pytest.raises(ValueError, match="GATES.json"):
        gates.Gates.from_dict([{"entropy_floor": 0.85}])


def test_an_unknown_field_is_refused_and_the_message_names_the_vocabulary():
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entrpy_floor": {"value": 0.85, "why": "typo"}})
    assert "entrpy_floor" in str(e.value)
    assert "entropy_floor" in str(e.value)


def test_a_field_authored_elsewhere_is_refused_and_the_message_says_where():
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"variety_min": {"value": 4, "why": "short reel"}})
    assert "variety_min" in str(e.value)
    assert "EDL" in str(e.value)


def test_an_entry_that_is_a_bare_number_is_refused():
    with pytest.raises(ValueError, match="value.*why|why.*value"):
        gates.Gates.from_dict({"entropy_floor": 0.85})


@pytest.mark.parametrize("why", [None, "", "   ", 7])
def test_a_value_without_a_written_reason_is_refused(why):
    # Design §1: the reason is structurally required, not conventionally expected.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": why}})
    assert "why" in str(e.value)


def test_a_value_the_owning_dataclass_rejects_is_refused_by_that_dataclass():
    # entropy_floor must be a ratio in (0, 1]; the loader does not re-implement that.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entropy_floor": {"value": 1.5, "why": "louder"}})
    msg = str(e.value)
    assert "GATES.json" in msg and "entropy_floor" in msg
    assert "ratio in (0, 1]" in msg     # the existing CheckSpec.__post_init__ text


def test_from_json_names_the_path_it_could_not_load(tmp_path):
    p = tmp_path / "GATES.json"
    p.write_text("{not json")
    with pytest.raises(ValueError) as e:
        gates.Gates.from_json(p)
    assert str(p) in str(e.value)


def test_the_record_carries_value_default_scope_blocking_and_why():
    g = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "log profile"},
                               "beat_tol": {"value": 0.08, "why": "no click track"}})
    by = {r["field"]: r for r in g.record()}
    assert by["entropy_floor"] == {"field": "entropy_floor", "value": 0.85,
                                   "default": 0.90, "scope": "episode",
                                   "blocking": True, "why": "log profile"}
    assert by["beat_tol"] == {"field": "beat_tol", "value": 0.08, "default": 0.05,
                              "scope": "reel", "blocking": False,
                              "why": "no click track"}


def test_an_empty_document_is_legal_and_authors_nothing():
    g = gates.Gates.from_dict({})
    assert g.for_spec(ReelCheckSpec) == {} and g.for_spec(CheckSpec) == {}
    assert g.record() == [] and g.to_dict() == {}


def test_to_dict_round_trips_through_from_dict():
    d = {"black_rel": {"value": 0.2, "why": "night shoot"}}
    assert gates.Gates.from_dict(gates.Gates.from_dict(d).to_dict()).to_dict() == d


def test_reasons_maps_field_to_why():
    g = gates.Gates.from_dict({"black_rel": {"value": 0.2, "why": "night shoot"}})
    assert g.reasons() == {"black_rel": "night shoot"}


# ---- Coverage the tests above do not give -----------------------------------------
# Each test below closes a breakage the tests above cannot see. They were found by
# breaking the module one deliberate way at a time and reading which tests went red:
# where none did, the design's claim was standing on nothing.


@pytest.mark.parametrize("entry", [
    {"value": 0.85},                                        # the reason is MISSING
    {"why": "log profile"},                                 # the value is missing
    {"value": 0.85, "why": "log profile", "note": "x"},     # a key the schema does not have
    [0.85, "log profile"],
    "0.85",
    None,
], ids=["no-why", "no-value", "extra-key", "list", "string", "null"])
def test_an_entry_that_is_not_exactly_value_and_why_is_refused(entry):
    # Design §2.2.4/§2.2.5: a MISSING why is a refusal of its own, distinct from a blank
    # one. Without it an entry lacking the key would reach entry["why"] and escape as a
    # bare KeyError, and a misspelt key ("whyy") would be dropped without a word.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entropy_floor": entry})
    msg = str(e.value)
    assert "entropy_floor" in msg and "'value'" in msg and "'why'" in msg


@pytest.mark.parametrize("name", sorted(gates.AUTHORED_ELSEWHERE))
def test_every_name_authored_elsewhere_is_refused_not_ignored(name):
    # Design §0.6: five names, each authored somewhere else. A value silently dropped
    # here would READ as authored, so each is refused, and the refusal says where.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({name: {"value": 1, "why": "x"}})
    assert name in str(e.value)
    assert gates.AUTHORED_ELSEWHERE[name] in str(e.value)


@pytest.mark.parametrize("doc", [
    [1],                                                    # not an object
    {"entrpy_floor": {"value": 0.85, "why": "typo"}},       # not a threshold
    {"variety_min": {"value": 4, "why": "short reel"}},     # authored elsewhere
    {"entropy_floor": 0.85},                                # a bare number
    {"entropy_floor": {"value": 0.85, "why": "  "}},        # a blank reason
    {"entropy_floor": {"value": 1.5, "why": "louder"}},     # the owning class refuses
], ids=["not-object", "unknown", "elsewhere", "bare", "blank-why", "owner-refuses"])
def test_every_refusal_names_where_the_document_came_from(doc):
    # ReelManifest.from_dict re-validates the block it carries under its own label
    # (design §2.3), so `where` has to reach ALL SIX messages, not only the first.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict(doc, where="ReelManifest.gates")
    assert "ReelManifest.gates" in str(e.value)


def test_from_json_reads_a_valid_file(tmp_path):
    doc = {"entropy_floor": {"value": 0.85, "why": "log profile"},
           "beat_tol": {"value": 0.08, "why": "no click track"}}
    p = tmp_path / "GATES.json"
    p.write_text(json.dumps(doc))
    assert gates.Gates.from_json(p) == gates.Gates.from_dict(doc)
    assert gates.Gates.from_json(str(p)).to_dict() == doc      # str and Path both work


def test_a_content_refusal_from_a_file_names_the_file(tmp_path):
    # Design §5: each refusal fires "with the path in the message". from_dict alone
    # can only say "GATES.json"; from_json is what knows which file, so this is the
    # half of the guarantee the invalid-JSON test above does not reach.
    p = tmp_path / "GATES.json"
    p.write_text(json.dumps({"entrpy_floor": {"value": 0.85, "why": "typo"}}))
    with pytest.raises(ValueError) as e:
        gates.Gates.from_json(p)
    assert str(p) in str(e.value)
    assert "entrpy_floor" in str(e.value)


def test_a_reason_is_stored_without_its_padding():
    g = gates.Gates.from_dict({"black_rel": {"value": 0.2, "why": "  night shoot \n"}})
    assert g.reasons() == {"black_rel": "night shoot"}
    assert g.to_dict() == {"black_rel": {"value": 0.2, "why": "night shoot"}}


def test_a_threshold_or_an_advisory_check_added_upstream_reaches_the_vocabulary():
    # The two DERIVED claims, made observable. `set(FIELDS) == names - ELSEWHERE` cannot
    # fail for a correct hand-typed list: it recomputes the same thing, so a tuple of
    # twelve literals passes it today and rots the day a thirteenth lands. Here the
    # INPUTS move instead. A fresh interpreter widens ReelCheckSpec by one field and
    # the advisory registry by one check BEFORE importing gates, and the module has to
    # follow. A fresh process rather than importlib.reload, because a reload mints new
    # Gate/Gates classes and leaves every module that already holds the old ones
    # comparing unequal to them.
    probe = textwrap.dedent("""
        import dataclasses, json
        from scripts.lib import models

        @dataclasses.dataclass
        class Widened(models.ReelCheckSpec):
            extra_tol: float = 1.0

        models.ReelCheckSpec = Widened
        models._ADVISORY_CHECKS = models._ADVISORY_CHECKS + ("loudness",)
        from scripts.lib import gates
        print(json.dumps({"fields": list(gates.FIELDS),
                          "blocking": sorted(gates.BLOCKING)}))
    """)
    run = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         cwd=ROOT)
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout)
    assert "extra_tol" in seen["fields"]                       # FIELDS follows the class
    assert "loudness_target" not in seen["blocking"]           # BLOCKING follows the registry
    assert "loudness_tol" not in seen["blocking"]
    assert "grade_residual_max" in seen["blocking"]            # ...and only what moved
