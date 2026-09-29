# Unenforced rules — a convention nothing can check is not a convention

> Backlog P2, three rows filed under one impression: a rule that lives in prose
> and nothing holds it.
> - `check_reel.run(chroma=…)` — two inlets, both documented, neither gated.
> - the two remaining two-producer dict merges (`edit_plan.py`, `orchestration.py`).
> - the plan-checkbox convention `CLAUDE.md` and `development-workflow.md` mandate.

**Status:** design. Version 0.14.1 (PATCH — one extracted validator, four documents
corrected, no contract change).

---

## §0 What is on this machine

Measured 2026-09-29, before any code was written. **All three rows overturn their
own premise**, and a fourth row that was to join them grew out of the slice.

### §0.1 The checkbox rule was never reliably honoured, and one commit made it look as if it had been

The row states it flatly: *"no shipped plan in `docs/plans/` has a single `[x]`
— checked against a fully released plan, not merely an in-progress one. So the
rule is not lagging, it has never once been applied."*

That is false. But so was this design's first reading of it, which counted `[x]` at
HEAD and bucketed the plans by the date in their filename. That is the **end state**,
not whether the rule was followed when each slice landed, and the boundary it drew is
one retroactive commit: `878a713` (2026-08-06), "tick the 955 step checkboxes on 27
landed plans", whose own message records that "23 landed plans were fully ticked, 27
carried 955 boxes still `- [ ]`". Re-derived from git (every commit that touches a
plan, `878a713` set aside, checkbox lines inside fenced blocks not counted), the
series is:

| era (by filename date) | plans | fully ticked at HEAD (end state) | fully ticked by its own slice's commits |
|---|---|---|---|
| before 2026-08-06 | 51 | 51 (100 %) | **24 (47 %)** |
| 2026-08-06 onward | 40 | 10 (25 %) | **10 (25 %)** |

`878a713` is what produces the 51: the 27 plans between 24 and 51 are exactly the 27
it swept. Five of them were one box short before it, missing the same last step each
time, the final review of the whole slice, which by construction happens after the
closing commit; 22 had not been ticked at all. Counting the five, 29 of 51 (57 %) had
been ticked by their own slices.

The rule asked for something narrower than that: *after finishing a task*, tick its
checkboxes. Task by task means at least three commits that tick boxes, none carrying
more than half of them. One plan of 91 met that: the core plan, in 13 per-task
commits (eleven titled `docs: tick Task N checkboxes`), none over 11 % of its boxes.
Every other plan that its own slice ticked at all was ticked in one commit (35 plans)
or in two, one of them small (4); 51 of the 91 were not ticked by their own slice at
all.

So the rule did not hold for fifty-one plans and then collapse. It was never reliably
honoured: the first plan not fully ticked by its own slice is the seventh of 91
(`2026-07-11-extract-spine`), ticked and unticked plans interleave from there, and the
rate at the close of a slice was about half before the sweep (47 %, or 57 % counting
the five one box short) and a quarter after it. Deleting the rule removes an
instruction this repo has been failing for its whole life, not one it recently lost.
That the rate fell across 2026-08-06 is measured here and not explained.

(The 91 are the plans that had landed. A re-run over `docs/plans/` today finds 92
files: this slice's own plan, `2026-09-29-unenforced-rules.md`, committed four
minutes after this design, has no landing to measure and is left out.)

### §0.2 The rule it lost to is not written down anywhere

`grep -i 'historical record\|plans are history\|frozen'` across `CLAUDE.md` and
`docs/development-workflow.md` returns nothing about plans. Yet this repo
consistently acts on it — three reviews in the last two slices declined to touch
a shipped plan's text, and the retry-record slice corrected a *design* in place
while leaving the plan that described the same behaviour alone. The convention
"a design is corrected in place; a plan is the record of what was planned" is
real, load-bearing and unwritten. One commit is the exception, and it is the one
§0.1 is about: `878a713` amended 27 shipped plans in bulk, under the written rule,
but only the state of their checkboxes — 955 lines, no other change.

