"""The authored-gate surface (design 2026-09-30)."""
import ast
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
    # Not the derivation's guard: a hand-typed list passes it. The real guard is
    # test_a_threshold_or_an_advisory_check_added_upstream_reaches_the_vocabulary.
    names = {f.name for f in dc_fields(ReelCheckSpec)} | {f.name for f in dc_fields(CheckSpec)}
    assert len(names) == 17
    assert set(gates.FIELDS) == names - set(gates.AUTHORED_ELSEWHERE)
    assert len(gates.FIELDS) == 12


def test_every_gateable_field_names_the_check_it_sets_the_bar_for():
    assert set(gates.OF_CHECK) == set(gates.FIELDS)


def test_the_blocking_set_is_derived_from_the_advisory_registry():
    # Not the derivation's guard: a hand-typed set passes it. The real guard is
    # test_a_threshold_or_an_advisory_check_added_upstream_reaches_the_vocabulary.
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
    msg = str(e.value)
    assert "variety_min" in msg
    assert "ReelManifest.variety_min" in msg
    # variety_min is NOT authored in the EDL: it occurs nowhere in edl.py or edl_to_reel.py
    # and the only inlet is EPISODES.json's key (design §0.4/§0.6). The assertion above
    # cannot tell the corrected message from the false one, which contained the same
    # symbol ("...carried to the gate as ReelManifest.variety_min"), so the true inlet is
    # pinned and the false home is refused outright.
    assert "EPISODES.json" in msg
    assert "EDL" not in msg


def test_an_entry_that_is_a_bare_number_is_refused():
    with pytest.raises(ValueError, match="value.*why|why.*value"):
        gates.Gates.from_dict({"entropy_floor": 0.85})


@pytest.mark.parametrize("why", [None, "", "   ", 7])
def test_a_value_without_a_written_reason_is_refused(why):
    # Design §1: the reason is structurally required, not conventionally expected.
    with pytest.raises(ValueError, match="non-empty") as e:
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
    with pytest.raises(ValueError, match="delete the file") as e:
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


@pytest.mark.parametrize("entry, needle", [
    ({"value": 0.85}, "needs a non-empty 'why'"),                       # the reason is MISSING
    ({"value": 0.85, "whyy": "typo"}, "whyy"),                          # ...or misspelt
    ({"why": "log profile"}, "exactly the keys 'value' and 'why'"),     # the value is missing
    ({"value": 0.85, "why": "log profile", "note": "x"}, "note"),       # a key the schema lacks
    ([0.85, "log profile"], "A bare value is refused"),
    ("0.85", "A bare value is refused"),
    (None, "A bare value is refused"),
], ids=["no-why", "typo-key", "no-value", "extra-key", "list", "string", "null"])
def test_an_entry_that_is_not_exactly_value_and_why_is_refused(entry, needle):
    # Design §2.2.4/§2.2.5: a MISSING why is a refusal of its own, distinct from a blank
    # one. Without it an entry lacking the key would reach entry["why"] and escape as a
    # bare KeyError, and a misspelt key ("whyy") would be dropped without a word. Each
    # shape gets the message that is TRUE of it: an object was once told "a bare number
    # is refused", and the remedy clauses are pinned so deleting one cannot go unnoticed.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"entropy_floor": entry})
    msg = str(e.value)
    assert "entropy_floor" in msg and needle in msg
    if isinstance(entry, dict):
        assert "bare" not in msg                                # an object is not a bare anything
    else:
        assert "what this file exists to prevent" in msg        # the tail's reason clause


@pytest.mark.parametrize("name", sorted(gates.AUTHORED_ELSEWHERE))
def test_every_name_authored_elsewhere_is_refused_not_ignored(name):
    # Design §0.6: five names, each authored somewhere else. A value silently dropped
    # here would READ as authored, so each is refused, the refusal says where, and it says
    # what to DO: a reader told only where a value lives still has to work out that the
    # line in this file is the thing to delete.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({name: {"value": 1, "why": "x"}})
    msg = str(e.value)
    assert name in msg
    assert gates.AUTHORED_ELSEWHERE[name] in msg
    assert f"Remove the {name!r} entry from GATES.json" in msg


