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
# every skill description leads with one of these role tags (2026-08-01, widened
# 2026-09-12 rederivable-purpose): the lead says HOW you reach the skill, not a
# design §5.x stage number (run order != §5.x, and two skills have no number — the
# number limped, so it is gone from descriptions). "Per-episode worker —" joined
# the set 2026-09-12: process-episode is a toolindex.SKILL_ROLES worker, not a
# stage, so its lead now names that directly instead of borrowing "Conveyor stage".
# "Music lane —" joined the same day: music-match/music-source are the two lanes
# of the one music-and-mood stage, and the tag names that instead of leaving them
# with no lead at all.
ROLE_LEADS = ("Start here —", "Router —", "Conveyor stage", "Preflight —",
              "Per-episode worker —", "Music lane —")


def skill_names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


def skill_pages(name: str, root: Path = REPO) -> list[Path]:
    """The reference pages a skill OWNS — `references/<skill name>/**/*.md`.

    Ownership is the directory name, not a list: a page belongs to a skill iff
    it lives in a directory named after it. The four repo-level references
    (`editing-canon`, `ffmpeg-recipes`, `landmines`, the generated `tools`) are
    shared documents of a different kind and are deliberately NOT skill pages —
    `tools.md` carries a maintainer regeneration command that the bans below
    would (correctly, for a skill) refuse."""
    base = root / "references" / name
    return sorted(base.rglob("*.md")) if base.is_dir() else []


def skill_docs(name: str) -> list[Path]:
    """Everything an agent reads when it works this skill: the body, then its
    pages. Every glob-based ban and presence check below runs over THIS, never
    over `SKILL.md` alone — otherwise moving a paragraph to a page moves it out
    from under its own check (design 2026-09-14 §2.2)."""
    return [SKILLS / name / "SKILL.md"] + skill_pages(name)


def all_skill_docs() -> list[Path]:
    return sorted(p for name in skill_names() for p in skill_docs(name))


def skill_text(name: str) -> str:
    return "\n".join(p.read_text() for p in skill_docs(name))


def test_no_skill_invokes_a_bare_venv_python():
    offenders = sorted(str(p.relative_to(REPO)) for p in all_skill_docs()
                       if ".venv/bin/python" in p.read_text())
    assert offenders == [], f"skills bypassing bin/vg: {offenders}"


PREAMBLE = """\
**Launcher and references.** Run every pipeline step through the repo's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. `setup.sh` records the runtime's location at
`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so resolve it once:

    ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"
    VG="$ROOT/bin/vg"

Then run every step as `"$VG" scripts.X`, read every reference as
`"$ROOT/references/…"`, and pass **absolute** paths for every footage / run /
output directory. Nothing here is relative to your working directory — a skill
runs from the user's footage project, not from the clone. If that file is
missing, the user has not run `bash setup.sh` — stop and say so rather than
guessing a path."""

# Command spellings a skill must never contain. The first is the bypass the
# packaging design closed; the second is what the first failed to catch — the
# guard tested one literal and eleven `python -m scripts.X` examples walked
# past it, seven of them in edit-plan and one each in footage-intake,
# reel-brief, reel-review and titles, whose CLI is the reason the cd into the
# clone is mandatory at all (ultralytics writes YOLO weights into the working
# directory). The third is what the second still missed, found in review: a
# bare `python -c` snippet importing `scripts` directly needs the clone cwd
# exactly as much as a `-m scripts.X` run does, and the brief's own table —
# built from a grep for one spelling — walked past the two sites that use it
# (edit-plan, reel-review). Design 2026-09-14 §0.4.
BANNED_SPELLINGS = (".venv/bin/python", "python -m scripts", "python -c")


def test_no_skill_spells_a_command_it_cannot_resolve():
    offenders = sorted(f"{p.relative_to(REPO)}: {spell}"
                       for p in all_skill_docs()
                       for spell in BANNED_SPELLINGS
                       if spell in p.read_text())
    assert offenders == [], (
        f"{len(offenders)} command(s) anchored to a working directory nobody "
        f"guarantees: {offenders}. Use \"$VG\" scripts.X — see PREAMBLE")


