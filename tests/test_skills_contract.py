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