So the collision is: a **written** rule that says amend the plan as you go, and
an **unwritten** rule that says a plan is not amended. The unwritten one won,
silently. One explanation for that was checked and refuted: that execution moved to
subagents, who are handed a plan as a frozen brief, around 2026-08-06. It had moved a
month earlier. `docs/plans/2026-07-08-engine-dataclass-hardening.md:5` and
`2026-07-09-project-init.md:5` already record "strict subagent-driven-development",
the workflow doc's first version (`917c114`, 2026-07-09) already lists a fresh
implementer subagent per task, and every plan header (92 of 92) names that skill from
the first plan on.

The written rule appears in **four** places (line numbers as of `8136999`), not the
two this section first counted: `docs/development-workflow.md:129`, `CLAUDE.md:207`,
`docs/build-status.md:4` ("tick the plan's checkboxes") and `README.md:76-77`
("keeps the design spec, the plan checkboxes, and `docs/build-status.md` in
sync"). The first count came from
`grep -n -i 'checkbox' CLAUDE.md docs/development-workflow.md`: two file names,
not a directory, run to confirm the two locations the backlog row already named.
That one cause produced both misses. `docs/build-status.md` sits under `docs/`, so
any directory sweep finds it, including the one the plan later prescribed
(`grep -rn -i 'checkbox' CLAUDE.md docs/ skills/ references/`), which did.
`README.md` is outside all four of that sweep's paths as well and would have
survived it too; only a search of every tracked file finds it.

The failure mode, plainly: the first count confirmed the locations the row named
instead of searching for the locations that exist, and a grep given the answer
cannot find a third instance. That is a check narrower than the claim it was taken
to support, which is this slice's own subject one layer up. The corrected count
says what it counted over: every tracked file, for `checkbox`, `tick` and
`check off`. (One method trap from that search: `git grep -E` here (Apple Git 2.54.0)
silently matches nothing for `\b` and `\<` — no error, exit 1 — while `-w`, `-P` and
`[[:<:]]` work, and plain `grep -E`, BSD or ugrep, is unaffected. The first widened
sweep's `tick` alternatives matched nothing for that reason, and an empty result
against text known to exist exposed it — use `-w`, with a control that must hit.)

### §0.3 The cost that deferred the chroma row is an artifact of one imagined remedy

The row: *"Closing it would mean constructing a throwaway `ReelEpisode` per
reprocessed episode purely to validate a two-key dict — filed rather than built
for that cost."*

That is the cost of one remedy, not of the fix. `ReelEpisode.__post_init__`
already holds three refusals for `chroma` (not a mapping; a not-checked entry
without a reason; a reading without numeric `delta_c`/`delta_h`). Extracting
them into a function that both `__post_init__` and the second filler call costs
one function and no object construction.

The unvalidated inlet is precise: `build_reel` builds `chroma = [e.chroma for e
in rm.episodes]` — every element validated, because it came off a `ReelEpisode`
— and then **replaces** one at `build_reel.py:255` with
`color_fidelity.shift_from_report(...)`, a fresh dict that passes through no
validator at all.

### §0.4 Neither dict-merge site can hold the defect the row fears

The row: *"Neither is a defect; both become one the day a key is read as a
discriminator after the merge."* For that day to arrive, the merge must produce
a mapping in which a key may be **absent**. Measured, neither can:

- `edit_plan.py:129` — `**{**defaults, **editorial}` is splatted directly into
  `EDLEpisode(...)`. No mapping survives the expression, so there is nothing
  afterwards to discriminate on, and an unknown key is already a loud
  `ValueError` via the site's own `except TypeError`.
- `orchestration.py:194` — `p = {**DEFAULT_PARAMS, **params}` where
  `DEFAULT_PARAMS` has exactly two keys, `max_speed` and `smooth_window_s`. Both
  are therefore always present, both are read by name and reassigned, and a
  presence test is vacuous.

The `orchestration` site becomes capable of holding the defect only if
`DEFAULT_PARAMS` gains a key that is *not* always supplied — a change someone
would have to make deliberately, and which is not what the row describes.

### §0.5 The row's own remedy is the defect class

The row asks for *"a comment at each site, not a slice."* A comment that says
"do not read a key as a discriminator after this merge" is a rule kept by
whoever next reads that function — which is the thing §0.1 just measured
decaying. Writing one here would be this slice contradicting its own subject in
its own diff.

### §0.6 A fourth row grew out of the slice

R2.4 ("a threshold widened by hand needs a reason attached") was to be the
fourth. Measuring it moved it:

`ReelManifest.check_spec` is `ReelCheckSpec(self.target_dur, self.variety_min)`.
Of the class's **11** fields, two arrive from the manifest. No CLI anywhere sets
a threshold — `edl_to_reel`, `check_reel` and `build_reel` expose none. The
per-episode `CheckSpec` is the same shape: `process_episode` builds it from
three manifest fields plus `attempt`, and `check_episode --help` offers the same
four.

**Twelve of the eighteen threshold fields across both classes are unreachable
from any authoring surface** — including `entropy_floor`, the blocking
grade-damage bar, and `grade_residual_max`, `loudness_target`, `layout_jump_max`.
Every one is a first cut on a single shoot.

So `provenance.spec_overrides` — a diff machine written to catch any loosened
gate — can only ever report one field, `variety_min`; and the mechanism the row
describes has one reachable knob. The real defect for a **general** tool is the
opposite of the row's: not "widened silently" but "cannot be set at all". That
is a contract slice of its own, and it is promoted to P1 rather than folded in
here.

---

## §1 The rule

**A convention that nothing can check is not a convention — it is a hope with a
good reputation.**

The measurement that makes this more than a slogan is §0.1: the same rule, by the
same author, in the same repo, was met task by task once in 91 plans and fully ticked
by its own slice in 34 of them (47 % before 2026-08-06, 25 % after), and one
retroactive commit is all that made the end state read 51 of 51. Nothing checked it.

Three remedies exist, and this repo already uses all three. The measurement picks
which one a given rule earns:

1. **Make the structure enforce it** — the rule becomes unstateable rather than
   unbroken. (The chroma validator.)
2. **Machine-check it** — the rule stays a rule and a test holds it. (The four
   path conventions, the skill-description pins, the registry partition.)
3. **Delete it** — when the thing it asks for is already carried elsewhere, or
   when it contradicts a rule that beat it. (The checkbox sentence.)

A fourth option — restate it as a comment and hope harder — is the one this slice
refuses, including for itself (§0.5).

---

## §2 The contract

### §2.1 Chroma: one validator, both inlets (remedy 1)

Extract `ReelEpisode.__post_init__`'s three `chroma` refusals into a module-level
`models.validate_chroma(c) -> None`, raising the same `ValueError`s with the same
messages. `__post_init__` calls it. `color_fidelity.shift_from_report` calls it on
its own return value, which covers **both** fillers — `edl_to_reel`'s phase 1 and
`build_reel`'s reprocess arm — because both go through that one function, and the
JSON route continues to go through `__post_init__`.

No message changes: `check_reel` and the mutation battery assert on their text.

This is remedy 1 and not remedy 2: after it, a filler that skips the validator has
to construct the dict some *other* way, which is a visible act rather than a
forgotten step.

### §2.2 The two merges: closed by measurement (no code)

Both sites are safe by construction (§0.4) and the proposed comment is the defect
class (§0.5). The row closes with its measurement recorded in the archive — what
it feared, why neither site can host it, and what would have to change first.

One thing does ship: the sweep that found these three sites lives only in a
design's prose. The archive note names the predicate — *a merge of two
independently produced mappings whose result survives as a mapping and is later
tested for a key's presence* — so a future reader can re-run it rather than
re-derive it.

### §2.3 The checkboxes: delete the sentence, write down the rule that won (remedy 3)

Remove the checkbox clause from `docs/development-workflow.md:129` and
`CLAUDE.md:207` — and, per the §0.2 correction, from `docs/build-status.md:4`
and `README.md:76-77`, which carried the same instruction. In its place, state
the convention that actually governs (once, in `development-workflow.md`, with
`CLAUDE.md` pointing there; the other two simply lose the clause):

> A **design** is corrected in place when the code moves under it. A **plan** is
> the record of what was planned, and is not amended in substance after its slice
> ships — what was *done* is carried by that slice's per-task commits.

This is not surrender. It removes a contradiction: two rules, one written and one
not, asking for opposite treatment of the same file. Deleting the written one and
writing the unwritten one leaves exactly one rule, and it describes what a
document *is* rather than a step anyone must remember to perform — so there is
nothing left to decay.

**Not machine-checked, deliberately.** A check would have to assert that no commit
touches a plan outside its authoring slice, which is brittle (a typo fix, a stale
pointer, a correction like this slice's own) and would fire on legitimate edits.
The rule earns remedy 3, not remedy 2, because after the deletion there is no
procedure left to enforce.

---

## §3 What does not change

- Every `chroma` refusal's message, and `check_reel._chroma_spread_check`'s
  reading of the three states.
- `edit_plan.window_to_episode` and `orchestration.adjust_reframe_params` — not
  one character. The measurement is the deliverable.
- Every shipped plan's existing checkboxes, ticked or not. Where a slice ticked its
  own plan they record what it did; the boxes `878a713` ticked record that sweep.
  Re-ticking the 29 that remain unticked would be a second sweep, and this slice
  does not run one.
- `provenance.spec_overrides` — R2.4 is promoted, not started.

---

## §4 Honest limits

- **The chroma validator closes the inlet, not the class.** A third filler that
  builds the dict literally still bypasses it; what changed is that it must do so
  visibly, not by forgetting a call.
- **§0.4's safety is a property of today's `DEFAULT_PARAMS`,** not a guarantee. A
  key added there that is not always supplied re-opens the question, and nothing
  will announce that.
- **Deleting the checkbox rule loses a real record.** The per-task commits carry
  *what was done*, but not against which planned step — a plan with 53 unticked
  boxes and six commits does not say which box each commit closed. The judgement
  is that the SDD ledger and the commit messages already carry enough, and that a
  rule ticked task by task once in 91 plans, and fully by its own slice in 34,
  carries less.
- **§0.1's first instrument measured the wrong thing.** It counted `[x]` at HEAD and
  bucketed plans by filename date, which is the end state, and it mistook one
  retroactive commit (`878a713`) for a behavioural cliff, then explained the cliff with
  a move to subagent-driven execution that §0.2 shows had happened a month earlier.
  The error was found by a reviewer going to git history, not to the working tree. The
  at-landing series that replaced it approximates "at landing" by "by the plan's own
  commits": it counts a plan one box short as not fully ticked, and it lets through two
  plans completed one and seventeen minutes after their own version-bump commit
  (`2026-09-15-named-regions`, `2026-09-02-fake-render-fixture`); for slices before the
  rule that every slice bumps, there is no such event to measure against.
- **None of the three makes a reel better.** They make the next slice's mistakes
  louder.

---

## §5 Deferred

To the backlog:

- **P1 — the twelve unreachable thresholds** (§0.6). Give `ReelCheckSpec` and
  `CheckSpec` an authoring surface, and make `spec_overrides` meaningful by
  requiring a reason at the point of authoring — the two halves are one slice,
  because a loosenable gate without a recorded reason is exactly the cry-wolf
  mechanism R2.4 was filed against. R2.4 folds into it.
- **P3 — the merge predicate has no machine check.** §2.2 records it in prose so
  it can be re-run by hand. Whether an AST check for it is worth its false
  positives is unmeasured; today there would be zero true positives to find.
