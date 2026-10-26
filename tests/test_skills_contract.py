"""The judge templates must state the contract their dataclass validates.

R10.7: `suggestion` was hard-gated by EpisodeFinding and appeared in
skills/episode-qc/episode-reviewer.md only as a placeholder inside the output JSON
example, never in the Rules block that enumerates the other four fields. A judge
learns the shape from the Rules, spends its whole budget, and is rejected after it
has exited. Nothing machine-checked the template against the dataclass; this does.

R10.6/R10.7 recurred verbatim in skills/reel-review/reel-reviewer.md — the OTHER judge
template, whose contract is scripts/lib/review.py's Finding, gated on the same six
fields as EpisodeFinding (design 2026-09-08 §0.5/§6, task 1). This module now checks
BOTH templates against their own dataclass, so neither can drift again unnoticed."""
import re
from dataclasses import fields
from pathlib import Path

import pytest

from scripts.lib.episode_qc import QC_AXES, EpisodeFinding
from scripts.lib.review import REVIEW_AXES, Finding
from scripts.lib import toolindex

ROOT = Path(__file__).resolve().parents[1]

# (template, its Finding dataclass, its axes tuple, the Rules-block start/end markers
# for THAT file). Both templates share the same section headings today, but each row
# names its own markers rather than assuming that stays true forever — a marker that
# silently stopped matching would make _rules_block slice the wrong region, and the
# test would keep passing over text that says nothing (design 2026-09-08 task 1c).
CASES = [
    pytest.param(ROOT / "skills/episode-qc/episode-reviewer.md", EpisodeFinding, QC_AXES,
                "## Rules", "## Write your output", id="episode-reviewer"),
    pytest.param(ROOT / "skills/reel-review/reel-reviewer.md", Finding, REVIEW_AXES,
                "## Rules", "## Write your output", id="reel-reviewer"),
]


def _rules_block(template: Path, start: str, end: str) -> str:
    text = template.read_text()
    assert text.count(start) == 1, f"{template.name}: {start!r} must occur exactly once"
    assert text.count(end) == 1, f"{template.name}: {end!r} must occur exactly once"
    return text[text.index(start):text.index(end)]


@pytest.mark.parametrize("template,finding_cls,axes,start,end", CASES)
def test_every_gated_finding_field_is_named_in_the_rules_block(template, finding_cls, axes,
                                                                start, end):
    rules = _rules_block(template, start, end)
    # `\bname\b`, not backtick-wrapped: episode-reviewer.md writes field names in
    # backticks ("`axis`"), reel-reviewer.md writes them bare ("axis ∈ ..."), and a
    # backtick is a non-word character, so the SAME word-boundary regex matches the
    # name inside either style — one check, not a second marker style to keep in sync.
    missing = [f.name for f in fields(finding_cls) if not re.search(rf"\b{f.name}\b", rules)]
    assert missing == [], (
        f"{missing} are validated by {finding_cls.__name__} but not named in "
        f"{template.name}'s Rules block — a judge cannot satisfy a gate it was "
        f"never told about")


@pytest.mark.parametrize("template,finding_cls,axes,start,end", CASES)
def test_the_axes_are_named_in_the_rules_block(template, finding_cls, axes, start, end):
    rules = _rules_block(template, start, end)
    assert all(a in rules for a in axes)


def test_the_template_names_the_extraction_tool():
    # Six of eight judges on the real run pulled their own full-resolution frames;
    # one hit `magick not found`. contact_sheet strip does exactly that (design §0.3).
    # episode-reviewer.md only: reel-reviewer.md has no equivalent instruction, and
    # inventing one is out of scope (design 2026-09-08 task 1c).
    text = (ROOT / "skills/episode-qc/episode-reviewer.md").read_text()
    assert "scripts.contact_sheet strip" in text
    assert "$VG" in text


SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
POINTER = "Tool index: references/tools.md."


def _description(path: Path) -> str:
    m = re.search(r"^description:\s*(.+)$", path.read_text(), re.M)
    assert m, f"{path} has no description: line"
    return m.group(1)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_every_skill_points_at_the_tool_index(skill):
    """The one rung always in context. A tool an agent has not already thought
    of is unreachable from --help, which requires typing its name first."""
    assert POINTER in _description(skill), (
        f"{skill.parent.name}'s description does not carry {POINTER!r} — the "
        f"index is only reachable from a surface that survives a compaction")


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_every_skill_states_its_conveyor_place(skill):
    """A stage skill carries its generated position; a non-stage skill says
    what it is instead. Inventing a predecessor for verify-runtime would be
    worse than omitting one (design §0.7)."""
    name, desc = skill.parent.name, _description(skill)
    if name in toolindex.SKILL_ROLES:
        role = toolindex.SKILL_ROLES[name]
        # Case-insensitive: a role that opens a sentence is capitalised there
        # ("Serves the music-and-mood stage.") and lowercase in the table.
        assert role.lower() in desc.lower(), (
            f"{name} is not a conveyor stage; its description must say what it "
            f"is instead: {role!r}")
    else:
        assert toolindex.position(name) in desc, (
            f"{name}'s description does not carry its generated position "
            f"sentence verbatim: {toolindex.position(name)!r}")


def test_the_router_carries_the_generated_chain():
    desc = _description(ROOT / "skills/using-montage/SKILL.md")
    assert toolindex.chain() in desc, (
        f"using-montage's description does not carry the chain rendered from "
        f"V1_STAGES: {toolindex.chain()!r}")


def test_the_judge_is_told_every_intent_key_the_packet_carries(tmp_path):
    """The intent header lists what the judge will find in {INTENT}; a key the packet
    carries and the header never names is one the judge reads without a word on what it
    means. Derived from episode_qc._evidence itself, so a key added there and not here
    turns this red (final review I3: `freeze` reached neither)."""
    from scripts import episode_qc
    from scripts.lib.models import ReelEpisode
    (tmp_path / "ep0").mkdir()
    clip = tmp_path / "ep0.mp4"
    clip.write_bytes(b"x")
    ep = ReelEpisode(manifest={"segment": "s.mp4"}, clip=str(clip),
                     path=str(tmp_path / "ep0" / "path.json"),
                     meta=str(tmp_path / "ep0" / "path.meta.json"))
    keys = episode_qc._evidence(ep, 0, {}, {"strip": "s.jpg", "cell_px": [1, 1]},
                                (1, 1))["intent"]
    text = (ROOT / "skills/episode-qc/episode-reviewer.md").read_text()
    header = text[text.index("## This episode's declared intent"):text.index("{INTENT}")]
    assert [k for k in keys if not re.search(rf"\b{k}\b", header)] == []


def test_the_judge_and_the_skill_say_what_a_freeze_is():
    # a correct freeze is a strip of one frame and a clip with no flash — read without
    # this as a stalled render, filed blocking, and refused with no waiver (final review I3)
    judge = (ROOT / "skills/episode-qc/episode-reviewer.md").read_text()
    skill = (ROOT / "skills/episode-qc/SKILL.md").read_text()
    for text in (judge, skill):
        assert "intent.freeze" in text and "intent.shutter" in text
        assert "not judgeable" in text.lower()
        # nothing re-renders a freeze, so its composition finding must not route to the
        # stage that re-renders (final re-review m2)
        flat = " ".join(text.split())
        assert "composition finding on it" in flat and "routes `edit-plan`" in flat
        assert "neither ever routes `reprocess`" in flat or "neither routes `reprocess`" in flat
