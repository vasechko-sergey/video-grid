# Re-derivable purpose — design

**Date:** 2026-09-12
**Rows:** backlog R4.1 (P1), R4.2 (P1), R4.3 (P2)
**Source:** [retro 2026-08-25](../retro/2026-08-25-first-real-run.md) §R4

---

## 0. The measurement half

Two of the three rows arrived with a stated remedy. Measuring the artifacts
overturned one of them outright and re-scoped another, and the sharpest defect
in the tree was not named by any row.

### 0.1 R4.2's remedy was already shipped — twice, before the run

R4.2 reads: *"Skills must name the tool at the moment of need."* Its two
examples are `scripts.probe` (**0** invocations in 831 tool calls) and
`CONSTRAINTS` (**0** mentions).

Both were named in the skills **before the run began** (2026-08-19):

| named | first commit | date | lead time |
|---|---|---|---|
| `CONSTRAINTS.json` | `be86b75` | 2026-08-07 | 12 days |
| `scripts.probe` | `a820c55` | 2026-08-16 | 3 days |

Naming was not the binding constraint. It had been done, deliberately, by two
earlier slices, and neither tool was reached.

### 0.2 `probe`'s real cause is written in the retro's own text

The retro states the mechanism three sections above the row that files it
([retro line 156](../retro/2026-08-25-first-real-run.md)):

> its CLI requires `--episodes EPISODES.json`, which only exists **after
> `edl_to_reel --stop-after-episodes` has encoded every episode**

The operator's stated order was to tune colour on stills **before** any render.
`probe` required the render to have already happened. That is a precondition,
not a discoverability failure — and it was removed on 2026-08-30 by the
geometry seam (0.6.0): `probe grade --geometry GEOMETRY.json` runs before a
single episode is encoded.

So R4.2's first example had a structural blocker that is closed, and its second
was named twelve days early and still unused. The retro's own verdict on the
second is not "the agent did not know" but:

> The agent did not merely skip these tools. It **outcompeted** them

A richer pointer does not beat the impulse to build your own instrument. This
slice does not claim it does.

### 0.3 The three rungs of surface have different lifetimes

What an agent can read about a tool lives at three rungs, and they are not
equal:

| rung | lifetime | state today |
|---|---|---|
| a skill's `description:` frontmatter | **always in context** — it is in the skill listing, so it survives a compaction | 14 of 14 already state purpose, inputs, outputs and when |
| a `SKILL.md` body | **perishable** — read once as content, summarized away by compaction | `using-montage` 646 lines / 43 KB, `edit-plan` 629 lines / 41 KB; 12 of 14 skills have no reference subfiles, so each body loads whole |
| `python -m scripts.X --help` | **re-derivable on demand** — one Bash call, any time, at any context age | measured below, and it is the empty one |

The retro measured where an agent goes when the middle rung evaporates:
**12 of 13 `--help` calls fall in the 2 h 17 min after one compaction.** That is
the recovery behaviour, and today the recovery route answers with almost
nothing.

The first rung states each *skill's* purpose well and states no *tool's* at
all — it is where §2.4 puts the index pointer, for the one property nothing
else has: it cannot be spent. The second is the 84 KB declined as scope. The
third is the defect §0.4 measures.

### 0.4 The third rung, measured

The tree has **46 help surfaces**: 31 top-level parsers and 15 subcommands.

**Top-level — 5 of 31 print no purpose at all:**
`check_episode`, `extract`, `reframe`, `storyboard`, `track`. Exactly the
per-episode workers.

`extract --help` is the specimen — it prints one usage line and nothing else:

```
usage: extract.py [-h] --start START --dur DUR src out

positional arguments:
  src
  out

options:
  -h, --help     show this help message and exit
  --start START
  --dur DUR
```

