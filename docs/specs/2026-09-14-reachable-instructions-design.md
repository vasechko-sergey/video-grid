# Reachable instructions — design

**Goal:** a skill's instructions must be reachable from where the skill
actually runs. Three things today are not: a body too large to survive the
context it is read into, a pointer with no resolution rule, and a command
anchored to a working directory nobody guarantees.

**Scope:** the two biggest skill bodies (`using-montage`, `edit-plan`) and the
one resolution rule, which binds all fourteen.

**Source:** `docs/backlog.md` P2 — "The two biggest skill bodies load whole and
are lost to compaction", filed by
[rederivable-purpose](2026-09-12-rederivable-purpose-design.md) §6 row 1. Two
further defects below were found while measuring it and are folded in.

---

## 0. What is measured

### 0.1 The two bodies are half the tree, and eighteen times the resident budget

Fourteen `SKILL.md` files, **180 637 bytes**, 2849 lines. Two of them —
`using-montage` (43 464 B, 646 lines) and `edit-plan` (40 773 B, 629 lines) —
are **84 237 B, 46.6 % of every skill byte in the repo**.

The previous slice cut the always-resident `description:` surface from 7244 to
**4685 characters**. These two bodies are **18× that entire budget**, and they
are not resident: a body is read into the turn that invokes the skill and is
spent by the first compaction. The slice that made the pointer durable did not
touch what the pointer leads to.

### 0.2 Four fifths of both bodies is block-conditional

`using-montage` is sixteen numbered blocks and has no reference subfiles:

| | lines | bytes |
|---|---|---|
| head — overview, when-to-use, run directory, launcher | 67 | 3 989 |
| the sixteen numbered blocks | 497 | 33 961 (**78 %**) |
| tail — reading the brief, boundaries | 82 | 5 511 |

`edit-plan` is four numbered steps and they are **84 %** of it (34 318 B of
40 773). One step carries most of that: step 2, *Author `selection.json`*, is
**26 192 B — 64 % of the file**, and it is two unrelated subjects. Roughly 170
lines are the episode-field reference plus a table the text itself introduces
as "**Every knob, in one place**"; roughly **190 lines are the colour
convergence loop** — a procedure around `match_grade` and `probe` that lives
here only because `edit-plan` owns the `selection.json` rebuild it turns on.

A block is needed when the agent is at that block. Four fifths of both files
is paid on every invocation to be useful at one moment of it.

### 0.3 Eighteen pointers into `references/`, and no rule anywhere for reaching it

`references/` is not a new convention: four files, 18 469 B —
`editing-canon.md`, `ffmpeg-recipes.md`, `landmines.md`, and the generated
`tools.md` the last slice added.

Eighteen pointers name it. Fourteen are the frontmatter
`Tool index: references/tools.md.` that slice put on every description; four
are prose, including `edit-plan`'s **required read** of
`references/editing-canon.md`. **All eighteen are bare relative paths, and no
skill states what they are relative to.**

Nothing resolves them. An agent's working directory during a run is the user's
footage project, not the clone. Inside the installed plugin the layout is
`<plugin>/references/` beside `<plugin>/skills/<name>/SKILL.md`, so the path is
two levels off from the skill's own directory as well. The only way a bare
`references/editing-canon.md` resolves today is a guess that happens to land.

The retro of the only real run does not mention `editing-canon.md` once. There
is no evidence the required read was ever read. That is not proof it failed —
it is the absence of any evidence that it worked, on the one file the authoring
skill calls its editorial base.

### 0.4 Five skills name a command they cannot run — and the predicate is exact

The launcher guard (`tests/test_skill_convention.py`) forbids one literal
string, `.venv/bin/python`. **Eleven command examples spell a bare
`python -m scripts.X` and pass it**: seven in `edit-plan`, one each in
`footage-intake`, `reel-brief`, `reel-review`, `titles`.

**Corrected during execution, 2026-09-14:** eleven is the count for that one
spelling, and the grep that produced it was itself a guard tested for a literal
— the same mistake one level up. Two further sites spell it `python -c "…"`
and import `scripts` directly (`edit-plan`, `reel-review`), so the real count
is **thirteen across two spellings**. They also cost more to fix: `bin/vg` ends
in `exec … python -m "$@"`, so `-m` is hardcoded and the launcher had to learn
a `-c` passthrough before any skill could name one. The lesson is §3.4's own:
a guard that tests for a spelling finds that spelling.

The predicate separating them is exact, not approximate:

- **All fourteen** skills name a `scripts.` command.
- **Nine** read the recorded root (`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`).
- The **five** that do not are `edit-plan`, `footage-intake`, `reel-brief`,
  `reel-review`, `titles` — **exactly the five carrying all eleven bare-`python`
  sites**, with no member on either side unaccounted for.

