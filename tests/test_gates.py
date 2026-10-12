"""The authored-gate surface (design 2026-09-30)."""
import ast
import dataclasses
import json
import subprocess
import sys
import textwrap
from dataclasses import fields as dc_fields
from pathlib import Path

import pytest

from scripts import mix
from scripts.lib import gates
from scripts.lib.models import CheckResult, CheckSpec, ReelCheckSpec, _ADVISORY_CHECKS

ROOT = Path(__file__).resolve().parents[1]


def test_the_vocabulary_is_derived_from_the_two_spec_classes_not_typed():
    # The row said twelve; the dataclasses say eleven, because loudness_target is a
    # rendered set-point and not a bar (design §0.2a, §0.6). This test is what fails the
    # day a twelfth threshold lands without a decision about it.
    # Not the derivation's guard: a hand-typed list passes it. The real guard is
    # test_a_threshold_or_an_advisory_check_added_upstream_reaches_the_vocabulary.
    names = {f.name for f in dc_fields(ReelCheckSpec)} | {f.name for f in dc_fields(CheckSpec)}
    assert len(names) == 17
    assert set(gates.FIELDS) == names - set(gates.AUTHORED_ELSEWHERE)
    assert len(gates.FIELDS) == 11


def test_every_gateable_field_names_the_check_it_sets_the_bar_for():
    assert set(gates.OF_CHECK) == set(gates.FIELDS)


def test_the_blocking_set_is_derived_from_the_advisory_registry():
    # Not the derivation's guard: a hand-typed set passes it. The real guard is
    # test_a_threshold_or_an_advisory_check_added_upstream_reaches_the_vocabulary.
    assert gates.BLOCKING == frozenset(
        n for n, c in gates.OF_CHECK.items() if c not in _ADVISORY_CHECKS)
    assert gates.BLOCKING == {"loudness_tol", "grade_residual_max", "length_retime_max",
                              "black_floor", "black_rel", "entropy_floor"}


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


@pytest.mark.parametrize("leak", [OverflowError, TypeError])
def test_a_guard_that_leaks_anything_but_a_value_error_escapes_from_dict_unchanged(
        monkeypatch, leak):
    # from_dict rewords ValueError, and only ValueError, into a message that names the
    # document. Anything else a guard raises is a defect IN THE GUARD (a 400-digit int reaching
    # math.isfinite, a str reaching a `<=`) and has to surface as itself: widen the `except`
    # and it is reworded into a file-naming ValueError that reads as a mistake in the author's
    # file, and the front-door test in tests/lib/test_models.py, which leans on this narrowness,
    # can no longer see a guard that leaks. It takes TWO defects together (a widened except AND
    # a leaking guard) to show, so no single-site mutation of either finds it; that is why the
    # except is pinned here directly instead of being left to the tests that exercise the guards.
    def leaking(self):
        raise leak("a defect in the guard, not a value the author got wrong")

    monkeypatch.setattr(ReelCheckSpec, "__post_init__", leaking)
    with pytest.raises(leak):
        gates.Gates.from_dict({"beat_tol": {"value": 0.08, "why": "x"}})


def test_from_json_names_the_path_it_could_not_load(tmp_path):
    p = tmp_path / "GATES.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="delete the file") as e:
        gates.Gates.from_json(p)
    assert str(p) in str(e.value)
    assert "is not valid JSON" in str(e.value)    # the syntax arm keeps its own wording


def test_a_gates_file_that_is_not_utf8_is_refused_naming_the_path(tmp_path):
    """read_text() raises UnicodeDecodeError on a Latin-1 save of a GATES.json whose `why`
    holds an accented letter, which is a ValueError but not a JSONDecodeError. The loader caught
    only the second, so the run died on a bare codec message that names no file (final review
    M4; filed by Task 1's review)."""
    p = tmp_path / "GATES.json"
    p.write_bytes(b'{"entropy_floor": {"value": 0.85, "why": "caf\xe9 light"}}')
    with pytest.raises(ValueError, match="delete the file") as e:
        gates.Gates.from_json(p)
    assert str(p) in str(e.value)
    assert "utf-8" in str(e.value).lower()
    assert "not valid JSON" not in str(e.value)   # a Latin-1 file is valid JSON in the wrong encoding


def test_an_integer_past_the_digit_limit_is_refused_naming_the_path(tmp_path):
    """json.loads raises a bare ValueError ("Exceeds the limit (4300 digits)...") for a longer
    integer, again not a JSONDecodeError. 400 digits was always clean (is_finite_number refuses
    it and from_dict names the file); 4301 stopped the run naming nothing (final review M4;
    filed by Task 2's review)."""
    p = tmp_path / "GATES.json"
    p.write_text('{"entropy_floor": {"value": ' + "9" * 4301 + ', "why": "x"}}')
    with pytest.raises(ValueError, match="delete the file") as e:
        gates.Gates.from_json(p)
    assert str(p) in str(e.value)
    assert "4300" in str(e.value)
    assert "not valid JSON" not in str(e.value)   # the syntax is fine; the integer is too long