Four of those five — `check_episode`, `extract`, `reframe`, `storyboard` — also
build their parser directly inside `if __name__ == "__main__":`, with no
`main()` function at all. Five scripts do that; the two sets overlap in four.
(`track` has a `main()` and no description; `process_episode` has a description
and no `main()`.) The tools nobody gave a function to are, four times in five,
the tools nobody gave a sentence to.

`extract` is where the whole 0.3.1 segment range contract lives
(`scale=in_range=auto:out_range=tv` + `-color_range tv` + `-pix_fmt yuv420p`).
Its `--help` says nothing about range, nothing about what `src` must be, and
nothing about what `out` becomes.

**Subcommands — 0 of 15 print a description.** All fifteen pass
`add_parser(help=...)` and none passes `description=`. `help=` renders only in
the *parent's* subcommand listing; a subparser's own `--help` shows
`description`, which is `None`. So:

```
$ python -m scripts.probe grade --help
usage: probe.py grade [-h] [--episodes EPISODES | --geometry GEOMETRY] ...
options:
  -h, --help           show this help message and exit
```

`probe grade` — the exact command R4.2's whole story turns on, and the one the
geometry seam built to answer the operator's complaint — states nothing about
itself at the surface an agent reaches by drilling into it.

This is the defect no row named, and it is 15 of 15.

**Arguments — 56 of 210 carry no `help`, and the deficit is concentrated where
the surface is thinnest:**

| kind | without help | total | |
|---|---|---|---|
| positional | **20** | 27 | **74%** |
| flag | 36 | 183 | 20% |

A flag carries some of its own meaning in its name — `--target-dur` says
"a target duration" before anything explains it. A positional renders as a bare
word: `src`, `out`, `clip`, `path`, `route`, `master`, `delivered`,
`footage_root`. `reframe` alone has 11 arguments with no help, 3 of them positional.

**10 of the 26 top-level descriptions that exist substitute a repo-internal
pointer for the purpose:** `(stage 5.2b)`, `(§5.13 Slice B)`, `(montage §5.9)`,
`(design 2026-08-01)`. Those resolve only against a design document the reader
must first find and then read. They are pointers, not statements — but note
that none of the ten is *only* a pointer, so this is a quality observation, not
a machine-checkable defect (§3.7).

### 0.5 Seven tools are named by no stage, no skill of their own, and no skill body

`assemble`, `build_reel`, `check_reel`, `extract`, `mix`, `reframe`,
`storyboard`. Six are internal engine steps driven by `edl_to_reel` or
`process_episode`; `build_reel` and `check_reel` are drivers. Their being
unnamed in the conveyor's registries is defensible — but it means `--help` is
their **only** surface, which makes the §0.4 emptiness load-bearing for exactly
these seven.

`probe` is **not** in this list: it is named three times across skill bodies.
The homelessness hypothesis does not explain it either. §0.2 does.

### 0.6 The router's own chain does not match the registry it describes

`using-montage`'s `description:` names the conveyor in order, and
`montage.V1_STAGES` **is** that order — so the two can be compared. They do not
agree. Three of the description's fifteen names are not stage keys at all:

| in the description | the registry's key |
|---|---|
| `music` | `music-and-mood` |
| `edl_to_reel episodes` | `episodes` |
| `edl_to_reel deliver` | `deliver` |

The order is right and `trend-scan` is correctly omitted as deferred, so this
is drift in vocabulary, not in sequence — today. Nothing checks it, and the
same description also declares each stage's optionality by hand, with brackets
that no test compares against `Stage.kind`.

Rendering the chain from the registry produces a **228-character** string,
shorter than the hand-written one it replaces and correct by construction:

    project-init -> footage-intake -> contact-sheet -> [reel-brief] ->
    edit-plan -> [music-and-mood] -> [pacing] -> episodes-geometry ->
    match-grade -> [assemble-draft] -> [titles] -> episodes -> episode-qc ->
    deliver -> reel-review

### 0.7 Nine of fourteen skills are stages; five are not, and seven stages have no skill

