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
              "Per-episode worker —", "Music lane —", "Install —")


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
**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty, or `"$VG"` does not exist — a harness that did not fill
the line in — `ROOT` is the directory two levels above this skill's base directory.
Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything."""

# Command spellings a skill must never contain. This is a SET OF SPELLINGS, not
# a predicate for "a command anchored to a working directory nobody guarantees"
# — and the distinction is design 2026-09-14 §0.4's own lesson one level up.
# The first entry is the bypass the packaging design closed; testing for that
# one literal is exactly how eleven `python -m scripts.X` examples walked past
# it — seven in edit-plan and one each in footage-intake, reel-brief,
# reel-review and titles. Of those four, footage-intake is the one whose CLI
# makes the cd into the clone mandatory rather than convenient (ultralytics
# writes YOLO weights into the working directory). Widening to that second
# spelling then found two more in a third, `python -c`, which the brief's own
# one-spelling grep had missed (edit-plan, reel-review) and which `bin/vg`
# could not even run until it learned a `-c` passthrough.
#
# The `python3` and `python scripts/foo.py` rows occur nowhere in the tree
# today. They are here because each is one keystroke from a spelling that did
# occur, and because listing them is the honest shape of this guard: the set
# narrows the gap, it never closes it. A spelling nobody has typed yet still
# walks past.
BANNED_SPELLINGS = (".venv/bin/python",
                    "python -m scripts", "python3 -m scripts",
                    "python -c", "python3 -c",
                    "python scripts/", "python3 scripts/")


def test_no_skill_spells_a_command_it_cannot_resolve():
    offenders = sorted(f"{p.relative_to(REPO)}: {spell}"
                       for p in all_skill_docs()
                       for spell in BANNED_SPELLINGS
                       if spell in p.read_text())
    assert offenders == [], (
        f"{len(offenders)} command(s) anchored to a working directory nobody "
        f"guarantees: {offenders}. Use \"$VG\" scripts.X — see PREAMBLE")


def test_every_skill_carries_the_resolution_preamble():
    """Every skill, not the seven `RUNNERS` used to name.

    Every skill names at least one path it cannot resolve without this block:
    all fourteen carry `Tool index: references/tools.md.` in their description,
    which the previous slice made resident and this one makes reachable."""
    missing = sorted(n for n in skill_names()
                     if PREAMBLE not in (SKILLS / n / "SKILL.md").read_text())
    assert missing == [], f"skills without the resolution preamble: {missing}"


def test_the_preamble_resolves_the_root_the_harness_fills_in():
    """Since 0.27.0 the code runs from the installed plugin itself (design 2026-10-21
    §2): Claude Code fills `${CLAUDE_PLUGIN_ROOT}` into a plugin skill's text when it
    loads it, so the instructions and the code are one version by construction. The
    COMMAND is pinned, once — a prose mention would be filled in too and read as a
    second, contradictory path — and so is the launcher under it."""
    assert PREAMBLE.count("${CLAUDE_PLUGIN_ROOT}") == 1
    assert '    ROOT="${CLAUDE_PLUGIN_ROOT}"\n    VG="$ROOT/bin/vg"' in PREAMBLE
    assert (REPO / "bin" / "vg").is_file()


def test_nothing_reads_the_root_setup_no_longer_records():
    """setup.sh stopped writing ~/.config/video-grid/root in 0.27.0. A skill, a
    reference page or a template still reading it would point at a stale clone, or
    at nothing, while every other check here stays green."""
    readers = sorted(str(p.relative_to(REPO)) for p in all_skill_docs()
                     if "video-grid/root" in p.read_text())
    readers += sorted(str(p.relative_to(REPO)) for p in (REPO / "references").rglob("*.md")
                      if "video-grid/root" in p.read_text())
    readers += sorted(str(p.relative_to(REPO)) for p in (REPO / "skills").rglob("*.md")
                      if "video-grid/root" in p.read_text() and p.name != "SKILL.md")
    assert readers == [], f"still reading the retired root record: {readers}"
    assert '> "$VG_CONFIG/root"' not in (REPO / "setup.sh").read_text()


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

    Reads the skill AND its pages (design 2026-09-14 §2.2) — not because the
    split moved this particular citation. Measured after it landed, all six
    spellings are still resident in the body, `<run>/reels/<reel>/EDL.json`
    three times over, so `SKILL.md` alone would pass today. The reason is that
    a bucket spelling CAN now legitimately live only on a page: reading the
    body alone would make this check depend on where the text happened to land
    rather than on whether the layout is documented at all."""
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
    keys = {s.key for s in montage.V1_STAGES}
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
    """A stub without its pointer is a page nobody reaches.

    Anchored to the `"$ROOT/…"` form the stubs use, NOT to the bare path: the
    byte-pinned table above the stubs already carries
    `references/using-montage/<key>.md` in all fifteen of its `page` cells, so a
    whole-file substring check for the bare path is green by construction —
    deleting every `Before running it, read …` line still leaves it empty
    (measured in review). The table's cells carry no `$ROOT`."""
    from scripts.lib import toolindex
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    missing = [s.key for _, s in toolindex.stage_steps()
               if f'"$ROOT/{toolindex.ROUTER_PAGES}/{s.key}.md"' not in text]
    assert missing == [], f"stubs with no pointer to their page: {missing}"