@pytest.mark.parametrize("doc", [
    [1],                                                    # not an object
    {"entrpy_floor": {"value": 0.85, "why": "typo"}},       # not a threshold
    {"variety_min": {"value": 4, "why": "short reel"}},     # authored elsewhere
    {"entropy_floor": 0.85},                                # a bare number
    {"entropy_floor": {"value": 0.85, "why": "  "}},        # a blank reason
    {"entropy_floor": {"why": "no value"}},                 # the wrong keys
    {"entropy_floor": {"value": 1.5, "why": "louder"}},     # the owning class refuses
], ids=["not-object", "unknown", "elsewhere", "bare", "blank-why", "wrong-keys",
        "owner-refuses"])
def test_every_refusal_names_where_the_document_came_from(doc):
    # ReelManifest.from_dict re-validates the block it carries under its own label
    # (design §2.3), so `where` has to reach EVERY refusal message, not only the first.
    # Each message OPENS with it: a reader learns which document to fix before why. That is
    # asserted as a prefix, not a substring — the authored-elsewhere message names `where` a
    # second time in its remedy, and an `in` check let that mask a first mention that was lost.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict(doc, where="ReelManifest.gates")
    assert str(e.value).startswith("ReelManifest.gates ")


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


def _probe(body: str) -> subprocess.CompletedProcess:
    """Run `body` in a FRESH interpreter at the repo root.

    For the checks that need `models` altered BEFORE gates is first imported. A fresh
    process rather than importlib.reload, because a reload mints new Gate/Gates classes
    and leaves every module that already holds the old ones comparing unequal to them.
    """
    return subprocess.run([sys.executable, "-c", textwrap.dedent(body)],
                          capture_output=True, text=True, cwd=ROOT)


def test_a_threshold_or_an_advisory_check_added_upstream_reaches_the_vocabulary():
    # The two DERIVED claims, made observable, for BOTH spec classes. `set(FIELDS) ==
    # names - ELSEWHERE` cannot fail for a correct hand-typed list: it recomputes the same
    # thing, so a tuple of twelve literals passes it today and rots the day a thirteenth
    # lands. Here the INPUTS move instead: a fresh interpreter widens ReelCheckSpec AND
    # CheckSpec by one field each, and the advisory registry by one check, BEFORE importing
    # gates, and the module has to follow all three. Widening only one class let a vocabulary
    # whose other half was hand-typed pass every test (measured, fix round 1).
    run = _probe("""
        import dataclasses, json
        from scripts.lib import models

        @dataclasses.dataclass
        class WidenedReel(models.ReelCheckSpec):
            extra_tol: float = 1.0

        @dataclasses.dataclass
        class WidenedEpisode(models.CheckSpec):
            extra_floor: float = 1.0

        models.ReelCheckSpec = WidenedReel
        models.CheckSpec = WidenedEpisode
        models._ADVISORY_CHECKS = models._ADVISORY_CHECKS + ("loudness",)
        from scripts.lib import gates
        print(json.dumps({"fields": list(gates.FIELDS),
                          "blocking": sorted(gates.BLOCKING)}))
    """)
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout)
    assert "extra_tol" in seen["fields"]                       # the ReelCheckSpec half follows
    assert "extra_floor" in seen["fields"]                     # ...and the CheckSpec half
    assert "loudness_target" not in seen["blocking"]           # BLOCKING follows the registry
    assert "loudness_tol" not in seen["blocking"]
    assert "grade_residual_max" in seen["blocking"]            # ...and only what moved


def test_a_name_on_both_spec_classes_has_no_single_owner_and_the_import_fails_loud():
    # `target_dur` is the one name both classes carry, and it is exempt. A second shared
    # name that is NOT exempt would resolve to whichever class the ownership loop visits
    # last, and a gate for it would silently reach only that one. Cannot happen today; the
    # loop is where the invariant belongs, so it raises the day it could.
    run = _probe("""
        import dataclasses
        from scripts.lib import models

        @dataclasses.dataclass
        class WidenedReel(models.ReelCheckSpec):
            black_floor: float = 6.0                 # ALSO a CheckSpec field, and not exempt

        models.ReelCheckSpec = WidenedReel
        from scripts.lib import gates
    """)
    assert run.returncode != 0
    assert "ValueError" in run.stderr
    for needle in ("black_floor", "WidenedReel", "CheckSpec", "AUTHORED_ELSEWHERE"):
        assert needle in run.stderr, run.stderr


