from pathlib import Path

SKILL = Path(__file__).parent.parent.parent / "SKILLS" / "project-init" / "SKILL.md"


def test_skill_frontmatter_and_shape():
    text = SKILL.read_text()
    assert text.startswith("---")
    assert "name: project-init" in text
    assert "description:" in text
    # points at the deterministic writer, not hand-authoring
    assert "scripts.project_init" in text
    # names the two questions it must ask
    assert "purpose" in text.lower() and "delivery" in text.lower()
    # native-default principle is stated
    assert "native" in text.lower()