The test's `RUNNERS` set names seven of the nine; `match-grade` and
`verify-runtime` read the root without being required to. The set is a list
that was typed, and it is already narrower than the tree.

The worst instance is `footage-intake`. Its whole instruction is
`python -m scripts.intake <footage_root> <out_dir>`, with no launcher preamble
at all — and `intake` is the one consumer that makes the `cd` into the clone
mandatory rather than a `PYTHONPATH` convenience, because **ultralytics writes
YOLO weights into the working directory**
([plugin-packaging](2026-07-22-plugin-packaging-design.md) §1.1). The router
hands that skill an out-dir at its step 3 and nothing else, so the skill's own
body is the only instruction the agent running intake ever sees.

This fails loud — a bare `python -m scripts.intake` from a footage folder
raises rather than corrupting anything. Loud is not harmless: an agent whose
documented command does not work improvises, and improvising is how the real
run built a 2.0 GB private colour lab beside a shipped tool it never reached.

### 0.5 The router's body has already drifted from the registry

`V1_STAGES` holds **fifteen live stages**. The router has **sixteen numbered
blocks**, and the numbering does not map onto the registry: block 0 is
`verify-runtime` and block 1 is "locate the run", neither a stage, leaving
**fourteen blocks for fifteen stages**.

The missing one is **`reel-review`, a required stage**. It has no block. It
lives at lines 539–551, buried inside block 15, below Checkpoint 3.

Block 15 is therefore three subjects under one heading — deliver, the third
checkpoint, and a required stage that lost its number — at **144 lines /
9 666 B, 22 % of the whole file**: nearly three times the next largest block
(`match-grade`, 3 351 B) and more than the eight smallest combined.

The previous slice found this same drift class on the *chain* (§0.6 there:
`music` vs `music-and-mood`) and closed it by generating the chain from
`V1_STAGES`. The chain can no longer drift. **The body's structure is still
typed, and it has drifted.**

### 0.6 The three user gates are each buried inside a stage block

The router exists to sequence, to checkpoint and to resume. Its three
checkpoints — the §4.1 user gates — have no home of their own: CP1 sits inside
block 2 (`project-init`), CP2 inside block 6 (`edit-plan`), CP3 **86 lines deep
inside block 15**. A gate reached only by reading far enough into an unrelated
stage is a gate that can be missed by reading a little less.

### 0.7 The installed plugin is seven minor versions behind

`~/.claude/plugins/cache/video-grid/video-grid/` holds exactly one version:
**0.2.1**. The repo is **0.9.2**. The install path is version-keyed, so nothing
is corrupt — the user simply has not reinstalled. It is recorded here because
it bounds every claim this design makes: what ships reaches a run only after a
reinstall, and nothing in the repo notices the gap.

---

## 1. Thesis

**A skill's instructions must be reachable from where the skill runs.**

Three failures above are one failure. A body of 43 KB is unreachable *later* —
it is spent by the compaction that follows it. A bare `references/x.md` is
unreachable *at all* — nothing says what it is relative to. A bare
`python -m scripts.x` is unreachable *from here* — it names a working directory
the agent does not have.

So the contract has two halves. **One anchor**: everything a skill names hangs
off the recorded root, which is the only path in this system that is both
absolute and current. **One split**: the body keeps what cannot be re-derived
at the moment of use, and a page carries what is only needed when something
goes wrong.

The split is newly safe. A pointer that is not followed is content that never
arrives — this repo has measured that (`probe grade`: 0 calls in 831). What
changed is that every one of the 47 `--help` surfaces now states its purpose
and `references/tools.md` exists, so an unfollowed pointer has a floor for the
first time. This slice spends the previous one's dividend.

---

## 2. The contract

### 2.1 One root, and everything hangs off it

Every skill that names a command or a required read resolves the root once:

    ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"
    VG="$ROOT/bin/vg"

and names nothing else relative: `"$VG" scripts.X` for every command,
`"$ROOT/references/…"` for every reference. `$VG` keeps the spelling nine
skills and `test_the_runner_skills_route_through_bin_vg` already use; `$ROOT`
is the generalization the reads need, and the launcher is now derived from it
rather than resolved beside it. A missing root file means `setup.sh` was never
run — stop and say so, never guess a path (the rule nine skills already
carry).

This is not a new mechanism. It is the mechanism
[plugin-runtime-resolution](2026-07-22-plugin-runtime-resolution-design.md)
established for the launcher, after the base-dir approach was measured wrong:
the install copies skills into a runtime-less cache, so a base-dir-relative
path finds a broken venv. The same argument covers reads for a different
reason — the cache is a **snapshot**, and the recorded root is the live clone.