| | |
|---|---|
| skill **is** a stage key (9) | `project-init`, `footage-intake`, `reel-brief`, `edit-plan`, `pacing`, `match-grade`, `titles`, `episode-qc`, `reel-review` |
| skill is **not** a stage (5) | `using-montage` (the router itself), `verify-runtime` (step 0, before every stage), `music-match` / `music-source` (both serve the one `music-and-mood` stage), `process-episode` (a per-episode worker under `episodes`) |
| stage has **no** same-named skill (7) | `contact-sheet`, `trend-scan`, `music-and-mood`, `episodes-geometry`, `assemble-draft`, `episodes`, `deliver` — CLI stages the router drives directly |

The mapping is not 1:1 in either direction, which is why §2.5 states a
*position* rather than assuming every skill has a predecessor and a successor.

### 0.8 What cannot be measured, ever

The run's transcripts are deleted — the retro was written against them and says
so. Reach cannot be re-measured. Every number in this design comes from
artifacts on disk; nothing here can establish that a better `--help` changes
what an agent does. §5 carries this.

---

## 1. Thesis

**A tool's purpose, and its place in the order, must live where they can be
re-derived — not only where they were once read.**

A skill body is context, and context is spent. Two surfaces are not: the tool's
own `--help`, recoverable on demand at any context age for the price of one
Bash call, and a skill's `description:` frontmatter, which is in the listing
and therefore never leaves. The retro measured an agent reaching for the first
after a compaction and finding it empty. The second is not empty, but it points
at nothing — so a tool an agent has not already thought of is unreachable from
either.

So the thesis has three questions and two durable surfaces to answer them on:

| question | answered by | resident? |
|---|---|---|
| *how do I run this* | `--help` (§2.1–2.3) | no — one Bash call, any context age |
| *which tool do I want* | `references/tools.md` (§2.4) | no — the pointer is, the index is not |
| *which skill comes next* | the position sentence and the front door's chain (§2.5) | yes, and it is 56 characters |

Fixing only the first leaves an agent who never types the name exactly where it
started, which is what §0.2 shows actually happened. Fixing the first two leaves
an agent who knows every tool and has to reconstruct the order — which is the
same failure one level up.

---

## 2. The contract

Every help surface in `scripts/` states what the tool is for.

**2.1 Every parser and every subparser carries a `description`.** For a
subparser this means `description=` in addition to `help=`, because the two
render on different screens: `help=` in the parent's listing, `description=` on
the subcommand's own `--help`. Passing only `help=` — today's state, 15 of 15 —
leaves the drilled-into surface blank.

**2.2 Every argument carries a `help`.** Positionals included, and first: they
are 74% of the deficit and carry the least meaning in their own name.

**2.3 A description states what the tool reads, what it writes, and when to run
it.** The arguments carry the input *formats* (2.2), so the description carries
the *purpose* and the *moment*. This is a prose standard enforced by review,
not by machine — §3.7 explains why inventing a predicate for it would be worse
than admitting it.

**2.4 One index names every tool; the durable rung points at it, and sheds what
the index now carries.** `--help` answers *how do I run this*; it cannot answer
*which tool do I want*, because reading it requires already having typed the
name. That second question needs an index, and the index needs to be reachable
from a surface that survives a compaction.

- **`references/tools.md` is an index, not a manual.** One row per help
  surface: the module, the subcommand if it has one, whether it is a
  `V1_STAGES` stage and which, the artifact that stage writes, and the one-line
  purpose. 46 rows. It lists no arguments — that is what `--help` is for, and
  duplicating it is how an index starts lying.
- **`references/` is the established home.** Three reference files already live
  there and skills already send readers to them — `edit-plan` calls
  `references/editing-canon.md` a **required read**. The shape exists; what is
  new is where the pointer lives.
