# Reachable instructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make every path a skill names resolvable from where the skill runs —
one recorded-root anchor for commands and reads, and the two biggest bodies
split so a stage's detail is a page fetched on demand instead of 84 KB spent
on every invocation.

**Architecture:** one verbatim preamble block in all fourteen `SKILL.md` files
resolves `ROOT` (and `VG` from it). `using-montage` keeps a generated,
byte-pinned stage table plus one numbered stub per stage carrying only the
command; the rest of each stage moves to `references/using-montage/<stage-key>.md`.
`edit-plan` keeps its four steps and moves two subjects out of step 2 to
`references/edit-plan/`. The existing skill-convention tests are made
page-aware *first*, so no ban goes blind when 60 KB of text leaves `SKILL.md`.

**Tech Stack:** Markdown skill bodies, `scripts/lib/toolindex.py` (pure
renderers over `scripts.montage.V1_STAGES`), pytest.

**Design:** [docs/specs/2026-09-14-reachable-instructions-design.md](../specs/2026-09-14-reachable-instructions-design.md)

## Global Constraints

- **Python is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .`
  in `pytest.ini`): `.venv/bin/python -m scripts.montage …`.
- **Never run an installer.** No `brew`, `pip`, `uv`, `npm`, `apt`, and never
  `bash setup.sh`. Verification is read-only plus `pytest`.
- **Never run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** To restore committed content use
  `git show HEAD:<path> > <path>`; before mutating a file that is *not* yet
  committed, save your own copy first with `cp <path> <path>.bak`.
- **Mutation checks run under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit
  can match the previous file's size and mtime-second, and CPython then serves
  a stale `.pyc`.
- **zsh does not word-split an unquoted variable.** A test selection held in a
  shell variable arrives as ONE argument and pytest prints `no tests ran`,
  which reads exactly like a non-discriminating mutation row. Pass selections
  literally.
- **Commit after every task.** Never amend; a follow-up fix is its own commit.
- **The skill text is the product.** Every byte moved between files must be
  moved, not retyped: use `sed -n 'A,Bp'` to extract ranges. A paraphrase of a
  moved paragraph is a silent content change no test can catch.
- **20 KB is the body budget** (`BODY_MAX = 20_000` bytes), and it is a budget,
  not a measurement — design §3.5. Say so in the test's docstring.
- **The two non-stage router blocks stay resident**: `0. **Verify the runtime
  (gate).**` and `1. **Locate the run.**`. Stage stubs are numbered from **2**.

---

## File Structure

| File | Responsibility |
|---|---|
| `tests/test_skill_convention.py` | modify — page-aware helpers; the rewritten launcher guard; the new resolution, orphan, page-set, stub-binding and budget checks |
| `scripts/lib/toolindex.py` | modify — `CHECKPOINT_LABEL`, `FIRST_STAGE_STEP`, `stage_steps()`, `render_stages()` |
| `scripts/montage.py` | modify — the `stages` subcommand |
| `references/tools.md` | regenerate — the `stages` subcommand is a 48th help surface |
| `skills/*/SKILL.md` (all 14) | modify — the one preamble block |
| `skills/using-montage/SKILL.md` | modify — generated table, 16 stubs, a Checkpoints section |
| `references/using-montage/<stage-key>.md` (15 new) | create — one page per live stage |
| `references/edit-plan/episode-fields.md` | create — the authorable-field reference and its knob table |
| `references/edit-plan/grade-convergence.md` | create — the colour convergence loop |
| `tests/test_tool_index.py` | modify — the stage table's byte pin |
| `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`, `docs/backlog.md`, `docs/build-status.md` | modify — 0.9.3 and the registry rows |

---

## Task 1: Make the skill-convention tests page-aware

Nothing moves yet. Three bans in `tests/test_skill_convention.py` glob
`skills/*/SKILL.md`; two presence tests read a single `SKILL.md`. Tasks 4 and 5
move ~60 KB out of two of those files. A ban that is not repointed does not
fail — **it silently stops covering the text that left**, which is worse than a
failure. Do this before any text moves, so the harness is already correct when
the text arrives.

**Files:**
- Modify: `tests/test_skill_convention.py`

**Interfaces:**
- Produces: `skill_pages(name: str) -> list[Path]` — the `.md` files under
  `references/<name>/`, recursively, empty when the directory does not exist.
- Produces: `skill_docs(name: str) -> list[Path]` — `skills/<name>/SKILL.md`
  followed by `skill_pages(name)`.
- Produces: `all_skill_docs() -> list[Path]` — `skill_docs()` for every skill
  directory, flattened and sorted.
- Produces: `skill_text(name: str) -> str` — every file of `skill_docs(name)`
  joined with `"\n"`.

- [ ] **Step 1: Add the helpers**

Insert after the `ROLE_LEADS` definition (currently ends near line 29):

```python
def skill_names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