All eleven `python -m scripts.X` sites become `"$VG" scripts.X`, and the two
`python -c` sites become `"$VG" -c` once the launcher accepts it. The five
skills of §0.4 gain the preamble the other nine carry.

### 2.2 The stub keeps the command

Each block leaves in its `SKILL.md`:

- the exact command, with its run-directory paths;
- one sentence of purpose;
- the names of any stop it can hit.

Everything else — why the stop fires, how to clear it, what the flags interact
with, the troubleshooting — moves to the block's page.

The line is drawn by what `--help` can answer. `--help` now states every
surface's purpose and every argument's meaning; it cannot state that the file
goes at `<run>/reels/<reel>/episodes/GEOMETRY.json`, because the run-directory
layout is not the CLI's to know. **So the paths stay and the prose goes.** An
unfollowed pointer costs detail, never the ability to run the stage.

### 2.3 A stage is a page

Router pages live at `references/using-montage/<stage-key>.md`, named by
**`V1_STAGES` keys, never by block number**. Renaming the unit from a number to
a registry key is what fixes §0.5: `reel-review` gets a page because it is a
stage, not because someone remembered it.

The set is exactly the fifteen live stage keys — no exemptions. Three pages
will be thin (`footage-intake`, `reel-brief`, `project-init` are 231, 582 and
919 bytes of block today) because their content lives in their own stage skill.
**That thinness is the routing answer, not waste**: a page whose whole content
is "this stage is conducted by the `footage-intake` skill" is exactly what a
read of it should return.

The two non-stage blocks — `verify-runtime` (step 0) and "locate the run"
(step 1) — stay resident in the body. Together they are 3 KB, they run on every
invocation regardless of stage, and keeping them in means the page set is a
clean equality with the registry rather than a set with two carve-outs.

### 2.4 The checkpoints come home

CP1, CP2 and CP3 come out of the stage blocks and into the body as their own
section, in compressed form. They stay resident. A stage page that goes unread
costs detail; **a checkpoint that goes unread is a user gate silently skipped**,
which is the worst failure available here and the one thing the router exists
to prevent.

### 2.5 `edit-plan`'s two pages

- `references/edit-plan/episode-fields.md` — every authorable `EDLEpisode`
  field and the knob table (~170 lines of step 2).
- `references/edit-plan/grade-convergence.md` — the convergence loop (~190
  lines of step 2), which is a `match_grade`/`probe` procedure, not selection
  authoring.

The selection prose and the **variety gate stay in the body**. The gate is a
refusal the author must know about *before* authoring, not a thing to look up
after being refused.

---

## 3. The machine check

### 3.1 One generated block, and the hand-written half is bound to it

The stage list must not get a third copy. It has two homes already — the
registry and the generated chain sentence — and §0.5 is what a typed third
copy costs.

So the router's body carries **exactly one generated block**: a stage table
rendered by `scripts/lib/toolindex.py` from `V1_STAGES`, exactly as `chain()`
is, and pinned byte-for-byte, the discipline `references/tools.md` already runs
under. Its columns are the routing facts and nothing else — the stage, whether
it is required or optional, the artifact it writes, and its page.

Beneath it the numbered stubs stay hand-written, because a command with
run-directory paths is not derivable from the registry (§2.2). They are bound
to the table by a structural check, not a second rendering: **the stub headings
are exactly the table's stage keys, in the table's order.** The generated block
owns the set; the stubs own the commands; nothing owns both.

### 3.2 The page set equals the registry

Every live `V1_STAGES` key has a page under `references/using-montage/`, and
every file there is a live key. Set equality, both directions, no exemption
list. Together with §3.1 this closes the triangle: registry, stub, page — any
one of the three losing a stage fails a check. It is the check §0.5's defect
would have failed.

§3.1 and §3.2 bind the router only: its blocks are stages and a registry says
what those are. `edit-plan`'s steps are a procedure with no registry behind
them, so its two pages are held by §3.3 alone — they must exist and must be
named. There is nothing to generate there and inventing a registry for four
steps would be a third copy of a list only one document holds.

### 3.3 Every named reference resolves, and none is orphaned

For every `references/…` path any skill names, the file exists. For every file
under `references/`, at least one skill names it. The first catches a rename;
the second catches a page that stops being reachable — the §0.3 failure in its
other direction.

### 3.4 The launcher guard gets a real predicate