- **One identical pointer sentence in every skill's `description:`
  frontmatter** — §0.3's one rung always in context. Identical across all 14 so
  it is one memorized phrase, not 14 variants, and present on every skill so an
  agent entering through `episode-qc` alone meets the same pointer as one
  entering through `using-montage`.
- **And the descriptions shed the documentation that has crept into them.**
  This is the half that makes the pointer free. Measured: the 14 descriptions
  are 7244 characters, and only **1072 of those are first sentences** — the
  remaining 6172 are detail. `episode-qc`'s description is **989 characters**
  and spends them on digest stamping, a concurrency cap of three, and five
  named axes; none of that helps an agent decide whether to invoke the skill,
  and all of it belongs in the body or the index. A description's job is to
  trigger: what this is, when to reach for it, required or optional. Everything
  past that is documentation filed in the one place that is never unloaded.

**2.5 Every skill states its conveyor position; the front door states the whole
path.** An index answers *which tool*. It does not answer *which skill comes
next*, and an agent that knows the tools and not the order still has to
reconstruct the sequence — which is what §0.2's private colour lab was, one
level up.

- **Each of the 9 stage skills carries one generated sentence** naming its
  predecessor and successor in the declared order: `Conveyor position: after
  <prev>, before <next>.` Measured at 43–66 characters, mean 56.
- **The 5 non-stage skills state what they actually are** (§0.7) — the router,
  the step-0 preflight, the two that serve `music-and-mood`, the per-episode
  worker under `episodes`. Saying "this skill has no conveyor position, it
  serves X" is the honest form; inventing a predecessor for `verify-runtime`
  would be worse than omitting one.
- **`using-montage` carries the full chain, rendered from `V1_STAGES`** —
  **228 characters**, with `[brackets]` taken from `Stage.kind` rather than
  typed, and `deferred` stages omitted. It is the one description that
  legitimately holds the whole sequence, and it is what makes the user's
  observation work: an agent that reads the front door once knows which skills
  exist and in what order, and each skill it later enters confirms its own
  place from the same source.
- **Neither is hand-written.** Both the per-skill sentence and the chain are
  generated from `montage.V1_STAGES`, and a test pins the exact string inside
  each description — the same shape as §3.3's index pin. §0.6 is why: the
  hand-written chain has **already drifted** from the registry it describes.

The per-skill sentence names the *declared* order, not a guarantee that the
neighbour runs — optional stages are skipped, and only the front door's chain
shows which. That division is deliberate: the neighbour is the cheap fact worth
carrying everywhere, the skippability is the expensive one worth carrying once.

**2.6 What §2.4 and §2.5 cost, and why the trade works.**

**The mechanism: a pointer is resident, the thing it points at is not.** This
is why the trade works and why it keeps working. A skill's `description:` is
paid in **every** session, read or not, needed or not — 6172 of today's 7244
characters are detail that is resident whether any tool is ever reached. A
pointer costs 32 characters in that block; the 46 rows it names cost nothing
until an agent actually asks *which tool*, and `--help` costs nothing until it
asks *how*.

The corollary is the part worth keeping: **the index can be as detailed as it
needs to be at zero resident cost, and a description cannot.** That is not a
preference about where documentation reads nicest — it is the reason detail
belongs in the index and nowhere near a frontmatter line. It is also the same
principle as §6's first deferred row, applied one level up: a skill body with
no reference subfiles is a 43 KB payload that loads whether or not the
invocation needs it.

**Measured effect on always-resident context.** Three real drafts
(`episode-qc` 989 → 383, `match-grade` 740 → 275, `using-montage` 659 → 392)
average **350 characters** with the pointer and the position clause both
included. Every one of the 14 is above that today. `using-montage` is the
exception that keeps its chain: 392 for the trigger plus the generated 228, so
**625**. Thirteen at 350 plus the router at 625 is **7244 → 5175 characters,
~1811 → ~1293 tokens, −29%** — about **517 tokens freed in every session**,
including sessions that never touch video-grid. The router alone is then 12% of
the block, which is the right shape: one description holds the map, thirteen
hold a pointer and a place.