def test_a_loaded_gate_set_cannot_be_changed_after_it_was_loaded():
    """Both dataclasses are frozen, and the property is load-bearing rather than tidy: the set
    is parsed ONCE (build_reel reads rm.gates into `authored` before its retry loop) and then
    read by the check, the report's `authored` rows and the attestation. A mutable set could
    be edited between the judging and the record that binds it. Found by the Task 7 AST sweep:
    dropping `frozen=True` from either class, or flipping it, survived the whole unit tier,
    because nothing ever assigned to a loaded Gate."""
    loaded = gates.Gates.from_dict({"entropy_floor": {"value": 0.85, "why": "log profile"}})
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.gates = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.gates[0].value = 0.1


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


def test_loudness_target_is_refused_and_the_message_names_what_the_stem_is_rendered_to():
    """loudness_target is the value the pipeline RENDERS TO, not a bar a check compares against
    (design §0.2a). mix bakes its own constant into the loudnorm filter and takes no parameter
    for it, so a GATES.json that moved only the gate would fail every reel with audio — and
    the only escape, widening loudness_tol, is a waiver wearing the target's name. The generic
    elsewhere test below proves the refusal fires; this one proves it points at the real home
    and says WHY, which is the part a reader who just tried to author −16 needs."""
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({"loudness_target": {"value": -16, "why": "the platform wants -16"}})
    msg = str(e.value)
    assert "mix._TARGET_LUFS" in msg and "scripts/mix.py" in msg
    assert "RENDERED" in msg and "every reel" in msg
    assert "loudness_target" not in gates.FIELDS        # left the vocabulary, not merely refused


def test_the_home_loudness_target_points_at_is_real_and_is_what_the_gate_confirms():
    """A pointer in a refusal is a claim about the tree, and claims rot: variety_min's was once
    wrong for exactly that reason. There are two constants with one meaning — what mix renders
    to, and what check_reel's default confirms — and the refusal exists because GATES.json could
    have moved only one. Until a platform table sets both from one place (design §7), their
    agreement is pinned here; a rename of mix._TARGET_LUFS also breaks the pointer, loudly."""
    assert mix._TARGET_LUFS == ReelCheckSpec(target_dur=1.0).loudness_target


@pytest.mark.parametrize("name", sorted(gates.AUTHORED_ELSEWHERE))
def test_every_name_authored_elsewhere_is_refused_not_ignored(name):
    # Design §0.6: six names, each authored somewhere else. A value silently dropped
    # here would READ as authored, so each is refused, the refusal says where, and it says
    # what to DO: a reader told only where a value lives still has to work out that the
    # line in this file is the thing to delete.
    with pytest.raises(ValueError) as e:
        gates.Gates.from_dict({name: {"value": 1, "why": "x"}})
    msg = str(e.value)
    assert name in msg
    assert gates.AUTHORED_ELSEWHERE[name] in msg
    assert f"Remove the {name!r} entry from GATES.json" in msg
    # The remedy names the document a second time, so it has to name the RIGHT one: gates
    # that came from an EPISODES.json block must not be told to go and edit a GATES.json
    # that may not exist. Under the default label the two are the same string, so only a
    # custom `where` can tell a remedy that follows it from one that hardcodes it.
    with pytest.raises(ValueError) as e2:
        gates.Gates.from_dict({name: {"value": 1, "why": "x"}}, where="ReelManifest.gates")
    assert f"Remove the {name!r} entry from ReelManifest.gates" in str(e2.value)


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
    # thing, so a tuple of eleven literals passes it today and rots the day a twelfth
    # lands. Here the INPUTS move instead: a fresh interpreter widens ReelCheckSpec AND
    # CheckSpec by one field each, and the advisory registry by one check, BEFORE importing
    # gates, and the module has to follow all three. Widening only one class would let a
    # vocabulary whose other half was hand-typed pass every test (design §0.6: derived, not
    # typed).
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
    assert "loudness_tol" not in seen["blocking"]              # BLOCKING follows the registry
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


# ---- Three invariants the derived vocabulary rests on (design §0.6, §2.4) ------------------


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