The guard stops testing for one literal and starts testing a set of
spellings — `.venv/bin/python`, `python -m scripts`, `python -c` — which is
what §0.4 measured once it was measured twice: **no skill spells a command
starting with a bare `python`**, and **any skill naming a `scripts.` command reads the recorded
root**. `RUNNERS` stops being a typed list and becomes derived — the list was
already narrower than the tree.

### 3.5 The body budget

No `SKILL.md` exceeds **20 KB**.

**This is a budget, not a measurement**, and the comment in the test says so.
Three facts anchor it, none of them a threshold of anything: it is under half
of either body today (43 464 and 40 773 B); it is above `episode-qc`
(16 017 B), the largest body against which no backlog row has ever been filed;
and it is above what this slice will land, which is the part that matters.

Mechanically projecting §2.2's rule over both files gives **13.5 KB for the
router (−69 %)** and **10.5 KB for `edit-plan` (−74 %)**. Both are floors, not
targets, and the router's is the softer of the two: the checkpoints come back
out of block 15 into the body (§2.4), every stub keeps its stops, and the
projection's own command capture under-reads — one block's command block came
back as 55 bytes, which is not a command. The router will land somewhere near
16–17 KB.

Which is why the cap is 20 and not 16. **A cap that binds on the day it ships
is a cap the next author fights instead of obeys** — it would refuse the first
legitimate sentence added after this slice and teach exactly the wrong lesson
about where new material goes.

---

## 4. What does not change

- **No CLI, no contract, no pixel.** This slice edits Markdown, one renderer
  and the tests around them. No stage's behaviour moves.
- **The other twelve skills keep their bodies.** Eight are under 10 KB; cutting
  them would buy a pointer where reading the whole file is already cheaper.
  They do gain the §2.1 anchor where §0.4 says they need it.
- **`references/`'s four existing files stay where they are and keep their
  content.** They are shared across skills; the new pages are per-skill and sit
  in per-skill subdirectories beside them.
- **The `description:` surface is untouched.** It was settled twelve days ago
  and the pointer it carries is the thing this slice makes resolvable.

---

## 5. The honest half

- **Nothing proves a page was read.** The same limit the contact-sheet stage
  ships with: the check proves presence, never that anyone looked. If an agent
  runs a stage from the stub alone and never opens the page, every check here
  still passes.
- **The 20 KB cap is a convention.** §3.5 says so in the code comment as well
  as here. One of its three anchors is a body nobody complained about, which is
  evidence about the backlog, not about context; the other two are arithmetic
  on today's sizes.
- **Splitting multiplies `Read` calls, and that cost is not measured.** A run
  that touches ten stages will issue up to ten reads it does not issue today.
  Each is smaller than the body it replaces, but the total is unknown and no
  artifact on disk can answer it before a real run.
- **The −69 %/−74 % projection is mechanical.** It was computed by a script
  over block boundaries, not by writing the bodies, and its command capture is
  known to under-read. The real numbers will be worse and the cap is set to
  absorb that (§3.5). An earlier draft of this design claimed −80 % against a
  16 KB cap; both figures came from a measurement that counted characters as
  bytes and ran the last block to end-of-file, swallowing two sections that
  were never part of it.
- **The installed plugin is 0.2.1 (§0.7).** Nothing this slice ships reaches a
  montage run until the user reinstalls, and nothing in the repo detects the
  gap. That is true of every skill change ever made here; this is the first
  design to write it down.
- **`references/editing-canon.md` being unread is unproven, not proven.** §0.3
  measures silence in the retro, and silence is not a reading. The resolution
  rule is built because the path provably cannot be resolved, not because the
  file provably was not read.

---

## 6. Deferred

Rows for `docs/backlog.md`:

1. **Nothing detects that the installed plugin is behind the repo.** 0.2.1
   against 0.9.2 (§0.7). `verify_runtime` already checks a runtime contract and
   is the natural home for comparing the recorded root's version against the
   plugin cache's. (P2, S)
2. **The twelve remaining skill bodies have no page structure.** Eight are
   under 10 KB and do not need one; `episode-qc` (16 KB), `match-grade` (13.5)
   and `titles` (13) are the three that would reach the 20 KB cap first, and
   the addition that takes one of them there is what should force the question.
   (P3, M)
3. **The variety gate, the knob table and the field reference are three
   documents in one skill.** §2.5 splits `edit-plan` along the subject
   boundary that measurement made obvious; whether the remaining body is one
   coherent procedure or two has not been measured. (P3, S)
4. **A page's content is not checked against the code it describes.** The stage
   index is generated and pinned (§3.1), but a page's prose can still describe
   a flag that no longer exists. `tests/test_cli_help.py` knows every flag;
   nothing joins the two. (P3, M)