def skill_pages(name: str) -> list[Path]:
    """The reference pages a skill OWNS — `references/<skill name>/**/*.md`.

    Ownership is the directory name, not a list: a page belongs to a skill iff
    it lives in a directory named after it. The four repo-level references
    (`editing-canon`, `ffmpeg-recipes`, `landmines`, the generated `tools`) are
    shared documents of a different kind and are deliberately NOT skill pages —
    `tools.md` carries a maintainer regeneration command that the bans below
    would (correctly, for a skill) refuse."""
    root = REPO / "references" / name
    return sorted(root.rglob("*.md")) if root.is_dir() else []


def skill_docs(name: str) -> list[Path]:
    """Everything an agent reads when it works this skill: the body, then its
    pages. Every glob-based ban and presence check below runs over THIS, never
    over `SKILL.md` alone — otherwise moving a paragraph to a page moves it out
    from under its own check (design 2026-09-14 §2.2)."""
    return [SKILLS / name / "SKILL.md"] + skill_pages(name)


def all_skill_docs() -> list[Path]:
    return [p for name in skill_names() for p in skill_docs(name)]


def skill_text(name: str) -> str:
    return "\n".join(p.read_text() for p in skill_docs(name))
```

- [ ] **Step 2: Repoint the three glob bans**

Replace `SKILLS.glob("*/SKILL.md")` with `all_skill_docs()` in exactly three
places — `test_no_skill_invokes_a_bare_venv_python` (line ~33),
`test_no_skill_spells_a_stage_artifact_outside_its_bucket` (line ~109),
`test_no_skill_still_names_the_retired_out_dir` (line ~121) — and in
`test_no_skill_example_passes_a_bare_path_into_the_run` (line ~197).

Leave `test_every_skill_description_leads_with_a_role_tag` (line ~76) on
`SKILLS.glob("*/SKILL.md")`: it parses frontmatter, and a page has none.

- [ ] **Step 3: Repoint the two presence tests**

In `test_edit_plan_skill_names_every_authorable_episode_field`, replace the
body's read:

```python
    missing = sorted(f.name for f in dataclasses.fields(EDLEpisode)
                     if f.name not in skill_text("edit-plan"))
    assert missing == [], (
        f"{len(missing)} EDLEpisode field(s) the authoring skill never names: "
        f"{missing}. Document them in skills/edit-plan/SKILL.md or one of its "
        f"references/edit-plan/ pages — an authorable knob nobody can find is "
        f"the same as one that does not exist")
```

In `test_using_montage_defines_every_bucket`, replace:

```python
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
```

with:

```python
    text = skill_text("using-montage")
```

and append to its docstring:

```
    Reads the skill AND its pages (design 2026-09-14 §2.2): the `reel` row's
    citation `<run>/reels/<reel>/EDL.json` first appears at line 228 today,
    inside a stage block that becomes a page — on `SKILL.md` alone this test
    would start failing the moment the split lands, for no real reason.
```

- [ ] **Step 4: Prove the helper is not vacuous**

Add:

```python
def test_skill_docs_reaches_pages_and_skips_the_shared_references():
    """The helper's whole value is that it reaches further than SKILL.md. If
    `references/<name>/` never matches anything, every ban above silently
    narrows back to the body and this suite keeps passing while covering less.

    Both halves are asserted because both can fail silently: a glob that
    matches nothing looks identical to a skill with no pages, and a glob that
    matches `references/*.md` would pull the four shared documents under bans
    they have never been subject to."""
    shared = {"editing-canon.md", "ffmpeg-recipes.md", "landmines.md", "tools.md"}
    reached = {p.name for p in all_skill_docs()}
    assert reached & shared == set(), (
        f"skill_docs() reached a shared repo-level reference: {reached & shared}")
    assert all((SKILLS / n / "SKILL.md") in skill_docs(n) for n in skill_names())
