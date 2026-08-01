# tests/test_verify_runtime_skill.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/verify-runtime/SKILL.md"
UM = ROOT / "skills/using-montage/SKILL.md"


def test_verify_runtime_skill_exists_and_runs_the_cli():
    text = SKILL.read_text()
    assert text.startswith("---")
    assert "name: verify-runtime" in text
    assert "scripts.verify_runtime" in text


def test_using_montage_step0_gates_on_verify_runtime():
    assert "scripts.verify_runtime" in UM.read_text()