# ---- The three invariants that lived in comments (fix round 1, M1) ------------------------


def test_every_probe_base_key_is_authored_elsewhere():
    # The probe base is the minimum a spec needs before an authored value reaches its own
    # __post_init__. A GATEABLE name smuggled into it (say clip_tol: 0.3) would silently
    # change the default that record() reports for that field, on every run.
    for cls, base in gates._PROBE_BASE.items():
        assert set(base) <= set(gates.AUTHORED_ELSEWHERE), (cls.__name__, sorted(base))


def test_every_name_authored_elsewhere_is_a_real_spec_field():
    # A ghost name here would be refused by name while meaning nothing: it would say
    # "authored elsewhere" about a field neither class carries.
    real = {f.name for f in dc_fields(ReelCheckSpec)} | {f.name for f in dc_fields(CheckSpec)}
    assert set(gates.AUTHORED_ELSEWHERE) <= real


@pytest.mark.parametrize("name", gates.FIELDS)
def test_the_record_reports_the_owning_dataclass_default_for_every_gateable_field(name):
    # The default is read here off the dataclass FIELD, not through the module's own
    # _DEFAULTS, so a probe base that moved it cannot move this side of the comparison too.
    owner, scope = ((ReelCheckSpec, "reel") if name in {f.name for f in dc_fields(ReelCheckSpec)}
                    else (CheckSpec, "episode"))
    default = next(f.default for f in dc_fields(owner) if f.name == name)
    authored = default / 2
    assert authored != default      # the control: else `default` could be read off `value` unseen
    (row,) = gates.Gates.from_dict({name: {"value": authored, "why": "x"}}).record()
    assert row == {"field": name, "value": authored, "default": default,
                   "scope": scope, "blocking": name in gates.BLOCKING, "why": "x"}


# ---- The check names OF_CHECK asserts, against the drivers that write them (M2) -----------


def _checks_written(driver: str) -> set[str]:
    """Every literal key `scripts/<driver>` assigns into its `checks` dict."""
    tree = ast.parse((ROOT / "scripts" / driver).read_text())
    return {t.slice.value
            for node in ast.walk(tree) if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
            and t.value.id == "checks" and isinstance(t.slice, ast.Constant)
            and isinstance(t.slice.value, str)}


@pytest.mark.parametrize("field", sorted(gates.OF_CHECK))
def test_every_check_of_check_names_is_written_by_the_driver_of_its_scope(field):
    # For an episode-scope field the check's NAME does not feed BLOCKING at all (only a reel
    # registry exists), so it is documentation, and documentation rots: the first draft named
    # `black` — a REEL check that reads no threshold — for the episode gate `black_frames`,
    # and every test stayed green. Checked here against the driver that owns the scope.
    reel = field in {f.name for f in dc_fields(ReelCheckSpec)}
    driver = "check_reel.py" if reel else "check_episode.py"
    written = _checks_written(driver)
    assert written, f"found no `checks[...] =` assignment in {driver}: this scan is vacuous"
    assert gates.OF_CHECK[field] in written, (
        f"{field} -> {gates.OF_CHECK[field]!r}, but {driver} writes only {sorted(written)}")


# ---- for_spec refuses a class that owns no gate (M5) ---------------------------------------


@pytest.mark.parametrize("not_a_spec", [dict, gates.Gate, ReelCheckSpec(target_dur=1.0), None,
                                        "CheckSpec"],
                         ids=["dict", "Gate", "an-instance", "None", "a-name"])
def test_for_spec_refuses_anything_but_the_two_spec_classes(not_a_spec):
    # Any other class owns none of the gates, so it would get {} in silence and every
    # authored bar would be dropped without a word. An INSTANCE is unhashable (a dataclass
    # with eq and no frozen), so the guard must ask "is this a class" before it looks one up.
    g = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "x"}})
    with pytest.raises(ValueError, match="ReelCheckSpec or CheckSpec"):
        g.for_spec(not_a_spec)
