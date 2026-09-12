"""Skill launch convention (design 2026-07-22 §2.5).

Every pipeline command a skill issues must go through bin/vg, never a bare
`.venv/bin/python` (which silently assumes cwd is the checkout — the exact bug
this slice removes). Lints the outcome so a reverted call-site fails loud, and
catches line-wrapped invocations a text-replace would miss.
"""
import dataclasses
import re
from pathlib import Path

from scripts.lib.edl import EDLEpisode

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
# the 7 skills that issue pipeline commands (design §2.5; episode-qc added 2026-08-08)
RUNNERS = {"using-montage", "music-source", "music-match", "pacing",
           "process-episode", "project-init", "episode-qc"}
# every skill description leads with one of these role tags (2026-08-01, widened
# 2026-09-12 rederivable-purpose): the lead says HOW you reach the skill, not a
# design §5.x stage number (run order != §5.x, and two skills have no number — the
# number limped, so it is gone from descriptions). "Per-episode worker —" joined
# the set 2026-09-12: process-episode is a toolindex.SKILL_ROLES worker, not a
# stage, so its lead now names that directly instead of borrowing "Conveyor stage".
ROLE_LEADS = ("Start here —", "Router —", "Conveyor stage", "Preflight —",
              "Per-episode worker —")
# music-match/music-source (2026-09-12): the other two toolindex.SKILL_ROLES
# skills dropped the categorical lead entirely for a plain action opener ("Pick
# the reel's track…" / "Source the reel's track…"); their role ("serves the
# music-and-mood stage") is asserted separately, mid-description, by
# tests/test_skills_contract.py::test_every_skill_states_its_conveyor_place.
_NO_ROLE_LEAD = {"music-match", "music-source"}


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
    conveyor (Start here / Router / Conveyor stage / Preflight / Per-episode
    worker), so a reader sees at a glance what to run and what the conveyor
    drives. Guards against drift. music-match/music-source opted out (see
    _NO_ROLE_LEAD); a description containing ": " is a double-quoted YAML
    scalar (2026-09-12), so the bounding quote is stripped before comparing,
    never the mandated colon inside it."""
    offenders = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        if path.parent.name in _NO_ROLE_LEAD:
            continue
        fm = path.read_text().split("---", 2)[1]
        m = re.search(r"^description:\s*(.+)$", fm, re.M)
        desc = m.group(1).strip().strip('"') if m else ""
        if not desc.startswith(ROLE_LEADS):
            offenders.append(path.parent.name)
    assert offenders == [], (
        f"skills whose description doesn't lead with a role tag {ROLE_LEADS}: "
        f"{offenders}")


def test_edit_plan_skill_names_every_authorable_episode_field():
    """Every EDLEpisode field appears by name in the authoring skill.

    The skill is the ONLY place an author learns a knob exists, and it drifted
    silently once already: five fields were authorable and undocumented until
    2026-08-17 (backlog #5). Proves PRESENCE of the name, never that the
    explanation beside it is correct or current (design 2026-08-17 §2.2) — it
    stops the silent half of the drift, not the whole of it."""
    missing = sorted(f.name for f in dataclasses.fields(EDLEpisode)
                     if f.name not in (SKILLS / "edit-plan" / "SKILL.md").read_text())
    assert missing == [], (
        f"{len(missing)} EDLEpisode field(s) the authoring skill never names: "
        f"{missing}. Document them in skills/edit-plan/SKILL.md — an authorable "
        f"knob nobody can find is the same as one that does not exist")


def test_no_skill_spells_a_stage_artifact_outside_its_bucket():
    """The layout had 74 `<run>` strings across nine SKILL.md files and no authority
    (design §4). A skill writing <run>/EDL.json now writes somewhere the router does
    not look, so the stage would re-run forever."""
    from scripts import montage
    offenders = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        text = path.read_text()
        for st in montage.V1_STAGES:
            if st.bucket == "run":
                continue
            if f"<run>/{st.artifact}" in text:
                offenders.append(f"{path.relative_to(REPO)}: <run>/{st.artifact}")
    assert offenders == []


def test_no_skill_still_names_the_retired_out_dir():
    """`<run>/out` was the deliveries dir the workflow rm -rf'd 47 times."""
    offenders = sorted(str(p.relative_to(REPO)) for p in SKILLS.glob("*/SKILL.md")
                       if "<run>/out" in p.read_text())
    assert offenders == []


def test_using_montage_defines_every_bucket():
    """Nine skills mention <run>; only using-montage defines it (design §4).

    Each bucket has ONE spelling here on purpose: `<run>/reel` would be satisfied
    by the substring of `<run>/reels/`, so the reel row would pass without the
    variant level ever being documented.

    The `reel` row goes further and names a FILE. `<run>/reels/<reel>/` is a string
    prefix of the episodes, deliveries and build spellings, so any one of those three
    would satisfy a bare-directory check for free — and a regression that deleted
    every reel-level citation (EDL.json, SPEC.json, MUSIC.json, PACING.json,
    draft.mp4, TITLES.json) while leaving the child buckets intact would pass
    undetected. EDL.json is the citation to hold: it is the artifact the whole
    conveyor is driven from."""
    from scripts.lib import runlayout
    spelling = {"footage": "<run>/footage/", "music": "<run>/music/",
                "reel": "<run>/reels/<reel>/EDL.json",
                "episodes": "<run>/reels/<reel>/episodes/",
                "deliveries": "<run>/reels/<reel>/deliveries/",
                "build": "<run>/reels/<reel>/build/"}
    assert set(spelling) == set(runlayout.BUCKETS) - {"run"}
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    missing = sorted(b for b, sp in spelling.items() if sp not in text)
    assert missing == []


# Flags whose value is a path INTO the run, so it must be spelled from `<run>`.
# `--source` is deliberately absent: FOOTAGE.json's `source` really is a bare
# filename, resolved against `--footage-root`, and the skills say so.
_RUN_PATH_FLAGS = ("--edl", "--footage", "--selection", "--project", "--cast",
                   "--spec", "--pacing", "--music", "--titles", "--episodes",
                   "--geometry", "--packets", "--out-dir", "--work-dir",
                   "--deliveries-dir", "--scratch-dir", "--findings",
                   "--reel-path", "--out")
_BARE_ARG = re.compile(
    r"(" + "|".join(re.escape(f) for f in _RUN_PATH_FLAGS) + r")\s+"
    r"(?!<)([A-Za-z_][A-Za-z0-9_./-]*\.(?:json|md|mp4|png|jpg)|\.)(?:\s|`|$)")


def test_the_bare_path_pattern_matches_the_shapes_it_was_widened_for():
    """The check below only ever runs against the CURRENT skills tree, so once that
    tree is clean the pattern itself is unpinned: reverting the widening while keeping
    the text fix leaves the suite green. Measured 2026-08-27 by the final re-review —
    the same "fix with no discriminating test" shape the fix wave existed to close.

    The backtick case is not hypothetical: `--out MUSIC.json` sat inside a markdown
    table cell in using-montage, terminated by a backtick rather than whitespace, and
    the original pattern walked past it."""
    hits = lambda line: [m.group(0).strip() for m in _BARE_ARG.finditer(line)]
    assert hits("| a track | `beats ... --out MUSIC.json` -> next |")     # backtick
    assert hits("  --project project.json \\")                            # whitespace
    assert hits("  --out-dir . \\")                                       # bare dot
    assert hits("  --footage some/dir/FOOTAGE.json ")                     # has a dir part
    # and the shapes it must NOT flag
    assert not hits("  --footage <run>/footage/FOOTAGE.json \\")          # already qualified
    assert not hits("  --source MVI_3739.mp4 \\")   # a real bare filename, by design
    assert not hits("  `--pacing --music` together")                      # flag, not a value


def test_no_skill_example_passes_a_bare_path_into_the_run():
    """A flag followed by a bare filename, or `--out-dir .`, worked while a run was
    one flat directory. It cannot work now: an example's inputs span the run root,
    footage/ and reels/<reel>/, so no working directory resolves them all, and the
    drivers have required=True with no defaults to fall back on.

    This is the class the other three checks cannot see — they look for a WRONG
    `<run>/` prefix, and a bare name has no prefix at all. Three such examples
    survived the layout migration precisely because they contained no `<run>`
    string for a reader or a grep to catch on, and one whole skill (reel-brief)
    was never in the migration's file list for the same reason."""
    offenders = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for m in _BARE_ARG.finditer(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}: {m.group(1)} {m.group(2)}")
    assert offenders == []


def test_footage_intake_binds_its_out_dir_to_the_footage_bucket():
    """footage-intake is the one skill that never writes `<run>/` — it speaks
    `<out_dir>` — so all three checks above are blind to it, and it could drift back
    to the run root with nothing noticing. Pointing intake's out_dir at the footage
    bucket is also the WHOLE move for the 93 MB `.intake_cache/`, `cast_crops/` and
    `cast_candidates.json`: `intake_cache._dir` derives them from that one argument
    (design 2026-08-26 §3), so a wrong binding here silently relocates all of it."""
    text = (SKILLS / "footage-intake" / "SKILL.md").read_text()
    assert "<footage_root>/montage/footage" in text
