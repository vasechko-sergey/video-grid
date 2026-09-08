"""The judge template must state the contract episode_qc validates.

R10.7: `suggestion` was hard-gated by EpisodeFinding and appeared in
skills/episode-qc/episode-reviewer.md only as a placeholder inside the output JSON
example, never in the Rules block that enumerates the other four fields. A judge
learns the shape from the Rules, spends its whole budget, and is rejected after it
has exited. Nothing machine-checked the template against the dataclass; this does."""
from dataclasses import fields
from pathlib import Path

from scripts.lib.episode_qc import QC_AXES, EpisodeFinding

ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = ROOT / "skills/episode-qc/episode-reviewer.md"


def _rules_block() -> str:
    text = _TEMPLATE.read_text()
    start = text.index("## Rules")
    end = text.index("## Write your output", start)
    return text[start:end]


def test_every_gated_finding_field_is_named_in_the_rules_block():
    rules = _rules_block()
    missing = [f.name for f in fields(EpisodeFinding) if f"`{f.name}`" not in rules]
    assert missing == [], (
        f"{missing} are validated by EpisodeFinding but not named in the template's "
        f"Rules block — a judge cannot satisfy a gate it was never told about")


def test_the_five_axes_are_named_in_the_rules_block():
    rules = _rules_block()
    assert all(a in rules for a in QC_AXES)


def test_the_template_names_the_extraction_tool():
    # Six of eight judges on the real run pulled their own full-resolution frames;
    # one hit `magick not found`. contact_sheet strip does exactly that (design §0.3).
    text = _TEMPLATE.read_text()
    assert "scripts.contact_sheet strip" in text
    assert "$VG" in text