The first draft of this design costed the pointer as a **+19% addition**; that
was arithmetic on the assumption that descriptions stay as they are, and the
assumption was the error.

This is what closes R4.2 by construction rather than by measurement alone. §0.1
proved that naming a tool inside a perishable body did not reach; naming the
*index* on the durable rung is a different instrument, and it is the one answer
to §0.2's "it outcompeted them" that does not require the agent to already
suspect the tool exists.

---

## 3. The machine check

**3.1 Every CLI exposes its parser.** Today 26 build the parser inline inside
`main()` and five build it inside `if __name__ == "__main__":` with no `main()`
at all (§0.4); either way the parser is constructed and consumed in the same
breath, so nothing outside can see the surface. Each script gains a
`build_parser() -> argparse.ArgumentParser`, and its entry point becomes
`build_parser().parse_args()`. This is mechanical and it is the whole
structural change in the slice: it turns 46 help surfaces from text that can
only be scraped into objects that can be walked. The five without a `main()`
gain one, so every script has the same two-function shape.

**3.2 The check walks the parsers, and a second check runs the real `--help`.**
Two instruments, because they answer different questions:

- `tests/test_cli_help.py` imports every `scripts/*.py`, calls `build_parser()`,
  and walks `parser._actions` plus every subparser's actions. It asserts a
  non-empty `description` on all 46 surfaces and a non-empty `help` on every
  argument. Exact — no line-wrap parsing, no guessing where argparse broke a
  line — and in-process, so it costs an import, not a spawn.
- A second test invokes `python -m scripts.<name> --help` and
  `python -m scripts.<name> <sub> --help` as subprocesses and asserts each
  exits 0 and prints its description. This measures **emission**, the landmine
  lint's own principle, and it is what catches a `build_parser()` that is
  correct but no longer wired into `main()`. Measured cost: the 31-module sweep
  is **7.29 s**, ~2% of the suite's 365 s, and every module exits 0 today.

**3.3 The index is generated, and a test pins the committed copy.**
`references/tools.md` is rendered from the same `build_parser()` objects the
check walks, plus `montage.V1_STAGES` for the stage and artifact columns — so
no fact in it is typed twice. `montage tools` prints it; the committed file is
that render, and a test asserts the two are byte-identical. A new flag, a
renamed subcommand or an edited description fails the suite until the file is
regenerated.

The precedent is `tests/test_plugin_manifests.py`, which pins `CHANGELOG.md`'s
top entry against `plugin.json`'s version — and its own comment records why a
stale committed fact is worse than none: the version-keyed install path let
`episode-qc` stay missing for **316 commits**. An index that has drifted is
the same hazard wearing the word "index", which is why it is generated and
pinned rather than written.

**3.4 Every skill's frontmatter is checked for the pointer.**
`tests/test_skills_contract.py` already machine-checks a skill file against a
dataclass; it gains one case asserting each of the 14 `description:` lines
carries the index pointer verbatim. A fifteenth skill added later fails the
suite until it carries it too — the same self-extending shape as §3.3's
generated index. The test pins **presence**, never length: the 350-character
figure in §2.4 is a target read off three drafts, not a measurement of what a
description needs, and it has no business in a gate (§3.5).

**3.5 The position sentence and the chain are pinned, not trusted.**
The same `tests/test_skills_contract.py` case that checks the pointer (§3.4)
checks that each of the 9 stage skills carries its generated position sentence
verbatim, that the 5 non-stage skills carry their declared role, and that
`using-montage` carries the chain rendered from `V1_STAGES` — brackets from
`Stage.kind`, `deferred` omitted. The skill file stays hand-written; one
substring in it is pinned to a code fact, exactly as
`test_the_changelog_top_entry_matches_the_plugin_version` pins one heading to
`plugin.json`.