# ---- The check names OF_CHECK asserts, against the drivers that write them (design §0.1) ---


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
    # registry exists), so it is documentation, and documentation rots: design §0.1 records
    # that its own first draft named `black` — a REEL check that reads no threshold — for the
    # episode gate `black_frames`, and nothing else would have noticed, since the name cannot
    # change BLOCKING. Checked here against the driver that owns the scope.
    reel = field in {f.name for f in dc_fields(ReelCheckSpec)}
    driver = "check_reel.py" if reel else "check_episode.py"
    written = _checks_written(driver)
    assert written, f"found no `checks[...] =` assignment in {driver}: this scan is vacuous"
    assert gates.OF_CHECK[field] in written, (
        f"{field} -> {gates.OF_CHECK[field]!r}, but {driver} writes only {sorted(written)}")


# ---- for_spec refuses a class that owns no gate (design §2.2: never stores-and-ignores) ----


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


# ---- beside_project: the ONE place the convention is spelled (design §0.5/§2.1) ------------


def test_beside_project_reads_the_file_in_the_projects_own_directory(tmp_path, monkeypatch):
    """Found beside project.json — not in the working directory, which is where a run started
    from the user's footage folder would otherwise look. The decoy in the cwd holds a DIFFERENT
    bar, so a lookup that strays there (or prefers it) reads the wrong file rather than reading
    nothing. The absent-file and broken-file halves of this helper's contract are pinned where
    they are consumed — the three phase-1 arms and the process_episode CLI — because a unit
    test of either here kills no mutation those do not."""
    run, elsewhere = tmp_path / "run", tmp_path / "elsewhere"
    run.mkdir()
    elsewhere.mkdir()
    doc = {"entropy_floor": {"value": 0.85, "why": "log profile"}}
    (run / "GATES.json").write_text(json.dumps(doc))
    (elsewhere / "GATES.json").write_text(json.dumps(
        {"black_floor": {"value": 2.0, "why": "a decoy: the wrong directory"}}))
    monkeypatch.chdir(elsewhere)
    assert gates.beside_project(str(run / "project.json")) == gates.Gates.from_dict(doc)


# ---- naming a moved bar beside the verdict it bought (design §2.4 item 1) --------------------
#
# The row in a check's own detail is {field, value, default, why} and deliberately NOT
# Gates.record()'s {field, value, default, scope, blocking, why}: the check already knows its own
# scope and whether it blocks, and the two answer different questions — what this check judged by
# (only a bar that MOVED), against everything an author wrote (the attestation).


def _judged(*names: str, passed: bool | None = True) -> dict[str, CheckResult]:
    return {n: CheckResult(n, passed, {"probe": 1}) for n in names}


def _authors(fields: dict, why: str = "a reason") -> dict[str, str]:
    return {f: f"{why}: {f}" for f in fields}


def _named(checks: dict[str, CheckResult]) -> dict[str, list[str]]:
    """{check: [the fields its detail names]}, [] for a check that names none."""
    return {n: [r["field"] for r in c.detail.get("authored", [])] for n, c in checks.items()}


def test_every_reel_bar_is_named_on_the_check_that_reads_it():
    """A literal table, typed here on purpose. The code derives the same mapping from OF_CHECK, so
    asserting against OF_CHECK would compare the table with itself; this is the independent copy
    that notices one bar filed under a neighbour (clip_tol under pad_bars reads as a plausible edit
    and moves no BLOCKING answer, since both are advisory). length_retime_max is named on TWO
    checks: `length`, where build_reel's absorb converts a blocking failure into a silent re-target
    (design §0.1), and `brief_length`, whose advisory band borrows the same number."""
    moved = dict(loudness_tol=2.0, grade_residual_max=6.0,
                 chroma_spread_max=8.0, length_retime_max=3.0, beat_tol=0.08, clip_tol=0.05,
                 bar_symmetry_tol=0.05, layout_jump_max=0.9)
    spec = ReelCheckSpec(target_dur=6.0, **moved)
    checks = _judged("loudness", "grade_faithful", "chroma_spread", "length", "brief_length",
                     "beat", "key_action", "pad_bars", "transitions", "black", "variety")
    gates.name_authored(checks, spec, _authors(moved))
    assert _named(checks) == {
        "loudness": ["loudness_tol"],
        "grade_faithful": ["grade_residual_max"],
        "chroma_spread": ["chroma_spread_max"],
        "length": ["length_retime_max"],
        "brief_length": ["length_retime_max"],
        "beat": ["beat_tol"],
        "key_action": ["clip_tol"],
        "pad_bars": ["bar_symmetry_tol"],
        "transitions": ["layout_jump_max"],
        "black": [],            # judges by no threshold
        "variety": [],          # variety_min is authored elsewhere (AUTHORED_ELSEWHERE)
    }


