"""Skill launch convention (design 2026-07-22 §2.5).

Every pipeline command a skill issues must go through bin/vg, never a bare
`.venv/bin/python` (which silently assumes cwd is the checkout — the exact bug
this slice removes). Lints the outcome so a reverted call-site fails loud, and
catches line-wrapped invocations a text-replace would miss.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
# the 6 skills that issue pipeline commands (design §2.5)
RUNNERS = {"using-montage", "music-source", "music-match", "pacing",
           "process-episode", "project-init"}


def test_no_skill_invokes_a_bare_venv_python():
    offenders = sorted(str(p.relative_to(REPO)) for p in SKILLS.glob("*/SKILL.md")
                       if ".venv/bin/python" in p.read_text())
    assert offenders == [], f"skills bypassing bin/vg: {offenders}"


def test_the_runner_skills_route_through_bin_vg():
    for name in sorted(RUNNERS):
        text = (SKILLS / name / "SKILL.md").read_text()
        assert "bin/vg" in text, f"{name} lost its bin/vg launcher"


def test_the_runner_skills_read_the_recorded_root():
    """The launcher path must come from setup.sh's recorded root, not from the
    skill's own base directory — the install copies skills to a runtime-less cache,
    so a base-dir-relative launcher (design §2.2, since corrected) would hit the
    broken cache venv. (design 2026-07-22 runtime-resolution §2)"""
    for name in sorted(RUNNERS):
        text = (SKILLS / name / "SKILL.md").read_text()
        assert "video-grid/root" in text, f"{name} does not read the recorded root"