def test_every_skill_carries_the_resolution_preamble():
    """All fourteen, not the seven `RUNNERS` used to name.

    Every skill names at least one path it cannot resolve without this block:
    all fourteen carry `Tool index: references/tools.md.` in their description,
    which the previous slice made resident and this one makes reachable."""
    missing = sorted(n for n in skill_names()
                     if PREAMBLE not in (SKILLS / n / "SKILL.md").read_text())
    assert missing == [], f"skills without the resolution preamble: {missing}"


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
    worker / Music lane), so a reader sees at a glance what to run and what the
    conveyor drives. Guards against drift -- every skill is checked, none
    exempted. A description containing ": " is a double-quoted YAML scalar
    (2026-09-12), so the bounding quote is stripped before comparing, never the
    mandated colon inside it."""
    offenders = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
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
                     if f.name not in skill_text("edit-plan"))
    assert missing == [], (
        f"{len(missing)} EDLEpisode field(s) the authoring skill never names: "
        f"{missing}. Document them in skills/edit-plan/SKILL.md or one of its "
        f"references/edit-plan/ pages — an authorable knob nobody can find is "
        f"the same as one that does not exist")


def test_no_skill_spells_a_stage_artifact_outside_its_bucket():
    """The layout had 74 `<run>` strings across nine SKILL.md files and no authority
    (design §4). A skill writing <run>/EDL.json now writes somewhere the router does
    not look, so the stage would re-run forever."""
    from scripts import montage
    offenders = []
    for path in sorted(all_skill_docs()):
        text = path.read_text()
        for st in montage.V1_STAGES:
            if st.bucket == "run":
                continue
            if f"<run>/{st.artifact}" in text:
                offenders.append(f"{path.relative_to(REPO)}: <run>/{st.artifact}")
    assert offenders == []


def test_no_skill_still_names_the_retired_out_dir():
    """`<run>/out` was the deliveries dir the workflow rm -rf'd 47 times."""
    offenders = sorted(str(p.relative_to(REPO)) for p in all_skill_docs()
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
    conveyor is driven from.

    Reads the skill AND its pages (design 2026-09-14 §2.2): the `reel` row's
    citation `<run>/reels/<reel>/EDL.json` first appears at line 228 today,
    inside a stage block that becomes a page — on `SKILL.md` alone this test
    would start failing the moment the split lands, for no real reason."""
    from scripts.lib import runlayout
    spelling = {"footage": "<run>/footage/", "music": "<run>/music/",
                "reel": "<run>/reels/<reel>/EDL.json",
                "episodes": "<run>/reels/<reel>/episodes/",
                "deliveries": "<run>/reels/<reel>/deliveries/",
                "build": "<run>/reels/<reel>/build/"}
    assert set(spelling) == set(runlayout.BUCKETS) - {"run"}
    text = skill_text("using-montage")
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
    for path in sorted(all_skill_docs()):
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


def test_skill_pages_finds_a_page_and_ignores_the_shared_references(tmp_path):
    """Discriminating TODAY, which the sibling test below is not.

    `references/<name>/` is empty until the split lands, so a `skill_pages()`
    hardcoded to `return []` would satisfy every other assertion in this module
    — including the one about reaching pages. Planting a tree is the only way
    to prove the reaching half before there is anything real to reach."""
    (tmp_path / "references" / "edit-plan").mkdir(parents=True)
    (tmp_path / "references" / "edit-plan" / "episode-fields.md").write_text("x")
    (tmp_path / "references" / "editing-canon.md").write_text("x")
    assert [p.name for p in skill_pages("edit-plan", root=tmp_path)] == ["episode-fields.md"]
    assert skill_pages("titles", root=tmp_path) == []


def test_skill_docs_never_reaches_a_shared_reference():
    """`references/<name>/` is skill-owned; the four repo-level references
    (`editing-canon`, `ffmpeg-recipes`, `landmines`, the generated `tools`) are
    a different kind of document and must never be pulled under a skill's own
    bans by accident — a glob one character wider (`references/*.md` instead of
    `references/<name>/**/*.md`) would do exactly that.

    This proves only that the shared four stay OUT of `all_skill_docs()`; it
    does not prove real pages get IN — `skill_pages` hardcoded to always
    return `[]` would pass this assertion just as well. That half is proven
    separately, against a planted tree, by
    test_skill_pages_finds_a_page_and_ignores_the_shared_references above."""
    shared = {"editing-canon.md", "ffmpeg-recipes.md", "landmines.md", "tools.md"}
    reached = {p.name for p in all_skill_docs()}
    assert reached & shared == set(), (
        f"skill_docs() reached a shared repo-level reference: {reached & shared}")


def test_every_live_stage_has_a_router_page():
    """Set equality with the registry, both directions, no exemption list.

    This is the check the drift would have failed: `reel-review` is required
    and had no block of its own, living inside the deliver block below
    Checkpoint 3 (design 2026-09-14 §0.5)."""
    from scripts import montage
    keys = {s.key for s in montage.V1_STAGES if s.kind != "deferred"}
    pages = {p.stem for p in (REPO / "references/using-montage").glob("*.md")}
    assert pages == keys, (
        f"pages without a stage: {sorted(pages - keys)}; "
        f"stages without a page: {sorted(keys - pages)}")


_STUB = re.compile(r"^(\d+)\. \*\*([a-z][a-z-]*)\*\* — ")


def test_the_router_stubs_are_the_table_s_stages_in_order():
    """The generated table owns the set, the order and the numbers; the stubs
    own the commands. This is the only thing binding the two, which is why it
    asserts the whole list at once rather than membership: a stub pair that
    swapped places is exactly the failure a membership check cannot see."""
    from scripts.lib import toolindex
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    found = [(int(m.group(1)), m.group(2)) for m in
             (_STUB.match(l) for l in text.splitlines()) if m]
    assert found == [(n, s.key) for n, s in toolindex.stage_steps()]


def test_every_router_stub_points_at_its_own_page():
    """A stub without its pointer is a page nobody reaches."""
    from scripts.lib import toolindex
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    missing = [s.key for _, s in toolindex.stage_steps()
               if f"{toolindex.ROUTER_PAGES}/{s.key}.md" not in text]
    assert missing == [], f"stubs with no pointer to their page: {missing}"
