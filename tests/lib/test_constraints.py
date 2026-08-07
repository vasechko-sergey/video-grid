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


from scripts.lib.constraints import ConstraintReport, Placed, Violation, evaluate
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _footage():
    # A.mp4 has a cut at 10.0: shot [0, 10) and shot [10, 20). Its windows 0 and 1
    # BOTH live in the first shot and do not overlap in time — the repeat a
    # per-window or per-interval comparison misses (design §2).
    return Footage(clips=[
        FootageClip(source="A.mp4", dur=20.0, res=(1920, 1080), fps=30.0, scene_cuts=[10.0],
                    windows=[
                        FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1,
                                      motion=0.3, shake=0.0),
                        FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1,
                                      motion=0.3, shake=0.0),
                        FootageWindow(start=12.0, dur=2.0, shot_type="close", people=1,
                                      motion=0.3, shake=0.0)]),
        FootageClip(source="B.mp4", dur=8.0, res=(1920, 1080), fps=30.0,
                    windows=[FootageWindow(start=1.0, dur=2.0, shot_type="medium", people=1,
                                           motion=0.3, shake=0.0)])])


def _placed(source, shot, hero=None):
    return Placed(source=source, shot=shot, hero=hero)


def test_no_repeat_fires_on_two_episodes_from_one_shot_that_do_not_overlap():
    rules = Constraints.from_dict({"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    placed = (_placed("A.mp4", (0.0, 10.0)), _placed("A.mp4", (0.0, 10.0)))
    rep = evaluate(rules, placed, _footage())
    assert not rep.ok
    assert rep.violations[0].rule_index == 0 and rep.violations[0].kind == "no_repeat"
    assert "episodes 0, 1" in rep.violations[0].message and "A.mp4" in rep.violations[0].message


def test_no_repeat_passes_for_two_different_shots_of_one_clip():
    rules = Constraints.from_dict({"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    placed = (_placed("A.mp4", (0.0, 10.0)), _placed("A.mp4", (10.0, 20.0)))
    rep = evaluate(rules, placed, _footage())
    assert rep.ok and rep.violations == ()
    assert rep.rules == ({"kind": "no_repeat", "stated": "no repeats"},)


def test_bookend_passes_when_the_edge_episode_pins_the_named_hero():
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"},
        {"kind": "close_with", "stated": "Anna closes", "hero": "Anna"}]})
    placed = (_placed("A.mp4", (0.0, 10.0), hero="Serge"),
              _placed("B.mp4", (0.0, 8.0), hero="Anna"))
    assert evaluate(rules, placed, _footage()).ok


def test_bookend_names_the_wrong_hero_it_found():
    rules = Constraints.from_dict({"rules": [
        {"kind": "close_with", "stated": "Anna closes", "hero": "Anna"}]})
    placed = (_placed("A.mp4", (0.0, 10.0), hero="Serge"),
              _placed("B.mp4", (0.0, 8.0), hero="Serge"))
    rep = evaluate(rules, placed, _footage())
    assert not rep.ok and "'Serge'" in rep.violations[0].message and "Anna" in rep.violations[0].message


def test_an_unpinned_edge_episode_is_a_violation_not_a_pass():
    # The S3 lesson, applied here: "cannot tell" must never read as "fine".
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]})
    placed = (_placed("A.mp4", (0.0, 10.0)), _placed("B.mp4", (0.0, 8.0)))
    rep = evaluate(rules, placed, _footage())
    assert not rep.ok
    assert "pins no cast name" in rep.violations[0].message
    assert '"hero": "Serge"' in rep.violations[0].message      # the remedy is mechanical


def test_exclude_bans_one_shot_when_a_window_is_named():
    rules = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "not that take", "source": "A.mp4", "window": 0}]})
    # window 0 starts at 1.0 -> shot [0, 10). An episode from the LATER shot is fine.
    assert evaluate(rules, (_placed("A.mp4", (10.0, 20.0)),), _footage()).ok
    rep = evaluate(rules, (_placed("A.mp4", (0.0, 10.0)),), _footage())
    assert not rep.ok and "0.00s–10.00s" in rep.violations[0].message


def test_exclude_without_a_window_bans_the_whole_clip():
    rules = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip B entirely", "source": "B.mp4"}]})
    assert evaluate(rules, (_placed("A.mp4", (0.0, 10.0)),), _footage()).ok
    rep = evaluate(rules, (_placed("B.mp4", (0.0, 8.0)),), _footage())
    assert not rep.ok and "the whole clip" in rep.violations[0].message


def test_a_stale_exclude_raises_instead_of_enforcing_nothing():
    gone = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip", "source": "GONE.mp4"}]})
    with pytest.raises(ValueError, match="not in FOOTAGE"):
        evaluate(gone, (_placed("A.mp4", (0.0, 10.0)),), _footage())
    oob = Constraints.from_dict({"rules": [
        {"kind": "exclude", "stated": "skip", "source": "B.mp4", "window": 9}]})
    with pytest.raises(ValueError, match="has 1 window"):
        evaluate(oob, (_placed("A.mp4", (0.0, 10.0)),), _footage())


def test_report_round_trips_through_dict():
    rules = Constraints.from_dict({"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    rep = evaluate(rules, (_placed("A.mp4", (0.0, 10.0)), _placed("A.mp4", (0.0, 10.0))),
                   _footage())
    back = ConstraintReport.from_dict(rep.to_dict())
    assert back == rep and not back.ok
    assert isinstance(back.violations[0], Violation)


def test_no_rules_reports_an_empty_ok_report():
    rep = evaluate(Constraints(), (_placed("A.mp4", (0.0, 10.0)),), _footage())
    assert rep.ok and rep.rules == () and rep.violations == ()