_REF = re.compile(r"references/[\w/-]+\.md")

#: A body budget, NOT a measurement of anything. It is set from what this slice
#: MEASURED itself landing — using-montage 22 268 bytes, edit-plan 18 340 — with
#: room above the larger of them, because a cap that binds on the day it ships is
#: a cap the next author fights instead of obeys. The design's own projection said
#: 13.5 KB and was wrong by 65%; the number here is the measurement, not the
#: projection. Design §3.5.
BODY_MAX = 26_000


_GENERATED = re.compile(r"<!-- generated:.*?-->(.*?)<!-- /generated -->", re.S)


def _split_generated(text: str) -> tuple[str, str]:
    """(everything outside the generated blocks, everything inside them)."""
    parts = _GENERATED.split(text)
    return "".join(parts[0::2]), "".join(parts[1::2])


def test_every_reference_in_a_skill_body_is_anchored():
    """A bare `references/x.md` is relative to a working directory a skill never
    has (design 2026-09-14 §0.3). The preamble defines `$ROOT`; a pointer that
    does not use it is a path the reader cannot resolve.

    Frontmatter is the one carve-out, and it is structural rather than an
    exemption: a `description:` is a YAML scalar read with no shell to expand a
    variable in, so `Tool index: references/tools.md.` can only ever be a bare
    path. It is what the preamble below it exists to make resolvable.

    The generated stage table is held to a weaker rule rather than exempted.
    Its `page` column is an index of NAMES — its `writes` column names
    `EDL.json` in exactly the same way, and neither is a path anyone is told to
    open; the instruction actually followed is the stub's `Before running it,
    read "$ROOT/…"` line beneath it. So every path the table names must appear
    anchored somewhere else in the same document. That is the guarantee the
    bare cells would otherwise drop, and it is why the block can stay
    byte-pinned to `toolindex.render_stages()` without a hole opening under it.

    The four shared repo-level references are out of scope here for the reason
    `skill_pages` gives: they are not skill documents. `references/tools.md`
    carries a bare pointer of its own (design §5)."""
    bare, unbacked = [], []
    for p in all_skill_docs():
        text = p.read_text()
        if p.name == "SKILL.md":
            text = text.split("---", 2)[2]
        outside, generated = _split_generated(text)
        anchored = set()
        for m in _REF.finditer(outside):
            if outside[max(0, m.start() - 6):m.start()] == "$ROOT/":
                anchored.add(m.group(0))
            else:
                bare.append(f"{p.relative_to(REPO)}: {m.group(0)}")
        unbacked += [f"{p.relative_to(REPO)}: {ref}"
                     for ref in _REF.findall(generated) if ref not in anchored]
    assert bare == [], (
        f"{len(bare)} unanchored reference pointer(s): {bare}. Write them as "
        f'`"$ROOT/references/….md"` — see PREAMBLE')
    assert unbacked == [], (
        f"{len(unbacked)} path(s) named only inside a generated block, with no "
        f"anchored pointer anywhere else in the same file: {unbacked}")


def test_every_reference_a_skill_names_exists():
    """Nineteen bare `references/…` pointers existed with no rule anywhere for
    resolving them (design §0.3) — fourteen frontmatter, five prose. The
    preamble supplies the rule; this supplies the other half — that the thing
    at the end of the path is there."""
    missing = sorted({f"{p.relative_to(REPO)} -> {ref}"
                      for p in all_skill_docs()
                      for ref in _REF.findall(p.read_text())
                      if not (REPO / ref).is_file()})
    assert missing == [], f"{len(missing)} reference(s) naming no file: {missing}"


def test_no_reference_file_is_orphaned():
    """The §0.3 failure in its other direction: a page nothing names is a page
    nothing reaches, and it rots without ever failing anything."""
    named = {ref for p in all_skill_docs() for ref in _REF.findall(p.read_text())}
    orphans = sorted(str(p.relative_to(REPO)) for p in (REPO / "references").rglob("*.md")
                     if str(p.relative_to(REPO)) not in named)
    assert orphans == [], f"reference file(s) no skill names: {orphans}"


def test_no_skill_body_exceeds_the_budget():
    over = {p.parent.name: len(p.read_bytes()) for p in SKILLS.glob("*/SKILL.md")
            if len(p.read_bytes()) > BODY_MAX}
    assert over == {}, (
        f"body over the {BODY_MAX} B budget: {over}. New material goes on a "
        f"reference page, not in the body — that is what the budget is for")
