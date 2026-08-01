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
    assert len(desc.group(1)) <= 500
    # role-led descriptions (2026-08-01): the lead names how you reach the skill,
    # not the old "Use when …" opener. process-episode is a conveyor sub-worker.
    assert desc.group(1).lstrip().lower().startswith("conveyor stage")


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
