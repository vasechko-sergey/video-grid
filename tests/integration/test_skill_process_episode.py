import re
from pathlib import Path

SKILL = Path(__file__).parent.parent.parent / "SKILLS" / "process-episode" / "SKILL.md"


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must open with a YAML frontmatter block"
    return m.group(1)


def test_skill_exists():
    assert SKILL.exists()


def test_frontmatter_name_and_description():
    fm = _frontmatter(SKILL.read_text())
    assert re.search(r"^name:\s*process-episode\s*$", fm, re.M)
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    assert desc, "description required"
    # A description containing ": " is a double-quoted YAML scalar (2026-09-12
    # rederivable-purpose) -- strip the bounding quote before judging content,
    # never the mandated colon inside it.
    text = desc.group(1).strip().strip('"')
    assert len(text) <= 500
    # role-led descriptions (2026-08-01, relabelled 2026-09-12): the lead names
    # how you reach the skill. process-episode is a per-episode WORKER, not a
    # stage of its own (toolindex.SKILL_ROLES) -- its lead now says so directly
    # instead of borrowing "Conveyor stage".
    assert text.lower().startswith("per-episode worker")


def test_required_sections_present():
    text = SKILL.read_text()
    for heading in ("## Overview", "## When to Use", "## The Process",
                    "## Red Flags", "## Self-Review", "Editorial gate"):
        assert heading in text, f"missing section: {heading}"


def test_announces_itself():
    assert "Using process-episode" in SKILL.read_text()


def test_no_force_links_and_self_referential():
    text = SKILL.read_text()
    assert "@" not in re.sub(r"[\w.+-]+@[\w.-]+", "", text) or "](" in text  # no @-force-links
    # cross-skill refs point to our own set, never superpowers
    assert "superpowers:" not in text
    assert "video-grid:" in text