§0.6 is the evidence that this check is not theoretical: the hand-written chain
has already drifted, in three of its fifteen names, with the optionality
brackets typed by hand and compared to nothing.

**3.6 The surfaces are discovered, not listed.** The test enumerates
`scripts/*.py` and each parser's own subparsers, so a new script or a new
subcommand is covered on the day it lands — the same shape as
`tests/test_skills_contract.py`, which derives its expectations from the
dataclass rather than from a copy of it.

**3.7 What it deliberately does not assert.** §2.3's "reads → writes → when"
has no honest predicate. The candidates were considered and rejected:

- *A minimum length.* An unmeasured constant policing prose — the class of knob
  this repo has spent four slices removing.
- *"Not only a repo-internal pointer."* Measured: none of the ten §0.4
  offenders is *only* a pointer, so the check passes all ten today and catches
  nothing. A check that cannot fire is worse than no check, because it reads as
  coverage.
- *"Names an artifact from `Stage.artifact`."* Half the tools are not stages,
  and `extract` reads a source clip and writes a segment — neither is a
  registry artifact.

So the contract has two machine-checked halves and one reviewed half, and this
design says which is which rather than dressing the third up as the first.

---

## 4. What does not change

- **No skill is rewritten.** The 84 KB perishable middle stays as it is; that
  was considered as a scope and declined. It is filed in §6.
- **A new command, after all — and the first draft of this design was wrong to
  refuse it.** That draft rejected a `montage tools` map on the ground that
  reaching the map recurses the same reachability problem one level up. That
  objection holds only while the pointer lives somewhere perishable. Put the
  pointer on the frontmatter — the one rung §0.3 measured as always in context
  — and the recursion stops at a surface that cannot be spent. The objection
  was right about the mechanism and wrong about the conclusion, because it
  assumed the pointer would live in a skill body like every other pointer in
  this tree does today.
- **No `Stage` field.** Adding `Stage.purpose` would cover 16 of 31 tools and
  introduce a second place for a description to live. The CLI's own description
  is the single source.
- **No behaviour changes.** Every edit is a `description=` or `help=` string,
  the mechanical `build_parser()` extraction (§3.1), the `montage tools`
  renderer, the generated `references/tools.md`, a rewrite of all 14 skill
  `description:` lines down to trigger plus pointer plus position (§2.4/§2.5),
  and the tests. No argv changes, no filter changes, no
  golden moves. `build_parser()` is a pure move: the same parser, constructed
  by the same statements, returned instead of consumed in place.

---

## 5. The honest half

- **Nothing here proves an agent will run `--help`.** It proves the route
  answers when taken. The retro's 12-of-13 measurement says the route *is*
  taken after a compaction; it does not say it is taken before one.
- **Reach can never be re-measured.** The transcripts are deleted (§0.8). No
  future run can be compared against this one on this axis, because the
  baseline is gone.
- **The retro's verdict is that the agent outcompeted the tools**, building a
  2.0 GB / 676-file private colour lab rather than using what shipped. A
  complete `--help` does not address that. It addresses the 56 greps of the
  product's own source, which is a different complaint by the same reader.
- **A complete `--help` does not make a tool findable by someone who never
  types its name.** That is the first rung, and the first rung is already in
  good shape — which is why this slice touches the third and says so.
- **§2.3 is unenforced.** A future description can satisfy both machine checks
  and still say nothing useful. The check pins presence, never quality — the
  same shape as the contact-sheet stage, which gates that a sheet exists and
  never that anyone looked.
- **The −27% depends on shrinking descriptions, and shrinking a description
  risks triggering.** A skill's `description:` is what a model reads to decide
  whether to invoke it. Cutting documentation out of it is right; cutting the
  trigger out with it is a regression nothing in this repo can detect — there
  is no eval that measures whether a skill fires on the prompts it should.
  The rule that keeps this safe is stated, not enforced: **what this is, when
  to reach for it, required or optional** stays; everything past that goes. A
  skill that fires less often is the failure mode to watch for, and it will
  show up as a stage being skipped, not as a red test.