def test_every_episode_bar_is_named_on_the_check_that_reads_it():
    """The same table for the other scope — and a control inside it: check_episode also writes a
    `length` check, which judges by no gate, while a reel gate named `length_retime_max` is authored
    in the same set. Naming it there would put a reel bar on an episode verdict."""
    moved = dict(black_floor=2.0, black_rel=0.2, entropy_floor=0.8)
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=1.0, **moved)
    checks = _judged("black_frames", "grade_damage", "length", "jitter")
    gates.name_authored(checks, spec, _authors({**moved, "length_retime_max": 3.0}))
    assert _named(checks) == {"black_frames": ["black_floor", "black_rel"],
                              "grade_damage": ["entropy_floor"],
                              "length": [], "jitter": []}


def test_a_named_bar_carries_its_value_its_default_and_its_reason():
    spec = ReelCheckSpec(target_dur=6.0, loudness_tol=2.0)
    checks = _judged("loudness")
    gates.name_authored(checks, spec, {"loudness_tol": "live room"})
    assert checks["loudness"].detail == {"probe": 1, "authored": [
        {"field": "loudness_tol", "value": 2.0, "default": 1.0, "why": "live room"}]}


def test_only_a_bar_that_moved_with_a_written_reason_is_named():
    """Both halves of the filter, in one call. `clip_tol` has a reason and sits at its default:
    an author may legally write the default value, and the bar did not move. `beat_tol` moved
    and has no reason: this function names reasons, and a value moved by hand is
    provenance.spec_overrides' business. Only `loudness_tol` moved AND was explained."""
    spec = ReelCheckSpec(target_dur=6.0, loudness_tol=2.0, beat_tol=0.08)
    checks = _judged("loudness", "beat", "key_action")
    gates.name_authored(checks, spec, {"loudness_tol": "live room",
                                       "clip_tol": "pinned at the default on purpose"})
    assert _named(checks) == {"loudness": ["loudness_tol"], "beat": [], "key_action": []}


def test_a_check_that_examined_nothing_does_not_claim_a_bar_it_never_read():
    """passed=None is a not-checked arm. Its detail can carry the bar (grade_faithful's does,
    as `max`), but no verdict was reached by it — so an `authored` row there would read as "this
    bar moved the result" on a check that produced none."""
    spec = ReelCheckSpec(target_dur=6.0, grade_residual_max=6.0)
    checks = _judged("grade_faithful", passed=None)
    gates.name_authored(checks, spec, {"grade_residual_max": "log profile"})
    assert checks["grade_faithful"].detail == {"probe": 1}


def test_naming_a_bar_never_mutates_a_detail_dict_someone_else_holds():
    """check_reel builds a ReelFailure from a copy of the detail it puts on the check, and the
    next edit could share one dict between them. The row goes on a NEW dict, so a failure that
    shares the original keeps the shape it had."""
    shared = {"probe": 1}
    checks = {"loudness": CheckResult("loudness", True, shared)}
    gates.name_authored(checks, ReelCheckSpec(target_dur=6.0, loudness_tol=2.0),
                        {"loudness_tol": "live room"})
    assert shared == {"probe": 1}


@pytest.mark.parametrize("call", [
    lambda spec: gates.authored_rows(spec, {}, "loudness_tol"),
    lambda spec: gates.name_authored({}, spec, {"loudness_tol": "x"}),
], ids=["authored_rows", "name_authored"])
def test_a_value_that_is_not_a_spec_is_refused_not_silently_left_unnamed(call):
    """A spec of any other class owns no gate, so every authored bar would go unnamed in
    silence — the failure for_spec's own refusal exists for. Two callers, because each of the
    two public functions makes its own call to the guard. The `name_authored` case hands it NO
    checks, on purpose: given one, name_authored calls authored_rows, whose guard raises the same
    message first, so a case built with a check present still passed with name_authored's own
    guard deleted. With none, only name_authored's own guard can raise."""
    with pytest.raises(ValueError, match="ReelCheckSpec or CheckSpec"):
        call(object())


def test_a_name_the_spec_does_not_own_is_refused_not_silently_never_reported():
    """A typo, or a reel bar asked of an episode spec. `n in reasons` short-circuits before the
    value is read, so without this the wrong name would simply never appear — a reason lost on
    the exact surface built to carry it."""
    with pytest.raises(ValueError, match="'loudnes_tol'") as typo:
        gates.authored_rows(ReelCheckSpec(target_dur=6.0), {}, "loudnes_tol")
    with pytest.raises(ValueError, match="'loudness_tol'.*CheckSpec") as wrong_scope:
        gates.authored_rows(CheckSpec("lead", "thirds", 1.0), {}, "loudness_tol")
    # The remedy lists the thresholds of the spec's OWN class, so the right spelling is in it for
    # the typo and the episode bars are in it for the reel bar asked of an episode spec. A list
    # drawn from the other class would send the reader to names that are wrong in this scope.
    assert "loudness_tol" in str(typo.value) and "black_floor" not in str(typo.value)
    assert "black_floor" in str(wrong_scope.value) and "beat_tol" not in str(wrong_scope.value)
