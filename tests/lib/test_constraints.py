import json

import pytest
from scripts.lib.constraints import Constraints, Rule


def test_rule_round_trips_only_the_fields_its_kind_owns():
    r = Rule(kind="exclude", stated="этот дубль не брать", source="A.mp4", window=7)
    assert r.to_dict() == {"kind": "exclude", "stated": "этот дубль не брать",
                           "source": "A.mp4", "window": 7}
    assert Rule(kind="no_repeat", stated="эпизоды не должны повторяться").to_dict() == {
        "kind": "no_repeat", "stated": "эпизоды не должны повторяться"}


def test_unknown_kind_is_refused_with_the_vocabulary():
    with pytest.raises(ValueError) as ei:
        Rule(kind="no_adjacent", stated="не два дрона подряд")
    assert "no_adjacent" in str(ei.value) and "no_repeat" in str(ei.value)


def test_blank_stated_is_refused():
    with pytest.raises(ValueError, match="stated"):
        Rule(kind="no_repeat", stated="   ")


def test_missing_required_field_is_refused_naming_it():
    with pytest.raises(ValueError, match="hero"):
        Rule(kind="open_with", stated="Serge opens")
    with pytest.raises(ValueError, match="source"):
        Rule(kind="exclude", stated="skip that take")


def test_a_field_that_does_not_belong_to_the_kind_is_refused():
    # A `hero` on an exclude is not a harmless extra: it reads as "exclude this
    # person", which the rule does not do. Refuse rather than ignore.
    with pytest.raises(ValueError, match="no 'hero'"):
        Rule(kind="exclude", stated="skip", source="A.mp4", hero="Serge")


def test_window_must_be_a_non_negative_int():
    with pytest.raises(ValueError, match="window"):
        Rule(kind="exclude", stated="skip", source="A.mp4", window=-1)
    with pytest.raises(ValueError, match="window"):
        Rule(kind="exclude", stated="skip", source="A.mp4", window=True)


def test_constraints_round_trip_through_dict():
    d = {"rules": [{"kind": "no_repeat", "stated": "no repeats"},
                   {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]}
    c = Constraints.from_dict(d)
    assert [r.kind for r in c.rules] == ["no_repeat", "open_with"]
    assert c.to_dict() == d


def test_a_second_singleton_rule_is_refused_as_a_contradiction():
    with pytest.raises(ValueError, match="singleton"):
        Constraints.from_dict({"rules": [
            {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"},
            {"kind": "open_with", "stated": "no, Anna opens", "hero": "Anna"}]})


def test_a_duplicate_exclude_is_refused_but_two_different_ones_are_fine():
    with pytest.raises(ValueError, match="twice"):
        Constraints.from_dict({"rules": [
            {"kind": "exclude", "stated": "skip", "source": "A.mp4", "window": 1},
            {"kind": "exclude", "stated": "skip again", "source": "A.mp4", "window": 1}]})
    c = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip 1", "source": "A.mp4", "window": 1},
        {"kind": "exclude", "stated": "skip 2", "source": "A.mp4", "window": 2},
        {"kind": "exclude", "stated": "skip B", "source": "B.mp4"}]})
    assert len(c.rules) == 3


def test_unknown_json_key_is_refused_with_the_field_help():
    with pytest.raises(ValueError) as ei:
        Constraints.from_dict({"rules": [
            {"kind": "open_with", "stated": "Serge opens", "heroes": "Serge"}]})
    msg = str(ei.value)
    assert "rules[0]" in msg and "open_with: hero" in msg


@pytest.mark.parametrize("body", ['[]', '"str"', '42', 'null', '{"rules": {}}'])
def test_wrong_shaped_file_raises_valueerror_with_a_remedy(tmp_path, body):
    p = tmp_path / "CONSTRAINTS.json"
    p.write_text(body)
    with pytest.raises(ValueError) as ei:
        Constraints.from_json(str(p))
    assert "rules" in str(ei.value)


def test_corrupt_json_names_the_file(tmp_path):
    p = tmp_path / "CONSTRAINTS.json"
    p.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        Constraints.from_json(str(p))


def test_empty_rule_list_is_legal(tmp_path):
    p = tmp_path / "CONSTRAINTS.json"
    p.write_text(json.dumps({"rules": []}))
    assert Constraints.from_json(str(p)).rules == ()
