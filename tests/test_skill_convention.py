"""Skill launch convention (design 2026-07-22 §2.5).

Every pipeline command a skill issues must go through bin/vg, never a bare
`.venv/bin/python` (which silently assumes cwd is the checkout — the exact bug
this slice removes). Lints the outcome so a reverted call-site fails loud, and
catches line-wrapped invocations a text-replace would miss.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
# the 6 skills that issue pipeline commands (design §2.5)
RUNNERS = {"using-montage", "music-source", "music-match", "pacing",
           "process-episode", "project-init"}
# every skill description leads with one of these role tags (2026-08-01): the lead
# says HOW you reach the skill, not a design §5.x stage number (run order != §5.x,
# and two skills have no number — the number limped, so it is gone from descriptions).
ROLE_LEADS = ("Start here —", "Router —", "Conveyor stage", "Preflight —")


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


def test_the_pacing_skill_documents_the_two_pass_flow():
    text = (SKILLS / "pacing" / "SKILL.md").read_text()
    assert "--edl" in text and "--footage" in text
    assert "edit_plan build --pacing" in text, (
        "the fit is APPLIED by re-running edit-plan; a skill that stops at PACING.json "
        "leaves the EDL un-snapped")


def test_using_montage_orders_edit_plan_before_music():
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    assert text.index("edit_plan build") < text.index("scripts.beats")


def test_every_skill_description_leads_with_a_role_tag():
    """Uniform, role-led descriptions: the lead names the skill's place in the
    conveyor (Start here / Router / Conveyor stage / Preflight), so a reader sees
    at a glance what to run and what the conveyor drives. Guards against drift."""
    offenders = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        fm = path.read_text().split("---", 2)[1]
        m = re.search(r"^description:\s*(.+)$", fm, re.M)
        desc = m.group(1).strip() if m else ""
        if not desc.startswith(ROLE_LEADS):
            offenders.append(path.parent.name)
    assert offenders == [], (
        f"skills whose description doesn't lead with a role tag {ROLE_LEADS}: "
        f"{offenders}")