- **A generated position sentence names the declared order, not what will
  actually run.** `match-grade`'s successor in `V1_STAGES` is the optional
  `assemble-draft`; on a run that skips it the real next stage is `episodes`.
  The sentence is accurate about the registry and can mislead about the run.
  Only the front door's chain shows optionality, and that asymmetry is chosen
  (§2.5), not overlooked.
- **The 350-character figure is three drafts, not a measurement.** It is a
  target for the plan to aim at, and a fourth description may honestly need
  450. §3.4's check pins the pointer's presence and deliberately pins no
  length.
- **Resolving `references/tools.md` costs a step after a compaction.** The path
  is relative to the runtime root, which `setup.sh` records at
  `~/.config/video-grid/root` — a resolution every skill body teaches and no
  frontmatter can afford to spell out. An agent that has lost the body pays one
  `cat` to get it back. `montage tools` prints the same index for an agent that
  already has `$VG` resolved. The alternative — making the index its own
  skill, reachable by name with no path at all — is filed in §6.
- **An index is a fifth place a description can live** — frontmatter, skill
  body, CLI description, index, `CLAUDE.md`. Generation and the pin test
  keep exactly one of those pairs — index against CLI — from drifting. The
  other three still drift independently, as they do today.
- **Nothing proves an agent reads the index either.** A frontmatter sentence
  is a directive, which is stronger than a fact buried in a body, and it is
  still only a directive. The same limit as §2.3's unenforced prose standard,
  and the same limit the contact-sheet stage carries: presence is gateable,
  attention is not.
- **This slice makes no reel better.** It changes no pixel, no cut, and no
  gate. It is a change to what the product can tell its own operator.

---

## 6. Deferred

Rows for `docs/backlog.md`:

1. **The two biggest skills load whole, 84 KB, and are lost to compaction.**
   `using-montage` (646 lines) and `edit-plan` (629) have no reference
   subfiles, so every invocation pays the full body and a compaction spends all
   of it. Progressive disclosure — a short SKILL.md plus `references/*.md`
   loaded on demand — is the shape, and it is its own slice. Declined as this
   slice's scope. (P2, M)
2. **`Stage.runner` names a tool and nothing checks the tool exists.**
   `trend-scan`'s runner is the literal string `"5.4 - not built"`, so any
   check needs a deferred exemption; worth building only if a rename ever
   breaks a runner pointer. (P3, S)
3. **The ten repo-internal pointers in CLI descriptions** (`stage 5.2b`,
   `§5.13 Slice B`) substitute a reference for a statement. §3.7 shows no
   honest machine predicate separates them from a description that merely
   *also* cites; a prose pass is a review item, not a gate. (P3, S)
4. **The index as its own skill, reachable by name instead of by path.**
   A `video-grid:tools` skill whose body is the index would need no runtime
   root, no `$VG` and no path — one Skill call at any context age. It costs a
   fifteenth row in the always-resident listing and gives the same content a
   second home. Worth building if the path resolution proves to be the barrier
   in practice; not built ahead of that evidence. (P3, S)
5. **The index answers "which tool", never "is this tool right here".**
   A row says `probe grade` exists and renders stills over a frozen route; it
   cannot say that this is the moment in *your* run to reach for it. That is
   the judgement the skill body carries, and it is the half that stays
   perishable. (P3, M)
6. **R4.2 closes by measurement AND construction** — both of its examples
   were addressed before this slice (§0.1/§0.2). What the row named as the
   cause was not the cause, and the retro's own text carries the real one. The
   generalizable residue — a tool whose CLI cannot be run at the moment its
   user needs it — has no open instance today and is not filed as a row. What
   this slice builds for it is §2.4's index, which addresses the shape of
   the complaint rather than either of its two settled instances.