```

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS, one more test than before. Nothing has moved, so every
repointed check still sees exactly what it saw.

- [ ] **Step 6: Commit**

```bash
git add tests/test_skill_convention.py
git commit -m "test(skills): make the convention checks page-aware before any text moves"
```

---

## Task 2: One anchor — the recorded root in all fourteen skills

The launcher guard forbids one literal string, so eleven bare
`python -m scripts.X` examples pass it. The five skills carrying them are
exactly the five that do not read the recorded root. All fourteen name
`references/tools.md` in their frontmatter and none says what it is relative
to. One block fixes both.

**Files:**
- Modify: all 14 `skills/*/SKILL.md`
- Modify: `tests/test_skill_convention.py`

**Interfaces:**
- Produces: `PREAMBLE` — the exact block every `SKILL.md` must contain
  verbatim. Later tasks must not reword it; `test_every_skill_carries_the_resolution_preamble` compares by substring.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skill_convention.py`, and DELETE `RUNNERS` (line ~17) along
with `test_the_runner_skills_route_through_bin_vg` and
`test_the_runner_skills_read_the_recorded_root` — the new test subsumes both
and is strictly stronger (fourteen skills instead of a typed seven, and the
block contains both `bin/vg` and `video-grid/root`):

```python
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
# past it, five of them in edit-plan and one in footage-intake, whose CLI is
# the reason the cd into the clone is mandatory at all (ultralytics writes YOLO
# weights into the working directory). Design 2026-09-14 §0.4.
BANNED_SPELLINGS = (".venv/bin/python", "python -m scripts")


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: FAIL — `test_no_skill_spells_a_command_it_cannot_resolve` lists 11
offenders across 5 skills, and `test_every_skill_carries_the_resolution_preamble`
lists all 14.

- [ ] **Step 3: Put the block in all fourteen skills**

**Eight** skills carry an older two-sentence paragraph beginning
`**Launcher.** Run every pipeline step through the repo's launcher` — in
`episode-qc`, `match-grade`, `music-match`, `music-source`, `pacing`,
`process-episode`, `project-init`, `using-montage`. Replace that whole
paragraph with `PREAMBLE`'s text verbatim.

**Six** have no such paragraph and get `PREAMBLE` inserted as a new paragraph
before their first numbered step or first procedure section: `edit-plan`
before `## Procedure`, `footage-intake` before `## The Process`, `reel-brief`
before `## Procedure`, `reel-review` before `## Inputs`, `titles` before
`## Procedure`, and `verify-runtime` before its numbered step 1.

`verify-runtime` is the sixth because it resolves the root in its own step 1
rather than in a launcher paragraph — and that step is where
`ROOT="$(cat …)"` / `"$ROOT/bin/vg"` is already spelled, which is why
`PREAMBLE` uses that spelling rather than inventing one. **Leave its step 1 in
place**: it carries a refusal the preamble does not (there is no runtime to
check yet, so stop rather than continue).

- [ ] **Step 4: Convert the eleven bare-`python` sites**

Each becomes `"$VG" scripts.X` with no other change:

| file:line | command |
|---|---|
| `skills/edit-plan/SKILL.md:73` | `scripts.contact_sheet strip` |
| `skills/edit-plan/SKILL.md:242` | `scripts.color_measure <clip>` (inline in prose) |
| `skills/edit-plan/SKILL.md:294` | `scripts.probe grade --geometry` |
| `skills/edit-plan/SKILL.md:352` | `scripts.edit_plan build` |
| `skills/edit-plan/SKILL.md:363` | `scripts.probe grade --episodes` |
| `skills/edit-plan/SKILL.md:453` | `scripts.process_episode` |
| `skills/edit-plan/SKILL.md:477` | `scripts.edit_plan build` |
| `skills/footage-intake/SKILL.md:40` | `scripts.intake <footage_root> <out_dir>` |
| `skills/reel-brief/SKILL.md:41` | `scripts.reel_brief build` |
| `skills/reel-review/SKILL.md:109` | `scripts.reel_review build` |
| `skills/titles/SKILL.md:53` | `scripts.titles build` |

Line numbers are from before Step 3's insertions — re-find each by its command
text, not by number.

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py tests/test_skills_contract.py tests/test_launcher.py tests/test_verify_runtime_skill.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills tests/test_skill_convention.py
git commit -m "fix(skills): one recorded-root anchor for every command and reference"
```

---

## Task 3: The generated stage table

`V1_STAGES` holds fifteen live stages; the router has fourteen stage blocks and
`reel-review` — required — has none. The chain sentence is already generated
and cannot drift; the body's structure is typed and has. Generate the stage
table from the registry and pin it.

**Files:**
- Modify: `scripts/lib/toolindex.py`
- Modify: `scripts/montage.py`
- Modify: `skills/using-montage/SKILL.md`
- Modify: `references/tools.md` (regenerate)
- Modify: `tests/test_tool_index.py`

**Interfaces:**
- Consumes: `scripts.montage.V1_STAGES` (`Stage.key`, `.kind`, `.artifact`,
  `.checkpoint`), `toolindex.chain()`.
- Produces: `toolindex.FIRST_STAGE_STEP = 2`,
  `toolindex.CHECKPOINT_LABEL: dict[str | None, str]`,
  `toolindex.stage_steps() -> list[tuple[int, Stage]]`,
  `toolindex.render_stages() -> str`,
  `toolindex.STAGES_BEGIN` / `STAGES_END` marker strings.
- Produces: `montage stages` CLI subcommand printing `render_stages()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tool_index.py`:

```python
SKILL = ROOT / "skills/using-montage/SKILL.md"


def _generated_block(text: str) -> str:
    """The bytes between the markers, exclusive, with the marker lines' own
    newlines excluded. Raises rather than returning '' when a marker is
    missing: an empty string would compare unequal to the renderer and report
    as staleness, hiding the real fault (the markers were deleted)."""
    begin, end = text.index(toolindex.STAGES_BEGIN), text.index(toolindex.STAGES_END)
    return text[begin + len(toolindex.STAGES_BEGIN):end].strip("\n") + "\n"


def test_the_router_table_matches_what_the_renderer_produces():
    assert _generated_block(SKILL.read_text()) == toolindex.render_stages(), (
        "the stage table in skills/using-montage/SKILL.md is stale — regenerate:\n"
        "    python -m scripts.montage stages\n"
        "and replace the block between the two markers")


def test_the_router_table_covers_every_live_stage_once():
    """Enumerated from V1_STAGES directly, never from stage_steps().

    Asking the renderer which stages exist and then checking it rendered those
    is circular — the identical mistake test_every_help_surface_has_a_row
    exists to avoid."""
    from scripts import montage
    live = [s.key for s in montage.V1_STAGES if s.kind != "deferred"]
    table = _generated_block(SKILL.read_text())
    rows = [l for l in table.splitlines() if l.startswith("| ") and "---" not in l][1:]
    assert len(rows) == len(live) == 15
    for key, row in zip(live, rows):
        assert f"`{key}`" in row, f"row for {key} missing or out of order: {row}"


def test_a_deferred_stage_gets_no_row():
    """trend-scan is `deferred` and must not appear: the table is what the
    router runs, and a row for an unbuilt stage is an instruction to run it."""
    assert "trend-scan" not in toolindex.render_stages()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_index.py -q`
Expected: FAIL with `AttributeError: module 'scripts.lib.toolindex' has no attribute 'STAGES_BEGIN'`.

- [ ] **Step 3: Add the renderer**

Append to `scripts/lib/toolindex.py`:

```python
#: Steps 0 and 1 of the router are the runtime gate and locating the run —
#: neither is a stage, so the first stage is step 2. The table owns these
#: numbers and tests/test_skill_convention.py binds the hand-written stubs to
#: them, which is what stops the drift design 2026-09-14 §0.5 measured: fifteen
#: live stages, fourteen numbered blocks, and `reel-review` — required — with
#: no number at all.
FIRST_STAGE_STEP = 2

#: Stage.checkpoint is the registry's own name for the three §4.1 user gates.
CHECKPOINT_LABEL: dict[str | None, str] = {
    None: "—", "spec": "CP1", "edl": "CP2", "final": "CP3"}

STAGES_BEGIN = "<!-- generated: stages — python -m scripts.montage stages -->\n"
STAGES_END = "<!-- /generated -->"

ROUTER_PAGES = "references/using-montage"


def stage_steps() -> list[tuple[int, object]]:
    """(step number, Stage) for every live stage, in conveyor order."""
    from scripts import montage
    live = [s for s in montage.V1_STAGES if s.kind != "deferred"]
    return list(enumerate(live, start=FIRST_STAGE_STEP))


def render_stages() -> str:
    """The router's stage table. One generated block: it owns the set, the
    order and the step numbers; the stubs beneath it own the commands, which
    carry run-directory paths no registry knows."""
    lines = ["| step | stage | kind | gate | writes | page |",
             "|---|---|---|---|---|---|"]
    for n, s in stage_steps():
        lines.append(f"| {n} | `{s.key}` | {s.kind} | {CHECKPOINT_LABEL[s.checkpoint]} "
                     f"| `{s.artifact}` | `{ROUTER_PAGES}/{s.key}.md` |")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Add the `stages` subcommand**

In `scripts/montage.py`'s `build_parser()`, immediately after the `tools`
subparser:

```python
    sub.add_parser("stages", help="print the generated router stage table",
                   description="print the generated stage table the using-montage "
                               "SKILL carries between its two generated: stages "
                               "markers — one row per live conveyor stage, naming "
                               "its step number, whether it is required, which of "
                               "the three user checkpoints it sits at, the artifact "
                               "whose presence marks it done, and the reference "
                               "page carrying its detail.")
```

and in `main()`, beside the `tools` arm:

```python
    if a.cmd == "stages":
        print(toolindex.render_stages(), end="")
        return
```

- [ ] **Step 5: Put the block in the router**

Insert into `skills/using-montage/SKILL.md` between the run-directory section
and `0. **Verify the runtime (gate).**` (currently line 67/68):

```markdown
## The stages

Generated from `montage.V1_STAGES` — the registry the inspector resolves against.
Read a stage's page before running it; the stub below each row carries the
command and nothing else.

<!-- generated: stages — python -m scripts.montage stages -->
<!-- /generated -->
```

Then fill it:

```bash
.venv/bin/python -m scripts.montage stages
```

and paste the output between the two marker lines.

- [ ] **Step 6: Regenerate the tool index**

The `stages` subcommand is a 48th `--help` surface, so `references/tools.md`
and `tests/test_cli_help.py`'s count both move.

```bash
.venv/bin/python -m scripts.montage tools > references/tools.md
```

Then update the `len(expected) == 47` backstop in
`tests/test_tool_index.py::test_every_help_surface_has_a_row` to `48`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_tool_index.py tests/test_cli_help.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/toolindex.py scripts/montage.py skills/using-montage/SKILL.md references/tools.md tests/test_tool_index.py
git commit -m "feat(toolindex): generate the router's stage table from V1_STAGES"
```

---

## Task 4: Split `using-montage` into stubs and pages

**The numbering already agrees with the registry for every existing block.**
`enumerate(live, start=2)` gives project-init=2 … deliver=15, so all fourteen
current numbers are already correct and none of the 27 `step N` cross-references
in this file (nor the ones in other skills) needs touching. The only new number
is **16, `reel-review`** — the required stage that has no block today and is
buried at lines 539–551 inside block 15.

**Files:**
- Modify: `skills/using-montage/SKILL.md`
- Create: `references/using-montage/<stage-key>.md` × 15
- Modify: `tests/test_skill_convention.py`

**Interfaces:**
- Consumes: `toolindex.stage_steps()`, `toolindex.ROUTER_PAGES` (Task 3).
- Produces: one page per live stage, and a stub per stage whose heading is
  `N. **<stage-key>** — `.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skill_convention.py`:

```python
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
```

Add `import re` to the imports if it is not already there.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q -k "router or live_stage"`
Expected: FAIL — no `references/using-montage/` directory, and the stub headings
do not match the `N. **<key>** — ` shape.

- [ ] **Step 3: Move each stage block to its page**

Re-find each block by its heading text, not by the line numbers below — Tasks 2
and 3 inserted the preamble and the table above them. The ranges below are from
the file as it stands at the START of this task; read it with
`git show HEAD:skills/using-montage/SKILL.md | sed -n 'A,Bp'` to extract a range
without touching the working tree.

| step | stage | pre-split lines | page |
|---|---|---|---|
| 2 | project-init | 112–125 | `project-init.md` |
| 3 | footage-intake | 126–129 | `footage-intake.md` |
| 4 | contact-sheet | 130–144 | `contact-sheet.md` |
| 5 | reel-brief | 145–152 | `reel-brief.md` |
| 6 | edit-plan | 153–193 | `edit-plan.md` |
| 7 | music-and-mood | 194–225 | `music-and-mood.md` |
| 8 | pacing | 226–246 | `pacing.md` |
| 9 | episodes-geometry | 247–267 | `episodes-geometry.md` |
| 10 | match-grade | 268–318 | `match-grade.md` |
| 11 | assemble-draft | 319–331 | `assemble-draft.md` |
| 12 | titles | 332–346 | `titles.md` |
| 13 | episodes | 347–387 | `episodes.md` |
| 14 | episode-qc | 388–420 | `episode-qc.md` |
| 15 | deliver | 421–506 | `deliver.md` |
| 16 | reel-review | 539–551 | `reel-review.md` |

Lines **507–538 and 552–564 are Checkpoint 3**, not a stage — Step 5.
Lines **114–124 are Checkpoint 1** (inside block 2, starting mid-line 114 after
`` `--purpose custom --canvas W:H`). ``) and **166–172 are Checkpoint 2**
(inside block 6, starting mid-line 166) — also Step 5, not their blocks' pages.

**`project-init.md` will be nearly empty and that is correct.** Its block is
fourteen lines: two are the command (which stays in the stub) and eleven are
Checkpoint 1 plus the `CONSTRAINTS.json` paragraph (which go to the Checkpoints
section). What is left for the page is the routing statement and whatever
detail the command's flags need. The same holds for `footage-intake.md` and
`reel-brief.md` — a thin page is the answer "this stage is conducted by its own
skill", not a gap (design §2.3).

Each page opens with a one-line title and nothing else new:

```markdown
# deliver — router stage 15

<the moved text, verbatim, de-indented by its list indent>
```

Move the text; do not rewrite it. De-indent by the four or five spaces the
numbered-list nesting added, and nothing more.

- [ ] **Step 4: Replace each block with its stub**

Every stage keeps a stub of exactly this shape — heading, one sentence, the
command block, the stop names when it has any, and the page pointer:

```markdown
15. **deliver** — encode the judged episodes into one versioned delivery.

    ```bash
    "$VG" scripts.edl_to_reel --from-episodes <run>/reels/<reel>/episodes/EPISODES.json \
      --project <run>/project.json --work-dir <run>/reels/<reel>/build \
      --out-dir <run>/reels/<reel>/deliveries [--titles <run>/reels/<reel>/TITLES.json]
    ```

    Stops: `episode-qc-reprocessed`, `grade_faithful`. Before running it, read
    `"$ROOT/references/using-montage/deliver.md"`.
```

Take each command verbatim from the block being replaced — the flags and the
run-directory paths are the half `--help` cannot re-derive (design §2.2), so
they stay here and everything explaining them goes to the page. Three stages
have no command of their own because a sub-skill runs them
(`footage-intake`, `edit-plan`, `episode-qc`): their stub names the skill to
invoke instead, and their pages are correspondingly thin, which is the routing
answer rather than waste (design §2.3).

- [ ] **Step 5: Give the checkpoints their own section**

Add `## Checkpoints` immediately after `## The stages`'s generated table and
before the stubs, carrying CP1 (pre-split 114–124), CP2 (166–172) and CP3
(507–538, 552–564), each under its own bold lead. They stay resident: a stage
page that goes unread costs detail, a checkpoint that goes unread is a user
gate silently skipped (design §2.4).

The gate column of the generated table already says which stages sit at which
checkpoint, so the section names the gate and what to present, not the stage
list.

- [ ] **Step 6: Prove nothing was lost**

```bash
.venv/bin/python - <<'EOF'
import subprocess
from pathlib import Path
before = subprocess.run(["git", "show", "HEAD:skills/using-montage/SKILL.md"],
                        capture_output=True, text=True, check=True).stdout.splitlines()
after = Path("skills/using-montage/SKILL.md").read_text()
after += "\n".join(p.read_text() for p in Path("references/using-montage").glob("*.md"))
squash = lambda s: " ".join(s.split())
after_s = squash(after)
lost = [l for l in before if len(squash(l)) > 25 and squash(l) not in after_s]
print(f"{len(lost)} line(s) of the pre-split body are not in the new body + pages")
for l in lost:
    print("   ", l[:100])
EOF
```

Expected: the only reported lines are ones you deliberately rewrote — the
sixteen stub headings and the old `**Launcher.**` paragraph Task 2 replaced.
Anything else is content dropped in the move; put it back. Whitespace is
squashed on both sides because de-indenting changes it by design.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py tests/test_tool_index.py tests/test_skills_contract.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add skills/using-montage/SKILL.md references/using-montage tests/test_skill_convention.py
git commit -m "refactor(using-montage): a stage is a page; the body keeps the command"
```

---

## Task 5: Split `edit-plan`'s step 2

Step 2 is 26 192 B — 64 % of the file — and it is two subjects: the authorable
field reference with its knob table, and a colour convergence procedure around
`match_grade`/`probe` that lives here only because `edit-plan` owns the
`selection.json` rebuild it turns on.

**Files:**
- Modify: `skills/edit-plan/SKILL.md`
- Create: `references/edit-plan/episode-fields.md`
- Create: `references/edit-plan/grade-convergence.md`

**Interfaces:**
- Consumes: `skill_text("edit-plan")` from Task 1 — the
  `EDLEpisode`-field presence test already reads the pages, so the fields may
  move.

- [ ] **Step 1: Move the two subjects**

Pre-split line ranges (re-find by their opening text; Task 2 inserted the
preamble above them):

| lines | opens with | destination |
|---|---|---|
| 112–283 | `**The reel's finish is `"look"`, a top-level key…` | `references/edit-plan/episode-fields.md` |
| 284–474 | `**Converging a grade before anything is ever rendered…` | `references/edit-plan/grade-convergence.md` |

Lines 83–111 — the ranking prose and the **variety gate** — stay in the body.
The gate is a refusal the author must know about *before* authoring, not a
thing to look up after being refused (design §2.5).

Each page opens with a title line and nothing else new:

```markdown
# edit-plan — every authorable episode field
```

```markdown
# edit-plan — converging a grade
```

- [ ] **Step 2: Leave the two pointers**

Where each block was, leave one sentence naming what moved and where:

```markdown
   Every authorable key — layout, motion, colour, the reel-level `look` and
   `variety_waiver` — with the refusals that go with it, and the index table
   of all of them: read `"$ROOT/references/edit-plan/episode-fields.md"`
   before authoring.

   Converging a grade, before episodes exist and after: read
   `"$ROOT/references/edit-plan/grade-convergence.md"`. It is the loop that
   rebuilds `selection.json` and re-runs **match-grade**, and running it wrong
   re-renders a reel that did not need re-rendering.
```

- [ ] **Step 3: Prove nothing was lost**

```bash
.venv/bin/python - <<'EOF'
import subprocess
from pathlib import Path
before = subprocess.run(["git", "show", "HEAD:skills/edit-plan/SKILL.md"],
                        capture_output=True, text=True, check=True).stdout.splitlines()
after = Path("skills/edit-plan/SKILL.md").read_text()
after += "\n".join(p.read_text() for p in Path("references/edit-plan").glob("*.md"))
squash = lambda s: " ".join(s.split())
after_s = squash(after)
lost = [l for l in before if len(squash(l)) > 25 and squash(l) not in after_s]
print(f"{len(lost)} line(s) not carried over")
for l in lost:
    print("   ", l[:100])
EOF
```

Expected: nothing but lines you deliberately replaced with the two pointers.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS — in particular
`test_edit_plan_skill_names_every_authorable_episode_field`, which Task 1
repointed at `skill_text("edit-plan")` precisely so this move is legal.

- [ ] **Step 5: Commit**

```bash
git add skills/edit-plan/SKILL.md references/edit-plan
git commit -m "refactor(edit-plan): the field reference and the convergence loop become pages"
```

---

## Task 6: The remaining checks, the battery, and the docs

**Files:**
- Modify: `tests/test_skill_convention.py`
- Modify: `docs/development-workflow.md`
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`,
  `docs/backlog.md`, `docs/build-status.md`

- [ ] **Step 1: Write the three remaining checks**

Add to `tests/test_skill_convention.py`:

```python
_REF = re.compile(r"references/[\w/-]+\.md")

#: A body budget, NOT a measurement of anything. Three facts anchor it and none
#: of them is a threshold: it is under half of either body before this slice
#: (43 464 and 40 773 bytes); it is above episode-qc (16 017), the largest body
#: against which no backlog row has ever been filed; and it is above what this
#: slice lands, which is the part that matters — a cap that binds on the day it
#: ships is a cap the next author fights instead of obeys. Design §3.5.
BODY_MAX = 20_000


def test_every_reference_a_skill_names_exists():
    """Eighteen bare `references/…` pointers existed with no rule anywhere for
    resolving them (design §0.3). The preamble supplies the rule; this supplies
    the other half — that the thing at the end of the path is there."""
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
```

- [ ] **Step 2: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS. If `test_no_skill_body_exceeds_the_budget` fails, Task 4 or 5
left too much in a body — move more to a page rather than raising the cap.

- [ ] **Step 3: Run the mutation battery**

Sixteen rows, each breaking one guarantee, each expected RED. Run every row
under `PYTHONDONTWRITEBYTECODE=1`, restore after each row, and pass the test
selection literally — an unquoted shell variable arrives as one argument and
pytest prints `no tests ran`, which is indistinguishable from a row that did
not discriminate.

To restore a committed file after a row: `git show HEAD:<path> > <path>`.
Before mutating a file you created in this task and have not yet committed,
`cp <path> <path>.bak` first.

| # | mutation | expected RED |
|---|---|---|
| 1 | delete `references/using-montage/pacing.md` | `test_every_live_stage_has_a_router_page` |
| 2 | create `references/using-montage/bogus.md` | `test_every_live_stage_has_a_router_page` |
| 3 | swap the `pacing` and `music-and-mood` stubs | `test_the_router_stubs_are_the_table_s_stages_in_order` |
| 4 | change stub `13.` to `12.` | `test_the_router_stubs_are_the_table_s_stages_in_order` |
| 5 | change one cell of the generated table (`required` → `optional`) | `test_the_router_table_matches_what_the_renderer_produces` |
| 6 | delete the `<!-- /generated -->` marker line | `test_the_router_table_matches_what_the_renderer_produces` raises `ValueError`, not a diff |
| 7 | put `python -m scripts.intake x y` back in `skills/footage-intake/SKILL.md` | `test_no_skill_spells_a_command_it_cannot_resolve` |
| 8 | put `python -m scripts.probe grade` in `references/edit-plan/grade-convergence.md` | same test — **this row is the one proving the ban reads pages**; without Task 1 it is green |
| 9 | delete the preamble from `skills/titles/SKILL.md` | `test_every_skill_carries_the_resolution_preamble` |
| 10 | change a stub's pointer to `references/using-montage/deliverr.md` | `test_every_reference_a_skill_names_exists` |
| 11 | create `references/edit-plan/bogus.md` | `test_no_reference_file_is_orphaned` |
| 12 | append 25 KB of text to `skills/verify-runtime/SKILL.md` | `test_no_skill_body_exceeds_the_budget` |
| 13 | delete the `ramp` field's name from both `edit-plan` body and pages | `test_edit_plan_skill_names_every_authorable_episode_field` |
| 14 | put `<run>/out` in `references/using-montage/deliver.md` | `test_no_skill_still_names_the_retired_out_dir` — the second page-awareness row, and it covers a DIFFERENT ban than row 8 |
| 15 | flip `trend-scan`'s kind from `deferred` to `optional` in `scripts/montage.py` | `test_a_deferred_stage_gets_no_row` and `test_every_live_stage_has_a_router_page` |
| 16 | delete the page pointer sentence from the `deliver` stub | `test_every_router_stub_points_at_its_own_page` |

Run each as, for example:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_skill_convention.py -q -k "router_page"
```

Record every row's result. **A row that comes back GREEN is a finding, not a
formality**: either the guarantee is unguarded — write the test that catches
it and say so in the report — or the row does not express the mutation it
claims, in which case fix the row. Do not report a green row as "expected".

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. The pre-branch baseline is **3815 passed, 1 skipped**; this
slice adds tests and removes two (`RUNNERS`'s pair), so the count moves up.
Report the exact numbers.

- [ ] **Step 5: Document the convention**

Add a section to `docs/development-workflow.md` under its doc-standards
material, stating the three rules an author needs and nothing more:

- every `SKILL.md` carries the resolution preamble verbatim, and names no
  command or path that is not anchored on `$VG` / `$ROOT`;
- a router stage is a page at `references/using-montage/<stage-key>.md`; the
  stub in the body carries the command and the pointer, the page carries the
  rest;
- a body stays under 20 KB — new material goes on a page. The number is a
  budget, not a measurement (design §3.5).

- [ ] **Step 6: Version and registry**

Bump `.claude-plugin/plugin.json` and the top `CHANGELOG.md` entry to
**0.9.3** (PATCH — no contract, no CLI behaviour, no pixel changes).
`tests/test_plugin_manifests.py` enforces that the two agree.

Add two rows to `CLAUDE.md`'s Quick Reference table, in the same style as the
neighbouring rows, pointing at this design and this plan.

In `docs/backlog.md`, remove the P2 row *"The two biggest skill bodies load
whole and are lost to compaction"* and move it to `docs/backlog-closed.md`
with its closure note — including what the row's own premise missed: it named
body size, and measuring it found two further unreachable-path defects of the
same kind, one of them in the skill whose CLI makes the clone `cd` mandatory.

Add the four §6 deferred rows to `docs/backlog.md`:

1. Nothing detects that the installed plugin is behind the repo — 0.2.1
   against 0.9.2. `verify_runtime` is the natural home. (P2, S)
2. The twelve remaining skill bodies have no page structure; `episode-qc`,
   `match-grade` and `titles` reach the 20 KB cap first. (P3, M)
3. Whether `edit-plan`'s remaining body is one coherent procedure or two has
   not been measured. (P3, S)
4. A page's prose is not checked against the code it describes;
   `tests/test_cli_help.py` knows every flag and nothing joins the two. (P3, M)

Add a Done entry to `docs/build-status.md`.

- [ ] **Step 7: Commit**

```bash
git add tests/test_skill_convention.py docs CHANGELOG.md CLAUDE.md .claude-plugin/plugin.json
git commit -m "docs: 0.9.3 — a skill's instructions are reachable from where it runs"
```
